package com.ownrag.eval;

import java.nio.file.Path;
import java.sql.Connection;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import com.ownrag.core.Db;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 评测的路由维度（docs 11 §八）：期望通道要能落库、要能统计"路由不符"。
 * 这一层的价值是让"调权重"变成可回归的事——否则改 ROUTES 权重全靠感觉。
 */
class EvalRouteTest {

    @TempDir
    Path tmp;

    @Test
    void 期望通道落库并参与KPI统计() throws Exception {
        Path db = tmp.resolve("eval.db");
        Db.initSchema(db);
        try (Connection conn = Db.connect(db)) {
            EvalStore.add(conn, "kb1", "报销金额一共多少", "manual", null, null, false,
                    null, null, null, "sql");
            EvalStore.add(conn, "kb1", "差旅标准是什么", "manual", null,
                    Arrays.asList("标准"), false, null, null, null, "rag");
            EvalStore.add(conn, "kb1", "随便问一句", "manual", null, null, false,
                    null, null, null, null);

            Map<String, Object> kpi = EvalStore.kpi(conn);
            assertEquals(2L, num(kpi.get("route_cases")), "只有两道题设了期望通道");
            assertEquals(0L, num(kpi.get("route_mismatch")));

            long sqlId = idOf(conn, "kb1", "报销金额一共多少");
            Map<String, Object> row = EvalStore.get(conn, sqlId);
            assertNotNull(row);
            assertEquals("sql", row.get("expect_route"));
            assertEquals("sql", row.get("category"), "期望通道=sql 且未指定题型时，题型应落成 sql 桶");
            assertNull(row.get("route_actual"), "还没跑过就不该有实跑通道");

            // 跑出来的通道与期望不符 → route_actual 落库，mismatch 计数 +1
            Map<String, Object> detail = new LinkedHashMap<>();
            detail.put("reason", "模拟");
            EvalStore.recordResult(conn, sqlId, "fail", 0.0, detail, "rag");
            Map<String, Object> row2 = EvalStore.get(conn, sqlId);
            assertEquals("rag", row2.get("route_actual"));
            assertEquals(1L, num(EvalStore.kpi(conn).get("route_mismatch")));

            // 改期望：旧判定作废、实跑通道清空（拿旧结论配新期望是最容易骗自己的组合）
            EvalStore.setExpect(conn, sqlId, null, false, "multi");
            Map<String, Object> row3 = EvalStore.get(conn, sqlId);
            assertEquals("pending", row3.get("verdict"));
            assertEquals("multi", row3.get("expect_route"));
            assertNull(row3.get("route_actual"));
            assertEquals(0L, num(EvalStore.kpi(conn).get("route_mismatch")));
        }
    }

    @Test
    void 期望通道只接受合法取值_脏值按不判路由处理() throws Exception {
        Path db = tmp.resolve("eval2.db");
        Db.initSchema(db);
        try (Connection conn = Db.connect(db)) {
            EvalStore.add(conn, "kb1", "问题一", "manual", null, null, false,
                    null, null, null, "web");
            Map<String, Object> row = EvalStore.get(conn, idOf(conn, "kb1", "问题一"));
            assertNull(row.get("expect_route"), "web 本期不实现，写进来按不判路由存");
            assertEquals("concept", row.get("category"));
        }
    }

    private static long idOf(Connection conn, String kb, String question) throws Exception {
        List<Map<String, Object>> cases = EvalStore.list(conn, kb, "", "", 100);
        for (Map<String, Object> c : cases) {
            if (question.equals(c.get("question"))) {
                return ((Number) c.get("id")).longValue();
            }
        }
        throw new IllegalStateException("没找到题目：" + question);
    }

    private static long num(Object v) {
        return v instanceof Number ? ((Number) v).longValue() : -1L;
    }
}
