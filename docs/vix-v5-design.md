# VIX 模块 v5 重构设计书

## 概述

**目标**：将当前 VIX 情绪指数系统从"观察指标"升级为具备实战区分度的"连续情绪量化系统"。
**核心变更**：多 ETF 合成 VIX、Z-Score 动态阈值、PCR 接入、删除北向、连续化现货位置分、统一输出口径。

**修改涉及文件**：

| 层级 | 文件 | 操作 |
|------|------|------|
| 数据源 | `backend/data/vix_sources.py` | 修改 |
| 计算服务 | `backend/services/vix_service.py` | 重写 |
| 数据库 | `backend/core/database.py` | 修改 |
| API 路由 | `backend/api/routes/vix.py` | 少量修改 |
| 配置 | `backend/config.py` | 少量修改 |
| 前端仪表盘 | `frontend/src/components/VixGauge.vue` | 修改 |
| 前端图表 | `frontend/src/components/VixTrendChart.vue` | 修改 |
| 前端详情页 | `frontend/src/views/VixView.vue` | 修改 |
| 前端 API | `frontend/src/api/index.js` | 少量修改 |
| 文档 | `docs/SPEC.md` | 修改 |

---

## 第一部分：后端数据源层 (`backend/data/vix_sources.py`)

### 1.1 新增函数：`fetch_pcr(date_str)`

在文件末尾（`# ── 6) 现货位置信号` 之前）新增：

```python
# ─────────────────────────────────────────────────────────────────
# 5.5) 50ETF 期权 PCR（Put/Call Ratio）—— 2026-06 修复
# ─────────────────────────────────────────────────────────────────

def fetch_pcr(date_str: str) -> Optional[dict]:
    """从上交所每日期权统计获取 50ETF 的成交量 PCR 和持仓量 PCR。

    数据源：ak.option_daily_stats_sse(date=YYYYMMDD)
    返回：{"pcr_volume": float, "pcr_oi": float, "call_volume": int,
            "put_volume": int, "call_oi": int, "put_oi": int, "source": "sse"}
    失败返回 None。
    """
    date_compact = date_str.replace("-", "")
    try:
        with _no_proxy():
            df = ak.option_daily_stats_sse(date=date_compact)
    except Exception as e:
        logger.warning(f"fetch_pcr 失败: {e}")
        return None

    if df is None or df.empty:
        return None

    # 列名是中文：合约标的代码、合约标的名称、认购成交量、认沽成交量、
    # 认沽/认购、未平仓认购合约数、未平仓认沽合约数
    col_map = {}
    for c in df.columns:
        cs = str(c)
        if "合约标的代码" in cs:
            col_map["code"] = c
        elif "认购成交量" in cs:
            col_map["call_vol"] = c
        elif "认沽成交量" in cs:
            col_map["put_vol"] = c
        elif "认沽/认购" in cs:
            col_map["cp_rate"] = c
        elif "未平仓认购" in cs:
            col_map["call_oi"] = c
        elif "未平仓认沽" in cs:
            col_map["put_oi"] = c

    # 找 510050（上证50ETF）行
    row = df[df[col_map["code"]].astype(str).str.contains("510050")]
    if row.empty:
        logger.warning(f"fetch_pcr: 未找到 510050 行")
        return None

    r = row.iloc[0]
    call_vol = int(pd.to_numeric(r[col_map["call_vol"]], errors="coerce") or 0)
    put_vol = int(pd.to_numeric(r[col_map["put_vol"]], errors="coerce") or 0)
    call_oi = int(pd.to_numeric(r[col_map["call_oi"]], errors="coerce") or 0)
    put_oi = int(pd.to_numeric(r[col_map["put_oi"]], errors="coerce") or 0)

    pcr_volume = round(put_vol / call_vol, 3) if call_vol > 0 else None
    pcr_oi = round(put_oi / call_oi, 3) if call_oi > 0 else None

    if pcr_volume is None and pcr_oi is None:
        return None

    return {
        "pcr_volume": pcr_volume,
        "pcr_oi": pcr_oi,
        "call_volume": call_vol,
        "put_volume": put_vol,
        "call_oi": call_oi,
        "put_oi": put_oi,
        "source": "sse",
    }
```

### 1.2 新增函数：`fetch_multi_etf_qvix(days=60)`

紧接在 `fetch_50etf_qvix` 函数后面新增：

```python
def fetch_multi_etf_qvix(days: int = 60) -> Optional[dict]:
    """拉取 5 个 ETF 期权的 QVIX，返回 dict。

    5 个标的：50ETF(510050) / 300ETF(510300) / 500ETF(510500) /
             创业板ETF(159915) / 科创50ETF(588000)

    返回：
      {
        "50etf": 17.57,
        "300etf": 19.24,
        "500etf": 26.54,
        "cyb": 33.50,
        "kcb": 44.60,
        "synthetic": 28.29,   # 等权平均
        "count": 5,
        "source": "multi_etf",
      }
    任一 ETF 拉取失败不影响其他；全部失败返回 None。
    """
    fetchers = {
        "50etf":  (ak_index_option_50etf_qvix,),
        "300etf": (ak.index_option_300etf_qvix,),
        "500etf": (ak.index_option_500etf_qvix,),
        "cyb":    (ak.index_option_cyb_qvix,),
        "kcb":    (ak.index_option_kcb_qvix,),
    }

    result = {}
    for key, (fn,) in fetchers.items():
        try:
            with _no_proxy():
                df = fn()
            if df is not None and not df.empty:
                df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
                cutoff = (datetime.now() - timedelta(days=days + 5)).strftime("%Y-%m-%d")
                df = df[df["date"] >= cutoff]
                if not df.empty:
                    result[key] = float(df["iv_close"].iloc[-1])
        except Exception as e:
            logger.warning(f"fetch_multi_etf_qvix.{key} 失败: {e}")

    if not result:
        return None

    values = list(result.values())
    synthetic = round(sum(values) / len(values), 2)
    return {
        **result,
        "synthetic": synthetic,
        "count": len(values),
        "source": "multi_etf",
    }
```

### 1.3 删除/废弃：`fetch_north_net_flow`

**不删除函数本身**（保留代码以防未来恢复），但在 vix_service 层不再调用它。

---

## 第二部分：计算服务层 (`backend/services/vix_service.py`)

这是本次重构的核心。**建议直接重写整个文件**，而非增量修改。以下是完整的新文件内容。

### 2.1 文件头部（保持不变）

```python
"""
VIX 恐慌指数 + 恐惧贪婪综合指数 计算服务（v5, 2026-06-09）

v5 重构要点：
  1. 合成 VIX = 5 ETF QVIX 等权平均（50/300/500/创业板/科创）
  2. Sigmoid 中心改为滚动 Z-Score 自适应
  3. PCR 接入 option_daily_stats_sse 真实数据
  4. 北向资金删除（已停止披露）
  5. 现货位置分改为连续 sigmoid（消除 5 档跳变）
  6. 统一输出口径：composite_score + 滚动百分位

设计：
  * 合成 VIX = avg(50ETF_QVIX, 300ETF_QVIX, 500ETF_QVIX, 创业板_QVIX, 科创50_QVIX)
  * 恐惧贪婪综合指数 = 0-100，0=极度恐慌 100=极度贪婪
    构成（权重，v5 修订）：
      - 合成 VIX          35%
      - 已实现波动率变化  15%
      - PCR（Put/Call）   15%
      - 融资融券变化      15%
      - 涨跌停家数比      20%

  阈值（regime 分类，v5 改为滚动百分位）：
    VIX:  基于近 252 日滚动百分位
    FG :  基于近 252 日滚动百分位
    Composite: 基于近 252 日滚动百分位
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from backend.core.database import (
    upsert_vix_history, get_vix_latest, get_vix_history,
    compute_vix_percentile as db_compute_percentile,
)
from backend.data.vix_sources import (
    fetch_50etf_qvix, fetch_multi_etf_qvix, fetch_index_daily,
    fetch_pcr, fetch_margin_balance, fetch_limit_counts,
    HS300_SYMBOL, ZZ1000_SYMBOL, SH_COMPOSITE_SYMBOL,
    get_spot_signals_for_date,
)

logger = logging.getLogger(__name__)
```

