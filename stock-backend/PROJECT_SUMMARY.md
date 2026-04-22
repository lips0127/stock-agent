# Spring Boot 后端项目完成总结

## 项目概述
本项目按照设计文档的要求，完成了一个功能完整的股票后端系统，包含用户认证、市场数据、熔断降级等功能。

## 技术栈
- Spring Boot 3.5.0
- Spring Security + JWT (双 Token 机制)
- Spring Data JPA + PostgreSQL
- Redis (缓存 + Token 黑名单)
- Resilience4j (熔断器 + 限流)
- Swagger/OpenAPI 文档
- RestClient (替代 RestTemplate)

## 已实现功能

### 1. 认证模块
- 用户注册
- 用户登录
- Token 刷新
- Token 黑名单 (登出)
- 微信登录
- 密码重置 (邮箱/用户名 + Token)
- JWT 双 Token 机制 (Access Token: 2小时, Refresh Token: 30天)

### 2. 市场数据模块
- 获取市场指数
- 获取高股息股票
- 熔断降级机制 (Python 服务不可用时返回缓存数据)
- Redis 缓存 (10分钟过期)
- stale 标志标识是否为缓存降级数据

### 3. 安全配置
- CORS 白名单配置
- JWT 验证过滤器
- BCrypt 密码加密
- API 限流 (登录和密码重置接口)

### 4. 异常处理
- 统一异常处理器
- 业务异常
- 参数验证异常
- 限流异常
- 熔断异常

### 5. 数据库
- PostgreSQL 用户表
- Redis Token 黑名单
- Redis 缓存
- 数据库初始化脚本 (SQL)

### 6. API 文档
- Swagger UI 集成
- OpenAPI 3.0 规范
- 认证接口文档

## 项目结构
```
stock-backend/
├── src/main/java/com/stock/backend/
│   ├── StockApplication.java          # 启动类
│   ├── annotation/                    # 自定义注解
│   │   └── RateLimit.java
│   ├── aspect/                        # 切面
│   │   └── RateLimiterAspect.java
│   ├── config/                        # 配置类
│   │   ├── CorsConfig.java
│   │   ├── OpenApiConfig.java
│   │   ├── RateLimiterConfig.java
│   │   ├── RedisConfig.java
│   │   ├── ResilienceConfig.java
│   │   ├── RestClientConfig.java
│   │   └── SecurityConfig.java
│   ├── constant/                      # 常量
│   │   └── RedisKeys.java
│   ├── controller/                    # 控制器
│   │   ├── AuthController.java
│   │   ├── MarketController.java
│   │   └── UserController.java
│   ├── dto/                           # 数据传输对象
│   │   ├── ApiResponse.java
│   │   ├── LoginRequest.java
│   │   ├── LoginResponse.java
│   │   ├── PasswordResetCodeRequest.java
│   │   ├── PasswordResetRequest.java
│   │   ├── RefreshRequest.java
│   │   ├── WechatLoginRequest.java
│   │   └── WechatLoginResponse.java
│   ├── entity/                        # JPA 实体
│   │   └── User.java
│   ├── exception/                     # 异常处理
│   │   ├── BusinessException.java
│   │   ├── GlobalExceptionHandler.java
│   │   └── RateLimitException.java
│   ├── repository/                    # JPA 仓库
│   │   └── UserRepository.java
│   ├── service/                       # 服务层
│   │   ├── AuthService.java
│   │   ├── MarketService.java
│   │   └── UserService.java
│   └── util/                          # 工具类
│       └── JwtUtil.java
├── src/main/resources/
│   ├── application.yml                # 应用配置
│   └── db/
│       └── schema.sql                 # 数据库初始化脚本
└── pom.xml                            # Maven 配置
```

## 配置说明

### application.yml 主要配置
- `server.port`: 8080
- 数据库: PostgreSQL (本地连接)
- Redis: 本地连接
- JWT: 密钥、过期时间配置
- Python 服务: 地址、超时时间
- CORS 白名单: 开发环境允许的域名
- 限流配置: 默认 10 次/60 秒

### 环境变量配置
- `DB_USERNAME`: 数据库用户名
- `DB_PASSWORD`: 数据库密码
- `REDIS_PASSWORD`: Redis 密码
- `JWT_SECRET`: JWT 密钥 (生产环境必须使用强随机密钥)
- `PYTHON_SERVICE_URL`: Python 服务地址

## API 端点

### 认证 API
- `POST /api/auth/register` - 用户注册
- `POST /api/auth/login` - 用户登录
- `POST /api/auth/refresh` - 刷新 Token
- `POST /api/auth/logout` - 登出
- `POST /api/auth/wechat` - 微信登录
- `POST /api/auth/password-reset-code` - 请求密码重置码
- `POST /api/auth/password-reset` - 重置密码

### 市场数据 API
- `GET /api/market/indices` - 获取市场指数
- `GET /api/market/top-dividend?limit=20` - 获取高股息股票

### 用户 API
- `GET /api/user/profile` - 获取用户信息 (需认证)
- `PUT /api/user/profile` - 更新用户信息 (需认证)

### 管理 API
- `GET /actuator/health` - 健康检查
- `GET /swagger-ui.html` - Swagger UI
- `GET /v3/api-docs` - OpenAPI 文档

## 运行说明

### 前置条件
1. Java 17+
2. Maven 3.9+
3. PostgreSQL 16+
4. Redis 7+
5. Python 后端服务 (端口 5000)

### 运行步骤
1. 配置数据库连接
2. 运行 schema.sql 初始化数据库
3. 配置 application.yml 或设置环境变量
4. 运行: `mvn spring-boot:run`
5. 访问: http://localhost:8080/swagger-ui.html

## 初始用户
- 用户名: admin
- 密码: admin123

## 注意事项
1. 生产环境必须使用强随机密钥作为 JWT_SECRET
2. CORS 白名单需要配置实际的域名
3. 数据库和 Redis 密码需要设置
4. Python 服务地址需要正确配置
5. 微信登录需要配置实际的微信 API

## 开发计划完成情况
- ✅ Phase 1: 骨架完善 (升级框架、配置 Redis、RestClient、Resilience4j)
- ✅ Phase 2: 核心功能 (用户认证、Token 黑名单、微信登录、市场数据降级)
- ✅ Phase 3: 安全加固 (CORS 白名单、API 限流、参数校验、统一异常处理)
- ✅ Phase 4: 提测准备 (Swagger 文档、健康检查、密码重置)
