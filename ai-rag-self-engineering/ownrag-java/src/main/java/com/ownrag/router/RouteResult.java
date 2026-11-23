package com.ownrag.router;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 一次路由的结论（docs 11-查询路由与多源编排.md §六 的 SSE `route` 事件载荷）。
 *
 * 只带"分诊"信息，不参与回答：路由错了要在观测页一眼看出来，而不是靠答案质量倒推。
 */
public class RouteResult {

    public static final String RAG = "rag";
    public static final String SQL = "sql";
    public static final String MULTI = "multi";
    public static final String WEB = "web";

    public String route = RAG;
    /** forced（请求体指定）| rule（规则打分）| structure（可用性掩码）| llm | fallback（低置信兜底）。 */
    public String layer = "rule";
    public double confidence;
    public String reason = "";
    public final List<Map<String, Object>> signals = new ArrayList<>();
    public final List<Map<String, Object>> targets = new ArrayList<>();
    public final Map<String, Object> availability = new LinkedHashMap<>();
    /** 0.1ms 精度：路由常在 1ms 内完成，整数毫秒看不出差别。 */
    public double ms;

    public boolean usesSql() {
        return SQL.equals(route) || MULTI.equals(route);
    }

    public boolean usesRag() {
        return RAG.equals(route) || MULTI.equals(route);
    }

    /** SSE 事件：debug=false 时不下发 detail（可能含业务字段的 SQL 全文）。 */
    public Map<String, Object> toEvent() {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("route", route);
        out.put("layer", layer);
        out.put("confidence", Math.round(confidence * 1000) / 1000.0);
        out.put("reason", reason);
        out.put("signals", signals);
        out.put("targets", targets);
        out.put("availability", availability);
        out.put("ms", ms);
        return out;
    }

    /** trace 落表用：不塞 signals 明细以外的大字段，避免 traces 表被撑大。 */
    public Map<String, Object> toCounters() {
        Map<String, Object> out = new LinkedHashMap<>(toEvent());
        return out;
    }
}
