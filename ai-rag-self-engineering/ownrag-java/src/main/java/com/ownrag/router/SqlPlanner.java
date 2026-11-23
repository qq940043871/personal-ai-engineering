package com.ownrag.router;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import org.springframework.stereotype.Component;

import com.ownrag.config.AppDef;
import com.ownrag.config.Settings;
import com.ownrag.generate.ChatClient;
import com.ownrag.util.Json;

/**
 * Text2SQL 的"生成 + 校验"两段（docs 11 §四）：
 *
 * 生成：一次 LLM 调用，输入只有"选定表的结构（含 sql_expr）+ 值提示 + 问题"。
 * 校验：**纯代码、可单测**。模型写什么都不能直接跑——白名单、单语句、禁注释、强制 LIMIT
 *       全部在这里落地。校验失败的错误信息会回喂一次让模型改，改不对就降级（绝不执行）。
 *
 * 为什么 sql_expr 必须进 prompt：staging 全列 TEXT，`SUM("金额")` 恒为 0。
 * 不给表达式，模型会写出"看起来对、算出来是 0"的 SQL，而 0 比报错更危险。
 */
@Component
public class SqlPlanner {

    private static final Pattern FORBIDDEN = Pattern.compile(
            "\\b(insert|update|delete|drop|alter|create|attach|detach|pragma|vacuum|reindex|trigger|load_extension)\\b");
    private static final Pattern FROM_JOIN = Pattern.compile(
            "(?i)\\b(?:from|join)\\s+(\"([^\"]+)\"|([A-Za-z_][A-Za-z0-9_]*))");
    private static final Pattern LIMIT_END = Pattern.compile("(?i)\\blimit\\s+(\\d+)\\s*$");

    public static class Plan {
        public boolean ok;
        public String sql;
        public String reason = "";
        public String error = "";
    }

    /**
     * 生成一条 SQL。lastError 非空 = 第二次尝试（把上一次的校验/执行错误回喂）。
     * 失败不抛异常：调用方按"降级"处理，降级路径本身就是契约的一部分。
     */
    public Plan plan(Settings settings, ChatClient chat, AppDef app, String question,
                     List<TableCatalog.TableInfo> tables, String lastError) {
        Plan plan = new Plan();
        if (tables == null || tables.isEmpty()) {
            plan.error = "无候选表";
            return plan;
        }
        List<Map<String, Object>> messages = new ArrayList<>();
        Map<String, Object> system = new LinkedHashMap<>();
        system.put("role", "system");
        system.put("content", "你是 SQL 生成器。只输出 JSON：{\"sql\":\"...\",\"reason\":\"...\"}，不要输出任何解释文字。");
        messages.add(system);
        Map<String, Object> user = new LinkedHashMap<>();
        user.put("role", "user");
        user.put("content", prompt(question, tables, app.sqlMaxRows, lastError));
        messages.add(user);
        String raw;
        try {
            raw = chat.chat(settings, messages, null, 4096, 0.0, 512);
        } catch (ChatClient.ChatError e) {
            plan.error = "SQL 生成调用失败：" + e.getMessage();
            return plan;
        }
        String sql = extractSql(raw);
        if (sql == null || sql.trim().isEmpty()) {
            plan.error = "模型未返回 SQL：" + clip(raw, 200);
            return plan;
        }
        try {
            Set<String> allowed = new LinkedHashSet<>();
            for (TableCatalog.TableInfo t : tables) {
                allowed.add(t.table);
            }
            plan.sql = validate(sql, allowed, app.sqlMaxRows);
            plan.reason = clip(reasonOf(raw), 200);
            plan.ok = true;
        } catch (IllegalArgumentException e) {
            plan.error = e.getMessage();
        }
        return plan;
    }

    // ---------------------------------------------------------------- 校验（纯函数）

    /**
     * 把模型产出的 SQL 收敛成"可以放心执行"的形态：不合法就抛 IllegalArgumentException（消息回喂重写）。
     * 这里没有"尽力修补"——白名单/单语句/禁注释三类直接拒绝，只对 LIMIT 做钳制（它是护栏不是语义）。
     */
    public static String validate(String raw, Set<String> allowedTables, int maxRows) {
        String sql = stripFences(raw == null ? "" : raw).trim();
        if (sql.isEmpty()) {
            throw new IllegalArgumentException("空 SQL");
        }
        while (sql.endsWith(";")) {
            sql = sql.substring(0, sql.length() - 1).trim();
        }
        if (sql.contains(";")) {
            throw new IllegalArgumentException("只允许单条语句（检测到分号分隔的多语句）");
        }
        String lower = sql.toLowerCase(Locale.ROOT);
        if (!lower.startsWith("select") && !lower.startsWith("with")) {
            throw new IllegalArgumentException("只允许 SELECT / WITH 查询，实际以「" + clip(sql, 20) + "」开头");
        }
        if (lower.contains("--") || lower.contains("/*") || lower.contains("*/")) {
            throw new IllegalArgumentException("禁止 SQL 注释（-- 或 /* */），这是注入面");
        }
        Matcher fw = FORBIDDEN.matcher(lower);
        if (fw.find()) {
            throw new IllegalArgumentException("禁止关键字：" + fw.group(1));
        }
        if (lower.contains("sqlite_")) {
            throw new IllegalArgumentException("禁止访问 sqlite_ 系统表");
        }
        Matcher tm = FROM_JOIN.matcher(sql);
        int tables = 0;
        while (tm.find()) {
            String name = tm.group(2) != null ? tm.group(2) : tm.group(3);
            if (!allowedTables.contains(name)) {
                throw new IllegalArgumentException("表不在候选白名单：" + name
                        + "（可选：" + allowedTables + "）");
            }
            tables++;
        }
        if (tables == 0) {
            throw new IllegalArgumentException("未找到 FROM 子句中的表名");
        }
        Matcher lm = LIMIT_END.matcher(sql);
        if (lm.find()) {
            int n;
            try {
                n = Integer.parseInt(lm.group(1));
            } catch (NumberFormatException e) {
                n = maxRows;
            }
            if (n > maxRows || n <= 0) {
                sql = sql.substring(0, lm.start()) + "LIMIT " + maxRows;
            }
        } else {
            sql = sql + " LIMIT " + maxRows;
        }
        return sql;
    }

