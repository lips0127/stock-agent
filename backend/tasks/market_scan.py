
import concurrent.futures
import time
import sqlite3
import akshare as ak
from backend.services.stock_service import get_stock_metrics, _no_proxy, get_sina_index_spot
from backend.config import DB_PATH as DB_FILE, SCAN_MAX_WORKERS
import pandas as pd
from datetime import date
import random
import logging

logger = logging.getLogger(__name__)

# Optimize SQLite for concurrency
def configure_db_pragma(conn):
    conn.execute("PRAGMA journal_mode=WAL;")  # Write-Ahead Logging for concurrency
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.commit()

def get_all_stock_codes():
    """
    Get all A-share stock codes.
    Using ak.stock_info_a_code_name() is efficient.
    """
    logger.info("Fetching all A-share codes...")
    try:
        with _no_proxy():
            df = ak.stock_info_a_code_name()
        return df['code'].tolist()
    except Exception as e:
        logger.error(f"Error fetching codes: {e}")
        return []

def process_single_stock(code):
    """
    Process a single stock code.
    Designed for concurrent execution.
    """
    try:
        # Skip if code is empty or invalid
        if not code: return None
        
        # Use our robust get_stock_metrics logic
        # Add slight random delay to avoid hitting rate limits too hard if workers are synced
        time.sleep(random.uniform(0.05, 0.2))
        
        metrics = get_stock_metrics(code)
        
        if metrics and metrics.get('最新价', 0) > 0: # Ensure valid price
             return {
                "code": code,
                "name": metrics['名称'],
                "price": metrics['最新价'],
                "dividend_yield": metrics['股息率']
            }
        return None
    except Exception:
        return None


def full_market_scan(max_workers=20):
    """
    Concurrent scan of the entire market using ThreadPoolExecutor.
    """
    all_codes = get_all_stock_codes()
    if not all_codes:
        logger.info(f"No codes found.")
        return

    logger.info(f"Total stocks to scan: {len(all_codes)}")
    
    today = date.today().isoformat()
    total_results = []
    
    # Use ThreadPoolExecutor for concurrent fetching
    # We submit individual tasks instead of batches for better load balancing
    # But for 5000 stocks, creating 5000 futures is fine.
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_code = {executor.submit(process_single_stock, code): code for code in all_codes}
        
        completed_count = 0
        total_count = len(all_codes)
        
        for future in concurrent.futures.as_completed(future_to_code):
            code = future_to_code[future]
            completed_count += 1
            
            if completed_count % 100 == 0:
                logger.info(f"Progress: {completed_count}/{total_count} ({(completed_count/total_count)*100:.1f}%)")
                
            try:
                data = future.result()
                if data:
                    total_results.append(data)
            except Exception as e:
                pass


    logger.info(f"Scan complete. Saving {len(total_results)} records to DB...")
    
    # Batch Insert to DB
    conn = sqlite3.connect(DB_FILE)
    configure_db_pragma(conn)
    
    try:
        c = conn.cursor()
        c.execute("BEGIN TRANSACTION;")
        
        # Clear today's existing data to avoid duplicates/stale mix?
        # Or just replace.
        
        c.executemany('''
            INSERT OR REPLACE INTO stock_daily_metrics (date, code, name, price, dividend_yield)
            VALUES (?, ?, ?, ?, ?)
        ''', [(today, r['code'], r['name'], r['price'], r['dividend_yield']) for r in total_results])
        
        conn.commit()
        logger.info("Database update successful.")

        # Write market indices
        INDEX_SYMBOLS = {
            "000001": "上证指数",
            "399001": "深证成指",
            "399006": "创业板指",
            "000016": "上证50",
            "000300": "沪深300",
        }
        for symbol, name in INDEX_SYMBOLS.items():
            try:
                data = get_sina_index_spot(symbol)
                if data:
                    c.execute(
                        "INSERT OR REPLACE INTO market_indices (date, symbol, name, value, change_amount, change_pct) VALUES (?, ?, ?, ?, ?, ?)",
                        (today, symbol, name, data.get("current", 0), data.get("change_amount", 0), data.get("change_pct", 0)),
                    )
            except Exception as e:
                logger.warning(f"Failed to fetch index {symbol}: {e}")
        conn.commit()

    except Exception as e:
        conn.rollback()
        logger.error(f"Database error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    start_time = time.time()
    # Adjust max_workers based on network capability. 
    # Too high might trigger rate limits from Sina/EastMoney.
    # 20-50 is usually safe for light HTTP requests.
    full_market_scan(max_workers=30) 
    logger.info(f"Total time: {time.time() - start_time:.2f} seconds")

