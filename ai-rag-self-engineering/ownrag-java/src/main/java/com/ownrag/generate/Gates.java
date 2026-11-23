package com.ownrag.generate;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 两道纯代码闸门（Python 版 generate/gates.py 的平移）：把"模型会错"从故障变成可测试的规则集。
 *
 * 闸门一 生成前 sufficiencyCheck：候选不足不进模型——"未找到有效依据"是合法答案。
 * 闸门二 生成后 citationCheck：引用的块必须在候选池内；数字/日期必须能在引用块原文找到。
 * 规则表进 Git、随评测集回归——确定性的事不交给模型。
 */
public final class Gates {

    private static final Pattern REF = Pattern.compile("\\[来源[:：]\\s*块?(\\d+)]|块(\\d+)");
    private static final Pattern NUM = Pattern.compile("\\d[\\d,，.]*");
    private static final Pattern DATE = Pattern.compile("\\d{4}[-/年]\\d{1,2}([-/月]\\d{1,2})?日?");
    // 行首列表序号（1. / 1、 / 1）是格式不是事实数字；(?!\d) 防吞小数（"2.5 万元"的 2. 不是序号）
    private static final Pattern LIST_ORD = Pattern.compile("^\\s*\\d+\\s*[.、)）](?!\\d)\\s*");
    private static final double MIN_SCORE = 0.0;    // RRF 分数下限——骨架期只做非空与相对值校验
    // 重排分下限：bge-reranker-v2-m3 校准（相关块 ~0.9+，语义邻近无关块 ~0.0）
    public static final double MIN_RERANK_SCORE = 0.05;

    private Gates() {
    }

    /** 闸门结果（Python 版 GateResult dataclass 的对应物）。 */
    public static class GateResult {
        public final String name;
        public final boolean passed;
        public final String reason;
        public final List<String> violations;

        public GateResult(String name, boolean passed, String reason) {
            this(name, passed, reason, new ArrayList<>());
        }

        public GateResult(String name, boolean passed, String reason, List<String> violations) {
            this.name = name;
            this.passed = passed;
            this.reason = reason;
            this.violations = violations;
        }
    }

    /**
     * 闸门一：候选不足不进模型。有重排分（rerank 已启用）时按重排分下限校验——
     * 向量通道永远能捞回"语义邻近"的块，RRF 名次分区分不了实质依据；无重排分退回 RRF 口径。
     */
    public static GateResult sufficiencyCheck(List<Map<String, Object>> candidates) {
        if (candidates == null || candidates.isEmpty()) {
            return new GateResult("sufficiency_check", false, "候选池为空：未找到有效依据，不进模型");
        }
        // SQL 结果是确定性证据（引擎算出来的，不是语义邻近）：只要它在，就不该被重排分下限拦掉。
        // 否则「多源问题里 RAG 那一路很弱」会把带 SQL 事实的正确答案一起判成"无依据"。
        for (Map<String, Object> c : candidates) {
            if ("sql".equals(c.get("kind"))) {
                return new GateResult("sufficiency_check", true, "命中 SQL 事实证据，放行");
            }
        }
        List<Double> rerankScores = new ArrayList<>();
        for (Map<String, Object> c : candidates) {
            Object s = c.get("rerank_score");
            if (s instanceof Number) {
                rerankScores.add(((Number) s).doubleValue());
            }
        }
        if (!rerankScores.isEmpty()) {
            double top = java.util.Collections.max(rerankScores);
            if (top < MIN_RERANK_SCORE) {
                return new GateResult("sufficiency_check", false,
                        String.format("最高重排分过低（%.4f < %s）：语义邻近但无实质依据，拒答", top, MIN_RERANK_SCORE));
            }
            return new GateResult("sufficiency_check", true,
                    String.format("候选 %d 条，top-rerank=%.4f", candidates.size(), top));
        }
        double top = candidates.get(0).get("rrf") instanceof Number ? ((Number) candidates.get(0).get("rrf")).doubleValue() : 0.0;
        if (top <= MIN_SCORE) {
            return new GateResult("sufficiency_check", false, "最高融合分过低（" + top + "）");
        }
        return new GateResult("sufficiency_check", true,
                String.format("候选 %d 条，top-rrf=%.4f", candidates.size(), top));
    }

