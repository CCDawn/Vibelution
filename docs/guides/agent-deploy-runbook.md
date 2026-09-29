# AI Agent 部署 Runbook（Vibelution 工作台）

**读者：任意 AI coding agent**（Claude Code / Codex / Cursor / ZCode 等），任务是帮你的用户在本机部署并启动 Vibelution。
人类可读安装指南：[Windows](install-windows.md) · [macOS](install-macos.md) · [Linux](install-linux.md)；服务器正式部署另见 [linux-bootstrap.md](../ops/linux-bootstrap.md)。
本文只给操作序列、机器可验证的验收标准和已知坑；命令以脚本实际参数为准。

## 0. 验收标准（全部满足才算完成）

1. 后端运行且 `GET http://127.0.0.1:8000/api/health`（或启动输出中的实际端口）返回 200；
2. 用户能在浏览器打开工作台（Windows 亦可由 Electron Launcher 窗口承载）；
3. 用户已知道模型密钥的配置方式（§5），且**密钥明文没有进入任何 git 跟踪文件**；
4. 部署过程**没有改动产品源码**（`git status` 干净；见 §1 的 package-lock 例外处理）。

## 1. 硬性约束（违反会失败或留下污染）

- **必须从 git 仓库运行**：launcher 校验源码身份与工作树状态，zip 快照缺 `.git` 无法启动。Linux 私有仓库源获取（deploy key / git bundle）见 [linux-bootstrap.md](../ops/linux-bootstrap.md)。
- **启动时 git 工作树必须干净**。`npm install` 可能改写 `web/package-lock.json`（npm 版本间元数据差异）——启动被拒时先 `git checkout -- web/package-lock.json`；一键安装脚本会自动还原。
- **macOS/Linux 必须用 `.venv/bin/python` 启动 launcher**。启动器在准备虚拟环境之前就导入 pydantic，裸 `python3` 会报 `ModuleNotFoundError: No module named 'pydantic'`。
- **Windows 禁止可见控制台常驻**：不要用 `python.exe` 直接拉起后台服务或 `taskkill` 粗暴杀进程，始终走 launcher 脚本 / 桌面 Launcher 入口。
- **不要请求、粘贴或代填 API key 明文**；密钥只走 §5 的 `credential_ref = "env:变量名"` 机制。
- **不要 git push**。部署是本地行为。

## 2. 平台检测与前置依赖

| 依赖 | 要求 | 检查 |
| --- | --- | --- |
| Python | 3.11+（推荐 3.12） | `python3 --version` / Windows `py -3.12 --version` |
| Node.js | 18+ | `node --version` |
| Git | 任意近期版 | `git --version` |

- macOS：系统 `/usr/bin/python3`（通常 3.9）**不满足**，需 `brew install python@3.12` 或 python.org / uv 安装。
- Debian/Ubuntu：发行版仓版本常过旧，必要时用 python.org / nodejs.org 官方包或 `uv` / `fnm`。
- 缺运行时时应向用户说明并给出上面的安装途径，不要静默降级。

## 3. 安装（幂等，可重复执行）

在仓库根目录：

```sh
# macOS / Linux
bash scripts/install_posix.sh            # 可选: --start 装完即启动

# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File scripts/install_windows.ps1   # 可选: -Start
```

脚本自动完成：检查依赖 → 创建/复用 `.venv` → 安装 Python 依赖 → `npm install`（缺 `node_modules` 时）→ 构建 `web/dist` → 还原 `package-lock.json`（POSIX）→ 同步桌面 Launcher 入口（Windows，best-effort）。POSIX 另有 `--skip-frontend-build` / `--skip-frontend-install`；Windows 对应 `-SkipFrontendBuild` / `-SkipFrontendInstall`。

## 4. 启动与验收

```sh
# macOS / Linux
.venv/bin/python scripts/vibelution_launcher.py --action start --no-browser
# 停止 / 重启
.venv/bin/python scripts/vibelution_launcher.py --action stop
.venv/bin/python scripts/vibelution_launcher.py --action restart --no-browser

# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File scripts/vibelution_launcher.ps1 -Action start
```

验收：

```sh
curl -fsS http://127.0.0.1:8000/api/health
```

- 端口被占用时 launcher 会自动迁移，**以启动输出的实际端口为准**再探测 health。
- Windows 用户日常入口是桌面/开始菜单的 **Vibelution Launcher**（Electron 控制窗），不是浏览器 URL。

## 5. 首次配置（引导用户完成，不代填密钥）

- 首次启动会自动生成配置（含各服务商模型模板）：Windows `%USERPROFILE%\Documents\Vibelution\config\config.toml`；macOS/Linux `~/Documents/Vibelution/config/config.toml`（可用 `VIBELUTION_CONFIG_HOME` / `VIBELUTION_CONFIG_PATH` 重定向）。
- 密钥不写进该文件，而是 `credential_ref = "env:变量名"` 引用环境变量：让用户把 `export <变量名>=<key>`（Windows 用 `setx`）加进自己的 shell 配置，重开终端后重启工作台。
- 可引导用户运行 `.venv/bin/python scripts/config_panel.py` 打开本地可视化配置面板（第一版）辅助填写。
- 配置完成后 `--action restart`，并用一次真实对话验证模型连通。

## 6. 故障速查（症状 → 处置）

| 症状 | 处置 |
| --- | --- |
| `No module named 'pydantic'` | 用 `.venv/bin/python` 启动，勿用系统/裸解释器 |
| 启动器报工作树不干净 | `git status` 还原；常见为 `web/package-lock.json` 被 npm 改写 |
| `npm: command not found` / 前端构建失败 | 先装 Node 18+（§2） |
| Python 版本过旧 / glibc 报错 | 装 3.12 / 换官方运行时包，勿用发行版旧仓 |
| 后端已起但页面打不开 | 用启动输出的实际端口；查 `.runtime/` 下最新日志 |
| Windows 黑窗闪烁 | 停止该路径，改走官方 Launcher / launcher 脚本（§1） |
| 端口冲突 | launcher 自动迁移端口；不要手动改配置抢占 |

## 7. 向用户汇报的完成模板

报告：启动方式（Launcher / URL+端口）、health 验收结果、密钥配置状态（已引导/待用户完成）、遗留问题。不要粘贴密钥、完整日志或大段 diff。
