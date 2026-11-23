package com.ownrag.auth;

import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.Set;

/**
 * 文档访问权限级别（documents.access_level 的取值域）。
 *
 * 只有两档，刻意不设第三档：
 *   public    —— 公开：任何访客（未登录）都能检索、看分块、看原件；
 *   protected —— 需登录：只有持有有效会话的用户能检索与访问。
 *
 * 与 sensitivity（public/internal/restricted）是两件不同的事：
 *   sensitivity 描述"内容能不能外发"，过滤是**用户自己选的**检索条件；
 *   access_level 描述"谁能看"，过滤是**服务端强制的**，不随请求参数改变。
 * 两者混用会出现"用户把过滤条件清空就绕过了权限"的漏洞，所以分列分道。
 */
public final class AccessLevel {

    public static final String PUBLIC = "public";
    public static final String PROTECTED = "protected";

    /** 上传/改权限时可接受的取值。 */
    public static final Set<String> LEVELS = new LinkedHashSet<>(Arrays.asList(PUBLIC, PROTECTED));

    private AccessLevel() {
    }

    /** 归一化：空值/未知值一律按 public（存量文档不因缺列而消失）；仅 protected 才是受限。 */
    public static String normalize(String level) {
        if (level == null) {
            return PUBLIC;
        }
        String v = level.trim().toLowerCase();
        return PROTECTED.equals(v) ? PROTECTED : PUBLIC;
    }

    public static boolean isProtected(String level) {
        return PROTECTED.equals(normalize(level));
    }

    /** 中文展示名（错误提示、页面 chip 共用一套说法）。 */
    public static String label(String level) {
        return isProtected(level) ? "需登录" : "公开";
    }
}
