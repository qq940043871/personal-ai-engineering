package com.ownrag.review;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.stereotype.Component;

import com.ownrag.core.Step;
import com.ownrag.core.StepContext;
import com.ownrag.core.StepResult;

/**
 * prepare_review 步骤（Python 版 PrepareReview 的平移）：
 * 解析 + 切分产物复核：落盘三份工件、跑自动检查、置 pending。
 * 放在 chunk_markdown 之后：复核要能同时看到"解析成了什么"和"切成了什么"。
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
        Map<String, Object> checks = ReviewStore.qualityChecks(parsed, chunks,
                minCharsPerPage, maxChunkTokens, oversizedRatio);
        Map<String, Object> stats = (Map<String, Object>) checks.get("stats");

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

        Map<String, String> paths;
        try {
            paths = ReviewStore.writeArtifacts(ctx.settings.getReviewDir().resolve(ctx.docId),
                    String.valueOf(md), chunks, report);
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
        counters.put("pages", stats.get("pages"));
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
