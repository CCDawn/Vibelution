# Electron Desktop Shell

**读者：coding Agent。**
**目标：30 秒定位 Launcher 控制面、窗口、托盘与无控制台 spawn；不要在 Python `:8765` 再写一套产品控制面。**

权威决策：[ADR 0009](../../docs/adr/0009-launcher-control-plane-lives-in-electron-main.md)。
迁移账本（已关闭，归档）：[CONTROL_PLANE_MIGRATION.md](../../docs/archive/plans/2026-08/CONTROL_PLANE_MIGRATION.md)。
现行 Python 遗留面：[`core/web/services/launcher_runtime.md`](../../core/web/services/launcher_runtime.md)。

---

## 30 秒编辑表

| 你在改… | 先打开 | 禁止 |
| --- | --- | --- |
| Launcher 窗口 / 遗留窗口 adopt | `src/windows/electronWindowProvider.ts` | 把 OS 上任意窗口当成 running；拆掉 isolated instance 窗口当 leftover |
| 托盘 / 单实例 / 退出 | `src/tray/desktopTray.ts` · `src/main.ts` | 与 WinForms 同时显示 NotifyIcon；用 `taskkill` 清 Electron；托盘「Launcher 代码版本」去打工作台 HTTP `/api/launcher/freshness` |
| `--project` 槽位 | `src/protocol/applyProjectSlot.ts` · `src/appLock.ts` · `src/main.ts` | 把 worktree 当成第二套 DesktopShell；未登记路径静默 start 当前 main |
| Launcher 控制命令（目标） | `src/ipc.ts` · `src/preload.ts` · 新 IPC host | 控制窗口 `fetch` `:8765` 当产品路径 |
| 工作台 URL / 安全 | `src/windows/windowUrlResolver.ts` · `src/security/urlPolicy.ts` | 工作台改走 IPC 替代 FastAPI |
| Python 子进程 spawn | `src/process/launcherServiceClient.ts` | 可见控制台；`windowsHide: false` |
| C# 入口转发 | `scripts/windows_launcher_entry/VibelutionLauncher.cs` | 把 C# 做成第二控制面 |

---

## 目标拓扑（ADR 0009）

```text
Electron 主进程（TS）= Launcher 服务
  ├─ 控制窗口 renderer（现有 React/VUI）── IPC，不 fetch :8765
  ├─ 工作台 renderer ── 加载工作台 origin（通常 :8000 的 dist）
  └─ 子进程：Python 工作台（FastAPI + Runtime Manager）
     以及必要的 git/worktree/maintenance CLI
     关闭桌面壳时必须停掉这棵进程树；打开桌面壳时必须先清掉上一轮托管进程，再拉起当前 checkout 的新 daemon
     打开/退出时还要 `stop-launcher --use-state-owned-backend-pid` 清掉 leftover Python `:8765`，不得把它当成第二控制面 attach

VibelutionLauncher.exe = 无控制台薄 shim
  → Electron 已在：转发 start|stop|restart；`--project` 作用在已有壳的 isolated slot 上，不是第二套 Electron workspace / userData
  → Electron 不在：启动当前 checkout 的 Electron main
     （packaged 且 provenance 对应当前 `HEAD:desktop/electron` 时用 `Vibelution.exe`；
      否则编译并启动 unpackaged `desktop/electron` 的 `electron dist/main.js`）
  → 不自建 :8765 控制面
```

Packaged / product Electron **不再 spawn 或代理** Python `:8765`。控制面唯一入口是 IPC；`launcherServiceClient` 只保留 leftover 进程的 `stop-launcher` 清理：无已知 owned pid 时走 `--use-state-owned-backend-pid`。桌面壳 **打开** 时与托管进程树一起 reap leftover `:8765`；**退出** 时即使 bootstrap `mode` 是 `attached` 也要再清一次。无 `win-unpacked` 或 packaged 落后当前 `HEAD:desktop/electron` 时，C# shim / Python `launch-desktop-shell` 启动 **当前 checkout 的 unpackaged Electron main**（`desktop/electron` 的 `npm run build` + `electron dist/main.js`），不是 Python HTTP 控制面。

---

## 已锁定的窗口合同

- 同 origin 的遗留工作台窗口：adopt 第一扇，destroy extras。
- 关闭/批准关闭时，即使 `workbenchWindow` 指针为 null 也要扫 leftovers。
- isolated branch instance 窗口不是 leftover，不得当 extras 销毁。
- Close leftover ≠ 维护与清理；不删除 worktree / 未提交文件。
- 控制窗口 `window.open`：deny 并复用当前窗口。

---

## 验证（可复制）

```powershell
cd desktop\electron
npx tsc --noEmit --pretty false
node node_modules\vitest\vitest.mjs run tests/windowProvider.test.ts tests/desktopTray.test.ts tests/desktopMainTransactionalClose.test.ts tests/desktopMainTrayIntegration.test.ts tests/launcherServiceClient.test.ts tests/packagedLauncherControlPlane.contract.test.ts
```

改 `web/src/api/launcher.ts` 或 Launcher 路由时，另跑：

```powershell
cd web
npx tsc -b --pretty false
npm test -- --run launcher
```

产品用户测的是 `dist\desktop\win-unpacked\Vibelution.exe`。Launcher 在 packaged 启动时对照 `package-provenance.json` 的 `electronTreeHash` 与当前 `HEAD:desktop/electron`；壳过期就先退出，由无控制台 helper 重建 `win-unpacked` 再拉起当前 checkout。不要让用户手跑 `package:dir`。只 `stop` Python `:8765` 不会加载新 `app.asar`。托盘版本行走同一套 `desktop-shell-status`，不要求工作台后端在线。
