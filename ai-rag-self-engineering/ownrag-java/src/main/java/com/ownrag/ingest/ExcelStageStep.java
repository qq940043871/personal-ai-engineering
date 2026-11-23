package com.ownrag.ingest;

import java.io.Reader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

import org.apache.poi.ss.usermodel.DataFormatter;
import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.ss.usermodel.Sheet;
import org.apache.poi.ss.usermodel.Workbook;
import org.apache.poi.ss.usermodel.WorkbookFactory;
import org.apache.poi.ss.util.CellRangeAddress;
import org.springframework.stereotype.Component;

import com.ownrag.core.Db;
import com.ownrag.core.Step;
import com.ownrag.core.StepContext;
import com.ownrag.core.StepResult;
import com.ownrag.util.Json;

/**
 * excel_stage 步骤（Python 版 ExcelStage 的平移）：逐 sheet 读 → SQLite staging 表。
 * 全 TEXT 保真：类型是推断出的结论，不是前提。
 *
 * 2026-11-23 补三处阻断项（见 docs 10-Excel通道口径.md §五）：
 *   ① 表头行探测：不再无脑取第 0 行（标题行/多级表头会把列名整个搞错）；
 *   ② 列名去重：同名/同 physical 名必须加后缀，否则 CREATE TABLE 直接报 duplicate column；
 *   ③ 合并单元格：表头区横向合并向右填充，其余合并只计数进 report（不猜业务含义）。
 * `schema_json` 同时存「原始列名 columns」与「物理列名 physical」——前者是语义真相，后者只用于 DDL/SQL。
 */
@Component
public class ExcelStageStep implements Step {