### 2.2 已实现波动率算法（保持不变）

保留 `garman_klass_rv`、`close_to_close_rv`、`blended_rv` 三个函数，代码完全不变。此处省略，直接复制现有代码。

### 2.3 新增：Z-Score 计算

```python
# ─────────────────────────────────────────────────────────────────
# Z-Score 动态中心（v5 新增）
# ─────────────────────────────────────────────────────────────────

def compute_vix_zscore(current_vix: float) -> float:
    """计算当前合成 VIX 在近 252 个交易日的 Z-Score。

    Z = (current - μ_rolling) / σ_rolling

    从 vix_history 表取最近 252 天的合成 VIX 值，
    计算滚动均值和标准差，返回 Z 值。
    数据不足 20 天时返回 0.0（中性）。
    """
    rows = get_vix_history(252)
    history = [r.get("vix") for r in rows if r.get("vix") is not None]
    if len(history) < 20:
        return 0.0
    mu = np.mean(history)
    sigma = np.std(history)
    if sigma < 0.5:  # 波动率太低，Z 无意义
        return 0.0
    return round((current_vix - mu) / sigma, 3)
```

### 2.4 重写：各分量 → 0-100 映射函数

```python
# ─────────────────────────────────────────────────────────────────
# 恐惧贪婪综合指数 — 得分映射（v5 修订）
# ─────────────────────────────────────────────────────────────────

def _vix_to_score(vix: float, zscore: Optional[float] = None) -> float:
    """合成 VIX → 0-100 分数（VIX 高 = 恐慌 = 低分）。

    v5 改动：sigmoid 中心用 Z-Score 替代固定值 21。
    Z=0 时 score=50（中性），Z=+2 时 score≈12（恐慌），Z=-2 时 score≈88（贪婪）。
    当 Z-Score 不可用时回退到固定中心 21 的旧公式。
    """
    if vix is None or pd.isna(vix):
        return 50.0
    if zscore is not None and not pd.isna(zscore):
        # Z-Score 自适应：k=2 使得 Z∈[-2.5, +2.5] 覆盖大部分范围
        return float(100 / (1 + math.exp(2.0 * zscore)))
    # 回退：固定中心 21
    return float(100 / (1 + math.exp(0.24 * (vix - 21))))


def _pcr_to_score(pcr_volume: Optional[float], pcr_oi: Optional[float] = None) -> float:
    """PCR → 0-100（PCR 高 = 看空多 = 低分）。

    v5 改动：接入真实数据。使用成交量 PCR 为主，持仓量 PCR 为辅。
    A 股 50ETF 期权 PCR 中位约 0.85，范围约 0.5-1.5。
    """
    pcr = pcr_volume if pcr_volume is not None else pcr_oi
    if pcr is None or pd.isna(pcr):
        return 50.0
    return float(100 / (1 + math.exp(3.0 * (pcr - 0.85))))


def _margin_change_to_score(prev: Optional[float], curr: Optional[float]) -> float:
    """融资融券余额环比变化 → 0-100（增长 = 加杠杆 = 贪婪）。"""
    if prev is None or curr is None or prev <= 0:
        return 50.0
    change_pct = (curr - prev) / prev * 100
    score = 50 + change_pct * 8.33
    return max(5.0, min(95.0, score))


def _limit_ratio_to_score(zt: Optional[int], dt: Optional[int]) -> float:
    """涨跌停家数比 → 0-100。"""
    zt = zt or 0
    dt = dt or 0
    total = zt + dt
    if total == 0:
        return 50.0
    ratio = zt / total * 100
    return float(100 / (1 + math.exp(-0.08 * (ratio - 50))))


def _rv_change_to_score(curr_rv: Optional[float], prev_rv: Optional[float]) -> float:
    """已实现波动率变化 → 0-100（上升 = 恐慌）。"""
    if curr_rv is None:
        return 50.0
    if prev_rv is None or prev_rv <= 0:
        return 50.0
    change = (curr_rv - prev_rv) / prev_rv
    score = 50 - change * 150
    return max(5.0, min(95.0, score))
```

### 2.5 重写：`compute_fear_greed`（v5 权重）

```python
def compute_fear_greed(components: dict) -> float:
    """综合 5 个分项（v5：删除北向），加权得到 0-100 恐惧贪婪指数。

    v5 权重（删除北向 15%，重新分配）：
      - 合成 VIX          35%
      - RV 变化           15%
      - PCR                15%
      - 融资融券变化      15%
      - 涨跌停家数比      20%
    """
    weights = {
        "vix":     0.35,
        "rv_chg":  0.15,
        "pcr":     0.15,
        "margin":  0.15,
        "limit":   0.20,
    }
    scores = {
        "vix":    components.get("vix_score", 50.0),
        "rv_chg": components.get("rv_change_score", 50.0),
        "pcr":    components.get("pcr_score", 50.0),
        "margin": components.get("margin_change_score", 50.0),
        "limit":  components.get("limit_score", 50.0),
    }
    available = {
        "vix":    components.get("vix") is not None and components.get("vix_source") != "none",
        "rv_chg": components.get("rv_blended") is not None,
        "pcr":    components.get("pcr_volume") is not None or components.get("pcr_oi") is not None,
        "margin": components.get("margin_balance") is not None,
        "limit":  components.get("limit_source") == "real",
    }
    active_weight = sum(weights[k] for k, ok in available.items() if ok)
    if active_weight <= 0:
        components["fg_scores"] = scores
        components["fg_available_weights"] = {}
        return 50.0

    normalized_weights = {
        k: round(weights[k] / active_weight, 4)
        for k, ok in available.items()
        if ok
    }
    components["fg_scores"] = {k: round(v, 2) for k, v in scores.items()}
    components["fg_available_weights"] = normalized_weights
    total = sum(scores[k] * normalized_weights[k] for k in normalized_weights)
    return round(total, 1)
```

### 2.6 重写：阈值分类（v5 改为滚动百分位）

```python
# ─────────────────────────────────────────────────────────────────
# 阈值与 regime（v5 改为基于滚动百分位）
# ─────────────────────────────────────────────────────────────────

def classify_by_percentile(pct: Optional[float]) -> str:
    """基于滚动百分位输出 5 档 regime。

    阈值（对称）：
      0-10%   → extreme_fear   （比 90% 的日子都恐慌）
      10-30%  → fear
      30-70%  → neutral
      70-90%  → greed
      90-100% → extreme_greed
    """
    if pct is None or pd.isna(pct):
        return "unknown"
    if pct < 10:
        return "extreme_fear"
    if pct < 30:
        return "fear"
    if pct <= 70:
        return "neutral"
    if pct <= 90:
        return "greed"
    return "extreme_greed"


# 保留旧函数以兼容（标记 deprecated）
def classify_vix_regime(vix: Optional[float]) -> str:
    """[deprecated] 基于绝对值阈值，v5 不再使用。保留仅为兼容。"""
    if vix is None or pd.isna(vix):
        return "unknown"
    if vix < 14:  return "extreme_greed"
    if vix < 18:  return "greed"
    if vix < 24:  return "neutral"
    if vix < 32:  return "fear"
    return "extreme_fear"


def classify_fg_regime(fg: Optional[float]) -> str:
    """[deprecated] 基于绝对值阈值，v5 不再使用。保留仅为兼容。"""
    if fg is None or pd.isna(fg):
        return "unknown"
    if fg < 25:  return "extreme_fear"
    if fg < 45:  return "fear"
    if fg < 55:  return "neutral"
    if fg < 75:  return "greed"
    return "extreme_greed"
```

