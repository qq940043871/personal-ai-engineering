package com.ownrag.ingest;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 统一中间态契约 ParsedDoc（Python 版 ingest/base.py 的平移）：三条解析链路的汇合点。
 * 换解析器不动向量库的前提：所有链路收敛到同一契约；
 * 锚点即引用——页码 / mm:ss / 行区间在解析层决定，生成层只透传。
 */
public class ParsedDoc {

    public String docId;
    public String sourceType;                       // pdf | av | excel
    public String markdown;
    public Map<String, Object> metadata = new LinkedHashMap<>();   // 公共元数据
    public List<Map<String, Object>> structures = new ArrayList<>(); // Structure.toMap() 列表
    public Map<String, String> assets = new LinkedHashMap<>();     // key -> 文件路径
    public Map<String, Object> stats = new LinkedHashMap<>();      // 页数/时长/行列数/耗时

    public ParsedDoc() {
    }

    public ParsedDoc(String docId, String sourceType, String markdown,
                     Map<String, Object> metadata, List<Map<String, Object>> structures,
                     Map<String, String> assets, Map<String, Object> stats) {
        this.docId = docId;
        this.sourceType = sourceType;
        this.markdown = markdown;
        if (metadata != null) {
            this.metadata.putAll(metadata);
        }
        if (structures != null) {
            this.structures.addAll(structures);
        }
        if (assets != null) {
            this.assets.putAll(assets);
        }
        if (stats != null) {
            this.stats.putAll(stats);
        }
    }

    /** 黑板里只存 JSON 原生类型：toMap 供 ctx.data 使用。 */
    public Map<String, Object> toMap() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("doc_id", docId);
        m.put("source_type", sourceType);
        m.put("markdown", markdown);
        m.put("metadata", metadata);
        m.put("structures", structures);
        m.put("assets", assets);
        m.put("stats", stats);
        return m;
    }

    public static ParsedDoc fromMap(Map<String, Object> map) {
        ParsedDoc doc = new ParsedDoc();
        doc.docId = str(map.get("doc_id"));
        doc.sourceType = str(map.get("source_type"));
        doc.markdown = str(map.get("markdown"));
        Map<String, Object> meta = asMap(map.get("metadata"));
        if (meta != null) {
            doc.metadata.putAll(meta);
        }
        Object structs = map.get("structures");
        if (structs instanceof List) {
            for (Object o : (List<?>) structs) {
                Map<String, Object> s = asMap(o);
                if (s != null) {
                    doc.structures.add(s);
                }
            }
        }
        Map<String, Object> assetsMap = asMap(map.get("assets"));
        if (assetsMap != null) {
            for (Map.Entry<String, Object> e : assetsMap.entrySet()) {
                doc.assets.put(e.getKey(), e.getValue() == null ? null : String.valueOf(e.getValue()));
            }
        }
        Map<String, Object> statsMap = asMap(map.get("stats"));
        if (statsMap != null) {
            doc.stats.putAll(statsMap);
        }
        return doc;
    }

    /**
     * 与 validate_parsed 步骤共用同一口径：产出可用 = 正文非空且达到最低信息量。
     * 返回 [ok, why]；ok=true 时 why 为空串。
     */
    public String[] isUsable(int minCharsTotal) {
        if (markdown == null || markdown.trim().isEmpty()) {
            return new String[]{null, "空 Markdown"};
        }
        String trimmed = markdown.trim();
        if (trimmed.length() < minCharsTotal) {
            return new String[]{null, "正文过短（" + trimmed.length() + " 字符 < " + minCharsTotal + "）"};
        }
        return new String[]{"", ""};
    }

    // ---- Structure 工厂：kind/location/pointer/text 四字段（与 Python 版 Structure dataclass 对齐）----

    public static Map<String, Object> structure(String kind, String location, String pointer, String text) {
        Map<String, Object> s = new LinkedHashMap<>();
        s.put("kind", kind);
        s.put("location", location);
        s.put("pointer", pointer);
        s.put("text", text);
        return s;
    }

    private static String str(Object o) {
        return o == null ? null : String.valueOf(o);
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMap(Object o) {
        return o instanceof Map ? (Map<String, Object>) o : null;
    }
}
