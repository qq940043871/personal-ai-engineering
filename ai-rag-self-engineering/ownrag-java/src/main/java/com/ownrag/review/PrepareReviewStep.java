package com.ownrag.review;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.stereotype.Component;

import com.ownrag.core.Step;
import com.ownrag.core.StepContext;
import com.ownrag.core.StepResult;
import com.ownrag.index.CleanMarkdown;

/**
 * prepare_review 步骤（Python 版 PrepareReview 的平移）：
 * 解析 + 切分产物复核：落盘四份工件（parsed.md / cleaned.md / chunks.json / report.json）、
 * 跑自动检查、置 pending。
 * 放在 chunk_markdown 之后：复核要能同时看到"解析成了什么""清洗后剩什么"和"切成了什么"——
 * 三栏并排，删掉的每一处都能当场对上账。
 */
@Component
public class PrepareReviewStep implements Step {

    @Override
    public String type() {
        return "prepare_review";
    }

    @SuppressWarnings("unchecked")
    @Override
    public StepResult run(StepContext ctx, Map<String, Object> params) {
        Map<String, Object> parsed =
                (Map<String, Object>) ctx.data.getOrDefault("parsed", new LinkedHashMap<>());
        List<Map<String, Object>> chunks =
                (List<Map<String, Object>>) ctx.data.getOrDefault("chunks", new java.util.ArrayList<>());
        Object md = parsed.get("markdown");
        if (md == null || String.valueOf(md).isEmpty()) {
            return StepResult.fail("无 parsed.markdown——上游解析步骤缺失或未产出");
        }
        if (chunks.isEmpty()) {
            return StepResult.fail("无 chunks——prepare_review 必须排在 chunk_markdown 之后");
        }

        int minCharsPerPage = params.get("min_chars_per_page") instanceof Number
                ? ((Number) params.get("min_chars_per_page")).intValue() : 20;
        int maxChunkTokens = params.get("max_chunk_tokens") instanceof Number
                ? ((Number) params.get("max_chunk_tokens")).intValue() : 512;
        double oversizedRatio = params.get("oversized_ratio") instanceof Number
                ? ((Number) params.get("oversized_ratio")).doubleValue() : 1.5;

        // 清洗后正文（= 切分与入库的实际输入）：与 chunk_markdown 同一纯函数 + 同一参数，现算不落黑板。
        // 先算清洗再跑质量检查：文档统计里"多少字"要同时给解析后与清洗后两个数。
        CleanMarkdown.Result cleaned = CleanMarkdown.apply(String.valueOf(md),
                (Map<String, Object>) orEmpty(ctx.data.get("clean_options")));
        Map<String, Object> cleanStats = ctx.data.get("clean") instanceof Map
                ? (Map<String, Object>) ctx.data.get("clean") : cleaned.stats;

        Map<String, Object> checks = ReviewStore.qualityChecks(parsed, chunks,
                minCharsPerPage, maxChunkTokens, oversizedRatio, cleanStats);
        Map<String, Object> stats = (Map<String, Object>) checks.get("stats");
        stats.put("clean_chars", cleanStats.get("chars_out"));
        stats.put("clean_removed_ratio", cleanStats.get("removed_ratio"));
        // 清洗过量 = 规则可能在删正文（页眉/页码规则误伤）：提示项，让人对着两栏看一眼
        Object removedRatio = cleanStats.get("removed_ratio");
        if (removedRatio instanceof Number && ((Number) removedRatio).doubleValue() > 0.25
                && !"fail".equals(checks.get("verdict"))) {
            double pct = ((Number) removedRatio).doubleValue() * 100;
            Map<String, Object> warnItem = new LinkedHashMap<>();
            warnItem.put("code", "clean_removed_lots");
            warnItem.put("detail", String.format("清洗移除了 %.1f%% 正文（%s → %s 字符）："
                            + "可能是页码/页标记规则误伤，对照「解析后 / 清洗后」两栏确认",
                    pct, cleanStats.get("chars_in"), cleanStats.get("chars_out")));
            ((List<Map<String, Object>>) checks.get("warn")).add(warnItem);
            checks.put("verdict", "warn");
        }

        boolean autoApprove = Boolean.TRUE.equals(params.get("auto_approve"));
        Map<String, Object> report = new LinkedHashMap<>();
        report.put("doc_id", ctx.docId);
        report.put("kb", ctx.kb);
        report.put("pipeline", ctx.data.get("_pipeline"));
        Map<String, Object> parsedMeta = (Map<String, Object>) orEmpty(parsed.get("metadata"));
        report.put("source_file", parsedMeta.get("source_file"));
        report.put("parse_route", ctx.data.get("page_route"));   // detect_pages 的页级路由结论
        report.put("params", params);
        report.put("stats", orEmpty(parsed.get("stats")));
        report.put("metadata", parsedMeta);
        Map<String, Object> assets = (Map<String, Object>) orEmpty(parsed.get("assets"));
        report.put("assets", new java.util.ArrayList<>(assets.keySet()).subList(0, Math.min(20, assets.size())));
        report.put("checks", checks);
        report.put("clean", cleanStats);   // "解析后 → 清洗后" 每条规则的命中计数，供复核页逐项核对
        report.put("doc_stats", checks.get("doc_stats"));   // 格式/页/字/图/公式/表 + 存疑清单

        Map<String, String> paths;
        try {
            paths = ReviewStore.writeArtifacts(ctx.settings.getReviewDir().resolve(ctx.docId),
                    String.valueOf(md), cleaned.markdown, chunks, report);
        } catch (Exception e) {
            return StepResult.fail("复核工件落盘失败：" + e.getMessage());
        }

        String status;
        try {
            status = ReviewStore.saveReview(ctx.conn, ctx.docId, ctx.kb,
                    ctx.data.get("_task_id") == null ? null : String.valueOf(ctx.data.get("_task_id")),
                    ctx.traceId,
                    ctx.data.get("_pipeline") == null ? "" : String.valueOf(ctx.data.get("_pipeline")),
                    String.valueOf(report.getOrDefault("source_file", ctx.docId)),
                    checks, paths.get("report"));
        } catch (Exception e) {
            return StepResult.fail("复核记录写入失败：" + e.getMessage());
        }

        // 自动放行只对"无阻断项"生效；auto_approve=false（默认）时一律等人看
        if (autoApprove && !"fail".equals(checks.get("verdict"))) {
            try {
                ReviewStore.setStatus(ctx.conn, ctx.docId, ReviewStore.STATUS_APPROVED,
                        "auto_approve：无阻断项，自动放行");
                status = ReviewStore.STATUS_APPROVED;
            } catch (Exception e) {
                return StepResult.fail("复核状态写入失败：" + e.getMessage());
            }
        }

        Map<String, Object> counters = new LinkedHashMap<>();
        counters.put("verdict", checks.get("verdict"));
        counters.put("status", status);
        counters.put("chars", stats.get("chars"));
        counters.put("clean_chars", stats.get("clean_chars"));
        counters.put("clean_removed_ratio", stats.get("clean_removed_ratio"));
        counters.put("pages", stats.get("pages"));
        counters.put("format", stats.get("format"));
        counters.put("images", stats.get("images"));
        counters.put("formulas", stats.get("formulas"));
        counters.put("suspects", stats.get("suspects"));
        counters.put("blocking", ((List<?>) checks.get("blocking")).size());
        counters.put("warn", ((List<?>) checks.get("warn")).size());

        if (!"fail".equals(checks.get("verdict"))) {
            return StepResult.ok(new LinkedHashMap<>(), counters);
        }
        StringBuilder detail = new StringBuilder();
        for (Map<String, Object> b : (List<Map<String, Object>>) checks.get("blocking")) {
            if (detail.length() > 0) {
                detail.append("；");
            }
            detail.append(b.get("code")).append(":").append(b.get("detail"));
        }
        return StepResult.fail("解析质量检查未通过（已落盘待复核）：" + detail, counters);
    }

    private static Map<String, Object> orEmpty(Object o) {
        return o instanceof Map ? (Map<String, Object>) o : new LinkedHashMap<>();
    }
}
