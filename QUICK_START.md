# Stock Agent - Quick Start Guide

## 快速开始 - 推荐方式（Python启动器）

这个方式更稳定，可以监控所有进程：

```cmd
cd start
run_all.bat
```

## 传统方式

```cmd
# 构建
cd build
build_all.bat

# 启动
cd ..\start
start_all.bat
```

## 已创建的文件

### Build 脚本 (build/)
- `build_all.bat` - 构建所有模块
- `build_java.bat` - Java后端 → JAR
- `build_python.bat` - Python环境设置
- `build_frontend.bat` - 前端编译
- `build_python_exe.bat` - Python打包为EXE（可选）

### Start 脚本 (start/)
- `run_all.bat` - **推荐** - 稳定的Python启动器
- `start_all.bat` - 原始启动脚本（多个窗口）
- `start_java.bat` - 仅启动Java
- `start_python.bat` - 仅启动Python
- `start_frontend.bat` - 仅启动前端
- `check_deps.bat` - 依赖检查
- `start_all.py` - Python启动器（核心）

### 文档
- `BUILD_AND_RUN.md` - 完整文档
- `QUICK_START.md` - 本文档

## 服务访问

| 服务 | 地址 |
|------|------|
| 前端H5 | http://localhost:10086 |
| Java后端 | http://localhost:8080 |
| Python后端 | http://localhost:5000 |
| Swagger UI | http://localhost:8080/swagger-ui.html |

## 前置要求

- Java 17+
- Python 3.8+
- Node.js 16+
- pnpm 7+

## 故障排除

如果启动失败，请运行：
```cmd
cd start
check_deps.bat
```
