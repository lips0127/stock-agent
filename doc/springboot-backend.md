# Spring Boot 后端服务 - 功能说明、整改与设计文档

**项目名称：** stock-backend
**文档版本：** v2.0（依据 Gemini 3.1 Pro 评审意见修订）
**创建日期：** 2026-04-21
**评审日期：** 2026-04-21
**状态：** 已评审

---

## 一、代码架构

### 1.1 项目结构

```
stock-backend/
├── pom.xml                                    # Maven 配置
├── src/main/
│   ├── java/com/stock/backend/
│   │   ├── StockApplication.java              # Spring Boot 启动类
│   │   ├── config/
│   │   │   ├── SecurityConfig.java           # 安全配置
│   │   │   ├── CorsConfig.java              # CORS 配置（白名单）
│   │   │   ├── RestClientConfig.java        # HTTP 客户端配置（RestClient）
│   │   │   └── ResilienceConfig.java        # 熔断器配置
│   │   └── controller/
│   │       ├── AuthController.java          # 认证控制器
│   │       └── MarketController.java       # 市场数据控制器
│   └── resources/
│       └── application.yml                   # 应用配置
└── src/test/                                # 测试目录（空）
```

### 1.2 技术栈（v2.0 修订）

| 组件 | 版本 | 用途 | 备注 |
|------|------|------|------|
| Spring Boot | **3.5.x / 4.0.x** | 基础框架 | 3.3.x 将于 2026 年中结束支持 |
| Spring Security | 6.x | 安全认证 | |
| Spring Web | 6.x | REST API | |
| **RestClient** | Spring 6 内置 | HTTP 客户端 | 替代已维护模式的 RestTemplate |
| Resilience4j | 2.x | 熔断降级 | |
| Redis | 7.x | 缓存/Token 黑名单 | |
| PostgreSQL | 16.x | 主数据库 | 推荐用于金融数据 |
| Java | 17+ | 运行时 | |
| Maven | 3.9+ | 构建工具 | |

### 1.3 数据流向

