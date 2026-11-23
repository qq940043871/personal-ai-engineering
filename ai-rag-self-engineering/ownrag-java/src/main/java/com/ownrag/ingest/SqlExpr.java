package com.ownrag.ingest;

/**
 * staging 表全列 TEXT → 可直接用在 SQL 里的表达式。
 *
 * 为什么必须单独有这一层：类型是推断出来的结论，不是表的物理属性。
 * `SUM("金额")` 对 TEXT 恒为 0；`"日期" >= '2024-01-01'` 对 `2024/1/5`、`2024年1月5日` 恒为假。
 * 所以 SQL 生成侧只能用这里的表达式，不能直接用列名裸算（见 docs 10-Excel通道口径.md §六）。
 */
public final class SqlExpr {

    private SqlExpr() {
    }

    /** 列标识符加双引号（staging 表列名可能含中文/数字开头）。 */
    public static String quote(String name) {
        String n = name == null ? "" : name;
        return "\"" + n.replace("\"", "\"\"") + "\"";
    }

    /**
     * 按推断类型给出可安全聚合/比较的表达式。
     * number → 去千分位/百分号后 CAST REAL；date → 归一成 YYYY-MM-DD；其余只 TRIM。
     */
    public static String of(String physical, String type) {
        String q = quote(physical);
        if ("number".equals(type)) {
            return "CAST(REPLACE(REPLACE(TRIM(" + q + "),',',''),'%','') AS REAL)";
        }
        if ("date".equals(type)) {
            return "date(replace(replace(replace(trim(" + q + "),'年','-'),'月','-'),'日',''))";
        }
        return "TRIM(" + q + ")";
    }

    /** 该类型是否允许出现在聚合函数里（text/enum 求和没有意义，直接不给生成机会）。 */
    public static boolean aggregatable(String type) {
        return "number".equals(type);
    }
}
