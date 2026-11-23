package com.ownrag.api;

import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.servlet.view.RedirectView;

/**
 * 控制台页面路由（Python 版 routes_ui.py 的对应物）：
 * 页面文件随 static/ 分发（零构建、零 CDN），/ui/{seg} 转发到 {seg}.html。
 * 页面只是壳——所有数据都从 /admin/* 与 /chat 拿，口径与线上链路一致。
 */
@Controller
public class UiController {

    /** 与 Python 版 PAGES 一致：路径段 → 页面文件（{seg}.html）；login 为 Java 侧新增的登录页。 */
    static final String[] PAGES = {"overview", "ingest", "review", "chat",
            "retrieve", "kb", "observe", "plan", "login"};

    @GetMapping("/")
    public RedirectView root() {
        return new RedirectView("/ui");
    }

    @GetMapping("/ui")
    public RedirectView ui() {
        return new RedirectView("/ui/overview");
    }
}
