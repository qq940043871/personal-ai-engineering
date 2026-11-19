package com.ownrag.ingest;

import java.nio.charset.Charset;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;

import org.apache.poi.xwpf.usermodel.XWPFDocument;
import org.apache.poi.xwpf.usermodel.XWPFParagraph;
import org.apache.poi.xwpf.usermodel.XWPFTable;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import com.ownrag.core.StepContext;
import com.ownrag.core.StepResult;
import com.ownrag.index.ChunkMarkdownStep;
import com.ownrag.index.ValidateParsedStep;
import com.ownrag.retrieve.RetrieveTest;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 文本/docx 直传链回归（个人知识库场景新增链路）：
 * md 原生直通 → validate → chunk 带标题路径；txt GBK 降级可见；
 * docx 标题样式转 #、表格转管道表、结构登记 table；坏编码显式失败不静默。
 */
class ParseTextAndDocxTest {

    @TempDir
    Path tmp;

    private StepContext ctx(String docId, Path src) {
        com.ownrag.config.Settings settings = new RetrieveTest.SettingsBuilder().dataDir(tmp.resolve("data")).build();
        // 这三个步骤不触库：conn 传 null 即可（与执行器无关，执行器才管 conn）
        StepContext ctx = new StepContext(docId, "t1", "default", null, settings);
        ctx.data.put("source_path", src.toString());
        Map<String, Object> sm = new LinkedHashMap<>();
        sm.put("source_file", src.getFileName().toString());
        sm.put("size_bytes", 0);
        ctx.data.put("source_meta", sm);
        return ctx;
    }

    @Test
    void md直通_标题树与表格由chunker承接() throws Exception {
        Path f = tmp.resolve("note.md");
        Files.write(f, ("# 一级标题\n\n正文第一段。\n\n## 二级标题\n\n"
                + "| 列A | 列B |\n| --- | --- |\n| 1 | 2 |\n\n```java\nint x = 1;\n```\n")
                .getBytes(StandardCharsets.UTF_8));
        StepContext ctx = ctx("dmd", f);

        StepResult r1 = new ParseTextFile().run(ctx, Collections.emptyMap());
        assertTrue(r1.ok, "parse_textfile 应成功：" + r1.error);
        Map<String, Object> parsed = (Map<String, Object>) ctx.data.get("parsed");
        assertEquals("md", parsed.get("source_type"));

        StepResult r2 = new ValidateParsedStep().run(ctx, mapOf("min_chars_per_page", 20));
        assertTrue(r2.ok, "validate 应通过：" + r2.error);

        StepResult r3 = new ChunkMarkdownStep().run(ctx, mapOf("max_tokens", 512, "overlap", 64));
        assertTrue(r3.ok);
        @SuppressWarnings("unchecked")
        java.util.List<Map<String, Object>> chunks =
                (java.util.List<Map<String, Object>>) ctx.data.get("chunks");
        assertTrue((Integer) r3.metrics.get("chunks") >= 2);
        // 块头注入：标题路径进正文，裸块不缺主语
        assertTrue(chunks.get(0).get("text").toString().contains("【note.md > 一级标题】"));
        boolean hasTable = false;
        for (Map<String, Object> c : chunks) {
            if (Boolean.TRUE.equals(((Map<?, ?>) c.get("meta")).get("has_table"))) {
                hasTable = true;
            }
        }
        assertTrue(hasTable, "表格块 has_table 应为 true");
    }

    @Test
    void txtGBK兜底_降级显式可见() throws Exception {
        Path f = tmp.resolve("old.txt");
        String content = "这是一段用 GBK 编码保存的中文文本，内容足够长以通过校验闸门。"
                + "这是一段用 GBK 编码保存的中文文本，内容足够长以通过校验闸门。";
        Files.write(f, content.getBytes(Charset.forName("GBK")));
        StepContext ctx = ctx("dtxt", f);

        StepResult r = new ParseTextFile().run(ctx, mapOf("format", "txt"));
        assertTrue(r.ok, "GBK 兜底应成功：" + r.error);
        assertEquals("gbk", r.metrics.get("encoding"));
        Map<String, Object> parsed = (Map<String, Object>) ctx.data.get("parsed");
        assertEquals("txt", parsed.get("source_type"));
        @SuppressWarnings("unchecked")
        Map<String, Object> meta = (Map<String, Object>) parsed.get("metadata");
        assertTrue(String.valueOf(meta.get("degraded")).contains("GBK"), "降级必须写进 metadata");
        assertEquals(content, parsed.get("markdown"), "GBK 解码应无损还原中文");
    }

