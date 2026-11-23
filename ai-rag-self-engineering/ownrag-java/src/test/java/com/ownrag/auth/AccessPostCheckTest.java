package com.ownrag.auth;

import java.nio.file.Path;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import com.ownrag.config.Settings;
import com.ownrag.core.Db;
import com.ownrag.retrieve.DirectHit;
import com.ownrag.retrieve.RetrieveTest;
import com.ownrag.router.TableCatalog;

import okhttp3.OkHttpClient;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 越权二次校验回归（生成前复核候选 / 生成后复核答案）+ 两条"绕开 RAG 过滤"的通道。
 *
 * 口径：
 *   ① 二次校验**不信任上游过滤**，自己回查 documents.access_level；查不到可读就剔除/拦截（fail-closed）；
 *   ② 剔除必须发生在**进模型之前**——流式 token 吐出去就收不回来；
 *   ③ SQL 通出整表数字、直击库直达答案，两者都不经过 chunks，必须各自按 documents/自带列过滤。
 */
class AccessPostCheckTest {

    @TempDir
    Path tmp;

    private Settings settings(String name) {
        return new RetrieveTest.SettingsBuilder().dataDir(tmp.resolve(name)).build();
    }

    private static Connection init(Settings s) throws Exception {
        Db.initSchema(s.getDbPath());
        return Db.connect(s.getDbPath());
    }

    private static void seedDoc(Connection conn, String docId, String kb, String file, String accessLevel)
            throws Exception {
        try (PreparedStatement ps = conn.prepareStatement(
                "INSERT INTO documents(doc_id, kb, source_file, access_level) VALUES (?,?,?,?)")) {
            ps.setString(1, docId);
            ps.setString(2, kb);
            ps.setString(3, file);
            ps.setString(4, accessLevel);
            ps.executeUpdate();
        }
        conn.commit();
    }

    private static Map<String, Object> cand(String docId, String docName, String text) {
        Map<String, Object> c = new LinkedHashMap<>();
        c.put("doc_id", docId);
        c.put("doc_name", docName);
        c.put("text", text);
        c.put("rrf", 0.5);
        return c;
    }

    // ---------------------------------------------------------------- 生成前

    @Test
    void 生成前复核_未登录剔除受限候选_登录后全留() throws Exception {
        Settings s = settings("pre");
        try (Connection conn = init(s)) {
            seedDoc(conn, "pub01", "kb1", "报销制度.md", AccessLevel.PUBLIC);
            seedDoc(conn, "sec01", "kb1", "薪酬带宽.xlsx", AccessLevel.PROTECTED);
            List<Map<String, Object>> anon = new ArrayList<>(Arrays.asList(
                    cand("pub01", "报销制度.md", "差旅按实报销"),
                    cand("sec01", "薪酬带宽.xlsx", "P7 月薪 35k")));

            AccessPostCheck.Result r = AccessPostCheck.filterCandidates(conn, anon, false);
            assertFalse(r.passed, "剔除受限块必须判为不通过（要留痕，不能静默）");
            assertEquals(1, r.droppedBlocks);
            assertEquals(Collections.singletonList("sec01"), r.droppedDocIds);
            assertEquals(1, anon.size(), "受限块必须从候选池里消失，之后的预算/上下文都看不到它");
            assertEquals("pub01", anon.get(0).get("doc_id"));

            // 已登录：同一批候选一条不剔
            List<Map<String, Object>> logged = new ArrayList<>(Arrays.asList(
                    cand("pub01", "报销制度.md", "差旅按实报销"),
                    cand("sec01", "薪酬带宽.xlsx", "P7 月薪 35k")));
            AccessPostCheck.Result ok = AccessPostCheck.filterCandidates(conn, logged, true);
            assertTrue(ok.passed);
            assertEquals(0, ok.droppedBlocks);
            assertEquals(2, logged.size());
        }
    }

    @Test
    void 生成前复核_文档表里没有这行时按公开处理() throws Exception {
        Settings s = settings("pre-legacy");
        try (Connection conn = init(s)) {
            // 存量库：chunks 有数据但 documents 没建行 → 不能被二次校验误杀
            List<Map<String, Object>> cs = new ArrayList<>(Collections.singletonList(
                    cand("legacy01", "老文档.md", "历史内容")));
            AccessPostCheck.Result r = AccessPostCheck.filterCandidates(conn, cs, false);
            assertTrue(r.passed);
            assertEquals(1, cs.size());
        }
    }

