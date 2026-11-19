package com.ownrag.core;

import java.sql.Connection;
import java.sql.SQLException;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.ownrag.config.PipelineDef;
import com.ownrag.config.Settings;
import com.ownrag.config.StepDef;
import com.ownrag.util.Json;

/**
 * 管道执行器（Python 版 core/pipeline.py 的平移）：按 DSL 串行执行步骤，
 * 带 fallback 降级链、检查点续跑、失败入待办。
 *
 * 承接六机制：
 *   ① 终止闸门  —— 线性有限步骤，天然有界
 *   ② 状态外置  —— 每步 checkpoint 到任务表，中断可续跑
 *   ④ 失败补偿  —— 步骤级 fallback 降级链 + 任务级失败入待办
 *   ⑥ 评测观测  —— 每步 trace 落表
 */
public class PipelineExecutor {

    private final StepRegistry registry;
    private final TaskStore taskStore;
    private final TraceLog traceLog;
    private final Settings settings;

    public PipelineExecutor(StepRegistry registry, TaskStore taskStore, TraceLog traceLog, Settings settings) {
        this.registry = registry;
        this.taskStore = taskStore;
        this.traceLog = traceLog;
        this.settings = settings;
    }

    /**
     * 执行一条任务，返回 done | failed。
     * resume=true 时从任务表检查点续跑（重试 = 同一入口，幂等键 doc_id+step）。
     */
    public String runPipeline(Connection conn, String taskId, boolean resume) throws SQLException {
        Map<String, Object> task = taskStore.getTask(conn, taskId);
        if (task == null) {
            throw new IllegalArgumentException("任务不存在：" + taskId);
        }

        String pipelineName = String.valueOf(task.get("pipeline"));
        PipelineDef spec = settings.pipeline(pipelineName);
        if (spec == null) {
            return fail(conn, taskId, "管道未定义：" + pipelineName);
        }
        List<StepDef> steps = spec.steps;

        String docId = String.valueOf(task.get("doc_id"));
        String traceId = task.get("trace_id") == null || String.valueOf(task.get("trace_id")).isEmpty()
                ? traceLog.newTraceId() : String.valueOf(task.get("trace_id"));
        String kb = task.get("kb") == null || String.valueOf(task.get("kb")).isEmpty()
                ? "default" : String.valueOf(task.get("kb"));

        StepContext ctx = new StepContext(docId, traceId, kb, conn, settings);

        int start = 0;
        // 初始 state（如 source_path）与检查点统一从任务表恢复（状态外置）
        Object stateJson = task.get("state_json");
        if (stateJson != null && !String.valueOf(stateJson).isEmpty()) {
            try {
                ctx.data.putAll(Json.readMap(String.valueOf(stateJson)));
            } catch (Exception ignored) {
                // 检查点坏了就从头来：源文件还在，重跑安全（按 doc_id 原子替换索引）
            }
        }
        ctx.data.put("_pipeline", pipelineName);  // 步骤留版本链用
        ctx.data.put("_task_id", taskId);          // 复核等步骤回写任务关联用
        if (resume && task.get("current_step") != null) {
            String current = String.valueOf(task.get("current_step"));
            for (int i = 0; i < steps.size(); i++) {
                if (steps.get(i).type.equals(current)) {
                    start = i;
                    break;
                }
            }
        }

        markRunning(conn, taskId);

        for (int i = 0; i < steps.size(); i++) {
            StepDef stepSpec = steps.get(i);
            if (i < start) {
                continue;
            }
            String stepName = stepSpec.type;
            taskStore.checkpoint(conn, taskId, stepName, ctx.data);

            StepResult result = runWithFallbacks(stepSpec, ctx);
            if (!result.ok) {
                String reason = "[" + pipelineName + "/" + stepName + "] " + result.error;
                Map<String, Object> payload = new LinkedHashMap<>();
                payload.put("metrics", result.metrics);
                payload.put("trace_id", ctx.traceId);
                if (result.awaitReview) {
                    // 停在人工闸门 ≠ 失败：换后端也救不了"没人看过"，续跑时也不必重复入队列
                    if (!taskStore.hasOpenTodo(conn, taskId)) {
                        taskStore.addTodo(conn, taskId, ctx.docId, reason, payload);
                    }
                    return awaitReview(conn, taskId, reason);
                }
                taskStore.addTodo(conn, taskId, ctx.docId, reason, payload);
                return fail(conn, taskId, reason);
            }
            ctx.data.putAll(result.data);
        }

        Map<String, Object> doneFields = new LinkedHashMap<>();
        doneFields.put("status", TaskStore.STATUS_DONE);
        doneFields.put("current_step", null);
        doneFields.put("error", null);
        taskStore.updateTask(conn, taskId, doneFields);

        Map<String, Object> counters = new LinkedHashMap<>();
        counters.put("pipeline", pipelineName);
        counters.put("steps", steps.size());
        TraceLog.log(conn, ctx.traceId, "pipeline", "ok", null, ctx.docId, counters, null);
        return TaskStore.STATUS_DONE;
    }

