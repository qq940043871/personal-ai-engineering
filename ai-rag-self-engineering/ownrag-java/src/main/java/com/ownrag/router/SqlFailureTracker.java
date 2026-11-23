package com.ownrag.router;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.LinkedHashMap;
import java.util.Map;

import com.ownrag.core.Db;
import com.ownrag.core.TaskStore;

/**
 * SQL 通道失败的连续计数与待办收口（docs 11 §四.4）。
 *
 * 为什么"连续"而不是"每次"：单次失败可能只是模型这一次没写好（重试一次就成），
 * 每次都开待办会把队列刷成噪音，人就再不看了。同一句问连续失败到阈值，才说明
 * 是"这张表/这类问题结构上不可 SQL 化"，这时才值得占用人工。
 *
 * 为什么落库而不是放内存：计数要跨请求、跨重启。放 ConcurrentHashMap 里，
 * 重启一次阈值就归零，"连续"永远到不了——等于没做。
 *
 * 口径：
 *   - 失败：count+1；到 {@link #THRESHOLD} 且当前没有未关待办 → 开一条 todo 并回填 todo_id
 *   - 成功：关掉该题未关的待办、删掉计数行（下次再坏从头算）
 *   - 待办写失败不能影响问答：调用方必须 catch，绝不因为记不了账让用户看不到答案
 */
public final class SqlFailureTracker {

    /** 连续失败到几次才打扰人。2 = "重试也救不回来"，一次偶发不惊动。 */
    public static final int THRESHOLD = 2;

    /** reason 前缀：批量关闭待办时按它 LIKE，且页面上能一眼认出这类待办。 */
    public static final String REASON_PREFIX = "SQL 通道连续失败";

    private SqlFailureTracker() {
    }

    public static class Outcome {
        public int count;
        public long todoId;
        public boolean todoCreated;
    }

    public static Outcome recordFailure(Connection conn, String app, String question, String note)
            throws SQLException {
        Outcome out = new Outcome();
        String appKey = blank(app) ? "default" : app.trim();
        String q = question == null ? "" : question.trim();
        if (q.isEmpty()) {
            return out;
        }
        // 先写（upsert 自增），再读回计数：写事务里读自己刚写的行没有快照冲突
        try (PreparedStatement ps = conn.prepareStatement(
                "INSERT INTO sql_failures(app, question_norm, question, count, last_note, last_at) "
                        + "VALUES(?,?,?,1,?,datetime('now','localtime')) "
                        + "ON CONFLICT(app, question_norm) DO UPDATE SET count=count+1,"
                        + " last_note=excluded.last_note, last_at=datetime('now','localtime')")) {
            ps.setString(1, appKey);
            ps.setString(2, q);
            ps.setString(3, q);
            ps.setString(4, clip(note, 200));
            ps.executeUpdate();
        }
        conn.commit();

        long todoId = 0;
        try (PreparedStatement ps = conn.prepareStatement(
                "SELECT count, todo_id FROM sql_failures WHERE app=? AND question_norm=?")) {
            ps.setString(1, appKey);
            ps.setString(2, q);
            try (ResultSet rs = ps.executeQuery()) {
                if (rs.next()) {
                    out.count = rs.getInt("count");
                    todoId = rs.getLong("todo_id");
                    if (rs.wasNull()) {
                        todoId = 0;
                    }
                }
            }
        }
        out.todoId = todoId;
        if (out.count < THRESHOLD || todoId > 0) {
            return out;   // 没到阈值，或队列里已有这条待办：不重复开
        }
        Db.endRead(conn);   // 读后要写：收尾读快照
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("app", appKey);
        payload.put("question", q);
        payload.put("count", out.count);
        payload.put("note", clip(note, 300));
        payload.put("hint", "检查该 Excel 表结构（列名/类型/sql_expr）与问题是否可 SQL 化；"
                + "修好后可批量关闭以 " + REASON_PREFIX + " 开头的待办");
        long newId = TaskStore.addTodo(conn, null, null,
                REASON_PREFIX + " " + out.count + " 次：" + q, payload);
        if (newId > 0) {
            try (PreparedStatement ps = conn.prepareStatement(
                    "UPDATE sql_failures SET todo_id=? WHERE app=? AND question_norm=?")) {
                ps.setLong(1, newId);
                ps.setString(2, appKey);
                ps.setString(3, q);
                ps.executeUpdate();
            }
            conn.commit();
            out.todoId = newId;
            out.todoCreated = true;
        }
        return out;
    }

    /** 成功一次就把账清掉：待办关掉、计数删除（"连续"从此重新计数）。 */
    public static void recordSuccess(Connection conn, String app, String question) throws SQLException {
        String appKey = blank(app) ? "default" : app.trim();
        String q = question == null ? "" : question.trim();
        if (q.isEmpty()) {
            return;
        }
        long todoId = 0;
        boolean exists = false;
        try (PreparedStatement ps = conn.prepareStatement(
                "SELECT todo_id FROM sql_failures WHERE app=? AND question_norm=?")) {
            ps.setString(1, appKey);
            ps.setString(2, q);
            try (ResultSet rs = ps.executeQuery()) {
                if (rs.next()) {
                    exists = true;
                    todoId = rs.getLong("todo_id");
                }
            }
        }
        if (!exists) {
            return;   // 绝大多数请求走这条：没有历史失败，零写入
        }
        Db.endRead(conn);
        if (todoId > 0) {
            TaskStore.resolveTodo(conn, todoId);
        }
        try (PreparedStatement ps = conn.prepareStatement(
                "DELETE FROM sql_failures WHERE app=? AND question_norm=?")) {
            ps.setString(1, appKey);
            ps.setString(2, q);
            ps.executeUpdate();
        }
        conn.commit();
    }

    private static boolean blank(String s) {
        return s == null || s.trim().isEmpty();
    }

    private static String clip(String s, int max) {
        String v = s == null ? "" : s.replaceAll("\\s+", " ").trim();
        return v.length() <= max ? v : v.substring(0, max) + "…";
    }
}
