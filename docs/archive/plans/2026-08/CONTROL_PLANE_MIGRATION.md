# Launcher Electron 控制面迁移

Status: **Closed** (2026-08-14). T1–T9 landed; `:8765` retired as the product control plane. Electron main is the Launcher control plane (IPC), the Python workbench runs as a child, and the C# shim forwards to Electron. See `desktop/electron/README.md` and `core/web/services/launcher_runtime.md` for the current contract. Archived per the ledger close condition.
Authority: [ADR 0009](../../../docs/adr/0009-launcher-control-plane-lives-in-electron-main.md) · 本文件只是执行账本，不另立规范。
Close condition: 产品路径不再监听/依赖 `127.0.0.1:8765`；控制窗口只经 IPC 拿到 status/lifecycle；C# shim 把命令交给已运行的 Electron；`core/launcher/app.py` 不再作为产品控制面 HTTP 服务。
On close: 把仍有历史价值的段落提炼进 `README.md` / `launcher_runtime.md` / ADR 0009 Consequences，本文件迁入 `docs/archive/plans/2026-08/`。

Out of scope（整次迁移都不要做）：

- 把 Chat / Agent / LLM / `core/runtime_manager` 改写成 TypeScript
- 把工作台 FastAPI 与工作台 renderer 合成「一列」
- Tauri / WinUI / 在 Electron 外再开一个 Node HTTP 控制面
- 用 Close leftover 删除 worktree 或未提交文件
- 用 `taskkill` / 可见控制台作为后台路径
- 在根 `main` 直接写；未授权不 push

---

## 现行痛点（已被代码证实）

| 现象 | 机制 |
| --- | --- |
| `main 控` 先出来，仪表盘「未连接」、表空 | 控制窗口 `loadURL(http://127.0.0.1:8765/launcher)`，React `fetch` `/api/launcher/status`；`LauncherRoute.isLauncherStatusNetworkDisconnect` |
| 列表「可启动」但屏幕上还有冻结的 `main` 工作台 | Electron 丢失 `workbenchWindow` 指针；Python overlay 仍信 closed bundle；Start 再 `BrowserWindow` |
| `stop` 之后桌面还在、新 asar 不生效 | `VibelutionLauncher.exe stop` 停的是 Python 控制面；产品壳是 `Vibelution.exe` |

窗口侧 leftover adopt 已在 `ea2cf31b7` 合入本地 `main`。本迁移要让 **控制面与窗口同属 Electron 主进程**，而不是继续让 Python HTTP 当权威。

---

## 推荐路径（strangler）

```text
T1 IPC 门面 + 控制窗口就绪闸
  → T2 控制窗口不再靠 :8765 提供静态页
  → T3 窗口/session 只由 main 写入
  → T4 start/stop/restart/rebuild 由 main 编排
  → T5 分支实例 list/start/stop/close 由 main 编排
  → T6 close transaction / desktop-actions 反转到 main
  → T7 settings / developer-mode / maintenance 改为 CLI 子进程
  → T8 C# shim 转发到 Electron
  → T9 退役 :8765
```

每一阶段合入后，产品路径只允许 **一个** 窗口真源、**一个** lifecycle 命令写入者。主进程代理 Python 可以，renderer 直连 `:8765` 不行（T1 之后）。

Python 在目标态保留为：

- 工作台 FastAPI + Runtime Manager 子进程
- git / worktree / maintenance / developer-cleanup 的 **JSON CLI**（`pythonw` + `windowsHide`）
- 不是长期占用 8765 的 Launcher HTTP 服务

---

## TASK_GRAPH

拆分理由：跨进程契约、窗口 SSOT、C# 兼容、退役 HTTP 各有独立验收和回滚点；不能在同一 PR 里一次性搬 `core/launcher/service.py`（约 3400 行）加约 50 条 `/api/launcher/*`。

Critical Path: T1 → T2 → T3 → T4 → T5 → T6 → T8 → T9。T7 可在 T4 之后与 T5/T6 串行插入，但必须在 T9 前完成，否则 8765 退不掉。

### Task 1: IPC 门面 + 控制窗口就绪闸