### 2.7 重写：`_spot_to_score`（连续化）

```python
# ─────────────────────────────────────────────────────────────────
# 现货位置维度（v5 连续化）
# ─────────────────────────────────────────────────────────────────

def _spot_to_score(spot: Optional[dict]) -> Optional[float]:
    """现货位置 → 0-100 分数（0=极恐/底部, 100=极贪/顶部）。

    v5 改动：用加权 sigmoid 替代 5 档离散 AND 逻辑。
    三个子信号各自 sigmoid 后加权平均，输出连续平滑的 0-100 曲线。

    子信号权重：
      - ma60_dev (偏离 60 日均线)   50%
      - mom_20d  (20 日动量)        30%
      - new_high_ratio (新高比例)   20%
    """
    if not spot:
        return None
    dev = spot.get("spot_ma60_dev")
    mom20 = spot.get("spot_mom_20d")
    hi20 = spot.get("spot_new_high_ratio")
    if dev is None or mom20 is None:
        return None

    # ma60_dev sigmoid：中心 0%，k=0.3
    # dev=-5% → ~18, dev=0% → 50, dev=+5% → 82
    dev_score = 100 / (1 + math.exp(-0.3 * dev))

    # mom_20d sigmoid：中心 0%，k=0.2
    # mom=-5% → ~27, mom=0% → 50, mom=+5% → 73
    mom_score = 100 / (1 + math.exp(-0.2 * mom20))

    # new_high_ratio 线性：0 → 30, 0.5 → 65, 1.0 → 95
    if hi20 is not None and not pd.isna(hi20):
        hi_score = 30 + hi20 * 65
    else:
        hi_score = 50.0

    score = 0.50 * dev_score + 0.30 * mom_score + 0.20 * hi_score
    return round(score, 1)
```

### 2.8 保持：`compute_composite_score` 和 `classify_composite_regime`

```python
def compute_composite_score(vix_fg: Optional[float], spot_score: Optional[float]) -> Optional[float]:
    """合成单一信号（VIX 恐惧贪婪 40% + 现货位置 60%）。

    任一维度为 None 时退回到另一维度。
    """
    if vix_fg is None and spot_score is None:
        return None
    if vix_fg is None:
        return round(spot_score, 1)
    if spot_score is None:
        return round(vix_fg, 1)
    return round(0.4 * vix_fg + 0.6 * spot_score, 1)


def classify_composite_regime(score: Optional[float]) -> str:
    """合成评分 → 5 档 regime（与 classify_by_percentile 一致）。"""
    if score is None or pd.isna(score):
        return "unknown"
    if score < 25:  return "extreme_fear"
    if score < 45:  return "fear"
    if score < 55:  return "neutral"
    if score < 75:  return "greed"
    return "extreme_greed"
```

### 2.9 重写：`VixSnapshot` dataclass

```python
@dataclass
class VixSnapshot:
    date: str
    # v5: synthetic_vix = 多 ETF 等权平均
    vix: Optional[float]
    vix_source: str
    vix_zscore: Optional[float]
    # v5: 各 ETF QVIX 明细
    iv_50etf: Optional[float]
    iv_300etf: Optional[float]
    iv_500etf: Optional[float]
    iv_cyb: Optional[float]
    iv_kcb: Optional[float]
    # v5: PCR 真实数据
    pcr_volume: Optional[float]
    pcr_oi: Optional[float]
    pcr_call_volume: Optional[int]
    pcr_put_volume: Optional[int]
    pcr_source: str
    # 已实现波动率
    rv_hs300: Optional[float]
    rv_zz1000: Optional[float]
    rv_blended: Optional[float]
    # 融资融券
    margin_balance: Optional[float]
    margin_source: str
    # 涨跌停
    limit_up_count: Optional[int]
    limit_down_count: Optional[int]
    limit_source: str
    # 综合得分
    fear_greed: Optional[float]
    composite_score: Optional[float]
    composite_regime: Optional[str]
    composite_percentile: Optional[float]  # v5 新增：composite 滚动百分位
    # 现货位置
    spot_close: Optional[float] = None
    spot_ma60_dev: Optional[float] = None
    spot_mom_5d: Optional[float] = None
    spot_mom_20d: Optional[float] = None
    spot_new_high_ratio: Optional[float] = None
    # 内部状态
    components: dict = None

    def to_db_payload(self) -> dict:
        return {
            "iv_50etf": self.iv_50etf,
            "iv_300etf": self.iv_300etf,
            "iv_500etf": self.iv_500etf,
            "iv_cyb": self.iv_cyb,
            "iv_kcb": self.iv_kcb,
            "pcr_volume": self.pcr_volume,
            "pcr_oi": self.pcr_oi,
            "pcr_call_volume": self.pcr_call_volume,
            "pcr_put_volume": self.pcr_put_volume,
            "pcr_source": self.pcr_source,
            "rv_hs300": self.rv_hs300,
            "rv_zz1000": self.rv_zz1000,
            "rv_blended": self.rv_blended,
            "margin_balance": self.margin_balance,
            "margin_source": self.margin_source,
            "limit_up_count": self.limit_up_count,
            "limit_down_count": self.limit_down_count,
            "limit_source": self.limit_source,
            "vix": self.vix,
            "vix_source": self.vix_source,
            "vix_zscore": self.vix_zscore,
            "fear_greed": self.fear_greed,
            "composite_score": self.composite_score,
            "composite_regime": self.composite_regime,
            "composite_percentile": self.composite_percentile,
            "components_json": json.dumps(self.components, ensure_ascii=False, default=str),
            "spot_close": self.spot_close,
            "spot_ma60_dev": self.spot_ma60_dev,
            "spot_mom_5d": self.spot_mom_5d,
            "spot_mom_20d": self.spot_mom_20d,
            "spot_new_high_ratio": self.spot_new_high_ratio,
        }
```

### 2.10 重写：`compute_today_snapshot`（核心函数）

