# -*- coding: utf-8 -*-
"""个人开发任务看板 - 本地服务端

仅使用 Python 标准库，无需安装第三方依赖。
职责：提供本地 HTTP 接口（任务 / 状态 / 日志的增删改查）与静态页面，
数据保存在本目录下的 data.json 中，任何修改都会立即写入文件。
"""

import datetime
import json
import os
import re
import sys
import threading
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(APP_DIR, "app")
DATA_FILE = os.path.join(APP_DIR, "data.json")
PORT_RANGE = list(range(8737, 8747))

DEFAULT_STATUSES = ["待处理", "进行中", "等待中", "已完成"]

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


def find_task(data, task_id):
    for t in data["tasks"]:
        if t.get("id") == task_id:
            return t
    return None


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


class BoardHandler(BaseHTTPRequestHandler):
    server_version = "TaskBoard/1.0"

    def log_message(self, *args):
        pass

    # ---------- 基础工具 ----------

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
        if path == "/favicon.ico":
            path = "/app.ico"
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
        if path == "/api/export":
            with _lock:
                data = load_data()
            payload = {
                "exportedAt": now_iso(),
                "version": data.get("version", 1),
                "statuses": data["statuses"],
                "tasks": data["tasks"],
                "logs": data["logs"],
            }
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            fname = "task-board-backup-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + ".json"
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="%s"' % fname)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        return self._serve_static(path)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            body = self._read_body()
        except ValueError as exc:
            return self._send_error_json(400, str(exc))
        if path == "/api/tasks":
            return self._create_task(body)
        m = re.fullmatch(r"/api/tasks/([A-Za-z0-9_-]+)/view", path)
        if m:
            return self._view_task(m.group(1))
        m = re.fullmatch(r"/api/tasks/([A-Za-z0-9_-]+)/archive", path)
        if m:
            return self._set_archive(m.group(1), True)
        m = re.fullmatch(r"/api/tasks/([A-Za-z0-9_-]+)/restore", path)
        if m:
            return self._set_archive(m.group(1), False)
        if path == "/api/statuses":
            return self._add_status(body)
        if path == "/api/statuses/rename":
            return self._rename_status(body)
        if path == "/api/statuses/delete":
            return self._delete_status(body)
        return self._send_error_json(404, "接口不存在")

    def do_PATCH(self):
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

    def _view_task(self, task_id):
        with _lock:
            data = load_data()
            task = find_task(data, task_id)
            if not task:
                return self._send_error_json(404, "任务不存在")
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


def already_running():
    """检测是否已有实例在运行（避免重复启动）。"""
    for port in PORT_RANGE:
        try:
            with urllib.request.urlopen(
                    "http://127.0.0.1:%d/api/health" % port, timeout=0.5) as resp:
                if resp.status == 200:
                    body = json.loads(resp.read().decode("utf-8"))
                    if body.get("app") == "task-board":
                        return port
        except Exception:
            continue
    return None


def main():
    with _lock:
        load_data()  # 确保 data.json 存在
    port = already_running()
    if port:
        print("任务看板已在运行：http://127.0.0.1:%d/ ，本次启动退出。" % port)
        return
    httpd = None
    bound_port = None
    for p in PORT_RANGE:
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", p), BoardHandler)
            httpd.daemon_threads = True
            bound_port = p
            break
        except OSError:
            httpd = None
    if httpd is None:
        print("无法绑定端口 %d-%d，任务看板启动失败。" % (PORT_RANGE[0], PORT_RANGE[-1]))
        sys.exit(1)
    print("个人开发任务看板服务已启动：http://127.0.0.1:%d/" % bound_port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