- Owner/Boundary: `desktop/electron/src/ipc.ts` · `preload.ts` · 新建 `src/protocol/launcherIpcHost.ts`；`web/src/api/launcher.ts`；`web/src/routes/LauncherRoute.tsx` 仅改 transport / 加载态。不改 `LauncherBranchInstancesPanel*` UI（可能与其它 lane 重叠）。
- Dependency: 无。可继续 spawn Python `:8765` 并在 **main 内** 代理。
- Mode: BDD_TDD（renderer↔main 公共契约）。
- 行为:
  - `window.vibelutionLauncher` 增加 `launcherInvoke(method, payload)`（或按现有 channel 表展开），sender 仅允许控制窗口。
  - `web/src/api/launcher.ts`：有 preload bridge 时走 IPC；**不要**再为产品窗口拼 `http://127.0.0.1:8765`。
  - 控制窗口在 IPC host ready 之前只显示启动中，不渲染空的「未连接」可启动表。
  - 工作台 renderer 不得拿到 Launcher 控制 IPC。
- Verification/Stop:
  - `web`：`launcher.test.ts`、`LauncherRoute.layout.test.ts`；`npx tsc -b --pretty false`
  - `desktop/electron`：新 IPC host 测试 + 现有 `launcherControlClient` 测试仍绿（此阶段 client 可仍被 host 用来打 Python）
  - 手测：断掉 8765 时控制窗口不得出现空仪表盘冒充「可启动」；应是启动中/控制面失败，而不是假 idle。
- Rollback: 保留 main 内 HTTP 代理；feature flag 只存在于 main，不把 HTTP 交回 renderer。

### Task 2: 控制窗口加载 packaged `web/dist`，不依赖 `:8765` 静态服务

- Owner/Boundary: `windowUrlResolver.ts` · `urlPolicy.ts` · `electronWindowProvider.openLauncher` · `main.ts` bootstrap。
- Dependency: T1（renderer 已不靠页面 origin 推断 8765）。
- Mode: SIMPLE。
- 行为: 注册 Electron custom protocol 或等价的本地加载，使 `/launcher` 来自 `web/dist`。`assertLocalHttpUrl` 继续约束 **工作台** origin。不要用随意 `file://` 削弱 CSP。
- Verification/Stop: windowProvider 测试覆盖 launcher URL 不再默认 8765；安全策略测试拒绝非本地工作台 URL。Python `:8765` 仍可在后台代理 API。
- Rollback: 退回 `loadURL(http://127.0.0.1:8765/launcher)`，IPC 仍在。

### Task 3: 窗口 / desktop-session 只由 main 写

- Owner/Boundary: `electronWindowProvider.ts`（已有 leftover adopt，**保持合同**）· `windows/desktopSessionClient.ts` 改为 in-process store · Python `desktop_session_store.py` 降为兼容读或删除写入。
- Dependency: T1。可与 T2 串行。
- Mode: BDD_TDD。
- 行为:
  - status 快照里的 `window.open` 以 Electron `getAllWindows()` / provider 为准。
  - leftover adopt / extras destroy / isolated 窗口豁免 保持 `ea2cf31b7` 合同。
  - Python overlay 不得再把 closed bundle 写成「可启动」而盖掉仍存在的 BrowserWindow。
- Verification/Stop: `tests/windowProvider.test.ts`；desktop session 相关 electron 测试；现有 `tests/test_launcher_service.py` 中依赖 HTTP session 的用例改为 CLI 或标记遗留。
- Rollback: 恢复 session HTTP，但 renderer 仍走 IPC（main 再转发）。

### Task 4: start / stop / restart / rebuild-and-start 由 main 编排

- Owner/Boundary: 新 `src/process/workbenchLifecycle.ts`（名可调整）；`launcherServiceClient.ts` 从「bootstrap 8765」改为「spawn 工作台 Python」；tray 不再 `POST /api/launcher/restart`。
- Dependency: T3（启动前必须知道窗口是否已在）。
- Mode: BDD_TDD（active-work guard、无控制台 spawn、失败不假 running）。
- 行为:
  - Start 工作台 = 确认/adopt 窗口 + spawn/attach Runtime Manager + load workbench URL。
  - Stop = close transaction 路径，不是 `taskkill`。
  - Rebuild 仍跑前端预检（含需要时 `tsc -b`），但命令主人是 Electron。
  - 所有 spawn：`pythonw` / `windowsHide: true` / 项目 `no_window_subprocess_kwargs`。
