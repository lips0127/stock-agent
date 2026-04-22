
import akshare as ak
import traceback

print("Testing Index Spot Data...")
try:
    # stock_zh_index_spot() or stock_zh_index_spot_em()
    # Shanghai: 000001
    # Shenzhen: 399001
    # ChiNext: 399006
    # STAR 50: 000688
    # Bond Index: 000012 (Shanghai Bond Index)
    
    # Try EM interface for indices
    df = ak.stock_zh_index_spot_em(symbol="上证指数") # Not specific
    if df is not None:
        print(df.head(2))
        print("Columns:", df.columns.tolist())
        
    print("\nFetching specific index: 000001 (SH)")
    # Usually we need to filter from the full list or use specific function
    # stock_zh_index_spot_em returns all indices? No, usually main ones.
    
    # Let's try searching for bond index
    bond_df = df[df['名称'].str.contains("债")]
    if not bond_df.empty:
        print("\nBond Indices Found:")
        print(bond_df[['代码', '名称', '最新价', '涨跌幅']].head())
        
except Exception as e:
    traceback.print_exc()
