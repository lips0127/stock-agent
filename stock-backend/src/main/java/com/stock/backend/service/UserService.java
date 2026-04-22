package com.stock.backend.service;

import com.stock.backend.constant.RedisKeys;
import com.stock.backend.entity.User;
import com.stock.backend.exception.BusinessException;
import com.stock.backend.repository.UserRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;

import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

@Service
public class UserService {
    @Autowired
    private UserRepository userRepository;

    @Autowired
    private BCryptPasswordEncoder passwordEncoder;

    @Autowired
    private RedisTemplate<String, Object> redisTemplate;

    public User createUser(String username, String password) {
        if (userRepository.existsByUsername(username)) {
            throw new BusinessException(400, "Username already exists");
        }

        User user = new User();
        user.setUsername(username);
        user.setPassword(passwordEncoder.encode(password));
        user.setStatus(1);
        return userRepository.save(user);
    }

    public User updateUser(Long id, String phone, String email) {
        Optional<User> userOptional = userRepository.findById(id);
        if (userOptional.isEmpty()) {
            throw new BusinessException(404, "User not found");
        }

        User user = userOptional.get();
        if (phone != null) {
            user.setPhone(phone);
        }
        if (email != null) {
            user.setEmail(email);
        }
        return userRepository.save(user);
    }

    public User getUserByUsername(String username) {
        Optional<User> userOptional = userRepository.findByUsername(username);
        return userOptional.orElse(null);
    }

    public String generatePasswordResetCode(String identifier) {
        Optional<User> user = userRepository.findByUsername(identifier);
        if (user.isEmpty()) {
            user = userRepository.findByEmail(identifier);
        }
        if (user.isEmpty()) {
            throw new BusinessException(404, "User not found");
        }

        String resetToken = UUID.randomUUID().toString();
        String redisKey = RedisKeys.BLACKLIST_REFRESH_PREFIX + resetToken;
        redisTemplate.opsForValue().set(redisKey, user.get().getId(), 10, TimeUnit.MINUTES);
        return resetToken;
    }

    public void resetPassword(String token, String newPassword) {
        String redisKey = RedisKeys.BLACKLIST_REFRESH_PREFIX + token;
        Object userIdObj = redisTemplate.opsForValue().get(redisKey);
        if (userIdObj == null) {
            throw new BusinessException(400, "Invalid or expired reset token");
        }

        Long userId = Long.valueOf(userIdObj.toString());
        Optional<User> userOptional = userRepository.findById(userId);
        if (userOptional.isEmpty()) {
            throw new BusinessException(404, "User not found");
        }

        User user = userOptional.get();
        user.setPassword(passwordEncoder.encode(newPassword));
        userRepository.save(user);

        redisTemplate.delete(redisKey);
    }
}
