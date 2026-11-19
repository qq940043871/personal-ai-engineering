package com.ownrag.generate;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** 上下文预算回归（对齐 Python 版 budget.py 语义）。 */
class BudgetTest {

    private static Map<String, Object> candidate(int ordinal, String text) {
        Map<String, Object> c = new LinkedHashMap<>();
        c.put("ordinal", ordinal);
        c.put("chunk_id", String.format("d#%04d", ordinal));
        c.put("doc_id", "d");
        c.put("text", text);
        return c;
    }

    @Test
    void 预算公式_含安全余量() {
        // 6144 - 100 - 512 - 64
        assertEquals(5468, Budget.contextBudget(6144, 100, 512));
        // 再紧也不低于 128
        assertEquals(128, Budget.contextBudget(200, 100, 512));
    }

    @Test
    void blockPrompt形态() {
        assertEquals("[块3]（来源 doc=d）\n正文", Budget.blockPrompt(candidate(3, "正文")));
        // doc_id 不同的候选：chunk_id 前缀
        Map<String, Object> c = candidate(1, "x");
        c.put("doc_id", "abc");
        assertEquals("[块1]（来源 doc=abc）\nx", Budget.blockPrompt(c));
    }

    @Test
    void fit_按序装块_超预算砍尾() {
        List<Map<String, Object>> candidates = new ArrayList<>();
        for (int i = 1; i <= 5; i++) {
            candidates.add(candidate(i, "块" + i + rep("甲", 50)));  // 甲 为真汉字，参与 CJK 计数
        }
        Budget.BudgetResult r = Budget.fitCandidates(candidates, 150);
        assertFalse(r.blocks.isEmpty());
        assertTrue(r.blocks.size() < 5, "预算应截掉部分尾块");
        assertFalse(r.dropped.isEmpty());
        assertFalse(r.truncated);
        assertTrue(r.tokens <= 150);
    }

    @Test
    void fit_首块超预算按字符比例截断() {
        StringBuilder big = new StringBuilder("首");
        for (int i = 0; i < 3000; i++) {
            big.append('甲');
        }
        List<Map<String, Object>> candidates = new ArrayList<>();
        candidates.add(candidate(1, big.toString()));
        candidates.add(candidate(2, "尾块"));
        Budget.BudgetResult r = Budget.fitCandidates(candidates, 200);
        assertEquals(1, r.blocks.size());
        assertTrue(r.truncated);
        assertEquals(Arrays.asList("d#0002", "d#0001"), r.dropped);  // Python 口径：尾块在前、被截块在后
        assertTrue(r.tokens <= 200 + 1, "截断后 tokens 应收敛到预算内（±1 由块头成本）");
    }

    @Test
    void fit_空候选() {
        Budget.BudgetResult r = Budget.fitCandidates(new ArrayList<>(), 500);
        assertEquals(0, r.blocks.size());
        assertEquals("", r.text);
        assertEquals(0, r.tokens);
    }

