package com.ownrag.retrieve;

import java.sql.Connection;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.stereotype.Component;

import com.ownrag.config.Settings;
import com.ownrag.index.ChunkStore;
import com.ownrag.index.Embedder;

/**
 * 混合检索（Python 版 retrieve/hybrid.py 的平移）：
 * 先过滤后召回 → 向量+BM25 双路 → RRF 名次融合。
 * RRF 等权起步——没有评测集之前调权重都是猜（评测先行原则）。
 * 候选池宁窄勿宽：宽了就是给模型编造的机会。
 */
@Component
public class HybridSearch {

    private final Embedder embedder;

    public HybridSearch(Embedder embedder) {
        this.embedder = embedder;
    }

    /** 名次融合：score = Σ 1/(k + rank)。不比分数免量纲问题；附各路命中详情。 */
    public static List<Map<String, Object>> rrfFuse(List<List<Map<String, Object>>> resultLists,
                                                    int k, int topN) {
        Map<String, Map<String, Object>> fused = new LinkedHashMap<>();
        for (List<Map<String, Object>> results : resultLists) {
            int rank = 0;
            for (Map<String, Object> r : results) {
                String cid = String.valueOf(r.get("chunk_id"));
                Map<String, Object> entry = fused.computeIfAbsent(cid, key -> {
                    Map<String, Object> e = new LinkedHashMap<>();
                    e.put("chunk_id", key);
                    e.put("doc_id", r.get("doc_id"));
                    e.put("rrf", 0.0);
                    e.put("channels", new ArrayList<Map<String, Object>>());
                    return e;
                });
                entry.put("rrf", (Double) entry.get("rrf") + 1.0 / (k + rank + 1));
                Map<String, Object> ch = new LinkedHashMap<>();
                ch.put("channel", r.get("channel"));
                ch.put("score", r.get("score"));
                @SuppressWarnings("unchecked")
                List<Map<String, Object>> channels = (List<Map<String, Object>>) entry.get("channels");
                channels.add(ch);
                rank++;
            }
        }
        List<Map<String, Object>> ordered = new ArrayList<>(fused.values());
        ordered.sort((a, b) -> Double.compare((Double) b.get("rrf"), (Double) a.get("rrf")));
        return ordered.size() > topN ? new ArrayList<>(ordered.subList(0, topN)) : ordered;
    }

    /**
     * 一次混合检索（String kb 便捷重载，单库）。
     * 返回 {candidates, vector_skipped_reason, channels{bm25,vector}, retrieval_path}。
     */
    public Map<String, Object> search(Connection conn, Settings settings, String kb, String query,
                                      int vectorTopk, int bm25Topk, int topN,
                                      Map<String, Object> metadataFilter) throws SQLException {
        return search(conn, settings, java.util.Collections.singletonList(kb), query,
                vectorTopk, bm25Topk, topN, metadataFilter);
    }

    /**
     * 一次混合检索：metadataFilter 实装（M2 兑现）——先过滤后召回（BM25/向量两路在 SQL 层
     * JOIN chunks 按敏感级/主题/日期过滤），过滤责任不进 Prompt。
     * 返回 {candidates, vector_skipped_reason, channels{bm25,vector}, retrieval_path}。
     */
    public Map<String, Object> search(Connection conn, Settings settings, List<String> kbs, String query,
                                      int vectorTopk, int bm25Topk, int topN,
                                      Map<String, Object> metadataFilter) throws SQLException {
        List<Map<String, Object>> bm25Hits =
                ChunkStore.keywordSearch(conn, kbs, query, bm25Topk, metadataFilter);

        List<Map<String, Object>> vecHits = new ArrayList<>();
        String vectorSkippedReason = null;
        try {
            List<Double> qEmb = embedder.embedQuery(settings, query);
            // 按当前 embed_version 隔离召回：换向量模型后旧向量（同维度、不同空间）不参与混算
            vecHits = ChunkStore.vectorSearch(conn, kbs, ChunkStore.toFloatArray(qEmb), vectorTopk,
                    metadataFilter, settings.getEmbedVersion());
            if (vecHits.isEmpty()) {
                vectorSkippedReason = "向量通道为空（kb 内无 embed_version=" + settings.getEmbedVersion()
                        + " 的向量），BM25 单路；换向量模型后需重建："
                        + "POST /admin/kbs/{kb}/reembed";
            }
        } catch (Embedder.EmbedError e) {
            vectorSkippedReason = "向量召回跳过：" + e.getMessage();
        }

        List<List<Map<String, Object>>> lists = new ArrayList<>();
        lists.add(vecHits);
        lists.add(bm25Hits);
        List<Map<String, Object>> fused = rrfFuse(lists, 60, topN);
        Map<String, Map<String, Object>> chunks =
                ChunkStore.readChunks(conn, idsOf(fused));
        List<Map<String, Object>> candidates = new ArrayList<>();
        for (Map<String, Object> f : fused) {
            Map<String, Object> chunk = chunks.get(String.valueOf(f.get("chunk_id")));
            if (chunk != null) {
                Map<String, Object> merged = new LinkedHashMap<>(f);
                merged.putAll(chunk);
                candidates.add(merged);
            }
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("candidates", candidates);
        out.put("vector_skipped_reason", vectorSkippedReason);
        // 两路原始命中（调试页要看"是哪一路把它捞上来的"，融合后的分数看不出通道贡献）
        Map<String, Object> channels = new LinkedHashMap<>();
        channels.put("bm25", bm25Hits);
        channels.put("vector", vecHits);
        out.put("channels", channels);
        Map<String, Object> path = new LinkedHashMap<>();
        path.put("kb", kbs == null || kbs.isEmpty() ? "default" : String.join(",", kbs));
        path.put("filter", metadataFilter == null || metadataFilter.isEmpty()
                ? null : String.valueOf(metadataFilter));
        path.put("vector_topk", vectorTopk);
        path.put("bm25_topk", bm25Topk);
        path.put("bm25_hits", bm25Hits.size());
        path.put("vector_hits", vecHits.size());
        out.put("retrieval_path", path);
        return out;
    }

    private static List<String> idsOf(List<Map<String, Object>> fused) {
        List<String> ids = new ArrayList<>();
        for (Map<String, Object> f : fused) {
            ids.add(String.valueOf(f.get("chunk_id")));
        }
        return ids;
    }
}