- Verification/Stop: electron vitest + `tests/test_vibelution_desktop_entry.py` 收缩到 spawn-workbench；禁止新的可见控制台路径。
- Rollback: main 继续把 lifecycle POST 给 8765。

### Task 5: 分支实例 list / start / stop / close 由 main 编排

- Owner/Boundary: 新 TS orchestration + Python JSON CLI 提供 git/worktree 事实（不要在 TS 重写 git）。`core/launcher/branch_instance_lifecycle.py` 可先变成 CLI。
- Dependency: T4。
- Mode: BDD_TDD。
- 行为: Close leftover = 停实例 + 清 failed 注册，行回到可启动；**不**删 worktree。脏 isolated worktree 仍允许启动（已有合同）。
- Verification/Stop: 分支实例 electron 测试 + 现有 `tests/test_launcher_branch_instance_runtime.py` 迁到 CLI 或双跑至 T9。
- 保护：不要改 `web/src/routes/LauncherBranchInstancesPanel*` 的 VUI 结构，除非 transport 类型被迫变。

### Task 6: workbench-close-transactions 与 desktop-actions 反转

- Owner/Boundary: `workbenchCloseTransactionClient.ts` · `desktopActionClient.ts` · `shutdownCoordinator.ts` · `runtimeSceneBridge.ts`。Python 侧从「发动作给 Electron 轮询」改为「被 Electron 调用」。
- Dependency: T4。
- Mode: BDD_TDD。
- 行为: Electron 不再 claim HTTP desktop-actions；关闭事务的权威在 main。工作台只报告自己的 backend 状态。
- Verification/Stop: `desktopActionClient.test.ts` · `desktopMainTransactionalClose.test.ts` · `desktopSmokeShutdown.test.ts`；对应 pytest 改为遗留或 CLI。

### Task 7: settings / developer-mode / maintenance

- Owner/Boundary: `core/launcher/developer_mode.py` · `maintenance_reset.py` 保持 Python 实现，经 JSON CLI 调用；IPC 只做门面。
- Dependency: T1；必须在 T9 前完成。
- Mode: SIMPLE（破坏性 apply 仍要 confirm 合同测试）。
- 行为: preview/apply/hash confirm 语义不变。不要把重置逻辑抄进 TS。
- Verification/Stop: `tests/test_launcher_developer_mode.py` · `tests/test_reset_service.py` 继续打 Python CLI；electron 只测 IPC 转发与错误码。

### Task 8: C# shim 与第二实例命令

- Owner/Boundary: `scripts/windows_launcher_entry/VibelutionLauncher.cs` · Electron `requestSingleInstanceLock` / `second-instance` · `scripts/vibelution_desktop_entry.py` 去掉「为 shim 拉起 8765」。
- Dependency: T4（命令在 main 里已存在）。
- Mode: BDD_TDD（shim 兼容 `start|stop|restart|rebuild-and-start`）。
- 行为:
  - Electron 活着：shim **不得** POST `:8765`；转发 argv 给现有实例。
  - Electron 没活：shim 启动 `Vibelution.exe`，由 Electron 接手。
  - WinForms NotifyIcon 仅当 Electron 不在。
- Verification/Stop: 现有 native/desktop entry 测试改断言；手测 `VibelutionLauncher.exe --project "<root>" start` 只 focus/启动同一 Electron。
- 授权闸门: 不改已安装 `%LOCALAPPDATA%\Vibelution\Launcher\VibelutionLauncher.exe` 的复制策略以外的发布流程；用户未授权不 push。

### Task 9: 退役 `:8765`

- Owner/Boundary: `core/launcher/app.py` 产品入口删除或改为测试夹具；`DEFAULT_LAUNCHER_CONTROL_PORT = 8765` 从 `web/src/api/launcher.ts`、`vibelution_desktop_entry.py`、C# `GetLauncherPort` 产品路径移除；更新 `launcher_runtime.md` / `07-launcher-runtime-workbench.md` 为现行而非目标。
- Dependency: T2–T8。
- Mode: SIMPLE + 回归包。
- Verification/Stop:
  - 仓库与产品路径 grep 不到「控制窗口依赖 8765」
  - `desktop-electron-smoke` + 聚焦 pytest + `web` launcher tests + `desktop/electron` `tsc --noEmit`
  - 启动后本机无 Launcher 控制口监听 8765
