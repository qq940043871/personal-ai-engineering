package com.ownrag.retrieve;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

import org.springframework.stereotype.Component;

import com.ownrag.config.Settings;
import com.ownrag.generate.ChatClient;

/**
 * 检索问句改写（Java 版新增）：只回答一个问题——这次召回到底用哪句话去检索。
 *
 * 口径（可关闭 / 可解释 / 可降级，绝不静默变脸）：
 *  1) 规则闸门决定"要不要改写"（零网络开销，命中才可能花钱）：
 *     - 指代/省略：本轮问题含「它/该/这个/上面/刚才…」且带对话历史 → 指代消解改写；
 *     - 套话：含「请问/帮我/麻烦/我想知道…」→ 剥掉套话（纯规则，不调模型）。
 *  2) 命中的改写手段：
 *     - delexical：规则去套话（确定性，零延迟）；
 *     - llm：一次短调用把（历史 + 本轮）压成可独立检索的问句（温度 0）；
 *     - fallback：模型不可用/失败时把上一轮问题拼进检索式（宁可多召回，也不静默丢上下文）。
 *  3) 不触发时 rewritten == original，前端必须能明确看到"没改写 / 为什么没改写"。
 *
 * 直击库（DirectHit）永远用原问题精确匹配——改写只服务召回通道，不许污染可控答案。
 */
@Component
public class QueryRewriter {

    /**
     * 指代词/省略线索：命中说明本轮问题自身不足以召回（"这个/该/上面"没有具体对象）。
     * 只收复合指代（该公司/该标准…），不收裸「该/其/此」——"其他""因此"会误触发。
     */
    private static final Pattern PRONOUN = Pattern.compile(
            "它|它们|他|她|该公司|该岗位|该标准|该流程|该制度|该政策|该文档|该员工|该规则|"
                    + "这个|那个|这些|那些|这种|那种|上述|前述|上面|刚才|上次|上一条|"
                    + "这条|这份|那份|这项|那项");
    /** 提问套话：去掉不改变语义，但会污染 BM25 的短语匹配（"请问报销口径" 短语命中率低）。 */
    private static final Pattern SMALLTALK = Pattern.compile(
            "请问|请教一下|请教|麻烦|帮我|帮忙|我想知道|想问一下|想了解|能不能|可不可以|"
                    + "可以告诉我|告诉我一下|说一下|讲一下|介绍一下|谢谢|多谢|辛苦了");

    /**
     * 改写结果（同时也是 SSE `rewrite` 事件的载荷）：
     * triggered=false 时 rewritten == original，reason 说明为什么没改写。
     */
    public static class Result {
        public final boolean triggered;
        public final String original;
        public final String rewritten;
        public final String method;     // none | delexical | llm | fallback
        public final String reason;
        public final int historyTurns;
        public final double ms;         // 0.1ms 精度：规则改写常在 1ms 内，用整数毫秒看不出差别

        Result(boolean triggered, String original, String rewritten, String method,
               String reason, int historyTurns, double ms) {
            this.triggered = triggered;
            this.original = original;
            this.rewritten = rewritten;
            this.method = method;
            this.reason = reason;
            this.historyTurns = historyTurns;
            this.ms = ms;
        }

        /**
         * 没走召回通道时（SQL 单通道）的占位结果：`rewrite` 事件仍要下发，
         * 否则前端按固定顺序消费事件时会以为链路缺一环。
         */
        public static Result skipped(String question, String reason) {
            return new Result(false, question, question, "none", reason, 0, 0.0);
        }

        /** 前端/SSE 直接消费的结构（键名与 Python 侧习惯保持一致：小写下划线）。 */
        public Map<String, Object> toEvent() {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("triggered", triggered);
            out.put("original", original);
            out.put("rewritten", rewritten);
            out.put("method", method);
            out.put("reason", reason);
            out.put("history_turns", historyTurns);
            out.put("ms", ms);
            return out;
        }
    }

    /**
     * 执行改写。
     *
     * @param llm    可为 null（单测/降级环境）：为 null 时指代消解走 fallback 拼接，不调模型
     * @param force  null=按规则自动触发；true=强制改写；false=本次关闭改写
     */
    public Result rewrite(Settings settings, ChatClient llm, String question,
                          List<Map<String, Object>> history, Boolean force) {
        long t0 = System.nanoTime();
        String original = question == null ? "" : question.trim();
        int turns = history == null ? 0 : history.size();
        String lastQ = lastQuestion(history);

        if (Boolean.FALSE.equals(force)) {
            return done(false, original, original, "none", "改写已关闭（本次请求 rewrite=false）", turns, t0);
        }

        boolean pronoun = PRONOUN.matcher(original).find();
        String delext = delexicalize(original);
        boolean delexChanged = !delext.equals(original) && delext.length() >= 4;
        boolean forced = Boolean.TRUE.equals(force);

        // ---- 1) 指代消解：优先于去套话（"它"指什么，比去掉"请问"更影响召回）----
        if ((pronoun && lastQ != null) || (forced && lastQ != null)) {
            String note = null;
            if (llm != null) {
                try {
                    String byLlm = llmRewrite(llm, settings, original, history);
                    if (byLlm != null && !byLlm.isEmpty() && !sameText(byLlm, original)) {
                        return done(true, original, byLlm, "llm",
                                pronoun ? "命中指代（" + pronounOf(original) + "）+ 有历史 → 模型解析成独立问句"
                                        : "强制改写 → 模型解析成独立问句",
                                turns, t0);
                    }
                } catch (Exception e) {
                    // 改写不是必备能力：模型挂了就降级拼接，并把原因播报出去
                    note = "模型改写失败已降级：" + e.getMessage();
                }
            } else {
                note = "无可用改写模型（按历史拼接降级）";
            }
            return done(true, original, joinQuery(lastQ, delexChanged ? delext : original), "fallback",
                    note != null ? note : "模型返回与原问题相同，按历史拼接兜底", turns, t0);
        }

        // ---- 2) 套话剥离：确定性规则，零模型开销 ----
        if (delexChanged) {
            return done(true, original, delext, "delexical",
                    "剥掉提问套话（关键词通道的短语匹配对套话敏感）", turns, t0);
        }

        // ---- 3) 不触发：如实汇报原因（前端要能看见"没改写"）----
        String reason;
        if (pronoun) {
            reason = "含指代词「" + pronounOf(original) + "」但无对话历史（首轮不做指代消解）";
        } else if (forced) {
            reason = "强制改写但无历史、无可用改写模型，保持原问题";
        } else {
            reason = "未命中改写条件（无指代、无套话）";
        }
        return done(false, original, original, "none", reason, turns, t0);
    }

