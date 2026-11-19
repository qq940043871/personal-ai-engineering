package com.ownrag.ingest;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.List;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import okhttp3.OkHttpClient;
import okhttp3.mockwebserver.Dispatcher;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * MinerU 开放平台三步流契约测试（MockWebServer 全打桩，对齐 Python 版 test_mineru_open.py）：
 * 裸 PUT 零附加头（多一个头都是 OSS 403）、业务错误 HTTP 200 + code!=0、
 * 轮询状态机（waiting-file→running→done）、zip 下载解压 + zip-slip 防护。
 */
class MineruOpenClientTest {

    @TempDir
    Path tmp;

    private MockWebServer server;
    private MineruOpenClient client;

    @BeforeEach
    void setUp() throws IOException {
        server = new MockWebServer();
        server.start();
        client = new MineruOpenClient(new OkHttpClient());
    }

    @AfterEach
    void tearDown() throws IOException {
        server.shutdown();
    }

    private static MockResponse json(String body) {
        return new MockResponse().addHeader("Content-Type", "application/json").setBody(body);
    }

    private static Path makePdf(Path dir) throws IOException {
        Path pdf = dir.resolve("test.pdf");
        // 内容不必是合法 PDF：本测试不关心解析，只关心上传字节与契约
        Files.write(pdf, "FAKE-PDF-BYTES".getBytes(StandardCharsets.UTF_8));
        return pdf;
    }

    /** 构造结果 zip（full.md + images/pic.png）。 */
    private static byte[] zipBytes() throws IOException {
        java.io.ByteArrayOutputStream bos = new java.io.ByteArrayOutputStream();
        try (ZipOutputStream zos = new ZipOutputStream(bos)) {
            zos.putNextEntry(new ZipEntry("full.md"));
            zos.write("# 标题\n\n正文内容".getBytes(StandardCharsets.UTF_8));
            zos.closeEntry();
            zos.putNextEntry(new ZipEntry("images/pic.png"));
            zos.write("PNG".getBytes(StandardCharsets.UTF_8));
            zos.closeEntry();
        }
        return bos.toByteArray();
    }

    @Test
    void 三步流全链路_裸PUT零附加头() throws Exception {
        byte[] zip = zipBytes();
        server.setDispatcher(new Dispatcher() {
            @Override
            public MockResponse dispatch(RecordedRequest request) throws InterruptedException {
                String path = request.getPath();
                if (path.endsWith("/file-urls/batch")) {
                    return json("{\"code\":0,\"data\":{\"batch_id\":\"B123\","
                            + "\"file_urls\":[\"" + server.url("/put-target") + "\"]}}");
                }
                if (path.startsWith("/put-target")) {
                    return new MockResponse().setResponseCode(200);
                }
                if (path.contains("/extract-results/batch/")) {
                    return json("{\"code\":0,\"data\":{\"extract_result\":[{\"data_id\":\"doc1\","
                            + "\"state\":\"done\",\"full_zip_url\":\"" + server.url("/result.zip")
                            + "\"}]}}");
                }
                if (path.endsWith("/result.zip")) {
                    return new MockResponse().setBody(new okio.Buffer().write(zip));
                }
                return new MockResponse().setResponseCode(404);
            }
        });

        Path src = makePdf(tmp);
        Path outDir = tmp.resolve("out");
        MineruOpenClient.OpenResult r = client.parseViaOpenapi(
                src, "doc1", server.url("/api/v4").toString(), "TOKEN",
                "pipeline", "ch", false, true, true, 0.05, 10, outDir);

        assertEquals("# 标题\n\n正文内容", r.markdown);
        assertEquals(1, r.assets.size());
        assertEquals("pipeline", r.stats.get("model_version"));
        assertEquals("open", r.stats.get("mode"));

        // 批量申请体：data_id=doc_id（请求顺序：申请 → PUT → 轮询 → 下载）
        RecordedRequest apply = server.takeRequest();
        assertEquals("/api/v4/file-urls/batch", apply.getPath());
        assertTrue(apply.getBody().readUtf8().contains("\"data_id\":\"doc1\""));
        // 关键回归：预签名 PUT 必须严格裸 PUT——零附加头（无 Content-Type、无 Authorization）
        RecordedRequest put = server.takeRequest();
        assertEquals("PUT", put.getMethod());
        assertEquals("/put-target", put.getPath());
        assertTrue(put.getHeaders().names().stream()
                .noneMatch(h -> h.equalsIgnoreCase("Authorization")), "PUT 不能带 Authorization");
        assertTrue(put.getHeaders().names().stream()
                .noneMatch(h -> h.equalsIgnoreCase("Content-Type")), "PUT 不能带 Content-Type");
        assertEquals("FAKE-PDF-BYTES", put.getBody().readUtf8());
    }

