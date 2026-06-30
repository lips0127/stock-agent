"""
全局代理强制直连（2026-06-15）。

设计动机
--------
工程部署在用户本地（Windows 11 + Clash 127.0.0.1:7890 系统代理）。
requests/akshare 走 ``requests.sessions`` → 默认会读 Windows 注册表系统代理
（不在 ProxyOverride 白名单里的域全部经 Clash 出网 → Clash 又因为目标 IP
被规则判为「直连」→ Remote end closed connection）。

修复策略
--------
**在进程启动的最早时机**（``backend.api.app`` import 阶段）执行一次
``install_proxy_bypass()``，做四件事：

1. **清空代理 env**：移除 ``HTTP_PROXY`` / ``HTTPS_PROXY`` / ``http_proxy`` /
   ``https_proxy`` / ``ALL_PROXY`` / ``all_proxy``。``NO_PROXY`` 保留不动。

2. **patch ``requests.sessions.resolve_proxies``**：这是最关键的修复。
   ``Session.request`` 内部 ``prepare_request(prep, self.proxies, ...)``
   会调 ``resolve_proxies(prep, self.proxies, self.trust_env)`` 解析最终
   代理列表。``self.proxies`` 默认是 ``{}``，``self.trust_env=True`` →
   ``resolve_proxies`` 走 ``get_environ_proxies`` 读 Windows 注册表 →
   出口带 ``OrderedDict([('http', '...'), ('https', '...'), ('ftp', '...')])``
   → 走代理。patch 这一函数让任何调用都返回 ``{http: None, https: None}``，
   一了百了。

3. **patch ``requests.Session.send``**：双保险 — 显式把
   ``kwargs['proxies']`` 设为 ``{http: None, https: None}``。

4. **patch ``urllib3.connectionpool.HTTPSConnectionPool.urlopen``**：
   防御性兜底，覆盖未来可能直接 ``urllib3.PoolManager().request(...)`` 的
   代码。

**幂等**：多次调用安全。
**零迁移成本**：`stock_service._no_proxy()` 上下文管理器保留为 no-op，
``with _no_proxy(): ...`` 在 30+ 处现有调用点 0 改动。

不在范围
--------
- 不动 ``smtplib``：SMTP 是 TCP 直连，不受 Win 系统代理影响，但有专门的
  ``SMTP_PROXY`` env 兜底（见 ``services/email_service.py``）。
- 不动 Linux / Docker 部署。
"""

from __future__ import annotations

import os
from typing import Any

# 代理环境变量键（与 stock_service._PROXY_KEYS / historical.py._PROXY_KEYS 保持一致）
_PROXY_KEYS = (
    "HTTP_PROXY", "HTTPS_PROXY",
    "http_proxy", "https_proxy",
    "ALL_PROXY", "all_proxy",
)

# 全局统一的"无代理"proxies 字典
_NO_PROXIES: dict = {"http": None, "https": None}

_installed: bool = False


def _strip_proxy_env() -> None:
    """永久清空代理 env。NO_PROXY 保留不动。"""
    for k in _PROXY_KEYS:
        os.environ.pop(k, None)


def _make_no_proxy_resolve(orig_resolve):
    """构造一个永远返回 {http: None, https: None} 的 resolve_proxies。

    这是修复的核心入口。``Session.request`` 内部会调
    ``resolve_proxies(prep, self.proxies, self.trust_env)``，而原始
    实现会读 Windows 注册表 / 环境变量 → 输出系统代理列表。patch 后
    不论传入什么 proxies / trust_env，都返回空代理 dict，请求直连。
    """
    def _no_proxy_resolve(request, proxies, trust_env=True):
        # 完全绕开原始实现，不读 env / 注册表 / session.proxies
        return dict(_NO_PROXIES)
    return _no_proxy_resolve


def _make_no_proxy_session_send(orig_send):
    """双保险：在 send 阶段把 proxies 强制设空。"""
    def _no_proxy_send(self, request, **kwargs):
        kwargs["proxies"] = _NO_PROXIES
        return orig_send(self, request, **kwargs)
    return _no_proxy_send


def _patch_requests() -> None:
    """patch resolve_proxies（核心）+ Session.send（双保险）。"""
    import requests
    from requests import sessions as _sessions

    # 1. patch resolve_proxies — 核心修复
    if not getattr(_sessions.resolve_proxies, "_proxy_bypass_installed", False):
        orig_resolve = _sessions.resolve_proxies
        new_resolve = _make_no_proxy_resolve(orig_resolve)
        new_resolve._proxy_bypass_installed = True  # type: ignore[attr-defined]
        _sessions.resolve_proxies = new_resolve
        # requests 顶层也 re-export 了，要同步覆盖
        if hasattr(requests, "resolve_proxies"):
            requests.resolve_proxies = new_resolve  # type: ignore[attr-defined]

    # 2. patch Session.send（双保险）
    if not getattr(requests.Session.send, "_proxy_bypass_installed", False):
        orig_send = requests.Session.send
        new_send = _make_no_proxy_session_send(orig_send)
        new_send._proxy_bypass_installed = True  # type: ignore[attr-defined]
        requests.Session.send = new_send  # type: ignore[assignment]


def _patch_urllib3() -> None:
    """patch urllib3 HTTPSConnectionPool.urlopen（防御性兜底）。"""
    try:
        from urllib3.connectionpool import HTTPSConnectionPool
    except ImportError:
        return

    if getattr(HTTPSConnectionPool.urlopen, "_proxy_bypass_installed", False):
        return

    orig_urlopen = HTTPSConnectionPool.urlopen

    def _no_proxy_urlopen(self, method, url, *args, **kwargs):
        kwargs.pop("proxies", None)
        kwargs.pop("proxy", None)
        kwargs.pop("proxy_headers", None)
        if getattr(self, "proxy", None):
            self.proxy = None
        return orig_urlopen(self, method, url, *args, **kwargs)

    _no_proxy_urlopen._proxy_bypass_installed = True  # type: ignore[attr-defined]
    HTTPSConnectionPool.urlopen = _no_proxy_urlopen  # type: ignore[assignment]


def install_proxy_bypass() -> None:
    """安装全局代理直连 patch。幂等。"""
    global _installed
    if _installed:
        return
    _strip_proxy_env()
    _patch_requests()
    _patch_urllib3()
    _installed = True


def is_installed() -> bool:
    """查询 patch 是否已安装（用于测试 / 健康检查）。"""
    return _installed


# ── 向后兼容：保留 no-op 上下文管理器 ──
# 老代码 `with _no_proxy(): ...` 全部继续工作（语义：标记"这里不应当走代理"）。
# 实际保护由 install_proxy_bypass() 的全局 patch 提供。
class _NoProxyContext:
    """``with _no_proxy(): ...`` 的 no-op 实现。保留是为了可读性 +
    显式标注「此处不应当走代理」的设计意图。
    """

    def __enter__(self) -> "_NoProxyContext":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


def no_proxy():
    """返回 no-op 上下文管理器。"""
    return _NoProxyContext()
