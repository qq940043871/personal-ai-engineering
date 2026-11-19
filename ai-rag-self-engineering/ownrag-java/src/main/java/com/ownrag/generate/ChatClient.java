package com.ownrag.generate;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Consumer;

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
 * chat 客户端分派（Python 版 generate/client.py + openai_client.py + ollama_client.py 的平移）：
 * 按 settings.chatProvider 分派 ollama / openai 兼容端点，同接口同异常。
 *
 * 参数映射：num_ctx 无 openai 对应项不上送——它只是预算侧的装箱口径；num_predict → max_tokens。
 * 思维链不进正文：delta.reasoning_content 直接跳过。
 */
@Component
public class ChatClient {

    private static final MediaType JSON_TYPE = MediaType.parse("application/json; charset=utf-8");

    /** 生成侧统一异常（供应商无关）：调用方统一捕获转 SSE error 事件。 */
    public static class ChatError extends RuntimeException {
        public ChatError(String message) {
            super(message);
        }
    }

    private final OkHttpClient http;

    public ChatClient(OkHttpClient http) {
        this.http = http;
    }

    /**
     * 流式生成：逐 token 回调；连接/模型异常抛 ChatError（调用方转 SSE error，快速失败不吊死）。
     * numCtx / numPredict 可为 null。
     */
    public void chatStream(Settings settings, List<Map<String, Object>> messages, String model,
                           Integer numCtx, double temperature, Integer numPredict,
                           Consumer<String> onToken) {
        if ("openai".equals(settings.getChatProvider())) {
            streamOpenai(settings, messages, model, temperature, numPredict, onToken);
        } else {
            streamOllama(settings, messages, model, numCtx, temperature, numPredict, onToken);
        }
    }

    /** 聚合版：闸门重答、列映射建议等非流式场景用。 */
    public String chat(Settings settings, List<Map<String, Object>> messages, String model,
                       Integer numCtx, double temperature, Integer numPredict) {
        StringBuilder sb = new StringBuilder();
        chatStream(settings, messages, model, numCtx, temperature, numPredict, sb::append);
        return sb.toString();
    }

