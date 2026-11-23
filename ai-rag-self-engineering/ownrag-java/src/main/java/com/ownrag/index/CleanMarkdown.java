package com.ownrag.index;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Markdown 清洗（"解析后文档 → 清洗后文档"之间的那一层，纯函数、幂等、可复算）。
 *
 * 定位：解析器产出的是"还原页面的 Markdown"（带页标记、页码行、NBSP、零宽字符、成片的空行），
 * 切分与嵌入要的是"可被检索的正文"。清洗只做**不改变语义**的归一化，且每一条规则都计数，
 * 复核页把 parsed.md / cleaned.md 与统计并排摆出来——"这条内容为什么没了"必须能当场回答。
 *
 * 刻意**不做**的事（都属于会丢信息、必须人工判断的清洗）：
 *   - 不删重复的页眉页脚行（识别不可靠，误删等于丢正文）
 *   - 不合并断行、不重排段落、不改标点、不做繁简/全半角转换
 *   - 不动代码围栏内的任何内容（页码行规则在 ``` 内一律不生效）
 *
 * 口径约束：切分侧（ChunkMarkdownStep）与复核工件（PrepareReviewStep）都调用本函数，
 * 两边参数不同则"看到的清洗后文档 ≠ 实际入库的正文"，所以参数统一由 clean_markdown 步骤
 * 归一化后写进黑板（ctx.data.clean_options），下游只读不猜。
 *
 * 清洗后的全文**不进黑板**（tasks.state_json 已经是全表最大列）：下游用同一纯函数现算即可。
 */
public final class CleanMarkdown {

    /** 页标记（ParsePdfbox 产出的 {@code <!--page:N-->}）：drop（默认）| keep。 */
    public static final String OPT_PAGE_MARKERS = "page_markers";
    /** 独立成行的页码（"12" / "- 12 -" / "第 3 页 / 共 20 页" / "Page 3 of 20"）：true（默认）| false。 */
    public static final String OPT_PAGE_NUMBERS = "page_numbers";
    /** 其余 HTML 注释：true（默认，删）| false。 */
    public static final String OPT_COMMENTS = "comments";
    /** 连续空行折叠成一个空行：true（默认）| false。 */
    public static final String OPT_BLANK_LINES = "blank_lines";

    private static final Pattern CRLF = Pattern.compile("\r\n|\r");
    private static final Pattern PAGE_MARK = Pattern.compile("<!--\\s*page:\\s*(\\d+)\\s*-->");
    /** 其余注释：明确排除页标记（否则 page_markers=keep 会被这一步悄悄删掉，两处计数还对不上）。 */
    private static final Pattern COMMENT = Pattern.compile("<!--(?!\\s*page:\\s*\\d+\\s*-->)[\\s\\S]*?-->");
    private static final Pattern TRAILING_WS = Pattern.compile("[ \\t]+$", Pattern.MULTILINE);
    private static final Pattern BLANK_RUN = Pattern.compile("\n{3,}");
    private static final Pattern CONTROL = Pattern.compile("[\\u0000-\\u0008\\u000B\\u000C\\u000E-\\u001F\\u007F]");
    private static final Pattern ZERO_WIDTH = Pattern.compile("[\\u200B-\\u200D\\uFEFF]");
    /** 页码行：整行只有页码/页脚页码，不含任何正文（含代码围栏内的行不参与判断）。 */
    private static final Pattern PAGE_NUMBER_LINE = Pattern.compile(
            "^\\s*(?:[-–—]\\s*)?(?:"
                    + "第\\s*\\d{1,4}\\s*页(?:\\s*[/／]\\s*共\\s*\\d{1,4}\\s*页)?"
                    + "|page\\s*\\d{1,4}(?:\\s*(?:of|/)\\s*\\d{1,4})?"
                    + "|\\d{1,4}(?:\\s*[-–—])?"
                    + ")\\s*$",
            Pattern.CASE_INSENSITIVE);

    private CleanMarkdown() {
    }

    /** 清洗结果：markdown = 切分/入库用的正文；stats = 每条规则的命中计数（写 report.json 与 trace）。 */
    public static final class Result {
        public final String markdown;
        public final Map<String, Object> stats;

        Result(String markdown, Map<String, Object> stats) {
            this.markdown = markdown;
            this.stats = stats;
        }
    }

    public static Result apply(String markdown) {
        return apply(markdown, null);
    }

    /**
     * 执行清洗。options 缺省即默认口径；未知键忽略（管道参数里常混着别的键）。
     */
    public static Result apply(String markdown, Map<String, Object> options) {
        Map<String, Object> opts = options(options);
        String text = markdown == null ? "" : markdown;
        int charsIn = text.length();

        Map<String, Object> stats = new LinkedHashMap<>();
        stats.put("options", opts);

        // ① 换行统一：CRLF / 孤立 CR → LF（否则行尾判据与空行折叠全部失效）
        int crlf = 0;
        if (text.indexOf('\r') >= 0) {
            Matcher m = CRLF.matcher(text);
            while (m.find()) {
                crlf++;
            }
            text = CRLF.matcher(text).replaceAll("\n");
        }
        stats.put("crlf", crlf);

        // ② 不可见字符：NBSP 变普通空格（NBSP 会让关键词两侧粘连）、零宽字符与 BOM 直接删
        int nbsp = count(text, "\u00A0");
        if (nbsp > 0) {
            text = text.replace('\u00A0', ' ');
        }
        Matcher zw = ZERO_WIDTH.matcher(text);
        int zeroWidth = 0;
        while (zw.find()) {
            zeroWidth++;
        }
        if (zeroWidth > 0) {
            text = ZERO_WIDTH.matcher(text).replaceAll("");
        }
        Matcher ctl = CONTROL.matcher(text);
        int control = 0;
        while (ctl.find()) {
            control++;
        }
        if (control > 0) {
            text = CONTROL.matcher(text).replaceAll("");
        }
        stats.put("nbsp", nbsp);
        stats.put("zero_width", zeroWidth);
        stats.put("control", control);

        // ③ 页标记：换成换行而不是空串（避免 "结论<!--page:2-->下一步" 粘成一词）
        int pageMarks = 0;
        Matcher pm = PAGE_MARK.matcher(text);
        while (pm.find()) {
            pageMarks++;
        }
        if (pageMarks > 0) {
            text = "keep".equals(opts.get(OPT_PAGE_MARKERS))
                    ? text : PAGE_MARK.matcher(text).replaceAll("\n");
        }
        stats.put("page_markers", pageMarks);

        // ④ 其余 HTML 注释
        int comments = 0;
        if (Boolean.TRUE.equals(opts.get(OPT_COMMENTS))) {
            Matcher cm = COMMENT.matcher(text);
            while (cm.find()) {
                comments++;
            }
            if (comments > 0) {
                text = COMMENT.matcher(text).replaceAll("");
            }
        }
        stats.put("comments", comments);

        // ⑤ 页码行（页脚 "12" / "第 3 页 共 20 页"）：只在代码围栏外生效
        int pageNumbers = 0;
        if (Boolean.TRUE.equals(opts.get(OPT_PAGE_NUMBERS))) {
            String[] lines = text.split("\n", -1);
            StringBuilder kept = new StringBuilder(text.length());
            boolean inFence = false;
            for (int i = 0; i < lines.length; i++) {
                String line = lines[i];
                if (line.trim().startsWith("```")) {
                    inFence = !inFence;
                }
                if (!inFence && PAGE_NUMBER_LINE.matcher(line).matches()) {
                    pageNumbers++;
                    continue;
                }
                kept.append(line);
                if (i < lines.length - 1) {
                    kept.append('\n');
                }
            }
            if (pageNumbers > 0) {
                text = kept.toString();
            }
        }
        stats.put("page_numbers", pageNumbers);

        // ⑥ 行尾空白（行尾空格在 Markdown 里是硬换行语义，但它同时污染嵌入与 FTS 切词；
        //    本项目列表/段落不依赖硬换行，统一去掉）
        Matcher tw = TRAILING_WS.matcher(text);
        int trailing = 0;
        while (tw.find()) {
            trailing++;
        }
        if (trailing > 0) {
            text = TRAILING_WS.matcher(text).replaceAll("");
        }
        stats.put("trailing_ws", trailing);

        // ⑦ 连续空行折叠（3 行以上 → 1 个空行）
        int blankCollapsed = 0;
        if (Boolean.TRUE.equals(opts.get(OPT_BLANK_LINES))) {
            Matcher bm = BLANK_RUN.matcher(text);
            while (bm.find()) {
                blankCollapsed++;
            }
            if (blankCollapsed > 0) {
                text = BLANK_RUN.matcher(text).replaceAll("\n\n");
            }
        }
        stats.put("blank_lines", blankCollapsed);

        text = text.trim();

        // ⑧ 兜底：清洗把正文洗空了（极端参数或"整篇都是页码"）→ 回退未清洗正文，绝不静默交空给人
        boolean fallback = false;
        if (text.isEmpty() && !(markdown == null ? "" : markdown).trim().isEmpty()) {
            text = markdown.trim();
            fallback = true;
            stats.put("fallback", "清洗后正文为空，已回退为未清洗正文（请检查 clean_markdown 参数）");
        }

        int charsOut = text.length();
        stats.put("chars_in", charsIn);
        stats.put("chars_out", charsOut);
        stats.put("removed_chars", charsIn - charsOut);
        stats.put("removed_ratio", charsIn == 0 ? 0.0 : round4((double) (charsIn - charsOut) / charsIn));
        stats.put("fallback_applied", fallback);
        return new Result(text, stats);
    }

    /** 参数归一化：只保留 4 个受支持的键，并补默认值（下游读 clean_options 时口径唯一）。 */
    public static Map<String, Object> options(Map<String, Object> params) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put(OPT_PAGE_MARKERS, "keep".equals(str(params, OPT_PAGE_MARKERS)) ? "keep" : "drop");
        out.put(OPT_PAGE_NUMBERS, bool(params, OPT_PAGE_NUMBERS, true));
        out.put(OPT_COMMENTS, bool(params, OPT_COMMENTS, true));
        out.put(OPT_BLANK_LINES, bool(params, OPT_BLANK_LINES, true));
        return out;
    }

    private static Object str(Map<String, Object> m, String key) {
        Object v = m == null ? null : m.get(key);
        return v == null ? null : String.valueOf(v);
    }

    private static boolean bool(Map<String, Object> m, String key, boolean def) {
        Object v = m == null ? null : m.get(key);
        if (v == null) {
            return def;
        }
        if (v instanceof Boolean) {
            return (Boolean) v;
        }
        String s = String.valueOf(v).trim().toLowerCase();
        if ("true".equals(s) || "1".equals(s) || "yes".equals(s) || "on".equals(s)) {
            return true;
        }
        if ("false".equals(s) || "0".equals(s) || "no".equals(s) || "off".equals(s)) {
            return false;
        }
        return def;
    }

    private static int count(String text, String needle) {
        int n = 0;
        int i = text.indexOf(needle);
        while (i >= 0) {
            n++;
            i = text.indexOf(needle, i + needle.length());
        }
        return n;
    }

    private static double round4(double v) {
        return Math.round(v * 10000.0) / 10000.0;
    }
}
