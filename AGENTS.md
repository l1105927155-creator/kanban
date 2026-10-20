# Repository Guidelines

## Project Structure & Module Organization

- `server.py` — 本地 HTTP 服务端（Python 标准库 `ThreadingHTTPServer`），负责任务/状态/日志的增删改查 API、静态页面服务及 `data.json` 持久化。
- `app/` — Web 前端（`index.html`、`style.css`、`app.js`、图标与 manifest），无框架、无构建步骤。
- `mcp/` — MCP stdio 适配层（`mcp/server.py`），供 Codex 等 Agent 通过 MCP 操作看板，内部复用后端 HTTP API。
- `tools/` — 测试与辅助脚本（`selftest.py`、`test_logs.py`、`test_titles.py`、图标/快捷方式生成等）。
- `backup/` — JSON 数据导出备份；`data.json` 为运行时数据，均已加入 `.gitignore`，不要提交。
- `launch_board.vbs` — Windows 启动器；必须保持 ANSI/GBK（无 BOM）编码，不得改为 UTF-8 保存。

## Build, Test, and Development Commands

```powershell
py server.py                # 启动本地服务，默认 http://127.0.0.1:8737/（端口占用时依次尝试 8738–8746，实际端口写入 port.txt）
py tools/selftest.py        # 自检：启动独立测试实例并使用临时数据目录，不影响日常数据
py tools/test_logs.py       # 日志相关功能测试
py tools/test_titles.py     # 标题相关功能测试
py -3.11 -m pip install "mcp>=1.28,<2"   # 仅使用 MCP 功能时需要安装
```

无第三方构建依赖；后端仅用 Python 标准库。

## Coding Style & Naming Conventions

- Python：`server.py` 及脚本均以 `# -*- coding: utf-8 -*-` 开头，使用标准库风格，模块级常量用大写下划线（如 `DATA_FILE`、`PORT_RANGE`），共享状态通过 `_lock`（`threading.RLock`）保护。
- 前端：原生 HTML/CSS/JS，文件名全小写（`app.js`、`style.css`）；中文注释与中文 UI 文案是常态，保持一致。
- 数据：任务状态为中文标签（默认「待处理 / 进行中 / 等待中 / 已完成」），接口字段保持现有命名不变。
- 编码敏感：所有 Python/前端文件用 UTF-8；唯一例外是 `.vbs` 必须为 ANSI/GBK。

## Testing Guidelines

- 测试脚本位于 `tools/`，直接以 `py tools/xxx.py` 运行，无外部测试框架。
- `selftest.py` 默认使用临时数据目录的独立实例；若手动传入服务地址，会直接操作该地址的数据，务必谨慎。
- 修改 `server.py` 后至少运行 `py tools/selftest.py` 验证。

## Commit & Pull Request Guidelines

- 提交前确认 `data.json`、`backup/`、`port.txt`、`__pycache__/` 等运行时产物未被暂存。
- 提交信息使用简洁中文短句描述变更目的（与现有历史风格一致），一次提交聚焦一件事。
- 涉及界面改动请附带截图或操作路径说明；涉及 API/MCP 改动需同步更新 `README.md` 与 `mcp/README.md`。

## Security & Configuration Tips

- 服务默认绑定 `127.0.0.1`；用户授权的局域网部署必须显式指定网卡地址与客户端白名单。不要暴露到公网。
- 清理日志、删除任务为不可逆操作；改动数据处理逻辑时注意保持备份导出（`backup/`）可用。
