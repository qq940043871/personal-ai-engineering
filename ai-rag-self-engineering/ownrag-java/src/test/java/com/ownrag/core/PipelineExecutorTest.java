package com.ownrag.core;

import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import com.ownrag.config.PipelineDef;
import com.ownrag.config.Settings;
import com.ownrag.config.StepDef;

import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 管道执行器回归：fallback 降级链（前败后继）、检查点续跑、失败入待办。
 * 对齐 Python 版 test_pipeline 语义。
 */
class PipelineExecutorTest {

    @TempDir
    Path tmp;

    /** 可编排的测试步骤：按 type() 返回预设结果。 */
    static class ScriptedStep implements Step {
        private final String type;
        private final Map<String, StepResult> scripts = new LinkedHashMap<>();
        private final List<String> calls = new ArrayList<>();

        ScriptedStep(String type) {
            this.type = type;
        }

        ScriptedStep on(Map<String, Object> expectParams, StepResult result) {
            scripts.put(expectParams.isEmpty() ? "*" : String.valueOf(expectParams.get("backend")), result);
            return this;
        }

        @Override
        public String type() {
            return type;
        }

        @Override
        public StepResult run(StepContext ctx, Map<String, Object> params) {
            calls.add(String.valueOf(params.get("backend")));
            StepResult r = scripts.getOrDefault(String.valueOf(params.get("backend")), null);
            if (r != null) {
                return r;
            }
            return StepResult.okMetrics("ran", type);
        }
    }

    private Settings settings(Path dataDir, PipelineDef... pipelines) {
        Map<String, PipelineDef> defs = new LinkedHashMap<>();
        for (PipelineDef p : pipelines) {
            defs.put(p.name, p);
        }
        // Settings 构造参数多，借 Embedder 所在包的完整构造：直接 new
        return new Settings(dataDir, "",
                "http://127.0.0.1:11434", "openai", "http://localhost:1/v1", "k", "m",
                "openai", "http://localhost:1/v1", "k", "bge-m3", "test", "",
                "", "", "BAAI/bge-reranker-v2-m3", "",
                "open", "", com.ownrag.ingest.MineruOpenClient.API_BASE_DEFAULT, "",
                "", "", "", "",
                6144, 512, 200,
                defs, new LinkedHashMap<>(), new LinkedHashMap<>());
    }

    private static PipelineDef pipeline(String name, StepDef... steps) {
        PipelineDef p = new PipelineDef();
        p.name = name;
        for (StepDef s : steps) {
            p.steps.add(s);
        }
        return p;
    }

    private static StepDef step(String type, String backend) {
        StepDef s = new StepDef();
        s.type = type;
        if (backend != null) {
            s.params.put("backend", backend);
        }
        return s;
    }

    @Test
    void fallback链_前败后继_成功采纳() throws Exception {
        ScriptedStep parse = new ScriptedStep("parse");
        parse.on(java.util.Collections.singletonMap("backend", "auto"), StepResult.fail("云端额度耗尽"));
        parse.on(java.util.Collections.singletonMap("backend", "pipeline"), StepResult.okMetrics("ok", 1));

        StepDef main = step("parse", "auto");
        StepDef fb1 = step("parse", "pipeline");
        main.fallback.add(fb1);
        StepDef fb2 = step("parse", "cli");
        main.fallback.add(fb2);

        PipelineDef def = pipeline("p1", main, step("next", null));
        Settings s = settings(tmp.resolve("data"), def);
        ScriptedStep next = new ScriptedStep("next");
        StepRegistry registry = new StepRegistry(new ArrayList<>(java.util.Arrays.asList(parse, next)));
        PipelineExecutor executor = new PipelineExecutor(registry, new TaskStore(), new TraceLog(), s);

        Db.initSchema(s.getDbPath());
        String taskId;
        try (Connection conn = Db.connect(s.getDbPath())) {
            taskId = TaskStore.createTask(conn, "doc1", "p1", "t1", "default",
                    java.util.Collections.singletonMap("source_path", "x.pdf"));
            String status = executor.runPipeline(conn, taskId, false);
            assertEquals("done", status);
            // 调用序列：auto 失败 → pipeline 成功；fallback2 未执行
            assertEquals(java.util.Arrays.asList("auto", "pipeline"), parse.calls);
        }
        try (Connection conn = Db.connect(s.getDbPath())) {
            Map<String, Object> task = TaskStore.getTask(conn, taskId);
            assertEquals("done", task.get("status"));
            assertEquals(0, TaskStore.listTodos(conn, true).size(), "成功路径不进待办");
        }
    }

