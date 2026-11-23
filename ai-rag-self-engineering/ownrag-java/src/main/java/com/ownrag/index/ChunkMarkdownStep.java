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
 *
 * 切分输入是**清洗后正文**（CleanMarkdown + clean_markdown 步骤归一化的参数），不是解析原样：
 * 页标记/页码行/页尾空白这类噪声会污染嵌入与 FTS 切词，进块之前清掉。
 * 清洗是纯函数，这里现算而不是从黑板读全文——state_json 不该再存一份文档正文。
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
        // 管线里 clean_markdown 归一化过的参数优先；没有该步骤（老任务续跑/单测直调）时用默认口径
        CleanMarkdown.Result cleaned = CleanMarkdown.apply(String.valueOf(markdown), asMap(ctx.data.get("clean_options")));
        String cleanText = cleaned.markdown.trim().isEmpty() ? String.valueOf(markdown) : cleaned.markdown;
        List<Map<String, Object>> chunks = Chunker.chunkMarkdown(
                cleanText, ctx.docId, ctx.kb,
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
        return StepResult.okMetrics("chunks", chunks.size(), "tables", tables,
                "clean_chars", cleanText.length(), "clean_removed_ratio", cleaned.stats.get("removed_ratio"));
    }

    private static Map<String, Object> asMap(Object o) {
        return o instanceof Map ? (Map<String, Object>) o : new LinkedHashMap<>();
    }
}
