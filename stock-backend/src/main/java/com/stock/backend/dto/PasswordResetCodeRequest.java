package com.stock.backend.dto;

import jakarta.validation.constraints.NotBlank;

public class PasswordResetCodeRequest {
    @NotBlank(message = "Username or email is required")
    private String identifier;

    public String getIdentifier() {
        return identifier;
    }

    public void setIdentifier(String identifier) {
        this.identifier = identifier;
    }
}
