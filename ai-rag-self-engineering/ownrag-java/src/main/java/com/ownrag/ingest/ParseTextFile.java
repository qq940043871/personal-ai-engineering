package com.ownrag.ingest;

import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.Charset;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.LinkedHashMap;
import java.util.Map;

import org.springframework.stereotype.Component;

import com.ownrag.core.Step;
import com.ownrag.core.StepContext;
import com.ownrag.core.StepResult;

/**
 * 纯文本直传（Python 版无此链路，Java 版为个人知识库场景新增）：
 * .md = 原生 Markdown 直通（标题树/表格/代码围栏由 Chunker 结构感知承接，零结构损失）；
 * .txt = 纯文本透传（no_headings 警告属预期，复核时可见）。
 * 编码 UTF-8 严格解码失败 → GBK 兜底（中文 txt 现实），降级显式写 metadata。
 */
@Component
public class ParseTextFile implements Step {

    @Override
    public String type() {
        return "parse_textfile";
    }

    @Override
    public StepResult run(StepContext ctx, Map<String, Object> params) {
        Path src = Paths.get(String.valueOf(ctx.data.get("source_path")));
        // 格式判定：params.format 显式优先，否则按扩展名（.md/.markdown→md，其余→txt）
        String fmt = params.get("format") == null || String.valueOf(params.get("format")).isEmpty()
                ? autoFormat(src) : String.valueOf(params.get("format"));

        byte[] bytes;
        try {
            bytes = Files.readAllBytes(src);
        } catch (Exception e) {
            return StepResult.fail("读取失败：" + e.getMessage());
        }
        String text;
        String encoding = "utf-8";
        try {
            text = strictDecode(bytes, StandardCharsets.UTF_8);
        } catch (CharacterCodingException e) {
            try {
                text = strictDecode(bytes, Charset.forName("GBK"));
                encoding = "gbk";
            } catch (CharacterCodingException e2) {
                return StepResult.fail("编码不可判定（UTF-8/GBK 均含非法字节）：" + src.getFileName());
            }
        }
        if (!text.isEmpty() && text.charAt(0) == '﻿') {  // 去 UTF-8 BOM
            text = text.substring(1);
        }

        // front-matter（--- key: value ---）剥离并提取：个人维度过滤字段的批量化载体——
        // 语料工厂把 kb/topic/date/sensitivity/origin 写进文件头，入库即成列，检索期可过滤
        Map<String, Object> frontMatter = extractFrontMatter(text);
        if (!frontMatter.isEmpty()) {
            text = stripFrontMatter(text);
        }

        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put("source_file", src.getFileName().toString());
        metadata.put("size_bytes", bytes.length);
        metadata.put("format", "native_" + fmt);
        if ("gbk".equals(encoding)) {
            metadata.put("degraded", "编码为 GBK 兜底解码，建议转存 UTF-8 后重传");
        }
        Object sourceMeta = ctx.data.get("source_meta");
        if (sourceMeta instanceof Map) {
            @SuppressWarnings("unchecked")
            Map<String, Object> sm = (Map<String, Object>) sourceMeta;
            metadata.putAll(sm);
        }
        // front-matter 最后合入：文档自带口径优先于上传参数（批导入场景 front-matter 是唯一事实源）
        metadata.putAll(frontMatter);
        // date → doc_date 规范化；size_bytes 以实读为准
        if (metadata.containsKey("date") && !metadata.containsKey("doc_date")) {
            metadata.put("doc_date", metadata.get("date"));
        }
        metadata.put("size_bytes", bytes.length);

        Map<String, Object> stats = new LinkedHashMap<>();
        stats.put("chars", text.length());
        stats.put("encoding", encoding);
        stats.put("backend", "textfile-native");

        ParsedDoc doc = new ParsedDoc(ctx.docId, fmt, text, metadata,
                new java.util.ArrayList<>(), new LinkedHashMap<>(), stats);
        String[] usable = doc.isUsable(20);
        if (usable[0] == null) {
            return StepResult.fail("产出不可用：" + usable[1]);
        }
        ctx.data.put("parsed", doc.toMap());
        return StepResult.okMetrics("chars", text.length(), "encoding", encoding);
    }

    private static String autoFormat(Path src) {
        String name = src.getFileName().toString().toLowerCase();
        return name.endsWith(".md") || name.endsWith(".markdown") ? "md" : "txt";
    }

    /** front-matter 开头（---\n...\n---\n），仅解析 "key: value" 简单 KV（个人语料够用，不引 YAML 库）。 */
    static Map<String, Object> extractFrontMatter(String text) {
        Map<String, Object> out = new LinkedHashMap<>();
        if (!text.startsWith("---")) {
            return out;
        }
        int end = text.indexOf("\n---", 3);
        if (end < 0) {
            return out;
        }
        String block = text.substring(3, end);
        for (String line : block.split("\r?\n")) {
            int colon = line.indexOf(':');
            if (colon <= 0) {
                continue;
            }
            String key = line.substring(0, colon).trim();
            String val = line.substring(colon + 1).trim();
            if (!key.isEmpty() && !val.isEmpty()) {
                out.put(key, val);
            }
        }
        return out;
    }

    /** 剥离 front-matter 块（含收尾分隔行），正文从分隔行之后开始。 */
    static String stripFrontMatter(String text) {
        int end = text.indexOf("\n---", 3);
        if (end < 0) {
            return text;
        }
        int bodyStart = text.indexOf('\n', end + 1);
        return bodyStart < 0 ? "" : text.substring(bodyStart + 1);
    }

    /** 严格解码：非法字节直接抛 CharacterCodingException，不用替换符静默吞掉。 */
    private static String strictDecode(byte[] bytes, Charset cs) throws CharacterCodingException {
        return cs.newDecoder()
                .onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT)
                .decode(ByteBuffer.wrap(bytes)).toString();
    }
}
