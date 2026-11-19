package com.ownrag.ingest;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

import com.fasterxml.jackson.databind.JsonNode;
import com.ownrag.util.Json;

import okhttp3.MediaType;
import okhttp3.MultipartBody;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;

/**
 * ASR HTTP 客户端（Java 版新增，替代 Python 的进程内 faster-whisper/funasr）：
 * OpenAI 兼容 /audio/transcriptions 契约（verbose_json 携带段时间戳）。
 * base_url 可指向本地 whisper.cpp-server（http://127.0.0.1:8081/v1）
 * 或云端（如 SiliconFlow https://api.siliconflow.cn/v1，SenseVoiceSmall）——两个世界同一契约。
 */
public class AsrClient {

    private static final MediaType OCTET = MediaType.parse("application/octet-stream");

    /** ASR 业务异常。 */
    public static class AsrError extends IOException {
        public AsrError(String message) {
            super(message);
        }
    }

    private final OkHttpClient http;

    public AsrClient(OkHttpClient http) {
        this.http = http;
    }

    /**
     * 转写 wav → 段列表 [{start, end, text, conf}]（秒为单位的 start/end；conf 缺失 = 0.0 不标记）。
     * 未配置服务地址即抛 AsrError（av_v1 失败入待办，绝不静默）。
     * 回退阶梯：① verbose_json（带 segments）② srt 自行解析时间戳
     * ③ 纯文本端点（如 SiliconFlow SenseVoice，只回 {"text":...} 不认 response_format）
     *   → 按句切分 + 按字符占比估算时间戳（近似锚点，调用方必须以 ts_approximated 显式标注）。
     */
    public List<Map<String, Object>> transcribe(String baseUrl, String apiKey, String model,
                                                String language, Path wav, double durationSec)
            throws IOException {
        List<Map<String, Object>> segs = transcribeFormat(baseUrl, apiKey, model, language, wav,
                "verbose_json");
        if (!segs.isEmpty()) {
            return segs;
        }
        segs = transcribeSrt(baseUrl, apiKey, model, language, wav);
        if (!segs.isEmpty()) {
            return segs;
        }
        // ③ 纯文本兜底：整段文本按句切分，时间按字符占比摊到音频时长上（近似，非真实对齐）
        String text = lastPlainJsonText();
        if (text != null && !text.trim().isEmpty() && durationSec > 0) {
            List<Map<String, Object>> approx = synthesizeSegments(text.trim(), durationSec);
            if (!approx.isEmpty()) {
                approximated.set(true);
                return approx;
            }
        }
        return new ArrayList<>();
    }

    /** 纯文本 JSON 的临时承载（transcribeFormat 内缓存；空 = 端点没回 text 字段）。 */
    private final ThreadLocal<String> lastPlainJsonText = new ThreadLocal<>();

    private String lastPlainJsonText() {
        String v = lastPlainJsonText.get();
        lastPlainJsonText.remove();
        return v;
    }

    /** transcribeFormat 末尾记录：端点是否回了纯 text（供 ③ 级兜底取用）。 */
    private void recordPlainText(String text) {
        lastPlainJsonText.set(text);
    }

    /** 时间戳近似标注（调用方读取后写入 trace metric，降级可见）。 */
    private final ThreadLocal<Boolean> approximated = ThreadLocal.withInitial(() -> false);

    public boolean isApproximated() {
        boolean v = approximated.get();
        approximated.remove();
        return v;
    }

    /** 按句切分（。！？；，收口，~20 字/句）+ 按字符占比分配时间。package 可见供单测。 */
    static List<Map<String, Object>> synthesizeSegments(String text, double durationSec) {
        List<String> parts = new ArrayList<>();
        StringBuilder buf = new StringBuilder();
        for (int i = 0; i < text.length(); i++) {
            char ch = text.charAt(i);
            buf.append(ch);
            if ("。！？；".indexOf(ch) >= 0 && buf.length() >= 12) {
                parts.add(buf.toString());
                buf.setLength(0);
            }
        }
        if (buf.length() > 0) {
            if (!parts.isEmpty() && buf.length() < 6) {
                parts.set(parts.size() - 1, parts.get(parts.size() - 1) + buf);
            } else {
                parts.add(buf.toString());
            }
        }
        int totalChars = 0;
        for (String p : parts) {
            totalChars += p.length();
        }
        List<Map<String, Object>> out = new ArrayList<>();
        if (totalChars == 0) {
            return out;
        }
        double t = 0;
        for (String p : parts) {
            double span = durationSec * (double) p.length() / totalChars;
            Map<String, Object> seg = new LinkedHashMap<>();
            seg.put("start", Math.round(t * 100) / 100.0);
            seg.put("end", Math.round((t + span) * 100) / 100.0);
            seg.put("text", p);
            seg.put("conf", 0.0);
            out.add(seg);
            t += span;
        }
        return out;
    }

