
import requests
import traceback
from backend.services.stock_service import _no_proxy

def get_sina_index_spot(symbol):
    """
    Fetch index spot data from Sina.
    s_sh000001 = 上证指数
    s_sz399001 = 深证成指
    s_sz399006 = 创业板指
    s_sh000688 = 科创50
    s_sh000012 = 国债指数
    """
    url = f"http://hq.sinajs.cn/list={symbol}"
    headers = {"Referer": "http://finance.sina.com.cn"}
    
    try:
        with _no_proxy():
            r = requests.get(url, headers=headers, timeout=5)
        
        # var hq_str_s_sh000001="上证指数,3041.17,54.12,1.81,3662283,39634568";
        # Name, Current, Change Amount, Change %, Volume, Amount
        if r.status_code == 200:
            content = r.text.split('"')[1]
            parts = content.split(',')
            return {
                "name": parts[0],
                "current": float(parts[1]),
                "change_amount": float(parts[2]),
                "change_pct": float(parts[3]),
                "volume": float(parts[4]),
                "amount": float(parts[5])
            }
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return None

print("Testing Sina Indices...")
indices = ["s_sh000001", "s_sz399001", "s_sz399006", "s_sh000688", "s_sh000012"]
for idx in indices:
    data = get_sina_index_spot(idx)
    print(f"{idx}: {data}")