    // ---------------------------------------------------------------- 生成后

    @Test
    void 生成后复核_答案点名受限文档即判越权() throws Exception {
        Settings s = settings("post");
        try (Connection conn = init(s)) {
            seedDoc(conn, "pub01", "kb1", "报销制度.md", AccessLevel.PUBLIC);
            seedDoc(conn, "sec01", "kb1", "薪酬带宽.xlsx", AccessLevel.PROTECTED);
            List<Map<String, Object>> cs = new ArrayList<>(Collections.singletonList(
                    cand("pub01", "报销制度.md", "差旅按实报销")));

            AccessPostCheck.Result bad = AccessPostCheck.checkAnswer(conn,
                    "根据《薪酬带宽.xlsx》，P7 月薪为 35k。[来源：块1]", cs, Collections.singletonList("kb1"), false);
            assertFalse(bad.passed);
            assertEquals(1, bad.violations.size());
            assertTrue(bad.violations.get(0).contains("薪酬带宽.xlsx"), bad.violations.get(0));

            // 只提公开文档名 → 通过
            AccessPostCheck.Result good = AccessPostCheck.checkAnswer(conn,
                    "根据《报销制度.md》，差旅按实报销。[来源：块1]", cs, Collections.singletonList("kb1"), false);
            assertTrue(good.passed, good.violations.toString());

            // 登录后同名文档本来就在候选里/本就允许 → 不拦
            assertTrue(AccessPostCheck.checkAnswer(conn, "见《薪酬带宽.xlsx》",
                    cs, Collections.singletonList("kb1"), true).passed);
        }
    }

    @Test
    void 生成后复核_另一个库的受限文档不误伤() throws Exception {
        Settings s = settings("post-kb");
        try (Connection conn = init(s)) {
            seedDoc(conn, "sec02", "kb2", "别的库内部表.xlsx", AccessLevel.PROTECTED);
            List<Map<String, Object>> cs = new ArrayList<>(Collections.singletonList(
                    cand("pub01", "报销制度.md", "差旅按实报销")));
            // 只查 kb1 → kb2 的受限文件名不参与扫描
            assertTrue(AccessPostCheck.checkAnswer(conn, "见《别的库内部表.xlsx》", cs,
                    Collections.singletonList("kb1"), false).passed);

            // 不限库（kbs 为空）时才会命中
            AccessPostCheck.Result all = AccessPostCheck.checkAnswer(conn, "见《别的库内部表.xlsx》", cs,
                    new ArrayList<String>(), false);
            assertFalse(all.passed);
            assertTrue(all.violations.get(0).contains("别的库内部表.xlsx"));
        }
    }

    @Test
    void 撤回话术_给下一步且不复述受限内容() throws Exception {
        String msg = AccessPostCheck.retractedAnswer();
        assertTrue(msg.contains("无权访问"));
        assertTrue(msg.contains("/ui/login"), "撤回提示必须给出可照做的下一步：" + msg);
        assertEquals("薪酬带宽", AccessPostCheck.baseName("D:/x/薪酬带宽.xlsx"));
        assertEquals("报销制度", AccessPostCheck.baseName("报销制度.md"));
        assertNull(AccessPostCheck.baseName("  "));
    }

    // ---------------------------------------------------------------- 通道：SQL 表目录

    @Test
    void SQL表目录_未登录看不到受限Excel表_登录可见() throws Exception {
        Settings s = settings("sql-acl");
        try (Connection conn = init(s)) {
            seedStagedTable(conn, "docpub00001", "kb1", "公开明细.xlsx", "staging_docpub00001_Sheet1",
                    AccessLevel.PUBLIC);
            seedStagedTable(conn, "docsec00002", "kb1", "薪酬发放.xlsx", "staging_docsec00002_Sheet1",
                    AccessLevel.PROTECTED);

            // 未登录：受限表不在目录里 → 生成 SQL 的表白名单里根本没有它
            List<TableCatalog.TableInfo> anon = TableCatalog.list(conn, Collections.singletonList("kb1"), false);
            assertEquals(1, anon.size());
            assertEquals("staging_docpub00001_Sheet1", anon.get(0).table);

            // 已登录（含管理/调试默认口径）：两张都在
            assertEquals(2, TableCatalog.list(conn, Collections.singletonList("kb1"), true).size());
            assertEquals(2, TableCatalog.list(conn, Collections.singletonList("kb1")).size());
        }
    }

