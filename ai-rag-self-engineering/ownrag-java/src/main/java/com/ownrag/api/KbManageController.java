package com.ownrag.api;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;

import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.ownrag.config.KbWhitelist;
import com.ownrag.config.Settings;
import com.ownrag.core.Db;
import com.ownrag.index.ChunkStore;
import com.ownrag.index.FingerprintStore;
import com.ownrag.util.Json;

/**
 * 知识库管理视图：知识库 → 文档 → 向量块 三级下钻。
 *
 * 与 /admin/chunks 的区别：那是"按关键词捞块"的检索调试口径；这里回答的是管理口径的三个问题——
 * 库里有哪些文档？每篇文档切了几块？这些块里哪些真的写了向量（dim / 模长 / 前几维）？
 * 另有 purge：库级清空（派生内容六通道一次清：chunks / FTS / 向量 / 文件指纹 / 块指纹 /
 * Excel 动态 staging 表，替代容易漏表的手工 SQL）；换 embedding 模型后用 reembed 原地重建向量。
 *
 * 没有 documents 实体表：文档身份以 doc_id 贯穿 chunks / chunk_vectors / tasks / parse_reviews，
 * 文件名优先取 doc_fingerprints（所有管道上传时都登记），parse_reviews 只覆盖带复核闸的管道。
 */
@RestController
public class KbManageController {

    /** 单块正文上限：防病态大块把响应撑爆，正常块（512 tok）远小于此。 */
    private static final int MAX_TEXT_CHARS = 20000;
    private static final int VEC_PREVIEW = 8;

    private final Settings settings;
    private final com.ownrag.index.Embedder embedder;

    public KbManageController(Settings settings, com.ownrag.index.Embedder embedder) {
        this.settings = settings;
        this.embedder = embedder;
    }

    // ---------------------------------------------------------------- 知识库

