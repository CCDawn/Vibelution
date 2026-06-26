# Electron Launcher Window Provider Test Alignment

日期：2026-06-26
范围：Electron Launcher supervisor migration

## 分类规则

- keep: protects a stable lifecycle invariant.
- update: useful assertion, but tied to Edge-specific fields.
- migrate-remove: protects retired Edge-only behavior.
- add: missing Electron or generic provider contract coverage.

## Initial Scan

Command:

```powershell
rg -n "msedge|--app=|browserManaged|workbench-app-profile|launcher_control_surface|open_workbench|restart_workbench|lifecycle_intent|control-token|runtime_scene" tests web/src desktop -g "*.py" -g "*.ts" -g "*.tsx" -g "*.md"
```

Observed current-state notes:

- `desktop` does not exist before Task 2; Electron coverage must be added rather than migrated from existing files.
- Existing Launcher/Runtime assertions are concentrated in `tests/test_launcher_service.py`, `tests/test_launcher_scripts.py`, `tests/test_web_runtime_routes.py`, `tests/test_runtime_manager.py`, frontend Launcher route tests, and control-token API tests.
- Existing `runtime_scene` coverage is broad; Electron-specific runtime evidence should reuse that surface instead of creating a parallel log store.

## Initial Ledger

| Test file | Current focus | Classification | Required action | Exit condition |
|---|---|---|---|---|
| `tests/test_runtime_manager.py` | Workbench process observation and `browserManaged` state | update | Move assertions to `windowManaged/windowProvider` while keeping compatibility projection checks | Generic provider tests pass for `electron` and Edge compatibility tests pass during migration |
| `tests/test_launcher_service.py` | Launcher status and active-work guard | keep | Keep active-work guard; update window field names only | Active-work start/stop/restart blockers still pass |
| `tests/test_launcher_scripts.py` | PowerShell Edge `--app=` behavior | migrate-remove | Keep only Edge-provider tests under legacy provider section; add Electron provider tests separately | Edge-specific tests no longer block Electron default |
| `tests/test_web_runtime_routes.py` | Launcher API, runtime shutdown, self-evolution cancellation | keep/update | Keep shutdown and active-work behavior; update provider naming | Runtime routes expose generic window provider state |
| `web/src/api/launcher.test.ts` | Launcher endpoint control-token behavior | keep | Keep endpoint and token tests unchanged | Electron shell uses same guarded Launcher endpoints |
| `web/src/app/systemStatus.test.ts` | Managed browser status wording | update | Rename assertions to managed window semantics | UI status reads Electron provider without Edge-specific wording |
| `desktop/electron/tests/desktopPaths.test.ts` | Electron bundle/workspace/userData/resources root separation | add | Validate development and packaged path fixtures without using install dir as workspace | Packaged path tests prove preload and workspace are resolved from different roots |
| `desktop/electron/tests/deepLink.test.ts` | `vibelution://` parsing and Windows path encoding | add | Validate focus/open links without launching children; lifecycle links are rejected in V1 | Invalid or duplicate links become safe typed responses |
| `desktop/electron/tests/launcherProtocol.test.ts` | Machine-readable Launcher command response | add | Assert schema fields and command/status/provider enums | Electron and backend adapter share one response shape |
| `tests/test_web_runtime_routes.py` | Launcher command adapter and active-work guard | add/update | Assert JSON lifecycle responses and blocked active-work states | Runtime commands stay Launcher-gated |
| `desktop/electron/tests/environmentSummary.test.ts` | Config/environment resolution summary | add | Assert external operator config, URL, Python source, and token presence are reported without secrets | Electron does not invent hidden config/env defaults |
| `desktop/electron/tests/desktopActionClient.test.ts` | Desktop Action claim/ack/fail semantics | add | Assert claimed actions are not re-delivered and runtime-effect actions are not executed by Electron | No infinite ACK replay or Node-side runtime commands |
| `desktop/electron/tests/desktopSessionClient.test.ts` | Electron window state writeback | add | Assert window state updates use Desktop Session API with `windowId`, `rendererProcessId`, and revision | Python status projection is lease-backed instead of stale local Electron state |
| `desktop/electron/tests/shutdownCoordinator.test.ts` | Launcher close and active-work guard | add | Assert close is blocked when active work exists and attach mode detaches instead of killing Launcher | Launcher close cannot bypass Python guard |
| `desktop/electron/tests/runtimeSceneBridge.test.ts` | Electron supervisor evidence transport | add | Assert bounded events post to guarded Launcher runtime-scene route and buffer only briefly on failure | Electron lifecycle decisions are diagnosable without full env or prompt logs |
