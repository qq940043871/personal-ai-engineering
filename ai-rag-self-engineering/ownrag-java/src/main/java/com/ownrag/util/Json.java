package com.ownrag.util;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * JSON 序列化统一入口：ctx.data（步骤间黑板）落 tasks.state_json 检查点用。
 * 黑板里只放 JSON 原生类型（Map/List/String/Number/Boolean），跨步骤与检查点往返无损。
 */
public final class Json {

    public static final ObjectMapper MAPPER = new ObjectMapper();

    private Json() {
    }

    public static String write(Object value) {
        try {
            return MAPPER.writeValueAsString(value);
        } catch (Exception e) {
            throw new IllegalStateException("JSON 序列化失败: " + e.getMessage(), e);
        }
    }

    public static <T> T read(String text, Class<T> type) {
        try {
            return MAPPER.readValue(text, type);
        } catch (Exception e) {
            throw new IllegalStateException("JSON 反序列化失败: " + e.getMessage(), e);
        }
    }

    public static MapType mapType() {
        return new MapType();
    }

    /** Map<String,Object> 的 TypeReference 便捷持有。 */
    public static final class MapType extends TypeReference<java.util.LinkedHashMap<String, Object>> {
    }

    public static java.util.LinkedHashMap<String, Object> readMap(String text) {
        try {
            return MAPPER.readValue(text, new MapType());
        } catch (Exception e) {
            throw new IllegalStateException("JSON 反序列化失败: " + e.getMessage(), e);
        }
    }
}
