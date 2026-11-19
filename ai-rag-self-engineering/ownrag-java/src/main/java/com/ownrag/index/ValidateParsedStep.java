package com.ownrag.index;

import java.util.Map;

import org.springframework.stereotype.Component;

import com.ownrag.core.Step;
import com.ownrag.core.StepContext;
import com.ownrag.core.StepResult;
import com.ownrag.ingest.ParsedDoc;

/**
 * validate_parsed 步骤（Python 版 ValidateParsed 的平移）：
 * 独立于 parse 的校验闸："解析成功但产出不可用"与"解析失败"同等待遇。
 */
@Component
public class ValidateParsedStep implements Step {

    @Override
    public String type() {
        return "validate_parsed";
    }

    @SuppressWarnings("unchecked")
    @Override
    public StepResult run(StepContext ctx, Map<String, Object> params) {
        Map<String, Object> parsed = (Map<String, Object>) ctx.data.get("parsed");
        int minChars = params.get("min_chars_per_page") instanceof Number
                ? ((Number) params.get("min_chars_per_page")).intValue() : 20;
        if (parsed == null || parsed.isEmpty()) {
            return StepResult.fail("校验不过：上游无 parsed 产物");
        }
        ParsedDoc doc = ParsedDoc.fromMap(parsed);
        String[] usable = doc.isUsable(minChars);
        if (usable[0] == null) {
            return StepResult.fail("校验不过：" + usable[1]);
        }
        return StepResult.okMetrics("chars",
                String.valueOf(parsed.getOrDefault("markdown", "")).length());
    }
}
