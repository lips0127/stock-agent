# -*- coding: utf-8 -*-
"""腾讯云服务器运维工具 —— 单容器部署的远程操作封装。

用法（仓库根目录执行）：
    python scripts/server_ops.py status          # 容器/磁盘/健康状态
    python scripts/server_ops.py deploy          # 打包 HEAD -> 上传 -> compose up -d --build
    python scripts/server_ops.py logs [N]        # 查看应用日志（默认 100 行）
    python scripts/server_ops.py health          # 服务器本机 + 本地外网两级健康检查
    python scripts/server_ops.py backup          # app-data 卷打包到服务器 ~/backups/
    python scripts/server_ops.py exec "命令"     # 在服务器上执行任意命令

连接信息读仓库根目录的 ``server.local.json``（已 gitignore，绝不入库）：

    {"host": "x.x.x.x", "user": "ubuntu", "port": 22,
     "key": "tencent_key", "app_dir": "/opt/stock-agent"}

首次使用复制 ``server.local.example.json`` 为 ``server.local.json`` 填写真实值。
"""

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "server.local.json"

# 远端命令统一非交互：BatchMode 禁止密码提示（密钥失败直接报错而非挂住）
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        sys.exit(
            f"缺少配置文件 {CONFIG_PATH}\n"
            "复制 server.local.example.json 为 server.local.json 并填入真实服务器信息。"
        )
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    for field in ("host", "user", "key", "app_dir"):
        if not cfg.get(field):
            sys.exit(f"server.local.json 缺少字段: {field}")
    cfg.setdefault("port", 22)
    key = Path(cfg["key"])
    if not key.is_absolute():
        key = ROOT / key
    if not key.exists():
        sys.exit(f"私钥不存在: {key}")
    cfg["key_path"] = str(key)
    return cfg


def _base_ssh_args(cfg: dict, extra: list) -> list:
    return [
        "ssh", "-p", str(cfg["port"]),
        "-i", cfg["key_path"],
        *SSH_OPTS,
        f"{cfg['user']}@{cfg['host']}",
        *extra,
    ]


def ssh(cfg: dict, remote_cmd: str, timeout: int = 120, capture: bool = True) -> int:
    """在服务器上执行 shell 命令，实时回显输出。"""
    argv = _base_ssh_args(cfg, [remote_cmd])
    result = subprocess.run(argv, timeout=timeout)
    return result.returncode


def ssh_out(cfg: dict, remote_cmd: str, timeout: int = 60) -> str:
    argv = _base_ssh_args(cfg, [remote_cmd])
    return subprocess.run(
        argv, capture_output=True, text=True, timeout=timeout, errors="replace"
    ).stdout


def cmd_status(cfg: dict) -> int:
    print(f"== {cfg['user']}@{cfg['host']} : {cfg['app_dir']} ==")
    return ssh(cfg, (
        f"cd {cfg['app_dir']} 2>/dev/null || exit 9; "
        "echo '--- 容器 ---'; sudo docker compose ps; "
        "echo '--- 磁盘 ---'; df -h / | tail -1; "
        "echo '--- 健康检查 ---'; curl -s -m 5 http://127.0.0.1/health || echo '(服务无响应)'; echo"
    ), timeout=60)


def cmd_health(cfg: dict) -> int:
    inner = ssh_out(cfg, "curl -s -m 5 http://127.0.0.1/health", timeout=30).strip()
    print(f"服务器本机 /health: {inner or '(无响应)'}")
    rc = 0 if '"healthy"' in inner else 1

    local = subprocess.run(
        ["curl", "-s", "-m", "8", f"http://{cfg['host']}/health"],
        capture_output=True, text=True, timeout=20,
    )
    outer = local.stdout.strip()
    print(f"外网访问 /health:   {outer or '(不可达 —— 检查腾讯云安全组是否放行 80/tcp)'}")
    return rc if '"healthy"' in outer else 1


