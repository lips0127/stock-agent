"""
VIX 数据源 adapter（v5, 2026-06-09）

封装 akshare 各数据源，统一：
  * 代理绕过（_no_proxy）
  * 异常容错（返回 None 而非抛错，让上层做降级）
  * 数据规范化（统一返回 pandas.DataFrame 或 dict，列名标准化为英文）

v5 新增：
  * fetch_multi_etf_qvix() — 5 ETF QVIX 等权合成 VIX
  * fetch_pcr() — 上交所 50ETF 期权 Put/Call Ratio
"""

from __future__ import annotations

import logging
import time as _time
import warnings
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from backend.services.stock_service import _no_proxy

logger = logging.getLogger(__name__)

# akshare 全量序列的进程内缓存（cache_key -> (fetched_ts, raw_df)），TTL 较长。
# 这些接口返回的是与目标日期无关的完整历史；回填整轮共用一份，
# 避免 250+ 天 × N 个数据源的重复全量拉取（否则单轮回填需数小时）。
# TTL 设为 30 分钟覆盖整轮回填；盘后实时每天只跑一次，不受影响。
_TX_CACHE: dict = {}
_TX_CACHE_TTL = 1800.0


def _cached_raw(cache_key: str, fetcher):
    """带 60s TTL 的原始 DataFrame 缓存。fetcher 无参，返回原始 df 或抛错。

    命中返回缓存副本前的原始引用（调用方需 .copy() 后再改）；未命中调用 fetcher 并缓存。
    fetcher 抛错或返回空时返回 None 且不缓存。
    """
    now = _time.time()
    cached = _TX_CACHE.get(cache_key)
    if cached is not None and (now - cached[0]) < _TX_CACHE_TTL:
        return cached[1]
    try:
        with _no_proxy():
            raw = fetcher()
    except Exception as e:
        logger.warning(f"_cached_raw({cache_key}) 失败: {e}")
        return None
    if raw is None or getattr(raw, "empty", True):
        return None
    _TX_CACHE[cache_key] = (now, raw)
    return raw

# 屏蔽 akshare 内部的 FutureWarning（频繁噪音）
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)


# ─────────────────────────────────────────────────────────────────
# 1) 50ETF 期权隐含波动率（QVIX）—— VIX 主体
# ─────────────────────────────────────────────────────────────────

def fetch_50etf_qvix(days: int = 60) -> Optional[pd.DataFrame]:
    """50ETF 期权 QVIX（隐含波动率）日线。

    AkShare 文档：https://akshare.akfamily.xyz/data/option/option.html
    返回：DataFrame[date, open, high, low, close]，close 即当日 QVIX（%）
    """
    try:
        with _no_proxy():
            df = ak_index_option_50etf_qvix()
    except Exception as e:
        logger.warning(f"fetch_50etf_qvix 失败: {e}")
        return None
    if df is None or df.empty:
        return None
    df = df.rename(columns={"date": "date", "close": "iv_close"})
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["iv_close"] = pd.to_numeric(df["iv_close"], errors="coerce")
    cutoff = (datetime.now() - timedelta(days=days + 5)).strftime("%Y-%m-%d")
    return df[df["date"] >= cutoff][["date", "iv_close"]].reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────
# 1.5) 多 ETF QVIX 合成（v6.1, 2026-06-28）—— 主体 VIX（代表性加权 + 宽基/成长拆分）
# ─────────────────────────────────────────────────────────────────

# 代表性权重（基于现货市值代表性 + 期权流动性深度）。v6 等权会让创业板/科创
# 这类高波动标的占 40%，把"全市场恐慌"做成"成长股恐慌"；改为非等权修正。
ETF_WEIGHTS = {
    "50etf":  0.20,
    "300etf": 0.30,
    "500etf": 0.20,
    "cyb":    0.15,
    "kcb":    0.15,
}
# 宽基 vs 成长分组（用于拆分系统性风险 vs 风格杀估值）
BROAD_ETFS = ("50etf", "300etf", "500etf")
GROWTH_ETFS = ("cyb", "kcb")


