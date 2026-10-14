# -*- coding: utf-8 -*-
"""个人任务看板 - 本地服务端

仅使用 Python 标准库，无需安装第三方依赖。
职责：提供本地 HTTP 接口（任务 / 状态 / 日志的增删改查）与静态页面，
数据保存在本目录下的 data.json 中，任何修改都会立即写入文件。
"""

import datetime
import json
import os
import re
import socket
import sys
import threading
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(APP_DIR, "app")
DATA_DIR = os.environ.get("TASK_BOARD_DATA_DIR", APP_DIR)
DATA_FILE = os.path.join(DATA_DIR, "data.json")
EXPORT_DIR = os.path.join(DATA_DIR, "backup")
PORT_RANGE = [int(os.environ["TASK_BOARD_TEST_PORT"])] if "TASK_BOARD_TEST_PORT" in os.environ else list(range(8737, 8747))
# 运行中服务的端口会写入该文件，启动器直接读取，无需扫描端口段
PORT_FILE = os.path.join(DATA_DIR, "port.txt")

DEFAULT_STATUSES = ["待处理", "进行中", "等待中", "已完成"]

# 是否记录“查看”日志：默认关闭以避免重复记录快速堆积；置为 True 可重新启用。
# 说明：仅影响新产生的日志，历史查看日志仍可查询和清理。
LOG_VIEWS = False

_lock = threading.RLock()

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".ico": "image/x-icon",
    ".png": "image/png",
    ".svg": "image/svg+xml",
}


def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def gen_id(prefix):
    return prefix + uuid.uuid4().hex[:10]


def default_data():
    return {"version": 1, "statuses": list(DEFAULT_STATUSES), "tasks": [], "logs": []}


def save_data(data):
    tmp = DATA_FILE + ".tmp"
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)


def load_data():
    if not os.path.exists(DATA_FILE):
        data = default_data()
        save_data(data)
        return data
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        # 数据文件损坏时先留档再重建，避免应用无法启动
        broken = DATA_FILE + ".broken-" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        try:
            os.replace(DATA_FILE, broken)
        except OSError:
            pass
        data = default_data()
        save_data(data)
        return data
    if not isinstance(data, dict):
        data = default_data()
    data.setdefault("version", 1)
    if not isinstance(data.get("statuses"), list) or not data["statuses"]:
        data["statuses"] = list(DEFAULT_STATUSES)
    if not isinstance(data.get("tasks"), list):
        data["tasks"] = []
    if not isinstance(data.get("logs"), list):
        data["logs"] = []
    return data


def data_rev():
    """数据文件的修订标记（修改时间 + 文件大小）。

    用作前端轮询的“是否有变化”判据：任何写入都会经 save_data() 原子替换
    data.json，从而改变该标记；组合 mtime_ns 与 size 既能覆盖普通写入，
    也能覆盖手工替换 / 恢复 data.json 的情形。
    """
    try:
        st = os.stat(DATA_FILE)
    except OSError:
        return "0-0"
    return "%d-%d" % (st.st_mtime_ns, st.st_size)


def find_task(data, task_id):
    for t in data["tasks"]:
        if t.get("id") == task_id:
            return t
    return None


def unique_task_title(data, title, exclude_id=None):
    """在全部任务（包含归档）中选择未占用标题。修改时忽略自身。"""
    used = {t.get("title") for t in data["tasks"] if t.get("id") != exclude_id}
    if title not in used:
        return title
    number = 1
    while f"{title} ({number})" in used:
        number += 1
    return f"{title} ({number})"


def add_log(data, log_type, task, changes=None, snapshot=None):
    """追加一条操作日志。taskTitle 记录操作时的标题快照，taskId 保证改名后仍可关联。"""
    entry = {
        "id": gen_id("log-"),
        "at": now_iso(),
        "taskId": task.get("id"),
        "taskTitle": task.get("title", ""),
        "type": log_type,
    }
    if changes:
        entry["changes"] = changes
    if snapshot is not None:
        entry["snapshot"] = snapshot
    data["logs"].append(entry)
    return entry


def remove_logs_by_ids(data, ids):
    """删除 id 在给定集合中的日志，返回删除条数。

    ids 由前端按当前列表的筛选结果传入（类型 / 时间范围 / 关键词），
    仅做 id 精确匹配删除：任务与状态数据不受影响，重复 id 只删除一次。
    """
    if not ids:
        return 0
    wanted = set(ids)
    before = len(data["logs"])
    data["logs"] = [log for log in data["logs"] if log.get("id") not in wanted]
    return before - len(data["logs"])


