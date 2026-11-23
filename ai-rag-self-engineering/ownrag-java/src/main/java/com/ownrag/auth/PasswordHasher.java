package com.ownrag.auth;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;

import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;

/**
 * 口令派生（PBKDF2-HmacSHA256 + 随机盐），只用 JDK，不引第三方加密库。
 *
 * 口径：
 *   - 库里**只存** 盐（Base64）与派生值（Base64），不存明文、不存可逆加密；
 *   - 每次建号/改密都换新盐（同口令在不同账号下派生值不同，彩虹表无效）；
 *   - 校验用 {@link MessageDigest#isEqual} 做定长比较，避免按字节短路泄露前缀。
 *
 * 迭代次数定在 12 万：个人设备的登录频率下 ~60ms，可接受的抗爆破成本；
 * 换值会让老口令全部失效，改这里必须同时提供改密通道（控制台 /auth/password）。
 */
public final class PasswordHasher {

    private static final String ALGORITHM = "PBKDF2WithHmacSHA256";
    private static final int ITERATIONS = 120_000;
    private static final int KEY_BITS = 256;
    private static final int SALT_BYTES = 16;

    private static final SecureRandom RANDOM = new SecureRandom();

    private PasswordHasher() {
    }

    /** 新盐（Base64，16 字节）。 */
    public static String newSalt() {
        byte[] salt = new byte[SALT_BYTES];
        RANDOM.nextBytes(salt);
        return Base64.getEncoder().encodeToString(salt);
    }

    /** 口令 + 盐 → 派生值（Base64）。 */
    public static String hash(String password, String saltBase64) {
        if (password == null || saltBase64 == null) {
            throw new IllegalArgumentException("口令与盐不能为空");
        }
        try {
            PBEKeySpec spec = new PBEKeySpec(password.toCharArray(),
                    Base64.getDecoder().decode(saltBase64), ITERATIONS, KEY_BITS);
            byte[] key = SecretKeyFactory.getInstance(ALGORITHM).generateSecret(spec).getEncoded();
            return Base64.getEncoder().encodeToString(key);
        } catch (Exception e) {
            // 派生算法缺失属于运行环境问题：直接抛出，绝不"降级成明文比较"
            throw new IllegalStateException("口令派生失败：" + e.getMessage(), e);
        }
    }

    /** 定长比较校验；salt/hash 为空一律 false（防止缺列的老行被当成"任意口令可登"）。 */
    public static boolean verify(String password, String saltBase64, String hashBase64) {
        if (password == null || saltBase64 == null || saltBase64.isEmpty()
                || hashBase64 == null || hashBase64.isEmpty()) {
            return false;
        }
        try {
            String actual = hash(password, saltBase64);
            return MessageDigest.isEqual(actual.getBytes(StandardCharsets.UTF_8),
                    hashBase64.getBytes(StandardCharsets.UTF_8));
        } catch (RuntimeException e) {
            return false;
        }
    }
}
