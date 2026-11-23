package com.ownrag.auth;

import java.nio.file.Path;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import com.ownrag.config.Settings;
import com.ownrag.core.Db;
import com.ownrag.core.DocumentStore;
import com.ownrag.index.ChunkStore;
import com.ownrag.retrieve.RetrieveTest;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 登录 + 文档权限回归：口令派生、会话生命周期、双通道按登录态过滤、权限字段读写。
 *
 * 口径（改代码前先看这三条）：
 *   ① 库里不存明文口令，校验失败与用户不存在返回同一句话（不泄露账号是否存在）；
 *   ② 未登录只在公开文档里召回——过滤发生在 SQL 层（先过滤后召回），不是召回后再筛；
 *   ③ access_level 改在 documents 一行上，检索/原件/分块同时生效（没有第二份副本要同步）。
 */
class AuthAclTest {

    @TempDir
    Path tmp;

    private Settings settings(String name) {
        return new RetrieveTest.SettingsBuilder().dataDir(tmp.resolve(name)).build();
    }

    private static Connection init(Settings s) throws Exception {
        Db.initSchema(s.getDbPath());
        return Db.connect(s.getDbPath());
    }

    private static Map<String, Object> chunk(String docId, String text) {
        Map<String, Object> c = new LinkedHashMap<>();
        c.put("chunk_id", docId + "#0001");
        c.put("doc_id", docId);
        c.put("kb", "kb_acl");
        c.put("source_type", "md");
        c.put("ordinal", 1);
        c.put("text", text);
        c.put("meta", new LinkedHashMap<String, Object>());
        return c;
    }

    /** 按生产口径建档 + 写块（documents 决定权限，chunks 只存正文）。 */
    private static void seedDoc(Connection conn, String docId, String text, String accessLevel)
            throws Exception {
        Map<String, Object> meta = new LinkedHashMap<>();
        meta.put("access_level", accessLevel);
        DocumentStore.upsertOnUpload(conn, docId, "kb_acl", docId + ".md", "md_v1", "t-" + docId,
                "tr-" + docId, null, 0, meta);
        List<Map<String, Object>> chunks = new ArrayList<>();
        chunks.add(chunk(docId, text));
        ChunkStore.keywordUpsert(conn, chunks);
        try (PreparedStatement ps = conn.prepareStatement(
                "INSERT OR REPLACE INTO chunks(chunk_id, doc_id, kb, text, meta_json) VALUES (?,?,?,?,?)")) {
            ps.setString(1, docId + "#0001");
            ps.setString(2, docId);
            ps.setString(3, "kb_acl");
            ps.setString(4, text);
            ps.setString(5, "{}");
            ps.executeUpdate();
        }
        conn.commit();
    }

    // ---------------------------------------------------------------- 口令

    @Test
    void 口令派生_同口令不同盐_校验正确() {
        String salt1 = PasswordHasher.newSalt();
        String salt2 = PasswordHasher.newSalt();
        assertFalse(salt1.equals(salt2), "每次建号必须换新盐");
        String h1 = PasswordHasher.hash("ownrag-123", salt1);
        String h2 = PasswordHasher.hash("ownrag-123", salt2);
        assertFalse(h1.equals(h2), "同口令在不同盐下派生值必须不同");
        assertTrue(PasswordHasher.verify("ownrag-123", salt1, h1));
        assertFalse(PasswordHasher.verify("ownrag-124", salt1, h1));
        // 缺盐/缺派生值一律 false：不能让缺列的老行变成"任意口令可登"
        assertFalse(PasswordHasher.verify("ownrag-123", null, h1));
        assertFalse(PasswordHasher.verify("ownrag-123", salt1, ""));
    }

    // ---------------------------------------------------------------- 会话

    @Test
    void 登录登出_会话跨请求保持一致() throws Exception {
        Settings s = settings("sess");
        init(s).close();
        AuthService auth = new AuthService(s);
        auth.upsertUser("alice", "pw-123456", "Alice", "admin");

        AuthService.Outcome ok = auth.login("ALICE ", "pw-123456");   // 用户名大小写/空白归一
        assertTrue(ok.ok, ok.message);
        assertNotNull(ok.token);
        AuthUser me = auth.resolveToken(ok.token);
        assertNotNull(me, "同一 token 在后续请求里必须能还原出用户（页面跳转不丢登录态）");
        assertEquals("alice", me.username);

        auth.logout(ok.token);
        assertNull(auth.resolveToken(ok.token), "登出后服务端会话行必须立刻失效");
    }

    @Test
    void 口令错误_不泄露账号是否存在() throws Exception {
        Settings s = settings("bad");
        init(s).close();
        AuthService auth = new AuthService(s);
        auth.upsertUser("bob", "pw-123456", "Bob", "user");

        assertEquals(auth.login("bob", "wrong-pw").message, auth.login("nobody", "wrong-pw").message,
                "两种失败必须是同一句话");
        assertFalse(auth.login("bob", "wrong-pw").ok);
        assertFalse(auth.login("", "").ok);
    }

