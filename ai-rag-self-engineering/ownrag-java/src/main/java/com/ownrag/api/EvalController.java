package com.ownrag.api;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
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
import com.ownrag.eval.EvalStore;
import com.ownrag.generate.Gates;
import com.ownrag.retrieve.DirectHit;
import com.ownrag.retrieve.HybridSearch;
import com.ownrag.retrieve.RerankClient;
import com.ownrag.router.QueryRouter;
import com.ownrag.router.RouteResult;
import com.ownrag.util.Json;

/**
 * 评测集路由（/ui/evalset 的后端）。
 *
 * 口径：**只跑检索侧，不调生成模型**——判的是"该找的块有没有被找上来 / 该拒答的有没有被拦下"，
 * 不是"答案写得漂不漂亮"。与 /chat、/admin/retrieve 共用 HybridSearch + RerankClient + 闸门一，
 * 保证评测看到的链路就是线上跑的那一条。
 *
 * 好/坏判定（页面同步展示同一段口径）：
 *   ① 有期望关键词：TopN 候选正文需包含**全部**期望词，且闸门一通过 → pass；否则 fail
 *   ② 应拒答题：闸门一必须拦下 → pass；放出候选 → fail
 *   ③ 无期望关键词（日志回流/直击库种子）：闸门一给出依据 → pass
 * pending 只出现在"还没跑"的题上——跑失败不降级成 pending，而是 fail + detail 里的原因。
 */
@RestController
public class EvalController {

    private final Settings settings;
    private final HybridSearch hybridSearch;
    private final RerankClient rerankClient;
    private final DirectHit directHit;
    private final QueryRouter queryRouter;

    public EvalController(Settings settings, HybridSearch hybridSearch, RerankClient rerankClient,
                          DirectHit directHit, QueryRouter queryRouter) {
        this.settings = settings;
        this.hybridSearch = hybridSearch;
        this.rerankClient = rerankClient;
        this.directHit = directHit;
        this.queryRouter = queryRouter;
    }

    // ---------------------------------------------------------------- 列表

    @GetMapping("/admin/eval-set")
    public Map<String, Object> list(@RequestParam(defaultValue = "") String kb,
                                    @RequestParam(defaultValue = "") String source,
                                    @RequestParam(defaultValue = "") String verdict,
                                    @RequestParam(defaultValue = "300") int limit) throws Exception {
        try (Connection conn = Db.connect(settings.getDbPath())) {
            // 首次打开空表：把已有真实资产（直击库 + 问答日志）导进来，先立分母
            EvalStore.ensureSeed(conn, settings);
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("kpi", EvalStore.kpi(conn));
            out.put("cases", EvalStore.list(conn, kb, source, verdict, limit));
            out.put("kbs", new ArrayList<>(KbWhitelist.all(settings)));
            return out;
        }
    }

    // ---------------------------------------------------------------- 增 / 删 / 改判

    @PostMapping("/admin/eval-set/cases")
    public Map<String, Object> add(@RequestBody Map<String, Object> body) throws Exception {
        String question = str(body.get("question"));
        if (question == null || question.isEmpty()) {
            throw new ApiError(422, "问题为空");
        }
        try (Connection conn = Db.connect(settings.getDbPath())) {
            return EvalStore.add(conn, str(body.get("kb")), question, str(body.get("source")),
                    str(body.get("source_ref")), listOf(body.get("expect_all")),
                    bool(body.get("expect_empty")), str(body.get("note")),
                    str(body.get("category")), str(body.get("difficulty")),
                    str(body.get("expect_route")));
        }
    }

    @DeleteMapping("/admin/eval-set/cases/{id}")
    public Map<String, Object> delete(@PathVariable long id) throws Exception {
        try (Connection conn = Db.connect(settings.getDbPath())) {
            if (!EvalStore.delete(conn, id)) {
                throw new ApiError(404, "评测题不存在：" + id);
            }
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("deleted", id);
            return out;
        }
    }

    /**
     * 补/改期望：日志回流的题本来就没有标准答案，先标"应拒答"或填关键词，才有好坏可判。
     * 期望一变旧判定作废（verdict=pending），避免拿旧结论配新期望。
     */
    @PostMapping("/admin/eval-set/cases/{id}/expect")
    public Map<String, Object> setExpect(@PathVariable long id,
                                         @RequestBody Map<String, Object> body) throws Exception {
        try (Connection conn = Db.connect(settings.getDbPath())) {
            boolean ok = EvalStore.setExpect(conn, id, listOf(body.get("expect_all")),
                    bool(body.get("expect_empty")), str(body.get("expect_route")));
            if (!ok) {
                throw new ApiError(404, "评测题不存在：" + id);
            }
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("id", id);
            out.put("verdict", "pending");
            return out;
        }
    }

