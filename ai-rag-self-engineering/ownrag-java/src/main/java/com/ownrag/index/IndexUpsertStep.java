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
import com.ownrag.util.Json;

/**
 * index_upsert 步骤（Python 版 IndexUpsert 的平移）：三通道写入
 * （chunks 表 + FTS5 + chunk_vectors），replace_by_doc=true 时先删后插（重跑/增量同一条路，天然幂等）。
 */
@Component
public class IndexUpsertStep implements Step {

    @SuppressWarnings("unchecked")
    @Override
    public String type() {
        return "index_upsert";
    }

    @SuppressWarnings("unchecked")
    @Override
    public StepResult run(StepContext ctx, Map<String, Object> params) {
        List<Map<String, Object>> chunks =
                (List<Map<String, Object>>) ctx.data.getOrDefault("chunks", new ArrayList<>());
        if (chunks.isEmpty()) {
            return StepResult.fail("无待索引块");
        }
        boolean replace = !Boolean.FALSE.equals(params.get("replace_by_doc"));
        try {
            if (replace) {
                ChunkStore.keywordDeleteDoc(ctx.conn, ctx.docId);
                ChunkStore.vectorDeleteDoc(ctx.conn, ctx.docId);
                try (java.sql.PreparedStatement ps = ctx.conn.prepareStatement(
                        "DELETE FROM chunks WHERE doc_id=?")) {
                    ps.setString(1, ctx.docId);
                    ps.executeUpdate();
                }
                // 块 hash 同步释放（重灌同 doc 内容可能变化，旧指纹不能残留占坑）
                try (java.sql.PreparedStatement ps = ctx.conn.prepareStatement(
                        "DELETE FROM chunk_hashes WHERE doc_id=?")) {
                    ps.setString(1, ctx.docId);
                    ps.executeUpdate();
                }
            }

            String embedVersion = ctx.settings.getEmbedVersion();
            try (java.sql.PreparedStatement ps = ctx.conn.prepareStatement(
                    "INSERT OR REPLACE INTO chunks(chunk_id, doc_id, kb, source_type, ordinal, text, "
                            + "anchors_json, meta_json, embed_version, sensitivity, topic, doc_date, origin) "
                            + "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)")) {
                for (Map<String, Object> c : chunks) {
                    ps.setString(1, String.valueOf(c.get("chunk_id")));
                    ps.setString(2, String.valueOf(c.get("doc_id")));
                    ps.setString(3, String.valueOf(c.get("kb")));
                    ps.setString(4, String.valueOf(c.get("source_type")));
                    ps.setInt(5, c.get("ordinal") instanceof Number ? ((Number) c.get("ordinal")).intValue() : 0);
                    ps.setString(6, String.valueOf(c.get("text")));
                    ps.setString(7, Json.write(c.get("anchors") == null ? new LinkedHashMap<>() : c.get("anchors")));
                    ps.setString(8, Json.write(c.get("meta") == null ? new LinkedHashMap<>() : c.get("meta")));
                    ps.setString(9, embedVersion);
                    // 个人维度过滤列从 meta 提升：检索期过滤走列，Prompt 不再承担过滤责任
                    Map<String, Object> meta = c.get("meta") instanceof Map
                            ? (Map<String, Object>) c.get("meta") : new LinkedHashMap<String, Object>();
                    ps.setString(10, strOrNull(meta.get("sensitivity")));
                    ps.setString(11, strOrNull(meta.get("topic")));
                    ps.setString(12, strOrNull(meta.get("doc_date")));
                    ps.setString(13, strOrNull(meta.get("origin")));
                    ps.executeUpdate();
                }
            }
            ChunkStore.keywordUpsert(ctx.conn, chunks);
            // 块 hash 登记（review 通过后才到这）：dedupe 只查不写，登记责任在闸门之后
            try (java.sql.PreparedStatement hs = ctx.conn.prepareStatement(
                    "INSERT OR IGNORE INTO chunk_hashes(hash, chunk_id, doc_id) VALUES (?,?,?)")) {
                for (Map<String, Object> c : chunks) {
                    Object hash = c.get("content_hash");
                    if (hash == null) {
                        hash = com.ownrag.util.Hashes.chunkHash(String.valueOf(c.get("text")));
                    }
                    hs.setString(1, String.valueOf(hash));
                    hs.setString(2, String.valueOf(c.get("chunk_id")));
                    hs.setString(3, ctx.docId);
                    hs.executeUpdate();
                }
            }

            boolean vectorsOk = false;
            List<List<Double>> embeddings =
                    (List<List<Double>>) ctx.data.getOrDefault("embeddings", new ArrayList<>());
            if (!embeddings.isEmpty()) {
                if (embeddings.size() != chunks.size()) {
                    return StepResult.fail("向量数与块数不符：" + embeddings.size() + " vs " + chunks.size());
                }
                vectorsOk = ChunkStore.vectorUpsert(ctx.conn, ctx.kb, chunks, embeddings);
            }
            com.ownrag.core.DocumentStore.refreshStats(ctx.conn, ctx.docId);
            ctx.conn.commit();

            Map<String, Object> metrics = new LinkedHashMap<>();
            metrics.put("chunks", chunks.size());
            metrics.put("vector", vectorsOk ? "ok" : "skipped");
            if (Boolean.TRUE.equals(params.get("require_vector")) && !vectorsOk) {
                return StepResult.fail("向量通道不可用且 require_vector=true", metrics);
            }
            return StepResult.ok(new LinkedHashMap<>(), metrics);
        } catch (SQLException e) {
            return StepResult.fail("索引写入失败：" + e.getMessage());
        }
    }

    private static String strOrNull(Object o) {
        if (o == null) {
            return null;
        }
        String s = String.valueOf(o).trim();
        return s.isEmpty() ? null : s;
    }
}
