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
 *
 *   catalog（默认，2026-11-23 起）：**一张 sheet 一块目录**——列名/类型/样本/行数/主键候选/查询提示。
 *      这是"Excel 行不嵌入"的落地方式：目录进 FTS 只为了让"有哪些表、哪些列"可被检索到，
 *      它本身不含业务结论，模型无法据此编数字；精确数值一律走查询期 SQL（docs 11）。
 *   row_card（保留）：每行一张"字段: 值"卡片。只在"没有 SQL 能力"时才该用；
 *      本工程有 SQL 通道之后它是负资产（同一事实存两份 → 必然漂移，且聚合题必错）。
 *   aggregate：已由查询期 SQL 通道承担，不在入库期做。
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
        String strategy = params.get("strategy") == null ? "catalog" : String.valueOf(params.get("strategy"));
        List<Map<String, Object>> staged =
                (List<Map<String, Object>>) ctx.data.getOrDefault("staged", new ArrayList<>());
        List<Map<String, Object>> schemas =
                (List<Map<String, Object>>) ctx.data.getOrDefault("schemas", new ArrayList<>());
        if ("aggregate".equals(strategy)) {
            return StepResult.fail("aggregate 由查询期 SQL 通道承担（见 docs 11-查询路由与多源编排），"
                    + "入库请用 catalog / row_card");
        }
        if ("row_card".equals(strategy)) {
            return rowCard(ctx, staged, params);
        }
        return catalog(ctx, staged, schemas, params);
    }

    // ---------------------------------------------------------------- catalog

    @SuppressWarnings("unchecked")
    private StepResult catalog(StepContext ctx, List<Map<String, Object>> staged,
                               List<Map<String, Object>> schemas, Map<String, Object> params) {
        int sampleRows = params.get("sample_rows") instanceof Number
                ? ((Number) params.get("sample_rows")).intValue() : 3;
        String file = Paths.get(String.valueOf(ctx.data.get("source_path"))).getFileName().toString();
        List<String> blocks = new ArrayList<>();
        try {
            for (Map<String, Object> schema : schemas) {
                String table = String.valueOf(schema.get("table"));
                String sheet = String.valueOf(schema.get("sheet"));
                int rows = ((Number) schema.get("rows")).intValue();
                List<Map<String, Object>> cols =
                        (List<Map<String, Object>>) schema.getOrDefault("columns", new ArrayList<>());
                String pk = schema.get("pk_column") == null ? null : String.valueOf(schema.get("pk_column"));

                StringBuilder sb = new StringBuilder();
                sb.append("#### ").append(file).append(" / ").append(sheet)
                        .append("（").append(rows).append(" 行）\n\n");

                List<String> colDesc = new ArrayList<>();
                List<String> aggregatable = new ArrayList<>();
                for (Map<String, Object> c : cols) {
                    String name = String.valueOf(c.get("column"));
                    String type = String.valueOf(c.get("type"));
                    String desc = name + "(" + type;
                    if ("enum".equals(type)) {
                        List<String> vals = strings(c.get("samples"));
                        if (!vals.isEmpty()) {
                            desc += ": " + String.join("/", vals.size() > 8 ? vals.subList(0, 8) : vals);
                        }
                    }
                    desc += ")";
                    colDesc.add(desc);
                    if ("number".equals(type)) {
                        aggregatable.add(name);
                    }
                }
                sb.append("- 列：").append(String.join("、", colDesc)).append('\n');
                if (pk != null && !pk.isEmpty()) {
                    sb.append("- 主键候选：").append(pk).append("（非空 100%，唯一 100%）\n");
                }
                if (!aggregatable.isEmpty()) {
                    sb.append("- 可聚合列：").append(String.join("、", aggregatable))
                            .append("（数值列物理上是 TEXT，聚合须先转 REAL）\n");
                }
                List<String> samples = sampleRows(ctx, table, cols, sampleRows);
                if (!samples.isEmpty()) {
                    sb.append("- 样本（前 ").append(samples.size()).append(" 行）：")
                            .append(String.join(" ｜ ", samples)).append('\n');
                }
                sb.append("- 查询提示：本表是结构化明细，统计/筛选请走 SQL（SELECT），")
                        .append("不要从本段文字里推算数字");
                blocks.add(sb.toString());
            }
        } catch (Exception e) {
            return StepResult.fail("目录文本化失败：" + e.getMessage());
        }
        if (blocks.isEmpty()) {
            return StepResult.fail("目录文本化零块（schema 缺失？）");
        }
        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put("source_file", file);
        metadata.put("strategy", "catalog");
        List<String> tables = new ArrayList<>();
        for (Map<String, Object> s : staged) {
            tables.add(String.valueOf(s.get("table")));
        }
        metadata.put("tables", tables);
        // 目录块用独立 source_type：`excel` 是历史行卡片的标记（迁移时要清掉），
        // `excel_catalog` 才是"目录"——两者混用会让"清行卡片"顺手把目录也删了
        metadata.put("source_type", "excel_catalog");
        metadata.put("catalog", true);
        Object sourceMeta = ctx.data.get("source_meta");
        if (sourceMeta instanceof Map) {
            metadata.putAll((Map<String, Object>) sourceMeta);
        }
        Map<String, Object> stats = new LinkedHashMap<>();
        stats.put("blocks", blocks.size());
        stats.put("sheets", schemaCount(ctx));
        ParsedDoc doc = new ParsedDoc(ctx.docId, "excel_catalog", String.join("\n\n", blocks),
                metadata, new ArrayList<>(), new LinkedHashMap<>(), stats);
        ctx.data.put("parsed", doc.toMap());
        return StepResult.okMetrics("blocks", blocks.size(), "sheets", stats.get("sheets"));
    }

    private static int schemaCount(StepContext ctx) {
        Object s = ctx.data.get("schemas");
        return s instanceof List ? ((List<?>) s).size() : 0;
    }

    /** 前 N 行样本：按原始列名展示，值取自物理列（与 SQL 里看到的完全一致）。 */
    @SuppressWarnings("unchecked")
    private static List<String> sampleRows(StepContext ctx, String table,
                                          List<Map<String, Object>> cols, int limit) throws Exception {
        List<String> out = new ArrayList<>();
        if (limit <= 0 || cols.isEmpty()) {
            return out;
        }
        try (Statement st = ctx.conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT * FROM \"" + table + "\" LIMIT " + limit)) {
            while (rs.next()) {
                List<String> parts = new ArrayList<>();
                for (Map<String, Object> c : cols) {
                    String v = rs.getString(String.valueOf(c.get("physical")));
                    if (v != null && !v.trim().isEmpty()) {
                        parts.add(String.valueOf(c.get("column")) + "=" + v.trim());
                    }
                }
                if (!parts.isEmpty()) {
                    out.add(String.join(", ", parts));
                }
            }
        }
        return out;
    }

    // ---------------------------------------------------------------- row_card（保留）

    @SuppressWarnings("unchecked")
    private StepResult rowCard(StepContext ctx, List<Map<String, Object>> staged,
                               Map<String, Object> params) {
        int maxRows = params.get("max_rows") instanceof Number
                ? ((Number) params.get("max_rows")).intValue() : 5000;
        List<String> blocks = new ArrayList<>();
        int[] skipped = {0};
        try {
            for (Map<String, Object> item : staged) {
                String table = String.valueOf(item.get("table"));
                String sheet = String.valueOf(item.get("sheet"));
                List<String> physical = SchemaInferStep.nonMetaColumns(ctx.conn, table);
                List<String> display = displayOf(item, physical);
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
                        for (int i = 0; i < physical.size(); i++) {
                            String v = rs.getString(physical.get(i));
                            if (v != null && !v.trim().isEmpty()) {
                                pairs.add(display.get(i) + ": " + v);
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
        metadata.put("strategy", "row_card");
        metadata.put("source_type", "excel");
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

    private static List<String> displayOf(Map<String, Object> item, List<String> physical) {
        Object c = item.get("columns");
        List<String> out = new ArrayList<>();
        for (int i = 0; i < physical.size(); i++) {
            if (c instanceof List && i < ((List<?>) c).size()) {
                out.add(String.valueOf(((List<?>) c).get(i)));
            } else {
                out.add(physical.get(i));
            }
        }
        return out;
    }

    private static List<String> strings(Object v) {
        List<String> out = new ArrayList<>();
        if (v instanceof List) {
            for (Object o : (List<?>) v) {
                if (o != null) {
                    out.add(String.valueOf(o));
                }
            }
        }
        return out;
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
