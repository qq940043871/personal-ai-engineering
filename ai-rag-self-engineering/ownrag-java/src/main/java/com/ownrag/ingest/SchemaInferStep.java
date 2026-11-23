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

import com.ownrag.core.Db;
import com.ownrag.core.Step;
import com.ownrag.core.StepContext;
import com.ownrag.core.StepResult;
import com.ownrag.util.Json;

/**
 * schema_infer 步骤（Python 版 SchemaInfer 的平移）：列名 / 非空率 / 样本值 / 类型推断。
 * 优先级：日期 > 数值 > 枚举 > 自由文本（匹配率 >0.8 判型）。
 *
 * 2026-11-23 起多产两样东西（SQL 通道的前提，见 docs 10-Excel通道口径.md §六）：
 *   ① `sql_expr`：staging 全列 TEXT，裸 `SUM("金额")` 恒为 0、中文日期比较恒为假，
 *      必须由类型给出"可聚合/可比较"的表达式，SQL 生成侧只允许用它；
 *   ② `pk_column`：非空 100% + 唯一 100% 的候选主键，供"按行回查"用（`_rownum` 会随重建漂移，不能当键）。
 * 推断结果回写 `staging_registry.schema_json`——目录的唯一真相在库里，不落第二份索引。
 */
@Component
public class SchemaInferStep implements Step {

