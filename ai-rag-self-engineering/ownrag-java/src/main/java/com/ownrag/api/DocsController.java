package com.ownrag.api;

import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import com.ownrag.config.Settings;
import com.ownrag.core.Db;
import com.ownrag.core.PipelineRunner;
import com.ownrag.core.TraceLog;
import com.ownrag.core.TaskStore;
import com.ownrag.index.ChunkStore;
import com.ownrag.util.Ids;

/**
 * 文档接入路由（Python 版 routes_docs.py 的平移）：上传 → 任务表 → 后台执行管道
 * （失败入待办，绝不静默丢文档）。
 */
@RestController
public class DocsController {

    /** 扩展名 → 管道路由键（pipelines.yaml 的 source.accept 同口径）。 */
    private static final Map<String, String> EXT_PIPELINE = new LinkedHashMap<>();
    static {
        EXT_PIPELINE.put(".pdf", "pdf_v1");
        EXT_PIPELINE.put(".mp4", "av_v1");
        EXT_PIPELINE.put(".mkv", "av_v1");
        EXT_PIPELINE.put(".mov", "av_v1");
        EXT_PIPELINE.put(".mp3", "av_v1");
        EXT_PIPELINE.put(".wav", "av_v1");
        EXT_PIPELINE.put(".m4a", "av_v1");
        EXT_PIPELINE.put(".flac", "av_v1");
        EXT_PIPELINE.put(".xlsx", "excel_v1");
        EXT_PIPELINE.put(".xlsm", "excel_v1");
        EXT_PIPELINE.put(".csv", "excel_v1");
        EXT_PIPELINE.put(".md", "md_v1");
        EXT_PIPELINE.put(".markdown", "md_v1");
        EXT_PIPELINE.put(".txt", "txt_v1");
        EXT_PIPELINE.put(".docx", "docx_v1");
    }

    private static final int CHUNK = 1024 * 1024;

    /** 敏感级取值域：public（可外发引用）/ internal（本机可用）/ restricted（仅本机陪练，外发必脱敏）。 */
    static final java.util.Set<String> SENSITIVITY_LEVELS =
            new java.util.LinkedHashSet<>(java.util.Arrays.asList("public", "internal", "restricted"));

    private static void putIfPresent(Map<String, Object> meta, String key, String value) {
        if (value != null && !value.isEmpty()) {
            meta.put(key, value);
        }
    }

    private final Settings settings;
    private final PipelineRunner runner;
    private final TraceLog traceLog;

    public DocsController(Settings settings, PipelineRunner runner, TraceLog traceLog) {
        this.settings = settings;
        this.runner = runner;
        this.traceLog = traceLog;
    }

    /** 分块落盘并计数、顺带算 SHA-256：超限即中止并清理，不留半截文件。 */
    private static int saveUpload(InputStream src, Path dest, int limitBytes,
                                  java.security.MessageDigest digest) throws Exception {
        int total = 0;
        Files.createDirectories(dest.getParent());
        try (java.io.OutputStream out = Files.newOutputStream(dest)) {
            byte[] buf = new byte[CHUNK];
            int n;
            while ((n = src.read(buf)) > 0) {
                total += n;
                if (limitBytes > 0 && total > limitBytes) {
                    throw new ApiError(413, "文件超过上限 " + (limitBytes / (1024 * 1024))
                            + " MB（OWNRAG_MAX_UPLOAD_MB / configs/models.yaml: max_upload_mb）");
                }
                digest.update(buf, 0, n);
                out.write(buf, 0, n);
            }
        }
        return total;
    }

