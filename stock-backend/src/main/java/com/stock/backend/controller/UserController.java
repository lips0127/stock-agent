package com.stock.backend.controller;

import com.stock.backend.dto.ApiResponse;
import com.stock.backend.entity.User;
import com.stock.backend.service.UserService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/user")
public class UserController {
    @Autowired
    private UserService userService;

    @GetMapping("/profile")
    public ApiResponse<User> getProfile(Authentication authentication) {
        String username = authentication.getName();
        User user = userService.getUserByUsername(username);
        return ApiResponse.success(user);
    }

    @PutMapping("/profile")
    public ApiResponse<User> updateProfile(Authentication authentication,
                                          @RequestParam(required = false) String phone,
                                          @RequestParam(required = false) String email) {
        String username = authentication.getName();
        User user = userService.getUserByUsername(username);
        User updatedUser = userService.updateUser(user.getId(), phone, email);
        return ApiResponse.success(updatedUser);
    }
}
