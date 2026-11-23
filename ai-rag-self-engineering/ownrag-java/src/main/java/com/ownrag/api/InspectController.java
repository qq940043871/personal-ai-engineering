package com.ownrag.api;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.ownrag.config.AppDef;
import com.ownrag.config.KbWhitelist;
import com.ownrag.config.Settings;
import com.ownrag.core.Db;
import com.ownrag.core.TaskStore;
import com.ownrag.core.TraceLog;
import com.ownrag.generate.Budget;
import com.ownrag.generate.Gates;
import com.ownrag.index.ChunkStore;
import com.ownrag.retrieve.DirectHit;
import com.ownrag.retrieve.HybridSearch;
import com.ownrag.retrieve.QueryRewriter;
import com.ownrag.retrieve.RerankClient;
import com.ownrag.router.QueryRouter;
import com.ownrag.router.RouteResult;
import com.ownrag.router.TableCatalog;
import com.ownrag.util.Ids;
import com.ownrag.util.Json;

/**
 * 调试/巡检路由（Python 版 routes_inspect.py 的平移）：把"检索内部发生了什么"直接暴露成 JSON。
 * 与问答链路共用同一批组件（hybrid / rerank / budget / gates），保证调试页看到的就是线上跑的。
 */
@RestController
public class InspectController {

    private static final int VIEW_CHARS = 600;   // 列表页正文截断长度（原文仍在库里，按 chunk_id 可查）

    private final Settings settings;
    private final HybridSearch hybridSearch;
    private final QueryRewriter queryRewriter;
    private final RerankClient rerankClient;
    private final DirectHit directHit;
    private final QueryRouter queryRouter;
    private final com.ownrag.auth.AuthService authService;

    public InspectController(Settings settings, HybridSearch hybridSearch, QueryRewriter queryRewriter,
                             RerankClient rerankClient, DirectHit directHit, QueryRouter queryRouter,
                             com.ownrag.auth.AuthService authService) {
        this.settings = settings;
        this.hybridSearch = hybridSearch;
        this.queryRewriter = queryRewriter;
        this.rerankClient = rerankClient;
        this.directHit = directHit;
        this.queryRouter = queryRouter;
        this.authService = authService;
    }

    // ---- 配置视图 ----
    @GetMapping("/admin/config")
    public Map<String, Object> getConfig() throws Exception {
        Map<String, Object> models = com.ownrag.util.Yamls.load(
                settings.getConfigDir().isEmpty() ? "classpath:configs/models.yaml"
                        : java.nio.file.Paths.get(settings.getConfigDir(), "models.yaml").toString());
        List<String> prompts = new ArrayList<>(settings.getPrompts().keySet());
        java.util.Collections.sort(prompts);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("config_dir", settings.getConfigDir());
        out.put("data_dir", settings.getDataDir().toString());
        out.put("known_kbs", new ArrayList<>(KbWhitelist.all(settings)));
        out.put("pipelines", settings.getPipelines());
        out.put("apps", settings.getApps());
        out.put("models", models);
        out.put("prompts", prompts);
        Map<String, Object> limits = new LinkedHashMap<>();
        limits.put("num_ctx", settings.getNumCtx());
        limits.put("max_new_tokens", settings.getMaxNewTokens());
        limits.put("max_upload_mb", settings.getMaxUploadMb());
        out.put("limits", limits);
        return out;
    }

