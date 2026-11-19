package com.ownrag.api;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;

import org.springframework.core.io.FileSystemResource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

import com.ownrag.config.Settings;

import javax.servlet.http.HttpServletRequest;

/**
 * 媒体路由（Java 版新增，支撑 UI 的图片渲染与视频播放）：
 *
 *   GET /media/{docId}/**   解析产物静态资源（MinerU 的 images/、layout.json 等），相对路径引用的落点
 *   GET /source/{docId}     上传原件（音视频播放用）：返回 Resource，Spring MVC 自动处理
 *                           HTTP Range（RFC 7233），<video> 拖动进度条才能 seek
 *
 * 安全：rest 路径归一化后必须仍落在基目录内（防 .. 逃逸）；docId/path 只做只读服务。
 */
@RestController
public class MediaController {

    private static final Map<String, String> CONTENT_TYPES = new LinkedHashMap<>();

    static {
        CONTENT_TYPES.put("png", "image/png");
        CONTENT_TYPES.put("jpg", "image/jpeg");
        CONTENT_TYPES.put("jpeg", "image/jpeg");
        CONTENT_TYPES.put("webp", "image/webp");
        CONTENT_TYPES.put("gif", "image/gif");
        CONTENT_TYPES.put("bmp", "image/bmp");
        CONTENT_TYPES.put("svg", "image/svg+xml");
        CONTENT_TYPES.put("json", "application/json");
        CONTENT_TYPES.put("pdf", "application/pdf");
        CONTENT_TYPES.put("mp4", "video/mp4");
        CONTENT_TYPES.put("webm", "video/webm");
        CONTENT_TYPES.put("mkv", "video/x-matroska");
        CONTENT_TYPES.put("mov", "video/quicktime");
        CONTENT_TYPES.put("mp3", "audio/mpeg");
        CONTENT_TYPES.put("wav", "audio/wav");
        CONTENT_TYPES.put("m4a", "audio/mp4");
        CONTENT_TYPES.put("flac", "audio/flac");
        CONTENT_TYPES.put("md", "text/plain; charset=utf-8");
    }

    private final Settings settings;

    public MediaController(Settings settings) {
        this.settings = settings;
    }

    /** 解析产物：GET /media/{docId}/images/xxx.jpg —— MinerU markdown 里的相对引用。 */
    @GetMapping("/media/{docId}/**")
    public ResponseEntity<FileSystemResource> media(@PathVariable String docId,
                                                    HttpServletRequest request) throws Exception {
        Path base = settings.getParsedDir().resolve(docId).toAbsolutePath().normalize();
        String rest = restOf(request, "/media/" + docId + "/");
        if (rest == null || rest.isEmpty()) {
            throw new ApiError(404, "缺少资源路径");
        }
        Path target = safe(base, rest);
        if (target == null || !Files.isRegularFile(target)) {
            throw new ApiError(404, "产物资源不存在：" + rest);
        }
        return serve(target);
    }

    /** 上传原件：GET /source/{docId} —— <video>/<audio> 播放入口（Range 可 seek）。 */
    @GetMapping("/source/{docId}")
    public ResponseEntity<FileSystemResource> source(@PathVariable String docId) throws Exception {
        Path dir = settings.getFilesDir().resolve(docId).toAbsolutePath().normalize();
        if (!Files.isDirectory(dir)) {
            throw new ApiError(404, "doc 不存在：" + docId);
        }
        Path src = null;
        try (java.util.stream.Stream<Path> files = Files.list(dir)) {
            src = files.filter(Files::isRegularFile)
                    .filter(p -> p.getFileName().toString().startsWith("source"))
                    .findFirst().orElse(null);
        }
        if (src == null) {
            throw new ApiError(404, "原件不存在：" + docId);
        }
        return serve(src);
    }

    /** 统一出厂：Content-Type 按扩展名；Resource 返回值让 Spring MVC 自动支持 Range。 */
    private ResponseEntity<FileSystemResource> serve(Path target) {
        String name = target.getFileName().toString().toLowerCase(Locale.ROOT);
        int dot = name.lastIndexOf('.');
        String ext = dot < 0 ? "" : name.substring(dot + 1);
        MediaType type = MediaType.APPLICATION_OCTET_STREAM;
        String ct = CONTENT_TYPES.get(ext);
        if (ct != null) {
            type = MediaType.parseMediaType(ct);
        }
        return ResponseEntity.ok()
                .header(HttpHeaders.ACCEPT_RANGES, "bytes")
                .header(HttpHeaders.CACHE_CONTROL, "max-age=3600")
                .contentType(type)
                .body(new FileSystemResource(target));
    }

    /** rest 取出 + URL 解码 + 防逃逸：归一化后必须仍在 base 内；逃逸返回 null。 */
    public static Path safe(Path base, String rest) {
        try {
            String decoded = java.net.URLDecoder.decode(rest, "UTF-8");
            if (decoded.contains("..") || decoded.contains(":")) {
                return null;
            }
            Path target = base.resolve(decoded).normalize();
            if (!target.startsWith(base)) {
                return null;
            }
            return target;
        } catch (Exception e) {
            return null;
        }
    }

    /** 从 /media/{docId}/rest 提取 rest（含多级路径），未匹配返回 null。 */
    static String restOf(HttpServletRequest request, String prefix) {
        String uri = request.getRequestURI();
        int idx = uri.indexOf(prefix);
        if (idx < 0) {
            return null;
        }
        return uri.substring(idx + prefix.length());
    }
}
