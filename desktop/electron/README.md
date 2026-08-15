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
| 托盘 / 单实例 / 退出 | `src/tray/desktopTray.ts` · `src/main.ts` | 与 WinForms 同时显示 NotifyIcon；用 `taskkill` 清 Electron |
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

VibelutionLauncher.exe = 无控制台薄 shim
  → Electron 已在：转发 start|stop|restart
  → Electron 不在：启动 Electron，不自建 :8765 控制面
```

迁移完成前，主进程仍可能 **spawn 并代理** Python `:8765`。那是 strangler 桥，不是目标架构。

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
node node_modules\vitest\vitest.mjs run tests/windowProvider.test.ts tests/desktopTray.test.ts tests/desktopMainTransactionalClose.test.ts tests/desktopMainTrayIntegration.test.ts tests/launcherServiceClient.test.ts
```

改 `web/src/api/launcher.ts` 或 Launcher 路由时，另跑：

```powershell
cd web
npx tsc -b --pretty false
npm test -- --run launcher
```

产品用户测的是 `dist\desktop\win-unpacked\Vibelution.exe`。改 Electron 主进程后必须 **退出桌面程序** 再 `npm run package:dir`；只 `stop` Python `:8765` 不会加载新 `app.asar`。