    // ---- 分块浏览 ----
    @GetMapping("/admin/chunks")
    public Map<String, Object> listChunks(@RequestParam(defaultValue = "") String kb,
                                          @RequestParam(defaultValue = "") String q,
                                          @RequestParam(defaultValue = "") String docId,
                                          @RequestParam(defaultValue = "20") int limit,
                                          javax.servlet.http.HttpServletRequest request) throws Exception {
        limit = Math.max(1, Math.min(limit, 100));
        // 分块正文属于文档内容：未登录只看公开文档（两条分支都要过滤，不能只顾关键词那条）
        boolean loggedIn = authService.currentUser(request) != null;
        Map<String, Object> accessFilter = com.ownrag.auth.AuthService.accessFilter(null, loggedIn);
        try (Connection conn = Db.connect(settings.getDbPath())) {
            if (!q.trim().isEmpty()) {
                // q 非空走 FTS5（与线上关键词通道同一函数）
                String kbForSearch = kb.isEmpty()
                        ? settings.getKnownKbs().stream().sorted().findFirst().orElse("default") : kb;
                long t0 = System.nanoTime();
                List<Map<String, Object>> hits =
                        ChunkStore.keywordSearch(conn, kbForSearch, q.trim(), limit, accessFilter);
                double ms = Math.round((System.nanoTime() - t0) / 1_000_000.0 * 10) / 10.0;
                Map<String, Map<String, Object>> mapped =
                        ChunkStore.readChunks(conn, idsOf(hits));
                List<Map<String, Object>> chunks = new ArrayList<>();
                for (Map<String, Object> h : hits) {
                    Map<String, Object> c = mapped.get(String.valueOf(h.get("chunk_id")));
                    if (c == null) {
                        continue;
                    }
                    Map<String, Object> row = new LinkedHashMap<>(c);
                    String text = String.valueOf(c.get("text"));
                    row.put("chars", text.length());
                    row.put("text", text.substring(0, Math.min(VIEW_CHARS, text.length())));
                    row.put("truncated_view", text.length() > VIEW_CHARS);
                    row.put("bm25_score", h.get("score"));
                    chunks.add(row);
                }
                Map<String, Object> out = new LinkedHashMap<>();
                out.put("mode", "fts");
                out.put("kb", kbForSearch);
                out.put("q", q.trim());
                out.put("ms", ms);
                out.put("public_only", !loggedIn);
                out.put("total", chunks.size());
                out.put("chunks", chunks);
                return out;
            }

            StringBuilder where = new StringBuilder();
            List<Object> args = new ArrayList<>();
            if (!loggedIn) {
                where.append("1=1 ").append(ChunkStore.publicOnlySql("chunks.doc_id"));
            }
            if (!kb.isEmpty()) {
                if (where.length() > 0) {
                    where.append(" AND ");
                }
                where.append("kb=?");
                args.add(kb);
            }
            if (!docId.isEmpty()) {
                if (where.length() > 0) {
                    where.append(" AND ");
                }
                where.append("doc_id=?");
                args.add(docId);
            }
            String sqlWhere = where.length() > 0 ? "WHERE " + where : "";
            long total;
            try (PreparedStatement ps = conn.prepareStatement(
                    "SELECT COUNT(*) n FROM chunks " + sqlWhere)) {
                for (int i = 0; i < args.size(); i++) {
                    ps.setObject(i + 1, args.get(i));
                }
                try (ResultSet rs = ps.executeQuery()) {
                    total = rs.next() ? rs.getLong(1) : 0;
                }
            }
            List<Map<String, Object>> chunks = new ArrayList<>();
            try (PreparedStatement ps = conn.prepareStatement(
                    "SELECT * FROM chunks " + sqlWhere + " ORDER BY created_at DESC, ordinal LIMIT ?")) {
                for (int i = 0; i < args.size(); i++) {
                    ps.setObject(i + 1, args.get(i));
                }
                ps.setInt(args.size() + 1, limit);
                try (ResultSet rs = ps.executeQuery()) {
                    while (rs.next()) {
                        chunks.add(chunkRow(rs));
                    }
                }
            }
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("mode", "list");
            out.put("kb", kb);
            out.put("public_only", !loggedIn);
            out.put("total", total);
            out.put("chunks", chunks);
            return out;
        }
    }

    private static Map<String, Object> chunkRow(ResultSet rs) throws SQLException {
        String text = rs.getString("text") == null ? "" : rs.getString("text");
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("chunk_id", rs.getString("chunk_id"));
        row.put("doc_id", rs.getString("doc_id"));
        row.put("kb", rs.getString("kb"));
        row.put("ordinal", rs.getInt("ordinal"));
        row.put("source_type", rs.getString("source_type"));
        row.put("anchors", parseOrEmpty(rs.getString("anchors_json")));
        row.put("meta", parseOrEmpty(rs.getString("meta_json")));
        row.put("embed_version", rs.getString("embed_version"));
        row.put("sensitivity", rs.getString("sensitivity"));
        row.put("topic", rs.getString("topic"));
        row.put("doc_date", rs.getString("doc_date"));
        row.put("origin", rs.getString("origin"));
        row.put("created_at", rs.getString("created_at"));
        row.put("chars", text.length());
        row.put("text", text.substring(0, Math.min(VIEW_CHARS, text.length())));
        row.put("truncated_view", text.length() > VIEW_CHARS);
        return row;
    }

