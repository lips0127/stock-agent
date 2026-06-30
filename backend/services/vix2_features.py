"""VIX 2.0 — 长历史因子构建（point-in-time，无未来泄漏）。

设计见 docs/vix2-ml-design.md §2。核心因子回溯到 50ETF QVIX 起点（2015-02），
全部用「t 日收盘后已知」的信息派生：滚动窗口一律 trailing，绝不引入未来值。

主要导出：
  CORE_FEATURES        — 核心因子列名顺序（训练/推断须一致）
  build_core_features  — 构建 [date, close, <CORE_FEATURES...>] 的 DataFrame
  latest_feature_row   — 取某日（默认最新）的单行因子向量，用于盘后推断
"""

from __future__ import annotations

import logging
import math
from typing import Optional

import numpy as np
import pandas as pd

from backend.services.stock_service import _no_proxy
from backend.data.vix_sources import (
    fetch_index_daily_tx, SH_COMPOSITE_SYMBOL, HS300_SYMBOL,
    ak_index_option_50etf_qvix,
)

logger = logging.getLogger(__name__)

# 训练 / 推断必须共用同一顺序（StandardScaler 与系数按位置对齐）
CORE_FEATURES = [
    "qvix_50",          # 50ETF 隐含波动率水平
    "qvix_50_z",        # QVIX 滚动 252 日 Z-Score
    "qvix_50_chg5",     # QVIX 5 日变化率 %
    "rv_hs300",         # 沪深300 Garman-Klass 已实现波动率（年化%）
    "rv_qvix_spread",   # RV − QVIX（方差风险溢价代理）
    "ma60_dev",         # 上证综指偏离 60 日线 %
    "mom_20d",          # 20 日动量 %
    "mom_60d",          # 60 日动量 %
    "new_high_ratio",   # 20 日新高比例 0-1
    "drawdown_252",     # 距 252 日高点回撤 %（≤0）
    "dist_low_252",     # 距 252 日低点涨幅 %（≥0）
]

_RV_WINDOW = 20         # Garman-Klass RV 滚动窗口
_Z_WINDOW = 252         # QVIX Z-Score 滚动窗口
_LONG_DAYS = 4200       # 拉取历史天数上限（覆盖 2015-至今 + 余量）


def _fetch_qvix_full() -> Optional[pd.DataFrame]:
    """全历史 50ETF QVIX（不按 days 截断）。返回 [date, qvix_50]。"""
    try:
        with _no_proxy():
            df = ak_index_option_50etf_qvix()
    except Exception as e:
        logger.warning(f"_fetch_qvix_full 失败: {e}")
        return None
    if df is None or df.empty or "close" not in df.columns:
        return None
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["qvix_50"] = pd.to_numeric(df["close"], errors="coerce")
    return df[["date", "qvix_50"]].dropna().sort_values("date").reset_index(drop=True)


def _rolling_gk_rv(df: pd.DataFrame, window: int = _RV_WINDOW) -> pd.Series:
    """逐日滚动 Garman-Klass 已实现波动率（年化%）。

    与 vix_service.garman_klass_rv 同公式，但输出整条序列（trailing 窗口，point-in-time）。
    """
    log_hl = np.log(df["high"] / df["low"])
    log_co = np.log(df["close"] / df["open"])
    term = 0.5 * log_hl ** 2 - (2 * math.log(2) - 1) * log_co ** 2
    var = term.rolling(window).mean()
    rv = np.sqrt(var.clip(lower=0)) * math.sqrt(252) * 100
    return rv.round(2)


