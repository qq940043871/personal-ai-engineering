package com.ownrag.ingest;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

import org.springframework.stereotype.Component;

import com.ownrag.core.Step;
import com.ownrag.core.StepContext;
import com.ownrag.core.StepResult;

/**
 * schema_infer 步骤（Python 版 SchemaInfer 的平移）：列名 / 非空率 / 样本值 / 类型推断。
 * 优先级：日期 > 数值 > 枚举 > 自由文本（匹配率 >0.8 判型）。
 */
@Component
public class SchemaInferStep implements Step {

    private static final Pattern DATE_RX = Pattern.compile("^\\d{4}[-/年]\\d{1,2}([-/月]\\d{1,2})?日?$");
    private static final Pattern NUMBER_RX = Pattern.compile("^-?\\d+([.,]\\d+)?%?$");

    @SuppressWarnings("unchecked")
    @Override
    public String type() {
        return "schema_infer";
    }

    @SuppressWarnings("unchecked")
    @Override
    public StepResult run(StepContext ctx, Map<String, Object> params) {
        List<Map<String, Object>> staged =
                (List<Map<String, Object>>) ctx.data.getOrDefault("staged", new ArrayList<>());
        int sampleN = params.get("sample_n") instanceof Number ? ((Number) params.get("sample_n")).intValue() : 5;
        List<Map<String, Object>> schemas = new ArrayList<>();
        try {
            for (Map<String, Object> item : staged) {
                String table = String.valueOf(item.get("table"));
                int rows = ((Number) item.get("rows")).intValue();
                List<String> cols = nonMetaColumns(ctx.conn, table);
                List<Map<String, Object>> colInfo = new ArrayList<>();
                for (String c : cols) {
                    List<String> vals = new ArrayList<>();
                    try (Statement st = ctx.conn.createStatement(); ResultSet rs = st.executeQuery(
                            "SELECT \"" + AsrClient.sanitize(c) + "\" FROM \"" + table
                                    + "\" WHERE TRIM(COALESCE(\"" + AsrClient.sanitize(c)
                                    + "\",''))<>'' LIMIT 200")) {
                        while (rs.next()) {
                            vals.add(rs.getString(1));
                        }
                    }
                    double nonnullRate = Math.round((double) vals.size() / Math.max(rows, 1) * 100) / 100.0;
                    String ctype = "text";
                    if (!vals.isEmpty()) {
                        if (matchRate(vals, DATE_RX) > 0.8) {
                            ctype = "date";
                        } else if (matchRate(vals, NUMBER_RX) > 0.8) {
                            ctype = "number";
                        } else if (new java.util.LinkedHashSet<>(vals).size() <= Math.max(3, vals.size() / 20)) {
                            ctype = "enum";
                        }
                    }
                    Map<String, Object> info = new LinkedHashMap<>();
                    info.put("column", c);
                    info.put("type", ctype);
                    info.put("nonnull_rate", nonnullRate);
                    info.put("samples", vals.subList(0, Math.min(sampleN, vals.size())));
                    colInfo.add(info);
                }
                Map<String, Object> schema = new LinkedHashMap<>();
                schema.put("table", table);
                schema.put("sheet", item.get("sheet"));
                schema.put("rows", rows);
                schema.put("columns", colInfo);
                schemas.add(schema);
            }
        } catch (Exception e) {
            return StepResult.fail("schema 推断失败：" + e.getMessage());
        }
        ctx.data.put("schemas", schemas);
        int columns = 0;
        for (Map<String, Object> s : schemas) {
            columns += ((List<?>) s.get("columns")).size();
        }
        return StepResult.okMetrics("tables", schemas.size(), "columns", columns);
    }

    static List<String> nonMetaColumns(Connection conn, String table) throws Exception {
        List<String> cols = new ArrayList<>();
        try (Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("PRAGMA table_info(\"" + table + "\")")) {
            while (rs.next()) {
                String name = rs.getString("name");
                if (!name.startsWith("_")) {
                    cols.add(name);
                }
            }
        }
        return cols;
    }

    static double matchRate(List<String> vals, Pattern rx) {
        if (vals.isEmpty()) {
            return 0.0;
        }
        int hits = 0;
        for (String v : vals) {
            if (rx.matcher(v == null ? "" : v.trim()).matches()) {
                hits++;
            }
        }
        return (double) hits / vals.size();
    }
}
