package com.ownrag.index;

import java.util.Map;

import org.springframework.stereotype.Component;

import com.ownrag.core.Step;
import com.ownrag.core.StepContext;
import com.ownrag.core.StepResult;

/**
 * clean_markdown 步骤：把"解析产物"变成"可切分正文"的显式一层。
 *
 * 为什么它要占一个步骤位（明明 chunk_markdown 自己也能调清洗）：
 *   1. 清洗规则会删内容（页码行、页标记、页眉残留），删了什么必须能在 trace 里按文档看到；
 *   2. 参数只在这里归一化一次（写 ctx.data.clean_options），切分与复核工件读同一份口径；
 *   3. 复核页的"解析后 / 清洗后"两栏之所以能对得上，是因为两边用的就是同一组参数。
 *
 * 契约：只写统计与参数进黑板，**不写清洗后全文**（tasks.state_json 已是全表最大列，
 * 再存一份全文等于把检查点体积翻倍）；下游用 CleanMarkdown.apply(parsed.markdown, 同一参数) 现算。
 */
@Component
public class CleanMarkdownStep implements Step {

    @Override
    public String type() {
        return "clean_markdown";
    }

    @SuppressWarnings("unchecked")
    @Override
    public StepResult run(StepContext ctx, Map<String, Object> params) {
        Map<String, Object> parsed = ctx.data.get("parsed") instanceof Map
                ? (Map<String, Object>) ctx.data.get("parsed") : new java.util.LinkedHashMap<String, Object>();
        Object md = parsed.get("markdown");
        if (md == null || String.valueOf(md).trim().isEmpty()) {
            return StepResult.fail("无 parsed.markdown——clean_markdown 必须排在解析步骤之后");
        }
        CleanMarkdown.Result cleaned = CleanMarkdown.apply(String.valueOf(md), params);
        if (cleaned.markdown.trim().isEmpty()) {
            return StepResult.fail("清洗后正文为空（回退保护亦未取回正文）：请检查 clean_markdown 参数");
        }
        ctx.data.put("clean", cleaned.stats);
        ctx.data.put("clean_options", CleanMarkdown.options(params));

        Map<String, Object> stats = cleaned.stats;
        return StepResult.okMetrics(
                "chars_in", stats.get("chars_in"),
                "chars_out", stats.get("chars_out"),
                "removed", stats.get("removed_chars"),
                "removed_ratio", stats.get("removed_ratio"),
                "page_markers", stats.get("page_markers"),
                "page_numbers", stats.get("page_numbers"),
                "comments", stats.get("comments"),
                "blank_lines", stats.get("blank_lines"));
    }
}