def build_core_features(as_of: Optional[str] = None) -> Optional[pd.DataFrame]:
    """构建长历史核心因子矩阵。

    返回 DataFrame：index 重置，列 = [date, close, <CORE_FEATURES...>]。
    - close 为上证综指收盘价，供三隘栏标签使用（labels 层）。
    - as_of 给定时，仅保留 date <= as_of 的行（推断/严格时间切分用）。
    - 不在此处 dropna：训练层按需丢弃前导 NaN（窗口未形成期）。
    """
    sh = fetch_index_daily_tx(SH_COMPOSITE_SYMBOL, days=_LONG_DAYS)
    if sh is None or sh.empty:
        logger.warning("build_core_features: 上证综指日线为空")
        return None
    sh = sh.sort_values("date").reset_index(drop=True)

    hs = fetch_index_daily_tx(HS300_SYMBOL, days=_LONG_DAYS)
    qvix = _fetch_qvix_full()
    if qvix is None:
        logger.warning("build_core_features: QVIX 历史为空")
        return None

    df = sh[["date", "open", "high", "low", "close"]].copy()

    # ── 价格位置因子（上证综指，全部 trailing）──
    ma60 = df["close"].rolling(60).mean()
    df["ma60_dev"] = ((df["close"] - ma60) / ma60 * 100).round(2)
    df["mom_20d"] = (df["close"].pct_change(20) * 100).round(2)
    df["mom_60d"] = (df["close"].pct_change(60) * 100).round(2)
    roll20_max = df["close"].rolling(20).max()
    is_new_high = (df["close"] >= roll20_max).astype(int)
    df["new_high_ratio"] = (is_new_high.rolling(20).sum() / 20).round(3)
    roll252_max = df["close"].rolling(252).max()
    roll252_min = df["close"].rolling(252).min()
    df["drawdown_252"] = ((df["close"] - roll252_max) / roll252_max * 100).round(2)
    df["dist_low_252"] = ((df["close"] - roll252_min) / roll252_min * 100).round(2)

    # ── 已实现波动率（沪深300 GK）──
    if hs is not None and not hs.empty:
        hs = hs.sort_values("date").reset_index(drop=True)
        hs["rv_hs300"] = _rolling_gk_rv(hs, _RV_WINDOW)
        df = df.merge(hs[["date", "rv_hs300"]], on="date", how="left")
    else:
        logger.warning("build_core_features: 沪深300 缺失，rv_hs300 置 NaN")
        df["rv_hs300"] = np.nan

    # ── QVIX 因子 ──
    qvix = qvix.copy()
    qvix["qvix_50_z"] = (
        (qvix["qvix_50"] - qvix["qvix_50"].rolling(_Z_WINDOW).mean())
        / qvix["qvix_50"].rolling(_Z_WINDOW).std()
    ).round(3)
    qvix["qvix_50_chg5"] = (qvix["qvix_50"].pct_change(5) * 100).round(2)
    df = df.merge(qvix[["date", "qvix_50", "qvix_50_z", "qvix_50_chg5"]], on="date", how="left")

    # ── 方差风险溢价代理 ──
    df["rv_qvix_spread"] = (df["rv_hs300"] - df["qvix_50"]).round(2)

    cols = ["date", "close"] + CORE_FEATURES
    out = df[cols]
    if as_of:
        out = out[out["date"] <= as_of]
    return out.reset_index(drop=True)


def latest_feature_row(as_of: Optional[str] = None,
                       cached: Optional[pd.DataFrame] = None) -> Optional[dict]:
    """取某日（默认最新可得交易日）的核心因子向量，用于盘后单日推断。

    cached：可传入 build_core_features 的结果复用，避免重复拉数据。
    返回 {"date": ..., "qvix_50": ..., ...}；任一核心因子缺失则返回 None
    （宁缺勿用降级值污染推断）。
    """
    df = cached if cached is not None else build_core_features(as_of=as_of)
    if df is None or df.empty:
        return None
    row = df.iloc[-1]
    if as_of and row["date"] != as_of:
        match = df[df["date"] == as_of]
        if match.empty:
            return None
        row = match.iloc[-1]
    feats = {f: row[f] for f in CORE_FEATURES}
    if any(pd.isna(v) for v in feats.values()):
        return None
    return {"date": row["date"], **{k: float(v) for k, v in feats.items()}}
