# Stock Agent - A股股息监测系统

本项目是一个基于 **Java Spring Boot** (业务核心) 和 **Python Flask** (数据采集与计算) 的混合架构应用，旨在为投资者提供A股市场的高股息股票监测、指数追踪及个股深度分析功能。

## 1. 项目概述

本系统利用 Python 强大的数据生态 (AkShare, Pandas) 进行实时行情抓取和复杂指标计算，通过 Java Spring Boot 提供稳定可靠的 API 接口和用户认证服务。前端计划支持 Web 和移动端。

### 核心功能
*   **市场扫描**: 实时监控全市场或特定指数 (如中证红利) 的股息率。
*   **个股分析**: 提供个股的实时报价、股息率 (TTM) 及投资评级。
*   **指数追踪**: 实时跟踪上证指数、国债指数等核心市场风向标。
*   **定时任务**: 自动化的每日全量市场扫描与数据落库。

## 2. 架构设计

### 目录结构

```
stock_agent/
├── backend/                 # Python 后端核心代码
│   ├── api/                 # Flask API 接口层
│   │   └── app.py           # API 服务入口
│   ├── core/                # 核心配置与基础组件
│   │   └── database.py      # 数据库连接与认证逻辑
│   ├── services/            # 业务逻辑服务层
│   │   ├── stock_service.py # 股票数据获取与计算
│   │   ├── scanner_service.py # 市场扫描逻辑
│   │   └── scheduler.py     # 定时任务调度器
│   ├── tasks/               # 独立任务脚本
│   │   └── market_scan.py   # 全量扫描任务
│   ├── dashboard/           # 数据看板 (Streamlit)
│   │   └── app.py           # 仪表盘入口
│   └── utils/               # 通用工具函数
├── stock-backend/           # Java Spring Boot 后端项目
│   ├── src/main/java/...    # Java 源代码
│   └── pom.xml              # Maven 依赖配置
├── frontend/                # Taro 前端项目
│   └── packages/client/     # 跨平台客户端 (微信小程序/H5)
├── stocks.db                # SQLite 数据库文件
├── requirements.txt         # Python 依赖清单
└── README.md                # 项目文档
```

### 模块职责
*   **Python Backend**: 负责通过 AkShare 获取行情数据，计算股息率等指标，并将清洗后的数据存入 SQLite/MySQL。提供 Flask API 供 Java 端调用。
*   **Java Backend**: 作为对外的统一网关，处理用户登录鉴权 (JWT)，转发数据请求至 Python 服务，并可扩展更多的业务逻辑 (如用户自选股管理)。

## 3. 启动指南

### 3.1 环境准备

**前置要求**
*   Python 3.9+
*   Java 17+
*   Maven 3.x
*   Node.js 16+ (前端)
*   pnpm 7+ (前端包管理器)

**初始化 Python 环境**

```bash
# 创建虚拟环境 (任选一种)
python -m venv venv              # 方式1: venv
python -m venv venv_new         # 方式2: venv_new (项目中已存在)

# 激活虚拟环境
# Windows:
venv\Scripts\activate.bat        # 或 venv_new\Scripts\activate.bat
# Linux/Mac:
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 3.2 Python 后端启动

#### 方式一：Flask API 服务 (主数据接口)

```bash
python -m backend.api.app
```
服务将在 `http://localhost:5000` 启动。

**API 端点：**
| 方法 | 路径 | 描述 |
| :--- | :--- | :--- |
| POST | `/api/login` | 用户登录 (username/password) |
| GET | `/api/indices` | 获取主要指数行情 |
| GET | `/api/top_stocks` | 获取高股息股票排行 |
| GET | `/api/stock/<symbol>` | 获取个股详细指标 |
| POST | `/api/refresh` | 手动触发全量扫描 |
| GET | `/api/logs` | 获取任务日志 |

**默认用户**: `admin` / `admin123`

#### 方式二：Streamlit 数据看板 (可视化界面)

```bash
streamlit run backend/dashboard/app.py
```
服务将在 `http://localhost:8501` 启动。

#### 方式三：定时任务调度器

定时任务在 Flask API 启动时自动初始化，运行时间为每个交易日的 **15:30** (周一至周五)。

如需手动触发全量扫描：
```bash
# 通过 API 触发 (异步)
curl -X POST http://localhost:5000/api/refresh

# 或直接运行扫描脚本
python -m backend.tasks.market_scan
```
全量扫描使用 ThreadPoolExecutor 并发获取全市场股票数据 (默认 30 个并发线程)。

### 3.3 Java 后端启动

```bash
cd stock-backend
mvn spring-boot:run
```
服务将在 `http://localhost:8080` 启动。

Java 后端作为统一网关，接收前端请求并转发至 Python Flask 服务。

### 3.4 前端启动

```bash
cd frontend

# 安装依赖
pnpm install

# 开发模式
pnpm run dev:h5       # H5 开发 (http://localhost:10086)
pnpm run dev:weapp    # 微信小程序开发 (watch 模式)

# 生产构建
pnpm run build:h5     # 构建 H5
pnpm run build:weapp  # 构建微信小程序
```

**微信小程序开发注意事项：**
1. 运行 `pnpm run dev:weapp` 后，用微信开发者工具导入 `frontend/packages/client/dist-weapp` 目录
2. 配置 `.env` 文件 (参考 `frontend/DEPLOY.md`)

### 3.5 Docker 部署 (预留)

```bash
# 容器化部署 (注意：当前 Dockerfile 和 docker-compose.yml 为预留配置)
docker-compose up -d
```

## 4. 开发规范

*   **代码风格**: 遵循 PEP 8 规范。
*   **命名规范**: 变量/函数使用 `snake_case`，类名使用 `CamelCase`。
*   **提交规范**: `feat: ...`, `fix: ...`, `docs: ...`。

## 5. 重要配置

### 数据库初始化

SQLite 数据库 (`stocks.db`) 会在首次调用时自动初始化，无需手动创建。

### 定时任务

使用 APScheduler，调度的任务为 `full_market_scan`，运行时间：**每个交易日的 15:30**。该任务会扫描全市场股票并更新 `stock_dividend_yield` 表。

### 代理设置

AkShare 请求默认使用 `_no_proxy()` 上下文管理器临时禁用代理，以确保在内网环境下正常工作。

## 6. 未来规划

1.  **数据库迁移**: 从 SQLite 迁移至 MySQL/PostgreSQL 以支持更高并发。
2.  **缓存层**: 引入 Redis 缓存热点数据 (如指数行情)。
3.  **微服务化**: 进一步解耦数据采集与业务逻辑，通过消息队列 (RabbitMQ/Kafka) 异步处理数据清洗。
4.  **前端开发**: 基于 Uni-app 开发跨平台客户端。

## 7. 贡献指南

欢迎提交 Pull Request 或 Issue 参与项目改进！