    /** 库列表 = apps.yaml 声明 ∪ kb_registry 登记 ∪ 库里实际有数据的 kb。 */
    @GetMapping("/admin/kbs")
    public Map<String, Object> listKbs() throws Exception {
        Set<String> names = KbWhitelist.all(settings);
        Map<String, long[]> stats = new TreeMap<>();
        try (Connection conn = Db.connect(settings.getDbPath())) {
            // 文档/块/字数统一以 documents 实体为口径，和文档清单页保持一致
            try (PreparedStatement ps = conn.prepareStatement(
                    "SELECT kb, COUNT(*) docs, COALESCE(SUM(chunk_count),0) chunks, "
                            + "COALESCE(SUM(vector_count),0) vectors, COALESCE(SUM(chars),0) chars "
                            + "FROM documents GROUP BY kb");
                 ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    String kb = rs.getString("kb");
                    names.add(kb);
                    long[] s = ensure(stats, kb);
                    s[0] = rs.getLong("vectors");
                    s[1] = rs.getLong("chunks");
                    s[2] = rs.getLong("docs");
                    s[3] = rs.getLong("chars");
                }
            }
        }
        Set<String> declared = settings.getKnownKbs();
        Set<String> registered = new LinkedHashSet<>();
        Map<String, String> descriptions = new LinkedHashMap<>();
        try (Connection conn = Db.connect(settings.getDbPath());
             PreparedStatement ps = conn.prepareStatement("SELECT kb, description FROM kb_registry");
             ResultSet rs = ps.executeQuery()) {
            while (rs.next()) {
                registered.add(rs.getString("kb"));
                descriptions.put(rs.getString("kb"), rs.getString("description"));
            }
        }
        List<Map<String, Object>> rows = new ArrayList<>();
        for (String kb : names) {
            long[] s = ensure(stats, kb);
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("kb", kb);
            row.put("documents", s[2]);
            row.put("chunks", s[1]);
            row.put("vectors", s[0]);
            row.put("chars", s[3]);
            row.put("declared", declared.contains(kb));
            row.put("source", declared.contains(kb) ? "apps.yaml" : (registered.contains(kb) ? "registry" : "data"));
            row.put("description", descriptions.getOrDefault(kb, ""));
            rows.add(row);
        }
        rows.sort(Comparator
                .comparingLong((Map<String, Object> r) -> (Long) r.get("documents"))
                .reversed()
                .thenComparing((Map<String, Object> r) -> String.valueOf(r.get("kb"))));
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("total", rows.size());
        out.put("kbs", rows);
        return out;
    }

    public static class KbIn {
        public String kb;
        public String description;
    }

    /** 运行时新建空库：写 kb_registry，上传白名单立即生效，无需改 apps.yaml 重启。 */
    @PostMapping("/admin/kbs")
    public Map<String, Object> createKb(@RequestBody KbIn body) throws Exception {
        String kb = body.kb == null ? "" : body.kb.trim();
        if (!kb.matches("[A-Za-z0-9_-]{1,64}")) {
            throw new ApiError(422, "kb 名只允许字母/数字/_/-，长度 1-64");
        }
        if (KbWhitelist.all(settings).contains(kb)) {
            throw new ApiError(409, "知识库已存在：" + kb + "（apps.yaml 声明或 kb_registry 登记）");
        }
        try (Connection conn = Db.connect(settings.getDbPath())) {
            try (PreparedStatement ps = conn.prepareStatement("SELECT 1 FROM chunks WHERE kb=? LIMIT 1")) {
                ps.setString(1, kb);
                try (ResultSet rs = ps.executeQuery()) {
                    if (rs.next()) {
                        throw new ApiError(409, "库中已有历史数据，直接复用即可：" + kb);
                    }
                }
            }
            try (PreparedStatement ps = conn.prepareStatement(
                    "INSERT INTO kb_registry(kb, description) VALUES (?,?)")) {
                ps.setString(1, kb);
                ps.setString(2, body.description == null ? "" : body.description.trim());
                ps.executeUpdate();
            }
            conn.commit();
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("kb", kb);
        out.put("status", "created");
        return out;
    }

    /** 删除运行时登记的库：不允许删 apps.yaml 声明库，也不允许删还有文档的库。 */
    @DeleteMapping("/admin/kbs/{kb}")
    public Map<String, Object> deleteKb(@PathVariable String kb) throws Exception {
        if (settings.getKnownKbs().contains(kb)) {
            throw new ApiError(422, "该库声明于 apps.yaml，删除需改配置并重启");
        }
        try (Connection conn = Db.connect(settings.getDbPath())) {
            long docs;
            try (PreparedStatement ps = conn.prepareStatement(
                    "SELECT COUNT(*) n FROM documents WHERE kb=?")) {
                ps.setString(1, kb);
                try (ResultSet rs = ps.executeQuery()) {
                    docs = rs.next() ? rs.getLong("n") : 0;
                }
            }
            if (docs > 0) {
                throw new ApiError(422, "库中还有 " + docs + " 篇文档，请先删除文档");
            }
            try (PreparedStatement ps = conn.prepareStatement("DELETE FROM kb_registry WHERE kb=?")) {
                ps.setString(1, kb);
                if (ps.executeUpdate() == 0) {
                    throw new ApiError(404, "运行时登记的库不存在：" + kb);
                }
            }
            conn.commit();
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("kb", kb);
        out.put("status", "deleted");
        return out;
    }

    /**
     * 清空一个库的全部索引内容：FTS / 向量 / 块hash / 文件指纹 / chunks 五通道一次清，
     * 任务与复核记录留作历史。清完再走 DELETE /admin/kbs/{kb} 删注册行即可。
     * 与逐文档 DELETE /docs/{docId} 同口径——封住"手工 SQL 删库漏清 chunk_hashes"的坑
     * （2026-11-20 审查发现：漏清的孤儿 hash 会让重灌的块全部被判重复丢弃）。
     */
    @PostMapping("/admin/kbs/{kb}/purge")
    public Map<String, Object> purgeKb(@PathVariable String kb) throws Exception {
        List<String> docIds = new ArrayList<>();
        long chunkCount = 0;
        try (Connection conn = Db.connect(settings.getDbPath())) {
            try (PreparedStatement ps = conn.prepareStatement(
                    "SELECT DISTINCT doc_id FROM chunks WHERE kb=?")) {
                ps.setString(1, kb);
                try (ResultSet rs = ps.executeQuery()) {
                    while (rs.next()) {
                        docIds.add(rs.getString(1));
                    }
                }
            }
            try (PreparedStatement ps = conn.prepareStatement(
                    "SELECT COUNT(*) FROM chunks WHERE kb=?")) {
                ps.setString(1, kb);
                try (ResultSet rs = ps.executeQuery()) {
                    chunkCount = rs.next() ? rs.getLong(1) : 0;
                }
            }
            Db.endRead(conn);  // 上面开了读事务，下面全是删：先收尾再写
            if (docIds.isEmpty()) {
                throw new ApiError(404, "库不存在或没有已索引文档：" + kb);
            }
            int removedChunks = 0;
            int stagingDropped = 0;
            for (String docId : docIds) {
                ChunkStore.keywordDeleteDoc(conn, docId);
                ChunkStore.vectorDeleteDoc(conn, docId);
                try (PreparedStatement ps = conn.prepareStatement(
                        "DELETE FROM chunks WHERE doc_id=?")) {
                    ps.setString(1, docId);
                    removedChunks += ps.executeUpdate();
                }
                // 块 hash 与文件指纹一并释放：同内容文件之后可重新灌库
                FingerprintStore.deleteByDoc(conn, docId);
                com.ownrag.core.DocumentStore.delete(conn, docId);
                // Excel 动态 staging 表 + 登记行（第六通道）：库级清空后不留孤儿表
                stagingDropped += com.ownrag.ingest.StagingStore.dropByDoc(conn, docId).size();
            }
            conn.commit();
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("kb", kb);
            out.put("status", "purged");
            out.put("docs_removed", docIds.size());
            out.put("chunks_removed", removedChunks);
            out.put("staging_tables_dropped", stagingDropped);
            out.put("chunk_count_before", chunkCount);
            return out;
        }
    }

    // ---------------------------------------------------------------- 文档

    /**
     * 向量通道重建（换 embedding 模型的必要动作）：按 chunks.text 原地重算向量，
     * 不重跑解析/切分（MinerU 额度、ffmpeg+ASR 成本全免），写完同步刷新 chunks.embed_version
     * 与 documents.vector_count。
     *
     * 为什么要有这条通道：检索侧按 embed_version 隔离召回，换值后旧向量立即失效，
     * 重建前向量通道为空（BM25 单路，检索页会明说）。手工 SQL 重建要自己处理 float[]→BLOB
     * 小端序列化与统计回填，很容易漏——这里一次做完，失败即整批回滚。
     *
     * 用法（batch 上限 32，受 SiliconFlow /embeddings 批量限制；limit=0 表示全量）：
     *   curl -X POST "http://127.0.0.1:8420/admin/kbs/kb_interview/reembed?batch=16"
     */
    @PostMapping("/admin/kbs/{kb}/reembed")
    public Map<String, Object> reembedKb(@PathVariable("kb") String kb,
                                         @RequestParam(value = "batch", defaultValue = "16") int batch,
                                         @RequestParam(value = "limit", defaultValue = "0") int limit)
            throws Exception {
        final String version = settings.getEmbedVersion();
        batch = Math.max(1, Math.min(batch, 32));

        // 先一次性读出待重建块，读完立刻收尾读事务（读后要写，见 Db.endRead 注释）
        List<Map<String, Object>> pending = new ArrayList<>();
        try (Connection conn = Db.connect(settings.getDbPath())) {
            String sql = "SELECT chunk_id, doc_id, text FROM chunks "
                    + "WHERE kb=? AND (embed_version IS NULL OR embed_version<>?) "
                    + "ORDER BY doc_id, ordinal, chunk_id" + (limit > 0 ? " LIMIT ?" : "");
            try (PreparedStatement ps = conn.prepareStatement(sql)) {
                ps.setString(1, kb);
                ps.setString(2, version);
                if (limit > 0) {
                    ps.setInt(3, limit);
                }
                try (ResultSet rs = ps.executeQuery()) {
                    while (rs.next()) {
                        Map<String, Object> row = new LinkedHashMap<>();
                        row.put("chunk_id", rs.getString(1));
                        row.put("doc_id", rs.getString(2));
                        String text = rs.getString(3);
                        row.put("text", text == null ? "" : text);
                        pending.add(row);
                    }
                }
            }
            Db.endRead(conn);
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("kb", kb);
        out.put("embed_model", settings.getEmbedModel());
        out.put("embed_version", version);
        if (pending.isEmpty()) {
            out.put("status", "noop");
            out.put("pending", 0);
            out.put("note", "该库已全部是当前 embed_version，无需重建");
            return out;
        }

        long t0 = System.nanoTime();
        int done = 0;
        int dim = 0;
        Set<String> docs = new LinkedHashSet<>();
        try (Connection conn = Db.connect(settings.getDbPath())) {
            for (int i = 0; i < pending.size(); i += batch) {
                List<Map<String, Object>> part = new ArrayList<>(
                        pending.subList(i, Math.min(i + batch, pending.size())));
                List<String> texts = new ArrayList<>();
                for (Map<String, Object> r : part) {
                    texts.add(String.valueOf(r.get("text")));
                }
                List<List<Double>> embs;
                try {
                    embs = embedder.embedTexts(settings, texts, batch, null);
                } catch (com.ownrag.index.Embedder.EmbedError e) {
                    conn.rollback();
                    throw new ApiError(502, "向量重建中断（已写入 " + done + " 块，可重复调用续跑，天然幂等）："
                            + e.getMessage());
                }
                if (embs.size() != part.size()) {
                    conn.rollback();
                    throw new ApiError(502, "向量数不符：请求 " + part.size() + " 返回 " + embs.size());
                }
                ChunkStore.vectorUpsert(conn, kb, part, embs);
                try (PreparedStatement ps = conn.prepareStatement(
                        "UPDATE chunks SET embed_version=? WHERE chunk_id=?")) {
                    for (Map<String, Object> r : part) {
                        ps.setString(1, version);
                        ps.setString(2, String.valueOf(r.get("chunk_id")));
                        ps.executeUpdate();
                        docs.add(String.valueOf(r.get("doc_id")));
                    }
                }
                conn.commit();
                done += part.size();
                dim = embs.get(0).size();
            }
            // documents.vector_count 等统计口径同步（管理页只读这张表）
            for (String docId : docs) {
                com.ownrag.core.DocumentStore.refreshStats(conn, docId);
            }
            conn.commit();
        }

        out.put("status", "reembedded");
        out.put("pending_before", pending.size());
        out.put("reembedded", done);
        out.put("docs", docs.size());
        out.put("dim", dim);
        out.put("batches", (pending.size() + batch - 1) / batch);
        out.put("ms", Math.round((System.nanoTime() - t0) / 1_000_000.0 * 10) / 10.0);
        if (limit > 0) {
            out.put("note", "limit=" + limit + " 截断本次处理量：再调一次会接着处理剩下的块（幂等）");
        }
        return out;
    }

    /** 某个库里的文档清单：文件名、块数、向量数、最近任务状态一屏看全。 */
    @GetMapping("/admin/kbs/{kb}/documents")
    public Map<String, Object> listDocuments(@PathVariable String kb,
                                             @RequestParam(defaultValue = "") String q,
                                             @RequestParam(defaultValue = "20") int limit,
                                             @RequestParam(defaultValue = "0") int offset)
            throws Exception {
        limit = Math.max(1, Math.min(limit, 200));
        offset = Math.max(0, offset);
        String qv = q.trim();
        String filter = qv.isEmpty() ? "" :
                " AND (instr(lower(COALESCE(source_file,'')), lower(?)) > 0"
                        + " OR instr(lower(doc_id), lower(?)) > 0)";

        long total = 0;
        try (Connection conn = Db.connect(settings.getDbPath())) {
            try (PreparedStatement ps = conn.prepareStatement(
                    "SELECT COUNT(*) n FROM documents WHERE kb=?" + filter)) {
                ps.setString(1, kb);
                if (!qv.isEmpty()) {
                    ps.setString(2, qv);
                    ps.setString(3, qv);
                }
                try (ResultSet rs = ps.executeQuery()) {
                    total = rs.next() ? rs.getLong("n") : 0;
                }
            }

            String sql = "SELECT doc_id, kb,"
                    + " COALESCE(source_file, doc_id) source_file,"
                    + " chunk_count, vector_count, chars,"
                    + " created_at first_at, updated_at last_at,"
                    + " task_status, pipeline, review_status, size_bytes, file_hash"
                    + " FROM documents WHERE kb=?" + filter
                    + " ORDER BY last_at DESC, doc_id LIMIT ? OFFSET ?";
            List<Map<String, Object>> docs = new ArrayList<>();
            try (PreparedStatement ps = conn.prepareStatement(sql)) {
                int i = 1;
                ps.setString(i++, kb);
                if (!qv.isEmpty()) {
                    ps.setString(i++, qv);
                    ps.setString(i++, qv);
                }
                ps.setInt(i++, limit);
                ps.setInt(i, offset);
                try (ResultSet rs = ps.executeQuery()) {
                    while (rs.next()) {
                        Map<String, Object> row = new LinkedHashMap<>();
                        row.put("doc_id", rs.getString("doc_id"));
                        row.put("kb", rs.getString("kb"));
                        row.put("source_file", rs.getString("source_file"));
                        row.put("chunk_count", rs.getLong("chunk_count"));
                        row.put("vector_count", rs.getLong("vector_count"));
                        row.put("chars", rs.getLong("chars"));
                        row.put("first_at", rs.getString("first_at"));
                        row.put("last_at", rs.getString("last_at"));
                        row.put("task_status", rs.getString("task_status"));
                        row.put("pipeline", rs.getString("pipeline"));
                        row.put("review_status", rs.getString("review_status"));
                        row.put("size_bytes", rs.getLong("size_bytes"));
                        row.put("file_hash", rs.getString("file_hash"));
                        docs.add(row);
                    }
                }
            }
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("kb", kb);
            out.put("q", qv);
            out.put("total", total);
            out.put("limit", limit);
            out.put("offset", offset);
            out.put("documents", docs);
            return out;
        }
    }

    // ---------------------------------------------------------------- 向量块

    /** 某篇文档切出的全部块（按 ordinal）：全文 + 锚点/元数据 + 向量在位情况。 */
    @GetMapping("/admin/documents/{docId}/chunks")
    public Map<String, Object> listDocChunks(@PathVariable String docId,
                                             @RequestParam(defaultValue = "") String kb,
                                             @RequestParam(defaultValue = "") String q,
                                             @RequestParam(defaultValue = "20") int limit,
                                             @RequestParam(defaultValue = "0") int offset)
            throws Exception {
        limit = Math.max(1, Math.min(limit, 200));
        offset = Math.max(0, offset);
        String qv = q.trim();
        StringBuilder where = new StringBuilder(" WHERE doc_id=?");
        List<Object> args = new ArrayList<>();
        args.add(docId);
        if (!kb.isEmpty()) {
            where.append(" AND kb=?");
            args.add(kb);
        }
        if (!qv.isEmpty()) {
            where.append(" AND instr(lower(text), lower(?)) > 0");
            args.add(qv);
        }

        long total = 0;
        try (Connection conn = Db.connect(settings.getDbPath())) {
            try (PreparedStatement ps = conn.prepareStatement(
                    "SELECT COUNT(*) n FROM chunks" + where)) {
                for (int i = 0; i < args.size(); i++) {
                    ps.setObject(i + 1, args.get(i));
                }
                try (ResultSet rs = ps.executeQuery()) {
                    total = rs.next() ? rs.getLong("n") : 0;
                }
            }

            // 一次取该文档所有向量，避免逐块查库；chunk_id 全局唯一，kb 条件对块行已生效
            Map<String, float[]> vectors = new LinkedHashMap<>();
            Map<String, Integer> dims = new LinkedHashMap<>();
            try (PreparedStatement ps = conn.prepareStatement(
                    "SELECT chunk_id, embedding, dim FROM chunk_vectors WHERE doc_id=?")) {
                ps.setString(1, docId);
                try (ResultSet rs = ps.executeQuery()) {
                    while (rs.next()) {
                        vectors.put(rs.getString("chunk_id"), ChunkStore.fromBlob(rs.getBytes("embedding")));
                        dims.put(rs.getString("chunk_id"), rs.getInt("dim"));
                    }
                }
            }

            List<Map<String, Object>> chunks = new ArrayList<>();
            String sql = "SELECT chunk_id, doc_id, kb, ordinal, source_type, text, "
                    + "anchors_json, meta_json, embed_version, sensitivity, topic, doc_date, origin, created_at"
                    + " FROM chunks" + where + " ORDER BY ordinal LIMIT ? OFFSET ?";
            try (PreparedStatement ps = conn.prepareStatement(sql)) {
                int i = 1;
                for (Object a : args) {
                    ps.setObject(i++, a);
                }
                ps.setInt(i++, limit);
                ps.setInt(i, offset);
                try (ResultSet rs = ps.executeQuery()) {
                    while (rs.next()) {
                        chunks.add(chunkRow(rs, vectors, dims));
                    }
                }
            }
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("doc_id", docId);
            out.put("kb", kb);
            out.put("q", qv);
            out.put("total", total);
            out.put("limit", limit);
            out.put("offset", offset);
            out.put("chunks", chunks);
            return out;
        }
    }

    // ---------------------------------------------------------------- 小工具

    private static Map<String, Object> chunkRow(ResultSet rs, Map<String, float[]> vectors,
                                                Map<String, Integer> dims) throws Exception {
        String chunkId = rs.getString("chunk_id");
        String text = rs.getString("text") == null ? "" : rs.getString("text");
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("chunk_id", chunkId);
        row.put("doc_id", rs.getString("doc_id"));
        row.put("kb", rs.getString("kb"));
        row.put("ordinal", rs.getInt("ordinal"));
        row.put("source_type", rs.getString("source_type"));
        row.put("embed_version", rs.getString("embed_version"));
        row.put("sensitivity", rs.getString("sensitivity"));
        row.put("topic", rs.getString("topic"));
        row.put("doc_date", rs.getString("doc_date"));
        row.put("origin", rs.getString("origin"));
        row.put("created_at", rs.getString("created_at"));
        row.put("chars", text.length());
        row.put("text", text.length() > MAX_TEXT_CHARS ? text.substring(0, MAX_TEXT_CHARS) : text);
        row.put("truncated", text.length() > MAX_TEXT_CHARS);
        row.put("anchors", parseOrEmpty(rs.getString("anchors_json")));
        row.put("meta", parseOrEmpty(rs.getString("meta_json")));

        Map<String, Object> vec = new LinkedHashMap<>();
        float[] v = vectors.get(chunkId);
        if (v == null) {
            vec.put("present", false);
            vec.put("dim", 0);
        } else {
            double sum = 0;
            List<Object> preview = new ArrayList<>();
            for (int i = 0; i < v.length; i++) {
                sum += v[i] * v[i];
                if (i < VEC_PREVIEW) {
                    preview.add(Math.round(v[i] * 1e4) / 1e4);
                }
            }
            vec.put("present", true);
            vec.put("dim", dims.containsKey(chunkId) ? dims.get(chunkId) : v.length);
            vec.put("norm", Math.round(Math.sqrt(sum) * 1e4) / 1e4);
            vec.put("preview", preview);
        }
        row.put("vector", vec);
        return row;
    }

    private static Map<String, Object> parseOrEmpty(String json) {
        if (json == null || json.isEmpty()) {
            return new LinkedHashMap<>();
        }
        try {
            return Json.readMap(json);
        } catch (Exception e) {
            return new LinkedHashMap<>();
        }
    }

    private static long[] ensure(Map<String, long[]> stats, String kb) {
        long[] s = stats.get(kb);
        if (s == null) {
            s = new long[4];
            stats.put(kb, s);
        }
        return s;
    }
}
