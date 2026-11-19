package com.ownrag.core;

import java.sql.Connection;
import java.util.LinkedHashMap;
import java.util.Map;

import com.ownrag.config.Settings;

/**
 * 步骤上下文（与 Python 版 StepContext dataclass 同构）：
 * data = 步骤间黑板（state 外置：每步 checkpoint 到任务表，中断可续跑）。
 * 黑板只放 JSON 原生类型（Map/List/String/Number/Boolean），保证 state_json 往返无损。
 */
public class StepContext {

    public final String docId;
    public final String traceId;
    public final String kb;
    public final Connection conn;
    public final Settings settings;
    public final Map<String, Object> data = new LinkedHashMap<>();

    public StepContext(String docId, String traceId, String kb, Connection conn, Settings settings) {
        this.docId = docId;
        this.traceId = traceId;
        this.kb = kb;
        this.conn = conn;
        this.settings = settings;
    }
}
