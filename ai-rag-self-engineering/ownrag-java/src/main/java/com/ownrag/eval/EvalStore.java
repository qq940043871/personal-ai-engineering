package com.ownrag.eval;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.sql.Types;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.ownrag.config.AppDef;
import com.ownrag.config.KbWhitelist;
import com.ownrag.config.Settings;
import com.ownrag.util.Json;

/**
 * 评测集数据层（表 eval_cases）：一行 = 一道题，三件事必须写清楚——
 *
 *   来源  manual（人工按语料出题）/ qa_log（线上真实提问回流）/ direct_hit（直击库回归）
 *   内容  question + expect_all（必须出现的关键词）+ expect_empty（该拒答）
 *   好坏  verdict 由"跑评测"按检索链路写回（pass/fail），跑不动就 pending，不假装有结论
 *
 * 种子策略：空表时把**已有的真实资产**（直击库问题 + 问答日志最近提问）导进来，
 * 先把分母立起来；期望关键词无法凭空生成，就留空——判定口径退化为"是否给出依据"，
 * 页面上写明，不拿假期望冒充真评测。
 */
public final class EvalStore {

    /** 来源白名单：未知来源一律按 manual 存，避免前端 chip 渲染出不存在的一档。 */
    private static final Set<String> SOURCES = new LinkedHashSet<>(
            java.util.Arrays.asList("manual", "qa_log", "direct_hit"));

    private static final Set<String> VERDICTS = new LinkedHashSet<>(
            java.util.Arrays.asList("pass", "fail", "pending"));

    /** 题型分桶（评测报告必须按题型拆开看，混在一起会掩盖结构性缺陷）。 */
    private static final Set<String> CATEGORIES = new LinkedHashSet<>(java.util.Arrays.asList(
            "fact", "concept", "compare", "troubleshoot", "multi", "cross", "reject", "direct", "sql"));

    /** 期望通道白名单：空值 = 不判路由（老题库原样保留，判定口径不因新维度变严）。 */
    private static final Set<String> ROUTES = new LinkedHashSet<>(
            java.util.Arrays.asList("rag", "sql", "multi"));

    private static final Set<String> DIFFICULTIES = new LinkedHashSet<>(
            java.util.Arrays.asList("easy", "medium", "hard"));

    private EvalStore() {
    }

    // ---------------------------------------------------------------- 读

