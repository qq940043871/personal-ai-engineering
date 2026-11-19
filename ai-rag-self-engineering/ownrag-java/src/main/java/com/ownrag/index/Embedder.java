package com.ownrag.index;

import java.io.IOException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;

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
 * embedding 适配（Python 版 index/embedder.py 的平移，供应商可换）：
 * ollama 原生 /api/embed | OpenAI 兼容 /embeddings。
 *
 * 显式版本：embed_version 与向量兼容性绑定——跨版本向量禁止混用（换供应商/模型 = 换值 = 全量重建索引）。
 * 熔断（breaker）：连接级失败在本机可能耗 2 秒以上；一次问答要付两份代价（直击库 L1 + 混合检索各 embed 一次）。
 * 只对**连接级失败**熔断，4xx/5xx 不熔断——那是配额/配置问题，重试也没用。
 * 指令前缀：Qwen3-Embedding 系 query 侧需 `Instruct: ...\nQuery: ...`，只加 query 侧、文档侧不加。
 */
@Component
public class Embedder {

    public static final double BREAKER_SECONDS = 20.0;   // 熔断窗口：期间直接快速失败，不反复撞墙
    private static final AtomicLong BREAKER_UNTIL = new AtomicLong(0);   // monotonic ms；0 = 闭合

    // Qwen3-Embedding 系官方推荐的任务指令（英文书写）
    public static final String DEFAULT_QUERY_INSTRUCT =
            "Given a search query, retrieve relevant passages that answer the query";

    private static final MediaType JSON_TYPE = MediaType.parse("application/json; charset=utf-8");

    private final OkHttpClient http;

    public Embedder(OkHttpClient http) {
        this.http = http;
    }

    /** 业务异常（Python 版 EmbedError 的对应物）：unchecked，调用方捕获后转 StepResult.fail / 降级。 */
    public static class EmbedError extends RuntimeException {
        public EmbedError(String message) {
            super(message);
        }
    }

    // ---- 熔断状态 ----
    public static boolean breakerOpen() {
        return System.nanoTime() / 1_000_000 < BREAKER_UNTIL.get();
    }

    public static double breakerRemainingSec() {
        return Math.max(0.0, (BREAKER_UNTIL.get() - System.nanoTime() / 1_000_000) / 1000.0);
    }

    /** 测试/运维用：清掉熔断状态（例如刚把后端起起来）。 */
    public static void resetBreaker() {
        BREAKER_UNTIL.set(0);
    }

    private static void tripBreaker() {
        BREAKER_UNTIL.set(System.nanoTime() / 1_000_000 + (long) (BREAKER_SECONDS * 1000));
    }

    /** 文档侧批量向量化：不加指令前缀。按 settings.embedProvider 分派，失败抛 EmbedError。 */
    public List<List<Double>> embedTexts(Settings settings, List<String> texts, int batch, String model) {
        return "openai".equals(settings.getEmbedProvider())
                ? embedTextsOpenai(settings, texts, batch, model)
                : embedTextsOllama(settings, texts, batch, model);
    }

    /** 查询侧单条向量化：指令前缀默认关闭（bge-m3 无此语义）；OWNRAG_EMBED_QUERY_INSTRUCT 开启。 */
    public List<Double> embedQuery(Settings settings, String query) {
        String q = query;
        if ("openai".equals(settings.getEmbedProvider()) && settings.getEmbedQueryInstruct() != null
                && !settings.getEmbedQueryInstruct().isEmpty()) {
            q = "Instruct: " + settings.getEmbedQueryInstruct() + "\nQuery: " + query;
        }
        return embedTexts(settings, java.util.Collections.singletonList(q), 32, null).get(0);
    }

    // ---- ollama 分派：POST {base}/api/embed（原生批量接口） ----
    List<List<Double>> embedTextsOllama(Settings settings, List<String> texts, int batch, String model) {
        String base = settings.getOllamaBaseUrl();
        String m = model == null ? settings.getEmbedModel() : model;
        if (breakerOpen()) {
            throw embedError("embedding 后端不可用（熔断中，" + String.format("%.1f", breakerRemainingSec())
                    + "s 后重试）：" + base);
        }
        List<List<Double>> out = new ArrayList<>();
        for (int i = 0; i < texts.size(); i += batch) {
            List<String> part = texts.subList(i, Math.min(i + batch, texts.size()));
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("model", m);
            body.put("input", part);
            Request request = new Request.Builder()
                    .url(base + "/api/embed")
                    .post(RequestBody.create(Json.write(body), JSON_TYPE))
                    .build();
            JsonNode payload;
            try (Response resp = http.newCall(request).execute()) {
                if (!resp.isSuccessful()) {
                    // 协议/状态码级：不改熔断，属于配置或模型问题
                    throw embedError("Ollama embedding 失败（" + base + "，模型 " + m + "）：HTTP " + resp.code());
                }
                payload = Json.MAPPER.readTree(resp.body().byteStream());
            } catch (EmbedError e) {
                throw e;
            } catch (IOException e) {
                // 连接级：Ollama 没起/网络不通
                tripBreaker();
                throw embedError("Ollama embedding 不可达（" + base + "，模型 " + m + "）：" + e.getMessage());
            }
            JsonNode embs = payload.path("embeddings");
            if (!embs.isArray() || embs.size() != part.size()) {
                throw embedError("embedding 数量不符：请求 " + part.size() + " 返回 "
                        + (embs.isArray() ? embs.size() : 0));
            }
            out.addAll(nodeToVectors(embs));
        }
        return out;
    }