    private static final Pattern DATE_RX = Pattern.compile("^\\d{4}[-/年]\\d{1,2}([-/月]\\d{1,2})?日?$");
    /**
     * 数值：必须同时容忍千分位与小数（"12,350.50" 是 Excel 里最常见的金额形态）。
     * 旧的 `^-?\d+([.,]\d+)?%?$` 只看一个分隔符，会把 1.2 万这种带千分位的列判成 enum，
     * 进而让 SQL 通道拿不到可聚合表达式——类型判错的代价是"数字算不出来"，不是"少个标签"。
     */
    private static final Pattern NUMBER_RX = Pattern.compile(
            "^-?(?:\\d{1,3}(?:,\\d{3})+|\\d+)(?:\\.\\d+)?%?$");
    /** 主键探测最多试几列：全表 COUNT(DISTINCT) 是扫描，列多了会拖慢入库。 */
    private static final int PK_CANDIDATES = 3;

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
                List<String> physical = physicalOf(ctx.conn, table, item);
                List<String> display = displayOf(item, physical);
                List<Map<String, Object>> colInfo = new ArrayList<>();
                for (int i = 0; i < physical.size(); i++) {
                    String p = physical.get(i);
                    List<String> vals = new ArrayList<>();
                    try (Statement st = ctx.conn.createStatement(); ResultSet rs = st.executeQuery(
                            "SELECT " + SqlExpr.quote(p) + " FROM \"" + table
                                    + "\" WHERE TRIM(COALESCE(" + SqlExpr.quote(p)
                                    + ",''))<>'' LIMIT 200")) {
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
                    info.put("column", display.get(i));       // 原始列名：语义真相、展示用
                    info.put("physical", p);                  // 物理列名：DDL / SQL 用
                    info.put("type", ctype);
                    info.put("nonnull_rate", nonnullRate);
                    info.put("samples", vals.subList(0, Math.min(sampleN, vals.size())));
                    info.put("sql_expr", SqlExpr.of(p, ctype));
                    colInfo.add(info);
                }
                String pk = detectPk(ctx.conn, table, colInfo);
                Map<String, Object> schema = new LinkedHashMap<>();
                schema.put("table", table);
                schema.put("sheet", item.get("sheet"));
                schema.put("rows", rows);
                schema.put("columns", colInfo);
                schema.put("pk_column", pk);
                schemas.add(schema);
                persist(ctx, table, colInfo, pk);
            }
        } catch (Exception e) {
            return StepResult.fail("schema 推断失败：" + e.getMessage());
        }
        // 上面的循环里做过 SELECT 又做过 UPDATE：写之前必须收尾读事务，否则撞 SQLITE_BUSY_SNAPSHOT
        Db.endRead(ctx.conn);
        ctx.data.put("schemas", schemas);
        int columns = 0;
        for (Map<String, Object> s : schemas) {
            columns += ((List<?>) s.get("columns")).size();
        }
        return StepResult.okMetrics("tables", schemas.size(), "columns", columns);
    }

    /**
     * 把推断结果写回登记行的 schema_json（保留 excel_stage 写入的表头/合并统计）。
     * 只在内存里放一份是不够的：查询期路由读的是库里的元数据，不是某次任务的检查点。
     */
    @SuppressWarnings("unchecked")
    private static void persist(StepContext ctx, String table, List<Map<String, Object>> colInfo,
                                String pk) throws Exception {
        Map<String, Object> schema = new LinkedHashMap<>();
        try (PreparedStatement ps = ctx.conn.prepareStatement(
                "SELECT schema_json FROM staging_registry WHERE doc_id=? AND table_name=?")) {
            ps.setString(1, ctx.docId);
            ps.setString(2, table);
            try (ResultSet rs = ps.executeQuery()) {
                if (rs.next() && rs.getString(1) != null) {
                    schema = Json.readMap(rs.getString(1));
                }
            }
        }
        schema.put("columns_detail", colInfo);
        schema.put("pk_column", pk);
        // 读后要写：先把读快照收尾，否则同连接升级写锁时撞 SQLITE_BUSY_SNAPSHOT（不走 busy handler）
        Db.endRead(ctx.conn);
        try (PreparedStatement ps = ctx.conn.prepareStatement(
                "UPDATE staging_registry SET schema_json=? WHERE doc_id=? AND table_name=?")) {
            ps.setString(1, Json.write(schema));
            ps.setString(2, ctx.docId);
            ps.setString(3, table);
            ps.executeUpdate();
        }
        ctx.conn.commit();
    }

    /** 物理列名：优先用 excel_stage 登记的（已去重），缺登记（老库）则回退 PRAGMA。 */
    private static List<String> physicalOf(Connection conn, String table, Map<String, Object> item)
            throws Exception {
        Object p = item.get("physical");
        if (p instanceof List && !((List<?>) p).isEmpty()) {
            List<String> out = new ArrayList<>();
            for (Object o : (List<?>) p) {
                out.add(String.valueOf(o));
            }
            return out;
        }
        return nonMetaColumns(conn, table);
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

    /**
     * 主键候选：非空率 100% 且 COUNT(DISTINCT)=COUNT(*) 的列。
     * 不做"必须叫 id"这类命名猜测——命名不可靠，数据分布才可靠。
     */
    private static String detectPk(Connection conn, String table, List<Map<String, Object>> colInfo)
            throws Exception {
        int tried = 0;
        for (Map<String, Object> info : colInfo) {
            Object rate = info.get("nonnull_rate");
            if (!(rate instanceof Number) || ((Number) rate).doubleValue() < 0.99) {
                continue;
            }
            String type = String.valueOf(info.get("type"));
            if (!"number".equals(type) && !"text".equals(type) && !"date".equals(type)) {
                continue;
            }
            if (tried++ >= PK_CANDIDATES) {
                break;
            }
            String p = String.valueOf(info.get("physical"));
            String q = SqlExpr.quote(p);
            try (Statement st = conn.createStatement();
                 ResultSet rs = st.executeQuery("SELECT COUNT(*) AS n, COUNT(DISTINCT " + q
                         + ") AS d FROM \"" + table + "\" WHERE TRIM(COALESCE(" + q + ",''))<>''")) {
                if (rs.next()) {
                    long n = rs.getLong("n");
                    long d = rs.getLong("d");
                    if (n > 0 && n == d) {
                        return p;
                    }
                }
            }
        }
        return null;
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