    @PostMapping("/docs/upload")
    public Map<String, Object> upload(@RequestParam("file") MultipartFile file,
                                      @RequestParam(value = "kb", defaultValue = "default") String kb,
                                      @RequestParam(value = "topic", required = false) String topic,
                                      @RequestParam(value = "sensitivity", required = false) String sensitivity,
                                      @RequestParam(value = "doc_date", required = false) String docDate,
                                      @RequestParam(value = "origin", required = false) String origin)
            throws Exception {
        String filename = file.getOriginalFilename() == null ? "" : file.getOriginalFilename();
        String suffix = suffixOf(filename);
        String pipeline = EXT_PIPELINE.get(suffix);
        if (pipeline == null) {
            throw new ApiError(415, "不支持的扩展名 " + suffix + "（支持：" + EXT_PIPELINE.keySet() + "）；"
                    + "新类型 = pipelines.yaml 加一段配置 + 步骤类型注册");
        }
        // kb 白名单：只收 apps.yaml 声明过的库，避免任意字符串落成孤立 collection
        java.util.Set<String> knownKbs = settings.getKnownKbs();
        if (!knownKbs.isEmpty() && !knownKbs.contains(kb)) {
            throw new ApiError(422, "未声明的知识库 '" + kb + "'（apps.yaml knowledge_bases：" + knownKbs + "）");
        }
        // 敏感级白名单：检索过滤的取值域必须收敛，否则过滤条件永远匹配不上
        if (sensitivity != null && !sensitivity.isEmpty()
                && !SENSITIVITY_LEVELS.contains(sensitivity)) {
            throw new ApiError(422, "非法 sensitivity '" + sensitivity + "'（允许：" + SENSITIVITY_LEVELS + "）");
        }

        String docId = Ids.short12();
        String traceId = traceLog.newTraceId();
        Path srcPath = settings.getFilesDir().resolve(docId).resolve("source" + suffix);
        java.security.MessageDigest digest = java.security.MessageDigest.getInstance("SHA-256");
        int size;
        String fileHash;
        try (InputStream in = file.getInputStream()) {
            size = saveUpload(in, srcPath, settings.getMaxUploadMb() * 1024 * 1024, digest);
            fileHash = com.ownrag.util.Hashes.sha256Hex(digest.digest());
        } catch (ApiError e) {
            // 失败上传不留痕迹：连空目录一起清掉
            Files.deleteIfExists(srcPath);
            try {
                Files.deleteIfExists(srcPath.getParent());
            } catch (Exception ignored) {
                // 目录非空（并发上传）不清理
            }
            throw e;
        }

        // ---- 文件级幂等：同 hash 且索引在位 → 直接返回已有 doc（不重灌）----
        try (java.sql.Connection conn = Db.connect(settings.getDbPath())) {
            String existing = com.ownrag.index.FingerprintStore.findDocByFileHash(conn, fileHash);
            if (existing != null && com.ownrag.index.FingerprintStore.hasIndexedChunks(conn, existing)) {
                Map<String, Object> prev = latestTask(conn, existing);
                Map<String, Object> out = new LinkedHashMap<>();
                out.put("doc_id", existing);
                out.put("task_id", prev.get("task_id"));
                out.put("pipeline", pipeline);
                out.put("status", "deduplicated");
                out.put("note", "同内容文件已入库（file_hash 命中），返回已有 doc_id，未产生新索引");
                out.put("size_bytes", size);
                return out;
            }
            // 旧指纹残留但索引已不在位（删除过/管线失败）：清掉旧指纹，按新上传走
            if (existing != null) {
                com.ownrag.index.FingerprintStore.deleteByDoc(conn, existing);
            }
            com.ownrag.index.FingerprintStore.registerFileHash(conn, fileHash, docId, kb,
                    filename.isEmpty() ? srcPath.getFileName().toString() : filename);
            conn.commit();
        }

        Map<String, Object> state = new LinkedHashMap<>();
        state.put("source_path", srcPath.toString());
        Map<String, Object> sourceMeta = new LinkedHashMap<>();
        sourceMeta.put("source_file", filename.isEmpty() ? srcPath.getFileName().toString() : filename);
        sourceMeta.put("size_bytes", size);
        // 个人维度过滤字段随上传进 source_meta → parsed.metadata → chunk.meta → chunks 列
        putIfPresent(sourceMeta, "topic", topic);
        putIfPresent(sourceMeta, "sensitivity", sensitivity);
        putIfPresent(sourceMeta, "doc_date", docDate);
        putIfPresent(sourceMeta, "origin", origin);
        state.put("source_meta", sourceMeta);

        String taskId;
        try (java.sql.Connection conn = Db.connect(settings.getDbPath())) {
            taskId = TaskStore.createTask(conn, docId, pipeline, traceId, kb, state);
        }
        runner.submit(taskId, false);  // 工作线程执行；执行器自带检查点与失败入待办
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("doc_id", docId);
        out.put("task_id", taskId);
        out.put("trace_id", traceId);
        out.put("pipeline", pipeline);
        out.put("size_bytes", size);
        out.put("status", "pending");
        return out;
    }

