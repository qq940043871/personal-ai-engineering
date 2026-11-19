package com.ownrag.index;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 结构感知切分（Python 版 index/chunker.py 的平移）：
 * 标题树优先、表格永不跨块、锚点保留、块头增强。
 * 索引侧决定天花板——切分参数变更必须过评测集回归，没有例外。
 */
public final class Chunker {

    private static final Pattern HEADING = Pattern.compile("^(#{1,6})\\s+(.*)$");
    private static final Pattern TABLE_LINE =
            Pattern.compile("^\\s*(\\|.*|<table\\b.*|</table>\\s*)$", Pattern.CASE_INSENSITIVE);
    private static final Pattern TIME_ANCHOR = Pattern.compile("\\[(\\d{1,2}:\\d{2})]");

    private Chunker() {
    }

    /** 段类型常量：heading | table | paragraph | code。 */
    public static final String KIND_HEADING = "heading";
    public static final String KIND_TABLE = "table";
    public static final String KIND_PARAGRAPH = "paragraph";
    public static final String KIND_CODE = "code";

    /**
     * 把 Markdown 拆成带语义类型的段：heading | table | paragraph | code。
     * 表格整段收集（永不跨块的前提）；标题记录层级供章节路径使用。
     * 段结构：{"kind","text","heading_path"}，全部 JSON 原生类型。
     */
    public static List<Map<String, Object>> splitSegments(String markdown) {
        List<Map<String, Object>> segments = new ArrayList<>();
        List<String> headingPath = new ArrayList<>();
        List<String> buf = new ArrayList<>();
        String[] kind = {KIND_PARAGRAPH};

        Runnable flush = () -> {
            String text = String.join("\n", buf).trim();
            if (!text.isEmpty()) {
                Map<String, Object> seg = new LinkedHashMap<>();
                seg.put("kind", kind[0]);
                seg.put("text", text);
                seg.put("heading_path", new ArrayList<>(headingPath));
                segments.add(seg);
            }
            buf.clear();
        };

        for (String line : markdown.split("\r?\n", -1)) {
            Matcher m = HEADING.matcher(line);
            if (m.matches()) {
                flush.run();
                int level = m.group(1).length();
                // heading_path[:level-1] + [标题]（就地变异，保持 lambda 捕获有效）
                List<String> kept = new ArrayList<>(headingPath.subList(0, Math.min(level - 1, headingPath.size())));
                headingPath.clear();
                headingPath.addAll(kept);
                headingPath.add(m.group(2).trim());
                kind[0] = KIND_HEADING;
                buf.add(line);
                flush.run();
                kind[0] = KIND_PARAGRAPH;
                continue;
            }
            if (TABLE_LINE.matcher(line).matches()) {
                if (!kind[0].equals(KIND_TABLE)) {
                    flush.run();
                    kind[0] = KIND_TABLE;
                }
                buf.add(line);
                continue;
            }
            if (kind[0].equals(KIND_TABLE)) {  // 表格结束
                flush.run();
                kind[0] = KIND_PARAGRAPH;
            }
            if (line.trim().startsWith("```")) {
                if (kind[0].equals(KIND_CODE)) {
                    buf.add(line);
                    flush.run();
                    kind[0] = KIND_PARAGRAPH;
                } else {
                    flush.run();
                    kind[0] = KIND_CODE;
                    buf.add(line);
                }
                continue;
            }
            buf.add(line);
        }
        flush.run();
        return segments;
    }

