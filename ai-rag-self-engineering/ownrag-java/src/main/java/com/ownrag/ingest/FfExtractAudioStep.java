package com.ownrag.ingest;

import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

import org.springframework.stereotype.Component;

import com.ownrag.core.Step;
import com.ownrag.core.StepContext;
import com.ownrag.core.StepResult;
import com.ownrag.util.Json;

/**
 * ff_extract_audio 步骤（Python 版 FfExtractAudio 的平移）：
 * -vn -ac 1 -ar 16000：ASR 标准输入；视频按固定间隔抽关键帧（画面信息不靠语音）。
 */
@Component
public class FfExtractAudioStep implements Step {

    @Override
    public String type() {
        return "ff_extract_audio";
    }

    @Override
    public StepResult run(StepContext ctx, Map<String, Object> params) {
        Path src = Paths.get(String.valueOf(ctx.data.get("source_path")));
        String ffmpeg;
        String ffprobe;
        try {
            ffmpeg = AsrClient.need("ffmpeg");
            ffprobe = AsrClient.need("ffprobe");
        } catch (IllegalStateException e) {
            return StepResult.fail(e.getMessage());
        }

        // ffprobe 拿时长
        double duration;
        try {
            AsrClient.ProcessResult probe = AsrClient.runProcess(new String[]{
                    ffprobe, "-v", "quiet", "-print_format", "json",
                    "-show_format", "-show_streams", src.toAbsolutePath().toString()}, 120);
            if (probe.exitCode != 0) {
                return StepResult.fail("ffprobe 失败：" + tail(probe.stderr, 200));
            }
            Map<String, Object> info = Json.MAPPER.convertValue(
                    Json.MAPPER.readTree(probe.stdout.isEmpty() ? "{}" : probe.stdout),
                    new Json.MapType());
            Map<String, Object> format = info.get("format") instanceof Map
                    ? (Map<String, Object>) info.get("format") : new LinkedHashMap<String, Object>();
            Object dur = format.get("duration");
            duration = dur instanceof Number ? ((Number) dur).doubleValue()
                    : dur instanceof String && !((String) dur).isEmpty()
                    ? Double.parseDouble((String) dur) : 0.0;
        } catch (Exception e) {
            return StepResult.fail("ffprobe 解析失败：" + e.getMessage());
        }

        java.nio.file.Path outDir = ctx.settings.getParsedDir().resolve(ctx.docId);
        try {
            java.nio.file.Files.createDirectories(outDir);
        } catch (Exception e) {
            return StepResult.fail("创建解析目录失败：" + e.getMessage());
        }
        java.nio.file.Path wav = outDir.resolve("audio_16k_mono.wav");
        String ac = params.get("ac") == null ? "1" : String.valueOf(params.get("ac"));
        String ar = params.get("ar") == null ? "16000" : String.valueOf(params.get("ar"));
        try {
            AsrClient.ProcessResult r = AsrClient.runProcess(new String[]{
                    ffmpeg, "-y", "-v", "error", "-i", src.toAbsolutePath().toString(),
                    "-vn", "-ac", ac, "-ar", ar, wav.toAbsolutePath().toString()}, 3600);
            if (r.exitCode != 0) {
                return StepResult.fail("ffmpeg 抽音轨失败：" + tail(r.stderr, 200));
            }
        } catch (Exception e) {
            return StepResult.fail("ffmpeg 执行失败：" + e.getMessage());
        }
        try {
            if (!java.nio.file.Files.exists(wav) || java.nio.file.Files.size(wav) == 0) {
                return StepResult.fail("ffmpeg 未产出有效音轨");
            }
        } catch (Exception e) {
            return StepResult.fail("音轨校验失败：" + e.getMessage());
        }

        Map<String, String> assets = new LinkedHashMap<>();
        String keyframeFps = params.get("keyframe_fps") == null ? "1/60" : String.valueOf(params.get("keyframe_fps"));
        String name = src.getFileName().toString().toLowerCase(Locale.ROOT);
        if (name.endsWith(".mp4") || name.endsWith(".mkv") || name.endsWith(".mov") || name.endsWith(".avi")) {
            Path kfDir = outDir.resolve("keyframes");
            try {
                java.nio.file.Files.createDirectories(kfDir);
                AsrClient.ProcessResult r = AsrClient.runProcess(new String[]{
                        ffmpeg, "-y", "-v", "error", "-i", src.toAbsolutePath().toString(),
                        "-vf", "fps=" + keyframeFps, kfDir.resolve("kf_%04d.jpg").toAbsolutePath().toString()}, 3600);
                if (r.exitCode == 0) {
                    try (java.util.stream.Stream<Path> files = java.nio.file.Files.list(kfDir)) {
                        files.filter(p -> p.getFileName().toString().endsWith(".jpg")).sorted()
                                .forEach(p -> assets.put(stripExt(p), p.toString()));
                    }
                } // 抽帧失败不阻断主链路：assets 为空 = 关键帧通道显式缺失
            } catch (Exception ignored) {
                // 关键帧是增益不是依赖
            }
        }

        // keyframe_fps 随黑板下传：下游按 帧序号/fps 推每帧时间锚
        ctx.data.put("audio_wav", wav.toString());
        ctx.data.put("duration_sec", duration);
        ctx.data.put("assets", assets);
        ctx.data.put("keyframe_fps", keyframeFps);
        return StepResult.okMetrics("keyframes", assets.size(), "duration_sec",
                Math.round(duration * 10) / 10.0);
    }

    static String stripExt(Path p) {
        String name = p.getFileName().toString();
        int dot = name.lastIndexOf('.');
        return dot < 0 ? name : name.substring(0, dot);
    }

    static String tail(String s, int max) {
        if (s == null) {
            return "";
        }
        return s.length() <= max ? s : s.substring(s.length() - max);
    }
}
