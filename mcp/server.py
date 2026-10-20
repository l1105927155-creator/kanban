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
mcp = FastMCP(
    "kanban",
    instructions=(
        "这是用户的个人任务看板，用于管理跨会话的任务目标、备注、状态与进展。"
        "当用户明确提到看板任务，或说“跟进任务：XXX”“继续之前的 XXX 任务”"
        "“查看 XXX 任务的进度”等指向已有记录的请求时，"
        "先用 list_tasks 查找，再用 get_task 读取目标和历史，之后开展工作。"
        "标题可能不完全一致；无法唯一匹配时不要擅自选择。"
        "不要将一般性的工作请求一律视为看板任务，也不要仅因查询而创建任务。"
        "执行过程中按需使用 add_progress 记录简短成果；"
        "仅在通过验收后才将状态更新为完成。"
    ),
)
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
    endpoint_file = ROOT / "remote-url.txt"
    remote = os.environ.get("TASK_BOARD_URL", "").strip()
    if not remote and endpoint_file.exists():
        remote = endpoint_file.read_text(encoding="utf-8").strip()
    if remote:
        from urllib.parse import urlsplit
        parsed = urlsplit(remote)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.username:
            raise RuntimeError("TASK_BOARD_URL 必须为 HTTP(S) 服务根地址")
        # Remote failures must never create a separate local database.
        return remote.rstrip("/")
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
    """查找个人任务看板中的已有任务。用户说“跟进任务：XXX”“继续 XXX 任务”
    “查看 XXX 进度”或要求恢复某项已记录的工作时，先用此工具按标题关键词搜索，
    再调用 get_task 读取目标、备注与历史记录。支持状态筛选；默认不含归档任务。
    找不到时可调整关键词或按需搜索归档任务，不要假定任务存在。"""
    data = _api("/api/state")
    tasks = [t for t in data["tasks"] if
             (include_archived or not t.get("archived")) and
             (not status or t.get("status") == status) and
             (not keyword or keyword.casefold() in t.get("title", "").casefold())]
    return {
        "statuses": data["statuses"],
        "statusDescriptions": data.get("statusDescriptions", {}),
        "tasks": tasks,
    }


@mcp.tool()
def set_status_description(name: str, description: str) -> dict:
    """设置某个状态的简短说明（可留空清除）。说明会展示在看板列标题与任务详情中。"""
    return _api("/api/statuses/description", "POST",
                {"name": name, "description": description})


@mcp.tool()
def get_task(task_id: str) -> dict:
    """读取匹配任务的完整目标、备注及历史操作日志。跟进或恢复看板任务时，
    先读取这些内容，再制定行动和判断验收；task_id 来自 list_tasks 的结果。"""
    task = _task(task_id)
    logs = [entry for entry in _api("/api/logs")["logs"] if entry.get("taskId") == task_id]
    return {"task": task, "logs": logs}


@mcp.tool()
def create_task(title: str, goal: str = "", note: str = "", status: str = "") -> dict:
    """用户要求将新任务加入看板时创建记录；“跟进已有任务”不是创建指令。
    默认使用首个状态。goal 写预期成果，note 只写长期有效的背景、约束或注意事项；
    勿将执行流水账写入备注。"""
    data = {"title": title, "goal": goal, "note": note}
    if status:
        data["status"] = status
    return _api("/api/tasks", "POST", data)


@mcp.tool()
def update_task(task_id: str, title: Optional[str] = None,
                goal: Optional[str] = None, note: Optional[str] = None,
                status: Optional[str] = None) -> dict:
    """只更新传入字段。goal 保留任务目标，note 仅记录长期有效的信息，不要反复追加阶段报告、测试明细或操作流水；进展请用 add_progress。标记完成前确认验收条件。"""
    body = {k: v for k, v in
            {"title": title, "goal": goal, "note": note, "status": status}.items()
            if v is not None}
    if not body:
        raise ValueError("至少提供一个待更新字段")
    return _api("/api/tasks/" + task_id, "PATCH", body)


@mcp.tool()
def add_progress(task_id: str, text: str) -> dict:
    """追加简短进展摘要：写已完成的结果、重要发现或阻塞及必要的下一步，通常一句话即可。避免目录路径、文件清单、提交哈希、命令、测试数量及完整排查过程；只有对后续决策确有必要时才保留细节。若前述判断被推翻，应明确记录结论变更。不覆盖备注。"""
    if not text.strip():
        raise ValueError("进展内容不能为空")
    return _api("/api/tasks/" + task_id + "/progress", "POST", {"text": text})


if __name__ == "__main__":
    mcp.run(transport="stdio")
