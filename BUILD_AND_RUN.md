# Stock Agent - Build and Run Guide

## Overview

This project provides a complete set of build and startup scripts for the Stock Agent System on Windows.

## Directory Structure

```
stock_agent/
├── build/          # Build scripts
│   ├── build_all.bat
│   ├── build_java.bat
│   ├── build_python.bat
│   ├── build_frontend.bat
│   └── README.md
├── start/          # Startup scripts
│   ├── start_all.bat
│   ├── start_java.bat
│   ├── start_python.bat
│   ├── start_frontend.bat
│   └── README.md
├── backend/        # Python backend
├── stock-backend/  # Java backend (Spring Boot)
└── frontend/       # Taro frontend
```

## Quick Start

### Option 1: Build then Start

1. **Build all modules:**
   ```cmd
   cd build
   build_all.bat
   ```

2. **Start all modules:**
   ```cmd
   cd ..\start
   start_all.bat
   ```

### Option 2: Direct Start (Auto-Build)

Just run the startup script, it will auto-build missing modules:
```cmd
cd start
start_all.bat
```

## Build Scripts (in `build/`)

| Script | Description |
|--------|-------------|
| `build_all.bat` | Build everything |
| `build_java.bat` | Build Java JAR only |
| `build_python.bat` | Setup Python env only |
| `build_frontend.bat` | Build frontend only |
| `build_python_exe.bat` | Package Python to EXE (optional) |

**Build options:**
```cmd
build_all.bat --no-java       # Skip Java
build_all.bat --no-python     # Skip Python
build_all.bat --no-frontend   # Skip Frontend
```

## Startup Scripts (in `start/`)

| Script | Description |
|--------|-------------|
| `start_all.bat` | Start all services |
| `start_java.bat` | Start Java backend only |
| `start_python.bat` | Start Python backend only |
| `start_frontend.bat` | Start frontend dev only |

**Start options:**
```cmd
start_all.bat --no-java       # Skip Java
start_all.bat --no-python     # Skip Python
start_all.bat --no-frontend   # Skip Frontend
```

## Services & Ports

| Service | Port | URL |
|---------|------|-----|
| Java Backend | 8080 | http://localhost:8080 |
| Python Backend | 5000 | http://localhost:5000 |
| Frontend H5 | 10086 | http://localhost:10086 |
| Swagger UI | 8080 | http://localhost:8080/swagger-ui.html |

## Prerequisites

- **Java 17+** - for Java backend
- **Python 3.8+** - for Python backend
- **Node.js 16+** - for frontend
- **pnpm 7+** - for frontend package manager
- **Maven** - for Java build (usually included in IDE or installed separately)

## Output Locations

- **Java JAR**: `stock-backend/target/stock-backend-0.0.1-SNAPSHOT.jar`
- **Python Virtual Env**: `venv_new/` or `venv/`
- **Frontend Build**: `frontend/packages/client/dist/`

## Troubleshooting

### Java Build Fails
- Check if JDK 17+ is installed: `java -version`
- Check if Maven is available: `mvn -version`

### Python Setup Fails
- Check Python installation: `python --version`
- Try deleting venv/venv_new folders and rebuild

### Frontend Build Fails
- Check Node.js: `node --version`
- Check pnpm: `pnpm --version`
- Try deleting `frontend/node_modules` and rebuild
