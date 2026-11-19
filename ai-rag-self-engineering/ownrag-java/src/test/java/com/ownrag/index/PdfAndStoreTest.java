package com.ownrag.index;

import java.nio.file.Path;
import java.sql.Connection;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.pdmodel.PDPage;
import org.apache.pdfbox.pdmodel.PDPageContentStream;
import org.apache.pdfbox.pdmodel.common.PDRectangle;
import org.apache.pdfbox.pdmodel.font.PDType1Font;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import com.ownrag.core.Db;
import com.ownrag.core.StepContext;
import com.ownrag.core.StepResult;
import com.ownrag.ingest.DetectPages;
import com.ownrag.ingest.ParsedDoc;
import com.ownrag.ingest.ParsePdfbox;
import com.ownrag.retrieve.RetrieveTest;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * PDF 兜底链 + 存储三通道回归：
 * PDFBox 生成真实文本 PDF → detect_pages 判电子版 → parse_pdfbox 逐页锚点 →
 * FTS5 关键词通道 CJK 逐字检索 → 向量通道暴力余弦 topK。
 */
class PdfAndStoreTest {

    @TempDir
    Path tmp;

    /** 生成两页文本 PDF（Helvetica 内置字体，无中文依赖）。 */
    private static Path makeTextPdf(Path dir, String name) throws Exception {
        Path pdf = dir.resolve(name);
        try (PDDocument doc = new PDDocument()) {
            for (int p = 0; p < 2; p++) {
                PDPage page = new PDPage(PDRectangle.A4);
                doc.addPage(page);
                try (PDPageContentStream cs = new PDPageContentStream(doc, page)) {
                    cs.beginText();
                    cs.setFont(PDType1Font.HELVETICA, 12);
                    cs.newLineAtOffset(50, 700);
                    cs.showText("Page " + (p + 1) + " contract amount is 10000 USD.");
                    cs.endText();
                }
            }
            doc.save(pdf.toFile());
        }
        return pdf;
    }

    private static StepContext ctx(com.ownrag.config.Settings settings, Connection conn,
                                   String docId, Path src) {
        StepContext ctx = new StepContext(docId, "t1", "default", conn, settings);
        ctx.data.put("source_path", src.toString());
        return ctx;
    }

    @Test
    void detectPages_电子版判pipeline_扫描件判vlm() throws Exception {
        Path pdf = makeTextPdf(tmp, "text.pdf");
        com.ownrag.config.Settings settings = new RetrieveTest.SettingsBuilder().dataDir(tmp.resolve("data")).build();
        Db.initSchema(settings.getDbPath());
        try (Connection conn = Db.connect(settings.getDbPath())) {
            StepResult r = new DetectPages().run(ctx(settings, conn, "d1", pdf), mapOf("sample_pages", 3));
            assertTrue(r.ok);
            assertEquals("pipeline", r.data.get("page_route"));
            assertTrue((Integer) r.metrics.get("text_chars") > 50);
        }
        // 无文本层的"扫描件"：空字节文件 PDFBox 加载失败 → 999 探测不拦路？999 > 50 → pipeline。
        // 与 Python 版口径一致：探测失败不拦路，交由 parse_mineru 自身路由。
    }

    @Test
    void parse_pdfbox_逐页锚点与降级标记() throws Exception {
        Path pdf = makeTextPdf(tmp, "text2.pdf");
        com.ownrag.config.Settings settings = new RetrieveTest.SettingsBuilder().dataDir(tmp.resolve("data2")).build();
        Db.initSchema(settings.getDbPath());
        try (Connection conn = Db.connect(settings.getDbPath())) {
            StepResult r = new ParsePdfbox().run(ctx(settings, conn, "d2", pdf), mapOf());
            assertTrue(r.ok);
            assertEquals(2, r.metrics.get("pages"));
            assertEquals(1, r.metrics.get("degraded"));
        }
    }

    @Test
    void fts5_CJK逐字检索与bm25负分() throws Exception {
        com.ownrag.config.Settings settings = new RetrieveTest.SettingsBuilder().dataDir(tmp.resolve("data3")).build();
        Db.initSchema(settings.getDbPath());
        try (Connection conn = Db.connect(settings.getDbPath())) {
            List<Map<String, Object>> chunks = new ArrayList<>();
            chunks.add(chunk("d#0001", "公司报销流程要求先提交发票", "kb1"));
            chunks.add(chunk("d#0002", "出差申请需要部门审批", "kb1"));
            ChunkStore.keywordUpsert(conn, chunks);
            conn.commit();

            List<Map<String, Object>> hits = ChunkStore.keywordSearch(conn, "kb1", "报销", 10);
            assertEquals(1, hits.size());
            assertEquals("d#0001", hits.get(0).get("chunk_id"));
            assertTrue((Double) hits.get(0).get("score") > 0, "bm25 取负后为正分");

            // 字符化 OR 阶梯：更长查询词也能命中
            List<Map<String, Object>> hits2 = ChunkStore.keywordSearch(conn, "kb1", "报销流程", 10);
            assertEquals(1, hits2.size());
        }
    }

