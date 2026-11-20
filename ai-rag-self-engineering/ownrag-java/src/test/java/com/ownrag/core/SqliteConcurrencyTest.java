package com.ownrag.core;

import java.nio.file.Path;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * SQLite 并发语义回归（复现线上 58 条 `[SQLITE_BUSY] database is locked`）：
 *
 * 根因不是 busy_timeout 太短，而是 **读事务升级写事务**：连接在 autocommit=false 下，
 * 一条 SELECT 就开启 deferred 读事务；之后同连接要写时必须把读快照升级为写锁。
 * 若这期间别的连接提交过，SQLite 返回 SQLITE_BUSY_SNAPSHOT，且**不走 busy handler**
 * （busy_timeout 白设），只能回滚重来。
 *
 * 管道的真实路径正是这个形状：getTask(SELECT) → markRunning(UPDATE)，
 * dedupe(SELECT chunk_hashes) → index_upsert(UPDATE)。修法是读写之间显式结束事务。
 */
class SqliteConcurrencyTest {

    @TempDir
    Path tmp;

    private static void insertTask(Connection conn, String id) throws SQLException {
        try (Statement st = conn.createStatement()) {
            st.executeUpdate("INSERT INTO tasks(id, doc_id, pipeline, kb, status) "
                    + "VALUES ('" + id + "', 'd-" + id + "', 'pdf_v1', 'kb', 'pending')");
        }
    }

    /** 读一下再写：不结束读事务就会撞 BUSY（这条锁死了"为什么必须 endRead"）。 */
    @Test
    void 读事务未结束_同连接再写必BUSY() throws Exception {
        Path db = tmp.resolve("busy.db");
        Db.initSchema(db);
        try (Connection reader = Db.connect(db); Connection writer = Db.connect(db)) {
            try (Statement st = reader.createStatement();
                 ResultSet rs = st.executeQuery("SELECT count(*) FROM tasks")) {
                rs.next();
            }
            insertTask(writer, "w1");
            writer.commit();

            long t0 = System.nanoTime();
            SQLException e = assertThrows(SQLException.class, () -> insertTask(reader, "r1"));
            long ms = (System.nanoTime() - t0) / 1_000_000;
            assertTrue(String.valueOf(e.getMessage()).contains("BUSY"),
                    "期望 SQLITE_BUSY，实际：" + e.getMessage());
            assertTrue(ms < 2000, "BUSY_SNAPSHOT 应立即失败而不是等满 busy_timeout，实际 " + ms + "ms");
        }
    }

    /** 读后 endRead 再写：同样的连接与并发序，写成功且不丢数据。 */
    @Test
    void 读后endRead_同连接可正常写入() throws Exception {
        Path db = tmp.resolve("ok.db");
        Db.initSchema(db);
        try (Connection reader = Db.connect(db); Connection writer = Db.connect(db)) {
            try (Statement st = reader.createStatement();
                 ResultSet rs = st.executeQuery("SELECT count(*) FROM tasks")) {
                rs.next();
            }
            insertTask(writer, "w2");
            writer.commit();

            Db.endRead(reader);
            insertTask(reader, "r2");
            reader.commit();

            try (Statement st = reader.createStatement();
                 ResultSet rs = st.executeQuery("SELECT count(*) FROM tasks")) {
                rs.next();
                assertEquals(2, rs.getInt(1));
            }
        }
    }

    /** 纯写-写竞争走 busy_timeout 正常排队：两个连接各写 20 行，全部落库。 */
    @Test
    void 写写竞争_靠busy_timeout排队不失败() throws Exception {
        Path db = tmp.resolve("ww.db");
        Db.initSchema(db);
        try (Connection a = Db.connect(db); Connection b = Db.connect(db)) {
            for (int i = 0; i < 20; i++) {
                insertTask(a, "a" + i);
                a.commit();
                insertTask(b, "b" + i);
                b.commit();
            }
            try (Statement st = a.createStatement();
                 ResultSet rs = st.executeQuery("SELECT count(*) FROM tasks")) {
                rs.next();
                assertEquals(40, rs.getInt(1));
            }
        }
    }
}
