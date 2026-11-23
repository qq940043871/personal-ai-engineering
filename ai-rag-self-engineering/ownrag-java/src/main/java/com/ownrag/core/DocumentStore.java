package com.ownrag.core;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 文档实体表存取（doc_id 的单一事实源）。
 *
 * 写入时机：上传建档 → 索引完成回写统计 → 复核/任务状态回写状态 → 删除销户。
 * 老库没有这张表时由 backfill() 从 chunks/tasks/parse_reviews/doc_fingerprints 幂等回填，
 * 每次启动都跑，INSERT OR IGNORE 保证不覆盖已经更新过的实体。
 */
public final class DocumentStore {

    private DocumentStore() {
    }

    /** 上传建档：doc_id 每次上传都是新值，用 INSERT OR IGNORE 保证幂等。 */
    public static void upsertOnUpload(Connection conn, String docId, String kb, String sourceFile,
                                      String pipeline, String taskId, String traceId, String fileHash,
                                      long sizeBytes, Map<String, Object> meta) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement(
                "INSERT OR IGNORE INTO documents(doc_id, kb, source_file, pipeline, task_id, trace_id, "
                        + "file_hash, size_bytes, sensitivity, topic, doc_date, origin, access_level, "
                        + "task_status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
                        + "datetime('now','localtime'), datetime('now','localtime'))")) {
            ps.setString(1, docId);
            ps.setString(2, kb);
            ps.setString(3, sourceFile);
            ps.setString(4, pipeline);
            ps.setString(5, taskId);
            ps.setString(6, traceId);
            ps.setString(7, fileHash);
            ps.setLong(8, sizeBytes);
            ps.setString(9, str(meta == null ? null : meta.get("sensitivity")));
            ps.setString(10, str(meta == null ? null : meta.get("topic")));
            ps.setString(11, str(meta == null ? null : meta.get("doc_date")));
            ps.setString(12, str(meta == null ? null : meta.get("origin")));
            // 访问权限随上传确定；缺省 public（不改存量口径），仅显式 protected 才受限
            ps.setString(13, com.ownrag.auth.AccessLevel.normalize(
                    meta == null ? null : str(meta.get("access_level"))));
            ps.setString(14, TaskStore.STATUS_PENDING);
            ps.executeUpdate();
        }
        conn.commit();
    }

    /** 索引写完后回写块数 / 向量数 / 正文字数，管理页不再逐次聚合 chunks。 */
    public static void refreshStats(Connection conn, String docId) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement(
                "UPDATE documents SET "
                        + "chunk_count=(SELECT COUNT(*) FROM chunks WHERE doc_id=?), "
                        + "vector_count=(SELECT COUNT(*) FROM chunk_vectors WHERE doc_id=?), "
                        + "chars=(SELECT COALESCE(SUM(LENGTH(text)),0) FROM chunks WHERE doc_id=?), "
                        + "updated_at=datetime('now','localtime') WHERE doc_id=?")) {
            ps.setString(1, docId);
            ps.setString(2, docId);
            ps.setString(3, docId);
            ps.setString(4, docId);
            ps.executeUpdate();
        }
    }

    /** 复核状态与任务状态共用一处回写，避免管理页再去 JOIN parse_reviews / tasks。 */
    public static void setStatus(Connection conn, String docId, String column, String value)
            throws SQLException {
        if (!"review_status".equals(column) && !"task_status".equals(column)) {
            throw new IllegalArgumentException("不支持的状态列：" + column);
        }
        try (PreparedStatement ps = conn.prepareStatement(
                "UPDATE documents SET " + column + "=?, updated_at=datetime('now','localtime') "
                        + "WHERE doc_id=?")) {
            ps.setString(1, value);
            ps.setString(2, docId);
            ps.executeUpdate();
        }
    }

    public static void delete(Connection conn, String docId) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement("DELETE FROM documents WHERE doc_id=?")) {
            ps.setString(1, docId);
            ps.executeUpdate();
        }
    }

    /**
     * 旧库回填：只回填真正有索引块的文档（tasks 里大量重试/失败任务不是独立文档）。
     * 全部使用带索引的简单查询：大库上一条带相关子查询的 INSERT...SELECT 实测 67 秒，
     * 拆成 chunks 分组 + 逐 doc 点查后降到毫秒级；INSERT OR IGNORE 保证重复启动无副作用。
     */
    public static void backfill(Connection conn) throws SQLException {
        Map<String, Long> vectorCounts = new HashMap<>();
        try (PreparedStatement ps = conn.prepareStatement(
                "SELECT doc_id, COUNT(*) FROM chunk_vectors GROUP BY doc_id");
             ResultSet rs = ps.executeQuery()) {
            while (rs.next()) {
                vectorCounts.put(rs.getString(1), rs.getLong(2));
            }
        }

        List<Object[]> groups = new ArrayList<>();
        try (PreparedStatement ps = conn.prepareStatement(
                "SELECT doc_id, kb, COUNT(*), COALESCE(SUM(LENGTH(text)),0), "
                        + "MIN(created_at), MAX(created_at), "
                        + "MAX(sensitivity), MAX(topic), MAX(doc_date), MAX(origin) "
                        + "FROM chunks GROUP BY doc_id, kb");
             ResultSet rs = ps.executeQuery()) {
            while (rs.next()) {
                Object[] row = new Object[10];
                for (int i = 0; i < row.length; i++) {
                    row[i] = rs.getObject(i + 1);
                }
                groups.add(row);
            }
        }

        try (PreparedStatement fingerprint = conn.prepareStatement(
                "SELECT source_file, file_hash FROM doc_fingerprints WHERE doc_id=? LIMIT 1");
             PreparedStatement review = conn.prepareStatement(
                     "SELECT pipeline, status FROM parse_reviews WHERE doc_id=?");
             PreparedStatement task = conn.prepareStatement(
                     "SELECT id, trace_id, status, pipeline FROM tasks WHERE doc_id=? "
                             + "ORDER BY created_at DESC, id DESC LIMIT 1");
             PreparedStatement insert = conn.prepareStatement(
                     "INSERT OR IGNORE INTO documents(doc_id, kb, source_file, pipeline, task_id, trace_id, "
                             + "file_hash, sensitivity, topic, doc_date, origin, review_status, task_status, "
                             + "chunk_count, vector_count, chars, created_at, updated_at) "
                             + "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")) {
            for (Object[] g : groups) {
                String docId = String.valueOf(g[0]);
                String sourceFile = docId;
                String fileHash = null;
                fingerprint.setString(1, docId);
                try (ResultSet rs = fingerprint.executeQuery()) {
                    if (rs.next()) {
                        sourceFile = rs.getString(1) == null ? docId : rs.getString(1);
                        fileHash = rs.getString(2);
                    }
                }
                String pipeline = null, reviewStatus = null;
                review.setString(1, docId);
                try (ResultSet rs = review.executeQuery()) {
                    if (rs.next()) {
                        pipeline = rs.getString(1);
                        reviewStatus = rs.getString(2);
                    }
                }
                String taskId = null, traceId = null, taskStatus = null, taskPipeline = null;
                task.setString(1, docId);
                try (ResultSet rs = task.executeQuery()) {
                    if (rs.next()) {
                        taskId = rs.getString(1);
                        traceId = rs.getString(2);
                        taskStatus = rs.getString(3);
                        taskPipeline = rs.getString(4);
                    }
                }
                insert.setString(1, docId);
                insert.setString(2, String.valueOf(g[1]));
                insert.setString(3, sourceFile);
                insert.setString(4, pipeline == null ? taskPipeline : pipeline);
                insert.setString(5, taskId);
                insert.setString(6, traceId);
                insert.setString(7, fileHash);
                insert.setString(8, str(g[6]));
                insert.setString(9, str(g[7]));
                insert.setString(10, str(g[8]));
                insert.setString(11, str(g[9]));
                insert.setString(12, reviewStatus);
                insert.setString(13, taskStatus);
                insert.setLong(14, ((Number) g[2]).longValue());
                insert.setLong(15, vectorCounts.containsKey(docId) ? vectorCounts.get(docId) : 0L);
                insert.setLong(16, ((Number) g[3]).longValue());
                insert.setString(17, String.valueOf(g[4]));
                insert.setString(18, String.valueOf(g[5]));
                insert.executeUpdate();
            }
        }
    }

    /** -management 页按 doc_id 取实体，缺失返回 null。 */
    public static Map<String, Object> get(Connection conn, String docId) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement("SELECT * FROM documents WHERE doc_id=?")) {
            ps.setString(1, docId);
            try (ResultSet rs = ps.executeQuery()) {
                return rs.next() ? TaskStore.rowToMap(rs) : null;
            }
        }
    }

    private static String str(Object o) {
        if (o == null) {
            return null;
        }
        String s = String.valueOf(o).trim();
        return s.isEmpty() ? null : s;
    }
}