    /** 人工改判：保留人工结论（score 清空），下一次跑评测会覆盖成机器结论。 */
    @PostMapping("/admin/eval-set/cases/{id}/verdict")
    public Map<String, Object> mark(@PathVariable long id,
                                    @RequestBody Map<String, Object> body) throws Exception {
        String verdict = str(body.get("verdict"));
        try (Connection conn = Db.connect(settings.getDbPath())) {
            boolean ok = EvalStore.setVerdict(conn, id, verdict, str(body.get("note")));
            if (!ok) {
                throw new ApiError(404, "评测题不存在：" + id);
            }
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("id", id);
            out.put("verdict", verdict);
            return out;
        }
    }

    // ---------------------------------------------------------------- 来源导入

    /** 问答日志回流：最近 N 条去重问题入评测集（来源标 qa_log，可回查原始 trace）。 */
    @PostMapping("/admin/eval-set/import/qa-log")
    public Map<String, Object> importQaLog(
            @RequestBody(required = false) Map<String, Object> body) throws Exception {
        int limit = body == null ? 10 : intVal(body.get("limit"), 10);
        try (Connection conn = Db.connect(settings.getDbPath())) {
            return EvalStore.importFromQaLog(conn, settings, limit);
        }
    }

    /**
     * 一键重建黄金集：从 classpath `eval/golden-set.json` 逐条导入（同库同题幂等）。
     * 换库/换机器后不必手工录 42 道题——题库是版本化资产，接口只负责把它落进库。
     */
    @SuppressWarnings("unchecked")
    @PostMapping("/admin/eval-set/import/golden")
    public Map<String, Object> importGolden() throws Exception {
        Map<String, Object> doc = Json.readMap(readResource("/eval/golden-set.json"));
        String kb = doc.get("kb") == null ? "kb_interview" : String.valueOf(doc.get("kb"));
        Object raw = doc.get("cases");
        List<Map<String, Object>> cases = raw instanceof List
                ? (List<Map<String, Object>>) raw : new ArrayList<Map<String, Object>>();

        int added = 0;
        int skipped = 0;
        try (Connection conn = Db.connect(settings.getDbPath())) {
            for (Map<String, Object> c : cases) {
                Map<String, Object> r = EvalStore.add(conn, kb, str(c.get("question")), "manual", null,
                        listOf(c.get("expect_all")), bool(c.get("expect_empty")), str(c.get("note")),
                        str(c.get("category")), str(c.get("difficulty")), str(c.get("expect_route")));
                if (Boolean.TRUE.equals(r.get("created"))) {
                    added++;
                } else {
                    skipped++;
                }
            }
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("added", added);
        out.put("skipped", skipped);
        out.put("scanned", cases.size());
        out.put("version", doc.get("version"));
        return out;
    }

    private static String readResource(String path) throws Exception {
        try (InputStream in = EvalController.class.getResourceAsStream(path)) {
            if (in == null) {
                throw new ApiError(404, "题库文件不存在：" + path);
            }
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) {
                out.write(buf, 0, n);
            }
            return new String(out.toByteArray(), StandardCharsets.UTF_8);
        }
    }

    // ---------------------------------------------------------------- 跑评测

