# 腾讯云部署指南（前后端一体单容器）

本产品以 **单容器** 形态部署：一个 Docker 容器内同时运行 Flask API 与前端静态产物，Flask 直接服务 `frontend/dist`，无需独立 Nginx 容器。

- 访问入口：`http://<服务器IP>`（或 `https://<域名>`，TLS 由云负载均衡 / Caddy 终止时开启 `ENABLE_HSTS=true`）
- 健康检查：`GET /health`
- 数据持久化：Docker 卷 `app-data`（SQLite + 缓存 + 日志）

## 1. 服务器准备（腾讯云）

1. 购买 **轻量应用服务器** 或 CVM（2C4G 起步即可），系统选 Ubuntu 22.04/24.04。
2. **防火墙 / 安全组**只放行必要端口：
   - `22/tcp`（SSH，建议限制为常用出口 IP）
   - `80/tcp`（HTTP 访问入口；如后续上 TLS 再放行 `443/tcp`）
3. SSH 密钥登录，禁用密码登录（腾讯云控制台可一键绑定密钥）。

## 2. 安装 Docker

```bash
# 腾讯云内网镜像加速（腾讯云服务器执行）
curl -fsSL https://mirrors.tencent.com/docker-ce/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker.gpg
echo "deb [signed-by=/usr/share/keyrings/docker.gpg] https://mirrors.tencent.com/docker-ce/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo systemctl enable --now docker
```

## 3. 获取代码与配置

```bash
sudo mkdir -p /opt/stock-agent && cd /opt/stock-agent
git clone <你的仓库地址> .   # 或 scp 上传代码目录

# 生成强随机 JWT 密钥（自己机器或服务器上执行均可）
python3 -c "import secrets; print(secrets.token_urlsafe(48))"

cp .env.production.example .env
vim .env   # 填入 JWT_SECRET / 管理员账号 / CORS_ORIGINS
```

`.env` 关键项：

| 变量 | 要求 |
| --- | --- |
| `JWT_SECRET` | ≥32 位强随机；泄露即等于任意伪造登录态 |
| `DEFAULT_ADMIN_USER` | 不得为 `admin` |
| `DEFAULT_ADMIN_PASSWORD` | ≥12 位，不得为示例值 |
| `CORS_ORIGINS` | 显式列出，如 `http://<服务器IP>`；禁止 `*` |
| `ENABLE_HSTS` | 前置 TLS 时 `true`，纯 HTTP 保持 `false` |

## 4. 部署与验证

```bash
# 构建并启动（前端在镜像内构建，干净环境可直接跑，无需宿主机 npm）
sudo docker compose up -d --build

# 验证
curl -s http://127.0.0.1/health          # {"status":"healthy","database":true}
sudo docker compose ps                   # healthy
sudo docker compose logs -f app          # 观察启动日志（Ctrl+C 退出）

# 部署前安全自检（容器内已自动执行；也可在宿主机手动审计 .env）
sudo docker compose exec app python -m backend.security_check
```

浏览器打开 `http://<服务器IP>` → 登录页使用 `.env` 中配置的管理员账号。

## 5. 日常运维

```bash
# 升级（代码更新后）
git pull && sudo docker compose up -d --build

# 查看任务/应用日志
sudo docker compose logs -f app
ls /var/lib/docker/volumes/stock-agent_app-data/_data/cache/logs/   # 应用日志文件

# 备份（SQLite + 缓存全量打包）
sudo docker run --rm -v stock-agent_app-data:/data -v $(pwd):/backup alpine \
    tar czf /backup/app-data-$(date +%F).tar.gz -C /data .

# 恢复
sudo docker run --rm -v stock-agent_app-data:/data -v $(pwd):/backup alpine \
    sh -c "cd /data && tar xzf /backup/app-data-<日期>.tar.gz"
```

## 6. 安全模块说明

| 层 | 机制 |
| --- | --- |
| 凭证强制 | compose `${VAR:?}` 缺变量拒绝启动；entrypoint + `backend/security_check.py` 双层校验强度/默认值/通配符 |
| 登录防爆破 | `/api/login` 每 IP 每分钟限流（`LOGIN_RATE_LIMIT_PER_MINUTE`，默认 10） |
| API 限流 | 业务接口每 IP 每分钟 `RATE_LIMIT_PER_MINUTE`（默认 30） |
| 安全响应头 | 全响应 `X-Content-Type-Options/X-Frame-Options/Referrer-Policy`；HTML 另加 CSP（禁外域脚本、禁 iframe 嵌套）；`ENABLE_HSTS=true` 时下发 HSTS |
| 错误隔离 | 接口不回显内部错误串；请求日志只记元数据，敏感 query 值打码 |
| 单实例调度 | entrypoint 强制 `GUNICORN_WORKERS=1`（调度器开启时），防重复调度 |

建议后续加固：接入 HTTPS（云负载均衡 + 证书，或服务器装 Caddy 自动签发，置 `ENABLE_HSTS=true`）、腾讯云防火墙只放行 443、定期执行第 5 节备份命令。

## 7. 故障排查

| 现象 | 处置 |
| --- | --- |
| 容器起不动，日志见 `Configuration error` | `.env` 缺变量或值不合规，按提示修正后 `docker compose up -d` |
| 页面能开但接口 401 | JWT 过期（默认 2h）重新登录；若反复掉线检查 `JWT_SECRET` 是否每次部署变化 |
| `502`/健康检查失败 | `docker compose logs app` 看启动异常；确认 `app-data` 卷权限 |
| 首次登录失败 | 确认用的是 `.env` 里的管理员凭证（非默认 admin/admin123）；连续失败触发登录限流，稍后再试 |
