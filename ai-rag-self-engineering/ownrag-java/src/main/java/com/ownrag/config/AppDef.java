package com.ownrag.config;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.ownrag.util.Yamls;

/**
 * 应用模板（apps.yaml 一段 = 一个问答应用）：检索参数 / 生成参数 / 闸门声明。
 * 与 Python 版 apps.yaml 结构一一对应。
 */
public class AppDef {

    public String name;
    public List<String> knowledgeBases = new ArrayList<>();
    public int vectorTopk = 20;
    public int bm25Topk = 20;
    public int topN = 12;
    public boolean rerankEnabled = false;
    /** 检索问句改写总开关（retrieval.query_rewrite）；请求体 rewrite=true/false 可单次覆盖。 */
    public boolean queryRewrite = true;
    public boolean directHitEnabled = true;
    public List<String> directHitLevels = new ArrayList<>();
    public String prompt = "policy_strict_v1";
    public boolean stream = true;
    public int maxCtxTokens = 6144;
    public int maxNewTokens = 512;
    public List<String> preGates = new ArrayList<>();
    public List<String> postGates = new ArrayList<>();

    // ---- 查询期路由（docs 11-查询路由与多源编排.md）----
    /** 总开关：false 时行为与改造前逐字一致（单轨 RAG），用于回滚与 A/B。 */
    public boolean routingEnabled = false;
    /** 允许的通道白名单：rag / sql（web 本期不实现，写进来也会被判不可用）。 */
    public List<String> routingAllow = new ArrayList<>();
    /** 路由给不出结论时的落点：rag | sql | multi。 */
    public String routingDefault = "rag";
    /** 置信度低于阈值时的落点。 */
    public String routingLowConfidence = "rag";
    public double routingMinConfidence = 0.4;
    /** 低置信时是否再花一次 LLM 归类（M2，默认关：规则命中即短路不花钱）。 */
    public boolean routingLlmClassify = false;
    /** SQL 通道护栏：一次最多返回行数 / 语句超时 / 候选表上限。 */
    public int sqlMaxRows = 200;
    public int sqlTimeoutMs = 5000;
    public int sqlMaxTables = 3;

    public static AppDef from(String name, Map<String, Object> map) {
        AppDef def = new AppDef();
        def.name = name;
        def.knowledgeBases = Yamls.strList(map, "knowledge_bases");

        Map<String, Object> retrieval = Yamls.map(map, "retrieval");
        if (retrieval != null) {
            def.vectorTopk = Yamls.intVal(retrieval, "vector_topk", 20);
            def.bm25Topk = Yamls.intVal(retrieval, "bm25_topk", 20);
            def.topN = Yamls.intVal(retrieval, "top_n", 12);
            def.queryRewrite = Yamls.bool(retrieval, "query_rewrite", true);
            Map<String, Object> rerank = Yamls.map(retrieval, "rerank");
            if (rerank != null) {
                def.rerankEnabled = Yamls.bool(rerank, "enabled", false);
            }
        }
        Map<String, Object> dh = Yamls.map(map, "direct_hit");
        if (dh != null) {
            def.directHitEnabled = Yamls.bool(dh, "enabled", true);
            def.directHitLevels = Yamls.strList(dh, "levels");
        }
        Map<String, Object> gen = Yamls.map(map, "generation");
        if (gen != null) {
            def.prompt = Yamls.str(gen, "prompt", def.prompt);
            def.stream = Yamls.bool(gen, "stream", true);
            def.maxCtxTokens = Yamls.intVal(gen, "max_ctx_tokens", 6144);
            def.maxNewTokens = Yamls.intVal(gen, "max_new_tokens", 512);
        }
        Map<String, Object> gates = Yamls.map(map, "gates");
        if (gates != null) {
            def.preGates = Yamls.strList(gates, "pre");
            def.postGates = Yamls.strList(gates, "post");
        }
        def.applyRouting(Yamls.map(map, "routing"));
        return def;
    }

    /** routing 段：缺省（null）= 关闭路由，保持改造前的单轨 RAG 行为。 */
    private void applyRouting(Map<String, Object> routing) {
        if (routing == null) {
            return;
        }
        this.routingEnabled = Yamls.bool(routing, "enabled", true);
        this.routingAllow = Yamls.strList(routing, "allow");
        if (this.routingAllow.isEmpty()) {
            this.routingAllow.add("rag");
        }
        this.routingDefault = Yamls.str(routing, "default", "rag");
        this.routingLowConfidence = Yamls.str(routing, "on_low_confidence", "rag");
        this.routingMinConfidence = Yamls.doubleVal(routing, "min_confidence", 0.4);
        this.routingLlmClassify = Yamls.bool(routing, "llm_classify", false);
        Map<String, Object> sql = Yamls.map(routing, "sql");
        if (sql != null) {
            this.sqlMaxRows = Yamls.intVal(sql, "max_rows", 200);
            this.sqlTimeoutMs = Yamls.intVal(sql, "timeout_ms", 5000);
            this.sqlMaxTables = Yamls.intVal(sql, "max_tables", 3);
        }
    }
}
