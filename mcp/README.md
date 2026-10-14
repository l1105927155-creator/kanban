# Kanban MCP（Codex 接入）

MCP 通过 stdio 接入 Codex，调用看板现有的本地 HTTP API。它会查找运行中的本地看板，必要时自动启动 `server.py`，不直接写入 `data.json`。

## 安装

使用 Python 3.11+。在看板所在电脑的终端运行：

```powershell
py -3.11 -m pip install "mcp>=1.28,<2"
```

如果使用虚拟环境，依赖应安装在启动 MCP 所用的同一个 Python 解释器中。

## Codex 配置

编辑 `~/.codex/config.toml`（Windows 通常为 `%USERPROFILE%\.codex\config.toml`），添加：

```toml
[mcp_servers.kanban]
command = "C:\\Path\\To\\Python311\\python.exe"
args = ["C:\\Path\\To\\kanban\\mcp\\server.py"]
```

把两处路径替换为实际绝对路径。可以运行 `py -3.11 -c "import sys; print(sys.executable)"` 获得 Python 路径。然后重新打开 Codex，并执行 `codex mcp list` 检查注册情况。

例如告诉 Codex：**“请通过 kanban 工具查找任务‘登录鉴权’，阅读目标、备注及日志，开始跟进。未通过验收不要标记已完成。”**

## 工具

- `list_tasks(keyword, status, include_archived)`：查询和筛选任务。
- `get_task(task_id)`：获取任务完整信息和该任务的所有操作日志。
- `create_task(title, goal, note, status)`：创建任务。
- `update_task(task_id, title, goal, note, status)`：只更新指定字段，可变更状态。
- `add_progress(task_id, text)`：记录进展或验收结果，不覆盖任务备注。

工具不会主动监控任务或在后台执行编码工作；需要由 Codex 会话发起调用。

## 使用边界

- 仅支持与看板服务在**同一台主机**上的 stdio MCP；远程电脑需先通过 SSH 等方式在远端启动 MCP。
- 状态名来自看板配置，更新状态必须使用实际存在的状态值。
- `update_task` 能修改“已完成”，但是否满足验收标准必须由 Agent 根据原需求和证据判断。
- MCP 使用已有的 `X-Board-Request: 1` 本地写入接口保护，不向外网开放服务。
