package com.stock.backend.aspect;

import io.github.resilience4j.ratelimiter.RequestNotPermitted;
import io.github.resilience4j.ratelimiter.annotation.RateLimiter;
import org.aspectj.lang.annotation.Aspect;
import org.aspectj.lang.annotation.Before;
import org.springframework.stereotype.Component;

@Aspect
@Component
public class RateLimiterAspect {

    @Before("@annotation(rateLimiter)")
    public void beforeMethod(RateLimiter rateLimiter) {
        // 实际限流逻辑由 Resilience4j 提供的注解驱动
    }
}
