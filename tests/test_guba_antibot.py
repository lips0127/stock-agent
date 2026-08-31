"""guba 引导壳（速率型反爬）处理逻辑测试。

v9 2026-08-31 背景：实测 guba 详情页引导壳是速率型间歇反爬，与 cookie 无关
（空 cookie 也能取正文）。本测试离线 mock HTTP 层，验证：
- 引导壳触发退避重试（_SHELL_BACKOFFS 预算），恢复后返回正文
- 退避耗尽置 _COOKIE_STALE，前端可见告警
- stale 期间非探测窗口快速失败；探测窗口放行一次请求
- 详情页成功后 stale 自动复位（自愈）
- 详情页全局节流：并发线程共享最小间隔
"""

import unittest
import threading
import time
from unittest.mock import patch

import backend.services.forum_service as fs


class _FakeResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text

    def json(self):
        raise ValueError("not json")


# 一段含 post_article 的正常详情页（截取到足够特征即可，解析走真实代码）
_OK_DETAIL = '<html><script>var post_article = {"post_id": 1, "post_title": "测试标题", "post_content": "正文内容"};</script></html>'
_SHELL_DETAIL = '<html><head><title>身份核实</title></head><body><div id="root"></div></body></html>'


def _make_get(script):
    """构造 mock 的 _GUBA_SESSION.get，按脚本序列返回响应。"""
    calls = {"n": 0}

    def get(url, timeout=None):
        i = min(calls["n"], len(script) - 1)
        calls["n"] += 1
        return script[i]
    return get, calls


