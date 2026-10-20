# Kanban MCP（Codex / DSH 接入）

MCP 通过 stdio 接入 Codex 与 DSH，调用看板现有的本地 HTTP API。它会查找运行中的本地看板，必要时自动启动 `server.py`，不直接写入 `data.json`。

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

## DSH 配置

DSH 内置 MCP 连接器 `@deepseek-ai/dsh-mcp-client`，无需额外安装即可接入 stdio MCP；安装 `dsh-mcp-connector` 面板插件后可在侧边栏「MCP连接器」中用图形界面管理连接。

### 方式一：面板插件（推荐）

```powershell
dsh plugin --profile desktop add dsh-mcp-connector
```

安装后**完全重启** DeepSeek Harness Desktop，侧边栏出现「MCP连接器」。在其中新建 stdio 连接，把下列路径替换为实际绝对路径：

- 名称：`kanban`
- 命令：`C:\Path\To\Python311\python.exe`
- 参数：`C:\Path\To\kanban\mcp\server.py`
- 工作目录：`C:\Path\To\kanban`
- 环境变量：`TEMP` 与 `TMP` 均设为 `C:\Path\To\Temp`

面板会把该连接转换为运行时的 `@deepseek-ai/dsh-mcp-client` 条目，工具名形如 `mcp__kanban__list_tasks`。

### 方式二：直接写 Cordis 补丁

在 profile 的 `cordis.patch.yml`（Windows 通常为 `%USERPROFILE%\.dsh\profiles\desktop\cordis.patch.yml`）中新增一行。新条目必须用 `insert:`，直接写 `- id:` 不会匹配到已有行，会被跳过：

```yaml
- insert:
    - id: mcp-kanban
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: kanban
        transport: stdio
        command: 'C:\Path\To\Python311\python.exe'
        args: ['C:\Path\To\kanban\mcp\server.py']
        cwd: 'C:\Path\To\kanban'
        env:
          TEMP: 'C:\Path\To\Temp'
          TMP: 'C:\Path\To\Temp'
```

`serverName` 决定工具名前缀（`mcp__<serverName>__<工具名>`），只允许 `[A-Za-z0-9_-]`，长度 1–32。

两种方式都要求启动 MCP 的解释器中已安装 `mcp`（见「安装」一节）。可以运行 `py -3.11 -c "import sys; print(sys.executable)"` 获得解释器路径。

## 工具

- `list_tasks(keyword, status, include_archived)`：查询和筛选任务。
- `get_task(task_id)`：获取任务完整信息和该任务的所有操作日志。
- `create_task(title, goal, note, status)`：创建任务。
- `update_task(task_id, title, goal, note, status)`：只更新指定字段，可变更状态。
- `add_progress(task_id, text)`：记录简短进展、问题结论或验收结果，不覆盖任务备注。

## 记录原则

看板用于了解任务**做了什么、当前状态、下一步是什么**，而非存放 Agent 的完整工作报告。

- **目标（goal）**：预期成果；**备注（note）**：长期有效的背景、约束、注意事项。不要不断将阶段进展追加到备注中。
- **进展（add_progress）**：优先一句话描述实际成果、关键发现或阻塞；必要时说明下一步。例：「已建立旧版行为基线，进入运行时重构」「已修复开机自启状态异常，待实机验收」。
- 默认省略本地路径、文件列表、提交编号、命令、测试条数、详细技术方案及排查过程。这些信息应留在代码仓库、测试报告或 Agent 会话；仅当它们是后续决策或交接的必要依据时才写入。
- 关键结论发生变化、发现需要用户处理的阻塞、验收未通过时，应明确记录；不为凑日志而记录每一个操作步骤。
- 仅约束 Agent 的记录方式，不裁剪用户主动填写的内容，也不改写历史数据。

工具不会主动监控任务或在后台执行编码工作；需要由 Codex 或 DSH 会话发起调用。

## 使用边界

- stdio MCP 可与后端分机运行；通过 TASK_BOARD_URL 或 remote-url.txt 指向局域网后端。
- 状态名来自看板配置，更新状态必须使用实际存在的状态值。
- `update_task` 能修改“已完成”，但是否满足验收标准必须由 Agent 根据原需求和证据判断。
- MCP 使用已有的 `X-Board-Request: 1` 本地写入接口保护，不向外网开放服务。


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
