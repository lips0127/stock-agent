package com.stock.backend.service;

import com.stock.backend.dto.LoginRequest;
import com.stock.backend.dto.LoginResponse;
import com.stock.backend.dto.WechatLoginRequest;
import com.stock.backend.dto.WechatLoginResponse;
import com.stock.backend.entity.User;
import com.stock.backend.exception.BusinessException;
import com.stock.backend.repository.UserRepository;
import com.stock.backend.util.JwtUtil;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;
import com.stock.backend.constant.RedisKeys;
import org.springframework.data.redis.core.RedisTemplate;

import java.util.Optional;
import java.util.concurrent.TimeUnit;

@Service
public class AuthService {
    @Autowired
    private UserRepository userRepository;

    @Autowired
    private BCryptPasswordEncoder passwordEncoder;

    @Autowired
    private JwtUtil jwtUtil;

    @Autowired
    private RedisTemplate<String, Object> redisTemplate;

    public LoginResponse login(LoginRequest request) {
        Optional<User> userOptional = userRepository.findByUsername(request.getUsername());
        if (userOptional.isEmpty() || !passwordEncoder.matches(request.getPassword(), userOptional.get().getPassword())) {
            throw new BusinessException(401, "Invalid username or password");
        }

        User user = userOptional.get();
        if (user.getStatus() != 1) {
            throw new BusinessException(403, "User account is disabled");
        }

        String accessToken = jwtUtil.generateToken(user.getUsername());
        String refreshToken = jwtUtil.generateRefreshToken(user.getUsername());

        return new LoginResponse(accessToken, refreshToken, 7200);
    }

    public LoginResponse refresh(String refreshToken) {
        if (!jwtUtil.isTokenValid(refreshToken)) {
            throw new BusinessException(401, "Invalid refresh token");
        }

        String username = jwtUtil.extractUsername(refreshToken);
        Optional<User> userOptional = userRepository.findByUsername(username);
        if (userOptional.isEmpty()) {
            throw new BusinessException(401, "User not found");
        }

        String newAccessToken = jwtUtil.generateToken(username);
        String newRefreshToken = jwtUtil.generateRefreshToken(username);

        return new LoginResponse(newAccessToken, newRefreshToken, 7200);
    }

    public void logout(String accessToken, String refreshToken) {
        String jti = jwtUtil.extractJti(accessToken);
        long remainingTime = jwtUtil.extractExpiration(accessToken).getTime() - System.currentTimeMillis();
        redisTemplate.opsForValue().set(RedisKeys.BLACKLIST_ACCESS_PREFIX + jti, "1", remainingTime, TimeUnit.MILLISECONDS);

        if (refreshToken != null) {
            String refreshJti = jwtUtil.extractJti(refreshToken);
            long refreshRemainingTime = jwtUtil.extractExpiration(refreshToken).getTime() - System.currentTimeMillis();
            redisTemplate.opsForValue().set(RedisKeys.BLACKLIST_REFRESH_PREFIX + refreshJti, "1", refreshRemainingTime, TimeUnit.MILLISECONDS);
        }
    }

    public boolean isAccessTokenBlacklisted(String accessToken) {
        String jti = jwtUtil.extractJti(accessToken);
        return Boolean.TRUE.equals(redisTemplate.hasKey(RedisKeys.BLACKLIST_ACCESS_PREFIX + jti));
    }

    public WechatLoginResponse wechatLogin(WechatLoginRequest request) {
        String code = request.getCode();
        // 这里应该调用微信API获取openid
        String mockOpenid = "mock-openid-" + code;
        Optional<User> userOptional = userRepository.findByWechatOpenid(mockOpenid);

        if (userOptional.isPresent()) {
            User user = userOptional.get();
            String accessToken = jwtUtil.generateToken(user.getUsername());
            String refreshToken = jwtUtil.generateRefreshToken(user.getUsername());
            return new WechatLoginResponse(accessToken, refreshToken, 7200, mockOpenid, false);
        } else {
            String mockUsername = "wechat_" + mockOpenid.substring(0, 8);
            User newUser = new User();
            newUser.setUsername(mockUsername);
            newUser.setPassword(passwordEncoder.encode(""));
            newUser.setWechatOpenid(mockOpenid);
            newUser.setStatus(1);
            userRepository.save(newUser);
            String accessToken = jwtUtil.generateToken(newUser.getUsername());
            String refreshToken = jwtUtil.generateRefreshToken(newUser.getUsername());
            return new WechatLoginResponse(accessToken, refreshToken, 7200, mockOpenid, true);
        }
    }
}
