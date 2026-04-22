
import akshare as ak
import traceback
import pandas as pd
from backend.services.stock_service import _no_proxy

# Set options
pd.set_option('display.max_rows', 100)
pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)

print("Testing Index Spot Data (Full Scan)...")
try:
    with _no_proxy():
        # Get main indices
        df_sh = ak.stock_zh_index_spot_em(symbol="上证系列指数")
        df_sz = ak.stock_zh_index_spot_em(symbol="深证系列指数")
        
    print("\nSH Indices (Head):")
    if df_sh is not None:
        print(df_sh[['代码', '名称', '最新价', '涨跌幅']].head())
        # Look for 国债
        bond_mask = df_sh['名称'].str.contains("国债")
        if bond_mask.any():
            print("\nFound Government Bond Indices in SH:")
            print(df_sh[bond_mask][['代码', '名称', '最新价', '涨跌幅']])
            
    print("\nSZ Indices (Head):")
    if df_sz is not None:
        print(df_sz[['代码', '名称', '最新价', '涨跌幅']].head())
        
except Exception as e:
    traceback.print_exc()
