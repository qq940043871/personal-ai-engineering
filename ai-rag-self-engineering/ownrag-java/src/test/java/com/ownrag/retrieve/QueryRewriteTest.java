package com.ownrag.retrieve;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 问句改写回归：触发条件、改写手段、不触发时的原因都必须可判定。
 * 问答调试页把 triggered/method/reason 直接展示给用户，所以这三个字段就是契约。
 */
public class QueryRewriteTest {

    private final QueryRewriter rewriter = new QueryRewriter();
    private final com.ownrag.config.Settings settings = new RetrieveTest.SettingsBuilder().build();

    private static List<Map<String, Object>> history(String... questions) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (String q : questions) {
            Map<String, Object> turn = new LinkedHashMap<>();
            turn.put("q", q);
            turn.put("a", "（答案略）");
            out.add(turn);
        }
        return out;
    }

    @Test
    void 无指代无套话_不触发且用原问题() {
        QueryRewriter.Result r = rewriter.rewrite(settings, null, "报销口径是什么", null, null);
        assertFalse(r.triggered);
        assertEquals("none", r.method);
        assertEquals("报销口径是什么", r.rewritten);
        assertTrue(r.reason.contains("未命中"), r.reason);
    }

    @Test
    void 套话剥离_纯规则触发() {
        QueryRewriter.Result r = rewriter.rewrite(settings, null, "请问报销口径是什么", null, null);
        assertTrue(r.triggered);
        assertEquals("delexical", r.method);
        assertEquals("报销口径是什么", r.rewritten);
    }

    @Test
    void 指代加历史_无模型时按历史拼接兜底() {
        QueryRewriter.Result r = rewriter.rewrite(settings, null, "它的审批人是谁",
                history("差旅报销的口径"), null);
        assertTrue(r.triggered);
        assertEquals("fallback", r.method);
        assertTrue(r.rewritten.contains("差旅报销的口径"), r.rewritten);
        assertTrue(r.rewritten.contains("它的审批人是谁"), r.rewritten);
        assertEquals(1, r.historyTurns);
    }

    @Test
    void 指代但无历史_如实汇报不改写() {
        QueryRewriter.Result r = rewriter.rewrite(settings, null, "它的审批人是谁", null, null);
        assertFalse(r.triggered);
        assertEquals("它的审批人是谁", r.rewritten);
        assertTrue(r.reason.contains("无对话历史"), r.reason);
    }

    @Test
    void 请求级关闭改写_优先于一切规则() {
        QueryRewriter.Result r = rewriter.rewrite(settings, null, "请问它的审批人是谁",
                history("差旅报销的口径"), Boolean.FALSE);
        assertFalse(r.triggered);
        assertEquals("none", r.method);
        assertEquals("请问它的审批人是谁", r.rewritten);
        assertTrue(r.reason.contains("已关闭"), r.reason);
    }

    @Test
    void 去套话不动实体词() {
        assertEquals("看看餐补标准", QueryRewriter.delexicalize("帮我看看餐补标准"));
        assertEquals("报销口径", QueryRewriter.delexicalize(" 报销口径？？ "));
        // 全是套话时不能把问题删空
        assertEquals("谢谢", QueryRewriter.delexicalize("谢谢"));
    }

    @Test
    void 模型输出清洗_取首行去前缀与引号() {
        assertEquals("差旅报销的审批人是谁", QueryRewriter.sanitizeRewrite("改写：差旅报销的审批人是谁"));
        assertEquals("差旅报销的审批人是谁",
                QueryRewriter.sanitizeRewrite("“差旅报销的审批人是谁”\n（已补全指代）"));
        assertEquals(null, QueryRewriter.sanitizeRewrite("  "));
    }

    @Test
    void 历史取最后一条非空问句() {
        assertEquals("第二个问题", QueryRewriter.lastQuestion(history("第一个问题", "第二个问题")));
        List<Map<String, Object>> withBlank = history("第一个问题");
        withBlank.add(new LinkedHashMap<>());
        assertEquals("第一个问题", QueryRewriter.lastQuestion(withBlank));
        assertEquals(null, QueryRewriter.lastQuestion(null));
    }
}
