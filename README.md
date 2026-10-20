# Kanban · 个人任务看板

轻量的本地任务看板，用来管理任务、记录变更与跟踪任务进展，也可以通过 MCP 交给 Codex 等 Agent 操作。

- **任务管理**：创建、编辑、搜索、归档、恢复、删除任务；标题必填，支持目标、备注及自定义状态。
- **看板视图**：按状态分列展示任务，另有归档箱。
- **历史记录**：自动记录任务变更和归档操作；支持类型、时间、关键词筛选及确认后清理。Agent 还可追加独立的进展记录。
- **自动更新**：页面定时检测数据变化并自动刷新，Agent 或其它窗口的改动无需手动刷新。
- **数据导出**：备份为 JSON 文件，保存在本地 `backup/` 目录。
- **Agent 集成**：内置 stdio MCP 适配层，支持任务查询、创建、编辑、状态更新与进展记录。

## 技术栈与架构

| 组件 | 技术 | 职责 |
| --- | --- | --- |
| Web 前端 | HTML、CSS、原生 JavaScript | 页面展示、交互与 HTTP API 调用；无需前端框架或构建步骤 |
| 后端 | Python 标准库 `ThreadingHTTPServer` | 本机 HTTP API、任务及日志业务逻辑 |
| 数据层 | 本地 `data.json` | 任务、状态和操作历史的持久化 |
| MCP 适配层 | Python、MCP SDK、stdio | 向 Codex 等 Agent 提供任务工具，并复用后端 HTTP API |
| Windows 启动器 | VBScript | 启动/复用后端，再以已安装的网页应用窗口打开页面（任务栏为高清图标）；未安装时回退为 Chrome/Edge 的 `--app` 应用窗口 |

```text
浏览器（普通网页 / --app 独立窗口）      Codex 等 Agent
             │                              │
             │ HTTP                         │ stdio
             │                              ▼
             │                         MCP Server
             │                              │ HTTP
             └──────────────┬───────────────┘
                            ▼
                  Python HTTP Server
                            │
                            ▼
                        data.json
```

## 快速开始

面向 Windows 本地使用，要求安装 Python（看板本身只依赖 Python 标准库）。

```powershell
git clone https://github.com/l1105927155-creator/kanban.git
cd kanban
py server.py
```

打开 <http://127.0.0.1:8737/>。如果端口被占用，服务会依次尝试 8738–8746，实际端口记录在 `port.txt`。

Windows 也可以双击项目中的 `launch_board.vbs` 启动并打开应用窗口。启动器会尝试复用已运行的看板服务；关闭浏览器窗口不等于停止后台服务。

启动器会先启动/复用服务，再打开看板窗口：若已在 Chrome 中把本页「安装为网页应用」，则直接以该网页应用窗口打开（任务栏图标取自 manifest 的 192/256 大图，清晰不糊）；否则回退为 `--app` 应用窗口（其任务栏图标取自 favicon，Chromium 上限 32px，高 DPI 下会发糊）。网页应用的来源固定为 `http://127.0.0.1:8737`，因此服务端口顺延时只能走回退路径。

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

## 已知问题

### 启动器报「无效字符 800A0408」

`launch_board.vbs` 必须保持 **ANSI/GBK（无 BOM）** 编码。Windows Script Host 按系统代码页解析无 BOM 的 `.vbs`（简体中文系统为 936），一旦该文件被改为 UTF-8 保存，其中的中文注释与提示信息会被解析成非法字符，双击启动器即弹出编译错误、无法打开看板：

    脚本: ...\launch_board.vbs
    错误: 无效字符
    代码: 800A0408

修复：将该文件转回 GBK 编码（保持原有文本内容与换行），不要以 UTF-8 覆盖保存。

## 适用范围

这是面向个人本机使用的工具，HTTP 服务默认绑定 `127.0.0.1`，支持显式配置局域网地址与客户端白名单，无账户体系，也不是可直接部署公网的多用户服务。多个 Agent 可以通过各自的 MCP 进程共享同一看板，但并发编辑同一任务时仍需自行协调。

更多日常操作及故障排查见 [使用说明](使用说明.md)。


## 局域网后端（Linux / Windows）

后端仍只依赖 Python 标准库，前端由同一服务提供。默认保持本机模式。
例如在 Linux 197 上运行（应使用固定局域网地址）：

```sh
TASK_BOARD_HOST=192.168.0.197 TASK_BOARD_PORT=8737 TASK_BOARD_ALLOWED_CLIENTS=192.168.0.21/32,192.168.0.197/32 python3 server.py
```

TASK_BOARD_DATA_DIR 可指定数据目录。显式指定端口时，占用会报错，不顺延。
只绑定指定网卡；所有页面和 API 均检查客户端白名单及 Host，写入还校验同源 Origin 与 X-Board-Request。
这是受信局域网部署，不提供账户、TLS 或公网发布能力。

客户端打开 http://192.168.0.197:8737/。本机 MCP 设置环境变量 TASK_BOARD_URL=http://192.168.0.197:8737，
或在项目根目录放置 remote-url.txt（仅一行该 URL，末尾不加斜线）。Windows 启动器也读取该文件，直接打开远端页面。
远端不可用时明确报错，不自动启动本机后端，避免产生两份数据。
MCP 本身保持 stdio，无须额外开放 MCP 网络端口；工具通过局域网 HTTP API 操作同一个后端。
已有 MCP 进程需重启后载入新代码；仅修改 URL 文件时每次调用都会重新读取。

迁移前备份原 data.json，停止旧后端写入，将完整数据文件复制到远端数据目录，再切换客户端。
回退时先停远端并把最新 data.json 复制回本机，再移除 remote-url.txt，避免丢失迁移后写入。

本机保留的 127.0.0.1 服务在配置 remote-url.txt 后仅转发请求，不再写入本机 data.json；旧书签和已启动的 MCP 也访问远端同一份数据。197 的用户级 task-board.service 已设置开机运行（Linger=yes），可通过 systemctl --user status/restart task-board.service 管理。
