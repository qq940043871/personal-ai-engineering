package com.ownrag.review;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** 文档统计口径回归：页数不估、跨页表格要报、公式/图片/表格三处交叉核对要能对上账。 */
class DocStatsTest {

    // ---------------------------------------------------------------- 用例构造

    private static Map<String, Object> parsed(String markdown, String format, String file,
                                              int pages, List<Map<String, Object>> structures,
                                              Map<String, Object> assets) {
        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put("format", format);
        metadata.put("source_file", file);
        Map<String, Object> stats = new LinkedHashMap<>();
        stats.put("pages", pages);
        Map<String, Object> p = new LinkedHashMap<>();
        p.put("markdown", markdown);
        p.put("metadata", metadata);
        p.put("stats", stats);
        p.put("structures", structures);
        p.put("assets", assets == null ? new LinkedHashMap<String, Object>() : assets);
        return p;
    }

    private static Map<String, Object> structure(String kind, String location, String text) {
        Map<String, Object> s = new LinkedHashMap<>();
        s.put("kind", kind);
        s.put("location", location);
        s.put("pointer", null);
        s.put("text", text);
        return s;
    }

    @SuppressWarnings("unchecked")
    private static List<String> suspectCodes(Map<String, Object> out) {
        List<String> codes = new ArrayList<>();
        for (Map<String, Object> s : (List<Map<String, Object>>) out.get("suspects")) {
            codes.add(String.valueOf(s.get("code")));
        }
        return codes;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> suspect(Map<String, Object> out, String code) {
        for (Map<String, Object> s : (List<Map<String, Object>>) out.get("suspects")) {
            if (code.equals(s.get("code"))) {
                return s;
            }
        }
        return null;
    }

    // ---------------------------------------------------------------- 页数口径

    @Test
    void PDF页数取解析器声明_页标记一致时不报存疑() {
        String md = "<!--page:1-->\n正文一\n\n<!--page:2-->\n正文二";
        Map<String, Object> out = DocStats.compute(
                parsed(md, "pdf", "a.pdf", 2, new ArrayList<Map<String, Object>>(), null), null, null);

        assertEquals("pdf", out.get("format"));
        assertEquals(Boolean.TRUE, out.get("pages_supported"));
        assertEquals(2, out.get("pages"));
        assertEquals("parser", out.get("pages_source"));
        assertTrue(suspectCodes(out).isEmpty(), "两页都对得上，不该凭空报警：" + suspectCodes(out));
    }

    @Test
    void 声明的页数与页标记不符要报存疑() {
        String md = "<!--page:1-->\n正文一\n\n<!--page:2-->\n正文二";
        Map<String, Object> out = DocStats.compute(
                parsed(md, "pdf", "a.pdf", 5, new ArrayList<Map<String, Object>>(), null), null, null);

        assertEquals("warn", suspect(out, "page_count_mismatch").get("level"));
    }

    @Test
    void 既无声明页数也无页标记时页数为null而不是估一个() {
        Map<String, Object> out = DocStats.compute(
                parsed("一段没有任何页标记的正文", "pdf", "a.pdf", 0,
                        new ArrayList<Map<String, Object>>(), null), null, null);

        assertNull(out.get("pages"));
        assertEquals("unknown", out.get("pages_source"));
        assertNotNull(suspect(out, "pages_unknown"));
    }

    @Test
    void docx没有固定分页_页数不适用() {
        Map<String, Object> out = DocStats.compute(
                parsed("# 标题\n\n正文", "docx", "合同.docx", 0,
                        new ArrayList<Map<String, Object>>(), null), null, null);

        assertEquals("docx", out.get("format"));
        assertEquals(Boolean.FALSE, out.get("pages_supported"));
        assertNull(out.get("pages"));
        assertEquals("n/a", out.get("pages_source"));
        assertFalse(suspectCodes(out).contains("pages_unknown"), "非分页格式不该报页数不可知");
    }

    // ---------------------------------------------------------------- 跨页表格

    @Test
    void 表格跨页被切断要报出具体页对() {
        String md = "<!--page:1-->\n开头说明\n\n| 列A | 列B |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |\n\n"
                + "<!--page:2-->\n| 5 | 6 |\n| 7 | 8 |\n\n结尾段落";
        Map<String, Object> out = DocStats.compute(
                parsed(md, "pdf", "a.pdf", 2, new ArrayList<Map<String, Object>>(), null), null, null);

        Map<String, Object> s = suspect(out, "table_cross_page");
        assertNotNull(s, "第 1 页末尾与第 2 页开头都是表格行，应报跨页表格");
        assertEquals("warn", s.get("level"));
        assertEquals(Arrays.asList(1, 2), s.get("pages"));
        assertEquals(1, out.get("table_pipe_blocks"));
    }

    @Test
    void 相邻页各登记一张表时提示可能被拆成两张() {
        List<Map<String, Object>> structures = new ArrayList<>();
        structures.add(structure("table", "page:0", "| a |\n| - |"));
        structures.add(structure("table", "page:1", "| b |\n| - |"));
        Map<String, Object> out = DocStats.compute(
                parsed("<!--page:1-->\n| a |\n| - |\n\n<!--page:2-->\n| b |\n| - |",
                        "pdf", "a.pdf", 2, structures, null), null, null);

        assertNotNull(suspect(out, "table_split_across_pages"));
        assertEquals(2, out.get("table_structures"));
    }

    @Test
    void 表格缺分隔行要报拍平() {
        String md = "| 项目 | 金额 |\n| 差旅 | 1200 |";
        Map<String, Object> out = DocStats.compute(
                parsed(md, "pdf", "a.pdf", 1, new ArrayList<Map<String, Object>>(), null), null, null);

        assertEquals("warn", suspect(out, "table_no_separator").get("level"));
        assertEquals(0, out.get("tables"), "没有分隔行不算一张表");
    }

    // ---------------------------------------------------------------- 图片 / 公式

    @Test
    void 图片引用在产物里找不到要报() {
        String md = "<!--page:1-->\n![](images/pic1.jpg)\n\n正文";
        Map<String, Object> assets = new LinkedHashMap<>();
        assets.put("pic2", "D:/data/images/pic2.jpg");
        Map<String, Object> out = DocStats.compute(
                parsed(md, "pdf", "a.pdf", 1, new ArrayList<Map<String, Object>>(), assets), null, null);

        assertEquals(1, out.get("image_refs"));
        assertEquals(1, out.get("image_assets"));
        assertNotNull(suspect(out, "image_ref_missing"));
    }

    @Test
    void 图片引用能在产物里对上就不报() {
        String md = "<!--page:1-->\n![](images/pic1.jpg)\n\n正文";
        Map<String, Object> assets = new LinkedHashMap<>();
        assets.put("pic1", "D:/data/images/pic1.jpg");
        Map<String, Object> out = DocStats.compute(
                parsed(md, "pdf", "a.pdf", 1, new ArrayList<Map<String, Object>>(), assets), null, null);

        assertNull(suspect(out, "image_ref_missing"));
    }

    @Test
    void 公式按行内与行间分别统计() {
        String md = "行内 $a^2+b^2=c^2$ 结束\n\n$$\n\\frac{1}{2}\n$$\n\n正文";
        Map<String, Object> out = DocStats.compute(
                parsed(md, "pdf", "a.pdf", 1, new ArrayList<Map<String, Object>>(), null), null, null);

        assertEquals(1, out.get("formula_inline"));
        assertEquals(1, out.get("formula_block"));
        assertEquals(2, out.get("formulas"));
    }

    @Test
    void 原件有公式但正文没写出来要报公式未渲染() {
        List<Map<String, Object>> structures = new ArrayList<>();
        structures.add(structure("formula", "docx-formula:1", null));
        structures.add(structure("formula", "docx-formula:2", null));
        Map<String, Object> out = DocStats.compute(
                parsed("正文里一个公式都没有", "docx", "报告.docx", 0, structures, null), null, null);

        assertEquals(2, out.get("formula_structures"));
        assertNotNull(suspect(out, "formula_not_rendered"));
    }

    // ---------------------------------------------------------------- 字数口径

    @Test
    void 正文字数去掉标记空白与表格分隔行() {
        String md = "<!--page:1-->\n# 标题\n\n| 列A | 列B |\n| --- | --- |\n| 甲 | 乙 |\n\n![图](images/x.jpg)";
        int plain = DocStats.plainChars(md);
        // 标题 2 字 + 表头 4 字（列A/列B）+ 表体 2 字（甲/乙）；页标记/图片/分隔行/空白都不算
        assertEquals(8, plain);
    }
}