    /**
     * 段打包成块：≤max_tokens；块首注入"文档标题 > 章节路径"短头（裸块缺主语会召回漂移）。
     * 返回 Chunk Map 列表（chunk_id/doc_id/kb/source_type/ordinal/text/anchors/meta）。
     */
    public static List<Map<String, Object>> chunkMarkdown(String markdown, String docId, String kb,
                                                          String sourceType, Map<String, Object> baseMeta,
                                                          int maxTokens, int overlap) {
        List<Map<String, Object>> segments = splitSegments(markdown);
        List<Map<String, Object>> chunks = new ArrayList<>();
        List<Map<String, Object>> cur = new ArrayList<>();
        int[] curTokens = {0};
        int[] ordinal = {0};
        String docTitle = baseMeta.getOrDefault("source_file", docId) + "";

        // pack：把当前段组封成一块
        class Packer {
            void pack(List<Map<String, Object>> segs) {
                if (segs.isEmpty()) {
                    return;
                }
                ordinal[0] += 1;
                List<String> headingPath = new ArrayList<>();
                Object hp = segs.get(0).get("heading_path");
                if (hp instanceof List) {
                    for (Object o : (List<?>) hp) {
                        headingPath.add(String.valueOf(o));
                    }
                }
                StringBuilder headerJoin = new StringBuilder(docTitle);
                for (String h : headingPath) {
                    headerJoin.append(" > ").append(h);
                }
                String header = headerJoin.toString();
                StringBuilder body = new StringBuilder();
                for (Map<String, Object> s : segs) {
                    if (body.length() > 0) {
                        body.append("\n\n");
                    }
                    body.append(s.get("text"));
                }
                String text = header.isEmpty() ? body.toString() : "【" + header + "】\n\n" + body;
                Map<String, Object> anchors = new LinkedHashMap<>();
                for (String key : new String[]{"page", "t", "row_range"}) {
                    if (baseMeta.containsKey(key)) {
                        anchors.put(key, baseMeta.get(key));
                    }
                }
                anchors.put("heading_path", headingPath);
                if ("av".equals(sourceType)) {
                    // 时间锚结构化进 anchors（引用粒度=块，范围=块内首末 [mm:ss]）
                    Matcher tm = TIME_ANCHOR.matcher(body);
                    List<String> stamps = new ArrayList<>();
                    while (tm.find()) {
                        stamps.add(tm.group(1));
                    }
                    if (!stamps.isEmpty()) {
                        anchors.put("t", stamps.get(0) + "-" + stamps.get(stamps.size() - 1));
                    }
                }
                boolean hasTable = false;
                for (Map<String, Object> s : segs) {
                    if (KIND_TABLE.equals(s.get("kind"))) {
                        hasTable = true;
                        break;
                    }
                }
                Map<String, Object> meta = new LinkedHashMap<>(baseMeta);
                meta.put("has_table", hasTable);
                Map<String, Object> chunk = new LinkedHashMap<>();
                chunk.put("chunk_id", String.format("%s#%04d", docId, ordinal[0]));
                chunk.put("doc_id", docId);
                chunk.put("kb", kb);
                chunk.put("source_type", sourceType);
                chunk.put("ordinal", ordinal[0]);
                chunk.put("text", text);
                chunk.put("anchors", anchors);
                chunk.put("meta", meta);
                chunks.add(chunk);
            }
        }
        Packer packer = new Packer();

        for (Map<String, Object> seg : segments) {
            String segText = String.valueOf(seg.get("text"));
            int t = EstTokens.est(segText);
            // 表格/代码/超长段独立成块（表格不切；单段超限也保留——完整性优先于块径均匀）
            if (KIND_TABLE.equals(seg.get("kind")) || KIND_CODE.equals(seg.get("kind")) || t > maxTokens) {
                packer.pack(cur);
                cur = new ArrayList<>();
                curTokens[0] = 0;
                List<Map<String, Object>> single = new ArrayList<>();
                single.add(seg);
                packer.pack(single);
                continue;
            }
            if (curTokens[0] + t > maxTokens) {
                packer.pack(cur);
                // 简化重叠：重叠仅在段落型内容间生效，且不跨表格——重叠的是"整段"而非字符窗口
                List<Map<String, Object>> tail = new ArrayList<>();
                if (overlap > 0 && !cur.isEmpty()
                        && KIND_PARAGRAPH.equals(cur.get(cur.size() - 1).get("kind"))) {
                    tail.add(cur.get(cur.size() - 1));
                }
                cur = new ArrayList<>(tail);
                int tokens = 0;
                for (Map<String, Object> s : tail) {
                    tokens += EstTokens.est(String.valueOf(s.get("text")));
                }
                curTokens[0] = tokens;
            }
            cur.add(seg);
            curTokens[0] += t;
        }
        packer.pack(cur);
        return chunks;
    }
}
