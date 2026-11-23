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

import com.ownrag.config.KbWhitelist;
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
    private final com.ownrag.auth.AuthService authService;

    public DocsController(Settings settings, PipelineRunner runner, TraceLog traceLog,
                          com.ownrag.auth.AuthService authService) {
        this.settings = settings;
        this.runner = runner;
        this.traceLog = traceLog;
        this.authService = authService;
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
                                      @RequestParam(value = "origin", required = false) String origin,
                                      @RequestParam(value = "access_level", required = false) String accessLevel,
                                      @RequestParam(value = "embed", defaultValue = "immediate") String embedMode,
                                      javax.servlet.http.HttpServletRequest request)
            throws Exception {
        // embed=deferred：只解析切分入库（资源），向量留空，由「资源」页手动/批量向量化
        boolean embedDeferred = "deferred".equalsIgnoreCase(embedMode);
        boolean loggedIn = authService.currentUser(request) != null;
        // 访问权限白名单：只收 public/protected，未知值直接拒（不猜成 public 蒙混过关）
        String level = com.ownrag.auth.AccessLevel.normalize(accessLevel);
        if (accessLevel != null && !accessLevel.trim().isEmpty()
                && !com.ownrag.auth.AccessLevel.LEVELS.contains(accessLevel.trim().toLowerCase())) {
            throw new ApiError(422, "非法 access_level '" + accessLevel + "'（允许："
                    + com.ownrag.auth.AccessLevel.LEVELS + "）");
        }
        if (com.ownrag.auth.AccessLevel.isProtected(level) && !loggedIn) {
            // 未登录不建"自己都看不到"的文档：否则上传者以为成功，实际检索不到还不知道为什么
            throw new ApiError(403, "未登录不能上传「需登录」级别的文档：请先登录 "
                    + AuthController.loginHint("/ui/ingest") + " ，或改选「公开」");
        }
        String filename = file.getOriginalFilename() == null ? "" : file.getOriginalFilename();
        String suffix = suffixOf(filename);
        String pipeline = EXT_PIPELINE.get(suffix);
        if (pipeline == null) {
            throw new ApiError(415, "不支持的扩展名 " + suffix + "（支持：" + EXT_PIPELINE.keySet() + "）；"
                    + "新类型 = pipelines.yaml 加一段配置 + 步骤类型注册");
        }
        // kb 白名单：只收 apps.yaml 声明过的库，避免任意字符串落成孤立 collection
        java.util.Set<String> knownKbs = KbWhitelist.all(settings);
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
                // 权限沿用已有文档。已登录时按本次选择对齐（重传即改权限，符合直觉）；
                // 未登录时**绝不**改已有权限——否则匿名者重传一份受限文件就能把它拉回公开
                String existingLevel = authService.accessLevelOf(existing);
                String finalLevel = existingLevel;
                boolean levelAligned = false;
                if (loggedIn && !level.equals(existingLevel)) {
                    levelAligned = authService.setAccessLevel(existing, level);
                    if (levelAligned) {
                        finalLevel = level;
                    }
                }
                Map<String, Object> out = new LinkedHashMap<>();
                out.put("doc_id", existing);
                out.put("task_id", prev.get("task_id"));
                out.put("pipeline", pipeline);
                out.put("status", "deduplicated");
                out.put("access_level", finalLevel);
                out.put("note", levelAligned
                        ? "同内容文件已入库（file_hash 命中），返回已有 doc_id；访问权限已按本次选择更新为「"
                          + com.ownrag.auth.AccessLevel.label(finalLevel) + "」"
                        : "同内容文件已入库（file_hash 命中），返回已有 doc_id，未产生新索引；"
                          + "访问权限沿用「" + com.ownrag.auth.AccessLevel.label(finalLevel) + "」"
                          + (com.ownrag.auth.AccessLevel.PROTECTED.equals(finalLevel) && !loggedIn
                          ? "（受限文档需登录后才能改权限）" : ""));
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
        if (embedDeferred) {
            state.put("embed_deferred", Boolean.TRUE);
        }
        Map<String, Object> sourceMeta = new LinkedHashMap<>();
        sourceMeta.put("source_file", filename.isEmpty() ? srcPath.getFileName().toString() : filename);
        sourceMeta.put("size_bytes", size);
        // 个人维度过滤字段随上传进 source_meta → parsed.metadata → chunk.meta → chunks 列
        putIfPresent(sourceMeta, "topic", topic);
        putIfPresent(sourceMeta, "sensitivity", sensitivity);
        putIfPresent(sourceMeta, "doc_date", docDate);
        putIfPresent(sourceMeta, "origin", origin);
        // 访问权限（public | protected）：落 documents.access_level，检索与原件读取都按它过滤
        sourceMeta.put("access_level", level);
        state.put("source_meta", sourceMeta);

        String taskId;
        try (java.sql.Connection conn = Db.connect(settings.getDbPath())) {
            taskId = TaskStore.createTask(conn, docId, pipeline, traceId, kb, state);
            com.ownrag.core.DocumentStore.upsertOnUpload(conn, docId, kb,
                    String.valueOf(sourceMeta.get("source_file")), pipeline, taskId, traceId,
                    fileHash, size, sourceMeta);
        }
        runner.submit(taskId, false);  // 工作线程执行；执行器自带检查点与失败入待办
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("doc_id", docId);
        out.put("task_id", taskId);
        out.put("trace_id", traceId);
        out.put("pipeline", pipeline);
        out.put("size_bytes", size);
        out.put("status", "pending");
        out.put("embed", embedDeferred ? "deferred" : "immediate");
        out.put("access_level", level);
        if (embedDeferred) {
            out.put("note", "资源已入库（仅解析切分，不入向量库）；到「资源」页手动向量化后才会进入检索");
        }
        return out;
    }

    /** doc → 最近一次任务（幂等返回时给客户端一个可跟踪的 task_id）。 */
    private static Map<String, Object> latestTask(java.sql.Connection conn, String docId) throws Exception {
        Map<String, Object> out = new LinkedHashMap<>();
        try (java.sql.PreparedStatement ps = conn.prepareStatement(
                "SELECT id, status FROM tasks WHERE doc_id=? ORDER BY created_at DESC LIMIT 1")) {
            ps.setString(1, docId);
            try (java.sql.ResultSet rs = ps.executeQuery()) {
                if (rs.next()) {
                    out.put("task_id", rs.getString("id"));
                    out.put("status", rs.getString("status"));
                }
            }
        }
        Db.endRead(conn);  // 调用方随后可能写（清旧指纹）
        return out;
    }

    @GetMapping("/docs/{docId}/status")
    public Map<String, Object> status(@PathVariable String docId,
                                      javax.servlet.http.HttpServletRequest request) throws Exception {
        // 任务详情里有文件名与步骤产物：受限文档未登录不给看（明确说"登录后可访问"）
        if (!authService.canRead(docId, authService.currentUser(request) != null)) {
            throw new ApiError(403, com.ownrag.auth.AuthService.deniedMessage(docId));
        }
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
    public Map<String, Object> deleteDoc(@PathVariable String docId,
                                         javax.servlet.http.HttpServletRequest request) throws Exception {
        // 删除是不可逆的：受限文档未登录一律拒绝，不因为"猜到了 doc_id"就放行
        if (!authService.canRead(docId, authService.currentUser(request) != null)) {
            throw new ApiError(403, com.ownrag.auth.AuthService.deniedMessage(docId));
        }
        // 删除文档 = 派生内容全部退出可检索状态（chunks/FTS/向量三通道一次清）
        try (java.sql.Connection conn = Db.connect(settings.getDbPath())) {
            List<String> kbs = new ArrayList<>();
            int removed = 0;
            try (java.sql.PreparedStatement ps = conn.prepareStatement(
                    "SELECT kb, COUNT(*) AS n FROM chunks WHERE doc_id=? GROUP BY kb")) {
                // 参数必须先绑定再执行：此处曾漏绑，doc_id=? 恒为 NULL → 删除接口永远 404（2026-11-21 发现）
                ps.setString(1, docId);
                try (java.sql.ResultSet rs = ps.executeQuery()) {
                    while (rs.next()) {
                        kbs.add(rs.getString("kb"));
                        removed += rs.getInt("n");
                    }
                }
            }
            if (kbs.isEmpty()) {
                throw new ApiError(404, "doc 不存在或无已索引块：" + docId);
            }
            // 上面 SELECT 开了读事务，下面全是删：先收尾，否则并发删/写时撞 BUSY_SNAPSHOT
            Db.endRead(conn);
            ChunkStore.keywordDeleteDoc(conn, docId);
            ChunkStore.vectorDeleteDoc(conn, docId);
            try (java.sql.PreparedStatement ps = conn.prepareStatement(
                    "DELETE FROM chunks WHERE doc_id=?")) {
                ps.setString(1, docId);
                ps.executeUpdate();
            }
            // 指纹与文档实体一并释放：同内容文件之后可重新上传入新 doc
            com.ownrag.index.FingerprintStore.deleteByDoc(conn, docId);
            com.ownrag.core.DocumentStore.delete(conn, docId);
            // Excel 链路的动态 staging 表是第六通道：不在这里清就会留孤儿表
            List<String> stagingDropped = com.ownrag.ingest.StagingStore.dropByDoc(conn, docId);
            conn.commit();
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("doc_id", docId);
            out.put("chunks_removed", removed);
            out.put("staging_tables_dropped", stagingDropped);
            out.put("vector", "ok");
            return out;
        }
    }

    /**
     * 文档启停（与删除相对的"临时下架"）：enabled=0 退出双通道检索（chunks/向量/FTS 全保留），
     * 再置 1 即恢复。用于"这篇先别让分身引用"而不必走不可逆删除。
     */
    @PostMapping("/docs/{docId}/enabled")
    public Map<String, Object> setEnabled(@PathVariable String docId,
                                          @org.springframework.web.bind.annotation.RequestBody
                                                  Map<String, Object> body,
                                          javax.servlet.http.HttpServletRequest request) throws Exception {
        if (!authService.canRead(docId, authService.currentUser(request) != null)) {
            throw new ApiError(403, com.ownrag.auth.AuthService.deniedMessage(docId));
        }
        boolean enabled = !Boolean.FALSE.equals(body.get("enabled"));
        try (java.sql.Connection conn = Db.connect(settings.getDbPath())) {
            try (java.sql.PreparedStatement ps = conn.prepareStatement(
                    "UPDATE documents SET enabled=?, updated_at=datetime('now','localtime') "
                            + "WHERE doc_id=?")) {
                ps.setInt(1, enabled ? 1 : 0);
                ps.setString(2, docId);
                int n = ps.executeUpdate();
                if (n == 0) {
                    throw new ApiError(404, "doc 不存在：" + docId);
                }
            }
            conn.commit();
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("doc_id", docId);
            out.put("enabled", enabled);
            out.put("note", enabled ? "已恢复检索" : "已停用：退出检索，块与向量保留，随时可再启用");
            return out;
        }
    }

    /**
     * 改文档访问权限（public ↔ protected）：落 documents.access_level 一行，
     * 检索双通道 / 原件 / 分块 / 复核四处立即按新权限生效（都按 documents 子查询过滤，无冗余副本）。
     * 需要登录：否则任何人都能把受限文档改成公开，权限形同虚设。
     */
    @PostMapping("/docs/{docId}/access")
    public Map<String, Object> setAccess(@PathVariable String docId,
                                        @org.springframework.web.bind.annotation.RequestBody
                                                Map<String, Object> body,
                                        javax.servlet.http.HttpServletRequest request) throws Exception {
        if (authService.currentUser(request) == null) {
            throw new ApiError(403, "改文档权限需要登录：请先到 "
                    + AuthController.loginHint("/ui/resources") + " 登录");
        }
        Object raw = body == null ? null : body.get("access_level");
        String level = raw == null ? "" : String.valueOf(raw).trim().toLowerCase();
        if (!com.ownrag.auth.AccessLevel.LEVELS.contains(level)) {
            throw new ApiError(422, "非法 access_level '" + raw + "'（允许："
                    + com.ownrag.auth.AccessLevel.LEVELS + "）");
        }
        if (!authService.setAccessLevel(docId, level)) {
            throw new ApiError(404, "doc 不存在或未建档：" + docId);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("doc_id", docId);
        out.put("access_level", level);
        out.put("label", com.ownrag.auth.AccessLevel.label(level));
        out.put("note", com.ownrag.auth.AccessLevel.isProtected(level)
                ? "已设为「需登录」：未登录用户检索不到这篇文档，也不能读它的分块与原件"
                : "已设为「公开」：未登录用户也能检索与访问这篇文档");
        return out;
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
