package com.ownrag.ingest;

import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.text.PDFTextStripper;
import org.springframework.stereotype.Component;

import com.ownrag.core.Step;
import com.ownrag.core.StepContext;
import com.ownrag.core.StepResult;

/**
 * 纯文本兜底（Python 版 ParsePyMuPDF 的平移，解析器换成 PDFBox）：
 * 结构丢了内容也要在。产出带页码锚点的 Markdown（降级质量可见）。
 */
@Component
public class ParsePdfbox implements Step {

    @Override
    public String type() {
        return "parse_pdfbox";
    }

    @Override
    public StepResult run(StepContext ctx, Map<String, Object> params) {
        Path src = Paths.get(String.valueOf(ctx.data.get("source_path")));
        List<String> pages = new ArrayList<>();
        try (PDDocument doc = PDDocument.load(src.toFile())) {
            PDFTextStripper stripper = new PDFTextStripper();
            for (int i = 1; i <= doc.getNumberOfPages(); i++) {
                stripper.setStartPage(i);
                stripper.setEndPage(i);
                String text = stripper.getText(doc);
                String cleaned = text == null ? "" : text.replace('\u0000', ' ').trim();
                // 与 Python 版一致：每页前置 <!--page:N--> 锚点（引用粒度 = 页）
                pages.add(cleaned.isEmpty()
                        ? "<!--page:" + i + "-->（本页无可提取文本）"
                        : "<!--page:" + i + "-->\n" + cleaned);
            }
        } catch (Exception e) {
            return StepResult.fail("PDFBox 兜底解析失败：" + e.getMessage());
        }
        String md = String.join("\n\n", pages);

        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put("source_file", src.getFileName().toString());
        metadata.put("degraded", "pdfbox 纯文本兜底，结构信息缺失");
        Object sourceMeta = ctx.data.get("source_meta");
        if (sourceMeta instanceof Map) {
            @SuppressWarnings("unchecked")
            Map<String, Object> sm = (Map<String, Object>) sourceMeta;
            metadata.putAll(sm);
        }
        Map<String, Object> stats = new LinkedHashMap<>();
        stats.put("pages", pages.size());
        stats.put("backend", "pdfbox-fallback");

        ParsedDoc doc = new ParsedDoc(ctx.docId, "pdf", md, metadata, new ArrayList<>(),
                new LinkedHashMap<>(), stats);
        String[] usable = doc.isUsable(20);
        if (usable[0] == null) {
            return StepResult.fail("兜底产出仍不可用：" + usable[1]);
        }
        ctx.data.put("parsed", doc.toMap());
        return StepResult.okMetrics("pages", pages.size(), "degraded", 1);
    }
}
