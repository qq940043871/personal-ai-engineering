package com.ownrag.retrieve;

import java.io.IOException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.stereotype.Component;

import com.fasterxml.jackson.databind.JsonNode;
import com.ownrag.config.Settings;
import com.ownrag.util.Json;

import okhttp3.MediaType;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;

/**
 * Rerank 适配（Python 版 retrieve/rerank.py 的平移，可选组件）：
 * 无服务时 RRF 顺序兜底；配置了重排后端则重排候选。
 *
 * 三种 provider 同接口（失败降级可见，不拖垮问答）：
 *   service      自建 bge-reranker 服务（/rerank，pairs 协议）
 *   siliconflow  SiliconFlow 云 API（/v1/rerank，BAAI/bge-reranker-v2-m3 免费）——平铺 documents + index 回映
 *   ollama       本地 Ollama：reranker GGUF 经 /api/embed 输出 1 维标量相关性分数，
 *                pair 拼接沿用 bge-reranker 官方约定 `query</s></s>doc`
 */
@Component
public class RerankClient {

    private static final String BGE_PAIR_SEP = "</s></s>";
    private static final String OLLAMA_RERANK_MODEL_DEFAULT = "qllama/bge-reranker-v2-m3";
    private static final MediaType JSON_TYPE = MediaType.parse("application/json; charset=utf-8");

    private final OkHttpClient http;

    public RerankClient(OkHttpClient http) {
        this.http = http;
    }

    /** 重排结果：候选（已按 rerank_score 降序）+ 说明（降级原因等，调用方写进 trace/响应）。 */
    public static class RerankResult {
        public final List<Map<String, Object>> candidates;
        public final String note;

        public RerankResult(List<Map<String, Object>> candidates, String note) {
            this.candidates = candidates;
            this.note = note;
        }
    }

    /** 返回 (重排后的候选, 说明)。无服务时原序返回（rrf 顺序兜底）。 */
    public RerankResult rerank(Settings settings, String query,
                               List<Map<String, Object>> candidates, int topN) {
        String provider = settings.getRerankProvider();
        if ((provider == null || provider.isEmpty())
                && settings.getRerankBaseUrl() != null && !settings.getRerankBaseUrl().isEmpty()) {
            provider = "service";
        }
        if ("siliconflow".equals(provider)) {
            return rerankSiliconflow(settings, query, candidates, topN);
        }
        if ("ollama".equals(provider)) {
            return rerankOllama(settings, query, candidates, topN);
        }
        return rerankService(settings, query, candidates, topN);
    }

