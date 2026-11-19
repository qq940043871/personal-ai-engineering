package com.ownrag.config;

import java.util.Map;

import com.ownrag.util.Yamls;

/** Prompt 模板（configs/prompts/*.yaml）：system + template，占位符 {context_blocks}/{question}。 */
public class PromptDef {

    public String name;
    public String description;
    public String system;
    public String template;

    public static PromptDef from(String name, Map<String, Object> map) {
        PromptDef def = new PromptDef();
        def.name = Yamls.str(map, "name", name);
        def.description = Yamls.rawStr(map, "description", "");
        def.system = Yamls.rawStr(map, "system", "");
        def.template = Yamls.rawStr(map, "template", "");
        return def;
    }
}
