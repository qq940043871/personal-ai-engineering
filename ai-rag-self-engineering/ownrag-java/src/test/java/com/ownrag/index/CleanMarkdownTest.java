package com.ownrag.index;

import java.sql.Connection;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import com.ownrag.core.StepContext;
import com.ownrag.core.StepResult;
import com.ownrag.ingest.ParsedDoc;
import com.ownrag.retrieve.RetrieveTest;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 清洗回归：复核页「解析后 / 清洗后」两栏之所以可信，是因为清洗是纯函数、幂等、逐条计数，
 * 且切分用的就是同一个函数 + 同一组参数。这里锁三件事：
 *   1. 只做不改语义的归一化（页标记 / 页码行 / 不可见字符 / 空白），代码围栏内一律不动；
 *   2. 极端情况下不把正文洗没（回退保护）；
 *   3. chunk_markdown 的输入确实是清洗后正文（页标记不再漏进块）。
 */
class CleanMarkdownTest {

    private static Map<String, Object> opt(Object... kv) {
        Map<String, Object> m = new LinkedHashMap<>();
        for (int i = 0; i + 1 < kv.length; i += 2) {
            m.put(String.valueOf(kv[i]), kv[i + 1]);
        }
        return m;
    }

    @Test
    void 页标记与换行统一_且幂等() {
        String raw = "# 差旅政策\r\n<!-- page:1 -->\r\n正文第一段。\r\n<!--page:2-->\r\n报销标准见附表。";
        CleanMarkdown.Result r = CleanMarkdown.apply(raw);
        assertFalse(r.markdown.contains("<!--"), "页标记必须清掉：" + r.markdown);
        assertFalse(r.markdown.contains("\r"), "CRLF 必须归一");
        assertEquals(2, r.stats.get("page_markers"));
        assertEquals(4, r.stats.get("crlf"));
        assertTrue(r.markdown.contains("正文第一段。"));
        // 幂等：再洗一次结果不变（切分侧与工件侧各算一次，必须收敛到同一份正文）
        assertEquals(r.markdown, CleanMarkdown.apply(r.markdown).markdown);
    }

    @Test
    void 页码行删除_代码围栏内不删() {
        String raw = "第一段\n12\n- 12 -\n第 3 页 / 共 20 页\nPage 4 of 20\n"
                + "```text\n12\n42\n```\n结尾段。";
        CleanMarkdown.Result r = CleanMarkdown.apply(raw);
        assertEquals(4, r.stats.get("page_numbers"));
        assertTrue(r.markdown.contains("```text\n12\n42\n```"), "代码围栏内必须原样保留：" + r.markdown);
        assertTrue(r.markdown.contains("第一段") && r.markdown.contains("结尾段。"));
        // 正文里带数字但不止数字的行不能被当页码删掉
        CleanMarkdown.Result keep = CleanMarkdown.apply("2026 年营业额 1200 万", opt("page_numbers", true));
        assertTrue(keep.markdown.contains("1200 万"));
        assertEquals(0, keep.stats.get("page_numbers"));
    }

    @Test
    void 不可见字符与行尾空白() {
        String raw = "报\u00A0销\u200B流程  \n第二行\t\t\n\uFEFF开头";
        CleanMarkdown.Result r = CleanMarkdown.apply(raw);
        assertTrue(r.markdown.contains("报 销流程"), "NBSP → 空格、零宽字符删除：" + r.markdown);
        assertEquals(1, r.stats.get("nbsp"));
        assertEquals(2, r.stats.get("zero_width"));   // \u200B + \uFEFF
        assertEquals(2, r.stats.get("trailing_ws"));
        for (String line : r.markdown.split("\n")) {
            assertEquals(line.trim(), line.replaceAll("[ \\t]+$", ""), "行尾空白已清：" + line);
        }
    }

    @Test
    void 空行折叠与首尾裁剪() {
        String raw = "\n\n\n第一段\n\n\n\n第二段\n\n\n";
        CleanMarkdown.Result r = CleanMarkdown.apply(raw);
        assertEquals("第一段\n\n第二段", r.markdown);
        assertTrue(((Number) r.stats.get("blank_lines")).intValue() >= 1, "必须记录折叠了几处空行块");
        // 关掉折叠时保持原样（供"想看解析原貌"的场景）
        CleanMarkdown.Result keep = CleanMarkdown.apply(raw, opt("blank_lines", false));
        assertTrue(keep.markdown.contains("\n\n\n"));
    }

