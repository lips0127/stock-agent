"""VIX2 时间顺序状态估计与遗留分类器防泄漏的无网络审计测试。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from flask import Flask

from backend.services.vix2_features import CORE_FEATURES


def _dataset(n: int = 260) -> pd.DataFrame:
    x = np.arange(n, dtype=float)
    data = {
        "date": pd.bdate_range("2024-01-02", periods=n).strftime("%Y-%m-%d"),
        "fear_truth": 45 + 8 * np.sin(x / 11) + x * 0.01,
    }
    for pos, feature in enumerate(CORE_FEATURES):
        data[feature] = np.sin(x / (5 + pos)) + x * (pos + 1) / 10000
    return pd.DataFrame(data)


def _legacy_dataset(n: int = 260) -> pd.DataFrame:
    x = np.arange(n, dtype=float)
    data = {
        "date": pd.bdate_range("2023-01-02", periods=n).strftime("%Y-%m-%d"),
        "label": ((x // 3) % 2).astype(int),
    }
    for pos, feature in enumerate(CORE_FEATURES):
        data[feature] = np.sin(x / (4 + pos)) + x * (pos + 1) / 10000
    return pd.DataFrame(data)


class _ConstantPipe:
    def __init__(self, value: float = 50.0):
        self.value = value

    def predict(self, values):
        return np.full(len(values), self.value, dtype=float)


def test_legacy_classifier_uses_horizon_aware_cv_and_oos_embargo(monkeypatch):
    import backend.services.vix2_model as model

    ds = _legacy_dataset()
    monkeypatch.setattr(model, "build_labeled_dataset", lambda features, **kwargs: ds.copy())

    meta = model.train_model(
        label_params={"horizon": 20},
        c_grid=[0.1],
        n_splits=2,
        cv_gap=5,
        save=False,
        features=ds,
    )

    assert meta["label_horizon"] == 20
    assert meta["requested_cv_gap"] == 5
    assert meta["cv_gap"] == 20
    assert all(fold["gap_observations"] == 20 for fold in meta["cv_folds"])
    boundary = meta["oos_boundary"]
    assert boundary["gap_observations"] == 20
    assert boundary["train_end_index"] + meta["label_horizon"] < boundary["oos_start_index"]
    assert meta["legacy_classifier"] is True
    assert meta["predictive_claim"] is False
    assert meta["validation_status"] == "legacy_no_robust_edge"


def test_legacy_train_validates_integer_params_before_task_conflict(monkeypatch):
    import backend.api.routes.vix2 as route

    app = Flask(__name__)

    def fail_if_conflict_check_runs():
        raise AssertionError("active-task check ran before parameter validation")

    monkeypatch.setattr(route, "get_active_task_runs", fail_if_conflict_check_runs)
    invalid_payloads = [
        {"horizon": True},
        {"horizon": 20.5},
        {"horizon": 0},
        {"horizon": 61},
        {"cv_gap": False},
        {"cv_gap": 5.5},
        {"cv_gap": 4},
        {"cv_gap": 61},
    ]
    for payload in invalid_payloads:
        with app.test_request_context(json=payload):
            response, status = route.train_vix2_route.__wrapped__()
        assert status == 400
        assert "error" in response.get_json()


def _patch_walkforward(monkeypatch, ds):
    import backend.services.vix2_service as service
    import backend.services.vix2_truth_labels as labels

    calls = []
    writes = []
    metas = []

    monkeypatch.setattr(labels, "build_truth_labeled_dataset", lambda: ds.copy())

    def fake_train(full_ds, cutoff_idx, **kwargs):
        calls.append((len(full_ds), cutoff_idx, kwargs))
        return {
            "pipe": _ConstantPipe(),
            "train_cutoff": str(full_ds.iloc[cutoff_idx - 1]["date"]),
            "n_train": cutoff_idx,
            "cv_gap": kwargs["cv_gap"],
            "cv_folds": [{"gap_observations": kwargs["cv_gap"]}],
        }

    monkeypatch.setattr(service, "train_truth_at_cutoff", fake_train)
    monkeypatch.setattr(
        service, "upsert_vix2_truth",
        lambda date, score, version, cutoff: writes.append((date, version, cutoff)),
    )
    monkeypatch.setattr(service, "get_vix2_truth_scores_asc", lambda: [])
    monkeypatch.setattr(service, "recompute_vix2_truth_percentiles", lambda: {"updated": len(writes)})
    monkeypatch.setattr(service, "save_walkforward_meta", lambda meta: metas.append(meta.copy()))
    return service, calls, writes, metas


def test_days_limits_output_without_truncating_training_history(monkeypatch):
    ds = _dataset(260)
    service, calls, writes, metas = _patch_walkforward(monkeypatch, ds)

    result = service.backfill_vix2_walkforward(
        days=12, block_size=5, cv_gap=5, min_train_samples=40,
    )

    assert calls[0][0] == 260
    assert calls[0][1] == 248
    assert len(writes) == 12
    assert result["output_samples"] == 12
    assert metas[0]["dataset_samples"] == 260
    assert all(cutoff < date for date, _, cutoff in writes)


def test_exact_min_train_gap_baseline_and_target_disclosure(monkeypatch):
    ds = _dataset(58)
    service, calls, writes, _ = _patch_walkforward(monkeypatch, ds)

    result = service.backfill_vix2_walkforward(
        days=0, block_size=6, cv_gap=7, min_train_samples=40,
    )

    assert calls[0][1] == 40
    assert calls[0][2]["cv_gap"] == 7
    assert writes[0][0] == ds.iloc[40]["date"]
    assert "model_oos_mae" in result
    assert "baseline_lag1_oos_mae" in result
    assert result["validation_status"] == "no_robust_edge"
    assert result["target_horizon"] == "same_day"
    assert result["breadth_available"] is False
    assert result["breadth_component_used"] is False
    assert result["predictive_claim"] is False


def test_train_cutoff_cv_gap_is_auditable():
    from backend.services.vix2_model import train_truth_at_cutoff

    ds = _dataset(90)
    trained = train_truth_at_cutoff(
        ds, cutoff_idx=60, alpha_grid=[1.0], n_splits=2,
        cv_gap=5, min_train_samples=40,
    )

    assert trained is not None
    assert trained["n_train"] == 60
    assert trained["train_cutoff"] == ds.iloc[59]["date"]
    assert trained["train_cutoff"] < ds.iloc[60]["date"]
    assert trained["cv_gap"] == 5
    assert all(fold["gap_observations"] >= 5 for fold in trained["cv_folds"])


def test_fear_percentile_regime_direction(monkeypatch):
    import backend.services.vix2_service as service

    assert service.classify_fear_percentile(95) == "极度恐慌"
    assert service.classify_fear_percentile(80) == "恐慌"
    assert service.classify_fear_percentile(50) == "中性"
    assert service.classify_fear_percentile(20) == "平静"
    assert service.classify_fear_percentile(5) == "极度平静"

    persisted = []
    monkeypatch.setattr(service, "get_vix2_truth_scores_asc", lambda: [
        (f"2026-01-{day:02d}", float(day)) for day in range(1, 11)
    ])
    monkeypatch.setattr(
        service, "update_vix2_truth_percentile",
        lambda date, percentile, regime: persisted.append((date, percentile, regime)),
    )
    service.recompute_vix2_truth_percentiles(window=252)

    assert persisted[-1] == ("2026-01-10", 100.0, "极度恐慌")


def test_truth_regime_migration_and_legacy_upsert_preserves_truth(tmp_path, monkeypatch):
    import backend.core.database as db

    db_path = Path(tmp_path) / "stocks.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE vix2_history ("
            "date TEXT PRIMARY KEY, p_up REAL, score REAL, percentile REAL, "
            "regime TEXT, model_version TEXT, features_json TEXT)"
        )
    monkeypatch.setattr(db, "_DB_PATH", db_path)
    db.init_db()

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(vix2_history)")}
    assert "truth_regime" in columns

    db.upsert_vix2_truth("2026-01-05", 61.2, "vix2-wf-a", "2026-01-02")
    db.update_vix2_truth_percentile("2026-01-05", 82.0, "恐慌")
    db.upsert_vix2_history("2026-01-05", {
        "p_up": 0.4, "score": 60.0, "model_version": "legacy",
        "features_json": {},
    })

    row = db.get_vix2_latest()
    assert row["fear_truth"] == 61.2
    assert row["truth_regime"] == "恐慌"
    assert row["truth_model_version"] == "vix2-wf-a"
    assert row["truth_train_cutoff"] == "2026-01-02"
