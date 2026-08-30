"""VIX1 研究接口不得把描述统计包装成交易或仓位建议。"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from backend.api.middleware import generate_token
from backend.api.routes import vix as vix_routes
from backend.services import vix_factor_study, vix_vol_risk_service


_FORBIDDEN_KEYS = {
    "production_ready_rules",
    "suggested_equity_max",
    "position_rule",
    "production_scope",
    "intent",
    "passed",
}
_FORBIDDEN_ACTION_TEXT = ("加仓", "降仓", "减仓", "杠杆上限", "仓位上限", "买入建议", "卖出建议", "生产就绪")


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _assert_neutral_payload(payload: dict) -> None:
    for node in _walk(payload):
        assert not (_FORBIDDEN_KEYS & set(node))
    rendered = json.dumps(payload, ensure_ascii=False)
    for phrase in _FORBIDDEN_ACTION_TEXT:
        assert phrase not in rendered


def _factor_frame() -> pd.DataFrame:
    n = 80
    bucket = np.array(["extreme_fear"] * 40 + ["fear"] * 40)
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2025-01-01", periods=n).strftime("%Y-%m-%d"),
            "bucket": bucket,
            "composite_percentile": np.where(bucket == "extreme_fear", 5.0, 20.0),
            "composite_score": 50.0,
            "fear_greed": 50.0,
            "spot_mom_5d": 0.0,
            "spot_mom_20d": 0.0,
            "spot_ma60_dev": 1.0,
        }
    )
    for horizon in (5, 10, 20, 60):
        frame[f"fwd_ret_{horizon}d"] = 2.0
        frame[f"fwd_mdd_{horizon}d"] = -1.0
    return frame


def test_factor_study_is_explicitly_exploratory(monkeypatch):
    monkeypatch.setattr(vix_factor_study, "_build_dataset", lambda _days: _factor_frame())

    payload = vix_factor_study._run_vix_factor_study_uncached(365)

    assert payload["study_type"] == "exploratory_descriptive_event_study"
    assert payload["not_a_trading_signal"] is True
    assert payload["validation_status"] == "requires_independent_out_of_sample_validation"
    assert len(payload["limitations"]) >= 4
    assert set(payload["summary"]) == {
        "highest_observed_avg_rule",
        "highest_observed_20d_avg",
        "threshold_met_rules",
    }
    assert all("threshold_met" in rule for rule in payload["rules"])
    _assert_neutral_payload(payload)


def test_factor_study_no_data_keeps_research_warnings(monkeypatch):
    monkeypatch.setattr(vix_factor_study, "_build_dataset", lambda _days: pd.DataFrame())

    payload = vix_factor_study._run_vix_factor_study_uncached(365)

    assert payload["status"] == "no_data"
    assert payload["not_a_trading_signal"] is True
    assert payload["limitations"]
    _assert_neutral_payload(payload)


def test_vol_risk_is_current_trailing_percentile_only(monkeypatch):
    rows = [
        {"date": f"2025-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}", "vix": float(i), "vix_zscore": 0.0}
        for i in range(1, 121)
    ]
    monkeypatch.setattr(vix_vol_risk_service, "get_vix_history", lambda _days: rows)
    monkeypatch.setattr(vix_vol_risk_service, "_CACHE", None)

    payload = vix_vol_risk_service.get_vix_vol_risk_api(force=True)

    assert payload["status"] == "ok"
    assert payload["orientation"] == "higher_score_means_higher_current_qvix_relative_to_trailing_window"
    assert payload["not_a_forecast"] is True
    assert payload["not_position_advice"] is True
    assert payload["latest"]["validation"]["status"] == "experimental"
    assert payload["latest"]["validation"]["evidence_status"] == "legacy_evidence_not_independently_revalidated"
    assert payload["latest"]["data_source"] == "vix_history.vix"
    _assert_neutral_payload(payload)


def test_every_percentile_label_is_descriptive_not_actionable():
    for score in (0, 20, 21, 40, 41, 59, 60, 79, 80, 100):
        level = vix_vol_risk_service._risk_level(score)
        assert {"level", "label", "tone", "message"} == set(level)
        _assert_neutral_payload(level)


def test_routes_preserve_paths_and_neutral_service_responses(monkeypatch):
    from backend.api import app as app_module

    factor_payload = {
        "status": "ok",
        "study_type": "exploratory_descriptive_event_study",
        "not_a_trading_signal": True,
        "limitations": ["需要独立样本验证"],
    }
    vol_payload = {
        "status": "ok",
        "factor": "qvix_trailing_percentile",
        "orientation": "current_value_relative_to_trailing_window",
        "not_a_forecast": True,
        "not_position_advice": True,
    }
    monkeypatch.setattr(vix_routes, "run_vix_factor_study", lambda _days: factor_payload)
    monkeypatch.setattr(vix_routes, "get_vix_vol_risk_api", lambda force=False: vol_payload)
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    monkeypatch.setattr(app_module, "setup_logging", lambda: None)
    app = app_module.create_app(testing=True)
    client = app.test_client()
    headers = {"Authorization": f"Bearer {generate_token('researcher')}"}

    factor_response = client.get("/api/vix/factor-study?days=365", headers=headers)
    vol_response = client.get("/api/vix/vol-risk", headers=headers)

    assert factor_response.status_code == 200
    assert factor_response.get_json() == factor_payload
    assert vol_response.status_code == 200
    assert vol_response.get_json() == vol_payload
    _assert_neutral_payload(factor_response.get_json())
    _assert_neutral_payload(vol_response.get_json())