```python
def compute_today_snapshot(date_str: Optional[str] = None) -> Optional[VixSnapshot]:
    """计算并返回某日 VIX 快照（v5 重写）。

    核心流程：
      1. 拉取 5 个 ETF QVIX → 等权合成 VIX
      2. 计算 Z-Score（动态中心）
      3. 拉取 PCR 真实数据
      4. 拉取 RV / 融资 / 涨跌停（不变）
      5. 各分量 → 0-100 分 → 加权得 FG
      6. 现货位置 → 连续 spot_score
      7. composite = 0.4×FG + 0.6×spot
      8. 计算 composite 滚动百分位
      9. 按百分位输出 regime
    """
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    days_lookback = 60
    try:
        target_dt = datetime.strptime(date_str, "%Y-%m-%d")
        days_lookback = max(60, (datetime.now() - target_dt).days + 30)
    except Exception:
        pass

    components: dict = {}
    components["_target_date"] = date_str
    components["_version"] = "v5"

    # ── 1) 多 ETF QVIX → 合成 VIX ──
    multi_qvix = fetch_multi_etf_qvix(days=days_lookback)
    if multi_qvix:
        components["iv_50etf"] = multi_qvix.get("50etf")
        components["iv_300etf"] = multi_qvix.get("300etf")
        components["iv_500etf"] = multi_qvix.get("500etf")
        components["iv_cyb"] = multi_qvix.get("cyb")
        components["iv_kcb"] = multi_qvix.get("kcb")
        synthetic_vix = multi_qvix["synthetic"]
        vix_source = "multi_etf"
        etf_count = multi_qvix["count"]
    else:
        # 全部 ETF QVIX 失败，回退到单 50ETF QVIX
        qvix_df = fetch_50etf_qvix(days=days_lookback)
        if qvix_df is not None and not qvix_df.empty:
            synthetic_vix = float(qvix_df["iv_close"].iloc[-1])
            components["iv_50etf"] = synthetic_vix
            vix_source = "50etf_only"
            etf_count = 1
        else:
            synthetic_vix = None
            vix_source = "none"
            etf_count = 0
    components["vix"] = synthetic_vix
    components["vix_source"] = vix_source
    components["vix_etf_count"] = etf_count

    # ── 2) Z-Score ──
    if synthetic_vix is not None:
        zscore = compute_vix_zscore(synthetic_vix)
    else:
        zscore = None
    components["vix_zscore"] = zscore

    # ── 3) VIX → 0-100 分 ──
    vix_score = _vix_to_score(synthetic_vix, zscore)
    components["vix_score"] = vix_score

    # ── 4) 已实现波动率 ──
    hs300_df = fetch_index_daily(HS300_SYMBOL, days=90)
    zz1000_df = fetch_index_daily(ZZ1000_SYMBOL, days=90)
    rv_hs300 = garman_klass_rv(hs300_df, window=30) if hs300_df is not None else None
    rv_zz1000 = garman_klass_rv(zz1000_df, window=30) if zz1000_df is not None else None
    rv_blended = blended_rv(rv_hs300, rv_zz1000)
    rv_hs300_prev = garman_klass_rv(hs300_df, window=60) if hs300_df is not None else None
    rv_change_score = _rv_change_to_score(rv_blended, rv_hs300_prev)
    components["rv_change_score"] = rv_change_score
    components["rv_hs300"] = rv_hs300
    components["rv_zz1000"] = rv_zz1000
    components["rv_blended"] = rv_blended

    # ── 5) PCR（v5 真实数据） ──
    pcr_data = fetch_pcr(date_str)
    if pcr_data:
        components["pcr_volume"] = pcr_data["pcr_volume"]
        components["pcr_oi"] = pcr_data["pcr_oi"]
        components["pcr_call_volume"] = pcr_data["call_volume"]
        components["pcr_put_volume"] = pcr_data["put_volume"]
        components["pcr_call_oi"] = pcr_data["call_oi"]
        components["pcr_put_oi"] = pcr_data["put_oi"]
        components["pcr_source"] = "sse"
    else:
        components["pcr_volume"] = None
        components["pcr_oi"] = None
        components["pcr_source"] = "unavailable"
    pcr_score = _pcr_to_score(
        components.get("pcr_volume"),
        components.get("pcr_oi"),
    )
    components["pcr_score"] = pcr_score

    # ── 6) 融资融券 ──
    margin = fetch_margin_balance()
    if margin:
        components["margin_balance"] = margin["margin_balance"]
        components["margin_source"] = "real"
    else:
        components["margin_balance"] = None
        components["margin_source"] = "unavailable"
    prev = get_vix_latest()
    prev_margin = prev.get("margin_balance") if prev else None
    components["margin_change_score"] = _margin_change_to_score(
        prev_margin, components.get("margin_balance")
    )

    # ── 7) 涨跌停 ──
    limits = fetch_limit_counts(date_str)
    if limits:
        components["limit_up_count"] = limits["limit_up_count"]
        components["limit_down_count"] = limits["limit_down_count"]
        components["limit_source"] = "real"
    else:
        components["limit_up_count"] = 0
        components["limit_down_count"] = 0
        components["limit_source"] = "unavailable"
    limit_score = _limit_ratio_to_score(
        components.get("limit_up_count"),
        components.get("limit_down_count"),
    )
    components["limit_score"] = limit_score

    # ── 8) 恐惧贪婪综合指数 ──
    fg = compute_fear_greed(components)

    # ── 9) 现货位置信号 ──
    spot = get_spot_signals_for_date(date_str, days=400)
    if spot:
        components["spot"] = spot
        components["spot_source"] = "real"
    else:
        components["spot"] = None
        components["spot_source"] = "unavailable"
    spot_score = _spot_to_score(spot)
    components["spot_score"] = spot_score

    # ── 10) 合成 + 百分位 + regime ──
    composite = compute_composite_score(fg, spot_score)
    components["composite_score"] = composite

    # composite 滚动百分位（基于 vix_history 中的 composite_score 历史）
    composite_pct = _compute_composite_percentile(composite)
    components["composite_percentile"] = composite_pct

    # regime 基于百分位
    composite_regime = classify_by_percentile(composite_pct)

    return VixSnapshot(
        date=date_str,
        vix=synthetic_vix,
        vix_source=vix_source,
        vix_zscore=zscore,
        iv_50etf=components.get("iv_50etf"),
        iv_300etf=components.get("iv_300etf"),
        iv_500etf=components.get("iv_500etf"),
        iv_cyb=components.get("iv_cyb"),
        iv_kcb=components.get("iv_kcb"),
        pcr_volume=components.get("pcr_volume"),
        pcr_oi=components.get("pcr_oi"),
        pcr_call_volume=components.get("pcr_call_volume"),
        pcr_put_volume=components.get("pcr_put_volume"),
        pcr_source=components.get("pcr_source", "unavailable"),
        rv_hs300=rv_hs300,
        rv_zz1000=rv_zz1000,
        rv_blended=rv_blended,
        margin_balance=components.get("margin_balance"),
        margin_source=components.get("margin_source", "unavailable"),
        limit_up_count=components.get("limit_up_count"),
        limit_down_count=components.get("limit_down_count"),
        limit_source=components.get("limit_source", "unavailable"),
        fear_greed=fg,
        composite_score=composite,
        composite_regime=composite_regime,
        composite_percentile=composite_pct,
        spot_close=spot.get("spot_close") if spot else None,
        spot_ma60_dev=spot.get("spot_ma60_dev") if spot else None,
        spot_mom_5d=spot.get("spot_mom_5d") if spot else None,
        spot_mom_20d=spot.get("spot_mom_20d") if spot else None,
        spot_new_high_ratio=spot.get("spot_new_high_ratio") if spot else None,
        components=components,
    )
```

### 2.11 新增：`_compute_composite_percentile`

```python
def _compute_composite_percentile(composite: Optional[float], days: int = 252) -> Optional[float]:
    """计算当前 composite 在近 N 天历史 composite 中的百分位。

    从 vix_history 表取最近 N 天的 composite_score 值。
    """
    if composite is None:
        return None
    rows = get_vix_history(days)
    history = [r.get("composite_score") for r in rows if r.get("composite_score") is not None]
    if len(history) < 20:
        return 50.0
    below = sum(1 for v in history if v <= composite)
    return round(below / len(history) * 100, 1)
```

### 2.12 重写：`snapshot_to_api`

