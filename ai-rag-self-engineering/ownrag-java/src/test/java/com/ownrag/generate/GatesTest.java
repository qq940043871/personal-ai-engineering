package com.ownrag.generate;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** 两道闸门回归（对齐 Python 版 gates.py 语义）。 */
class GatesTest {

    private static Map<String, Object> candidate(int ordinal, String text) {
        Map<String, Object> c = new LinkedHashMap<>();
        c.put("ordinal", ordinal);
        c.put("chunk_id", String.format("d#%04d", ordinal));
        c.put("doc_id", "d");
        c.put("text", text);
        return c;
    }

    @Test
    void 闸门一_候选空拒答() {
        Gates.GateResult r = Gates.sufficiencyCheck(new ArrayList<>());
        assertFalse(r.passed);
        assertTrue(r.reason.contains("候选池为空"));
    }

    @Test
    void 闸门一_重排分过低拒答() {
        List<Map<String, Object>> candidates = new ArrayList<>();
        Map<String, Object> c = candidate(1, "相关内容");
        c.put("rerank_score", 0.01);
        candidates.add(c);
        Gates.GateResult r = Gates.sufficiencyCheck(candidates);
        assertFalse(r.passed);
        assertTrue(r.reason.contains("重排分过低"), r.reason);
    }

    @Test
    void 闸门一_重排分足量放行() {
        List<Map<String, Object>> candidates = new ArrayList<>();
        Map<String, Object> c = candidate(1, "相关内容");
        c.put("rerank_score", 0.95);
        candidates.add(c);
        assertTrue(Gates.sufficiencyCheck(candidates).passed);
    }

    @Test
    void 闸门一_无重排分退回RRF口径() {
        List<Map<String, Object>> candidates = new ArrayList<>();
        Map<String, Object> c = candidate(1, "相关内容");
        c.put("rrf", 0.032);
        candidates.add(c);
        Gates.GateResult r = Gates.sufficiencyCheck(candidates);
        assertTrue(r.passed);
        assertTrue(r.reason.contains("top-rrf"), r.reason);
    }

    @Test
    void 闸门二_假引用被抓() {
        List<Map<String, Object>> candidates = new ArrayList<>();
        candidates.add(candidate(1, "正文"));
        Gates.GateResult r = Gates.citationCheck("这是结论 [来源: 块9]", candidates);
        assertFalse(r.passed);
        assertTrue(r.violations.stream().anyMatch(v -> v.contains("引用不存在")), r.violations.toString());
    }

    @Test
    void 闸门二_数字幻觉被抓() {
        List<Map<String, Object>> candidates = new ArrayList<>();
        candidates.add(candidate(1, "公司注册资本 100 万元"));
        Gates.GateResult r = Gates.citationCheck("注册资本为 500 万元 [来源: 块1]", candidates);
        assertFalse(r.passed);
        assertTrue(r.violations.stream().anyMatch(v -> v.contains("500") && v.contains("不在块1原文")),
                r.violations.toString());
    }

    @Test
    void 闸门二_逐字引用通过() {
        List<Map<String, Object>> candidates = new ArrayList<>();
        candidates.add(candidate(1, "公司注册资本 100 万元"));
        Gates.GateResult r = Gates.citationCheck("注册资本为 100 万元 [来源: 块1]", candidates);
        assertTrue(r.passed, r.violations.toString());
    }

    @Test
    void 闸门二_数字无引用违规() {
        List<Map<String, Object>> candidates = new ArrayList<>();
        candidates.add(candidate(1, "正文一段"));
        Gates.GateResult r = Gates.citationCheck("根据规定期限为 30 个工作日", candidates);
        assertFalse(r.passed);
        assertTrue(r.violations.stream().anyMatch(v -> v.contains("数字/日期无引用")),
                r.violations.toString());
    }

    @Test
    void 闸门二_行首列表序号不参与数字核验() {
        List<Map<String, Object>> candidates = new ArrayList<>();
        candidates.add(candidate(1, "正文"));
        Gates.GateResult r = Gates.citationCheck("1. 第一点结论 [来源: 块1]\n2. 第二点 [来源: 块1]", candidates);
        assertTrue(r.passed, r.violations.toString());
    }

    @Test
    void 闸门二_长答案无引用违规() {
        List<Map<String, Object>> candidates = new ArrayList<>();
        candidates.add(candidate(1, "正文"));
        String longAnswer = rep("很长", 80);
        Gates.GateResult r = Gates.citationCheck(longAnswer, candidates);
        assertFalse(r.passed);
        assertTrue(r.violations.stream().anyMatch(v -> v.contains("长答案无任何引用")));
    }

    @Test
    void 闸门二_引用标注里的数字不算事实数字() {
        List<Map<String, Object>> candidates = new ArrayList<>();
        candidates.add(candidate(1, "正文"));
        Gates.GateResult r = Gates.citationCheck("这是唯一结论 [来源: 块1]", candidates);
        assertTrue(r.passed, r.violations.toString());
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
