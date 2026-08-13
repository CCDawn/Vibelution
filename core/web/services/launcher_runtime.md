# Launcher / Runtime 迷你索引（R13）

**读者：coding Agent。**
**目标：30 秒内定位生命周期、无控制台红线与主测；不要在 Web facade 里堆进程逻辑。**

权威细则：`docs/standards/development-standard.md` §8.0 · 根 `AGENTS.md` §2。
Runtime scene pack：[`runtime_scene/README.md`](runtime_scene/README.md)。

---

## 30 秒编辑表

| 你在改… | 先打开 | 禁止 |
| --- | --- | --- |
| start / stop / restart / active-work 拦截 | `core/launcher/service.py` | 在 `runtime_service.py` 再写一套 lifecycle |
| Web 路由 import 稳定面 | `launcher_service.py`（re-export only） | 往 facade 加业务体 |
| Force-stop / close transaction / desktop session | `core/launcher/`（`lifecycle_*` · `desktop_session_store` · `window_provider_dispatcher`） | 裸 `taskkill.exe`、直接杀 PID 当常态 |
| Reset / maintenance | `core/launcher/maintenance_reset.py`（`reset_service.py` 仅 alias） | 平行 reset 实现 |
| Runtime Manager daemon / work-run / 预检 | `core/runtime_manager/` | 用 PowerShell lifecycle 制造可见控制台 |
| 轻量 RM 存活检查 | `runtime_manager_control_service.py` | 在此扩展完整 lifecycle |
| Workbench runtime summary 投影 | `runtime_service.py` | 当成第二写入者改 store |
| Scene 证据包读写 / 诊断 | `runtime_scene/*` · facade `runtime_scene_service.py` | 手写无界 log dump 进 Prompt |
| 托盘 / 脚本入口 | `scripts/vibelution_launcher.py` · `scripts/vibelution_desktop_entry.py` | 后台路径弹 `cmd`/`powershell`/WT |
| 产品托盘 owner | Electron `desktopTray.ts` + `desktopShellOwner.ts` | 与 WinForms 同时显示 NotifyIcon |

---

## 生命周期（谁拥有什么）

```text
Electron (product tray owner, globally unique desktop shell)
  → pin userData to %LOCALAPPDATA%\\Vibelution\\DesktopShell before requestSingleInstanceLock
  → second launch without --project/--open-workbench/deep-link focuses the existing Launcher window
  → claim .runtime/launcher/desktop_shell_owner.json
  → Python launcher service (vibelution_desktop_entry.py bootstrap)
  → Runtime Manager → FastAPI + Workbench
  → isolated worktree backends stay allowed; they do not spawn a second desktop shell

VibelutionLauncher.exe --project <root> launcher
  → if Electron owner pid is alive: no NotifyIcon (thin shim / open console)
  → else native WinForms tray
  → core/launcher (control plane)
```

Web: core/web/routes/launcher.py · runtime.py · logs.py
  → launcher_service / runtime_service / runtime_scene_service（薄委托）
```

- Operator config 真源：`%USERPROFILE%\Documents\Vibelution\config\config.toml`（ADR0003）。
- active-work 挡 refresh：报告固定句（`AGENTS.md` §4），禁止强杀绕过。
- Launcher refresh 命令见 `docs/guides/loop.md` §3。

---

## 无控制台检查点（FAIL CLOSED）

改 spawn / stop / Git / 轮询 / 子进程时，合入前自检：

1. 后台父进程优先 `pythonw`；子树仍要 `CREATE_NO_WINDOW` / 项目 shared no-console helper。
2. 禁止产品路径弹出 `cmd.exe`、`powershell.exe`、Windows Terminal、OpenConsole、交互式 Git 编辑器。
3. **禁止** `taskkill.exe` 作为常态清理；用 in-process `psutil`/WinAPI（§8.0）。
4. 禁止用裸 `git` cmd wrapper、`npm`/`cmd` 脚本壳当后台路径。
5. 用户明确打开的 CLI 终端面板除外。

证据：相关 launcher/runtime 测试 + 说明 helper/`pythonw`/`CREATE_NO_WINDOW`/`windowsHide` 落点。

---

## 主测（可复制）

```powershell
# Launcher 控制面 / close transaction / desktop session
.\.venv\Scripts\python.exe -m pytest tests\test_launcher_service.py tests\test_launcher_developer_mode.py -q

# Reset alias + routing
.\.venv\Scripts\python.exe -m pytest tests\test_reset_service.py -q

# Runtime summary / RM control
.\.venv\Scripts\python.exe -m pytest tests\test_runtime_service.py tests\test_runtime_manager_control_service.py -q

# Runtime scene pack 结构
.\.venv\Scripts\python.exe -m pytest tests\test_runtime_scene_structure_packs.py tests\test_runtime_scene_package_index.py -q

# 巨石回归（改 daemon / 预检时再开；勿默认全跑）
.\.venv\Scripts\python.exe -m pytest tests\test_runtime_manager.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_launcher_scripts.py -q
```

## 窄冒烟包（tray / quit / workbenchUrl 交接，合入前子集）

```powershell
# Python: live URL / ports.json handoff
.\.venv\Scripts\python.exe -m pytest tests\test_vibelution_desktop_entry.py tests\test_runtime_manager_electron_window_handoff.py -q

# Electron: tray menu, quit/lifecycle, workbench URL
node desktop\electron\node_modules\vitest\vitest.mjs run tests/windowProvider.test.ts tests/desktopTray.test.ts tests/desktopLifecycleCoordinator.test.ts tests/desktopMainTransactionalClose.test.ts tests/desktopMainTrayIntegration.test.ts tests/desktopActionClient.test.ts tests/desktopSmokeShutdown.test.ts
```

选择器：`desktop-electron-smoke`（`tests/test_matrix.yaml`）。这不是双壳重写；改完源码后若用户跑的是 `dist\desktop\win-unpacked\Vibelution.exe`，需要重新 package 才看得到 tray/quit/handoff。

影响面选择器：`tests\select_tests.py --changed-file <path> --commands-only`。

---

## 相关

| 文档 | 用途 |
| --- | --- |
| [`README.md`](README.md) | 全量 facade 表 |
| [`runtime_scene/README.md`](runtime_scene/README.md) | scene pack 路由 |
| [`docs/guides/loop.md`](../../../docs/guides/loop.md) | 诊断三件套 + Launcher 命令 |
| [`docs/ops/config/07-launcher-runtime-workbench.md`](../../../docs/ops/config/07-launcher-runtime-workbench.md) | 运维配置 |
