"""VIX 2.0 — 三隘栏标签（Triple-Barrier, López de Prado）。

设计见 docs/vix2-ml-design.md §2.2。对每个交易日 t，在 (t, t+H] 窗口内观察
close 先触哪条 barrier：
  先触 upper（止盈）→ label=+1（此处买入未来上涨 → 当前是「底」侧）
  先触 lower（止损）→ label=-1（此处买入未来下跌 → 当前是「顶」侧）
  都没触，到 vertical → label = sign(close[t+H] − close[t])

barrier 宽度按近 RV 动态缩放，避免高波动期全部秒触发、低波动期永不触发。
训练目标 P(label=+1)=「当前是底、未来涨」的概率；分数 = (1−P_up)×100。
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def triple_barrier_labels(
    close: pd.Series,
    pt: float = 0.05,
    sl: float = 0.05,
    horizon: int = 20,
    rv_scale: bool = True,
    rv_window: int = 20,
    rv_ref: float = 0.015,
) -> pd.Series:
    """对收盘价序列生成三隘栏标签 {+1, -1}。

    参数:
      close     : 按日期升序的收盘价 Series（index 任意，按位置处理）
      pt / sl   : 止盈 / 止损 barrier 基准宽度（rv_scale=False 时即固定宽度）
      horizon   : 时间 barrier（向前看的交易日数 H）
      rv_scale  : 是否按近 rv_window 日收益波动缩放 barrier 宽度
      rv_ref    : 参考日波动率（缩放基准，0.015≈1.5% 日波动）；
                  实际宽度 = pt × (近期日波动 / rv_ref)，clip 到 [0.5, 3] 倍
      rv_window : 估计近期波动的窗口

    返回:
      与 close 同长度的 Series（值 ∈ {+1, -1}，最后 horizon 个交易日无法定标 → NaN）
    """
    n = len(close)
    vals = close.to_numpy(dtype=float)
    labels = np.full(n, np.nan)

    if rv_scale:
        rets = pd.Series(vals).pct_change()
        daily_vol = rets.rolling(rv_window).std().to_numpy()
    else:
        daily_vol = None

    for t in range(n - 1):
        entry = vals[t]
        if not np.isfinite(entry) or entry <= 0:
            continue
        if rv_scale and daily_vol is not None and np.isfinite(daily_vol[t]) and daily_vol[t] > 0:
            scale = float(np.clip(daily_vol[t] / rv_ref, 0.5, 3.0))
        else:
            scale = 1.0
        upper = entry * (1 + pt * scale)
        lower = entry * (1 - sl * scale)
        end = min(t + horizon, n - 1)
        if end <= t:
            break

        label = None
        for j in range(t + 1, end + 1):
            px = vals[j]
            if not np.isfinite(px):
                continue
            if px >= upper:
                label = 1
                break
            if px <= lower:
                label = -1
                break
        if label is None:
            # 未触任何 barrier → 按到期方向
            terminal = vals[end]
            label = 1 if terminal >= entry else -1
        labels[t] = label

    return pd.Series(labels, index=close.index)


def build_labeled_dataset(
    features: pd.DataFrame,
    pt: float = 0.05,
    sl: float = 0.05,
    horizon: int = 20,
    rv_scale: bool = True,
) -> Optional[pd.DataFrame]:
    """给特征矩阵附加三隘栏标签，丢弃含 NaN（窗口未形成 / 末端无法定标）的行。

    入参 features：build_core_features 的输出（含 date, close, CORE_FEATURES）。
    返回：在原列基础上追加 'label'（0/1，0=顶侧 -1 重编码，1=底侧），
          以及 'y'（原始 ±1）。无有效样本返回 None。
    """
    from backend.services.vix2_features import CORE_FEATURES

    if features is None or features.empty:
        return None
    df = features.sort_values("date").reset_index(drop=True).copy()
    df["y"] = triple_barrier_labels(df["close"], pt=pt, sl=sl, horizon=horizon, rv_scale=rv_scale)
    # 逻辑回归目标：底侧(+1)→1，顶侧(-1)→0
    df["label"] = (df["y"] > 0).astype("float")
    needed = ["label"] + CORE_FEATURES
    df = df.dropna(subset=needed + ["y"]).reset_index(drop=True)
    if df.empty:
        return None
    df["label"] = df["label"].astype(int)
    return df
