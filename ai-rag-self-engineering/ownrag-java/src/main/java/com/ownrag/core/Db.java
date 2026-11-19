package com.ownrag.core;

import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;

/**
 * SQLite 连接与建表（Python 版 core/db.py 的平移，单文件零部署；字段按可平迁 PostgreSQL 设计）。
 *
 * 与 Python 版的差异：
 *   - Python 的向量通道是 chromadb 本地目录；Java 版新增 chunk_vectors 表（BLOB float[]），
 *     查询时全量载入内存做暴力余弦（万级块毫秒级、精确召回）。
 *   - 每次 connect() 开新连接（WAL + busy_timeout），pipeline 长跑持连接期间
 *     chat/admin 的短连接读写不互斥（WAL 读写并行）。
 *
 * 表清单：
 *   tasks / todos / traces / chunks / chunks_fts / direct_hits / qa_log /
 *   staging_registry / parse_reviews / chunk_vectors(Java 新增)
 */
public final class Db {

    private Db() {
    }

    /** 与 Python 版 db.py DDL 一致 + chunk_vectors（Java 向量通道）。 */
    public static final String DDL = ""
            + "CREATE TABLE IF NOT EXISTS tasks (\n"
            + "    id TEXT PRIMARY KEY,\n"
            + "    doc_id TEXT NOT NULL,\n"
            + "    pipeline TEXT NOT NULL,\n"
            + "    kb TEXT NOT NULL DEFAULT 'default',\n"
            + "    status TEXT NOT NULL DEFAULT 'pending',\n"
            + "    current_step TEXT,\n"
            + "    error TEXT,\n"
            + "    state_json TEXT,\n"
            + "    trace_id TEXT,\n"
            + "    created_at TEXT DEFAULT (datetime('now', 'localtime')),\n"
            + "    updated_at TEXT DEFAULT (datetime('now', 'localtime'))\n"
            + ");\n"
            + "CREATE TABLE IF NOT EXISTS todos (\n"
            + "    id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            + "    task_id TEXT,\n"
            + "    doc_id TEXT,\n"
            + "    reason TEXT NOT NULL,\n"
            + "    payload_json TEXT,\n"
            + "    status TEXT NOT NULL DEFAULT 'open',\n"
            + "    created_at TEXT DEFAULT (datetime('now', 'localtime')),\n"
            + "    resolved_at TEXT\n"
            + ");\n"
            + "CREATE TABLE IF NOT EXISTS traces (\n"
            + "    id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            + "    trace_id TEXT NOT NULL,\n"
            + "    doc_id TEXT,\n"
            + "    step TEXT NOT NULL,\n"
            + "    status TEXT NOT NULL,\n"
            + "    ms REAL,\n"
            + "    counters_json TEXT,\n"
            + "    error TEXT,\n"
            + "    created_at TEXT DEFAULT (datetime('now', 'localtime'))\n"
            + ");\n"
            + "CREATE INDEX IF NOT EXISTS idx_traces_tid ON traces(trace_id);\n"
            + "CREATE TABLE IF NOT EXISTS chunks (\n"
            + "    chunk_id TEXT PRIMARY KEY,\n"
            + "    doc_id TEXT NOT NULL,\n"
            + "    kb TEXT NOT NULL,\n"
            + "    source_type TEXT,\n"
            + "    ordinal INTEGER,\n"
            + "    text TEXT NOT NULL,\n"
            + "    anchors_json TEXT,\n"
            + "    meta_json TEXT,\n"
            + "    embed_version TEXT,\n"
            + "    sensitivity TEXT,\n"          // 个人维度过滤列：public | internal | restricted（缺省按 internal 处理）
            + "    topic TEXT,\n"
            + "    doc_date TEXT,\n"           // ISO 日期，字符串比较即时间过滤
            + "    origin TEXT,\n"             // owner | third_party（第三方版权语料标记）
            + "    created_at TEXT DEFAULT (datetime('now', 'localtime'))\n"
            + ");\n"
            + "CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);\n"
            + "CREATE INDEX IF NOT EXISTS idx_chunks_kb ON chunks(kb);\n"
            + "CREATE TABLE IF NOT EXISTS direct_hits (\n"
            + "    id TEXT PRIMARY KEY,\n"
            + "    kb TEXT NOT NULL,\n"
            + "    level TEXT NOT NULL,\n"
            + "    question TEXT NOT NULL,\n"
            + "    aliases_json TEXT DEFAULT '[]',\n"
            + "    answer TEXT NOT NULL,\n"
            + "    enabled INTEGER NOT NULL DEFAULT 1,\n"
            + "    created_at TEXT DEFAULT (datetime('now', 'localtime'))\n"
            + ");\n"
            + "CREATE TABLE IF NOT EXISTS qa_log (\n"
            + "    id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            + "    ts TEXT DEFAULT (datetime('now', 'localtime')),\n"
            + "    app TEXT, question TEXT NOT NULL,\n"
            + "    hit_chunks_json TEXT, answer TEXT,\n"
            + "    feedback TEXT,\n"
            + "    trace_id TEXT\n"
            + ");\n"
            + "CREATE TABLE IF NOT EXISTS staging_registry (\n"
            + "    doc_id TEXT NOT NULL,\n"
            + "    table_name TEXT NOT NULL,\n"
            + "    sheet TEXT,\n"
            + "    schema_json TEXT,\n"
            + "    created_at TEXT DEFAULT (datetime('now', 'localtime')),\n"
            + "    PRIMARY KEY (doc_id, table_name)\n"
            + ");\n"
            + "CREATE TABLE IF NOT EXISTS parse_reviews (\n"
            + "    doc_id TEXT PRIMARY KEY,\n"
            + "    kb TEXT,\n"
            + "    task_id TEXT,\n"
            + "    trace_id TEXT,\n"
            + "    pipeline TEXT,\n"
            + "    source_file TEXT,\n"
            + "    backend TEXT,\n"
            + "    status TEXT NOT NULL DEFAULT 'pending',\n"
            + "    verdict TEXT,\n"
            + "    pages INTEGER DEFAULT 0,\n"
            + "    chars INTEGER DEFAULT 0,\n"
            + "    tables INTEGER DEFAULT 0,\n"
            + "    structures INTEGER DEFAULT 0,\n"
            + "    blocking_json TEXT,\n"
            + "    warn_json TEXT,\n"
            + "    pages_json TEXT,\n"
            + "    report_path TEXT,\n"
            + "    note TEXT,\n"
            + "    reviewed_at TEXT,\n"
            + "    created_at TEXT DEFAULT (datetime('now', 'localtime')),\n"
            + "    updated_at TEXT DEFAULT (datetime('now', 'localtime'))\n"
            + ");\n"
            // Java 版新增：向量通道（替代 chromadb）。float[] → BLOB 小端序列化。
            + "CREATE TABLE IF NOT EXISTS chunk_vectors (\n"
            + "    chunk_id TEXT PRIMARY KEY,\n"
            + "    doc_id TEXT NOT NULL,\n"
            + "    kb TEXT NOT NULL,\n"
            + "    embedding BLOB NOT NULL,\n"
            + "    dim INTEGER NOT NULL\n"
            + ");\n"
            + "CREATE INDEX IF NOT EXISTS idx_vectors_doc ON chunk_vectors(doc_id);\n"
            + "CREATE INDEX IF NOT EXISTS idx_vectors_kb ON chunk_vectors(kb);\n"
            // Java 版新增：文件级指纹（上传幂等）+ 块级内容指纹（跨文档去重）。
            // 块 hash 登记发生在 index_upsert（review 通过后），reject 的文档不占坑
            + "CREATE TABLE IF NOT EXISTS doc_fingerprints (\n"
            + "    file_hash TEXT PRIMARY KEY,\n"
            + "    doc_id TEXT NOT NULL,\n"
            + "    kb TEXT,\n"
            + "    source_file TEXT,\n"
            + "    created_at TEXT DEFAULT (datetime('now', 'localtime'))\n"
            + ");\n"
            + "CREATE TABLE IF NOT EXISTS chunk_hashes (\n"
            + "    hash TEXT PRIMARY KEY,\n"
            + "    chunk_id TEXT NOT NULL,\n"
            + "    doc_id TEXT NOT NULL,\n"
            + "    created_at TEXT DEFAULT (datetime('now', 'localtime'))\n"
            + ");\n"
            + "CREATE INDEX IF NOT EXISTS idx_chunk_hashes_doc ON chunk_hashes(doc_id);\n";

