package com.ownrag;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;

import com.ownrag.config.Settings;
import com.ownrag.core.PipelineExecutor;

import okhttp3.OkHttpClient;

/**
 * ownrag-java 入口：Python 版 main.py 的对应物。
 * 启动期校验（建表 + FTS5 探测 + DSL 步骤类型全量校验）在 {@link com.ownrag.core.StartupCheck}，
 * 配置错误启动期爆——与 Python 版「配置错误启动期爆」口径一致。
 */
@SpringBootApplication
public class OwnRagApplication {

    public static void main(String[] args) {
        SpringApplication.run(OwnRagApplication.class, args);
    }

    /**
     * 全局共享 OkHttp：所有模型端点（chat/embed/rerank/mineru/asr）的手写 HTTP 薄客户端共用。
     * NO_PROXY 对齐 Python 版 httpx trust_env=False 的口径：模型端点一律不走系统代理。
     */
    @Bean
    public OkHttpClient okHttpClient() {
        return new OkHttpClient.Builder()
                .connectTimeout(java.time.Duration.ofSeconds(15))
                .readTimeout(java.time.Duration.ofSeconds(300))
                .writeTimeout(java.time.Duration.ofSeconds(600))
                .proxy(java.net.Proxy.NO_PROXY)
                .build();
    }

    @Bean
    public Settings settings(com.ownrag.config.ConfigLoader loader) {
        return loader.load();
    }

    /** 任务/待办表工具（全静态方法，无状态）。 */
    @Bean
    public com.ownrag.core.TaskStore taskStore() {
        return new com.ownrag.core.TaskStore();
    }

    @Bean
    public PipelineExecutor pipelineExecutor(com.ownrag.core.StepRegistry registry,
                                             com.ownrag.core.TaskStore taskStore,
                                             com.ownrag.core.TraceLog traceLog,
                                             Settings settings) {
        return new PipelineExecutor(registry, taskStore, traceLog, settings);
    }
}
