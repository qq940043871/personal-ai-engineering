package com.ownrag.ingest;

import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.stereotype.Component;

import com.ownrag.core.Step;
import com.ownrag.core.StepContext;
import com.ownrag.core.StepResult;

/**
 * segment_by_time 步骤（Python 版 SegmentByTime 的平移）：聚段成块——优先语义边界，其次时长上限。
 * 字幕不能按时长硬切。每段要能独立说清一件事：
 * - 段间停顿 > gap_sec → 自然停顿即话题边界，先切；
 * - 块长超过 max_sec → 必切，但回退到最后一个句尾段之后，不把一句话拦腰截断。
 * 低置信度段在正文上显式标记 [?mm:ss]（ASR 错误是链路噪声不是静默失败）。
 */
@Component
public class SegmentByTimeStep implements Step {

    private static final String SENT_END = "。！？；!?;…";

    @SuppressWarnings("unchecked")
    @Override
    public String type() {
        return "segment_by_time";
    }

    @SuppressWarnings("unchecked")
    @Override
    public StepResult run(StepContext ctx, Map<String, Object> params) {
        List<Map<String, Object>> segments =
                (List<Map<String, Object>>) ctx.data.getOrDefault("segments", new ArrayList<>());
        if (segments.isEmpty()) {
            return StepResult.fail("无转写段（上游 asr_transcribe 缺失？）");
        }
        double maxSec = params.get("max_sec") instanceof Number ? ((Number) params.get("max_sec")).doubleValue() : 60.0;
        double gapSec = params.get("gap_sec") instanceof Number ? ((Number) params.get("gap_sec")).doubleValue() : 1.5;
        List<String> blocks = new ArrayList<>();
        List<Map<String, Object>> buf = new ArrayList<>();
        double[] bufStart = {0.0};
        double[] prevEnd = {Double.NaN};

        Runnable flush = () -> {
            if (buf.isEmpty()) {
                return;
            }
            List<String> lines = new ArrayList<>();
            for (Map<String, Object> seg : buf) {
                String stamp = AsrClient.fmtTs(((Number) seg.get("start")).doubleValue());
                String text = String.valueOf(seg.get("text"));
                double conf = seg.get("conf") instanceof Number ? ((Number) seg.get("conf")).doubleValue() : 0.0;
                if (conf < -0.8) {  // 低置信度：检索照常，人工核验有标记
                    text = "[?" + stamp + "] " + text;
                }
                lines.add("[" + stamp + "] " + text);
            }
            blocks.add("#### [" + AsrClient.fmtTs(bufStart[0]) + "]（源视频锚点）\n\n" + String.join("\n", lines));
            buf.clear();
            bufStart[0] = 0.0;
        };

        for (Map<String, Object> seg : segments) {
            double start = ((Number) seg.get("start")).doubleValue();
            double end = ((Number) seg.get("end")).doubleValue();
            boolean paused = !Double.isNaN(prevEnd[0]) && (start - prevEnd[0]) > gapSec;
            boolean overflow = !buf.isEmpty() && (end - bufStart[0]) > maxSec;
            if (paused || overflow) {
                int cut = buf.size();
                if (overflow && cut > 1 && !endsWithSentEnd(String.valueOf(buf.get(cut - 1).get("text")))) {
                    // 超限但末段没说完：回退到最近句尾再切
                    for (int i = cut - 1; i > 0; i--) {
                        if (endsWithSentEnd(String.valueOf(buf.get(i).get("text")))) {
                            cut = i + 1;
                            break;
                        }
                    }
                }
                List<Map<String, Object>> keep = new ArrayList<>(buf.subList(cut, buf.size()));
                buf.subList(Math.min(cut, buf.size()), buf.size()).clear();
                flush.run();
                if (!keep.isEmpty()) {  // 被回退的段留给下一块，锚点跟块走
                    buf.addAll(keep);
                    bufStart[0] = ((Number) keep.get(0).get("start")).doubleValue();
                }
            }
            if (buf.isEmpty()) {
                bufStart[0] = start;
            }
            buf.add(seg);
            prevEnd[0] = end;
        }
        flush.run();

        if (blocks.isEmpty()) {
            return StepResult.fail("切分零块");
        }
        Path src = Paths.get(String.valueOf(ctx.data.get("source_path")));
        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put("source_file", src.getFileName().toString());
        metadata.put("duration_sec", ctx.data.getOrDefault("duration_sec", 0));
        Map<String, Object> splitParams = new LinkedHashMap<>();
        splitParams.put("max_sec", maxSec);
        splitParams.put("gap_sec", gapSec);
        metadata.put("split_params", splitParams);
        // 时间戳近似估算时必须可见（ASR 端点不回段时间戳 → 按字符占比估算，锚点非精确对齐）
        metadata.put("ts_approximated", Boolean.TRUE.equals(ctx.data.get("ts_approximated")));
        Object sourceMeta = ctx.data.get("source_meta");
        if (sourceMeta instanceof Map) {
            metadata.putAll((Map<String, Object>) sourceMeta);
        }
        List<Map<String, Object>> structures = keyframeStructures(ctx.data);
        Map<String, Object> assets = ctx.data.get("assets") instanceof Map
                ? (Map<String, Object>) ctx.data.get("assets") : new LinkedHashMap<>();
        Map<String, Object> stats = new LinkedHashMap<>();
        stats.put("blocks", blocks.size());
        stats.put("duration_sec", ctx.data.getOrDefault("duration_sec", 0));

        ParsedDoc doc = new ParsedDoc(ctx.docId, "av", String.join("\n\n", blocks),
                metadata, structures, stringMap(assets), stats);
        ctx.data.put("parsed", doc.toMap());
        return StepResult.okMetrics("blocks", blocks.size(), "keyframes", structures.size());
    }

    static boolean endsWithSentEnd(String text) {
        if (text.isEmpty()) {
            return false;
        }
        return SENT_END.indexOf(text.charAt(text.length() - 1)) >= 0;
    }

    static double fpsOf(String raw) {
        return AsrClient.fpsOf(raw);
    }

    /** 关键帧 → 结构化画面证据：location=t:时间锚（帧序号/fps 的窗口起点近似）。 */
    static List<Map<String, Object>> keyframeStructures(Map<String, Object> data) {
        Map<String, Object> assets = data.get("assets") instanceof Map
                ? (Map<String, Object>) data.get("assets") : new LinkedHashMap<>();
        if (assets.isEmpty()) {
            return new ArrayList<>();
        }
        double fps = fpsOf(data.get("keyframe_fps") == null ? "1/60" : String.valueOf(data.get("keyframe_fps")));
        List<String> keys = new ArrayList<>();
        keys.addAll(assets.keySet());
        java.util.Collections.sort(keys);
        List<Map<String, Object>> out = new ArrayList<>();
        int i = 0;
        for (String key : keys) {
            out.add(ParsedDoc.structure("keyframe", "t:" + AsrClient.fmtTs(i / fps), key, null));
            i++;
        }
        return out;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, String> stringMap(Map<String, Object> assets) {
        Map<String, String> out = new LinkedHashMap<>();
        for (Map.Entry<String, Object> e : assets.entrySet()) {
            out.put(e.getKey(), e.getValue() == null ? null : String.valueOf(e.getValue()));
        }
        return out;
    }
}
