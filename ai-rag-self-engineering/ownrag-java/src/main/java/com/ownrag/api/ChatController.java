package com.ownrag.api;

import java.io.IOException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;

import javax.annotation.PreDestroy;
import javax.servlet.http.HttpServletRequest;

import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import com.ownrag.auth.AccessPostCheck;
import com.ownrag.auth.AuthService;
import com.ownrag.auth.AuthUser;
import com.ownrag.config.AppDef;
import com.ownrag.config.Settings;
import com.ownrag.core.Db;
import com.ownrag.core.TraceLog;
import com.ownrag.generate.Budget;
import com.ownrag.generate.ChatClient;
import com.ownrag.generate.Gates;
import com.ownrag.generate.PromptRenderer;
import com.ownrag.retrieve.DirectHit;
import com.ownrag.retrieve.HybridSearch;
import com.ownrag.retrieve.QueryRewriter;
import com.ownrag.retrieve.RerankClient;
import com.ownrag.router.QueryRouter;
import com.ownrag.router.RouteResult;
import com.ownrag.router.SqlChannel;
import com.ownrag.router.SqlFailureTracker;
import com.ownrag.util.Ids;
import com.ownrag.util.Json;

/**
 * 问答路由（SSE 流式，Python 版 routes_chat.py 的平移）：
 * 直击库 →（问句改写）→ 混合检索 → rerank → 闸门一 → 预算 → 流式生成 → 闸门二 → 修复。
 *
 * SSE 事件契约（顺序不可变，前端按序消费）：
 *   hit（直击库命中）→ rewrite（改写是否触发）→ gate(retrieval_degraded) → retrieval/fuse（调试）
 *   → rerank（调试）→ ctx（候选依据）→ prompt（调试：发给模型的全文）→ token（流式增量，repaired 标记）
 *   → gate(post/context_budget/repair_failed) → no_evidence（无依据，合法答案）→ done → error。
 *
 * 调试事件（`debug=true` 才发，避免普通对话页多背几十 KB）：
 *   retrieval = 关键词/向量两路原始命中（含正文预览）；fuse = RRF 融合后的顺序；
 *   rerank = 重排后的顺序（带名次变化）；prompt = system/user 全文；done.raw_answer = 闸门重答前的首答。
 * 分层动作各自成私有方法（与 Python 版 _search/_rerank/_fit_context/_repair_answer/_log_qa 对齐）。
 */
@RestController
public class ChatController {

    private final Settings settings;
    private final HybridSearch hybridSearch;
    private final QueryRewriter queryRewriter;
    private final RerankClient rerankClient;
    private final DirectHit directHit;
    private final ChatClient chatClient;
    private final TraceLog traceLog;
    private final QueryRouter queryRouter;
    private final SqlChannel sqlChannel;
    private final AuthService authService;
    private final ExecutorService pool = Executors.newFixedThreadPool(4, r -> {
        Thread t = new Thread(r, "chat-sse-" + SEQ.incrementAndGet());
        t.setDaemon(true);
        return t;
    });

    private static final AtomicInteger SEQ = new AtomicInteger();

    public ChatController(Settings settings, HybridSearch hybridSearch, QueryRewriter queryRewriter,
                          RerankClient rerankClient,
                          DirectHit directHit, ChatClient chatClient, TraceLog traceLog,
                          QueryRouter queryRouter, SqlChannel sqlChannel, AuthService authService) {
        this.settings = settings;
        this.hybridSearch = hybridSearch;
        this.queryRewriter = queryRewriter;
        this.rerankClient = rerankClient;
        this.directHit = directHit;
        this.chatClient = chatClient;
        this.traceLog = traceLog;
        this.queryRouter = queryRouter;
        this.sqlChannel = sqlChannel;
        this.authService = authService;
    }

    /** 请求体（Python 版 ChatReq 的对应物）。metadataFilter：{sensitivity, topic, date_from, date_to}。 */
    public static class ChatReq {
        public String app = "interview_coach";
        public String question;
        public Integer top_n;
        public Map<String, Object> metadataFilter;
        /**
         * 多轮对话历史（干净对话页传入）：[{q, a}]，旧→新。默认只进生成不进检索——
         * 追问的召回仍按本轮问题原文跑，检索口径保持可解释；指代消解交给 prompt 里的【对话历史】段。
         * 例外：问题含指代词时 QueryRewriter 会用它做一次检索式改写（`rewrite` 事件可见）。
         */
        public List<Map<String, Object>> history;
        /**
         * 调试模式：true 时额外下发 retrieval/fuse/rerank/prompt 四类事件与 done.raw_answer。
         * 默认 false——普通对话页不需要几十 KB 的检索明细。
         */
        public Boolean debug;
        /** 单次改写开关：null=按 apps.yaml 的 retrieval.query_rewrite 自动判定；true=强制；false=关闭。 */
        public Boolean rewrite;
        /**
         * 强制通道：auto（默认）=按规则判定；rag / sql / multi = 直接采纳（仍做可用性校验）。
         * 调试台与"我要按表查"按钮用它绕开判定，避免为了验证 SQL 通道还要改配置。
         */
        public String route;
    }

    /** 预算裁剪后的上下文装配结果：模型看到什么，由这里决定。 */
    static class Context {
        final List<Map<String, Object>> blocks;   // 真正进模型的块（闸门二与引用只认这批）
        final String text;
        final int tokens;
        final List<Map<String, Object>> messages;
        final int numCtx;
        final int maxNew;
        final String promptName;
        final AppDef appCfg;                       // 修复验证要按同一套 post 闸门口径

        Context(List<Map<String, Object>> blocks, String text, int tokens,
                List<Map<String, Object>> messages, int numCtx, int maxNew, String promptName,
                AppDef appCfg) {
            this.blocks = blocks;
            this.text = text;
            this.tokens = tokens;
            this.messages = messages;
            this.numCtx = numCtx;
            this.maxNew = maxNew;
            this.promptName = promptName;
            this.appCfg = appCfg;
        }
    }

