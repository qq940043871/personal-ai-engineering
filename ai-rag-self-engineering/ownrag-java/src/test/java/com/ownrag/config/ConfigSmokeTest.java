package com.ownrag.config;

import java.util.ArrayList;
import java.util.List;

import org.junit.jupiter.api.Test;

import com.ownrag.core.Step;
import com.ownrag.core.StepRegistry;
import com.ownrag.index.ChunkMarkdownStep;
import com.ownrag.index.CleanMarkdownStep;
import com.ownrag.index.DedupeChunksStep;
import com.ownrag.index.EmbedStep;
import com.ownrag.index.IndexUpsertStep;
import com.ownrag.index.ValidateParsedStep;
import com.ownrag.ingest.AsrTranscribeStep;
import com.ownrag.ingest.ColumnMappingStep;
import com.ownrag.ingest.DetectPages;
import com.ownrag.ingest.ExcelStageStep;
import com.ownrag.ingest.FfExtractAudioStep;
import com.ownrag.ingest.OcrKeyframesStep;
import com.ownrag.ingest.ParseDocx;
import com.ownrag.ingest.ParseMineru;
import com.ownrag.ingest.ParsePdfbox;
import com.ownrag.ingest.ParseTextFile;
import com.ownrag.ingest.SchemaInferStep;
import com.ownrag.ingest.SegmentByTimeStep;
import com.ownrag.ingest.TextualizeStep;
import com.ownrag.review.PrepareReviewStep;
import com.ownrag.review.ReviewGateStep;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 配置冒烟（classpath:configs 默认装载）：新管道/新步骤/新应用/新 Prompt 全部注册在位，
 * DSL 引用的步骤类型与注册表一致（启动期校验口径在测试期提前爆）。
 */
class ConfigSmokeTest {

    @Test
    void 默认配置装载_新链路双模式全在位() {
        Settings s = new ConfigLoader().load();

        // 六条管道齐：pdf/av/excel 老链路 + md/txt/docx 新链路
        assertNotNull(s.pipeline("pdf_v1"));
        assertNotNull(s.pipeline("av_v1"));
        assertNotNull(s.pipeline("excel_v1"));
        assertNotNull(s.pipeline("md_v1"));
        assertNotNull(s.pipeline("txt_v1"));
        assertNotNull(s.pipeline("docx_v1"));

        // 每条链路都必须显式有 clean_markdown，且排在 chunk_markdown 之前：
        // 复核页的"清洗后"那一栏 = 实际切分输入，缺这步就只能看到解析原样，对比失去意义
        for (String name : new String[]{"pdf_v1", "av_v1", "excel_v1", "md_v1", "txt_v1", "docx_v1"}) {
            int clean = -1;
            int chunk = -1;
            List<StepDef> steps = s.pipeline(name).steps;
            for (int i = 0; i < steps.size(); i++) {
                if ("clean_markdown".equals(steps.get(i).type)) {
                    clean = i;
                }
                if ("chunk_markdown".equals(steps.get(i).type) && chunk < 0) {
                    chunk = i;
                }
            }
            assertTrue(clean >= 0, name + " 缺少 clean_markdown 步骤");
            assertTrue(chunk > clean, name + " 的 clean_markdown 必须排在 chunk_markdown 之前");
        }

        // 双模式 app + 引用的 prompt 装载成功
        assertNotNull(s.app("interview_coach"), "interview_coach 未定义");
        assertNotNull(s.app("knowledge_advisor"), "knowledge_advisor 未定义");
        assertEquals("persona_v1", s.app("interview_coach").prompt);
        assertNotNull(s.prompt("persona_v1"), "persona_v1 未被装载");
        assertEquals(1, s.app("interview_coach").knowledgeBases.size());
        assertEquals("kb_interview", s.app("interview_coach").knowledgeBases.get(0));
        // 当前只保留 kb_interview（其余库按用户口径已删）；这里锁"该有的在"，不锁死未来扩容
        assertTrue(s.app("knowledge_advisor").knowledgeBases.contains("kb_interview"),
                "knowledge_advisor 知识库装配缺失：" + s.app("knowledge_advisor").knowledgeBases);
        // kb 白名单随 app 装配（当前只保留 kb_interview）
        assertTrue(s.getKnownKbs().contains("kb_interview"));
        assertFalse(s.getKnownKbs().contains("kb_backend"), "kb_backend 已按用户口径删除，不应再出现在白名单");

        // 查询期路由配置在位（docs 11）：allow 决定通道白名单，SQL 护栏参数缺省值也要锁
        AppDef coach = s.app("interview_coach");
        assertTrue(coach.routingEnabled, "routing 段未装载");
        assertTrue(coach.routingAllow.contains("sql"), "allow 里没有 sql：" + coach.routingAllow);
        assertFalse(coach.routingAllow.contains("web"), "本期不实现联网，allow 不该声明 web");
        assertEquals(200, coach.sqlMaxRows);
        assertEquals("rag", coach.routingDefault);

        // DSL ↔ 注册表一致性：真实步骤类手工组册（等价启动期 validate）
        List<Step> steps = new ArrayList<>();
        steps.add(new DetectPages());
        steps.add(new ParseMineru(new okhttp3.OkHttpClient()));
        steps.add(new ParsePdfbox());
        steps.add(new ParseTextFile());
        steps.add(new ParseDocx());
        steps.add(new ValidateParsedStep());
        steps.add(new CleanMarkdownStep());
        steps.add(new ChunkMarkdownStep());
        steps.add(new DedupeChunksStep());
        steps.add(new PrepareReviewStep());
        steps.add(new ReviewGateStep());
        steps.add(new EmbedStep(new com.ownrag.index.Embedder(new okhttp3.OkHttpClient())));
        steps.add(new IndexUpsertStep());
        steps.add(new FfExtractAudioStep());
        steps.add(new AsrTranscribeStep(new okhttp3.OkHttpClient()));
        steps.add(new SegmentByTimeStep());
        steps.add(new OcrKeyframesStep());
        steps.add(new ExcelStageStep());
        steps.add(new SchemaInferStep());
        steps.add(new ColumnMappingStep());
        steps.add(new TextualizeStep());
        StepRegistry registry = new StepRegistry(steps);
        registry.validate(s);  // 引用未注册步骤类型 = 抛异常
        assertTrue(registry.describe().containsKey("dedupe_chunks"));
    }
}
