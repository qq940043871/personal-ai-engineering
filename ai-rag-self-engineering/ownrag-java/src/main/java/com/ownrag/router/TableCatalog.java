package com.ownrag.router;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.ownrag.util.Json;

/**
 * Excel 表目录（docs 10-Excel通道口径.md §九 的"A 方案"：不落第二份索引，查询期现算）。
 *
 * 唯一真相是 `staging_registry.schema_json`（由 excel_stage 写表头/合并统计、schema_infer 补
 * 列类型与 sql_expr）。这里只读不写，且**顺手校验物理表还在**——登记行可能比表活得久
 * （历史 bug 或手工 SQL 留下的孤儿），拿着一张不存在的表去生成 SQL，报错会误导成"SQL 写错了"。
 */
public final class TableCatalog {

    private TableCatalog() {
    }

    /** 一张可查询的表：doc/sheet 是给人看的，table/physical 是给 SQL 用的。 */
    public static class TableInfo {
        public String docId;
        public String docName;
        public String kb;
        public String table;
        public String sheet;
        public String pk;                                  // 主键候选（physical），可空
        public long rows;
        public List<Map<String, Object>> columns = new ArrayList<>();   // column/physical/type/samples/sql_expr
        public Map<String, Object> schema = new LinkedHashMap<>();

        /** 展示名：`文件 / sheet`，引用与 trace 用这个，不用 staging_xxx 这种物理名。 */
        public String label() {
            String f = docName == null || docName.isEmpty() ? docId : docName;
            return f + " / " + (sheet == null || sheet.isEmpty() ? table : sheet);
        }
    }

    /** 该 app 可见（documents.enabled=1）的全部 Excel 表；kbs 为空 = 不限库（管理/调试口径，含受限表）。 */
    public static List<TableInfo> list(Connection conn, List<String> kbs) throws SQLException {
        return list(conn, kbs, true);
    }

