package com.ownrag.ingest;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.stream.Stream;

import org.springframework.stereotype.Component;

import com.ownrag.config.PipelineDef;
import com.ownrag.core.Step;
import com.ownrag.core.StepContext;
import com.ownrag.core.StepResult;

import okhttp3.MediaType;
import okhttp3.MultipartBody;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;

/**
 * MinerU 解析 → ParsedDoc（统一中间态）。mode: http | open | cli 同接口
 * （Python 版 ParseMinerU 的平移）。open 模式走云端不抢本地显存，Java 版默认档；
 * 重活失败走 DSL fallback 链，绝不静默丢文档。
 */
@Component
public class ParseMineru implements Step {

    private final OkHttpClient http;

    public ParseMineru(OkHttpClient http) {
        this.http = http;
    }

    @Override
    public String type() {
        return "parse_mineru";
    }

    @Override
    public StepResult run(StepContext ctx, Map<String, Object> params) {
        Path src = Paths.get(String.valueOf(ctx.data.get("source_path")));
        String backend = params.get("backend") == null ? "auto" : String.valueOf(params.get("backend"));
        if ("auto".equals(backend)) {
            Object route = ctx.data.getOrDefault("page_route", "pipeline");
            backend = "vlm".equals(route) ? "vlm" : "pipeline";
        }

        String md;
        Map<String, String> assets = new LinkedHashMap<>();
        List<Map<String, Object>> structures = new ArrayList<>();
        Map<String, Object> stats = new LinkedHashMap<>();
        String mode = ctx.settings.getMineruMode();
        if ("http".equals(mode)) {
            Object[] triple = viaHttp(src, ctx, params);
            md = (String) triple[0];
            @SuppressWarnings("unchecked")
            Map<String, String> httpAssets = (Map<String, String>) triple[1];
            assets.putAll(httpAssets);
            @SuppressWarnings("unchecked")
            Map<String, Object> httpStats = (Map<String, Object>) triple[2];
            stats.putAll(httpStats);
        } else if ("open".equals(mode)) {
            MineruOpenClient client = new MineruOpenClient(http);
            // is_ocr 语义对齐官方 API：vlm 内置视觉理解通常无需显式 OCR，is_ocr 主要对 pipeline 有意义——
            // 仅当页级路由判了扫描件却落回 pipeline 时才默认强制开
            Boolean isOcrParam = params.get("is_ocr") instanceof Boolean ? (Boolean) params.get("is_ocr") : null;
            boolean isOcr = isOcrParam != null ? isOcrParam
                    : "pipeline".equals(backend) && "vlm".equals(ctx.data.get("page_route"));
            MineruOpenClient.OpenResult r;
            try {
                r = client.parseViaOpenapi(src, ctx.docId,
                        ctx.settings.getMineruOpenBaseUrl(),
                        ctx.settings.getMineruOpenToken(),
                        backend,                              // 官方参数名 model_version：pipeline / vlm
                        params.get("lang") == null ? "ch" : String.valueOf(params.get("lang")),
                        isOcr,
                        true,                                 // enable_formula / enable_table 与 Python 默认一致
                        true,
                        params.get("poll_interval") instanceof Number ? ((Number) params.get("poll_interval")).doubleValue() : 5.0,
                        params.get("poll_timeout") instanceof Number ? ((Number) params.get("poll_timeout")).doubleValue() : 3600.0,
                        ctx.settings.getParsedDir().resolve(ctx.docId));
            } catch (Exception e) {
                return StepResult.fail("MinerU 开放平台：" + e.getMessage());
            }
            md = r.markdown;
            assets.putAll(r.assets);
            structures.addAll(r.structures);
            stats.putAll(r.stats);
        } else {
            Object[] cli = viaCli(src, ctx);
            md = (String) cli[0];
            @SuppressWarnings("unchecked")
            Map<String, String> cliAssets = (Map<String, String>) cli[1];
            assets.putAll(cliAssets);
            @SuppressWarnings("unchecked")
            Map<String, Object> cliStats = (Map<String, Object>) cli[2];
            stats.putAll(cliStats);
        }

        if (md == null || md.trim().isEmpty()) {
            Map<String, Object> metrics = new LinkedHashMap<>();
            metrics.put("backend", backend);
            return StepResult.fail("MinerU 产出空 Markdown", metrics);
        }

        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put("source_file", src.getFileName().toString());
        Object sourceMeta = ctx.data.get("source_meta");
        if (sourceMeta instanceof Map) {
            @SuppressWarnings("unchecked")
            Map<String, Object> sm = (Map<String, Object>) sourceMeta;
            metadata.putAll(sm);
        }
        stats.put("backend", backend);
        ParsedDoc doc = new ParsedDoc(ctx.docId, "pdf", md, metadata, structures, assets, stats);
        String[] usable = doc.isUsable(20);
        if (usable[0] == null) {
            Map<String, Object> metrics = new LinkedHashMap<>();
            metrics.put("backend", backend);
            return StepResult.fail("产出不可用：" + usable[1], metrics);
        }
        ctx.data.put("parsed", doc.toMap());
        Map<String, Object> metrics = new LinkedHashMap<>();
        metrics.put("pages", stats.getOrDefault("pages", 0));
        metrics.put("backend", backend);
        return StepResult.ok(new LinkedHashMap<>(), metrics);
    }

