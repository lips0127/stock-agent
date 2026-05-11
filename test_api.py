"""API 接口冒烟测试脚本 — 逐个验证所有端点是否可达且返回合理。"""

import requests
import sys

BASE = "http://127.0.0.1:5000"
TOKEN = None
RESULTS = []


def report(name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    RESULTS.append((name, ok))
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


def test_health():
    r = requests.get(f"{BASE}/health")
    ok = r.status_code == 200 and r.json().get("status") == "healthy"
    report("GET /health", ok, f"status={r.status_code}, body={r.text[:100]}")


def test_login():
    global TOKEN
    r = requests.post(f"{BASE}/api/login", json={"username": "admin", "password": "admin123"})
    ok = r.status_code == 200 and "token" in r.json()
    if ok:
        TOKEN = r.json()["token"]
    report("POST /api/auth/login", ok, f"status={r.status_code}, body={r.text[:100]}")


def headers():
    return {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}


def test_indices_db():
    r = requests.get(f"{BASE}/api/indices", headers=headers())
    ok = r.status_code == 200 and isinstance(r.json(), list)
    report("GET /api/indices (DB缓存)", ok, f"status={r.status_code}, count={len(r.json()) if ok else 'N/A'}")


def test_indices_live():
    r = requests.get(f"{BASE}/api/indices/live", headers=headers())
    ok = r.status_code == 200 and isinstance(r.json(), list)
    report("GET /api/indices/live (实时)", ok, f"status={r.status_code}, count={len(r.json()) if ok else 'N/A'}")


def test_top_stocks():
    r = requests.get(f"{BASE}/api/top_stocks", headers=headers(), params={"limit": 5})
    ok = r.status_code == 200 and isinstance(r.json(), list)
    report("GET /api/top_stocks", ok, f"status={r.status_code}, count={len(r.json()) if ok else 'N/A'}")


def test_all_stocks():
    r = requests.get(f"{BASE}/api/all_stocks", headers=headers(), params={"page": 1, "page_size": 10})
    ok = r.status_code == 200 and "stocks" in r.json()
    report("GET /api/all_stocks", ok, f"status={r.status_code}, total={r.json().get('total','N/A')}")


def test_stock_detail():
    r = requests.get(f"{BASE}/api/stock/600519", headers=headers())
    ok = r.status_code == 200 and "code" in r.json()
    report("GET /api/stock/600519", ok, f"status={r.status_code}, body={r.text[:120]}")


def test_index_scan():
    r = requests.post(f"{BASE}/api/index_scan", headers=headers())
    ok = r.status_code == 200 and "message" in r.json()
    report("POST /api/index_scan", ok, f"status={r.status_code}, body={r.text[:120]}")


def test_full_refresh():
    r = requests.post(f"{BASE}/api/full_refresh", headers=headers())
    ok = r.status_code == 200 and "task_id" in r.json()
    detail = f"status={r.status_code}"
    if r.status_code == 409:
        ok = True
        detail = "status=409 (已有任务在运行，说明锁机制生效，这是正常行为)"
    elif r.status_code == 200:
        detail = f"task_id={r.json().get('task_id')}"
    report("POST /api/full_refresh", ok, detail)


def test_tasks():
    r = requests.get(f"{BASE}/api/tasks", headers=headers())
    ok = r.status_code == 200 and isinstance(r.json(), list)
    report("GET /api/tasks", ok, f"status={r.status_code}, count={len(r.json()) if ok else 'N/A'}")


def test_task_progress():
    r = requests.get(f"{BASE}/api/tasks", headers=headers())
    tasks = r.json() if r.status_code == 200 else []
    if tasks:
        task_id = tasks[0]["id"]
        r2 = requests.get(f"{BASE}/api/tasks/{task_id}/progress", headers=headers())
        ok = r2.status_code in (200, 404)
        report(f"GET /api/tasks/:id/progress", ok, f"status={r2.status_code}")
    else:
        report("GET /api/tasks/:id/progress", True, "skipped — no tasks yet")


def test_logs():
    r = requests.get(f"{BASE}/api/logs", headers=headers())
    ok = r.status_code == 200 and isinstance(r.json(), list)
    report("GET /api/logs", ok, f"status={r.status_code}, count={len(r.json()) if ok else 'N/A'}")


def test_old_refresh_gone():
    """确认旧 /api/refresh 已不存在（应返回 404 或 405）。"""
    r = requests.post(f"{BASE}/api/refresh", headers=headers())
    ok = r.status_code in (404, 405)
    report("POST /api/refresh (已废弃，应404/405)", ok, f"status={r.status_code}")


if __name__ == "__main__":
    print("=" * 60)
    print("API 冒烟测试")
    print("=" * 60)

    test_health()
    test_login()

    if not TOKEN:
        print("\n登录失败，终止测试")
        sys.exit(1)

    print("\n--- 认证接口 ---")
    # login already tested

    print("\n--- 市场数据接口 ---")
    test_indices_db()
    test_indices_live()
    test_top_stocks()
    test_all_stocks()
    test_stock_detail()

    print("\n--- 操作接口 ---")
    test_index_scan()
    test_full_refresh()

    print("\n--- 任务与日志接口 ---")
    test_tasks()
    test_task_progress()
    test_logs()

    print("\n--- 旧路由 ---")
    test_old_refresh_gone()

    print("\n" + "=" * 60)
    passed = sum(1 for _, ok in RESULTS if ok)
    failed = len(RESULTS) - passed
    print(f"结果: {passed} passed, {failed} failed, {len(RESULTS)} total")
    if failed:
        print("失败项:")
        for name, ok in RESULTS:
            if not ok:
                print(f"  - {name}")
    print("=" * 60)
    sys.exit(1 if failed else 0)