    /**
     * 带权限口径的表目录：`includeProtected=false` 时只返回公开文档的表。
     *
     * SQL 通道出的是**整表明细数字**（SUM/COUNT 直接算），比 RAG 的片段泄露更彻底，
     * 所以问答链路必须传登录态；管理/调试页继续用上面的重载看全量。
     */
    public static List<TableInfo> list(Connection conn, List<String> kbs, boolean includeProtected)
            throws SQLException {
        List<TableInfo> out = new ArrayList<>();
        Set<String> live = liveTables(conn);
        StringBuilder sql = new StringBuilder(
                "SELECT r.doc_id, r.table_name, r.sheet, r.schema_json, d.kb, d.source_file "
                        + "FROM staging_registry r LEFT JOIN documents d ON d.doc_id = r.doc_id "
                        + "WHERE COALESCE(d.enabled,1)=1");
        if (!includeProtected) {
            sql.append(" AND COALESCE(d.access_level,'public')='public'");
        }
        if (kbs != null && !kbs.isEmpty()) {
            sql.append(" AND d.kb IN (");
            for (int i = 0; i < kbs.size(); i++) {
                sql.append(i == 0 ? "?" : ",?");
            }
            sql.append(")");
        }
        sql.append(" ORDER BY r.created_at DESC");
        try (PreparedStatement ps = conn.prepareStatement(sql.toString())) {
            int i = 1;
            if (kbs != null) {
                for (String kb : kbs) {
                    ps.setString(i++, kb);
                }
            }
            try (ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    String table = rs.getString("table_name");
                    if (table == null || !live.contains(table)) {
                        continue;   // 孤儿登记行：表已经没了
                    }
                    TableInfo t = new TableInfo();
                    t.docId = rs.getString("doc_id");
                    t.docName = rs.getString("source_file");
                    t.kb = rs.getString("kb");
                    t.table = table;
                    t.sheet = rs.getString("sheet");
                    String json = rs.getString("schema_json");
                    if (json != null && !json.isEmpty()) {
                        try {
                            t.schema = Json.readMap(json);
                        } catch (Exception ignored) {
                            t.schema = new LinkedHashMap<>();
                        }
                    }
                    t.columns = columnsOf(t.schema);
                    t.pk = t.schema.get("pk_column") == null ? null : String.valueOf(t.schema.get("pk_column"));
                    Object rows = t.schema.get("rows");
                    t.rows = rows instanceof Number ? ((Number) rows).longValue() : 0L;
                    out.add(t);
                }
            }
        }
        return out;
    }

    public static int count(Connection conn, List<String> kbs) throws SQLException {
        return list(conn, kbs).size();
    }

    /**
     * 选表：sheet 名 / 表名 / 原始列名出现在问题里就加分（同一族只算一次，避免长表名刷分）。
     * 没有任何表名命中时：只有一张表就那它（用户就是问这张表的事），多张表则返回空 = 无法定位。
     */
    public static List<TableInfo> pick(List<TableInfo> tables, String question, int limit) {
        List<TableInfo> scored = new ArrayList<>();
        Map<TableInfo, Integer> scores = new LinkedHashMap<>();
        String q = question == null ? "" : question;
        for (TableInfo t : tables) {
            int score = 0;
            if (contains(q, t.sheet) || contains(q, stripPrefix(t.table))) {
                score += 2;
            }
            Set<String> hits = new LinkedHashSet<>();
            for (Map<String, Object> c : t.columns) {
                String name = String.valueOf(c.get("column"));
                if (name.length() >= 2 && q.contains(name)) {
                    hits.add(name);
                }
            }
            score += Math.min(2, hits.size());   // 列命中最多加 2：再多也只是同一张表
            if (score > 0) {
                scored.add(t);
                scores.put(t, score);
            }
        }
        if (scored.isEmpty()) {
            if (tables.size() == 1) {
                scored.add(tables.get(0));
            } else {
                return new ArrayList<>();
            }
        }
        scored.sort((a, b) -> Integer.compare(scores.getOrDefault(b, 0), scores.getOrDefault(a, 0)));
        return scored.size() > limit ? new ArrayList<>(scored.subList(0, limit)) : scored;
    }

    /** 问题里点名了哪些列（schema linking 的规则部分；列白名单以外的不许进 SQL）。 */
    public static List<String> columnHits(TableInfo t, String question) {
        List<String> out = new ArrayList<>();
        String q = question == null ? "" : question;
        for (Map<String, Object> c : t.columns) {
            String name = String.valueOf(c.get("column"));
            if (name.length() >= 2 && q.contains(name)) {
                out.add(name);
            }
        }
        return out;
    }

    /** 问题里出现的枚举取值（如"华东"），作为值提示喂给 SQL 生成，别让模型猜枚举。 */
    public static List<String> valueHits(TableInfo t, String question) {
        List<String> out = new ArrayList<>();
        String q = question == null ? "" : question;
        for (Map<String, Object> c : t.columns) {
            if (!"enum".equals(String.valueOf(c.get("type")))) {
                continue;
            }
            Object samples = c.get("samples");
            if (!(samples instanceof List)) {
                continue;
            }
            for (Object v : (List<?>) samples) {
                String s = v == null ? "" : String.valueOf(v).trim();
                if (s.length() >= 2 && q.contains(s) && !out.contains(s)) {
                    out.add(String.valueOf(c.get("column")) + "=" + s);
                }
            }
        }
        return out;
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> columnsOf(Map<String, Object> schema) {
        Object cols = schema.get("columns_detail");
        List<Map<String, Object>> out = new ArrayList<>();
        if (cols instanceof List) {
            for (Object o : (List<?>) cols) {
                if (o instanceof Map) {
                    out.add((Map<String, Object>) o);
                }
            }
            return out;
        }
        // 老库（schema_infer 未回写 columns_detail）：退回 excel_stage 写的原始列名，类型未知
        Object raw = schema.get("columns");
        Object physical = schema.get("physical");
        if (raw instanceof List) {
            List<?> names = (List<?>) raw;
            List<?> phys = physical instanceof List ? (List<?>) physical : names;
            for (int i = 0; i < names.size(); i++) {
                Map<String, Object> c = new LinkedHashMap<>();
                c.put("column", names.get(i));
                c.put("physical", i < phys.size() ? phys.get(i) : names.get(i));
                c.put("type", "text");
                c.put("sql_expr", "TRIM(\"" + (i < phys.size() ? phys.get(i) : names.get(i)) + "\")");
                out.add(c);
            }
        }
        return out;
    }

    private static Set<String> liveTables(Connection conn) {
        Set<String> out = new LinkedHashSet<>();
        try (Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT name FROM sqlite_master WHERE type='table'")) {
            while (rs.next()) {
                out.add(rs.getString(1));
            }
        } catch (SQLException ignored) {
            // 拿不到表清单时按"没有表"处理：宁可 route 判不可用，也不要拿假表去生成 SQL
        }
        return out;
    }

    private static boolean contains(String q, String name) {
        return name != null && name.length() >= 2 && q.contains(name);
    }

    private static String stripPrefix(String table) {
        int i = table == null ? -1 : table.lastIndexOf('_');
        return i < 0 ? table : table.substring(i + 1);
    }
}