    // ---- openai 兼容分派：POST {base}/embeddings，响应 data[i].embedding 按 index 对齐 ----
    List<List<Double>> embedTextsOpenai(Settings settings, List<String> texts, int batch, String model) {
        String base = settings.getEmbedBaseUrl() == null ? "" : settings.getEmbedBaseUrl().replaceAll("/+$", "");
        if (base.isEmpty() || settings.getEmbedApiKey() == null || settings.getEmbedApiKey().isEmpty()) {
            throw embedError("OPENAI 嵌入供应商未配置：OWNRAG_EMBED_BASE_URL / OWNRAG_EMBED_API_KEY 未设置");
        }
        String m = model == null ? settings.getEmbedModel() : model;
        if (breakerOpen()) {
            throw embedError("embedding 后端不可用（熔断中，" + String.format("%.1f", breakerRemainingSec())
                    + "s 后重试）：" + base);
        }
        List<List<Double>> out = new ArrayList<>();
        for (int i = 0; i < texts.size(); i += batch) {
            List<String> part = texts.subList(i, Math.min(i + batch, texts.size()));
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("model", m);
            body.put("input", part);
            Request request = new Request.Builder()
                    .url(base + "/embeddings")
                    .header("Authorization", "Bearer " + settings.getEmbedApiKey())
                    .post(RequestBody.create(Json.write(body), JSON_TYPE))
                    .build();
            JsonNode payload;
            try (Response resp = http.newCall(request).execute()) {
                if (!resp.isSuccessful()) {
                    int code = resp.code();
                    String hint = code == 429 ? "（速率/额度限制，稍后重试）"
                            : code == 402 ? "（账户余额不足）" : "";
                    throw embedError("嵌入端点返回 HTTP " + code + hint + "（" + base + "，模型 " + m + "）");
                }
                payload = Json.MAPPER.readTree(resp.body().byteStream());
            } catch (EmbedError e) {
                throw e;
            } catch (IOException e) {
                tripBreaker();
                throw embedError("嵌入端点不可达（" + base + "，模型 " + m + "）：" + e.getMessage());
            }
            JsonNode data = payload.path("data");
            if (!data.isArray() || data.size() != part.size()) {
                throw embedError("embedding 数量不符：请求 " + part.size() + " 返回 "
                        + (data.isArray() ? data.size() : 0));
            }
            // 按 index 排序对齐（OpenAI 兼容端点顺序不保证）
            List<int[]> order = new ArrayList<>();
            for (int j = 0; j < data.size(); j++) {
                order.add(new int[]{data.get(j).path("index").asInt(j), j});
            }
            order.sort((a, b) -> Integer.compare(a[0], b[0]));
            for (int[] pair : order) {
                JsonNode emb = data.get(pair[1]).path("embedding");
                List<Double> vec = new ArrayList<>(emb.size());
                for (JsonNode v : emb) {
                    vec.add(v.asDouble());
                }
                out.add(vec);
            }
        }
        return out;
    }

    private static List<List<Double>> nodeToVectors(JsonNode embs) {
        List<List<Double>> out = new ArrayList<>();
        for (JsonNode emb : embs) {
            List<Double> vec = new ArrayList<>(emb.size());
            for (JsonNode v : emb) {
                vec.add(v.asDouble());
            }
            out.add(vec);
        }
        return out;
    }

    /** EmbedError 只经此构造（统一消息构造点），由调用方 throw——编译器可识别确定性抛出路径。 */
    private static EmbedError embedError(String msg) {
        return new EmbedError(msg);
    }

    /** 便捷：等待熔断窗口（供测试与工具用）。 */
    static void sleepMs(long ms) {
        try {
            TimeUnit.MILLISECONDS.sleep(ms);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}
