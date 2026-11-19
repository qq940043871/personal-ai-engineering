package com.ownrag.review;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import com.ownrag.index.EstTokens;
import com.ownrag.util.Json;

/**
 * 解析复核（Python 版 review.py 的平移，入库前的第三道闸）：
 * 把"解析成了什么 + 切成了什么"落盘给人看，通过才写索引。
 *
 * 三道闸门的分工：
 *   ① 解析闸 validate_parsed（自动：空/过短/页缺失 → 与解析失败同待遇）
 *   ② 复核闸 prepare_review + review_gate（人工：产物给人看，通过才入库）
 *   ③ 生成闸 gates（自动：候选不足拒答、引用与数字可核验）
 *
 * 落盘结构（data/review/<doc_id>/）：
 *   parsed.md     解析中间态全文（复核对象原貌，不经任何裁剪）
 *   chunks.json   切分预览（块序号 / 块头 / 锚点 / 字数 / 前若干字）
 *   report.json   页级明细 + 解析步骤 + 质量检查 + 本次参数
 */
public final class ReviewStore {

    public static final String STATUS_PENDING = "pending";
    public static final String STATUS_APPROVED = "approved";
    public static final String STATUS_REJECTED = "rejected";

    public static final int PREVIEW_CHARS = 160;   // 切分预览里每块保留的正文长度
    private static final Pattern PAGE_MARK = Pattern.compile("<!--\\s*page:(\\d+)\\s*-->");
    private static final Pattern HEADING_LINE = Pattern.compile("^#{1,6}\\s+", Pattern.MULTILINE);
    private static final Pattern PIPE_LINE = Pattern.compile("^\\s*\\|.*\\|\\s*$", Pattern.MULTILINE);
    /** 替换符 + 控制字符 */
    private static final Pattern BAD_CHARS = Pattern.compile("[\uFFFD\u0000-\u0008\u000B\u000C\u000E-\u001F]");
    private static final Pattern PAGE_LOC = Pattern.compile("page:(\\d+)");

    private ReviewStore() {
    }

    // ---------------------------------------------------------------- 质量检查

    /**
     * 页级明细：只在 markdown 带 `<!--page:N-->` 标记时算得出来（降级链的 pdfbox 路径会带）。
     * MinerU 产出的 Markdown 大多无页标记——那就不编造，返回空列表并在报告里标明。
     */
    static class PageDetails {
        final List<Map<String, Object>> pages;
        final int markerCount;

        PageDetails(List<Map<String, Object>> pages, int markerCount) {
            this.pages = pages;
            this.markerCount = markerCount;
        }
    }

    @SuppressWarnings("unchecked")
    static PageDetails pageDetails(String markdown, List<Map<String, Object>> structures) {
        List<int[]> marks = new ArrayList<>();   // [start, end, pageNo]
        Matcher m = PAGE_MARK.matcher(markdown);
        while (m.find()) {
            marks.add(new int[]{m.start(), m.end(), Integer.parseInt(m.group(1))});
        }
        if (marks.isEmpty()) {
            return new PageDetails(new ArrayList<>(), 0);
        }
        Map<Integer, Map<String, Integer>> kindByPage = new LinkedHashMap<>();
        for (Map<String, Object> s : structures) {
            String loc = s.get("location") == null ? "" : String.valueOf(s.get("location"));
            Matcher pm = PAGE_LOC.matcher(loc);
            if (!pm.find()) {
                continue;
            }
            int page = Integer.parseInt(pm.group(1));
            String kind = s.get("kind") == null ? "other" : String.valueOf(s.get("kind"));
            Map<String, Integer> bucket = kindByPage.computeIfAbsent(page, k -> new LinkedHashMap<>());
            bucket.merge(kind, 1, Integer::sum);
        }
        List<Map<String, Object>> pages = new ArrayList<>();
        for (int idx = 0; idx < marks.size(); idx++) {
            int end = marks.get(idx)[1];
            int stop = idx + 1 < marks.size() ? marks.get(idx + 1)[0] : markdown.length();
            String body = markdown.substring(end, stop).trim();
            int pageNo = marks.get(idx)[2];
            Map<String, Integer> kinds = kindByPage.getOrDefault(pageNo, new LinkedHashMap<>());
            Map<String, Object> p = new LinkedHashMap<>();
            p.put("page", pageNo);
            p.put("chars", body.length());
            p.put("tables", kinds.getOrDefault("table", 0));
            p.put("images", kinds.getOrDefault("image", 0) + kinds.getOrDefault("keyframe", 0));
            p.put("empty", body.isEmpty());
            pages.add(p);
        }
        return new PageDetails(pages, marks.size());
    }

