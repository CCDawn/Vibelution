# Launcher / Runtime 迷你索引（R13）

**读者：coding Agent。**
**目标：30 秒内定位生命周期、无控制台红线与主测；不要在 Web facade 里堆进程逻辑。**

权威细则：`docs/standards/development-standard.md` §8.0 · 根 `AGENTS.md` §2 · [ADR 0009](../../../docs/adr/0009-launcher-control-plane-lives-in-electron-main.md)。
隔离实例生命周期合同：[`core/launcher/instance-lifecycle.md`](../../launcher/instance-lifecycle.md)。
Runtime scene pack：[`runtime_scene/README.md`](runtime_scene/README.md)。
Electron 壳：[`desktop/electron/README.md`](../../../desktop/electron/README.md)。已归档迁移账本：[`docs/archive/plans/2026-08/CONTROL_PLANE_MIGRATION.md`](../../../docs/archive/plans/2026-08/CONTROL_PLANE_MIGRATION.md)。

---

## 30 秒编辑表

| 你在改… | 先打开 | 禁止 |
| --- | --- | --- |
| start / stop / restart / active-work 拦截 | Electron `lifecycle/mainLine` 队列 → `runWorkbenchLifecycle` → 直接 `pythonw scripts/web_workbench.py`；active-work 读 work_runs / evolution 快照 | 在 `runtime_service.py` 再写一套 lifecycle；renderer 直连 :8765；产品路径再 spawn `--action lifecycle`；让 RM daemon 在 Electron 在场时执行 open/close/restart 队列 |
| 隔离 worktree 启停 / READY / 端口 | [`instance-lifecycle.md`](../../launcher/instance-lifecycle.md) · Electron `instanceRegistryStore.ts` · `isolatedInstanceSupervisor.ts` · `instanceAdmissionControl.ts` · `workbenchBackend.ts` | exec 目标树 `vibelution_launcher.py`；spawn exit 0 当 `running`；无 generation CAS 盲写 `instances.json`；observe/waitForHttp 再 spawn Python bridge；hang 回收仍看 spawnPid；把 I4a 冷却写进 `instances.json`；让 `state_refresh` 再 `save_registry` |
| Launcher 窗口真相 / leftover adopt | `desktop/electron/src/windows/electronWindowProvider.ts` | Python overlay 把 live window 标成 closed |
| Launcher UI 传输 | `web/src/api/launcher.ts`（preload IPC 门面） | 可操作仪表盘在 API 未就绪时画空表 + `未连接` |
| Web 路由 import 稳定面 | `launcher_service.py`（re-export only） | 往 facade 加业务体 |
| close transaction / desktop session | Electron main（`workbenchCloseTransactionStore.ts` · `desktopSessionStore.ts`）；Python session 只作兼容副本 | 裸 `taskkill.exe`、直接杀 PID 当常态 |
| Reset / maintenance / settings / developer-mode | `core/launcher/maintenance_reset.py`（`reset_service.py` 仅 alias）经 `vibelution_desktop_entry.py --action launcher-api` CLI | 把 reset 逻辑抄进 TS；平行 reset 实现 |
| Runtime Manager daemon / work-run / 预检 | `core/runtime_manager/` | 用 PowerShell lifecycle 制造可见控制台 |
| 轻量 RM 存活检查 | `runtime_manager_control_service.py` | 在此扩展完整 lifecycle |
| Workbench runtime summary 投影 | `runtime_service.py` | 当成第二写入者改 store |
| Scene 证据包读写 / 诊断 | `runtime_scene/*` · facade `runtime_scene_service.py` | 手写无界 log dump 进 Prompt |
| 托盘 / 脚本入口 | `scripts/vibelution_launcher.py` · `scripts/vibelution_desktop_entry.py`（JSON CLI bridge） | 后台路径弹 `cmd`/`powershell`/WT |
| 产品托盘 owner | Electron `desktopTray.ts` + `desktopShellOwner.ts` | 与 WinForms 同时显示 NotifyIcon |
| 托盘 Launcher 代码版本 | `desktopShellFreshness.ts` `formatTrayLauncherFreshness` ← `desktop-shell-status` | 向工作台 HTTP `/api/launcher/freshness` 问「Launcher 版本」 |

---

## 生命周期（谁拥有什么，现行）

