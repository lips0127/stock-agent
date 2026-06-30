"""Demo: 实测 akshare 资产负债表接口，确认财报异动信号取数可用。

按计划「数据拉取接口 demo 实测先行」闸门：集成进 tenbag_anomaly_service 前，
先实测 ak.stock_balance_sheet_by_report_em（东方财富）+ sina 兜底，
打印真实列名 + 存货/合同负债/在建工程/应收账款/固定资产数值，交用户 review
字段归一化映射。

运行: python -m scripts.demo_tenbag_balance_sheet [symbol]
默认 symbol=600519 (贵州茅台)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import akshare as ak

from backend.services.stock_service import _no_proxy  # no-op，全局 proxy_bypass 生效
from backend.services.financial_service import _full_symbol  # 'sh600519' 小写前缀


def _em_symbol(symbol: str) -> str:
    """EM 接口要大写前缀：SH600519 / SZ000001 / BJ830799。"""
    f = _full_symbol(symbol)  # sh600519
    return f[:2].upper() + f[2:]


# 异动信号需要的字段（中文别名候选）
WANTED = {
    "存货": ["存货", "存货净额", "存货（净额）"],
    "合同负债": ["合同负债"],
    "在建工程": ["在建工程", "在建工程净额"],
    "应收账款": ["应收账款", "应收账款净额", "应收帐款"],
    "固定资产": ["固定资产", "固定资产净额", "固定资产合计"],
}


def _print_section(title: str):
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def _try_em(symbol: str):
    em_sym = _em_symbol(symbol)
    _print_section(f"[EM] stock_balance_sheet_by_report_em({em_sym})")
    try:
        with _no_proxy():
            df = ak.stock_balance_sheet_by_report_em(symbol=em_sym)
    except Exception as e:
        print(f"❌ EM 接口异常: {e}")
        return None
    if df is None or df.empty:
        print("❌ EM 返回空")
        return None
    print(f"✅ EM 返回 {len(df)} 行, {len(df.columns)} 列")
    print(f"列名: {list(df.columns)}")
    _dump_wanted(df, "EM")
    return df


def _try_sina(symbol: str):
    sina_stock = _full_symbol(symbol)  # sh600519
    _print_section(f"[Sina 兜底] stock_financial_report_sina(stock='{sina_stock}', symbol='资产负债表')")
    try:
        with _no_proxy():
            df = ak.stock_financial_report_sina(stock=sina_stock, symbol="资产负债表")
    except Exception as e:
        print(f"❌ Sina 接口异常: {e}")
        return None
    if df is None or df.empty:
        print("❌ Sina 返回空")
        return None
    print(f"✅ Sina 返回 {len(df)} 行, {len(df.columns)} 列")
    print(f"列名: {list(df.columns)[:40]}{'...' if len(df.columns) > 40 else ''}")
    _dump_wanted(df, "Sina")
    return df


def _dump_wanted(df, source: str):
    cols = set(df.columns)
    print(f"\n--- [{source}] 目标字段命中情况 ---")
    for label, candidates in WANTED.items():
        hit = [c for c in candidates if c in cols]
        if hit:
            col = hit[0]
            vals = df[col].head(3).tolist()
            print(f"  {label}: 命中列 '{col}'，前 3 期值 = {vals}")
        else:
            print(f"  {label}: ❌ 未命中（候选 {candidates} 均不在列名中）")


def main():
    symbol = sys.argv[1] if len(sys.argv) > 1 else "600519"
    print(f"### 资产负债表 demo: symbol={symbol} ###")
    em_df = _try_em(symbol)
    if em_df is None:
        print("\nEM 失败，尝试 Sina 兜底...")
        _try_sina(symbol)
    print("\n=== demo 完成，请 review：哪些字段可稳定取到、归一化映射如何定 ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
