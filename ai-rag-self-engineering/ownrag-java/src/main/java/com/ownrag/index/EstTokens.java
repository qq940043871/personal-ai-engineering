package com.ownrag.index;

/**
 * Token 粗估（预算口径）：CJK 一字≈1 token，其余 4 字符≈1 token。
 * 不追求精确分词——预算只需同口径可比。切分与上下文裁剪共用同一函数，
 * 避免"切分按一套口径、预算按另一套"的两本账。
 */
public final class EstTokens {

    private EstTokens() {
    }

    public static int est(String text) {
        if (text == null || text.isEmpty()) {
            return 0;
        }
        int cjk = 0;
        for (int i = 0; i < text.length(); i++) {
            char ch = text.charAt(i);
            if (ch >= '\u4e00' && ch <= '\u9fff') {
                cjk++;
            }
        }
        return cjk + (text.length() - cjk) / 4;
    }
}
