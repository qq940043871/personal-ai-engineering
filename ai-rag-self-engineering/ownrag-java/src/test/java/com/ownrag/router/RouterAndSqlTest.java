package com.ownrag.router;

import java.nio.file.Path;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import com.ownrag.config.AppDef;
import com.ownrag.core.Db;
import com.ownrag.util.Json;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 查询期路由与 SQL 通道回归（docs 11-查询路由与多源编排.md §十二）：
 * 规则定案 / 可用性掩码 / 跨源 MULTI / 低置信兜底 / 强制通道 / SQL 白名单与只读执行。
 */
class RouterAndSqlTest {

    @TempDir
    Path tmp;

    // ---------------------------------------------------------------- 路由（纯函数）

    @Test
    void 聚合问题且库里有表_判SQL() {
        RouteResult r = QueryRouter.decide(5, 1, 0, true, true, false, app());
        assertEquals(RouteResult.SQL, r.route);
        assertEquals("rule", r.layer);
        assertTrue(r.confidence >= 0.4);
    }

    @Test
    void 无可查表时不回落RAG造假_标记结构层() {
        // sql 分最高，但库里没有 Excel 表 → 掩码后只能走 RAG，且 layer 必须写明是"缺数据"
        RouteResult r = QueryRouter.decide(5, 1, 0, false, true, false, app());
        assertEquals(RouteResult.RAG, r.route);
        assertEquals("structure", r.layer, "由可用性掩码改变的结论必须可辨认，不能混成 rule");
        assertEquals(false, r.availability.get("sql"));
    }

    @Test
    void 跨源问题判MULTI() {
        // 既要算（表/列指称 + 聚合词）又要读规定（知识型词）
        RouteResult r = QueryRouter.decide(5, 3, 0, true, true, false, app());
        assertEquals(RouteResult.MULTI, r.route);
    }

    @Test
    void 知识型问题判RAG() {
        RouteResult r = QueryRouter.decide(0, 3, 0, true, true, false, app());
        assertEquals(RouteResult.RAG, r.route);
    }

    @Test
    void 量路都不可用且低置信_按兜底落点() {
        RouteResult r = QueryRouter.decide(0, 1, 0, false, false, false, app());
        assertEquals(RouteResult.RAG, r.route);
        assertEquals("fallback", r.layer);
        assertEquals(0.0, r.confidence);
    }

    @Test
    void 置信度低于阈值时兜底到配置落点() {
        // sql 与 rag 同为 1 分 → 置信 0.2 < 0.4 → 按 on_low_confidence 抓回 RAG
        AppDef a = app();
        a.routingLowConfidence = "rag";
        RouteResult r = QueryRouter.decide(1, 1, 0, true, true, false, a);
        assertEquals(RouteResult.RAG, r.route);
        assertEquals("fallback", r.layer);
    }

    @Test
    void 联网得分再高也不选中_本期不可用() {
        // 掩码语义：web 不可用时它的分数被抹掉，argmax 只能在 sql/rag 之间选
        RouteResult r = QueryRouter.decide(0, 3, 9, true, true, false, app());
        assertEquals(RouteResult.RAG, r.route);
        assertEquals(false, r.availability.get("web"));
    }

    // ---------------------------------------------------------------- 路由（接库）

    @Test
    void 库里有staging表时_问题点名列即判SQL并给出目标() throws Exception {
        Path db = tmp.resolve("router.db");
        Db.initSchema(db);
        try (Connection conn = Db.connect(db)) {
            seedExcel(conn);
            QueryRouter router = new QueryRouter();
            RouteResult r = router.route(conn, app(), Collections.singletonList("kb1"),
                    "报销金额一共多少", "auto");
            assertEquals(RouteResult.SQL, r.route);
            assertEquals(1, r.targets.size());
            assertEquals("staging_doc1234_Sheet1", r.targets.get(0).get("table"));
            assertEquals(false, r.availability.get("web"), "联网本期恒不可用，必须如实播报");
        }
    }

    @Test
    void 库里没有任何Excel表时_聚合问题落到RAG并说明原因() throws Exception {
        Path db = tmp.resolve("router-empty.db");
        Db.initSchema(db);
        try (Connection conn = Db.connect(db)) {
            RouteResult r = new QueryRouter().route(conn, app(), Collections.singletonList("kb1"),
                    "报销金额一共多少", "auto");
            assertEquals(RouteResult.RAG, r.route);
            assertTrue(r.targets.isEmpty());
        }
    }

    @Test
    void 强制SQL但没有表时回落并在原因里说明() throws Exception {
        Path db = tmp.resolve("router-forced.db");
        Db.initSchema(db);
        try (Connection conn = Db.connect(db)) {
            RouteResult r = new QueryRouter().route(conn, app(), Collections.singletonList("kb1"),
                    "随便问点什么", "sql");
            assertEquals("fallback", r.layer);
            assertEquals(RouteResult.RAG, r.route);
            assertTrue(r.reason.contains("不可用"), r.reason);
        }
    }

