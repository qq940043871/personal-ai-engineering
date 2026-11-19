package com.ownrag.index;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import com.ownrag.core.Db;
import com.ownrag.core.StepContext;
import com.ownrag.core.StepResult;
import com.ownrag.ingest.ParseTextFile;
import com.ownrag.retrieve.RetrieveTest;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 个人维度过滤回归（P0-2）：过滤列迁移、meta 提升落列、双通道先过滤后召回、
 * 多库 IN、md front-matter 提取。红线口径：restricted 只有显式放行才可见。
 */
class MetadataFilterTest {

    @TempDir
    Path tmp;

    private Connection conn(String name) throws Exception {
        Path db = tmp.resolve(name + ".db");
        Db.initSchema(db);
        return Db.connect(db);
    }

    private static Map<String, Object> chunk(String id, String text, String kb,
                                             String sensitivity, String topic, String docDate) {
        Map<String, Object> c = new LinkedHashMap<>();
        c.put("chunk_id", id);
        c.put("doc_id", id.split("#")[0]);
        c.put("kb", kb);
        c.put("source_type", "md");
        c.put("ordinal", 1);
        c.put("text", text);
        Map<String, Object> meta = new LinkedHashMap<>();
        if (sensitivity != null) {
            meta.put("sensitivity", sensitivity);
        }
        if (topic != null) {
            meta.put("topic", topic);
        }
        if (docDate != null) {
            meta.put("doc_date", docDate);
        }
        c.put("meta", meta);
        return c;
    }

    private static Map<String, Object> filterOf(String k1, Object v1, String k2, Object v2) {
        Map<String, Object> m = new LinkedHashMap<>();
        if (k1 != null) {
            m.put(k1, v1);
        }
        if (k2 != null) {
            m.put(k2, v2);
        }
        return m;
    }

    @Test
    void 旧库迁移_补齐过滤列幂等() throws Exception {
        Path db = tmp.resolve("legacy.db");
        try (Connection conn = Db.connect(db)) {
            // 造一个"改造前"的旧 schema：无四个过滤列
            java.sql.Statement st1 = conn.createStatement();
            try {
                st1.executeUpdate("DROP TABLE IF EXISTS chunks");
                st1.executeUpdate("CREATE TABLE chunks (chunk_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL,"
                        + " kb TEXT NOT NULL, source_type TEXT, ordinal INTEGER, text TEXT NOT NULL,"
                        + " anchors_json TEXT, meta_json TEXT, embed_version TEXT,"
                        + " created_at TEXT DEFAULT (datetime('now','localtime')))");
                st1.executeUpdate("INSERT INTO chunks(chunk_id, doc_id, kb, text) VALUES ('old#0001','old','k','旧行')");
            } finally {
                st1.close();
            }
            conn.commit();
            Db.migrate(conn);
            conn.commit();
            // 迁移后新列可读，旧行 sensitivity 为 NULL（检索按 internal 兜底）
            java.sql.Statement st2 = conn.createStatement();
            try {
                ResultSet rs = st2.executeQuery("SELECT sensitivity, topic FROM chunks WHERE chunk_id='old#0001'");
                assertTrue(rs.next());
                assertEquals(null, rs.getString("sensitivity"));
            } finally {
                st2.close();
            }
            // 幂等：再跑一次不炸
            Db.migrate(conn);
            conn.commit();
        }
    }

    @Test
    void indexUpsert_meta过滤字段提升为列() throws Exception {
        try (Connection conn = conn("upsert")) {
            List<Map<String, Object>> chunks = new ArrayList<>();
            chunks.add(chunk("d1#0001", "撮合引擎单线程内存结构", "kbx", "restricted", "撮合", "2026-01-01"));
            StepContext ctx = new StepContext("d1", "t1", "kbx", conn,
                    new RetrieveTest.SettingsBuilder().dataDir(tmp.resolve("data1")).build());
            ctx.data.put("chunks", chunks);
            StepResult r = new IndexUpsertStep().run(ctx, new LinkedHashMap<>());
            assertTrue(r.ok, "index_upsert 应成功：" + r.error + "（vector=skipped 属预期）");

            try (PreparedStatement ps = conn.prepareStatement(
                    "SELECT sensitivity, topic, doc_date FROM chunks WHERE chunk_id='d1#0001'")) {
                try (ResultSet rs = ps.executeQuery()) {
                    assertTrue(rs.next());
                    assertEquals("restricted", rs.getString("sensitivity"));
                    assertEquals("撮合", rs.getString("topic"));
                    assertEquals("2026-01-01", rs.getString("doc_date"));
                }
            }
        }
    }