    // ---- 直击库（只读之外补上维护面） ----
    public static class DirectHitIn {
        public String kb;
        public String question;
        public String answer;
        public String level = "L0";
        public List<String> aliases = new ArrayList<>();
        /** public | protected：直击库直达用户，不挂在 documents 上，权限得自己带（缺省 public）。 */
        public String access_level;
    }

    @GetMapping("/admin/direct_hits")
    public Map<String, Object> listDirectHits(@RequestParam(defaultValue = "") String kb) throws Exception {
        try (Connection conn = Db.connect(settings.getDbPath())) {
            StringBuilder sql = new StringBuilder("SELECT * FROM direct_hits");
            List<Object> args = new ArrayList<>();
            if (!kb.isEmpty()) {
                sql.append(" WHERE kb=?");
                args.add(kb);
            }
            sql.append(" ORDER BY created_at DESC");
            List<Map<String, Object>> hits = new ArrayList<>();
            try (PreparedStatement ps = conn.prepareStatement(sql.toString())) {
                for (int i = 0; i < args.size(); i++) {
                    ps.setObject(i + 1, args.get(i));
                }
                try (ResultSet rs = ps.executeQuery()) {
                    while (rs.next()) {
                        Map<String, Object> row = TaskStore.rowToMap(rs);
                        row.put("aliases", parseOrEmpty(rs.getString("aliases_json")));
                        hits.add(row);
                    }
                }
            }
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("hits", hits);
            return out;
        }
    }

