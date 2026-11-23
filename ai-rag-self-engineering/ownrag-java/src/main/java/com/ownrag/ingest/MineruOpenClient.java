package com.ownrag.ingest;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.TimeUnit;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

import com.fasterxml.jackson.databind.JsonNode;
import com.ownrag.util.Json;

import okhttp3.MediaType;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;

/**
 * MinerU 开放平台（mineru.net /api/v4）HTTP 客户端 —— parse_mineru 的 open 模式
 * （Python 版 ingest/mineru_openapi.py 的平移，契约逐行对齐）。
 *
 * 为什么是批量三步流而不是单文件提交（POST /extract/task）：后者只收 URL 不收本地文件。
 * 官方契约（2026-11 核实）：
 *   1. POST /file-urls/batch     → batch_id + 预签名 PUT url（24h 有效）
 *   2. PUT 文件字节到预签名 URL  → 任何附加头（含 Content-Type）都会让 OSS 签名失效返回 403，
 *      也不带 Authorization；上传后平台自动提交解析，无需再调提交接口
 *   3. GET /extract-results/batch/{batch_id} 轮询 → waiting-file|pending|running|converting
 *      为进行中；done → full_zip_url；failed → err_msg
 * 结果 zip：full.md + images/（md 内相对路径引用，须保持同级）+ *_content_list.json 等。
 *
 * 限制：单文件 ≤200MB / ≤200 页，批量 ≤50 个；每日页数额度见控制台（超限 code=-60018）。
 * 错误统一 MineruException：pipeline 层兜底转 StepResult.fail → fallback 链，绝不静默丢文档。
 */
public class MineruOpenClient {

    public static final String API_BASE_DEFAULT = "https://mineru.net/api/v4";
    /** 进行中状态集合（官方口径）；waiting-file = 已申请链接但文件还没被平台扫描到 */
    private static final Set<String> IN_PROGRESS = new HashSet<>(
            Arrays.asList("waiting-file", "pending", "running", "converting"));
    private static final Set<String> IMAGE_EXTS = new HashSet<>(
            Arrays.asList(".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"));

    private static final MediaType JSON_TYPE = MediaType.parse("application/json; charset=utf-8");

    private final OkHttpClient http;

    public MineruOpenClient(OkHttpClient http) {
        this.http = http;
    }

    /** 解析结果（Python 版返回四元组的对象化）。 */
    public static class OpenResult {
        public final String markdown;
        public final Map<String, String> assets;
        public final List<Map<String, Object>> structures;
        public final Map<String, Object> stats;

        public OpenResult(String markdown, Map<String, String> assets,
                          List<Map<String, Object>> structures, Map<String, Object> stats) {
            this.markdown = markdown;
            this.assets = assets;
            this.structures = structures;
            this.stats = stats;
        }
    }

    /** 业务错误统一异常（HTTP 200 + code!=0 也算错误）。 */
    public static class MineruException extends IOException {
        public MineruException(String message) {
            super(message);
        }
    }

    /**
     * 本地 PDF → 开放平台云端解析 → OpenResult。
     * 三步流见类注释；产物落 outDir（full.md + images/），md 内相对图片引用天然可达。
     */
    public OpenResult parseViaOpenapi(Path src, String docId, String baseUrl, String token,
                                      String modelVersion, String lang, boolean isOcr,
                                      boolean enableFormula, boolean enableTable,
                                      double pollInterval, double pollTimeout, Path outDir)
            throws IOException, InterruptedException {
        if (token == null || token.isEmpty()) {
            throw new MineruException(
                    "MINERU_OPEN_TOKEN 未配置：登录 mineru.net → API 管理 → 创建 API Token，设为环境变量 MINERU_OPEN_TOKEN");
        }
        String base = baseUrl == null || baseUrl.isEmpty() ? API_BASE_DEFAULT : baseUrl;
        Files.createDirectories(outDir);

        String batchId = applyUpload(src, base, token, docId, modelVersion, lang, isOcr,
                enableFormula, enableTable);
        Map<String, Object> hit = pollResult(src.getFileName().toString(), docId, base, token,
                batchId, pollInterval, pollTimeout);
        String zipUrl = String.valueOf(hit.get("full_zip_url"));
        downloadExtract(zipUrl, outDir);

        Path mdPath = outDir.resolve("full.md");
        String markdown = Files.exists(mdPath)
                ? new String(Files.readAllBytes(mdPath), StandardCharsets.UTF_8) : "";
        Path imagesDir = outDir.resolve("images");
        Map<String, String> assets = new LinkedHashMap<>();
        if (Files.isDirectory(imagesDir)) {
            try (java.util.stream.Stream<Path> files = Files.list(imagesDir)) {
                files.filter(Files::isRegularFile)
                        .filter(p -> IMAGE_EXTS.contains(ext(p)))
                        .sorted()
                        .forEach(p -> assets.put(stripExt(p), p.toString()));
            }
        }
        List<Map<String, Object>> structures = new ArrayList<>();
        int[] pages = {0};
        structuresFromContentList(outDir, structures, pages);
        Map<String, Object> stats = new LinkedHashMap<>();
        stats.put("pages", pages[0]);
        stats.put("mode", "open");
        stats.put("model_version", modelVersion);
        stats.put("batch_id", batchId);
        return new OpenResult(markdown, assets, structures, stats);
    }

