package com.ownrag.auth;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * 越权二次校验（生成前复核候选 + 生成后复核答案）：**不信任上游的过滤**，自己再查一次库。
 *
 * 为什么要它：检索层的 public_only 过滤是"一条 SQL 写对了才生效"的约定；将来新增一条召回通道
 * （向量、SQL、直击、外部 API…）忘了带过滤条件，越权内容就会悄无声息地进候选池。这里做的是
 * fail-closed 的兜底：把候选/答案里的 doc_id 拿去 documents 再问一遍"当前会话能不能读"。
 *
 * 两条时间线（对应 docs「先过滤后召回」之外的第二道）：
 *   ① {@link #filterCandidates}：候选池成型后、进模型之前——越权块直接剔除（这才挡得住内容，
 *      因为流式 token 一旦吐出去就收不回来）。
 *   ② {@link #checkAnswer}：生成之后——答案点名了"当前会话读不到的文档"→ 判越权并撤回。
 *
 * 注意它**不判断内容本身是否敏感**（那是 sensitivity/redline 的活），只判断"来源是否有权"。
 */
public final class AccessPostCheck {

    private AccessPostCheck() {
    }

    /** 校验结果：passed=false 就是越权，violations 只说"哪个文档/哪一块"，不回显受限正文。 */
    public static class Result {
        public boolean passed = true;
        public final List<String> violations = new ArrayList<>();
        public final List<String> droppedDocIds = new ArrayList<>();
        public int droppedBlocks;
        public String note = "";

        public Map<String, Object> toCounters() {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("passed", passed);
            m.put("violations", violations);
            m.put("dropped_doc_ids", droppedDocIds);
            m.put("dropped_blocks", droppedBlocks);
            m.put("note", note);
            return m;
        }
    }

    /**
     * ① 生成前：独立复核候选池里每个块的 doc_id。
     * 已登录 → 全部可读，直接放行（不过一遍无谓的 SQL）；未登录 → 只留 public。
     * 返回的 Result 里 droppedBlocks / droppedDocIds 描述"被剔掉了什么"，调用方据此播报。
     */
    public static Result filterCandidates(Connection conn, List<Map<String, Object>> candidates,
                                          boolean loggedIn) throws SQLException {
        Result r = new Result();
        if (candidates == null || candidates.isEmpty()) {
            r.note = "候选池为空，无需复核";
            return r;
        }
        if (loggedIn) {
            r.note = "已登录：全部候选可读";
            return r;
        }
        Set<String> docIds = new LinkedHashSet<>();
        for (Map<String, Object> c : candidates) {
            String id = str(c.get("doc_id"));
            if (id != null && !id.isEmpty()) {
                docIds.add(id);
            }
        }
        // 取"受限"集合而不是"公开"集合：documents 里没有行的存量文档按公开处理（与检索层同口径），
        // 否则老库升级后所有历史块都会被二次校验误杀
        Set<String> blocked = protectedDocIds(conn, docIds);
        List<Map<String, Object>> kept = new ArrayList<>();
        for (Map<String, Object> c : candidates) {
            String id = str(c.get("doc_id"));
            if (id == null || id.isEmpty() || !blocked.contains(id)) {
                kept.add(c);
            } else {
                r.droppedBlocks++;
                if (!r.droppedDocIds.contains(id)) {
                    r.droppedDocIds.add(id);
                }
            }
        }
        if (r.droppedBlocks > 0) {
            r.passed = false;
            r.violations.add("候选池含 " + r.droppedBlocks + " 块「需登录」文档的内容（doc_id "
                    + r.droppedDocIds + "），已在进模型前剔除");
            r.note = "生成前二次校验剔除 " + r.droppedBlocks + " 块越权候选";
            candidates.clear();
            candidates.addAll(kept);
        } else {
            r.note = "生成前二次校验通过（候选 " + candidates.size() + " 块全部可读）";
        }
        return r;
    }

    /**
     * ② 生成后：答案是否点名了"当前会话读不到的文档"。
     * 只看**受限文档的文件名**（去扩展名、≥4 字），且排除已出现在候选里的名字——
     * 公开文档名、普通业务词都不会误伤。
     */
    public static Result checkAnswer(Connection conn, String answer, List<Map<String, Object>> candidates,
                                     List<String> kbs, boolean loggedIn) throws SQLException {
        Result r = new Result();
        if (answer == null || answer.trim().isEmpty()) {
            r.note = "空答案，跳过";
            return r;
        }
        if (loggedIn) {
            r.note = "已登录：无受限文档可越权";
            return r;
        }
        Set<String> allowedNames = new LinkedHashSet<>();
        for (Map<String, Object> c : candidates == null ? new ArrayList<Map<String, Object>>() : candidates) {
            String name = baseName(str(c.get("doc_name")));
            if (name != null) {
                allowedNames.add(name.toLowerCase(Locale.ROOT));
            }
        }
        List<String[]> blocked = protectedDocNames(conn, kbs);
        String lowerAnswer = answer.toLowerCase(Locale.ROOT);
        for (String[] pair : blocked) {
            String name = baseName(pair[0]);
            if (name == null || name.length() < 4) {
                continue;   // 太短的名字（如 "a.md"）当关键词会满屏误伤
            }
            String key = name.toLowerCase(Locale.ROOT);
            if (allowedNames.contains(key)) {
                continue;
            }
            if (lowerAnswer.contains(key)) {
                r.passed = false;
                r.violations.add("答案点名了无权访问的文档《" + pair[0] + "》");
            }
        }
        r.note = r.passed ? "生成后二次校验通过" : "生成后二次校验拦截 " + r.violations.size() + " 项";
        return r;
    }

    /** 撤回话术：不解释"看到了什么"，只给"为什么看不到 + 下一步怎么做"。 */
    public static String retractedAnswer() {
        return "本轮答案涉及你无权访问的内容，已被安全校验拦截，无法展示。\n"
                + "登录后可以查询与访问全部文档：/ui/login?next=/ui/chat";
    }

    // ---------------------------------------------------------------- 只读查询（documents 是唯一事实源）

    private static Set<String> protectedDocIds(Connection conn, Collection<String> docIds) throws SQLException {
        Set<String> out = new LinkedHashSet<>();
        if (docIds.isEmpty()) {
            return out;
        }
        StringBuilder sql = new StringBuilder(
                "SELECT doc_id FROM documents WHERE COALESCE(access_level,'public')<>'public' AND doc_id IN (");
        for (int i = 0; i < docIds.size(); i++) {
            sql.append(i == 0 ? "?" : ",?");
        }
        sql.append(")");
        try (PreparedStatement ps = conn.prepareStatement(sql.toString())) {
            int i = 1;
            for (String id : docIds) {
                ps.setString(i++, id);
            }
            try (ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    out.add(rs.getString(1));
                }
            }
        }
        return out;
    }

    /** 受限文档清单（source_file 与 doc_id）：答案点名扫描用，不含正文。 */
    private static List<String[]> protectedDocNames(Connection conn, List<String> kbs) throws SQLException {
        List<String[]> out = new ArrayList<>();
        StringBuilder sql = new StringBuilder(
                "SELECT source_file, doc_id FROM documents WHERE COALESCE(access_level,'public')<>'public'");
        boolean withKb = kbs != null && !kbs.isEmpty();
        if (withKb) {
            sql.append(" AND kb IN (");
            for (int i = 0; i < kbs.size(); i++) {
                sql.append(i == 0 ? "?" : ",?");
            }
            sql.append(")");
        }
        try (PreparedStatement ps = conn.prepareStatement(sql.toString())) {
            if (withKb) {
                for (int i = 0; i < kbs.size(); i++) {
                    ps.setString(i + 1, kbs.get(i));
                }
            }
            try (ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    out.add(new String[]{rs.getString(1), rs.getString(2)});
                }
            }
        }
        return out;
    }

    /** "薪酬带宽.xlsx" → "薪酬带宽"：答案里引用文档时通常不带扩展名。 */
    static String baseName(String sourceFile) {
        if (sourceFile == null || sourceFile.trim().isEmpty()) {
            return null;
        }
        String s = sourceFile.trim();
        int slash = Math.max(s.lastIndexOf('/'), s.lastIndexOf('\\'));
        if (slash >= 0) {
            s = s.substring(slash + 1);
        }
        int dot = s.lastIndexOf('.');
        if (dot > 0) {
            s = s.substring(0, dot);
        }
        return s.isEmpty() ? null : s;
    }

    private static String str(Object o) {
        return o == null ? null : String.valueOf(o);
    }
}
