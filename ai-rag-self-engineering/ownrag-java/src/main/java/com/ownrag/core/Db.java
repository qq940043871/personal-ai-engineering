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
 * 表清单（18 张实体表 + FTS5）：
 *   tasks / todos / traces / chunks / chunks_fts / direct_hits / qa_log /
 *   staging_registry / parse_reviews                                  ← 与 Python 版同名同结构
 *   chunk_vectors / doc_fingerprints / chunk_hashes / kb_registry / documents /
 *   eval_cases / sql_failures / users / user_sessions                 ← Java 版新增
 *
 * 访问控制：documents.access_level（public | protected）是**文档级权限的唯一事实源**，
 * 检索与原件读取都按它过滤（未登录只看 public）。chunks 不冗余这一列——一篇文档的权限
 * 只该有一个可改的地方，改 documents 一行即对全链路生效（见 ChunkStore.filterSql）。
 * 用户与登录会话落库（users / user_sessions）而不是内存：重启不掉登录态，多实例不必共享内存。
 *
 * 另有 Excel 链路的**动态表**：每个 sheet 一张 `staging_<docId前8位>_<sheet>`
 * （全列 TEXT + _src_file/_sheet/_rownum），由 ExcelStageStep 建、StagingStore 在删文档/purge 时清。
 */
public final class Db {