class BoardServer(ThreadingHTTPServer):
    """独占端口的看板服务。

    为什么必须独占：
        Python 的 HTTPServer 默认 allow_reuse_address=True，在 Windows 上
        即 SO_REUSEADDR，它允许同一端口被多个进程同时绑定。一旦出现重复
        实例，连接会被内核分摊到不同进程，表现为「/api/health 正常、但
        页面空响应（ERR_EMPTY_RESPONSE）」，且重复实例互相看不见、
        谁都不退出。改为独占后，后启动的实例会绑定失败，从而顺延到下一个
        端口或被 already_running() 挡下，避免半死状态。
    """

    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        # Windows 下再显式声明独占，双保险（非 Windows 无此选项）
        try:
            self.socket.setsockopt(socket.SOL_SOCKET,
                                   socket.SO_EXCLUSIVEADDRUSE, 1)
        except (AttributeError, OSError):
            pass
        super().server_bind()


class BoardHandler(BaseHTTPRequestHandler):
    server_version = "TaskBoard/1.0"

    def log_message(self, *args):
        pass

    # ---------- 基础工具 ----------

    def _allow_mutation(self):
        # Custom header forces browser CORS preflight and blocks cross-site forms.
        host = self.headers.get("Host", "").lower()
        hostname = host.rsplit(":", 1)[0]
        if hostname not in ("127.0.0.1", "localhost") or self.headers.get("X-Board-Request") != "1":
            self._send_error_json(403, "请求来源不被允许")
            return False
        origin = self.headers.get("Origin")
        if origin and origin.rstrip("/").lower() != "http://" + host:
            self._send_error_json(403, "请求来源不被允许")
            return False
        return True


    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_error_json(self, status, message):
        self._send_json({"error": message}, status)

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError("请求数据格式错误")
        if not isinstance(body, dict):
            raise ValueError("请求数据格式错误")
        return body

    @staticmethod
    def _clean(value):
        return "" if value is None else str(value).strip()

    @staticmethod
    def _clean_multiline(value):
        return "" if value is None else str(value).replace("\r\n", "\n").strip()

    # ---------- 静态文件 ----------

    def _serve_static(self, path):
        if path in ("", "/"):
            path = "/index.html"
        rel = path.lstrip("/")
        full = os.path.normpath(os.path.join(STATIC_DIR, rel))
        if not full.startswith(STATIC_DIR + os.sep) or not os.path.isfile(full):
            self._send_error_json(404, "页面不存在")
            return
        ext = os.path.splitext(full)[1].lower()
        ctype = MIME_TYPES.get(ext, "application/octet-stream")
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ---------- 路由 ----------

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/health":
            return self._send_json({"ok": True, "app": "task-board", "time": now_iso()})
        if path == "/api/state":
            with _lock:
                data = load_data()
            return self._send_json({
                "statuses": data["statuses"],
                "tasks": data["tasks"],
                "serverTime": now_iso(),
            })
        if path == "/api/logs":
            with _lock:
                data = load_data()
            return self._send_json({"logs": list(reversed(data["logs"]))})
        if path == "/api/rev":
            # 轻量接口：只返回修订标记，供前端轮询判断是否需要重新拉取数据
            with _lock:
                rev = data_rev()
            return self._send_json({"rev": rev})
        return self._serve_static(path)

    def do_POST(self):
        if not self._allow_mutation():
            return
        path = self.path.split("?", 1)[0]
        try:
            body = self._read_body()
        except ValueError as exc:
            return self._send_error_json(400, str(exc))
        if path == "/api/tasks":
            return self._create_task(body)
        if path == "/api/export":
            return self._export_data(body)
        if path == "/api/export/open":
            return self._open_export_dir()
        m = re.fullmatch(r"/api/tasks/([A-Za-z0-9_-]+)/progress", path)
        if m:
            return self._add_progress(m.group(1), body)
        m = re.fullmatch(r"/api/tasks/([A-Za-z0-9_-]+)/view", path)
        if m:
            return self._view_task(m.group(1))
        m = re.fullmatch(r"/api/tasks/([A-Za-z0-9_-]+)/archive", path)
        if m:
            return self._set_archive(m.group(1), True)
        m = re.fullmatch(r"/api/tasks/([A-Za-z0-9_-]+)/restore", path)
        if m:
            return self._set_archive(m.group(1), False)
        if path == "/api/logs/cleanup":
            return self._cleanup_logs(body)
        if path == "/api/statuses":
            return self._add_status(body)
        if path == "/api/statuses/rename":
            return self._rename_status(body)
        if path == "/api/statuses/delete":
            return self._delete_status(body)
        return self._send_error_json(404, "接口不存在")

    def do_PATCH(self):
        if not self._allow_mutation():
            return
        path = self.path.split("?", 1)[0]
        m = re.fullmatch(r"/api/tasks/([A-Za-z0-9_-]+)", path)
        if m:
            try:
                body = self._read_body()
            except ValueError as exc:
                return self._send_error_json(400, str(exc))
            return self._update_task(m.group(1), body)
        return self._send_error_json(404, "接口不存在")

    def do_DELETE(self):
        if not self._allow_mutation():
            return
        path = self.path.split("?", 1)[0]
        m = re.fullmatch(r"/api/tasks/([A-Za-z0-9_-]+)", path)
        if m:
            return self._delete_task(m.group(1))
        return self._send_error_json(404, "接口不存在")

    # ---------- 任务 ----------

    def _create_task(self, body):
        title = self._clean(body.get("title"))
        if not title:
            return self._send_error_json(400, "标题不能为空")
        goal = self._clean_multiline(body.get("goal"))
        note = self._clean_multiline(body.get("note"))
        status = self._clean(body.get("status"))
        with _lock:
            data = load_data()
            if status not in data["statuses"]:
                status = data["statuses"][0]
            title = unique_task_title(data, title)
            ts = now_iso()
            task = {
                "id": gen_id("task-"),
                "title": title,
                "goal": goal,
                "note": note,
                "status": status,
                "createdAt": ts,
                "updatedAt": ts,
                "archived": False,
                "archivedAt": None,
            }
            data["tasks"].append(task)
            add_log(data, "create", task,
                    snapshot={"title": title, "goal": goal, "note": note, "status": status})
            save_data(data)
        return self._send_json({"task": task})

    def _add_progress(self, task_id, body):
        message = self._clean_multiline(body.get("text"))
        if not message:
            return self._send_error_json(400, "进展内容不能为空")
        with _lock:
            data = load_data()
            task = find_task(data, task_id)
            if task is None:
                return self._send_error_json(404, "任务不存在")
            entry = add_log(data, "progress", task, snapshot={"text": message})
            save_data(data)
        return self._send_json({"log": entry})

    def _view_task(self, task_id):
        with _lock:
            data = load_data()
            task = find_task(data, task_id)
            if not task:
                return self._send_error_json(404, "任务不存在")
            if LOG_VIEWS:
                add_log(data, "view", task)
                save_data(data)
        return self._send_json({"ok": True})

    def _update_task(self, task_id, body):
        with _lock:
            data = load_data()
            task = find_task(data, task_id)
            if not task:
                return self._send_error_json(404, "任务不存在")
            changes = []
            if "title" in body:
                title = self._clean(body.get("title"))
                if not title:
                    return self._send_error_json(400, "标题不能为空")
                if title != task.get("title"):
                    title = unique_task_title(data, title, exclude_id=task_id)
                    changes.append({"field": "title", "from": task.get("title", ""), "to": title})
                    task["title"] = title
            if "goal" in body:
                goal = self._clean_multiline(body.get("goal"))
                if goal != task.get("goal", ""):
                    changes.append({"field": "goal", "from": task.get("goal", ""), "to": goal})
                    task["goal"] = goal
            if "note" in body:
                note = self._clean_multiline(body.get("note"))
                if note != task.get("note", ""):
                    changes.append({"field": "note", "from": task.get("note", ""), "to": note})
                    task["note"] = note
            if "status" in body:
                status = self._clean(body.get("status"))
                if status not in data["statuses"]:
                    return self._send_error_json(400, "状态不存在")
                if status != task.get("status"):
                    changes.append({"field": "status", "from": task.get("status", ""), "to": status})
                    task["status"] = status
            if changes:
                task["updatedAt"] = now_iso()
                add_log(data, "update", task, changes=changes)
                save_data(data)
            return self._send_json({"task": task, "changed": bool(changes)})

    def _set_archive(self, task_id, archived):
        with _lock:
            data = load_data()
            task = find_task(data, task_id)
            if not task:
                return self._send_error_json(404, "任务不存在")
            if bool(task.get("archived")) == archived:
                return self._send_json({"task": task, "changed": False})
            task["archived"] = archived
            task["archivedAt"] = now_iso() if archived else None
            task["updatedAt"] = now_iso()
            add_log(data, "archive" if archived else "restore", task)
            save_data(data)
        return self._send_json({"task": task, "changed": True})

    def _delete_task(self, task_id):
        with _lock:
            data = load_data()
            task = find_task(data, task_id)
            if not task:
                return self._send_error_json(404, "任务不存在")
            add_log(data, "delete", task, snapshot={
                "title": task.get("title", ""),
                "goal": task.get("goal", ""),
                "note": task.get("note", ""),
                "status": task.get("status", ""),
                "createdAt": task.get("createdAt"),
                "archived": bool(task.get("archived")),
            })
            data["tasks"].remove(task)
            save_data(data)
        return self._send_json({"ok": True})

    # ---------- 状态 ----------

    def _add_status(self, body):
        name = self._clean(body.get("name"))
        if not name:
            return self._send_error_json(400, "状态名称不能为空")
        with _lock:
            data = load_data()
            if name in data["statuses"]:
                return self._send_error_json(409, "状态名称已存在")
            data["statuses"].append(name)
            save_data(data)
        return self._send_json({"statuses": data["statuses"]})

    def _rename_status(self, body):
        old = self._clean(body.get("from"))
        new = self._clean(body.get("to"))
        if not new:
            return self._send_error_json(400, "状态名称不能为空")
        with _lock:
            data = load_data()
            if old not in data["statuses"]:
                return self._send_error_json(404, "状态不存在")
            if new == old:
                return self._send_json({"statuses": data["statuses"], "renamed": 0})
            if new in data["statuses"]:
                return self._send_error_json(409, "状态名称已存在")
            idx = data["statuses"].index(old)
            data["statuses"][idx] = new
            renamed = 0
            ts = now_iso()
            for task in data["tasks"]:
                if task.get("status") == old:
                    task["status"] = new
                    task["updatedAt"] = ts
                    add_log(data, "update", task,
                            changes=[{"field": "status", "from": old, "to": new}])
                    renamed += 1
            save_data(data)
        return self._send_json({"statuses": data["statuses"], "renamed": renamed})

    def _delete_status(self, body):
        name = self._clean(body.get("name"))
        with _lock:
            data = load_data()
            if name not in data["statuses"]:
                return self._send_error_json(404, "状态不存在")
            used = [t for t in data["tasks"] if t.get("status") == name]
            if used:
                return self._send_error_json(
                    409, "该状态仍被 %d 个任务使用，请先修改这些任务的状态" % len(used))
            if len(data["statuses"]) <= 1:
                return self._send_error_json(409, "至少需要保留一个状态")
            data["statuses"].remove(name)
            save_data(data)
        return self._send_json({"statuses": data["statuses"]})

    # ---------- 日志 ----------

    def _cleanup_logs(self, body):
        """清理日志：按前端传入的 id 列表精确删除（即当前列表筛选出的日志）。

        只删除 id 命中的条目（前端按当前筛选结果传入）；无 id 列表视为参数错误，
        避免误删。不存在于列表中的 id 会被忽略。
        """
        raw_ids = body.get("ids")
        if not isinstance(raw_ids, list):
            return self._send_error_json(400, "参数错误：需要提供日志 id 列表")
        ids = [str(i) for i in raw_ids]
        with _lock:
            data = load_data()
            removed = remove_logs_by_ids(data, ids)
            if removed:
                save_data(data)
        return self._send_json({"removed": removed})

    # ---------- 导出 ----------

    def _export_data(self, request):
        """将全量数据保存到 backup 目录，返回保存信息（供界面展示路径与打开目录）。"""
        mode = request.get("mode", "all")
        if mode not in ("all", "filtered"):
            return self._send_error_json(400, "无效的导出范围")
        if mode == "filtered":
            task_ids, log_ids = request.get("taskIds"), request.get("logIds")
            if (not isinstance(task_ids, list) or not isinstance(log_ids, list)
                    or any(not isinstance(i, str) for i in task_ids + log_ids)):
                return self._send_error_json(400, "筛选导出需要任务及日志 ID 列表")
        with _lock:
            data = load_data()
            tasks, logs = data["tasks"], data["logs"]
            if mode == "filtered":
                task_ids, log_ids = set(task_ids), set(log_ids)
                tasks = [t for t in tasks if t.get("id") in task_ids]
                logs = [l for l in logs if l.get("id") in log_ids]
            payload = {
                "exportedAt": now_iso(),
                "version": data.get("version", 1),
                "statuses": data["statuses"],
                "tasks": tasks,
                "logs": logs,
            }
            os.makedirs(EXPORT_DIR, exist_ok=True)
            fname = "task-board-" + ("backup" if mode == "all" else "filtered") + "-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + ".json"
            fpath = os.path.join(EXPORT_DIR, fname)
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            base, ext = os.path.splitext(fpath)
            counter = 1
            while True:
                try:
                    f = open(fpath, "xb")
                    break
                except FileExistsError:
                    fpath = "%s-%d%s" % (base, counter, ext)
                    counter += 1
            with f:
                f.write(body)
        return self._send_json({
            "ok": True,
            "file": fpath,
            "dir": EXPORT_DIR,
            "name": fname,
            "size": len(body),
            "exportedAt": payload["exportedAt"],
        })

    def _open_export_dir(self):
        """在资源管理器中打开备份目录（固定目录，不接受客户端传入路径）。"""
        os.makedirs(EXPORT_DIR, exist_ok=True)
        if not hasattr(os, "startfile"):
            return self._send_error_json(500, "当前系统不支持自动打开目录")
        try:
            os.startfile(EXPORT_DIR)
        except OSError as exc:
            return self._send_error_json(500, "打开目录失败：%s" % exc)
        return self._send_json({"ok": True, "dir": EXPORT_DIR})


