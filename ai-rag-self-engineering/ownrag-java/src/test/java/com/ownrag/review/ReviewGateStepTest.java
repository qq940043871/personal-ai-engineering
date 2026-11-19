package com.ownrag.review;

import java.nio.file.Path;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.util.LinkedHashMap;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import com.ownrag.core.Db;
import com.ownrag.core.StepContext;
import com.ownrag.core.StepResult;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * review_gate 三种出口的语义边界：
 *   人工已通过 → ok；
 *   待复核（verdict pass/warn）→ awaitReview（任务 pending_review，不算失败）；
 *   verdict=fail（解析产物本身不可用）/ 已驳回 / 无记录 → fail。
 * 这条边界很关键：混了就会出现"任务全红了其实只是等人"或"产物烂了却让人点通过"。
 */
class ReviewGateStepTest {

    @TempDir
    Path tmp;

    private Connection conn() throws Exception {
        Db.initSchema(tmp.resolve("ownrag.db"));
        return Db.connect(tmp.resolve("ownrag.db"));
    }

    private static void saveReview(Connection conn, String docId, String status, String verdict,
                                  String blockingJson) throws Exception {
        try (PreparedStatement ps = conn.prepareStatement(
                "INSERT INTO parse_reviews(doc_id, kb, status, verdict, blocking_json)"
                        + " VALUES (?,?,?,?,?)")) {
            ps.setString(1, docId);
            ps.setString(2, "policy_v1");
            ps.setString(3, status);
            ps.setString(4, verdict);
            ps.setString(5, blockingJson);
            ps.executeUpdate();
        }
        conn.commit();
    }

    private StepResult run(Connection conn, String docId) {
        return new ReviewGateStep().run(new StepContext(docId, "t1", "policy_v1", conn, null),
                new LinkedHashMap<>());
    }

    @Test
    void 已通过_放行() throws Exception {
        try (Connection conn = conn()) {
            saveReview(conn, "d1", ReviewStore.STATUS_APPROVED, "warn", "[]");
            StepResult r = run(conn, "d1");
            assertTrue(r.ok);
            assertFalse(r.awaitReview);
        }
    }

    @Test
    void 待复核_awaitReview而非失败() throws Exception {
        try (Connection conn = conn()) {
            saveReview(conn, "d2", ReviewStore.STATUS_PENDING, "pass", "[]");
            StepResult r = run(conn, "d2");
            assertFalse(r.ok);
            assertTrue(r.awaitReview, "等人不是失败：任务应挂 pending_review");
            assertTrue(r.error.contains("待人工复核"));
        }
    }

    @Test
    void 有阻断项_必须真失败不放行() throws Exception {
        try (Connection conn = conn()) {
            saveReview(conn, "d3", ReviewStore.STATUS_PENDING, "fail",
                    "[{\"code\":\"too_few_chars\",\"detail\":\"字符密度过低：20 字符 / 5 页\"}]");
            StepResult r = run(conn, "d3");
            assertFalse(r.ok);
            assertFalse(r.awaitReview, "产物本身不可用，点通过也救不回来");
            assertTrue(r.error.contains("too_few_chars"), "阻断项要带出来，别只说'未通过'");
        }
    }

    @Test
    void 已驳回_带原因失败() throws Exception {
        try (Connection conn = conn()) {
            saveReview(conn, "d4", ReviewStore.STATUS_REJECTED, "warn", "[]");
            StepResult r = run(conn, "d4");
            assertFalse(r.ok);
            assertFalse(r.awaitReview);
            assertTrue(r.error.contains("驳回"));
        }
    }

    @Test
    void 无复核记录_失败() throws Exception {
        try (Connection conn = conn()) {
            StepResult r = run(conn, "d5");
            assertFalse(r.ok);
            assertTrue(r.error.contains("复核记录缺失"));
        }
    }
}