    // ---- 自建服务（旧协议：/rerank pairs）----
    RerankResult rerankService(Settings settings, String query,
                               List<Map<String, Object>> candidates, int topN) {
        String base = settings.getRerankBaseUrl() == null ? "" : settings.getRerankBaseUrl();
        if (base.isEmpty()) {
            return new RerankResult(head(candidates, topN), "rerank 未启用，RRF 顺序兜底");
        }
        List<Object> pairs = new ArrayList<>();
        for (Map<String, Object> c : candidates) {
            List<String> pair = new ArrayList<>();
            pair.add(query);
            pair.add(c.get("text") == null ? "" : String.valueOf(c.get("text")));
            pairs.add(pair);
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("query", query);
        body.put("documents", pairs);
        try {
            JsonNode root = postJson(base.replaceAll("/+$", "") + "/rerank", body, null, 60_000);
            JsonNode scores = root.has("scores") ? root.path("scores") : root.path("results");
            for (int i = 0; i < candidates.size() && i < scores.size(); i++) {
                JsonNode s = scores.get(i);
                double score = s.isObject()
                        ? (s.hasNonNull("score") ? s.path("score").asDouble() : s.path("relevance_score").asDouble(0.0))
                        : s.asDouble(0.0);
                candidates.get(i).put("rerank_score", score);
            }
            return new RerankResult(head(sortByRerankScore(candidates), topN), "rerank ok");
        } catch (Exception e) {
            return new RerankResult(head(candidates, topN), "rerank 服务失败已降级：" + e.getMessage());
        }
    }

    // ---- SiliconFlow 云 API：平铺 documents + index 回映 ----
    RerankResult rerankSiliconflow(Settings settings, String query,
                                   List<Map<String, Object>> candidates, int topN) {
        String base = settings.getRerankBaseUrl() == null ? "" : settings.getRerankBaseUrl().replaceAll("/+$", "");
        if (base.isEmpty() || settings.getRerankApiKey() == null || settings.getRerankApiKey().isEmpty()) {
            return new RerankResult(head(candidates, topN),
                    "rerank 未启用（OWNRAG_RERANK_URL / OWNRAG_RERANK_API_KEY 未配置）");
        }
        List<String> docs = new ArrayList<>();
        for (Map<String, Object> c : candidates) {
            docs.add(c.get("text") == null ? "" : String.valueOf(c.get("text")));
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("model", settings.getRerankModel() == null ? "BAAI/bge-reranker-v2-m3" : settings.getRerankModel());
        body.put("query", query);
        body.put("documents", docs);
        body.put("top_n", docs.size());
        body.put("return_documents", false);
        try {
            JsonNode root = postJson(base + "/rerank", body,
                    "Bearer " + settings.getRerankApiKey(), 60_000);
            JsonNode results = root.path("results");
            if (!results.isArray() || results.size() != docs.size()) {
                return new RerankResult(head(candidates, topN),
                        "rerank 返回条数不符（" + (results.isArray() ? results.size() : 0) + "/" + docs.size() + "），已降级");
            }
            // 规范回映：results[].index 对应输入 documents 下标；缺失/异常时退回位置对齐
            boolean indexOk = true;
            for (JsonNode r : results) {
                int idx = r.path("index").asInt(-1);
                if (idx < 0 || idx >= candidates.size()) {
                    indexOk = false;
                    break;
                }
            }
            if (indexOk) {
                for (JsonNode r : results) {
                    candidates.get(r.path("index").asInt())
                            .put("rerank_score", r.path("relevance_score").asDouble(0.0));
                }
            } else {
                for (int i = 0; i < candidates.size() && i < results.size(); i++) {
                    candidates.get(i).put("rerank_score", results.get(i).path("relevance_score").asDouble(0.0));
                }
            }
            return new RerankResult(head(sortByRerankScore(candidates), topN), "rerank ok");
        } catch (Exception e) {
            // rerank 服务挂了不应拖垮问答——降级可见
            return new RerankResult(head(candidates, topN), "rerank 服务失败已降级：" + e.getMessage());
        }
    }

    // ---- Ollama 本地：/api/embed 标量分数 ----
    RerankResult rerankOllama(Settings settings, String query,
                              List<Map<String, Object>> candidates, int topN) {
        String base = settings.getOllamaBaseUrl() == null ? "" : settings.getOllamaBaseUrl().replaceAll("/+$", "");
        if (base.isEmpty()) {
            return new RerankResult(head(candidates, topN), "rerank 未启用（OLLAMA_BASE_URL 未配置）");
        }
        String model = settings.getRerankModel() == null || settings.getRerankModel().isEmpty()
                ? OLLAMA_RERANK_MODEL_DEFAULT : settings.getRerankModel();
        List<String> inputs = new ArrayList<>();
        for (Map<String, Object> c : candidates) {
            String doc = c.get("text") == null ? "" : String.valueOf(c.get("text"));
            inputs.add(query + BGE_PAIR_SEP + doc);
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("model", model);
        body.put("input", inputs);
        try {
            JsonNode root = postJson(base + "/api/embed", body, null, 120_000);
            JsonNode embs = root.path("embeddings");
            if (!embs.isArray() || embs.size() != candidates.size()) {
                return new RerankResult(head(candidates, topN),
                        "rerank 返回条数不符（" + (embs.isArray() ? embs.size() : 0) + "/" + candidates.size() + "），已降级");
            }
            int bad = -1;
            for (JsonNode e : embs) {
                if (e.isArray() && e.size() != 1) {
                    bad = e.size();
                    break;
                }
            }
            if (bad >= 0) {
                return new RerankResult(head(candidates, topN),
                        "rerank 模型输出 " + bad + " 维（期望 1 维标量分数）——该 GGUF 未按 rank pooling 封装，"
                                + "已降级；换 " + model + " 这类 rerank 封装或改用 service/siliconflow 分派");
            }
            for (int i = 0; i < candidates.size(); i++) {
                candidates.get(i).put("rerank_score", embs.get(i).get(0).asDouble());
            }
            return new RerankResult(head(sortByRerankScore(candidates), topN), "rerank ok");
        } catch (Exception e) {
            return new RerankResult(head(candidates, topN), "rerank 服务失败已降级：" + e.getMessage());
        }
    }

    // ---- 小工具 ----

    private JsonNode postJson(String url, Map<String, Object> body, String bearer, long timeoutMs)
            throws IOException {
        Request.Builder rb = new Request.Builder().url(url)
                .post(RequestBody.create(Json.write(body), JSON_TYPE));
        if (bearer != null) {
            rb.header("Authorization", bearer);
        }
        OkHttpClient scoped = http.newBuilder()
                .readTimeout(java.time.Duration.ofMillis(timeoutMs)).build();
        try (Response resp = scoped.newCall(rb.build()).execute()) {
            if (!resp.isSuccessful()) {
                throw new IOException("HTTP " + resp.code());
            }
            return Json.MAPPER.readTree(resp.body().byteStream());
        }
    }

    private static List<Map<String, Object>> sortByRerankScore(List<Map<String, Object>> candidates) {
        List<Map<String, Object>> ordered = new ArrayList<>(candidates);
        ordered.sort((a, b) -> Double.compare(
                b.get("rerank_score") instanceof Number ? ((Number) b.get("rerank_score")).doubleValue() : 0.0,
                a.get("rerank_score") instanceof Number ? ((Number) a.get("rerank_score")).doubleValue() : 0.0));
        return ordered;
    }

    private static List<Map<String, Object>> head(List<Map<String, Object>> candidates, int topN) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (Map<String, Object> c : candidates) {
            if (out.size() >= topN) {
                break;
            }
            out.add(c);
        }
        return out;
    }
}