    // -------------------------------------------------- 步骤①②：申请链接 + 上传
    /** 申请预签名 URL 并裸 PUT 上传，返回 batch_id。data_id 用 doc_id 便于结果条目对账。 */
    String applyUpload(Path src, String baseUrl, String token, String docId,
                       String modelVersion, String lang, boolean isOcr,
                       boolean enableFormula, boolean enableTable) throws IOException {
        Map<String, Object> fileEntry = new LinkedHashMap<>();
        fileEntry.put("name", src.getFileName().toString());
        fileEntry.put("is_ocr", isOcr);
        fileEntry.put("data_id", docId);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("model_version", modelVersion);   // pipeline=电子版快 / vlm=扫描件准（与 detect_pages 路由对齐）
        body.put("language", lang);
        body.put("enable_formula", enableFormula);
        body.put("enable_table", enableTable);
        body.put("files", new ArrayList<>(Arrays.asList(fileEntry)));

        Request apply = new Request.Builder()
                .url(baseUrl + "/file-urls/batch")
                .header("Authorization", "Bearer " + token)
                .post(RequestBody.create(Json.write(body), JSON_TYPE))
                .build();
        JsonNode payload;
        try (Response resp = http.newCall(apply).execute()) {
            ensureHttpOk(resp, "开放平台申请上传链接");
            payload = Json.MAPPER.readTree(resp.body().byteStream());
        }
        if (payload.path("code").asInt(0) != 0) {
            throw new MineruException("开放平台申请上传链接失败 code=" + payload.path("code").asInt()
                    + " msg=" + payload.path("msg").asText()
                    + "（code=-60018 通常为每日页额度耗尽）");
        }
        JsonNode data = payload.path("data");
        JsonNode urls = data.path("file_urls");
        if (!urls.isArray() || urls.size() == 0) {
            throw new MineruException("开放平台未返回上传链接（file_urls 空）");
        }
        String putUrl = urls.get(0).asText();

        // 预签名 URL 必须严格裸 PUT：多一个头（哪怕 Content-Type）都是 403。
        // OkHttp 的 RequestBody.create(bytes, null) 不发 Content-Type；Request 不带任何其他头。
        Request put = new Request.Builder()
                .url(putUrl)
                .put(RequestBody.create(Files.readAllBytes(src), (MediaType) null))
                .build();
        try (Response resp = http.newCall(put).execute()) {
            if (!resp.isSuccessful()) {
                throw new MineruException("上传文件到预签名 URL 失败 status=" + resp.code());
            }
        }
        return data.path("batch_id").asText("");
    }

