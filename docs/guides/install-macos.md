# macOS 安装指南（最终用户）

其他平台：[Windows](install-windows.md) · [Linux](install-linux.md)

目标：用尽量少的步骤在本机跑起 Vibelution 工作台。macOS 走 headless 启动器 + 浏览器访问，不提供 Electron 桌面壳。

> 2026-09 在 macOS 26（Apple Silicon）+ Python 3.12.14 + Node 22.17.0 实测通过；依赖安装、前端构建、启动/停止生命周期与健康检查（`/api/health`）均验证。

## 你需要什么

| 依赖 | 版本建议 | 检查命令 |
|------|----------|----------|
| macOS | 13+（Apple Silicon / Intel） | — |
| Python | 3.11+（推荐 3.12） | `python3 --version` |
| Node.js | 18+（含 npm） | `node --version` / `npm --version` |
| Git | 任意近期版 | `git --version` |
| 浏览器 | Safari / Chrome / Edge | — |

注意：

- 系统自带的 `python3` 若是 3.9（`/usr/bin/python3`）**不满足要求**。用 [python.org 安装包](https://www.python.org/downloads/)、Homebrew（`brew install python@3.12`）或 [uv](https://docs.astral.sh/uv/)（`uv python install 3.12`）另装 3.12。
- 本机没有 Node 时，任选其一：Homebrew（`brew install node`）、[官网 pkg](https://nodejs.org/)，或解压官方 tarball 到用户目录（无需管理员权限）。

## 安装

### 一键安装（推荐）

在终端进入项目目录后执行：

```sh
bash scripts/install_posix.sh
```

脚本会检查依赖、创建 `.venv`、安装 Python 依赖、安装前端依赖并构建、激活项目 git hooks，并还原 npm 可能改写的 `package-lock.json`。可选参数：`--start`（装完自动启动）、`--skip-frontend-build`、`--skip-frontend-install`。幂等，可重复执行。

### 手动安装

```sh
# 1) Python 虚拟环境与依赖
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

# 2) 前端依赖与构建
cd web
npm install
npm run build
cd ..
```

> `npm install` 在 macOS 上可能改写 `web/package-lock.json`（npm 版本间的元数据格式差异）。启动器要求 git 工作树干净，若启动被拒，先还原：`git checkout -- web/package-lock.json`（一键脚本会自动处理）。

## 启动与停止

```sh
# 启动（首次会自动准备 ~/Documents/Vibelution 配置目录）
.venv/bin/python scripts/vibelution_launcher.py --action start --no-browser

# 停止 / 重启
.venv/bin/python scripts/vibelution_launcher.py --action stop
.venv/bin/python scripts/vibelution_launcher.py --action restart --no-browser
```

启动成功后浏览器打开 **http://127.0.0.1:8000**（端口被外部占用时会自动迁移，以命令输出为准）。

两个关键点（踩过的坑）：

- **必须用 `.venv/bin/python` 启动**。启动器会在准备虚拟环境之前导入需要 pydantic 的核心模块，用裸解释器直接跑会报 `ModuleNotFoundError: No module named 'pydantic'`。
- **启动时 git 工作树必须干净**。启动器以此保证运行代码与 HEAD 一致，不会在脏树上启动。

## 配置模型密钥（首次对话前）

配置文件默认在 `~/Documents/Vibelution/config/config.toml`：

- 首次经启动器启动时自动生成，含各服务商模型预设模板；
- 密钥不写入该文件，而是以 `credential_ref = "env:变量名"` 引用环境变量——把你使用的服务商对应的 `export` 写进 `~/.zshrc`（变量名清单见该文件中对应模型的 `credential_ref`），重开终端再启动；
- 也可用环境变量 `VIBELUTION_CONFIG_HOME` / `VIBELUTION_CONFIG_PATH` 指定位置。

## 与 Windows 体验的差异

| 能力 | macOS |
|------|-------|
| 工作台界面 | 浏览器访问，功能同 Windows |
| Electron Launcher 桌面壳 / 原生窗口 | 不提供（无 darwin 打包脚本） |
| 桌面伙伴等桌面集成 | 以浏览器工作台为准 |
| Windows 专属依赖（`pywinpty` 等） | 安装时按平台标记自动跳过 |

## 失败时看哪里

| 现象 | 处理 |
|------|------|
| `No module named 'pydantic'` | 用 `.venv/bin/python` 启动，勿用系统/裸解释器 |
| 启动器报工作树不干净 | `git status` 查看并还原（常见为 `web/package-lock.json` 被 npm 改写） |
| `npm: command not found` / 构建失败 | 先装 Node 18+，确认 `node --version` 可用 |
| 后端起来了页面打不开 | 确认命令输出中的实际端口；查 `.runtime/` 下最新日志 |
| 依赖安装失败 | 确认 Python 是 3.11+/3.12（`python3 --version`），非系统 3.9 |

## 开发者

完整开发依赖、测试与源码结构见仓库根目录 [README.md](../../README.md) 与 [CONTRIBUTING.md](../../CONTRIBUTING.md)；macOS/Linux 开发启动命令见 [CONTRIBUTING.md](../../CONTRIBUTING.md)。
