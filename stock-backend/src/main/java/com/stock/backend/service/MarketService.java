package com.stock.backend.service;

import com.stock.backend.constant.RedisKeys;
import com.stock.backend.dto.ApiResponse;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

@Service
public class MarketService {
    private static final Logger logger = LoggerFactory.getLogger(MarketService.class);

    @Autowired
    private RestClient restClient;

    @Autowired
    private RedisTemplate<String, Object> redisTemplate;

    @Value("${python.service.url}")
    private String pythonServiceUrl;

    @Value("${python.service.timeout}")
    private int pythonServiceTimeout;

    @CircuitBreaker(name = "pythonService", fallbackMethod = "getIndicesFallback")
    public ApiResponse<List<Map<String, Object>>> getIndices() {
        logger.info("Calling Python service for market indices at: {}", pythonServiceUrl);
        try {
            List<Map<String, Object>> indices = restClient
                    .get()
                    .uri("/api/indices")
                    .retrieve()
                    .body(List.class);

            redisTemplate.opsForValue().set(RedisKeys.CACHE_MARKET_INDICES, indices, 10, TimeUnit.MINUTES);
            logger.debug("Market indices retrieved and cached successfully");
            return ApiResponse.success(indices);
        } catch (Exception e) {
            logger.error("Failed to call Python service: {}", e.getMessage());
            throw e;
        }
    }

    @SuppressWarnings("unchecked")
    public ApiResponse<List<Map<String, Object>>> getIndicesFallback(Exception e) {
        logger.warn("Falling back to cached indices due to: {}", e.getMessage());
        Object cached = redisTemplate.opsForValue().get(RedisKeys.CACHE_MARKET_INDICES);
        if (cached != null) {
            return ApiResponse.degraded((List<Map<String, Object>>) cached);
        }
        return ApiResponse.error(503, "Service temporarily unavailable");
    }

    @CircuitBreaker(name = "pythonService", fallbackMethod = "getTopDividendFallback")
    public ApiResponse<List<Map<String, Object>>> getTopDividend(int limit) {
        logger.info("Calling Python service for top dividend stocks at: {}", pythonServiceUrl);
        try {
            List<Map<String, Object>> stocks = restClient
                    .get()
                    .uri("/api/top_stocks?limit=" + limit)
                    .retrieve()
                    .body(List.class);

            redisTemplate.opsForValue().set(RedisKeys.CACHE_MARKET_TOP_DIVIDEND, stocks, 10, TimeUnit.MINUTES);
            logger.debug("Top dividend stocks retrieved and cached successfully");
            return ApiResponse.success(stocks);
        } catch (Exception e) {
            logger.error("Failed to call Python service: {}", e.getMessage());
            throw e;
        }
    }

    @SuppressWarnings("unchecked")
    public ApiResponse<List<Map<String, Object>>> getTopDividendFallback(int limit, Exception e) {
        logger.warn("Falling back to cached top dividend stocks due to: {}", e.getMessage());
        Object cached = redisTemplate.opsForValue().get(RedisKeys.CACHE_MARKET_TOP_DIVIDEND);
        if (cached != null) {
            return ApiResponse.degraded((List<Map<String, Object>>) cached);
        }
        return ApiResponse.error(503, "Service temporarily unavailable");
    }
}
