package com.ownrag.ingest;

import java.nio.file.Path;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.List;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import com.ownrag.core.Db;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Excel 动态 staging 表清理回归（2026-11-20 审查发现）：
 * 删文档 / 库级 purge 若不一起清 `staging_*` 与 `staging_registry`，就会留下孤儿表
 * （统计里还有幽灵文档、同名 sheet 重灌靠 DROP IF EXISTS 侥幸覆盖）。
 */
class StagingStoreTest {

    @TempDir
    Path tmp;

    private static boolean tableExists(Connection conn, String name) throws Exception {
        try (PreparedStatement ps = conn.prepareStatement(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?")) {
            ps.setString(1, name);
            try (ResultSet rs = ps.executeQuery()) {
                return rs.next();
            }
        }
    }

    private static int registryRows(Connection conn, String docId) throws Exception {
        try (PreparedStatement ps = conn.prepareStatement(
                "SELECT COUNT(*) FROM staging_registry WHERE doc_id=?")) {
            ps.setString(1, docId);
            try (ResultSet rs = ps.executeQuery()) {
                return rs.next() ? rs.getInt(1) : 0;
            }
        }
    }

    @Test
    void 删文档时清掉动态表与登记行() throws Exception {
        Path db = tmp.resolve("staging.db");
        Db.initSchema(db);
        try (Connection conn = Db.connect(db)) {
            try (Statement st = conn.createStatement()) {
                st.executeUpdate("CREATE TABLE \"staging_doc1_Sheet1\" (\"a\" TEXT, \"_rownum\" INTEGER)");
                st.executeUpdate("CREATE TABLE \"staging_doc1_Sheet2\" (\"a\" TEXT, \"_rownum\" INTEGER)");
            }
            try (PreparedStatement ps = conn.prepareStatement(
                    "INSERT INTO staging_registry(doc_id, table_name, sheet, schema_json) VALUES (?,?,?,?)")) {
                ps.setString(1, "doc1");
                ps.setString(2, "staging_doc1_Sheet1");
                ps.setString(3, "Sheet1");
                ps.setString(4, "{}");
                ps.executeUpdate();
                ps.setString(1, "doc1");
                ps.setString(2, "staging_doc1_Sheet2");
                ps.setString(3, "Sheet2");
                ps.setString(4, "{}");
                ps.executeUpdate();
            }
            conn.commit();

            assertTrue(tableExists(conn, "staging_doc1_Sheet1"));
            List<String> dropped = StagingStore.dropByDoc(conn, "doc1");
            conn.commit();

            assertEquals(2, dropped.size());
            assertFalse(tableExists(conn, "staging_doc1_Sheet1"), "动态表必须一起 drop");
            assertFalse(tableExists(conn, "staging_doc1_Sheet2"));
            assertEquals(0, registryRows(conn, "doc1"), "登记行必须一起清，否则 purge 后仍是幽灵文档");

            // 幂等：再清一次不报错、返回空
            assertTrue(StagingStore.dropByDoc(conn, "doc1").isEmpty());
            conn.commit();
        }
    }
}
