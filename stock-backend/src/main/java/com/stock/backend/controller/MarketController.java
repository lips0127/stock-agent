package com.stock.backend.controller;

import com.stock.backend.dto.ApiResponse;
import com.stock.backend.service.MarketService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/market")
public class MarketController {

    @Autowired
    private MarketService marketService;

    @GetMapping("/indices")
    public ApiResponse<List<Map<String, Object>>> getIndices() {
        return marketService.getIndices();
    }

    @GetMapping("/top-dividend")
    public ApiResponse<List<Map<String, Object>>> getTopDividend(@RequestParam(defaultValue = "20") int limit) {
        return marketService.getTopDividend(limit);
    }
}
