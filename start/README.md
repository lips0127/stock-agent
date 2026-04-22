# Start Scripts

This directory contains startup scripts for the Stock Agent System.

## Quick Start

### `start_all.bat`
Starts all modules in separate console windows.

**Usage:**
```bash
start_all.bat                    # Start all modules
start_all.bat --no-java          # Start Python + Frontend only
start_all.bat --no-python        # Start Java + Frontend only
start_all.bat --no-frontend      # Start Java + Python only
```

### Individual Module Scripts
- `start_java.bat` - Start only the Java backend
- `start_python.bat` - Start only the Python backend
- `start_frontend.bat` - Start only the frontend dev server

## Ports

| Service | Port |
|---------|------|
| Java Backend | 8080 |
| Python Backend | 5000 |
| Frontend H5 Dev | 10086 |

## Access URLs

- **Frontend H5:** http://localhost:10086
- **Java API:** http://localhost:8080
- **Swagger UI:** http://localhost:8080/swagger-ui.html
- **Python API:** http://localhost:5000

## Stopping the System

Close each individual console window or press Ctrl+C in each window.

## Prerequisites

- **Java:** JDK 17+
- **Python:** Python 3.8+
- **Node.js:** 16+
- **pnpm:** 7+

## First Time Setup

If modules haven't been built yet, the startup scripts will automatically call the corresponding build scripts.
