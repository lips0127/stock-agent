"""安全响应头（安全模块）测试。"""

import pytest

pytest.importorskip("flask_cors")

from backend.api.middleware import _DOCUMENT_CSP, install_security_headers
from backend.api.app import create_app


@pytest.fixture()
def app_with_html(monkeypatch):
    monkeypatch.setenv("ENABLE_HSTS", "false")
    import backend.api.middleware as mw

    monkeypatch.setattr(mw, "ENABLE_HSTS", False)
    app = create_app(testing=True)

    @app.route("/__test_html")
    def __test_html():
        return "<html><body>ok</body></html>", 200

    return app


@pytest.fixture()
def client(app_with_html):
    return app_with_html.test_client()


def test_every_response_carries_baseline_security_headers(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_html_documents_get_csp_json_does_not(client):
    html = client.get("/__test_html")
    assert html.headers["Content-Security-Policy"] == _DOCUMENT_CSP
    assert "frame-ancestors 'none'" in html.headers["Content-Security-Policy"]
    assert "script-src 'self'" in html.headers["Content-Security-Policy"]

    json_resp = client.get("/health")
    assert "Content-Security-Policy" not in json_resp.headers


def test_hsts_absent_by_default_present_when_enabled(monkeypatch):
    import backend.api.middleware as mw

    monkeypatch.setattr(mw, "ENABLE_HSTS", False)
    app = create_app(testing=True)
    client = app.test_client()
    assert "Strict-Transport-Security" not in client.get("/health").headers

    monkeypatch.setattr(mw, "ENABLE_HSTS", True)
    app2 = create_app(testing=True)
    resp = app2.test_client().get("/health")
    assert resp.headers["Strict-Transport-Security"] == (
        "max-age=31536000; includeSubDomains"
    )


def test_existing_headers_not_overwritten(app_with_html):
    @app_with_html.route("/__test_custom")
    def __test_custom():
        resp = app_with_html.response_class("x", 200)
        resp.headers["X-Frame-Options"] = "SAMEORIGIN"
        return resp

    resp = app_with_html.test_client().get("/__test_custom")
    # setdefault 语义：应用显式设置的头不被覆盖
    assert resp.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
