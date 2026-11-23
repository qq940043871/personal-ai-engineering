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

    /**
     * RAG 通道的统一检索口径：**不吃 Excel 行卡片**（`source_type='excel'`）。
     *
     * 为什么在检索层而不是在迁移脚本里一次性清掉：历史库的行卡片可能还在（迁移漏跑、或从旧备份恢复），
     * 而"让 Excel 明细参与向量召回"本身就是错的——它会抢占召回名额，还会诱导模型从行卡片里抄数字。
     * 清库是清理空间，过滤是保证口径，两件事都要有。目录块（`excel_catalog`）不受影响。
     */
    public static Map<String, Object> ragFilter(Map<String, Object> filter) {
        Map<String, Object> f = new LinkedHashMap<>();
        if (filter != null) {
            f.putAll(filter);
        }
        List<String> exclude = new ArrayList<>();
        Object raw = f.get("source_exclude");
        if (raw instanceof List) {
            for (Object o : (List<?>) raw) {
                if (o != null) {
                    exclude.add(String.valueOf(o));
                }
            }
        } else if (raw != null && !String.valueOf(raw).isEmpty()) {
            exclude.add(String.valueOf(raw));
        }
        if (!exclude.contains("excel")) {
            exclude.add("excel");
        }
        f.put("source_exclude", exclude);
        return f;
    }

    /**
     * 访问权限过滤（登录态的唯一落点）：未登录时追加 `public_only`，已登录原样返回。
     *
     * 与 {@link #ragFilter} 串联使用：`withAccess(ragFilter(req.metadataFilter), loggedIn)`。
     * 放在检索层而不是 Prompt 层：没权限的块**根本不进候选池**，模型不可能引用到它，
     * 也不存在"上下文里塞了一段机密再叮嘱模型别说"这种自欺。
     */
    public static Map<String, Object> withAccess(Map<String, Object> filter, boolean loggedIn) {
        return com.ownrag.auth.AuthService.accessFilter(filter, loggedIn);
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
                        + " 的向量），BM25 单路；修复方式：控制台「知识库」页对该库点「重新嵌入」，"
                        + "或调 POST /admin/kbs/{kb}/reembed";
            }
        } catch (Embedder.EmbedError e) {
            vectorSkippedReason = "向量召回跳过：" + e.getMessage();
        }

        List<List<Map<String, Object>>> lists = new ArrayList<>();
        lists.add(vecHits);
        lists.add(bm25Hits);
        List<Map<String, Object>> fused = rrfFuse(lists, 60, topN);
        // 融合候选 + 两路原始命中的并集一次读回：调试页要看"这块是哪一路捞上来的、正文讲什么"
        java.util.Set<String> allIds = new java.util.LinkedHashSet<>(idsOf(fused));
        for (List<Map<String, Object>> list : lists) {
            for (Map<String, Object> r : list) {
                allIds.add(String.valueOf(r.get("chunk_id")));
            }
        }
        Map<String, Map<String, Object>> chunks =
                ChunkStore.readChunks(conn, new ArrayList<>(allIds));
        enrich(bm25Hits, chunks);
        enrich(vecHits, chunks);
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

    /** 单路命中回填正文/锚点/ordinal：只看分数看不出"捞上来的到底是什么"，调试页要能直接读。 */
    private static void enrich(List<Map<String, Object>> hits,
                               Map<String, Map<String, Object>> chunks) {
        for (Map<String, Object> h : hits) {
            Map<String, Object> chunk = chunks.get(String.valueOf(h.get("chunk_id")));
            if (chunk == null) {
                continue;
            }
            h.put("doc_id", chunk.get("doc_id"));
            h.put("doc_name", chunk.get("doc_name"));
            h.put("ordinal", chunk.get("ordinal"));
            h.put("anchors", chunk.get("anchors"));
            String text = chunk.get("text") == null ? "" : String.valueOf(chunk.get("text"));
            h.put("chars", text.length());
            h.put("preview", text.substring(0, Math.min(200, text.length())));
        }
    }

    private static List<String> idsOf(List<Map<String, Object>> fused) {
        List<String> ids = new ArrayList<>();
        for (Map<String, Object> f : fused) {
            ids.add(String.valueOf(f.get("chunk_id")));
        }
        return ids;
    }
}