    /** 去套话：只删提问套话与首尾标点噪声，不动实体词。 */
    static String delexicalize(String question) {
        String out = question == null ? "" : question.trim();
        out = SMALLTALK.matcher(out).replaceAll("");
        out = out.replaceAll("^[\\s，,。、；;：:？?！!]+", "").replaceAll("[\\s，,。、；;：:？?！!]+$", "").trim();
        return out.isEmpty() ? (question == null ? "" : question.trim()) : out;
    }

    /** 历史拼接兜底：上一轮问题 + 本轮问题（BM25 要关键词，向量要语义，两句话都留下）。 */
    static String joinQuery(String lastQ, String current) {
        if (lastQ == null || lastQ.isEmpty()) {
            return current;
        }
        return lastQ + " " + current;
    }

    /** 历史里最后一条用户问题（只取 q：答案太长且会把召回拉偏）。 */
    static String lastQuestion(List<Map<String, Object>> history) {
        if (history == null) {
            return null;
        }
        for (int i = history.size() - 1; i >= 0; i--) {
            Object q = history.get(i) == null ? null : history.get(i).get("q");
            String s = q == null ? "" : String.valueOf(q).trim();
            if (!s.isEmpty()) {
                return s.length() > 200 ? s.substring(0, 200) : s;
            }
        }
        return null;
    }

    /** 命中历史的首个指代词（写进 reason，人看得懂"为什么触发"）。 */
    static String pronounOf(String question) {
        java.util.regex.Matcher m = PRONOUN.matcher(question == null ? "" : question);
        return m.find() ? m.group() : "";
    }

    // ---- 模型改写（短调用、温度 0、只输出一行）----

    private String llmRewrite(ChatClient llm, Settings settings, String question,
                              List<Map<String, Object>> history) {
        List<Map<String, Object>> messages = new ArrayList<>();
        messages.add(msg("system", "你是检索问句改写器。把用户的最新问题改写成一句可独立检索的短问句："
                + "补全指代（它/该/这个）所指的对象，保留原意与关键实体，不回答问题、不解释、不加引号。"
                + "只输出改写后的一行问句。"));
        StringBuilder user = new StringBuilder();
        if (history != null && !history.isEmpty()) {
            user.append("【对话历史（旧→新，最多 2 轮）】\n");
            int from = Math.max(0, history.size() - 2);
            for (int i = from; i < history.size(); i++) {
                Map<String, Object> turn = history.get(i);
                user.append("用户：").append(clip(turn == null ? null : turn.get("q"), 160)).append('\n');
            }
        }
        user.append("【本轮问题】\n").append(question).append("\n【改写】");
        messages.add(msg("user", user.toString()));

        String raw = llm.chat(settings, messages, null, 2048, 0.0, 96);
        return sanitizeRewrite(raw);
    }

    /** 模型输出清洗：取第一行、去「改写：」前缀与引号，超长/空则视为无效。 */
    static String sanitizeRewrite(String raw) {
        if (raw == null) {
            return null;
        }
        String s = raw.trim();
        int nl = s.indexOf('\n');
        if (nl >= 0) {
            s = s.substring(0, nl).trim();
        }
        s = s.replaceFirst("^(改写|检索问句|问句)\\s*[：:]\\s*", "");
        s = s.replaceAll("^[\"'“”‘’《》]+|[\"'“”‘’《》]+$", "").trim();
        if (s.length() < 2 || s.length() > 200) {
            return null;
        }
        return s;
    }

    private static boolean sameText(String a, String b) {
        return a.replaceAll("\\s+", "").equals(b.replaceAll("\\s+", ""));
    }

    private static String clip(Object o, int max) {
        String s = o == null ? "" : String.valueOf(o).trim();
        return s.length() <= max ? s : s.substring(0, max) + "…";
    }

    private static Map<String, Object> msg(String role, String content) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("role", role);
        m.put("content", content);
        return m;
    }

    private static Result done(boolean triggered, String original, String rewritten, String method,
                               String reason, int turns, long t0) {
        double ms = Math.round((System.nanoTime() - t0) / 1e5) / 10.0;
        return new Result(triggered, original, rewritten == null ? original : rewritten.trim(),
                method, reason, turns, ms);
    }
}