    @PostMapping("/admin/eval-set/run")
    public Map<String, Object> run(@RequestBody(required = false) Map<String, Object> body)
            throws Exception {
        String kbFilter = body == null ? "" : str(body.get("kb"));
        List<Long> ids = longList(body == null ? null : body.get("ids"));
        int topN = body == null ? 12 : intVal(body.get("top_n"), 12);

        long t0 = System.nanoTime();
        int pass = 0;
        int fail = 0;
        int pending = 0;
        List<Map<String, Object>> results = new ArrayList<>();

        try (Connection conn = Db.connect(settings.getDbPath())) {
            EvalStore.ensureSeed(conn, settings);
            List<Map<String, Object>> cases = EvalStore.list(conn, kbFilter, "", "", 500);
            Db.endRead(conn);   // 读快照收尾：随后同连接要 UPDATE 判定，避免 BUSY_SNAPSHOT

            for (Map<String, Object> c : cases) {
                long id = ((Number) c.get("id")).longValue();
                if (!ids.isEmpty() && !ids.contains(id)) {
                    continue;
                }
                String verdict;
                Double score;
                Map<String, Object> detail;
                String routeActual = null;
                try {
                    Map<String, Object> judged = judgeOne(conn, c, topN);
                    verdict = String.valueOf(judged.get("verdict"));
                    score = (Double) judged.get("score");
                    detail = (Map<String, Object>) judged.get("detail");
                    routeActual = (String) judged.get("route_actual");
                } catch (Exception e) {
                    // 单题执行异常也落成 fail + 原因：批量评测不能被一道题整体打断，
                    // 更不能静默跳过（跳过会让"分母"看起来比真实更好）
                    verdict = "fail";
                    score = 0.0;
                    detail = new LinkedHashMap<>();
                    detail.put("reason", "评测执行失败：" + e.getMessage());
                }
                EvalStore.recordResult(conn, id, verdict, score, detail, routeActual);
                Db.endRead(conn);   // 判定写完再进入下一题的读事务
                if ("pass".equals(verdict)) {
                    pass++;
                } else if ("fail".equals(verdict)) {
                    fail++;
                } else {
                    pending++;   // 未设期望：观察到了，但不算好坏
                }
                Map<String, Object> row = new LinkedHashMap<>();
                row.put("id", id);
                row.put("question", c.get("question"));
                row.put("verdict", verdict);
                row.put("score", score);
                row.put("reason", detail.get("reason"));
                results.add(row);
            }
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("ran", results.size());
        out.put("pass", pass);
        out.put("fail", fail);
        out.put("pending", pending);
        out.put("ms", Math.round((System.nanoTime() - t0) / 1_000_000.0 * 10) / 10.0);
        out.put("results", results);
        return out;
    }

    /**
     * 单题判定：检索 → 重排 → 闸门一 → 按期望口径算分。
     * 不生成答案：评测要能反复跑且不烧 token，答案质量靠闸门二与人工抽检。
     */
    @SuppressWarnings("unchecked")
    private Map<String, Object> judgeOne(Connection conn, Map<String, Object> c, int topN)
            throws Exception {
        long t0 = System.nanoTime();
        String kb = str(c.get("kb"));
        AppDef appCfg = appForKb(kb);
        int vTopk = appCfg == null ? 20 : appCfg.vectorTopk;
        int bTopk = appCfg == null ? 20 : appCfg.bm25Topk;
        int n = topN > 0 ? topN : (appCfg == null ? 12 : appCfg.topN);

        // 路由判定独立于检索：检索全对但走错通道，同样是坏（"答案对、路子错"最难被发现）。
        // 判的通道必须是 /chat 真会走的那个：app 未开启 routing 时，线上恒为 rag。
        RouteResult route = judgeRoute(conn, appCfg, kb, String.valueOf(c.get("question")));
        String routeActual = route.route;
        String expectRoute = str(c.get("expect_route"));
        boolean routeMismatch = expectRoute != null && !expectRoute.isEmpty()
                && !expectRoute.equals(routeActual);

        Map<String, Object> retrieval = hybridSearch.search(conn, settings, kb,
                String.valueOf(c.get("question")), vTopk, bTopk, n, null);
        List<Map<String, Object>> candidates =
                (List<Map<String, Object>>) retrieval.getOrDefault("candidates", new ArrayList<>());
        RerankClient.RerankResult reranked =
                rerankClient.rerank(settings, String.valueOf(c.get("question")), candidates,
                        Math.max(4, n / 2));
        Gates.GateResult gate = Gates.sufficiencyCheck(reranked.candidates);

        List<String> expectAll = (List<String>) c.getOrDefault("expect_all", new ArrayList<String>());
        boolean expectEmpty = Boolean.TRUE.equals(c.get("expect_empty"));

        List<String> hit = new ArrayList<>();
        List<String> missing = new ArrayList<>();
        Map<String, Object> directInfo = new LinkedHashMap<>();
        String verdict;
        Double score;
        String reason;

        if (expectEmpty) {
            // 该拒答的拒答：闸门一拦下 = 好；把无关块放进上下文 = 坏
            verdict = gate.passed ? "fail" : "pass";
            score = gate.passed ? 0.0 : 1.0;
            reason = gate.passed
                    ? "应拒答但闸门一放行（候选 " + reranked.candidates.size() + " 块）"
                    : "闸门一按预期拦下：" + gate.reason;
        } else if (!expectAll.isEmpty()) {
            String blob = textBlob(reranked.candidates);
            for (String kw : expectAll) {
                if (blob.contains(kw.toLowerCase())) {
                    hit.add(kw);
                } else {
                    missing.add(kw);
                }
            }
            score = expectAll.isEmpty() ? 0.0
                    : Math.round(hit.size() * 1e4 / expectAll.size()) / 1e4;
            verdict = missing.isEmpty() && gate.passed ? "pass" : "fail";
            if (missing.isEmpty() && !gate.passed) {
                reason = "关键词都在，但闸门一未通过：" + gate.reason;
            } else if (!missing.isEmpty()) {
                reason = "缺期望词 " + missing.size() + "/" + expectAll.size() + "：" + missing;
            } else {
                reason = "期望词全部命中（" + hit.size() + " 个）";
            }
        } else if ("direct_hit".equals(c.get("source"))) {
            // 直击库回归题：该问题必须命中直击库（L0 精确/别名 → L1 语义 → L2 沉淀）。
            // "掉到检索链路"就算回归失败——直击库的整点价值就是高频题零检索零生成。
            DirectHit.Hit dh = directHit.match(conn, java.util.Collections.singletonList(kb),
                    String.valueOf(c.get("question")), 0.86);
            verdict = dh != null ? "pass" : "fail";
            score = dh != null ? 1.0 : 0.0;
            reason = dh != null
                    ? "直击库命中 " + dh.level + "（相似度 " + Math.round(dh.score * 1e4) / 1e4 + "）"
                    : "直击库未命中，掉到检索链路（回归失败）";
            directInfo.put("hit", dh != null);
            if (dh != null) {
                directInfo.put("level", dh.level);
                directInfo.put("hit_id", dh.hitId);
                directInfo.put("score", dh.score);
            }
        } else {
            // 没有标准答案就没有对错：只记录链路这次怎么走，不判好/坏。
            // 给 pass 会把"没标准"包装成"已通过"——这是评测集最容易骗自己的地方。
            verdict = "pending";
            score = null;
            reason = "未设期望词：只观察不判定（"
                    + (gate.passed ? "链路给出依据，top-rerank=" + topScore(reranked.candidates) : "链路拒答：" + gate.reason)
                    + "）；补期望词或标应拒答后再跑";
        }

        if (routeMismatch) {
            // 路由错就把结论降成 fail，但把检索侧的原结论保留在 reason 里——
            // 否则修完路由再跑一次，看不出检索本来是好是坏
            verdict = "fail";
            score = 0.0;
            reason = "路由不符：期望 " + expectRoute + "，实际 " + routeActual
                    + "（layer=" + route.layer + "）；原判定：" + reason;
        }

        Map<String, Object> detail = new LinkedHashMap<>();
        detail.put("reason", reason);
        Map<String, Object> routeInfo = new LinkedHashMap<>();
        routeInfo.put("expect", expectRoute);
        routeInfo.put("actual", routeActual);
        routeInfo.put("layer", route.layer);
        routeInfo.put("confidence", Math.round(route.confidence * 1000) / 1000.0);
        routeInfo.put("mismatch", routeMismatch);
        routeInfo.put("availability", route.availability);
        routeInfo.put("signals", route.signals);
        routeInfo.put("targets", route.targets);
        detail.put("route", routeInfo);
        Map<String, Object> gateMap = new LinkedHashMap<>();
        gateMap.put("passed", gate.passed);
        gateMap.put("reason", gate.reason);
        detail.put("gate", gateMap);
        Map<String, Object> expect = new LinkedHashMap<>();
        expect.put("expect_empty", expectEmpty);
        expect.put("keywords", expectAll);
        expect.put("hit", hit);
        expect.put("missing", missing);
        detail.put("expect", expect);
        Map<String, Object> rr = new LinkedHashMap<>();
        rr.put("note", reranked.note);
        detail.put("rerank", rr);
        if (!directInfo.isEmpty()) {
            detail.put("direct_hit", directInfo);
        }
        detail.put("channels", retrieval.get("retrieval_path"));
        // 向量通道本题有没有参与：判"坏"时第一件要排除的事就是通道静默缺失
        detail.put("vector_skipped_reason", retrieval.get("vector_skipped_reason"));
        detail.put("ms", Math.round((System.nanoTime() - t0) / 1_000_000.0 * 10) / 10.0);
        detail.put("top", topRows(reranked.candidates, 3));

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("verdict", verdict);
        out.put("score", score);
        out.put("detail", detail);
        out.put("route_actual", routeActual);
        return out;
    }

    /**
     * 评测用的路由判定：app 开启 routing 就用它自己的配置（权重/白名单与线上一致）；
     * 没开（或该 kb 不属于任何 app）就用一套"只读演练"配置——这样路由可以被评测，
     * 而不必先在生产开关上打开它。
     */
    private RouteResult judgeRoute(Connection conn, AppDef appCfg, String kb, String question) {
        AppDef app = appCfg != null && appCfg.routingEnabled ? appCfg : routingRehearsalApp();
        try {
            return queryRouter.route(conn, app, java.util.Collections.singletonList(kb), question, null);
        } catch (Exception e) {
            RouteResult r = new RouteResult();
            r.layer = "fallback";
            r.route = RouteResult.RAG;
            r.confidence = 0;
            r.reason = "路由异常：" + e.getMessage();
            r.availability.put("sql", false);
            r.availability.put("rag", true);
            r.availability.put("web", false);
            return r;
        }
    }

    private static AppDef routingRehearsalApp() {
        AppDef a = new AppDef();
        a.name = "eval_rehearsal";
        a.routingEnabled = true;
        a.routingAllow = new ArrayList<>(java.util.Arrays.asList("rag", "sql"));
        a.routingDefault = "rag";
        a.routingLowConfidence = "rag";
        a.routingMinConfidence = 0.4;
        a.sqlMaxTables = 3;
        return a;
    }

    // ---------------------------------------------------------------- 小工具

    private AppDef appForKb(String kb) {
        if (kb == null || kb.isEmpty()) {
            return null;
        }
        for (String name : settings.getApps().keySet()) {
            AppDef def = settings.app(name);
            if (def != null && def.knowledgeBases != null && def.knowledgeBases.contains(kb)) {
                return def;
            }
        }
        return null;
    }

    /** 候选正文拼一起（小写）：关键词判定与"模型能看到什么"同口径，只算预算内候选。 */
    private static String textBlob(List<Map<String, Object>> candidates) {
        StringBuilder sb = new StringBuilder();
        for (Map<String, Object> c : candidates) {
            Object text = c.get("text");
            if (text != null) {
                sb.append(String.valueOf(text).toLowerCase()).append('\n');
            }
        }
        return sb.toString();
    }

    /** 最高重排分（保留 4 位）：判"坏"时用一眼看出是"没捞到"还是"捞到但不够相关"。 */
    private static double topScore(List<Map<String, Object>> candidates) {
        double max = 0;
        for (Map<String, Object> c : candidates) {
            Object s = c.get("rerank_score");
            if (s instanceof Number) {
                max = Math.max(max, ((Number) s).doubleValue());
            }
        }
        return Math.round(max * 1e4) / 1e4;
    }

    private static List<Map<String, Object>> topRows(List<Map<String, Object>> candidates, int n) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (int i = 0; i < candidates.size() && i < n; i++) {
            Map<String, Object> c = candidates.get(i);
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("chunk_id", c.get("chunk_id"));
            row.put("doc_id", c.get("doc_id"));
            row.put("ordinal", c.get("ordinal"));
            row.put("rrf", c.get("rrf"));
            row.put("rerank_score", c.get("rerank_score"));
            String text = c.get("text") == null ? "" : String.valueOf(c.get("text"));
            row.put("preview", text.substring(0, Math.min(160, text.length())));
            out.add(row);
        }
        return out;
    }