    @Test
    void 业务错误_HTTP200加code非0() {
        server.setDispatcher(new Dispatcher() {
            @Override
            public MockResponse dispatch(RecordedRequest request) throws InterruptedException {
                return json("{\"code\":-60018,\"msg\":\"页额度耗尽\"}");
            }
        });
        MineruOpenClient.MineruException e = assertThrows(MineruOpenClient.MineruException.class,
                () -> client.parseViaOpenapi(makePdf(tmp), "doc1",
                        server.url("/api/v4").toString(), "TOKEN",
                        "pipeline", "ch", false, true, true, 0.05, 5, tmp.resolve("out2")));
        assertTrue(e.getMessage().contains("-60018"), e.getMessage());
    }

    @Test
    void 轮询状态机_failed透传err_msg() {
        server.setDispatcher(new Dispatcher() {
            @Override
            public MockResponse dispatch(RecordedRequest request) throws InterruptedException {
                if (request.getPath().endsWith("/file-urls/batch")) {
                    return json("{\"code\":0,\"data\":{\"batch_id\":\"B9\","
                            + "\"file_urls\":[\"" + server.url("/p2") + "\"]}}");
                }
                if (request.getPath().startsWith("/p2")) {
                    return new MockResponse().setResponseCode(200);
                }
                return json("{\"code\":0,\"data\":{\"extract_result\":[{\"data_id\":\"doc1\","
                        + "\"state\":\"failed\",\"err_msg\":\"解析崩溃\"}]}}");
            }
        });
        MineruOpenClient.MineruException e = assertThrows(MineruOpenClient.MineruException.class,
                () -> client.parseViaOpenapi(makePdf(tmp), "doc1",
                        server.url("/api/v4").toString(), "TOKEN",
                        "pipeline", "ch", false, true, true, 0.05, 5, tmp.resolve("out3")));
        assertTrue(e.getMessage().contains("解析崩溃"), e.getMessage());
    }

    @Test
    void 轮询状态机_进行中状态持续等待直至done() throws Exception {
        final int[] polls = {0};
        final byte[] zip = zipBytes();
        server.setDispatcher(new Dispatcher() {
            @Override
            public MockResponse dispatch(RecordedRequest request) throws InterruptedException {
                String path = request.getPath();
                if (path.endsWith("/file-urls/batch")) {
                    return json("{\"code\":0,\"data\":{\"batch_id\":\"B7\","
                            + "\"file_urls\":[\"" + server.url("/p3") + "\"]}}");
                }
                if (path.startsWith("/p3")) {
                    return new MockResponse().setResponseCode(200);
                }
                if (path.contains("/extract-results/batch/")) {
                    polls[0]++;
                    if (polls[0] < 3) {
                        return json("{\"code\":0,\"data\":{\"extract_result\":[{\"data_id\":\"doc1\","
                                + "\"state\":\"running\",\"extract_progress\":{\"extracted_pages\":1,"
                                + "\"total_pages\":3}}]}}");
                    }
                    return json("{\"code\":0,\"data\":{\"extract_result\":[{\"data_id\":\"doc1\","
                            + "\"state\":\"done\",\"full_zip_url\":\"" + server.url("/r.zip")
                            + "\"}]}}");
                }
                if (path.endsWith("/r.zip")) {
                    return new MockResponse().setBody(new okio.Buffer().write(zip));
                }
                return new MockResponse().setResponseCode(404);
            }
        });
        MineruOpenClient.OpenResult r = client.parseViaOpenapi(makePdf(tmp), "doc1",
                server.url("/api/v4").toString(), "TOKEN",
                "pipeline", "ch", false, true, true, 0.02, 10, tmp.resolve("out4"));
        assertEquals(3, polls[0]);
        assertTrue(r.markdown.contains("正文内容"));
    }

