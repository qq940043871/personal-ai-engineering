package com.ownrag.api;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.ownrag.config.Settings;
import com.ownrag.core.Db;
import com.ownrag.core.PipelineRunner;
import com.ownrag.core.TaskStore;
import com.ownrag.core.TraceLog;
import com.ownrag.review.ReviewStore;
import com.ownrag.util.Json;

/**
 * 解析复核路由（Python 版 routes_review.py 的平移）：把"解析成了什么 / 切成了什么"摆到眼前，
 * 人工点头才入库。
 *
 *   GET  /admin/reviews                 复核队列（按状态过滤，默认全部）
 *   GET  /admin/reviews/{doc_id}        详情：质量检查 + 页级明细 + 产物全文 + 切分预览 + 解析步骤
 *   POST /admin/reviews/{doc_id}/approve 通过 → 记录 approved + 关闭该任务待办 → 自动续跑剩余管道（入库）
 *   POST /admin/reviews/{doc_id}/reject  驳回（必填原因）→ 拒绝入库，关闭待办，任务归 failed
 *
 * 审批与驳回都改状态机，真正拦人的是管道里的 review_gate 步骤——接口本身不"代跑管道逻辑"。
 */
@RestController
public class ReviewController {

    private static final int MD_VIEW_CHARS = 400_000;   // 产物全文单次返回上限

    private final Settings settings;
    private final PipelineRunner runner;
    private final com.ownrag.auth.AuthService authService;

    public ReviewController(Settings settings, PipelineRunner runner,
                            com.ownrag.auth.AuthService authService) {
        this.settings = settings;
        this.runner = runner;
        this.authService = authService;
    }

    public static class NoteBody {
        public String note;
    }

    private static Map<String, Object> rowOut(Map<String, Object> row) {
        Map<String, Object> out = new LinkedHashMap<>();
        for (String k : new String[]{"doc_id", "kb", "task_id", "trace_id", "pipeline",
                "source_file", "backend", "status", "verdict", "pages", "chars", "tables",
                "structures", "format", "images", "formulas", "suspects",
                "note", "reviewed_at", "created_at"}) {
            out.put(k, row.get(k));
        }
        out.put("blocking", parseList(row.get("blocking_json")));
        out.put("warn", parseList(row.get("warn_json")));
        Object docStats = parseObject(row.get("doc_stats_json"));
        out.put("doc_stats", docStats);
        // 老记录没统计过：前端据此显示"未统计"，不拿补列默认的 0 冒充"0 张图/0 个公式"
        out.put("stats_ready", docStats != null);
        return out;
    }

    private static Object parseObject(Object json) {
        if (json == null || String.valueOf(json).isEmpty()) {
            return null;
        }
        try {
            return Json.MAPPER.readValue(String.valueOf(json), Object.class);
        } catch (Exception e) {
            return null;
        }
    }

