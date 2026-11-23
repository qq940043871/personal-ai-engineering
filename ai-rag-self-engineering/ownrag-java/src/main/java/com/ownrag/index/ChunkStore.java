package com.ownrag.index;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.ownrag.util.Json;

/**
 * 双通道存储（Python 版 index/store.py 的平移）：
 * 向量 = chunk_vectors 表（BLOB float[]）+ 查询时暴力余弦（替代 chromadb）；
 * 关键词 = SQLite FTS5，CJK 逐字切 token。按 doc_id 原子替换。
 *
 * 降级语义：向量通道不可用时显式跳过并记 metric（vector=skipped），
 * 检索退 BM25 单路——**降级可见，不是静默**。embed_version 记录在 chunks 行上。
 */
public final class ChunkStore {

    private ChunkStore() {
    }

    // ------------------------------------------------ 关键词通道（FTS5）

    /**
     * FTS5 unicode61 不切 CJK（整段中文=一个 token，中文查询必零召回）。
     * 字符化兜底：CJK 逐字成 token、拉丁数字按词、其余当分隔——索引与查询两侧必须同函数。
     * jieba 预分词为后续增强。
     */
    public static String ftsCjk(String text) {
        StringBuilder out = new StringBuilder();
        StringBuilder buf = new StringBuilder();
        for (int i = 0; i < text.length(); i++) {
            char ch = text.charAt(i);
            if (ch >= '\u4e00' && ch <= '\u9fff') {
                if (buf.length() > 0) {
                    out.append(buf).append(' ');
                    buf.setLength(0);
                }
                out.append(ch).append(' ');
            } else if (Character.isLetterOrDigit(ch) && ch < 128) {
                buf.append(ch);
            } else {
                if (buf.length() > 0) {
                    out.append(buf).append(' ');
                    buf.setLength(0);
                }
            }
        }
        if (buf.length() > 0) {
            out.append(buf);
        }
        return out.toString().trim();
    }

    public static void keywordUpsert(Connection conn, List<Map<String, Object>> chunks) throws SQLException {
        try (PreparedStatement del = conn.prepareStatement("DELETE FROM chunks_fts WHERE chunk_id=?");
             PreparedStatement ins = conn.prepareStatement(
                     "INSERT INTO chunks_fts(text, chunk_id, doc_id, kb) VALUES (?,?,?,?)")) {
            for (Map<String, Object> c : chunks) {
                String chunkId = String.valueOf(c.get("chunk_id"));
                del.setString(1, chunkId);
                del.executeUpdate();
                ins.setString(1, ftsCjk(String.valueOf(c.get("text"))));
                ins.setString(2, chunkId);
                ins.setString(3, String.valueOf(c.get("doc_id")));
                ins.setString(4, String.valueOf(c.get("kb")));
                ins.executeUpdate();
            }
        }
    }