    static String stripFences(String s) {
        String out = s;
        int i = out.indexOf("```");
        if (i >= 0) {
            out = out.substring(i + 3);
            int nl = out.indexOf('\n');
            if (nl >= 0 && !out.substring(0, nl).toLowerCase(Locale.ROOT).contains("select")) {
                out = out.substring(nl + 1);   // 去掉 ```sql 这类语言标注
            }
            int end = out.indexOf("```");
            if (end >= 0) {
                out = out.substring(0, end);
            }
        }
        return out;
    }

    /** 从模型输出里取 SQL：优先 JSON 的 sql 字段，其次从第一个 SELECT/WITH 开始截。 */
    static String extractSql(String raw) {
        if (raw == null) {
            return null;
        }
        String body = stripFences(raw);
        int lb = body.indexOf('{');
        int rb = body.lastIndexOf('}');
        if (lb >= 0 && rb > lb) {
            try {
                com.fasterxml.jackson.databind.JsonNode node = Json.MAPPER.readTree(body.substring(lb, rb + 1));
                if (node.hasNonNull("sql")) {
                    return node.get("sql").asText();
                }
            } catch (Exception ignored) {
                // 不是合法 JSON → 走下面的文本截取
            }
        }
        String lower = body.toLowerCase(Locale.ROOT);
        int s = lower.indexOf("select");
        int w = lower.indexOf("with ");
        int start = s < 0 ? w : (w < 0 ? s : Math.min(s, w));
        return start < 0 ? null : body.substring(start).trim();
    }

    private static String reasonOf(String raw) {
        int lb = raw == null ? -1 : raw.indexOf('{');
        int rb = raw == null ? -1 : raw.lastIndexOf('}');
        if (lb >= 0 && rb > lb) {
            try {
                com.fasterxml.jackson.databind.JsonNode node = Json.MAPPER.readTree(raw.substring(lb, rb + 1));
                if (node.hasNonNull("reason")) {
                    return node.get("reason").asText();
                }
            } catch (Exception ignored) {
                // reason 只是给人看的，拿不到就算了
            }
        }
        return "";
    }

    // ---------------------------------------------------------------- prompt

    private static String prompt(String question, List<TableCatalog.TableInfo> tables,
                                 int maxRows, String lastError) {
        StringBuilder sb = new StringBuilder();
        sb.append("【可选表与列】\n");
        for (TableCatalog.TableInfo t : tables) {
            sb.append("表 ").append(t.table).append("（").append(t.label())
                    .append("，约 ").append(t.rows).append(" 行）\n");
            for (Map<String, Object> c : t.columns) {
                sb.append("  - 列「").append(c.get("column")).append("」 类型=").append(c.get("type"))
                        .append(" 物理名=").append(c.get("physical"))
                        .append(" 表达式=").append(c.get("sql_expr")).append('\n');
            }
            if (t.pk != null) {
                sb.append("  - 主键候选：").append(t.pk).append('\n');
            }
            List<String> values = TableCatalog.valueHits(t, question);
            if (!values.isEmpty()) {
                sb.append("  - 问题中出现的取值：").append(String.join("、", values)).append('\n');
            }
        }
        sb.append("\n【硬性规则】\n")
                .append("1. 只生成一条 SELECT（可带 WITH），不要写分号\n")
                .append("2. 表名只能从上面列出的表里选，用双引号包裹\n")
                .append("3. 数值列必须用给定的「表达式」参与聚合/比较，例如 SUM(CAST(... AS REAL))；")
                .append("直接 SUM(\"列\") 恒为 0\n")
                .append("4. 日期列必须用给定的 date() 表达式比较或分组\n")
                .append("5. 不要 SELECT *；只选需要的列，聚合结果用中文别名\n")
                .append("6. 不要写 LIMIT（外层会加，最多 ").append(maxRows).append(" 行）\n")
                .append("7. 问题里的筛选条件必须落到 WHERE；枚举取值优先用样本里出现过的值\n")
                .append("8. 如果问题无法用这些表回答，sql 返回空字符串\n");
        if (lastError != null && !lastError.isEmpty()) {
            sb.append("\n【上一次尝试失败】\n").append(lastError)
                    .append("\n请修正后重新输出 JSON。\n");
        }
        sb.append("\n【问题】\n").append(question);
        return sb.toString();
    }

    private static String clip(String s, int max) {
        String v = s == null ? "" : s.replaceAll("\\s+", " ").trim();
        return v.length() <= max ? v : v.substring(0, max) + "…";
    }
}