    // ---------------------------------------------------------------- 通道：直击库

    @Test
    void 直击库_受限条目匿名不命中_登录才命中() throws Exception {
        Settings s = settings("dh-acl");
        try (Connection conn = init(s)) {
            insertHit(conn, "h-public", "kb1", "报销流程是什么", "先审批后报销", AccessLevel.PUBLIC);
            insertHit(conn, "h-secret", "kb1", "薪酬带宽怎么定", "P7 月薪 35k", AccessLevel.PROTECTED);
            DirectHit dh = new DirectHit(new com.ownrag.index.Embedder(new OkHttpClient()), s);

            DirectHit.Hit anon = dh.match(conn, Collections.singletonList("kb1"), "薪酬带宽怎么定", 0.86, false);
            assertNull(anon, "未登录不能命中受限直击条目（它绕开检索直达用户）");

            DirectHit.Hit logged = dh.match(conn, Collections.singletonList("kb1"), "薪酬带宽怎么定", 0.86, true);
            assertNotNull(logged);
            assertEquals("h-secret", logged.hitId);

            // 公开条目两种身份都命中
            assertNotNull(dh.match(conn, Collections.singletonList("kb1"), "报销流程是什么", 0.86, false));
        }
    }

    // ---------------------------------------------------------------- 造数

    private static void seedStagedTable(Connection conn, String docId, String kb, String file,
                                        String table, String accessLevel) throws Exception {
        try (Statement st = conn.createStatement()) {
            st.executeUpdate("CREATE TABLE \"" + table + "\" (\"部门\" TEXT, \"金额\" TEXT)");
            st.executeUpdate("INSERT INTO \"" + table + "\" VALUES ('研发部','100')");
        }
        seedDoc(conn, docId, kb, file, accessLevel);
        Map<String, Object> schema = new LinkedHashMap<>();
        schema.put("columns", Arrays.asList("部门", "金额"));
        schema.put("physical", Arrays.asList("部门", "金额"));
        List<Map<String, Object>> detail = new ArrayList<>();
        detail.add(col("部门", "enum"));
        detail.add(col("金额", "number"));
        schema.put("columns_detail", detail);
        schema.put("rows", 1);
        try (PreparedStatement ps = conn.prepareStatement(
                "INSERT INTO staging_registry(doc_id, table_name, sheet, schema_json) VALUES (?,?,?,?)")) {
            ps.setString(1, docId);
            ps.setString(2, table);
            ps.setString(3, "Sheet1");
            ps.setString(4, com.ownrag.util.Json.write(schema));
            ps.executeUpdate();
        }
        conn.commit();
    }

    private static void insertHit(Connection conn, String id, String kb, String question, String answer,
                                  String accessLevel) throws Exception {
        try (PreparedStatement ps = conn.prepareStatement(
                "INSERT INTO direct_hits(id,kb,level,question,aliases_json,answer,enabled,access_level) "
                        + "VALUES (?,?,'L0',?,'[]',?,1,?)")) {
            ps.setString(1, id);
            ps.setString(2, kb);
            ps.setString(3, question);
            ps.setString(4, answer);
            ps.setString(5, accessLevel);
            ps.executeUpdate();
        }
        conn.commit();
    }

    private static Map<String, Object> col(String name, String type) {
        Map<String, Object> c = new LinkedHashMap<>();
        c.put("column", name);
        c.put("physical", name);
        c.put("type", type);
        c.put("nonnull_rate", 1.0);
        c.put("samples", Collections.singletonList(name));
        c.put("sql_expr", "number".equals(type)
                ? "CAST(REPLACE(REPLACE(TRIM(\"" + name + "\"),',',''),'%','') AS REAL)"
                : "TRIM(\"" + name + "\")");
        return c;
    }
}