```python
def snapshot_to_api(snap_dict: dict) -> dict:
    """DB 行 → API JSON（v5 结构）。"""
    if not snap_dict:
        return {}
    components = {}
    if snap_dict.get("components_json"):
        try:
            components = json.loads(snap_dict["components_json"])
        except Exception:
            pass

    def _is_real(source) -> bool:
        if source is None:
            return False
        return str(source) in ("real", "iv", "hist", "min", "summary",
                                "rv_fallback", "multi_etf", "50etf_only", "sse")

    quality_signals = {
        "vix":     _is_real(components.get("vix_source", "")),
        "rv_chg":  snap_dict.get("rv_hs300") is not None,
        "pcr":     _is_real(components.get("pcr_source", "")),
        "margin":  _is_real(components.get("margin_source", "")),
        "limit":   _is_real(components.get("limit_source", "")),
        "spot":    _is_real(components.get("spot_source", "")),
    }
    real_count = sum(1 for v in quality_signals.values() if v)

    return {
        "date":                snap_dict.get("date"),
        # v5: 合成 VIX
        "vix":                 snap_dict.get("vix"),
        "vix_source":          components.get("vix_source", "unknown"),
        "vix_zscore":          snap_dict.get("vix_zscore"),
        "vix_etf_count":       components.get("vix_etf_count", 0),
        # v5: 各 ETF IV 明细
        "iv_50etf":            snap_dict.get("iv_50etf"),
        "iv_300etf":           snap_dict.get("iv_300etf"),
        "iv_500etf":           snap_dict.get("iv_500etf"),
        "iv_cyb":              snap_dict.get("iv_cyb"),
        "iv_kcb":              snap_dict.get("iv_kcb"),
        # v5: PCR
        "pcr_volume":          snap_dict.get("pcr_volume"),
        "pcr_oi":              snap_dict.get("pcr_oi"),
        "pcr_call_volume":     snap_dict.get("pcr_call_volume"),
        "pcr_put_volume":      snap_dict.get("pcr_put_volume"),
        "pcr_source":          components.get("pcr_source", "unknown"),
        # RV
        "rv_hs300":            snap_dict.get("rv_hs300"),
        "rv_zz1000":           snap_dict.get("rv_zz1000"),
        "rv_blended":          snap_dict.get("rv_blended"),
        # 融资融券
        "margin_balance":      snap_dict.get("margin_balance"),
        "margin_source":       components.get("margin_source", "unknown"),
        # 涨跌停
        "limit_up_count":      snap_dict.get("limit_up_count"),
        "limit_down_count":    snap_dict.get("limit_down_count"),
        "limit_source":        components.get("limit_source", "unknown"),
        # 综合得分（v5 统一输出）
        "fear_greed":          snap_dict.get("fear_greed"),
        "composite_score":     snap_dict.get("composite_score"),
        "composite_regime":    snap_dict.get("composite_regime"),
        "composite_percentile": snap_dict.get("composite_percentile"),
        # v5: regime = composite_regime（统一标签）
        "regime":              snap_dict.get("composite_regime"),
        "vix_only_regime":     snap_dict.get("regime"),  # 保留兼容
        # 百分位（基于 composite，不再基于 vix）
        "percentile":          snap_dict.get("composite_percentile"),
        # 现货位置
        "spot": {
            "close":          snap_dict.get("spot_close"),
            "ma60_dev":       snap_dict.get("spot_ma60_dev"),
            "mom_5d":         snap_dict.get("spot_mom_5d"),
            "mom_20d":        snap_dict.get("spot_mom_20d"),
            "new_high_ratio": snap_dict.get("spot_new_high_ratio"),
            "source":         components.get("spot_source", "unknown"),
        },
        # composite 明细
        "composite": {
            "score":     snap_dict.get("composite_score"),
            "regime":    snap_dict.get("composite_regime"),
            "percentile": snap_dict.get("composite_percentile"),
            "vix_fg":    snap_dict.get("fear_greed"),
            "spot_score": components.get("spot_score"),
        },
        # 数据质量（v5：5 分量 + 现货 = 6 总）
        "data_quality": {
            "total":   6,
            "real":    real_count,
            "missing": 6 - real_count,
            "signals": quality_signals,
        },
        "components": components,
    }
```

### 2.13 保持不变的函数

以下函数代码**完全不变**，直接从现有文件复制：
- `compute_and_store(date_str)` — 保持不变
- `backfill_vix_history(days, skip_existing)` — 保持不变
- `get_backfill_status()` — 保持不变
- `_is_trading_day(date_str)` — 保持不变
- `get_latest_api()` — 保持不变
- `get_history_api(days)` — 保持不变

---

## 第三部分：数据库层 (`backend/core/database.py`)

### 3.1 vix_history 表新增列

在 `init_db()` 中，`vix_history` 表的 CREATE TABLE 语句需要更新。由于现有表已存在，使用 ALTER TABLE 幂等迁移。

在文件末尾（或 init_db 中 vix_history 建表后）添加：

```python
# v5 VIX 重构列迁移（幂等）
_vix_v5_columns = [
    ("iv_300etf", "REAL"),
    ("iv_500etf", "REAL"),
    ("iv_cyb", "REAL"),
    ("iv_kcb", "REAL"),
    ("pcr_volume", "REAL"),
    ("pcr_oi", "REAL"),
    ("pcr_call_volume", "INTEGER"),
    ("pcr_put_volume", "INTEGER"),
    ("pcr_source", "TEXT"),
    ("vix_zscore", "REAL"),
    ("vix_source", "TEXT"),
    ("composite_percentile", "REAL"),
    ("margin_source", "TEXT"),
    ("limit_source", "TEXT"),
]
for col_name, col_type in _vix_v5_columns:
    try:
        conn.execute(f"ALTER TABLE vix_history ADD COLUMN {col_name} {col_type}")
    except sqlite3.OperationalError:
        pass  # 列已存在
```

### 3.2 新增函数：`get_vix_history_for_zscore`

```python
def get_vix_history_for_zscore(days: int = 252) -> list[float]:
    """取最近 N 天的 vix 值（仅数值列表），用于 Z-Score 计算。"""
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT vix FROM vix_history ORDER BY date DESC LIMIT ?",
            (days,),
        )
        return [r[0] for r in cur.fetchall() if r[0] is not None]
```

### 3.3 保持：`compute_vix_percentile`（不变）

---

## 第四部分：API 路由层 (`backend/api/routes/vix.py`)

### 4.1 改动

**不需要改动**。现有端点 `/api/vix`、`/api/vix/history`、`/api/vix/recompute`、`/api/vix/backfill` 全部保持不变。它们只是透传 `vix_service` 的输出，新的 JSON 结构会自动反映。

---

## 第五部分：前端 API 客户端 (`frontend/src/api/index.js`)

### 5.1 改动

**不需要改动**。现有 `getVix()`、`getVixHistory()` 等函数保持不变。前端组件根据新的 JSON 字段名调整即可。

---

## 第六部分：前端仪表盘组件 (`frontend/src/components/VixGauge.vue`)

### 6.1 改动要点

当前 VixGauge 显示 `value`（VIX 数值）和 `regime`（VIX 的 5 档标签）。v5 需要改为显示 **composite_score** 和 **composite_regime**。

具体改动：

1. **Props 语义调整**：
   - `value` → 改为 composite_score（0-100 分）
   - `regime` → 改为 composite_regime
   - `percentile` → 改为 composite_percentile
   - `min` 默认值从 10 改为 0
   - `max` 默认值从 40 改为 100
   - 新增 prop `vix: Number`（合成 VIX 原始值，显示在副标题）
   - 新增 prop `vixZscore: Number`

2. **刻度标记调整**：
   ```javascript
   const ticks = computed(() => {
     const stops = [
       { value: 10, color: '#dc2626' },   // extreme_fear 边界
       { value: 30, color: '#f97316' },   // fear 边界
       { value: 70, color: '#facc15' },   // greed 边界
       { value: 90, color: '#10b981' },   // extreme_greed 边界
     ]
     // ... 计算坐标不变
   })
   ```