```text
Electron main (TS) = Launcher 控制面（ADR 0009 已落地）
  → pin userData to %LOCALAPPDATA%\Vibelution\DesktopShell before requestSingleInstanceLock
  → 控制窗口 renderer 只走 IPC（launcher:invoke）；不 fetch :8765
  → 工作台 renderer 加载工作台 origin（通常 :8000）
  → lifecycle 启停由 main 直接 spawn `pythonw scripts/web_workbench.py`（无 `--action lifecycle` CLI）
    settings / maintenance / leftover `:8765` 仍可走无控制台 Python JSON CLI
    （vibelution_desktop_entry.py --action launcher-api|resolve-workbench|stop-launcher）
    `--action lifecycle` / `--action branch-instance` 写路径已退役，返回 `control_plane_is_electron`
    Electron 在场时 RM daemon 跳过 open/close/restart 文件队列（`hot_restart_workbench` 演化循环仍跑）
    状态刷新走只读 `preview_reconcile_registry`，不得写 `instances.json`
  → Python 子进程：Runtime Manager + FastAPI 工作台（packaged/product 不占用 :8765）
  → 关闭桌面壳 / 重启 Launcher 必须先停掉 RM daemon 及其工作台/隔离实例进程树
  → 打开桌面壳时必须先清掉上一轮托管进程树，不能 attach 到已无父进程的 RM/工作台；点启动/重启也会先杀掉遗留工作台再拉当前 checkout
  → 打开/退出桌面壳时必须 `stop-launcher --use-state-owned-backend-pid` 清 leftover Python `:8765`；不得把 leftover HTTP 当第二控制面 attach
  → close transaction / desktop session 真相在 main；Python 侧只报告 backend 状态
  → 「工作台开着」= 后端健康 **且** Electron 工作台窗口 open。仅后端就绪（noBrowser）是 `partial` / `browser_missing`，不是 `open`
  → isolated worktree backends 仍在同一 desktop shell 开 `{shortName} 台`
  → Electron `launcherServiceClient` 只 `stop-launcher` 清理 leftover `:8765`（已知 pid 走 `--owned-backend-pid`，否则 `--use-state-owned-backend-pid`），不再 bootstrap uvicorn

VibelutionLauncher.exe = thin no-console shim
  → packaged Vibelution.exe 且 provenance 当前：转发 start|stop|restart|rebuild-and-start 给 Electron（second-instance），不自建 :8765
  → packaged 缺失或落后当前 `HEAD:desktop/electron`：`vibelution_desktop_entry.py --action launch-desktop-shell` 编译并启动 unpackaged Electron main（当前 checkout），不自建 :8765
```

Web: `core/web/routes/launcher.py` · `runtime.py` · `logs.py` → `launcher_service` / `runtime_service` / `runtime_scene_service`（薄委托）。

- Operator config 真源：`%USERPROFILE%\Documents\Vibelution\config\config.toml`（ADR0003）。
- active-work 挡 refresh：报告固定句（`AGENTS.md` §4），禁止强杀绕过。
- Launcher refresh 命令见 `docs/guides/loop.md` §3。
- 产品重启 wall-clock 基线约 **7.3s**。`restart_initial_observation_ms` 只在 RM daemon 仍执行 `restart_workbench` 文件队列时出现；Electron 在场的产品路径不再打这条探针，对照请用 Launcher 启停墙钟，不要把缺探针当成计时回归。

---

## 无控制台检查点（FAIL CLOSED）

改 spawn / stop / Git / 轮询 / 子进程时，合入前自检：

1. 后台父进程优先 `pythonw`；子树仍要 `CREATE_NO_WINDOW` / 项目 shared no-console helper。
2. 禁止产品路径弹出 `cmd.exe`、`powershell.exe`、Windows Terminal、OpenConsole、交互式 Git 编辑器。
3. **禁止** `taskkill.exe` 作为常态清理；用 in-process `psutil`/WinAPI（§8.0）。
4. 禁止用裸 `git` cmd wrapper、`npm`/`cmd` 脚本壳当后台路径。
5. 用户明确打开的 CLI 终端面板除外。

证据：相关 launcher/runtime 测试 + 说明 helper/`pythonw`/`CREATE_NO_WINDOW`/`windowsHide` 落点。Electron 侧所有 JSON CLI spawn 均断言 `windowsHide: true`。

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
# Python: live URL / ports.json handoff / JSON CLI bridge
.\.venv\Scripts\python.exe -m pytest tests\test_vibelution_desktop_entry.py tests\test_runtime_manager_electron_window_handoff.py -q

# Electron: tray menu, quit/lifecycle, workbench URL, close store, IPC host
node desktop\electron\node_modules\vitest\vitest.mjs run tests/windowProvider.test.ts tests/desktopTray.test.ts tests/desktopLifecycleCoordinator.test.ts tests/desktopMainTransactionalClose.test.ts tests/desktopMainTrayIntegration.test.ts tests/desktopActionClient.test.ts tests/desktopSmokeShutdown.test.ts tests/launcherIpcHost.test.ts tests/workbenchCloseTransactionStore.test.ts
```

选择器：`desktop-electron-smoke`（`tests/test_matrix.yaml`）。这不是双壳重写。packaged `Vibelution.exe` 由 Launcher 对照 provenance 自刷新 `app.asar`；不要让用户手跑 `package:dir`。

影响面选择器：`tests\select_tests.py --changed-file <path> --commands-only`。

---

## 相关

| 文档 | 用途 |
| --- | --- |
| [`README.md`](README.md) | 全量 facade 表 |
| [`runtime_scene/README.md`](runtime_scene/README.md) | scene pack 路由 |
| [`docs/adr/0009-launcher-control-plane-lives-in-electron-main.md`](../../../docs/adr/0009-launcher-control-plane-lives-in-electron-main.md) | Launcher 控制面落 Electron main |
| [`desktop/electron/README.md`](../../../desktop/electron/README.md) | 桌面壳 30 秒表 |
| [`docs/archive/plans/2026-08/CONTROL_PLANE_MIGRATION.md`](../../../docs/archive/plans/2026-08/CONTROL_PLANE_MIGRATION.md) | 已归档迁移账本 |
| [`docs/guides/loop.md`](../../../docs/guides/loop.md) | 诊断三件套 + Launcher 命令 |
| [`docs/ops/config/07-launcher-runtime-workbench.md`](../../../docs/ops/config/07-launcher-runtime-workbench.md) | 运维配置 |
| [`core/launcher/instance-lifecycle.md`](../../launcher/instance-lifecycle.md) | 隔离实例 desired/observed、202、generation、READY |
