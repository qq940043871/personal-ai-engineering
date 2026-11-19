package com.ownrag.generate;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.ownrag.index.EstTokens;
import com.ownrag.util.Yamls;

/**
 * 上下文预算（Python 版 generate/budget.py 的平移）：先算容量再拼装，不把截断权交给模型侧。
 *
 * num_ctx 是输入+输出的总窗口，超窗时模型静默截断——若把 top_n 个候选原样拼进去，
 * 最坏情况先被截掉的是问题本身。这里把预算显式化：
 *
 *   上下文容量 = num_ctx - prompt 固定开销（system+模板+问题） - 输出预留(max_new_tokens) - 安全余量
 *
 * 超出部分按候选顺序丢弃（保留高分在前），丢弃与截断都通过 SSE 事件上报，属"降级可见"的一部分。
 */
public final class Budget {

    public static final int SAFETY_TOKENS = 64;      // 模板渲染的格式差异余量
    public static final int MIN_CONTEXT_TOKENS = 128; // 再紧也要留一块的位置，否则等于拒答

    private Budget() {
    }

    /** 预算结果（Python 版 BudgetResult 的对应物）。 */
    public static class BudgetResult {
        public final List<Map<String, Object>> blocks;
        public final String text;
        public final int tokens;
        public final List<String> dropped = new ArrayList<>();
        public final boolean truncated;

        public BudgetResult(List<Map<String, Object>> blocks, String text, int tokens,
                            List<String> dropped, boolean truncated) {
            this.blocks = blocks;
            this.text = text;
            this.tokens = tokens;
            if (dropped != null) {
                this.dropped.addAll(dropped);
            }
            this.truncated = truncated;
        }
    }

    /** 单块的 prompt 形态（与路由里拼装口径必须一致）。 */
    public static String blockPrompt(Map<String, Object> c) {
        return "[块" + c.get("ordinal") + "]（来源 doc=" + c.get("doc_id") + "）\n"
                + (c.get("text") == null ? "" : c.get("text"));
    }

    /** 可用上下文预算（token）。永远至少 MIN_CONTEXT_TOKENS，避免配置写错就变成永远拒答。 */
    public static int contextBudget(int numCtx, int promptOverhead, int maxNewTokens) {
        return Math.max(MIN_CONTEXT_TOKENS,
                numCtx - promptOverhead - maxNewTokens - SAFETY_TOKENS);
    }

    /** 按序装块直到预算用尽；首个块就超预算时按字符比例截断并标记 truncated。 */
    public static BudgetResult fitCandidates(List<Map<String, Object>> candidates, int budgetTokens) {
        if (candidates == null || candidates.isEmpty()) {
            return new BudgetResult(new ArrayList<>(), "", 0, new ArrayList<>(), false);
        }
        int budget = Math.max(MIN_CONTEXT_TOKENS, budgetTokens);
        List<Map<String, Object>> kept = new ArrayList<>();
        List<String> parts = new ArrayList<>();
        int used = 0;

        for (int idx = 0; idx < candidates.size(); idx++) {
            Map<String, Object> c = candidates.get(idx);
            String text = blockPrompt(c);
            int cost = Math.max(1, EstTokens.est(text));
            if (used + cost <= budget) {
                kept.add(c);
                parts.add(text);
                used += cost;
                continue;
            }
            if (kept.isEmpty()) {
                // 第一块就超：截正文保住块头与引用编号
                String head = "[块" + c.get("ordinal") + "]（来源 doc=" + c.get("doc_id") + "）\n";
                String body = c.get("text") == null ? "" : String.valueOf(c.get("text"));
                // 按预算比例先裁一次，再按实际估算收敛（CJK/ASCII 混排时比例不精确）
                int cut = Math.max(1, (int) ((double) body.length() * budget / Math.max(1, cost)));
                while (cut > 1 && EstTokens.est(head + body.substring(0, cut)) > budget) {
                    cut = (int) (cut * 0.9);
                }
                Map<String, Object> trimmed = new LinkedHashMap<>(c);
                trimmed.put("text", body.substring(0, cut));
                kept.add(trimmed);
                parts.add(blockPrompt(trimmed));
                used = EstTokens.est(parts.get(parts.size() - 1));
                List<String> dropped = new ArrayList<>();
                for (int j = idx + 1; j < candidates.size(); j++) {
                    dropped.add(String.valueOf(candidates.get(j).get("chunk_id")));
                }
                dropped.add(String.valueOf(c.get("chunk_id")));
                return new BudgetResult(kept, String.join("\n\n", parts), used, dropped, true);
            }
            List<String> dropped = new ArrayList<>();
            for (int j = idx; j < candidates.size(); j++) {
                dropped.add(String.valueOf(candidates.get(j).get("chunk_id")));
            }
            return new BudgetResult(kept, String.join("\n\n", parts), used, dropped, false);
        }
        return new BudgetResult(kept, String.join("\n\n", parts), used, new ArrayList<>(), false);
    }

    /** 窗口与输出预留的优先级：环境变量（运维 kill-switch）> apps.yaml > models.yaml。 */
    public static int[] resolveLimits(com.ownrag.config.Settings settings, Map<String, Object> genCfg) {
        int numCtx = intEnvOr("OWNRAG_NUM_CTX",
                genCfg != null && genCfg.get("max_ctx_tokens") instanceof Number
                        ? ((Number) genCfg.get("max_ctx_tokens")).intValue() : settings.getNumCtx());
        int maxNew = intEnvOr("OWNRAG_MAX_NEW_TOKENS",
                genCfg != null && genCfg.get("max_new_tokens") instanceof Number
                        ? ((Number) genCfg.get("max_new_tokens")).intValue() : settings.getMaxNewTokens());
        return new int[]{numCtx, maxNew};
    }

    /** 预算计划（问答与调试页共用）：问答链路与检索调试端点共用同一份预算计算。 */
    public static class ContextPlan {
        public final BudgetResult fitted;
        public final String promptName;
        public final int numCtx;
        public final int maxNewTokens;
        public final int promptOverhead;
        public final int available;

        public ContextPlan(BudgetResult fitted, String promptName, int numCtx,
                           int maxNewTokens, int promptOverhead, int available) {
            this.fitted = fitted;
            this.promptName = promptName;
            this.numCtx = numCtx;
            this.maxNewTokens = maxNewTokens;
            this.promptOverhead = promptOverhead;
            this.available = available;
        }
    }

    public static ContextPlan planContext(List<Map<String, Object>> candidates, String question,
                                          String promptName, int numCtx, int maxNewTokens,
                                          com.ownrag.config.Settings settings) {
        List<Map<String, Object>> probe = PromptRenderer.render(settings, promptName, question, "");
        int overhead = 0;
        for (Map<String, Object> m : probe) {
            overhead += EstTokens.est(String.valueOf(m.get("content")));
        }
        int available = contextBudget(numCtx, overhead, maxNewTokens);
        return new ContextPlan(fitCandidates(candidates, available), promptName,
                numCtx, maxNewTokens, overhead, available);
    }

    private static int intEnvOr(String key, int def) {
        String v = System.getenv(key);
        if (v == null || v.trim().isEmpty()) {
            return def;
        }
        try {
            return Integer.parseInt(v.trim());
        } catch (NumberFormatException e) {
            return def;
        }
    }
}
