package com.ownrag.ingest;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import com.ownrag.config.Settings;
import com.ownrag.core.Db;
import com.ownrag.core.StepContext;
import com.ownrag.core.StepResult;
import com.ownrag.index.ChunkMarkdownStep;
import com.ownrag.index.ChunkStore;
import com.ownrag.index.IndexUpsertStep;
import com.ownrag.retrieve.RetrieveTest;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Excel 通道端到端口径（docs 10-Excel通道口径.md §十一/§十二）：
 * excel_stage → schema_infer → textualize(catalog) → chunk → index_upsert。
 *
 * 最关键的一条断言：**`chunk_vectors` 必须是 0 行**。
 * Excel 的数值走查询期 SQL，行不嵌入；只要这条不成立，聚合题就又会退回到"让模型从文字里抄数字"。
 */
class ExcelCatalogPipelineTest {

    @TempDir
    Path tmp;

    @Test
    void CSV走catalog链路_只进FTS不进向量() throws Exception {
        Path csv = tmp.resolve("e2e.csv");
        Files.write(csv, ("月份,部门,报销金额,备注\n"
                + "2024-01,研发部,\"12,350.50\",含税\n"
                + "2024-02,市场部,9120.75,待审批\n")
                .getBytes(StandardCharsets.UTF_8));

        Settings settings = new RetrieveTest.SettingsBuilder().dataDir(tmp.resolve("data")).build();
        Db.initSchema(settings.getDbPath());
        try (Connection conn = Db.connect(settings.getDbPath())) {
            StepContext ctx = new StepContext("docExcel01", "t1", "kb1", conn, settings);
            ctx.data.put("source_path", csv.toString());

            StepResult stage = new ExcelStageStep().run(ctx, Collections.emptyMap());
            assertTrue(stage.ok, stage.error);

            StepResult schema = new SchemaInferStep().run(ctx, mapOf("sample_n", 5));
            assertTrue(schema.ok, schema.error);
            Map<String, String> types = new LinkedHashMap<>();
            Map<String, String> exprs = new LinkedHashMap<>();
            for (Map<String, Object> s : schemas(ctx)) {
                for (Map<String, Object> c : columns(s)) {
                    types.put(String.valueOf(c.get("column")), String.valueOf(c.get("type")));
                    exprs.put(String.valueOf(c.get("column")), String.valueOf(c.get("sql_expr")));
                }
            }
            assertEquals("date", types.get("月份"));
            assertEquals("number", types.get("报销金额"), "千分位数值列必须判成 number");
            assertTrue(exprs.get("报销金额").contains("AS REAL"), "数值列必须给可聚合表达式：" + exprs);

            StepResult cat = new TextualizeStep().run(ctx, mapOf("strategy", "catalog"));
            assertTrue(cat.ok, cat.error);
            String markdown = String.valueOf(((Map<?, ?>) ctx.data.get("parsed")).get("markdown"));
            assertTrue(markdown.contains("#### e2e.csv / csv"), markdown);
            assertTrue(markdown.contains("报销金额(number)"), markdown);
            assertFalse(markdown.contains("第 2 行"), "catalog 策略不该再产出行级卡片");

            StepResult chunk = new ChunkMarkdownStep().run(ctx, mapOf("max_tokens", 512, "overlap", 0));
            assertTrue(chunk.ok, chunk.error);

            StepResult upsert = new IndexUpsertStep().run(ctx, mapOf("replace_by_doc", true));
            assertTrue(upsert.ok, upsert.error);

            assertEquals(0, count(conn, "SELECT COUNT(*) FROM chunk_vectors"), "Excel 目录块不能进向量通道");
            assertEquals(count(conn, "SELECT COUNT(*) FROM chunks"),
                    count(conn, "SELECT COUNT(*) FROM chunks WHERE source_type='excel_catalog'"));

            List<Map<String, Object>> hits = ChunkStore.keywordSearch(conn, "kb1", "报销金额", 5, null);
            assertFalse(hits.isEmpty(), "目录块必须能被关键词检索到（路由与列链接要用它）");
        }
    }

