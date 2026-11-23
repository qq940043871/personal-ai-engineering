package com.ownrag.router;

import java.nio.file.Path;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.List;

import com.ownrag.core.Db;

/**
 * 只读执行器（docs 11 §四.4）：独立连接 + `PRAGMA query_only=1` + 超时 + `maxRows` 上限。
 *
 * 为什么用独立连接而不是复用请求连接：请求连接是读写混用的（后面还要写 trace/qa_log），
 * 而这里跑的是一段模型生成的 SQL。**连接级只读**是最后一道保险——即使校验漏了某个写语句，
 * SQLite 也会直接拒绝，不会污染主库。
 */
public final class SqlExecutor {

    private SqlExecutor() {
    }

    /** 一次查询的结果 + 渲染好的证据文本。 */
    public static class Result {
        public boolean ok;
        public String error;
        public String sql = "";
        public List<String> headers = new ArrayList<>();
        public List<List<String>> rows = new ArrayList<>();
        public boolean truncated;
        public double ms;
        /** 证据块的正文（含 SQL 口径），进 prompt 与引用校验都用这一份。 */
        public String text = "";
    }

    public static Result execute(Path dbPath, String sql, int maxRows, int timeoutMs, String label) {
        long t0 = System.nanoTime();
        Result r = new Result();
        r.sql = sql;
        int limit = Math.max(1, maxRows);
        try (Connection conn = Db.connect(dbPath)) {
            try (Statement pragma = conn.createStatement()) {
                pragma.execute("PRAGMA query_only=1;");
            }
            try (Statement st = conn.createStatement()) {
                try {
                    st.setQueryTimeout(Math.max(1, timeoutMs / 1000));
                } catch (SQLException ignored) {
                    // 驱动不支持查询超时时靠 LIMIT + query_only 兜底（降级可见：不静默宣称有超时）
                }
                try (ResultSet rs = st.executeQuery(sql)) {
                    ResultSetMetaData md = rs.getMetaData();
                    int cols = md.getColumnCount();
                    for (int i = 1; i <= cols; i++) {
                        r.headers.add(md.getColumnLabel(i));
                    }
                    while (rs.next()) {
                        if (r.rows.size() >= limit) {
                            r.truncated = true;
                            break;
                        }
                        List<String> row = new ArrayList<>();
                        for (int i = 1; i <= cols; i++) {
                            String v = rs.getString(i);
                            row.add(v == null ? "" : v);
                        }
                        r.rows.add(row);
                    }
                }
            }
            r.ok = true;
        } catch (SQLException e) {
            r.error = e.getMessage();
        }
        r.ms = Math.round((System.nanoTime() - t0) / 1e5) / 10.0;
        if (r.ok) {
            r.text = render(r, label, limit);
        }
        return r;
    }

    /**
     * 证据块正文：**必须带 SQL 全文与行数口径**。
     * 没有 SQL 的数字等于没有出处——引用校验和事后复盘都靠它，不是给模型看的装饰。
     */
    static String render(Result r, String label, int limit) {
        StringBuilder sb = new StringBuilder();
        sb.append("【SQL 查询结果｜来源：").append(label == null ? "staging" : label)
                .append("｜返回 ").append(r.rows.size()).append(" 行")
                .append(r.truncated ? "（已截断到 " + limit + " 行，实际更多）" : "（未截断）")
                .append("】\n");
        sb.append("SQL: ").append(r.sql).append('\n');
        if (r.rows.isEmpty()) {
            sb.append("（该条件下没有记录）");
            return sb.toString();
        }
        sb.append('|').append(String.join(" | ", r.headers)).append(" |\n");
        List<String> sep = new ArrayList<>();
        for (int i = 0; i < r.headers.size(); i++) {
            sep.add("---");
        }
        sb.append('|').append(String.join(" | ", sep)).append(" |\n");
        for (List<String> row : r.rows) {
            List<String> cells = new ArrayList<>();
            for (String v : row) {
                cells.add(cell(v));
            }
            sb.append('|').append(String.join(" | ", cells)).append(" |\n");
        }
        sb.append("（执行耗时 ").append(r.ms).append("ms）");
        return sb.toString();
    }

    private static String cell(String v) {
        String s = v == null ? "" : v.trim().replace("|", "\\|").replaceAll("\\s+", " ");
        return s.length() <= 80 ? s : s.substring(0, 80) + "…";
    }
}