    private static final org.slf4j.Logger log = org.slf4j.LoggerFactory.getLogger(Db.class);

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
            // 回填/管理页按 doc_id 取最近任务：无此索引时相关子查询会全表扫描（1GB 库实测 67s）
            + "CREATE INDEX IF NOT EXISTS idx_tasks_doc ON tasks(doc_id, created_at, id);\n"
            // 任务列表 ORDER BY created_at DESC LIMIT n：无此索引时 SQLite 要把整行（含 state_json
            // 检查点，全表可达数百 MB）塞进临时排序器，实测 12 行也要 9.5s
            + "CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at DESC, id DESC);\n"
            // metrics 的 GROUP BY status：索引可做 index-only scan，避免再读 state_json 大列
            + "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);\n"
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
            // 直击库答案绕开检索直达用户：它不挂在 documents 上，权限必须自己带一列
            + "    access_level TEXT NOT NULL DEFAULT 'public',\n"      // public | protected
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
            // 文档统计（格式/图片/公式/存疑数）：列表页要按这些列直接排序筛选，
            // 完整统计（含存疑明细）另存 doc_stats_json，避免每次都读 report.json
            + "    format TEXT,\n"
            + "    images INTEGER DEFAULT 0,\n"
            + "    formulas INTEGER DEFAULT 0,\n"
            + "    suspects INTEGER DEFAULT 0,\n"
            + "    doc_stats_json TEXT,\n"
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
            + "CREATE INDEX IF NOT EXISTS idx_chunk_hashes_doc ON chunk_hashes(doc_id);\n"
            // 运行时登记的知识库：apps.yaml 声明之外，允许在控制台新建空库再上传
            + "CREATE TABLE IF NOT EXISTS kb_registry (\n"
            + "    kb TEXT PRIMARY KEY,\n"
            + "    description TEXT DEFAULT '',\n"
            + "    created_at TEXT DEFAULT (datetime('now', 'localtime'))\n"
            + ");\n"
            // 文档实体：doc_id 不再是只在 chunks/tasks 上飘的隐式身份，管理面只读这一张表
            + "CREATE TABLE IF NOT EXISTS documents (\n"
            + "    doc_id TEXT PRIMARY KEY,\n"
            + "    kb TEXT NOT NULL DEFAULT 'default',\n"
            + "    source_file TEXT,\n"
            + "    pipeline TEXT,\n"
            + "    task_id TEXT,\n"
            + "    trace_id TEXT,\n"
            + "    file_hash TEXT,\n"
            + "    size_bytes INTEGER DEFAULT 0,\n"
            + "    sensitivity TEXT,\n"
            + "    topic TEXT,\n"
            + "    doc_date TEXT,\n"
            + "    origin TEXT,\n"
            + "    review_status TEXT,\n"
            + "    task_status TEXT,\n"
            + "    enabled INTEGER NOT NULL DEFAULT 1,\n"   // 文档启停：0 = 暂时退出检索（不删块与向量）
            + "    access_level TEXT NOT NULL DEFAULT 'public',\n"  // public = 公开；protected = 需登录
            + "    chunk_count INTEGER DEFAULT 0,\n"
            + "    vector_count INTEGER DEFAULT 0,\n"
            + "    chars INTEGER DEFAULT 0,\n"
            + "    created_at TEXT DEFAULT (datetime('now', 'localtime')),\n"
            + "    updated_at TEXT DEFAULT (datetime('now', 'localtime'))\n"
            + ");\n"
            + "CREATE INDEX IF NOT EXISTS idx_documents_kb ON documents(kb);\n"
            + "CREATE INDEX IF NOT EXISTS idx_documents_task ON documents(task_id);\n"
            // 评测集：一行 = 一道题（来源 + 期望 + 上次判定），判定结果由"跑评测"写回，
            // 也可以人工改判——好/坏不是人拍的，是检索链路按口径跑出来的，跑不动就显式 pending。
            + "CREATE TABLE IF NOT EXISTS eval_cases (\n"
            + "    id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            + "    kb TEXT NOT NULL DEFAULT 'default',\n"
            + "    question TEXT NOT NULL,\n"
            + "    source TEXT NOT NULL DEFAULT 'manual',\n"     // manual | qa_log | direct_hit
            + "    source_ref TEXT,\n"                            // qa_log.id / direct_hits.id
            + "    expect_all TEXT DEFAULT '[]',\n"               // JSON：命中即好的关键词（全部要出现）
            + "    expect_empty INTEGER NOT NULL DEFAULT 0,\n"    // 1 = 该拒答的题（语料里没有答案）
            + "    category TEXT DEFAULT 'concept',\n"            // fact|concept|compare|troubleshoot|multi|cross|reject|direct
            + "    difficulty TEXT DEFAULT 'medium',\n"           // easy|medium|hard
            + "    note TEXT,\n"
            + "    verdict TEXT NOT NULL DEFAULT 'pending',\n"    // pass | fail | pending
            + "    last_score REAL,\n"                            // 0~1 判定分（关键词命中率 / 拒答正确 1|0）
            + "    last_detail TEXT,\n"                            // JSON：闸门结论 + 命中/缺失关键词 + Top 候选
            + "    last_run_at TEXT,\n"
            // 期望通道与实跑通道：路由也要有回归口径——路由错但答案对，同样算坏
            + "    expect_route TEXT,\n"                           // rag | sql | multi（空=不判路由）
            + "    route_actual TEXT,\n"                           // 上次跑出来的通道
            + "    created_at TEXT DEFAULT (datetime('now', 'localtime'))\n"
            + ");\n"
            // 同一库内同一问题只留一条：问答日志回流与手工补录都可能重复提交
            + "CREATE UNIQUE INDEX IF NOT EXISTS idx_eval_cases_kb_q ON eval_cases(kb, question);\n"
            + "CREATE INDEX IF NOT EXISTS idx_eval_cases_verdict ON eval_cases(verdict);\n"
            // SQL 通道连续失败计数：跨请求、跨重启都要能累计，所以落库而不是放内存。
            // key 用 (app, question_norm)：同一句问反复失败才值得进待办，偶发一次不打扰人。
            + "CREATE TABLE IF NOT EXISTS sql_failures (\n"
            + "    id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            + "    app TEXT NOT NULL DEFAULT 'default',\n"
            + "    question_norm TEXT NOT NULL,\n"
            + "    question TEXT,\n"
            + "    count INTEGER NOT NULL DEFAULT 0,\n"
            + "    last_note TEXT,\n"
            + "    todo_id INTEGER,\n"                             // 已开的待办：成功一次就关掉它
            + "    first_at TEXT DEFAULT (datetime('now','localtime')),\n"
            + "    last_at TEXT DEFAULT (datetime('now','localtime'))\n"
            + ");\n"
            + "CREATE UNIQUE INDEX IF NOT EXISTS idx_sql_failures_key "
            + "ON sql_failures(app, question_norm);"
            // 用户表：口令只存 PBKDF2 派生值与盐（不存明文、不存可逆加密），校验在 PasswordHasher 里
            + "CREATE TABLE IF NOT EXISTS users (\n"
            + "    username TEXT PRIMARY KEY,\n"
            + "    password_hash TEXT NOT NULL,\n"
            + "    salt TEXT NOT NULL,\n"
            + "    display_name TEXT,\n"
            + "    role TEXT NOT NULL DEFAULT 'user',\n"          // admin | user（当前只用于展示与账号管理）
            + "    created_at TEXT DEFAULT (datetime('now', 'localtime')),\n"
            + "    last_login_at TEXT\n"
            + ");\n"
            // 登录会话：token（随机 32 字节 hex）= 主键，落库而不是放内存，重启后登录态不丢。
            // expires_at 用本地时间字符串（与全库时间列同口径），过期判定就是字符串比较。
            + "CREATE TABLE IF NOT EXISTS user_sessions (\n"
            + "    token TEXT PRIMARY KEY,\n"
            + "    username TEXT NOT NULL,\n"
            + "    expires_at TEXT NOT NULL,\n"
            + "    created_at TEXT DEFAULT (datetime('now', 'localtime')),\n"
            + "    last_seen_at TEXT\n"
            + ");\n"
            + "CREATE INDEX IF NOT EXISTS idx_user_sessions_user ON user_sessions(username);"
            + "CREATE INDEX IF NOT EXISTS idx_user_sessions_exp ON user_sessions(expires_at);";

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

