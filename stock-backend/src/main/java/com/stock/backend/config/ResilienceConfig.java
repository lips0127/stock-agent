package com.stock.backend.config;

import io.github.resilience4j.circuitbreaker.CircuitBreakerConfig;
import io.github.resilience4j.circuitbreaker.CircuitBreakerRegistry;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.time.Duration;

@Configuration
public class ResilienceConfig {
    @Value("${python.circuit-breaker.failure-rate-threshold}")
    private int failureRateThreshold;

    @Value("${python.circuit-breaker.wait-duration-in-open-state}")
    private int waitDurationInOpenState;

    @Value("${python.circuit-breaker.sliding-window-size}")
    private int slidingWindowSize;

    @Bean
    public CircuitBreakerRegistry circuitBreakerRegistry() {
        CircuitBreakerConfig circuitBreakerConfig = CircuitBreakerConfig.custom()
                .failureRateThreshold(failureRateThreshold)
                .waitDurationInOpenState(Duration.ofMillis(waitDurationInOpenState))
                .slidingWindowSize(slidingWindowSize)
                .build();
        return CircuitBreakerRegistry.of(circuitBreakerConfig);
    }
}
