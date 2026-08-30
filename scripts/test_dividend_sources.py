# -*- coding: utf-8 -*-
"""修复后验证：异常停发分红股应归零，正常分红股应保持合理数值。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backend.core.proxy_bypass  # noqa: F401
from backend.services.stock_service import get_stock_metrics

# 停发分红的问题股 / 正常分红股对照
CASES = {
    "300158": "振东制药(2021年10派27后停发)",
    "000761": "本钢板材(FY2021后停发)",
    "000002": "万科A(FY2022后停发)",
    "002622": "皓宸医疗(截图48%)",
    "600519": "贵州茅台(每年分红,对照)",
    "601088": "中国神华(高分红对照)",
    "000895": "双汇发展(高分红对照)",
}

for sym, desc in CASES.items():
    m = get_stock_metrics(sym)
    if m is None:
        print(f"{sym} {desc}: 行情获取失败")
        continue
    print(f"{sym} {desc}: 价={m['最新价']} 股息率={m['股息率']}% "
          f"每股分红={m['每股分红']} 备注={m['分红备注']}")
