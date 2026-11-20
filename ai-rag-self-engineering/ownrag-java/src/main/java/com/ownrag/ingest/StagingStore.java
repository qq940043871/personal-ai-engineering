package com.ownrag.ingest;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.List;

/**
 * Excel 链路的动态 staging 表清理（表结构的一半在 DDL 之外：每个 sheet 一张实体表）。
 *
 * 动态表命名由 {@link ExcelStageStep} 决定：`staging_<docId前8位>_<sanitize(sheet)>`，
 * 全列 TEXT + `_src_file` / `_sheet` / `_rownum` 三个溯源列；登记行写在 `staging_registry`。
 *
 * 为什么单独有这个类：删文档 / 库级 purge 只清 chunks/FTS/向量/指纹五处，
 * staging 表与登记行是**第六处**——漏清会留下孤儿表（占空间、重新上传同名 sheet 时靠 DROP IF EXISTS
 * 侥幸覆盖，但库级清空后统计仍留着幽灵文档）。2026-11-20 审查发现并统一收口到这里。
 */
public final class StagingStore {

    private StagingStore() {
    }

    /** 删掉该 doc 的全部 staging 表与登记行，返回被删的表名（供接口回显）。 */
    public static List<String> dropByDoc(Connection conn, String docId) throws SQLException {
        List<String> tables = new ArrayList<>();
        try (PreparedStatement ps = conn.prepareStatement(
                "SELECT table_name FROM staging_registry WHERE doc_id=?")) {
            ps.setString(1, docId);
            try (ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    tables.add(rs.getString(1));
                }
            }
        }
        for (String table : tables) {
            // 表名来自本库登记行（写侧只允许 sanitize 后的 [A-Za-z0-9_]），双引号兜住标识符
            try (Statement st = conn.createStatement()) {
                st.executeUpdate("DROP TABLE IF EXISTS \"" + table.replace("\"", "\"\"") + "\"");
            }
        }
        try (PreparedStatement ps = conn.prepareStatement(
                "DELETE FROM staging_registry WHERE doc_id=?")) {
            ps.setString(1, docId);
            ps.executeUpdate();
        }
        return tables;
    }
}