class GubaShellRetryTests(unittest.TestCase):
    def setUp(self):
        # 每个用例重置全局状态，避免用例间串扰
        fs._COOKIE_STALE = False
        fs._last_shell_warn_ts = 0.0
        fs._last_shell_probe_ts = 0.0
        # 退避设 0，测试不真正 sleep
        self._orig_backoffs = fs._SHELL_BACKOFFS
        fs._SHELL_BACKOFFS = (0.0, 0.0)
        # 节流关掉（单线程顺序请求，不测节流时避免拖慢）
        self._orig_interval = fs.GUBA_DETAIL_MIN_INTERVAL
        fs.GUBA_DETAIL_MIN_INTERVAL = 0.0

    def tearDown(self):
        fs._COOKIE_STALE = False
        fs._SHELL_BACKOFFS = self._orig_backoffs
        fs.GUBA_DETAIL_MIN_INTERVAL = self._orig_interval

    def test_shell_then_recover_returns_content(self):
        """壳 -> 退避重试 -> 恢复：返回正文且不置 stale。"""
        script = [
            _FakeResponse(text=_SHELL_DETAIL),   # 第 1 次：壳
            _FakeResponse(text=_OK_DETAIL),      # 退避后重试：成功
        ]
        get, calls = _make_get(script)
        with patch.object(fs._GUBA_SESSION, "get", side_effect=get):
            r = fs._http_get_with_retry(
                "https://guba.eastmoney.com/news,600584,123.html", {}, timeout=1)
        self.assertIn("post_article", r.text)
        self.assertEqual(calls["n"], 2)
        self.assertFalse(fs._COOKIE_STALE)

    def test_shell_persistent_sets_stale(self):
        """退避耗尽仍壳 -> 置 stale，返回壳（上层转 fetch_error）。"""
        get, calls = _make_get([_FakeResponse(text=_SHELL_DETAIL)])
        with patch.object(fs._GUBA_SESSION, "get", side_effect=get):
            r = fs._http_get_with_retry(
                "https://guba.eastmoney.com/news,600584,123.html", {}, timeout=1)
        self.assertIn('id="root"', r.text)
        self.assertTrue(fs._COOKIE_STALE)
        # 1 次原始 + 2 次退避重试 = 3 次
        self.assertEqual(calls["n"], 3)

    def test_stale_probe_window_fast_fail_then_probe(self):
        """stale 后：非探测窗口无退避重试（快速失败）；到窗口后带退避探测并自愈。"""
        # 窗口关闭：壳响应不触发退避重试，直接返回壳
        shell_get, shell_calls = _make_get([_FakeResponse(text=_SHELL_DETAIL)])
        fs._COOKIE_STALE = True
        fs._last_shell_probe_ts = time.time()  # 刚探测过 -> 窗口关闭
        with patch.object(fs._GUBA_SESSION, "get", side_effect=shell_get):
            r = fs._http_get_with_retry(
                "https://guba.eastmoney.com/news,600584,123.html", {}, timeout=1)
        self.assertIn('id="root"', r.text)
        # 仅 1 次请求（原始），无退避重试
        self.assertEqual(shell_calls["n"], 1)
        # stale 保持（壳未被恢复）
        self.assertTrue(fs._COOKIE_STALE)

        # 窗口到期：放行探测（壳 -> 退避 -> 成功），成功后复位 stale
        script = [
            _FakeResponse(text=_SHELL_DETAIL),
            _FakeResponse(text=_OK_DETAIL),
        ]
        ok_get, ok_calls = _make_get(script)
        fs._last_shell_probe_ts = time.time() - 3600
        with patch.object(fs._GUBA_SESSION, "get", side_effect=ok_get):
            r = fs._http_get_with_retry(
                "https://guba.eastmoney.com/news,600584,123.html", {}, timeout=1)
        self.assertIn("post_article", r.text)
        self.assertFalse(fs._COOKIE_STALE, "探测成功应复位 stale")

    def test_success_resets_stale(self):
        """stale 状态下探测请求成功 -> 自动复位（自愈）。"""
        get, _ = _make_get([_FakeResponse(text=_OK_DETAIL)])
        fs._COOKIE_STALE = True
        fs._last_shell_probe_ts = time.time() - 3600
        with patch.object(fs._GUBA_SESSION, "get", side_effect=get):
            fs._http_get_with_retry(
                "https://guba.eastmoney.com/news,600584,123.html", {}, timeout=1)
        self.assertFalse(fs._COOKIE_STALE)

    def test_list_page_shell_does_not_affect_stale(self):
        """列表页不参与节流/自愈语义：成功列表页不应复位 stale（详情页专属）。"""
        get, _ = _make_get([_FakeResponse(text="x" * 5000)])
        fs._COOKIE_STALE = True
        with patch.object(fs._GUBA_SESSION, "get", side_effect=get):
            r = fs._http_get_with_retry(
                "https://guba.eastmoney.com/list,600584.html", {}, timeout=1)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(fs._COOKIE_STALE, "列表页成功不应复位 stale")


