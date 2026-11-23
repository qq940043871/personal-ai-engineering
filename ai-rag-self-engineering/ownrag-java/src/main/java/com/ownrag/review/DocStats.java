package com.ownrag.review;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 文档统计 + 存疑清单（解析复核页顶部"这份文档到底是什么样"的那张表）。
 *
 * <p>回答四个可数事实：多少页 / 多少文字 / 多少图片 / 多少公式 / 多少表格，
 * 以及**哪些地方不能信**：跨页表格、被拆成两张表的跨页表、公式被拍平成文本、
 * 图片引用指向不存在的产物、页标记缺失导致页级判断不可用……
 *
 * <p>三条口径约束（刻意如此，不是没做）：
 * <ol>
 *   <li><b>只统计能核对的东西</b>：页数优先取解析器声明，其次数正文里的 {@code <!--page:N-->}，
 *       两者都没有就返回 null 并写 {@code pages_source=n/a|unknown}——不拿字符数估页数。</li>
 *   <li><b>格式决定"页"是否有意义</b>：PDF 有固定分页；docx/xlsx/md/txt/av 没有，
 *       {@code pages_supported=false}，不硬编一个页数出来。</li>
 *   <li><b>存疑是启发式，level 写明强度</b>：{@code warn}=大概率要人看一眼，
 *       {@code info}=只是"这里判不了/不建议依赖"。存疑项不参与 verdict，不阻断放行。</li>
 * </ol>
 */
public final class DocStats {

    /** 有固定分页概念的格式：只有这类格式里"多少页"是硬事实。 */
    private static final List<String> PAGED = Arrays.asList("pdf");
    private static final Pattern PAGE_MARK = Pattern.compile("<!--\\s*page:(\\d+)\\s*-->");
    private static final Pattern PAGE_LOC = Pattern.compile("page:(\\d+)");
    private static final Pattern IMG_REF = Pattern.compile("!\\[[^\\]]*\\]\\s*\\(\\s*<?([^)\\s>]+)>?[^)]*\\)");
    private static final Pattern HTML_COMMENT = Pattern.compile("(?s)<!--.*?-->");
    private static final Pattern HEADING_MARK = Pattern.compile("(?m)^\\s*#{1,6}\\s+");
    private static final Pattern TABLE_ROW = Pattern.compile("^\\s*\\|.*\\|\\s*$");
    private static final Pattern BLOCK_FORMULA = Pattern.compile("\\$\\$[\\s\\S]{1,4000}?\\$\\$");
    private static final Pattern INLINE_FORMULA = Pattern.compile("(?<!\\$)\\$(?!\\$)(?=\\S)[^$\\n]{1,200}?(?<=\\S)\\$(?!\\$)");
    private static final Pattern TEX_BRACKET = Pattern.compile("\\\\\\[[\\s\\S]{1,4000}?\\\\\\]");
    private static final Pattern TEX_PAREN = Pattern.compile("\\\\\\([\\s\\S]{1,1000}?\\\\\\)");
    /** 正文里出现这些 LaTeX 命令，说明"这里本该是公式"，用来抓"公式被拍成纯文本"。 */
    private static final Pattern LATEX_HINT = Pattern.compile(
            "\\\\(frac|sqrt|sum|prod|int|alpha|beta|gamma|delta|theta|lambda|mu|sigma|omega|pi|"
                    + "times|cdot|div|le|ge|leq|geq|neq|approx|infty|partial|nabla|begin|end)"
                    + "|\\^\\{|_\\{");
    private static final Pattern MD_MARKUP = Pattern.compile("[*_`>~\\[\\]()#|]+");

    private DocStats() {
    }

