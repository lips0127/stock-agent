# -*- coding: utf-8 -*-
"""batch_analyze 显式 codes 路径回归测试（2026-09-01 生产 bug）。

事故：batch_analyze(codes=[...]) 时 code_to_name 只在 codes=None 分支绑定，
进度路径 code_to_name.get(c, "") 触发 UnboundLocalError，整批崩溃记失败。
单只补跑/重试场景必现。
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _setup_temp_db() -> None:
    d = tempfile.mkdtemp()
    os.environ["CACHE_DIR"] = d
    import backend.core.database as db_mod
    import backend.core.db_compat as compat_mod
    import importlib
    importlib.reload(compat_mod)
    importlib.reload(db_mod)
    db_mod._DB_PATH = Path(d) / "stocks.db"
    db_mod.init_db()


class TestBatchAnalyzeExplicitCodes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _setup_temp_db()
        from backend.core.database import get_connection
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO sentiment_config (stock_code, stock_name, forum_type, enabled)"
                " VALUES ('600036', '招商银行', 'eastmoney', 1)"
            )

    def test_explicit_codes_does_not_crash(self):
        """显式传 codes 的批量分析不得因 code_to_name 未绑定而崩溃。"""
        import backend.services.sentiment_service as ss

        with patch.object(
            ss, "analyze_sentiment",
            return_value={"score": 50.0, "sentiment": "中性", "post_count": 3},
        ):
            results = ss.batch_analyze(codes=["600036"])

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].get("code"), "600036")

    def test_codes_are_normalized(self):
        """传入非 6 位代码会被 zfill 归一。"""
        import backend.services.sentiment_service as ss

        captured = []

        def fake_analyze(code, forum_type="eastmoney"):
            captured.append(code)
            return {"score": 50.0}

        with patch.object(ss, "analyze_sentiment", side_effect=fake_analyze):
            ss.batch_analyze(codes=["36"])

        self.assertEqual(captured, ["000036"])


if __name__ == "__main__":
    unittest.main()
