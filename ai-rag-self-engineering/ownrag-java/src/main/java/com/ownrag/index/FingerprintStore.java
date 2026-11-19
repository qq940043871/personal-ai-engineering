package com.ownrag.index;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 指纹双表存取（个人知识库场景新增）：
 * doc_fingerprints = 文件级 SHA-256（重传幂等，同 hash 且索引在位 → 直接返回已有 doc）；
 * chunk_hashes = 块级内容指纹（跨文档去重；reject 不登记，删文档即释放）。
 */
public final class FingerprintStore {

    private FingerprintStore() {
    }

    // ---- 文件级 ----

    /** hash → doc_id（无则 null）。 */
    public static String findDocByFileHash(Connection conn, String fileHash) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement(
                "SELECT doc_id FROM doc_fingerprints WHERE file_hash=?")) {
            ps.setString(1, fileHash);
            try (ResultSet rs = ps.executeQuery()) {
                return rs.next() ? rs.getString("doc_id") : null;
            }
        }
    }

    public static void registerFileHash(Connection conn, String fileHash, String docId,
                                        String kb, String sourceFile) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement(
                "INSERT OR REPLACE INTO doc_fingerprints(file_hash, doc_id, kb, source_file) VALUES (?,?,?,?)")) {
            ps.setString(1, fileHash);
            ps.setString(2, docId);
            ps.setString(3, kb);
            ps.setString(4, sourceFile);
            ps.executeUpdate();
        }
    }

    /** 已索引块数>0 = 指纹对应的索引仍在位。 */
    public static boolean hasIndexedChunks(Connection conn, String docId) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement(
                "SELECT COUNT(*) FROM chunks WHERE doc_id=?")) {
            ps.setString(1, docId);
            try (ResultSet rs = ps.executeQuery()) {
                return rs.next() && rs.getLong(1) > 0;
            }
        }
    }

    // ---- 块级 ----

    /** 块 hash 是否已入库（在库=内容重复，跳过）。 */
    public static boolean chunkHashExists(Connection conn, String hash) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement(
                "SELECT 1 FROM chunk_hashes WHERE hash=?")) {
            ps.setString(1, hash);
            try (ResultSet rs = ps.executeQuery()) {
                return rs.next();
            }
        }
    }

    public static void registerChunkHash(Connection conn, String hash, String chunkId,
                                         String docId) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement(
                "INSERT OR IGNORE INTO chunk_hashes(hash, chunk_id, doc_id) VALUES (?,?,?)")) {
            ps.setString(1, hash);
            ps.setString(2, chunkId);
            ps.setString(3, docId);
            ps.executeUpdate();
        }
    }

    public static void deleteByDoc(Connection conn, String docId) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement("DELETE FROM chunk_hashes WHERE doc_id=?");
             PreparedStatement ps2 = conn.prepareStatement("DELETE FROM doc_fingerprints WHERE doc_id=?")) {
            ps.setString(1, docId);
            ps.executeUpdate();
            ps2.setString(1, docId);
            ps2.executeUpdate();
        }
    }

    /** 统计（admin/metrics 用）。 */
    public static Map<String, Object> stats(Connection conn) throws SQLException {
        Map<String, Object> out = new LinkedHashMap<>();
        try (PreparedStatement ps = conn.prepareStatement("SELECT COUNT(*) FROM doc_fingerprints");
             ResultSet rs = ps.executeQuery()) {
            out.put("docs", rs.next() ? rs.getLong(1) : 0);
        }
        try (PreparedStatement ps = conn.prepareStatement("SELECT COUNT(*) FROM chunk_hashes");
             ResultSet rs = ps.executeQuery()) {
            out.put("unique_chunks", rs.next() ? rs.getLong(1) : 0);
        }
        return out;
    }
}
