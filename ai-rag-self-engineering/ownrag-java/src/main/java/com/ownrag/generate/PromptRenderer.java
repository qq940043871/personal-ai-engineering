package com.ownrag.generate;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import com.ownrag.config.PromptDef;
import com.ownrag.config.Settings;

/**
 * Prompt 版本化（Python 版 generate/prompts.py 的平移）：配置即代码，文件进 Git——历史与回滚免费送。
 * 模板占位符缺失在渲染期爆（配置错误不进运行期）。
 */
public final class PromptRenderer {

    private static final Pattern PLACEHOLDER = Pattern.compile("\\{(\\w+)}");

    private PromptRenderer() {
    }

    /** 渲染成 messages（system + user）；渲染后仍有未填占位符 = 配置错误，直接抛异常。 */
    public static List<Map<String, Object>> render(Settings settings, String name,
                                                   String question, String contextBlocks,
                                                   String... extraPairs) {
        PromptDef spec = settings.prompt(name);
        if (spec == null) {
            throw new IllegalArgumentException("Prompt 模板不存在：" + name);
        }
        if (spec.system == null || spec.system.isEmpty() || spec.template == null || spec.template.isEmpty()) {
            throw new IllegalArgumentException("Prompt " + name + " 缺少 system/template 字段");
        }
        Map<String, String> vars = new LinkedHashMap<>();
        vars.put("question", question);
        vars.put("context_blocks", contextBlocks);
        for (int i = 0; i + 1 < extraPairs.length; i += 2) {
            vars.put(extraPairs[i], extraPairs[i + 1]);
        }
        // 占位符校验只扫【模板本身】：渲染产物里包含资料正文，LaTeX 的 \frac{1}{2}
        // 会带 {1}{2} 花括号——扫产物会把公式误判成未填占位符（Python 版同源隐患，此修）
        Set<String> allowed = new LinkedHashSet<>(vars.keySet());
        List<String> leftover = new ArrayList<>();
        Matcher tm = PLACEHOLDER.matcher(spec.template);
        while (tm.find()) {
            String token = tm.group(1);
            if (!allowed.contains(token) && !leftover.contains(token)) {
                leftover.add(token);
            }
        }
        if (!leftover.isEmpty()) {
            throw new IllegalArgumentException("Prompt " + name + " 模板含未支持的占位符：" + leftover);
        }
        String user = spec.template;
        for (Map.Entry<String, String> e : vars.entrySet()) {
            user = user.replace("{" + e.getKey() + "}", e.getValue());
        }
        List<Map<String, Object>> messages = new ArrayList<>();
        Map<String, Object> system = new LinkedHashMap<>();
        system.put("role", "system");
        system.put("content", spec.system);
        messages.add(system);
        Map<String, Object> userMsg = new LinkedHashMap<>();
        userMsg.put("role", "user");
        userMsg.put("content", user);
        messages.add(userMsg);
        return messages;
    }
}
