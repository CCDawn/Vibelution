# ADR 0009 · Launcher Control Plane Lives In Electron Main

## Status

Accepted (2026-08-14). Amended 2026-08-17: the packaged product path no longer spawns Python `:8765`.

## Context

The product Launcher is a desktop control surface. Today it is split across three runtimes that do not share one source of window and lifecycle truth:

```text
C# VibelutionLauncher.exe  (thin no-console shim / last-resort tray)
  → Electron main (windows, tray, spawn)
      → Python FastAPI :8765  (core/launcher/app.py + service.py)
          → React Launcher UI fetches http://127.0.0.1:8765/api/launcher/*
      → Python workbench :8000 (Runtime Manager + FastAPI + web/dist)
```

Observed failures this split causes:

1. Electron can paint `main 控` before or after the Python control plane is reachable. The React shell then `fetch`es `:8765`, hits `isLauncherStatusNetworkDisconnect`, and shows **未连接** with empty tables.
2. Window truth lives in Electron (`electronWindowProvider.ts`, leftover-window adoption). Overlay truth lives in Python (`desktop_session_store`, status payload). When the in-process window pointer is lost, the list can say **可启动** while a frozen workbench window is still on screen, and Start opens a second window.
3. Official `VibelutionLauncher.exe --project "<root>" stop` stops the Python control plane, not the Electron shell. Packaged `app.asar` updates do not load until the desktop process is quit and relaunched.

The Launcher should be an independent product whose **service and frontend stay together**. Workbench Chat/Agent/LLM/`core/runtime_manager` stay Python. This is not a request to merge workbench backend/frontend columns in the UI, rewrite the workbench backend in TypeScript, adopt Tauri/WinUI, or add a second Node HTTP server in front of `:8765`.

## Decision

1. **Electron main is the Launcher control plane** (TypeScript). It owns launcher lifecycle commands, window/session truth, branch-instance orchestration that affects desktop windows, tray actions, and the loading/ready gate for the control window.
2. **The Launcher renderer talks to main over IPC**, using the existing `preload.ts` / `IPC_CHANNELS` pattern. The product path must not `fetch` `:8765`. A disconnected empty dashboard is a control-plane failure, not a valid idle UI.
3. **Workbench remains Python.** Electron opens a separate renderer that loads the workbench origin (typically `:8000` / Runtime Manager + FastAPI + `web/dist`). Isolated branch instances remain extra workbench windows inside the same Electron process, each with its own Python backend.
4. **`VibelutionLauncher.exe` stays a thin no-console shim.** If an Electron desktop owner is alive, the shim forwards `start|stop|restart|rebuild-and-start` into that process (second-instance argv or an equivalent local command channel). It must not become a second control plane. WinForms NotifyIcon remains last-resort bootstrap only when Electron is not running.
5. **Python `:8765` is a strangler leftover, not the target.** Packaged Electron no longer spawns or proxies it as the product control plane (`bootstrapMainOwnedLauncher` + `resolve-workbench`). Unpackaged checkout HTTP (`vibelution_desktop_entry.py --action launcher`) remains for tests and the native shim. Remaining Python launcher logic on the product path is invoked as no-console child/CLI libraries (`pythonw` + `windowsHide` / `CREATE_NO_WINDOW`), not as a long-lived Launcher HTTP server. `core/launcher/app.py` serving `/launcher` and `/api/launcher/*` is not the packaged control plane.
6. **Preserve already-shipped contracts** while moving ownership:
   - leftover workbench windows of the same origin are adopted; extras are destroyed; isolated instance windows are not destroyed as leftovers;
   - Close leftover ≠ 维护与清理; Close does not delete worktrees or uncommitted files;
   - active-work guard still blocks refresh with the fixed Chinese sentence in `AGENTS.md` §4;
   - Windows product paths remain no-console (`AGENTS.md` §2 / development-standard §8.0).
7. **Migrate with a strangler**, not a one-shot rewrite of `core/launcher/service.py`. The execution ledger is archived at [`docs/archive/plans/2026-08/CONTROL_PLANE_MIGRATION.md`](../archive/plans/2026-08/CONTROL_PLANE_MIGRATION.md) and is not living procedure. Living ownership: [`desktop/electron/README.md`](../../desktop/electron/README.md) and [`core/web/services/launcher_runtime.md`](../../core/web/services/launcher_runtime.md).

## Consequences

- Launcher UI origin will move off `:8765` (Electron protocol or packaged `web/dist`). `web/src/api/launcher.ts` transport becomes IPC when `window.vibelutionLauncher` is present.
- `launcherControlClient.ts`, `desktopActionClient.ts`, `desktopSessionClient.ts`, `workbenchCloseTransactionClient.ts`, tray POSTs, and shutdown status fetches invert: they become in-process calls, then Python is a child for workbench spawn/git/worktree/maintenance only.
- Tests move with ownership: Electron vitest becomes the control-plane suite; `tests/test_launcher_*.py` shrink to Python child/CLI contracts; C# shim tests must not assume `:8765` as the product control plane.
- Packaged desktop still loads `dist/desktop/win-unpacked`. Electron main changes do not take effect until the live `Vibelution.exe` quits and the packaged `app.asar` is rebuilt; Launcher owns that refresh (detached no-console helper after the current shell exits). Python `stop` alone is not enough.
- Dual-writer risk on the packaged product path is closed: Electron main owns window truth and lifecycle commands. Do not reintroduce a renderer `fetch` to `:8765` as a dashboard fallback. Unpackaged checkout HTTP is a test/native-shim leftover, not a second product control plane.

## Related

- `docs/archive/plans/2026-08/CONTROL_PLANE_MIGRATION.md` (historical execution ledger)
- `desktop/electron/README.md`
- `core/web/services/launcher_runtime.md`
- `docs/ops/config/07-launcher-runtime-workbench.md`
- ADR 0003 (operator config still outside the repo)
- ADR 0005 (this decision stays in `docs/adr/`; the dated ledger archives after close)
- `AGENTS.md` §2 Windows no-console red line
