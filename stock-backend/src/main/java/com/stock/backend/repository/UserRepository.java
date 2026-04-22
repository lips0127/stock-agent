package com.stock.backend.repository;

import com.stock.backend.entity.User;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;

@Repository
public interface UserRepository extends JpaRepository<User, Long> {
    Optional<User> findByUsername(String username);
    Optional<User> findByWechatOpenid(String wechatOpenid);
    Optional<User> findByEmail(String email);
    Boolean existsByUsername(String username);
}