def _weighted_last(close_wide: pd.DataFrame, keys, row_idx: int = -1) -> Optional[float]:
    """对 close_wide（列=ETF key）某一行取加权平均，权重按可用列重新归一化。"""
    cols = [k for k in keys if k in close_wide.columns]
    if not cols or abs(row_idx) > len(close_wide):
        return None
    row = close_wide.iloc[row_idx]
    pairs = [(k, ETF_WEIGHTS[k], row[k]) for k in cols if pd.notna(row[k])]
    if not pairs:
        return None
    wsum = sum(w for _, w, _ in pairs)
    if wsum <= 0:
        return None
    return round(sum(w * v for _, w, v in pairs) / wsum, 2)


def fetch_multi_etf_qvix(days: int = 60, as_of: Optional[str] = None) -> Optional[dict]:
    """拉取 5 个 ETF 期权的 QVIX，代表性加权合成 VIX（v6.1）。

    5 个标的：50ETF(510050) / 300ETF(510300) / 500ETF(510500) /
             创业板ETF(159915) / 科创50ETF(588000)

    akshare QVIX 函数返回的列是 date/open/high/low/close（注意是 close，
    不是 iv_close）。本函数直接读 close。

    v6.1 变更：
      * 合成 VIX 改代表性加权（ETF_WEIGHTS），权重按当日可用 ETF 重新归一化
      * 输出宽基 VIX（50+300+500）与成长 VIX（创业板+科创）+ 成长溢价
      * 日内振幅改为"单 ETF 各自振幅% → 加权"（旧版先拼 high/low 会造出虚假全天恐慌）

    入参 as_of：目标日期（YYYY-MM-DD），回填历史用；取该日及之前最后一根。

    返回 dict：
      {
        "50etf": .., ...,                  # 各 ETF 当日 close
        "synthetic": 加权合成 VIX,
        "synthetic_prev": 上一交易日加权合成,
        "broad": 宽基加权 VIX, "growth": 成长加权 VIX,
        "growth_premium": growth - broad,
        "swing_pct": 跨 ETF 波动冲击强度（单 ETF 振幅%加权，已是百分比）,
        "count": 实际可用 ETF 数, "source": "multi_etf",
      }
    任一 ETF 拉取失败不影响其他；全部失败返回 None。
    """
    fetchers = {
        "50etf":  ak_index_option_50etf_qvix,
        "300etf": ak_index_option_300etf_qvix,
        "500etf": ak_index_option_500etf_qvix,
        "cyb":    ak_index_option_cyb_qvix,
        "kcb":    ak_index_option_kcb_qvix,
    }
    cutoff = (datetime.now() - timedelta(days=days + 5)).strftime("%Y-%m-%d")

    per_etf: dict = {}        # key -> DataFrame[date, close, high, low]
    latest_close: dict = {}   # key -> 当日 close（明细展示）
    latest_swing: dict = {}   # key -> 当日单 ETF 振幅%((high-low)/close*100)
    for key, fn in fetchers.items():
        if fn is None:
            logger.debug(f"fetch_multi_etf_qvix.{key}: ak 函数未注册，跳过")
            continue
        try:
            df = _cached_raw(f"qvix:{key}", fn)
            if df is None or df.empty or "close" not in df.columns:
                continue
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
            for c in ("close", "high", "low"):
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
            df = df[(df["date"] >= cutoff) & df["close"].notna()]
            if as_of:
                df = df[df["date"] <= as_of]
            if df.empty:
                continue
            df = df.sort_values("date")
            cols = [c for c in ("date", "close", "high", "low") if c in df.columns]
            per_etf[key] = df[cols].reset_index(drop=True)
            last = df.iloc[-1]
            latest_close[key] = float(last["close"])
            # 单 ETF 当日振幅%（v6.1：先各自标准化，避免跨 ETF 异步 high/low 造假）
            if "high" in df.columns and "low" in df.columns \
                    and pd.notna(last["high"]) and pd.notna(last["low"]) and last["close"]:
                latest_swing[key] = (last["high"] - last["low"]) / last["close"] * 100
        except Exception as e:
            logger.warning(f"fetch_multi_etf_qvix.{key} 失败: {e}")

    if not per_etf:
        return None

    # 按日期对齐成宽表（列=ETF key），加权合成
    close_wide = pd.concat(
        {k: v.set_index("date")["close"] for k, v in per_etf.items()}, axis=1
    ).sort_index().dropna(how="all")
    if close_wide.empty:
        return None

    synthetic = _weighted_last(close_wide, ETF_WEIGHTS.keys(), -1)
    synthetic_prev = _weighted_last(close_wide, ETF_WEIGHTS.keys(), -2) if len(close_wide) >= 2 else None
    synthetic_prev2 = _weighted_last(close_wide, ETF_WEIGHTS.keys(), -3) if len(close_wide) >= 3 else None
    broad = _weighted_last(close_wide, BROAD_ETFS, -1)
    growth = _weighted_last(close_wide, GROWTH_ETFS, -1)
    growth_premium = round(growth - broad, 2) if (growth is not None and broad is not None) else None

    # 跨 ETF 波动冲击强度：单 ETF 振幅% 按权重加权（已是百分比，无需再除 close）
    swing_pct = None
    if latest_swing:
        wsum = sum(ETF_WEIGHTS[k] for k in latest_swing)
        if wsum > 0:
            swing_pct = round(sum(ETF_WEIGHTS[k] * s for k, s in latest_swing.items()) / wsum, 2)

    return {
        **{k: round(v, 2) for k, v in latest_close.items()},
        "synthetic": synthetic,
        "synthetic_prev": synthetic_prev,
        "synthetic_prev2": synthetic_prev2,
        "broad": broad,
        "growth": growth,
        "growth_premium": growth_premium,
        "swing_pct": swing_pct,
        "count": len(latest_close),
        "source": "multi_etf",
    }


