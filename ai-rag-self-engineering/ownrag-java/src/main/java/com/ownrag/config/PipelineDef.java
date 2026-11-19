package com.ownrag.config;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.ownrag.util.Yamls;

/** 一条入库管道：source（扩展名路由）+ 有序步骤链。 */
public class PipelineDef {

    public String name;
    public String sourceType;
    public List<String> accept = new ArrayList<>();
    public List<StepDef> steps = new ArrayList<>();

    public static PipelineDef from(String name, Map<String, Object> map) {
        PipelineDef def = new PipelineDef();
        def.name = name;
        Map<String, Object> source = Yamls.map(map, "source");
        if (source != null) {
            def.sourceType = Yamls.rawStr(source, "type", "upload");
            def.accept = Yamls.strList(source, "accept");
        }
        List<Object> steps = Yamls.list(map, "steps");
        if (steps != null) {
            for (Object o : steps) {
                if (o instanceof Map) {
                    @SuppressWarnings("unchecked")
                    Map<String, Object> m = (Map<String, Object>) o;
                    def.steps.add(StepDef.from(m));
                }
            }
        }
        return def;
    }
}
