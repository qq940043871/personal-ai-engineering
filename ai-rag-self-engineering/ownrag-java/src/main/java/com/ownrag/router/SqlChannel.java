package com.ownrag.router;

import java.sql.Connection;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.stereotype.Component;

import com.ownrag.config.AppDef;
import com.ownrag.config.Settings;
import com.ownrag.generate.ChatClient;

/**
 * SQL 通道（docs 11 §四）：定位表 → 生成 SQL → 校验 → 只读执行 → 装配成**一个**证据块。
 *
 * 一条查询只产出一个块（不是一个结果行一个块）：聚合结果是一张表，切成行块既无意义、
 * 又会把预算吃光，还会让"块 N"的引用失去可读性。
 *
 * 失败一律走降级而不是抛异常：SQL 生成失败时把「表结构 + 样本」当证据给模型，
 * 让它据实说"无法统计"，**绝不放行编造数字**。
 */
@Component
public class SqlChannel {

    private final SqlPlanner planner;

    public SqlChannel(SqlPlanner planner) {
        this.planner = planner;
    }

    public static class Outcome {
        public boolean hasEvidence;
        public boolean degraded;
        public String note = "";
        public String sql = "";
        public int rowCount;
        public boolean truncated;
        public double ms;
        public String label = "";
        public final List<Map<String, Object>> candidates = new ArrayList<>();
        public final List<Map<String, Object>> targets = new ArrayList<>();

        public Map<String, Object> detail() {
            Map<String, Object> d = new LinkedHashMap<>();
            d.put("sql", sql);
            d.put("rows", rowCount);
            d.put("truncated", truncated);
            d.put("ms", ms);
            d.put("degraded", degraded);
            d.put("note", note);
            d.put("target", label);
            return d;
        }
    }

    public Outcome run(Connection conn, Settings settings, ChatClient chat, AppDef app,
                       String question, List<String> kbs) throws Exception {
        return run(conn, settings, chat, app, question, kbs, true);
    }

    /**
     * @param loggedIn 为 false 时目录里只有公开文档的表：SQL 通道出的是**整表聚合数字**，
     *                 一旦把「需登录」的 Excel 放进候选，匿名用户问一句"合计多少"就能拿到全表明细，
     *                 比 RAG 泄漏一个片段严重得多。与检索层同一条口径，过滤发生在选表之前。
     */
    public Outcome run(Connection conn, Settings settings, ChatClient chat, AppDef app,
                       String question, List<String> kbs, boolean loggedIn) throws Exception {
        Outcome out = new Outcome();
        List<TableCatalog.TableInfo> all = TableCatalog.list(conn, kbs, loggedIn);
        if (all.isEmpty()) {
            out.note = "该知识库没有可查询的 Excel 表（staging_registry 为空）";
            return out;
        }
        List<TableCatalog.TableInfo> picked = TableCatalog.pick(all, question, app.sqlMaxTables);
        if (picked.isEmpty()) {
            out.note = "库里有 " + all.size() + " 张表，但问题里没有指向任何一张（缺表名/列名线索）";
            return out;
        }
        for (TableCatalog.TableInfo t : picked) {
            Map<String, Object> target = new LinkedHashMap<>();
            target.put("kb", t.kb);
            target.put("doc_id", t.docId);
            target.put("doc_name", t.docName);
            target.put("table", t.table);
            target.put("sheet", t.sheet);
            out.targets.add(target);
        }
        out.label = picked.get(0).label();

        SqlPlanner.Plan plan = planner.plan(settings, chat, app, question, picked, null);
        if (!plan.ok) {
            // 第二次：把校验错误回喂（只一次——修两次还不对，说明问题本身不可 SQL 化，该降级）
            plan = planner.plan(settings, chat, app, question, picked, plan.error);
        }
        if (!plan.ok) {
            out.degraded = true;
            out.note = "SQL 生成失败：" + plan.error;
            out.hasEvidence = true;
            out.candidates.add(evidenceFromSchema(picked, out.note));
            return out;
        }
        out.sql = plan.sql;
        SqlExecutor.Result res = SqlExecutor.execute(settings.getDbPath(), plan.sql,
                app.sqlMaxRows, app.sqlTimeoutMs, out.label);
        out.ms = res.ms;
        out.rowCount = res.rows.size();
        out.truncated = res.truncated;
        if (!res.ok) {
            out.degraded = true;
            out.note = "SQL 执行失败：" + res.error;
            out.hasEvidence = true;
            out.candidates.add(evidenceFromSchema(picked, out.note));
            return out;
        }
        out.hasEvidence = true;
        out.candidates.add(evidenceOf(picked.get(0), res.text));
        return out;
    }

    /** 成功路径：结果表 + SQL 全文口径，一个块。 */
    private static Map<String, Object> evidenceOf(TableCatalog.TableInfo t, String text) {
        return base(t, text);
    }

    /** 降级路径：表结构 + 样本，明确写"无法统计"，不给模型任何可抄的数字。 */
    private static Map<String, Object> evidenceFromSchema(List<TableCatalog.TableInfo> tables, String note) {
        StringBuilder sb = new StringBuilder();
        sb.append("【未能生成可执行查询】").append(note).append('\n');
        sb.append("下面是可查询的表结构；请据此说明「无法给出精确统计」，不要推算数字。\n");
        for (TableCatalog.TableInfo t : tables) {
            sb.append("- 表 ").append(t.table).append("（").append(t.label())
                    .append("，约 ").append(t.rows).append(" 行）：");
            List<String> cols = new ArrayList<>();
            for (Map<String, Object> c : t.columns) {
                cols.add(String.valueOf(c.get("column")) + "(" + c.get("type") + ")");
            }
            sb.append(String.join("、", cols)).append('\n');
        }
        return base(tables.get(0), sb.toString());
    }

    private static Map<String, Object> base(TableCatalog.TableInfo t, String text) {
        Map<String, Object> c = new LinkedHashMap<>();
        c.put("chunk_id", "sql:" + (t.docId == null ? "na" : t.docId.substring(0, Math.min(8, t.docId.length())))
                + ":" + Integer.toHexString(Math.abs(text.hashCode())));
        c.put("doc_id", t.docId);
        c.put("doc_name", t.docName);
        c.put("kb", t.kb);
        c.put("ordinal", 0);          // 由 ChatController 统一编号（保证"块 N"全文唯一）
        c.put("text", text);
        Map<String, Object> anchors = new LinkedHashMap<>();
        anchors.put("table", t.table);
        anchors.put("sheet", t.sheet);
        c.put("anchors", anchors);
        c.put("meta", new LinkedHashMap<String, Object>());
        c.put("kind", "sql");
        c.put("trust", "high");
        c.put("rrf", 1.0);
        List<Map<String, Object>> channels = new ArrayList<>();
        Map<String, Object> ch = new LinkedHashMap<>();
        ch.put("channel", "sql");
        ch.put("score", 1.0);
        channels.add(ch);
        c.put("channels", channels);
        return c;
    }
}
