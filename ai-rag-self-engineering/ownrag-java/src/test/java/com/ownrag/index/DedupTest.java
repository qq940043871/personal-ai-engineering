package com.ownrag.index;

import java.nio.file.Path;
import java.sql.Connection;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import com.ownrag.core.Db;
import com.ownrag.core.StepContext;
import com.ownrag.core.StepResult;
import com.ownrag.retrieve.RetrieveTest;
import com.ownrag.util.Hashes;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 指纹幂等与块去重回归（P0-3）：
 * 文件级 SHA-256 幂等（同 hash 索引在位不重灌）、块级跨文档去重（只查不写，
 * index_upsert 过闸登记）、同批内重复剔除、删文档释放指纹。
 */
class DedupTest {

    @TempDir
    Path tmp;

    private Connection conn(String name) throws Exception {
        Path db = tmp.resolve(name + ".db");
        Db.initSchema(db);
        return Db.connect(db);
    }

    private static Map<String, Object> chunk(String id, String text) {
        Map<String, Object> c = new LinkedHashMap<>();
        c.put("chunk_id", id);
        c.put("doc_id", id.split("#")[0]);
        c.put("kb", "kb1");
        c.put("source_type", "md");
        c.put("ordinal", Integer.parseInt(id.split("#")[1]));
        c.put("text", text);
        c.put("meta", new LinkedHashMap<String, Object>());
        return c;
    }

    @Test
    void chunkHash_空白折叠_异文异hash() throws Exception {
        String a = "撮合引擎：单线程\n内存撮合。";
        String b = "撮合引擎：单线程 内存撮合。";
        assertEquals(Hashes.chunkHash(a), Hashes.chunkHash(b), "空白折叠后同文同 hash");
        assertFalse(Hashes.chunkHash(a).equals(Hashes.chunkHash("不同正文的内容块")), "异文异 hash");
    }

    @Test
    void dedupeChunks_跨文档重复剔除_批内重复剔除() throws Exception {
        try (Connection conn = conn("dedupe")) {
            // 既有文档已入库 chunk A（hash 已登记）
            Map<String, Object> existing = chunk("dA#0001", "既有的撮合叙事正文。");
            existing.put("content_hash", Hashes.chunkHash("既有的撮合叙事正文。"));
            FingerprintStore.registerChunkHash(conn, String.valueOf(existing.get("content_hash")),
                    "dA#0001", "dA");
            conn.commit();

            StepContext ctx = new StepContext("dB", "t1", "kb1", conn,
                    new RetrieveTest.SettingsBuilder().dataDir(tmp.resolve("data1")).build());
            List<Map<String, Object>> batch = new ArrayList<>();
            batch.add(chunk("dB#0001", "既有的撮合叙事正文。"));          // 跨文档重复 → 剔除
            batch.add(chunk("dB#0002", "全新内容的块。"));                // 新内容 → 保留
            batch.add(chunk("dB#0003", "全新内容的块。"));                // 批内重复 → 剔除
            ctx.data.put("chunks", batch);

            StepResult r = new DedupeChunksStep().run(ctx, new LinkedHashMap<>());
            assertTrue(r.ok);
            assertEquals(3, r.metrics.get("total"));
            assertEquals(1, r.metrics.get("kept"));
            assertEquals(2, r.metrics.get("skipped"));

            @SuppressWarnings("unchecked")
            List<Map<String, Object>> kept = (List<Map<String, Object>>) ctx.data.get("chunks");
            assertEquals(1, kept.size());
            assertEquals("dB#0002", kept.get(0).get("chunk_id"));
            assertEquals(Hashes.chunkHash("全新内容的块。"), kept.get(0).get("content_hash"),
                    "保留块带 content_hash，登记责任在 index_upsert");
        }
    }

    @Test
    void indexUpsert登记hash_重复hash不再入库() throws Exception {
        try (Connection conn = conn("reg")) {
            // 第一次入库：两块，hash 登记
            StepContext ctx1 = new StepContext("d1", "t1", "kb1", conn,
                    new RetrieveTest.SettingsBuilder().dataDir(tmp.resolve("data2")).build());
            List<Map<String, Object>> batch1 = new ArrayList<>();
            batch1.add(chunk("d1#0001", "撮合叙事第一块。"));
            batch1.add(chunk("d1#0002", "撮合叙事第二块。"));
            ctx1.data.put("chunks", batch1);
            assertTrue(new IndexUpsertStep().run(ctx1, new LinkedHashMap<>()).ok);
            conn.commit();

            // dedupe 对重灌内容：同 hash 已登记 → 全部剔除（空批不炸）
            StepContext ctx2 = new StepContext("d2", "t2", "kb1", conn,
                    new RetrieveTest.SettingsBuilder().dataDir(tmp.resolve("data3")).build());
            List<Map<String, Object>> batch2 = new ArrayList<>();
            batch2.add(chunk("d2#0001", "撮合叙事第一块。"));
            ctx2.data.put("chunks", batch2);
            StepResult r = new DedupeChunksStep().run(ctx2, new LinkedHashMap<>());
            assertTrue(r.ok);
            assertEquals(0, r.metrics.get("kept"));
        }
    }

    @Test
    void 指纹登记查询与删除释放() throws Exception {
        try (Connection conn = conn("fp")) {
            FingerprintStore.registerFileHash(conn, "hashA", "docA", "kb1", "a.md");
            conn.commit();
            assertEquals("docA", FingerprintStore.findDocByFileHash(conn, "hashA"));
            assertEquals(null, FingerprintStore.findDocByFileHash(conn, "hashB"));

            FingerprintStore.deleteByDoc(conn, "docA");
            conn.commit();
            assertEquals(null, FingerprintStore.findDocByFileHash(conn, "hashA"), "删除即释放指纹");
        }
    }

    @Test
    void 幂等口径_索引在位才算重复() throws Exception {
        try (Connection conn = conn("idem")) {
            FingerprintStore.registerFileHash(conn, "hashA", "docA", "kb1", "a.md");
            conn.commit();
            // 索引不在位（管线失败/已删）→ 不算已入库
            assertFalse(FingerprintStore.hasIndexedChunks(conn, "docA"));
            // 补一条已索引块 → 在位
            java.sql.Statement st = conn.createStatement();
            try {
                st.executeUpdate("INSERT INTO chunks(chunk_id, doc_id, kb, text) "
                        + "VALUES ('docA#0001','docA','kb1','正文')");
            } finally {
                st.close();
            }
            conn.commit();
            assertTrue(FingerprintStore.hasIndexedChunks(conn, "docA"));
        }
    }
}
