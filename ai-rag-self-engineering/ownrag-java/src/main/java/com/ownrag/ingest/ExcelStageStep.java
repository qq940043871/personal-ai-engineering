package com.ownrag.ingest;

import java.io.Reader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.apache.poi.ss.usermodel.DataFormatter;
import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.ss.usermodel.Sheet;
import org.apache.poi.ss.usermodel.Workbook;
import org.apache.poi.ss.usermodel.WorkbookFactory;
import org.springframework.stereotype.Component;

import com.ownrag.core.Step;
import com.ownrag.core.StepContext;
import com.ownrag.core.StepResult;
import com.ownrag.util.Json;

/**
 * excel_stage 步骤（Python 版 ExcelStage 的平移）：逐 sheet 读 → SQLite staging 表。
 * 全 TEXT 保真：类型是推断出的结论，不是前提。
 */
@Component
public class ExcelStageStep implements Step {

    @Override
    public String type() {
        return "excel_stage";
    }

    @Override
    public StepResult run(StepContext ctx, Map<String, Object> params) {
        Path src = Paths.get(String.valueOf(ctx.data.get("source_path")));
        String name = src.getFileName().toString().toLowerCase();
        List<Map<String, Object>> registered = new ArrayList<>();
        try {
            if (name.endsWith(".csv")) {
                stageCsv(ctx, src, registered);
            } else {
                stageXlsx(ctx, src, registered);
            }
        } catch (StepResultException e) {
            return StepResult.fail(e.getMessage());
        } catch (Exception e) {
            return StepResult.fail("Excel 读取失败：" + e.getMessage());
        }
        if (registered.isEmpty()) {
            return StepResult.fail("无有效 sheet（全部为空）");
        }
        ctx.data.put("staged", registered);
        int rows = 0;
        for (Map<String, Object> r : registered) {
            rows += ((Number) r.get("rows")).intValue();
        }
        return StepResult.okMetrics("tables", registered.size(), "rows", rows);
    }

    private void stageXlsx(StepContext ctx, Path src, List<Map<String, Object>> registered)
            throws Exception {
        DataFormatter fmt = new DataFormatter();
        try (Workbook wb = WorkbookFactory.create(src.toFile())) {
            for (int i = 0; i < wb.getNumberOfSheets(); i++) {
                Sheet sheet = wb.getSheetAt(i);
                if (sheet == null || sheet.getRow(0) == null) {
                    continue;
                }
                Row header = sheet.getRow(0);
                List<String> cols = new ArrayList<>();
                short last = header.getLastCellNum();
                for (int c = 0; c < last; c++) {
                    String col = fmt.formatCellValue(header.getCell(c)).trim();
                    cols.add(col.isEmpty() ? "col_" + (c + 1) : col);
                }
                List<List<String>> rows = new ArrayList<>();
                for (int r = 1; r <= sheet.getLastRowNum(); r++) {
                    Row row = sheet.getRow(r);
                    if (row == null) {
                        continue;
                    }
                    List<String> values = new ArrayList<>();
                    boolean any = false;
                    for (int c = 0; c < cols.size(); c++) {
                        String v = fmt.formatCellValue(row.getCell(c));
                        values.add(v);
                        if (!v.trim().isEmpty()) {
                            any = true;
                        }
                    }
                    if (any) {
                        rows.add(values);
                    }
                }
                if (rows.isEmpty()) {
                    continue;
                }
                stageInto(ctx, cols, rows, src.getFileName().toString(),
                        wb.getSheetName(i), registered);
            }
        }
    }

    private void stageCsv(StepContext ctx, Path src, List<Map<String, Object>> registered)
            throws Exception {
        List<List<String>> rows = new ArrayList<>();
        List<String> cols;
        try (Reader reader = Files.newBufferedReader(src, StandardCharsets.UTF_8)) {
            List<org.apache.commons.csv.CSVRecord> records =
                    org.apache.commons.csv.CSVFormat.DEFAULT.builder()
                            .setIgnoreEmptyLines(false).setTrim(false).build()
                            .parse(reader).getRecords();
            if (records.isEmpty()) {
                return;
            }
            cols = new ArrayList<>();
            for (String h : records.get(0)) {
                cols.add(h.trim());
            }
            for (int i = 1; i < records.size(); i++) {
                org.apache.commons.csv.CSVRecord rec = records.get(i);
                List<String> values = new ArrayList<>();
                boolean any = false;
                for (int c = 0; c < cols.size(); c++) {
                    String v = c < rec.size() ? rec.get(c) : "";
                    values.add(v);
                    if (!v.trim().isEmpty()) {
                        any = true;
                    }
                }
                if (any) {
                    rows.add(values);
                }
            }
        }
        if (!rows.isEmpty()) {
            stageInto(ctx, cols, rows, src.getFileName().toString(), "csv", registered);
        }
    }

    private void stageInto(StepContext ctx, List<String> cols, List<List<String>> rows,
                           String srcFile, String sheet, List<Map<String, Object>> registered)
            throws SQLException {
        String table = "staging_" + ctx.docId.substring(0, Math.min(8, ctx.docId.length()))
                + "_" + AsrClient.sanitize(sheet);
        StringBuilder defs = new StringBuilder();
        for (String c : cols) {
            if (defs.length() > 0) {
                defs.append(", ");
            }
            defs.append('"').append(AsrClient.sanitize(c)).append("\" TEXT");
        }
        try (Statement st = ctx.conn.createStatement()) {
            st.executeUpdate("DROP TABLE IF EXISTS \"" + table + "\"");
            st.executeUpdate("CREATE TABLE \"" + table + "\" (" + defs
                    + ", \"_src_file\" TEXT, \"_sheet\" TEXT, \"_rownum\" INTEGER)");
        }
        StringBuilder insert = new StringBuilder("INSERT INTO \"" + table + "\" VALUES (");
        for (int i = 0; i < cols.size() + 3; i++) {
            if (i > 0) {
                insert.append(", ");
            }
            insert.append('?');
        }
        insert.append(')');
        try (PreparedStatement ps = ctx.conn.prepareStatement(insert.toString())) {
            int rownum = 1;
            for (List<String> values : rows) {
                int idx = 1;
                for (String v : values) {
                    ps.setString(idx++, v);
                }
                ps.setString(idx++, srcFile);
                ps.setString(idx++, sheet);
                ps.setInt(idx, rownum++);
                ps.addBatch();
            }
            ps.executeBatch();
        }
        Map<String, Object> schema = new LinkedHashMap<>();
        schema.put("columns", cols);
        try (PreparedStatement ps = ctx.conn.prepareStatement(
                "INSERT OR REPLACE INTO staging_registry(doc_id, table_name, sheet, schema_json) "
                        + "VALUES (?,?,?,?)")) {
            ps.setString(1, ctx.docId);
            ps.setString(2, table);
            ps.setString(3, sheet);
            ps.setString(4, Json.write(schema));
            ps.executeUpdate();
        }
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("table", table);
        item.put("sheet", sheet);
        item.put("rows", rows.size());
        item.put("columns", cols);
        registered.add(item);
        ctx.conn.commit();
    }

    /** 步骤内已知失败的统一出口（不污染外层 catch 的"意外失败"语义）。 */
    static class StepResultException extends RuntimeException {
        public StepResultException(String message) {
            super(message);
        }
    }
}
