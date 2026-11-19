package com.ownrag.config;

import java.io.File;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 运行时设置（Python 版 config.py Settings 的对应物）。
 * 优先级：环境变量 > models.yaml；api_key 一律只走环境变量，不落配置文件。
 */
public class Settings {

    // ---- 目录 ----
    private final Path dataDir;
    private final String configDir;

    // ---- 模型端点（models.yaml endpoints + defaults，env 覆盖）----
    private final String ollamaBaseUrl;
    private final String chatProvider;      // ollama | openai
    private final String chatBaseUrl;
    private final String chatApiKey;        // env OWNRAG_CHAT_API_KEY
    private final String chatModel;
    private final String embedProvider;     // ollama | openai
    private final String embedBaseUrl;
    private final String embedApiKey;       // env OWNRAG_EMBED_API_KEY
    private final String embedModel;
    private final String embedVersion;      // 换值 = 全量重建索引
    private final String embedQueryInstruct; // env OWNRAG_EMBED_QUERY_INSTRUCT（Qwen3 系才需要）
    private final String rerankProvider;    // "" | service | siliconflow
    private final String rerankBaseUrl;
    private final String rerankModel;
    private final String rerankApiKey;      // env OWNRAG_RERANK_API_KEY
    private final String mineruMode;        // cli | http | open
    private final String mineruBaseUrl;
    private final String mineruOpenBaseUrl;
    private final String mineruOpenToken;   // env MINERU_OPEN_TOKEN
    private final String asrBaseUrl;        // OpenAI 兼容 /audio/transcriptions（Java 版新增）
    private final String asrModel;
    private final String asrLanguage;
    private final String asrApiKey;         // env OWNRAG_ASR_API_KEY
    private final int numCtx;
    private final int maxNewTokens;
    private final int maxUploadMb;

    // ---- 配置驱动（pipelines.yaml / apps.yaml / prompts）----
    private final Map<String, PipelineDef> pipelines = new LinkedHashMap<>();
    private final Map<String, AppDef> apps = new LinkedHashMap<>();
    private final Map<String, PromptDef> prompts = new LinkedHashMap<>();

    public Settings(Path dataDir, String configDir,
                    String ollamaBaseUrl, String chatProvider, String chatBaseUrl, String chatApiKey,
                    String chatModel, String embedProvider, String embedBaseUrl, String embedApiKey,
                    String embedModel, String embedVersion, String embedQueryInstruct,
                    String rerankProvider, String rerankBaseUrl, String rerankModel, String rerankApiKey,
                    String mineruMode, String mineruBaseUrl, String mineruOpenBaseUrl, String mineruOpenToken,
                    String asrBaseUrl, String asrModel, String asrLanguage, String asrApiKey,
                    int numCtx, int maxNewTokens, int maxUploadMb,
                    Map<String, PipelineDef> pipelines, Map<String, AppDef> apps, Map<String, PromptDef> prompts) {
        this.dataDir = dataDir;
        this.configDir = configDir;
        this.ollamaBaseUrl = ollamaBaseUrl;
        this.chatProvider = chatProvider;
        this.chatBaseUrl = chatBaseUrl;
        this.chatApiKey = chatApiKey;
        this.chatModel = chatModel;
        this.embedProvider = embedProvider;
        this.embedBaseUrl = embedBaseUrl;
        this.embedApiKey = embedApiKey;
        this.embedModel = embedModel;
        this.embedVersion = embedVersion;
        this.embedQueryInstruct = embedQueryInstruct;
        this.rerankProvider = rerankProvider;
        this.rerankBaseUrl = rerankBaseUrl;
        this.rerankModel = rerankModel;
        this.rerankApiKey = rerankApiKey;
        this.mineruMode = mineruMode;
        this.mineruBaseUrl = mineruBaseUrl;
        this.mineruOpenBaseUrl = mineruOpenBaseUrl;
        this.mineruOpenToken = mineruOpenToken;
        this.asrBaseUrl = asrBaseUrl;
        this.asrModel = asrModel;
        this.asrLanguage = asrLanguage;
        this.asrApiKey = asrApiKey;
        this.numCtx = numCtx;
        this.maxNewTokens = maxNewTokens;
        this.maxUploadMb = maxUploadMb;
        if (pipelines != null) {
            this.pipelines.putAll(pipelines);
        }
        if (apps != null) {
            this.apps.putAll(apps);
        }
        if (prompts != null) {
            this.prompts.putAll(prompts);
        }
    }

