package com.ownrag.index;

import java.sql.SQLException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.stereotype.Component;

import com.ownrag.core.Step;
import com.ownrag.core.StepContext;
import com.ownrag.core.StepResult;

/**
 * embed 步骤（Python 版 Embed 的平移）：embedding 批量。
 * 后端不可用时：allow_skip=true → 显式降级（embedded=0，BM25 单路，降级写入 trace 与 metric，
 * 检索侧会播报）；false → 任务失败进待办（默认严格）。
 */
@Component
public class EmbedStep implements Step {

    private final Embedder embedder;

    public EmbedStep(Embedder embedder) {
        this.embedder = embedder;
    }

    @Override
    public String type() {
        return "embed";
    }

    @SuppressWarnings("unchecked")
    @Override
    public StepResult run(StepContext ctx, Map<String, Object> params) {
        List<Map<String, Object>> chunks =
                (List<Map<String, Object>>) ctx.data.getOrDefault("chunks", new ArrayList<>());
        if (chunks.isEmpty()) {
            return StepResult.fail("无待向量化块（上游 chunk 步骤缺失？）");
        }
        int batch = params.get("batch") instanceof Number ? ((Number) params.get("batch")).intValue() : 32;
        String model = params.get("model") == null ? null : String.valueOf(params.get("model"));
        List<String> texts = new ArrayList<>();
        for (Map<String, Object> c : chunks) {
            texts.add(String.valueOf(c.get("text")));
        }
        List<List<Double>> embeddings;
        try {
            embeddings = embedder.embedTexts(ctx.settings, texts, batch, model);
        } catch (Embedder.EmbedError e) {
            if (Boolean.TRUE.equals(params.get("allow_skip"))) {
                Map<String, Object> metrics = new LinkedHashMap<>();
                metrics.put("embedded", 0);
                metrics.put("vector", "skipped（关键词单路）");
                metrics.put("note", e.getMessage() == null ? "" : e.getMessage().substring(0, Math.min(200, e.getMessage().length())));
                return StepResult.ok(new LinkedHashMap<>(), metrics);
            }
            return StepResult.fail(e.getMessage());
        }
        ctx.data.put("embeddings", embeddings);
        return StepResult.okMetrics("embedded", embeddings.size(), "model", ctx.settings.getEmbedModel());
    }
}
