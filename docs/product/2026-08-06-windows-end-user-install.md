# Windows 最终用户快速安装（对齐结论）

**日期**：2026-08-06
**状态**：对齐确认 · Phase 1 落地中
**分支建议**：`feat/windows-end-user-install`

## 1. 目标

让**不熟悉 Python/Node 的 Windows 用户**能在约 **5 分钟内**完成安装并打开工作台对话。

### 已确认（按推荐）

| 项 | 选择 |
|----|------|
| 首期用户 | 最终用户（不懂 Python/Node 为默认心智） |
| 交付形态 | Windows 便携包 / 安装入口（Launcher） |
| 验收 | 双击 Launcher → 看到工作台且可开始对话配置 |
| 范围 | 仅 Windows + 本机 workbench |

### 非目标（首期）

- macOS / Linux 安装器
- 云托管 / SaaS
- 要求用户会 `git clone` + 手敲多段 pip/npm（仍保留为**开发者**路径）
- 把密钥打进安装包

## 2. 用户路径（目标体验）

```text
下载官方包
  → 解压或安装到本地目录
  → 双击「Vibelution Launcher」
  → 首次启动自动准备运行环境（若策略允许）
  → 浏览器/托管窗口打开工作台
  → 引导配置 Documents\Vibelution\config\config.toml 中的模型密钥
  → 可在 /chat 发第一条消息
```

成功标准（可测）：

1. 全新 Windows 10/11 机器（有 Edge，可联网）
2. 不手动创建 venv / 不手动 npm install
3. ≤ 5 分钟到工作台 UI
4. 失败时有**一条**用户可读原因 + 日志路径

## 3. 现状与缺口

| 已有 | 缺口 |
|------|------|
| `scripts/vibelution_launcher.*` 首启可装 venv / 前端依赖 / 构建 dist | 仍要求本机已装 **Python 3.11+** 与 **Node 18+** |
| `%LocalAppData%\Vibelution\Launcher\VibelutionLauncher.exe` | 无「下载即用」的离线运行时捆绑 |
| `scripts/build_desktop_package.ps1` + Electron | 打包仍依赖本机 Python 解析 profile；偏开发/运维产物 |
| README 快速开始 | 面向开发者命令流，非最终用户 |

## 4. 分期

### Phase 1 — 一键安装脚本 + 文档分流（本 PR）

- 用户指南：`docs/guides/install-windows.md`
- 一键脚本：`scripts/install_windows.ps1`
  - 检测 Python/Node/Git
  - 创建 `.venv`、装依赖、构建 `web/dist`
  - 同步/注册桌面 Launcher 入口
  - 打印「下一步：双击 Launcher / 配置密钥」
- README 拆成 **最终用户** / **开发者**
- 发布脚手架：`scripts/package_windows_release.ps1` 产出 `dist/release/windows/` 目录结构（含说明与脚本入口）

**验收**：有 Python+Node 的 Windows 用户执行一条 PowerShell 即可装好并启动 Launcher。

### Phase 2 — 可分发便携包（内嵌/附带运行时）

- 发布物内嵌 **便携 Python**（或官方 embeddable）+ **预构建 web/dist**
- 用户机器**不要求**预装 Node（构建在 CI/发布机完成）
- 可选：不要求预装系统 Python
- 冒烟：`verify` 脚本冷启动打开 workbench

### Phase 3 — 安装器体验

- Inno Setup / MSIX / 简易 setup.exe
- 开始菜单 + 桌面快捷方式
- 升级通道（版本文件 + 覆盖安装）

## 5. 架构约束（继承现有红线）

- 配置权威在用户目录外部 config（见 ADR 0003），不入库密钥
- Launcher 无控制台红线：后台服务 pythonw + CREATE_NO_WINDOW
- 控制面与 workbench 生命周期由 Launcher 管理，不鼓励用户手搓 uvicorn
- 重建/重启身份策略：产品默认 main 门禁；最终用户包应固定在发布快照（非开发工作区脏分支）

## 6. 成功证据

- [x] `docs/guides/install-windows.md` 可独立完成安装
- [x] `scripts/install_windows.ps1` 一键装依赖 + 可选 `-Start`（Phase 1 仍需本机 Python/Node）
- [x] `scripts/package_windows_release.ps1` 产出 `dist/release/windows/` 快照 + zip
- [x] README 最终用户路径 ≤ 3 步到 Launcher（install → 配置 → 双击 Launcher）
- [ ] 干净机器实装冒烟（可选，合并前建议）

## 7. 风险

| 风险 | 缓解 |
|------|------|
| 捆绑 Python 体积大 | Phase 2 再做；Phase 1 明确前置依赖 |
| Electron 与 native Launcher 双入口混淆 | 文档只推一个公共入口（Launcher） |
| 首启长时间装依赖 | 脚本进度输出 + 预构建 dist 减少首启 |
