package com.ownrag.auth;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import javax.servlet.http.HttpServletRequest;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import com.ownrag.config.Settings;
import com.ownrag.core.Db;

/**
 * 登录与文档权限的唯一入口（控制器只调这里，不自己比对口令、不自己拼权限 SQL）。
 *
 * 三件事：
 *   ① 会话：Cookie（HttpOnly，Path=/）里的随机 token → user_sessions 表 → {@link AuthUser}。
 *      token 落库而不是放内存：页面跳转、重启、并发请求看到的登录态是**同一个事实**。
 *   ② 检索过滤：未登录时给 metadataFilter 打 `public_only` 标记，双通道在 SQL 层过滤
 *      （先过滤后召回，过滤责任不进 Prompt——见 {@link com.ownrag.index.ChunkStore#filterSql}）。
 *   ③ 文档级校验：原件、分块、复核、状态等按 docId 取内容的接口统一走 {@link #canRead}，
 *      拒绝时给一句能照做的提示（"登录后访问" + 登录地址），而不是干巴巴的 403。
 *
 * 首次启动引导：库里一个用户都没有时建一个默认管理员（OWNRAG_ADMIN_USER/PASSWORD，
 * 缺省 admin/ownrag），并在日志里明确喊一次——默认口令只用于"先把门装起来"，不是终点。
 */
@Component
public class AuthService {

    private static final Logger log = LoggerFactory.getLogger(AuthService.class);

    public static final String COOKIE = "ownrag_session";
    public static final String DEFAULT_ADMIN = "admin";
    public static final String DEFAULT_PASSWORD = "ownrag";

    /** 登录失败闸门：同一用户名 60 秒内失败 8 次即短时拒绝（内存计数，重启即清）。 */
    private static final int MAX_FAILS = 8;
    private static final long FAIL_WINDOW_MS = 60_000L;

    private final Settings settings;
    private final Map<String, long[]> failures = new ConcurrentHashMap<>();

    public AuthService(Settings settings) {
        this.settings = settings;
    }

    // ---------------------------------------------------------------- 会话解析

    /** 当前用户；未登录/会话过期返回 null（一次性读 Cookie，不做缓存，避免登出后仍显示已登录）。 */
    public AuthUser currentUser(HttpServletRequest request) {
        return resolveToken(tokenOf(request));
    }

    /** Cookie 名固定；同时接受 `X-Ownrag-Token`（curl / 脚本联调方便，不改变浏览器路径）。 */
    public String tokenOf(HttpServletRequest request) {
        if (request == null) {
            return null;
        }
        javax.servlet.http.Cookie[] cookies = request.getCookies();
        if (cookies != null) {
            for (javax.servlet.http.Cookie c : cookies) {
                if (COOKIE.equals(c.getName()) && c.getValue() != null && !c.getValue().isEmpty()) {
                    return c.getValue();
                }
            }
        }
        String header = request.getHeader("X-Ownrag-Token");
        return header == null || header.trim().isEmpty() ? null : header.trim();
    }

    public AuthUser resolveToken(String token) {
        if (token == null || token.isEmpty()) {
            return null;
        }
        try (Connection conn = Db.connect(settings.getDbPath())) {
            return UserStore.resolveSession(conn, token);
        } catch (Exception e) {
            log.warn("[auth] 会话解析失败（按未登录处理）：{}", e.getMessage());
            return null;
        }
    }

    // ---------------------------------------------------------------- 登录 / 登出

    /** 登录结果：成功带 token 与用户；失败只有一句人话（不区分"用户不存在/口令错"，避免枚举账号）。 */
    public static class Outcome {
        public final boolean ok;
        public final String message;
        public final String token;
        public final AuthUser user;

        private Outcome(boolean ok, String message, String token, AuthUser user) {
            this.ok = ok;
            this.message = message;
            this.token = token;
            this.user = user;
        }

        static Outcome fail(String msg) {
            return new Outcome(false, msg, null, null);
        }

        static Outcome success(String token, AuthUser user) {
            return new Outcome(true, "", token, user);
        }
    }