    @Test
    void 表目录回显含类型与聚合表达式_孤儿登记行被剔除() throws Exception {
        Path db = tmp.resolve("catalog.db");
        Db.initSchema(db);
        try (Connection conn = Db.connect(db)) {
            seedExcel(conn);
            List<TableCatalog.TableInfo> tables = TableCatalog.list(conn, Collections.singletonList("kb1"));
            assertEquals(1, tables.size());
            TableCatalog.TableInfo t = tables.get(0);
            assertEquals("Sheet1", t.sheet);
            assertEquals("报销明细.xlsx", t.docName);
            assertEquals(2, t.columns.size());
            assertTrue(String.valueOf(t.columns.get(1).get("sql_expr")).contains("AS REAL"));
            // 选表：问题点名了列 → 命中该表（路由回归台靠这条解释"为什么选它"）
            assertEquals(1, TableCatalog.pick(tables, "部门的报销金额合计", 3).size());

            // 登记行比物理表活得久（历史 bug / 手工 SQL）：目录必须能剔掉，否则会拿假表生成 SQL
            try (Statement st = conn.createStatement()) {
                st.executeUpdate("DROP TABLE \"staging_doc1234_Sheet1\"");
            }
            conn.commit();
            assertEquals(0, TableCatalog.list(conn, Collections.singletonList("kb1")).size());
        }
    }

    // ---------------------------------------------------------------- SQL 校验

    private static final Set<String> ALLOWED = new LinkedHashSet<>(Arrays.asList("staging_x_Sheet1"));

    @Test
    void 合法SELECT被补上LIMIT() {
        String sql = SqlPlanner.validate("SELECT SUM(CAST(\"金额\" AS REAL)) AS s FROM \"staging_x_Sheet1\"",
                ALLOWED, 200);
        assertTrue(sql.endsWith("LIMIT 200"), sql);
    }

    @Test
    void 超大LIMIT被钳到上限() {
        String sql = SqlPlanner.validate("SELECT a FROM \"staging_x_Sheet1\" LIMIT 99999", ALLOWED, 50);
        assertTrue(sql.endsWith("LIMIT 50"), sql);
    }

    @Test
    void 非SELECT一律拒绝() {
        assertThrows(IllegalArgumentException.class,
                () -> SqlPlanner.validate("DELETE FROM \"staging_x_Sheet1\"", ALLOWED, 200));
        assertThrows(IllegalArgumentException.class,
                () -> SqlPlanner.validate("UPDATE \"staging_x_Sheet1\" SET a=1", ALLOWED, 200));
    }

    @Test
    void 多语句与注释一律拒绝() {
        assertThrows(IllegalArgumentException.class,
                () -> SqlPlanner.validate("SELECT a FROM \"staging_x_Sheet1\"; DROP TABLE x", ALLOWED, 200));
        assertThrows(IllegalArgumentException.class,
                () -> SqlPlanner.validate("SELECT a FROM \"staging_x_Sheet1\" -- 注释", ALLOWED, 200));
        assertThrows(IllegalArgumentException.class,
                () -> SqlPlanner.validate("SELECT a FROM \"staging_x_Sheet1\" /* x */", ALLOWED, 200));
    }

    @Test
    void 表名必须在白名单内() {
        assertThrows(IllegalArgumentException.class,
                () -> SqlPlanner.validate("SELECT * FROM \"chunks\"", ALLOWED, 200));
        assertThrows(IllegalArgumentException.class,
                () -> SqlPlanner.validate("SELECT name FROM sqlite_master", ALLOWED, 200));
    }

    @Test
    void 模型输出带代码围栏也能取到SQL() {
        String raw = "```sql\nSELECT 1 FROM \"staging_x_Sheet1\"\n```";
        assertEquals("SELECT 1 FROM \"staging_x_Sheet1\"", SqlPlanner.extractSql(raw));
    }

    @Test
    void JSON输出取sql字段() {
        String raw = "{\"sql\":\"SELECT a FROM \\\"staging_x_Sheet1\\\"\",\"reason\":\"按部门汇总\"}";
        assertEquals("SELECT a FROM \"staging_x_Sheet1\"", SqlPlanner.extractSql(raw));
    }

    // ---------------------------------------------------------------- 执行器