    @Test
    void render_资料正文含LaTeX花括号不得误判占位符() {
        // 回归：\frac{1}{2} 的 {1}{2} 曾被"渲染产物未填占位符"校验误杀，问答直接 500
        com.ownrag.config.Settings base = new com.ownrag.retrieve.RetrieveTest.SettingsBuilder().build();
        java.util.Map<String, com.ownrag.config.PromptDef> prompts = new LinkedHashMap<>();
        com.ownrag.config.PromptDef strict = new com.ownrag.config.PromptDef();
        strict.name = "policy_strict_v1";
        strict.system = "系统规则";
        strict.template = "【资料】\n{context_blocks}\n\n【问题】\n{question}";
        prompts.put("policy_strict_v1", strict);
        com.ownrag.config.Settings settings = new com.ownrag.config.Settings(
                base.getDataDir(), "", base.getOllamaBaseUrl(), base.getChatProvider(),
                base.getChatBaseUrl(), base.getChatApiKey(), base.getChatModel(),
                base.getEmbedProvider(), base.getEmbedBaseUrl(), base.getEmbedApiKey(),
                base.getEmbedModel(), base.getEmbedVersion(), "",
                base.getRerankProvider(), base.getRerankBaseUrl(), base.getRerankModel(), "",
                base.getMineruMode(), "", base.getMineruOpenBaseUrl(), "",
                base.getAsrBaseUrl(), base.getAsrModel(), base.getAsrLanguage(), "",
                base.getNumCtx(), base.getMaxNewTokens(), base.getMaxUploadMb(),
                new LinkedHashMap<>(), new LinkedHashMap<>(), prompts);
        String ctxWithLatex = "动能公式 $E_k = \\frac{1}{2}mv^2$，欧拉恒等式 $e^{i\\pi}+1=0$";
        List<Map<String, Object>> msgs = PromptRenderer.render(settings, "policy_strict_v1", "问题Q", ctxWithLatex);
        String user = String.valueOf(msgs.get(1).get("content"));
        assertTrue(user.contains("\\frac{1}{2}"), "资料正文的 LaTeX 必须原样保留");
        assertTrue(user.contains("问题Q"));
    }

    @Test
    void render_占位符缺失渲染期爆() {
        com.ownrag.config.Settings base = new com.ownrag.retrieve.RetrieveTest.SettingsBuilder().build();
        // 注册 policy_strict_v1（正文模板）与含未支持占位符 {oops} 的坏模板
        java.util.Map<String, com.ownrag.config.PromptDef> prompts = new LinkedHashMap<>();
        com.ownrag.config.PromptDef strict = new com.ownrag.config.PromptDef();
        strict.name = "policy_strict_v1";
        strict.system = "系统规则";
        strict.template = "【资料】\n{context_blocks}\n\n【问题】\n{question}";
        prompts.put("policy_strict_v1", strict);
        com.ownrag.config.PromptDef bad = new com.ownrag.config.PromptDef();
        bad.name = "bad";
        bad.system = "s";
        bad.template = "{question}\n{oops}";
        prompts.put("bad", bad);
        com.ownrag.config.Settings settings = new com.ownrag.config.Settings(
                base.getDataDir(), "", base.getOllamaBaseUrl(), base.getChatProvider(),
                base.getChatBaseUrl(), base.getChatApiKey(), base.getChatModel(),
                base.getEmbedProvider(), base.getEmbedBaseUrl(), base.getEmbedApiKey(),
                base.getEmbedModel(), base.getEmbedVersion(), "",
                base.getRerankProvider(), base.getRerankBaseUrl(), base.getRerankModel(), "",
                base.getMineruMode(), "", base.getMineruOpenBaseUrl(), "",
                base.getAsrBaseUrl(), base.getAsrModel(), base.getAsrLanguage(), "",
                base.getNumCtx(), base.getMaxNewTokens(), base.getMaxUploadMb(),
                new LinkedHashMap<>(), new LinkedHashMap<>(), prompts);
        IllegalArgumentException e = assertThrows(IllegalArgumentException.class,
                () -> PromptRenderer.render(settings, "bad", "q", "ctx"));
        assertTrue(e.getMessage().contains("oops"), e.getMessage());

        // 正常渲染出 system + user 两条消息
        List<Map<String, Object>> msgs = PromptRenderer.render(settings, "policy_strict_v1", "问题Q", "资料C");
        assertEquals(2, msgs.size());
        assertEquals("system", msgs.get(0).get("role"));
        assertTrue(String.valueOf(msgs.get(1).get("content")).contains("资料C"));
        assertTrue(String.valueOf(msgs.get(1).get("content")).contains("问题Q"));
    }

    /** JDK8 无 String.repeat：测试用小工具。 */
    private static String rep(String s, int n) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < n; i++) {
            sb.append(s);
        }
        return sb.toString();
    }
}