    public static Connection connect(Path dbPath) throws SQLException {
        Path parent = dbPath.toAbsolutePath().getParent();
        if (parent != null) {
            parent.toFile().mkdirs();
        }
        Connection conn = DriverManager.getConnection("jdbc:sqlite:" + dbPath.toAbsolutePath());
        try (Statement st = conn.createStatement()) {
            st.execute("PRAGMA journal_mode=WAL;");
            st.execute("PRAGMA foreign_keys=ON;");
            st.execute("PRAGMA busy_timeout=15000;");  // 批量灌库场景：管线写 + approve 写 + 大查询并发，5s 不够
        }
        // 与 Python 版 sqlite3 隐式事务语义对齐：写操作需显式 commit（各 Store 方法内自带），
        // 读连接关闭时回滚无副作用。autoCommit 必须在 PRAGMA 之后设置（WAL 切换不能发生在事务内）。
        conn.setAutoCommit(false);
        return conn;
    }

    /** 幂等建表 + 旧库迁移 + FTS5 探测：FTS5 不可用 = 关键词通道不可建，启动期直接失败。 */
    public static void initSchema(Path dbPath) throws SQLException {
        try (Connection conn = connect(dbPath)) {
            try (Statement st = conn.createStatement()) {
                st.executeUpdate(DDL);
            }
            migrate(conn);
            probeFts5(conn);
            conn.commit();
        }
    }

