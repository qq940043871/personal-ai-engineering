package com.ownrag.retrieve;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** 检索层纯函数回归：RRF 名次融合 + 直击库归一化/余弦。 */
public class RetrieveTest {

    private static Map<String, Object> hit(String chunkId, String channel, double score) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("chunk_id", chunkId);
        m.put("doc_id", chunkId.split("#")[0]);
        m.put("score", score);
        m.put("channel", channel);
        return m;
    }

    @Test
    void rrf_手算对齐1除以60加rank() {
        List<List<Map<String, Object>>> lists = new ArrayList<>();
        List<Map<String, Object>> vector = new ArrayList<>();
        vector.add(hit("d#0001", "vector", 0.9));
        vector.add(hit("d#0002", "vector", 0.8));
        List<Map<String, Object>> bm25 = new ArrayList<>();
        bm25.add(hit("d#0002", "bm25", 5.2));
        lists.add(vector);
        lists.add(bm25);

        List<Map<String, Object>> fused = HybridSearch.rrfFuse(lists, 60, 10);
        // d#0002: vector 路 rank1（1/62）+ bm25 路 rank0（1/61）；d#0001: vector 路 rank0（1/61）
        double expect2 = 1.0 / 61 + 1.0 / 62;
        assertEquals(expect2, (Double) fused.get(0).get("rrf"), 1e-9);
        assertEquals(1.0 / 61, (Double) fused.get(1).get("rrf"), 1e-9);
        assertEquals("d#0002", fused.get(0).get("chunk_id"));
        // channels 记录每路贡献
        assertEquals(2, ((List<?>) fused.get(0).get("channels")).size());
    }

    @Test
    void rrf_topN截断() {
        List<List<Map<String, Object>>> lists = new ArrayList<>();
        List<Map<String, Object>> single = new ArrayList<>();
        for (int i = 1; i <= 5; i++) {
            single.add(hit(String.format("d#%04d", i), "bm25", 5 - i));
        }
        lists.add(single);
        List<Map<String, Object>> fused = HybridSearch.rrfFuse(lists, 60, 3);
        assertEquals(3, fused.size());
    }

    @Test
    void 直击库归一化_全半角与标点() {
        assertEquals("abc123测试", DirectHit.normalize("ＡＢＣ１２３，测试！ "));
        assertEquals("abc123test", DirectHit.normalize("ABC123,TEST！ "));
        assertEquals(DirectHit.normalize("报销口径？"), DirectHit.normalize("报销口径"));
    }

    @Test
    void 余弦_方向一致满分() {
        List<Double> a = java.util.Arrays.asList(1.0, 0.0, 2.0);
        assertEquals(1.0, DirectHit.cosine(a, a), 1e-9);
        assertEquals(0.0, DirectHit.cosine(a, java.util.Arrays.asList(0.0, 1.0, 0.0)), 1e-9);
    }

    @Test
    void rerank_siliconflow降级可见() {
        // 未配置 base_url/api_key → 原序返回 + 明确说明（不抛异常，不拖垮问答）
        com.ownrag.config.Settings s = new SettingsBuilder().build();
        RerankClient client = new RerankClient(new okhttp3.OkHttpClient());
        List<Map<String, Object>> candidates = new ArrayList<>();
        Map<String, Object> c = new LinkedHashMap<>();
        c.put("text", "x");
        candidates.add(c);
        RerankClient.RerankResult r = client.rerankSiliconflow(s, "q", candidates, 5);
        assertEquals(1, r.candidates.size());
        assertTrue(r.note.contains("未配置"), r.note);
    }

    /** 测试专用 Settings 构造器（最小可用配置，跨测试包共用）。 */
    public static class SettingsBuilder {
        private String embedProvider = "openai";
        private String embedBaseUrl = "http://localhost:1/v1";
        private String embedApiKey = "k";
        private String embedModel = "bge-m3";
        private String embedVersion = "test";
        private String chatProvider = "openai";
        private String chatBaseUrl = "http://localhost:1/v1";
        private String chatApiKey = "k";
        private String chatModel = "m";
        private String rerankProvider = "";
        private String rerankBaseUrl = "";
        private String rerankModel = "BAAI/bge-reranker-v2-m3";
        private String ollamaBaseUrl = "http://127.0.0.1:11434";
        private String mineruMode = "open";
        private String mineruOpenBaseUrl = com.ownrag.ingest.MineruOpenClient.API_BASE_DEFAULT;
        private int numCtx = 6144;
        private int maxNewTokens = 512;
        private int maxUploadMb = 200;
        private java.nio.file.Path dataDir;

        public SettingsBuilder embedProvider(String v) { this.embedProvider = v; return this; }
        public SettingsBuilder rerankProvider(String v) { this.rerankProvider = v; return this; }
        public SettingsBuilder rerankBaseUrl(String v) { this.rerankBaseUrl = v; return this; }
        public SettingsBuilder mineruMode(String v) { this.mineruMode = v; return this; }
        public SettingsBuilder dataDir(java.nio.file.Path v) { this.dataDir = v; return this; }

        public com.ownrag.config.Settings build() {
            return new com.ownrag.config.Settings(
                    dataDir == null ? java.nio.file.Paths.get("./data") : dataDir,
                    "",
                    ollamaBaseUrl, chatProvider, chatBaseUrl, chatApiKey, chatModel,
                    embedProvider, embedBaseUrl, embedApiKey, embedModel, embedVersion, "",
                    rerankProvider, rerankBaseUrl, rerankModel, "",
                    mineruMode, "", mineruOpenBaseUrl, "token",
                    "http://localhost:1/v1", "m", "zh", "k",
                    numCtx, maxNewTokens, maxUploadMb,
                    new LinkedHashMap<>(), new LinkedHashMap<>(), new LinkedHashMap<>());
        }
    }
}