    @Test
    void 全链穷尽失败_任务failed入待办() throws Exception {
        ScriptedStep parse = new ScriptedStep("parse");
        parse.on(java.util.Collections.singletonMap("backend", "auto"), StepResult.fail("A败"));
        parse.on(java.util.Collections.singletonMap("backend", "pipeline"), StepResult.fail("B败"));

        StepDef main = step("parse", "auto");
        main.fallback.add(step("parse", "pipeline"));

        PipelineDef def = pipeline("p1", main);
        Settings s = settings(tmp.resolve("data2"), def);
        StepRegistry registry = new StepRegistry(new ArrayList<>(java.util.Collections.singletonList(parse)));
        PipelineExecutor executor = new PipelineExecutor(registry, new TaskStore(), new TraceLog(), s);

        Db.initSchema(s.getDbPath());
        String taskId;
        try (Connection conn = Db.connect(s.getDbPath())) {
            taskId = TaskStore.createTask(conn, "doc1", "p1", "t2", "default", new LinkedHashMap<>());
            String status = executor.runPipeline(conn, taskId, false);
            assertEquals("failed", status);
        }
        try (Connection conn = Db.connect(s.getDbPath())) {
            Map<String, Object> task = TaskStore.getTask(conn, taskId);
            assertEquals("failed", task.get("status"));
            assertTrue(String.valueOf(task.get("error")).contains("B败"), "错误 = 最后一个 fallback 的失败");
            List<Map<String, Object>> todos = TaskStore.listTodos(conn, true);
            assertEquals(1, todos.size());
            assertTrue(String.valueOf(todos.get(0).get("reason")).contains("p1/parse"));
        }
    }

    @Test
    void 待人工复核_pending_review不记failed_不跑fallback() throws Exception {
        // review_gate 这类人工闸门：换后端也救不了"没人看过"，所以不该走 fallback，也不该算失败
        ScriptedStep gate = new ScriptedStep("review_gate");
        gate.on(java.util.Collections.singletonMap("backend", "auto"),
                StepResult.awaitReview("解析产物待人工复核"));
        StepDef main = step("review_gate", "auto");
        main.fallback.add(step("review_gate", "pipeline"));

        PipelineDef def = pipeline("p1", main);
        Settings s = settings(tmp.resolve("data6"), def);
        StepRegistry registry = new StepRegistry(new ArrayList<Step>(
                java.util.Collections.singletonList(gate)));
        PipelineExecutor executor = new PipelineExecutor(registry, new TaskStore(), new TraceLog(), s);

        Db.initSchema(s.getDbPath());
        String taskId;
        try (Connection conn = Db.connect(s.getDbPath())) {
            taskId = TaskStore.createTask(conn, "doc1", "p1", "t6", "default", new LinkedHashMap<>());
            assertEquals(TaskStore.STATUS_PENDING_REVIEW, executor.runPipeline(conn, taskId, false));
        }
        assertEquals(java.util.Collections.singletonList("auto"), gate.calls, "待复核不试 fallback 后端");
        try (Connection conn = Db.connect(s.getDbPath())) {
            Map<String, Object> task = TaskStore.getTask(conn, taskId);
            assertEquals(TaskStore.STATUS_PENDING_REVIEW, task.get("status"), "不是 failed");
            assertEquals("review_gate", task.get("current_step"), "检查点仍停在该步，复核通过可续跑");
            // 人工队列不能漏：待复核也要进待办
            List<Map<String, Object>> todos = TaskStore.listTodos(conn, true);
            assertEquals(1, todos.size());
            assertTrue(String.valueOf(todos.get(0).get("reason")).contains("待人工复核"));
            // 重复重试（resume）不该在队列里刷重复待办
            assertEquals(TaskStore.STATUS_PENDING_REVIEW, executor.runPipeline(conn, taskId, true));
            assertEquals(1, TaskStore.listTodos(conn, true).size());
            // 复核通过 = 决策已做：待办随之关闭，不留"任务 done、待办还 open"的假活
            assertEquals(1, TaskStore.closeOpenTodos(conn, taskId));
            assertEquals(0, TaskStore.listTodos(conn, true).size());
        }
    }