    /**
     * 统计一份解析产物。三个入参都来自黑板：{@code parsed}（解析中间态）、
     * {@code chunks}（切分结果，只取块数）、{@code clean}（清洗统计，可空）。
     */
    public static Map<String, Object> compute(Map<String, Object> parsed,
                                              List<Map<String, Object>> chunks,
                                              Map<String, Object> clean) {
        Map<String, Object> p = parsed == null ? new LinkedHashMap<String, Object>() : parsed;
        String markdown = str(p.get("markdown"));
        Map<String, Object> metadata = asMap(p.get("metadata"));
        Map<String, Object> statsIn = asMap(p.get("stats"));
        List<Map<String, Object>> structures = asList(p.get("structures"));
        Map<String, Object> assets = asMap(p.get("assets"));

        String format = formatOf(metadata, p, statsIn);
        boolean paged = PAGED.contains(format);

        // ---- 页数：解析器声明 > 页标记 > 未知；非分页格式一律不可得
        List<int[]> marks = pageMarks(markdown);
        int declaredPages = num(statsIn.get("pages"));
        Integer pages = null;
        String pagesSource = "n/a";
        if (paged) {
            if (declaredPages > 0) {
                pages = declaredPages;
                pagesSource = "parser";
            } else if (!marks.isEmpty()) {
                pages = marks.size();
                pagesSource = "page_markers";
            } else {
                pagesSource = "unknown";
            }
        }

        int chars = markdown.length();
        int textChars = plainChars(markdown);

        // ---- 图片：正文引用 / structures / 落盘产物三处交叉核对
        List<String> imageRefs = imageRefs(markdown);
        int imageStructs = countKind(structures, "image") + countKind(structures, "keyframe");
        int images = Math.max(imageRefs.size(), imageStructs);

        // ---- 公式：结构化清单 / Markdown 公式语法 取大者
        int formulaStructs = countKind(structures, "formula") + countKind(structures, "equation");
        int formulaBlock = count(BLOCK_FORMULA, markdown);
        int formulaInline = count(INLINE_FORMULA, markdown);
        int formulaTex = count(TEX_BRACKET, markdown) + count(TEX_PAREN, markdown);
        int formulaMd = formulaBlock + formulaInline + formulaTex;
        int formulas = Math.max(formulaStructs, formulaMd);

        // ---- 表格：管道表块（必须带分隔行才算表）/ structures 取大者
        TableScan scan = scanTables(markdown);
        int tableStructs = countKind(structures, "table");
        int tables = Math.max(scan.blocks, tableStructs);

        List<Map<String, Object>> suspects = new ArrayList<>();
        List<String> notes = new ArrayList<>();
        notes.add("字数口径：chars=解析产物 Markdown 字符数（含标记）；text_chars=去掉标记与空白后的正文；"
                + "chars_clean=清洗后字符数（切分与入库用的就是这份）");

        if (!paged) {
            notes.add("该格式（" + format + "）没有固定分页：页数不适用（pages_supported=false），"
                    + "不按字符数估算页数");
        } else if (pages == null) {
            suspects.add(item("pages_unknown", "info",
                    "既没有解析器声明的页数，正文也没有 page 标记：页数不可知，页级明细与跨页判断全部不可用", null));
        } else if ("parser".equals(pagesSource) && !marks.isEmpty() && marks.size() != declaredPages) {
            suspects.add(item("page_count_mismatch", "warn",
                    "解析器声明 " + declaredPages + " 页，正文里只有 " + marks.size()
                            + " 个页标记：引用页码可能错位（少的那几页可能整页没解析出来）", null));
        } else if ("page_markers".equals(pagesSource)) {
            notes.add("页数来自正文页标记（解析器未声明页数）");
        } else if ("parser".equals(pagesSource)) {
            notes.add("页数来自解析器声明（MinerU 取 content_list 的最大页号 + 1；PDFBox 取实际页数）");
        }

        // ---- 跨页判断：只有带页标记才做，不编造
        List<Map<String, Object>> pagesDetail = new ArrayList<>();
        if (!marks.isEmpty()) {
            pagesDetail = pageDetail(markdown, marks, structures);
            crossPageTables(pagesDetail, suspects);
            pageCharsSkew(pagesDetail, suspects);
        } else if (paged && pages != null) {
            suspects.add(item("no_page_marks", "info",
                    "正文没有 page 标记：页级字符数、空页、跨页表格都无法核对（MinerU 的 full.md 通常不带页标记）", null));
        }

        // ---- 表格结构核对
        if (scan.noSeparator > 0) {
            suspects.add(item("table_no_separator", "warn",
                    scan.noSeparator + " 处管道表缺分隔行（没有 | --- | 那行）：渲染不成表格，"
                            + "多数是表格被拍平成普通段落", null));
        }
        if (scan.blocks > tableStructs) {
            suspects.add(item("table_struct_missing", "warn",
                    "正文有 " + scan.blocks + " 张管道表，structures 只登记了 " + tableStructs
                            + " 张：结构清单漏表（表格在，但定位/页号缺失）", null));
        }
        if (tableStructs > scan.blocks) {
            suspects.add(item("table_body_missing", "warn",
                    "structures 登记了 " + tableStructs + " 张表，正文只有 " + scan.blocks
                            + " 张管道表：可能有表格正文没写进 Markdown（表头/表体丢失）", null));
        }
        tableSplitAcrossPages(structures, suspects);

        // ---- 公式核对
        if (formulas == 0 && count(LATEX_HINT, markdown) > 0) {
            suspects.add(item("formula_as_text", "warn",
                    "正文出现 LaTeX 命令（\\frac / \\sum / ^{…} 等）但统计不到任何公式："
                            + "公式很可能被拍成了纯文本行，KaTeX 排版与检索都会失真", null));
        }
        if (formulaStructs == 0 && formulaMd > 0) {
            suspects.add(item("formula_no_structure", "info",
                    "正文有 " + formulaMd + " 处公式语法，structures 未登记：公式只有文本形态，页号/位置不可定位", null));
        }
        if (formulaStructs > 0 && formulaMd == 0) {
            suspects.add(item("formula_not_rendered", "warn",
                    "原件里有 " + formulaStructs + " 处公式，正文里却没有任何公式语法：公式内容没写进 Markdown"
                            + "（例如 Word 的 OMML 公式，POI 只数得出个数、提取不到内容）——问答拿不到公式，"
                            + "复核页也渲染不出来", null));
        }

        // ---- 图片核对
        if (!assets.isEmpty() && !imageRefs.isEmpty()) {
            List<String> missing = new ArrayList<>();
            for (String ref : imageRefs) {
                String base = basename(ref);
                if (!base.isEmpty() && !assets.containsKey(base) && !assetPathEndsWith(assets, base)) {
                    missing.add(ref);
                }
            }
            if (!missing.isEmpty()) {
                suspects.add(item("image_ref_missing", "warn",
                        missing.size() + " 处图片引用找不到对应产物（例如 " + firstN(missing, 2)
                                + "）：复核页会显示裂图，图里的信息等于丢了", null));
            }
        }
        if (imageStructs > 0 && imageRefs.isEmpty()) {
            suspects.add(item("image_unreferenced", "warn",
                    "解析器识别出 " + imageStructs + " 张图片，但正文里没有任何图片引用："
                            + "图片在 Markdown 合成阶段丢了（只剩清单）", null));
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("format", format);
        out.put("format_label", label(format));
        out.put("pages_supported", paged);
        out.put("pages", pages);
        out.put("pages_source", pagesSource);
        if (!pagesDetail.isEmpty()) {
            out.put("pages_empty", countEmpty(pagesDetail));
        }
        out.put("chars", chars);
        out.put("text_chars", textChars);
        out.put("chars_clean", clean == null ? null : clean.get("chars_out"));
        out.put("headings", count(HEADING_MARK, markdown));
        out.put("chunks", chunks == null ? 0 : chunks.size());
        out.put("images", images);
        out.put("image_refs", imageRefs.size());
        out.put("image_structures", imageStructs);
        out.put("image_assets", assets.size());
        out.put("formulas", formulas);
        out.put("formula_structures", formulaStructs);
        out.put("formula_inline", formulaInline);
        out.put("formula_block", formulaBlock + formulaTex);
        out.put("tables", tables);
        out.put("table_pipe_blocks", scan.blocks);
        out.put("table_structures", tableStructs);
        // 非分页格式的"规模"替代口径：xlsx 看 sheet/行，音视频看时长，docx 看段落
        Map<String, Object> extra = new LinkedHashMap<>();
        if (!paged) {
            Object sheets = metadata.get("tables");
            if (sheets instanceof List) {
                extra.put("sheets", ((List<?>) sheets).size());
            }
            if (statsIn.get("blocks") != null) {
                extra.put("blocks", statsIn.get("blocks"));
                extra.put("rows_textualized", statsIn.get("blocks"));
            }
            if (statsIn.get("skipped_rows") != null) {
                extra.put("rows_skipped", statsIn.get("skipped_rows"));
            }
            if (statsIn.get("paragraphs") != null) {
                extra.put("paragraphs", statsIn.get("paragraphs"));
            }
            if (statsIn.get("duration_sec") != null) {
                extra.put("duration_sec", statsIn.get("duration_sec"));
            }
        }
        out.put("extra", extra);
        out.put("suspects", suspects);
        out.put("suspect_count", suspects.size());
        out.put("notes", notes);
        return out;
    }

    // ---------------------------------------------------------------- 分页细节

    private static List<int[]> pageMarks(String markdown) {
        List<int[]> marks = new ArrayList<>();
        Matcher m = PAGE_MARK.matcher(markdown);
        while (m.find()) {
            marks.add(new int[]{m.start(), m.end(), Integer.parseInt(m.group(1))});
        }
        return marks;
    }

    /** 每页：页号 / 正文（去掉标记与空白前）/ 字符数 / 首行尾行（跨页判断用）。 */
    private static List<Map<String, Object>> pageDetail(String markdown, List<int[]> marks,
                                                        List<Map<String, Object>> structures) {
        Map<Integer, Map<String, Integer>> kindByPage = new LinkedHashMap<>();
        for (Map<String, Object> s : structures) {
            Matcher pm = PAGE_LOC.matcher(str(s.get("location")));
            if (!pm.find()) {
                continue;
            }
            int page = Integer.parseInt(pm.group(1));
            String kind = str(s.get("kind"));
            Map<String, Integer> bucket = kindByPage.get(page);
            if (bucket == null) {
                bucket = new LinkedHashMap<>();
                kindByPage.put(page, bucket);
            }
            Integer old = bucket.get(kind);
            bucket.put(kind, old == null ? 1 : old + 1);
        }
        List<Map<String, Object>> out = new ArrayList<>();
        for (int i = 0; i < marks.size(); i++) {
            int end = marks.get(i)[1];
            int stop = i + 1 < marks.size() ? marks.get(i + 1)[0] : markdown.length();
            String body = markdown.substring(end, stop).trim();
            int pageNo = marks.get(i)[2];
            List<String> lines = nonBlankLines(body);
            Map<String, Integer> kinds = kindByPage.get(pageNo);
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("page", pageNo);
            row.put("chars", body.length());
            row.put("tables", kinds == null || kinds.get("table") == null ? 0 : kinds.get("table"));
            row.put("images", kinds == null ? 0
                    : (kinds.get("image") == null ? 0 : kinds.get("image"))
                    + (kinds.get("keyframe") == null ? 0 : kinds.get("keyframe")));
            row.put("first_line", lines.isEmpty() ? "" : lines.get(0));
            row.put("last_line", lines.isEmpty() ? "" : lines.get(lines.size() - 1));
            row.put("table_rows", countTableRows(lines));
            row.put("empty", body.isEmpty());
            out.add(row);
        }
        return out;
    }

    /** 跨页表格：上一页最后一行是表格行、下一页第一行也是表格行——表格很可能被页边界切断。 */
    private static void crossPageTables(List<Map<String, Object>> pages, List<Map<String, Object>> suspects) {
        for (int i = 0; i + 1 < pages.size(); i++) {
            Map<String, Object> a = pages.get(i);
            Map<String, Object> b = pages.get(i + 1);
            String last = str(a.get("last_line"));
            String first = str(b.get("first_line"));
            if (!isTableRow(last) || !isTableRow(first)) {
                continue;
            }
            int rows = num(a.get("table_rows"));
            int pa = num(a.get("page"));
            int pb = num(b.get("page"));
            if (rows >= 3) {
                suspects.add(item("table_cross_page", "warn",
                        "第 " + pa + " 页末尾与第 " + pb + " 页开头都是表格行（第 " + pa + " 页共 " + rows
                                + " 行表格）：疑似同一张表被页边界切断，核对两页列数、表头是否重复/缺失",
                        Arrays.asList(pa, pb)));
            } else {
                suspects.add(item("table_touches_page_break", "info",
                        "第 " + pa + " 页末尾与第 " + pb + " 页开头都紧贴表格行：可能是两张相邻表，"
                                + "也可能是一张表跨页（行数太少不足以判断）", Arrays.asList(pa, pb)));
            }
        }
    }

    /** 页字符数离群：某页字符数是中位数的 5 倍以上或不足 10%（合并页 / 整页丢失）。 */
    private static void pageCharsSkew(List<Map<String, Object>> pages, List<Map<String, Object>> suspects) {
        if (pages.size() < 3) {
            return;
        }
        List<Integer> sizes = new ArrayList<>();
        for (Map<String, Object> p : pages) {
            sizes.add(num(p.get("chars")));
        }
        List<Integer> sorted = new ArrayList<>(sizes);
        java.util.Collections.sort(sorted);
        int median = sorted.get(sorted.size() / 2);
        if (median < 100) {
            return;
        }
        List<Integer> fat = new ArrayList<>();
        List<Integer> thin = new ArrayList<>();
        for (Map<String, Object> p : pages) {
            int c = num(p.get("chars"));
            if (c == 0) {
                continue;   // 空页已由 empty_pages 报，不重复
            }
            if (c > median * 5) {
                fat.add(num(p.get("page")));
            } else if (c < median * 0.1) {
                thin.add(num(p.get("page")));
            }
        }
        if (!fat.isEmpty()) {
            suspects.add(item("page_chars_outlier_high", "info",
                    "第 " + firstN(fat, 6) + " 页字符数是中位数（" + median + "）的 5 倍以上："
                            + "可能两页被合并成一页（页锚点会指偏）", fat));
        }
        if (!thin.isEmpty()) {
            suspects.add(item("page_chars_outlier_low", "warn",
                    "第 " + firstN(thin, 6) + " 页字符数不足中位数的 10%：疑似整页正文没解析出来"
                            + "（扫描页 / 纯图页 / 分栏错乱）", thin));
        }
    }

    /** structures 里相邻两页各有一张表：疑似同一张跨页表被拆成两张（MinerU 常见）。 */
    private static void tableSplitAcrossPages(List<Map<String, Object>> structures,
                                              List<Map<String, Object>> suspects) {
        List<Integer> tablePages = new ArrayList<>();
        for (Map<String, Object> s : structures) {
            if (!"table".equals(str(s.get("kind")))) {
                continue;
            }
            Matcher m = PAGE_LOC.matcher(str(s.get("location")));
            if (m.find()) {
                tablePages.add(Integer.parseInt(m.group(1)));
            }
        }
        if (tablePages.size() < 2) {
            return;
        }
        java.util.Collections.sort(tablePages);
        List<String> pairs = new ArrayList<>();
        int adjacent = 0;
        for (int i = 0; i + 1 < tablePages.size(); i++) {
            if (tablePages.get(i + 1) == tablePages.get(i) + 1) {
                adjacent++;
                if (pairs.size() < 5) {
                    pairs.add((tablePages.get(i) + 1) + "→" + (tablePages.get(i + 1) + 1));
                }
            }
        }
        if (adjacent > 0) {
            suspects.add(item("table_split_across_pages", "warn",
                    adjacent + " 组相邻页各登记了一张表（页对 " + String.join(", ", pairs) + "）："
                            + "可能是同一张跨页表被拆成两张，核对后一张的第一行是不是续行而非新表头", null));
        }
    }

    // ---------------------------------------------------------------- 计数工具

    private static final class TableScan {
        int blocks;          // 带分隔行的管道表块数
        int noSeparator;     // 有管道行但没有分隔行的块数（渲染不成表）
    }

    private static TableScan scanTables(String markdown) {
        TableScan scan = new TableScan();
        String[] lines = markdown.split("\n", -1);
        boolean inBlock = false;
        boolean hasSep = false;
        int rows = 0;
        for (String line : lines) {
            if (isTableRow(line)) {
                if (!inBlock) {
                    inBlock = true;
                    hasSep = false;
                    rows = 0;
                }
                rows++;
                if (isSepRow(line)) {
                    hasSep = true;
                }
            } else if (inBlock) {
                if (hasSep) {
                    scan.blocks++;
                } else if (rows >= 2) {
                    scan.noSeparator++;
                }
                inBlock = false;
            }
        }
        if (inBlock) {
            if (hasSep) {
                scan.blocks++;
            } else if (rows >= 2) {
                scan.noSeparator++;
            }
        }
        return scan;
    }

    /** 正文纯文字数：去掉页标记、HTML 注释、图片/链接语法、表格分隔行、Markdown 标记与空白。 */
    static int plainChars(String markdown) {
        String s = PAGE_MARK.matcher(markdown).replaceAll(" ");
        s = HTML_COMMENT.matcher(s).replaceAll(" ");
        s = IMG_REF.matcher(s).replaceAll(" ");
        s = s.replaceAll("\\[([^\\]]*)\\]\\([^)]*\\)", "$1");   // 链接只留文字
        s = s.replaceAll("(?m)^\\s*\\|?[\\s:|-]*-{2,}[\\s:|-]*$", " ");   // 表格分隔行
        s = s.replaceAll("(?s)```.*?```", " ");                  // 代码块（含围栏）
        s = s.replaceAll("\\$\\$[\\s\\S]{1,4000}?\\$\\$", " ");   // 公式定界符与内容
        s = MD_MARKUP.matcher(s).replaceAll(" ");
        s = s.replaceAll("\\s+", "");
        return s.length();
    }

    private static List<String> imageRefs(String markdown) {
        List<String> refs = new ArrayList<>();
        Matcher m = IMG_REF.matcher(markdown);
        while (m.find()) {
            refs.add(m.group(1));
        }
        return refs;
    }

    private static List<String> nonBlankLines(String body) {
        List<String> out = new ArrayList<>();
        for (String line : body.split("\n", -1)) {
            if (!line.trim().isEmpty()) {
                out.add(line);
            }
        }
        return out;
    }

    private static int countTableRows(List<String> lines) {
        int n = 0;
        for (String line : lines) {
            if (isTableRow(line)) {
                n++;
            }
        }
        return n;
    }

    private static boolean isTableRow(String line) {
        return line != null && TABLE_ROW.matcher(line).matches();
    }

    /** 表格分隔行：字符集只有 | - : 空白，且至少一个 '-'（避免把正文里的竖线算成表）。 */
    private static boolean isSepRow(String line) {
        String t = line == null ? "" : line.trim();
        if (t.isEmpty() || t.indexOf('-') < 0) {
            return false;
        }
        for (int i = 0; i < t.length(); i++) {
            char c = t.charAt(i);
            if (c != '|' && c != '-' && c != ':' && c != ' ' && c != '\t') {
                return false;
            }
        }
        return true;
    }

    private static int count(Pattern p, String text) {
        if (text == null || text.isEmpty()) {
            return 0;
        }
        Matcher m = p.matcher(text);
        int n = 0;
        while (m.find()) {
            n++;
        }
        return n;
    }

    private static int countKind(List<Map<String, Object>> structures, String kind) {
        int n = 0;
        for (Map<String, Object> s : structures) {
            if (kind.equals(str(s.get("kind")))) {
                n++;
            }
        }
        return n;
    }

    private static int countEmpty(List<Map<String, Object>> pages) {
        int n = 0;
        for (Map<String, Object> p : pages) {
            if (Boolean.TRUE.equals(p.get("empty"))) {
                n++;
            }
        }
        return n;
    }

    /** 图片引用 → assets 的 key（去目录、去扩展名）。 */
    private static String basename(String ref) {
        String s = ref == null ? "" : ref.trim();
        int q = s.indexOf('?');
        if (q >= 0) {
            s = s.substring(0, q);
        }
        int slash = Math.max(s.lastIndexOf('/'), s.lastIndexOf('\\'));
        s = slash >= 0 ? s.substring(slash + 1) : s;
        int dot = s.lastIndexOf('.');
        return dot > 0 ? s.substring(0, dot) : s;
    }

    private static boolean assetPathEndsWith(Map<String, Object> assets, String base) {
        for (Object v : assets.values()) {
            String path = str(v).replace('\\', '/');
            if (path.endsWith("/" + base + ".jpg") || path.endsWith("/" + base + ".png")
                    || path.endsWith("/" + base + ".jpeg") || path.endsWith("/" + base + ".webp")) {
                return true;
            }
        }
        return false;
    }

    /**
     * 格式推断：解析器写的 metadata.format > source_type > 文件名扩展名。
     * 只有扩展名可信时也照实给（比如历史文档没有 metadata）。
     */
    private static String formatOf(Map<String, Object> metadata, Map<String, Object> parsed,
                                   Map<String, Object> stats) {
        String fmt = str(metadata.get("format"));
        if (fmt.isEmpty()) {
            fmt = str(parsed.get("source_type"));
        }
        String file = str(metadata.get("source_file"));
        String ext = "";
        if (!file.isEmpty()) {
            int dot = file.lastIndexOf('.');
            if (dot >= 0) {
                ext = file.substring(dot + 1).toLowerCase(Locale.ROOT);
            }
        }
        if (!ext.isEmpty() && !ext.equals(fmt)) {
            // 扩展名比 source_type 细（docx/xlsx/md/txt 都报成各自格式，而不是笼统的 "pdf|av|excel"）
            fmt = ext;
        }
        return fmt.isEmpty() ? "unknown" : fmt;
    }

    private static String label(String format) {
        if ("pdf".equals(format)) {
            return "PDF";
        }
        if ("docx".equals(format) || "doc".equals(format)) {
            return "Word（docx）";
        }
        if ("xlsx".equals(format) || "xls".equals(format) || "xlsm".equals(format) || "csv".equals(format)) {
            return "表格（" + format.toUpperCase(Locale.ROOT) + "）";
        }
        if ("md".equals(format) || "markdown".equals(format)) {
            return "Markdown（原生，无解析风险）";
        }
        if ("txt".equals(format)) {
            return "纯文本";
        }
        if ("mp4".equals(format) || "mkv".equals(format) || "mov".equals(format)
                || "mp3".equals(format) || "wav".equals(format) || "m4a".equals(format)
                || "flac".equals(format) || "av".equals(format)) {
            return "音视频（ASR 转写）";
        }
        return format.toUpperCase(Locale.ROOT);
    }

    private static Map<String, Object> item(String code, String level, String detail, List<Integer> pages) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("code", code);
        m.put("level", level);
        m.put("detail", detail);
        if (pages != null) {
            m.put("pages", pages);
        }
        return m;
    }

    private static String firstN(List<?> list, int n) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < Math.min(n, list.size()); i++) {
            if (i > 0) {
                sb.append(", ");
            }
            sb.append(list.get(i));
        }
        return sb.toString();
    }

    private static String str(Object o) {
        return o == null ? "" : String.valueOf(o);
    }

    private static int num(Object o) {
        return o instanceof Number ? ((Number) o).intValue() : 0;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMap(Object o) {
        return o instanceof Map ? (Map<String, Object>) o : new LinkedHashMap<String, Object>();
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> asList(Object o) {
        List<Map<String, Object>> out = new ArrayList<>();
        if (o instanceof List) {
            for (Object e : (List<?>) o) {
                if (e instanceof Map) {
                    out.add((Map<String, Object>) e);
                }
            }
        }
        return out;
    }
}
