#!/bin/bash

# ========================================
#   Stock Agent - 前后端同时启动脚本
# ========================================

# 配置区域
PYTHON_VENV="${VENV_NAME:-venv_new}"
API_PORT=5000
JAVA_PORT=8080
H5_PORT=10086

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}   Stock Agent - All-in-One Launcher${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# 检查虚拟环境
if [ ! -d "$PYTHON_VENV/bin/activate" ] && [ ! -f "$PYTHON_VENV/Scripts/activate" ]; then
    echo -e "${RED}[错误] 找不到虚拟环境: $PYTHON_VENV${NC}"
    echo "请设置环境变量 VENV_NAME 或修改脚本中的 PYTHON_VENV 变量"
    exit 1
fi

# 启动函数
start_service() {
    local name="$1"
    local cmd="$2"
    local port="$3"

    echo -e "${YELLOW}[启动]${NC} $name (端口: $port)..."
    if [ -f "$PYTHON_VENV/Scripts/activate" ]; then
        # Windows Git Bash / MSYS
        source "$PYTHON_VENV/Scripts/activate"
    else
        source "$PYTHON_VENV/bin/activate"
    fi

    if [ -n "$port" ]; then
        # 检查端口是否已被占用
        if command -v lsof > /dev/null 2>&1; then
            if lsof -i :$port > /dev/null 2>&1; then
                echo -e "${YELLOW}[警告]${NC} 端口 $port 已被占用，$name 可能无法启动"
            fi
        fi
    fi

    # 在后台启动
    eval "$cmd" > /dev/null 2>&1 &
    local pid=$!
    echo -e "${GREEN}[OK]${NC} $name 已启动 (PID: $pid)"
}

# 创建日志目录
mkdir -p logs

# 依次启动服务
echo -e "${YELLOW}[1/3]${NC} 启动 Python Flask API..."
if [ -f "$PYTHON_VENV/Scripts/activate" ]; then
    source "$PYTHON_VENV/Scripts/activate"
else
    source "$PYTHON_VENV/bin/activate"
fi
python -m backend.api.app > logs/flask.log 2>&1 &
FLASK_PID=$!
echo -e "${GREEN}[OK]${NC} Flask API 已启动 (PID: $FLASK_PID)"

echo ""
echo -e "${YELLOW}[2/3]${NC} 启动 Java Spring Boot..."
if [ -d "stock-backend" ] && [ -f "stock-backend/pom.xml" ]; then
    cd stock-backend && mvn spring-boot:run > ../logs/spring.log 2>&1 &
    SPRING_PID=$!
    echo -e "${GREEN}[OK]${NC} Spring Boot 已启动 (PID: $SPRING_PID)"
    cd ..
else
    echo -e "${YELLOW}[跳过]${NC} stock-backend 目录不存在"
fi

echo ""
echo -e "${YELLOW}[3/3]${NC} 启动前端 H5 开发服务器..."
if [ -d "frontend" ] && [ -f "frontend/package.json" ]; then
    cd frontend && pnpm run dev:h5 > ../logs/taro.log 2>&1 &
    TARO_PID=$!
    echo -e "${GREEN}[OK]${NC} Taro H5 已启动 (PID: $TARO_PID)"
    cd ..
else
    echo -e "${YELLOW}[跳过]${NC} frontend 目录不存在"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}   启动完成！${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "   - Flask API:    http://localhost:${API_PORT}"
echo "   - Spring Boot:  http://localhost:${JAVA_PORT}"
echo "   - H5 前端:      http://localhost:${H5_PORT}"
echo ""
echo "日志文件: logs/"
echo ""
echo "停止所有服务: kill $FLASK_PID $SPRING_PID $TARO_PID 2>/dev/null"