    private List<Map<String, Object>> transcribeFormat(String baseUrl, String apiKey, String model,
                                                       String language, Path wav, String format)
            throws IOException {
        if (baseUrl == null || baseUrl.isEmpty()) {
            throw new AsrError("ASR 服务未配置：OWNRAG_ASR_BASE_URL 未设置（models.yaml asr.base_url）"
                    + "——可指向本地 whisper.cpp-server 或云端 OpenAI 兼容端点");
        }
        String base = baseUrl.replaceAll("/+$", "");
        MultipartBody.Builder mb = new MultipartBody.Builder()
                .setType(MultipartBody.FORM)
                .addFormDataPart("file", wav.getFileName().toString(),
                        RequestBody.create(Files.readAllBytes(wav), OCTET))
                .addFormDataPart("model", model)
                .addFormDataPart("response_format", format);
        if (language != null && !language.isEmpty()) {
            mb.addFormDataPart("language", language);
        }
        Request.Builder rb = new Request.Builder().url(base + "/audio/transcriptions").post(mb.build());
        if (apiKey != null && !apiKey.isEmpty()) {
            rb.header("Authorization", "Bearer " + apiKey);
        }
        // 长音频转写读超时放宽到 30 分钟（scoped client，不动全局）
        OkHttpClient scoped = http.newBuilder()
                .readTimeout(java.time.Duration.ofMinutes(30)).build();
        try (Response resp = scoped.newCall(rb.build()).execute()) {
            if (!resp.isSuccessful()) {
                throw new AsrError("ASR 端点返回 HTTP " + resp.code() + "（" + base + "）");
            }
            JsonNode root = Json.MAPPER.readTree(resp.body().byteStream());
            recordPlainText(root.path("text").asText(""));
            JsonNode segments = root.path("segments");
            List<Map<String, Object>> out = new ArrayList<>();
            if (segments.isArray()) {
                for (JsonNode s : segments) {
                    String text = s.path("text").asText("").trim();
                    if (text.isEmpty()) {
                        continue;
                    }
                    Map<String, Object> seg = new LinkedHashMap<>();
                    seg.put("start", s.path("start").asDouble(0));
                    seg.put("end", s.path("end").asDouble(0));
                    seg.put("text", text);
                    // conf：OpenAI verbose_json 无置信度 = 0.0（不标记）；avg_logprob 兼容 whisper.cpp
                    double conf = s.hasNonNull("avg_logprob") ? s.path("avg_logprob").asDouble() : 0.0;
                    seg.put("conf", conf);
                    out.add(seg);
                }
            }
            return out;
        }
    }

    /** SRT 解析回退：1\n00:00:01,000 --> 00:00:03,500\n文本 —— 时间戳毫秒精度转秒。 */
    private List<Map<String, Object>> transcribeSrt(String baseUrl, String apiKey, String model,
                                                    String language, Path wav) throws IOException {
        if (baseUrl == null || baseUrl.isEmpty()) {
            throw new AsrError("ASR 服务未配置：OWNRAG_ASR_BASE_URL 未设置（models.yaml asr.base_url）");
        }
        String base = baseUrl.replaceAll("/+$", "");
        MultipartBody.Builder mb = new MultipartBody.Builder()
                .setType(MultipartBody.FORM)
                .addFormDataPart("file", wav.getFileName().toString(),
                        RequestBody.create(Files.readAllBytes(wav), OCTET))
                .addFormDataPart("model", model)
                .addFormDataPart("response_format", "srt");
        if (language != null && !language.isEmpty()) {
            mb.addFormDataPart("language", language);
        }
        Request.Builder rb = new Request.Builder().url(base + "/audio/transcriptions").post(mb.build());
        if (apiKey != null && !apiKey.isEmpty()) {
            rb.header("Authorization", "Bearer " + apiKey);
        }
        OkHttpClient scoped = http.newBuilder()
                .readTimeout(java.time.Duration.ofMinutes(30)).build();
        String srt;
        try (Response resp = scoped.newCall(rb.build()).execute()) {
            if (!resp.isSuccessful()) {
                throw new AsrError("ASR 端点返回 HTTP " + resp.code() + "（" + base + "）");
            }
            srt = resp.body().string();
        }
        List<Map<String, Object>> out = new ArrayList<>();
        java.util.regex.Pattern cue = java.util.regex.Pattern.compile(
                "(\\d{2}):(\\d{2}):(\\d{2})[,.](\\d{3})\\s*-->\\s*(\\d{2}):(\\d{2}):(\\d{2})[,.](\\d{3})");
        String[] lines = srt.replace("\r", "").split("\n");
        for (int i = 0; i < lines.length; i++) {
            java.util.regex.Matcher m = cue.matcher(lines[i]);
            if (!m.find()) {
                continue;
            }
            // 文本 = 时间码行之后的非空行（直到空行）
            StringBuilder text = new StringBuilder();
            for (int j = i + 1; j < lines.length; j++) {
                if (lines[j].trim().isEmpty()) {
                    break;
                }
                if (cue.matcher(lines[j]).find() || lines[j].trim().matches("\\d+")) {
                    continue;
                }
                if (text.length() > 0) {
                    text.append(' ');
                }
                text.append(lines[j].trim());
            }
            if (text.length() == 0) {
                continue;
            }
            Map<String, Object> seg = new LinkedHashMap<>();
            seg.put("start", Integer.parseInt(m.group(1)) * 3600 + Integer.parseInt(m.group(2)) * 60
                    + Integer.parseInt(m.group(3)) + Integer.parseInt(m.group(4)) / 1000.0);
            seg.put("end", Integer.parseInt(m.group(5)) * 3600 + Integer.parseInt(m.group(6)) * 60
                    + Integer.parseInt(m.group(7)) + Integer.parseInt(m.group(8)) / 1000.0);
            seg.put("text", text.toString());
            seg.put("conf", 0.0);
            out.add(seg);
        }
        return out;
    }

