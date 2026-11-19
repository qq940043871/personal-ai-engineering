package com.ownrag.config;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import com.ownrag.util.Yamls;

/**
 * 配置装载（Python 版 config.py 的装载逻辑对应物）：
 * models.yaml（端点+默认值，env 覆盖）+ pipelines.yaml + apps.yaml + prompts/*.yaml。
 * 配置目录缺省走 classpath:/configs，ownrag.config-dir 指向文件系统可免重启改 DSL。
 */
@Component
public class ConfigLoader {

    @Value("${ownrag.data-dir:./data}")
    private String dataDirProp;

    @Value("${ownrag.config-dir:}")
    private String configDirProp;

    public Settings load() {
        Path dataDir = Settings.normalizeDir(dataDirProp);
        String dir = configDirProp == null ? "" : configDirProp.trim();
        String base = dir.isEmpty() ? "classpath:configs/" : ensureTrailingSlash(dir);

        Map<String, Object> models = Yamls.load(base + "models.yaml");
        Map<String, Object> endpoints = orEmpty(Yamls.map(models, "endpoints"));
        Map<String, Object> defaults = orEmpty(Yamls.map(models, "defaults"));
        Map<String, Object> mineruCfg = orEmpty(Yamls.map(models, "mineru"));
        Map<String, Object> asrCfg = orEmpty(Yamls.map(models, "asr"));

        Map<String, Object> ollama = orEmpty(Yamls.map(endpoints, "ollama"));
        Map<String, Object> chatEp = orEmpty(Yamls.map(endpoints, "chat"));
        Map<String, Object> embedEp = orEmpty(Yamls.map(endpoints, "embed"));
        Map<String, Object> rerankEp = orEmpty(Yamls.map(endpoints, "rerank"));

        // 优先级：env > models.yaml（与 Python 版一致）
        String chatProvider = env("OWNRAG_CHAT_PROVIDER", Yamls.str(chatEp, "provider", "ollama"));
        String chatBaseUrl = env("OWNRAG_CHAT_BASE_URL", Yamls.str(chatEp, "base_url", ""));
        String chatModel = env("OWNRAG_CHAT_MODEL", Yamls.str(defaults, "chat", "qwen2.5:7b-instruct-q4_K_M"));
        String embedProvider = env("OWNRAG_EMBED_PROVIDER", Yamls.str(embedEp, "provider", "ollama"));
        String embedBaseUrl = env("OWNRAG_EMBED_BASE_URL", Yamls.str(embedEp, "base_url", ""));
        String embedModel = env("OWNRAG_EMBED_MODEL", Yamls.str(defaults, "embed", "bge-m3"));
        String embedVersion = env("OWNRAG_EMBED_VERSION", Yamls.str(defaults, "embed_version", "bge-m3@ollama"));
        String rerankProvider = env("OWNRAG_RERANK_PROVIDER", Yamls.str(rerankEp, "provider", ""));
        String rerankBaseUrl = env("OWNRAG_RERANK_URL", Yamls.str(rerankEp, "base_url", ""));
        String rerankModel = env("OWNRAG_RERANK_MODEL", Yamls.str(rerankEp, "model", "BAAI/bge-reranker-v2-m3"));
        String mineruMode = env("MINERU_MODE", Yamls.str(mineruCfg, "mode", "open"));
        String mineruBaseUrl = env("MINERU_BASE_URL", Yamls.str(mineruCfg, "base_url", ""));
        String mineruOpenBaseUrl = env("MINERU_OPEN_BASE_URL", Yamls.str(mineruCfg, "open_base_url", "https://mineru.net/api/v4"));
        String asrBaseUrl = env("OWNRAG_ASR_BASE_URL", Yamls.str(asrCfg, "base_url", ""));
        String asrModel = env("OWNRAG_ASR_MODEL", Yamls.str(asrCfg, "model", "SenseVoiceSmall"));
        String asrLanguage = env("OWNRAG_ASR_LANGUAGE", Yamls.str(asrCfg, "language", "zh"));

        int numCtx = intEnv("OWNRAG_NUM_CTX", Yamls.intVal(defaults, "num_ctx", 6144));
        int maxNewTokens = intEnv("OWNRAG_MAX_NEW_TOKENS", Yamls.intVal(defaults, "max_new_tokens", 512));
        int maxUploadMb = intEnv("OWNRAG_MAX_UPLOAD_MB", Yamls.intVal(defaults, "max_upload_mb", 200));

        // ---- pipelines.yaml：Map<String,PipelineDef> ----
        Map<String, Object> pipelinesRaw = orEmpty(Yamls.map(Yamls.load(base + "pipelines.yaml"), "pipelines"));
        Map<String, PipelineDef> pipelines = new LinkedHashMap<>();
        for (Map.Entry<String, Object> e : pipelinesRaw.entrySet()) {
            if (e.getValue() instanceof Map) {
                @SuppressWarnings("unchecked")
                Map<String, Object> m = (Map<String, Object>) e.getValue();
                pipelines.put(e.getKey(), PipelineDef.from(e.getKey(), m));
            }
        }

        // ---- apps.yaml ----
        Map<String, Object> appsRaw = orEmpty(Yamls.map(Yamls.load(base + "apps.yaml"), "apps"));
        Map<String, AppDef> apps = new LinkedHashMap<>();
        for (Map.Entry<String, Object> e : appsRaw.entrySet()) {
            if (e.getValue() instanceof Map) {
                @SuppressWarnings("unchecked")
                Map<String, Object> m = (Map<String, Object>) e.getValue();
                apps.put(e.getKey(), AppDef.from(e.getKey(), m));
            }
        }

        // ---- prompts/*.yaml：classpath 无法列目录，从 apps 引用到的名字逐一装载 ----
        Map<String, PromptDef> prompts = new LinkedHashMap<>();
        java.util.Set<String> names = new java.util.LinkedHashSet<>();
        for (AppDef app : apps.values()) {
            names.add(app.prompt);
        }
        for (String name : names) {
            Map<String, Object> pm = Yamls.load(base + "prompts/" + name + ".yaml");
            prompts.put(name, PromptDef.from(name, pm));
        }

        return new Settings(dataDir, dir,
                Yamls.str(ollama, "base_url", "http://127.0.0.1:11434"),
                chatProvider, chatBaseUrl, env("OWNRAG_CHAT_API_KEY", ""),
                chatModel, embedProvider, embedBaseUrl, env("OWNRAG_EMBED_API_KEY", ""),
                embedModel, embedVersion, env("OWNRAG_EMBED_QUERY_INSTRUCT", ""),
                rerankProvider, rerankBaseUrl, rerankModel, env("OWNRAG_RERANK_API_KEY", ""),
                mineruMode, mineruBaseUrl, mineruOpenBaseUrl, env("MINERU_OPEN_TOKEN", ""),
                asrBaseUrl, asrModel, asrLanguage, env("OWNRAG_ASR_API_KEY", ""),
                numCtx, maxNewTokens, maxUploadMb,
                pipelines, apps, prompts);
    }