    /** 表头最多在前 5 行里找：再往下就是数据了，往下找只会把数据行当表头。 */
    private static final int HEADER_SCAN_ROWS = 5;
    /** 列数上限：防止有人把空白列拖到 XFD 导致建一张 16000 列的表。 */
    private static final int MAX_COLUMNS = 64;
    /** 与 schema_infer 同口径：千分位 + 小数 + 百分号都要认，否则表头行探测会把数值行当表头。 */
    private static final Pattern NUMBER_LIKE = Pattern.compile(
            "^-?(?:\\d{1,3}(?:,\\d{3})+|\\d+)(?:\\.\\d+)?%?$");

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
            return StepResult.fail("无有效 sheet（全部为空，或表头无法识别）");
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
                if (sheet == null) {
                    continue;
                }
                List<List<String>> grid = gridOf(sheet, fmt);
                if (grid.isEmpty()) {
                    continue;
                }
                Table table = toTable(grid, sheet.getMergedRegions());
                if (table == null || table.rows.isEmpty()) {
                    continue;
                }
                stageInto(ctx, table, src.getFileName().toString(), wb.getSheetName(i), registered);
            }
        }
    }

    private void stageCsv(StepContext ctx, Path src, List<Map<String, Object>> registered)
            throws Exception {
        List<List<String>> grid = new ArrayList<>();
        try (Reader reader = Files.newBufferedReader(src, StandardCharsets.UTF_8)) {
            List<org.apache.commons.csv.CSVRecord> records =
                    org.apache.commons.csv.CSVFormat.DEFAULT.builder()
                            .setIgnoreEmptyLines(false).setTrim(false).build()
                            .parse(reader).getRecords();
            for (org.apache.commons.csv.CSVRecord rec : records) {
                List<String> values = new ArrayList<>();
                for (int c = 0; c < rec.size() && c < MAX_COLUMNS; c++) {
                    values.add(rec.get(c));
                }
                grid.add(values);
            }
        }
        if (grid.isEmpty()) {
            return;
        }
        Table table = toTable(grid, new ArrayList<CellRangeAddress>());
        if (table == null || table.rows.isEmpty()) {
            return;
        }
        stageInto(ctx, table, src.getFileName().toString(), "csv", registered);
    }

    // ---------------------------------------------------------------- 网格与表头

    /** 整张 sheet → 字符串网格（不裁剪数据值：保真是 staging 的第一原则）。 */
    private static List<List<String>> gridOf(Sheet sheet, DataFormatter fmt) {
        int width = 0;
        int lastRow = sheet.getLastRowNum();
        for (int r = 0; r <= lastRow; r++) {
            Row row = sheet.getRow(r);
            if (row == null) {
                continue;
            }
            width = Math.max(width, Math.min(row.getLastCellNum(), MAX_COLUMNS));
        }
        if (width <= 0) {
            return new ArrayList<>();
        }
        List<List<String>> grid = new ArrayList<>();
        for (int r = 0; r <= lastRow; r++) {
            Row row = sheet.getRow(r);
            List<String> values = new ArrayList<>();
            for (int c = 0; c < width; c++) {
                String v = row == null ? "" : fmt.formatCellValue(row.getCell(c));
                values.add(v == null ? "" : v);
            }
            grid.add(values);
        }
        return grid;
    }

    /** 网格 + 合并区 → 表头行、列名、数据行。返回 null = 这张 sheet 不可用。 */
    static Table toTable(List<List<String>> grid, List<CellRangeAddress> merged) {
        int header = detectHeaderRow(grid);
        if (header < 0) {
            header = firstNonEmptyRow(grid);
        }
        if (header < 0) {
            return null;
        }
        boolean twoLevel = isSecondHeaderRow(grid, header);
        int bottom = twoLevel ? header + 1 : header;

        List<List<String>> filled = fillHeaderMerged(grid, merged, header, bottom);
        List<String> names = columnNames(filled, header, twoLevel);
        List<List<String>> data = new ArrayList<>();
        for (int r = bottom + 1; r < filled.size(); r++) {
            data.add(filled.get(r));
        }

        // 整列全空（表头也空、数据也空）的列直接丢：Excel 里拖出来的空白列不该进表
        List<Integer> keep = new ArrayList<>();
        for (int c = 0; c < names.size(); c++) {
            boolean any = !names.get(c).trim().isEmpty();
            for (List<String> row : data) {
                if (c < row.size() && !row.get(c).trim().isEmpty()) {
                    any = true;
                    break;
                }
            }
            if (any) {
                keep.add(c);
            }
        }
        if (keep.isEmpty()) {
            return null;
        }

        List<String> display = new ArrayList<>();
        for (int c : keep) {
            String n = names.get(c).trim();
            display.add(n.isEmpty() ? "col_" + (c + 1) : n);
        }
        display = dedup(display);
        List<String> physical = new ArrayList<>();
        for (String n : display) {
            physical.add(AsrClient.sanitize(n));
        }
        physical = dedup(physical);

        Table table = new Table();
        table.columns = display;
        table.physical = physical;
        table.headerRow = header;
        table.twoLevel = twoLevel;
        table.mergedHeader = countHeaderMerged(merged, header, bottom);
        table.mergedData = merged == null ? 0 : Math.max(0, merged.size() - table.mergedHeader);
        for (List<String> row : data) {
            List<String> values = new ArrayList<>();
            boolean any = false;
            for (int c : keep) {
                String v = c < row.size() ? row.get(c) : "";
                values.add(v);
                if (!v.trim().isEmpty()) {
                    any = true;
                }
            }
            if (any) {
                table.rows.add(values);
            }
        }
        return table;
    }

    /**
     * 表头行探测：在前 {@link #HEADER_SCAN_ROWS} 行里取**最早的、列数不显著少于本区最多列**的行。
     *
     * 为什么不是"得分最高者胜"（原实现）：多级表头的父级行因为合并单元格，非空格天然少于子级行，
     * 按非空数打分永远选中子级行 → 父级被当数据行、二级表头整个丢失。
     * 也不能简单地取"第一个非空 ≥2 的行"：Excel 顶部经常有一行「XX 部门统计表」之类的双格标题。
     * 折中判据：
     *   ① 非空 ≥2 且至少一个非数字（单格标题 / 全数字数据行都被排除）；
     *   ② 在候选里取最早且非空数 ≥ 最大值 60% 的行（父级行虽然少 1-2 格，仍然够格）。
     * 返回 -1 = 没有任何行像表头（调用方退化为首个非空行）。
     */
    static int detectHeaderRow(List<List<String>> grid) {
        int limit = Math.min(grid.size(), HEADER_SCAN_ROWS);
        int[] nonEmpty = new int[limit];
        boolean[] ok = new boolean[limit];
        int max = 0;
        for (int r = 0; r < limit; r++) {
            int ne = 0;
            int numeric = 0;
            for (String v : grid.get(r)) {
                if (v == null || v.trim().isEmpty()) {
                    continue;
                }
                ne++;
                if (NUMBER_LIKE.matcher(v.trim()).matches()) {
                    numeric++;
                }
            }
            nonEmpty[r] = ne;
            // 表头几乎不含数字（日期/金额这类"看起来像表头"的列名是少数）：
            // 数字占比超 20% 的行按数据行排除——否则一条 4 列的数据行会把 3 列表头挤掉
            ok[r] = ne >= 2 && numeric * 5 <= ne;
            if (ok[r]) {
                max = Math.max(max, ne);
            }
        }
        if (max == 0) {
            return -1;
        }
        int floor = (int) Math.ceil(max * 0.6);
        for (int r = 0; r < limit; r++) {
            if (ok[r] && nonEmpty[r] >= floor) {
                return r;
            }
        }
        return -1;
    }

    private static int firstNonEmptyRow(List<List<String>> grid) {
        for (int r = 0; r < grid.size(); r++) {
            for (String v : grid.get(r)) {
                if (v != null && !v.trim().isEmpty()) {
                    return r;
                }
            }
        }
        return -1;
    }

    /**
     * 多级表头判定：下一行是"纯文本且非空 ≥2"，并且本行存在**空洞**（两个非空之间的空格，
     * 典型来自横向合并的父级表头）。缺"空洞"这一条会把「表头 + 全文本数据行」误判成两级表头。
     */
    static boolean isSecondHeaderRow(List<List<String>> grid, int header) {
        if (header + 1 >= grid.size()) {
            return false;
        }
        List<String> parent = grid.get(header);
        List<String> child = grid.get(header + 1);
        if (!hasHole(parent)) {
            return false;
        }
        int childNonEmpty = 0;
        int parentNonEmpty = 0;
        for (String v : parent) {
            if (v != null && !v.trim().isEmpty()) {
                parentNonEmpty++;
            }
        }
        for (String v : child) {
            if (v == null || v.trim().isEmpty()) {
                continue;
            }
            if (NUMBER_LIKE.matcher(v.trim()).matches()) {
                return false;   // 子行带数字 = 数据行
            }
            if (v.trim().length() > 20) {
                return false;   // 长文本 = 数据，不是二级表头
            }
            childNonEmpty++;
        }
        return childNonEmpty >= 2 && childNonEmpty * 2 >= Math.max(1, parentNonEmpty);
    }

    private static boolean hasHole(List<String> row) {
        boolean seen = false;
        boolean hole = false;
        for (String v : row) {
            boolean empty = v == null || v.trim().isEmpty();
            if (!empty) {
                if (hole) {
                    return true;
                }
                seen = true;
            } else if (seen) {
                hole = true;
            }
        }
        return false;
    }

    /** 表头区的合并单元格向右/向下填充（只动表头行，数据区的合并只计数）。 */
    private static List<List<String>> fillHeaderMerged(List<List<String>> grid,
                                                       List<CellRangeAddress> merged,
                                                       int top, int bottom) {
        List<List<String>> out = new ArrayList<>();
        for (List<String> row : grid) {
            out.add(new ArrayList<>(row));
        }
        if (merged == null) {
            return out;
        }
        for (CellRangeAddress region : merged) {
            if (region.getLastRow() < top || region.getFirstRow() > bottom) {
                continue;
            }
            int r0 = Math.max(top, region.getFirstRow());
            int r1 = Math.min(bottom, region.getLastRow());
            String value = cellAt(out, region.getFirstRow(), region.getFirstColumn());
            for (int r = r0; r <= r1 && r < out.size(); r++) {
                List<String> row = out.get(r);
                for (int c = region.getFirstColumn(); c <= region.getLastColumn() && c < row.size(); c++) {
                    if (c != region.getFirstColumn() || r != region.getFirstRow()) {
                        row.set(c, value);
                    }
                }
            }
        }
        return out;
    }

    private static int countHeaderMerged(List<CellRangeAddress> merged, int top, int bottom) {
        int n = 0;
        if (merged == null) {
            return 0;
        }
        for (CellRangeAddress region : merged) {
            if (region.getLastRow() >= top && region.getFirstRow() <= bottom) {
                n++;
            }
        }
        return n;
    }

    private static String cellAt(List<List<String>> grid, int r, int c) {
        if (r < 0 || r >= grid.size()) {
            return "";
        }
        List<String> row = grid.get(r);
        return c >= 0 && c < row.size() ? row.get(c) : "";
    }

    /** 列名：两级表头拼 `父_子`，父级按最后出现的非空向右延续；单级表头直接用本行值。 */
    private static List<String> columnNames(List<List<String>> grid, int header, boolean twoLevel) {
        List<String> out = new ArrayList<>();
        List<String> parentRow = grid.get(header);
        List<String> childRow = twoLevel && header + 1 < grid.size() ? grid.get(header + 1) : new ArrayList<>();
        String carry = "";
        for (int c = 0; c < parentRow.size(); c++) {
            String parent = clean(parentRow.get(c));
            if (!parent.isEmpty()) {
                carry = parent;
            }
            if (!twoLevel) {
                out.add(parent);
                continue;
            }
            String child = c < childRow.size() ? clean(childRow.get(c)) : "";
            if (carry.isEmpty() && child.isEmpty()) {
                out.add("");
            } else if (carry.isEmpty()) {
                out.add(child);
            } else if (child.isEmpty() || child.equals(carry)) {
                out.add(carry);
            } else {
                out.add(carry + "_" + child);
            }
        }
        return out;
    }

    /** 列名去重：同名追加 `_2`、`_3`；这是 `CREATE TABLE` 不报 duplicate column 的前提。 */
    static List<String> dedup(List<String> names) {
        List<String> out = new ArrayList<>();
        Set<String> used = new HashSet<>();
        for (String n : names) {
            String base = n == null ? "" : n;
            String cand = base;
            int k = 2;
            while (used.contains(cand)) {
                cand = base + "_" + (k++);
            }
            used.add(cand);
            out.add(cand);
        }
        return out;
    }

    private static String clean(String v) {
        if (v == null) {
            return "";
        }
        return v.replaceAll("[\\r\\n\\t]+", " ").replaceAll("\\s{2,}", " ").trim();
    }

    // ---------------------------------------------------------------- 落库

    /**
     * 建表 + 灌数 + **原子换表**（docs 10-Excel通道口径.md §4.2）。
     *
     * 旧实现是 `DROP IF EXISTS` 原地重建：重传同一份 Excel 时，DROP 与 INSERT 之间有一段窗口，
     * 查询会打到空表、返回 0 行——看起来像"数据没了"，实际是"正在换表"。这里改成三段：
     *
     *   ① 建 `_v<epoch秒>` 新表并灌数（读者仍打旧表，完全无感）
     *   ② 单事务：删该 sheet 的旧登记行 + 写新登记行（切换点：读者要么看到旧、要么看到新，不会两者都有）
     *   ③ 提交后再 DROP 旧表（失败只是留垃圾，不影响正确性；StagingStore 有前缀兜底清理）
     *
     * 注意登记表 PK 是 (doc_id, table_name)，新表名不同 → 必须先 DELETE 旧行再 INSERT，
     * 不能只 INSERT OR REPLACE（那会留下两行，目录里同一 sheet 出现两次）。
     */
    private void stageInto(StepContext ctx, Table table, String srcFile, String sheet,
                           List<Map<String, Object>> registered) throws SQLException {
        String base = "staging_" + ctx.docId.substring(0, Math.min(8, ctx.docId.length()))
                + "_" + AsrClient.sanitize(sheet);
        String name = base + "_v" + (System.currentTimeMillis() / 1000L);
        StringBuilder defs = new StringBuilder();
        for (String c : table.physical) {
            if (defs.length() > 0) {
                defs.append(", ");
            }
            defs.append('"').append(c).append("\" TEXT");
        }

        // ① 新表（同秒重跑先清同名残留；此时旧表仍在，查询不受影响）
        try (Statement st = ctx.conn.createStatement()) {
            st.executeUpdate("DROP TABLE IF EXISTS \"" + name + "\"");
            st.executeUpdate("CREATE TABLE \"" + name + "\" (" + defs
                    + ", \"_src_file\" TEXT, \"_sheet\" TEXT, \"_rownum\" INTEGER)");
        }
        StringBuilder insert = new StringBuilder("INSERT INTO \"" + name + "\" VALUES (");
        for (int i = 0; i < table.physical.size() + 3; i++) {
            if (i > 0) {
                insert.append(", ");
            }
            insert.append('?');
        }
        insert.append(')');
        try (PreparedStatement ps = ctx.conn.prepareStatement(insert.toString())) {
            int rownum = 1;
            for (List<String> values : table.rows) {
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
        ctx.conn.commit();   // 新表落定（尚未被任何登记行引用，读者看不到）

        // 旧表名：切换前收集，切换后用来清理
        List<String> old = new ArrayList<>();
        try (PreparedStatement ps = ctx.conn.prepareStatement(
                "SELECT table_name FROM staging_registry WHERE doc_id=? AND COALESCE(sheet,'')=?")) {
            ps.setString(1, ctx.docId);
            ps.setString(2, sheet == null ? "" : sheet);
            try (ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    old.add(rs.getString(1));
                }
            }
        }
        Db.endRead(ctx.conn);   // 读后要写：收尾读快照

        // ② 原子切换：删除该 sheet 旧登记行 + 插入新行（同事务）
        // 原始列名 = 语义真相；physical = 只用于 DDL/SQL。两列都存，展示与生成各取所需
        Map<String, Object> schema = new LinkedHashMap<>();
        schema.put("columns", table.columns);
        schema.put("physical", table.physical);
        schema.put("header_row", table.headerRow);
        schema.put("two_level_header", table.twoLevel);
        schema.put("merged_header_cells", table.mergedHeader);
        schema.put("merged_data_cells", table.mergedData);
        schema.put("swap_at", System.currentTimeMillis());
        try (PreparedStatement ps = ctx.conn.prepareStatement(
                "DELETE FROM staging_registry WHERE doc_id=? AND COALESCE(sheet,'')=?")) {
            ps.setString(1, ctx.docId);
            ps.setString(2, sheet == null ? "" : sheet);
            ps.executeUpdate();
        }
        try (PreparedStatement ps = ctx.conn.prepareStatement(
                "INSERT INTO staging_registry(doc_id, table_name, sheet, schema_json) VALUES (?,?,?,?)")) {
            ps.setString(1, ctx.docId);
            ps.setString(2, name);
            ps.setString(3, sheet);
            ps.setString(4, Json.write(schema));
            ps.executeUpdate();
        }
        ctx.conn.commit();

        // ③ 旧表延后删：这一步失败只是留垃圾，绝不回滚切换（正确性优先于整洁）
        try (Statement st = ctx.conn.createStatement()) {
            for (String t : old) {
                if (!t.equals(name)) {
                    st.executeUpdate("DROP TABLE IF EXISTS \"" + t.replace("\"", "\"\"") + "\"");
                }
            }
        }
        ctx.conn.commit();

        Map<String, Object> item = new LinkedHashMap<>();
        item.put("table", name);
        item.put("sheet", sheet);
        item.put("rows", table.rows.size());
        item.put("columns", table.columns);
        item.put("physical", table.physical);
        registered.add(item);
    }

    /** 一张 sheet 的解析结果（表头 + 列名 + 数据行 + 合并统计）。 */
    static class Table {
        List<String> columns = new ArrayList<>();   // 原始列名（语义）
        List<String> physical = new ArrayList<>();  // DDL/ SQL 用列名（去重后的 sanitize）
        List<List<String>> rows = new ArrayList<>();
        int headerRow;
        boolean twoLevel;
        int mergedHeader;
        int mergedData;
    }

    /** 步骤内已知失败的统一出口（不污染外层 catch 的"意外失败"语义）。 */
    static class StepResultException extends RuntimeException {
        public StepResultException(String message) {
            super(message);
        }
    }
}
