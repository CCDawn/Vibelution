# Windows 安装指南（最终用户）

目标：用尽量少的步骤在本机打开 Vibelution 工作台。

## 你需要什么

### Phase 1（当前）

本机已安装：

| 依赖 | 版本建议 | 检查命令 |
|------|----------|----------|
| Windows | 10/11 | — |
| Python | 3.11+（推荐 3.12） | `py -3.12 --version` 或 `python --version` |
| Node.js | 18+（含 npm） | `node --version` / `npm --version` |
| Git | 任意近期版 | `git --version` |
| 浏览器 | Edge（推荐） | — |

> **Phase 2 规划**：官方便携包将尽量不再要求你预装 Python/Node。当前请用下方一键脚本。

### 不需要你会的

- 手写 `pip` / `npm` 多段命令（脚本代劳）
- 手动起 uvicorn / vite

## 一键安装（推荐）

在 **PowerShell** 中进入项目目录后执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install_windows.ps1
```

可选：

```powershell
# 装完后自动启动 Launcher
powershell -ExecutionPolicy Bypass -File scripts/install_windows.ps1 -Start

# 跳过前端构建（已有可用 web/dist 时）
powershell -ExecutionPolicy Bypass -File scripts/install_windows.ps1 -SkipFrontendBuild
```

脚本会：

1. 检查 Python / Node / Git
2. 创建项目 `.venv` 并安装 `requirements.txt`
3. 在 `web/` 执行 `npm install`（若缺 `node_modules`）
4. 构建 `web/dist`（若需要）
5. 同步桌面/开始菜单用的 **Vibelution Launcher** 入口（若本机工具链可用）
6. 打印配置路径与启动方式

## 启动

**推荐**：双击桌面上的 **Vibelution Launcher**（或开始菜单同名项）。

或：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/vibelution_launcher.ps1 -Action start
```

控制面默认：`http://127.0.0.1:8765`
工作台默认由 Launcher 打开（常见 `http://127.0.0.1:8002`，以界面/日志为准）。

## 配置模型密钥（首次对话前）

配置文件默认在：

`%USERPROFILE%\Documents\Vibelution\config\config.toml`

- 首次经 Launcher 启动时，一般会自动创建目录与 starter 文件
- 用文本编辑器填入你的模型 provider / API key（**不要**把含密钥的文件提交到 git）
- 也可用环境变量 `VIBELUTION_CONFIG_HOME` / `VIBELUTION_CONFIG_PATH` 指定位置

## 失败时看哪里

| 现象 | 优先查看 |
|------|----------|
| 脚本报缺 Python/Node | 安装对应运行时后重跑 `install_windows.ps1` |
| Launcher 起不来 | `.runtime/launcher/launcher-control.log` |
| 工作台打不开 / 重建失败 | `logs/runtime_scenes/` 最新目录；确认 git 在 **main**（开发机） |
| 黑窗闪烁 | 应使用官方 Launcher / pythonw 路径，勿手搓 `python.exe` 常驻服务 |

## 开发者

完整开发依赖、测试与源码结构见仓库根目录 [README.md](../../README.md) 与 [CONTRIBUTING.md](../../CONTRIBUTING.md)。