    @Test
    void 坏编码显式失败不静默() throws Exception {
        Path f = tmp.resolve("bad.txt");
        Files.write(f, new byte[]{(byte) 0xFF, (byte) 0xFE, (byte) 0xFF});
        StepResult r = new ParseTextFile().run(ctx("dbad", f), Collections.emptyMap());
        assertFalse(r.ok);
        assertTrue(r.error.contains("编码不可判定"));
    }

    @Test
    void docx_标题样式转井号_表格转管道表() throws Exception {
        Path f = tmp.resolve("plan.docx");
        try (XWPFDocument doc = new XWPFDocument()) {
            XWPFParagraph h1 = doc.createParagraph();
            h1.setStyle("Heading1");
            h1.createRun().setText("面试准备计划");

            XWPFParagraph body = doc.createParagraph();
            body.createRun().setText("九大主题主线件是叙事唯一口径。");

            XWPFParagraph h2 = doc.createParagraph();
            h2.setStyle("2");  // 中文 Word 样式 id："2" = 标题 2
            h2.createRun().setText("追问弹药");

            XWPFTable t = doc.createTable(2, 2);
            t.getRow(0).getCell(0).setText("主题");
            t.getRow(0).getCell(1).setText("验收标准");
            t.getRow(1).getCell(0).setText("撮合");
            t.getRow(1).getCell(1).setText("5 问脱稿");

            java.io.OutputStream out = Files.newOutputStream(f);
            try {
                doc.write(out);
            } finally {
                out.close();
            }
        }
        StepContext ctx = ctx("ddocx", f);
        StepResult r = new ParseDocx().run(ctx, Collections.emptyMap());
        assertTrue(r.ok, "parse_docx 应成功：" + r.error);
        assertEquals(1, r.metrics.get("tables"));

        Map<String, Object> parsed = (Map<String, Object>) ctx.data.get("parsed");
        String md = String.valueOf(parsed.get("markdown"));
        assertTrue(md.contains("# 面试准备计划"));
        assertTrue(md.contains("## 追问弹药"));
        assertTrue(md.contains("| 主题 | 验收标准 |"), "表格应转管道表");
        @SuppressWarnings("unchecked")
        java.util.List<Map<String, Object>> structures =
                (java.util.List<Map<String, Object>>) parsed.get("structures");
        assertEquals(1, structures.size());
        assertEquals("table", structures.get(0).get("kind"));
    }

    @Test
    void docx超长表格截断留痕() throws Exception {
        Path f = tmp.resolve("big.docx");
        try (XWPFDocument doc = new XWPFDocument()) {
            XWPFTable t = doc.createTable(6, 1);
            for (int i = 0; i < 6; i++) {
                t.getRow(i).getCell(0).setText("行" + i);
            }
            java.io.OutputStream out = Files.newOutputStream(f);
            try {
                doc.write(out);
            } finally {
                out.close();
            }
        }
        StepContext ctx = ctx("dbig", f);
        StepResult r = new ParseDocx().run(ctx, mapOf("max_table_rows", 3));
        assertTrue(r.ok);
        String md = String.valueOf(((Map<String, Object>) ctx.data.get("parsed")).get("markdown"));
        assertTrue(md.contains("截断，共 6 行"), "超限截断必须留痕");
        assertFalse(md.contains("行5"), "被截断的行不出现");
    }

    private static Map<String, Object> mapOf(Object... pairs) {
        Map<String, Object> m = new LinkedHashMap<>();
        for (int i = 0; i + 1 < pairs.length; i += 2) {
            m.put(String.valueOf(pairs[i]), pairs[i + 1]);
        }
        return m;
    }
}
