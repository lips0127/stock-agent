"""生产就绪安全审计 CLI。

用法：
    python -m backend.security_check [--allow-localhost-cors]

读取当前环境变量（与容器 entrypoint 同源），校验：
  1. JWT_SECRET 已显式配置、长度 >= 32、非示例值（未配置 = 进程内随机密钥，判不通过）；
  2. 管理员用户名/密码非默认、非示例、密码 >= 12 位；
  3. CORS_ORIGINS 无通配符、（默认）不含 localhost / 127.0.0.1；
  4. APP_DEBUG 未开启。

退出码：0 = 通过；1 = 存在不通过项；2 = 用法错误。
绝不回显任何密钥值，只输出长度与指纹前缀。

本地开发（.env 无 JWT_SECRET、默认管理员）跑此命令判不通过是预期行为——
它审计的是「可以公网暴露」的生产就绪度，不阻塞本地调试。
"""

import hashlib
import os
import sys

_EXAMPLE_SECRET_FRAGMENTS = (
    "replace",
    "change-me",
    "change_me",
    "changeme",
    "placeholder",
    "example",
    "your_",
    "your-",
)

_EXAMPLE_USER_FRAGMENTS = ("change_me", "changeme", "placeholder", "example")
_EXAMPLE_PASSWORD_FRAGMENTS = ("change_me", "changeme", "placeholder", "example", "admin123")


def _fingerprint(value: str) -> str:
    """密钥指纹前缀：可核对是否一致，但不可还原原值。"""
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"sha256:{digest[:12]}…"


class Check:
    def __init__(self, name: str, passed: bool, detail: str):
        self.name = name
        self.passed = passed
        self.detail = detail


def check_jwt_secret(value: str | None) -> Check:
    name = "JWT_SECRET"
    if not value:
        return Check(name, False, "未配置：当前会回退为进程内随机密钥（重启失效、多进程不互通），不可用于生产")
    lowered = value.lower()
    if len(value) < 32:
        return Check(name, False, f"长度 {len(value)} < 32（指纹 {_fingerprint(value)}）")
    for fragment in _EXAMPLE_SECRET_FRAGMENTS:
        if fragment in lowered:
            return Check(name, False, f"包含示例值片段“{fragment}”，疑似未替换模板")
    return Check(name, True, f"长度 {len(value)}（指纹 {_fingerprint(value)}）")


def check_admin_user(value: str | None) -> Check:
    name = "DEFAULT_ADMIN_USER"
    if not value:
        return Check(name, False, "未配置")
    lowered = value.lower()
    if lowered == "admin":
        return Check(name, False, "使用了默认用户名 admin")
    for fragment in _EXAMPLE_USER_FRAGMENTS:
        if fragment in lowered:
            return Check(name, False, f"包含示例值片段“{fragment}”")
    return Check(name, True, f"“{value}”非默认/示例值")


def check_admin_password(value: str | None) -> Check:
    name = "DEFAULT_ADMIN_PASSWORD"
    if not value:
        return Check(name, False, "未配置")
    lowered = value.lower()
    if len(value) < 12:
        return Check(name, False, f"长度 {len(value)} < 12")
    if lowered == "admin123":
        return Check(name, False, "使用了示例密码 admin123")
    for fragment in _EXAMPLE_PASSWORD_FRAGMENTS:
        if fragment in lowered:
            return Check(name, False, f"包含示例值片段“{fragment}”")
    return Check(name, True, f"长度 {len(value)}，非默认/示例值")


def check_cors_origins(value: str | None, allow_localhost: bool = False) -> Check:
    name = "CORS_ORIGINS"
    if not value:
        return Check(name, False, "未配置")
    if "*" in value:
        return Check(name, False, "包含通配符 *，必须显式列出受信来源")
    origins = [o.strip() for o in value.split(",") if o.strip()]
    if not origins:
        return Check(name, False, "没有列出任何来源")
    if not allow_localhost:
        local = [o for o in origins if "localhost" in o or "127.0.0.1" in o]
        if local:
            return Check(name, False, f"包含本机来源 {local}（生产不允许；本地联调加 --allow-localhost-cors）")
    return Check(name, True, f"{len(origins)} 个显式来源")


def check_debug(value: str | None) -> Check:
    name = "APP_DEBUG"
    lowered = (value or "").strip().lower()
    if lowered in ("1", "true", "yes"):
        return Check(name, False, "生产环境必须关闭 DEBUG")
    return Check(name, True, "APP_DEBUG 未开启")


def run_checks(allow_localhost_cors: bool = False) -> list[Check]:
    return [
        check_jwt_secret(os.environ.get("JWT_SECRET")),
        check_admin_user(os.environ.get("DEFAULT_ADMIN_USER")),
        check_admin_password(os.environ.get("DEFAULT_ADMIN_PASSWORD")),
        check_cors_origins(os.environ.get("CORS_ORIGINS"), allow_localhost_cors),
        check_debug(os.environ.get("APP_DEBUG")),
    ]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    allow_localhost = False
    for arg in argv:
        if arg == "--allow-localhost-cors":
            allow_localhost = True
        elif arg in ("-h", "--help"):
            print(__doc__)
            return 0
        else:
            print(f"未知参数: {arg}", file=sys.stderr)
            return 2

    checks = run_checks(allow_localhost_cors=allow_localhost)
    for check in checks:
        mark = "PASS" if check.passed else "FAIL"
        print(f"[{mark}] {check.name}: {check.detail}")
    failed = [c for c in checks if not c.passed]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} 项通过。")
    if failed:
        print("存在不通过项：当前配置不可公开部署。", file=sys.stderr)
        return 1
    print("生产就绪检查全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
