"""生产就绪安全审计 CLI（backend.security_check）测试。"""

import backend.security_check as sc


def test_jwt_secret_checks():
    assert not sc.check_jwt_secret(None).passed
    assert not sc.check_jwt_secret("short").passed
    assert not sc.check_jwt_secret("a" * 40 + "CHANGE-ME").passed
    ok = sc.check_jwt_secret("xK9mQ2vL7pR4wT8yZ1nB6cD3fG5hJ0sU")
    assert ok.passed
    # 指纹不泄露原值
    assert "xK9mQ2" not in ok.detail


def test_admin_credential_checks():
    assert not sc.check_admin_user("admin").passed
    assert not sc.check_admin_user(None).passed
    assert not sc.check_admin_user("CHANGE_ME_ADMIN").passed
    assert sc.check_admin_user("weizhou").passed

    assert not sc.check_admin_password("admin123").passed
    assert not sc.check_admin_password("short12").passed
    assert not sc.check_admin_password(None).passed
    assert sc.check_admin_password("Tv9#mK2wQ!zR").passed
    # 不回显密码
    assert "Tv9#" not in sc.check_admin_password("Tv9#mK2wQ!zR").detail


def test_cors_and_debug_checks():
    assert not sc.check_cors_origins("*").passed
    assert not sc.check_cors_origins(None).passed
    assert not sc.check_cors_origins("http://localhost:5173").passed
    assert not sc.check_cors_origins("http://127.0.0.1:5173").passed
    assert sc.check_cors_origins("http://localhost:5173", allow_localhost=True).passed
    assert sc.check_cors_origins("https://example.com,https://app.example.com").passed

    assert not sc.check_debug("true").passed
    assert not sc.check_debug("1").passed
    assert sc.check_debug("false").passed
    assert sc.check_debug(None).passed


def test_run_checks_and_exit_codes(monkeypatch, capsys):
    strong = {
        "JWT_SECRET": "xK9mQ2vL7pR4wT8yZ1nB6cD3fG5hJ0sU",
        "DEFAULT_ADMIN_USER": "weizhou",
        "DEFAULT_ADMIN_PASSWORD": "Tv9#mK2wQ!zR",
        "CORS_ORIGINS": "https://example.com",
        "APP_DEBUG": "false",
    }
    monkeypatch.setenv("JWT_SECRET", strong["JWT_SECRET"])
    monkeypatch.setenv("DEFAULT_ADMIN_USER", strong["DEFAULT_ADMIN_USER"])
    monkeypatch.setenv("DEFAULT_ADMIN_PASSWORD", strong["DEFAULT_ADMIN_PASSWORD"])
    monkeypatch.setenv("CORS_ORIGINS", strong["CORS_ORIGINS"])
    monkeypatch.setenv("APP_DEBUG", strong["APP_DEBUG"])

    assert all(c.passed for c in sc.run_checks())
    assert sc.main([]) == 0

    monkeypatch.setenv("JWT_SECRET", "weak")
    assert sc.main([]) == 1
    out = capsys.readouterr().out
    assert "[FAIL] JWT_SECRET" in out
    assert "weak" not in out  # 不回显不通过值


def test_unknown_argument_exit_2():
    assert sc.main(["--nope"]) == 2
