"""十倍股分层器（确定性规则，纯函数）。

输入模块二趋势信号 + 异动信号（+ 可选行业景气），输出分层观察池 tier + 理由。

tier 口径：
  '1'  一级：基本面明显变化（≥3 正向异动、无风险）+ 趋势确认
  '2'  二级：逻辑性感业绩未兑现（趋势确认 + 1-2 个萌芽异动），
            或业绩已兑现但趋势未确认（≥3 异动 + 横盘）
  '3'  三级：概念强财务弱（趋势/概念强 + 无/极少异动）
  'exclude'  排除：趋势破位 + 无基本面，或无任何积极信号

口径约束：仅作观察池分类，不输出买卖信号（同 VIX 约束）。
"""

from __future__ import annotations

POSITIVE_KEYS = [
    "revenue_high_growth", "net_profit_high_growth",
    "gross_margin_improve", "inventory_down",
    "contract_liability_up", "cip_to_fixed_asset",
]
RISK_KEYS = ["receivable_risk", "cashflow_lag"]

TIER1_MIN_POSITIVE = 3
TIER2_WEAK_MIN = 1
TIER2_WEAK_MAX = 2
TIER3_MAX_POSITIVE = 1
CONCEPT_NEW_HIGH = 0.4
CONCEPT_VOLUME_RATIO = 1.5


def classify_pool(trend_signals: dict, anomaly_signals: dict,
                  industry_signals: dict | None = None) -> dict:
    """分层判定。

    Args:
        trend_signals: tenbag_trend_service.compute_trend_signals 输出。
        anomaly_signals: tenbag_anomaly_service.derive_anomaly_signals 输出。
        industry_signals: 可选 {'prosperity': 'high'|'mid'|'low'}（M3 后填充）。

    Returns:
        {'tier': '1'|'2'|'3'|'exclude', 'reasons': [str]}
    """
    regime = (trend_signals or {}).get("regime")
    sigs = (anomaly_signals or {}).get("signals", {}) or {}
    positive = sum(1 for k in POSITIVE_KEYS if sigs.get(k))
    risk = sum(1 for k in RISK_KEYS if sigs.get(k))

    trend_confirmed = regime in ("stage2_breakout", "advancing")
    concept_strong = _is_concept_strong(trend_signals)

    industry_high = bool(industry_signals and
                         industry_signals.get("prosperity") == "high")

    # 排除：趋势破位 + 无基本面
    if regime == "downtrend" and positive == 0:
        return _result("exclude", ["趋势破位且无基本面异动"])

    # 一级：基本面明显变化 + 趋势确认 + 无风险
    if positive >= TIER1_MIN_POSITIVE and trend_confirmed and risk == 0:
        reasons = [f"{positive} 个正向异动 + 趋势确认（{regime}）"]
        if industry_high:
            reasons.append("所处行业高景气")
        return _result("1", reasons)

    # 二级：业绩已兑现但趋势未确认（≥3 异动 + 横盘）
    if positive >= TIER1_MIN_POSITIVE and regime == "consolidation":
        return _result("2", [f"{positive} 个正向异动但趋势未确认，业绩待市场验证"])

    # 二级：趋势确认 + 萌芽异动（1-2 个，未全面兑现）
    if trend_confirmed and TIER2_WEAK_MIN <= positive <= TIER2_WEAK_MAX:
        return _result("2", [f"趋势确认（{regime}）但仅 {positive} 个异动，业绩未全面兑现"])

    # 三级：概念强 + 财务弱
    if concept_strong and positive <= TIER3_MAX_POSITIVE:
        return _result("3", ["概念/趋势强但财务异动弱，谨慎"])

    # 排除：无任何积极信号
    if positive == 0 and not trend_confirmed:
        return _result("exclude", ["无基本面异动且趋势未确认"])

    # 兜底：有零星信号但不满足以上 -> 三级谨慎
    return _result("3", ["信号不足，谨慎观察"])


def _is_concept_strong(trend_signals: dict) -> bool:
    """概念强：stage2 突破，或新高比例/放量显著。"""
    if not trend_signals:
        return False
    if trend_signals.get("regime") == "stage2_breakout":
        return True
    nh = trend_signals.get("new_high_ratio")
    vr = trend_signals.get("volume_ratio")
    if nh is not None and nh >= CONCEPT_NEW_HIGH:
        return True
    if vr is not None and vr >= CONCEPT_VOLUME_RATIO:
        return True
    return False


def _result(tier: str, reasons: list[str]) -> dict:
    return {"tier": tier, "reasons": reasons}
