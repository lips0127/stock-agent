
# A 股股息监测系统重构规格说明书 (Spring Boot + Uni-app)

## 1. 项目概述
本项目旨在将原有的 Python 原型系统重构为企业级应用，目标是支持多端（微信小程序、Web、App）访问，并具备高并发、高可用能力。

## 2. 技术栈选型

### 后端 (Backend)
*   **语言**: Java 17+
*   **框架**: Spring Boot 3.x
*   **数据库**: MySQL 8.0+ / PostgreSQL 14+
*   **ORM**: MyBatis-Plus 或 Spring Data JPA
*   **缓存**: Redis (用于缓存实时行情、Token)
*   **定时任务**: Quartz 或 Spring Scheduled (替代 APScheduler)
*   **核心逻辑**: 
    *   保留 Python 脚本作为**独立数据服务 (Data Service)**，通过 HTTP/RPC 供 Java 调用，或者完全迁移至 Java (推荐保留 Python 仅作爬虫，Java 负责业务)。
    *   鉴于 akshare 是 Python 库，建议采用 **Java (业务) + Python (数据侧车)** 模式。

### 前端 (Frontend)
*   **框架**: Uni-app (Vue 3)
*   **UI 库**: Uni-ui 或 uView Plus
*   **编译目标**: 微信小程序 (Priority P0), H5 (Priority P1)

## 3. 系统架构设计

### 3.1 数据库设计 (Schema)

#### 用户表 (users)
| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| id | BIGINT | 主键 |
| username | VARCHAR(50) | 用户名 |
| password | VARCHAR(100) | 加密密码 |
| openid | VARCHAR(64) | 微信 OpenID |
| nickname | VARCHAR(64) | 昵称 |
| avatar_url | VARCHAR(255) | 头像 |
| created_at | DATETIME | 创建时间 |

#### 股票基础表 (stock_info)
| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| code | VARCHAR(10) | 股票代码 (PK) |
| name | VARCHAR(50) | 股票名称 |
| market | VARCHAR(10) | 市场 (SH/SZ/BJ) |

#### 每日行情与股息表 (stock_daily_metrics)
| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| id | BIGINT | PK |
| date | DATE | 数据日期 |
| code | VARCHAR(10) | 股票代码 |
| price | DECIMAL(10,2)| 收盘价 |
| dividend_yield | DECIMAL(10,4)| 股息率 (%) |
| dividend_per_share | DECIMAL(10,4)| 每股股息 (TTM) |
| update_time | DATETIME | 更新时间 |

### 3.2 API 接口定义 (RESTful)

#### 认证模块
*   `POST /api/auth/login`: 账号密码登录
*   `POST /api/auth/wechat`: 微信一键登录
*   `POST /api/auth/refresh`: 刷新 Token

#### 市场数据模块
*   `GET /api/market/indices`: 获取核心指数 (上证/深证等)
*   `GET /api/market/top-dividend`: 获取高股息排行榜 (支持分页)
*   `GET /api/market/scan`: 触发实时扫描 (限流)

#### 个股模块
*   `GET /api/stock/{code}`: 获取个股详情与股息分析

## 4. Python 数据服务 (Sidecar)
由于 akshare 是 Python 独占库，Java 重写爬虫成本极高且不稳定。
建议保留一个轻量级 Python Web 服务 (Flask/FastAPI)，仅暴露数据获取接口：
*   `GET /data/fetch/indices`: 抓取指数
*   `GET /data/fetch/dividend/{code}`: 抓取个股分红
*   `POST /data/job/full-scan`: 触发全量扫描

Spring Boot 通过 `RestTemplate` 或 `Feign` 调用此 Python 服务，并将数据清洗后存入 MySQL。

## 5. 任务清单

### Phase 1: 基础设施搭建
1.  搭建 Spring Boot 项目骨架 (Maven/Gradle)。
2.  配置 MySQL 数据库连接与 MyBatis/JPA。
3.  搭建 Uni-app 项目骨架。

### Phase 2: 后端业务开发
1.  实现用户认证 (JWT + 微信登录逻辑)。
2.  实现 Python 数据服务的 API 封装。
3.  实现 Java 端的定时任务调度 (调用 Python 服务 -> 存库)。

### Phase 3: 前端开发
1.  开发“首页/仪表盘”组件 (指数卡片 + 排行榜)。
2.  开发“个股详情”页。
3.  开发“登录/个人中心”页。

### Phase 4: 联调与部署
1.  Docker Compose 编排 (Java + Python + MySQL + Redis)。
2.  Nginx 反向代理配置。

---
**确认事项：**
您是否同意采用 **Spring Boot (业务核心) + Python (数据采集适配器) + MySQL** 的后端架构？
这种架构能最大化利用现有的 Python 代码资产，同时获得 Java 的工程化优势。如果非要完全用 Java 重写爬虫，需要寻找 Java 版的财经数据源，难度较大且容易失效。
