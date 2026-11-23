package com.ownrag.router;

import java.nio.file.Path;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import com.ownrag.core.Db;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * SQL 连续失败入待办（docs 11 §四.4）：
 * 一次失败只计数、到阈值才打扰人、同一题不重复开、成功一次自动关账。
 */
class SqlFailureTrackerTest {

    @TempDir
    Path tmp;

    @Test
    void 连续失败到阈值才开待办_成功一次自动关闭() throws Exception {
        Path db = tmp.resolve("fail.db");
        Db.initSchema(db);
        try (Connection conn = Db.connect(db)) {
            SqlFailureTracker.Outcome first =
                    SqlFailureTracker.recordFailure(conn, "app1", "华东报销合计多少", "无候选表");
            assertEquals(1, first.count);
            assertFalse(first.todoCreated, "单次失败不该打扰人");
            assertEquals(0, count(conn, "SELECT COUNT(*) FROM todos"));

            SqlFailureTracker.Outcome second =
                    SqlFailureTracker.recordFailure(conn, "app1", "华东报销合计多少", "无候选表");
            assertEquals(2, second.count);
            assertTrue(second.todoCreated);
            assertTrue(second.todoId > 0);
            assertEquals(1, count(conn, "SELECT COUNT(*) FROM todos WHERE status='open'"));
            String reason = text(conn, "SELECT reason FROM todos WHERE id=" + second.todoId);
            assertTrue(reason.contains(SqlFailureTracker.REASON_PREFIX), reason);
            assertTrue(reason.contains("华东报销合计多少"), reason);

            // 第三次：计数继续涨，但不该再开一条（队列里已有）
            SqlFailureTracker.Outcome third =
                    SqlFailureTracker.recordFailure(conn, "app1", "华东报销合计多少", "还是失败");
            assertEquals(3, third.count);
            assertFalse(third.todoCreated);
            assertEquals(second.todoId, third.todoId);
            assertEquals(1, count(conn, "SELECT COUNT(*) FROM todos"));

            // 成功一次：待办关闭 + 计数清零（下次再坏从头算）
            SqlFailureTracker.recordSuccess(conn, "app1", "华东报销合计多少");
            assertEquals(0, count(conn, "SELECT COUNT(*) FROM sql_failures"));
            assertEquals(0, count(conn, "SELECT COUNT(*) FROM todos WHERE status='open'"));
            assertEquals(1, count(conn, "SELECT COUNT(*) FROM todos"), "待办是关掉不是删掉（保留可追溯）");
        }
    }

    @Test
    void 不同题目互不影响_没有历史失败时成功是零写入() throws Exception {
        Path db = tmp.resolve("fail2.db");
        Db.initSchema(db);
        try (Connection conn = Db.connect(db)) {
            SqlFailureTracker.recordFailure(conn, "app1", "问题A", "x");
            SqlFailureTracker.Outcome b = SqlFailureTracker.recordFailure(conn, "app1", "问题B", "y");
            assertEquals(1, b.count, "不同问题的计数必须分开算");

            // 从未失败过的问题：成功一次不应留下任何行（绝大多数请求走这条路径）
            SqlFailureTracker.recordSuccess(conn, "app1", "问题C");
            assertEquals(0, count(conn, "SELECT COUNT(*) FROM sql_failures WHERE question_norm='问题C'"));
            assertEquals(2, count(conn, "SELECT COUNT(*) FROM sql_failures"));
        }
    }

    private static int count(Connection conn, String sql) throws Exception {
        try (PreparedStatement ps = conn.prepareStatement(sql); ResultSet rs = ps.executeQuery()) {
            return rs.next() ? rs.getInt(1) : 0;
        }
    }

    private static String text(Connection conn, String sql) throws Exception {
        try (PreparedStatement ps = conn.prepareStatement(sql); ResultSet rs = ps.executeQuery()) {
            return rs.next() ? String.valueOf(rs.getString(1)) : "";
        }
    }
}
