package com.ownrag.ingest;

import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.stereotype.Component;

import com.ownrag.core.Step;
import com.ownrag.core.StepContext;
import com.ownrag.core.StepResult;

/**
 * textualize 步骤（Python 版 Textualize 的平移）：
 * row_card：每行一张"字段: 值"卡片文本（明细查询类）。
 * aggregate：分组聚合摘要，数字必须来自 SQL 结果（M2 实现 SQL 路径，先立接口）。
 */
@Component
public class TextualizeStep implements Step {

    @SuppressWarnings("unchecked")
    @Override
    public String type() {
        return "textualize";
    }

    @SuppressWarnings("unchecked")
    @Override
    public StepResult run(StepContext ctx, Map<String, Object> params) {
        String strategy = params.get("strategy") == null ? "row_card" : String.valueOf(params.get("strategy"));
        List<Map<String, Object>> staged =
                (List<Map<String, Object>>) ctx.data.getOrDefault("staged", new ArrayList<>());
        int maxRows = params.get("max_rows") instanceof Number ? ((Number) params.get("max_rows")).intValue() : 5000;
        if ("aggregate".equals(strategy)) {
            return StepResult.fail("aggregate 策略属 M2（问题→SQL→结果直入答案），当前先用 row_card");
        }
        List<String> blocks = new ArrayList<>();
        int[] skipped = {0};
        try {
            for (Map<String, Object> item : staged) {
                String table = String.valueOf(item.get("table"));
                String sheet = String.valueOf(item.get("sheet"));
                List<String> cols = SchemaInferStep.nonMetaColumns(ctx.conn, table);
                int rownum = 0;
                try (Statement st = ctx.conn.createStatement();
                     ResultSet rs = st.executeQuery("SELECT * FROM \"" + table + "\" LIMIT " + (maxRows + 1))) {
                    while (rs.next()) {
                        rownum++;
                        if (rownum > maxRows) {
                            int rows = ((Number) item.get("rows")).intValue();
                            skipped[0] += Math.max(0, rows - maxRows);
                            break;
                        }
                        List<String> pairs = new ArrayList<>();
                        for (String c : cols) {
                            String v = rs.getString(AsrClient.sanitize(c));
                            if (v != null && !v.trim().isEmpty()) {
                                pairs.add(c + ": " + v);
                            }
                        }
                        if (pairs.isEmpty()) {
                            continue;
                        }
                        blocks.add("#### " + sheet + " 第 " + rownum + " 行\n\n" + joinBullets(pairs));
                    }
                }
            }
        } catch (Exception e) {
            return StepResult.fail("文本化失败：" + e.getMessage());
        }
        if (blocks.isEmpty()) {
            return StepResult.fail("文本化零块（全空表？）");
        }
        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put("source_file", Paths.get(String.valueOf(ctx.data.get("source_path"))).getFileName().toString());
        metadata.put("strategy", strategy);
        List<String> tables = new ArrayList<>();
        for (Map<String, Object> s : staged) {
            tables.add(String.valueOf(s.get("table")));
        }
        metadata.put("tables", tables);
        Object sourceMeta = ctx.data.get("source_meta");
        if (sourceMeta instanceof Map) {
            metadata.putAll((Map<String, Object>) sourceMeta);
        }
        Map<String, Object> stats = new LinkedHashMap<>();
        stats.put("blocks", blocks.size());
        stats.put("skipped_rows", skipped[0]);
        ParsedDoc doc = new ParsedDoc(ctx.docId, "excel", String.join("\n\n", blocks),
                metadata, new ArrayList<>(), new LinkedHashMap<>(), stats);
        ctx.data.put("parsed", doc.toMap());
        return StepResult.okMetrics("blocks", blocks.size(), "skipped_rows", skipped[0]);
    }

    private static String joinBullets(List<String> pairs) {
        StringBuilder sb = new StringBuilder();
        for (String p : pairs) {
            if (sb.length() > 0) {
                sb.append('\n');
            }
            sb.append("- ").append(p);
        }
        return sb.toString();
    }
}
