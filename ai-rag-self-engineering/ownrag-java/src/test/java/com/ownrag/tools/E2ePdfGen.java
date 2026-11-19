package com.ownrag.tools;

import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.pdmodel.PDPage;
import org.apache.pdfbox.pdmodel.PDPageContentStream;
import org.apache.pdfbox.pdmodel.font.PDType0Font;

/** E2E 验证辅助：生成两页中文政策 PDF（仅测试用，不进主代码）。 */
public final class E2ePdfGen {

    public static void main(String[] args) throws Exception {
        String out = args.length > 0 ? args[0] : "e2e_policy.pdf";
        try (PDDocument doc = new PDDocument()) {
            // TTC 集合字体：先按索引取出 TTF 再装载
            org.apache.fontbox.ttf.TrueTypeCollection ttc =
                    new org.apache.fontbox.ttf.TrueTypeCollection(
                            new java.io.File("C:\\Windows\\Fonts\\simsun.ttc"));
            PDType0Font font = PDType0Font.load(doc, ttc.getFontByName("SimSun"), true);
            String[][] pages = {
                    {"公司差旅费管理办法（2026 年修订）",
                     "第一条 员工出差须提前三个工作日提交申请，经部门负责人审批。",
                     "第二条 市内交通费实报实销，每日上限 80 元。",
                     "第三条 住宿费标准：一线城市每晚 400 元，其他城市 300 元。"},
                    {"报销流程与口径",
                     "第四条 差旅报销须在返回后 10 个工作日内提交，逾期不予受理。",
                     "第五条 报销材料包括：行程单、发票原件、审批单。",
                     "第六条 本办法自 2026 年 1 月 1 日起施行。"},
            };
            for (String[] lines : pages) {
                PDPage page = new PDPage();
                doc.addPage(page);
                PDPageContentStream cs = new PDPageContentStream(doc, page);
                float y = 750;
                for (String line : lines) {
                    cs.beginText();
                    cs.setFont(font, 14);
                    cs.newLineAtOffset(60, y);
                    cs.showText(line);
                    cs.endText();
                    y -= 40;
                }
                cs.close();
            }
            doc.save(out);
        }
        System.out.println("PDF written: " + out);
    }
}
