package com.ownrag.core;

import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;

import com.ownrag.config.Settings;
import com.ownrag.util.Json;

/**
 * 启动期三件套（与 Python 版 main.py lifespan 一致）：
 * ① 幂等建表 + FTS5 探测  ② DSL 全量校验：YAML type 必须在注册表，缺失即启动失败
 * 失败直接抛异常退出——配置错误启动期爆，绝不带病运行。
 */
@Component
public class StartupCheck implements ApplicationRunner {

    private static final Logger log = LoggerFactory.getLogger(StartupCheck.class);

    private final Settings settings;
    private final StepRegistry registry;
    private final com.ownrag.config.ConfigLoader configLoader;

    public StartupCheck(Settings settings, StepRegistry registry, com.ownrag.config.ConfigLoader configLoader) {
        this.settings = settings;
        this.registry = registry;
        this.configLoader = configLoader;
    }

    @Override
    public void run(ApplicationArguments args) throws Exception {
        Db.initSchema(settings.getDbPath());
        // 登录功能的首启引导：必须在建表之后（users/user_sessions 才存在），所以放这里而不是 @PostConstruct
        com.ownrag.auth.AuthService.ensureDefaultAdmin(settings);
        registry.validate(settings);
        normalizeLegacyTaskStates();
        log.info("[ownrag] 启动完成: db={} steps_registered={} pipelines={} apps={}",
                settings.getDbPath(), registry.size(), settings.getPipelines().keySet(), settings.getApps().keySet());
        log.debug("[ownrag] steps: {}", Json.write(registry.describe()));
        if (!settings.getKnownKbs().isEmpty()) {
            log.info("[ownrag] KB 白名单: {}", settings.getKnownKbs());
        }
    }

    private void normalizeLegacyTaskStates() throws Exception {
        try (java.sql.Connection conn = Db.connect(settings.getDbPath())) {
            int[] fixed = normalizeLegacyTaskStates(conn);
            if (fixed[0] > 0 || fixed[1] > 0) {
                log.info("[ownrag] 口径修正：{} 个任务 failed → pending_review，{} 条假待办关闭",
                        fixed[0], fixed[1]);
            }
        }
    }

    /**
     * 幂等口径修正（老库一次性归位，重复执行无副作用）：
     *   ① 改造前"停在 review_gate 等人"被记成 failed，按新口径改回 pending_review；
     *   ② 关掉"任务已经 done、待办还 open"的假待办（人工早已决策过，队列不该残留）。
     * 返回 [改回的任务数, 关闭的待办数]。
     */
    static int[] normalizeLegacyTaskStates(java.sql.Connection conn) throws Exception {
        int tasks;
        try (java.sql.PreparedStatement ps = conn.prepareStatement(
                "UPDATE tasks SET status=? WHERE status=? AND current_step='review_gate' "
                        + "AND error LIKE '%待人工复核%'")) {
            ps.setString(1, TaskStore.STATUS_PENDING_REVIEW);
            ps.setString(2, TaskStore.STATUS_FAILED);
            tasks = ps.executeUpdate();
        }
        int todos;
        try (java.sql.PreparedStatement ps = conn.prepareStatement(
                "UPDATE todos SET status='done', resolved_at=datetime('now','localtime') "
                        + "WHERE status='open' AND task_id IN "
                        + "(SELECT id FROM tasks WHERE status=?)")) {
            ps.setString(1, TaskStore.STATUS_DONE);
            todos = ps.executeUpdate();
        }
        conn.commit();
        return new int[]{tasks, todos};
    }
}