    @PostMapping("/admin/direct_hits")
    public Map<String, Object> createDirectHit(@RequestBody DirectHitIn body) throws Exception {
        if (body.level == null || !java.util.Arrays.asList("L0", "L1", "L2").contains(body.level)) {
            throw new ApiError(422, "level 只能是 L0/L1/L2");
        }
        if (body.question == null || body.question.trim().isEmpty()
                || body.answer == null || body.answer.trim().isEmpty()) {
            throw new ApiError(422, "question 与 answer 不能为空");
        }
        String hitId = Ids.short12().substring(0, 10);
        String level = com.ownrag.auth.AccessLevel.normalize(body.access_level);
        // 幂等：同 (kb, question) 已存在 → 更新内容并返回原 id，不新增行（灌库脚本可重跑）
        String existingId = null;
        try (Connection conn = Db.connect(settings.getDbPath())) {
            try (PreparedStatement ps = conn.prepareStatement(
                    "SELECT id FROM direct_hits WHERE kb=? AND question=?")) {
                ps.setString(1, body.kb);
                ps.setString(2, body.question.trim());
                try (ResultSet rs = ps.executeQuery()) {
                    if (rs.next()) {
                        existingId = rs.getString("id");
                    }
                }
            }
            Db.endRead(conn);  // 先查后写：读事务不收尾，下面的写会撞 BUSY_SNAPSHOT
            if (existingId != null) {
                // access_level 未显式给出时不覆盖已有值（避免"改答案顺手把权限改回公开"）
                String sql = body.access_level == null
                        ? "UPDATE direct_hits SET level=?, aliases_json=?, answer=? WHERE id=?"
                        : "UPDATE direct_hits SET level=?, aliases_json=?, answer=?, access_level=? WHERE id=?";
                try (PreparedStatement ps = conn.prepareStatement(sql)) {
                    ps.setString(1, body.level);
                    ps.setString(2, Json.write(body.aliases == null ? new ArrayList<>() : body.aliases));
                    ps.setString(3, body.answer);
                    int i = 4;
                    if (body.access_level != null) {
                        ps.setString(i++, level);
                    }
                    ps.setString(i, existingId);
                    ps.executeUpdate();
                }
            } else {
                try (PreparedStatement ps = conn.prepareStatement(
                        "INSERT INTO direct_hits(id,kb,level,question,aliases_json,answer,enabled,access_level) "
                                + "VALUES (?,?,?,?,?,?,1,?)")) {
                    ps.setString(1, hitId);
                    ps.setString(2, body.kb);
                    ps.setString(3, body.level);
                    ps.setString(4, body.question.trim());
                    ps.setString(5, Json.write(body.aliases == null ? new ArrayList<>() : body.aliases));
                    ps.setString(6, body.answer);
                    ps.setString(7, level);
                    ps.executeUpdate();
                }
            }
            conn.commit();
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", existingId != null ? existingId : hitId);
        out.put("status", existingId != null ? "updated" : "created");
        return out;
    }

    @DeleteMapping("/admin/direct_hits/{hitId}")
    public Map<String, Object> deleteDirectHit(@PathVariable String hitId) throws Exception {
        try (Connection conn = Db.connect(settings.getDbPath());
             PreparedStatement ps = conn.prepareStatement("DELETE FROM direct_hits WHERE id=?")) {
            ps.setString(1, hitId);
            int n = ps.executeUpdate();
            conn.commit();
            if (n == 0) {
                throw new ApiError(404, "直击条目不存在：" + hitId);
            }
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", hitId);
        out.put("status", "deleted");
        return out;
    }

    // ---- 纯检索调试 ----
    public static class RetrieveReq {
        public String question;
        public String app = "policy_qa";
        public String kb;
        public Integer vector_topk;
        public Integer bm25_topk;
        public Integer top_n;
        public Integer rerank_top_n;
        public java.util.Map<String, Object> metadataFilter;
        /** 单次改写开关：null=按 apps.yaml；true=强制（本端点无历史，等价于去套话）；false=关闭。 */
        public Boolean rewrite;
        /** true = 只跑路由（不检索、不生成、不执行 SQL）：路由回归台。 */
        public Boolean route;
        /** route=true 时强制指定通道（rag/sql/multi/web），用于验证"指定了但不可用"的回落。 */
        public String force_route;
    }

    @PostMapping("/admin/retrieve")
    public Map<String, Object> debugRetrieve(@RequestBody RetrieveReq req,
                                            @RequestParam(value = "route", required = false) Boolean routeParam,
                                            javax.servlet.http.HttpServletRequest request)
            throws Exception {
        // 只跑检索侧：直击库 →（问句改写）→ 双通道 → RRF → rerank → 预算 → 闸门一。不调用生成模型。
        if (req.question == null || req.question.trim().isEmpty()) {
            throw new ApiError(422, "问题为空");
        }
        AppDef appCfg = settings.app(req.app == null ? "policy_qa" : req.app);
        if (appCfg == null) {
            throw new ApiError(404, "应用未定义：" + req.app);
        }
        List<String> kbs = appCfg.knowledgeBases.isEmpty()
                ? java.util.Collections.singletonList("default") : appCfg.knowledgeBases;
        String kb = req.kb == null || req.kb.isEmpty() ? kbs.get(0) : req.kb;
        // 调试台与线上同一口径：未登录时同样只看公开文档（否则"调试能搜到、问答搜不到"无从解释）
        boolean loggedIn = authService.currentUser(request) != null;
        Map<String, Object> metadataFilter =
                com.ownrag.auth.AuthService.accessFilter(req.metadataFilter, loggedIn);

        // 路由回归台：只跑"分诊"，不检索、不生成、不执行 SQL。
        // 它是唯一能脱离模型、脱离答案质量来验证"判定对不对"的入口（路由错但答案对也算错）。
        if (Boolean.TRUE.equals(req.route) || Boolean.TRUE.equals(routeParam)) {
            return routeOnly(req, appCfg, kbs);
        }

        // 改写这一步与 /chat 同源：llm=null（本端点约定不调生成模型）、history=null（无对话上下文），
        // 因此这里只会走"去套话"或"不改"两条确定性分支——调试页看到的检索式与问答页首轮一致。
        QueryRewriter.Result rw = queryRewriter.rewrite(settings, null, req.question, null,
                req.rewrite != null ? req.rewrite : (appCfg.queryRewrite ? null : Boolean.FALSE));
        String query = rw.triggered ? rw.rewritten : rw.original;

        long t0 = System.nanoTime();
        Map<String, Object> direct;
        Map<String, Object> result;
        RerankClient.RerankResult reranked;
        Budget.ContextPlan plan;
        Gates.GateResult pre;
        try (Connection conn = Db.connect(settings.getDbPath())) {
            DirectHit.Hit hit = directHit.match(conn, kbs, req.question, 0.86);
            direct = new LinkedHashMap<>();
            if (hit != null) {
                direct.put("hit", true);
                direct.put("level", hit.level);
                direct.put("question", hit.question);
                direct.put("score", hit.score);
            } else {
                direct.put("hit", false);
            }
            // 与 /chat 同一口径：调试台看到的候选必须就是线上会进 prompt 的那批
            // （不含 Excel 行卡片 + 未登录时不含需登录文档）
            result = hybridSearch.search(conn, settings, kb, query,
                    req.vector_topk != null ? req.vector_topk : appCfg.vectorTopk,
                    req.bm25_topk != null ? req.bm25_topk : appCfg.bm25Topk,
                    req.top_n != null ? req.top_n : appCfg.topN,
                    HybridSearch.withAccess(HybridSearch.ragFilter(metadataFilter), loggedIn));
            List<Map<String, Object>> candidates =
                    (List<Map<String, Object>>) result.getOrDefault("candidates", new ArrayList<>());
            int rerankTopN = req.rerank_top_n != null ? req.rerank_top_n
                    : Math.max(4, (req.top_n != null ? req.top_n : appCfg.topN) / 2);
            reranked = rerankClient.rerank(settings, query, candidates, rerankTopN);
            Map<String, Object> genCfg = new LinkedHashMap<>();
            genCfg.put("max_ctx_tokens", appCfg.maxCtxTokens);
            genCfg.put("max_new_tokens", appCfg.maxNewTokens);
            int[] limits = Budget.resolveLimits(settings, genCfg);
            plan = Budget.planContext(reranked.candidates, req.question, appCfg.prompt,
                    limits[0], limits[1], settings);
            pre = Gates.sufficiencyCheck(reranked.candidates);
        }
        double ms = Math.round((System.nanoTime() - t0) / 1_000_000.0 * 10) / 10.0;

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("question", req.question);
        out.put("app", req.app);
        out.put("kb", kb);
        // 权限口径随结果回显：候选为空时，页面才能区分"语料没有"和"未登录看不到"
        Map<String, Object> access = new LinkedHashMap<>();
        access.put("logged_in", loggedIn);
        access.put("public_only", !loggedIn);
        access.put("protected_docs", loggedIn ? 0 : authService.countProtected(kbs));
        access.put("note", loggedIn ? "已登录：检索全部文档"
                : "未登录：只在公开文档中检索，登录后可检索全部");
        out.put("access", access);
        out.put("ms", ms);
        out.put("rewrite", rw.toEvent());   // 检索用的是哪句话：静默改写查不出问题
        out.put("direct_hit", direct);
        out.put("vector_skipped_reason", result.get("vector_skipped_reason"));
        out.put("retrieval_path", result.get("retrieval_path"));
        out.put("channels", result.get("channels"));
        out.put("candidates", briefList(reranked.candidates));
        Map<String, Object> budget = new LinkedHashMap<>();
        budget.put("num_ctx", plan.numCtx);
        budget.put("reserved_output", plan.maxNewTokens);
        budget.put("prompt_overhead", plan.promptOverhead);
        budget.put("available", plan.available);
        budget.put("kept", plan.fitted.blocks.size());
        budget.put("dropped", plan.fitted.dropped.size());
        budget.put("dropped_ids", plan.fitted.dropped);
        budget.put("truncated", plan.fitted.truncated);
        budget.put("ctx_tokens", plan.fitted.tokens);
        budget.put("blocks", briefList(plan.fitted.blocks));
        out.put("budget", budget);
        Map<String, Object> rerankNote = new LinkedHashMap<>();
        rerankNote.put("note", reranked.note);
        out.put("rerank", rerankNote);
        Map<String, Object> gatePre = new LinkedHashMap<>();
        gatePre.put("name", pre.name);
        gatePre.put("passed", pre.passed);
        gatePre.put("reason", pre.reason);
        out.put("gate_pre", gatePre);
        return out;
    }

    // ---- 路由回归台 ----
    /**
     * 只跑路由 + 选表。刻意不执行 SQL、不调生成模型：
     * 这个端点回答的是"系统认为这道题该查哪类数据"，一旦掺进 SQL 结果或答案，就分不清
     * "判定错"和"执行错"了。
     */
    private Map<String, Object> routeOnly(RetrieveReq req, AppDef appCfg, List<String> kbs) throws Exception {
        long t0 = System.nanoTime();
        Map<String, Object> out = new LinkedHashMap<>();
        try (Connection conn = Db.connect(settings.getDbPath())) {
            RouteResult r = queryRouter.route(conn, appCfg, kbs, req.question, req.force_route);
            out.put("mode", "route");
            out.put("question", req.question);
            out.put("app", appCfg.name);
            out.put("kbs", kbs);
            out.put("routing_enabled", appCfg.routingEnabled);
            if (!appCfg.routingEnabled) {
                out.put("note", "该 app 未开启 routing：/chat 仍走单轨 RAG，此处仅试跑判定");
            }
            out.put("route", r.toEvent());

            // 判成 sql 但 targets 为空 = "判对了一半"（知道要查表，但不知道查哪张）：
            // 单列一个字段，让这种半对在页面上一眼可见，而不是埋在 route.targets 的空数组里
            List<Map<String, Object>> picked = new ArrayList<>();
            for (Map<String, Object> t : r.targets) {
                picked.add(t);
            }
            out.put("picked_tables", picked);
            out.put("catalog", catalogView(conn, kbs));
        }
        out.put("ms", Math.round((System.nanoTime() - t0) / 1_000_000.0 * 10) / 10.0);
        return out;
    }

    /** 该 app 可见的 Excel 表目录（staging_registry 现算）：路由为什么选/不选某张表，靠它解释。 */
    private List<Map<String, Object>> catalogView(Connection conn, List<String> kbs) throws Exception {
        List<Map<String, Object>> out = new ArrayList<>();
        for (TableCatalog.TableInfo t : TableCatalog.list(conn, kbs)) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("table", t.table);
            m.put("sheet", t.sheet);
            m.put("kb", t.kb);
            m.put("doc_id", t.docId);
            m.put("doc_name", t.docName);
            m.put("rows", t.rows);
            m.put("pk", t.pk);
            List<Map<String, Object>> cols = new ArrayList<>();
            for (Map<String, Object> c : t.columns) {
                Map<String, Object> cm = new LinkedHashMap<>();
                cm.put("column", c.get("column"));
                cm.put("physical", c.get("physical"));
                cm.put("type", c.get("type"));
                cm.put("sql_expr", c.get("sql_expr"));
                cols.add(cm);
            }
            m.put("columns", cols);
            out.add(m);
        }
        return out;
    }

    // ---- 任务详情 ----
    @GetMapping("/admin/tasks/{taskId}")
    public Map<String, Object> taskDetail(@PathVariable String taskId) throws Exception {
        try (Connection conn = Db.connect(settings.getDbPath())) {
            Map<String, Object> row = TaskStore.getTask(conn, taskId);
            if (row == null) {
                throw new ApiError(404, "任务不存在：" + taskId);
            }
            List<Map<String, Object>> steps =
                    AdminController.withCounters(TraceLog.byTrace(conn, String.valueOf(row.get("trace_id"))));
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("task", row);
            out.put("steps", steps);
            return out;
        }
    }

    // ---- 小工具 ----
    private static List<String> idsOf(List<Map<String, Object>> hits) {
        List<String> ids = new ArrayList<>();
        for (Map<String, Object> h : hits) {
            ids.add(String.valueOf(h.get("chunk_id")));
        }
        return ids;
    }

    private static List<Map<String, Object>> briefList(List<Map<String, Object>> candidates) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (Map<String, Object> c : candidates) {
            Map<String, Object> b = new LinkedHashMap<>();
            b.put("chunk_id", c.get("chunk_id"));
            b.put("doc_id", c.get("doc_id"));
            b.put("doc_name", c.get("doc_name"));  // 引用位置要能直接看出是哪篇文档，而不是 doc_id 前几位
            b.put("ordinal", c.get("ordinal"));
            Object rrf = c.get("rrf");
            b.put("rrf", rrf instanceof Number ? Math.round(((Number) rrf).doubleValue() * 1e6) / 1e6 : 0);
            b.put("rerank_score", c.get("rerank_score"));
            b.put("channels", c.get("channels"));
            b.put("anchors", c.get("anchors"));
            b.put("meta", c.get("meta"));  // 出处与过滤列随候选回显：调试/评测要按文件溯源
            String text = c.get("text") == null ? "" : String.valueOf(c.get("text"));
            b.put("chars", text.length());
            b.put("preview", text.substring(0, Math.min(200, text.length())));
            out.add(b);
        }
        return out;
    }

    private static Object parseOrEmpty(String json) {
        if (json == null || json.isEmpty()) {
            return new LinkedHashMap<>();
        }
        try {
            return Json.readMap(json);
        } catch (Exception e) {
            return new LinkedHashMap<>();
        }
    }
}