    /**
     * 自动质量检查：blocking（阻断，不允许放行）/ warn（提示，复核重点）/ stats（可量化事实）。
     * 刻意不把"能不能入库"压成单一分数——阻断项是硬事实（空正文、几乎无字），
     * 提示项是"这里通常意味着解析出了问题，你自己看一眼"。
     */
    public static Map<String, Object> qualityChecks(Map<String, Object> parsed, List<Map<String, Object>> chunks,
                                                    int minCharsPerPage, int maxChunkTokens, double oversizedRatio) {
        String markdown = parsed.get("markdown") == null ? "" : String.valueOf(parsed.get("markdown"));
        Map<String, Object> metadata = orEmpty(parsed.get("metadata"));
        Map<String, Object> statsIn = orEmpty(parsed.get("stats"));
        List<Map<String, Object>> structures = new ArrayList<>();
        Object st = parsed.get("structures");
        if (st instanceof List) {
            for (Object o : (List<?>) st) {
                if (o instanceof Map) {
                    structures.add((Map<String, Object>) o);
                }
            }
        }

        int declaredPages = statsIn.get("pages") instanceof Number ? ((Number) statsIn.get("pages")).intValue() : 0;
        PageDetails details = pageDetails(markdown, structures);
        int markerCount = details.markerCount;
        int chars = markdown.length();
        Matcher h = HEADING_LINE.matcher(markdown);
        int headings = 0;
        while (h.find()) {
            headings++;
        }
        int tables = 0;
        for (Map<String, Object> s : structures) {
            if ("table".equals(s.get("kind"))) {
                tables++;
            }
        }
        Matcher pl = PIPE_LINE.matcher(markdown);
        int pipeLines = 0;
        while (pl.find()) {
            pipeLines++;
        }
        Matcher bad = BAD_CHARS.matcher(markdown);
        int badCount = 0;
        while (bad.find()) {
            badCount++;
        }
        double badRate = chars == 0 ? 0.0 : round5((double) badCount / chars);
        List<Integer> emptyPages = new ArrayList<>();
        for (Map<String, Object> p : details.pages) {
            if (Boolean.TRUE.equals(p.get("empty"))) {
                emptyPages.add((Integer) p.get("page"));
            }
        }

        List<Map<String, Object>> blocking = new ArrayList<>();
        List<Map<String, Object>> warn = new ArrayList<>();

        if (markdown.trim().isEmpty()) {
            blocking.add(item("empty_markdown", "解析产物为空 Markdown"));
        } else {
            double perPage = declaredPages > 0 ? (double) chars / declaredPages : chars;
            if (perPage < minCharsPerPage) {
                blocking.add(item("too_few_chars",
                        "字符密度过低：" + chars + " 字符 / " + (declaredPages > 0 ? declaredPages : "未知") + " 页"
                                + "（阈值 " + minCharsPerPage + "/页），疑似扫描件未 OCR 或文本层缺失"));
            }
        }
        if (markerCount > 0 && declaredPages > 0 && markerCount != declaredPages) {
            warn.add(item("page_marker_mismatch",
                    "页标记 " + markerCount + " 个 ≠ 解析声明 " + declaredPages + " 页——引用页码可能错位"));
        }
        if (!emptyPages.isEmpty()) {
            String head = firstN(emptyPages, 10);
            warn.add(item("empty_pages",
                    emptyPages.size() + " 页无可提取文本：第 [" + head + "] 页"
                            + (emptyPages.size() > 10 ? "（等）" : "")));
        }
        if (badRate > 0.005) {
            warn.add(item("mojibake",
                    String.format("乱码/控制字符占比 %.2f%%（%d 个），疑似编码或 OCR 质量差", badRate * 100, badCount)));
        }
        if (headings == 0 && chars > 200) {
            warn.add(item("no_headings",
                    "正文超过 200 字符但没有任何标题行——结构丢失，切分只能按长度硬切"));
        }
        if (tables == 0 && pipeLines >= 3) {
            warn.add(item("table_flattened",
                    "正文有 " + pipeLines + " 行表格行文，但 structures 里 0 张表——表格可能被拍平成普通段落"));
        }
        int oversizedLimit = (int) (maxChunkTokens * oversizedRatio);
        List<Map<String, Object>> oversized = new ArrayList<>();
        for (Map<String, Object> c : chunks) {
            String text = c.get("text") == null ? "" : String.valueOf(c.get("text"));
            if (EstTokens.est(text) > oversizedLimit) {
                oversized.add(c);
            }
        }
        if (!oversized.isEmpty()) {
            warn.add(item("oversized_chunk",
                    oversized.size() + " 个块超过 " + oversizedLimit + " tokens（表格/超长段独立成块，属预期则忽略）"));
        }
        String degraded = metadata.get("degraded") == null ? null : String.valueOf(metadata.get("degraded"));
        if (degraded != null && !degraded.isEmpty()) {
            warn.add(item("degraded_path", "走了降级链：" + degraded));
        }

        String verdict = !blocking.isEmpty() ? "fail" : (!warn.isEmpty() ? "warn" : "pass");
        Map<String, Object> stats = new LinkedHashMap<>();
        stats.put("chars", chars);
        stats.put("pages", declaredPages);
        stats.put("page_markers", markerCount);
        stats.put("headings", headings);
        stats.put("tables", tables);
        stats.put("structures", structures.size());
        stats.put("bad_char_rate", badRate);
        stats.put("chunks", chunks.size());
        String backend = statsIn.get("backend") == null ? null : String.valueOf(statsIn.get("backend"));
        stats.put("backend", backend != null && !backend.isEmpty() ? backend
                : (degraded != null && !degraded.isEmpty() ? degraded : "unknown"));

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("verdict", verdict);
        out.put("blocking", blocking);
        out.put("warn", warn);
        out.put("stats", stats);
        out.put("pages", details.pages);
        return out;
    }