    /** 主步骤失败后按序尝试 fallback 链：能表达串行/降级，不表达复杂图。 */
    StepResult runWithFallbacks(StepDef stepSpec, StepContext ctx) {
        StepResult last = null;
        int idx = 0;
        for (StepDef attempt : attemptsOf(stepSpec)) {
            String tag = idx == 0 ? "main" : "fallback" + idx;
            StepResult result = invoke(attempt, ctx, tag);
            // awaitReview 是"需要人"而不是"这步没做成"，试下一个后端没有意义
            if (result.ok || result.awaitReview) {
                return result;
            }
            last = result;
            idx++;
        }
        return last == null ? StepResult.fail("空步骤定义") : last;
    }

    private static List<StepDef> attemptsOf(StepDef stepSpec) {
        java.util.ArrayList<StepDef> attempts = new java.util.ArrayList<>();
        attempts.add(stepSpec);
        attempts.addAll(stepSpec.fallback);
        return attempts;
    }

    /** 步骤内未捕获异常 = 一次失败，不是执行器崩溃；每步 trace 落表（含耗时/metrics/error）。 */
    StepResult invoke(StepDef stepSpec, StepContext ctx, String attemptTag) {
        Step step = registry.get(stepSpec.type);
        if (step == null) {
            return StepResult.fail("步骤类型未注册：" + stepSpec.type);
        }
        long t0 = System.nanoTime();
        StepResult result;
        try {
            result = step.run(ctx, stepSpec.params);
        } catch (Exception e) {
            result = StepResult.fail(e.getClass().getSimpleName() + ": " + e.getMessage());
        }
        double ms = (System.nanoTime() - t0) / 1_000_000.0;
        TraceLog.log(ctx.conn, ctx.traceId, attemptTag + ":" + stepSpec.type,
                result.ok ? "ok" : "fail", ms, ctx.docId, result.metrics, result.error);
        return result;
    }

    private String fail(Connection conn, String taskId, String error) throws SQLException {
        Map<String, Object> fields = new LinkedHashMap<>();
        fields.put("status", TaskStore.STATUS_FAILED);
        fields.put("error", error.length() > 500 ? error.substring(0, 500) : error);
        taskStore.updateTask(conn, taskId, fields);
        return TaskStore.STATUS_FAILED;
    }

    /** 停在人工闸门：任务挂 pending_review（检查点仍指向该步），复核通过后 resume 从此步续跑。 */
    private String awaitReview(Connection conn, String taskId, String error) throws SQLException {
        Map<String, Object> fields = new LinkedHashMap<>();
        fields.put("status", TaskStore.STATUS_PENDING_REVIEW);
        fields.put("error", error.length() > 500 ? error.substring(0, 500) : error);
        taskStore.updateTask(conn, taskId, fields);
        return TaskStore.STATUS_PENDING_REVIEW;
    }

    private void markRunning(Connection conn, String taskId) throws SQLException {
        Map<String, Object> fields = new LinkedHashMap<>();
        fields.put("status", TaskStore.STATUS_RUNNING);
        taskStore.updateTask(conn, taskId, fields);
    }
}
