package com.ownrag.router;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

import org.springframework.stereotype.Component;

import com.ownrag.config.AppDef;

/**
 * 查询期路由（docs 11-查询路由与多源编排.md §二/§三）：
 *
 *   L0 强制：请求体 `route` 指定 → 直接采纳（仍做可用性校验）
 *   L1 规则：信号词打分。命中即短路，不花任何模型钱
 *   L2 结构：可用性掩码——**先看有没有这类数据，再看想问什么**
 *   L3 LLM：本期关闭（AppDef.routingLlmClassify，默认 false）
 *
 * 三条不可动摇的口径：
 *   ① 路由只读原问题，不做改写（改写服务召回通道，与直击库"用原问题精确匹配"一致）；
 *   ② 不可用的通道权重直接抹成负无穷，不允许"判成 SQL 却没表"时悄悄回落 RAG 假装回答；
 *   ③ 规则命中就不调模型——低置信才考虑花第二次钱（本期直接按 on_low_confidence 兜底）。
 */
@Component
public class QueryRouter {

    /** 掩码后的分数：比任何真实得分都低，argmax 永远不会选到它。 */
    private static final int MASKED = -999;
    /** 置信度归一化分母：最高分 5 分 ≈ 100% 确信（一个表名命中 + 一个聚合词就到顶）。 */
    private static final double CONF_DENOM = 5.0;

    private static final class Rule {
        final String name;
        final Pattern rx;
        final String route;
        final int weight;

        Rule(String name, String rx, String route, int weight) {
            this.name = name;
            this.rx = Pattern.compile(rx);
            this.route = route;
            this.weight = weight;
        }
    }

    /**
     * 信号词表（进 Git，随评测集回归）。同一族只记一次分——"多少...总计..."重复出现不代表更确信，
     * 只会让长问题系统性偏向 SQL。
     */
    private static final List<Rule> RULES = new ArrayList<>();

    static {
        RULES.add(new Rule("汇总/统计词",
                "多少|总计|合计|一共|总共|汇总|统计|求和|总额|总金额|合计金额|平均|均值|最大|最小|最高|最低|占比|比例|环比|同比|按月|按季|前\\s*\\d+|排名",
                RouteResult.SQL, 2));
        RULES.add(new Rule("明细/筛选词",
                "大于|小于|超过|低于|高于|不低于|不超过|介于|分别|列出|清单|明细|哪些|排序",
                RouteResult.SQL, 1));
        RULES.add(new Rule("数字口径词",
                "元|万元|亿元|%|％|笔数|单号|条数",
                RouteResult.SQL, 1));
        RULES.add(new Rule("知识型词",
                "为什么|怎么|如何|流程|标准|规定|区别|差异|原理|依据|方案|建议|注意|是什么|定义|含义|步骤|要点",
                RouteResult.RAG, 2));
        RULES.add(new Rule("内部资料词",
                "公司|内部|制度|合同|纪要|条款|政策|规范|手册|办法",
                RouteResult.RAG, 2));
        RULES.add(new Rule("时效/外网词",
                "最新|今天|最近|本周|本月|实时|现在|新闻|官网|公告|汇率|天气|上网|网上|搜一下",
                RouteResult.WEB, 3));
    }

    /**
     * 一次路由。forced 来自请求体（null 或 "auto" = 不强制）。
     * conn 只用于读目录与统计块数，不写任何东西。
     */
    public RouteResult route(Connection conn, AppDef app, List<String> kbs, String question, String forced)
            throws SQLException {
        return route(conn, app, kbs, question, forced, true);
    }

