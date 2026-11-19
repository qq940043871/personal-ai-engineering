package com.ownrag.core;

import java.nio.file.Path;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.junit.jupiter.api.Assertions.assertEquals;

/**
 * 老库口径归位：改造前"停在 review_gate 等人"被记成 failed，启动期一次性改回 pending_review；
 * 同时清掉"任务已 done、待办还 open"的假活。必须幂等——每次重启都会跑。
 */
class StartupCheckTest {

    @TempDir
    Path tmp;

    private Connection conn() throws Exception {
        Db.initSchema(tmp.resolve("ownrag.db"));
        return Db.connect(tmp.resolve("ownrag.db"));
    }

    /** 直接落一条任务（createTask 只能建 pending，这里要造历史状态）。 */
    private static void legacyTask(Connection conn, String id, String docId, String status,
                                   String currentStep, String error) throws Exception {
        String taskId = TaskStore.createTask(conn, docId, "pdf_v1", "t-" + id, "default", new LinkedHashMap<>());
        try (PreparedStatement ps = conn.prepareStatement(
                "UPDATE tasks SET status=?, current_step=?, error=? WHERE id=?")) {
            ps.setString(1, status);
            ps.setString(2, currentStep);
            ps.setString(3, error);
            ps.setString(4, taskId);
            ps.executeUpdate();
        }
        conn.commit();
        // 用 docId 反查 taskId 太绕：把映射塞进返回不便，这里靠 docId 关联
        try (PreparedStatement ps = conn.prepareStatement(
                "INSERT INTO todos(task_id, doc_id, reason) VALUES (?,?,?)")) {
            ps.setString(1, taskId);
            ps.setString(2, docId);
            ps.setString(3, "[" + id + "] " + error);
            ps.executeUpdate();
        }
        conn.commit();
    }

    @Test
    void 停在复核闸门的failed改回pending_review_假待办关闭() throws Exception {
        try (Connection conn = conn()) {
            legacyTask(conn, "a", "docGate", TaskStore.STATUS_FAILED, "review_gate",
                    "[pdf_v1/review_gate] 解析产物待人工复核（自动结论 verdict=pass，阻断项 0 条）");
            legacyTask(conn, "b", "docDone", TaskStore.STATUS_DONE, null, null);
            legacyTask(conn, "c", "docFail", TaskStore.STATUS_FAILED, "parse",
                    "[pdf_v1/parse] 解析崩溃");

            int[] fixed = StartupCheck.normalizeLegacyTaskStates(conn);
            assertEquals(1, fixed[0], "只有 review_gate 待复核那条改口径");
            assertEquals(1, fixed[1], "只关 done 任务下的待办");

            List<Map<String, Object>> todos = TaskStore.listTodos(conn, true);
            assertEquals(2, todos.size(), "待复核 + 真失败的待办都要留着等人处理");
            try (PreparedStatement ps = conn.prepareStatement(
                    "SELECT status FROM tasks WHERE doc_id=?")) {
                ps.setString(1, "docGate");
                try (java.sql.ResultSet rs = ps.executeQuery()) {
                    rs.next();
                    assertEquals(TaskStore.STATUS_PENDING_REVIEW, rs.getString(1));
                }
            }

            // 幂等：再跑一次什么都不改
            int[] again = StartupCheck.normalizeLegacyTaskStates(conn);
            assertEquals(0, again[0]);
            assertEquals(0, again[1]);
        }
    }
}