    /**
     * 结束只读事务（"读到这里"）。**读后可能再写的路径必须调用**。
     *
     * 原因：autocommit=false 下一条 SELECT 就开启 deferred 读事务；同连接随后要写时，
     * SQLite 必须把读快照升级成写锁。若这期间别的连接提交过，返回 SQLITE_BUSY_SNAPSHOT，
     * 且**不走 busy handler**——busy_timeout 调多大都没用，表现为
     * `[SQLITE_BUSY] The database file is locked` 立即失败（批量灌库时的 58 条失败任务即此）。
     *
     * 用 commit 而非 rollback：纯读事务提交无副作用；调用方若有未提交写也会随之落地，
     * 与"写方法自带 commit"的既有约定一致。
     */
    public static void endRead(Connection conn) {
        if (conn == null) {
            return;
        }
        try {
            if (!conn.getAutoCommit()) {
                conn.commit();
            }
        } catch (SQLException e) {
            try {
                conn.rollback();
            } catch (SQLException ignored) {
                // 连接已坏：交给上层按"步骤失败"处理，别再抛第二个异常盖掉现场
            }
        }
    }

    /** 幂等建表 + 旧库迁移 + 历史文档回填 + FTS5 探测：FTS5 不可用则启动期直接失败。 */
    public static void initSchema(Path dbPath) throws SQLException {
        try (Connection conn = connect(dbPath)) {
            try (Statement st = conn.createStatement()) {
                st.executeUpdate(DDL);
            }
            migrate(conn);
            conn.commit();   // DDL 先落地：回填失败也不能让新表随事务回滚
            try {
                DocumentStore.backfill(conn);
                conn.commit();
            } catch (SQLException e) {
                conn.rollback();
                log.error("[ownrag] 历史文档回填失败（表结构已就绪，可重启重试）", e);
            }
            probeFts5(conn);
            conn.commit();
        }
    }

