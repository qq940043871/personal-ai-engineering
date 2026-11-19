package com.ownrag.ingest;

import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import org.apache.poi.xwpf.usermodel.IBodyElement;
import org.apache.poi.xwpf.usermodel.XWPFDocument;
import org.apache.poi.xwpf.usermodel.XWPFParagraph;
import org.apache.poi.xwpf.usermodel.XWPFTable;
import org.apache.poi.xwpf.usermodel.XWPFTableCell;
import org.apache.poi.xwpf.usermodel.XWPFTableRow;
import org.springframework.stereotype.Component;

import com.ownrag.core.Step;
import com.ownrag.core.StepContext;
import com.ownrag.core.StepResult;

/**
 * docx 直传（Python 版无此链路，Java 版为个人知识库场景新增）：
 * POI XWPF 按文档体顺序遍历，段落 → Markdown（标题样式→#，编号段落→列表项），
 * 表格 → Markdown 管道表（永不跨块的前提是表格整体保留）。
 * 降级显式可见：加粗/斜体/颜色/图片不保留，图片计数进 stats；.doc 老格式不支持。
 */
@Component
public class ParseDocx implements Step {

    /** 英文 Word 样式 Heading1-6；中文 Word 样式 id 常见为 "1"-"6"（样式名"标题 N"）。 */
    private static final Pattern HEADING_STYLE = Pattern.compile("(?i)^heading([1-6])$");

    @Override
    public String type() {
        return "parse_docx";
    }

    @Override
    public StepResult run(StepContext ctx, Map<String, Object> params) {
        Path src = Paths.get(String.valueOf(ctx.data.get("source_path")));
        int maxTableRows = params.get("max_table_rows") instanceof Number
                ? ((Number) params.get("max_table_rows")).intValue() : 500;

        StringBuilder md = new StringBuilder();
        List<Map<String, Object>> structures = new ArrayList<>();
        int paragraphs = 0;
        int tables = 0;
        int images = 0;
        try (InputStream in = Files.newInputStream(src); XWPFDocument doc = new XWPFDocument(in)) {
            for (IBodyElement el : doc.getBodyElements()) {
                if (el instanceof XWPFParagraph) {
                    XWPFParagraph p = (XWPFParagraph) el;
                    images += countPictures(p);
                    String text = p.getText();
                    if (text == null || text.trim().isEmpty()) {
                        continue;
                    }
                    md.append(markdownOf(p, text.trim())).append("\n\n");
                    paragraphs++;
                } else if (el instanceof XWPFTable) {
                    XWPFTable t = (XWPFTable) el;
                    tables++;
                    md.append(tableToMarkdown(t, maxTableRows)).append("\n\n");
                    structures.add(ParsedDoc.structure("table", "docx-table:" + tables,
                            "rows=" + t.getRows().size(), preview(t)));
                }
            }
        } catch (Exception e) {
            String msg = e.getClass().getSimpleName() + ": " + e.getMessage();
            if (String.valueOf(src.getFileName()).toLowerCase().endsWith(".doc")) {
                msg += "（.doc 老格式不支持，请先另存为 .docx）";
            }
            return StepResult.fail("docx 解析失败：" + msg);
        }
        String out = md.toString();

        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put("source_file", src.getFileName().toString());
        metadata.put("size_bytes", sizeOf(src));
        metadata.put("format", "docx");
        metadata.put("degraded", "docx 段落级提取：加粗/斜体/颜色/脚注不保留，图片不索引");
        Object sourceMeta = ctx.data.get("source_meta");
        if (sourceMeta instanceof Map) {
            @SuppressWarnings("unchecked")
            Map<String, Object> sm = (Map<String, Object>) sourceMeta;
            metadata.putAll(sm);
        }
        metadata.put("size_bytes", sizeOf(src));  // 以磁盘为准

        Map<String, Object> stats = new LinkedHashMap<>();
        stats.put("paragraphs", paragraphs);
        stats.put("tables", tables);
        stats.put("images_skipped", images);
        stats.put("backend", "poi-xwpf");

        ParsedDoc parsed = new ParsedDoc(ctx.docId, "docx", out, metadata, structures,
                new LinkedHashMap<>(), stats);
        String[] usable = parsed.isUsable(20);
        if (usable[0] == null) {
            return StepResult.fail("产出不可用：" + usable[1]);
        }
        ctx.data.put("parsed", parsed.toMap());
        return StepResult.okMetrics("paragraphs", paragraphs, "tables", tables, "images_skipped", images);
    }