def cmd_deploy(cfg: dict) -> int:
    """git archive HEAD 打包（只含跟踪文件，天然排除 .env/密钥/数据库），
    scp 上传后在服务器解压并重建容器。"""
    print("[1/4] 打包 HEAD（git archive，只含跟踪文件，天然排除 .env/密钥/数据库）...")
    tar_path = Path(tempfile.gettempdir()) / f"stock-agent-deploy-{int(time.time())}.tar"
    r = subprocess.run(
        ["git", "archive", "--format=tar", "-o", str(tar_path), "HEAD"],
        cwd=ROOT,
    )
    if r.returncode != 0:
        sys.exit("git archive 失败")
    size_mb = tar_path.stat().st_size / 1024 / 1024
    print(f"      {tar_path.name} ({size_mb:.1f} MB)")

    print("[2/4] 上传到服务器（家目录，时间戳唯一名）...")
    remote_tar = "stock-agent-deploy-{ts}.tar".format(ts=int(time.time()))
    r = subprocess.run(
        ["scp", "-P", str(cfg["port"]), "-i", cfg["key_path"], *SSH_OPTS,
         str(tar_path), f"{cfg['user']}@{cfg['host']}:{remote_tar}"],
    )
    if r.returncode != 0:
        sys.exit("scp 上传失败")
    tar_path.unlink()

    print("[3/4] 解压（.env 与卷内数据不在包内，不受影响）...")
    rc = ssh(cfg, (
        f"mkdir -p {cfg['app_dir']} && tar -xf ~/{remote_tar} -C {cfg['app_dir']} "
        f"&& rm ~/{remote_tar} && echo 解压完成"
    ), timeout=120)
    if rc != 0:
        sys.exit("解压失败")

    print("[4/4] 服务器后台构建（nohup 脱离会话，日志 app_dir/deploy.log）...")
    rc = ssh(cfg, (
        f"cd {cfg['app_dir']} && "
        "sudo bash -c 'nohup docker compose up -d --build >deploy.log 2>&1 &' && echo 已启动"
    ), timeout=60)
    if rc != 0:
        sys.exit("后台构建启动失败")

    # 轮询构建进度。pgrep 模式用 [c] 防止匹配到承载本命令的远端 shell 自身。
    deadline = time.time() + 1800
    while time.time() < deadline:
        time.sleep(20)
        state = ssh_out(
            cfg,
            "pgrep -f 'docker[-]compose.*up' >/dev/null && echo BUILDING || echo EXITED",
            timeout=30,
        ).strip()
        last = ssh_out(
            cfg,
            f"tail -n 1 {cfg['app_dir']}/deploy.log 2>/dev/null | tr -d '\\r' | cut -c1-110",
            timeout=30,
        ).strip()
        print(f"  [{time.strftime('%H:%M:%S')}] {state} | {last}")
        if state == "EXITED":
            break
    else:
        sys.exit("构建轮询超时（30 分钟）。用 exec 查看 deploy.log 排查。")

    print("构建结束，检查容器状态：")
    rc = ssh(cfg, f"cd {cfg['app_dir']} && sudo docker compose ps && tail -n 3 deploy.log", timeout=120)
    if rc != 0:
        return rc
    time.sleep(5)
    return cmd_health(cfg)


def cmd_logs(cfg: dict, lines: int) -> int:
    return ssh(cfg, f"cd {cfg['app_dir']} && sudo docker compose logs --tail {lines} app", timeout=60)


def cmd_backup(cfg: dict) -> int:
    name = f"app-data-{time.strftime('%Y-%m-%d-%H%M%S')}.tar.gz"
    return ssh(cfg, (
        f"mkdir -p ~/backups && sudo docker run --rm -v stock-agent_app-data:/data -v $HOME/backups:/backup alpine "
        f"tar czf /backup/{name} -C /data . && ls -lh ~/backups/{name}"
    ), timeout=300)


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, *rest = argv
    cfg = load_config()
    if cmd == "status":
        return cmd_status(cfg)
    if cmd == "deploy":
        return cmd_deploy(cfg)
    if cmd == "logs":
        return cmd_logs(cfg, int(rest[0]) if rest else 100)
    if cmd == "health":
        return cmd_health(cfg)
    if cmd == "backup":
        return cmd_backup(cfg)
    if cmd == "exec":
        if not rest:
            sys.exit('exec 需要一个命令参数，如: exec "sudo docker ps"')
        return ssh(cfg, rest[0], timeout=600)
    print(f"未知命令: {cmd}\n{__doc__}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