```
┌─────────────────────────────────────────────────────────────────┐
│                    客户端 (Taro / 微信小程序)                     │
└─────────────────────────────┬───────────────────────────────────┘
                              │ HTTPS
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Java BFF (单体应用)  :8080                      │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │   统一认证    │  │  限流熔断    │  │    请求路由/聚合       │  │
│  │   JWT 验证    │  │ Resilience4j │  │    降级处理           │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────────┬───────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
          ▼                   ▼                   ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│   PostgreSQL     │  │     Redis        │  │  Python API      │
│   (用户数据)      │  │  (缓存/黑名单)   │  │   :5000          │
│                  │  │                  │  │  (数据采集计算)   │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

### 1.4 架构定性

> **BFF (Backend for Frontend) 单体应用**，而非微服务网关。
>
> Java 服务职责：统一认证鉴权、接口聚合路由、限流熔断降级。
> Python 服务职责：数据采集、股票指标计算（独立运行，定时调度）。
>
> 无需引入 Spring Cloud Gateway 等重型组件，Python 服务地址作为应用配置项注入即可。

---

## 二、功能梳理

### 2.1 已实现功能

#### 2.1.1 认证模块 (AuthController)

| 接口 | 方法 | 路径 | 功能 | 现状 |
|------|------|------|------|------|
| 登录 | POST | /api/auth/login | 用户登录 | **Mock 实现**，返回假 JWT token |
| 微信登录 | POST | /api/auth/wechat | 微信授权登录 | **占位代码**，未调用微信 API |
| 刷新Token | POST | /api/auth/refresh | 刷新 Access Token | **未实现** |

#### 2.1.2 市场数据模块 (MarketController)

| 接口 | 方法 | 路径 | 功能 | 现状 |
|------|------|------|------|------|
| 指数行情 | GET | /api/market/indices | 获取市场指数 | **代理转发**到 Python 服务 |
| 高股息股票 | GET | /api/market/top-dividend | 获取高股息股票列表 | **代理转发**到 Python 服务 |

#### 2.1.3 安全配置 (SecurityConfig)

| 配置项 | 现状 |
|--------|------|
| CORS | 允许所有来源（`*`）- **危险** |
| CSRF | 已禁用 |
| 认证路径 | /api/auth/**, /api/market/** 允许匿名访问 |
| 其他路径 | 需要认证（但实际未实现） |

### 2.2 缺失功能

- [ ] 用户注册
- [ ] 密码加密存储（BCrypt）
- [ ] 真正的 JWT Token 生成与验证
- [ ] 双 Token 机制（Access + Refresh）
- [ ] Token 黑名单（Redis）
- [ ] 微信登录接入
- [ ] 密码重置（手机/邮箱验证）
- [ ] Redis 缓存集成
- [ ] Resilience4j 熔断降级
- [ ] API 限流
- [ ] 请求日志与监控

---

## 三、现状问题分析

### 3.1 安全性问题（严重）

```java
// SecurityConfig.java:34
configuration.setAllowedOrigins(Arrays.asList("*")); // 生产环境危险
```

| 问题 | 风险等级 | 说明 |
|------|----------|------|
| CORS 全开 | 🔴 高 | 任何网站都能调用 API |
| Mock 认证 | 🔴 高 | 任何用户名都能登录 |
| 无密码加密 | 🔴 高 | 若接数据库，密码明文存储 |
| 无 Token 验证 | 🔴 高 | JWT 只是一串假字符串 |
| 无 Token 黑名单 | 🟡 中 | 登出后 Token 仍可使用 |
| 无密码重置 | 🟡 中 | 无法找回密码 |

### 3.2 代码质量问题

| 问题 | 位置 | 说明 |
|------|------|------|
| RestTemplate 非单例 | MarketController:14 | 已过时，应使用 RestClient |
| 硬编码 URL | MarketController:15 | Python 服务地址写死在代码中 |
| 无异常处理 | MarketController | 捕获异常后只打印堆栈，返回空列表 |
| 无输入校验 | AuthController | 未校验 username/password 是否为空 |
| 无 DTO | Controller 层 | 直接使用 Map 接收和返回 |
| 无统一响应格式 | 所有 Controller | 返回格式不统一 |
| 无熔断降级 | MarketController | Python 服务不可用时直接报错 |

### 3.3 架构问题

| 问题 | 说明 |
|------|------|
| 无 Service 层 | Controller 直接调用外部服务，业务逻辑混杂 |
| 无 Repository 层 | 若接数据库，无数据访问层 |
| 无配置外化 | Python 服务地址写死在代码中 |
| 无健康检查 | 未提供 /actuator/health 接口 |
| 无缓存层 | 高频数据请求直接打到 Python 服务 |

---

## 四、整改方案

### 4.1 短期整改（骨架完善）

#### Step 1: 框架与基础设施
```
目标：升级技术栈，建立工程化基础
产出：
- 升级至 Spring Boot 3.5.x / 4.0.x
- 引入 RestClient（替代 RestTemplate）
- 引入 Redis（配置化，Token 黑名单 + 缓存）
- 引入 Resilience4j（熔断降级基础）
- 重构包结构（Controller -> Service -> Repository）
```

#### Step 2: 完善认证模块
```
目标：实现基本的用户认证功能
产出：
- 用户实体 (User Entity)
- PostgreSQL 用户表
- BCrypt 密码加密
- 真正的 JWT Token 生成与验证（Access + Refresh 双 Token）
- Token 黑名单（Redis）
- 微信 OpenID 绑定
```

#### Step 3: 完善市场数据模块
```
目标：解耦 Python 服务依赖，增强稳定性
产出：
- RestClient 注入为 Bean
- Python 服务地址配置化
- Resilience4j 熔断器配置
- Redis 缓存（降级时返回缓存数据）
- 数据响应附带时间戳
```

### 4.2 中期整改（架构升级）

```
目标：构建可扩展的企业级架构
产出：
- 统一响应格式（ApiResponse<T>）
- 参数校验（Jakarta Validator）
- 统一异常处理（GlobalExceptionHandler）
- CORS 白名单配置化
- 操作日志
- API 限流
- OpenAPI/Swagger 文档
```

### 4.3 长期整改（生产化）

```
目标：满足生产环境要求
产出：
- 数据库迁移（数据初始化脚本）
- 灰度发布支持
- 容器化部署（Docker）
- 全链路监控（Micrometer + Prometheus）
- 密钥外部管理（KMS）
```

---

## 五、设计方案

### 5.1 目标架构

> 详见 1.3 节数据流向图。

### 5.2 包结构设计（v2.0 修订）

```
com.stock.backend/
├── StockApplication.java
├── config/
│   ├── SecurityConfig.java          # 安全配置（JWT + 白名单）
│   ├── CorsConfig.java             # CORS 白名单配置
│   ├── RestClientConfig.java       # RestClient Bean 配置
│   ├── ResilienceConfig.java       # Resilience4j 熔断器配置
│   └── RedisConfig.java            # Redis 配置
├── controller/
│   ├── AuthController.java         # 认证接口
│   ├── UserController.java         # 用户接口
│   └── MarketController.java      # 市场数据接口
├── service/
│   ├── AuthService.java            # 认证业务（JWT 生成/验证）
│   ├── UserService.java           # 用户业务
│   └── MarketService.java         # 市场数据业务（含熔断逻辑）
├── repository/
│   └── UserRepository.java        # 用户数据访问（JPA）
├── entity/
│   └── User.java                  # 用户实体
├── dto/
│   ├── LoginRequest.java          # 登录请求
│   ├── LoginResponse.java         # 登录响应（双 Token）
│   ├── RefreshRequest.java        # 刷新 Token 请求
│   └── ApiResponse.java          # 统一响应
├── exception/
│   ├── GlobalExceptionHandler.java
│   └── BusinessException.java
├── util/
│   └── JwtUtil.java               # JWT 工具类
└── constant/
    └── RedisKeys.java             # Redis Key 常量
