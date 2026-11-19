package com.ownrag.ingest;

import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** ASR 客户端纯逻辑回归：近似时间戳合成 + 媒体路径防逃逸。 */
class AsrClientAndMediaTest {

    @Test
    void synthesizeSegments_按句切分时间单调递增且铺满时长() {
        String text = "第一句话内容比较长一些。第二句话也稍微长一点的！第三句话同样超过十二个字了；结尾也拉长了些。";
        List<Map<String, Object>> segs = AsrClient.synthesizeSegments(text, 40.0);
        assertEquals(4, segs.size());
        double t = 0;
        for (Map<String, Object> s : segs) {
            assertEquals(t, (Double) s.get("start"), 0.01);
            assertTrue((Double) s.get("end") > (Double) s.get("start"));
            t = (Double) s.get("end");
            assertTrue(String.valueOf(s.get("text")).endsWith("。")
                    || String.valueOf(s.get("text")).endsWith("！")
                    || String.valueOf(s.get("text")).endsWith("；"));
        }
        assertEquals(40.0, t, 0.05, "全部段拼起来应铺满音频时长");
        for (Map<String, Object> s : segs) {
            assertEquals(0.0, (Double) s.get("conf"), 1e-9, "近似段不标置信度（不触发 [?mm:ss] 标记）");
        }
    }

    @Test
    void synthesizeSegments_无句尾时整段一块() {
        List<Map<String, Object>> segs = AsrClient.synthesizeSegments("没有句尾标点的长文本内容", 10.0);
        assertEquals(1, segs.size());
        assertEquals(0.0, (Double) segs.get(0).get("start"), 1e-9);
        assertEquals(10.0, (Double) segs.get(0).get("end"), 1e-9);
    }

    @Test
    void mediaSafe_防路径逃逸() {
        java.nio.file.Path base = java.nio.file.Paths.get("data/parsed").toAbsolutePath().normalize();
        assertNull(MediaControllerSafeBridge.safe(base, "../files/x.mp4"), ".. 必须被拒绝");
        assertNull(MediaControllerSafeBridge.safe(base, "a/../../b"), "间接 .. 必须被拒绝");
        assertNull(MediaControllerSafeBridge.safe(base, "C:/Windows/win.ini"), "盘符必须被拒绝");
        java.nio.file.Path ok = MediaControllerSafeBridge.safe(base, "images/a.jpg");
        assertEquals(base.resolve("images/a.jpg").normalize(), ok);
    }
}

/** MediaController.safe 桥（静态包内方法跨包测试）。 */
class MediaControllerSafeBridge {
    static java.nio.file.Path safe(java.nio.file.Path base, String rest) {
        return com.ownrag.api.MediaController.safe(base, rest);
    }
}