3. **中心数值显示调整**：
   ```html
   <div class="vix-gauge__value">
     <span class="vix-gauge__num">{{ value != null ? value.toFixed(1) : '—' }}</span>
     <span class="vix-gauge__suffix">分</span>
   </div>
   <div class="vix-gauge__vix-sub">
     合成VIX {{ vix != null ? vix.toFixed(2) : '—' }}
     <span v-if="vixZscore != null" class="vix-gauge__zscore">
       Z={{ vixZscore.toFixed(1) }}
     </span>
   </div>
   ```

4. **颜色映射调整**（指针颜色基于百分位而非绝对值）：
   ```javascript
   const pointerColor = computed(() => {
     if (props.value == null) return '#a1a1aa'
     if (props.value < 10) return '#dc2626'   // extreme_fear
     if (props.value < 30) return '#f97316'   // fear
     if (props.value <= 70) return '#facc15'  // neutral
     if (props.value <= 90) return '#84cc16'  // greed
     return '#10b981'                          // extreme_greed
   })
   ```

5. **regime 标签颜色调整**：保持现有的 `regimeKey` 和 `regimeLabel` 逻辑，但 `extreme_greed` 的背景色改为红色系（顶部风险），`extreme_fear` 改为绿色系（底部机会）。

   ```javascript
   // 注意：这里"贪婪"是风险信号，"恐慌"是机会信号
   // 与旧版的颜色语义相反
   ```

6. **模板新增**：在 `.vix-gauge__readout` 中百分位下方添加：
   ```html
   <div v-if="vix != null" class="vix-gauge__vix-detail">
     <span>合成VIX</span>
     <strong>{{ vix.toFixed(2) }}</strong>
   </div>
   ```

7. **CSS 新增**：
   ```css
   .vix-gauge__vix-sub {
     font-size: var(--text-xs);
     color: var(--color-text-tertiary);
     margin-top: 2px;
   }
   .vix-gauge__zscore {
     margin-left: 6px;
     font-family: var(--font-mono);
     color: var(--color-text-secondary);
   }
   .vix-gauge__vix-detail {
     margin-top: var(--space-2);
     font-size: var(--text-xs);
     color: var(--color-text-tertiary);
     display: flex;
     gap: 6px;
     justify-content: center;
     align-items: baseline;
   }
   .vix-gauge__vix-detail strong {
     color: var(--color-text-primary);
     font-weight: var(--weight-semibold);
     font-variant-numeric: tabular-nums;
   }
   ```

---

## 第七部分：前端图表组件 (`frontend/src/components/VixTrendChart.vue`)

### 7.1 改动要点

1. **新增 series**：除了现有的 VIX / FG / Composite 三条线，新增：
   - `composite_percentile`（右 Y 轴，0-100%）
   - 移除 `fear_greed` 线或将其标记为"辅助参考"

2. **tooltip 更新**：显示字段调整为新 JSON 结构：
   ```
   日期: 2026-06-05
   合成VIX: 20.15 (Z=+0.3)
   FG: 58.2
   综合位置: 62.1 (百分位 68%)
   情绪: 贪婪
   ```

3. **Y 轴调整**：
   - 左轴：VIX 值（范围自适应，通常 10-50）
   - 右轴：0-100（composite_score / composite_percentile 共用）

4. **阈值带更新**：基于百分位的 5 档色带（10/30/70/90），替代旧版 VIX 绝对值色带。

5. **series 数据映射更新**（以 ECharts 配置为例）：
   ```javascript
   // 从 API 数据构建 series
   const compositeData = history.map(d => [d.date, d.composite_score])
   const percentileData = history.map(d => [d.date, d.composite_percentile])
   const vixData = history.map(d => [d.date, d.vix])
   const fgData = history.map(d => [d.date, d.fear_greed])
   ```

---

## 第八部分：前端详情页 (`frontend/src/views/VixView.vue`)

### 8.1 顶部 StatCard 调整

当前 5 个 StatCard：VIX / 恐惧贪婪 / 百分位 / 涨跌停比 / 综合位置

改为 5 个 StatCard：
1. **合成 VIX**：大数字 = 合成 VIX 值（如 20.15），副标题 = Z-Score + ETF 数量（如 "Z=+0.3 · 5 ETF"），tone = 根据百分位动态
2. **综合位置**：大数字 = composite_score（如 62.1），副标题 = "0-100 分"，tone = 根据 regime
3. **滚动百分位**：大数字 = composite_percentile（如 68%），副标题 = "近 252 日排位"，tone = 根据百分位
4. **恐惧贪婪**：大数字 = fear_greed（如 58.2），副标题 = "FG 综合分"
5. **涨跌停比**：保持不变

### 8.2 新增："多 ETF 隐含波动率"卡片

一张 ModernCard（bordered），展示 5 个 ETF 的 IV 条形图/数值：

```html
<div class="etf-iv-grid">
  <div v-for="etf in etfIvList" :key="etf.label" class="etf-iv-item">
    <span class="etf-iv-label">{{ etf.label }}</span>
    <div class="etf-iv-bar-wrap">
      <div class="etf-iv-bar" :style="{ width: etf.pct + '%', background: etf.color }" />
    </div>
    <span class="etf-iv-value">{{ etf.value?.toFixed(2) || '—' }}</span>
  </div>
</div>
```

数据来源：
```javascript
const etfIvList = computed(() => [
  { label: '50ETF',  value: latest.value?.iv_50etf,  pct: (latest.value?.iv_50etf  || 0) / 50 * 100, color: '#6366f1' },
  { label: '300ETF', value: latest.value?.iv_300etf, pct: (latest.value?.iv_300etf || 0) / 50 * 100, color: '#8b5cf6' },
  { label: '500ETF', value: latest.value?.iv_500etf, pct: (latest.value?.iv_500etf || 0) / 50 * 100, color: '#a78bfa' },
  { label: '创业板',  value: latest.value?.iv_cyb,    pct: (latest.value?.iv_cyb    || 0) / 50 * 100, color: '#c4b5fd' },
  { label: '科创50', value: latest.value?.iv_kcb,    pct: (latest.value?.iv_kcb    || 0) / 50 * 100, color: '#ddd6fe' },
])
```

### 8.3 修改："市场位置信号"卡片

将 4 个子信号更新为 v5 的连续化版本：

- `ma60_dev`、`mom_20d`、`new_high_ratio` 的值不变
- 底部 verdict 横条的文案基于 **composite_regime**（v5 的百分位阈值），而非旧版离散档

### 8.4 修改："分项明细"卡片

从 6 格改为 5 格（删除北向，PCR 改为真实数据）：

1. **合成 VIX**：大数字 = 合成 VIX + Z-Score 标签
2. **RV 波动率**：HS300 + ZZ1000 两个值
3. **PCR**：成交量 PCR + 持仓量 PCR + call/put 成交量
4. **融资余额**：余额 + 环比变化
5. **涨跌停**：涨停数 / 跌停数

### 8.5 data_quality 横幅更新

```html
<div class="quality-bar">
  <span>数据完整度：{{ quality.real }}/{{ quality.total }}</span>
  <span v-for="sig in missingSignals" :key="sig" class="quality-chip quality-chip--missing">
    {{ sig }}
  </span>
</div>
```

`quality.total` 现在是 6（5 分量 + 现货位置），不再是旧版的 7。

---

## 第九部分：SPEC 文档更新 (`docs/SPEC.md`)

### 9.1 需要修改的章节

1. **§11** (VIX 恐慌指数 v2)：更新组成成分表、权重、数据源说明
2. **§11A** (v3 现货位置)：更新 `_spot_to_score` 算法描述
3. **§11B** (v4 离散度增强)：新增 v5 重构说明
4. **§11.2** 组成成分与权重表：更新为新权重
5. **§11.3** 数据源表：新增 PCR 数据源、多 ETF QVIX
6. **§11.4** 计算服务表：新增/修改函数列表
7. **§11.5** 数据库 schema：新增列
8. **§11.6** API 响应示例：更新为新 JSON 结构

