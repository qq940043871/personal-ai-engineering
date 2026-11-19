package com.ownrag.api;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.Statement;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.ownrag.config.Settings;
import com.ownrag.core.Db;
import com.ownrag.core.StepRegistry;
import com.ownrag.core.TaskStore;
import com.ownrag.core.TraceLog;
import com.ownrag.index.Embedder;
import com.ownrag.util.Json;

import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;

/**
 * 管理路由（Python 版 routes_admin.py 的平移）：任务/待办/trace/问答日志/健康。
 * 最低观测标准：任何一次"答案不对"，10 分钟内答出——
 * 召回给了什么块、模型看到了什么上下文、闸门放过了什么。
 */
@RestController
public class AdminController {

    private final Settings settings;
    private final StepRegistry registry;
    private final OkHttpClient http;

    public AdminController(Settings settings, StepRegistry registry, OkHttpClient http) {
        this.settings = settings;
        this.registry = registry;
        this.http = http;
    }

    @GetMapping("/admin/tasks")
    public Map<String, Object> listTasks(@RequestParam(defaultValue = "50") int limit) throws Exception {
        try (Connection conn = Db.connect(settings.getDbPath())) {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("tasks", TaskStore.listTasks(conn, limit));
            return out;
        }
    }

    @GetMapping("/admin/todos")
    public Map<String, Object> listTodos(@RequestParam(defaultValue = "true") boolean onlyOpen)
            throws Exception {
        try (Connection conn = Db.connect(settings.getDbPath())) {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("todos", TaskStore.listTodos(conn, onlyOpen));
            return out;
        }
    }

    @PostMapping("/admin/todos/{todoId}/resolve")
    public Map<String, Object> resolveTodo(@PathVariable long todoId) throws Exception {
        // 人工处理完待办后关闭；重跑走 /docs/tasks/{task_id}/retry
        try (Connection conn = Db.connect(settings.getDbPath())) {
            if (!TaskStore.resolveTodo(conn, todoId)) {
                throw new ApiError(404, "待办不存在或已关闭");
            }
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("todo_id", todoId);
            out.put("status", "done");
            return out;
        }
    }

    @GetMapping("/admin/trace/{traceId}")
    public Map<String, Object> getTrace(@PathVariable String traceId) throws Exception {
        try (Connection conn = Db.connect(settings.getDbPath())) {
            List<Map<String, Object>> rows = withCounters(TraceLog.byTrace(conn, traceId));
            if (rows.isEmpty()) {
                throw new ApiError(404, "trace 不存在：" + traceId);
            }
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("trace_id", traceId);
            out.put("steps", rows);
            return out;
        }
    }

    @GetMapping("/admin/qa_log")
    public Map<String, Object> qaLog(@RequestParam(defaultValue = "50") int limit) throws Exception {
        try (Connection conn = Db.connect(settings.getDbPath())) {
            List<Map<String, Object>> rows = new ArrayList<>();
            try (PreparedStatement ps = conn.prepareStatement(
                    "SELECT * FROM qa_log ORDER BY id DESC LIMIT ?")) {
                ps.setInt(1, limit);
                try (ResultSet rs = ps.executeQuery()) {
                    while (rs.next()) {
                        rows.add(TaskStore.rowToMap(rs));
                    }
                }
            }
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("qa_log", rows);
            return out;
        }
    }

    @GetMapping("/admin/metrics")
    public Map<String, Object> metrics() throws Exception {
        // 骨架期聚合口径：全部指标【待实测】，先立分母再谈数字
        try (Connection conn = Db.connect(settings.getDbPath())) {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("tasks_by_status", groupCount(conn,
                    "SELECT status, COUNT(*) n FROM tasks GROUP BY status", "status"));
            out.put("todos_open", scalar(conn, "SELECT COUNT(*) n FROM todos WHERE status='open'"));
            out.put("chunks_by_kb", groupCount(conn,
                    "SELECT kb, COUNT(*) n FROM chunks GROUP BY kb", "kb"));
            out.put("chunks_by_embed_version", groupCount(conn,
                    "SELECT embed_version, COUNT(*) n FROM chunks GROUP BY embed_version", "embed_version"));
            out.put("note", "解析成功率/命中率等业务指标待评测集基线（M2），此处只给运行计数");
            return out;
        }
    }

    @GetMapping("/health")
    public Map<String, Object> alive() {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("service", "ownrag-java");
        out.put("ok", true);
        return out;
    }