    /**
     * 列表：坏题在前、待跑其次、好题最后——打开页面先看该修的，不是先看漂亮的。
     * 过滤条件全走 SQL，前端只负责展示。
     */
    public static List<Map<String, Object>> list(Connection conn, String kb, String source,
                                                 String verdict, int limit) throws SQLException {
        StringBuilder sql = new StringBuilder("SELECT * FROM eval_cases WHERE 1=1");
        List<Object> args = new ArrayList<>();
        if (kb != null && !kb.trim().isEmpty()) {
            sql.append(" AND kb=?");
            args.add(kb.trim());
        }
        if (source != null && SOURCES.contains(source)) {
            sql.append(" AND source=?");
            args.add(source);
        }
        if (verdict != null && VERDICTS.contains(verdict)) {
            sql.append(" AND verdict=?");
            args.add(verdict);
        }
        sql.append(" ORDER BY CASE verdict WHEN 'fail' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END,");
        sql.append(" id DESC LIMIT ?");
        args.add(Math.max(1, Math.min(limit, 1000)));

        List<Map<String, Object>> out = new ArrayList<>();
        try (PreparedStatement ps = conn.prepareStatement(sql.toString())) {
            bind(ps, args);
            try (ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    out.add(rowToMap(rs));
                }
            }
        }
        return out;
    }

    /**
     * 汇总：总数 / 好 / 坏 / 待跑 / 拒答题 / 来源分布 / 库分布 / 题型分桶通过率 / 最近一次跑的时间。
     *
     * 分桶（by_category）是"能不能用来评 RAG 质量"的关键：只看总通过率会掩盖
     * "事实题全过、跨文档综合全挂"这种结构性缺陷——分母必须拆开看。
     */
    public static Map<String, Object> kpi(Connection conn) throws SQLException {
        Map<String, Object> out = new LinkedHashMap<>();
        Map<String, Object> byVerdict = groupCount(conn,
                "SELECT verdict k, COUNT(*) n FROM eval_cases GROUP BY verdict");
        Map<String, Object> bySource = groupCount(conn,
                "SELECT source k, COUNT(*) n FROM eval_cases GROUP BY source");
        out.put("total", scalar(conn, "SELECT COUNT(*) FROM eval_cases", -1));
        out.put("pass", num(byVerdict.get("pass")));
        out.put("fail", num(byVerdict.get("fail")));
        out.put("pending", num(byVerdict.get("pending")));
        out.put("reject_cases", scalar(conn, "SELECT COUNT(*) FROM eval_cases WHERE expect_empty=1", -1));
        out.put("expect_cases", scalar(conn,
                "SELECT COUNT(*) FROM eval_cases WHERE expect_all<>'[]' AND expect_all IS NOT NULL", -1));
        out.put("sources", bySource);
        out.put("kbs", groupCount(conn, "SELECT kb k, COUNT(*) n FROM eval_cases GROUP BY kb"));
        out.put("route_cases", scalar(conn,
                "SELECT COUNT(*) FROM eval_cases WHERE expect_route IS NOT NULL AND expect_route<>''", -1));
        // 路由不符单独计数：它和"检索没捞到"是两种缺陷，混在一起看不出该改权重还是该补语料
        out.put("route_mismatch", scalar(conn,
                "SELECT COUNT(*) FROM eval_cases WHERE expect_route IS NOT NULL AND expect_route<>''"
                        + " AND route_actual IS NOT NULL AND route_actual<>expect_route", -1));
        out.put("by_category", byCategory(conn));
        out.put("by_difficulty", byDifficulty(conn));
        out.put("by_route", bucket(conn, "route_actual"));
        out.put("last_run_at", one(conn, "SELECT MAX(last_run_at) v FROM eval_cases"));
        out.put("verdict_rule", "关键词题=TopN 候选含全部期望词且闸门一通过；拒答题=闸门一必须拦下；"
                + "直击库题=必须命中直击库；设了期望通道的题=实跑通道必须一致（路由错但答案对也算坏）；"
                + "无期望的人工题=只观察不判定（pending）");
        return out;
    }

    /** 题型分桶：total / pass / fail / pending（只算判过的题，pending 单独一列不混入通过率分母）。 */
    private static List<Map<String, Object>> byCategory(Connection conn) throws SQLException {
        return bucket(conn, "category");
    }

    private static List<Map<String, Object>> byDifficulty(Connection conn) throws SQLException {
        return bucket(conn, "difficulty");
    }

    private static List<Map<String, Object>> bucket(Connection conn, String column) throws SQLException {
        List<Map<String, Object>> out = new ArrayList<>();
        String sql = "SELECT COALESCE(" + column + ",'-') k, COUNT(*) total,"
                + " SUM(CASE WHEN verdict='pass' THEN 1 ELSE 0 END) pass_n,"
                + " SUM(CASE WHEN verdict='fail' THEN 1 ELSE 0 END) fail_n,"
                + " SUM(CASE WHEN verdict='pending' THEN 1 ELSE 0 END) pending_n"
                + " FROM eval_cases GROUP BY k ORDER BY total DESC";
        try (Statement st = conn.createStatement(); ResultSet rs = st.executeQuery(sql)) {
            while (rs.next()) {
                Map<String, Object> row = new LinkedHashMap<>();
                row.put("key", rs.getString("k"));
                row.put("total", rs.getInt("total"));
                row.put("pass", rs.getInt("pass_n"));
                row.put("fail", rs.getInt("fail_n"));
                row.put("pending", rs.getInt("pending_n"));
                int judged = rs.getInt("pass_n") + rs.getInt("fail_n");
                row.put("rate", judged == 0 ? null
                        : Math.round(rs.getInt("pass_n") * 1e3 / judged) / 1e3);
                out.add(row);
            }
        }
        return out;
    }

    public static Map<String, Object> get(Connection conn, long id) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement("SELECT * FROM eval_cases WHERE id=?")) {
            ps.setLong(1, id);
            try (ResultSet rs = ps.executeQuery()) {
                return rs.next() ? rowToMap(rs) : null;
            }
        }
    }

    // ---------------------------------------------------------------- 写

    /**
     * 新增一道题（幂等）：同库同题已存在时返回既有 id 且 created=false。
     * sourceRef 记录"从哪条日志/直击库来的"，页面据此可回查原始 trace。
     */
    public static Map<String, Object> add(Connection conn, String kb, String question, String source,
                                          String sourceRef, List<String> expectAll, boolean expectEmpty,
                                          String note, String category, String difficulty,
                                          String expectRoute)
            throws SQLException {
        String cleanQ = question == null ? "" : question.trim();
        if (cleanQ.isEmpty()) {
            throw new IllegalArgumentException("问题为空");
        }
        String src = SOURCES.contains(source) ? source : "manual";
        List<String> expects = new ArrayList<>();
        if (expectAll != null) {
            for (String e : expectAll) {
                if (e != null && !e.trim().isEmpty()) {
                    expects.add(e.trim());
                }
            }
        }
        String kbVal = kb == null || kb.trim().isEmpty() ? "default" : kb.trim();
        String route = ROUTES.contains(expectRoute) ? expectRoute : null;
        String cat = CATEGORIES.contains(category) ? category
                : (expectEmpty ? "reject"
                : ("direct_hit".equals(src) ? "direct" : ("sql".equals(route) ? "sql" : "concept")));
        String diff = DIFFICULTIES.contains(difficulty) ? difficulty : "medium";

        int inserted;
        try (PreparedStatement ps = conn.prepareStatement(
                "INSERT OR IGNORE INTO eval_cases"
                        + "(kb, question, source, source_ref, expect_all, expect_empty,"
                        + " category, difficulty, note, expect_route)"
                        + " VALUES(?,?,?,?,?,?,?,?,?,?)")) {
            ps.setString(1, kbVal);
            ps.setString(2, cleanQ);
            ps.setString(3, src);
            ps.setString(4, sourceRef);
            ps.setString(5, Json.write(expects));
            ps.setInt(6, expectEmpty ? 1 : 0);
            ps.setString(7, cat);
            ps.setString(8, diff);
            ps.setString(9, note);
            ps.setString(10, route);
            inserted = ps.executeUpdate();
            conn.commit();
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("created", inserted > 0);
        out.put("id", idOf(conn, kbVal, cleanQ));
        return out;
    }

    public static boolean delete(Connection conn, long id) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement("DELETE FROM eval_cases WHERE id=?")) {
            ps.setLong(1, id);
            boolean ok = ps.executeUpdate() > 0;
            conn.commit();
            return ok;
        }
    }

    /** 人工改判（好/坏/待跑）：label 只接受三档；人工结论不写 score，避免和跑分混淆。 */
    public static boolean setVerdict(Connection conn, long id, String verdict, String note)
            throws SQLException {
        if (!VERDICTS.contains(verdict)) {
            throw new IllegalArgumentException("判定只能是 pass / fail / pending：" + verdict);
        }
        try (PreparedStatement ps = conn.prepareStatement(
                "UPDATE eval_cases SET verdict=?, note=COALESCE(?, note),"
                        + " last_run_at=datetime('now','localtime') WHERE id=?")) {
            ps.setString(1, verdict);
            ps.setString(2, note);
            ps.setLong(3, id);
            boolean ok = ps.executeUpdate() > 0;
            conn.commit();
            return ok;
        }
    }

    /**
     * 跑评测后写回判定：score 0~1，detail 是给人看的证据（闸门结论 + 命中/缺失词 + Top 候选）。
     * score 允许 null（未设期望词的题只观察不判分）——别用 0 冒充"判过了"。
     */
    public static void recordResult(Connection conn, long id, String verdict, Double score,
                                    Map<String, Object> detail, String routeActual) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement(
                "UPDATE eval_cases SET verdict=?, last_score=?, last_detail=?, route_actual=?,"
                        + " last_run_at=datetime('now','localtime') WHERE id=?")) {
            ps.setString(1, verdict);
            if (score == null) {
                ps.setNull(2, Types.REAL);
            } else {
                ps.setDouble(2, score);
            }
            ps.setString(3, Json.write(detail == null ? new LinkedHashMap<String, Object>() : detail));
            ps.setString(4, routeActual);
            ps.setLong(5, id);
            ps.executeUpdate();
            conn.commit();
        }
    }

    /**
     * 补/改期望（关键词 or 应拒答）：期望一变，旧判定立即作废回 pending——
     * 拿旧结论配新期望是最容易骗自己的组合。
     */
    public static boolean setExpect(Connection conn, long id, List<String> expectAll, boolean expectEmpty,
                                    String expectRoute) throws SQLException {
        List<String> expects = new ArrayList<>();
        if (expectAll != null) {
            for (String e : expectAll) {
                if (e != null && !e.trim().isEmpty()) {
                    expects.add(e.trim());
                }
            }
        }
        try (PreparedStatement ps = conn.prepareStatement(
                "UPDATE eval_cases SET expect_all=?, expect_empty=?, expect_route=?, verdict='pending',"
                        + " last_score=NULL, last_detail=NULL, route_actual=NULL, last_run_at=NULL WHERE id=?")) {
            ps.setString(1, Json.write(expects));
            ps.setInt(2, expectEmpty ? 1 : 0);
            ps.setString(3, ROUTES.contains(expectRoute) ? expectRoute : null);
            ps.setLong(4, id);
            boolean ok = ps.executeUpdate() > 0;
            conn.commit();
            return ok;
        }
    }

    // ---------------------------------------------------------------- 来源导入

    /**
     * 空表时导入真实资产作种子：**只导直击库**（L0/L1/L2 快问快答，与知识库强相关，
     * 且判定口径明确——该问题必须命中直击库）。
     *
     * 问答日志不自动导：qa_log 里有大量与语料无关的一次性提问（天气、股票、隐私问题），
     * 自动全量灌进来只会把分母变成噪音。要用日志题走页面上的「从问答日志回流」，由人来挑。
     */
    public static int ensureSeed(Connection conn, Settings settings) throws Exception {
        if (scalar(conn, "SELECT COUNT(*) FROM eval_cases", 0) > 0) {
            return 0;
        }
        int n = 0;
        try (Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(
                     "SELECT id, kb, level, question FROM direct_hits WHERE enabled=1 ORDER BY id")) {
            while (rs.next()) {
                String kb = rs.getString("kb");
                String level = rs.getString("level");
                Map<String, Object> r = add(conn, kb, rs.getString("question"), "direct_hit",
                        rs.getString("id"), null, false,
                        "直击库 " + (level == null ? "-" : level)
                                + " 快问快答：回归口径 = 该问题必须命中直击库，掉到检索链路即算坏",
                        "direct", "easy", null);
                if (Boolean.TRUE.equals(r.get("created"))) {
                    n++;
                }
            }
        }
        return n;
    }

    /**
     * 问答日志回流：最近 limit 条去重问题入评测集。
     * kb 按该条 app 在 apps.yaml 的首个知识库推断；app 找不到就落到第一个已知库。
     */
    public static Map<String, Object> importFromQaLog(Connection conn, Settings settings,
                                                      int limit) throws Exception {
        int cap = Math.max(1, Math.min(limit, 200));
        List<String[]> rows = new ArrayList<>();   // [app, question, id, ts]
        try (PreparedStatement ps = conn.prepareStatement(
                "SELECT id, app, question, ts FROM qa_log ORDER BY id DESC LIMIT ?")) {
            ps.setInt(1, cap * 3);   // 先多取：同一句重复问很常见，去重后可能不够 cap
            try (ResultSet rs = ps.executeQuery()) {
                Set<String> seen = new LinkedHashSet<>();
                while (rs.next() && rows.size() < cap) {
                    String q = rs.getString("question");
                    String key = q == null ? "" : q.trim();
                    if (key.isEmpty() || !seen.add(key)) {
                        continue;
                    }
                    rows.add(new String[]{rs.getString("app"), key,
                            String.valueOf(rs.getLong("id")), rs.getString("ts")});
                }
            }
        }
        int added = 0;
        int skipped = 0;
        for (String[] r : rows) {
            String kb = kbOfApp(settings, r[0]);
            Map<String, Object> res = add(conn, kb, r[1], "qa_log", r[2], null, false,
                    "线上真实提问（app=" + (r[0] == null ? "-" : r[0])
                            + "，qa_log#" + r[2] + " " + (r[3] == null ? "" : r[3])
                            + "）：补期望词或标应拒答后再判", "concept", "medium", null);
            if (Boolean.TRUE.equals(res.get("created"))) {
                added++;
            } else {
                skipped++;
            }
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("added", added);
        out.put("skipped", skipped);
        out.put("scanned", rows.size());
        return out;
    }

    // ---------------------------------------------------------------- 内部

    private static String kbOfApp(Settings settings, String app) throws Exception {
        if (app != null && !app.isEmpty()) {
            AppDef def = settings.app(app);
            if (def != null && def.knowledgeBases != null && !def.knowledgeBases.isEmpty()) {
                return def.knowledgeBases.get(0);
            }
        }
        List<String> known = new ArrayList<>(KbWhitelist.all(settings));
        return known.isEmpty() ? "default" : known.get(0);
    }

    private static long idOf(Connection conn, String kb, String question) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement(
                "SELECT id FROM eval_cases WHERE kb=? AND question=?")) {
            ps.setString(1, kb);
            ps.setString(2, question);
            try (ResultSet rs = ps.executeQuery()) {
                return rs.next() ? rs.getLong(1) : -1L;
            }
        }
    }

    /** 行 → 前端可直接消费的结构：expect_all / last_detail 反序列化成数组与对象。 */
    private static Map<String, Object> rowToMap(ResultSet rs) throws SQLException {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", rs.getLong("id"));
        m.put("kb", rs.getString("kb"));
        m.put("question", rs.getString("question"));
        m.put("source", rs.getString("source"));
        m.put("source_ref", rs.getString("source_ref"));
        m.put("expect_all", parseList(rs.getString("expect_all")));
        m.put("expect_empty", rs.getInt("expect_empty") == 1);
        m.put("expect_route", rs.getString("expect_route"));
        m.put("route_actual", rs.getString("route_actual"));
        m.put("category", rs.getString("category"));
        m.put("difficulty", rs.getString("difficulty"));
        m.put("note", rs.getString("note"));
        m.put("verdict", rs.getString("verdict"));
        double score = rs.getDouble("last_score");
        m.put("last_score", rs.wasNull() ? null : score);
        m.put("last_detail", parseMap(rs.getString("last_detail")));
        m.put("last_run_at", rs.getString("last_run_at"));
        m.put("created_at", rs.getString("created_at"));
        return m;
    }

    private static List<String> parseList(String json) {
        if (json == null || json.trim().isEmpty()) {
            return new ArrayList<>();
        }
        try {
            List<String> out = new ArrayList<>();
            Object v = Json.MAPPER.readValue(json, Object.class);
            if (v instanceof List) {
                for (Object o : (List<?>) v) {
                    if (o != null) {
                        out.add(String.valueOf(o));
                    }
                }
            }
            return out;
        } catch (Exception e) {
            return new ArrayList<>();
        }
    }

    private static Map<String, Object> parseMap(String json) {
        if (json == null || json.trim().isEmpty()) {
            return new LinkedHashMap<>();
        }
        try {
            return Json.readMap(json);
        } catch (Exception e) {
            return new LinkedHashMap<>();
        }
    }

    private static void bind(PreparedStatement ps, List<Object> args) throws SQLException {
        for (int i = 0; i < args.size(); i++) {
            Object a = args.get(i);
            if (a instanceof Integer) {
                ps.setInt(i + 1, (Integer) a);
            } else if (a == null) {
                ps.setNull(i + 1, Types.VARCHAR);
            } else {
                ps.setString(i + 1, String.valueOf(a));
            }
        }
    }

    private static Map<String, Object> groupCount(Connection conn, String sql) throws SQLException {
        Map<String, Object> out = new LinkedHashMap<>();
        try (Statement st = conn.createStatement(); ResultSet rs = st.executeQuery(sql)) {
            while (rs.next()) {
                out.put(rs.getString("k") == null ? "-" : rs.getString("k"), rs.getInt("n"));
            }
        }
        return out;
    }

    private static long scalar(Connection conn, String sql, long fallback) throws SQLException {
        try (Statement st = conn.createStatement(); ResultSet rs = st.executeQuery(sql)) {
            return rs.next() ? rs.getLong(1) : fallback;
        }
    }

    private static String one(Connection conn, String sql) throws SQLException {
        try (Statement st = conn.createStatement(); ResultSet rs = st.executeQuery(sql)) {
            return rs.next() ? rs.getString(1) : null;
        }
    }

    private static int num(Object v) {
        return v instanceof Number ? ((Number) v).intValue() : 0;
    }
}
