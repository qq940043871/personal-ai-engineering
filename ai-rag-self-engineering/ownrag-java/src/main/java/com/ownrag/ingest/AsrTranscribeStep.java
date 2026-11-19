package com.ownrag.ingest;

import java.nio.file.Paths;
import java.util.List;
import java.util.Map;

import org.springframework.stereotype.Component;

import com.ownrag.core.Step;
import com.ownrag.core.StepContext;
import com.ownrag.core.StepResult;

import okhttp3.OkHttpClient;

/**
 * asr_transcribe 步骤（Java 版替代 Python 进程内引擎）：
 * OpenAI 兼容 HTTP ASR → 段级时间戳转写。服务地址由 models.yaml asr 段 / 环境变量配置；
 * 未配置或失败 → 任务失败入待办（绝不静默）。
 */
@Component
public class AsrTranscribeStep implements Step {

    private final OkHttpClient http;

    public AsrTranscribeStep(OkHttpClient http) {
        this.http = http;
    }

    @Override
    public String type() {
        return "asr_transcribe";
    }

    @Override
    public StepResult run(StepContext ctx, Map<String, Object> params) {
        Object wav = ctx.data.get("audio_wav");
        if (wav == null || String.valueOf(wav).isEmpty()) {
            return StepResult.fail("无 audio_wav——上游 ff_extract_audio 缺失？");
        }
        String engine = params.get("engine") == null ? "openai" : String.valueOf(params.get("engine"));
        if (!"openai".equals(engine)) {
            return StepResult.fail("未知 ASR 引擎：" + engine
                    + "（Java 版仅支持 openai 兼容 HTTP 契约，engine=openai）");
        }
        List<Map<String, Object>> segments;
        boolean approx;
        try {
            AsrClient client = new AsrClient(http);
            double duration = ctx.data.get("duration_sec") instanceof Number
                    ? ((Number) ctx.data.get("duration_sec")).doubleValue() : 0.0;
            segments = client.transcribe(
                    ctx.settings.getAsrBaseUrl(), ctx.settings.getAsrApiKey(),
                    ctx.settings.getAsrModel(), ctx.settings.getAsrLanguage(),
                    Paths.get(String.valueOf(wav)), duration);
            approx = client.isApproximated();
        } catch (Exception e) {
            return StepResult.fail("ASR 转写失败：" + e.getMessage());
        }
        if (segments.isEmpty()) {
            return StepResult.fail("转写结果为空（静音或引擎异常）");
        }
        ctx.data.put("segments", segments);
        ctx.data.put("ts_approximated", approx);
        return StepResult.okMetrics("engine", "openai", "model", ctx.settings.getAsrModel(),
                "segments", segments.size(), "ts_approximated", approx ? 1 : 0);
    }
}
