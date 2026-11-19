package com.ownrag.core;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.SQLException;

import com.ownrag.util.Json;
import com.ownrag.util.Ids;

/** 步骤 trace 落表（Python 版 core/trace.py 对应物）：trace_id 串全链路。 */
@org.springframework.stereotype.Component
public class TraceLog {

    public String newTraceId() {
        return Ids.short12();
    }

    public static void log(Connection conn, String traceId, String step, String status,
                           Double ms, String docId, java.util.Map<String, Object> counters,
                           String error) {
        try (PreparedStatement ps = conn.prepareStatement(
                "INSERT INTO traces(trace_id, doc_id, step, status, ms, counters_json, error) "
                        + "VALUES (?,?,?,?,?,?,?)")) {
            ps.setString(1, traceId);
            ps.setString(2, docId);
            ps.setString(3, step);
            ps.setString(4, status);
            ps.setObject(5, ms);
            ps.setString(6, counters == null || counters.isEmpty() ? null : Json.write(counters));
            ps.setString(7, error);
            ps.executeUpdate();
        } catch (SQLException e) {
            // trace 落表失败不影响主流程，但必须可见
            System.err.println("[trace] 落表失败: " + e.getMessage());
        }
    }

    /** 按 trace_id 取全部步骤行（状态页时间线用）。 */
    public static java.util.List<java.util.Map<String, Object>> byTrace(Connection conn, String traceId)
            throws SQLException {
        java.util.List<java.util.Map<String, Object>> out = new java.util.ArrayList<>();
        try (PreparedStatement ps = conn.prepareStatement(
                "SELECT * FROM traces WHERE trace_id=? ORDER BY id")) {
            ps.setString(1, traceId);
            try (java.sql.ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    out.add(com.ownrag.core.TaskStore.rowToMap(rs));
                }
            }
        }
        return out;
    }
}
