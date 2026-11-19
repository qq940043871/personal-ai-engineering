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
    public boolean directHitEnabled = true;
    public List<String> directHitLevels = new ArrayList<>();
    public String prompt = "policy_strict_v1";
    public boolean stream = true;
    public int maxCtxTokens = 6144;
    public int maxNewTokens = 512;
    public List<String> preGates = new ArrayList<>();
    public List<String> postGates = new ArrayList<>();

    public static AppDef from(String name, Map<String, Object> map) {
        AppDef def = new AppDef();
        def.name = name;
        def.knowledgeBases = Yamls.strList(map, "knowledge_bases");

        Map<String, Object> retrieval = Yamls.map(map, "retrieval");
        if (retrieval != null) {
            def.vectorTopk = Yamls.intVal(retrieval, "vector_topk", 20);
            def.bm25Topk = Yamls.intVal(retrieval, "bm25_topk", 20);
            def.topN = Yamls.intVal(retrieval, "top_n", 12);
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
        return def;
    }
}