    @GetMapping("/admin/health")
    public Map<String, Object> health() throws Exception {
        try (Connection conn = Db.connect(settings.getDbPath())) {
            // DSL 已在启动期校验（StartupCheck）；此处回显注册状态
            Map<String, Object> ollama = new LinkedHashMap<>();
            try {
                Response resp = http.newBuilder().connectTimeout(Duration.ofSeconds(2))
                        .readTimeout(Duration.ofSeconds(2)).build().newCall(
                                new Request.Builder().url(settings.getOllamaBaseUrl() + "/api/tags").build())
                        .execute();
                try (Response r = resp) {
                    ollama.put("ok", r.isSuccessful());
                    ollama.put("detail", r.isSuccessful() ? "" : "HTTP " + r.code());
                }
            } catch (Exception e) {
                ollama.put("ok", false);
                ollama.put("detail", truncate(e.getMessage(), 120));
            }
            // chat 后端按供应商探测：openai = 远程 /models（Bearer）；ollama = 上面的 /api/tags
            Map<String, Object> chatBackend = new LinkedHashMap<>();
            chatBackend.put("provider", settings.getChatProvider());
            chatBackend.put("model", settings.getChatModel());
            chatBackend.put("ok", false);
            chatBackend.put("detail", "");
            if ("openai".equals(settings.getChatProvider())) {
                try {
                    String base = settings.getChatBaseUrl() == null ? ""
                            : settings.getChatBaseUrl().replaceAll("/+$", "");
                    Response resp = http.newBuilder().connectTimeout(Duration.ofSeconds(5))
                            .readTimeout(Duration.ofSeconds(5)).build().newCall(
                                    new Request.Builder().url(base + "/models")
                                            .header("Authorization", "Bearer " + settings.getChatApiKey())
                                            .build()).execute();
                    try (Response r = resp) {
                        chatBackend.put("ok", r.isSuccessful());
                        chatBackend.put("detail", r.isSuccessful() ? "" : "HTTP " + r.code());
                    }
                } catch (Exception e) {
                    chatBackend.put("detail", truncate(e.getMessage(), 120));
                }
            } else {
                chatBackend.put("ok", ollama.get("ok"));
                chatBackend.put("detail", ollama.get("detail"));
            }
            Map<String, Object> embedBackend = new LinkedHashMap<>();
            embedBackend.put("breaker_open", Embedder.breakerOpen());
            embedBackend.put("retry_in", Embedder.breakerRemainingSec());

            Map<String, Object> out = new LinkedHashMap<>();
            out.put("steps_registered", new ArrayList<>(registry.describe().keySet()));
            out.put("pipeline_missing_steps", new ArrayList<>());
            out.put("ollama", ollama);
            out.put("chat_backend", chatBackend);
            out.put("embed_backend", embedBackend);
            out.put("rerank_enabled", settings.getRerankBaseUrl() != null
                    && !settings.getRerankBaseUrl().isEmpty());
            out.put("mineru_mode", settings.getMineruMode());
            out.put("asr_engine", "openai");
            out.put("config_dir", settings.getConfigDir());
            out.put("data_dir", settings.getDataDir().toString());
            out.put("known_kbs", new ArrayList<>(settings.getKnownKbs()));
            Map<String, Object> limits = new LinkedHashMap<>();
            limits.put("max_upload_mb", settings.getMaxUploadMb());
            limits.put("num_ctx", settings.getNumCtx());
            limits.put("max_new_tokens", settings.getMaxNewTokens());
            out.put("limits", limits);
            return out;
        }
    }

    // ---- 小工具 ----

    static List<Map<String, Object>> withCounters(List<Map<String, Object>> rows) {
        for (Map<String, Object> row : rows) {
            Object cj = row.remove("counters_json");
            try {
                row.put("counters", cj == null || String.valueOf(cj).isEmpty()
                        ? new LinkedHashMap<>() : Json.readMap(String.valueOf(cj)));
            } catch (Exception e) {
                row.put("counters", new LinkedHashMap<>());
            }
        }
        return rows;
    }

    private static Map<String, Object> groupCount(Connection conn, String sql, String key)
            throws Exception {
        Map<String, Object> out = new LinkedHashMap<>();
        try (Statement st = conn.createStatement(); ResultSet rs = st.executeQuery(sql)) {
            while (rs.next()) {
                out.put(String.valueOf(rs.getObject(key)), rs.getLong("n"));
            }
        }
        return out;
    }

    private static long scalar(Connection conn, String sql) throws Exception {
        try (Statement st = conn.createStatement(); ResultSet rs = st.executeQuery(sql)) {
            return rs.next() ? rs.getLong(1) : 0;
        }
    }

    private static String truncate(String s, int max) {
        return s == null ? "" : (s.length() <= max ? s : s.substring(0, max));
    }
}
