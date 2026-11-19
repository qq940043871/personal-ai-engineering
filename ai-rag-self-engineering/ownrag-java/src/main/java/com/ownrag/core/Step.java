package com.ownrag.core;

import java.util.Map;

/**
 * 步骤抽象（Python 版 core/registry.py Step 的对应物）：
 * 入参 = StepContext（doc/trace/kb + 连接 + 设置 + 步骤间黑板），params 来自管道 DSL。
 * 实现类声明为 Spring @Component，由 StepRegistry 按 type() 收集注册。
 */
public interface Step {

    /** 注册名（pipelines.yaml 里的 type），如 detect_pages / parse_mineru / chunk_markdown。 */
    String type();

    StepResult run(StepContext ctx, Map<String, Object> params);
}
