package com.ownrag.tools;

import java.awt.Color;
import java.awt.Font;
import java.awt.Graphics2D;
import java.io.File;

import javax.imageio.ImageIO;

import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.pdmodel.PDPage;
import org.apache.pdfbox.pdmodel.PDPageContentStream;
import org.apache.pdfbox.pdmodel.common.PDRectangle;
import org.apache.pdfbox.pdmodel.font.PDType0Font;
import org.apache.pdfbox.pdmodel.graphics.image.PDImageXObject;
import org.apache.pdfbox.pdmodel.graphics.state.RenderingMode;

/** E2E 验证辅助：生成带内嵌图片与公式文本的富 PDF（仅测试用）。 */
public final class E2eRichPdfGen {

    public static void main(String[] args) throws Exception {
        String out = args.length > 0 ? args[0] : "e2e/e2e_rich.pdf";
        File png = File.createTempFile("chart", ".png");
        png.deleteOnExit();
        drawChart(png);

        try (PDDocument doc = new PDDocument()) {
            org.apache.fontbox.ttf.TrueTypeCollection ttc =
                    new org.apache.fontbox.ttf.TrueTypeCollection(new File("C:\\Windows\\Fonts\\simsun.ttc"));
            PDType0Font font = PDType0Font.load(doc, ttc.getFontByName("SimSun"), true);

            PDPage page = new PDPage(PDRectangle.A4);
            doc.addPage(page);
            PDPageContentStream cs = new PDPageContentStream(doc, page);
            float y = 780;

            y = line(cs, font, y, "物理常数速查（示例文档）");
            y = line(cs, font, y, "质能方程写作 $$E = mc^2$$，其中 c 为真空光速。");
            y = line(cs, font, y, "动能公式 $E_k = \\frac{1}{2}mv^2$，重力势能 $E_p = mgh$。");

            // 内嵌图片（MinerU 会抽出图片并在 markdown 里以相对路径引用）
            PDImageXObject img = PDImageXObject.createFromFileByContent(png, doc);
            float w = 300, h = w * img.getHeight() / img.getWidth();
            cs.drawImage(img, 60, y - h, w, h);
            y -= h + 24;
            cs.setNonStrokingColor(Color.GRAY);
            cs.beginText();
            cs.setFont(font, 11);
            cs.newLineAtOffset(60, y);
            cs.showText("图 1：示例数据曲线（内嵌位图）");
            cs.endText();
            y -= 30;
            cs.setNonStrokingColor(Color.BLACK);

            y = line(cs, font, y, "欧拉恒等式 $$e^{i\\pi} + 1 = 0$$ 被誉为最优美的公式。");
            y = line(cs, font, y, "以上内容用于验证 UI 的图片与公式渲染链路。");
            cs.close();
            doc.save(out);
        }
        System.out.println("rich PDF written: " + out);
    }

    private static float line(PDPageContentStream cs, PDType0Font font, float y, String text)
            throws Exception {
        cs.setNonStrokingColor(Color.BLACK);
        cs.beginText();
        cs.setFont(font, 13);
        cs.newLineAtOffset(60, y);
        cs.showText(text);
        cs.endText();
        return y - 28;
    }

    /** 画一张简单折线图 PNG（MinerU 会把它抽成 images/*.png 并在 md 里引用）。 */
    private static void drawChart(File png) throws Exception {
        java.awt.image.BufferedImage img =
                new java.awt.image.BufferedImage(480, 280, java.awt.image.BufferedImage.TYPE_INT_RGB);
        Graphics2D g = img.createGraphics();
        g.setColor(Color.WHITE);
        g.fillRect(0, 0, 480, 280);
        g.setColor(new Color(235, 238, 244));
        for (int gx = 40; gx <= 440; gx += 50) {
            g.drawLine(gx, 30, gx, 240);
        }
        for (int gy = 30; gy <= 240; gy += 35) {
            g.drawLine(40, gy, 440, gy);
        }
        g.setColor(new Color(31, 97, 196));
        g.setFont(new Font("SansSerif", Font.BOLD, 14));
        g.drawString("Sample Curve", 180, 24);
        int[] xs = {40, 90, 140, 190, 240, 290, 340, 390, 440};
        int[] ys = {200, 160, 175, 120, 90, 110, 70, 55, 60};
        g.setRenderingHint(java.awt.RenderingHints.KEY_ANTIALIASING,
                java.awt.RenderingHints.VALUE_ANTIALIAS_ON);
        for (int i = 0; i < xs.length - 1; i++) {
            g.drawLine(xs[i], ys[i], xs[i + 1], ys[i + 1]);
        }
        g.setColor(new Color(192, 57, 43));
        for (int i = 0; i < xs.length; i++) {
            g.fillOval(xs[i] - 4, ys[i] - 4, 8, 8);
        }
        g.dispose();
        ImageIO.write(img, "png", png);
    }
}