```

### 5.3 核心接口设计（v2.0 修订）

#### 5.3.1 认证接口

```
POST /api/auth/login
请求体：
{
  "username": "string",
  "password": "string"
}
响应：
{
  "code": 200,
  "message": "success",
  "data": {
    "accessToken": "eyJhbGciOiJIUzI1NiIs...",
    "refreshToken": "eyJhbGciOiJIUzI1NiIs...",
    "expiresIn": 7200
  }
}
```

```
POST /api/auth/refresh
请求体：
{
  "refreshToken": "string"
}
响应：
{
  "code": 200,
  "message": "success",
  "data": {
    "accessToken": "eyJhbGciOiJIUzI1NiIs...",
    "refreshToken": "eyJhbGciOiJIUzI1NiIs...",
    "expiresIn": 7200
  }
}
```

```
POST /api/auth/logout
请求头：Authorization: Bearer <accessToken>
响应：
{
  "code": 200,
  "message": "success",
  "data": null
}
```

```
POST /api/auth/wechat
请求体：
{
  "code": "微信授权code"
}
响应：
{
  "code": 200,
  "message": "success",
  "data": {
    "accessToken": "eyJhbGciOiJIUzI1NiIs...",
    "refreshToken": "eyJhbGciOiJIUzI1NiIs...",
    "openid": "微信openid",
    "isNewUser": true
  }
}
```

#### 5.3.2 市场数据接口（v2.0 修订）

```
GET /api/market/indices
响应：
{
  "code": 200,
  "message": "success",
  "data": [
    {
      "name": "上证指数",
      "code": "000001",
      "price": 3285.67,
      "change": 1.23,
      "changePercent": 0.04
    }
  ],
  "timestamp": "2026-04-21T22:30:00+08:00",
  "stale": false
}
```

```
GET /api/market/top-dividend?limit=20
响应：
{
  "code": 200,
  "message": "success",
  "data": [
    {
      "symbol": "600519",
      "name": "贵州茅台",
      "dividendYield": 5.67,
      "price": 1680.00,
      "change": -0.52
    }
  ],
  "timestamp": "2026-04-21T22:30:00+08:00",
  "stale": false
}
```

> **降级响应示例**（Python 服务不可用时）：
```
{
  "code": 503,
  "message": "Service temporarily unavailable",
  "data": [...],
  "timestamp": "2026-04-21T22:25:00+08:00",
  "stale": true
}
```

### 5.4 统一响应格式（v2.0 修订）

```java
public class ApiResponse<T> {
    private int code;       // 状态码：200成功，4xx客户端错误，5xx服务端错误
    private String message; // 消息
    private T data;        // 数据
    private String timestamp; // 数据时间戳
    private boolean stale;  // 是否为降级缓存数据

    public static <T> ApiResponse<T> success(T data) {
        ApiResponse<T> response = new ApiResponse<>();
        response.code = 200;
        response.message = "success";
        response.data = data;
        response.timestamp = Instant.now().toString();
        response.stale = false;
        return response;
    }

    public static <T> ApiResponse<T> degraded(T data) {
        ApiResponse<T> response = success(data);
        response.stale = true;
        return response;
    }

    public static <T> ApiResponse<T> error(int code, String message) {
        ApiResponse<T> response = new ApiResponse<>();
        response.code = code;
        response.message = message;
        response.data = null;
        response.timestamp = Instant.now().toString();
        return response;
    }
}
```

---

## 六、数据库设计（v2.0 修订）

> **推荐使用 PostgreSQL**，原因：
> - JSONB 类型支持股票衍生指标存储
> - 强大的窗口函数和时序数据处理能力
> - 更适合金融数据查询特征

### 6.1 用户表

```sql
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,       -- BCrypt 加密
    phone VARCHAR(20),
    email VARCHAR(100),
    wechat_openid VARCHAR(100) UNIQUE,
    status SMALLINT DEFAULT 1,           -- 1:正常 0:禁用
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_users_wechat_openid ON users(wechat_openid);
CREATE INDEX idx_users_username ON users(username);
```

### 6.2 Token 黑名单表（Redis 结构）

```
Key: blacklist:access:<token_jti>
Value: "1"
TTL: 与 token 剩余有效期一致

