package com.ownrag.index;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.stereotype.Component;

import com.ownrag.core.Step;
import com.ownrag.core.StepContext;
import com.ownrag.core.StepResult;
import com.ownrag.ingest.ParsedDoc;

/**
 * chunk_markdown 步骤（Python 版 ChunkMarkdown 的平移）：
 * 切分 + 处理版本链（块上留痕管道名与切分参数），重灌后同块可比较新旧口径。
 */
@Component
public class ChunkMarkdownStep implements Step {

    @Override
    public String type() {
        return "chunk_markdown";
    }

    @SuppressWarnings("unchecked")
    @Override
    public StepResult run(StepContext ctx, Map<String, Object> params) {
        Map<String, Object> parsed = (Map<String, Object>) ctx.data.getOrDefault("parsed", new LinkedHashMap<>());
        Object markdown = parsed.get("markdown");
        if (markdown == null || String.valueOf(markdown).isEmpty()) {
            return StepResult.fail("无 parsed.markdown——上游解析步骤缺失或未产出");
        }
        int maxTokens = params.get("max_tokens") instanceof Number ? ((Number) params.get("max_tokens")).intValue() : 512;
        int overlap = params.get("overlap") instanceof Number ? ((Number) params.get("overlap")).intValue() : 64;

        Map<String, Object> baseMeta = asMap(parsed.get("metadata"));
        List<Map<String, Object>> chunks = Chunker.chunkMarkdown(
                String.valueOf(markdown), ctx.docId, ctx.kb,
                parsed.get("source_type") == null ? "unknown" : String.valueOf(parsed.get("source_type")),
                baseMeta, maxTokens, overlap);
        if (chunks.isEmpty()) {
            return StepResult.fail("切分零块");
        }
        // 处理版本链：块上留痕管道名与切分参数（解析侧 split_params 已随 metadata 带入 meta）
        String pipeline = ctx.data.get("_pipeline") == null ? null : String.valueOf(ctx.data.get("_pipeline"));
        for (Map<String, Object> c : chunks) {
            Map<String, Object> meta = asMap(c.get("meta"));
            if (pipeline != null) {
                meta.put("pipeline", pipeline);
            }
            Map<String, Object> chunkerMeta = new LinkedHashMap<>();
            chunkerMeta.put("max_tokens", maxTokens);
            chunkerMeta.put("overlap", overlap);
            meta.put("chunker", chunkerMeta);
        }
        ctx.data.put("chunks", chunks);
        int tables = 0;
        for (Map<String, Object> c : chunks) {
            if (Boolean.TRUE.equals(asMap(c.get("meta")).get("has_table"))) {
                tables++;
            }
        }
        return StepResult.okMetrics("chunks", chunks.size(), "tables", tables);
    }

    private static Map<String, Object> asMap(Object o) {
        return o instanceof Map ? (Map<String, Object>) o : new LinkedHashMap<>();
    }
}
