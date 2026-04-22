package com.stock.backend.exception;

import org.springframework.http.HttpStatus;

public class RateLimitException extends BusinessException {

    public RateLimitException(String message) {
        super(HttpStatus.TOO_MANY_REQUESTS.value(), message);
    }

    public RateLimitException() {
        super(HttpStatus.TOO_MANY_REQUESTS.value(), "Rate limit exceeded");
    }
}
