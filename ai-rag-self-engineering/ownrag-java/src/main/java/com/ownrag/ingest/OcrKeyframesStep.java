package com.ownrag.ingest;

import java.util.List;
import java.util.Map;
import java.util.LinkedHashMap;

import org.springframework.stereotype.Component;

import com.ownrag.core.Step;
import com.ownrag.core.StepContext;
import com.ownrag.core.StepResult;

/**
 * ocr_keyframes 步骤（可选）：画面文字不拼进正文——口播字幕与画面文字分字段保存，
 * 冲突不隐藏归属（某句话来自口播、某个数值来自哪一帧的画面，都能分别回到对应时间）。
 *
 * Java 版差异：无进程内 PaddleOCR，当前始终显式 skipped（降级可见，不静默）；
 * 后续可接 HTTP OCR 服务（M2）。
 */
@Component
public class OcrKeyframesStep implements Step {

    @SuppressWarnings("unchecked")
    @Override
    public String type() {
        return "ocr_keyframes";
    }

    @SuppressWarnings("unchecked")
    @Override
    public StepResult run(StepContext ctx, Map<String, Object> params) {
        Map<String, Object> assets = ctx.data.get("assets") instanceof Map
                ? (Map<String, Object>) ctx.data.get("assets") : new LinkedHashMap<>();
        if (assets.isEmpty()) {
            return StepResult.okMetrics("ocr", 0, "ocr_note", "无关键帧（纯音频或未抽帧）");
        }
        // 显式降级：OCR 通道不可用（Java 版无进程内 OCR），留 structures 不动、记 note
        Map<String, Object> metrics = new LinkedHashMap<>();
        metrics.put("ocr", 0);
        metrics.put("ocr_note", "OCR 不可用（Java 版未接 OCR 通道，显式降级）");
        return StepResult.ok(new java.util.LinkedHashMap<>(), metrics);
    }
}