    public Outcome login(String rawUsername, String password) {
        String username = UserStore.normUsername(rawUsername);
        if (username.isEmpty() || password == null || password.isEmpty()) {
            return Outcome.fail("请输入用户名与口令");
        }
        if (throttled(username)) {
            return Outcome.fail("登录失败次数过多，请 1 分钟后再试");
        }
        try (Connection conn = Db.connect(settings.getDbPath())) {
            Map<String, Object> row = UserStore.find(conn, username);
            if (row == null) {
                // 用户不存在也照常算一次派生：响应时间不泄露"这个名字存在与否"
                PasswordHasher.hash(password, PasswordHasher.newSalt());
                recordFailure(username);
                return Outcome.fail("用户名或口令不正确");
            }
            boolean okPwd = PasswordHasher.verify(password,
                    str(row.get("salt")), str(row.get("password_hash")));
            if (!okPwd) {
                recordFailure(username);
                return Outcome.fail("用户名或口令不正确");
            }
            failures.remove(username);
            String token = UserStore.newToken();
            String expiresAt = UserStore.createSession(conn, token, username, UserStore.SESSION_TTL_HOURS);
            UserStore.touchLogin(conn, username);
            UserStore.purgeExpired(conn);
            AuthUser user = new AuthUser(username, str(row.get("display_name")), str(row.get("role")), expiresAt);
            log.info("[auth] 登录成功：user={} 会话到期={}", username, expiresAt);
            return Outcome.success(token, user);
        } catch (Exception e) {
            log.error("[auth] 登录异常", e);
            return Outcome.fail("登录服务异常：" + e.getMessage());
        }
    }

    public void logout(String token) {
        if (token == null || token.isEmpty()) {
            return;
        }
        try (Connection conn = Db.connect(settings.getDbPath())) {
            UserStore.deleteSession(conn, token);
        } catch (Exception e) {
            log.warn("[auth] 登出失败（会话可能已过期）：{}", e.getMessage());
        }
    }

    private boolean throttled(String username) {
        long[] f = failures.get(username);
        if (f == null) {
            return false;
        }
        if (System.currentTimeMillis() - f[1] > FAIL_WINDOW_MS) {
            failures.remove(username);
            return false;
        }
        return f[0] >= MAX_FAILS;
    }

    private void recordFailure(String username) {
        failures.compute(username, (k, v) -> {
            long now = System.currentTimeMillis();
            if (v == null || now - v[1] > FAIL_WINDOW_MS) {
                return new long[]{1, now};
            }
            return new long[]{v[0] + 1, v[1]};
        });
    }

    // ---------------------------------------------------------------- 账号管理

    /** 建号/改密（控制台用）：需要已登录调用方在控制器层把关。 */
    public void upsertUser(String rawUsername, String password, String displayName, String role)
            throws Exception {
        String username = UserStore.normUsername(rawUsername);
        if (username.isEmpty()) {
            throw new IllegalArgumentException("用户名不能为空");
        }
        String bad = UserStore.validatePassword(password);
        if (bad != null) {
            throw new IllegalArgumentException(bad);
        }
        String salt = PasswordHasher.newSalt();
        String hash = PasswordHasher.hash(password, salt);
        try (Connection conn = Db.connect(settings.getDbPath())) {
            if (UserStore.find(conn, username) != null) {
                UserStore.updatePassword(conn, username, hash, salt);
            } else {
                UserStore.create(conn, username, hash, salt, displayName, role);
            }
        }
    }

    public List<Map<String, Object>> listUsers() throws Exception {
        try (Connection conn = Db.connect(settings.getDbPath())) {
            return UserStore.list(conn);
        }
    }

    public boolean deleteUser(String username) throws Exception {
        try (Connection conn = Db.connect(settings.getDbPath())) {
            return UserStore.delete(conn, UserStore.normUsername(username));
        }
    }

    // ---------------------------------------------------------------- 文档权限

    /**
     * 未登录 → 给过滤条件打上 `public_only`（检索层在 SQL 里按 documents.access_level 过滤）。
     * 已登录 → 原样返回（可查全部文档）。
     */
    public static Map<String, Object> accessFilter(Map<String, Object> filter, boolean loggedIn) {
        if (loggedIn) {
            return filter;
        }
        Map<String, Object> f = filter == null ? new LinkedHashMap<String, Object>()
                : new LinkedHashMap<>(filter);
        f.put("public_only", Boolean.TRUE);
        return f;
    }

    /** 某文档的权限级别；文档不存在返回 null（由调用方按 404 处理）。 */
    public String accessLevelOf(String docId) {
        try (Connection conn = Db.connect(settings.getDbPath());
             PreparedStatement ps = conn.prepareStatement(
                     "SELECT access_level FROM documents WHERE doc_id=?")) {
            ps.setString(1, docId);
            try (ResultSet rs = ps.executeQuery()) {
                return rs.next() ? AccessLevel.normalize(rs.getString(1)) : null;
            }
        } catch (Exception e) {
            return null;
        }
    }

