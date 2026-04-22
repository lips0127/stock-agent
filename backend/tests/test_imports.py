import sys
import os

# Add current directory to path
sys.path.append(os.getcwd())

print("Checking imports...")
try:
    from backend.api import app
    print("✅ backend.api.app imported")
except ImportError as e:
    print(f"❌ backend.api.app failed: {e}")

try:
    from backend.core import database
    print(f"✅ backend.core.database imported. DB_FILE: {database.DB_FILE}")
    if os.path.exists(database.DB_FILE):
        print("✅ Database file found at correct path")
    else:
        print(f"❌ Database file NOT found at: {database.DB_FILE}")
except ImportError as e:
    print(f"❌ backend.core.database failed: {e}")

try:
    from backend.services import stock_service
    print("✅ backend.services.stock_service imported")
except ImportError as e:
    print(f"❌ backend.services.stock_service failed: {e}")

try:
    from backend.services import scanner_service
    print("✅ backend.services.scanner_service imported")
except ImportError as e:
    print(f"❌ backend.services.scanner_service failed: {e}")

try:
    from backend.tasks import market_scan
    print("✅ backend.tasks.market_scan imported")
except ImportError as e:
    print(f"❌ backend.tasks.market_scan failed: {e}")

try:
    from backend.services import scheduler
    print("✅ backend.services.scheduler imported")
except ImportError as e:
    print(f"❌ backend.services.scheduler failed: {e}")

print("\nVerification complete.")