    @Test
    void 检查点续跑_resume从失败步骤起() throws Exception {
        // 步骤1 成功；步骤2 首次失败（带数据增量步骤3 依赖），resume 后成功
        ScriptedStep s1 = new ScriptedStep("s1");
        final boolean[] first = {true};
        ScriptedStep s2Control = new ScriptedStep("s2") {
            @Override
            public StepResult run(StepContext ctx, Map<String, Object> params) {
                if (first[0]) {
                    first[0] = false;
                    return StepResult.fail("首次失败");
                }
                return StepResult.ok(StepResult.pairs("s2out", "ok2"), StepResult.pairs("ran", 1));
            }
        };
        ScriptedStep s3 = new ScriptedStep("s3") {
            @Override
            public StepResult run(StepContext ctx, Map<String, Object> params) {
                assertEquals("ok2", ctx.data.get("s2out"), "续跑时上游产出应从检查点恢复");
                return StepResult.okMetrics("ran", 1);
            }
        };
        PipelineDef def = pipeline("p1", step("s1", null), step("s2", null), step("s3", null));
        Settings s = settings(tmp.resolve("data3"), def);
        StepRegistry registry = new StepRegistry(new ArrayList<Step>(
                java.util.Arrays.asList(s1, s2Control, s3)));
        PipelineExecutor executor = new PipelineExecutor(registry, new TaskStore(), new TraceLog(), s);

        Db.initSchema(s.getDbPath());
        String taskId;
        try (Connection conn = Db.connect(s.getDbPath())) {
            taskId = TaskStore.createTask(conn, "doc1", "p1", "t3", "default", new LinkedHashMap<>());
            assertEquals("failed", executor.runPipeline(conn, taskId, false));
        }
        try (Connection conn = Db.connect(s.getDbPath())) {
            Map<String, Object> task = TaskStore.getTask(conn, taskId);
            assertEquals("s2", task.get("current_step"), "检查点 = 失败步骤");
            // resume：从 s2 起（s1 不再执行）
            assertEquals("done", executor.runPipeline(conn, taskId, true));
        }
    }

    @Test
    void 未注册步骤类型_fail不入todo只报缺失() throws Exception {
        StepDef unknown = step("no_such_step", null);
        PipelineDef def = pipeline("p1", unknown);
        Settings s = settings(tmp.resolve("data4"), def);
        StepRegistry registry = new StepRegistry(new ArrayList<>());
        PipelineExecutor executor = new PipelineExecutor(registry, new TaskStore(), new TraceLog(), s);
        Db.initSchema(s.getDbPath());
        try (Connection conn = Db.connect(s.getDbPath())) {
            String taskId = TaskStore.createTask(conn, "doc1", "p1", "t4", "default", new LinkedHashMap<>());
            assertEquals("failed", executor.runPipeline(conn, taskId, false));
            Map<String, Object> task = TaskStore.getTask(conn, taskId);
            assertTrue(String.valueOf(task.get("error")).contains("未注册"));
        }
    }

    @Test
    void 步骤内抛异常_执行器不崩() throws Exception {
        Step boom = new Step() {
            @Override
            public String type() {
                return "boom";
            }

            @Override
            public StepResult run(StepContext ctx, Map<String, Object> params) {
                throw new IllegalStateException("步骤内部炸了");
            }
        };
        PipelineDef def = pipeline("p1", step("boom", null));
        Settings s = settings(tmp.resolve("data5"), def);
        StepRegistry registry = new StepRegistry(new ArrayList<>(java.util.Collections.singletonList(boom)));
        PipelineExecutor executor = new PipelineExecutor(registry, new TaskStore(), new TraceLog(), s);
        Db.initSchema(s.getDbPath());
        try (Connection conn = Db.connect(s.getDbPath())) {
            String taskId = TaskStore.createTask(conn, "doc1", "p1", "t5", "default", new LinkedHashMap<>());
            assertEquals("failed", executor.runPipeline(conn, taskId, false));
            List<Map<String, Object>> todos = TaskStore.listTodos(conn, true);
            assertEquals(1, todos.size());
            assertTrue(String.valueOf(todos.get(0).get("reason")).contains("IllegalStateException"));
        }
    }

    @Test
    void fts_cjk_索引查询同函数() {
        String out = ChunkStoreFtsBridge.ftsCjk("报销口径v2 与ABC流程");
        // CJK 逐字 + 拉丁词
        assertTrue(out.contains("报 销 口 径"));
        assertTrue(out.contains("v2"));
        assertTrue(out.contains("ABC"));
    }

    @Test
    void 步骤注册表_重复type启动期爆() {
        ScriptedStep a = new ScriptedStep("dup");
        ScriptedStep b = new ScriptedStep("dup");
        Exception e = assertThrows(IllegalStateException.class,
                () -> new StepRegistry(new ArrayList<Step>(java.util.Arrays.asList(a, b))));
        assertTrue(e.getMessage().contains("重复注册"));
    }
}

/** ftsCjk 桥（避免测试类直接依赖包私有）。 */
class ChunkStoreFtsBridge {
    static String ftsCjk(String s) {
        return com.ownrag.index.ChunkStore.ftsCjk(s);
    }

    /** JDK8 无 String.repeat：测试用小工具。 */
    private static String rep(String s, int n) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < n; i++) {
            sb.append(s);
        }
        return sb.toString();
    }
}