# ─────────────────────────────────────────────────────────────────
# 2) 沪深 300 / 中证 1000 日线 —— 已实现波动率
# ─────────────────────────────────────────────────────────────────

# 主流数据源（akshare）：sh000300=沪深300, sh000852=中证1000
HS300_SYMBOL = "sh000300"
ZZ1000_SYMBOL = "sh000852"
# 上证综指（用于现货位置信号，2026-06-04 v2 算法）
SH_COMPOSITE_SYMBOL = "sh000001"


def fetch_index_daily(symbol: str, days: int = 90) -> Optional[pd.DataFrame]:
    """拉取指数日线 OHLC。复用 akshare stock_zh_index_daily 接口。"""
    df = _cached_raw(f"idx_daily:{symbol}", lambda: ak_stock_zh_index_daily(symbol=symbol))
    if df is None or df.empty:
        return None
    df = df.copy()
    # 标准化列名
    rename = {}
    for c in df.columns:
        cl = str(c).lower()
        if cl in ("date", "日期"):
            rename[c] = "date"
        elif cl in ("open", "开盘"):
            rename[c] = "open"
        elif cl in ("high", "最高"):
            rename[c] = "high"
        elif cl in ("low", "最低"):
            rename[c] = "low"
        elif cl in ("close", "收盘"):
            rename[c] = "close"
    df = df.rename(columns=rename)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    for c in ("open", "high", "low", "close"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    cutoff = (datetime.now() - timedelta(days=days + 5)).strftime("%Y-%m-%d")
    return df[df["date"] >= cutoff][["date", "open", "high", "low", "close"]].dropna().reset_index(drop=True)


def fetch_index_daily_tx(symbol: str, days: int = 400) -> Optional[pd.DataFrame]:
    """腾讯财经指数日线（兜底数据源，覆盖更长历史）。

    akshare stock_zh_index_daily 在 2024-2025 数据窗口只有 ~200 行，无法形成 ma60；
    腾讯接口 stock_zh_index_daily_tx 返回自 1990 起的全量历史，能稳定支持 250 天回填。

    带 60s TTL 的进程内缓存：腾讯接口返回的是同一份全量历史（与 days 无关），
    回填 250 天时若每天重拉一次约 50s/次 → 总耗时 4h。缓存后整轮回填只拉一次。
    """
    raw = _cached_raw(f"tx:{symbol}", lambda: ak_stock_zh_index_daily_tx(symbol=symbol))
    if raw is None or raw.empty:
        return None
    df = raw.copy()
    rename = {}
    for c in df.columns:
        cl = str(c).lower()
        if cl in ("date", "日期"):
            rename[c] = "date"
        elif cl in ("open", "开盘"):
            rename[c] = "open"
        elif cl in ("high", "最高"):
            rename[c] = "high"
        elif cl in ("low", "最低"):
            rename[c] = "low"
        elif cl in ("close", "收盘"):
            rename[c] = "close"
    df = df.rename(columns=rename)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    for c in ("open", "high", "low", "close"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    cutoff = (datetime.now() - timedelta(days=days + 5)).strftime("%Y-%m-%d")
    return df[df["date"] >= cutoff][["date", "open", "high", "low", "close"]].dropna().reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────
# 3) 沪深港通北向资金 —— 外资态度
# ─────────────────────────────────────────────────────────────────

def fetch_north_net_flow(date_str: str) -> Optional[dict]:
    """指定日期的北向资金净流入（亿元）。

    数据源优先级（v2, 2026-06-04）：
      1) stock_hsgt_hist_em        — 沪深港通历史北向日线（含"当日成交净买额"列）
      2) stock_hsgt_fund_min_em    — 分钟级实时，累加当日最后一根 bar 的沪+深净买额
      3) stock_hsgt_fund_flow_summary_em — 实时 4 行（沪/深 + 港股通南向）
                                         取 row 0（沪股通-沪股通）+ row 2（深股通-深股通）

    兼容性说明：akshare 1.18.30 中 hist_em 自 2024-08 后大量 NaN；fund_min_em 在盘中可能
    返回 0（数据延迟）；fund_flow_summary_em 部分字段也含 0。三者任一成功即可。
    失败时返回 None（上层按中性 50 分处理 + data_quality 标记 unavailable）。
    返回：{"north_net": float, "source": "hist"|"min"|"summary"}
    """
    # 方案 1：hist_em（按日，含历史）
    try:
        with _no_proxy():
            df = ak_stock_hsgt_hist_em()
        if df is not None and not df.empty:
            # col 0=日期, col 1=当日成交净买额（按 akshare 1.18.30 的列顺序）
            # 但 hist_em 在 2024-08 后数据全 NaN，过滤后取该日非 NaN 值
            row = df[df.iloc[:, 0].astype(str) == date_str]
            if not row.empty:
                val = pd.to_numeric(row.iloc[0, 1], errors="coerce")
                if not pd.isna(val) and val != 0:
                    return {"north_net": round(float(val), 2), "source": "hist"}
    except Exception as e:
        logger.debug(f"fetch_north_net_flow.hist 失败: {e}")

    # 方案 2：fund_min_em（盘中实时）
    try:
        with _no_proxy():
            df = ak_stock_hsgt_fund_min_em()
        if df is not None and not df.empty:
            # 列名是"沪股通"/"深股通"或类似
            sh_col = None
            sz_col = None
            for c in df.columns:
                cs = str(c)
                if "沪股通" in cs and "净买额" in cs:
                    sh_col = c
                elif "深股通" in cs and "净买额" in cs:
                    sz_col = c
            if sh_col and sz_col:
                sh = pd.to_numeric(df[sh_col], errors="coerce").iloc[-1]
                sz = pd.to_numeric(df[sz_col], errors="coerce").iloc[-1]
                if not (pd.isna(sh) and pd.isna(sz)):
                    total = (0 if pd.isna(sh) else sh) + (0 if pd.isna(sz) else sz)
                    if total != 0:
                        return {"north_net": round(float(total), 2), "source": "min"}
    except Exception as e:
        logger.debug(f"fetch_north_net_flow.min 失败: {e}")

    # 方案 3：fund_flow_summary_em（实时 4 行）
    try:
        with _no_proxy():
            df = ak_stock_hsgt_fund_flow_summary_em()
        if df is not None and len(df) >= 3:
            # 按位置：row 0=沪股通-沪股通(北向), row 2=深股通-深股通(北向)
            sh = pd.to_numeric(df.iloc[0, 5], errors="coerce")
            sz = pd.to_numeric(df.iloc[2, 5], errors="coerce")
            if not (pd.isna(sh) and pd.isna(sz)):
                total = (0 if pd.isna(sh) else sh) + (0 if pd.isna(sz) else sz)
                if total != 0:
                    return {"north_net": round(float(total), 2), "source": "summary"}
    except Exception as e:
        logger.debug(f"fetch_north_net_flow.summary 失败: {e}")

    return None


# ─────────────────────────────────────────────────────────────────
# 4) 融资融券余额 —— 杠杆资金情绪
# ─────────────────────────────────────────────────────────────────


def fetch_margin_balance() -> Optional[dict]:
    """全市场融资融券余额合计（亿元）。

    数据源 macro_china_market_margin_sh / sz，单位是"元"，需 /1e8 转亿。
    """
    total = 0.0
    found = False
    for fn in (ak_macro_china_market_margin_sh, ak_macro_china_market_margin_sz):
        df = _cached_raw(f"margin:{fn.__name__}", fn)
        if df is None or df.empty:
            continue
        col = None
        for c in df.columns:
            if "融资余额" in str(c):
                col = c
                break
        if col is None:
            continue
        val = pd.to_numeric(df[col].iloc[-1], errors="coerce")
        if pd.isna(val):
            continue
        total += float(val)
        found = True
    if not found:
        return None
    # 单位"元" → "亿"
    return {"margin_balance": round(total / 1e8, 2)}


# ─────────────────────────────────────────────────────────────────
# 5) 涨跌停家数 —— 情绪面
# ─────────────────────────────────────────────────────────────────

def fetch_limit_counts(date_str: str) -> Optional[dict]:
    """指定日期涨停 / 跌停家数。

    akshare 接口要求 date 格式为 YYYYMMDD（无连字符），传入 YYYY-MM-DD 会
    返回 "invalid literal for int()" 错误。
    """
    date_compact = date_str.replace("-", "")
    try:
        with _no_proxy():
            zt = ak_stock_zt_pool_em(date=date_compact)
            dt = ak_stock_zt_pool_dtgc_em(date=date_compact)
    except Exception as e:
        logger.debug(f"fetch_limit_counts 失败: {e}")
        return None
    return {
        "limit_up_count": len(zt) if zt is not None else 0,
        "limit_down_count": len(dt) if dt is not None else 0,
    }


# ─────────────────────────────────────────────────────────────────
# 5.5) 50ETF 期权 PCR（Put/Call Ratio）—— 2026-06 v5 修复
# ─────────────────────────────────────────────────────────────────

def fetch_pcr(date_str: str) -> Optional[dict]:
    """从上交所每日期权统计获取 50ETF 的成交量 PCR 和持仓量 PCR。

    数据源：ak.option_daily_stats_sse(date=YYYYMMDD)
    返回：{"pcr_volume": float, "pcr_oi": float, "call_volume": int,
            "put_volume": int, "call_oi": int, "put_oi": int, "source": "sse"}
    失败返回 None。
    """
    if ak_option_daily_stats_sse is None:
        logger.debug("fetch_pcr: ak.option_daily_stats_sse 不存在")
        return None
    date_compact = date_str.replace("-", "")
    try:
        with _no_proxy():
            df = ak_option_daily_stats_sse(date=date_compact)
    except Exception as e:
        logger.warning(f"fetch_pcr 失败: {e}")
        return None

    if df is None or df.empty:
        return None

    # 列名是中文：合约标的代码 / 合约标的名称 / 认购成交量 / 认沽成交量 /
    # 认沽/认购 / 未平仓认购合约数 / 未平仓认沽合约数
    col_map: dict = {}
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

    if "code" not in col_map:
        logger.warning("fetch_pcr: 缺少 合约标的代码 列")
        return None

    # 找 510050（上证50ETF）行
    row = df[df[col_map["code"]].astype(str).str.contains("510050")]
    if row.empty:
        logger.warning("fetch_pcr: 未找到 510050 行")
        return None

    r = row.iloc[0]
    call_vol = int(pd.to_numeric(r.get(col_map.get("call_vol", "")), errors="coerce") or 0) \
        if "call_vol" in col_map else 0
    put_vol = int(pd.to_numeric(r.get(col_map.get("put_vol", "")), errors="coerce") or 0) \
        if "put_vol" in col_map else 0
    call_oi = int(pd.to_numeric(r.get(col_map.get("call_oi", "")), errors="coerce") or 0) \
        if "call_oi" in col_map else 0
    put_oi = int(pd.to_numeric(r.get(col_map.get("put_oi", "")), errors="coerce") or 0) \
        if "put_oi" in col_map else 0

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


# ─────────────────────────────────────────────────────────────────
# akshare 函数导入（统一在此处，便于 mock）
# ─────────────────────────────────────────────────────────────────

try:
    import akshare as ak
    # v1 期权 IV
    ak_index_option_50etf_qvix = ak.index_option_50etf_qvix
    # v5 新增：5 ETF QVIX（合成 VIX）
    ak_index_option_300etf_qvix = getattr(ak, "index_option_300etf_qvix", None)
    ak_index_option_500etf_qvix = getattr(ak, "index_option_500etf_qvix", None)
    ak_index_option_cyb_qvix = getattr(ak, "index_option_cyb_qvix", None)
    ak_index_option_kcb_qvix = getattr(ak, "index_option_kcb_qvix", None)
    # v5 新增：上交所期权每日统计（PCR）
    ak_option_daily_stats_sse = getattr(ak, "option_daily_stats_sse", None)
    # 指数
    ak_stock_zh_index_daily = ak.stock_zh_index_daily
    ak_stock_zh_index_daily_tx = ak.stock_zh_index_daily_tx
    # 北向（v5 已不再用于 VIX 算法，保留 import 不破坏外部引用）
    ak_stock_hsgt_fund_flow_summary_em = ak.stock_hsgt_fund_flow_summary_em
    ak_stock_hsgt_fund_min_em = ak.stock_hsgt_fund_min_em
    # 融资融券
    ak_macro_china_market_margin_sh = ak.macro_china_market_margin_sh
    ak_macro_china_market_margin_sz = ak.macro_china_market_margin_sz
    # 涨跌停
    ak_stock_zt_pool_em = ak.stock_zt_pool_em
    ak_stock_zt_pool_dtgc_em = ak.stock_zt_pool_dtgc_em
except ImportError as e:
    logger.error(f"akshare import 失败: {e}")
    raise


# ─────────────────────────────────────────────────────────────────
# 6) 现货位置信号（v2, 2026-06-04）—— 区分底部 vs 顶部
# ─────────────────────────────────────────────────────────────────

def compute_spot_signals_from_df(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """给定日线 OHLC DataFrame，计算 4 个现货位置指标。

    输入：fetch_index_daily() 返回的 df（含 date/open/high/low/close 列）
    输出：在原 df 上追加 ma20/ma60/ma60_dev/mom_5d/mom_20d/new_high_ratio_20d 列；
          不足窗口的行（ma60 NaN）保留，但下游需自行过滤。

    信号含义（用于 vix_service._spot_to_score）：
      - ma60_dev          : 当前位置偏离 60 日均线 %（负=超跌/底部，正=超涨/顶部）
      - mom_5d            : 5 日累计涨跌幅 %
      - mom_20d           : 20 日累计涨跌幅 %
      - new_high_ratio_20d: 过去 20 日中创 20 日新高日数 / 20（趋势强度 0-1）
    """
    if df is None or df.empty:
        return None
    df = df.copy()
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma60"] = df["close"].rolling(60).mean()
    df["ma60_dev"] = (df["close"] - df["ma60"]) / df["ma60"] * 100
    df["mom_5d"] = df["close"].pct_change(5) * 100
    df["mom_20d"] = df["close"].pct_change(20) * 100
    # 20 日新高比例（窗口内 close == 20 日 max 的日数 / 20）
    rolling_max = df["close"].rolling(20).max()
    is_new_high = (df["close"] == rolling_max).astype(int)
    df["new_high_ratio_20d"] = is_new_high.rolling(20).sum() / 20
    return df


def get_spot_signals_for_date(target_date: str, days: int = 400) -> Optional[dict]:
    """便捷函数：拉上证综指日线 → 计算现货信号 → 提取 target_date 那一行。

    使用腾讯 stock_zh_index_daily_tx 接口（自 1990 起全量历史），
    比 em 接口 (akshare stock_zh_index_daily) 数据窗口长，能稳定形成 ma60。
    返回 dict 含 close/ma60_dev/mom_5d/mom_20d/new_high_ratio_20d；
    任何一步失败或日期不在窗口内返回 None。
    """
    df = fetch_index_daily_tx(SH_COMPOSITE_SYMBOL, days=days)
    if df is None or df.empty:
        return None
    df = compute_spot_signals_from_df(df)
    if df is None or df.empty:
        return None
    row = df[df["date"] == target_date]
    if row.empty:
        return None
    r = row.iloc[0]
    if pd.isna(r.get("ma60")):
        # 窗口不足（ma60 未形成），返回 None
        return None
    return {
        "spot_close":        float(r["close"]),
        "spot_ma60_dev":     round(float(r["ma60_dev"]), 2),
        "spot_mom_5d":       round(float(r["mom_5d"]), 2) if not pd.isna(r["mom_5d"]) else None,
        "spot_mom_20d":      round(float(r["mom_20d"]), 2) if not pd.isna(r["mom_20d"]) else None,
        "spot_new_high_ratio": round(float(r["new_high_ratio_20d"]), 3) if not pd.isna(r["new_high_ratio_20d"]) else None,
    }