    // ---- OpenAI 兼容：标准 /chat/completions + SSE 流式 ----
    private void streamOpenai(Settings settings, List<Map<String, Object>> messages, String model,
                              double temperature, Integer numPredict, Consumer<String> onToken) {
        String baseUrl = settings.getChatBaseUrl() == null ? "" : settings.getChatBaseUrl().replaceAll("/+$", "");
        if (baseUrl.isEmpty() || settings.getChatApiKey() == null || settings.getChatApiKey().isEmpty()) {
            throw new ChatError("OPENAI 供应商未配置：OWNRAG_CHAT_BASE_URL / OWNRAG_CHAT_API_KEY 未设置");
        }
        String usedModel = model == null ? settings.getChatModel() : model;
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("model", usedModel);
        payload.put("messages", messages);
        payload.put("stream", true);
        payload.put("temperature", temperature);
        if (numPredict != null && numPredict > 0) {
            payload.put("max_tokens", numPredict);
        }
        Request request = new Request.Builder()
                .url(baseUrl + "/chat/completions")
                .header("Authorization", "Bearer " + settings.getChatApiKey())
                .post(RequestBody.create(Json.write(payload), JSON_TYPE))
                .build();
        try (Response resp = http.newCall(request).execute()) {
            if (!resp.isSuccessful()) {
                throw new ChatError("生成端点返回 HTTP " + resp.code() + "（" + baseUrl + "，模型 " + usedModel + "）");
            }
            try (BufferedReader reader = new BufferedReader(
                    new InputStreamReader(resp.body().byteStream(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null) {
                    line = line.trim();
                    if (!line.startsWith("data:")) {
                        continue; // SSE 注释行 / 事件名行 / 空行一律跳过
                    }
                    String data = line.substring(5).trim();
                    if ("[DONE]".equals(data)) {
                        return;
                    }
                    JsonNode chunk;
                    try {
                        chunk = Json.MAPPER.readTree(data);
                    } catch (IOException e) {
                        throw new ChatError("生成端点响应无法解析：" + truncate(data, 120) + "（" + e.getMessage() + "）");
                    }
                    if (chunk.hasNonNull("error")) {
                        JsonNode err = chunk.path("error");
                        String msg = err.isTextual() ? err.asText()
                                : err.hasNonNull("message") ? err.path("message").asText() : err.toString();
                        throw new ChatError("生成端点返回错误：" + msg);
                    }
                    // 思维链不进正文：delta.reasoning_content 直接跳过
                    JsonNode delta = chunk.path("choices").path(0).path("delta");
                    String piece = delta.hasNonNull("content") ? delta.path("content").asText() : "";
                    if (!piece.isEmpty()) {
                        onToken.accept(piece);
                    }
                }
            }
        } catch (ChatError e) {
            throw e;
        } catch (IOException e) {
            throw new ChatError("生成端点不可达（" + baseUrl + "，模型 " + usedModel + "）：" + e.getMessage());
        }
    }

    // ---- Ollama 原生：/api/chat stream ----
    private void streamOllama(Settings settings, List<Map<String, Object>> messages, String model,
                              Integer numCtx, double temperature, Integer numPredict, Consumer<String> onToken) {
        String baseUrl = settings.getOllamaBaseUrl() == null ? "" : settings.getOllamaBaseUrl().replaceAll("/+$", "");
        String usedModel = model == null ? settings.getChatModel() : model;
        Map<String, Object> options = new LinkedHashMap<>();
        options.put("temperature", temperature);
        if (numCtx != null) {
            options.put("num_ctx", numCtx);
        }
        if (numPredict != null && numPredict > 0) {
            options.put("num_predict", numPredict);
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("model", usedModel);
        payload.put("messages", messages);
        payload.put("stream", true);
        payload.put("options", options);
        Request request = new Request.Builder()
                .url(baseUrl + "/api/chat")
                .post(RequestBody.create(Json.write(payload), JSON_TYPE))
                .build();
        try (Response resp = http.newCall(request).execute()) {
            if (!resp.isSuccessful()) {
                throw new ChatError("Ollama 返回 HTTP " + resp.code() + "（" + baseUrl + "，模型 " + usedModel + "）");
            }
            try (BufferedReader reader = new BufferedReader(
                    new InputStreamReader(resp.body().byteStream(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null) {
                    if (line.trim().isEmpty()) {
                        continue;
                    }
                    JsonNode chunk;
                    try {
                        chunk = Json.MAPPER.readTree(line);
                    } catch (IOException e) {
                        throw new ChatError("Ollama 响应无法解析：" + truncate(line, 120) + "（" + e.getMessage() + "）");
                    }
                    if (chunk.hasNonNull("error")) {
                        throw new ChatError("Ollama 返回错误：" + chunk.path("error").asText());
                    }
                    String piece = chunk.path("message").path("content").asText("");
                    if (!piece.isEmpty()) {
                        onToken.accept(piece);
                    }
                    if (chunk.path("done").asBoolean(false)) {
                        return;
                    }
                }
            }
        } catch (ChatError e) {
            throw e;
        } catch (IOException e) {
            throw new ChatError("Ollama 不可达（" + baseUrl + "，模型 " + usedModel + "）：" + e.getMessage());
        }
    }

    /** 快速失败信息不吊死：长响应体截断进错误消息。 */
    private static String truncate(String s, int max) {
        return s.length() <= max ? s : s.substring(0, max);
    }

    /** messages 构造便捷：role + content 对。 */
    public static List<Map<String, Object>> message(String role, String content) {
        List<Map<String, Object>> out = new ArrayList<>();
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("role", role);
        m.put("content", content);
        out.add(m);
        return out;
    }
}
