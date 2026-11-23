package com.ownrag.api;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;

import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import com.ownrag.auth.AuthService;
import com.ownrag.auth.AuthUser;
import com.ownrag.auth.UserStore;

/**
 * 登录接口（会话走 HttpOnly Cookie，前端不接触 token）。
 *
 *   POST /auth/login     {username, password} → 下发 Cookie + 用户信息；失败 401（同一句"用户名或口令不正确"）
 *   POST /auth/logout    清 Cookie + 删会话（服务端删行，不只是让浏览器忘掉）
 *   GET  /auth/me        当前登录态：未登录也返回 200 + logged_in=false（页面据此提示"仅公开文档"）
 *   POST /auth/password  自助改密（需登录，校验原口令；改完旧会话全部失效，需要重新登录）
 *   GET  /auth/users     账号清单（需登录）
 *   POST /auth/users     建号/重置口令（需登录且 admin）
 *   DELETE /auth/users/{u} 删号（需登录且 admin，不能删自己）
 *
 * 为什么 /auth/me 用 200 而不是 401：它是"读状态"，每个页面 boot() 都会调一次；
 * 401 会让控制台每页都弹一次错误提示，也不利于"未登录也能用（只看公开文档）"的产品口径。
 */
@RestController
public class AuthController {

    private final AuthService auth;

    public AuthController(AuthService auth) {
        this.auth = auth;
    }

    public static class LoginIn {
        public String username;
        public String password;
    }

    public static class PasswordIn {
        public String old_password;
        public String new_password;
    }

    public static class UserIn {
        public String username;
        public String password;
        public String display_name;
        public String role;
    }

    @PostMapping("/auth/login")
    public Map<String, Object> login(@RequestBody LoginIn body, HttpServletResponse response) {
        if (body == null || body.username == null || body.username.trim().isEmpty()) {
            throw new ApiError(422, "请输入用户名");
        }
        if (body.password == null || body.password.isEmpty()) {
            throw new ApiError(422, "请输入口令");
        }
        AuthService.Outcome out = auth.login(body.username, body.password);
        if (!out.ok) {
            // 失败原因只有一句人话：不区分"用户不存在"与"口令错"，避免账号枚举
            throw new ApiError(out.message.contains("次数过多") ? 429 : 401, out.message);
        }
        setSessionCookie(response, out.token, UserStore.SESSION_TTL_HOURS * 3600);
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("ok", true);
        resp.put("message", "登录成功");
        resp.put("user", out.user.toJson());
        return resp;
    }

    @PostMapping("/auth/logout")
    public Map<String, Object> logout(HttpServletRequest request, HttpServletResponse response) {
        auth.logout(auth.tokenOf(request));
        setSessionCookie(response, "", 0);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("ok", true);
        out.put("message", "已退出登录，接下来只能查看公开文档");
        return out;
    }

