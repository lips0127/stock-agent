package com.stock.backend.dto;

import jakarta.validation.constraints.NotBlank;

public class WechatLoginRequest {
    @NotBlank(message = "Code is required")
    private String code;

    public String getCode() {
        return code;
    }

    public void setCode(String code) {
        this.code = code;
    }
}