    @Test
    void staging登记行带原始列名与物理列名两套() throws Exception {
        Path csv = tmp.resolve("dup.csv");
        Files.write(csv, ("金额,金额,备注\n1,2,x\n").getBytes(StandardCharsets.UTF_8));

        Settings settings = new RetrieveTest.SettingsBuilder().dataDir(tmp.resolve("data2")).build();
        Db.initSchema(settings.getDbPath());
        try (Connection conn = Db.connect(settings.getDbPath())) {
            StepContext ctx = new StepContext("docExcel02", "t2", "kb1", conn, settings);
            ctx.data.put("source_path", csv.toString());
            StepResult stage = new ExcelStageStep().run(ctx, Collections.emptyMap());
            assertTrue(stage.ok, "重名列必须靠去重活下来：" + stage.error);

            try (PreparedStatement ps = conn.prepareStatement(
                    "SELECT schema_json FROM staging_registry WHERE doc_id=?")) {
                ps.setString(1, "docExcel02");
                try (ResultSet rs = ps.executeQuery()) {
                    assertTrue(rs.next(), "必须登记 staging_registry，否则查询期路由看不到这张表");
                    String json = rs.getString(1);
                    assertTrue(json.contains("\"columns\""), json);
                    assertTrue(json.contains("\"physical\""), json);
                    assertTrue(json.contains("金额_2"), "物理列名必须去重：" + json);
                }
            }
        }
    }

    @Test
    void 重复入库原子换表_登记行唯一且旧表被清() throws Exception {
        Path csv = tmp.resolve("swap.csv");
        Files.write(csv, ("部门,金额\n研发部,100\n市场部,200\n").getBytes(StandardCharsets.UTF_8));

        Settings settings = new RetrieveTest.SettingsBuilder().dataDir(tmp.resolve("data3")).build();
        Db.initSchema(settings.getDbPath());
        try (Connection conn = Db.connect(settings.getDbPath())) {
            for (int i = 0; i < 2; i++) {
                StepContext ctx = new StepContext("docSwap01", "t3", "kb1", conn, settings);
                ctx.data.put("source_path", csv.toString());
                StepResult stage = new ExcelStageStep().run(ctx, Collections.emptyMap());
                assertTrue(stage.ok, "第 " + (i + 1) + " 次入库失败：" + stage.error);
            }
            // 登记行 PK 是 (doc_id, table_name)：换表名后若只 INSERT OR REPLACE 会留下两行
            assertEquals(1, count(conn, "SELECT COUNT(*) FROM staging_registry WHERE doc_id='docSwap01'"));
            // 物理表也必须只剩一张（旧表在切换后被 DROP）
            // 表名前缀是 docId 前 8 位（docSwap0），不是完整 docId
            assertEquals(1, count(conn,
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                            + "AND name LIKE 'staging\\_docSwap0%' ESCAPE '\\'"));
            String table = text(conn, "SELECT table_name FROM staging_registry WHERE doc_id='docSwap01'");
            assertTrue(table.contains("_v"), "换表后应带 _v<epoch> 版本后缀：" + table);
            assertEquals(2, count(conn, "SELECT COUNT(*) FROM \"" + table + "\""));
            assertTrue(text(conn, "SELECT schema_json FROM staging_registry WHERE doc_id='docSwap01'")
                    .contains("swap_at"));
        }
    }

    private static String text(Connection conn, String sql) throws Exception {
        try (PreparedStatement ps = conn.prepareStatement(sql); ResultSet rs = ps.executeQuery()) {
            return rs.next() ? String.valueOf(rs.getString(1)) : "";
        }
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> schemas(StepContext ctx) {
        return (List<Map<String, Object>>) ctx.data.get("schemas");
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> columns(Map<String, Object> schema) {
        return (List<Map<String, Object>>) schema.get("columns");
    }

    private static Map<String, Object> mapOf(Object... pairs) {
        Map<String, Object> m = new LinkedHashMap<>();
        for (int i = 0; i + 1 < pairs.length; i += 2) {
            m.put(String.valueOf(pairs[i]), pairs[i + 1]);
        }
        return m;
    }

    private static int count(Connection conn, String sql) throws Exception {
        try (PreparedStatement ps = conn.prepareStatement(sql); ResultSet rs = ps.executeQuery()) {
            return rs.next() ? rs.getInt(1) : 0;
        }
    }
}
