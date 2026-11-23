package com.ownrag.auth;

import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 用户表与会话表存取（纯 JDBC，无状态）。
 *
 * 时间口径与全库一致：`TEXT` + `datetime('now','localtime')`，过期判定就是字符串比较
 * （`expires_at > datetime('now','localtime')`），不给 SQLite 引入时区换算。
 */
public final class UserStore {

    /** 会话默认有效期：7 天。够长到不用天天登录，够短到丢设备不会长期被借用。 */
    public static final int SESSION_TTL_HOURS = 24 * 7;

    private static final SecureRandom RANDOM = new SecureRandom();

    private UserStore() {
    }

    // ---------------------------------------------------------------- 用户

    /** 按用户名取用户行（含 salt/hash，仅供 AuthService 校验，不要直接下发）。 */
    public static Map<String, Object> find(Connection conn, String username) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement("SELECT * FROM users WHERE username=?")) {
            ps.setString(1, username);
            try (ResultSet rs = ps.executeQuery()) {
                if (!rs.next()) {
                    return null;
                }
                Map<String, Object> row = new LinkedHashMap<>();
                row.put("username", rs.getString("username"));
                row.put("password_hash", rs.getString("password_hash"));
                row.put("salt", rs.getString("salt"));
                row.put("display_name", rs.getString("display_name"));
                row.put("role", rs.getString("role"));
                row.put("created_at", rs.getString("created_at"));
                row.put("last_login_at", rs.getString("last_login_at"));
                return row;
            }
        }
    }

    public static long count(Connection conn) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement("SELECT COUNT(*) FROM users");
             ResultSet rs = ps.executeQuery()) {
            return rs.next() ? rs.getLong(1) : 0;
        }
    }

    /** 建号（用户名已存在返回 false，调用方决定是拒绝还是改密）。 */
    public static boolean create(Connection conn, String username, String passwordHash, String salt,
                                 String displayName, String role) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement(
                "INSERT OR IGNORE INTO users(username, password_hash, salt, display_name, role) "
                        + "VALUES (?,?,?,?,?)")) {
            ps.setString(1, username);
            ps.setString(2, passwordHash);
            ps.setString(3, salt);
            ps.setString(4, displayName == null || displayName.isEmpty() ? username : displayName);
            ps.setString(5, role == null || role.isEmpty() ? "user" : role);
            boolean ok = ps.executeUpdate() > 0;
            conn.commit();
            return ok;
        }
    }

    /** 改密（换新盐），同时清空该用户全部会话——改密的语义就是"把旧设备踢下线"。 */
    public static void updatePassword(Connection conn, String username, String passwordHash, String salt)
            throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement(
                "UPDATE users SET password_hash=?, salt=? WHERE username=?")) {
            ps.setString(1, passwordHash);
            ps.setString(2, salt);
            ps.setString(3, username);
            ps.executeUpdate();
        }
        deleteSessionsOf(conn, username);
        conn.commit();
    }

    public static void touchLogin(Connection conn, String username) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement(
                "UPDATE users SET last_login_at=datetime('now','localtime') WHERE username=?")) {
            ps.setString(1, username);
            ps.executeUpdate();
        }
        conn.commit();
    }

    public static boolean delete(Connection conn, String username) throws SQLException {
        boolean ok;
        try (PreparedStatement ps = conn.prepareStatement("DELETE FROM users WHERE username=?")) {
            ps.setString(1, username);
            ok = ps.executeUpdate() > 0;
        }
        deleteSessionsOf(conn, username);
        conn.commit();
        return ok;
    }

    /** 账号清单（供控制台/接口回显，绝不带 salt/hash）。 */
    public static List<Map<String, Object>> list(Connection conn) throws SQLException {
        List<Map<String, Object>> out = new ArrayList<>();
        try (PreparedStatement ps = conn.prepareStatement(
                "SELECT u.username, u.display_name, u.role, u.created_at, u.last_login_at, "
                        + "(SELECT COUNT(*) FROM user_sessions s WHERE s.username=u.username "
                        + " AND s.expires_at > datetime('now','localtime')) AS active_sessions "
                        + "FROM users u ORDER BY u.username");
             ResultSet rs = ps.executeQuery()) {
            while (rs.next()) {
                Map<String, Object> row = new LinkedHashMap<>();
                row.put("username", rs.getString("username"));
                row.put("display_name", rs.getString("display_name"));
                row.put("role", rs.getString("role"));
                row.put("created_at", rs.getString("created_at"));
                row.put("last_login_at", rs.getString("last_login_at"));
                row.put("active_sessions", rs.getLong("active_sessions"));
                out.add(row);
            }
        }
        return out;
    }

    // ---------------------------------------------------------------- 会话

    /** 新会话 token：32 字节随机数的 hex（64 字符），不放任何用户信息（不签名也不可猜）。 */
    public static String newToken() {
        byte[] buf = new byte[32];
        RANDOM.nextBytes(buf);
        StringBuilder sb = new StringBuilder(buf.length * 2);
        for (byte b : buf) {
            sb.append(Character.forDigit((b >> 4) & 0xf, 16)).append(Character.forDigit(b & 0xf, 16));
        }
        return sb.toString();
    }

    /** 建会话，返回过期时间字符串。 */
    public static String createSession(Connection conn, String token, String username, int ttlHours)
            throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement(
                "INSERT INTO user_sessions(token, username, expires_at, last_seen_at) "
                        + "VALUES (?,?, datetime('now','localtime', ?), datetime('now','localtime'))")) {
            ps.setString(1, token);
            ps.setString(2, username);
            ps.setString(3, "+" + Math.max(1, ttlHours) + " hours");
            ps.executeUpdate();
        }
        conn.commit();
        try (PreparedStatement ps = conn.prepareStatement(
                "SELECT expires_at FROM user_sessions WHERE token=?")) {
            ps.setString(1, token);
            try (ResultSet rs = ps.executeQuery()) {
                return rs.next() ? rs.getString(1) : null;
            }
        }
    }

    /** 有效会话 → 用户（顺带刷新 last_seen_at）；过期/不存在返回 null，并把过期行清掉。 */
    public static AuthUser resolveSession(Connection conn, String token) throws SQLException {
        if (token == null || token.trim().isEmpty()) {
            return null;
        }
        String username = null;
        String expiresAt = null;
        try (PreparedStatement ps = conn.prepareStatement(
                "SELECT s.username, s.expires_at FROM user_sessions s "
                        + "WHERE s.token=? AND s.expires_at > datetime('now','localtime')")) {
            ps.setString(1, token);
            try (ResultSet rs = ps.executeQuery()) {
                if (rs.next()) {
                    username = rs.getString(1);
                    expiresAt = rs.getString(2);
                }
            }
        }
        if (username == null) {
            deleteSession(conn, token);   // 过期行顺手清掉：表不会无限膨胀
            return null;
        }
        String displayName = null;
        String role = "user";
        try (PreparedStatement ps = conn.prepareStatement(
                "SELECT display_name, role FROM users WHERE username=?")) {
            ps.setString(1, username);
            try (ResultSet rs = ps.executeQuery()) {
                if (!rs.next()) {
                    deleteSession(conn, token);   // 账号已删除：会话立即失效
                    return null;
                }
                displayName = rs.getString(1);
                role = rs.getString(2);
            }
        }
        try (PreparedStatement ps = conn.prepareStatement(
                "UPDATE user_sessions SET last_seen_at=datetime('now','localtime') WHERE token=?")) {
            ps.setString(1, token);
            ps.executeUpdate();
        }
        conn.commit();
        return new AuthUser(username, displayName, role, expiresAt);
    }

    public static void deleteSession(Connection conn, String token) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement("DELETE FROM user_sessions WHERE token=?")) {
            ps.setString(1, token);
            ps.executeUpdate();
        }
        conn.commit();
    }

    public static void deleteSessionsOf(Connection conn, String username) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement("DELETE FROM user_sessions WHERE username=?")) {
            ps.setString(1, username);
            ps.executeUpdate();
        }
        conn.commit();
    }

    /** 清过期会话（启动期跑一次即可；不会误删有效会话）。 */
    public static int purgeExpired(Connection conn) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement(
                "DELETE FROM user_sessions WHERE expires_at <= datetime('now','localtime')")) {
            int n = ps.executeUpdate();
            conn.commit();
            return n;
        }
    }

    /** 用户名规范化：去空白、小写（"Admin" 与 "admin" 是同一个账号，避免看起来像重复建号）。 */
    public static String normUsername(String username) {
        return username == null ? "" : username.trim().toLowerCase();
    }

    /** 口令策略：最短 6 位（个人部署下不折腾复杂度规则，但绝不允许空口令）。 */
    public static String validatePassword(String password) {
        if (password == null || password.isEmpty()) {
            return "口令不能为空";
        }
        if (password.length() < 6) {
            return "口令至少 6 位";
        }
        if (password.getBytes(StandardCharsets.UTF_8).length > 200) {
            return "口令过长（≤200 字节）";
        }
        return null;
    }
}
