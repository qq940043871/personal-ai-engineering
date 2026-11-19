package com.ownrag.ingest;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.stereotype.Component;

import com.ownrag.core.Step;
import com.ownrag.core.StepContext;
import com.ownrag.core.StepResult;

/**
 * column_mapping 步骤（Python 版 ColumnMapping 的平移）：
 * LLM 给建议映射，人工确认后生效（写待办 = HITL 卡点）。
 * 默认恒等映射 + 待办提示；LLM 建议为 params.suggest_by_llm=true 时的增强（M2）。
 */
@Component
public class ColumnMappingStep implements Step {

    @SuppressWarnings("unchecked")
    @Override
    public String type() {
        return "column_mapping";
    }

    @SuppressWarnings("unchecked")
    @Override
    public StepResult run(StepContext ctx, Map<String, Object> params) {
        List<Map<String, Object>> schemas =
                (List<Map<String, Object>>) ctx.data.getOrDefault("schemas", new ArrayList<>());
        Map<String, Object> mapping = new LinkedHashMap<>();
        for (Map<String, Object> s : schemas) {
            Map<String, Object> tableMap = new LinkedHashMap<>();
            for (Map<String, Object> c : (List<Map<String, Object>>) s.get("columns")) {
                tableMap.put(String.valueOf(c.get("column")), String.valueOf(c.get("column")));
            }
            mapping.put(String.valueOf(s.get("table")), tableMap);
        }
        ctx.data.put("column_mapping", mapping);
        if (Boolean.TRUE.equals(params.get("suggest_by_llm"))) {
            try (java.sql.PreparedStatement ps = ctx.conn.prepareStatement(
                    "INSERT INTO todos(task_id, doc_id, reason, payload_json) VALUES (?,?,?,?)")) {
                ps.setString(1, null);
                ps.setString(2, ctx.docId);
                ps.setString(3, "Excel 列语义映射待人工确认（当前为恒等映射）");
                String payload = com.ownrag.util.Json.write(schemas);
                ps.setString(4, payload.length() > 4000 ? payload.substring(0, 4000) : payload);
                ps.executeUpdate();
                ctx.conn.commit();
            } catch (Exception e) {
                return StepResult.fail("待办写入失败：" + e.getMessage());
            }
        }
        return StepResult.okMetrics("tables", mapping.size());
    }
}