    // ---- 派生路径（与 Python 版派生属性一致）----
    public Path getDataDir() {
        return dataDir;
    }

    public Path getDbPath() {
        return dataDir.resolve("ownrag.db");
    }

    public Path getFilesDir() {
        return dataDir.resolve("files");
    }

    public Path getParsedDir() {
        return dataDir.resolve("parsed");
    }

    public Path getReviewDir() {
        return dataDir.resolve("review");
    }

    public String getConfigDir() {
        return configDir;
    }

    /** KB 白名单：由 apps.yaml 各应用的 knowledge_bases 推导，未声明拒收。 */
    public java.util.Set<String> getKnownKbs() {
        java.util.Set<String> kbs = new java.util.LinkedHashSet<>();
        for (AppDef app : apps.values()) {
            kbs.addAll(app.knowledgeBases);
        }
        return kbs;
    }

    public PipelineDef pipeline(String name) {
        return pipelines.get(name);
    }

    public AppDef app(String name) {
        return apps.get(name);
    }

    public PromptDef prompt(String name) {
        return prompts.get(name);
    }

    public Map<String, PipelineDef> getPipelines() {
        return pipelines;
    }

    public Map<String, AppDef> getApps() {
        return apps;
    }

    public Map<String, PromptDef> getPrompts() {
        return prompts;
    }

    public String getOllamaBaseUrl() {
        return ollamaBaseUrl;
    }

    public String getChatProvider() {
        return chatProvider;
    }

    public String getChatBaseUrl() {
        return chatBaseUrl;
    }

    public String getChatApiKey() {
        return chatApiKey;
    }

    public String getChatModel() {
        return chatModel;
    }

    public String getEmbedProvider() {
        return embedProvider;
    }

    public String getEmbedBaseUrl() {
        return embedBaseUrl;
    }

    public String getEmbedApiKey() {
        return embedApiKey;
    }

    public String getEmbedModel() {
        return embedModel;
    }

    public String getEmbedVersion() {
        return embedVersion;
    }

    public String getEmbedQueryInstruct() {
        return embedQueryInstruct;
    }

    public String getRerankProvider() {
        return rerankProvider;
    }

    public String getRerankBaseUrl() {
        return rerankBaseUrl;
    }

    public String getRerankModel() {
        return rerankModel;
    }

    public String getRerankApiKey() {
        return rerankApiKey;
    }

    public String getMineruMode() {
        return mineruMode;
    }

    public String getMineruBaseUrl() {
        return mineruBaseUrl;
    }

    public String getMineruOpenBaseUrl() {
        return mineruOpenBaseUrl;
    }

    public String getMineruOpenToken() {
        return mineruOpenToken;
    }

    public String getAsrBaseUrl() {
        return asrBaseUrl;
    }

    public String getAsrModel() {
        return asrModel;
    }

    public String getAsrLanguage() {
        return asrLanguage;
    }

    public String getAsrApiKey() {
        return asrApiKey;
    }

    public int getNumCtx() {
        return numCtx;
    }

    public int getMaxNewTokens() {
        return maxNewTokens;
    }

    public int getMaxUploadMb() {
        return maxUploadMb;
    }

    /** 解析上限常量：上下文预算 SAFETY 余量（Python 版 budget.py 同值）。 */
    public static final int BUDGET_SAFETY = 64;
    public static final int BUDGET_MIN = 128;

    /** 相对 data-dir 解析（文件落盘统一入口，保证相对路径行为一致）。 */
    public File resolveData(String relative) {
        return dataDir.resolve(relative).toFile();
    }

    public static Path normalizeDir(String dir) {
        return dir == null || dir.trim().isEmpty() ? Paths.get("./data") : Paths.get(dir.trim());
    }
}
