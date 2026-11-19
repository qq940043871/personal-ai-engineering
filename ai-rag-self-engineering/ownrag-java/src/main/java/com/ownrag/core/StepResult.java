package com.ownrag.core;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 步骤结果（与 Python 版 StepResult dataclass 同构）：
 * status ok|fail；data 并入 ctx.data 的增量；metrics 进 trace counters。
 *
 * 第三种形态 awaitReview：不是失败，是"故意停下来等人"（review_gate 这种人工闸门）。
 * 执行器把任务标 pending_review，不进失败口径，也不继续试 fallback。
 */
public class StepResult {

    public final boolean ok;
    public final String error;
    public final boolean awaitReview;
    public final Map<String, Object> data = new LinkedHashMap<>();
    public final Map<String, Object> metrics = new LinkedHashMap<>();

    private StepResult(boolean ok, boolean awaitReview, String error) {
        this.ok = ok;
        this.awaitReview = awaitReview;
        this.error = error;
    }

    public static StepResult ok(Map<String, Object> data, Map<String, Object> metrics) {
        StepResult r = new StepResult(true, false, null);
        if (data != null) {
            r.data.putAll(data);
        }
        if (metrics != null) {
            r.metrics.putAll(metrics);
        }
        return r;
    }

    /**
     * 便捷：仅 metrics（无数据增量）。参数按 key/value 成对传入。
     * 独立命名避免与 ok(Map, Map) 产生重载歧义（Map/Object[] 混传会被 varargs 吞掉成垃圾）。
     */
    public static StepResult okMetrics(Object... metricPairs) {
        StepResult r = new StepResult(true, false, null);
        for (int i = 0; i + 1 < metricPairs.length; i += 2) {
            r.metrics.put(String.valueOf(metricPairs[i]), metricPairs[i + 1]);
        }
        return r;
    }

    /**
     * 停机等人：语义"未完成但不失败"（解析复核闸门）。任务标 pending_review，
     * 仍然入待办（人工队列不能漏），但不是错误——所以不跑 fallback、不算失败计数。
     */
    public static StepResult awaitReview(String reason) {
        return new StepResult(false, true, reason);
    }

    public static StepResult awaitReview(String reason, Map<String, Object> metrics) {
        StepResult r = new StepResult(false, true, reason);
        if (metrics != null) {
            r.metrics.putAll(metrics);
        }
        return r;
    }

    /** key/value 可变参数 → 有序 Map（构造 data/metrics 字面量的助手）。 */
    public static Map<String, Object> pairs(Object... kv) {
        Map<String, Object> m = new LinkedHashMap<>();
        for (int i = 0; i + 1 < kv.length; i += 2) {
            m.put(String.valueOf(kv[i]), kv[i + 1]);
        }
        return m;
    }

    public static StepResult fail(String error) {
        return new StepResult(false, false, error);
    }

    /** 失败但带 metrics（进 trace counters，排障要看的上下文随失败一起落表）。 */
    public static StepResult fail(String error, Map<String, Object> metrics) {
        StepResult r = new StepResult(false, false, error);
        if (metrics != null) {
            r.metrics.putAll(metrics);
        }
        return r;
    }

    @Override
    public String toString() {
        if (awaitReview) {
            return "StepResult(awaitReview, " + error + ")";
        }
        return ok ? "StepResult(ok, metrics=" + metrics + ")" : "StepResult(fail, " + error + ")";
    }
}
