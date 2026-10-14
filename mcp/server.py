"""Local Kanban MCP adapter (stdio). Requires: pip install 'mcp>=1.28,<2'."""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

ROOT = Path(__file__).resolve().parent.parent
mcp = FastMCP("kanban")
BASE = None
_child = None


def _check(port):
    url = f"http://127.0.0.1:{port}"
    try:
        with urllib.request.urlopen(url + "/api/health", timeout=0.25) as response:
            data = json.load(response)
            if response.status == 200 and data.get("app") == "task-board":
                return url
    except (OSError, ValueError, urllib.error.URLError):
        pass
    return None


def _find_board():
    port_file = ROOT / "port.txt"
    if port_file.exists():
        try:
            port = int(port_file.read_text(encoding="utf-8").strip())
            if 8737 <= port <= 8746:
                url = _check(port)
                if url:
                    return url
        except (ValueError, OSError):
            pass
    for port in range(8737, 8747):
        url = _check(port)
        if url:
            return url
    return None


def _base():
    global BASE, _child
    if BASE and _check(int(BASE.rsplit(":", 1)[1])):
        return BASE
    BASE = _find_board()
    if BASE:
        return BASE

    # Spawn the existing service; it remains available for the browser.
    if _child is None or _child.poll() is not None:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        _child = subprocess.Popen(
            [sys.executable, str(ROOT / "server.py")],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
    for _ in range(35):
        time.sleep(0.15)
        BASE = _find_board()
        if BASE:
            return BASE
        if _child.poll() is not None:
            break
    raise RuntimeError("看板服务不可用：请手动运行 python server.py 查看错误")


def _api(path, method="GET", payload=None):
    url = _base() + path
    headers = {}
    if method != "GET":
        headers["X-Board-Request"] = "1"
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            message = json.load(exc).get("error", str(exc))
        except (ValueError, UnicodeDecodeError):
            message = str(exc)
        raise ValueError(f"看板 API {exc.code}: {message}") from exc


def _task(task_id):
    for task in _api("/api/state")["tasks"]:
        if task["id"] == task_id:
            return task
    raise ValueError("任务不存在: " + task_id)


@mcp.tool()
def list_tasks(keyword: str = "", status: str = "", include_archived: bool = False) -> dict:
    """列出看板任务。支持标题关键词、状态筛选，默认不含归档任务。"""
    data = _api("/api/state")
    tasks = [t for t in data["tasks"] if
             (include_archived or not t.get("archived")) and
             (not status or t.get("status") == status) and
             (not keyword or keyword.casefold() in t.get("title", "").casefold())]
    return {"statuses": data["statuses"], "tasks": tasks}


@mcp.tool()
def get_task(task_id: str) -> dict:
    """获取任务完整内容及全部关联操作日志，评估需求与验收依据。"""
    task = _task(task_id)
    logs = [entry for entry in _api("/api/logs")["logs"] if entry.get("taskId") == task_id]
    return {"task": task, "logs": logs}


@mcp.tool()
def create_task(title: str, goal: str = "", note: str = "", status: str = "") -> dict:
    """创建任务。默认采用看板的首个状态。"""
    data = {"title": title, "goal": goal, "note": note}
    if status:
        data["status"] = status
    return _api("/api/tasks", "POST", data)


@mcp.tool()
def update_task(task_id: str, title: Optional[str] = None,
                goal: Optional[str] = None, note: Optional[str] = None,
                status: Optional[str] = None) -> dict:
    """更新任务字段及状态。只有实际传入的字段才修改，已完成需满足任务验收条件。"""
    body = {k: v for k, v in
            {"title": title, "goal": goal, "note": note, "status": status}.items()
            if v is not None}
    if not body:
        raise ValueError("至少提供一个待更新字段")
    return _api("/api/tasks/" + task_id, "PATCH", body)


@mcp.tool()
def add_progress(task_id: str, text: str) -> dict:
    """向任务追加独立的进展/阻塞/验证记录，不覆盖任务备注。"""
    if not text.strip():
        raise ValueError("进展内容不能为空")
    return _api("/api/tasks/" + task_id + "/progress", "POST", {"text": text})


if __name__ == "__main__":
    mcp.run(transport="stdio")