class GubaThrottleTests(unittest.TestCase):
    def setUp(self):
        fs._COOKIE_STALE = False
        self._orig_interval = fs.GUBA_DETAIL_MIN_INTERVAL
        self._last = fs._last_detail_req_ts

    def tearDown(self):
        fs.GUBA_DETAIL_MIN_INTERVAL = self._orig_interval
        fs._last_detail_req_ts = self._last

    def test_detail_throttle_enforces_interval(self):
        """两个详情页请求之间至少间隔 GUBA_DETAIL_MIN_INTERVAL。"""
        fs.GUBA_DETAIL_MIN_INTERVAL = 0.3
        fs._last_detail_req_ts[0] = 0.0
        timestamps = []

        def fake_get(url, timeout=None):
            timestamps.append(time.time())
            return _FakeResponse(text=_OK_DETAIL)

        with patch.object(fs._GUBA_SESSION, "get", side_effect=fake_get):
            fs._http_get_with_retry(
                "https://guba.eastmoney.com/news,600584,1.html", {}, timeout=1)
            fs._http_get_with_retry(
                "https://guba.eastmoney.com/news,600584,2.html", {}, timeout=1)
        self.assertEqual(len(timestamps), 2)
        self.assertGreaterEqual(timestamps[1] - timestamps[0], 0.25)

    def test_list_page_not_throttled(self):
        """列表页请求不受节流约束。"""
        fs.GUBA_DETAIL_MIN_INTERVAL = 5.0  # 若列表页被节流会用时 > 5s / 卡死
        fs._last_detail_req_ts[0] = 0.0
        t0 = time.time()
        fake_get = lambda url, timeout=None: _FakeResponse(text="x" * 5000)
        with patch.object(fs._GUBA_SESSION, "get", side_effect=fake_get):
            fs._http_get_with_retry(
                "https://guba.eastmoney.com/list,600584.html", {}, timeout=1)
        self.assertLess(time.time() - t0, 1.0)

    def test_concurrent_detail_requests_do_not_overlap(self):
        """并发线程的详情页请求在时间上互不重叠（预约时隙）。"""
        fs.GUBA_DETAIL_MIN_INTERVAL = 0.2
        fs._last_detail_req_ts[0] = 0.0
        stamps = []
        lock = threading.Lock()

        def fake_get(url, timeout=None):
            with lock:
                stamps.append(time.time())
            return _FakeResponse(text=_OK_DETAIL)

        threads = []
        with patch.object(fs._GUBA_SESSION, "get", side_effect=fake_get):
            for i in range(4):
                t = threading.Thread(target=fs._http_get_with_retry, args=(
                    f"https://guba.eastmoney.com/news,600584,{i}.html", {}, 1))
                threads.append(t)
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(len(stamps), 4)
        stamps.sort()
        for a, b in zip(stamps, stamps[1:]):
            self.assertGreaterEqual(b - a, 0.15)


class GubaCookieFileTests(unittest.TestCase):
    """采集 cookie 文件热加载（tools/guba_cookie_harvest.py 的服务侧）。"""

    def setUp(self):
        fs._COOKIE_STALE = False
        self._orig_mtime = fs._cookie_file_mtime[0]
        self._orig_file = fs._COOKIE_FILE

    def tearDown(self):
        fs._cookie_file_mtime[0] = self._orig_mtime
        fs._COOKIE_FILE = self._orig_file
        fs._inject_bootstrap_cookies.__globals__["_cookie_file_mtime"][0] = self._orig_mtime

    def test_load_cookie_file_playwright_format(self):
        """playwright list 格式加载并热换新 jar。"""
        import json as _json
        import tempfile
        import os

        payload = [
            {"name": "qgqp_b_id", "value": "fresh1", "domain": ".eastmoney.com"},
            {"name": "new_token", "value": "v2", "domain": ".eastmoney.com"},
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            _json.dump(payload, f)
            path = f.name
        try:
            fs._COOKIE_FILE = __import__("pathlib").Path(path)
            fs._cookie_file_mtime[0] = None
            # 触发注入：文件存在 -> 清 jar 换新
            jar = {}
            real_set = fs._GUBA_SESSION.cookies.set
            real_clear = fs._GUBA_SESSION.cookies.clear
            real_keys = fs._GUBA_SESSION.cookies.keys
            fs._GUBA_SESSION.cookies.set = lambda k, v, domain=None: jar.__setitem__(k, v)
            fs._GUBA_SESSION.cookies.clear = lambda: jar.clear()
            fs._GUBA_SESSION.cookies.keys = lambda: list(jar)
            try:
                fs._inject_bootstrap_cookies()
            finally:
                fs._GUBA_SESSION.cookies.set = real_set
                fs._GUBA_SESSION.cookies.clear = real_clear
                fs._GUBA_SESSION.cookies.keys = real_keys
            self.assertEqual(jar, {"qgqp_b_id": "fresh1", "new_token": "v2"})
            # mtime 未变时不再重读（返回 None 路径）
            self.assertEqual(fs._load_cookie_file(), None)
        finally:
            os.unlink(path)

    def test_load_cookie_file_missing_returns_none(self):
        import pathlib
        fs._COOKIE_FILE = pathlib.Path("Z:/nonexistent/guba_cookies.json")
        fs._cookie_file_mtime[0] = None
        self.assertIsNone(fs._load_cookie_file())


if __name__ == "__main__":
    unittest.main()
