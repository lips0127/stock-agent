"""Demo: 实测 akshare 现金流量表接口，确认财报异动「经营现金流」取数可用。

按计划「数据拉取接口 demo 实测先行」闸门：集成进 tenbag_anomaly_service 前，
先实测 ak.stock_cash_flow_sheet_by_report_em（东方财富），打印真实列名 +
经营活动现金流净额数值，交用户 review 字段归一化映射。

运行: python -m scripts.demo_tenbag_cash_flow [symbol]
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

from backend.services.stock_service import _no_proxy
from backend.services.financial_service import _full_symbol


def _em_symbol(symbol: str) -> str:
    f = _full_symbol(symbol)
    return f[:2].upper() + f[2:]


# 异动信号需要的现金流字段（EM 英文代号候选）
WANTED = {
    "经营活动现金流净额": [
        "NETCASH_OPERATE", "NETCASH_FROM_OPERATING",
        "NETCASH_OPERATE_ACT", "CCE_ADD_OPERATE",
    ],
}


def main():
    symbol = sys.argv[1] if len(sys.argv) > 1 else "600519"
    em_sym = _em_symbol(symbol)
    print(f"### 现金流量表 demo: symbol={symbol} (EM={em_sym}) ###")
    print(f"{'=' * 60}")

    try:
        with _no_proxy():
            df = ak.stock_cash_flow_sheet_by_report_em(symbol=em_sym)
    except Exception as e:
        print(f"❌ EM 现金流接口异常: {e}")
        return 1

    if df is None or df.empty:
        print("❌ EM 返回空")
        return 1

    print(f"✅ EM 返回 {len(df)} 行, {len(df.columns)} 列")
    # 只打印前 50 列避免刷屏
    cols = list(df.columns)
    print(f"列名(前 50): {cols[:50]}")
    if len(cols) > 50:
        print(f"  ... 共 {len(cols)} 列")

    print(f"\n--- 目标字段命中情况 ---")
    colset = set(cols)
    for label, candidates in WANTED.items():
        hit = [c for c in candidates if c in colset]
        if hit:
            col = hit[0]
            print(f"  {label}: ✅ 命中列 '{col}'")
            # 打印前 3 期报告日 + 数值
            for _, row in df.head(3).iterrows():
                rd = row.get("REPORT_DATE", "?")
                val = row.get(col)
                print(f"    {rd}: {val}")
        else:
            print(f"  {label}: ❌ 未命中候选 {candidates}")
            # 尝试模糊提示：列名含 OPERATE / 经营
            op_cols = [c for c in cols if "OPERATE" in c or "经营" in c]
            if op_cols:
                print(f"    含 OPERATE/经营 的列: {op_cols[:15]}")

    print("\n=== demo 完成，请 review：经营现金流净额字段名 + 是否有 _YOY 同比列 ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