    public static void keywordDeleteDoc(Connection conn, String docId) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement("DELETE FROM chunks_fts WHERE doc_id=?")) {
            ps.setString(1, docId);
            ps.executeUpdate();
        }
    }

    /**
     * MATCH 语法与召回兜底阶梯：原文短语 → 字符化短语 → 字符化 OR（CJK 主路径）。
     * OR 命中按 bm25 排名，重叠字符越多越靠前。
     * 过滤在召回前（JOIN chunks 做个人维度过滤），kb 支持多库 IN——先过滤后召回，过滤责任不进 Prompt。
     */
    public static List<Map<String, Object>> keywordSearch(Connection conn, String kb, String query, int topK)
            throws SQLException {
        return keywordSearch(conn, kb == null ? null : java.util.Collections.singletonList(kb), query, topK, null);
    }

    /** 单库 + 过滤便捷重载。 */
    public static List<Map<String, Object>> keywordSearch(Connection conn, String kb, String query,
                                                          int topK, Map<String, Object> filter) throws SQLException {
        return keywordSearch(conn, kb == null ? null : java.util.Collections.singletonList(kb), query, topK, filter);
    }

    public static List<Map<String, Object>> keywordSearch(Connection conn, List<String> kbs, String query,
                                                          int topK, Map<String, Object> filter)
            throws SQLException {
        String cjk = ftsCjk(query);
        List<String> ladder = new ArrayList<>();
        ladder.add("\"" + query.replace("\"", "\"\"") + "\"");
        if (!cjk.isEmpty() && !cjk.equals(query)) {
            ladder.add("\"" + cjk.replace("\"", "\"\"") + "\"");
            StringBuilder or = new StringBuilder();
            for (String token : cjk.split(" ")) {
                if (or.length() > 0) {
                    or.append(" OR ");
                }
                // 每个 token 必须加引号：问题里出现 NOT / AND / OR / NEAR 时，
                // 裸词会被 FTS5 当运算符解析，整条 BM25 直接语法报错→零召回。
                // 引号内是字面短语，语义不变、只消除运算符歧义（评测集里 "NOT IN 子查询" 就是踩的这个坑）。
                or.append('"').append(token.replace("\"", "\"\"")).append('"');
            }
            ladder.add(or.toString());
        }
        String sql = "SELECT chunks_fts.chunk_id, chunks_fts.doc_id, bm25(chunks_fts) AS score "
                + "FROM chunks_fts LEFT JOIN chunks ON chunks.chunk_id = chunks_fts.chunk_id "
                + "WHERE chunks_fts MATCH ? " + kbInSql(kbs, "chunks_fts.kb")
                + enabledSql("chunks.doc_id") + filterSql(filter, "chunks.")
                + " ORDER BY score LIMIT ?";
        for (String q : ladder) {
            try (PreparedStatement ps = conn.prepareStatement(sql)) {
                int i = 1;
                ps.setString(i++, q);
                if (kbs != null) {
                    for (String kb : kbs) {
                        ps.setString(i++, kb);
                    }
                }
                i = bindFilter(ps, i, filter);
                ps.setInt(i, topK);
                try (ResultSet rs = ps.executeQuery()) {
                    List<Map<String, Object>> rows = new ArrayList<>();
                    while (rs.next()) {
                        Map<String, Object> row = new LinkedHashMap<>();
                        row.put("chunk_id", rs.getString("chunk_id"));
                        row.put("doc_id", rs.getString("doc_id"));
                        row.put("score", -rs.getDouble("score"));
                        row.put("channel", "bm25");
                        rows.add(row);
                    }
                    if (!rows.isEmpty()) {
                        return rows;
                    }
                }
            } catch (SQLException ignored) {
                // MATCH 语法阶梯逐级降级（原文含特殊字符时短语可能非法）
            }
        }
        return new ArrayList<>();
    }

    // ------------------------------------------------ 向量通道（SQLite BLOB + 暴力余弦）

    public static float[] toFloatArray(List<Double> vec) {
        float[] out = new float[vec.size()];
        for (int i = 0; i < out.length; i++) {
            out[i] = vec.get(i).floatValue();
        }
        return out;
    }

    /** float[] → 小端 BLOB（读取端同序）。 */
    public static byte[] toBlob(float[] vec) {
        ByteBuffer buf = ByteBuffer.allocate(vec.length * 4).order(ByteOrder.LITTLE_ENDIAN);
        for (float v : vec) {
            buf.putFloat(v);
        }
        return buf.array();
    }

    public static float[] fromBlob(byte[] blob) {
        ByteBuffer buf = ByteBuffer.wrap(blob).order(ByteOrder.LITTLE_ENDIAN);
        float[] out = new float[blob.length / 4];
        for (int i = 0; i < out.length; i++) {
            out[i] = buf.getFloat();
        }
        return out;
    }

    public static boolean vectorUpsert(Connection conn, String kb, List<Map<String, Object>> chunks,
                                       List<List<Double>> embeddings) throws SQLException {
        if (chunks.size() != embeddings.size()) {
            throw new SQLException("向量数与块数不符：" + embeddings.size() + " vs " + chunks.size());
        }
        try (PreparedStatement ps = conn.prepareStatement(
                "INSERT OR REPLACE INTO chunk_vectors(chunk_id, doc_id, kb, embedding, dim) VALUES (?,?,?,?,?)")) {
            for (int i = 0; i < chunks.size(); i++) {
                Map<String, Object> c = chunks.get(i);
                float[] vec = toFloatArray(embeddings.get(i));
                ps.setString(1, String.valueOf(c.get("chunk_id")));
                ps.setString(2, String.valueOf(c.get("doc_id")));
                ps.setString(3, kb);
                ps.setBytes(4, toBlob(vec));
                ps.setInt(5, vec.length);
                ps.executeUpdate();
            }
        }
        return true;
    }

    public static void vectorDeleteDoc(Connection conn, String docId) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement("DELETE FROM chunk_vectors WHERE doc_id=?")) {
            ps.setString(1, docId);
            ps.executeUpdate();
        }
    }

    /**
     * 向量检索：kb 内全量载入 → 暴力余弦 → topK。
     * 万级块 × 1024 维在 Java 下毫秒级，且精确召回优于近似索引（个人规模的最优解）。
     * 返回 score = 余弦相似度（[-1,1]，与 Python 版 1-distance 的语义等价）。
     * 过滤在召回前：JOIN chunks 按个人维度列过滤，避免"召回后被 Prompt 过滤"的口径外泄。
     */
    public static List<Map<String, Object>> vectorSearch(Connection conn, String kb,
                                                         float[] queryVec, int topK) throws SQLException {
        return vectorSearch(conn, java.util.Collections.singletonList(kb), queryVec, topK, null);
    }

    /** 单库 + 过滤便捷重载。 */
    public static List<Map<String, Object>> vectorSearch(Connection conn, String kb, float[] queryVec,
                                                         int topK, Map<String, Object> filter) throws SQLException {
        return vectorSearch(conn, java.util.Collections.singletonList(kb), queryVec, topK, filter);
    }

    public static List<Map<String, Object>> vectorSearch(Connection conn, List<String> kbs,
                                                         float[] queryVec, int topK,
                                                         Map<String, Object> filter) throws SQLException {
        return vectorSearch(conn, kbs, queryVec, topK, filter, null);
    }

    /**
     * 带 embed_version 校验的向量召回（检索主路径必须走这个重载）。
     *
     * 为什么必须校验：换 embed 模型时新旧向量落在**同一个 chunk_vectors 表**，bge-m3 与
     * bge-large-zh-v1.5 都是 1024 维——维度相同意味着不会报错，余弦照算，但两套向量空间
     * 混算出来的分数毫无意义（静默脏召回）。这里按 embed_version 硬隔离：
     * 版本不符的旧向量不参与召回，重建完成前该通道退化为空并在检索侧播报（降级可见）。
     * embedVersion 为空 = 不校验（仅供单测/调试直接构造向量时使用）。
     */
    public static List<Map<String, Object>> vectorSearch(Connection conn, List<String> kbs,
                                                         float[] queryVec, int topK,
                                                         Map<String, Object> filter,
                                                         String embedVersion) throws SQLException {
        double qNorm = norm(queryVec);
        boolean versioned = embedVersion != null && !embedVersion.trim().isEmpty();
        // 大顶堆思路直接简化为：全量算分 → 排序取前 topK（个人规模下可接受）
        List<Map<String, Object>> all = new ArrayList<>();
        String sql = "SELECT chunk_vectors.chunk_id, chunk_vectors.doc_id, chunk_vectors.embedding "
                + "FROM chunk_vectors LEFT JOIN chunks ON chunks.chunk_id = chunk_vectors.chunk_id "
                + "WHERE 1=1 " + kbInSql(kbs, "chunk_vectors.kb")
                + enabledSql("chunk_vectors.doc_id") + filterSql(filter, "chunks.")
                + (versioned ? "AND chunks.embed_version = ? " : "");
        try (PreparedStatement ps = conn.prepareStatement(sql)) {
            int i = 1;
            if (kbs != null) {
                for (String kb : kbs) {
                    ps.setString(i++, kb);
                }
            }
            i = bindFilter(ps, i, filter);
            if (versioned) {
                ps.setString(i++, embedVersion.trim());
            }
            try (ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    float[] vec = fromBlob(rs.getBytes("embedding"));
                    double dot = 0;
                    int n = Math.min(vec.length, queryVec.length);
                    for (int j = 0; j < n; j++) {
                        dot += vec[j] * queryVec[j];
                    }
                    double score = qNorm == 0 || norm(vec) == 0 ? 0 : dot / (qNorm * norm(vec));
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("chunk_id", rs.getString("chunk_id"));
                    row.put("doc_id", rs.getString("doc_id"));
                    row.put("score", score);
                    row.put("channel", "vector");
                    all.add(row);
                }
            }
        }
        all.sort((a, b) -> Double.compare((Double) b.get("score"), (Double) a.get("score")));
        return all.size() > topK ? new ArrayList<>(all.subList(0, topK)) : all;
    }

    private static double norm(float[] vec) {
        double s = 0;
        for (float v : vec) {
            s += v * v;
        }
        return Math.sqrt(s);
    }

    // ------------------------------------------------ 块表

    /** 按 id 批量取块正文与锚点（检索结果回填用）。
     *  doc_name 一并带出：引用位置只给块号，等于让用户自己去猜"这段出自哪篇文档"。 */
    public static Map<String, Map<String, Object>> readChunks(Connection conn, List<String> chunkIds)
            throws SQLException {
        Map<String, Map<String, Object>> out = new LinkedHashMap<>();
        // documents 是文档实体的权威来源；缺行/空值时回退块 meta_json 的 source_file，最后才退回 doc_id
        try (PreparedStatement ps = conn.prepareStatement(
                "SELECT c.*, COALESCE(NULLIF(d.source_file, ''), '') AS doc_name "
                        + "FROM chunks c LEFT JOIN documents d ON d.doc_id = c.doc_id "
                        + "WHERE c.chunk_id=?")) {
            for (String cid : chunkIds) {
                ps.setString(1, cid);
                try (ResultSet rs = ps.executeQuery()) {
                    if (rs.next()) {
                        Map<String, Object> row = new LinkedHashMap<>();
                        Map<String, Object> meta = parseJsonOrEmpty(rs.getString("meta_json"));
                        row.put("chunk_id", rs.getString("chunk_id"));
                        row.put("doc_id", rs.getString("doc_id"));
                        String docName = rs.getString("doc_name");
                        if (docName == null || docName.isEmpty()) {
                            Object fromMeta = meta.get("source_file");
                            docName = fromMeta == null ? rs.getString("doc_id") : String.valueOf(fromMeta);
                        }
                        row.put("doc_name", docName);
                        row.put("kb", rs.getString("kb"));
                        row.put("ordinal", rs.getInt("ordinal"));
                        row.put("text", rs.getString("text"));
                        row.put("anchors", parseJsonOrEmpty(rs.getString("anchors_json")));
                        row.put("meta", meta);
                        out.put(cid, row);
                    }
                }
            }
        }
        return out;
    }

    /** 列出 kb 内全部 chunk_id（向量检索回填与全量重建用）。 */
    public static List<String> listChunkIdsByKb(Connection conn, String kb) throws SQLException {
        List<String> out = new ArrayList<>();
        try (PreparedStatement ps = conn.prepareStatement("SELECT chunk_id FROM chunks WHERE kb=?")) {
            ps.setString(1, kb);
            try (ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    out.add(rs.getString(1));
                }
            }
        }
        return out;
    }

    private static Map<String, Object> parseJsonOrEmpty(String json) {
        if (json == null || json.isEmpty()) {
            return new LinkedHashMap<>();
        }
        try {
            return Json.readMap(json);
        } catch (Exception e) {
            return new LinkedHashMap<>();
        }
    }

    /** 统计工具（admin/metrics 用）。 */
    public static long countByKb(Connection conn, String kb) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement("SELECT COUNT(*) FROM chunks WHERE kb=?")) {
            ps.setString(1, kb);
            try (ResultSet rs = ps.executeQuery()) {
                return rs.next() ? rs.getLong(1) : 0;
            }
        }
    }

    // ------------------------------------------------ 个人维度过滤（先过滤后召回）

    private static String placeholders(int n) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < n; i++) {
            sb.append(i == 0 ? "?" : ",?");
        }
        return sb.toString();
    }

    /** kb IN 条件：kbs 为空 → 不限制（全库）。每条件自带前导 AND。 */
    private static String kbInSql(List<String> kbs, String column) {
        if (kbs == null || kbs.isEmpty()) {
            return "";
        }
        return "AND " + column + " IN (" + placeholders(kbs.size()) + ") ";
    }

    /**
     * 文档启停过滤（每条件自带前导 AND）：enabled=0 的文档退出检索但保留块与向量——
     * 与删除（六通道全清、不可逆）相对的"临时下架"。correlated 子查询按 doc_id 查
     * documents.enabled，缺行/缺列（老库未迁移）按 1 处理，存量行为不变。
     */
    private static String enabledSql(String docIdColumn) {
        return "AND COALESCE((SELECT d.enabled FROM documents d WHERE d.doc_id = "
                + docIdColumn + "), 1) = 1 ";
    }

    /**
     * 访问权限过滤（每条件自带前导 AND）：只留 access_level='public' 的文档。
     *
     * 事实源是 documents 一行（按主键点查，万级块上即为索引查找）；缺行（老库/未建档）按 public，
     * 与"存量文档不因改版突然消失"的口径一致。公开方法供 InspectController 的列表查询复用——
     * 同一句 SQL 片段只写一次，避免"某条列表接口忘了过滤"。
     */
    public static String publicOnlySql(String docIdColumn) {
        return "AND COALESCE((SELECT d.access_level FROM documents d WHERE d.doc_id = "
                + docIdColumn + "), 'public') = 'public' ";
    }

    /**
     * 个人维度过滤 SQL（每条件自带前导 AND；无过滤返回空串）：
     * sensitivity=允许档位列表（缺省行按 internal 处理）、topic=精确、date_from/date_to=ISO 字符串比较。
     *
     * 另外承载**访问权限过滤**（`public_only=true`，未登录时由 AuthService 打上）：
     * 它查 documents.access_level（缺行按 public），与 sensitivity 刻意分开——
     * sensitivity 是调用方可选的内容分级，public_only 是服务端强制的权限，用户清空过滤条件也绕不过。
     */
    static String filterSql(Map<String, Object> filter, String colPrefix) {
        if (filter == null || filter.isEmpty()) {
            return "";
        }
        StringBuilder sb = new StringBuilder();
        if (Boolean.TRUE.equals(filter.get("public_only"))) {
            sb.append(publicOnlySql(colPrefix + "doc_id"));
        }
        List<String> sens = sensListOf(filter.get("sensitivity"));
        if (!sens.isEmpty()) {
            sb.append(" AND COALESCE(").append(colPrefix).append("sensitivity,'internal') IN (")
                    .append(placeholders(sens.size())).append(")");
        }
        Object topic = filter.get("topic");
        if (topic != null && !String.valueOf(topic).isEmpty()) {
            sb.append(" AND ").append(colPrefix).append("topic = ?");
        }
        Object dateFrom = filter.get("date_from");
        if (dateFrom != null && !String.valueOf(dateFrom).isEmpty()) {
            sb.append(" AND COALESCE(").append(colPrefix).append("doc_date,'') >= ?");
        }
        Object dateTo = filter.get("date_to");
        if (dateTo != null && !String.valueOf(dateTo).isEmpty()) {
            sb.append(" AND COALESCE(").append(colPrefix).append("doc_date,'') <= ?");
        }
        // 数据源类型过滤：RAG 通道用它把 Excel 历史行卡片（source_type='excel'）挡在召回之外，
        // 即使迁移漏清也不会串道。excel_catalog（目录块）不在此列——目录本来就该能被检索到。
        List<String> src = sensListOf(filter.get("source_type"));
        if (!src.isEmpty()) {
            sb.append(" AND COALESCE(").append(colPrefix).append("source_type,'') IN (")
                    .append(placeholders(src.size())).append(")");
        }
        List<String> srcEx = sensListOf(filter.get("source_exclude"));
        if (!srcEx.isEmpty()) {
            sb.append(" AND COALESCE(").append(colPrefix).append("source_type,'') NOT IN (")
                    .append(placeholders(srcEx.size())).append(")");
        }
        return sb.toString();
    }

    /** filterSql 生成的占位符按同顺序绑定；返回下一个参数位。 */
    static int bindFilter(PreparedStatement ps, int start, Map<String, Object> filter) throws java.sql.SQLException {
        if (filter == null || filter.isEmpty()) {
            return start;
        }
        int i = start;
        List<String> sens = sensListOf(filter.get("sensitivity"));
        if (!sens.isEmpty()) {
            for (String s : sens) {
                ps.setString(i++, s);
            }
        }
        Object topic = filter.get("topic");
        if (topic != null && !String.valueOf(topic).isEmpty()) {
            ps.setString(i++, String.valueOf(topic));
        }
        Object dateFrom = filter.get("date_from");
        if (dateFrom != null && !String.valueOf(dateFrom).isEmpty()) {
            ps.setString(i++, String.valueOf(dateFrom));
        }
        Object dateTo = filter.get("date_to");
        if (dateTo != null && !String.valueOf(dateTo).isEmpty()) {
            ps.setString(i++, String.valueOf(dateTo));
        }
        for (String s : sensListOf(filter.get("source_type"))) {
            ps.setString(i++, s);
        }
        for (String s : sensListOf(filter.get("source_exclude"))) {
            ps.setString(i++, s);
        }
        return i;
    }

    /** sensitivity 参数兼容三种写法："public,internal" / List / 单字符串。 */
    private static List<String> sensListOf(Object v) {
        List<String> out = new ArrayList<>();
        if (v instanceof List) {
            for (Object o : (List<?>) v) {
                if (o != null && !String.valueOf(o).isEmpty()) {
                    out.add(String.valueOf(o));
                }
            }
            return out;
        }
        if (v != null && !String.valueOf(v).isEmpty()) {
            for (String s : String.valueOf(v).split(",")) {
                if (!s.trim().isEmpty()) {
                    out.add(s.trim());
                }
            }
        }
        return out;
    }

    public static long countVectors(Connection conn) throws SQLException {
        try (Statement st = conn.createStatement(); ResultSet rs = st.executeQuery("SELECT COUNT(*) FROM chunk_vectors")) {
            return rs.next() ? rs.getLong(1) : 0;
        }
    }
}
