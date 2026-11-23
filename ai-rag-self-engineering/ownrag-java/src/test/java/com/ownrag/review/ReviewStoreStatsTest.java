package com.ownrag.review;

import java.nio.file.Path;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import com.ownrag.core.Db;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** 复核记录落库口径：文档统计要能建表、能写入、能在老库上补列（不靠重建库）。 */
class ReviewStoreStatsTest {

    @TempDir
    Path tmp;

    private static Map<String, Object> parsedDoc() {
        String md = "<!--page:1-->\n# 标题\n\n正文带行内公式 $x^2$ 与图片 ![](images/p1.jpg)\n\n"
                + "| 列A | 列B |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |\n\n"
                + "<!--page:2-->\n| 5 | 6 |\n| 7 | 8 |\n\n结尾";
        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put("format", "pdf");
        metadata.put("source_file", "a.pdf");
        Map<String, Object> stats = new LinkedHashMap<>();
        stats.put("pages", 2);
        stats.put("backend", "mineru-open");
        Map<String, Object> p = new LinkedHashMap<>();
        p.put("markdown", md);
        p.put("metadata", metadata);
        p.put("stats", stats);
        p.put("structures", new ArrayList<Map<String, Object>>());
        p.put("assets", new LinkedHashMap<String, Object>());
        return p;
    }

    private static List<Map<String, Object>> chunks() {
        List<Map<String, Object>> chunks = new ArrayList<>();
        Map<String, Object> c = new LinkedHashMap<>();
        c.put("ordinal", 0);
        c.put("text", "标题\n\n正文带行内公式与图片");
        chunks.add(c);
        return chunks;
    }

    @Test
    void 保存复核记录时写入文档统计列() throws Exception {
        Path db = tmp.resolve("ownrag.db");
        Db.initSchema(db);
        try (Connection conn = Db.connect(db)) {
            Map<String, Object> checks = ReviewStore.qualityChecks(parsedDoc(), chunks(), 20, 512, 1.5, null);
            ReviewStore.saveReview(conn, "d1", "kb_policy", "t1", "tr1", "pdf_v1", "a.pdf",
                    checks, tmp.resolve("report.json").toString());

            Map<String, Object> row = ReviewStore.getReview(conn, "d1");
            assertNotNull(row);
            assertEquals("pdf", row.get("format"));
            assertEquals(1, ((Number) row.get("images")).intValue());
            assertEquals(1, ((Number) row.get("formulas")).intValue());
            assertEquals(1, ((Number) row.get("tables")).intValue());
            assertTrue(((Number) row.get("suspects")).intValue() >= 1, "表格跨页应进存疑计数");
            String json = String.valueOf(row.get("doc_stats_json"));
            assertTrue(json.contains("\"table_cross_page\""), "存疑明细要随记录落库，列表页不用再读 report.json：" + json);
        }
    }

    @Test
    void 老库启动迁移补齐文档统计列() throws Exception {
        Path db = tmp.resolve("old.db");
        try (Connection conn = Db.connect(db)) {
            try (Statement st = conn.createStatement()) {
                // 模拟上一版 schema：parse_reviews 没有 format/images/formulas/suspects/doc_stats_json
                st.executeUpdate("CREATE TABLE parse_reviews ("
                        + "doc_id TEXT PRIMARY KEY, kb TEXT, status TEXT NOT NULL DEFAULT 'pending',"
                        + " verdict TEXT, pages INTEGER DEFAULT 0, chars INTEGER DEFAULT 0,"
                        + " tables INTEGER DEFAULT 0, structures INTEGER DEFAULT 0,"
                        + " blocking_json TEXT, warn_json TEXT, pages_json TEXT, report_path TEXT)");
            }
            conn.commit();
            Db.migrate(conn);
            conn.commit();

            Set<String> cols = new LinkedHashSet<>();
            try (Statement st = conn.createStatement();
                 ResultSet rs = st.executeQuery("PRAGMA table_info(parse_reviews)")) {
                while (rs.next()) {
                    cols.add(rs.getString("name"));
                }
            }
            assertTrue(cols.contains("format"), "老库应补出 format 列：" + cols);
            assertTrue(cols.contains("images"));
            assertTrue(cols.contains("formulas"));
            assertTrue(cols.contains("suspects"));
            assertTrue(cols.contains("doc_stats_json"));
        }
    }
}
