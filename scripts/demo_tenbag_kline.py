"""Demo: 复跑腾讯日 K 线接口，确认模块二（股价趋势分析器）取数仍可用。

按计划「数据拉取接口 demo 实测先行」闸门：集成进 tenbag_trend_service 前，
先实测 _fetch_tencent_kline，打印真实返回结构交用户 review。

运行: python -m scripts.demo_tenbag_kline [symbol] [days]
默认 symbol=600519 (贵州茅台), days=365
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Windows 控制台 GBK 编码兜底，避免 emoji/中文报 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from backend.services.financial_service import _fetch_tencent_kline


def main():
    symbol = sys.argv[1] if len(sys.argv) > 1 else "600519"
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 365

    print(f"=== 腾讯日 K 线 demo: symbol={symbol}, days={days} ===")
    bars = _fetch_tencent_kline(symbol, days=days)

    if not bars:
        print("❌ 未取到任何 K 线数据")
        return 1

    print(f"✅ 取到 {len(bars)} 根日 K")
    print(f"首根: {bars[0]}")
    print(f"末根: {bars[-1]}")

    # 字段完整性核对
    sample = bars[-1]
    expected_keys = {"date", "open", "close", "high", "low", "volume"}
    missing = expected_keys - set(sample.keys())
    print(f"\n字段核对: 期望 {sorted(expected_keys)}")
    print(f"  缺失字段: {sorted(missing) if missing else '无'}")

    # 月线重采样可行性预演（模块二要用）
    months = sorted({b["date"][:7] for b in bars})
    print(f"\n月线重采样预演: 覆盖 {len(months)} 个月份")
    print(f"  月份样例: {months[:3]} ... {months[-3:]}")

    # 52 周高点回撤预演
    closes = [b["close"] for b in bars]
    last_close = closes[-1]
    high_52w = max(closes)
    drawdown = (last_close - high_52w) / high_52w * 100
    print(f"\n52 周高点回撤预演: 最新收盘={last_close}, 52w高点={high_52w}, 回撤={drawdown:.2f}%")

    print("\n=== demo 完成，请 review 字段结构是否满足模块二需求 ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
