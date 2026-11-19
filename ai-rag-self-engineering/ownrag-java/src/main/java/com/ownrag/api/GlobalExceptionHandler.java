package com.ownrag.api;

import java.util.LinkedHashMap;
import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.multipart.MaxUploadSizeExceededException;

/** 统一错误响应：ApiError → {status, detail}，与 Python 版 HTTPException(4xx, detail) 契约对齐。 */
@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(ApiError.class)
    public ResponseEntity<Map<String, Object>> apiError(ApiError e) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("detail", e.getMessage());
        return ResponseEntity.status(e.status).body(body);
    }

    @ExceptionHandler(MaxUploadSizeExceededException.class)
    public ResponseEntity<Map<String, Object>> tooLarge(MaxUploadSizeExceededException e) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("detail", "上传超过容器上限（spring.servlet.multipart.max-file-size）");
        return ResponseEntity.status(413).body(body);
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Map<String, Object>> badRequest(IllegalArgumentException e) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("detail", e.getMessage());
        return ResponseEntity.status(400).body(body);
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Map<String, Object>> serverError(Exception e) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("detail", "服务内部错误：" + e.getMessage());
        return ResponseEntity.status(500).body(body);
    }
}