    @GetMapping("/auth/me")
    public Map<String, Object> me(HttpServletRequest request) {
        AuthUser user = auth.currentUser(request);
        if (user != null) {
            return user.toJson();
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("logged_in", false);
        out.put("username", null);
        out.put("access", "仅公开文档");
        out.put("login_url", "/ui/login");
        return out;
    }

    @PostMapping("/auth/password")
    public Map<String, Object> changePassword(@RequestBody PasswordIn body, HttpServletRequest request) {
        AuthUser user = auth.currentUser(request);
        if (user == null) {
            throw new ApiError(403, "需登录后才能改密：请先到 /ui/login 登录");
        }
        if (body == null || body.old_password == null || body.new_password == null) {
            throw new ApiError(422, "原口令与新口令都不能为空");
        }
        // 原口令校验复用登录路径：错误即拒绝（不允许"已登录就能改别人的密码"这种模糊口径）
        AuthService.Outcome check = auth.login(user.username, body.old_password);
        if (!check.ok) {
            throw new ApiError(401, "原口令不正确");
        }
        String bad = UserStore.validatePassword(body.new_password);
        if (bad != null) {
            throw new ApiError(422, bad);
        }
        try {
            auth.upsertUser(user.username, body.new_password, user.displayName, user.role);
        } catch (Exception e) {
            throw new ApiError(500, "改密失败：" + e.getMessage());
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("ok", true);
        out.put("message", "口令已更新，原会话全部失效，请用新口令重新登录");
        return out;
    }

    @GetMapping("/auth/users")
    public Map<String, Object> users(HttpServletRequest request) {
        if (auth.currentUser(request) == null) {
            throw new ApiError(403, "需登录后才能查看账号清单：请先到 /ui/login 登录");
        }
        try {
            List<Map<String, Object>> rows = auth.listUsers();
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("total", rows.size());
            out.put("users", rows);
            return out;
        } catch (Exception e) {
            throw new ApiError(500, "读取账号失败：" + e.getMessage());
        }
    }

    @PostMapping("/auth/users")
    public Map<String, Object> upsertUser(@RequestBody UserIn body, HttpServletRequest request) {
        AuthUser me = requireAdmin(request);
        if (body == null || body.username == null || body.username.trim().isEmpty()) {
            throw new ApiError(422, "用户名不能为空");
        }
        if (body.password == null || body.password.isEmpty()) {
            throw new ApiError(422, "口令不能为空");
        }
        try {
            auth.upsertUser(body.username, body.password, body.display_name,
                    body.role == null || body.role.trim().isEmpty() ? "user" : body.role.trim());
        } catch (IllegalArgumentException e) {
            throw new ApiError(422, e.getMessage());
        } catch (Exception e) {
            throw new ApiError(500, "建号失败：" + e.getMessage());
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("ok", true);
        out.put("username", UserStore.normUsername(body.username));
        out.put("by", me.username);
        out.put("message", "已保存（同名账号视为重置口令）");
        return out;
    }

    @DeleteMapping("/auth/users/{username}")
    public Map<String, Object> deleteUser(@PathVariable String username, HttpServletRequest request) {
        AuthUser me = requireAdmin(request);
        if (UserStore.normUsername(username).equals(me.username)) {
            throw new ApiError(422, "不能删除当前登录账号");
        }
        try {
            if (!auth.deleteUser(username)) {
                throw new ApiError(404, "账号不存在：" + username);
            }
        } catch (ApiError e) {
            throw e;
        } catch (Exception e) {
            throw new ApiError(500, "删号失败：" + e.getMessage());
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("ok", true);
        out.put("username", UserStore.normUsername(username));
        return out;
    }

    private AuthUser requireAdmin(HttpServletRequest request) {
        AuthUser me = auth.currentUser(request);
        if (me == null) {
            throw new ApiError(403, "需登录后才能管理账号：请先到 /ui/login 登录");
        }
        if (!me.isAdmin()) {
            throw new ApiError(403, "只有 admin 角色可以管理账号（当前：" + me.username + "）");
        }
        return me;
    }

    /**
     * 手工拼 Set-Cookie 而不是 servlet Cookie：需要 SameSite（javax.servlet 4 没有 setSameSite），
     * Lax + HttpOnly = 跨站表单不会带着会话提交，页面内跳转与 fetch 正常携带。
     */
    private static void setSessionCookie(HttpServletResponse response, String token, int maxAgeSeconds) {
        StringBuilder sb = new StringBuilder();
        sb.append(AuthService.COOKIE).append('=').append(token == null ? "" : token);
        sb.append("; Path=/; HttpOnly; SameSite=Lax; Max-Age=").append(Math.max(0, maxAgeSeconds));
        response.addHeader("Set-Cookie", sb.toString());
    }

    /** 供其它控制器复用的话术拼装（登录页地址带上回跳目标）。 */
    static String loginHint(String nextPath) {
        try {
            return "/ui/login?next=" + java.net.URLEncoder.encode(
                    nextPath == null ? "/ui/overview" : nextPath, "UTF-8");
        } catch (java.io.UnsupportedEncodingException e) {
            return "/ui/login";
        }
    }
}