    private static Map<String, Object> item(String code, String detail) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("code", code);
        m.put("detail", detail);
        return m;
    }

    // ---------------------------------------------------------------- 工件落盘

    /** 三份工件落盘（全量，不截断）：给人看的原件、切分预览、结构化报告。 */
    public static Map<String, String> writeArtifacts(Path reviewDir, String markdown,
                                                     List<Map<String, Object>> chunks,
                                                     Map<String, Object> report) throws java.io.IOException {
        Files.createDirectories(reviewDir);
        Path parsedMd = reviewDir.resolve("parsed.md");
        Files.write(parsedMd, markdown.getBytes(StandardCharsets.UTF_8));

        List<Map<String, Object>> preview = new ArrayList<>();
        for (Map<String, Object> c : chunks) {
            String text = c.get("text") == null ? "" : String.valueOf(c.get("text"));
            Map<String, Object> meta = orEmpty(c.get("meta"));
            Map<String, Object> p = new LinkedHashMap<>();
            p.put("ordinal", c.get("ordinal"));
            p.put("chunk_id", c.get("chunk_id"));
            p.put("chars", text.length());
            p.put("tokens", EstTokens.est(text));
            p.put("anchors", orEmpty(c.get("anchors")));
            p.put("has_table", Boolean.TRUE.equals(meta.get("has_table")));
            p.put("head", text.substring(0, Math.min(PREVIEW_CHARS, text.length())));
            preview.add(p);
        }
        Path chunksJs = reviewDir.resolve("chunks.json");
        Files.write(chunksJs, Json.MAPPER.writerWithDefaultPrettyPrinter()
                .writeValueAsString(preview).getBytes(StandardCharsets.UTF_8));

        Path reportJs = reviewDir.resolve("report.json");
        Files.write(reportJs, Json.MAPPER.writerWithDefaultPrettyPrinter()
                .writeValueAsString(report).getBytes(StandardCharsets.UTF_8));
        Map<String, String> paths = new LinkedHashMap<>();
        paths.put("parsed_md", parsedMd.toString());
        paths.put("chunks", chunksJs.toString());
        paths.put("report", reportJs.toString());
        return paths;
    }

    // ---------------------------------------------------------------- 状态机

    public static Map<String, Object> getReview(Connection conn, String docId) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement("SELECT * FROM parse_reviews WHERE doc_id=?")) {
            ps.setString(1, docId);
            try (ResultSet rs = ps.executeQuery()) {
                return rs.next() ? com.ownrag.core.TaskStore.rowToMap(rs) : null;
            }
        }
    }

    public static List<Map<String, Object>> listReviews(Connection conn, String status, int limit)
            throws SQLException {
        StringBuilder q = new StringBuilder("SELECT * FROM parse_reviews");
        List<Object> args = new ArrayList<>();
        if (status != null && !status.isEmpty()) {
            q.append(" WHERE status=?");
            args.add(status);
        }
        q.append(" ORDER BY created_at DESC LIMIT ?");
        args.add(Math.max(1, Math.min(limit, 200)));
        try (PreparedStatement ps = conn.prepareStatement(q.toString())) {
            for (int i = 0; i < args.size(); i++) {
                ps.setObject(i + 1, args.get(i));
            }
            try (ResultSet rs = ps.executeQuery()) {
                List<Map<String, Object>> out = new ArrayList<>();
                while (rs.next()) {
                    out.add(com.ownrag.core.TaskStore.rowToMap(rs));
                }
                return out;
            }
        }
    }

    /**
     * 写复核记录并返回状态。已 approved 的记录不因重跑而回落 pending——
     * 人工审批过的事实不该被一次 resume 抹掉。
     */
    @SuppressWarnings("unchecked")
    public static String saveReview(Connection conn, String docId, String kb, String taskId,
                                    String traceId, String pipeline, String sourceFile,
                                    Map<String, Object> checks, String reportPath) throws SQLException {
        Map<String, Object> stats = (Map<String, Object>) checks.get("stats");
        Map<String, Object> existing = getReview(conn, docId);
        String status = existing != null && STATUS_APPROVED.equals(existing.get("status"))
                ? STATUS_APPROVED : STATUS_PENDING;
        try (PreparedStatement ps = conn.prepareStatement(
                "INSERT INTO parse_reviews(doc_id, kb, task_id, trace_id, pipeline, source_file, backend,"
                        + " status, verdict, pages, chars, tables, structures, blocking_json, warn_json,"
                        + " pages_json, report_path) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                        + " ON CONFLICT(doc_id) DO UPDATE SET kb=excluded.kb, task_id=excluded.task_id,"
                        + " trace_id=excluded.trace_id, pipeline=excluded.pipeline,"
                        + " source_file=excluded.source_file, backend=excluded.backend,"
                        + " verdict=excluded.verdict, pages=excluded.pages, chars=excluded.chars,"
                        + " tables=excluded.tables, structures=excluded.structures,"
                        + " blocking_json=excluded.blocking_json, warn_json=excluded.warn_json,"
                        + " pages_json=excluded.pages_json, report_path=excluded.report_path,"
                        + " updated_at=datetime('now','localtime')")) {
            ps.setString(1, docId);
            ps.setString(2, kb);
            ps.setString(3, taskId);
            ps.setString(4, traceId);
            ps.setString(5, pipeline);
            ps.setString(6, sourceFile);
            ps.setString(7, String.valueOf(stats.get("backend")));
            ps.setString(8, status);
            ps.setString(9, String.valueOf(checks.get("verdict")));
            ps.setInt(10, num(stats.get("pages")));
            ps.setInt(11, num(stats.get("chars")));
            ps.setInt(12, num(stats.get("tables")));
            ps.setInt(13, num(stats.get("structures")));
            ps.setString(14, Json.write(checks.get("blocking")));
            ps.setString(15, Json.write(checks.get("warn")));
            ps.setString(16, Json.write(checks.get("pages")));
            ps.setString(17, reportPath);
            ps.executeUpdate();
        }
        conn.commit();
        return status;
    }

    public static boolean setStatus(Connection conn, String docId, String status, String note)
            throws SQLException {
        if (!Arrays.asList(STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED).contains(status)) {
            throw new IllegalArgumentException("非法复核状态：" + status);
        }
        try (PreparedStatement ps = conn.prepareStatement(
                "UPDATE parse_reviews SET status=?, note=?, reviewed_at=datetime('now','localtime'),"
                        + " updated_at=datetime('now','localtime') WHERE doc_id=?")) {
            ps.setString(1, status);
            ps.setString(2, note);
            ps.setString(3, docId);
            boolean ok = ps.executeUpdate() > 0;
            conn.commit();
            return ok;
        }
    }

    // ---- 小工具 ----

    @SuppressWarnings("unchecked")
    private static Map<String, Object> orEmpty(Object o) {
        return o instanceof Map ? (Map<String, Object>) o : new LinkedHashMap<>();
    }

    private static int num(Object o) {
        return o instanceof Number ? ((Number) o).intValue() : 0;
    }

    private static double round5(double v) {
        return Math.round(v * 100000.0) / 100000.0;
    }

    private static String firstN(List<Integer> list, int n) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < Math.min(n, list.size()); i++) {
            if (i > 0) {
                sb.append(", ");
            }
            sb.append(list.get(i));
        }
        return sb.toString();
    }
}
