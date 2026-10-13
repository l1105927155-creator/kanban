# -*- coding: utf-8 -*-
"""任务看板 API 自检脚本：对本地服务执行一轮完整流程并逐项校验。

用法：py selftest.py [服务地址，默认 http://127.0.0.1:8737]
"""

import json
import os
import sys
import time
import socket
import tempfile
import subprocess
import pathlib
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else None
_test_dir = None
_test_process = None

def start_test_server():
    global BASE, _test_dir, _test_process
    _test_dir = tempfile.TemporaryDirectory(prefix="kanban-test-")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = os.environ.copy()
    env["TASK_BOARD_DATA_DIR"] = _test_dir.name
    env["TASK_BOARD_TEST_PORT"] = str(port)
    root = pathlib.Path(__file__).resolve().parent.parent
    _test_process = subprocess.Popen(
        [sys.executable, str(root / "server.py")],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    BASE = "http://127.0.0.1:%d" % port
    for _ in range(80):
        if _test_process.poll() is not None:
            break
        try:
            with urllib.request.urlopen(BASE + "/api/health", timeout=0.2) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.1)
    raise RuntimeError("隔离测试服务启动失败")

def stop_test_server():
    if _test_process is not None:
        _test_process.terminate()
        try:
            _test_process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            _test_process.kill()
            _test_process.wait()
    if _test_dir is not None:
        _test_dir.cleanup()

STAMP = time.strftime("%H%M%S")

passed = 0
failed = 0


def req(method, path, body=None):
    url = BASE + path
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json", "X-Board-Request": "1"})
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print("PASS", name)
    else:
        failed += 1
        print("FAIL", name, ("| " + str(extra)) if extra else "")


def get_task(task_id):
    status, data = req("GET", "/api/state")
    for t in data.get("tasks", []):
        if t["id"] == task_id:
            return t
    return None