    @PostMapping(value = "/chat", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter chat(@RequestBody ChatReq req, HttpServletRequest request) {
        AppDef appCfg = settings.app(req.app == null ? "interview_coach" : req.app);
        if (appCfg == null) {
            throw new ApiError(404, "应用未定义：" + req.app + "（configs/apps.yaml）");
        }
        if (req.question == null || req.question.trim().isEmpty()) {
            throw new ApiError(422, "问题为空");
        }
        // 登录态在**请求线程**里解析完再交给 SSE 线程：HttpServletRequest 不跨线程使用，
        // 而且这样整轮问答用的是同一个权限快照（不会中途被登出/登录改掉过滤口径）
        AuthUser me = authService.currentUser(request);
        final boolean loggedIn = me != null;
        SseEmitter emitter = new SseEmitter(300_000L);  // 5 分钟上限：长答案也不吊死连接
        pool.execute(() -> {
            try {
                stream(req, appCfg, emitter, loggedIn);
            } catch (Exception e) {
                emitter.complete();
            }
        });
        return emitter;
    }

    private void stream(ChatReq req, AppDef appCfg, SseEmitter emitter, boolean loggedIn) {
        try (java.sql.Connection conn = Db.connect(settings.getDbPath())) {
            String traceId = traceLog.newTraceId();
            boolean debug = Boolean.TRUE.equals(req.debug);

            // ---- 提问前置红线闸门：问题本身含禁词（客户名等）直接拒答，不生成不流式 ----
            List<String> qHits = com.ownrag.generate.RedlineGate.check(req.question, settings);
            // 通过也留痕：观测页要能证明"这一步跑过且通过"，而不是"没这行 = 没执行"
            Map<String, Object> redlineCounters = new LinkedHashMap<>();
            redlineCounters.put("passed", qHits.isEmpty());
            redlineCounters.put("hits", qHits);
            TraceLog.log(conn, traceId, "pre_redline", "ok", null, null, redlineCounters, null);
            if (!qHits.isEmpty()) {
                Map<String, Object> noEv = new LinkedHashMap<>();
                noEv.put("reason", "问题涉及红线禁词，按红线口径拒答，不做任何生成。");
                noEv.put("trace_id", traceId);
                send(emitter, "no_evidence", noEv);
                Map<String, Object> donePayload = new LinkedHashMap<>();
                donePayload.put("citations", new ArrayList<>());
                donePayload.put("source", "gate");
                send(emitter, "done", donePayload);
                logQa(conn, req.app, req.question, "（提问含红线禁词，拒答）", new ArrayList<>(), traceId);
                emitter.complete();
                return;
            }

            List<String> kbs = appCfg.knowledgeBases.isEmpty()
                    ? java.util.Collections.singletonList("default") : appCfg.knowledgeBases;
            Map<String, Object> genCfg = new LinkedHashMap<>();
            genCfg.put("prompt", appCfg.prompt);
            genCfg.put("stream", appCfg.stream);
            genCfg.put("max_ctx_tokens", appCfg.maxCtxTokens);
            genCfg.put("max_new_tokens", appCfg.maxNewTokens);
            Map<String, Object> retCfg = new LinkedHashMap<>();
            retCfg.put("vector_topk", appCfg.vectorTopk);
            retCfg.put("bm25_topk", appCfg.bm25Topk);
            retCfg.put("top_n", appCfg.topN);

            // ---- 直击库：高频题不进 RAG（零检索零生成，答案完全可控）----
            // 关闭时不查库：L1 会为每条候选 embed 一次，关掉的开关不该还收这笔开销
            DirectHit.Hit hit = appCfg.directHitEnabled
                    ? directHit.match(conn, kbs, req.question, 0.86, loggedIn) : null;
            if (hit != null) {
                Map<String, Object> hitCounters = new LinkedHashMap<>();
                hitCounters.put("level", hit.level);
                hitCounters.put("question", hit.question);
                hitCounters.put("answer", clip(hit.answer, 2000));
                hitCounters.put("score", round6(hit.score));
                TraceLog.log(conn, traceId, "direct_hit", "ok", null, null, hitCounters, null);
                Map<String, Object> hitPayload = new LinkedHashMap<>();
                hitPayload.put("level", hit.level);
                hitPayload.put("question", hit.question);
                hitPayload.put("answer", hit.answer);
                hitPayload.put("score", hit.score);
                hitPayload.put("trace_id", traceId);
                send(emitter, "hit", hitPayload);
                Map<String, Object> donePayload = new LinkedHashMap<>();
                donePayload.put("citations", new ArrayList<>());
                donePayload.put("source", "direct_hit");
                send(emitter, "done", donePayload);
                logQa(conn, req.app, req.question, hit.answer, new ArrayList<>(), traceId);
                emitter.complete();
                return;
            }

            // ---- 查询期路由（docs 11-查询路由与多源编排）：先判"该查哪类数据"，再决定走哪条通道 ----
            // routing.enabled=false 时不产生 routeRes，后续行为与改造前逐字一致（可回滚 / A|B）
            RouteResult routeRes = null;
            SqlChannel.Outcome sqlOut = null;
            Long sqlTodoId = null;
            if (appCfg.routingEnabled) {
                routeRes = routeOf(conn, appCfg, kbs, req.question, req.route, loggedIn);
                if (routeRes.usesSql()) {
                    // SQL 用原问题：改写服务召回通道，而结构化查询要的是用户原话里的字面条件
                    try {
                        sqlOut = sqlChannel.run(conn, settings, chatClient, appCfg, req.question, kbs, loggedIn);
                    } catch (Exception e) {
                        // 通道异常=降级，不是整次问答 500：后面还有 RAG 与闸门兜着
                        sqlOut = new SqlChannel.Outcome();
                        sqlOut.degraded = true;
                        sqlOut.note = "SQL 通道异常：" + e.getMessage();
                    }
                    if (sqlOut.degraded) {
                        Map<String, Object> gate = new LinkedHashMap<>();
                        gate.put("stage", "sql_degraded");
                        gate.put("note", sqlOut.note);
                        // 连续失败到阈值 → 入待办。单次失败只加计数，不打扰人（见 SqlFailureTracker 口径）
                        SqlFailureTracker.Outcome fo = trackFailure(conn, req.app, req.question, sqlOut.note);
                        if (fo != null && fo.todoCreated) {
                            sqlTodoId = fo.todoId;
                            gate.put("todo_id", fo.todoId);
                            gate.put("note", sqlOut.note + "（连续失败 " + fo.count + " 次，已入待办 #" + fo.todoId + "）");
                        }
                        send(emitter, "gate", gate);
                    } else if (sqlOut.hasEvidence) {
                        clearFailures(conn, req.app, req.question);
                    }
                }
                Map<String, Object> routeEvent = routeRes.toEvent();
                if (debug && sqlOut != null) {
                    routeEvent.put("detail", sqlOut.detail());   // SQL 全文可能含业务字段：只有 debug 才发
                }
                send(emitter, "route", routeEvent);
                // 路由读过目录/块表，后面要写 trace：先收尾读事务，避免 SQLITE_BUSY_SNAPSHOT
                Db.endRead(conn);
                TraceLog.log(conn, traceId, "route", "ok", routeRes.ms, null, routeRes.toCounters(), null);
            }
            boolean needRag = routeRes == null || routeRes.usesRag();

            // ---- 访问权限闸门（登录态）：未登录只在公开文档中检索 ----
            // 过滤在 SQL 层（先过滤后召回），没权限的块根本不进候选池——不是"进了上下文再叮嘱模型别说"。
            // 同时把"这次少看了什么"如实播报：用户看到的是"还有 N 篇需登录文档没参与"，而不是莫名的空结果。
            long protectedDocs = 0;
            if (!loggedIn) {
                protectedDocs = authService.countProtected(kbs);
                Map<String, Object> accessGate = new LinkedHashMap<>();
                accessGate.put("stage", "access_limited");
                accessGate.put("public_only", true);
                accessGate.put("protected_docs", protectedDocs);
                accessGate.put("note", protectedDocs > 0
                        ? "未登录：本轮只在公开文档中检索；本库另有 " + protectedDocs
                        + " 篇「需登录」文档未参与（登录后可见全部）"
                        : "未登录：本轮只在公开文档中检索（本库暂无「需登录」文档）");
                send(emitter, "gate", accessGate);
            }

            // ---- 检索问句改写：直击库用原问题精确匹配，改写只服务召回通道 ----
            // req.rewrite: null=按 apps.yaml 自动；true=强制；false=关闭
            Boolean rewriteFlag = req.rewrite != null ? req.rewrite
                    : (appCfg.queryRewrite ? null : Boolean.FALSE);
            QueryRewriter.Result rw = needRag
                    ? queryRewriter.rewrite(settings, chatClient, req.question, req.history, rewriteFlag)
                    : QueryRewriter.Result.skipped(req.question, "本轮走 SQL 单通道，不需要改写");
            send(emitter, "rewrite", rw.toEvent());
            // 未触发也落一行：观测页 8 步里的①必须"有这一步"，否则看起来像链路缺环
            Map<String, Object> rwCounters = new LinkedHashMap<>();
            rwCounters.put("triggered", rw.triggered);
            rwCounters.put("method", rw.method);
            rwCounters.put("reason", rw.reason);
            rwCounters.put("original", rw.original);
            rwCounters.put("rewritten", rw.rewritten);
            rwCounters.put("history_turns", rw.historyTurns);
            TraceLog.log(conn, traceId, "rewrite", "ok", rw.ms, null, rwCounters, null);
            String query = rw.triggered ? rw.rewritten : rw.original;

            // ---- 检索 →（降级可见）→ 重排；多库 IN + 个人维度过滤（先过滤后召回）----
            long tRetrieve = System.nanoTime();
            Map<String, Object> result = new LinkedHashMap<>();
            List<Map<String, Object>> candidates = new ArrayList<>();
            List<Map<String, Object>> rrfOrder = new ArrayList<>();
            RerankClient.RerankResult reranked = null;
            String skippedReason = null;
            if (needRag) {
                // RAG 口径统一收口：不吃 Excel 行卡片（明细数据走 SQL 通道，见 docs 10/11）
                result = hybridSearch.search(conn, settings, kbs, query,
                        intOf(retCfg.get("vector_topk"), 20), intOf(retCfg.get("bm25_topk"), 20),
                        intOf(retCfg.get("top_n"), 12),
                        HybridSearch.withAccess(HybridSearch.ragFilter(req.metadataFilter), loggedIn));
                candidates = (List<Map<String, Object>>) result.getOrDefault("candidates", new ArrayList<>());
                skippedReason = (String) result.get("vector_skipped_reason");
                if (skippedReason != null && !skippedReason.isEmpty()) {
                    Map<String, Object> gate = new LinkedHashMap<>();
                    gate.put("stage", "retrieval_degraded");
                    gate.put("note", skippedReason);
                    send(emitter, "gate", gate);
                }
                // 融合顺序快照：rerank 会原地写分数并重排，不先留一份就无法展示"名次怎么变了"
                rrfOrder = new ArrayList<>(candidates);
                if (debug) {
                    send(emitter, "retrieval", retrievalEvent(result, query));
                    send(emitter, "fuse", fuseEvent(rrfOrder));
                }
                reranked = rerankTopN(query, req.top_n, appCfg.topN, candidates);
                if (debug) {
                    send(emitter, "rerank", rerankEvent(rrfOrder, reranked));
                }
                candidates = reranked.candidates;
            }

            // ---- SQL 证据块并进同一批候选：它是"算出来的事实"，排最前，预算裁剪不该先裁它 ----
            if (sqlOut != null) {
                if (sqlOut.hasEvidence) {
                    List<Map<String, Object>> merged = new ArrayList<>(sqlOut.candidates);
                    merged.addAll(candidates);
                    candidates = merged;
                } else if (!needRag) {
                    // 只走 SQL 却拿不到证据：这是"缺数据/缺目标"，必须如实说，不许悄悄回落 RAG 编答案
                    Map<String, Object> noEv = new LinkedHashMap<>();
                    noEv.put("reason", sqlOut.note.isEmpty() ? "库中没有可查询的结构化数据" : sqlOut.note);
                    noEv.put("reason_code", "no_table");
                    noEv.put("path", sqlOut.targets);
                    noEv.put("trace_id", traceId);
                    send(emitter, "no_evidence", noEv);
                    Map<String, Object> donePayload = new LinkedHashMap<>();
                    donePayload.put("citations", new ArrayList<>());
                    donePayload.put("source", "gate");
                    send(emitter, "done", donePayload);
                    logQa(conn, req.app, req.question, "（无结构化数据可查，未生成）", new ArrayList<>(), traceId);
                    emitter.complete();
                    return;
                }
            }
            // 统一编号：SQL 块接在检索候选之后，保证"块 N"全文唯一（SQL 排前是优先级，不是编号）
            applySqlOrdinals(candidates);

            // ---- 越权二次校验①（进模型前）：独立回查 documents，剔除任何"当前会话读不到"的块 ----
            // 上游过滤是"SQL 写对才生效"的约定；这里 fail-closed 兜底，防止将来新增通道漏带过滤条件。
            // 放在生成前而不是生成后：流式 token 一旦吐出去就收不回来，只有进模型前挡住才有意义。
            AccessPostCheck.Result accessPre = AccessPostCheck.filterCandidates(conn, candidates, loggedIn);
            if (accessPre.droppedBlocks > 0) {
                Map<String, Object> gate = new LinkedHashMap<>();
                gate.put("stage", "access_precheck");
                gate.put("dropped_blocks", accessPre.droppedBlocks);
                gate.put("dropped_docs", accessPre.droppedDocIds.size());
                gate.put("note", "安全校验：候选里有 " + accessPre.droppedBlocks
                        + " 块内容属于「需登录」文档，已在送入模型前剔除；登录后可检索全部文档");
                send(emitter, "gate", gate);
            }

            Map<String, Object> counters = new LinkedHashMap<>();
            counters.put("candidates", candidates.size());
            counters.put("access_precheck", accessPre.toCounters());
            counters.put("rerank", reranked == null ? "未重排（无检索通道）" : reranked.note);
            counters.put("query", query);
            // 权限口径落 trace：事后复盘"为什么这块没被召回"时，先看当时是不是未登录
            counters.put("access_public_only", !loggedIn);
            counters.put("access_protected_docs", protectedDocs);
            if (routeRes != null) {
                counters.put("route", routeRes.route);
                counters.put("route_layer", routeRes.layer);
                counters.put("route_confidence", routeRes.confidence);
            }
            if (sqlOut != null) {
                counters.put("sql", sqlOut.detail());
            }
            if (sqlTodoId != null) {
                counters.put("sql_todo_id", sqlTodoId);
            }
            // ---- ②-⑤ 明细落表：观测页要能脱离当时那一次会话，事后逐块复盘 ----
            Map<String, Object> retrievalPath = (Map<String, Object>) result.get("retrieval_path");
            if (retrievalPath != null) {
                counters.putAll(retrievalPath);
            }
            @SuppressWarnings("unchecked")
            Map<String, Object> rawChannels = (Map<String, Object>) result.get("channels");
            counters.put("vector_skipped_reason", skippedReason);
            counters.put("bm25_top", briefHits(rawChannels == null ? null
                    : (List<Map<String, Object>>) rawChannels.get("bm25"), 120));
            counters.put("vector_top", briefHits(rawChannels == null ? null
                    : (List<Map<String, Object>>) rawChannels.get("vector"), 120));
            counters.put("fuse_order", fuseEvent(rrfOrder).get("order"));
            counters.put("rerank_order", reranked == null ? new ArrayList<>()
                    : rerankEvent(rrfOrder, reranked).get("order"));
            // 耗时落 trace：复盘要能回答"检索慢还是生成慢"
            TraceLog.log(conn, traceId, "retrieve", "ok", elapsedMs(tRetrieve), null, counters, null);

            // ---- 闸门一（生成前）：候选不足不进模型 ----
            Gates.GateResult pre = Gates.sufficiencyCheck(candidates);
            if (!pre.passed) {
                // 未登录时的空结果有两种可能：语料里真没有，或"有但你没登录"。后者必须说清楚，
                // 否则用户会以为知识库缺内容而去重复上传（同一份语料再传一次仍是 protected）。
                String reason = pre.reason;
                if (!loggedIn && protectedDocs > 0) {
                    reason = reason + "（注意：当前未登录，只检索了公开文档；另有 " + protectedDocs
                            + " 篇「需登录」文档未参与，登录后可检索全部）";
                }
                Map<String, Object> noEv = new LinkedHashMap<>();
                noEv.put("reason", reason);
                noEv.put("public_only", !loggedIn);
                noEv.put("protected_docs", protectedDocs);
                noEv.put("path", result.get("retrieval_path"));
                noEv.put("trace_id", traceId);
                send(emitter, "no_evidence", noEv);
                Map<String, Object> donePayload = new LinkedHashMap<>();
                donePayload.put("citations", new ArrayList<>());
                donePayload.put("source", "gate");
                send(emitter, "done", donePayload);
                logQa(conn, req.app, req.question, "（无依据，未生成）", new ArrayList<>(), traceId);
                emitter.complete();
                return;
            }

            // ---- 上下文预算 + 渲染 ----
            String historyText = historyTextOf(req.history);
            int[] limits = Budget.resolveLimits(settings, genCfg);
            int numCtx = limits[0];
            int maxNew = limits[1];
            Budget.ContextPlan plan = Budget.planContext(candidates, req.question,
                    appCfg.prompt, numCtx, maxNew, settings, historyText);
            Budget.BudgetResult fitted = plan.fitted;
            if (!fitted.dropped.isEmpty() || fitted.truncated) {
                // 降级可见：丢了几块、截了多少、预算怎么算的，全部随事件回传
                Map<String, Object> gate = new LinkedHashMap<>();
                gate.put("stage", "context_budget");
                gate.put("kept", fitted.blocks.size());
                gate.put("dropped", fitted.dropped.size());
                gate.put("truncated", fitted.truncated);
                gate.put("ctx_tokens", fitted.tokens);
                gate.put("num_ctx", numCtx);
                gate.put("prompt_overhead", plan.promptOverhead);
                gate.put("available", plan.available);
                gate.put("reserved_output", maxNew);
                send(emitter, "gate", gate);
            }
            List<Map<String, Object>> messages =
                    PromptRenderer.render(settings, plan.promptName, req.question, fitted.text,
                            "history", historyText);
            Context ctx = new Context(fitted.blocks, fitted.text, fitted.tokens,
                    messages, numCtx, maxNew, plan.promptName, appCfg);
            candidates = ctx.blocks;  // 闸门二与引用只认模型真正看到的块
            send(emitter, "ctx", ctxEvent(candidates));
            // 先留快照再发：debug 关闭时也要能把"发给模型什么"落到 trace（观测页第⑦步）
            Map<String, Object> genPrompt = promptEvent("generate", ctx.messages, ctx.promptName,
                    ctx.blocks.size(), ctx.tokens, ctx.numCtx, ctx.maxNew);
            if (debug) {
                // 发给模型的是什么，逐字可见（含 system 全文与预算裁剪后的资料正文）
                send(emitter, "prompt", genPrompt);
            }

            // ---- 流式生成 ----
            long tGenerate = System.nanoTime();
            StringBuilder answer = new StringBuilder();
            try {
                final StringBuilder sink = answer;
                chatClient.chatStream(settings, ctx.messages,
                        null, ctx.numCtx, 0.2, ctx.maxNew,
                        piece -> {
                            sink.append(piece);
                            Map<String, Object> token = new LinkedHashMap<>();
                            token.put("t", piece);
                            send(emitter, "token", token);
                        });
            } catch (ChatClient.ChatError e) {
                Map<String, Object> err = new LinkedHashMap<>();
                err.put("message", e.getMessage());
                err.put("trace_id", traceId);
                send(emitter, "error", err);
                TraceLog.log(conn, traceId, "generate", "fail", null, null, null, e.getMessage());
                emitter.complete();
                return;
            }
            String answerText = answer.toString();

            // ---- 闸门二（生成后）：post 闸门全跑（引用真实性 + 红线禁词），违规合并带反馈重答一次 ----
            List<String> violations = collectViolations(answerText, candidates, appCfg);
            Gates.GateResult post = new Gates.GateResult("post", violations.isEmpty(),
                    violations.isEmpty() ? "闸门二通过" : "闸门二违规 " + violations.size() + " 项", violations);
            Map<String, Object> postGate = new LinkedHashMap<>();
            postGate.put("stage", "post");
            postGate.put("passed", post.passed);
            postGate.put("reason", post.reason);
            postGate.put("violations", post.violations);
            send(emitter, "gate", postGate);
            String firstPass = answerText;  // 闸门重答前的首答（调试面板用来对比）
            boolean repaired = false;
            Map<String, Object> repairPrompt = null;
            if (!post.passed) {
                RepairOutcome fixed = repairAnswer(ctx, answerText, post, candidates, genCfg,
                        emitter, debug);
                repaired = true;
                answerText = fixed.answer;
                post = fixed.post;
                repairPrompt = fixed.prompt;
            }

            // ---- 越权二次校验②（生成后）：答案点名了"当前会话读不到"的文档 → 撤回 ----
            // 流式场景下已经吐出的字收不回来，所以这里的价值是：不把它写进 citations / trace / qa_log，
            // 并给客户端一个明确的撤回信号（前端据此把正文换成提示），同时把结论落 trace 供复盘。
            AccessPostCheck.Result accessPost = AccessPostCheck.checkAnswer(conn, answerText, candidates, kbs, loggedIn);
            boolean retracted = !accessPost.passed;
            if (retracted) {
                Map<String, Object> gate = new LinkedHashMap<>();
                gate.put("stage", "access_blocked");
                gate.put("violations", accessPost.violations);
                gate.put("public_only", !loggedIn);
                gate.put("note", "安全校验：本轮答案涉及你无权访问的文档，已撤回；"
                        + (loggedIn ? "请确认文档权限配置" : "登录后可查询与访问全部文档"));
                send(emitter, "gate", gate);
                answerText = AccessPostCheck.retractedAnswer();
            }

            List<Map<String, Object>> cites = retracted ? new ArrayList<>() : citationsOf(candidates);
            Map<String, Object> done = new LinkedHashMap<>();
            done.put("trace_id", traceId);
            done.put("answer", answerText);
            done.put("citations", cites);
            if (retracted) {
                done.put("retracted", true);
                done.put("retract_note", "答案涉及无权访问的内容，已拦截");
            }
            if (debug) {
                // 首答同样遮住：debug=true 对匿名用户也开放，越权内容不能借调试面板漏出去
                done.put("raw_answer", retracted ? "（首答含越权内容，已拦截不展示）" : firstPass);
                done.put("gate_post_passed", post.passed);
            }
            send(emitter, "done", done);
            // ---- ⑥-⑧ 明细落表：上下文块、实际 prompt、最终答案与闸门结论 ----
            Map<String, Object> budgetInfo = new LinkedHashMap<>();
            budgetInfo.put("kept", fitted.blocks.size());
            budgetInfo.put("dropped", fitted.dropped.size());
            budgetInfo.put("dropped_ids", fitted.dropped);
            budgetInfo.put("truncated", fitted.truncated);
            budgetInfo.put("ctx_tokens", fitted.tokens);
            budgetInfo.put("num_ctx", numCtx);
            budgetInfo.put("prompt_overhead", plan.promptOverhead);
            budgetInfo.put("available", plan.available);
            budgetInfo.put("reserved_output", maxNew);

            Map<String, Object> genCounters = new LinkedHashMap<>();
            genCounters.put("chars", answerText.length());
            genCounters.put("gate_post", post.passed);
            genCounters.put("gate_post_reason", post.reason);
            genCounters.put("violations", post.violations);
            genCounters.put("repaired", repaired);
            genCounters.put("ctx_blocks", candidates.size());
            genCounters.put("ctx_tokens", ctx.tokens);
            genCounters.put("num_ctx", ctx.numCtx);
            genCounters.put("reserved_output", ctx.maxNew);
            genCounters.put("budget", budgetInfo);
            genCounters.put("ctx", ctxEvent(candidates).get("candidates"));
            genCounters.put("prompt", tracePrompt(genPrompt));
            if (repairPrompt != null) {
                genCounters.put("prompt_repair", tracePrompt(repairPrompt));
            }
            genCounters.put("answer", clip(answerText, 4000));
            // 撤回时首答同样不落库：trace/qa_log 会被观测页与别人读到，越权内容不能在库里留副本
            genCounters.put("first_answer", retracted ? "（首答含越权内容，已拦截不落库）" : clip(firstPass, 4000));
            genCounters.put("citations", cites);
            genCounters.put("access_postcheck", accessPost.toCounters());
            TraceLog.log(conn, traceId, "generate", "ok", elapsedMs(tGenerate), null, genCounters, null);
            logQa(conn, req.app, req.question, answerText, candidates, traceId);
            emitter.complete();
        } catch (Exception e) {
            // 兜底必须留痕：吞掉的 NPE 会让"答案对不对"无从归因
            org.slf4j.LoggerFactory.getLogger(ChatController.class)
                    .error("[chat] 服务内部错误", e);
            Map<String, Object> err = new LinkedHashMap<>();
            err.put("message", "服务内部错误：" + e.getMessage());
            send(emitter, "error", err);
            emitter.complete();
        }
    }

    /** 收集 post 闸门全部违规（引用真实性 + 红线禁词）。 */
    private List<String> collectViolations(String answer, List<Map<String, Object>> candidates,
                                          AppDef appCfg) {
        List<String> violations = new ArrayList<>();
        for (String gateName : appCfg.postGates) {
            if ("citation_check".equals(gateName)) {
                Gates.GateResult r = Gates.citationCheck(answer, candidates);
                if (!r.passed) {
                    violations.addAll(r.violations);
                }
            } else if ("redline_check".equals(gateName)) {
                violations.addAll(com.ownrag.generate.RedlineGate.check(answer, settings));
            }
        }
        return violations;
    }

    /** 闸门二违规 → 带错误反馈重答一次；只有"通过"或"违规更少"才采纳重答；
     *  红线禁词不可修复时直接拒答——绝不把带禁词的答案交付给用户。 */
    private RepairOutcome repairAnswer(Context ctx, String answer, Gates.GateResult post,
                                       List<Map<String, Object>> candidates,
                                       Map<String, Object> genCfg, SseEmitter emitter, boolean debug) {
        List<Map<String, Object>> repair = new ArrayList<>(ctx.messages);
        Map<String, Object> assistant = new LinkedHashMap<>();
        assistant.put("role", "assistant");
        assistant.put("content", answer);
        repair.add(assistant);
        Map<String, Object> user = new LinkedHashMap<>();
        user.put("role", "user");
        String redlineNote = post.violations.stream().anyMatch(v -> v.contains("禁词"))
                ? "，红线禁词（客户名、内网信息等）任何形式都不得输出" : "";
        user.put("content", "你的上一版回答存在以下问题：" + String.join("；", post.violations)
                + redlineNote + "。请重答：只保留能被候选块支持的结论，每个结论标注 [来源: 块N]。");
        repair.add(user);
        // 第二次调用的完整入参：重答靠的是"违规清单"这段反馈；无论 debug 都要留快照给观测页
        Map<String, Object> repairPrompt = promptEvent("repair", repair, ctx.promptName,
                ctx.blocks.size(), ctx.tokens, ctx.numCtx, ctx.maxNew);
        if (debug) {
            send(emitter, "prompt", repairPrompt);
        }
        try {
            String answer2 = chatClient.chat(settings, repair, null, ctx.numCtx, 0.2, ctx.maxNew);
            List<String> v2 = collectViolations(answer2, candidates, appCfgOf(ctx));
            Gates.GateResult post2 = new Gates.GateResult("post", v2.isEmpty(),
                    v2.isEmpty() ? "闸门二通过" : "闸门二违规 " + v2.size() + " 项", v2);
            if (post2.passed || v2.size() < post.violations.size()) {
                Map<String, Object> token = new LinkedHashMap<>();
                token.put("t", answer2);
                token.put("repaired", true);
                send(emitter, "token", token);
                return new RepairOutcome(answer2, post2, repairPrompt);
            }
            // 修复后仍有违规（尤其红线禁词复述）：拒答，不交付带禁词的答案
            Map<String, Object> gate = new LinkedHashMap<>();
            gate.put("stage", "redline_refused");
            gate.put("note", "修复后仍含红线违规，已按规则拒答");
            send(emitter, "gate", gate);
            return new RepairOutcome("该问题涉及红线范围（客户名、内网信息等），我不能作答。"
                    + "如需方法论层面的信息，可以换一种不含具体名称的方式提问。", post2, repairPrompt);
        } catch (ChatClient.ChatError e) {
            Map<String, Object> gate = new LinkedHashMap<>();
            gate.put("stage", "repair_failed");
            gate.put("note", String.valueOf(e.getMessage()));
            send(emitter, "gate", gate);
            return new RepairOutcome("（引用校验未通过，已按规则拒答原答案。请缩小问题范围重试。）",
                    post, repairPrompt);
        }
    }

    /** 当前请求的 app 定义（修复验证要按同一套 post 闸门口径）。 */
    private AppDef appCfgOf(Context ctx) {
        return ctx.appCfg;
    }

    private static class RepairOutcome {
        final String answer;
        final Gates.GateResult post;
        final Map<String, Object> prompt;

        RepairOutcome(String answer, Gates.GateResult post, Map<String, Object> prompt) {
            this.answer = answer;
            this.post = post;
            this.prompt = prompt;
        }
    }

    /** 历史轮次 → prompt 注入文本：最多 4 轮、每条截断，超量直接丢旧的（预算公式会把它算进开销）。 */
    static String historyTextOf(List<Map<String, Object>> history) {
        if (history == null || history.isEmpty()) {
            return "（无，本轮为首轮）";
        }
        List<Map<String, Object>> turns = history.size() > 4
                ? history.subList(history.size() - 4, history.size()) : history;
        StringBuilder sb = new StringBuilder();
        for (Map<String, Object> t : turns) {
            String q = clip(t.get("q"), 300);
            String a = clip(t.get("a"), 400);
            if (q.isEmpty() && a.isEmpty()) {
                continue;
            }
            sb.append("用户：").append(q).append('\n');
            sb.append("分身：").append(a).append('\n');
            sb.append("——\n");
        }
        return sb.length() == 0 ? "（无，本轮为首轮）" : sb.toString();
    }

    private static String clip(Object o, int max) {
        String s = o == null ? "" : String.valueOf(o).trim();
        return s.length() <= max ? s : s.substring(0, max) + "…";
    }

    /**
     * 记账失败绝不能让问答失败：吞掉异常返回 null（本方法唯一职责是计数，答不答得出来更重要）。
     * 写之前先收尾读快照，否则连续 SELECT 之后 UPDATE 会撞 SQLITE_BUSY_SNAPSHOT。
     */
    private SqlFailureTracker.Outcome trackFailure(java.sql.Connection conn, String app,
                                                   String question, String note) {
        try {
            Db.endRead(conn);
            return SqlFailureTracker.recordFailure(conn, app, question, note);
        } catch (Exception e) {
            return null;
        }
    }

    private void clearFailures(java.sql.Connection conn, String app, String question) {
        try {
            Db.endRead(conn);
            SqlFailureTracker.recordSuccess(conn, app, question);
        } catch (Exception ignored) {
            // 同上：计数清零失败不影响本次回答
        }
    }

    /** 路由异常不该让整次问答 500：降级为 RAG 并在 route 事件里写明原因（降级可见）。 */
    private RouteResult routeOf(java.sql.Connection conn, AppDef app, List<String> kbs,
                                String question, String forced, boolean loggedIn) {
        try {
            // 登录态影响"SQL 通道可不可用"：未登录时受限 Excel 表不进目录，路由就不会把人引向一条空通道
            return queryRouter.route(conn, app, kbs, question, forced, loggedIn);
        } catch (Exception e) {
            RouteResult r = new RouteResult();
            r.layer = "fallback";
            r.route = RouteResult.RAG;
            r.confidence = 0;
            r.reason = "路由异常，回落 RAG：" + e.getMessage();
            r.availability.put("sql", false);
            r.availability.put("rag", true);
            r.availability.put("web", false);
            return r;
        }
    }

    /**
     * SQL 证据块的编号接在检索候选之后。
     * 为什么要编号而不是沿用 doc 内 ordinal：`[块N]` 是模型引用与闸门校验的唯一锚点，
     * 两路来源都从 1 开始编号会出现"块1"指两份不同证据的歧义。
     */
    private static void applySqlOrdinals(List<Map<String, Object>> candidates) {
        int max = 0;
        for (Map<String, Object> c : candidates) {
            if ("sql".equals(c.get("kind")) || !(c.get("ordinal") instanceof Number)) {
                continue;
            }
            max = Math.max(max, ((Number) c.get("ordinal")).intValue());
        }
        for (Map<String, Object> c : candidates) {
            if ("sql".equals(c.get("kind"))) {
                c.put("ordinal", ++max);
            }
        }
    }

    private RerankClient.RerankResult rerankTopN(String question, Integer reqTopN, int appTopN,
                                                 List<Map<String, Object>> candidates) {
        // Python 口径：top_n = top_n//2*2 or 8（偶数化）
        int base = reqTopN != null ? reqTopN : appTopN;
        int topN = base / 2 * 2;
        if (topN == 0) {
            topN = 8;
        }
        return rerankClient.rerank(settings, question, candidates, topN);
    }

    // ---------------- 调试事件装配（debug=true 才发）：每一步"看得到"才算可归因 ----------------

    /** 两路原始命中：哪一路把它捞上来的、分数多少、正文讲什么。 */
    @SuppressWarnings("unchecked")
    private static Map<String, Object> retrievalEvent(Map<String, Object> result, String query) {
        Map<String, Object> channels = (Map<String, Object>) result.get("channels");
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("query", query);
        out.put("path", result.get("retrieval_path"));
        out.put("vector_skipped_reason", result.get("vector_skipped_reason"));
        out.put("bm25", briefHits(channels == null ? null
                : (List<Map<String, Object>>) channels.get("bm25"), 160));
        out.put("vector", briefHits(channels == null ? null
                : (List<Map<String, Object>>) channels.get("vector"), 160));
        return out;
    }

    /** 混合（RRF）融合后的顺序——rerank 之前的原始名次。 */
    private static Map<String, Object> fuseEvent(List<Map<String, Object>> order) {
        List<Map<String, Object>> rows = new ArrayList<>();
        int rank = 0;
        for (Map<String, Object> c : order) {
            Map<String, Object> r = new LinkedHashMap<>();
            r.put("rank", rank++);
            r.put("chunk_id", c.get("chunk_id"));
            r.put("doc_id", c.get("doc_id"));
            r.put("doc_name", c.get("doc_name"));
            r.put("ordinal", c.get("ordinal"));
            r.put("rrf", round6(c.get("rrf")));
            r.put("channels", channelBrief(c.get("channels")));
            r.put("chars", textLength(c.get("text")));
            r.put("preview", clipPreview(c.get("text"), 140));
            rows.add(r);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("count", rows.size());
        out.put("order", rows);
        return out;
    }

    /** 重排后的顺序：带 prev_rank，前端才能画"谁上去了谁下去了"。 */
    private static Map<String, Object> rerankEvent(List<Map<String, Object>> rrfOrder,
                                                   RerankClient.RerankResult reranked) {
        Map<String, Integer> prev = new LinkedHashMap<>();
        int i = 0;
        for (Map<String, Object> c : rrfOrder) {
            prev.put(String.valueOf(c.get("chunk_id")), i++);
        }
        List<Map<String, Object>> rows = new ArrayList<>();
        int rank = 0;
        for (Map<String, Object> c : reranked.candidates) {
            String cid = String.valueOf(c.get("chunk_id"));
            Map<String, Object> r = new LinkedHashMap<>();
            r.put("rank", rank++);
            r.put("prev_rank", prev.containsKey(cid) ? prev.get(cid) : -1);  // -1 = rerank 前不在候选池
            r.put("chunk_id", c.get("chunk_id"));
            r.put("doc_id", c.get("doc_id"));
            r.put("doc_name", c.get("doc_name"));
            r.put("ordinal", c.get("ordinal"));
            r.put("rrf", round6(c.get("rrf")));
            r.put("rerank_score", round6(c.get("rerank_score")));
            r.put("channels", channelBrief(c.get("channels")));
            r.put("chars", textLength(c.get("text")));
            r.put("preview", clipPreview(c.get("text"), 140));
            rows.add(r);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("note", reranked.note);
        out.put("before", rrfOrder.size());
        out.put("after", reranked.candidates.size());
        out.put("dropped", Math.max(0, rrfOrder.size() - reranked.candidates.size()));
        out.put("order", rows);
        return out;
    }

    /** 发给大模型的全部 messages（system + user 全文），逐字回传。 */
    private static Map<String, Object> promptEvent(String phase, List<Map<String, Object>> messages,
                                                   String promptName, int blocks, int ctxTokens,
                                                   int numCtx, int maxNew) {
        List<Map<String, Object>> msgs = new ArrayList<>();
        int chars = 0;
        for (Map<String, Object> m : messages) {
            String content = m.get("content") == null ? "" : String.valueOf(m.get("content"));
            Map<String, Object> one = new LinkedHashMap<>();
            one.put("role", m.get("role"));
            one.put("content", content);
            one.put("chars", content.length());
            chars += content.length();
            msgs.add(one);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("phase", phase);        // generate = 首答；repair = 闸门二重答
        out.put("prompt", promptName);
        out.put("ctx_blocks", blocks);
        out.put("ctx_tokens", ctxTokens);
        out.put("num_ctx", numCtx);
        out.put("max_new", maxNew);
        out.put("chars", chars);
        out.put("messages", msgs);
        return out;
    }

    /**
     * 落表用的 prompt 快照：每条 message 的 content 单独截断（4000 字），
     * 保持阶段/窗口等元信息完整。SSE 仍发全量，只有 trace 侧做限长。
     */
    @SuppressWarnings("unchecked")
    private static Map<String, Object> tracePrompt(Map<String, Object> promptEvent) {
        Map<String, Object> out = new LinkedHashMap<>(promptEvent);
        List<Map<String, Object>> rows = new ArrayList<>();
        for (Map<String, Object> m : (List<Map<String, Object>>) promptEvent.get("messages")) {
            String content = m.get("content") == null ? "" : String.valueOf(m.get("content"));
            Map<String, Object> one = new LinkedHashMap<>();
            one.put("role", m.get("role"));
            one.put("chars", content.length());
            one.put("content", content.length() > 4000
                    ? content.substring(0, 4000) + "…（trace 截断，全文在问答调试页可见）" : content);
            rows.add(one);
        }
        out.put("messages", rows);
        return out;
    }

    private static List<Map<String, Object>> briefHits(List<Map<String, Object>> hits, int previewChars) {
        List<Map<String, Object>> out = new ArrayList<>();
        if (hits == null) {
            return out;
        }
        int rank = 0;
        for (Map<String, Object> h : hits) {
            Map<String, Object> b = new LinkedHashMap<>();
            b.put("rank", rank++);
            b.put("chunk_id", h.get("chunk_id"));
            b.put("doc_id", h.get("doc_id"));
            b.put("doc_name", h.get("doc_name"));
            b.put("ordinal", h.get("ordinal"));
            b.put("score", round6(h.get("score")));
            b.put("chars", h.get("chars"));
            b.put("preview", clipPreview(h.get("preview"), previewChars));
            out.add(b);
        }
        return out;
    }

    private static List<Map<String, Object>> channelBrief(Object channels) {
        List<Map<String, Object>> out = new ArrayList<>();
        if (!(channels instanceof List)) {
            return out;
        }
        for (Object o : (List<?>) channels) {
            if (!(o instanceof Map)) {
                continue;
            }
            Map<?, ?> m = (Map<?, ?>) o;
            Map<String, Object> ch = new LinkedHashMap<>();
            ch.put("channel", m.get("channel"));
            ch.put("score", round6(m.get("score")));
            out.add(ch);
        }
        return out;
    }

    /** 分数保留 6 位：rrf 量级 1e-2~1e-3，四舍五入太多就分不出名次差。 */
    private static Object round6(Object v) {
        if (!(v instanceof Number)) {
            return v;
        }
        return Math.round(((Number) v).doubleValue() * 1e6) / 1e6;
    }

    private static int textLength(Object text) {
        return text == null ? 0 : String.valueOf(text).length();
    }

    private static String clipPreview(Object v, int max) {
        String s = v == null ? "" : String.valueOf(v);
        return s.length() <= max ? s : s.substring(0, max) + "…";
    }

    private Map<String, Object> ctxEvent(List<Map<String, Object>> candidates) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (Map<String, Object> c : candidates) {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("ordinal", c.get("ordinal"));
            item.put("chunk_id", c.get("chunk_id"));
            item.put("doc_id", c.get("doc_id"));
            item.put("doc_name", c.get("doc_name"));
            item.put("anchors", c.get("anchors"));
            item.put("score", c.get("rrf"));
            item.put("channels", c.get("channels"));
            String text = c.get("text") == null ? "" : String.valueOf(c.get("text"));
            item.put("preview", text.substring(0, Math.min(160, text.length())));
            out.add(item);
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("candidates", out);
        return payload;
    }

    private static List<Map<String, Object>> citationsOf(List<Map<String, Object>> candidates) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (Map<String, Object> c : candidates) {
            if (c.get("ordinal") instanceof Number) {
                Map<String, Object> cite = new LinkedHashMap<>();
                cite.put("ordinal", c.get("ordinal"));
                cite.put("doc_id", c.get("doc_id"));
                cite.put("doc_name", c.get("doc_name"));
                cite.put("anchors", c.get("anchors"));
                out.add(cite);
            }
        }
        return out;
    }

    private void logQa(java.sql.Connection conn, String app, String question, String answer,
                       List<Map<String, Object>> hits, String traceId) {
        try (java.sql.PreparedStatement ps = conn.prepareStatement(
                "INSERT INTO qa_log(app, question, hit_chunks_json, answer, feedback, trace_id) "
                        + "VALUES (?,?,?,?,?,?)")) {
            List<String> ids = new ArrayList<>();
            for (Map<String, Object> h : hits) {
                ids.add(String.valueOf(h.get("chunk_id")));
            }
            ps.setString(1, app);
            ps.setString(2, question);
            ps.setString(3, Json.write(ids));
            ps.setString(4, answer);
            ps.setString(5, null);
            ps.setString(6, traceId);
            ps.executeUpdate();
            conn.commit();
        } catch (Exception e) {
            System.err.println("[qa_log] 落库失败: " + e.getMessage());
        }
    }

    private static void send(SseEmitter emitter, String event, Object payload) {
        try {
            // 纯字符串发送：Spring 直接写原始文本（带 MediaType 会经 Jackson 二次编码成 JSON 字符串字面量）
            emitter.send(SseEmitter.event().name(event).data(Json.write(payload)));
        } catch (IOException | IllegalStateException e) {
            // 客户端断开 = 停止发送即可（管道继续跑完落库，不吊死后台线程）
            throw new IllegalStateException("SSE 客户端断开", e);
        }
    }

    /** 纳秒起点 → 0.1ms 精度的耗时（trace 的 ms 列：复盘要能分辨"检索慢"还是"生成慢"）。 */
    private static double elapsedMs(long t0) {
        return Math.round((System.nanoTime() - t0) / 1e5) / 10.0;
    }

    private static int intOf(Object o, int def) {
        return o instanceof Number ? ((Number) o).intValue() : def;
    }

    private static Map<String, Object> single(String k, Object v) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put(k, v);
        return m;
    }

    @PreDestroy
    public void shutdown() {
        pool.shutdown();
    }
}
