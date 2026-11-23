package com.ownrag.tools;

import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.ownrag.core.Db;
import com.ownrag.review.DocStats;
import com.ownrag.util.Json;

/**
 * 一次性回填：给"旧包跑出来的"复核记录补上文档统计（doc_stats）。
 *
 * <p>背景：{@code parse_reviews} 的 format/images/formulas/suspects/doc_stats_json 是后加的列，
 * 2026-11-23 之前的构建根本不产出 doc_stats（{@code DocStats} 当时还不存在）。老库补列后这些列
 * 一律为 NULL，复核页就整列显示"文档统计未生成"——不是页面 bug，是数据里真的没有。
 *
 * <p>做法：**不重新解析、不调用模型**，只从已经落盘的复核工件复原 {@code parsed} 中间态，
 * 然后调用与管道完全相同的 {@link DocStats#compute}（同一函数、同一口径），把结果写回
 * {@code parse_reviews} 的五个列，并把 {@code doc_stats} 补进 {@code report.json}。
 *
 * <p>复原边界（刻意写在日志里，不假装）：
 * <ul>
 *   <li>{@code structures} / {@code assets} 是解析中间态，从未单独落盘。textfile-native 链路
 *       （md/txt，本库 4450 条全是这一类）本来就是空清单，复原是**精确**的。</li>
 *   <li>其它链路（MinerU / PDFBox / POI）拿不到结构清单：默认跳过并提示"需重跑管道"，
 *       加 {@code --best-effort} 才会用空清单算，此时"结构与正文对不上"类存疑会失真（结果里会写明）。</li>
 *   <li>没有 {@code parsed.md} 的记录无从复原（工件被删或从未落盘），只能重跑。</li>
 * </ul>
 *
 * <p>用法（在本目录下）。
 * <pre>
 *   mvn -o -q compile
 *   java -cp "target/classes;$(Get-Content target/cp.txt -Raw)" com.ownrag.tools.BackfillDocStats
 *   java -cp "target/classes;..." com.ownrag.tools.BackfillDocStats --apply
 * </pre>
 * 参数：{@code --data} 数据目录（默认 ./data）、{@code --db} 库文件（默认 data/ownrag.db）、
 * {@code --doc <id>} 只处理指定文档（可重复）、{@code --limit N}、
 * {@code --apply} 真正写回（默认 dry-run）、{@code --force} 已有统计的也重算、
 * {@code --best-effort} 结构清单缺失也硬算、{@code --verbose} 逐条打印、{@code --help}。
 *
 * <p>安全：只 UPDATE 五个统计列（不碰 status/verdict/blocking，已审批结论不动）；
 * 每 200 条提交一次，尽量少占 WAL 写锁；服务运行中可直接跑。
 */
public final class BackfillDocStats {

    private static final int COMMIT_EVERY = 200;
    private static final int SAMPLE_MAX = 10;

    private BackfillDocStats() {
    }