    @Test
    void bm25过滤_restricted默认不可见_多库IN() throws Exception {
        try (Connection conn = conn("bm25")) {
            List<Map<String, Object>> chunks = new ArrayList<>();
            chunks.add(chunk("d1#0001", "撮合引擎的撮合细节", "kb1", "internal", null, null));
            chunks.add(chunk("d2#0001", "撮合引擎的另一个说法", "kb1", "restricted", null, null));
            chunks.add(chunk("d3#0001", "撮合在另一个知识库", "kb2", "internal", null, null));
            ChunkStore.keywordUpsert(conn, chunks);
            // chunks 表也要有行（过滤列在这里）：index_upsert 会写，这里手工按生产口径补
            try (PreparedStatement ps = conn.prepareStatement(
                    "INSERT OR REPLACE INTO chunks(chunk_id, doc_id, kb, text, meta_json, sensitivity) "
                            + "VALUES (?,?,?,?,?,?)")) {
                for (Map<String, Object> c : chunks) {
                    ps.setString(1, String.valueOf(c.get("chunk_id")));
                    ps.setString(2, String.valueOf(c.get("doc_id")));
                    ps.setString(3, String.valueOf(c.get("kb")));
                    ps.setString(4, String.valueOf(c.get("text")));
                    ps.setString(5, "{}");
                    ps.setString(6, String.valueOf(((Map<?, ?>) c.get("meta")).get("sensitivity")));
                    ps.executeUpdate();
                }
            }
            conn.commit();

            // 默认（不过滤）：三库都命中？单库只 kb1 两块
            assertEquals(2, ChunkStore.keywordSearch(conn, "kb1", "撮合", 10).size());
            // 多库 IN：kb1+kb2 = 3 块
            assertEquals(3, ChunkStore.keywordSearch(conn, Arrays.asList("kb1", "kb2"), "撮合", 10, null).size());
            // 默认放行档位：internal+public → restricted 不可见
            List<Map<String, Object>> hits = ChunkStore.keywordSearch(conn, Arrays.asList("kb1", "kb2"),
                    "撮合", 10, filterOf("sensitivity", "public,internal", null, null));
            assertEquals(2, hits.size(), "restricted 必须被过滤");
            // 显式放行 restricted → 可见
            List<Map<String, Object>> hits2 = ChunkStore.keywordSearch(conn, "kb1",
                    "撮合", 10, filterOf("sensitivity", "restricted", null, null));
            assertEquals(1, hits2.size());
            assertEquals("d2#0001", hits2.get(0).get("chunk_id"));
        }
    }

    @Test
    void 向量过滤_同一套口径() throws Exception {
        try (Connection conn = conn("vec")) {
            List<Map<String, Object>> chunks = new ArrayList<>();
            chunks.add(chunk("d1#0001", "公开", "kb1", "public", null, "2026-01-01"));
            chunks.add(chunk("d2#0001", "受限", "kb1", "restricted", null, "2026-06-01"));
            // chunks 行（过滤列在这里）：index_upsert 会写，这里手工按生产口径补
            try (PreparedStatement ps = conn.prepareStatement(
                    "INSERT OR REPLACE INTO chunks(chunk_id, doc_id, kb, text, meta_json, sensitivity, doc_date) "
                            + "VALUES (?,?,?,?,?,?,?)")) {
                for (Map<String, Object> c : chunks) {
                    ps.setString(1, String.valueOf(c.get("chunk_id")));
                    ps.setString(2, String.valueOf(c.get("doc_id")));
                    ps.setString(3, String.valueOf(c.get("kb")));
                    ps.setString(4, String.valueOf(c.get("text")));
                    ps.setString(5, "{}");
                    ps.setString(6, String.valueOf(((Map<?, ?>) c.get("meta")).get("sensitivity")));
                    ps.setString(7, String.valueOf(((Map<?, ?>) c.get("meta")).get("doc_date")));
                    ps.executeUpdate();
                }
            }
            List<List<Double>> embeddings = new ArrayList<>();
            embeddings.add(Arrays.asList(1.0, 0.0));
            embeddings.add(Arrays.asList(0.0, 1.0));
            ChunkStore.vectorUpsert(conn, "kb1", chunks, embeddings);
            conn.commit();

            float[] q = {1f, 0f};
            // 不过滤：两块都回
            assertEquals(2, ChunkStore.vectorSearch(conn, "kb1", q, 10).size());
            // sensitivity 过滤：只剩 public（d1）
            List<Map<String, Object>> hits = ChunkStore.vectorSearch(conn, "kb1", q, 10,
                    filterOf("sensitivity", "public", null, null));
            assertEquals(1, hits.size());
            assertEquals("d1#0001", hits.get(0).get("chunk_id"));
            // date 过滤：2026-03-01 之后只剩 d2
            List<Map<String, Object>> hits2 = ChunkStore.vectorSearch(conn, "kb1", q, 10,
                    filterOf("date_from", "2026-03-01", null, null));
            assertEquals(1, hits2.size());
            assertEquals("d2#0001", hits2.get(0).get("chunk_id"));
        }
    }

    @Test
    void md_frontMatter提取_剥离并进元数据() throws Exception {
        Path f = tmp.resolve("doc.md");
        String content = "---\ntopic: 撮合\ndate: 2026-05-19\nsensitivity: internal\n---\n\n"
                + "# 撮合叙事\n\n正文足够长，能过校验闸门的二十个字符下限。";
        Files.write(f, content.getBytes(StandardCharsets.UTF_8));
        StepContext ctx = new StepContext("dfm", "t1", "kbz", null,
                new RetrieveTest.SettingsBuilder().dataDir(tmp.resolve("data2")).build());
        ctx.data.put("source_path", f.toString());
        Map<String, Object> sm = new LinkedHashMap<>();
        sm.put("source_file", f.getFileName().toString());
        sm.put("size_bytes", 0);
        ctx.data.put("source_meta", sm);

        StepResult r = new ParseTextFile().run(ctx, new LinkedHashMap<>());
        assertTrue(r.ok, "解析应成功：" + r.error);
        Map<String, Object> parsed = (Map<String, Object>) ctx.data.get("parsed");
        String md = String.valueOf(parsed.get("markdown"));
        assertFalse(md.contains("---"), "front-matter 必须剥离出正文");
        assertTrue(md.contains("# 撮合叙事"));
        @SuppressWarnings("unchecked")
        Map<String, Object> meta = (Map<String, Object>) parsed.get("metadata");
        assertEquals("撮合", meta.get("topic"));
        assertEquals("2026-05-19", meta.get("doc_date"), "date → doc_date 规范化");
        assertEquals("internal", meta.get("sensitivity"));
    }
}
