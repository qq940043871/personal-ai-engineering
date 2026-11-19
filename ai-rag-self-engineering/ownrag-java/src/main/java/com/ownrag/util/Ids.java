package com.ownrag.util;

import java.util.UUID;

/** 短随机 ID：doc_id / task_id / trace_id 统一口径（uuid hex 12，与 Python 版一致）。 */
public final class Ids {

    private Ids() {
    }

    public static String short12() {
        return UUID.randomUUID().toString().replace("-", "").substring(0, 12);
    }
}