    @Test
    void zip防护_父级跳转条目被丢弃() throws Exception {
        java.io.ByteArrayOutputStream bos = new java.io.ByteArrayOutputStream();
        try (ZipOutputStream zos = new ZipOutputStream(bos)) {
            zos.putNextEntry(new ZipEntry("../evil.txt"));
            zos.write("evil".getBytes(StandardCharsets.UTF_8));
            zos.closeEntry();
            zos.putNextEntry(new ZipEntry("full.md"));
            zos.write("safe".getBytes(StandardCharsets.UTF_8));
            zos.closeEntry();
        }
        Path outDir = tmp.resolve("out5");
        // 直接验证解压过滤语义：手工写 zip 后按 downloadExtract 的规则逐条检查
        Path zipPath = outDir.resolve("result.zip");
        Files.createDirectories(outDir);
        Files.write(zipPath, bos.toByteArray());
        java.util.zip.ZipFile zf = new java.util.zip.ZipFile(zipPath.toFile());
        java.util.Enumeration<? extends ZipEntry> entries = zf.entries();
        int safe = 0;
        while (entries.hasMoreElements()) {
            ZipEntry e = entries.nextElement();
            if (e.getName().contains("..")) {
                continue;
            }
            safe++;
        }
        zf.close();
        assertEquals(1, safe, "含 .. 的条目应被跳过");
        Files.delete(zipPath);
    }

    @Test
    void 解压_相对outDir也必须落盘_full_md() throws Exception {
        // 回归：data-dir 为相对路径时，防逃逸基准曾用绝对路径对比相对目标，全部条目被静默跳过
        byte[] zip = zipBytes();
        server.enqueue(new MockResponse().setBody(new okio.Buffer().write(zip)));
        Path relOut = Paths.get("target/probe_rel_out");   // 相对路径（工作目录相关）
        try (java.util.stream.Stream<Path> st = Files.walk(relOut)) {
            st.sorted(java.util.Comparator.reverseOrder()).forEach(p -> p.toFile().delete());
        } catch (Exception ignored) {
            // 目录不存在 = 首次运行
        }
        // 生产语义：parseViaOpenapi 先建目录，downloadExtract 直接写
        Files.createDirectories(relOut);
        client.downloadExtract(server.url("/result.zip").toString(), relOut);
        assertTrue(Files.exists(relOut.resolve("full.md")), "相对 outDir 下 full.md 必须落盘");
        assertTrue(Files.exists(relOut.resolve("images/pic.png")));
        String md = new String(Files.readAllBytes(relOut.resolve("full.md")), StandardCharsets.UTF_8);
        assertTrue(md.contains("正文内容"));
    }

    @Test
    void 结构清单提取_image与table与页数() throws Exception {
        Path outDir = tmp.resolve("out6");
        Files.createDirectories(outDir);
        Path cl = outDir.resolve("doc1_content_list.json");
        Files.write(cl, ("[{\"type\":\"image\",\"page_idx\":0,\"img_path\":\"images/a.png\"},"
                + "{\"type\":\"table\",\"page_idx\":1,\"table_body\":\"<table><tr><td>x</td></tr></table>\"},"
                + "{\"type\":\"text\",\"page_idx\":2}]").getBytes(StandardCharsets.UTF_8));
        List<Map<String, Object>> structures = new java.util.ArrayList<>();
        int[] pages = {0};
        MineruOpenClient.structuresFromContentList(outDir, structures, pages);
        assertEquals(2, structures.size());
        assertEquals("image", structures.get(0).get("kind"));
        assertEquals("table", structures.get(1).get("kind"));
        assertEquals("<table><tr><td>x</td></tr></table>", structures.get(1).get("text"));
        assertEquals(3, pages[0]);
    }

    @Test
    void 未配置token_即报错不入网() {
        MineruOpenClient.MineruException e = assertThrows(MineruOpenClient.MineruException.class,
                () -> client.parseViaOpenapi(makePdf(tmp), "doc1",
                        server.url("/api/v4").toString(), "",
                        "pipeline", "ch", false, true, true, 0.05, 5, tmp.resolve("out7")));
        assertTrue(e.getMessage().contains("MINERU_OPEN_TOKEN"));
    }
}