    private static String str(Object v) {
        return v == null ? null : String.valueOf(v).trim();
    }

    private static int intVal(Object v, int fallback) {
        return v instanceof Number ? ((Number) v).intValue() : fallback;
    }

    private static boolean bool(Object v) {
        if (v instanceof Boolean) {
            return (Boolean) v;
        }
        return v != null && ("1".equals(String.valueOf(v)) || "true".equalsIgnoreCase(String.valueOf(v)));
    }

    /** 期望关键词：接受数组，也接受"逗号/顿号分隔"的字符串（页面输入框直接贴）。 */
    private static List<String> listOf(Object v) {
        List<String> out = new ArrayList<>();
        if (v == null) {
            return out;
        }
        if (v instanceof List) {
            for (Object o : (List<?>) v) {
                if (o != null && !String.valueOf(o).trim().isEmpty()) {
                    out.add(String.valueOf(o).trim());
                }
            }
            return out;
        }
        for (String part : String.valueOf(v).split("[,，、;；]")) {
            if (!part.trim().isEmpty()) {
                out.add(part.trim());
            }
        }
        return out;
    }

    private static List<Long> longList(Object v) {
        List<Long> out = new ArrayList<>();
        if (v instanceof List) {
            for (Object o : (List<?>) v) {
                if (o instanceof Number) {
                    out.add(((Number) o).longValue());
                } else if (o != null) {
                    try {
                        out.add(Long.parseLong(String.valueOf(o).trim()));
                    } catch (NumberFormatException ignored) {
                        // 非数字 id 直接忽略：批量跑评测不该被一个脏参数整体打断
                    }
                }
            }
        }
        return out;
    }
}
