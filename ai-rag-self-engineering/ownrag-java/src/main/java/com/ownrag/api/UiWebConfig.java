package com.ownrag.api;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.ViewControllerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * /ui/{seg} → {seg}.html 的静态转发（页面文件在 classpath:/static）。
 * 与 Python 版 routes_ui 的 /ui/{page} URL 结构保持一致，前端零改动迁移。
 * 必须用 forward 而非 redirect：redirect 会丢 query（如 /ui/review?doc=xxx 的定位参数）。
 */
@Configuration
public class UiWebConfig implements WebMvcConfigurer {

    @Override
    public void addViewControllers(ViewControllerRegistry registry) {
        for (String page : new String[]{"overview", "ingest", "review", "chat",
                "retrieve", "kb", "observe", "plan"}) {
            registry.addViewController("/ui/" + page).setViewName("forward:/" + page + ".html");
        }
    }

    @Override
    public void addResourceHandlers(org.springframework.web.servlet.config.annotation.ResourceHandlerRegistry registry) {
        // 前端沿用 Python 版路由 /ui/assets/**（app.js/menu.js/md.js/katex/）；
        // 默认静态映射落在 /assets/**，这里把 /ui/assets/** 也指到同一目录。
        // no-store：改前端资源后刷新即生效（浏览器曾缓存旧 md.js 导致修复不生效）
        registry.addResourceHandler("/ui/assets/**")
                .addResourceLocations("classpath:/static/assets/")
                .setCacheControl(org.springframework.http.CacheControl.noStore());
    }
}