### 9.2 具体修改内容

在 §11B 之后新增 §11C：

```markdown
## 11C. VIX 算法 v5 — 重构（2026-06-09）

### 11C.1 设计动机

v4 及之前版本存在以下结构性问题：
1. VIX 主体仅依赖 50ETF QVIX，样本偏差严重
2. 阈值使用硬编码绝对值（VIX<14 极贪），不随市场状态自适应
3. PCR 固定为 None（未发现 `option_daily_stats_sse` 接口）
4. 北向资金已停止披露但仍占 15% 权重
5. 现货位置分使用 5 档离散 AND 逻辑，输出跳变
6. 多个标签口径不一致（regime 用 composite，percentile 用 VIX）

### 11C.2 核心变更

| # | 变更 | 旧 | 新 |
|---|------|-----|-----|
| 1 | 合成 VIX | 50ETF QVIX 单一值 | 5 ETF (50/300/500/创业板/科创) 等权平均 |
| 2 | Sigmoid 中心 | 固定值 21 | 滚动 Z-Score 自适应 |
| 3 | PCR 数据 | 永远 None | `option_daily_stats_sse` 真实数据 |
| 4 | 北向资金 | 权重 15% | 删除 |
| 5 | 现货位置分 | 5 档离散 AND | 3 子信号加权 sigmoid 连续映射 |
| 6 | 统一输出 | 多重标签口径 | composite_score + 滚动百分位 |
| 7 | 阈值 | 硬编码绝对值 | 基于近 252 日滚动百分位 |

### 11C.3 新权重表

| 分量 | 权重 | 数据源 |
|------|------|--------|
| 合成 VIX | 35% | 5 ETF QVIX 等权 |
| RV 变化 | 15% | HS300+ZZ1000 Garman-Klass |
| PCR | 15% | 上交所 option_daily_stats_sse |
| 融资融券 | 15% | 沪深两市 macro_china_market_margin |
| 涨跌停比 | 20% | 涨停池+跌停池 |

### 11C.4 新 Regime 阈值（基于滚动百分位）

| 百分位 | Regime | 策略含义 |
|--------|--------|----------|
| 0-10% | extreme_fear | 市场极度恐慌，关注买入机会 |
| 10-30% | fear | 偏恐慌 |
| 30-70% | neutral | 中性震荡 |
| 70-90% | greed | 偏贪婪 |
| 90-100% | extreme_greed | 极度贪婪，警惕顶部风险 |
```

---

## 第十部分：实施步骤（按顺序执行）

### Step 1: 修改 `backend/data/vix_sources.py`
- 在 `fetch_50etf_qvix` 后面新增 `fetch_multi_etf_qvix`
- 在 `# 5) 涨跌停家数` 后面新增 `fetch_pcr`
- 在文件末尾的 import 区域确认所有 QVIX 函数已导入
- **验证**：`python -c "from backend.data.vix_sources import fetch_multi_etf_qvix, fetch_pcr; print(fetch_multi_etf_qvix()); print(fetch_pcr('2026-06-05'))"`

### Step 2: 修改 `backend/core/database.py`
- 在 `init_db()` 中 vix_history 建表后添加 ALTER TABLE 迁移代码
- 新增 `get_vix_history_for_zscore` 函数
- **验证**：重启后端，确认无 SQL 报错

### Step 3: 重写 `backend/services/vix_service.py`
- 用新代码完整替换旧文件
- 特别注意保留 `compute_and_store`、`backfill_vix_history`、`get_backfill_status`、`_is_trading_day`、`get_latest_api`、`get_history_api` 不变
- **验证**：`POST /api/vix/recompute` → `GET /api/vix` 返回新 JSON 结构

### Step 4: 回填历史数据
```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"days": 250, "skip_existing": false}' \
  http://localhost:5000/api/vix/backfill
```
轮询 `GET /api/vix/backfill_status` 直到完成。

### Step 5: 修改前端 `VixGauge.vue`
- 按第六部分的改动清单逐项修改
- **验证**：Dashboard VIX 卡片显示 composite_score（0-100）而非旧 VIX 值

### Step 6: 修改前端 `VixTrendChart.vue`
- 按第七部分修改
- **验证**：`/vix` 详情页趋势图显示新 series

### Step 7: 修改前端 `VixView.vue`
- 按第八部分修改
- **验证**：`/vix` 详情页所有卡片、图表、数据质量横幅正常

### Step 8: 更新 `docs/SPEC.md`
- 按第九部分修改
- 将旧 §11、§11A、§11B 的内容合并为 v5 版本

---

## 第十一部分：验证清单

### 后端验证

```bash
TOKEN=$(curl -s -X POST http://localhost:5000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' | python -c "import json,sys;print(json.load(sys.stdin)['token'])")

# 1. 最新快照
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/vix | python -m json.tool

# 预期响应包含以下新字段：
#   - vix: 合成 VIX 值（约 20-30）
#   - vix_source: "multi_etf" 或 "50etf_only"
#   - vix_zscore: Z 值（如 0.35）
#   - vix_etf_count: 5（或回退时 1）
#   - iv_50etf, iv_300etf, iv_500etf, iv_cyb, iv_kcb
#   - pcr_volume, pcr_oi（非 null）
#   - pcr_source: "sse"（非 "unavailable"）
#   - composite_score, composite_regime, composite_percentile
#   - data_quality.signals.pcr: true（不再是 false）
#   - 不应出现 north_net, north_source

# 2. 确认 PCR 不再 unavailable
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/vix | python -c "import json,sys;d=json.load(sys.stdin);print('PCR source:', d.get('pcr_source'));print('PCR volume:', d.get('pcr_volume'))"
# 预期: PCR source: sse, PCR volume: 0.7~1.2

# 3. 确认北向已删除
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/vix | python -c "import json,sys;d=json.load(sys.stdin);print('north_net' in d, 'north_source' in d)"
# 预期: False False

# 4. 确认 composite_percentile 在 0-100 范围
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/vix | python -c "import json,sys;d=json.load(sys.stdin);p=d.get('composite_percentile');print('percentile:', p, 'in 0-100:', 0 <= p <= 100 if p else 'N/A')"
# 预期: 0-100 之间

# 5. 历史数据
curl -s -H "Authorization: Bearer $TOKEN" "http://localhost:5000/api/vix/history?days=7" | python -c "import json,sys;d=json.load(sys.stdin);print('total:', len(d['data']));[print(r['date'], r['composite_score'], r['composite_regime']) for r in d['data'][:3]]"
```

### 前端验证

1. 打开 `/dashboard` → VIX 卡片显示 composite_score（0-100）+ 合成 VIX 小字 + Z-Score
2. 打开 `/vix` → 顶部 5 个 StatCard 全部有数据
3. `/vix` → "多 ETF 隐含波动率"卡片显示 5 条 IV 柱状条
4. `/vix` → "市场位置信号"卡片显示连续化的 3 个子信号
5. `/vix` → 趋势图有 composite_score + composite_percentile 两条线
6. `/vix` → data_quality 横幅显示 `5/6` 或 `6/6`（不再包含 north）
7. `/vix` → 分项明细 PCR 卡片显示真实 PCR 值（成交量 + 持仓量）
8. `/vix` → 分项明细不再有"北向资金"卡片

---

## 第十二部分：回滚方案

如果 v5 上线后出现问题，回滚步骤：