    /** 段落 → Markdown 行：标题样式转 #，编号段落转列表项，其余原样。 */
    private static String markdownOf(XWPFParagraph p, String text) {
        int level = headingLevel(p);
        if (level > 0) {
            StringBuilder h = new StringBuilder();
            for (int i = 0; i < level; i++) {
                h.append('#');
            }
            return h.append(' ').append(text).toString();
        }
        if (p.getNumID() != null) {
            return "- " + text;
        }
        return text;
    }

    private static int headingLevel(XWPFParagraph p) {
        String style = p.getStyle();
        if (style == null || style.isEmpty()) {
            return 0;
        }
        Matcher m = HEADING_STYLE.matcher(style);
        if (m.matches()) {
            return Integer.parseInt(m.group(1));
        }
        // 中文 Word：样式 id "1"-"6"（样式名"标题 N"）
        return style.matches("^[1-6]$") ? Integer.parseInt(style) : 0;
    }

    private static int countPictures(XWPFParagraph p) {
        int n = 0;
        if (p.getRuns() == null) {
            return 0;
        }
        for (org.apache.poi.xwpf.usermodel.XWPFRun r : p.getRuns()) {
            if (r.getEmbeddedPictures() != null) {
                n += r.getEmbeddedPictures().size();
            }
        }
        return n;
    }

    /** 表格 → Markdown 管道表：首行当表头；超 max_table_rows 截断并留痕（表格不硬切）。 */
    static String tableToMarkdown(XWPFTable t, int maxTableRows) {
        List<XWPFTableRow> rows = t.getRows();
        int cols = 1;
        for (XWPFTableRow r : rows) {
            cols = Math.max(cols, r.getTableCells().size());
        }
        StringBuilder sb = new StringBuilder();
        int limit = Math.min(rows.size(), maxTableRows);
        for (int i = 0; i < limit; i++) {
            sb.append(rowLine(rows.get(i), cols));
            sb.append('\n');
            if (i == 0) {
                sb.append('|');
                for (int c = 0; c < cols; c++) {
                    sb.append(" --- |");
                }
                sb.append('\n');
            }
        }
        if (rows.size() > limit) {
            sb.append('|');
            for (int c = 0; c < cols; c++) {
                sb.append(c == 0 ? " …（截断，共 " + rows.size() + " 行） |" : " |");
            }
            sb.append('\n');
        }
        return sb.toString();
    }

    private static String rowLine(XWPFTableRow row, int cols) {
        StringBuilder sb = new StringBuilder("|");
        List<XWPFTableCell> cells = row.getTableCells();
        for (int c = 0; c < cols; c++) {
            String cell = c < cells.size() ? cells.get(c).getText() : "";
            cell = cell == null ? "" : cell.replace('|', '\\').replace("\r\n", " ").replace('\n', ' ').trim();
            sb.append(' ').append(cell).append(" |");
        }
        return sb.toString();
    }

    private static String preview(XWPFTable t) {
        if (t.getRows().isEmpty() || t.getRow(0).getTableCells().isEmpty()) {
            return "";
        }
        String head = t.getRow(0).getTableCells().get(0).getText();
        return head == null ? "" : head.trim();
    }

    private static long sizeOf(Path src) {
        try {
            return Files.size(src);
        } catch (Exception e) {
            return 0;
        }
    }
}