    @GetMapping("/admin/reviews")
    public Map<String, Object> listReviews(@RequestParam(defaultValue = "") String status,
                                           @RequestParam(defaultValue = "50") int limit,
                                           javax.servlet.http.HttpServletRequest request)
            throws Exception {
        boolean loggedIn = authService.currentUser(request) != null;
        try (Connection conn = Db.connect(settings.getDbPath())) {
            List<Map<String, Object>> rows = ReviewStore.listReviews(conn, status, limit);
            List<Map<String, Object>> items = new ArrayList<>();
            for (Map<String, Object> r : rows) {
                // 队列里含文件名：未登录时不列受限文档（否则"不可检索"却在队列里公开了标题）
                if (!loggedIn && isProtected(conn, String.valueOf(r.get("doc_id")))) {
                    continue;
                }
                items.add(rowOut(r));
            }
            Map<String, Object> counts = new LinkedHashMap<>();
            try (PreparedStatement ps = conn.prepareStatement(
                    "SELECT status, COUNT(*) AS n FROM parse_reviews GROUP BY status");
                 ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    counts.put(rs.getString("status"), rs.getLong("n"));
                }
            }
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("items", items);
            out.put("counts", counts);
            out.put("pending_total", counts.getOrDefault("pending", 0L));
            out.put("public_only", !loggedIn);
            out.put("review_dir", settings.getReviewDir().toString());
            return out;
        }
    }

    /** 未登录时的可见性判断（含"documents 里没这行"的存量数据 → 视为公开）。 */
    private static boolean isProtected(Connection conn, String docId) throws Exception {
        try (PreparedStatement ps = conn.prepareStatement(
                "SELECT access_level FROM documents WHERE doc_id=?")) {
            ps.setString(1, docId);
            try (ResultSet rs = ps.executeQuery()) {
                return rs.next() && com.ownrag.auth.AccessLevel.isProtected(rs.getString(1));
            }
        }
    }

    @GetMapping("/admin/reviews/{docId}")
    public Map<String, Object> reviewDetail(@PathVariable String docId,
                                            @RequestParam(defaultValue = "true") boolean md,
                                            @RequestParam(defaultValue = "0") int offset,
                                            @RequestParam(defaultValue = "400000") int maxChars,
                                            javax.servlet.http.HttpServletRequest request)
            throws Exception {
        // 复核详情就是"原文 + 解析产物 + 清洗后全文"：受限文档未登录一律拒绝
        if (!authService.canRead(docId, authService.currentUser(request) != null)) {
            throw new ApiError(403, com.ownrag.auth.AuthService.deniedMessage(docId));
        }
        Map<String, Object> row;
        Map<String, Object> out;
        try (Connection conn = Db.connect(settings.getDbPath())) {
            row = ReviewStore.getReview(conn, docId);
            if (row == null) {
                throw new ApiError(404, "无复核记录：" + docId);
            }
            out = rowOut(row);
            out.put("pages_detail", parseList(row.get("pages_json")));
            out.put("steps", TraceLog.byTrace(conn,
                    row.get("trace_id") == null ? "" : String.valueOf(row.get("trace_id"))));
            Object taskId = row.get("task_id");
            Map<String, Object> task = taskId == null || String.valueOf(taskId).isEmpty()
                    ? null : TaskStore.getTask(conn, String.valueOf(taskId));
            if (task != null) {
                Map<String, Object> taskBrief = new LinkedHashMap<>();
                taskBrief.put("status", task.get("status"));
                taskBrief.put("error", task.get("error"));
                taskBrief.put("current_step", task.get("current_step"));
                out.put("task", taskBrief);
            } else {
                out.put("task", null);
            }
        }
        Path base = settings.getReviewDir().resolve(docId);
        String reportPath = row.get("report_path") == null || String.valueOf(row.get("report_path")).isEmpty()
                ? base.resolve("report.json").toString() : String.valueOf(row.get("report_path"));
        Object report = readJson(Paths.get(reportPath));
        out.put("report", report);
        if (out.get("doc_stats") == null && report instanceof Map) {
            // 老库没有 doc_stats_json 列值：回退读 report.json，避免历史记录显示"未统计"
            Object ds = ((Map<?, ?>) report).get("doc_stats");
            if (ds == null && ((Map<?, ?>) report).get("checks") instanceof Map) {
                ds = ((Map<?, ?>) ((Map<?, ?>) report).get("checks")).get("doc_stats");
            }
            out.put("doc_stats", ds);
            out.put("stats_ready", ds != null);
        }
        out.put("chunks", readJson(base.resolve("chunks.json")));
        // 原件（三栏对照的第一栏）：只报"能不能看、怎么看"，文件本身走 GET /source/{docId}
        out.put("original", originalInfo(docId, report));
        if (md) {
            int len = Math.max(1, Math.min(maxChars, MD_VIEW_CHARS));
            // 解析后 / 清洗后同一窗口取：字符位置不对齐但顺序一致，翻页与续读口径统一
            putText(out, "markdown", base.resolve("parsed.md"), offset, len);
            putText(out, "cleaned", base.resolve("cleaned.md"), offset, len);
        }
        return out;
    }

    /** 读一份工件并按窗口截取；文件不存在则不写键（前端据此区分"未生成"与"空正文"）。 */
    private static void putText(Map<String, Object> out, String key, Path path, int offset, int len) {
        if (!Files.exists(path)) {
            return;
        }
        try {
            String text = new String(Files.readAllBytes(path), StandardCharsets.UTF_8);
            int off = Math.max(0, Math.min(offset, text.length()));
            out.put(key, text.substring(off, Math.min(off + len, text.length())));
            out.put(key + "_total_chars", text.length());
            out.put(key + "_offset", off);
        } catch (Exception e) {
            out.put(key, null);
        }
    }

    private static final Map<String, String> ORIGINAL_KIND = new LinkedHashMap<>();
    static {
        for (String e : new String[]{"pdf"}) {
            ORIGINAL_KIND.put(e, "pdf");
        }
        for (String e : new String[]{"png", "jpg", "jpeg", "webp", "gif", "bmp", "svg"}) {
            ORIGINAL_KIND.put(e, "image");
        }
        for (String e : new String[]{"mp4", "webm", "mkv", "mov"}) {
            ORIGINAL_KIND.put(e, "video");
        }
        for (String e : new String[]{"mp3", "wav", "m4a", "flac"}) {
            ORIGINAL_KIND.put(e, "audio");
        }
        for (String e : new String[]{"md", "markdown", "txt", "csv"}) {
            ORIGINAL_KIND.put(e, "text");
        }
    }

    /**
     * 原件信息：kind 决定前端怎么渲染（pdf 内嵌 / 图片 / 音视频 / 文本直读 / 二进制给下载）。
     * Word/Excel 浏览器渲染不了——如实标注，让人下载原件对照，而不是在页面上假装能看。
     */
    private Map<String, Object> originalInfo(String docId, Object report) {
        Map<String, Object> out = new LinkedHashMap<>();
        Path src = null;
        Path dir = settings.getFilesDir().resolve(docId).toAbsolutePath().normalize();
        if (Files.isDirectory(dir)) {
            try (java.util.stream.Stream<Path> files = Files.list(dir)) {
                src = files.filter(Files::isRegularFile)
                        .filter(p -> p.getFileName().toString().startsWith("source"))
                        .findFirst().orElse(null);
            } catch (Exception ignored) {
                // 列目录失败同样按"无原件"处理
            }
        }
        if (src == null) {
            out.put("available", false);
            out.put("reason", "原件不在 data/files/" + docId + "（可能已清理）");
            return out;
        }
        String name = src.getFileName().toString();
        int dot = name.lastIndexOf('.');
        String ext = dot < 0 ? "" : name.substring(dot + 1).toLowerCase();
        String kind = ORIGINAL_KIND.get(ext);
        long size = 0;
        try {
            size = Files.size(src);
        } catch (Exception ignored) {
            // 大小读不到不影响查看
        }
        out.put("available", true);
        out.put("ext", ext);
        out.put("kind", kind == null ? "binary" : kind);
        out.put("size_bytes", size);
        out.put("url", "/source/" + docId);
        Object reported = report instanceof Map ? ((Map<?, ?>) report).get("source_file") : null;
        out.put("name", reported == null ? name : String.valueOf(reported));
        return out;
    }

    @PostMapping("/admin/reviews/{docId}/approve")
    public Map<String, Object> approve(@PathVariable String docId,
                                       @RequestBody(required = false) NoteBody body) throws Exception {
        // 通过 → approved + 关闭本任务的待办 → 后台续跑管道（从 review_gate 之后继续，检查点在任务表里）
        String taskId;
        int todosClosed;
        try (Connection conn = Db.connect(settings.getDbPath())) {
            Map<String, Object> row = ReviewStore.getReview(conn, docId);
            if (row == null) {
                throw new ApiError(404, "无复核记录：" + docId);
            }
            String verdict = String.valueOf(row.get("verdict"));
            String blockingJson = row.get("blocking_json") == null ? "[]" : String.valueOf(row.get("blocking_json"));
            if ("fail".equals(verdict)) {
                throw new ApiError(409, "存在阻断项，不能放行：" + blockingJson
                        + "；请换解析后端/修正参数后重传文档");
            }
            String note = body != null && body.note != null && !body.note.isEmpty()
                    ? body.note : "人工复核通过";
            ReviewStore.setStatus(conn, docId, ReviewStore.STATUS_APPROVED, note);
            taskId = row.get("task_id") == null ? null : String.valueOf(row.get("task_id"));
            // 人已经决策过了：这条任务的待办不该继续挂在队列里（否则会出现"任务 done、待办还 open"）
            todosClosed = TaskStore.closeOpenTodos(conn, taskId);
        }
        // 续跑走后台工作线程（PipelineRunner），本接口立即返回审批结果
        String taskStatus = "skipped（无关联任务，可能已入库或来自脚本导入）";
        if (taskId != null && !taskId.isEmpty()) {
            runner.submit(taskId, true);
            taskStatus = "submitted（后台续跑中，状态见 /admin/tasks/" + taskId + "）";
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("doc_id", docId);
        out.put("status", "approved");
        out.put("note", body != null && body.note != null && !body.note.isEmpty() ? body.note : "人工复核通过");
        out.put("task_status", taskStatus);
        out.put("todos_closed", todosClosed);
        return out;
    }

    @PostMapping("/admin/reviews/{docId}/reject")
    public Map<String, Object> reject(@PathVariable String docId, @RequestBody NoteBody body)
            throws Exception {
        // 驳回 → rejected：拒绝入库，并关闭该任务的待办（人工已决策，队列不该残留）
        String note = body == null || body.note == null ? "" : body.note.trim();
        if (note.isEmpty()) {
            throw new ApiError(422, "驳回必须写明原因（会写进待办与复核记录）");
        }
        int closed;
        try (Connection conn = Db.connect(settings.getDbPath())) {
            Map<String, Object> row = ReviewStore.getReview(conn, docId);
            if (row == null) {
                throw new ApiError(404, "无复核记录：" + docId);
            }
            ReviewStore.setStatus(conn, docId, ReviewStore.STATUS_REJECTED, note);
            String taskId = row.get("task_id") == null ? null : String.valueOf(row.get("task_id"));
            closed = TaskStore.closeOpenTodos(conn, taskId);
            // 驳回 = 人工已经判死：任务归 failed（否则会永远挂在"待复核"里当僵尸）
            if (taskId != null && !taskId.isEmpty()) {
                Map<String, Object> fields = new LinkedHashMap<>();
                fields.put("status", TaskStore.STATUS_FAILED);
                fields.put("error", "解析产物已驳回，拒绝入库：" + note);
                TaskStore.updateTask(conn, taskId, fields);
            }
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("doc_id", docId);
        out.put("status", "rejected");
        out.put("note", note);
        out.put("todos_closed", closed);
        return out;
    }

    private static List<Object> parseList(Object json) {
        if (json == null || String.valueOf(json).isEmpty()) {
            return new ArrayList<>();
        }
        try {
            return Json.MAPPER.readValue(String.valueOf(json),
                    Json.MAPPER.getTypeFactory().constructCollectionType(List.class, Object.class));
        } catch (Exception e) {
            return new ArrayList<>();
        }
    }

    private static Object readJson(Path path) {
        if (!Files.exists(path)) {
            return null;
        }
        try {
            return Json.MAPPER.readValue(new String(Files.readAllBytes(path), StandardCharsets.UTF_8),
                    Object.class);
        } catch (Exception e) {
            return null;
        }
    }
}
