package com.ownrag.auth;

import java.util.LinkedHashMap;
import java.util.Map;

/** 当前登录用户（请求级视图对象，不含任何口令材料）。 */
public class AuthUser {

    public final String username;
    public final String displayName;
    public final String role;
    /** 会话过期时间（本地时间字符串，用于前端提示"登录到几点"）。 */
    public final String expiresAt;

    public AuthUser(String username, String displayName, String role, String expiresAt) {
        this.username = username;
        this.displayName = displayName;
        this.role = role;
        this.expiresAt = expiresAt;
    }

    public boolean isAdmin() {
        return "admin".equalsIgnoreCase(role == null ? "" : role);
    }

    /** 对外 JSON（/auth/me、登录响应）：**永不含** token/盐/派生值。 */
    public Map<String, Object> toJson() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("logged_in", true);
        m.put("username", username);
        m.put("display_name", displayName == null || displayName.isEmpty() ? username : displayName);
        m.put("role", role == null || role.isEmpty() ? "user" : role);
        m.put("expires_at", expiresAt);
        m.put("access", "全部文档（含需登录）");
        return m;
    }
}
