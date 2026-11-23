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

import com.ownrag.config.KbWhitelist;
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

    /**
     * 启动期预热 chat 探活缓存：否则重启后打开的第一个页面还要等一次跨公网 /models（实测 0.3~1.2s）。
     * 后台线程跑，不阻塞启动；探测失败也只是让首屏徽标显示"不可达"，不影响服务可用性。
     */
    @javax.annotation.PostConstruct
    public void warmUpProbe() {
        refreshChatProbeAsync();
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

    /**
     * 批量关闭待办（可选 reason 前缀过滤）。系统性失败修完后的成批同因待办用这个清，
     * 记录保留（status='done'）只是退出人工队列。body 可省略 = 全清 open 待办。
     */
    @PostMapping("/admin/todos/resolve_all")
    public Map<String, Object> resolveAllTodos(
            @org.springframework.web.bind.annotation.RequestBody(
                    required = false) Map<String, Object> body) throws Exception {
        String reasonPrefix = body == null || body.get("reason_prefix") == null
                ? "" : String.valueOf(body.get("reason_prefix")).trim();
        try (Connection conn = Db.connect(settings.getDbPath())) {
            int n = TaskStore.resolveAllOpenTodos(conn, reasonPrefix);
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("resolved", n);
            out.put("reason_prefix", reasonPrefix.isEmpty() ? null : reasonPrefix);
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
            // 生成后端只有 OpenAI 兼容一种形态：探远端 /models（带 15s 缓存 + 后台单飞刷新）。
            // 不再探本地 Ollama：每个页面 boot() 都先 await 这个接口、前端还 20s 轮询一次，
            // 探一个没装的服务等于每次白等 connectTimeout（曾造成"打开页面停顿 10 秒"）。
            Map<String, Object> chatBackend = new LinkedHashMap<>();
            chatBackend.put("provider", "openai");
            chatBackend.put("model", settings.getChatModel());
            chatBackend.put("ok", false);
            chatBackend.put("detail", "");
            probeChatBackend(chatBackend);
            Map<String, Object> embedBackend = new LinkedHashMap<>();
            embedBackend.put("breaker_open", Embedder.breakerOpen());
            embedBackend.put("retry_in", Embedder.breakerRemainingSec());

            Map<String, Object> out = new LinkedHashMap<>();
            out.put("steps_registered", new ArrayList<>(registry.describe().keySet()));
            out.put("pipeline_missing_steps", new ArrayList<>());
            out.put("chat_backend", chatBackend);
            out.put("embed_backend", embedBackend);
            out.put("rerank_enabled", settings.getRerankBaseUrl() != null
                    && !settings.getRerankBaseUrl().isEmpty());
            out.put("mineru_mode", settings.getMineruMode());
            out.put("asr_engine", "openai");
            out.put("config_dir", settings.getConfigDir());
            out.put("data_dir", settings.getDataDir().toString());
            out.put("known_kbs", new ArrayList<>(KbWhitelist.all(settings)));
            Map<String, Object> limits = new LinkedHashMap<>();
            limits.put("max_upload_mb", settings.getMaxUploadMb());
            limits.put("num_ctx", settings.getNumCtx());
            limits.put("max_new_tokens", settings.getMaxNewTokens());
            out.put("limits", limits);
            return out;
        }
    }

    /** 远端 chat 探活结果的短缓存：/admin/health 是每个页面 boot() 的第一个请求，前端还 20s 轮询一次。 */
    private static final long CHAT_PROBE_TTL_MS = 15_000;
    private static volatile long chatProbeAt = 0L;
    private static volatile boolean chatProbeOk = false;
    private static volatile String chatProbeDetail = "";
    private static volatile boolean chatProbeRunning = false;

    /**
     * 探测远端 chat 后端（OpenAI 兼容 /models）。
     *
     * 为什么不能每次请求都探：每个页面 boot() 的第一个请求就是 /admin/health，前端还 20s 轮询一次；
     * 跨公网一次 /models 实测 300ms~1.2s，直接拖慢首屏。策略：
     *   ① 进程内首次调用同步探一次（别让首屏永远显示"不可达"）；
     *   ② 之后只在超过 {@value #CHAT_PROBE_TTL_MS}ms 时**后台**刷新，请求永远拿缓存立即返回。
     * 真实可用性由问答链路自己暴露（chat 报错会带 HTTP 码与端点）。
     */
    private void probeChatBackend(Map<String, Object> chatBackend) {
        boolean never = chatProbeAt == 0L;
        if (never) {
            runChatProbe();
        } else if (System.currentTimeMillis() - chatProbeAt > CHAT_PROBE_TTL_MS) {
            refreshChatProbeAsync();
        }
        chatBackend.put("ok", chatProbeOk);
        chatBackend.put("detail", chatProbeDetail);
        chatBackend.put("cached", !never);
    }

    private void runChatProbe() {
        boolean ok = false;
        String detail = "";
        try {
            String base = settings.getChatBaseUrl() == null ? ""
                    : settings.getChatBaseUrl().replaceAll("/+$", "");
            Response resp = http.newBuilder().connectTimeout(Duration.ofSeconds(3))
                    .readTimeout(Duration.ofSeconds(3)).build().newCall(
                            new Request.Builder().url(base + "/models")
                                    .header("Authorization", "Bearer " + settings.getChatApiKey())
                                    .build()).execute();
            try (Response r = resp) {
                ok = r.isSuccessful();
                detail = ok ? "" : "HTTP " + r.code();
            }
        } catch (Exception e) {
            detail = truncate(e.getMessage(), 120);
        }
        chatProbeOk = ok;
        chatProbeDetail = detail;
        chatProbeAt = System.currentTimeMillis();
    }

    /** 单飞后台刷新：并发轮询不会堆出一串探测请求。 */
    private void refreshChatProbeAsync() {
        if (chatProbeRunning) {
            return;
        }
        chatProbeRunning = true;
        Thread t = new Thread(() -> {
            try {
                runChatProbe();
            } finally {
                chatProbeRunning = false;
            }
        }, "chat-probe");
        t.setDaemon(true);
        t.start();
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