    /**
     * 旧库幂等迁移：CREATE TABLE IF NOT EXISTS 不会给已存在的表补列，
     * 个人维度过滤列（sensitivity/topic/doc_date/origin）与 documents.enabled
     * 按列名探测后 ALTER TABLE 补齐。每次启动都会跑，列已存在即跳过。
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
        // documents.enabled（文档启停）：老库补列；默认 1 = 全部参与检索，存量行为不变
        java.util.Set<String> docCols = new java.util.LinkedHashSet<>();
        try (Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("PRAGMA table_info(documents)")) {
            while (rs.next()) {
                docCols.add(rs.getString("name"));
            }
        }
        if (!docCols.isEmpty() && !docCols.contains("enabled")) {
            try (Statement st = conn.createStatement()) {
                st.executeUpdate("ALTER TABLE documents ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1");
            }
        }
        // documents.access_level（文档级权限）：老库补列后存量文档一律 public——行为不变，
        // 要收口的文档由管理员逐篇改成 protected（不按"猜"的方式自动授权）
        if (!docCols.isEmpty() && !docCols.contains("access_level")) {
            try (Statement st = conn.createStatement()) {
                st.executeUpdate("ALTER TABLE documents ADD COLUMN access_level TEXT NOT NULL DEFAULT 'public'");
            }
        }
        // direct_hits.access_level（直击库权限）：老库补列后一律 public = 存量行为不变
        java.util.Set<String> hitCols = new java.util.LinkedHashSet<>();
        try (Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("PRAGMA table_info(direct_hits)")) {
            while (rs.next()) {
                hitCols.add(rs.getString("name"));
            }
        }
        if (!hitCols.isEmpty() && !hitCols.contains("access_level")) {
            try (Statement st = conn.createStatement()) {
                st.executeUpdate(
                        "ALTER TABLE direct_hits ADD COLUMN access_level TEXT NOT NULL DEFAULT 'public'");
            }
        }
        // parse_reviews 的文档统计列（format/images/formulas/suspects/doc_stats_json）：
        // 老库补列后历史行为 NULL，复核页按"未统计"处理（不拿 0 冒充"没有图片/公式"）
        java.util.Set<String> reviewCols = new java.util.LinkedHashSet<>();
        try (Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("PRAGMA table_info(parse_reviews)")) {
            while (rs.next()) {
                reviewCols.add(rs.getString("name"));
            }
        }
        String[][] reviewAdditions = {
                {"format", "TEXT"},
                {"images", "INTEGER DEFAULT 0"},
                {"formulas", "INTEGER DEFAULT 0"},
                {"suspects", "INTEGER DEFAULT 0"},
                {"doc_stats_json", "TEXT"},
        };
        try (Statement st = conn.createStatement()) {
            for (String[] col : reviewAdditions) {
                if (!reviewCols.isEmpty() && !reviewCols.contains(col[0])) {
                    st.executeUpdate("ALTER TABLE parse_reviews ADD COLUMN " + col[0] + " " + col[1]);
                }
            }
        }
        // eval_cases 的题型/难度（分桶统计用）：2026-11-22 之前建的库没有这两列
        java.util.Set<String> evalCols = new java.util.LinkedHashSet<>();
        try (Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("PRAGMA table_info(eval_cases)")) {
            while (rs.next()) {
                evalCols.add(rs.getString("name"));
            }
        }
        String[][] evalAdditions = {
                {"category", "TEXT DEFAULT 'concept'"},
                {"difficulty", "TEXT DEFAULT 'medium'"},
                // 路由回归：老库补列后历史题 expect_route 为 NULL = 不判路由，判定口径不变
                {"expect_route", "TEXT"},
                {"route_actual", "TEXT"},
        };
        try (Statement st = conn.createStatement()) {
            for (String[] col : evalAdditions) {
                if (!evalCols.isEmpty() && !evalCols.contains(col[0])) {
                    st.executeUpdate("ALTER TABLE eval_cases ADD COLUMN " + col[0] + " " + col[1]);
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
