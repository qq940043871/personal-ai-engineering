package com.ownrag.retrieve;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;

import org.springframework.stereotype.Component;

import com.fasterxml.jackson.databind.JsonNode;
import com.ownrag.config.Settings;
import com.ownrag.index.Embedder;
import com.ownrag.util.Json;

/**
 * 直击库（Python 版 retrieve/direct_hit.py 的平移）：L0 精确/别名 → L1 语义 → L2 沉淀候选。
 * 高频题不进 RAG：命中直接返回，零检索零生成。
 * 直击库答错比 RAG 答错更伤信任，因为它看起来最权威。
 */
@Component
public class DirectHit {

    private final Embedder embedder;
    private final Settings settings;

    public DirectHit(Embedder embedder, Settings settings) {
        this.embedder = embedder;
        this.settings = settings;
    }

    /** 命中结果（Python 版 DirectHit dataclass 的对应物）。 */
    public static class Hit {
        public final String hitId;
        public final String level;
        public final String question;
        public final String answer;
        public final double score;

        public Hit(String hitId, String level, String question, String answer, double score) {
            this.hitId = hitId;
            this.level = level;
            this.question = question;
            this.answer = answer;
            this.score = score;
        }
    }

    public Hit match(Connection conn, List<String> kbList, String question, double l1Threshold) {
        return match(conn, kbList, question, l1Threshold, true);
    }

    /**
     * @param loggedIn 为 false 时只命中 `access_level='public'` 的条目。
     *                 直击库是"零检索零生成"直达用户的答案，不挂在 documents 上，
     *                 所以它的权限必须按自己的 access_level 列过滤——否则它就是绕开文档权限的后门。
     */
    public Hit match(Connection conn, List<String> kbList, String question, double l1Threshold,
                     boolean loggedIn) {
        String q = question == null ? "" : question.trim();
        if (q.isEmpty()) {
            return null;
        }
        String placeholders = String.join(",", Collections.nCopies(kbList.size(), "?"));
        String accessClause = loggedIn ? "" : " AND COALESCE(access_level,'public')='public'";

        // ---- L0：标准问 + 别名 精确匹配（归一化：去空白/标点/全半角）----
        String norm = normalize(q);
        try (PreparedStatement ps = conn.prepareStatement(
                "SELECT * FROM direct_hits WHERE enabled=1 AND level='L0' AND kb IN (" + placeholders + ")"
                        + accessClause)) {
            for (int i = 0; i < kbList.size(); i++) {
                ps.setString(i + 1, kbList.get(i));
            }
            try (ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    if (norm.equals(normalize(rs.getString("question")))) {
                        return new Hit(rs.getString("id"), "L0", rs.getString("question"),
                                rs.getString("answer"), 1.0);
                    }
                    JsonNode aliases = Json.MAPPER.readTree(rs.getString("aliases_json") == null
                            || rs.getString("aliases_json").isEmpty() ? "[]" : rs.getString("aliases_json"));
                    for (JsonNode a : aliases) {
                        if (norm.equals(normalize(a.asText()))) {
                            return new Hit(rs.getString("id"), "L0", rs.getString("question"),
                                    rs.getString("answer"), 1.0);
                        }
                    }
                }
            }
        } catch (Exception e) {
            // 表/JSON 异常 = 直击库 L0 不可用，走 RAG 正常链路（降级可见由调用方记录）
            return null;
        }

        // ---- L1/L2：embedding 相似度阈值命中（embed 不可用时跳过，降级可见）----
        try {
            return matchSemantic(conn, kbList, q, l1Threshold, accessClause);
        } catch (Embedder.EmbedError | SQLException e) {
            // L1 通道不可用——调用方把"直击库未检 L1"写进 trace 说明
            return null;
        }
    }

    private Hit matchSemantic(Connection conn, List<String> kbList, String q, double l1Threshold,
                              String accessClause) throws SQLException {
        String placeholders = String.join(",", Collections.nCopies(kbList.size(), "?"));
        List<Map<String, Object>> rows = new ArrayList<>();
        try (PreparedStatement ps = conn.prepareStatement(
                "SELECT * FROM direct_hits WHERE enabled=1 AND level IN ('L1','L2') AND kb IN ("
                        + placeholders + ")" + accessClause)) {
            for (int i = 0; i < kbList.size(); i++) {
                ps.setString(i + 1, kbList.get(i));
            }
            try (ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    rows.add(com.ownrag.core.TaskStore.rowToMap(rs));
                }
            }
        }
        if (rows.isEmpty()) {
            return null;
        }
        List<Double> qEmb = embedder.embedQuery(settings, q);
        List<List<Double>> embs = embedder.embedTexts(settings, questionsOf(rows), 32, null);
        for (int i = 0; i < rows.size() && i < embs.size(); i++) {
            double sim = cosine(qEmb, embs.get(i));
            if (sim >= l1Threshold) {
                Map<String, Object> row = rows.get(i);
                return new Hit(String.valueOf(row.get("id")),
                        String.valueOf(row.get("level")),
                        String.valueOf(row.get("question")),
                        String.valueOf(row.get("answer")),
                        Math.round(sim * 10000.0) / 10000.0);
            }
        }
        return null;
    }

    private static List<String> questionsOf(List<Map<String, Object>> rows) {
        List<String> out = new ArrayList<>();
        for (Map<String, Object> row : rows) {
            out.add(String.valueOf(row.get("question")));
        }
        return out;
    }

    /** 归一化：去空白/标点，全角字母数字归半角，仅保留字母数字汉字。 */
    static String normalize(String s) {
        StringBuilder out = new StringBuilder();
        for (int i = 0; i < s.length(); i++) {
            char ch = s.charAt(i);
            if (ch >= '\uFF01' && ch <= '\uFF5E') {
                ch = (char) (ch - 0xFEE0);
            }
            if ((ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') || (ch >= '0' && ch <= '9')) {
                out.append(Character.toLowerCase(ch));
            } else if (ch >= '\u4e00' && ch <= '\u9fff') {
                out.append(ch);
            }
        }
        return out.toString();
    }

    static double cosine(List<Double> a, List<Double> b) {
        int n = Math.min(a.size(), b.size());
        double num = 0, da = 0, db = 0;
        for (int i = 0; i < n; i++) {
            num += a.get(i) * b.get(i);
            da += a.get(i) * a.get(i);
            db += b.get(i) * b.get(i);
        }
        if (da == 0 || db == 0) {
            return 0.0;
        }
        return num / (Math.sqrt(da) * Math.sqrt(db));
    }
}