    /**
     * 带登录态的重载：`loggedIn=false` 时只看得到公开文档的表——否则路由会说"SQL 可用"，
     * 实际却一张表都选不出来，用户看到的是"库里没有可查询的结构化数据"这种误导性结论。
     */
    public RouteResult route(Connection conn, AppDef app, List<String> kbs, String question, String forced,
                             boolean loggedIn) throws SQLException {
        long t0 = System.nanoTime();
        RouteResult r = new RouteResult();
        boolean allowSql = allowed(app, RouteResult.SQL);
        boolean allowRag = allowed(app, RouteResult.RAG);

        List<TableCatalog.TableInfo> tables = allowSql
                ? TableCatalog.list(conn, kbs, loggedIn) : new ArrayList<>();
        boolean sqlAvail = allowSql && !tables.isEmpty();
        boolean ragAvail = allowRag && hasRagChunks(conn, kbs);
        // 联网本期不实现：没有 search 端点、没有引用契约，判进来只会答不出处。恒不可用是诚实的。
        boolean webAvail = false;
        r.availability.put("sql", sqlAvail);
        r.availability.put("rag", ragAvail);
        r.availability.put("web", webAvail);

        int sqlScore = 0;
        int ragScore = 1;   // RAG 是基线：没有明确信号时，知识库问答是默认行为
        int webScore = 0;

        // 表/列显式指称是最强信号（用户点名了数据在哪），但它命中的前提是库里真有表
        if (allowSql && !tables.isEmpty()) {
            List<TableCatalog.TableInfo> hits = TableCatalog.pick(tables, question, app.sqlMaxTables);
            boolean named = false;
            for (TableCatalog.TableInfo t : hits) {
                if (TableCatalog.columnHits(t, question).size() > 0 || mentionsTable(t, question)) {
                    named = true;
                    break;
                }
            }
            if (named) {
                sqlScore += 3;
                r.signals.add(signal("表/列指称", 3, RouteResult.SQL));
            }
        }

        String q = question == null ? "" : question;
        for (Rule rule : RULES) {
            if (!rule.rx.matcher(q).find()) {
                continue;
            }
            r.signals.add(signal(rule.name, rule.weight, rule.route));
            if (RouteResult.SQL.equals(rule.route)) {
                sqlScore += rule.weight;
            } else if (RouteResult.RAG.equals(rule.route)) {
                ragScore += rule.weight;
            } else {
                webScore += rule.weight;
            }
        }
        // 知识型词与聚合词同时出现时，RAG 基线会被聚合词抵掉：避免"为什么本月总报销变高了"被判成纯 RAG
        if (ragScore < 1) {
            ragScore = 1;
        }

        String forcedRoute = normalizeForced(forced);
        if (forcedRoute != null) {
            r.layer = "forced";
            r.route = forcedRoute;
            r.confidence = 1.0;
            r.reason = "请求体强制指定 route=" + forcedRoute;
            if (!allowed(app, forcedRoute) || (RouteResult.SQL.equals(forcedRoute) && !sqlAvail)) {
                r.route = resolveFallback(app, sqlAvail, ragAvail);
                r.layer = "fallback";
                r.confidence = 0;
                r.reason += "；但该通道不可用（白名单/无表），已回落 " + r.route;
            }
        } else {
            RouteResult decided = decide(sqlScore, ragScore, webScore, sqlAvail, ragAvail, webAvail, app);
            r.route = decided.route;
            r.layer = decided.layer;
            r.confidence = decided.confidence;
            r.reason = decided.reason
                    + "；得分 sql=" + sqlScore + " rag=" + ragScore + " web=" + webScore;
        }

        if (r.usesSql()) {
            List<TableCatalog.TableInfo> picked = TableCatalog.pick(tables, q, app.sqlMaxTables);
            for (TableCatalog.TableInfo t : picked) {
                Map<String, Object> target = new LinkedHashMap<>();
                target.put("kb", t.kb);
                target.put("doc_id", t.docId);
                target.put("doc_name", t.docName);
                target.put("table", t.table);
                target.put("sheet", t.sheet);
                r.targets.add(target);
            }
            if (r.targets.isEmpty()) {
                // 判成 SQL 却没定位到表：这是"缺目标"，不是"缺数据"，必须显式降级
                r.route = resolveFallback(app, sqlAvail, ragAvail);
                if (r.layer == null || "rule".equals(r.layer)) {
                    r.layer = "structure";
                }
                r.reason += "；但未定位到目标表，已回落 " + r.route;
            }
        }
        r.ms = Math.round((System.nanoTime() - t0) / 1e5) / 10.0;
        return r;
    }

