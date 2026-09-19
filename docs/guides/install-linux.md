# Linux 安装指南（最终用户）

其他平台：[Windows](install-windows.md) · [macOS](install-macos.md)

目标：在本机 Linux 上跑起 Vibelution 工作台，适合本机使用与开发调试。流程与 macOS 相同（headless 启动器 + 浏览器访问）。

> 服务器/私有仓库的正式部署（源获取、Codex CLI 沙盒验收、Electron linux-arm64 打包）见 [Linux 部署参考](../ops/linux-bootstrap.md)，两者不重复；本文只覆盖单机安装起步。

## 你需要什么

| 依赖 | 版本建议 | 检查命令 |
|------|----------|----------|
| Python | 3.11+（推荐 3.12） | `python3 --version` |
| Node.js | 18+（含 npm） | `node --version` / `npm --version` |
| Git | 任意近期版 | `git --version` |
| 浏览器 | 任意现代浏览器 | — |

各发行版示例（Debian/Ubuntu）：

```sh
sudo apt update
sudo apt install -y python3.12 python3.12-venv nodejs npm git
```

发行版仓库版本过旧时，从 [python.org](https://www.python.org/downloads/) 与 [nodejs.org](https://nodejs.org/) 安装，或使用版本管理器（如 `uv`、`fnm`）。

## 安装

在终端进入项目目录后执行：

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

> `npm install` 可能改写 `web/package-lock.json`（npm 版本间的元数据格式差异）。启动器要求 git 工作树干净，若启动被拒，先还原：`git checkout -- web/package-lock.json`。

## 启动与停止

```sh
# 启动（首次会自动准备 ~/Documents/Vibelution 配置目录）
.venv/bin/python scripts/vibelution_launcher.py --action start --no-browser

# 停止 / 重启
.venv/bin/python scripts/vibelution_launcher.py --action stop
.venv/bin/python scripts/vibelution_launcher.py --action restart --no-browser
```

启动成功后浏览器打开 **http://127.0.0.1:8000**（端口被外部占用时会自动迁移，以命令输出为准）。

两个关键点：

- **必须用 `.venv/bin/python` 启动**。启动器会在准备虚拟环境之前导入需要 pydantic 的核心模块，用裸解释器直接跑会报 `ModuleNotFoundError: No module named 'pydantic'`。
- **启动时 git 工作树必须干净**。启动器以此保证运行代码与 HEAD 一致，不会在脏树上启动。

## 配置模型密钥（首次对话前）

配置文件默认在 `~/Documents/Vibelution/config/config.toml`：

- 首次经启动器启动时自动生成，含各服务商模型预设模板；
- 密钥不写入该文件，而是以 `credential_ref = "env:变量名"` 引用环境变量——把对应 `export` 写进 `~/.bashrc` / `~/.zshrc`（变量名清单见该文件中对应模型的 `credential_ref`），重开终端再启动；
- 也可用环境变量 `VIBELUTION_CONFIG_HOME` / `VIBELUTION_CONFIG_PATH` 指定位置；服务器部署请保持配置在源码树之外（见 [Linux 部署参考](../ops/linux-bootstrap.md)）。

## 平台差异说明

| 能力 | Linux |
|------|-------|
| 工作台界面 | 浏览器访问，功能同 Windows |
| Electron 桌面壳 | 可选，仅 linux-arm64 有打包脚本（见 [Linux 部署参考](../ops/linux-bootstrap.md)），普通安装无需 |
| Agent shell 工具（Codex CLI 沙盒） | 需另装 Codex CLI 才能启用；缺失时相关命令拒绝执行而非绕过沙盒（细节见部署参考） |
| Windows 专属依赖（`pywinpty` 等） | 安装时按平台标记自动跳过 |

## 失败时看哪里

| 现象 | 处理 |
|------|------|
| `No module named 'pydantic'` | 用 `.venv/bin/python` 启动，勿用系统/裸解释器 |
| 启动器报工作树不干净 | `git status` 查看并还原（常见为 `web/package-lock.json` 被 npm 改写） |
| `npm: command not found` / 构建失败 | 先装 Node 18+，确认 `node --version` 可用 |
| glibc / Python 版本过旧报错 | 用 python.org / nodejs.org 官方包或版本管理器，勿用发行版旧仓 |
| 后端起来了页面打不开 | 确认命令输出中的实际端口；查 `.runtime/` 下最新日志 |

## 开发者

完整开发依赖、测试与源码结构见仓库根目录 [README.md](../../README.md) 与 [CONTRIBUTING.md](../../CONTRIBUTING.md)；macOS/Linux 开发启动命令见 [CONTRIBUTING.md](../../CONTRIBUTING.md)。