1. `git checkout` 恢复 `backend/services/vix_service.py`、`backend/data/vix_sources.py`、`backend/core/database.py`
2. 前端恢复 `VixGauge.vue`、`VixTrendChart.vue`、`VixView.vue`、`DashboardView.vue`
3. 重启 Flask
4. 执行 `POST /api/vix/backfill {"days": 250, "skip_existing": false}` 用旧算法重新计算历史数据

---

## 第十三部分：实施完成报告（2026-06-09）

### 13.1 完成总览

| 步骤 | 任务 | 文件 | 状态 |
|------|------|------|------|
| 1 | 数据源：新增 `fetch_multi_etf_qvix` | `backend/data/vix_sources.py` | ✅ |
| 1 | 数据源：新增 `fetch_pcr`（`option_daily_stats_sse`） | `backend/data/vix_sources.py` | ✅ |
| 1 | 数据源：注册 5 个新 akshare QVIX 函数 + option_daily_stats_sse | `backend/data/vix_sources.py` | ✅ |
| 2 | DB：v5 schema 迁移 14 列（ALTER TABLE 幂等） | `backend/core/database.py` | ✅ |
| 2 | DB：扩展 `upsert_vix_history` 写入 v5 全列 | `backend/core/database.py` | ✅ |
| 2 | DB：新增 `get_vix_history_for_zscore(days=252)` | `backend/core/database.py` | ✅ |
| 3 | 计算服务：完整重写为 v5 | `backend/services/vix_service.py` | ✅ |
| 3 | 计算服务：合成 VIX（5 ETF 等权）+ Z-Score + PCR 真实数据 + 连续现货分 | `backend/services/vix_service.py` | ✅ |
| 3 | 计算服务：删除北向，重新分配权重（VIX 35% / Limit 20%） | `backend/services/vix_service.py` | ✅ |
| 3 | 计算服务：regime 改为基于 252 日滚动百分位 | `backend/services/vix_service.py` | ✅ |
| 3 | 计算服务：`compute_and_store` / `backfill_vix_history` / `snapshot_to_api` 升级 | `backend/services/vix_service.py` | ✅ |
| 4 | API 路由：无需改动（透传 v5 结构） | `backend/api/routes/vix.py` | ✅（保持原样） |
| 5 | 前端 API 客户端：无需改动 | `frontend/src/api/index.js` | ✅（保持原样） |
| 6 | 前端：VixGauge 升级（0-100 + 百分位刻度 + VIX 副标题 + Z-Score + 颜色反转） | `frontend/src/components/VixGauge.vue` | ✅ |
| 7 | 前端：VixTrendChart 升级（新增 Percentile series + 百分位阈值带） | `frontend/src/components/VixTrendChart.vue` | ✅ |
| 8 | 前端：VixView 重写（5 个 StatCard + 多 ETF IV 卡片 + 5 格分项明细 + 百分位阈值表） | `frontend/src/views/VixView.vue` | ✅ |
| 8 | 前端：Dashboard 子指标调整（北向→PCR） | `frontend/src/views/DashboardView.vue` | ✅ |
| 9 | SPEC：§11C VIX v5 重构说明（13 小节） | `docs/SPEC.md` | ✅ |
| — | 实施完成报告（本节） | `docs/vix-v5-design.md` | ✅ |

### 13.2 与设计书的偏差

实施过程**严格按设计书执行**，无结构性偏差。微小补充：

- `ak.option_daily_stats_sse` / 4 个新 QVIX 函数在某些 akshare 版本中可能不存在，`vix_sources.py` 用 `getattr(ak, ..., None)` 容错导入，任一接口缺失时 `fetch_multi_etf_qvix` 跳过该 ETF，`fetch_pcr` 直接返回 None，整体仍能降级运行。
- `snapshot_to_api` 的 `data_quality` 判定中 `multi_etf` / `50etf_only` / `sse` 被加入 `_is_real` 白名单（v4 原本只识别 `iv` / `rv_fallback` 等），以保证新数据源被正确标记为真实。
- VixTrendChart 新增 `LegendComponent` import 用于显示 4 条曲线图例；右 Y 轴改名为「综合/百分位」（更准确表达 0-100 共享刻度）。

### 13.3 端到端验证

**后端 import smoke test**：
```
all symbols import OK
classify_by_percentile(50): neutral
classify_by_percentile(5): extreme_fear
classify_by_percentile(95): extreme_greed
_vix_to_score(20, 0.0): 50.0
_vix_to_score(20, 2.0): 1.80
_vix_to_score(20, -2.0): 98.20
_pcr_to_score(0.85): 50.0
_pcr_to_score(1.20): 25.92
_pcr_to_score(0.50): 74.08
_spot_to_score(dev=2, mom=1.5, hi=0.3): 59.4
_spot_to_score(extreme top): 79.8
_spot_to_score(extreme bottom): 23.8
compute_fear_greed: 40.0
compute_fear_greed(no data): 50.0
```

**DB schema 验证**：v5 全部 14 列通过 `PRAGMA table_info(vix_history)` 检查，状态 OK。

**JSON 契约验证**（写入 mock 行 → 读回 → snapshot_to_api）：
- 30+ v5 字段全部存在（date / vix / vix_source / vix_zscore / vix_etf_count / 5 个 iv_* / 5 个 pcr_* / rv_* / margin_* / limit_* / fear_greed / composite_score / composite_regime / composite_percentile / regime / percentile / spot / composite / data_quality / vix_only_regime）
- `north_net` / `north_source` 彻底消失
- `data_quality.total = 6`、`signals = {vix, rv_chg, pcr, margin, limit, spot}` 全部 true
- `composite` 块含 `score / regime / percentile / vix_fg / spot_score`

**Vue 文件结构检查**：4 个改动的 .vue 文件 template/script/style 三段式完整且平衡。

### 13.4 上线后立即执行

```bash
TOKEN=$(curl -s -X POST http://localhost:5000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' | python -c "import json,sys;print(json.load(sys.stdin)['token'])")

# 1) 触发重算当日
curl -X POST -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/vix/recompute
sleep 5

# 2) 验证 v5 字段
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/vix | python -m json.tool
#   预期：pcr_source: "sse"（非 unavailable）
#         vix_source: "multi_etf"（非 iv）
#         data_quality.total: 6
#         不含 north_net / north_source

# 3) 回填近 1 年历史（覆盖旧行以补齐 v5 新列）
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"days": 250, "skip_existing": false}' \
  http://localhost:5000/api/vix/backfill
# 轮询 /api/vix/backfill_status 至 running=false（250 个交易日约 8-12 分钟）

# 4) 前端验证
# 浏览器打开 /dashboard：VixGauge 显示 composite_score（0-100）+ 合成 VIX 副标题 + Z-Score
# 浏览器打开 /vix：5 个 StatCard 全部有数据；多 ETF IV 卡片 5 条柱；分项 5 格；data_quality 6/6
```

### 13.5 实施人 / 时间

- 实施日期：2026-06-09
- 设计书：本文档（vix-v5-design.md）
- 同步更新文档：`docs/SPEC.md` §11C
- 关联 commit：基于 main 分支工作，未单独 commit（待用户确认后再合入）

---

## 第十四部分：v6 后续修复（2026-06-28）

v5 上线后排查发现「多 ETF 合成从未生效（列名 bug）」「平稳日不敏感」「回填 ~4h」三类问题，
v6 已修复：列名 `iv_close`→`close`、新增 VIX 日变化率/日内振幅信号、FG 权重重平衡（VIX 类 45%）、
composite 拆分 FG 50%/现货 50%、全量历史 60s TTL 缓存（回填 ~4h→~20min）。
完整设计与改动清单见 `docs/SPEC.md` §11D。

