package com.ownrag.index;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** 结构感知切分回归（对齐 Python 版 chunker.py 语义）。 */
class ChunkerTest {

    private static Map<String, Object> meta() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("source_file", "测试文档.pdf");
        return m;
    }

    @Test
    void est_tokens_CJK口径() {
        assertEquals(0, EstTokens.est(""));
        assertEquals(4, EstTokens.est("四个汉字"));          // 4 CJK = 4
        assertEquals(2, EstTokens.est("abcdefgh"));          // 8 ascii / 4 = 2
        assertEquals(5, EstTokens.est("两个汉字abcdefg"));   // 4 + 7/4 = 4+1 = 5
    }

    @Test
    void splitSegments_标题路径与表格整段收集() {
        String md = "# 一级\n\n段落一。\n\n## 二级\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n后续段落。";
        List<Map<String, Object>> segs = Chunker.splitSegments(md);
        List<String> kinds = new ArrayList<>();
        for (Map<String, Object> s : segs) {
            kinds.add(String.valueOf(s.get("kind")));
        }
        // heading(一级) / paragraph(段落一) / heading(二级) / table(整段收集) / paragraph(后续)
        assertEquals(java.util.Arrays.asList("heading", "paragraph", "heading", "table", "paragraph"), kinds);
        // 二级标题后的段落 heading_path = [一级, 二级]
        Map<String, Object> tableSeg = segs.get(3);
        assertEquals(java.util.Arrays.asList("一级", "二级"), tableSeg.get("heading_path"));
    }

    @Test
    void chunk_markdown_块头注入与chunk_id格式() {
        String md = "# 章节\n\n" + rep("甲", 60) + "\n\n" + rep("乙", 60);
        List<Map<String, Object>> chunks = Chunker.chunkMarkdown(md, "doc1", "kb1", "pdf", meta(), 100, 0);
        assertEquals(2, chunks.size());
        assertEquals("doc1#0001", chunks.get(0).get("chunk_id"));
        assertEquals("doc1#0002", chunks.get(1).get("chunk_id"));
        assertTrue(String.valueOf(chunks.get(0).get("text")).startsWith("【测试文档.pdf > 章节】"),
                "块首必须注入 文档标题 > 章节路径 短头");
        assertEquals("章节", ((List<?>) ((Map<?, ?>) chunks.get(0).get("anchors")).get("heading_path")).get(0));
    }

    @Test
    void chunk_markdown_表格永不跨块() {
        String table = "| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |";
        String md = "段落前置。\n\n" + table + "\n\n" + "段落后置。";
        List<Map<String, Object>> chunks = Chunker.chunkMarkdown(md, "d", "kb", "pdf", meta(), 512, 64);
        boolean tableInOne = false;
        for (Map<String, Object> c : chunks) {
            String text = String.valueOf(c.get("text"));
            if (text.contains("| 1 | 2 |")) {
                tableInOne = text.contains("| 3 | 4 |");
                assertTrue((Boolean) ((Map<?, ?>) c.get("meta")).get("has_table"));
            }
        }
        assertTrue(tableInOne, "表格必须完整落在单个块内");
    }

    @Test
    void chunk_markdown_重叠整段携带且不跨表格() {
        // 结构：段落A → 标题二 → 段落B（连续段落行会合并成一个段，分段边界 = 标题/表格/围栏）。
        // maxTokens=12（est("a"*50)=12）：段落A 后跟标题时跨预算边界，A 作为"上一块最后的段落段"整段带入块2。
        String a = rep("a", 50);
        String md = a + "\n\n# 标题二\n\n" + rep("b", 50);
        List<Map<String, Object>> chunks = Chunker.chunkMarkdown(md, "d", "kb", "pdf", meta(), 12, 64);
        assertTrue(chunks.size() >= 2, "应切出多块，实际 " + chunks.size());
        assertTrue(String.valueOf(chunks.get(0).get("text")).contains(a), "块1 = 段落A");
        String second = String.valueOf(chunks.get(1).get("text"));
        assertTrue(second.contains(a), "重叠 = 整段携带上一块最后一段");
        assertTrue(second.contains("标题二"));
        // 表格独立成块且不携带前段重叠
        String table = "| x |\n|---|\n| 1 |";
        String md2 = "段落甲" + rep("甲", 40) + "\n\n" + table + "\n\n" + "段落乙" + rep("乙", 40);
        List<Map<String, Object>> chunks2 = Chunker.chunkMarkdown(md2, "d", "kb", "pdf", meta(), 80, 64);
        for (int i = 1; i < chunks2.size(); i++) {
            if (String.valueOf(chunks2.get(i).get("text")).contains("| 1 |")) {
                assertFalse(String.valueOf(chunks2.get(i).get("text")).contains("段落甲"),
                        "表格块（独立成块）不应携带前段重叠");
            }
        }
    }

    @Test
    void av块_时间锚进anchors() {
        String md = "#### [00:10]（源视频锚点）\n\n[00:10] 第一句\n[00:25] 第二句";
        Map<String, Object> meta = new LinkedHashMap<>();
        meta.put("source_file", "demo.mp4");
        List<Map<String, Object>> chunks = Chunker.chunkMarkdown(md, "d", "kb", "av", meta, 512, 64);
        Map<?, ?> anchors = (Map<?, ?>) chunks.get(0).get("anchors");
        assertEquals("00:10-00:25", anchors.get("t"));
    }

    /** JDK8 无 String.repeat：测试用小工具。 */
    private static String rep(String s, int n) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < n; i++) {
            sb.append(s);
        }
        return sb.toString();
    }
}