    @Test
    void 执行器返回结果并渲染成带SQL口径的证据文本() throws Exception {
        Path db = tmp.resolve("exec.db");
        seedSimple(db);
        SqlExecutor.Result r = SqlExecutor.execute(db,
                "SELECT 部门, SUM(CAST(报销金额 AS REAL)) AS 总额 FROM \"staging_t\" GROUP BY 部门 ORDER BY 部门 LIMIT 10",
                200, 3000, "报销明细.xlsx / Sheet1");
        assertTrue(r.ok, r.error);
        assertEquals(2, r.rows.size());
        assertEquals(Arrays.asList("部门", "总额"), r.headers);
        assertTrue(r.text.contains("SQL: "), "证据块必须带 SQL 全文，否则数字没有出处");
        assertTrue(r.text.contains("报销明细.xlsx / Sheet1"));
    }

    @Test
    void 执行器是只读的_写语句不会落库() throws Exception {
        Path db = tmp.resolve("ro.db");
        seedSimple(db);
        SqlExecutor.Result r = SqlExecutor.execute(db, "DELETE FROM \"staging_t\"", 200, 3000, "x");
        assertFalse(r.ok, "只读连接必须拒绝写语句");
        try (Connection conn = Db.connect(db);
             Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT COUNT(*) FROM \"staging_t\"")) {
            assertTrue(rs.next());
            assertEquals(2, rs.getInt(1), "数据不能被删掉");
        }
    }

    // ---------------------------------------------------------------- 夹具

    private static AppDef app() {
        AppDef a = new AppDef();
        a.name = "t";
        a.routingEnabled = true;
        a.routingAllow = new ArrayList<>(Arrays.asList("rag", "sql"));
        a.routingDefault = "rag";
        a.routingLowConfidence = "rag";
        a.routingMinConfidence = 0.4;
        a.sqlMaxRows = 200;
        a.sqlTimeoutMs = 3000;
        a.sqlMaxTables = 3;
        return a;
    }

    /** 一张 staging 表 + documents 行 + 登记行（含 schema_infer 回写后的 columns_detail）。 */
    private static void seedExcel(Connection conn) throws Exception {
        try (Statement st = conn.createStatement()) {
            st.executeUpdate("CREATE TABLE \"staging_doc1234_Sheet1\" ("
                    + "\"部门\" TEXT, \"报销金额\" TEXT, \"_src_file\" TEXT, \"_sheet\" TEXT, \"_rownum\" INTEGER)");
            st.executeUpdate("INSERT INTO \"staging_doc1234_Sheet1\" VALUES ('研发部','100','报销明细.xlsx','Sheet1',1)");
            st.executeUpdate("INSERT INTO \"staging_doc1234_Sheet1\" VALUES ('市场部','200','报销明细.xlsx','Sheet1',2)");
        }
        try (PreparedStatement ps = conn.prepareStatement(
                "INSERT INTO documents(doc_id, kb, source_file) VALUES (?,?,?)")) {
            ps.setString(1, "doc1234abcd");
            ps.setString(2, "kb1");
            ps.setString(3, "报销明细.xlsx");
            ps.executeUpdate();
        }
        Map<String, Object> schema = new LinkedHashMap<>();
        schema.put("columns", Arrays.asList("部门", "报销金额"));
        schema.put("physical", Arrays.asList("部门", "报销金额"));
        List<Map<String, Object>> detail = new ArrayList<>();
        detail.add(col("部门", "enum", Arrays.asList("研发部", "市场部")));
        detail.add(col("报销金额", "number", Arrays.asList("100", "200")));
        schema.put("columns_detail", detail);
        schema.put("rows", 2);
        try (PreparedStatement ps = conn.prepareStatement(
                "INSERT INTO staging_registry(doc_id, table_name, sheet, schema_json) VALUES (?,?,?,?)")) {
            ps.setString(1, "doc1234abcd");
            ps.setString(2, "staging_doc1234_Sheet1");
            ps.setString(3, "Sheet1");
            ps.setString(4, Json.write(schema));
            ps.executeUpdate();
        }
        conn.commit();
    }

    private static Map<String, Object> col(String name, String type, List<String> samples) {
        Map<String, Object> c = new LinkedHashMap<>();
        c.put("column", name);
        c.put("physical", name);
        c.put("type", type);
        c.put("nonnull_rate", 1.0);
        c.put("samples", samples);
        c.put("sql_expr", "number".equals(type)
                ? "CAST(REPLACE(REPLACE(TRIM(\"" + name + "\"),',',''),'%','') AS REAL)"
                : "TRIM(\"" + name + "\")");
        return c;
    }

    private static void seedSimple(Path db) throws Exception {
        Db.initSchema(db);
        try (Connection conn = Db.connect(db); Statement st = conn.createStatement()) {
            st.executeUpdate("CREATE TABLE \"staging_t\" (\"部门\" TEXT, \"报销金额\" TEXT)");
            st.executeUpdate("INSERT INTO \"staging_t\" VALUES ('研发部','100')");
            st.executeUpdate("INSERT INTO \"staging_t\" VALUES ('市场部','200')");
            conn.commit();
        }
    }
}