    @Test
    void 页标记可选保留() {
        String raw = "上<!--page:7-->下";
        CleanMarkdown.Result r = CleanMarkdown.apply(raw, opt("page_markers", "keep"));
        assertTrue(r.markdown.contains("<!--page:7-->"));
        assertEquals(1, r.stats.get("page_markers"));
    }

    @Test
    void 洗空了要回退_绝不静默交空() {
        String raw = "12\n13\n14";
        CleanMarkdown.Result r = CleanMarkdown.apply(raw, opt("page_numbers", true));
        assertFalse(r.markdown.isEmpty(), "全页码正文必须回退为原文");
        assertEquals(Boolean.TRUE, r.stats.get("fallback_applied"));
        assertTrue(String.valueOf(r.stats.get("fallback")).contains("回退"));
    }

    @Test
    void 空输入与统计口径() {
        CleanMarkdown.Result r = CleanMarkdown.apply(null);
        assertEquals("", r.markdown);
        assertEquals(0, r.stats.get("chars_in"));
        assertEquals(0.0, r.stats.get("removed_ratio"));
    }

    @Test
    void 参数归一化_未知键忽略() {
        Map<String, Object> o = CleanMarkdown.options(opt("page_numbers", "no", "whatever", 1));
        assertEquals("drop", o.get(CleanMarkdown.OPT_PAGE_MARKERS));
        assertEquals(Boolean.FALSE, o.get(CleanMarkdown.OPT_PAGE_NUMBERS));
        assertEquals(Boolean.TRUE, o.get(CleanMarkdown.OPT_COMMENTS));
        assertEquals(4, o.size(), "只保留受支持的 4 个键");
    }

    @Test
    void 步骤只写统计不写全文_切分输入是清洗后正文() throws Exception {
        java.nio.file.Path tmp = java.nio.file.Files.createTempDirectory("clean-step");
        com.ownrag.config.Settings settings = new RetrieveTest.SettingsBuilder().dataDir(tmp).build();
        com.ownrag.core.Db.initSchema(settings.getDbPath());
        try (Connection conn = com.ownrag.core.Db.connect(settings.getDbPath())) {
            StepContext ctx = new StepContext("docClean", "t1", "kb1", conn, settings);
            Map<String, Object> parsed = new ParsedDoc("docClean", "pdf",
                    "# 标题\n<!--page:1-->\n正文内容足够长，用于验证清洗后进入切分。\n\n\n\n12",
                    new LinkedHashMap<>(), new ArrayList<>(), new LinkedHashMap<>(), new LinkedHashMap<>())
                    .toMap();
            ctx.data.put("parsed", parsed);

            StepResult clean = new CleanMarkdownStep().run(ctx, opt("page_numbers", true));
            assertTrue(clean.ok, "clean_markdown 必须成功：" + clean.error);
            assertFalse(ctx.data.containsKey("clean_markdown") || ctx.data.containsKey("cleaned"),
                    "清洗后全文不进黑板（state_json 不能翻倍）");
            assertTrue(ctx.data.containsKey("clean_options"), "参数归一化结果必须留给下游");
            Map<String, Object> stats = (Map<String, Object>) ctx.data.get("clean");
            assertEquals(Boolean.FALSE, stats.get("fallback_applied"));

            StepResult chunk = new ChunkMarkdownStep().run(ctx, opt("max_tokens", 512, "overlap", 0));
            assertTrue(chunk.ok, "chunk_markdown 必须成功：" + chunk.error);
            List<Map<String, Object>> chunks = (List<Map<String, Object>>) ctx.data.get("chunks");
            StringBuilder all = new StringBuilder();
            for (Map<String, Object> c : chunks) {
                all.append(c.get("text"));
            }
            assertFalse(all.toString().contains("<!--page:"), "页标记不得漏进块：" + all);
            assertTrue(all.toString().contains("正文内容足够长"));
            assertEquals(((Number) stats.get("chars_out")).intValue(),
                    ((Number) chunk.metrics.get("clean_chars")).intValue(),
                    "切分侧看到的字符数必须等于清洗统计（同一函数、同一参数）");
        }
    }
}
