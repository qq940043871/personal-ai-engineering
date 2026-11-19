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

    public ReviewController(Settings settings, PipelineRunner runner) {
        this.settings = settings;
        this.runner = runner;
    }

    public static class NoteBody {
        public String note;
    }

    private static Map<String, Object> rowOut(Map<String, Object> row) {
        Map<String, Object> out = new LinkedHashMap<>();
        for (String k : new String[]{"doc_id", "kb", "task_id", "trace_id", "pipeline",
                "source_file", "backend", "status", "verdict", "pages", "chars", "tables",
                "structures", "note", "reviewed_at", "created_at"}) {
            out.put(k, row.get(k));
        }
        out.put("blocking", parseList(row.get("blocking_json")));
        out.put("warn", parseList(row.get("warn_json")));
        return out;
    }

    @GetMapping("/admin/reviews")
    public Map<String, Object> listReviews(@RequestParam(defaultValue = "") String status,
                                           @RequestParam(defaultValue = "50") int limit) throws Exception {
        try (Connection conn = Db.connect(settings.getDbPath())) {
            List<Map<String, Object>> rows = ReviewStore.listReviews(conn, status, limit);
            List<Map<String, Object>> items = new ArrayList<>();
            for (Map<String, Object> r : rows) {
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
            out.put("review_dir", settings.getReviewDir().toString());
            return out;
        }
    }

    @GetMapping("/admin/reviews/{docId}")
    public Map<String, Object> reviewDetail(@PathVariable String docId,
                                            @RequestParam(defaultValue = "true") boolean md,
                                            @RequestParam(defaultValue = "0") int offset,
                                            @RequestParam(defaultValue = "400000") int maxChars)
            throws Exception {
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
        out.put("report", readJson(Paths.get(reportPath)));
        out.put("chunks", readJson(base.resolve("chunks.json")));
        if (md) {
            Path mdPath = base.resolve("parsed.md");
            if (Files.exists(mdPath)) {
                String text = new String(Files.readAllBytes(mdPath), StandardCharsets.UTF_8);
                int off = Math.max(0, Math.min(offset, text.length()));
                int len = Math.max(1, Math.min(maxChars, MD_VIEW_CHARS));
                out.put("markdown", text.substring(off, Math.min(off + len, text.length())));
                out.put("markdown_total_chars", text.length());
                out.put("markdown_offset", off);
            }
        }
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