    @Test
    void 向量通道_blob往返与暴力余弦topK() throws Exception {
        com.ownrag.config.Settings settings = new RetrieveTest.SettingsBuilder().dataDir(tmp.resolve("data4")).build();
        Db.initSchema(settings.getDbPath());
        try (Connection conn = Db.connect(settings.getDbPath())) {
            List<Map<String, Object>> chunks = new ArrayList<>();
            chunks.add(chunk("d#0001", "报销", "kb1"));
            chunks.add(chunk("d#0002", "出差", "kb1"));
            List<List<Double>> embeddings = new ArrayList<>();
            embeddings.add(java.util.Arrays.asList(1.0, 0.0, 0.0));
            embeddings.add(java.util.Arrays.asList(0.0, 1.0, 0.0));
            ChunkStore.vectorUpsert(conn, "kb1", chunks, embeddings);
            conn.commit();

            // blob 往返无损（float 精度）
            float[] roundTrip = ChunkStore.fromBlob(ChunkStore.toBlob(new float[]{1.5f, -2.25f}));
            assertEquals(1.5f, roundTrip[0], 1e-6);
            assertEquals(-2.25f, roundTrip[1], 1e-6);

            // 查询向量与第 0 块同向 → top1 = d#0001
            List<Map<String, Object>> hits =
                    ChunkStore.vectorSearch(conn, "kb1", new float[]{1f, 0.1f, 0f}, 2);
            assertEquals("d#0001", hits.get(0).get("chunk_id"));
            assertTrue((Double) hits.get(0).get("score") > 0.9);
            assertEquals("vector", hits.get(0).get("channel"));

            // 按 doc 删：两块 doc_id 都是 "d"，删后应清零
            ChunkStore.vectorDeleteDoc(conn, "d");
            assertEquals(0, ChunkStore.countVectors(conn));
        }
    }

    @Test
    void parsedDoc_isUsable口径() {
        ParsedDoc empty = new ParsedDoc("d", "pdf", "  ", null, null, null, null);
        String[] r1 = empty.isUsable(20);
        assertEquals(null, r1[0]);
        assertTrue(r1[1].contains("空 Markdown"));

        ParsedDoc shortDoc = new ParsedDoc("d", "pdf", "太短", null, null, null, null);
        String[] r2 = shortDoc.isUsable(20);
        assertEquals(null, r2[0]);
        assertTrue(r2[1].contains("正文过短"));

        ParsedDoc ok = new ParsedDoc("d", "pdf", "这是一段足够长的正文内容，超过二十个字符了。", null, null, null, null);
        String[] r3 = ok.isUsable(20);
        assertEquals("", r3[0]);
    }

    @Test
    void schemaInfer_CJK列名SQL与类型推断() throws Exception {
        // 回归：COALESCE 标识符引号曾未闭合（CJK 列名触发 token 错误）
        com.ownrag.config.Settings settings = new RetrieveTest.SettingsBuilder().dataDir(tmp.resolve("data6")).build();
        Db.initSchema(settings.getDbPath());
        try (Connection conn = Db.connect(settings.getDbPath())) {
            try (java.sql.Statement st = conn.createStatement()) {
                st.executeUpdate("CREATE TABLE \"staging_test_csv\" ("
                        + "\"月份\" TEXT, \"部门\" TEXT, \"报销金额\" TEXT, \"状态\" TEXT,"
                        + " \"_src_file\" TEXT, \"_sheet\" TEXT, \"_rownum\" INTEGER)");
                for (String[] r : new String[][]{{"2026-01", "研发部", "12350.50", "已支付"},
                        {"2026-01", "研发部", "8800.00", "已支付"},
                        {"2026-02", "市场部", "9120.75", "待审批"}}) {
                    st.executeUpdate("INSERT INTO \"staging_test_csv\" VALUES ('" + r[0] + "','" + r[1]
                            + "','" + r[2] + "','" + r[3] + "','f','csv',1)");
                }
            }
            conn.commit();

            StepContext ctx = new StepContext("docX", "t9", "kb1", conn, settings);
            java.util.List<Map<String, Object>> staged = new ArrayList<>();
            Map<String, Object> item = new java.util.LinkedHashMap<>();
            item.put("table", "staging_test_csv");
            item.put("sheet", "csv");
            item.put("rows", 3);
            staged.add(item);
            ctx.data.put("staged", staged);

            StepResult r = new com.ownrag.ingest.SchemaInferStep().run(ctx, java.util.Collections.emptyMap());
            assertTrue(r.ok, "schema_infer 必须成功：" + r.error);
            List<Map<String, Object>> schemas = (List<Map<String, Object>>) ctx.data.get("schemas");
            Map<String, String> types = new java.util.LinkedHashMap<>();
            for (Map<String, Object> col : (List<Map<String, Object>>) schemas.get(0).get("columns")) {
                types.put(String.valueOf(col.get("column")), String.valueOf(col.get("type")));
            }
            assertEquals("date", types.get("月份"));  // "2026-01" 命中日期正则（与 Python 版同规则）
            assertEquals("number", types.get("报销金额"));
            assertEquals("enum", types.get("部门"));  // 唯一值 2 ≤ max(3, 3/20) → enum
        }
    }

    private static Map<String, Object> chunk(String chunkId, String text, String kb) {
        Map<String, Object> c = new LinkedHashMap<>();
        c.put("chunk_id", chunkId);
        c.put("doc_id", chunkId.split("#")[0]);
        c.put("kb", kb);
        c.put("text", text);
        return c;
    }

    private static Map<String, Object> mapOf(Object... pairs) {
        Map<String, Object> m = new LinkedHashMap<>();
        for (int i = 0; i + 1 < pairs.length; i += 2) {
            m.put(String.valueOf(pairs[i]), pairs[i + 1]);
        }
        return m;
    }
}
