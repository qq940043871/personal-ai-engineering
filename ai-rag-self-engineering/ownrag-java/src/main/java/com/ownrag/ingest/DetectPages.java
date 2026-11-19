package com.ownrag.ingest;

import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Map;

import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.text.PDFTextStripper;
import org.springframework.stereotype.Component;

import com.ownrag.core.Step;
import com.ownrag.core.StepContext;
import com.ownrag.core.StepResult;

/**
 * 页级路由探测（Python 版 DetectPages 的平移）：抽样判版式，电子版走 pipeline（快），
 * 扫描/复杂版式建议 VLM（准）。判定允许人工在待办里改判重跑——判定错了两头不讨好。
 */
@Component
public class DetectPages implements Step {

    @Override
    public String type() {
        return "detect_pages";
    }

    @Override
    public StepResult run(StepContext ctx, Map<String, Object> params) {
        Path src = Paths.get(String.valueOf(ctx.data.get("source_path")));
        if (!src.getFileName().toString().toLowerCase().endsWith(".pdf")) {
            return StepResult.ok(StepResult.pairs("page_route", "skip"),
                    StepResult.pairs("sample_pages", 0));
        }

        int sampleN = params.get("sample_pages") instanceof Number
                ? ((Number) params.get("sample_pages")).intValue() : 3;
        int textChars = sampleTextChars(src, sampleN);
        // 极简口径：抽样页几乎无文本层 → 扫描件倾向 VLM；有文本层 → pipeline。
        // 复杂版式（多栏/嵌套表）的精细判定留给 MinerU 自身后端能力。
        String route = textChars > 50 ? "pipeline" : "vlm";
        return StepResult.ok(StepResult.pairs("page_route", route),
                StepResult.pairs("sampled", sampleN, "text_chars", textChars));
    }

    /** 抽样前 n 页文本层字符总数；PDFBox 加载失败 → 999（无法探测时不拦路，交由 parse_mineru 自身路由）。 */
    static int sampleTextChars(Path src, int n) {
        try (PDDocument doc = PDDocument.load(src.toFile())) {
            int pages = Math.min(Math.max(n, 0), doc.getNumberOfPages());
            int total = 0;
            PDFTextStripper stripper = new PDFTextStripper();
            for (int i = 1; i <= pages; i++) {
                stripper.setStartPage(i);
                stripper.setEndPage(i);
                String text = stripper.getText(doc);
                total += text == null ? 0 : text.trim().length();
            }
            return total;
        } catch (Exception e) {
            return 999;
        }
    }
}