    // ---- http 模式：POST 文件，约定返回 JSON {"markdown": "...", "pages": N, "assets": {...}} ----
    private Object[] viaHttp(Path src, StepContext ctx, Map<String, Object> params) {
        String base = ctx.settings.getMineruBaseUrl();
        if (base == null || base.isEmpty()) {
            throw new IllegalStateException("MINERU_MODE=http 但 MINERU_BASE_URL 未配置");
        }
        try {
            RequestBody fileBody = RequestBody.create(Files.readAllBytes(src),
                    MediaType.parse("application/octet-stream"));
            MultipartBody body = new MultipartBody.Builder()
                    .setType(MultipartBody.FORM)
                    .addFormDataPart("file", src.getFileName().toString(), fileBody)
                    .addFormDataPart("backend", String.valueOf(params.getOrDefault("backend", "auto")))
                    .addFormDataPart("lang", String.valueOf(params.getOrDefault("lang", "ch")))
                    .build();
            Request request = new Request.Builder().url(base + "/file_parse").post(body).build();
            try (Response resp = http.newCall(request).execute()) {
                if (!resp.isSuccessful()) {
                    throw new IllegalStateException("MinerU 服务返回 status=" + resp.code());
                }
                com.fasterxml.jackson.databind.JsonNode payload =
                        com.ownrag.util.Json.MAPPER.readTree(resp.body().byteStream());
                Map<String, String> assets = new LinkedHashMap<>();
                if (payload.path("assets").isObject()) {
                    com.fasterxml.jackson.databind.JsonNode assetsNode = payload.path("assets");
                    java.util.Iterator<Map.Entry<String, com.fasterxml.jackson.databind.JsonNode>> it =
                            assetsNode.fields();
                    while (it.hasNext()) {
                        Map.Entry<String, com.fasterxml.jackson.databind.JsonNode> e = it.next();
                        assets.put(e.getKey(), e.getValue().asText());
                    }
                }
                Map<String, Object> stats = new LinkedHashMap<>();
                stats.put("pages", payload.path("pages").asInt(0));
                return new Object[]{payload.path("markdown").asText(""), assets, stats};
            }
        } catch (Exception e) {
            throw new IllegalStateException("MinerU http 解析失败：" + e.getMessage(), e);
        }
    }

    // ---- cli 模式：子进程拉起，读输出目录的 .md ----
    private Object[] viaCli(Path src, StepContext ctx) {
        String cmdName = "mineru";
        File exe = findExecutable(cmdName);
        if (exe == null) {
            throw new IllegalStateException("MinerU CLI 不可用：" + cmdName
                    + " 未安装（可用 pdf 降级链或改 open/http 模式）");
        }
        Path outDir = ctx.settings.getParsedDir().resolve(ctx.docId);
        try {
            Files.createDirectories(outDir);
            ProcessBuilder pb = new ProcessBuilder(
                    exe.getAbsolutePath(), "-p", src.toAbsolutePath().toString(), "-o", outDir.toAbsolutePath().toString());
            pb.redirectErrorStream(true);
            Process proc = pb.start();
            // 显式 UTF-8：Windows 默认按 GBK 解码子进程输出，中文路径/日志会直接抛乱码
            StringBuilder output = new StringBuilder();
            try (java.io.BufferedReader reader = new java.io.BufferedReader(
                    new java.io.InputStreamReader(proc.getInputStream(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null) {
                    if (output.length() < 4000) {
                        output.append(line).append('\n');
                    }
                }
            }
            if (!proc.waitFor(1800, java.util.concurrent.TimeUnit.SECONDS)) {
                proc.destroyForcibly();
                throw new IllegalStateException("MinerU CLI 超时（1800s）");
            }
            if (proc.exitValue() != 0) {
                throw new IllegalStateException("MinerU CLI 失败：" + tail(output.toString(), 300));
            }
            String md = null;
            Map<String, String> assets = new LinkedHashMap<>();
            Map<String, Object> stats = new LinkedHashMap<>();
            try (Stream<Path> walk = Files.walk(outDir)) {
                List<Path> mds = new ArrayList<>();
                walk.filter(p -> p.getFileName().toString().toLowerCase(Locale.ROOT).endsWith(".md"))
                        .sorted().forEach(mds::add);
                if (mds.isEmpty()) {
                    throw new IllegalStateException("MinerU CLI 未产出 Markdown");
                }
                md = new String(Files.readAllBytes(mds.get(0)), StandardCharsets.UTF_8);
                stats.put("pages", mds.size());
            }
            try (Stream<Path> walk = Files.walk(outDir)) {
                walk.filter(Files::isRegularFile)
                        .filter(p -> p.toString().toLowerCase(Locale.ROOT).endsWith(".png")
                                || p.toString().toLowerCase(Locale.ROOT).endsWith(".jpg"))
                        .forEach(p -> assets.put(stripExt(p), p.toString()));
            }
            return new Object[]{md, assets, stats};
        } catch (IllegalStateException e) {
            throw e;
        } catch (Exception e) {
            throw new IllegalStateException("MinerU CLI 执行失败：" + e.getMessage(), e);
        }
    }

    private static File findExecutable(String name) {
        String[] candidates = {name + ".exe", name + ".bat", name + ".cmd", name};
        for (String dir : System.getenv("PATH").split(java.io.File.pathSeparator)) {
            for (String cand : candidates) {
                File f = new File(dir, cand);
                if (f.isFile()) {
                    return f;
                }
            }
        }
        return null;
    }

    private static String stripExt(Path p) {
        String name = p.getFileName().toString();
        int dot = name.lastIndexOf('.');
        return dot < 0 ? name : name.substring(0, dot);
    }

    private static String tail(String s, int max) {
        if (s.length() <= max) {
            return s;
        }
        return s.substring(s.length() - max);
    }
}
