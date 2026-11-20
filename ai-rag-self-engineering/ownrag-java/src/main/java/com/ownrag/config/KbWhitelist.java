package com.ownrag.config;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.util.LinkedHashSet;
import java.util.Set;

import com.ownrag.core.Db;

/**
 * 知识库白名单的运行时视图 = apps.yaml 声明 ∪ kb_registry 登记。
 *
 * apps.yaml 仍然是「声明即收口」的基础口径；控制台新建的库写进 kb_registry，
 * 上传与配置回显统一走这里，新增库不必再改配置重启。
 */
public final class KbWhitelist {

    private KbWhitelist() {
    }

    public static Set<String> all(Settings settings) throws Exception {
        Set<String> kbs = new LinkedHashSet<>(settings.getKnownKbs());
        try (Connection conn = Db.connect(settings.getDbPath());
             PreparedStatement ps = conn.prepareStatement("SELECT kb FROM kb_registry ORDER BY kb");
             ResultSet rs = ps.executeQuery()) {
            while (rs.next()) {
                kbs.add(rs.getString("kb"));
            }
        }
        return kbs;
    }
}
