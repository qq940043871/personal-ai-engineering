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
import com.ownrag.util.Hashes;

/**
 * dedupe_chunks 步骤（个人知识库场景新增）：块级跨文档去重。
 * 位置固定在 chunk_markdown 之后、prepare_review 之前——重复块在 embed 前剔除
 * （省嵌入开销），且复核报告能看到剔除结果。
 * 只查不写：hash 登记发生在 index_upsert（review 通过后），reject 的文档不占坑。
 */
@Component
public class DedupeChunksStep implements Step {

    @Override
    public String type() {
        return "dedupe_chunks";
    }

    @SuppressWarnings("unchecked")
    @Override
    public StepResult run(StepContext ctx, Map<String, Object> params) {
        boolean enabled = !Boolean.FALSE.equals(params.get("enabled"));
        List<Map<String, Object>> chunks =
                (List<Map<String, Object>>) ctx.data.getOrDefault("chunks", new ArrayList<>());
        if (chunks.isEmpty()) {
            return StepResult.okMetrics("total", 0);
        }
        if (!enabled) {
            return StepResult.okMetrics("total", chunks.size(), "skipped", 0, "enabled", 0);
        }
        // 同文档内的重复也去：重传时块头+正文全同的块只保留首块
        java.util.Set<String> seenInBatch = new java.util.LinkedHashSet<>();
        List<Map<String, Object>> kept = new ArrayList<>();
        List<String> droppedIds = new ArrayList<>();
        try {
            for (Map<String, Object> c : chunks) {
                String hash = Hashes.chunkHash(String.valueOf(c.get("text")));
                if (seenInBatch.contains(hash) || FingerprintStore.chunkHashExists(ctx.conn, hash)) {
                    droppedIds.add(String.valueOf(c.get("chunk_id")));
                    continue;
                }
                seenInBatch.add(hash);
                c.put("content_hash", hash);  // index_upsert 拿它登记，避免重算
                kept.add(c);
            }
        } catch (Exception e) {
            return StepResult.fail("块去重失败：" + e.getMessage());
        }
        ctx.data.put("chunks", kept);
        Map<String, Object> metrics = new LinkedHashMap<>();
        metrics.put("total", chunks.size());
        metrics.put("kept", kept.size());
        metrics.put("skipped", droppedIds.size());
        return StepResult.ok(new LinkedHashMap<>(), metrics);
    }
}