    /**
     * 纯函数定案（单测直击，不需要 DB）：
     * 掩码 → 跨源 → argmax → 置信度 → 低置信兜底。
     */
    public static RouteResult decide(int sqlScore, int ragScore, int webScore,
                                     boolean sqlAvail, boolean ragAvail, boolean webAvail,
                                     AppDef app) {
        RouteResult r = new RouteResult();
        r.availability.put("sql", sqlAvail);
        r.availability.put("rag", ragAvail);
        r.availability.put("web", webAvail);

        int s = sqlAvail ? sqlScore : MASKED;
        int g = ragAvail ? ragScore : MASKED;
        int w = webAvail ? webScore : MASKED;
        int best = Math.max(s, Math.max(g, w));

        if (best <= 0) {
            r.route = resolveFallback(app, sqlAvail, ragAvail);
            r.layer = "fallback";
            r.confidence = 0;
            r.reason = "无有效信号，按 on_low_confidence 兜底";
            return r;
        }

        // 跨源：既要算又要读规定。单选任何一路都答不全（原方案最缺的一格）
        if (sqlAvail && ragAvail && sqlScore >= 3 && ragScore >= 3) {
            r.route = RouteResult.MULTI;
            r.layer = "rule";
            r.confidence = Math.min(1.0, Math.max(sqlScore, ragScore) / CONF_DENOM);
            r.reason = "同时命中结构化数据指称与知识型词，走 MULTI（SQL + RAG 双通道）";
            return r;
        }

        String winner;
        if (s == best) {
            winner = RouteResult.SQL;
        } else if (g == best) {
            winner = RouteResult.RAG;
        } else {
            winner = RouteResult.WEB;
        }
        r.route = winner;
        r.confidence = Math.min(1.0, (double) best / CONF_DENOM);
        // 掩码改变了结论（最高分的那个通道不可用）→ layer 记 structure：
        // 观测页要能一眼分清"判错了"和"库里没这类数据"，两者的修法完全不同
        int rawBest = Math.max(sqlScore, Math.max(ragScore, webScore));
        boolean masked = (rawBest == sqlScore && !sqlAvail)
                || (rawBest == ragScore && !ragAvail)
                || (rawBest == webScore && !webAvail);
        r.layer = masked ? "structure" : "rule";
        r.reason = masked ? "最高分通道不可用（缺数据/未配置），已回落" : "规则打分定案";

        double minConf = app == null ? 0.4 : app.routingMinConfidence;
        if (r.confidence < minConf) {
            String low = app == null ? RouteResult.RAG : app.routingLowConfidence;
            String before = r.route;
            r.route = available(low, sqlAvail, ragAvail) ? low : resolveFallback(app, sqlAvail, ragAvail);
            // 结论没变（例如本来就是 rag）就别把"缺数据(structure)"这个更有信息量的原因覆盖成 fallback
            if (!before.equals(r.route)) {
                r.layer = "fallback";
            }
            r.reason += "；置信度 " + round3(r.confidence) + " < " + minConf + "，按 on_low_confidence 兜底";
        }
        return r;
    }

    // ---------------------------------------------------------------- 内部

    /** 该库有没有"非 Excel 行卡片"的块——没有就说明 RAG 通道答不出东西。 */
    private boolean hasRagChunks(Connection conn, List<String> kbs) throws SQLException {
        StringBuilder sql = new StringBuilder(
                "SELECT COUNT(*) FROM chunks c LEFT JOIN documents d ON d.doc_id=c.doc_id "
                        + "WHERE COALESCE(d.enabled,1)=1 AND COALESCE(c.source_type,'')<>'excel'");
        if (kbs != null && !kbs.isEmpty()) {
            sql.append(" AND c.kb IN (");
            for (int i = 0; i < kbs.size(); i++) {
                sql.append(i == 0 ? "?" : ",?");
            }
            sql.append(")");
        }
        try (PreparedStatement ps = conn.prepareStatement(sql.toString())) {
            int i = 1;
            if (kbs != null) {
                for (String kb : kbs) {
                    ps.setString(i++, kb);
                }
            }
            try (ResultSet rs = ps.executeQuery()) {
                return rs.next() && rs.getLong(1) > 0;
            }
        }
    }

    private static boolean mentionsTable(TableCatalog.TableInfo t, String q) {
        if (q == null) {
            return false;
        }
        return (t.sheet != null && t.sheet.length() >= 2 && q.contains(t.sheet))
                || (t.table != null && q.contains(t.table));
    }

    private static boolean allowed(AppDef app, String route) {
        if (RouteResult.WEB.equals(route)) {
            return false;   // 本期不实现联网：白名单写了也不放行
        }
        return app == null || app.routingAllow.contains(route) || app.routingAllow.isEmpty();
    }

    private static boolean available(String route, boolean sqlAvail, boolean ragAvail) {
        if (RouteResult.SQL.equals(route)) {
            return sqlAvail;
        }
        if (RouteResult.RAG.equals(route)) {
            return ragAvail;
        }
        return false;   // multi/web 不作兜底：兜底要的是"一定能答"的通道
    }

    /** 兜底通道：优先配置的 default，其次任何可用通道，都没有就 rag（拒答由闸门一负责）。 */
    static String resolveFallback(AppDef app, boolean sqlAvail, boolean ragAvail) {
        String dft = app == null ? RouteResult.RAG : app.routingDefault;
        if (available(dft, sqlAvail, ragAvail)) {
            return dft;
        }
        if (ragAvail) {
            return RouteResult.RAG;
        }
        if (sqlAvail) {
            return RouteResult.SQL;
        }
        return RouteResult.RAG;
    }

    private static String normalizeForced(String forced) {
        if (forced == null) {
            return null;
        }
        String f = forced.trim().toLowerCase();
        if (f.isEmpty() || "auto".equals(f)) {
            return null;
        }
        return f;
    }

    private static Map<String, Object> signal(String name, int weight, String route) {
        Map<String, Object> s = new LinkedHashMap<>();
        s.put("name", name);
        s.put("weight", weight);
        s.put("route", route);
        return s;
    }

    private static double round3(double v) {
        return Math.round(v * 1000) / 1000.0;
    }
}
