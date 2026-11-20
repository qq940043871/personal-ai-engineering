package com.ownrag.index;

import java.nio.file.Path;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import com.ownrag.core.Db;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 向量版本隔离回归（2026-11-20 审查发现）：
 * 换 embedding 模型时新旧向量同表同维（bge-m3 / bge-large-zh-v1.5 都是 1024），
 * 不校验 embed_version 就会把两套向量空间混算——不报错、只静默降质。
 * 这里锁死：带版本召回只回同版本，版本不符直接空；不带版本（测试/调试口径）才全量。
 */
class EmbedVersionGuardTest {

    @TempDir
    Path tmp;

    private static float[] vec(double a, double b) {
        return new float[]{(float) a, (float) b};
    }

    private Connection seed() throws Exception {
        Path db = tmp.resolve("ver.db");
        Db.initSchema(db);
        Connection conn = Db.connect(db);

        try (PreparedStatement ps = conn.prepareStatement(
                "INSERT INTO chunks(chunk_id, doc_id, kb, source_type, ordinal, text, embed_version) "
                        + "VALUES (?,?,?,?,?,?,?)")) {
            ps.setString(1, "d1#0001");
            ps.setString(2, "d1");
            ps.setString(3, "kb1");
            ps.setString(4, "md");
            ps.setInt(5, 1);
            ps.setString(6, "旧模型向量块");
            ps.setString(7, "bge-m3@local");
            ps.executeUpdate();

            ps.setString(1, "d2#0001");
            ps.setString(2, "d2");
            ps.setString(3, "kb1");
            ps.setString(4, "md");
            ps.setInt(5, 1);
            ps.setString(6, "新模型向量块");
            ps.setString(7, "bge-large-zh-v1.5@siliconflow");
            ps.executeUpdate();
        }

        List<Map<String, Object>> chunks = new ArrayList<>();
        List<List<Double>> embs = new ArrayList<>();
        String[] ids = {"d1#0001", "d2#0001"};
        double[][] values = {{1.0, 0.0}, {0.6, 0.8}};
        for (int i = 0; i < ids.length; i++) {
            Map<String, Object> c = new LinkedHashMap<>();
            c.put("chunk_id", ids[i]);
            c.put("doc_id", ids[i].split("#")[0]);
            chunks.add(c);
            embs.add(Arrays.asList(values[i][0], values[i][1]));
        }
        ChunkStore.vectorUpsert(conn, "kb1", chunks, embs);
        conn.commit();
        return conn;
    }

    @Test
    void 带版本召回只回同版本_不混算旧向量() throws Exception {
        try (Connection conn = seed()) {
            List<Map<String, Object>> hits = ChunkStore.vectorSearch(conn,
                    java.util.Collections.singletonList("kb1"), vec(1.0, 0.0), 10, null,
                    "bge-large-zh-v1.5@siliconflow");
            assertEquals(1, hits.size(), "只应召回当前 embed_version 的块：" + hits);
            assertEquals("d2#0001", hits.get(0).get("chunk_id"));

            // 库里存在旧版本、但请求的是新版本 → 旧向量必须完全不可见
            List<Map<String, Object>> onlyOld = ChunkStore.vectorSearch(conn,
                    java.util.Collections.singletonList("kb1"), vec(1.0, 0.0), 10, null, "bge-m3@local");
            assertEquals(1, onlyOld.size());
            assertEquals("d1#0001", onlyOld.get(0).get("chunk_id"));

            // 版本值对不上 = 空（降级可见，不退化成"全量混算"）
            List<Map<String, Object>> none = ChunkStore.vectorSearch(conn,
                    java.util.Collections.singletonList("kb1"), vec(1.0, 0.0), 10, null, "other@vendor");
            assertTrue(none.isEmpty(), "版本不符时必须空，而不是返回别的版本向量");
        }
    }

    @Test
    void 不带版本时全量召回_仅供单测与调试() throws Exception {
        try (Connection conn = seed()) {
            List<Map<String, Object>> hits = ChunkStore.vectorSearch(conn,
                    java.util.Collections.singletonList("kb1"), vec(1.0, 0.0), 10, null);
            assertEquals(2, hits.size());
            // 余弦降序：与查询向量同向的旧向量排第一
            assertEquals("d1#0001", hits.get(0).get("chunk_id"));
        }
    }
}