def main():
    title_a = "自检任务A-" + STAMP
    title_a2 = title_a + "-已改名"

    # 1. 健康检查
    status, data = req("GET", "/api/health")
    check("健康检查 /api/health", status == 200 and data.get("app") == "task-board", data)

    # 2. 初始状态包含预置状态
    status, data = req("GET", "/api/state")
    check("预置状态存在", "待处理" in data.get("statuses", []), data.get("statuses"))

    # 3. 新增任务
    status, data = req("POST", "/api/tasks", {
        "title": title_a, "goal": "验证新增流程", "note": "自检脚本创建", "status": "待处理"})
    check("新增任务", status == 200 and data.get("task", {}).get("id"), data)
    task_id = data.get("task", {}).get("id")

    # 4. 新增后能查到
    task = get_task(task_id) if task_id else None
    check("新增后可见", task is not None and task.get("title") == title_a, task)

    # 5. 打开详情默认不新增“查看”日志
    status, logs_snapshot = req("GET", "/api/logs")
    logs_before = len(logs_snapshot.get("logs", []))
    status, _ = req("POST", "/api/tasks/%s/view" % task_id)
    check("查看操作返回 200", status == 200, status)
    status, data = req("GET", "/api/logs")
    new_view_logs = [l for l in data.get("logs", [])
                     if l.get("taskId") == task_id and l.get("type") == "view"]
    check("打开详情默认不记查看日志",
          len(data.get("logs", [])) == logs_before and not new_view_logs,
          (logs_before, len(data.get("logs", [])), new_view_logs))

    # 6. 修改标题与备注
    status, data = req("PATCH", "/api/tasks/%s" % task_id,
                       {"title": title_a2, "note": "备注已修改", "status": "进行中"})
    check("修改任务", status == 200 and data.get("changed") is True, data)
    task = get_task(task_id)
    check("修改已生效", task and task.get("title") == title_a2 and task.get("status") == "进行中", task)

    # 7. 修改日志包含修改前后值
    status, data = req("GET", "/api/logs")
    update_logs = [l for l in data.get("logs", [])
                   if l.get("taskId") == task_id and l.get("type") == "update"]
    has_before_after = any(
        any(c.get("field") == "title" and c.get("from") == title_a and c.get("to") == title_a2
            for c in l.get("changes", []))
        for l in update_logs)
    check("修改日志含前后值", has_before_after, update_logs)

    # 8. 日志按时间倒序
    times = [l.get("at") for l in data.get("logs", [])]
    check("日志按时间倒序", times == sorted(times, reverse=True))

    # 8b. 清理接口参数校验（ids 必须为列表，避免误删）
    total_before = len(data.get("logs", []))
    status, res = req("POST", "/api/logs/cleanup", {"since": "2099-01-01T00:00:00+08:00"})
    check("清理接口缺少 ids 被拒绝(400)", status == 400, (status, res))
    status, res = req("POST", "/api/logs/cleanup", {"ids": "not-a-list"})
    check("清理接口 ids 非列表被拒绝(400)", status == 400, (status, res))

    # 8c. 安全性：不存在的 id 不会误删任何日志
    status, res = req("POST", "/api/logs/cleanup", {"ids": ["log-nonexistent-" + STAMP]})
    check("清理不存在的 id：removed=0", status == 200 and res.get("removed") == 0, (status, res))
    status, data = req("GET", "/api/logs")
    check("清理不存在的 id：日志总数不变", len(data.get("logs", [])) == total_before,
          (total_before, len(data.get("logs", []))))

    # 9. 归档 / 恢复
    status, _ = req("POST", "/api/tasks/%s/archive" % task_id)
    task = get_task(task_id)
    check("归档任务", status == 200 and task and task.get("archived") is True, task)
    status, _ = req("POST", "/api/tasks/%s/restore" % task_id)
    task = get_task(task_id)
    check("恢复任务", status == 200 and task and task.get("archived") is False, task)

    # 10. 状态：新增 / 重命名 / 删除（未被使用）
    tmp_status = "自检状态" + STAMP
    tmp_status2 = tmp_status + "-改名"
    status, data = req("POST", "/api/statuses", {"name": tmp_status})
    check("新增状态", status == 200 and tmp_status in data.get("statuses", []), data)
    status, data = req("POST", "/api/statuses/rename", {"from": tmp_status, "to": tmp_status2})
    check("重命名状态", status == 200 and tmp_status2 in data.get("statuses", []), data)
    status, data = req("POST", "/api/statuses/delete", {"name": tmp_status2})
    check("删除未使用状态", status == 200 and tmp_status2 not in data.get("statuses", []), data)

    # 11. 删除使用中的状态应被拒绝
    status, data = req("POST", "/api/tasks", {"title": "自检任务B-" + STAMP, "status": "等待中"})
    task_b = data.get("task", {}).get("id")
    status, data = req("POST", "/api/statuses/delete", {"name": "等待中"})
    check("删除使用中状态被拒绝(409)", status == 409 and "使用" in data.get("error", ""), (status, data))

    # 12. 状态重命名会自动同步任务
    status, data = req("POST", "/api/statuses/rename", {"from": "等待中", "to": "等待中"})
    check("重命名同名状态无副作用", status == 200 and data.get("renamed") == 0, data)

    # 13. 标题为空应报错
    status, data = req("POST", "/api/tasks", {"title": "  "})
    check("空标题被拒绝(400)", status == 400, (status, data))

    # 14. 删除任务
    status, _ = req("DELETE", "/api/tasks/%s" % task_b)
    check("删除任务", status == 200 and get_task(task_b) is None)

    # 15. 删除日志仍保留且能关联
    status, data = req("GET", "/api/logs")
    delete_logs = [l for l in data.get("logs", []) if l.get("taskId") == task_b]
    check("删除后日志保留", any(l.get("type") == "delete" for l in delete_logs), delete_logs)

    # 16. 导出备份（保存到本地 backup 目录并返回保存信息）
    status, data = req("POST", "/api/export")
    saved_ok = False
    if status == 200 and data.get("file") and os.path.exists(data["file"]):
        try:
            with open(data["file"], encoding="utf-8") as fh:
                saved = json.load(fh)
            saved_ok = isinstance(saved.get("tasks"), list) and isinstance(saved.get("logs"), list)
        except (OSError, json.JSONDecodeError):
            saved_ok = False
    check("导出数据", status == 200 and data.get("ok") is True and saved_ok, data)

    # 17. 收尾：删除自检任务 A（此删除也会产生一条 delete 日志）
    req("DELETE", "/api/tasks/%s" % task_id)

    # 18. 清理接口正向用例：按 id 删除本次自检产生的全部日志（同时保持现场干净）
    status, data = req("GET", "/api/logs")
    junk_ids = [l["id"] for l in data.get("logs", []) if l.get("taskId") in (task_id, task_b)]
    base_count = len(data.get("logs", []))
    check("收集到自检日志（任务A 5 条 + 任务B 2 条）", len(junk_ids) == 7, junk_ids)
    status, res = req("POST", "/api/logs/cleanup", {"ids": junk_ids})
    check("清理接口：按 id 删除自检日志",
          status == 200 and res.get("removed") == len(junk_ids), (status, res, len(junk_ids)))
    status, data = req("GET", "/api/logs")
    left = data.get("logs", [])
    check("清理接口：仅自检日志被删，其余原样保留",
          len(left) == base_count - len(junk_ids)
          and not any(l.get("taskId") in (task_id, task_b) for l in left),
          (base_count, len(left)))

    print()
    print("自检完成：通过 %d 项，失败 %d 项" % (passed, failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    try:
        if BASE is None:
            start_test_server()
        main()
    finally:
        stop_test_server()