    public static void main(String[] args) throws Exception {
        System.setOut(new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8"));

        Path dataDir = Paths.get("data");
        Path dbArg = null;
        boolean apply = false;
        boolean force = false;
        boolean bestEffort = false;
        boolean verbose = false;
        int limit = Integer.MAX_VALUE;
        Set<String> only = new LinkedHashSet<String>();

        for (int i = 0; i < args.length; i++) {
            String a = args[i];
            if ("--data".equals(a) && i + 1 < args.length) {
                dataDir = Paths.get(args[++i]);
            } else if ("--db".equals(a) && i + 1 < args.length) {
                dbArg = Paths.get(args[++i]);
            } else if ("--doc".equals(a) && i + 1 < args.length) {
                only.add(args[++i].trim());
            } else if ("--limit".equals(a) && i + 1 < args.length) {
                limit = Integer.parseInt(args[++i].trim());
            } else if ("--apply".equals(a)) {
                apply = true;
            } else if ("--force".equals(a)) {
                force = true;
            } else if ("--best-effort".equals(a)) {
                bestEffort = true;
            } else if ("--verbose".equals(a)) {
                verbose = true;
            } else if ("--help".equals(a) || "-h".equals(a)) {
                usage();
                return;
            } else {
                System.err.println("未知参数：" + a);
                usage();
                System.exit(2);
                return;
            }
        }

        Path db = dbArg != null ? dbArg : dataDir.resolve("ownrag.db");
        System.out.println("== ownrag 文档统计回填（doc_stats）==");
        System.out.println("数据目录 : " + dataDir.toAbsolutePath().normalize());
        System.out.println("数据库   : " + db.toAbsolutePath().normalize());
        System.out.println("模式     : " + (apply ? "APPLY —— 写回 parse_reviews + report.json"
                : "DRY-RUN —— 只计算不落库（加 --apply 才写）"));
        if (!Files.exists(db)) {
            System.err.println("数据库不存在，检查 --data / --db：" + db.toAbsolutePath().normalize());
            System.exit(1);
            return;
        }

        int scanned = 0;
        int filled = 0;
        int skippedNoMd = 0;
        int skippedNonNative = 0;
        int failed = 0;
        Map<String, Integer> skipReasons = new LinkedHashMap<String, Integer>();
        List<String> samples = new ArrayList<String>();

        try (Connection conn = Db.connect(db)) {
            List<Row> rows = loadRows(conn, force, only, limit);
            System.out.println("待处理   : " + rows.size() + " 条"
                    + (force ? "（--force：已有统计的也重算）" : "（doc_stats_json IS NULL）"));
            System.out.println();

            PreparedStatement update = apply ? conn.prepareStatement(
                    "UPDATE parse_reviews SET format=?, images=?, formulas=?, suspects=?, tables=?,"
                            + " doc_stats_json=?, updated_at=datetime('now','localtime') WHERE doc_id=?") : null;
            int pending = 0;
            try {
                for (Row row : rows) {
                    scanned++;
                    Path reviewDir = dataDir.resolve("review").resolve(row.docId);
                    String markdown = readText(reviewDir.resolve("parsed.md"));
                    if (markdown == null) {
                        skippedNoMd++;
                        bump(skipReasons, "没有 parsed.md（工件未落盘/已删），只能重跑管道");
                        continue;
                    }

                    Path reportFile = Files.exists(reviewDir.resolve("report.json"))
                            ? reviewDir.resolve("report.json") : resolveReport(row.reportPath);
                    Map<String, Object> report = reportFile == null ? null : readMap(reportFile);

                    Map<String, Object> metadata = asMap(report == null ? null : report.get("metadata"));
                    if (isBlank(str(metadata.get("source_file")))) {
                        metadata.put("source_file", row.sourceFile);
                    }
                    Map<String, Object> stats = asMap(report == null ? null : report.get("stats"));
                    List<Map<String, Object>> chunks = readList(reviewDir.resolve("chunks.json"));
                    Map<String, Object> clean = asMapOrNull(report == null ? null : report.get("clean"));

                    boolean nativeText = isNativeText(row.backend, metadata);
                    if (!nativeText && !bestEffort) {
                        skippedNonNative++;
                        bump(skipReasons, "非 textfile-native 链路（" + str(row.backend)
                                + "）：structures/assets 未落盘，需重跑管道或加 --best-effort");
                        continue;
                    }

                    Map<String, Object> parsed = new LinkedHashMap<String, Object>();
                    parsed.put("markdown", markdown);
                    parsed.put("metadata", metadata);
                    parsed.put("stats", stats);
                    parsed.put("structures", new ArrayList<Map<String, Object>>());
                    parsed.put("assets", new LinkedHashMap<String, Object>());

                    Map<String, Object> docStats;
                    try {
                        docStats = DocStats.compute(parsed, chunks, clean);
                    } catch (RuntimeException e) {
                        failed++;
                        System.out.println("[FAIL] " + row.docId + " " + e);
                        continue;
                    }
                    if (!nativeText) {
                        docStats.put("backfill_note", "best-effort：structures/assets 未落盘，"
                                + "结构类存疑（table_* / image_unreferenced / formula_no_structure）可能失真");
                    }

                    if (samples.size() < SAMPLE_MAX) {
                        samples.add(String.format("  %s  %s  %s字 · 图%s 式%s 表%s · 存疑%s  <- %s",
                                row.docId, str(docStats.get("format")), fmt(docStats.get("chars")),
                                fmt(docStats.get("images")), fmt(docStats.get("formulas")),
                                fmt(docStats.get("tables")), fmt(docStats.get("suspect_count")),
                                row.sourceFile));
                    }
                    if (verbose) {
                        System.out.println("[ok] " + row.docId + "  " + str(docStats.get("format"))
                                + "  " + fmt(docStats.get("chars")) + "字 图" + fmt(docStats.get("images"))
                                + " 式" + fmt(docStats.get("formulas")) + " 表" + fmt(docStats.get("tables"))
                                + " 存疑" + fmt(docStats.get("suspect_count")) + "  <- " + row.sourceFile);
                    }

                    if (apply) {
                        try {
                            writeDb(update, row.docId, docStats);
                            rewriteReport(reportFile, report, docStats);
                            filled++;
                            pending++;
                            if (pending >= COMMIT_EVERY) {
                                conn.commit();
                                pending = 0;
                                System.out.println("... 已提交 " + filled + " 条");
                            }
                        } catch (Exception e) {
                            failed++;
                            System.out.println("[FAIL] " + row.docId + " 写回失败：" + e.getMessage());
                        }
                    } else {
                        filled++;
                    }
                }
                if (apply && pending > 0) {
                    conn.commit();
                }
            } finally {
                if (update != null) {
                    update.close();
                }
            }
        }

        System.out.println();
        System.out.println("== 结果 ==");
        System.out.println("扫描      : " + scanned);
        System.out.println((apply ? "已回填    : " : "可回填    : ") + filled);
        System.out.println("跳过      : " + (scanned - filled - failed) + "（" + skipReasons.size() + " 种原因）");
        for (Map.Entry<String, Integer> e : skipReasons.entrySet()) {
            System.out.println("           - " + e.getValue() + " 条：" + e.getKey());
        }
        System.out.println("失败      : " + failed);
        if (!samples.isEmpty()) {
            System.out.println();
            System.out.println("样例（最多 " + SAMPLE_MAX + " 条）:");
            for (String s : samples) {
                System.out.println(s);
            }
        }
        System.out.println();
        if (apply) {
            System.out.println("已写回：刷新 /ui/review.html 即可看到「规模」列与详情里的统计面板。");
        } else {
            System.out.println("DRY-RUN：确认上面的样例口径没问题后，加 --apply 重新执行才会落库。");
        }
    }

    // ---------------------------------------------------------------- DB

    private static final class Row {
        String docId;
        String backend;
        String sourceFile;
        String reportPath;
    }

    private static List<Row> loadRows(Connection conn, boolean force, Set<String> only, int limit)
            throws Exception {
        StringBuilder sql = new StringBuilder(
                "SELECT doc_id, backend, source_file, report_path FROM parse_reviews");
        if (!force) {
            sql.append(" WHERE doc_stats_json IS NULL OR TRIM(doc_stats_json)=''");
        }
        if (!only.isEmpty()) {
            sql.append(force ? " WHERE" : " AND").append(" doc_id IN (");
            for (int i = 0; i < only.size(); i++) {
                sql.append(i == 0 ? "?" : ",?");
            }
            sql.append(')');
        }
        sql.append(" ORDER BY created_at DESC, doc_id");
        List<Row> out = new ArrayList<Row>();
        try (PreparedStatement ps = conn.prepareStatement(sql.toString())) {
            int idx = 1;
            for (String d : only) {
                ps.setString(idx++, d);
            }
            try (ResultSet rs = ps.executeQuery()) {
                while (rs.next() && out.size() < limit) {
                    Row r = new Row();
                    r.docId = rs.getString("doc_id");
                    r.backend = rs.getString("backend");
                    r.sourceFile = rs.getString("source_file");
                    r.reportPath = rs.getString("report_path");
                    out.add(r);
                }
            }
        }
        // 读事务到此结束：下面要写，避免读快照升级写锁时撞 SQLITE_BUSY_SNAPSHOT
        conn.commit();
        return out;
    }

    private static void writeDb(PreparedStatement ps, String docId, Map<String, Object> ds)
            throws Exception {
        ps.setString(1, str(ds.get("format")));
        ps.setInt(2, num(ds.get("images")));
        ps.setInt(3, num(ds.get("formulas")));
        ps.setInt(4, num(ds.get("suspect_count")));
        // tables 用文档统计口径（正文管道表 ∪ structures，取大者），与 saveReview 一致
        ps.setInt(5, num(ds.get("tables")));
        ps.setString(6, Json.write(ds));
        ps.setString(7, docId);
        ps.executeUpdate();
    }

    /**
     * report.json 补 doc_stats：详情接口在老记录上会回退读这份文件，
     * 顺手把 checks.stats 的 format/images/formulas/suspects 补齐，两个口径不留缝。
     */
    @SuppressWarnings("unchecked")
    private static void rewriteReport(Path reportFile, Map<String, Object> report,
                                      Map<String, Object> docStats) throws Exception {
        if (reportFile == null || report == null) {
            return;
        }
        report.put("doc_stats", docStats);
        Object checks = report.get("checks");
        if (checks instanceof Map) {
            Object stats = ((Map<String, Object>) checks).get("stats");
            if (stats instanceof Map) {
                Map<String, Object> st = (Map<String, Object>) stats;
                st.put("format", docStats.get("format"));
                st.put("images", docStats.get("images"));
                st.put("formulas", docStats.get("formulas"));
                st.put("suspects", docStats.get("suspect_count"));
            }
        }
        Files.write(reportFile, Json.MAPPER.writerWithDefaultPrettyPrinter()
                .writeValueAsString(report).getBytes(StandardCharsets.UTF_8));
    }

    // ---------------------------------------------------------------- 工件读取

    /** report_path 里存的是写库时的相对路径（形如 {@code .\data\review\x\report.json}）；能找到就用。 */
    private static Path resolveReport(String reportPath) {
        if (isBlank(reportPath)) {
            return null;
        }
        try {
            Path p = Paths.get(reportPath.trim());
            return Files.exists(p) ? p : null;
        } catch (Exception e) {
            return null;
        }
    }

    private static String readText(Path p) {
        if (p == null || !Files.isRegularFile(p)) {
            return null;
        }
        try {
            return new String(Files.readAllBytes(p), StandardCharsets.UTF_8);
        } catch (Exception e) {
            return null;
        }
    }

    private static Map<String, Object> readMap(Path p) {
        String text = readText(p);
        if (text == null || text.trim().isEmpty()) {
            return null;
        }
        try {
            return Json.readMap(text);
        } catch (Exception e) {
            return null;
        }
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> readList(Path p) {
        String text = readText(p);
        if (text == null || text.trim().isEmpty()) {
            return new ArrayList<Map<String, Object>>();
        }
        try {
            Object o = Json.MAPPER.readValue(text, Object.class);
            List<Map<String, Object>> out = new ArrayList<Map<String, Object>>();
            if (o instanceof List) {
                for (Object e : (List<Object>) o) {
                    if (e instanceof Map) {
                        out.add((Map<String, Object>) e);
                    }
                }
            }
            return out;
        } catch (Exception e) {
            return new ArrayList<Map<String, Object>>();
        }
    }

    /** textfile-native 链路（md/txt）的 structures/assets 恒为空，复原才精确。 */
    private static boolean isNativeText(String backend, Map<String, Object> metadata) {
        String b = str(backend).toLowerCase();
        if (b.startsWith("textfile") || b.startsWith("native")) {
            return true;
        }
        return str(metadata.get("format")).toLowerCase().startsWith("native_");
    }

    // ---------------------------------------------------------------- 小工具

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMap(Object o) {
        return o instanceof Map ? (Map<String, Object>) o : new LinkedHashMap<String, Object>();
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMapOrNull(Object o) {
        return o instanceof Map ? (Map<String, Object>) o : null;
    }

    private static void bump(Map<String, Integer> counter, String key) {
        Integer old = counter.get(key);
        counter.put(key, old == null ? 1 : old + 1);
    }

    private static String fmt(Object o) {
        return o == null ? "-" : String.valueOf(o);
    }

    private static int num(Object o) {
        return o instanceof Number ? ((Number) o).intValue() : 0;
    }

    private static String str(Object o) {
        return o == null ? "" : String.valueOf(o);
    }

    private static boolean isBlank(String s) {
        return s == null || s.trim().isEmpty();
    }

    private static void usage() {
        System.out.println("用法: BackfillDocStats [选项]");
        System.out.println("  --data <dir>    数据目录，默认 ./data");
        System.out.println("  --db <file>     数据库文件，默认 <data>/ownrag.db");
        System.out.println("  --doc <id>      只处理指定文档（可重复）");
        System.out.println("  --limit N       最多处理 N 条");
        System.out.println("  --apply         真正写回（默认 dry-run，只算不写）");
        System.out.println("  --force         已有 doc_stats 的记录也重算");
        System.out.println("  --best-effort   非 textfile-native 链路（结构清单未落盘）也硬算，结果会标 backfill_note");
        System.out.println("  --verbose       逐条打印");
        System.out.println("  --help          本帮助");
    }
}