    /** doc → 最近一次任务（幂等返回时给客户端一个可跟踪的 task_id）。 */
    private static Map<String, Object> latestTask(java.sql.Connection conn, String docId) throws Exception {
        try (java.sql.PreparedStatement ps = conn.prepareStatement(
                "SELECT id, status FROM tasks WHERE doc_id=? ORDER BY created_at DESC LIMIT 1")) {
            ps.setString(1, docId);
            try (java.sql.ResultSet rs = ps.executeQuery()) {
                Map<String, Object> out = new LinkedHashMap<>();
                if (rs.next()) {
                    out.put("task_id", rs.getString("id"));
                    out.put("status", rs.getString("status"));
                }
                return out;
            }
        }
    }

    @GetMapping("/docs/{docId}/status")
    public Map<String, Object> status(@PathVariable String docId) throws Exception {
        try (java.sql.Connection conn = Db.connect(settings.getDbPath())) {
            Map<String, Object> row;
            try (java.sql.PreparedStatement ps = conn.prepareStatement(
                    "SELECT * FROM tasks WHERE doc_id=? ORDER BY created_at DESC LIMIT 1")) {
                ps.setString(1, docId);
                try (java.sql.ResultSet rs = ps.executeQuery()) {
                    row = rs.next() ? TaskStore.rowToMap(rs) : null;
                }
            }
            if (row == null) {
                throw new ApiError(404, "doc 不存在：" + docId);
            }
            List<Map<String, Object>> steps =
                    TraceLog.byTrace(conn, String.valueOf(row.get("trace_id")));
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("task", row);
            out.put("steps", steps);
            return out;
        }
    }

    @DeleteMapping("/docs/{docId}")
    public Map<String, Object> deleteDoc(@PathVariable String docId) throws Exception {
        // 删除文档 = 派生内容全部退出可检索状态（chunks/FTS/向量三通道一次清）
        try (java.sql.Connection conn = Db.connect(settings.getDbPath())) {
            List<String> kbs = new ArrayList<>();
            int removed = 0;
            try (java.sql.PreparedStatement ps = conn.prepareStatement(
                    "SELECT kb, COUNT(*) AS n FROM chunks WHERE doc_id=? GROUP BY kb");
                 java.sql.ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    kbs.add(rs.getString("kb"));
                    removed += rs.getInt("n");
                }
            }
            if (kbs.isEmpty()) {
                throw new ApiError(404, "doc 不存在或无已索引块：" + docId);
            }
            ChunkStore.keywordDeleteDoc(conn, docId);
            ChunkStore.vectorDeleteDoc(conn, docId);
            try (java.sql.PreparedStatement ps = conn.prepareStatement(
                    "DELETE FROM chunks WHERE doc_id=?")) {
                ps.setString(1, docId);
                ps.executeUpdate();
            }
            // 指纹一并释放：同内容文件之后可重新上传入新 doc
            com.ownrag.index.FingerprintStore.deleteByDoc(conn, docId);
            conn.commit();
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("doc_id", docId);
            out.put("chunks_removed", removed);
            out.put("vector", "ok");
            return out;
        }
    }

    @PostMapping("/docs/tasks/{taskId}/retry")
    public Map<String, Object> retry(@PathVariable String taskId) throws Exception {
        // 重跑 = 同一入口 resume：检查点在任务表里，幂等键 doc_id+step
        try (java.sql.Connection conn = Db.connect(settings.getDbPath())) {
            Map<String, Object> task = TaskStore.getTask(conn, taskId);
            if (task == null) {
                throw new ApiError(404, "任务不存在：" + taskId);
            }
        }
        runner.submit(taskId, true);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("task_id", taskId);
        out.put("status", "submitted");
        out.put("note", "已投递后台续跑（检查点续跑）；状态见 /docs/tasks 或 /admin/tasks");
        return out;
    }

    static String suffixOf(String filename) {
        int dot = filename.lastIndexOf('.');
        String suffix = dot < 0 ? "" : filename.substring(dot).toLowerCase();
        if (suffix.isEmpty()) {
            suffix = Paths.get(filename).getFileName().toString().toLowerCase();
        }
        return suffix.startsWith(".") ? suffix : (suffix.contains(".")
                ? suffix.substring(suffix.lastIndexOf('.')) : suffix);
    }
}