    @Test
    void 默认管理员_只在空库创建一次() throws Exception {
        Settings s = settings("boot");
        init(s).close();
        AuthService.ensureDefaultAdmin(s);
        AuthService.ensureDefaultAdmin(s);   // 幂等：第二次不重建、不改密
        try (Connection conn = Db.connect(s.getDbPath())) {
            assertEquals(1, UserStore.count(conn));
        }
        AuthService auth = new AuthService(s);
        assertTrue(auth.login(AuthService.DEFAULT_ADMIN, AuthService.DEFAULT_PASSWORD).ok,
                "默认账号应可登录（口令来自 OWNRAG_ADMIN_PASSWORD，缺省 " + AuthService.DEFAULT_PASSWORD + "）");
    }

    // ---------------------------------------------------------------- 文档权限

    @Test
    void 未登录只召回公开文档_登录后全部可见() throws Exception {
        Settings s = settings("acl");
        try (Connection conn = init(s)) {
            seedDoc(conn, "pub01", "报销口径与差旅标准", AccessLevel.PUBLIC);
            seedDoc(conn, "sec01", "报销口径的内部附件", AccessLevel.PROTECTED);

            // 未登录：public_only 由 AuthService.accessFilter 打上，过滤在 SQL 层
            List<Map<String, Object>> anon = ChunkStore.keywordSearch(conn, "kb_acl", "报销", 10,
                    AuthService.accessFilter(null, false));
            assertEquals(1, anon.size(), "未登录只能召回公开文档");
            assertEquals("pub01#0001", anon.get(0).get("chunk_id"));

            // 已登录：不加过滤，两篇都在
            List<Map<String, Object>> admin = ChunkStore.keywordSearch(conn, "kb_acl", "报销", 10,
                    AuthService.accessFilter(null, true));
            assertEquals(2, admin.size(), "已登录可检索全部文档");

            // 用户自己塞请求参数也绕不过：access_filter 已强制 public_only
            Map<String, Object> tampered = new LinkedHashMap<>();
            tampered.put("sensitivity", "public,internal,restricted");
            assertEquals(1, ChunkStore.keywordSearch(conn, "kb_acl", "报销", 10,
                    AuthService.accessFilter(tampered, false)).size(),
                    "清空/伪造过滤条件不能突破权限");
        }
    }

    @Test
    void 权限字段_上传写入且改动立即生效() throws Exception {
        Settings s = settings("switch");
        try (Connection conn = init(s)) {
            seedDoc(conn, "doc-switch", "差旅政策的第九条", AccessLevel.PROTECTED);
            try (PreparedStatement ps = conn.prepareStatement(
                    "SELECT access_level FROM documents WHERE doc_id=?")) {
                ps.setString(1, "doc-switch");
                try (ResultSet rs = ps.executeQuery()) {
                    assertTrue(rs.next());
                    assertEquals("protected", rs.getString(1), "上传时的 access_level 必须落库");
                }
            }
            Db.endRead(conn);   // 收尾读事务：AuthService 会从别的连接写，再读才不会看到旧快照

            AuthService auth = new AuthService(s);
            assertFalse(auth.canRead("doc-switch", false), "未登录不能读受限文档");
            assertTrue(auth.canRead("doc-switch", true), "已登录可读全部");
            // documents 里没有记录的历史 doc：按公开处理（存量文档不会因改版突然消失）
            assertTrue(auth.canRead("legacy-doc-without-row", false));

            assertTrue(auth.setAccessLevel("doc-switch", "public"));
            conn.commit();
            assertTrue(auth.canRead("doc-switch", false), "改成公开后未登录即可访问");
            assertEquals(1, ChunkStore.keywordSearch(conn, "kb_acl", "差旅", 10,
                    AuthService.accessFilter(null, false)).size(), "改权限对检索立即生效");

            // 非法值归一化为 public 而不是报错写脏数据；未知 doc 返回 false
            assertTrue(auth.setAccessLevel("doc-switch", "whatever"));
            assertEquals(AccessLevel.PUBLIC, auth.accessLevelOf("doc-switch"));
            assertFalse(auth.setAccessLevel("no-such-doc", "protected"));
        }
    }

    @Test
    void 未登录访问受限文档_提示里带登录入口() {
        String msg = AuthService.deniedMessage("doc-x");
        assertTrue(msg.contains("需登录"), msg);
        assertTrue(msg.contains("/ui/login"), "提示必须给出可照做的下一步：" + msg);
    }

    @Test
    void 统计受限文档数_只数protected() throws Exception {
        Settings s = settings("count");
        try (Connection conn = init(s)) {
            seedDoc(conn, "p1", "公开一", AccessLevel.PUBLIC);
            seedDoc(conn, "p2", "受限一", AccessLevel.PROTECTED);
            seedDoc(conn, "p3", "受限二", AccessLevel.PROTECTED);
        }
        AuthService auth = new AuthService(s);
        assertEquals(2, auth.countProtected(java.util.Collections.singletonList("kb_acl")));
        assertEquals(0, auth.countProtected(java.util.Collections.singletonList("other_kb")));
    }
}
