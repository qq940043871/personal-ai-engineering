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

import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

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
import com.ownrag.retrieve.RerankClient;
import com.ownrag.util.Ids;
import com.ownrag.util.Json;

/**
 * 问答路由（SSE 流式，Python 版 routes_chat.py 的平移）：
 * 直击库 → 混合检索 → rerank → 闸门一 → 预算 → 流式生成 → 闸门二 → 修复。
 *
 * SSE 事件契约（顺序不可变，前端按序消费）：
 *   hit（直击库命中）→ gate(retrieval_degraded) → ctx（候选依据）→ token（流式增量，repaired 标记）
 *   → gate(post/context_budget/repair_failed) → no_evidence（无依据，合法答案）→ done → error。
 * 分层动作各自成私有方法（与 Python 版 _search/_rerank/_fit_context/_repair_answer/_log_qa 对齐）。
 */
@RestController
public class ChatController {

    private final Settings settings;
    private final HybridSearch hybridSearch;
    private final RerankClient rerankClient;
    private final DirectHit directHit;
    private final ChatClient chatClient;
    private final TraceLog traceLog;
    private final ExecutorService pool = Executors.newFixedThreadPool(4, r -> {
        Thread t = new Thread(r, "chat-sse-" + SEQ.incrementAndGet());
        t.setDaemon(true);
        return t;
    });

    private static final AtomicInteger SEQ = new AtomicInteger();

    public ChatController(Settings settings, HybridSearch hybridSearch, RerankClient rerankClient,
                          DirectHit directHit, ChatClient chatClient, TraceLog traceLog) {
        this.settings = settings;
        this.hybridSearch = hybridSearch;
        this.rerankClient = rerankClient;
        this.directHit = directHit;
        this.chatClient = chatClient;
        this.traceLog = traceLog;
    }

    /** 请求体（Python 版 ChatReq 的对应物）。metadataFilter：{sensitivity, topic, date_from, date_to}。 */
    public static class ChatReq {
        public String app = "policy_qa";
        public String question;
        public Integer top_n;
        public Map<String, Object> metadataFilter;
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

        Context(List<Map<String, Object>> blocks, String text, int tokens,
                List<Map<String, Object>> messages, int numCtx, int maxNew, String promptName) {
            this.blocks = blocks;
            this.text = text;
            this.tokens = tokens;
            this.messages = messages;
            this.numCtx = numCtx;
            this.maxNew = maxNew;
            this.promptName = promptName;
        }
    }

