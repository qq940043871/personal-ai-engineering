package com.ownrag.core;

import java.nio.file.Path;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import com.ownrag.config.PipelineDef;
import com.ownrag.config.Settings;
import com.ownrag.config.StepDef;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 并发回归：SQLite「读事务升级写锁」的端到端防线。
 *
 * 场景对齐线上批量灌库：4 条管道并发跑 + 一个外部线程持续提交写库。
 * 每条管道是"先读（reader，模拟 getTask / dedupe 查指纹）后写（writer，模拟
 * markRunning / index_upsert）"两步——正是修复前必挂的形状。
 *
 * 修复前：reader 开的读事务挂到 writer，外部线程已提交 → SQLITE_BUSY_SNAPSHOT（busy_timeout 无效）
 *         → 任务 failed，待办堆积。
 * 修复后：executor 在步骤边界 endRead，40 个任务全 done。
 */
class PipelineConcurrencyTest {

    @TempDir
    Path tmp;

    private static final int THREADS = 4;
    private static final int TASKS_PER_THREAD = 10;

    /** 只读步骤：故意把读事务窗口拉到 8ms，制造"读快照已过期"的时间差。 */
    static class ReaderStep implements Step {
        @Override
        public String type() {
            return "reader";
        }

        @Override
        public StepResult run(StepContext ctx, Map<String, Object> params) {
            try {
                try (Statement st = ctx.conn.createStatement();
                     ResultSet rs = st.executeQuery("SELECT COUNT(*) FROM tasks")) {
                    rs.next();
                }
                Thread.sleep(8);
                return StepResult.okMetrics("read", 1);
            } catch (Exception e) {
                return StepResult.fail("读失败：" + e.getMessage());
            }
        }
    }

    /** 写入步骤：读事务只能靠 executor 在步骤边界收尾，这里自己不管。 */
    static class WriterStep implements Step {
        @Override
        public String type() {
            return "writer";
        }

        @Override
        public StepResult run(StepContext ctx, Map<String, Object> params) {
            try (PreparedStatement ps = ctx.conn.prepareStatement(
                    "INSERT INTO traces(trace_id, step, status) VALUES (?,?,?)")) {
                ps.setString(1, ctx.traceId);
                ps.setString(2, "writer");
                ps.setString(3, "ok");
                ps.executeUpdate();
                ctx.conn.commit();
                return StepResult.okMetrics("wrote", 1);
            } catch (SQLException e) {
                return StepResult.fail("写失败：" + e.getMessage());
            }
        }
    }

    private Settings settings(Path dataDir, PipelineDef... pipelines) {
        Map<String, PipelineDef> defs = new LinkedHashMap<>();
        for (PipelineDef p : pipelines) {
            defs.put(p.name, p);
        }
        return new Settings(dataDir, "",
                "http://127.0.0.1:11434", "openai", "http://localhost:1/v1", "k", "m",
                "openai", "http://localhost:1/v1", "k", "bge-m3", "test", "",
                "", "", "BAAI/bge-reranker-v2-m3", "",
                "open", "", com.ownrag.ingest.MineruOpenClient.API_BASE_DEFAULT, "",
                "", "", "", "",
                6144, 512, 200,
                defs, new LinkedHashMap<>(), new LinkedHashMap<>());
    }

    private static StepDef step(String type) {
        StepDef s = new StepDef();
        s.type = type;
        return s;
    }

    @Test
    void 并发管道_读后写不再退化成failed() throws Exception {
        PipelineDef def = new PipelineDef();
        def.name = "p1";
        def.steps.add(step("reader"));
        def.steps.add(step("writer"));

        Settings s = settings(tmp.resolve("data"), def);
        StepRegistry registry = new StepRegistry(new ArrayList<Step>(
                java.util.Arrays.asList(new ReaderStep(), new WriterStep())));
        PipelineExecutor executor = new PipelineExecutor(registry, new TaskStore(), new TraceLog(), s);
        Db.initSchema(s.getDbPath());

        // 外部噪声线程：模拟上传/审批/别的 worker 持续提交，专门让读快照过期
        AtomicBoolean stop = new AtomicBoolean(false);
        AtomicInteger noiseWrites = new AtomicInteger();
        Thread noise = new Thread(() -> {
            try (Connection conn = Db.connect(s.getDbPath())) {
                int i = 0;
                while (!stop.get()) {
                    try {
                        try (PreparedStatement ps = conn.prepareStatement(
                                "INSERT INTO tasks(id, doc_id, pipeline, kb, status) VALUES (?,?,?,?,?)")) {
                            ps.setString(1, "noise-" + i++);
                            ps.setString(2, "noise-doc");
                            ps.setString(3, "p1");
                            ps.setString(4, "kb");
                            ps.setString(5, "pending");
                            ps.executeUpdate();
                        }
                        conn.commit();
                        noiseWrites.incrementAndGet();
                    } catch (SQLException e) {
                        conn.rollback();   // 噪声自己撞 BUSY 无妨，重来即可
                    }
                    Thread.sleep(2);
                }
            } catch (Exception ignored) {
                // 线程退出：测试结束
            }
        }, "noise-writer");
        noise.setDaemon(true);
        noise.start();

        CountDownLatch go = new CountDownLatch(1);
        List<Thread> workers = new ArrayList<>();
        List<String> failures = java.util.Collections.synchronizedList(new ArrayList<>());
        for (int t = 0; t < THREADS; t++) {
            final int tid = t;
            Thread w = new Thread(() -> {
                try {
                    go.await();
                    try (Connection conn = Db.connect(s.getDbPath())) {
                        for (int i = 0; i < TASKS_PER_THREAD; i++) {
                            String docId = "d-" + tid + "-" + i;
                            String taskId = TaskStore.createTask(conn, docId, "p1",
                                    "trace-" + tid + "-" + i, "kb", new LinkedHashMap<>());
                            String status = executor.runPipeline(conn, taskId, false);
                            if (!TaskStore.STATUS_DONE.equals(status)) {
                                Map<String, Object> task = TaskStore.getTask(conn, taskId);
                                failures.add(taskId + " → " + status + " : " + task.get("error"));
                            }
                        }
                    }
                } catch (Exception e) {
                    failures.add("线程异常：" + e);
                }
            }, "pipe-" + t);
            w.setDaemon(true);
            workers.add(w);
            w.start();
        }

        go.countDown();
        for (Thread w : workers) {
            w.join(60_000);
        }
        stop.set(true);
        noise.join(5_000);

        assertTrue(noiseWrites.get() > 0, "噪声线程没写成功，测试无效");
        assertTrue(failures.isEmpty(), "并发下有任务没跑完：" + failures);

        try (Connection conn = Db.connect(s.getDbPath())) {
            try (Statement st = conn.createStatement();
                 ResultSet rs = st.executeQuery(
                         "SELECT COUNT(*) FROM tasks WHERE pipeline='p1' AND doc_id LIKE 'd-%'")) {
                rs.next();
                assertEquals(THREADS * TASKS_PER_THREAD, rs.getInt(1));
            }
            try (Statement st = conn.createStatement();
                 ResultSet rs = st.executeQuery(
                         "SELECT COUNT(*) FROM tasks WHERE status='failed'")) {
                rs.next();
                assertEquals(0, rs.getInt(1), "不应出现 failed（修复前这里会是 SQLITE_BUSY）");
            }
        }
    }
}