Key: refresh:<user_id>
Value: <refresh_token_jti>
TTL: 30天
```

---

## 七、配置设计（v2.0 修订）

### 7.1 application.yml

```yaml
server:
  port: 8080

spring:
  application:
    name: stock-backend
  datasource:
    url: jdbc:postgresql://localhost:5432/stock_db
    username: ${DB_USERNAME}
    password: ${DB_PASSWORD}
  data:
    redis:
      host: localhost
      port: 6379
      password: ${REDIS_PASSWORD}

# JWT 配置
jwt:
  secret: ${JWT_SECRET}                    # 必须通过环境变量注入，禁止明文
  expiration: 7200000                       # Access Token 有效期（2小时）
  refresh-expiration: 2592000000            # Refresh Token 有效期（30天）
  algorithm: HS256

# Python 服务配置
python:
  service:
    url: ${PYTHON_SERVICE_URL}             # 配置化
    timeout: 5000
  circuit-breaker:
    failure-rate-threshold: 50
    wait-duration-in-open-state: 30000
    sliding-window-size: 10

# CORS 白名单（按环境配置）
cors:
  allowed-origins:
    - http://localhost:10086               # 开发环境
    # 生产环境应限定具体域名
```

### 7.2 环境配置分离

```
application-dev.yml   # 开发环境
application-prod.yml  # 生产环境（敏感配置隔离）
```

---

## 八、已评审决策（v2.0 新增）

> 以下内容经 Gemini 3.1 Pro 评审确认，已在 v2.0 中修订

### 8.1 架构决策

| 问题 | 决策 | 理由 |
|------|------|------|
| 认证方案 | **JWT（双 Token）** | 跨平台兼容（小程序）、无状态扩展、配合 Redis 黑名单 |
| 部署模式 | **BFF 单体** | 职责单一，无需 Spring Cloud Gateway |
| 数据库 | **PostgreSQL** | JSONB 支持、窗口函数强、适合金融数据 |

### 8.2 安全要点（落地设计）

| 评审点 | 落地设计 |
|--------|----------|
| **CORS 白名单** | 通过 `application.yml` 配置，禁止硬编码。按环境隔离（dev/prod）。 |
| **JWT Secret** | 高熵随机字符串（≥256位 HMAC-SHA）。通过 `${JWT_SECRET}` 环境变量注入，禁止提交至代码仓库。 |
| **密码重置** | 外部验证通道（手机短信/邮箱链接）+ 极短有效期 Token（5-10分钟）+ BCrypt 更新。接口需限流。 |

### 8.3 集成要点（落地设计）

| 评审点 | 落地设计 |
|--------|----------|
| **Python 服务降级** | Resilience4j 断路器。降级时从 Redis 返回缓存数据（标记 `stale=true`），若无缓存则返回 503。 |
| **数据同步延迟** | Python 侧独立定时调度采集计算，Java 侧仅读已就绪数据。响应附 `timestamp` 字段。 |
| **微信登录** | 推荐实现。OpenID 可作为独立用户身份建立账户体系，简化 Phase 2 注册流程。 |

---

## 九、开发计划（v2.0 修订）

### Phase 1: 骨架完善（2-3天）

- [ ] **升级框架**：Spring Boot 3.5.x / 4.0.x
- [ ] **引入 Redis**：基础配置 + 连接池
- [ ] **引入 RestClient**：替代 RestTemplate
- [ ] **引入 Resilience4j**：熔断器基础配置
- [ ] **重构包结构**：Controller -> Service -> Repository 分层
- [ ] **配置外化**：环境变量 + application.yml

### Phase 2: 核心功能（3-5天）

- [ ] **用户注册/登录**：BCrypt + JWT 双 Token
- [ ] **Token 黑名单**：Redis 实现登出失效
- [ ] **微信登录**：OpenID 绑定
- [ ] **市场数据降级**：熔断 + 缓存 + stale 标识

### Phase 3: 安全加固（1-2天）

- [ ] **CORS 白名单**：配置化
- [ ] **API 限流**：Redis + 滑动窗口
- [ ] **参数校验**：Jakarta Validator
- [ ] **统一异常处理**：GlobalExceptionHandler

### Phase 4: 提测准备（1天）

- [ ] **Swagger API 文档**：OpenAPI 3.0
- [ ] **健康检查**：/actuator/health
- [ ] **密码重置**：手机/邮箱验证流程

---

**文档结束**

---

## 附录：修订历史

| 版本 | 日期 | 修订内容 |
|------|------|----------|
| v1.0 | 2026-04-21 | 初始版本 |
| v2.0 | 2026-04-21 | 依据 Gemini 3.1 Pro 评审意见修订：升级技术栈（Spring Boot 4.0.x + RestClient）、确认 BFF 单体架构、推荐 PostgreSQL、补充 Redis + 熔断降级设计、重排 Phase 1 开发计划 |