- Rollback: 恢复 app.py 与 main 代理；IPC 合同保留。

---

## 现行 HTTP 面（迁出清单）

来源：`core/launcher/app.py`。T9 前每一组必须有新主人。

| 组 | 路由前缀 | 目标主人 |
| --- | --- | --- |
| status / freshness | `/api/launcher/status` · `/freshness` | T1 代理 → T3/T4 main 聚合 |
| lifecycle | `/start` `/stop` `/force-stop` `/restart` `/rebuild-and-start` `/lifecycle-intents` | T4 |
| branch-instances | `/branch-instances*` | T5 |
| settings | `/settings/workbench-window` `/settings/startup` | T7 |
| developer-mode | `/developer-mode*` | T7 |
| maintenance | `/maintenance/reset*` | T7 |
| close tx | `/workbench-close-transactions*` | T6 |
| desktop-actions | `/desktop-actions*` | T6 |
| desktop-sessions | `/desktop-sessions*` | T3 |
| runtime-scene events | `/runtime-scene/events` | main 桥到现有 `runtime_scene` pack（不改 pack 写入语义） |
| static `/launcher` | FastAPI `WEB_DIST` | T2 Electron protocol |

---

## 验证策略（全路径）

| 阶段 | 必跑 |
| --- | --- |
| 任何 Electron 主进程 | `desktop/electron` `tsc --noEmit` + 触及 vitest |
| 任何 `web/` 控制窗口 transport | `web` `npx tsc -b --pretty false` + launcher vitest；触及 UI 时 `vuiShadcnRouteContract` |
| Python 仍被 spawn/CLI | 对应 `tests/test_launcher_*.py` / `test_vibelution_desktop_entry.py` |
| 子进程 | 断言 `windowsHide: true` / `pythonw` / `CREATE_NO_WINDOW`；禁止新 `taskkill.exe` |
| 用户可测 | 先 **退出** `Vibelution.exe`，再 `desktop/electron` `npm run package:dir`；`stop` 不够 |

Launcher refresh：**required before user testing**（Electron 主进程）。Python-only CLI 阶段可以是 not needed。

---

## 风险与回滚

| 风险 | 检测 | 回滚 |
| --- | --- | --- |
| 双写入（Python overlay vs Electron 窗口） | status.window.open 与 `BrowserWindow.getAllWindows()` 不一致 | 该阶段只保留 main 为窗口写入者 |
| 控制窗口未就绪就画空表 | 「未连接」+ 空表 + 仍有 BrowserWindow | T1 闸门；禁止 renderer HTTP fallback |
| 无控制台回归 | 启动/停止弹出 cmd/WT | 拒合入；走 shared helper |
| asar 未加载 | 用户仍看到旧行为 | 确认进程启动时间晚于 asar 写入；托盘退出后重启 |
| C# 仍打 8765 | shim 在 Electron 活着时启动第二套 Python | T8 闸门 |
| 与其它 lane 重叠 | `LauncherBranchInstancesPanel*`、`AGENTS.md`、`electronWindowProvider.ts` 现有 claim | 缩 scope；窗口合同只加测试不改行为，除非本任务明确拥有 |

失败检测：runtime scene + `desktop-entry-python.log` + Electron 主进程日志。不要用 `taskkill` 清场。

---

## 并行 / 串行边界

- 只串行 Critical Path。不要平行改 `electronWindowProvider.ts` 的 adopt 合同（已有 claim `cursor-grok-launcher-zombie-workbench-window` 曾覆盖该文件）。
- 不要平行改 `AGENTS.md` / `development-standard.md`（现有 `agent-root-agents-cleanup-policy`）。
- `polish-launcher-workbench-tools` 一类 VUI 面板工作与 T1–T9 的 transport 拆开。

---

## 实现许可

用户已同意目标拓扑。T1 起按 HIGH_RISK 在独立 worktree 实施；每任务可单独 ff-only 合入本地 `main`。不要在本规划提交里改 `core/launcher/service.py`。