def is_board_ready(port, timeout=0.4):
    """判断该端口上的看板是否真的可用（接口 + 页面都能正常返回）。

    先用很短的超时做一次 TCP 探测，再发 HTTP 请求。原因：本机连接未监听的
    端口不会立即收到拒绝，而是要等满超时，若直接发 HTTP 请求，扫描 10 个
    端口会耗时数秒；TCP 预探测可把这一步压到 0.1 秒级。

    另外，只检查 /api/health 不够：端口可能被"半死"实例占用——它能应答接口，
    却发不出页面，浏览器会显示 ERR_EMPTY_RESPONSE。因此额外要求根路径 /
    也能返回非空内容。
    """
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.1):
            pass
    except OSError:
        return False
    try:
        with urllib.request.urlopen(
                "http://127.0.0.1:%d/api/health" % port, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            body = json.loads(resp.read().decode("utf-8"))
            if body.get("app") != "task-board":
                return False
    except Exception:
        return False
    try:
        with urllib.request.urlopen(
                "http://127.0.0.1:%d/" % port, timeout=timeout) as resp:
            return resp.status == 200 and len(resp.read()) > 0
    except Exception:
        return False


def read_port_file():
    """读取端口文件，返回端口号；文件不存在或内容非法时返回 None。"""
    try:
        with open(PORT_FILE, "r", encoding="utf-8") as f:
            text = f.read().strip()
        port = int(text)
        if port in PORT_RANGE:
            return port
    except (OSError, ValueError):
        pass
    return None


def write_port_file(port):
    """把当前端口写入文件（原子替换，避免读到写了一半的内容）。"""
    tmp = PORT_FILE + ".tmp"
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(str(port))
        os.replace(tmp, PORT_FILE)
    except OSError:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def already_running():
    """检测是否已有可用实例在运行（避免重复启动）。

    优先读端口文件：正常情况下服务启动时已把端口写入文件，这里只需验证
    这一个端口，无需扫描整个端口段（未监听的端口每次都要等满超时，很慢）。
    仅当端口文件缺失（首次运行或已被删除）时，才退回扫描作为兜底。
    """
    port = read_port_file()
    if port is not None:
        return port if is_board_ready(port) else None
    for p in PORT_RANGE:
        if is_board_ready(p):
            return p
    return None


def main():
    with _lock:
        load_data()  # 确保 data.json 存在
    port = already_running()
    if port:
        # 补写端口文件：即使文件曾被删除，也能让启动器直接读到端口
        write_port_file(port)
        print("任务看板已在运行：http://127.0.0.1:%d/ ，本次启动退出。" % port)
        return
    httpd = None
    bound_port = None
    for p in PORT_RANGE:
        try:
            httpd = BoardServer(("127.0.0.1", p), BoardHandler)
            bound_port = p
            break
        except OSError:
            httpd = None
    if httpd is None:
        print("无法绑定端口 %d-%d，任务看板启动失败。" % (PORT_RANGE[0], PORT_RANGE[-1]))
        sys.exit(1)
    print("个人任务看板服务已启动：http://127.0.0.1:%d/" % bound_port)
    write_port_file(bound_port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        # 服务退出后不再可用，清掉端口文件，避免启动器读到过期端口
        try:
            if os.path.exists(PORT_FILE):
                os.remove(PORT_FILE)
        except OSError:
            pass


if __name__ == "__main__":
    main()