    /** 列出配置目录里实际的 prompts 文件（config-dir 为文件系统时支持目录扫描）。 */
    public List<String> listPromptFiles(String dir) {
        List<String> out = new ArrayList<>();
        if (dir == null || dir.trim().isEmpty()) {
            return out;
        }
        Path p = Paths.get(dir.trim(), "prompts");
        if (Files.isDirectory(p)) {
            try (java.util.stream.Stream<Path> s = Files.list(p)) {
                s.filter(f -> f.getFileName().toString().endsWith(".yaml"))
                        .map(f -> f.getFileName().toString().replaceAll("\\.yaml$", ""))
                        .forEach(out::add);
            } catch (Exception ignored) {
                // 目录不可读 = 提示词缺失，启动期校验会拦住引用不到的 prompt
            }
        }
        return out;
    }

    private static String ensureTrailingSlash(String dir) {
        return dir.endsWith("/") || dir.endsWith("\\") ? dir : dir + "/";
    }

    private static String env(String key, String def) {
        String v = System.getenv(key);
        return v == null || v.trim().isEmpty() ? def : v.trim();
    }

    private static int intEnv(String key, int def) {
        String v = System.getenv(key);
        if (v == null || v.trim().isEmpty()) {
            return def;
        }
        try {
            return Integer.parseInt(v.trim());
        } catch (NumberFormatException e) {
            return def;
        }
    }

    private static Map<String, Object> orEmpty(Map<String, Object> map) {
        return map == null ? new LinkedHashMap<String, Object>() : map;
    }
}
