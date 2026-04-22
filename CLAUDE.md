# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an A-share dividend monitoring system (A股股息监测系统) using a hybrid Java + Python architecture:
- **Python Backend** (`backend/`): Data acquisition engine using AkShare for real-time stock metrics and dividend calculations
- **Java Backend** (`stock-backend/`): Spring Boot gateway for authentication and business logic (in development)
- **Frontend** (`frontend/`): Taro (React) cross-platform app targeting WeChat Mini Program and H5
- **Database**: SQLite (`stocks.db`) — migration to MySQL planned

## Common Commands

### Python Backend (Data Service)
```bash
# Start Flask API (port 5000)
python -m backend.api.app

# Start Streamlit dashboard
streamlit run backend/dashboard/app.py

# Run market scan task directly
python -m backend.tasks.market_scan
```

### Frontend (Taro)
```bash
cd frontend
npm run dev:weapp    # Watch mode for WeChat Mini Program
npm run build:weapp  # Build for WeChat Mini Program
npm run dev:h5       # Watch mode for H5
npm run build:h5     # Build for H5
```

### Java Backend
```bash
cd stock-backend
mvn spring-boot:run
```

### Database
The SQLite database (`stocks.db`) auto-initializes on first run. Default admin user: `admin` / `admin123`

## Architecture

### Data Flow
```
Client (Taro) → Java Gateway (8080) → Python Flask API (5000) → AkShare/Sina/EastMoney
                                       ↓
                                  SQLite DB
```

### Python Backend Structure
- `backend/api/app.py` — Flask API routes (login, indices, top_stocks, stock/{symbol}, refresh, logs)
- `backend/services/stock_service.py` — Stock metrics via Sina HQ + EastMoney dividend data
- `backend/services/scanner_service.py` — CSI Dividend Index (000922) constituent scanning with caching
- `backend/services/scheduler.py` — APScheduler daily task at 15:30 Mon-Fri
- `backend/core/database.py` — SQLite schema init, user auth with pbkdf2_sha256

### Key API Endpoints (Flask :5000)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/login` | User authentication |
| GET | `/api/indices` | Market indices snapshot |
| GET | `/api/top_stocks` | High dividend stocks ranking |
| GET | `/api/stock/<symbol>` | Individual stock metrics |
| POST | `/api/refresh` | Trigger full market scan |
| GET | `/api/logs` | Task execution logs |

### Dividend Calculation Logic
`stock_service.py:get_stock_metrics()` uses a two-tier approach:
1. **TTM approach**: Sum cash dividends with ex-rights dates in the past 12 months
2. **Fallback**: If no recent dividends, use the latest dividend (within 18 months)

## Development Notes

- AkShare calls are wrapped with `_no_proxy()` context manager to bypass corporate proxies
- `market_dividends_cache.json` caches high-dividend scan results to avoid re-fetching
- The `run.bat` script activates `venv_new` and runs a Streamlit app — this appears to be an alternative entry point
- Frontend API service (`frontend/packages/client/src/services/api.ts`) makes requests to Java gateway at port 8080