    /**
     * 旧库幂等迁移：CREATE TABLE IF NOT EXISTS 不会给已存在的表补列，
     * 个人维度过滤列（sensitivity/topic/doc_date/origin）按列名探测后 ALTER TABLE 补齐。
     * 每次启动都会跑，列已存在即跳过。
     */
    public static void migrate(Connection conn) throws SQLException {
        java.util.Set<String> cols = new java.util.LinkedHashSet<>();
        try (Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("PRAGMA table_info(chunks)")) {
            while (rs.next()) {
                cols.add(rs.getString("name"));
            }
        }
        // 表不存在时 PRAGMA 返回空——那是全新库，DDL 已建好最新 schema，无需补列
        String[][] additions = {
                {"sensitivity", "TEXT"},
                {"topic", "TEXT"},
                {"doc_date", "TEXT"},
                {"origin", "TEXT"},
        };
        try (Statement st = conn.createStatement()) {
            for (String[] col : additions) {
                if (!cols.isEmpty() && !cols.contains(col[0])) {
                    st.executeUpdate("ALTER TABLE chunks ADD COLUMN " + col[0] + " " + col[1]);
                }
            }
        }
    }

    /** FTS5 探测：xerial sqlite-jdbc 需编译期开启 FTS5；失败即拒绝启动（配置错误启动期爆口径）。 */
    static void probeFts5(Connection conn) throws SQLException {
        try (Statement st = conn.createStatement()) {
            st.executeUpdate("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5("
                    + "text, chunk_id UNINDEXED, doc_id UNINDEXED, kb UNINDEXED)");
            st.executeUpdate("DROP TABLE IF EXISTS ownrag_fts5_probe");
            st.executeUpdate("CREATE VIRTUAL TABLE ownrag_fts5_probe USING fts5(x)");
            st.executeUpdate("DROP TABLE ownrag_fts5_probe");
        } catch (SQLException e) {
            throw new SQLException("SQLite FTS5 不可用（关键词通道依赖 FTS5）：" + e.getMessage(), e);
        }
    }
}
