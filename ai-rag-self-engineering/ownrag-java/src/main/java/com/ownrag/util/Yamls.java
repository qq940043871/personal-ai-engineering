package com.ownrag.util;

import java.util.List;
import java.util.Map;

import org.yaml.snakeyaml.Yaml;

/**
 * YAML 加载与安全取值：配置文件解析为 Map 后的导航助手。
 * 与 Python 版直接 dict 访问 + or 默认值的风格对齐，避免到处 NPE 判断。
 */
public final class Yamls {

    private Yamls() {
    }

    /** 加载 YAML 为有序 Map；空文档返回空 Map。 */
    @SuppressWarnings("unchecked")
    public static java.util.LinkedHashMap<String, Object> load(String path) {
        try (java.io.InputStream in = open(path)) {
            if (in == null) {
                throw new IllegalStateException("配置文件不存在: " + path);
            }
            Object root = new Yaml().load(in);
            return root instanceof Map ? new java.util.LinkedHashMap<>((Map<String, Object>) root) : new java.util.LinkedHashMap<>();
        } catch (IllegalStateException e) {
            throw e;
        } catch (Exception e) {
            throw new IllegalStateException("配置文件解析失败: " + path + " - " + e.getMessage(), e);
        }
    }

    /** classpath 优先，文件系统路径兜底（便于免重启改配置）。 */
    private static java.io.InputStream open(String path) throws java.io.IOException {
        if (path.startsWith("classpath:")) {
            // Class.getResourceAsStream 需要绝对路径（前导 /），否则按包相对路径解析必为 null
            return Yamls.class.getResourceAsStream("/" + path.substring("classpath:".length()));
        }
        java.io.File f = new java.io.File(path);
        if (f.exists()) {
            return new java.io.FileInputStream(f);
        }
        String cp = "/" + path;
        return Yamls.class.getResourceAsStream(cp);
    }

    public static String str(Map<String, Object> map, String key, String def) {
        Object v = map == null ? null : map.get(key);
        if (v == null) {
            return def;
        }
        String s = String.valueOf(v).trim();
        return s.isEmpty() ? def : s;
    }

    public static String rawStr(Map<String, Object> map, String key, String def) {
        Object v = map == null ? null : map.get(key);
        return v == null ? def : String.valueOf(v);
    }

    public static int intVal(Map<String, Object> map, String key, int def) {
        Object v = map == null ? null : map.get(key);
        if (v instanceof Number) {
            return ((Number) v).intValue();
        }
        if (v instanceof String && !((String) v).trim().isEmpty()) {
            try {
                return Integer.parseInt(((String) v).trim());
            } catch (NumberFormatException ignored) {
                return def;
            }
        }
        return def;
    }

    public static double doubleVal(Map<String, Object> map, String key, double def) {
        Object v = map == null ? null : map.get(key);
        if (v instanceof Number) {
            return ((Number) v).doubleValue();
        }
        if (v instanceof String && !((String) v).trim().isEmpty()) {
            try {
                return Double.parseDouble(((String) v).trim());
            } catch (NumberFormatException ignored) {
                return def;
            }
        }
        return def;
    }

    public static boolean bool(Map<String, Object> map, String key, boolean def) {
        Object v = map == null ? null : map.get(key);
        if (v instanceof Boolean) {
            return (Boolean) v;
        }
        if (v instanceof String) {
            return Boolean.parseBoolean(((String) v).trim());
        }
        return def;
    }

    @SuppressWarnings("unchecked")
    public static Map<String, Object> map(Map<String, Object> map, String key) {
        Object v = map == null ? null : map.get(key);
        return v instanceof Map ? (Map<String, Object>) v : null;
    }

    @SuppressWarnings("unchecked")
    public static List<Object> list(Map<String, Object> map, String key) {
        Object v = map == null ? null : map.get(key);
        return v instanceof List ? (List<Object>) v : null;
    }

    public static List<String> strList(Map<String, Object> map, String key) {
        List<Object> raw = list(map, key);
        if (raw == null) {
            return new java.util.ArrayList<>();
        }
        List<String> out = new java.util.ArrayList<>();
        for (Object o : raw) {
            if (o != null) {
                out.add(String.valueOf(o));
            }
        }
        return out;
    }
}
