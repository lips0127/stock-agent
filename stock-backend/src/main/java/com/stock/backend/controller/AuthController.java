package com.stock.backend.controller;

import com.stock.backend.dto.*;
import com.stock.backend.service.AuthService;
import com.stock.backend.service.UserService;
import io.github.resilience4j.ratelimiter.annotation.RateLimiter;
import jakarta.validation.Valid;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/auth")
public class AuthController {
    @Autowired
    private AuthService authService;

    @Autowired
    private UserService userService;

    @PostMapping("/login")
    @RateLimiter(name = "login")
    public ApiResponse<LoginResponse> login(@Valid @RequestBody LoginRequest request) {
        LoginResponse response = authService.login(request);
        return ApiResponse.success(response);
    }

    @PostMapping("/register")
    public ApiResponse<String> register(@Valid @RequestBody LoginRequest request) {
        userService.createUser(request.getUsername(), request.getPassword());
        return ApiResponse.success("User created successfully");
    }

    @PostMapping("/refresh")
    public ApiResponse<LoginResponse> refresh(@Valid @RequestBody RefreshRequest request) {
        LoginResponse response = authService.refresh(request.getRefreshToken());
        return ApiResponse.success(response);
    }

    @PostMapping("/logout")
    public ApiResponse<Void> logout(@RequestHeader(value = "Authorization", required = false) String authHeader,
                                   @RequestBody(required = false) RefreshRequest request) {
        String accessToken = null;
        String refreshToken = null;

        if (authHeader != null && authHeader.startsWith("Bearer ")) {
            accessToken = authHeader.substring(7);
        }

        if (request != null) {
            refreshToken = request.getRefreshToken();
        }

        authService.logout(accessToken, refreshToken);
        return ApiResponse.success(null);
    }

    @PostMapping("/wechat")
    public ApiResponse<WechatLoginResponse> wechatLogin(@Valid @RequestBody WechatLoginRequest request) {
        WechatLoginResponse response = authService.wechatLogin(request);
        return ApiResponse.success(response);
    }

    @PostMapping("/password-reset-code")
    @RateLimiter(name = "password-reset")
    public ApiResponse<String> requestPasswordResetCode(@Valid @RequestBody PasswordResetCodeRequest request) {
        String token = userService.generatePasswordResetCode(request.getIdentifier());
        return ApiResponse.success("Reset code sent. Token: " + token);
    }

    @PostMapping("/password-reset")
    public ApiResponse<String> resetPassword(@Valid @RequestBody PasswordResetRequest request) {
        userService.resetPassword(request.getToken(), request.getNewPassword());
        return ApiResponse.success("Password reset successfully");
    }
}
