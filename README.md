# Kanban · 个人开发任务看板

轻量的本地任务看板，用来管理开发任务、记录变更与跟踪工作进展，也可以通过 MCP 交给 Codex 等 Agent 操作。

- **任务管理**：创建、编辑、搜索、归档、恢复、删除任务；标题必填，支持目标、备注及自定义状态。
- **看板视图**：按状态分列展示任务，另有归档箱。
- **历史记录**：自动记录任务变更和归档操作；支持类型、时间、关键词筛选及确认后清理。Agent 还可追加独立的进展记录。
- **数据导出**：备份为 JSON 文件，保存在本地 `backup/` 目录。
- **Agent 集成**：内置 stdio MCP 适配层，支持任务查询、创建、编辑、状态更新与进展记录。

## 快速开始

面向 Windows 本地使用，要求安装 Python（看板本身只依赖 Python 标准库）。

```powershell
git clone https://github.com/l1105927155-creator/kanban.git
cd kanban
py server.py
```

打开 <http://127.0.0.1:8737/>。如果端口被占用，服务会依次尝试 8738–8746，实际端口记录在 `port.txt`。

Windows 也可以双击项目中的 `launch_board.vbs` 启动并打开应用窗口。启动器会尝试复用已运行的看板服务；关闭浏览器窗口不等于停止后台服务。

## 连接 Codex（MCP）

MCP 是可选功能，安装依赖不会影响普通看板的使用。Python 3.11+ 环境下执行：

```powershell
py -3.11 -m pip install "mcp>=1.28,<2"
```

在 Codex 的 `config.toml` 中添加（替换实际绝对路径）：

```toml
[mcp_servers.kanban]
command = "C:\\Path\\To\\Python311\\python.exe"
args = ["C:\\Path\\To\\kanban\\mcp\\server.py"]
```

重启 Codex 后，即可让 Agent 查找任务、阅读目标与历史记录、追加进展，并在满足验收条件后更新状态。例如：

> 查找看板中的“登录鉴权”任务，阅读目标、备注和操作日志，跟进实现并记录进展。只有完成验收后才设为“已完成”。

MCP 默认通过本机 HTTP API 访问看板；如果看板未启动，会尝试自动启动。它不会自主派工或在没有 Agent 会话时持续处理任务。

完整的工具清单、路径配置和使用边界见 [MCP 接入说明](mcp/README.md)。

## 数据与测试

任务、状态和日志保存在项目目录下的 `data.json`，不会提交到 Git；导出备份位于 `backup/`。建议定期备份重要任务数据。清理日志和删除任务属于不可逆操作，操作前请确认范围。

```powershell
py tools/test_logs.py
py tools/selftest.py
```

`selftest.py` 默认启动独立测试实例，使用临时数据目录，不会修改日常看板数据。手动为其传入服务地址则会直接操作该地址的数据，务必谨慎。

## 项目结构

```text
app/                 Web 前端
server.py            本地 HTTP 服务及数据存储
launch_board.vbs     Windows 启动器
mcp/server.py        MCP stdio 适配层
tools/               测试及辅助脚本
使用说明.md           更详细的界面使用说明
```

## 适用范围

这是面向个人本机使用的工具，HTTP 服务仅绑定 `127.0.0.1`，无账户体系，也不是可直接部署公网的多用户服务。多个 Agent 可以通过各自的 MCP 进程共享同一看板，但并发编辑同一任务时仍需自行协调。

更多日常操作及故障排查见 [使用说明](使用说明.md)。
