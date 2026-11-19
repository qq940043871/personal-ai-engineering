package com.ownrag.api;

/** HTTP 错误统一类型：message = detail（与 Python 版 HTTPException(status, detail) 契约对齐）。 */
public class ApiError extends RuntimeException {

    public final int status;

    public ApiError(int status, String message) {
        super(message);
        this.status = status;
    }
}