    /** 段时间戳格式化：mm:ss（与 Python 版 _fmt_ts 同口径）。 */
    public static String fmtTs(double seconds) {
        int total = (int) seconds;
        return String.format("%02d:%02d", total / 60, total % 60);
    }

    /** 抽帧率解析：'1/60' -> 1/60；解析失败回退默认值。 */
    public static double fpsOf(String raw) {
        try {
            String[] parts = String.valueOf(raw).split("/", 2);
            double num = Double.parseDouble(parts[0]);
            double den = parts.length > 1 ? Double.parseDouble(parts[1]) : 1;
            return num / den;
        } catch (Exception e) {
            return 1.0 / 60;
        }
    }

    /** 进程执行统一封装：UTF-8 读流（Windows GBK 坑），超时即杀。 */
    static ProcessResult runProcess(String[] cmd, long timeoutSeconds) throws IOException, InterruptedException {
        ProcessBuilder pb = new ProcessBuilder(cmd);
        pb.redirectErrorStream(false);
        Process proc = pb.start();
        StringBuilder stdout = new StringBuilder();
        StringBuilder stderr = new StringBuilder();
        Thread outT = drain(proc.getInputStream(), stdout);
        Thread errT = drain(proc.getErrorStream(), stderr);
        boolean finished = proc.waitFor(timeoutSeconds, TimeUnit.SECONDS);
        if (!finished) {
            proc.destroyForcibly();
            throw new IOException("子进程超时（" + timeoutSeconds + "s）：" + cmd[0]);
        }
        outT.join(1000);
        errT.join(1000);
        return new ProcessResult(proc.exitValue(), stdout.toString(), stderr.toString());
    }

    static class ProcessResult {
        final int exitCode;
        final String stdout;
        final String stderr;

        ProcessResult(int exitCode, String stdout, String stderr) {
            this.exitCode = exitCode;
            this.stdout = stdout;
            this.stderr = stderr;
        }
    }

    private static Thread drain(java.io.InputStream in, StringBuilder sink) {
        Thread t = new Thread(() -> {
            try (BufferedReader reader = new BufferedReader(new InputStreamReader(in, StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null && sink.length() < 16_000) {
                    sink.append(line).append('\n');
                }
            } catch (IOException ignored) {
                // 进程结束导致的流关闭属正常
            }
        });
        t.setDaemon(true);
        t.start();
        return t;
    }

    /** ffmpeg/ffprobe 依赖定位：不在 PATH 即抛（安装：winget install ffmpeg）。 */
    static String need(String bin) {
        String[] exts = {".exe", ".bat", ".cmd", ""};
        for (String dir : System.getenv("PATH").split(java.io.File.pathSeparator)) {
            for (String ext : exts) {
                java.io.File f = new java.io.File(dir, bin + ext);
                if (f.isFile()) {
                    return f.getAbsolutePath();
                }
            }
        }
        throw new IllegalStateException("依赖 " + bin + " 不在 PATH（安装 ffmpeg：winget install ffmpeg）");
    }

    /** JSON 字符串安全转义用于 SQL 表名（Excel 链路共用）。 */
    public static String sanitize(String name) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < name.length() && sb.length() < 40; i++) {
            char ch = name.charAt(i);
            boolean keep = (ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z')
                    || ch == '_' || (ch >= '\u4e00' && ch <= '\u9fa5');
            sb.append(keep ? ch : '_');
        }
        String s = sb.toString();
        return s.isEmpty() ? "sheet" : s;
    }
}