    /**
     * 闸门二：引用真实性校验。
     * ① 引用的块编号必须在候选池内；
     * ② 答案中的数字/日期必须能在其引用的块原文中找到（防数字幻觉；无引用的数字句=违规）。
     */
    public static GateResult citationCheck(String answer, List<Map<String, Object>> candidates) {
        Map<Integer, Map<String, Object>> byOrdinal = new LinkedHashMap<>();
        for (Map<String, Object> c : candidates) {
            if (c.get("ordinal") instanceof Number) {
                byOrdinal.put(((Number) c.get("ordinal")).intValue(), c);
            }
        }
        List<String> violations = new ArrayList<>();
        Set<Integer> cited = new LinkedHashSet<>();

        String[] lines = answer.split("\r?\n");
        for (String line : lines) {
            List<Integer> refs = new ArrayList<>();
            Matcher rm = REF.matcher(line);
            while (rm.find()) {
                if (!rm.group(1).isEmpty()) {
                    refs.add(Integer.parseInt(rm.group(1)));
                } else {
                    refs.add(Integer.parseInt(rm.group(2)));
                }
            }
            String bare = REF.matcher(line).replaceAll("");  // 剔除引用标注本身，防"块1"的 1 被当数字校验
            bare = LIST_ORD.matcher(bare).replaceFirst("");    // 行首列表序号同理是格式，不参与数字核验
            List<String> nums = new ArrayList<>();
            Matcher nm = NUM.matcher(bare);
            while (nm.find()) {
                nums.add(nm.group());
            }
            Matcher dm = DATE.matcher(bare);
            while (dm.find()) {
                nums.add(dm.group());
            }
            if (refs.isEmpty()) {
                if (!nums.isEmpty()) {  // 有数字但无引用——数字幻觉的温床
                    violations.add("数字/日期无引用：" + trim60(line));
                }
                continue;
            }
            for (int r : refs) {
                Map<String, Object> chunk = byOrdinal.get(r);
                if (chunk == null) {
                    violations.add("引用不存在：块" + r + "（候选池 " + new TreeSet<>(byOrdinal.keySet()) + "）");
                    continue;
                }
                cited.add(r);
                String chunkText = chunk.get("text") == null ? "" : String.valueOf(chunk.get("text"));
                for (String n : nums) {
                    String norm = normNum(n);
                    if (!norm.isEmpty() && !normText(chunkText).contains(norm)) {
                        violations.add("数字 " + norm + " 不在块" + r + "原文中：" + trim60(line));
                    }
                }
            }
        }

        // 关键硬约束：一条引用都没有但答案很长——疑似模型自由发挥
        if (cited.isEmpty() && answer.trim().length() > 100) {
            violations.add("长答案无任何引用");
        }

        return new GateResult("citation_check", violations.isEmpty(),
                cited.isEmpty() ? "无有效引用" : "引用块 " + new TreeSet<>(cited), violations);
    }

    /** 输出结构校验（JSON 模式时的骨架实现）。 */
    public static GateResult schemaCheck(String answer, boolean expectJson) {
        if (!expectJson) {
            return new GateResult("schema_check", true, "非 JSON 模式，跳过");
        }
        try {
            com.ownrag.util.Json.MAPPER.readTree(answer);
            return new GateResult("schema_check", true, "JSON 合法");
        } catch (Exception e) {
            return new GateResult("schema_check", false, "JSON 不合法：" + e.getMessage());
        }
    }

    static String normNum(String s) {
        String v = s.replaceAll("[,，\\s]", "");
        return v.endsWith(".") ? v.substring(0, v.length() - 1) : v;
    }

    static String normText(String s) {
        return s.replaceAll("[\\s,，]", "");
    }

    private static String trim60(String s) {
        String t = s.trim();
        return t.length() <= 60 ? t : t.substring(0, 60);
    }
}
