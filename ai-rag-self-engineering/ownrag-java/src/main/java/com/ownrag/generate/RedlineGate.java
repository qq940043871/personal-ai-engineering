package com.ownrag.generate;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

import com.ownrag.config.Settings;

/**
 * 红线后置闸门（个人数字分身场景新增）：
 * 生成后检查答案是否包含禁词表（客户名/敏感词）——禁词来源可以是检索内容
 * （放行口径下 restricted 块可见），也可以是用户提问的复述。
 * 命中即违规，走修复/拒答，不依赖模型自律。
 * 禁词表：configs/redline_terms.txt（一行一个词，仅过滤用途）。
 */
public final class RedlineGate {

    private RedlineGate() {
    }

    /** 加载禁词表（每次调用读文件——配置即代码，改词表即时生效，无需重启）。
     *  优先 classpath（configs/redline_terms.txt，打包进 jar 的场景）；
     *  无 classpath 资源时回落文件系统（config-dir 模式）。 */
    public static Set<String> loadTerms(Settings settings) {
        Set<String> terms = new LinkedHashSet<>();
        java.io.InputStream in = RedlineGate.class.getResourceAsStream("/configs/redline_terms.txt");
        if (in == null) {
            String dir = settings.getConfigDir();
            Path p = Paths.get(dir, "redline_terms.txt");
            if (!Files.exists(p)) {
                return terms;  // 未配置禁词表 = 闸门不生效（降级可见由调用方记录）
            }
            try {
                in = Files.newInputStream(p);
            } catch (IOException e) {
                return terms;
            }
        }
        try (java.io.BufferedReader br = new java.io.BufferedReader(
                new java.io.InputStreamReader(in, StandardCharsets.UTF_8))) {
            String line;
            while ((line = br.readLine()) != null) {
                String t = line.trim();
                if (!t.isEmpty() && !t.startsWith("#")) {
                    terms.add(t);
                }
            }
        } catch (IOException ignored) {
            // 读不了 = 闸门不生效，不阻断问答
        }
        return terms;
    }

    /** 检查答案中的禁词命中，返回违规列表（空 = 通过）。 */
    public static List<String> check(String answer, Settings settings) {
        List<String> hits = new ArrayList<>();
        if (answer == null || answer.isEmpty()) {
            return hits;
        }
        for (String term : loadTerms(settings)) {
            if (answer.contains(term)) {
                hits.add("答案包含红线禁词「" + term + "」");
            }
        }
        return hits;
    }
}
