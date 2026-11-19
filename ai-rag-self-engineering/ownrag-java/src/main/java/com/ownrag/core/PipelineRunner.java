package com.ownrag.core;

import java.sql.Connection;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;

import javax.annotation.PreDestroy;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import com.ownrag.config.Settings;

/**
 * 管道异步执行入口：上传/重试后投递，工作线程持独立连接跑完整个管道。
 * 默认 2 个工作线程串行消费任务（SQLite 写入天然排队，WAL 保证读不阻塞）。
 */
@Component
public class PipelineRunner {

    private static final Logger log = LoggerFactory.getLogger(PipelineRunner.class);

    private final Settings settings;
    private final PipelineExecutor executor;
    private final TaskStore taskStore;
    private final ExecutorService pool;

    public PipelineRunner(Settings settings, PipelineExecutor executor, TaskStore taskStore) {
        this.settings = settings;
        this.executor = executor;
        this.taskStore = taskStore;
        this.pool = Executors.newFixedThreadPool(1, r -> {  // 单写者：SQLite WAL 批量灌库并发=2 会 BUSY 打爆，串行最稳
            Thread t = new Thread(r, "pipeline-worker-" + WORKER_SEQ.incrementAndGet());
            t.setDaemon(false);
            return t;
        });
    }

    private static final AtomicInteger WORKER_SEQ = new AtomicInteger();

    /** 投递一次管道执行（resume=true 时从检查点续跑）。 */
    public void submit(String taskId, boolean resume) {
        pool.execute(() -> run(taskId, resume));
    }

    private void run(String taskId, boolean resume) {
        try (Connection conn = Db.connect(settings.getDbPath())) {
            String status = executor.runPipeline(conn, taskId, resume);
            log.info("[pipeline] task={} -> {}", taskId, status);
        } catch (Exception e) {
            // 执行器崩溃级异常：任务标 failed + 入待办（与步骤失败同等待遇，绝不静默）
            log.error("[pipeline] task={} 执行器异常: {}", taskId, e.getMessage(), e);
            try (Connection conn = Db.connect(settings.getDbPath())) {
                Map<String, Object> fields = new LinkedHashMap<>();
                fields.put("status", "failed");
                fields.put("error", truncate("执行器异常: " + e.getMessage()));
                taskStore.updateTask(conn, taskId, fields);
                taskStore.addTodo(conn, taskId, null, "执行器异常: " + e.getMessage(), null);
            } catch (Exception inner) {
                log.error("[pipeline] task={} 失败状态回写也失败: {}", taskId, inner.getMessage(), inner);
            }
        }
    }

    @PreDestroy
    public void shutdown() {
        pool.shutdown();
    }

    private static String truncate(String s) {
        return s != null && s.length() > 500 ? s.substring(0, 500) : s;
    }
}