    // -------------------------------------------------- 步骤③：轮询结果
    /** 轮询批量结果直至 done，返回命中条目（含 full_zip_url）。failed / 超时抛 MineruException。 */
    Map<String, Object> pollResult(String srcName, String docId, String baseUrl, String token,
                                   String batchId, double pollInterval, double pollTimeout)
            throws IOException, InterruptedException {
        String url = baseUrl + "/extract-results/batch/" + batchId;
        long deadline = System.nanoTime() + (long) (pollTimeout * 1_000_000_000.0);
        String lastState = null;
        while (true) {
            Request poll = new Request.Builder()
                    .url(url)
                    .header("Authorization", "Bearer " + token)
                    .get()
                    .build();
            JsonNode payload;
            try (Response resp = http.newCall(poll).execute()) {
                ensureHttpOk(resp, "开放平台查询结果");
                payload = Json.MAPPER.readTree(resp.body().byteStream());
            }
            if (payload.path("code").asInt(0) != 0) {
                throw new MineruException("开放平台查询结果失败 code=" + payload.path("code").asInt()
                        + " msg=" + payload.path("msg").asText());
            }
            JsonNode entries = payload.path("data").path("extract_result");
            Map<String, Object> hit = null;
            if (entries.isArray()) {
                // data_id 优先（我们提交时就是 doc_id）；缺失再按文件名对账
                for (JsonNode e : entries) {
                    if (docId.equals(e.path("data_id").asText())) {
                        hit = Json.MAPPER.convertValue(e, new Json.MapType());
                        break;
                    }
                }
                if (hit == null) {
                    for (JsonNode e : entries) {
                        if (srcName.equals(e.path("file_name").asText())) {
                            hit = Json.MAPPER.convertValue(e, new Json.MapType());
                            break;
                        }
                    }
                }
            }
            if (hit == null) {
                if (entries.isArray() && entries.size() > 0) {
                    List<String> names = new ArrayList<>();
                    for (JsonNode e : entries) {
                        names.add(e.path("file_name").asText());
                    }
                    throw new MineruException("批量结果缺本文件条目：batch=" + batchId + " 有 " + names);
                }
                // 空条目 = 上传还没被扫描提交，等下一轮
            } else {
                String state = String.valueOf(hit.getOrDefault("state", ""));
                if ("done".equals(state)) {
                    if (hit.get("full_zip_url") == null || String.valueOf(hit.get("full_zip_url")).isEmpty()) {
                        throw new MineruException("开放平台任务 done 但未返回 full_zip_url");
                    }
                    return hit;
                }
                if ("failed".equals(state)) {
                    String err = hit.get("err_msg") == null ? null : String.valueOf(hit.get("err_msg"));
                    throw new MineruException("开放平台解析失败：" + (err == null || err.isEmpty() ? "未知错误" : err));
                }
                if (!state.equals(lastState)) {  // 只在状态变化时打日志，长轮询不刷屏
                    JsonNode progress = null;
                    for (JsonNode e : entries) {
                        if (docId.equals(e.path("data_id").asText())
                                || srcName.equals(e.path("file_name").asText())) {
                            progress = e.path("extract_progress");
                            break;
                        }
                    }
                    String a = progress == null || !progress.hasNonNull("extracted_pages")
                            ? "?" : String.valueOf(progress.path("extracted_pages").asInt());
                    String b = progress == null || !progress.hasNonNull("total_pages")
                            ? "?" : String.valueOf(progress.path("total_pages").asInt());
                    System.out.println("[MinerU-开放平台] state=" + state + " " + a + "/" + b + " 页（batch="
                            + batchId.substring(0, Math.min(8, batchId.length())) + "…）");
                    lastState = state;
                }
            }
            if (System.nanoTime() >= deadline) {
                throw new MineruException("开放平台解析超时（" + pollTimeout + "s）：batch=" + batchId + " 仍在进行中");
            }
            TimeUnit.MILLISECONDS.sleep((long) (pollInterval * 1000));
        }
    }

