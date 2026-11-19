package com.ownrag.util;

import java.io.InputStream;
import java.security.MessageDigest;

/**
 * 内容指纹工具（个人知识库场景新增）：文件级 SHA-256（上传幂等）与
 * 块级去重 hash（跨文档近重复）。归一化只折叠空白——正文实质相同才算重复。
 */
public final class Hashes {

    private Hashes() {
    }

    /** 流式 SHA-256：上传边落盘边算，不二次读文件。返回 64 位小写 hex。 */
    public static String sha256Hex(InputStream in) throws Exception {
        MessageDigest md = MessageDigest.getInstance("SHA-256");
        byte[] buf = new byte[8192];
        int n;
        while ((n = in.read(buf)) > 0) {
            md.update(buf, 0, n);
        }
        return hex(md.digest());
    }

    public static String sha256Hex(byte[] bytes) throws Exception {
        MessageDigest md = MessageDigest.getInstance("SHA-256");
        return hex(md.digest(bytes));
    }

    /** 块去重 hash：折叠全部空白为单空格后 SHA-256。块头注入文本参与 hash（同头不同正文不误伤）。 */
    public static String chunkHash(String text) {
        String normalized = text == null ? "" : text.replaceAll("\\s+", " ").trim();
        try {
            return sha256Hex(normalized.getBytes(java.nio.charset.StandardCharsets.UTF_8));
        } catch (Exception e) {
            // SHA-256 在 JVM 内恒可用，失败=环境异常，按工程口径直接爆
            throw new IllegalStateException("SHA-256 不可用", e);
        }
    }

    private static String hex(byte[] bytes) {
        StringBuilder sb = new StringBuilder(bytes.length * 2);
        for (byte b : bytes) {
            sb.append(Character.forDigit((b >> 4) & 0xF, 16)).append(Character.forDigit(b & 0xF, 16));
        }
        return sb.toString();
    }
}
