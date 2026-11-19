package com.ownrag.core;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.MissingResourceException;

import org.springframework.stereotype.Component;

import com.ownrag.config.Settings;

/**
 * 步骤注册表（Python 版 STEP_REGISTRY 的对应物）：收集所有 Step Bean，启动期全量校验 DSL。
 */
@Component
public class StepRegistry {

    private final Map<String, Step> registry = new LinkedHashMap<>();

    public StepRegistry(java.util.List<Step> steps) {
        for (Step step : steps) {
            String type = step.type();
            if (type == null || type.isEmpty()) {
                throw new IllegalStateException("Step 未声明 type(): " + step.getClass().getName());
            }
            if (registry.containsKey(type)) {
                throw new IllegalStateException("步骤类型重复注册: " + type
                        + " (" + registry.get(type).getClass().getName() + " / " + step.getClass().getName() + ")");
            }
            registry.put(type, step);
        }
    }

    public Step get(String type) {
        return registry.get(type);
    }

    public int size() {
        return registry.size();
    }

    public Map<String, String> describe() {
        Map<String, String> out = new LinkedHashMap<>();
        for (Map.Entry<String, Step> e : registry.entrySet()) {
            out.put(e.getKey(), e.getValue().getClass().getSimpleName());
        }
        return out;
    }

    /**
     * DSL 全量校验（含 fallback 链）：引用到的 type 必须全部已注册，缺失即抛异常（启动期爆）。
     * 与 Python 版 validate_pipeline_steps 同语义。
     */
    public void validate(Settings settings) {
        java.util.LinkedHashSet<String> missing = new java.util.LinkedHashSet<>();
        for (com.ownrag.config.PipelineDef pipeline : settings.getPipelines().values()) {
            collectMissing(pipeline.steps, missing);
        }
        if (!missing.isEmpty()) {
            throw new MissingResourceException(
                    "管道引用了未注册的步骤类型: " + missing + "；已注册: " + registry.keySet(),
                    Step.class.getName(), String.join(",", missing));
        }
    }

    private void collectMissing(java.util.List<com.ownrag.config.StepDef> steps,
                                java.util.Set<String> missing) {
        for (com.ownrag.config.StepDef def : steps) {
            if (!registry.containsKey(def.type)) {
                missing.add(def.type);
            }
            collectMissing(def.fallback, missing);
        }
    }
}
