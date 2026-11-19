package com.ownrag.config;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.ownrag.util.Yamls;

/** 管道 DSL 中的一个步骤定义：type + params + fallback 降级链。 */
public class StepDef {

    public String type;
    public Map<String, Object> params = new LinkedHashMap<>();
    public List<StepDef> fallback = new ArrayList<>();

    public static StepDef from(Map<String, Object> map) {
        StepDef def = new StepDef();
        def.type = Yamls.rawStr(map, "type", "");
        Map<String, Object> p = Yamls.map(map, "params");
        if (p != null) {
            def.params.putAll(p);
        }
        List<Object> fb = Yamls.list(map, "fallback");
        if (fb != null) {
            for (Object o : fb) {
                if (o instanceof Map) {
                    @SuppressWarnings("unchecked")
                    Map<String, Object> m = (Map<String, Object>) o;
                    def.fallback.add(from(m));
                }
            }
        }
        return def;
    }
}