    // -------------------------------------------------- 步骤④：结果落地
    /** 流式下载结果 zip 并安全解压（防 zip-slip）；解压后删 zip，full.md 与 images/ 保持同级。 */
    public void downloadExtract(String zipUrl, Path outDir) throws IOException {
        Request download = new Request.Builder().url(zipUrl).get().build();
        Path zipPath = outDir.resolve("result.zip");
        try (Response resp = http.newCall(download).execute()) {
            ensureHttpOk(resp, "下载解析结果 zip");
            try (InputStream in = resp.body().byteStream()) {
                Files.copy(in, zipPath, java.nio.file.StandardCopyOption.REPLACE_EXISTING);
            }
        }
        try (ZipFile zf = new ZipFile(zipPath.toFile())) {
            // 防逃逸基准与目标统一转绝对路径：data-dir 为相对路径时，相对 target 对比绝对 base
            // 恒为 false，会把全部条目静默跳过（实测：zip 有 full.md 但解压 0 个文件）
            Path base = outDir.toAbsolutePath().normalize();
            java.util.Enumeration<? extends ZipEntry> entries = zf.entries();
            while (entries.hasMoreElements()) {
                ZipEntry entry = entries.nextElement();
                String name = entry.getName();
                Path entryPath = java.nio.file.Paths.get(name);
                // 防路径逃逸：正规产物不会长成绝对路径 / 带父级跳转，长了也不放出去
                if (name.startsWith("/") || name.startsWith("\\") || name.contains("..")) {
                    continue;
                }
                if (entry.isDirectory()) {
                    Files.createDirectories(base.resolve(entryPath.toString()));
                    continue;
                }
                Path target = base.resolve(entryPath.toString()).normalize();
                if (!target.startsWith(base)) {
                    continue;
                }
                Files.createDirectories(target.getParent());
                try (InputStream in = zf.getInputStream(entry)) {
                    Files.copy(in, target, java.nio.file.StandardCopyOption.REPLACE_EXISTING);
                }
            }
        }
        Files.delete(zipPath);
    }

    /** 从 *_content_list.json 尽力提取结构清单（image/table）与页数。失败不影响主流程。 */
    static void structuresFromContentList(Path outDir, List<Map<String, Object>> structures, int[] pagesOut) {
        try (java.util.stream.Stream<Path> walk = Files.walk(outDir)) {
            Path cl = walk.filter(p -> p.getFileName().toString().endsWith("_content_list.json"))
                    .findFirst().orElse(null);
            if (cl == null) {
                return;
            }
            JsonNode items = Json.MAPPER.readTree(new String(Files.readAllBytes(cl), StandardCharsets.UTF_8));
            if (!items.isArray()) {
                return;
            }
            int pages = 0;
            for (JsonNode item : items) {
                int pageIdx = item.path("page_idx").asInt(0);
                pages = Math.max(pages, pageIdx + 1);
                String type = item.path("type").asText();
                if ("image".equals(type) && !item.path("img_path").asText("").isEmpty()) {
                    structures.add(ParsedDoc.structure("image", "page:" + pageIdx,
                            item.path("img_path").asText(), null));
                } else if ("table".equals(type)) {
                    String body = item.path("table_body").isMissingNode() ? null : item.path("table_body").asText();
                    structures.add(ParsedDoc.structure("table", "page:" + pageIdx, null, body));
                } else if ("equation".equals(type) || "interline_equation".equals(type)) {
                    // 行间/行内公式：content_list 里带 latex，个别版本只有 text。
                    // 登记进 structures 才能让复核页统计"多少公式"，否则公式数永远为 0。
                    String latex = item.path("latex").asText("");
                    if (latex.isEmpty()) {
                        latex = item.path("text").asText("");
                    }
                    String img = item.path("img_path").asText("");
                    structures.add(ParsedDoc.structure("formula", "page:" + pageIdx,
                            img.isEmpty() ? null : img, latex));
                }
            }
            pagesOut[0] = Math.max(pagesOut[0], pages);
        } catch (Exception ignored) {
            // 结构清单是增益不是依赖：坏 JSON / 缺字段都只损失增强信息
        }
    }

    // -------------------------------------------------- 小工具
    private static void ensureHttpOk(Response resp, String what) throws IOException {
        if (!resp.isSuccessful()) {
            throw new MineruException(what + "失败 status=" + resp.code());
        }
    }

    private static String ext(Path p) {
        String name = p.getFileName().toString();
        int dot = name.lastIndexOf('.');
        return dot < 0 ? "" : name.substring(dot).toLowerCase(Locale.ROOT);
    }

    private static String stripExt(Path p) {
        String name = p.getFileName().toString();
        int dot = name.lastIndexOf('.');
        return dot < 0 ? name : name.substring(0, dot);
    }
}
