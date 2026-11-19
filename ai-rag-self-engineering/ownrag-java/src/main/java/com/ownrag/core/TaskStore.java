package com.ownrag.core;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.ownrag.util.Json;
import com.ownrag.util.Ids;

/**
 * 任务表 + 待办表 CRUD（Python 版 core/tasks.py 对应物）：
 * 状态外置（Harness 机制②）、失败入待办（机制④），没有静默出口。
 */
public class TaskStore {

    /** 任务状态口径：pending → running → done | failed；pending_review = 停在人工闸门，不算失败。 */
    public static final String STATUS_PENDING = "pending";
    public static final String STATUS_RUNNING = "running";
    public static final String STATUS_DONE = "done";
    public static final String STATUS_FAILED = "failed";
    public static final String STATUS_PENDING_REVIEW = "pending_review";

    public static String createTask(Connection conn, String docId, String pipeline, String traceId,
                                    String kb, Map<String, Object> state) throws SQLException {
        String taskId = Ids.short12();
        try (PreparedStatement ps = conn.prepareStatement(
                "INSERT INTO tasks(id, doc_id, pipeline, kb, status, trace_id, state_json) "
                        + "VALUES (?,?,?,?,?,?,?)")) {
            ps.setString(1, taskId);
            ps.setString(2, docId);
            ps.setString(3, pipeline);
            ps.setString(4, kb == null ? "default" : kb);
            ps.setString(5, "pending");
            ps.setString(6, traceId);
            ps.setString(7, Json.write(state == null ? new LinkedHashMap<>() : state));
            ps.executeUpdate();
        }
        conn.commit();
        return taskId;
    }

    /** 任务行 → Map（字段名与表列一致，直接喂 API 层）。 */
    public static Map<String, Object> getTask(Connection conn, String taskId) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement("SELECT * FROM tasks WHERE id=?")) {
            ps.setString(1, taskId);
            try (ResultSet rs = ps.executeQuery()) {
                return rs.next() ? rowToMap(rs) : null;
            }
        }
    }

    public static void updateTask(Connection conn, String taskId, Map<String, Object> fields) throws SQLException {
        if (fields == null || fields.isEmpty()) {
            return;
        }
        StringBuilder cols = new StringBuilder();
        Object[] values = new Object[fields.size() + 1];
        int i = 0;
        for (Map.Entry<String, Object> e : fields.entrySet()) {
            if (i > 0) {
                cols.append(", ");
            }
            cols.append(e.getKey()).append("=?");
            values[i++] = e.getValue();
        }
        values[i] = taskId;
        try (PreparedStatement ps = conn.prepareStatement(
                "UPDATE tasks SET " + cols + ", updated_at=datetime('now','localtime') WHERE id=?")) {
            for (int j = 0; j < values.length; j++) {
                ps.setObject(j + 1, values[j]);
            }
            ps.executeUpdate();
        }
        conn.commit();
    }

    /** 执行器检查点：每步开始前落盘，中断可从这里续跑（状态外置）。 */
    public static void checkpoint(Connection conn, String taskId, String stepName,
                                  Map<String, Object> state) throws SQLException {
        Map<String, Object> fields = new LinkedHashMap<>();
        fields.put("current_step", stepName);
        fields.put("status", "running");
        fields.put("state_json", Json.write(state));
        updateTask(conn, taskId, fields);
    }

    /** 待办表 = 人工队列。解析失败、校验不过，全部进这里。 */
    public static int addTodo(Connection conn, String taskId, String docId, String reason,
                              Map<String, Object> payload) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement(
                "INSERT INTO todos(task_id, doc_id, reason, payload_json) VALUES (?,?,?,?)")) {
            ps.setString(1, taskId);
            ps.setString(2, docId);
            ps.setString(3, truncate(reason, 300));
            ps.setString(4, Json.write(payload == null ? new LinkedHashMap<>() : payload));
            ps.executeUpdate();
        }
        conn.commit();
        try (Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT last_insert_rowid()")) {
            return rs.next() ? rs.getInt(1) : 0;
        }
    }

    public static List<Map<String, Object>> listTasks(Connection conn, int limit) throws SQLException {
        List<Map<String, Object>> out = new ArrayList<>();
        try (PreparedStatement ps = conn.prepareStatement(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?")) {
            ps.setInt(1, limit);
            try (ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    out.add(rowToMap(rs));
                }
            }
        }
        return out;
    }

    public static List<Map<String, Object>> listTodos(Connection conn, boolean onlyOpen) throws SQLException {
        List<Map<String, Object>> out = new ArrayList<>();
        String q = "SELECT * FROM todos" + (onlyOpen ? " WHERE status='open'" : "") + " ORDER BY created_at DESC";
        try (Statement st = conn.createStatement(); ResultSet rs = st.executeQuery(q)) {
            while (rs.next()) {
                out.add(rowToMap(rs));
            }
        }
        return out;
    }

    public static boolean resolveTodo(Connection conn, long todoId) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement(
                "UPDATE todos SET status='done', resolved_at=datetime('now','localtime') "
                        + "WHERE id=? AND status='open'")) {
            ps.setLong(1, todoId);
            boolean ok = ps.executeUpdate() > 0;
            conn.commit();
            return ok;
        }
    }

    /** 该任务是否已有未处理待办（待复核这种"等人"状态重试时用来去重，不刷重复条目）。 */
    public static boolean hasOpenTodo(Connection conn, String taskId) throws SQLException {
        if (taskId == null || taskId.isEmpty()) {
            return false;
        }
        try (PreparedStatement ps = conn.prepareStatement(
                "SELECT 1 FROM todos WHERE task_id=? AND status='open' LIMIT 1")) {
            ps.setString(1, taskId);
            try (ResultSet rs = ps.executeQuery()) {
                return rs.next();
            }
        }
    }

    /**
     * 关闭某个任务下所有未处理待办：人工已经就这条任务做了决策（复核通过/驳回）时调用，
     * 否则队列里会残留"任务早已 done、待办还 open"的假待办。
     */
    public static int closeOpenTodos(Connection conn, String taskId) throws SQLException {
        if (taskId == null || taskId.isEmpty()) {
            return 0;
        }
        try (PreparedStatement ps = conn.prepareStatement(
                "UPDATE todos SET status='done', resolved_at=datetime('now','localtime') "
                        + "WHERE task_id=? AND status='open'")) {
            ps.setString(1, taskId);
            int n = ps.executeUpdate();
            conn.commit();
            return n;
        }
    }

    public static Map<String, Object> rowToMap(ResultSet rs) throws SQLException {
        java.sql.ResultSetMetaData meta = rs.getMetaData();
        int n = meta.getColumnCount();
        Map<String, Object> row = new LinkedHashMap<>();
        for (int i = 1; i <= n; i++) {
            row.put(meta.getColumnLabel(i), rs.getObject(i));
        }
        return row;
    }

    private static String truncate(String s, int max) {
        if (s == null) {
            return "";
        }
        return s.length() <= max ? s : s.substring(0, max);
    }
}