    /** 能否读这篇文档：已登录一律可以；未登录只有 public（含"documents 里没有这行"的存量数据）。 */
    public boolean canRead(String docId, boolean loggedIn) {
        if (loggedIn) {
            return true;
        }
        return !AccessLevel.isProtected(accessLevelOf(docId));
    }

    /** 未登录访问受限文档时的统一话术（能照着做，而不是只说"禁止"）。 */
    public static String deniedMessage(String docId) {
        return "文档 " + docId + " 的访问权限是「需登录」：未登录只能查看公开文档。"
                + "请先登录 /ui/login?next=" + "/ui/kb?doc=" + docId + " ，登录后可查询与访问全部文档。";
    }

    /**
     * 改文档权限级别（写入 documents.access_level）。返回 false = 文档不存在。
     * chunks 不冗余这一列：过滤走 documents 子查询，改一行即对检索、原件、分块三处同时生效。
     */
    public boolean setAccessLevel(String docId, String level) throws Exception {
        String normalized = AccessLevel.normalize(level);
        try (Connection conn = Db.connect(settings.getDbPath())) {
            try (PreparedStatement ps = conn.prepareStatement(
                    "UPDATE documents SET access_level=?, updated_at=datetime('now','localtime') "
                            + "WHERE doc_id=?")) {
                ps.setString(1, normalized);
                ps.setString(2, docId);
                int n = ps.executeUpdate();
                conn.commit();
                return n > 0;
            }
        }
    }

    /** 统计给定库里的受限文档数（未登录时给用户一句"还有 N 篇没参与检索"的实话）。 */
    public long countProtected(List<String> kbs) {
        StringBuilder sql = new StringBuilder(
                "SELECT COUNT(*) FROM documents WHERE COALESCE(access_level,'public')<>'public'");
        List<String> args = new ArrayList<>();
        if (kbs != null && !kbs.isEmpty()) {
            sql.append(" AND kb IN (");
            for (int i = 0; i < kbs.size(); i++) {
                sql.append(i == 0 ? "?" : ",?");
                args.add(kbs.get(i));
            }
            sql.append(")");
        }
        try (Connection conn = Db.connect(settings.getDbPath());
             PreparedStatement ps = conn.prepareStatement(sql.toString())) {
            for (int i = 0; i < args.size(); i++) {
                ps.setString(i + 1, args.get(i));
            }
            try (ResultSet rs = ps.executeQuery()) {
                return rs.next() ? rs.getLong(1) : 0;
            }
        } catch (Exception e) {
            return 0;
        }
    }

    // ---------------------------------------------------------------- 首启引导

    /**
     * 首个用户引导（由 StartupCheck 在**建表之后**调用，不能放 @PostConstruct：
     * ApplicationRunner 才保证 DDL 已执行）。
     */
    public static void ensureDefaultAdmin(Settings settings) {
        String username = UserStore.normUsername(
                envOr("OWNRAG_ADMIN_USER", DEFAULT_ADMIN));
        String password = envOr("OWNRAG_ADMIN_PASSWORD", DEFAULT_PASSWORD);
        try (Connection conn = Db.connect(settings.getDbPath())) {
            if (UserStore.count(conn) > 0) {
                UserStore.purgeExpired(conn);
                return;
            }
            String salt = PasswordHasher.newSalt();
            String hash = PasswordHasher.hash(password, salt);
            UserStore.create(conn, username, hash, salt, "管理员", "admin");
            log.warn("[auth] 已创建默认管理员 '{}'（口令{}）——请在 /ui/login 登录后到控制台改密，"
                            + "或用环境变量 OWNRAG_ADMIN_USER/OWNRAG_ADMIN_PASSWORD 指定",
                    username, DEFAULT_PASSWORD.equals(password) ? "为默认值 " + DEFAULT_PASSWORD : "取自环境变量");
        } catch (Exception e) {
            log.error("[auth] 默认账号初始化失败（登录功能将不可用，请检查 users 表）：{}", e.getMessage());
        }
    }

    private static String envOr(String key, String def) {
        String v = System.getenv(key);
        return v == null || v.trim().isEmpty() ? def : v.trim();
    }

    private static String str(Object o) {
        return o == null ? null : String.valueOf(o);
    }
}