    @PostMapping(value = "/chat", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter chat(@RequestBody ChatReq req) {
        AppDef appCfg = settings.app(req.app == null ? "policy_qa" : req.app);
        if (appCfg == null) {
            throw new ApiError(404, "应用未定义：" + req.app + "（configs/apps.yaml）");
        }
        if (req.question == null || req.question.trim().isEmpty()) {
            throw new ApiError(422, "问题为空");
        }
        SseEmitter emitter = new SseEmitter(300_000L);  // 5 分钟上限：长答案也不吊死连接
        pool.execute(() -> {
            try {
                stream(req, appCfg, emitter);
            } catch (Exception e) {
                emitter.complete();
            }
        });
        return emitter;
    }

    private void stream(ChatReq req, AppDef appCfg, SseEmitter emitter) {
        try (java.sql.Connection conn = Db.connect(settings.getDbPath())) {
            String traceId = traceLog.newTraceId();
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
                    ? directHit.match(conn, kbs, req.question, 0.86) : null;
            if (hit != null) {
                TraceLog.log(conn, traceId, "direct_hit", "ok", null, null,
                        single("level", hit.level), null);
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

            // ---- 检索 →（降级可见）→ 重排；多库 IN + 个人维度过滤（先过滤后召回）----
            Map<String, Object> result = hybridSearch.search(conn, settings, kbs, req.question,
                    intOf(retCfg.get("vector_topk"), 20), intOf(retCfg.get("bm25_topk"), 20),
                    intOf(retCfg.get("top_n"), 12), req.metadataFilter);
            List<Map<String, Object>> candidates =
                    (List<Map<String, Object>>) result.getOrDefault("candidates", new ArrayList<>());
            String skippedReason = (String) result.get("vector_skipped_reason");
            if (skippedReason != null && !skippedReason.isEmpty()) {
                Map<String, Object> gate = new LinkedHashMap<>();
                gate.put("stage", "retrieval_degraded");
                gate.put("note", skippedReason);
                send(emitter, "gate", gate);
            }

            RerankClient.RerankResult reranked =
                    rerankTopN(req.question, req.top_n, appCfg.topN, candidates);
            Map<String, Object> counters = new LinkedHashMap<>();
            counters.put("candidates", reranked.candidates.size());
            counters.put("rerank", reranked.note);
            counters.putAll((Map<String, Object>) result.get("retrieval_path"));
            TraceLog.log(conn, traceId, "retrieve", "ok", null, null, counters, null);
            candidates = reranked.candidates;

            // ---- 闸门一（生成前）：候选不足不进模型 ----
            Gates.GateResult pre = Gates.sufficiencyCheck(candidates);
            if (!pre.passed) {
                Map<String, Object> noEv = new LinkedHashMap<>();
                noEv.put("reason", pre.reason);
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
            int[] limits = Budget.resolveLimits(settings, genCfg);
            int numCtx = limits[0];
            int maxNew = limits[1];
            Budget.ContextPlan plan = Budget.planContext(candidates, req.question,
                    appCfg.prompt, numCtx, maxNew, settings);
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
                    PromptRenderer.render(settings, plan.promptName, req.question, fitted.text);
            Context ctx = new Context(fitted.blocks, fitted.text, fitted.tokens,
                    messages, numCtx, maxNew, plan.promptName);
            candidates = ctx.blocks;  // 闸门二与引用只认模型真正看到的块
            send(emitter, "ctx", ctxEvent(candidates));

            // ---- 流式生成 ----
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

            // ---- 闸门二（生成后）：引用真实性；违规带反馈重答一次 ----
            Gates.GateResult post = Gates.citationCheck(answerText, candidates);
            Map<String, Object> postGate = new LinkedHashMap<>();
            postGate.put("stage", "post");
            postGate.put("passed", post.passed);
            postGate.put("reason", post.reason);
            postGate.put("violations", post.violations);
            send(emitter, "gate", postGate);
            if (!post.passed) {
                RepairOutcome repaired = repairAnswer(ctx, answerText, post, candidates, genCfg, emitter);
                answerText = repaired.answer;
                post = repaired.post;
            }

            Map<String, Object> done = new LinkedHashMap<>();
            done.put("trace_id", traceId);
            done.put("answer", answerText);
            done.put("citations", citationsOf(candidates));
            send(emitter, "done", done);
            Map<String, Object> genCounters = new LinkedHashMap<>();
            genCounters.put("chars", answerText.length());
            genCounters.put("gate_post", post.passed);
            genCounters.put("ctx_blocks", candidates.size());
            genCounters.put("ctx_tokens", ctx.tokens);
            genCounters.put("num_ctx", ctx.numCtx);
            genCounters.put("reserved_output", ctx.maxNew);
            TraceLog.log(conn, traceId, "generate", "ok", null, null, genCounters, null);
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

    /** 闸门二违规 → 带错误反馈重答一次；只有"通过"或"违规更少"才采纳重答。 */
    private RepairOutcome repairAnswer(Context ctx, String answer, Gates.GateResult post,
                                       List<Map<String, Object>> candidates,
                                       Map<String, Object> genCfg, SseEmitter emitter) {
        List<Map<String, Object>> repair = new ArrayList<>(ctx.messages);
        Map<String, Object> assistant = new LinkedHashMap<>();
        assistant.put("role", "assistant");
        assistant.put("content", answer);
        repair.add(assistant);
        Map<String, Object> user = new LinkedHashMap<>();
        user.put("role", "user");
        user.put("content", "你的上一版回答存在以下问题：" + String.join("；", post.violations)
                + "。请重答：只保留能被候选块支持的结论，每个结论标注 [来源: 块N]。");
        repair.add(user);
        try {
            String answer2 = chatClient.chat(settings, repair, null, ctx.numCtx, 0.2, ctx.maxNew);
            Gates.GateResult post2 = Gates.citationCheck(answer2, candidates);
            if (post2.passed || post2.violations.size() < post.violations.size()) {
                Map<String, Object> token = new LinkedHashMap<>();
                token.put("t", answer2);
                token.put("repaired", true);
                send(emitter, "token", token);
                return new RepairOutcome(answer2, post2);
            }
            return new RepairOutcome(answer, post);
        } catch (ChatClient.ChatError e) {
            Map<String, Object> gate = new LinkedHashMap<>();
            gate.put("stage", "repair_failed");
            gate.put("note", String.valueOf(e.getMessage()));
            send(emitter, "gate", gate);
            return new RepairOutcome("（引用校验未通过，已按规则拒答原答案。请缩小问题范围重试。）", post);
        }
    }

    private static class RepairOutcome {
        final String answer;
        final Gates.GateResult post;

        RepairOutcome(String answer, Gates.GateResult post) {
            this.answer = answer;
            this.post = post;
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

    private Map<String, Object> ctxEvent(List<Map<String, Object>> candidates) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (Map<String, Object> c : candidates) {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("ordinal", c.get("ordinal"));
            item.put("chunk_id", c.get("chunk_id"));
            item.put("doc_id", c.get("doc_id"));
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
