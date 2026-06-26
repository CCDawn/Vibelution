# Electron Launcher Supervisor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert Vibelution to a single-entry Electron desktop application where the Electron main process acts as the Launcher supervisor, owns lifecycle authority, and manages Workbench, backend, Runtime Manager, self-evolution lifecycle intents, and worker processes as children.

**Architecture:** Vibelution keeps one user-visible entrypoint, one lifecycle source of truth, and multiple managed child processes. Electron replaces the current Edge app window provider, but it must reuse existing Launcher, Runtime Manager, FastAPI, runtime-scene, active-work guard, config, and control-token contracts instead of creating a parallel lifecycle system.

**Tech Stack:** Electron, Node.js, TypeScript, React/Vite `web/dist`, FastAPI backend, Python Runtime Manager, existing `scripts/vibelution_launcher.ps1` / `scripts/vibelution_launcher.py`, existing Launcher API, Vitest, pytest.

## Global Constraints

- Single visible user entrypoint: one packaged `Vibelution` launcher entry, not separate public Launcher and Workbench shortcuts.
- Single lifecycle authority: Launcher supervisor owns start, stop, restart, recover, focus, child process status, and runtime-scene lifecycle evidence.
- Multi-process runtime: Electron main process is the root supervisor; Workbench window, Launcher window, FastAPI backend, Runtime Manager daemon, self-evolution workers, and tool workers are child windows or child processes.
- Workbench cannot start the project directly; it is opened, focused, and closed only through Launcher commands.
- Self-evolution Agent cannot spawn or kill the project directly; it writes structured lifecycle intents that Launcher validates and executes.
- Electron main process must not contain product business logic, LLM calls, file scanning, agent execution, or tool execution; it supervises and delegates.
- Reuse-first rule: reuse current Launcher APIs, Runtime Manager commands, runtime-scene logging, control-token guard, and web build output before adding new paths.
- Architecture/test alignment rule: update old tests that assert `msedge.exe`, `--app=`, `browserManaged`, or Edge profile details so they protect the new window-provider contract instead of the retired implementation.
- Security baseline: renderer Node integration stays disabled; `contextIsolation` stays enabled; preload exposes only narrow lifecycle IPC calls.
- Package manager baseline: use `npm` and lockfiles; Bun remains auxiliary and must not become the release build path.
- Runtime refresh during implementation remains Launcher-gated; do not use ad hoc process killing as the normal validation path.

---

## Confirmed Product Contract

This plan is based on the aligned requirement:

```text
Vibelution.exe
└─ Electron Main Process: Launcher Supervisor
   ├─ Launcher Renderer Window
   ├─ Workbench Renderer Window
   ├─ Python FastAPI Backend
   ├─ Runtime Manager Daemon
   ├─ Self-Evolution Agent Worker(s)
   ├─ Supervised/Coding/Tool Worker(s)
   └─ Lifecycle Intent Queue
```

The product behavior must feel like one app:

- User opens one `Vibelution` entry.
- Launcher control surface appears first.
- User starts or focuses Workbench through Launcher.
- Closing Workbench does not necessarily close Launcher.
- Closing Launcher runs active-work checks before closing managed children.
- Self-evolution can request a restart or resume only by writing a lifecycle intent.
- Launcher records who requested a lifecycle action, why it was accepted or rejected, which process executed it, and what happened.

## Non-Goals For Version 1

- Do not rewrite FastAPI routes into Electron IPC.
- Do not load the Workbench from `file://`; continue loading local HTTP so `/api/*`, control tokens, SSE, and runtime telemetry keep working.
- Do not move LLM invocation, tool execution, Git execution, self-evolution execution, or memory logic into Electron main.
- Do not introduce auto-update, code signing, or installer publishing in the first implementation slice.
- Do not delete the existing Edge provider until Electron reaches parity and tests no longer protect Edge-specific internals.
- Do not convert Runtime Manager into a Node service; keep the Python daemon until a separate migration proves parity.

## Source Authority Model

| Domain | Authority | Notes |
|---|---|---|
| User-visible entry | Electron packaged `Vibelution` entry | Only public shortcut / app entry in version 1. |
| Lifecycle state | Launcher supervisor + existing Launcher state files | Electron main writes through the same contract or an explicitly versioned successor. |
| Runtime commands | Runtime Manager command queue | Launcher submits commands; Runtime Manager executes workbench lifecycle operations. |
| Backend API | FastAPI backend | Electron loads the backend URL and does not replace API routes. |
| UI surface | React/Vite `web/dist` | Existing web app remains the UI implementation. |
| Self-evolution restart intent | Lifecycle intent queue | Agent writes intent; Launcher validates and executes. |
| Evidence | Runtime scene package | Every branch, rejection, child exit, restart, and recovery is diagnosable. |
| Operator config | External config at `C:\Users\17533\Documents\Vibelution\config\config.toml` | Package must not move this source of truth. |

## Proposed File Structure

Create the Electron app as a separate desktop layer so the existing `web/` package stays focused on the browser UI.

```text
desktop/electron/
  package.json
  tsconfig.json
  electron-builder.json
  src/
    main.ts
    appLock.ts
    config.ts
    paths.ts
    ipc.ts
    preload.ts
    process/
      childProcessSupervisor.ts
      managedProcessTypes.ts
      pythonRuntime.ts
      runtimeManagerClient.ts
    lifecycle/
      lifecycleIntentStore.ts
      lifecycleIntentTypes.ts
      lifecyclePolicy.ts
      launcherStateAdapter.ts
      runtimeSceneBridge.ts
    windows/
      launcherWindow.ts
      workbenchWindow.ts
      windowProviderTypes.ts
      electronWindowProvider.ts
  tests/
    appLock.test.ts
    childProcessSupervisor.test.ts
    lifecycleIntentStore.test.ts
    lifecyclePolicy.test.ts
    windowProvider.test.ts
```

Modify existing Python and web layers only where the Electron provider must integrate with existing contracts:

```text
core/runtime_manager/workbench_controller.py
core/runtime_manager/process_inventory.py
core/launcher/service.py
core/web/services/runtime_service.py
core/web/services/self_evolution_control_service.py
core/web/routes/launcher.py
web/src/api/types.ts
web/src/api/launcher.ts
web/src/app/systemStatus.ts
tests/test_runtime_manager.py
tests/test_launcher_service.py
tests/test_web_runtime_routes.py
web/src/api/launcher.test.ts
web/src/app/systemStatus.test.ts
```

Keep compatibility fields during the migration:

```ts
type WorkbenchWindowProvider = "edge_app" | "electron";

type WorkbenchWindowState = {
  windowManaged: boolean;
  windowProvider: WorkbenchWindowProvider;
  windowProcessId: number;
  windowLaunchProcessId: number;
  windowProfileDir: string;
  browserManaged?: boolean; // Compatibility projection during migration.
};
```

## Lifecycle Intent Contract

Self-evolution and other agents may request lifecycle actions only by appending an intent:

```ts
type LifecycleIntent = {
  intentId: string;
  schemaVersion: 1;
  requestedBy: {
    actorType: "self_evolution_agent" | "supervised_agent" | "user" | "system";
    actorId: string;
  };
  action:
    | "open_workbench"
    | "focus_workbench"
    | "restart_after_apply"
    | "resume_self_evolution"
    | "recover_after_crash";
  reason: string;
  sourceRunId?: string;
  sourceTaskId?: string;
  sourceWorktree?: string;
  idempotencyKey: string;
  status: "queued" | "accepted" | "rejected" | "executing" | "succeeded" | "failed" | "superseded";
  createdAt: string;
  updatedAt: string;
  rejectionReason?: string;
  commandId?: string;
  runtimeSceneRef?: string;
};
```

Storage:

```text
.runtime/launcher/lifecycle-intents/intents.jsonl
.runtime/launcher/lifecycle-intents/index.json
```

Rules:

- Intent writes are append-only; `index.json` is a projection.
- Launcher validates active work, worktree review state, apply/rollback safety, and duplicate idempotency keys.
- Accepted intents become Runtime Manager commands.
- Rejected intents stay visible with a safe reason.
- Intent execution records runtime-scene events before and after command submission.

## Window Provider Contract

The current Edge app window should become one provider implementation. Electron becomes another implementation, then the default.

```ts
type WindowProviderCommand =
  | { type: "open_launcher"; url: string }
  | { type: "open_workbench"; url: string }
  | { type: "focus_workbench" }
  | { type: "close_workbench"; reason: string }
  | { type: "close_launcher"; reason: string };

type WindowProviderResult = {
  ok: boolean;
  provider: "edge_app" | "electron";
  launcherWindowPid?: number;
  workbenchWindowPid?: number;
  reason?: string;
};
```

The first Electron implementation can live entirely in the desktop layer, but backend status APIs must expose the generic provider fields.

## Phase Plan

### Task 1: Baseline Inventory And Test Alignment Ledger

**Files:**
- Create: `docs/testing/electron-launcher-window-provider-test-alignment.md`
- Modify: none
- Test: none

**Interfaces:**
- Consumes: current tests that mention `msedge.exe`, `--app=`, `browserManaged`, `workbench-app-profile`, Launcher control ports, Runtime Manager commands.
- Produces: a test classification ledger used by later tasks.

- [ ] **Step 1: Generate the first affected-test list**

Run:

```powershell
rg -n "msedge|--app=|browserManaged|workbench-app-profile|launcher_control_surface|open_workbench|restart_workbench" tests web/src -g "*.py" -g "*.ts" -g "*.tsx"
```

Expected: output includes `tests/test_runtime_manager.py`, `tests/test_launcher_service.py`, `tests/test_launcher_scripts.py`, `tests/test_web_runtime_routes.py`, `web/src/api/launcher.test.ts`, and `web/src/app/systemStatus.test.ts`.

- [ ] **Step 2: Create the ledger**

Create `docs/testing/electron-launcher-window-provider-test-alignment.md` with this structure:

```markdown
# Electron Launcher Window Provider Test Alignment

日期：2026-06-26
范围：Electron Launcher supervisor migration

## 分类规则

- keep: protects a stable lifecycle invariant.
- update: useful assertion, but tied to Edge-specific fields.
- migrate-remove: protects retired Edge-only behavior.
- add: missing Electron or generic provider contract coverage.

## Initial Ledger

| Test file | Current focus | Classification | Required action | Exit condition |
|---|---|---|---|---|
| `tests/test_runtime_manager.py` | Workbench process observation and `browserManaged` state | update | Move assertions to `windowManaged/windowProvider` while keeping compatibility projection checks | Generic provider tests pass for `electron` and Edge compatibility tests pass during migration |
| `tests/test_launcher_service.py` | Launcher status and active-work guard | keep | Keep active-work guard; update window field names only | Active-work start/stop/restart blockers still pass |
| `tests/test_launcher_scripts.py` | PowerShell Edge `--app=` behavior | migrate-remove | Keep only Edge-provider tests under legacy provider section; add Electron provider tests separately | Edge-specific tests no longer block Electron default |
| `tests/test_web_runtime_routes.py` | Launcher API, runtime shutdown, self-evolution cancellation | keep/update | Keep shutdown and active-work behavior; update provider naming | Runtime routes expose generic window provider state |
| `web/src/api/launcher.test.ts` | Launcher endpoint control-token behavior | keep | Keep endpoint and token tests unchanged | Electron shell uses same guarded Launcher endpoints |
| `web/src/app/systemStatus.test.ts` | Managed browser status wording | update | Rename assertions to managed window semantics | UI status reads Electron provider without Edge-specific wording |
```

- [ ] **Step 3: Commit**

```powershell
git add docs/testing/electron-launcher-window-provider-test-alignment.md
git commit -m "docs: align tests for electron launcher migration"
```

### Task 2: Electron Package Scaffold Without Runtime Ownership

**Files:**
- Create: `desktop/electron/package.json`
- Create: `desktop/electron/tsconfig.json`
- Create: `desktop/electron/src/main.ts`
- Create: `desktop/electron/src/preload.ts`
- Create: `desktop/electron/src/paths.ts`
- Create: `desktop/electron/tests/appLock.test.ts`
- Modify: none

**Interfaces:**
- Consumes: existing `web/dist` and existing local HTTP backend URL.
- Produces: a compilable Electron desktop package that can open a static test window but does not start backend processes.

- [ ] **Step 1: Add package metadata**

Create `desktop/electron/package.json`:

```json
{
  "name": "vibelution-desktop",
  "private": true,
  "version": "1.0.16",
  "type": "module",
  "main": "dist/main.js",
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "test": "vitest run",
    "dev": "tsc -p tsconfig.json && electron dist/main.js"
  },
  "dependencies": {
    "electron": "^37.2.0"
  },
  "devDependencies": {
    "@types/node": "^24.0.0",
    "typescript": "^5.9.3",
    "vitest": "^3.2.4"
  }
}
```

- [ ] **Step 2: Add TypeScript config**

Create `desktop/electron/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "strict": true,
    "outDir": "dist",
    "rootDir": ".",
    "types": ["node", "vitest"],
    "skipLibCheck": true
  },
  "include": ["src/**/*.ts", "tests/**/*.ts"]
}
```

- [ ] **Step 3: Add path resolver**

Create `desktop/electron/src/paths.ts`:

```ts
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));

export function resolveProjectRoot(): string {
  return resolve(here, "..", "..", "..");
}

export function resolveRuntimeDir(projectRoot = resolveProjectRoot()): string {
  return resolve(projectRoot, ".runtime", "launcher");
}
```

- [ ] **Step 4: Add minimal preload**

Create `desktop/electron/src/preload.ts`:

```ts
import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("vibelutionLauncher", {
  getVersion: () => ipcRenderer.invoke("launcher:get-version"),
});
```

- [ ] **Step 5: Add minimal main process**

Create `desktop/electron/src/main.ts`:

```ts
import { app, BrowserWindow, ipcMain } from "electron";
import { resolve } from "node:path";
import { resolveProjectRoot } from "./paths.js";

let launcherWindow: BrowserWindow | null = null;

function createLauncherWindow(): BrowserWindow {
  const projectRoot = resolveProjectRoot();
  const window = new BrowserWindow({
    width: 1180,
    height: 760,
    title: "Vibelution Launcher",
    webPreferences: {
      preload: resolve(projectRoot, "desktop", "electron", "dist", "src", "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });
  void window.loadURL("about:blank");
  return window;
}

ipcMain.handle("launcher:get-version", () => app.getVersion());

app.whenReady().then(() => {
  launcherWindow = createLauncherWindow();
  launcherWindow.on("closed", () => {
    launcherWindow = null;
  });
});

app.on("window-all-closed", () => {
  app.quit();
});
```

- [ ] **Step 6: Add a path test**

Create `desktop/electron/tests/appLock.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { resolveRuntimeDir } from "../src/paths.js";

describe("Electron desktop paths", () => {
  it("keeps launcher runtime state under .runtime/launcher", () => {
    expect(resolveRuntimeDir("C:/repo").replace(/\\/g, "/")).toBe("C:/repo/.runtime/launcher");
  });
});
```

- [ ] **Step 7: Verify**

Run:

```powershell
npm --prefix desktop/electron install
npm --prefix desktop/electron run build
npm --prefix desktop/electron test -- --run
```

Expected: TypeScript build passes and the Vitest path test passes.

- [ ] **Step 8: Commit**

```powershell
git add desktop/electron/package.json desktop/electron/package-lock.json desktop/electron/tsconfig.json desktop/electron/src desktop/electron/tests
git commit -m "feat: scaffold electron launcher shell"
```

### Task 3: Single-Instance Launcher Supervisor Lock

**Files:**
- Create: `desktop/electron/src/appLock.ts`
- Modify: `desktop/electron/src/main.ts`
- Test: `desktop/electron/tests/appLock.test.ts`

**Interfaces:**
- Consumes: Electron `app.requestSingleInstanceLock`.
- Produces: single visible entry behavior where second launches focus the existing Launcher instead of spawning another supervisor.

- [ ] **Step 1: Add testable lock decision helper**

Create `desktop/electron/src/appLock.ts`:

```ts
export type SingleInstanceDecision =
  | { action: "continue_as_primary" }
  | { action: "focus_existing"; reason: "secondary_launch" };

export function singleInstanceDecision(hasLock: boolean): SingleInstanceDecision {
  return hasLock ? { action: "continue_as_primary" } : { action: "focus_existing", reason: "secondary_launch" };
}
```

- [ ] **Step 2: Add tests**

Append to `desktop/electron/tests/appLock.test.ts`:

```ts
import { singleInstanceDecision } from "../src/appLock.js";

describe("singleInstanceDecision", () => {
  it("continues as primary when the app owns the lock", () => {
    expect(singleInstanceDecision(true)).toEqual({ action: "continue_as_primary" });
  });

  it("focuses the existing launcher for secondary launches", () => {
    expect(singleInstanceDecision(false)).toEqual({ action: "focus_existing", reason: "secondary_launch" });
  });
});
```

- [ ] **Step 3: Wire main process lock**

Modify `desktop/electron/src/main.ts` so startup begins with:

```ts
import { singleInstanceDecision } from "./appLock.js";

const lockDecision = singleInstanceDecision(app.requestSingleInstanceLock());
if (lockDecision.action === "focus_existing") {
  app.quit();
}

app.on("second-instance", () => {
  if (launcherWindow) {
    if (launcherWindow.isMinimized()) {
      launcherWindow.restore();
    }
    launcherWindow.focus();
  }
});
```

- [ ] **Step 4: Verify**

Run:

```powershell
npm --prefix desktop/electron run build
npm --prefix desktop/electron test -- --run
```

Expected: build passes and `singleInstanceDecision` tests pass.

- [ ] **Step 5: Commit**

```powershell
git add desktop/electron/src/main.ts desktop/electron/src/appLock.ts desktop/electron/tests/appLock.test.ts
git commit -m "feat: enforce single electron launcher instance"
```

### Task 4: Managed Child Process Supervisor

**Files:**
- Create: `desktop/electron/src/process/managedProcessTypes.ts`
- Create: `desktop/electron/src/process/childProcessSupervisor.ts`
- Test: `desktop/electron/tests/childProcessSupervisor.test.ts`

**Interfaces:**
- Consumes: Node child process lifecycle events.
- Produces: reusable state transitions for backend, Runtime Manager, and worker child processes.

- [ ] **Step 1: Add process state types**

Create `desktop/electron/src/process/managedProcessTypes.ts`:

```ts
export type ManagedProcessRole =
  | "fastapi_backend"
  | "runtime_manager"
  | "self_evolution_worker"
  | "tool_worker";

export type ManagedProcessStatus = "idle" | "starting" | "running" | "stopping" | "exited" | "failed";

export type ManagedProcessState = {
  role: ManagedProcessRole;
  status: ManagedProcessStatus;
  pid: number;
  startedAt: string;
  exitedAt: string;
  exitCode: number | null;
  signal: string;
  lastError: string;
};

export function initialManagedProcessState(role: ManagedProcessRole): ManagedProcessState {
  return {
    role,
    status: "idle",
    pid: 0,
    startedAt: "",
    exitedAt: "",
    exitCode: null,
    signal: "",
    lastError: ""
  };
}
```

- [ ] **Step 2: Add transition helpers**

Create `desktop/electron/src/process/childProcessSupervisor.ts`:

```ts
import type { ManagedProcessState } from "./managedProcessTypes.js";

export function markProcessStarting(state: ManagedProcessState, now: string): ManagedProcessState {
  return { ...state, status: "starting", startedAt: now, exitedAt: "", exitCode: null, signal: "", lastError: "" };
}

export function markProcessRunning(state: ManagedProcessState, pid: number): ManagedProcessState {
  return { ...state, status: "running", pid };
}

export function markProcessExited(
  state: ManagedProcessState,
  exitCode: number | null,
  signal: string,
  now: string
): ManagedProcessState {
  return { ...state, status: "exited", pid: 0, exitedAt: now, exitCode, signal };
}

export function markProcessFailed(state: ManagedProcessState, message: string, now: string): ManagedProcessState {
  return { ...state, status: "failed", pid: 0, exitedAt: now, lastError: message };
}
```

- [ ] **Step 3: Add tests**

Create `desktop/electron/tests/childProcessSupervisor.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { initialManagedProcessState } from "../src/process/managedProcessTypes.js";
import { markProcessExited, markProcessFailed, markProcessRunning, markProcessStarting } from "../src/process/childProcessSupervisor.js";

describe("child process supervisor transitions", () => {
  it("records start and running pid", () => {
    const idle = initialManagedProcessState("fastapi_backend");
    const starting = markProcessStarting(idle, "2026-06-26T00:00:00.000Z");
    const running = markProcessRunning(starting, 1234);
    expect(running).toMatchObject({
      role: "fastapi_backend",
      status: "running",
      pid: 1234,
      startedAt: "2026-06-26T00:00:00.000Z"
    });
  });

  it("clears pid and records exit evidence", () => {
    const running = markProcessRunning(markProcessStarting(initialManagedProcessState("runtime_manager"), "start"), 2222);
    const exited = markProcessExited(running, 0, "", "end");
    expect(exited).toMatchObject({ status: "exited", pid: 0, exitCode: 0, exitedAt: "end" });
  });

  it("records failure reason", () => {
    const failed = markProcessFailed(initialManagedProcessState("tool_worker"), "spawn failed", "now");
    expect(failed).toMatchObject({ status: "failed", lastError: "spawn failed", exitedAt: "now" });
  });
});
```

- [ ] **Step 4: Verify**

Run:

```powershell
npm --prefix desktop/electron run build
npm --prefix desktop/electron test -- --run
```

Expected: all Electron unit tests pass.

- [ ] **Step 5: Commit**

```powershell
git add desktop/electron/src/process desktop/electron/tests/childProcessSupervisor.test.ts
git commit -m "feat: add electron child process supervisor state"
```

### Task 5: Generic Window Provider State In Backend

**Files:**
- Modify: `core/runtime_manager/workbench_controller.py`
- Modify: `core/launcher/service.py`
- Modify: `core/web/services/runtime_service.py`
- Modify: `web/src/api/types.ts`
- Test: `tests/test_runtime_manager.py`
- Test: `tests/test_launcher_service.py`
- Test: `tests/test_web_runtime_routes.py`

**Interfaces:**
- Consumes: current `browserManaged`, `browserWindowPid`, `browserProfileDir` fields.
- Produces: generic `windowManaged`, `windowProvider`, `windowProcessId`, `windowProfileDir` fields while preserving compatibility projections.

- [ ] **Step 1: Write failing backend tests**

Add assertions to focused tests so status payloads include:

```python
assert payload["workbench"]["windowManaged"] is True
assert payload["workbench"]["windowProvider"] in {"edge_app", "electron"}
assert payload["workbench"]["browserManaged"] is payload["workbench"]["windowManaged"]
```

Run:

```powershell
$env:TEMP="$PWD\\.tmp\\pytest-temp"; $env:TMP="$PWD\\.tmp\\pytest-temp"; pytest tests/test_runtime_manager.py tests/test_launcher_service.py tests/test_web_runtime_routes.py -k "launcher or workbench or browserManaged" -q --basetemp "$PWD\\.tmp\\pytest-basetemp"
```

Expected: failing assertions for missing generic window fields.

- [ ] **Step 2: Implement compatibility projection**

Update Python payload builders so existing state produces:

```python
window_provider = str(workbench.get("windowProvider") or "edge_app")
window_managed = bool(workbench.get("windowManaged", workbench.get("browserManaged", True)))
window_process_id = int(workbench.get("windowProcessId") or workbench.get("browserWindowPid") or 0)
window_profile_dir = str(workbench.get("windowProfileDir") or workbench.get("browserProfileDir") or "")
```

Return both generic and compatibility fields during migration:

```python
"windowProvider": window_provider,
"windowManaged": window_managed,
"windowProcessId": window_process_id,
"windowProfileDir": window_profile_dir,
"browserManaged": window_managed,
"browserWindowPid": window_process_id,
"browserProfileDir": window_profile_dir,
```

- [ ] **Step 3: Update TypeScript API types**

Extend the workbench state types in `web/src/api/types.ts` with:

```ts
windowManaged: boolean;
windowProvider: "edge_app" | "electron" | string;
windowProcessId: number;
windowProfileDir: string;
```

Keep `browserManaged` as an optional compatibility projection until Edge-specific UI tests are migrated.

- [ ] **Step 4: Verify**

Run:

```powershell
$env:TEMP="$PWD\\.tmp\\pytest-temp"; $env:TMP="$PWD\\.tmp\\pytest-temp"; pytest tests/test_runtime_manager.py tests/test_launcher_service.py tests/test_web_runtime_routes.py -k "launcher or workbench or browserManaged" -q --basetemp "$PWD\\.tmp\\pytest-basetemp"
npm --prefix web test -- src/app/systemStatus.test.ts src/api/launcher.test.ts --run
npm --prefix web run build
```

Expected: focused pytest passes, focused web tests pass, web build passes.

- [ ] **Step 5: Commit**

```powershell
git add core/runtime_manager/workbench_controller.py core/launcher/service.py core/web/services/runtime_service.py web/src/api/types.ts tests/test_runtime_manager.py tests/test_launcher_service.py tests/test_web_runtime_routes.py
git commit -m "feat: expose generic workbench window provider state"
```

### Task 6: Electron Window Provider

**Files:**
- Create: `desktop/electron/src/windows/windowProviderTypes.ts`
- Create: `desktop/electron/src/windows/electronWindowProvider.ts`
- Create: `desktop/electron/src/windows/launcherWindow.ts`
- Create: `desktop/electron/src/windows/workbenchWindow.ts`
- Modify: `desktop/electron/src/main.ts`
- Test: `desktop/electron/tests/windowProvider.test.ts`

**Interfaces:**
- Consumes: local Launcher URL and Workbench URL.
- Produces: Launcher and Workbench BrowserWindows controlled by Electron main process.

- [ ] **Step 1: Add provider types**

Create `desktop/electron/src/windows/windowProviderTypes.ts`:

```ts
export type ElectronWindowRole = "launcher" | "workbench";

export type ManagedWindowState = {
  role: ElectronWindowRole;
  provider: "electron";
  open: boolean;
  focused: boolean;
  processId: number;
  url: string;
};

export function closedWindowState(role: ElectronWindowRole): ManagedWindowState {
  return { role, provider: "electron", open: false, focused: false, processId: 0, url: "" };
}
```

- [ ] **Step 2: Add state tests**

Create `desktop/electron/tests/windowProvider.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { closedWindowState } from "../src/windows/windowProviderTypes.js";

describe("Electron window provider state", () => {
  it("uses electron as the provider authority", () => {
    expect(closedWindowState("workbench")).toEqual({
      role: "workbench",
      provider: "electron",
      open: false,
      focused: false,
      processId: 0,
      url: ""
    });
  });
});
```

- [ ] **Step 3: Implement Launcher window factory**

Create `desktop/electron/src/windows/launcherWindow.ts`:

```ts
import { BrowserWindow } from "electron";
import { resolve } from "node:path";
import { resolveProjectRoot } from "../paths.js";

export function createLauncherWindow(url: string): BrowserWindow {
  const projectRoot = resolveProjectRoot();
  const window = new BrowserWindow({
    width: 1180,
    height: 760,
    title: "Vibelution Launcher",
    webPreferences: {
      preload: resolve(projectRoot, "desktop", "electron", "dist", "src", "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });
  void window.loadURL(url);
  return window;
}
```

- [ ] **Step 4: Implement Workbench window factory**

Create `desktop/electron/src/windows/workbenchWindow.ts`:

```ts
import { BrowserWindow } from "electron";
import { resolve } from "node:path";
import { resolveProjectRoot } from "../paths.js";

export function createWorkbenchWindow(url: string): BrowserWindow {
  const projectRoot = resolveProjectRoot();
  const window = new BrowserWindow({
    width: 1440,
    height: 960,
    title: "Vibelution Workbench",
    webPreferences: {
      preload: resolve(projectRoot, "desktop", "electron", "dist", "src", "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });
  void window.loadURL(url);
  return window;
}
```

- [ ] **Step 5: Wire provider into main process**

Update `desktop/electron/src/main.ts` to open the Launcher URL first:

```ts
const DEFAULT_LAUNCHER_URL = process.env.VIBELUTION_LAUNCHER_URL || "http://127.0.0.1:8765/launcher";
```

Use `createLauncherWindow(DEFAULT_LAUNCHER_URL)` instead of loading `about:blank`.

- [ ] **Step 6: Verify**

Run:

```powershell
npm --prefix desktop/electron run build
npm --prefix desktop/electron test -- --run
```

Expected: Electron package builds and window provider tests pass.

- [ ] **Step 7: Commit**

```powershell
git add desktop/electron/src/windows desktop/electron/src/main.ts desktop/electron/tests/windowProvider.test.ts
git commit -m "feat: add electron window provider"
```

### Task 7: Launcher-Controlled Backend And Runtime Manager Startup

**Files:**
- Create: `desktop/electron/src/process/pythonRuntime.ts`
- Create: `desktop/electron/src/process/runtimeManagerClient.ts`
- Modify: `desktop/electron/src/main.ts`
- Test: `desktop/electron/tests/childProcessSupervisor.test.ts`

**Interfaces:**
- Consumes: existing Python runtime paths, existing `scripts/vibelution_launcher.py` or Runtime Manager command API.
- Produces: Electron main can start the existing Launcher/Runtime Manager path without introducing a parallel backend startup contract.

- [ ] **Step 1: Add Python runtime resolver**

Create `desktop/electron/src/process/pythonRuntime.ts`:

```ts
import { existsSync } from "node:fs";
import { resolve } from "node:path";

export type PythonRuntimeResolution = {
  pythonPath: string;
  source: "env" | "project_venv";
};

export function resolvePythonRuntime(projectRoot: string, env = process.env): PythonRuntimeResolution {
  const override = String(env.VIBELUTION_PYTHON_EXE || "").trim();
  if (override) {
    return { pythonPath: override, source: "env" };
  }
  const candidate = resolve(projectRoot, ".venv", "Scripts", "python.exe");
  if (existsSync(candidate)) {
    return { pythonPath: candidate, source: "project_venv" };
  }
  return { pythonPath: "python", source: "env" };
}
```

- [ ] **Step 2: Add tests for resolver**

Append to `desktop/electron/tests/childProcessSupervisor.test.ts`:

```ts
import { resolvePythonRuntime } from "../src/process/pythonRuntime.js";

describe("resolvePythonRuntime", () => {
  it("prefers VIBELUTION_PYTHON_EXE", () => {
    expect(resolvePythonRuntime("C:/repo", { VIBELUTION_PYTHON_EXE: "C:/Python/python.exe" } as NodeJS.ProcessEnv)).toEqual({
      pythonPath: "C:/Python/python.exe",
      source: "env"
    });
  });
});
```

- [ ] **Step 3: Add Runtime Manager launcher client**

Create `desktop/electron/src/process/runtimeManagerClient.ts`:

```ts
import { spawn } from "node:child_process";
import { resolve } from "node:path";

export type LauncherAdapterCommand = "launcher" | "start" | "stop" | "restart" | "status";

export function spawnPythonLauncherAdapter(projectRoot: string, pythonPath: string, action: LauncherAdapterCommand) {
  return spawn(
    pythonPath,
    [resolve(projectRoot, "scripts", "vibelution_launcher.py"), "--action", action, "--no-browser"],
    {
      cwd: projectRoot,
      windowsHide: true,
      stdio: "pipe"
    }
  );
}
```

- [ ] **Step 4: Wire startup through adapter**

Update Electron main so first startup calls the existing launcher adapter with `launcher`, then loads Launcher window. Keep this behind an environment switch during the first implementation:

```ts
const shouldStartLauncher = process.env.VIBELUTION_ELECTRON_START_LAUNCHER !== "0";
```

This prevents local developer runs from spawning runtime processes while unit tests compile the package.

- [ ] **Step 5: Verify**

Run:

```powershell
npm --prefix desktop/electron run build
npm --prefix desktop/electron test -- --run
python scripts/vibelution_launcher.py --action status --no-browser
```

Expected: Electron build/tests pass and the existing Python launcher adapter still reports status.

- [ ] **Step 6: Commit**

```powershell
git add desktop/electron/src/process desktop/electron/src/main.ts desktop/electron/tests/childProcessSupervisor.test.ts
git commit -m "feat: let electron supervisor reuse launcher adapter"
```

### Task 8: Lifecycle Intent Store

**Files:**
- Create: `desktop/electron/src/lifecycle/lifecycleIntentTypes.ts`
- Create: `desktop/electron/src/lifecycle/lifecycleIntentStore.ts`
- Create: `desktop/electron/src/lifecycle/lifecyclePolicy.ts`
- Test: `desktop/electron/tests/lifecycleIntentStore.test.ts`

**Interfaces:**
- Consumes: self-evolution run IDs, source task IDs, idempotency keys.
- Produces: append-only lifecycle intent records and policy decisions.

- [ ] **Step 1: Add intent types**

Create `desktop/electron/src/lifecycle/lifecycleIntentTypes.ts`:

```ts
export type LifecycleIntentAction =
  | "open_workbench"
  | "focus_workbench"
  | "restart_after_apply"
  | "resume_self_evolution"
  | "recover_after_crash";

export type LifecycleIntentStatus = "queued" | "accepted" | "rejected" | "executing" | "succeeded" | "failed" | "superseded";

export type LifecycleIntent = {
  intentId: string;
  schemaVersion: 1;
  requestedBy: {
    actorType: "self_evolution_agent" | "supervised_agent" | "user" | "system";
    actorId: string;
  };
  action: LifecycleIntentAction;
  reason: string;
  sourceRunId: string;
  sourceTaskId: string;
  sourceWorktree: string;
  idempotencyKey: string;
  status: LifecycleIntentStatus;
  createdAt: string;
  updatedAt: string;
  rejectionReason: string;
  commandId: string;
  runtimeSceneRef: string;
};
```

- [ ] **Step 2: Add policy helper**

Create `desktop/electron/src/lifecycle/lifecyclePolicy.ts`:

```ts
import type { LifecycleIntent } from "./lifecycleIntentTypes.js";

export type LifecyclePolicyInput = {
  activeWorkCount: number;
  selfEvolutionRunActive: boolean;
  applyWindowOpen: boolean;
};

export type LifecyclePolicyDecision =
  | { accepted: true; reason: "allowed" }
  | { accepted: false; reason: "active_work_running" | "self_evolution_already_active" | "apply_window_closed" };

export function decideLifecycleIntent(intent: LifecycleIntent, input: LifecyclePolicyInput): LifecyclePolicyDecision {
  if (input.activeWorkCount > 0 && intent.action !== "focus_workbench") {
    return { accepted: false, reason: "active_work_running" };
  }
  if (intent.action === "resume_self_evolution" && input.selfEvolutionRunActive) {
    return { accepted: false, reason: "self_evolution_already_active" };
  }
  if (intent.action === "restart_after_apply" && !input.applyWindowOpen) {
    return { accepted: false, reason: "apply_window_closed" };
  }
  return { accepted: true, reason: "allowed" };
}
```

- [ ] **Step 3: Add policy tests**

Create `desktop/electron/tests/lifecycleIntentStore.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import type { LifecycleIntent } from "../src/lifecycle/lifecycleIntentTypes.js";
import { decideLifecycleIntent } from "../src/lifecycle/lifecyclePolicy.js";

const baseIntent: LifecycleIntent = {
  intentId: "intent-1",
  schemaVersion: 1,
  requestedBy: { actorType: "self_evolution_agent", actorId: "self-agent" },
  action: "restart_after_apply",
  reason: "apply completed",
  sourceRunId: "self-run-1",
  sourceTaskId: "task-1",
  sourceWorktree: "C:/worktree",
  idempotencyKey: "self-run-1:restart",
  status: "queued",
  createdAt: "2026-06-26T00:00:00.000Z",
  updatedAt: "2026-06-26T00:00:00.000Z",
  rejectionReason: "",
  commandId: "",
  runtimeSceneRef: ""
};

describe("decideLifecycleIntent", () => {
  it("blocks restart while active work is running", () => {
    expect(decideLifecycleIntent(baseIntent, { activeWorkCount: 1, selfEvolutionRunActive: false, applyWindowOpen: true })).toEqual({
      accepted: false,
      reason: "active_work_running"
    });
  });

  it("allows restart after apply when guards pass", () => {
    expect(decideLifecycleIntent(baseIntent, { activeWorkCount: 0, selfEvolutionRunActive: false, applyWindowOpen: true })).toEqual({
      accepted: true,
      reason: "allowed"
    });
  });
});
```

- [ ] **Step 4: Implement append-only store**

Create `desktop/electron/src/lifecycle/lifecycleIntentStore.ts`:

```ts
import { mkdirSync, appendFileSync, readFileSync, existsSync } from "node:fs";
import { dirname } from "node:path";
import type { LifecycleIntent } from "./lifecycleIntentTypes.js";

export function appendLifecycleIntent(path: string, intent: LifecycleIntent): void {
  mkdirSync(dirname(path), { recursive: true });
  appendFileSync(path, `${JSON.stringify(intent)}\n`, { encoding: "utf8" });
}

export function readLifecycleIntents(path: string): LifecycleIntent[] {
  if (!existsSync(path)) {
    return [];
  }
  return readFileSync(path, "utf8")
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => JSON.parse(line) as LifecycleIntent);
}
```

- [ ] **Step 5: Add store tests**

Append to `desktop/electron/tests/lifecycleIntentStore.test.ts`:

```ts
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { appendLifecycleIntent, readLifecycleIntents } from "../src/lifecycle/lifecycleIntentStore.js";

describe("lifecycle intent store", () => {
  it("appends and reads intents as jsonl", () => {
    const path = join(mkdtempSync(join(tmpdir(), "vibelution-intents-")), "intents.jsonl");
    appendLifecycleIntent(path, baseIntent);
    expect(readLifecycleIntents(path)).toEqual([baseIntent]);
  });
});
```

- [ ] **Step 6: Verify**

Run:

```powershell
npm --prefix desktop/electron run build
npm --prefix desktop/electron test -- --run
```

Expected: intent policy and store tests pass.

- [ ] **Step 7: Commit**

```powershell
git add desktop/electron/src/lifecycle desktop/electron/tests/lifecycleIntentStore.test.ts
git commit -m "feat: add launcher lifecycle intent queue"
```

### Task 9: Self-Evolution Lifecycle Intent Integration

**Files:**
- Modify: `core/web/services/self_evolution_control_service.py`
- Modify: `core/web/routes/launcher.py`
- Modify: `tests/test_web_runtime_routes.py`
- Test: `tests/test_web_runtime_routes.py`

**Interfaces:**
- Consumes: existing self-evolution run state and runtime-scene logging.
- Produces: structured lifecycle intents instead of direct process actions from self-evolution.

- [ ] **Step 1: Write failing route/service tests**

Add a test to `tests/test_web_runtime_routes.py`:

```python
def test_self_evolution_restart_request_writes_lifecycle_intent(tmp_path, monkeypatch):
    intents_path = tmp_path / ".runtime" / "launcher" / "lifecycle-intents" / "intents.jsonl"
    monkeypatch.setattr(self_evolution_control_service, "LIFECYCLE_INTENTS_PATH", intents_path)

    result = self_evolution_control_service.request_lifecycle_intent(
        {
            "requestedBy": {"actorType": "self_evolution_agent", "actorId": "self-agent"},
            "action": "restart_after_apply",
            "reason": "apply completed",
            "sourceRunId": "self-run-1",
            "sourceTaskId": "task-1",
            "sourceWorktree": str(tmp_path / "worktree"),
            "idempotencyKey": "self-run-1:restart",
        }
    )

    assert result["status"] == "queued"
    assert intents_path.exists()
    assert "restart_after_apply" in intents_path.read_text(encoding="utf-8")
```

Run:

```powershell
$env:TEMP="$PWD\\.tmp\\pytest-temp"; $env:TMP="$PWD\\.tmp\\pytest-temp"; pytest tests/test_web_runtime_routes.py -k "self_evolution_restart_request_writes_lifecycle_intent" -q --basetemp "$PWD\\.tmp\\pytest-basetemp"
```

Expected: failure because `request_lifecycle_intent` is not implemented.

- [ ] **Step 2: Implement service function**

Add to `core/web/services/self_evolution_control_service.py`:

```python
LIFECYCLE_INTENTS_PATH = PROJECT_ROOT / ".runtime" / "launcher" / "lifecycle-intents" / "intents.jsonl"


def request_lifecycle_intent(payload: dict[str, Any]) -> dict[str, Any]:
    now = _now_timestamp()
    intent = {
        "intentId": f"intent-{uuid4().hex}",
        "schemaVersion": 1,
        "requestedBy": payload.get("requestedBy") or {},
        "action": str(payload.get("action") or ""),
        "reason": str(payload.get("reason") or ""),
        "sourceRunId": str(payload.get("sourceRunId") or ""),
        "sourceTaskId": str(payload.get("sourceTaskId") or ""),
        "sourceWorktree": str(payload.get("sourceWorktree") or ""),
        "idempotencyKey": str(payload.get("idempotencyKey") or ""),
        "status": "queued",
        "createdAt": now,
        "updatedAt": now,
        "rejectionReason": "",
        "commandId": "",
        "runtimeSceneRef": "",
    }
    LIFECYCLE_INTENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LIFECYCLE_INTENTS_PATH.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(intent, ensure_ascii=False) + "\n")
    _record_self_scene_event(
        "lifecycle_intent",
        "self_evolution.lifecycle_intent.queued",
        run_id=intent["sourceRunId"],
        message="Self-evolution lifecycle intent queued.",
        outcome="started",
        fields={
            "intentId": intent["intentId"],
            "action": intent["action"],
            "sourceTaskId": intent["sourceTaskId"],
            "idempotencyKey": intent["idempotencyKey"],
        },
        lifecycle=True,
    )
    return intent
```

- [ ] **Step 3: Verify**

Run:

```powershell
$env:TEMP="$PWD\\.tmp\\pytest-temp"; $env:TMP="$PWD\\.tmp\\pytest-temp"; pytest tests/test_web_runtime_routes.py -k "self_evolution_restart_request_writes_lifecycle_intent or self_evolution_control_paths_record_child_log" -q --basetemp "$PWD\\.tmp\\pytest-basetemp"
```

Expected: lifecycle intent test passes and existing self-evolution runtime-scene child log test still passes.

- [ ] **Step 4: Commit**

```powershell
git add core/web/services/self_evolution_control_service.py tests/test_web_runtime_routes.py
git commit -m "feat: queue self-evolution lifecycle intents"
```

### Task 10: Launcher Executes Accepted Lifecycle Intents

**Files:**
- Modify: `desktop/electron/src/lifecycle/lifecycleIntentStore.ts`
- Modify: `desktop/electron/src/lifecycle/lifecyclePolicy.ts`
- Modify: `desktop/electron/src/process/runtimeManagerClient.ts`
- Modify: `desktop/electron/src/main.ts`
- Test: `desktop/electron/tests/lifecycleIntentStore.test.ts`

**Interfaces:**
- Consumes: queued lifecycle intents and active-work status.
- Produces: accepted intents become existing Launcher/Runtime Manager commands.

- [ ] **Step 1: Add command mapping tests**

Append to `desktop/electron/tests/lifecycleIntentStore.test.ts`:

```ts
import { runtimeCommandForIntent } from "../src/process/runtimeManagerClient.js";

describe("runtimeCommandForIntent", () => {
  it("maps restart_after_apply to restart", () => {
    expect(runtimeCommandForIntent("restart_after_apply")).toBe("restart");
  });

  it("maps focus_workbench to launcher", () => {
    expect(runtimeCommandForIntent("focus_workbench")).toBe("launcher");
  });
});
```

- [ ] **Step 2: Implement command mapping**

Update `desktop/electron/src/process/runtimeManagerClient.ts`:

```ts
import type { LifecycleIntentAction } from "../lifecycle/lifecycleIntentTypes.js";

export function runtimeCommandForIntent(action: LifecycleIntentAction): LauncherAdapterCommand {
  if (action === "restart_after_apply" || action === "recover_after_crash") {
    return "restart";
  }
  if (action === "open_workbench" || action === "resume_self_evolution") {
    return "start";
  }
  if (action === "focus_workbench") {
    return "launcher";
  }
  return "status";
}
```

- [ ] **Step 3: Add polling loop in Electron main**

In `desktop/electron/src/main.ts`, add a timer that:

1. reads queued intents;
2. applies `decideLifecycleIntent`;
3. records accepted or rejected status;
4. maps accepted actions to existing Launcher adapter commands;
5. spawns the command through `spawnPythonLauncherAdapter`;
6. records command ID and child exit result.

Keep the polling interval conservative in version 1:

```ts
const LIFECYCLE_INTENT_POLL_MS = 2000;
```

- [ ] **Step 4: Verify**

Run:

```powershell
npm --prefix desktop/electron run build
npm --prefix desktop/electron test -- --run
```

Expected: command mapping tests pass; build remains strict.

- [ ] **Step 5: Commit**

```powershell
git add desktop/electron/src/lifecycle desktop/electron/src/process/runtimeManagerClient.ts desktop/electron/src/main.ts desktop/electron/tests/lifecycleIntentStore.test.ts
git commit -m "feat: execute lifecycle intents through launcher supervisor"
```

### Task 11: Security And IPC Boundary

**Files:**
- Modify: `desktop/electron/src/preload.ts`
- Create: `desktop/electron/src/ipc.ts`
- Test: `desktop/electron/tests/windowProvider.test.ts`

**Interfaces:**
- Consumes: Electron IPC.
- Produces: narrow renderer-to-main bridge for lifecycle status and window focus only.

- [ ] **Step 1: Add IPC channel constants**

Create `desktop/electron/src/ipc.ts`:

```ts
export const IPC_CHANNELS = {
  getVersion: "launcher:get-version",
  getLifecycleSummary: "launcher:get-lifecycle-summary",
  focusWorkbench: "launcher:focus-workbench"
} as const;

export type IpcChannel = (typeof IPC_CHANNELS)[keyof typeof IPC_CHANNELS];
```

- [ ] **Step 2: Update preload to expose only narrow methods**

Modify `desktop/electron/src/preload.ts`:

```ts
import { contextBridge, ipcRenderer } from "electron";
import { IPC_CHANNELS } from "./ipc.js";

contextBridge.exposeInMainWorld("vibelutionLauncher", {
  getVersion: () => ipcRenderer.invoke(IPC_CHANNELS.getVersion),
  getLifecycleSummary: () => ipcRenderer.invoke(IPC_CHANNELS.getLifecycleSummary),
  focusWorkbench: () => ipcRenderer.invoke(IPC_CHANNELS.focusWorkbench)
});
```

- [ ] **Step 3: Add channel test**

Append to `desktop/electron/tests/windowProvider.test.ts`:

```ts
import { IPC_CHANNELS } from "../src/ipc.js";

describe("IPC channels", () => {
  it("keeps the bridge narrow", () => {
    expect(Object.keys(IPC_CHANNELS).sort()).toEqual(["focusWorkbench", "getLifecycleSummary", "getVersion"]);
  });
});
```

- [ ] **Step 4: Verify**

Run:

```powershell
npm --prefix desktop/electron run build
npm --prefix desktop/electron test -- --run
```

Expected: bridge test passes and no Node APIs are exposed to renderer.

- [ ] **Step 5: Commit**

```powershell
git add desktop/electron/src/preload.ts desktop/electron/src/ipc.ts desktop/electron/tests/windowProvider.test.ts
git commit -m "feat: constrain electron launcher ipc bridge"
```

### Task 12: Packaging Skeleton

**Files:**
- Create: `desktop/electron/electron-builder.json`
- Modify: `desktop/electron/package.json`
- Create: `scripts/build_desktop_package.ps1`
- Test: no installer test in version 1; build smoke only

**Interfaces:**
- Consumes: `web/dist`, Python runtime, existing project files.
- Produces: a local packaged Electron application skeleton.

- [ ] **Step 1: Add builder config**

Create `desktop/electron/electron-builder.json`:

```json
{
  "appId": "com.vibelution.desktop",
  "productName": "Vibelution",
  "directories": {
    "output": "../../dist/desktop"
  },
  "files": [
    "dist/**/*",
    "package.json"
  ],
  "extraResources": [
    { "from": "../../web/dist", "to": "web/dist" },
    { "from": "../../scripts", "to": "scripts" },
    { "from": "../../core", "to": "core" },
    { "from": "../../requirements.txt", "to": "requirements.txt" }
  ],
  "win": {
    "target": ["dir"],
    "artifactName": "Vibelution-${version}-${arch}.${ext}"
  }
}
```

- [ ] **Step 2: Add package script**

Modify `desktop/electron/package.json` scripts:

```json
"package:dir": "npm run build && electron-builder --config electron-builder.json --dir"
```

Add dependency:

```json
"electron-builder": "^26.0.0"
```

- [ ] **Step 3: Add local build wrapper**

Create `scripts/build_desktop_package.ps1`:

```powershell
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
npm --prefix (Join-Path $projectDir "web") run build
npm --prefix (Join-Path $projectDir "desktop/electron") install
npm --prefix (Join-Path $projectDir "desktop/electron") run package:dir
```

- [ ] **Step 4: Verify**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_desktop_package.ps1
```

Expected: `dist/desktop/win-unpacked` or equivalent directory target is produced.

- [ ] **Step 5: Commit**

```powershell
git add desktop/electron/electron-builder.json desktop/electron/package.json desktop/electron/package-lock.json scripts/build_desktop_package.ps1
git commit -m "build: add electron desktop package skeleton"
```

### Task 13: Runtime Scene Evidence For Electron Supervisor

**Files:**
- Create: `desktop/electron/src/lifecycle/runtimeSceneBridge.ts`
- Modify: `core/web/services/runtime_scene_service.py`
- Modify: `tests/test_web_runtime_routes.py`
- Test: `tests/test_web_runtime_routes.py`

**Interfaces:**
- Consumes: existing runtime-scene package structure.
- Produces: bounded evidence for Electron supervisor lifecycle decisions.

- [ ] **Step 1: Define event names**

Use these event codes:

```text
electron.launcher.supervisor.started
electron.launcher.window.opened
electron.workbench.window.opened
electron.child_process.started
electron.child_process.exited
electron.lifecycle_intent.accepted
electron.lifecycle_intent.rejected
electron.lifecycle_intent.executed
```

- [ ] **Step 2: Add backend helper test**

In `tests/test_web_runtime_routes.py`, add a runtime scene test that writes an Electron supervisor event and verifies it appears in `timeline.jsonl` and a bounded event file.

- [ ] **Step 3: Add Electron bridge**

Create `desktop/electron/src/lifecycle/runtimeSceneBridge.ts`:

```ts
export type RuntimeSceneElectronEvent = {
  eventCode: string;
  message: string;
  fields: Record<string, string | number | boolean>;
};

export function electronEventPayload(event: RuntimeSceneElectronEvent) {
  return {
    component: "electron_launcher",
    phase: "desktop_supervisor",
    event_code: event.eventCode,
    message: event.message,
    fields: event.fields
  };
}
```

- [ ] **Step 4: Verify**

Run:

```powershell
npm --prefix desktop/electron run build
npm --prefix desktop/electron test -- --run
$env:TEMP="$PWD\\.tmp\\pytest-temp"; $env:TMP="$PWD\\.tmp\\pytest-temp"; pytest tests/test_web_runtime_routes.py -k "runtime_scene" -q --basetemp "$PWD\\.tmp\\pytest-basetemp"
```

Expected: Electron payload tests and runtime scene tests pass.

- [ ] **Step 5: Commit**

```powershell
git add desktop/electron/src/lifecycle/runtimeSceneBridge.ts core/web/services/runtime_scene_service.py tests/test_web_runtime_routes.py
git commit -m "feat: record electron launcher supervisor evidence"
```

## Migration Gates

### Gate 1: Electron Scaffold Ready

Evidence required:

```powershell
npm --prefix desktop/electron run build
npm --prefix desktop/electron test -- --run
```

Pass condition:

- Electron package compiles.
- Single-instance lock tests pass.
- No runtime process is spawned during tests.

### Gate 2: Generic Window Provider Ready

Evidence required:

```powershell
pytest tests/test_runtime_manager.py tests/test_launcher_service.py tests/test_web_runtime_routes.py -k "launcher or workbench or browserManaged" -q
npm --prefix web test -- src/app/systemStatus.test.ts src/api/launcher.test.ts --run
npm --prefix web run build
```

Pass condition:

- Status APIs expose `windowProvider` and `windowManaged`.
- Compatibility `browserManaged` field remains stable during migration.
- UI status no longer depends on Edge-specific language.

### Gate 3: Electron Provider Can Open Launcher And Workbench

Evidence required:

```powershell
npm --prefix web run build
npm --prefix desktop/electron run build
npm --prefix desktop/electron run dev
```

Manual check:

- One visible Vibelution entry starts.
- Launcher window appears first.
- Workbench opens only from Launcher.
- Closing Workbench leaves Launcher alive.
- Closing Launcher runs active-work guard.

### Gate 4: Self-Evolution Intent Loop Ready

Evidence required:

```powershell
pytest tests/test_web_runtime_routes.py -k "self_evolution and lifecycle_intent" -q
npm --prefix desktop/electron test -- --run
```

Pass condition:

- Self-evolution restart request writes a queued intent.
- Launcher accepts or rejects the intent with a safe reason.
- Accepted intent maps to existing Runtime Manager / Launcher commands.
- Runtime-scene evidence records request, decision, command, and outcome.

### Gate 5: Packaging Skeleton Ready

Evidence required:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_desktop_package.ps1
```

Pass condition:

- Local unpacked desktop package is produced.
- Package uses one visible product entry.
- Workbench has no independent public shortcut.

## Old Test Alignment Rules

During implementation, old tests must be classified before being changed:

| Old assertion | Treatment |
|---|---|
| `msedge.exe` process exists | update to provider-specific Edge compatibility test or migrate-remove after Electron default is stable |
| `--app=http://...` exists | update to Edge-provider-only test |
| `browserManaged is True` | update to `windowManaged is True`, keep `browserManaged` compatibility projection temporarily |
| `workbench-app-profile` exists | update to `windowProfileDir` generic field |
| Launcher start/stop/restart active-work blockers | keep |
| control-token and `/api/launcher/*` guarded endpoints | keep |
| direct `uvicorn` or direct browser launch as normal lifecycle path | reject as anti-pattern |

No implementation step may claim correctness only because old tests pass. The new provider, intent, and supervisor contract tests must be present.

## Rollback Strategy

Version 1 must support fallback:

- Keep the Edge provider behind `windowProvider=edge_app`.
- Keep PowerShell and Python launcher adapters working.
- Keep `browserManaged` compatibility fields while frontend and tests migrate.
- Keep Electron startup behind a feature flag until Gate 3 passes.
- If Electron startup fails, Launcher status must report `windowProvider=electron`, `phase=failed`, and a safe `failureMessage`.
- The user can still start the current Launcher path during the migration until the Electron path is selected as default.

## Logging Decision

New logs are required because this plan changes lifecycle, process supervision, self-evolution restart behavior, packaging, and window management.

Log through existing runtime-scene helpers or bounded Electron bridge payloads:

- supervisor startup and shutdown;
- child process start/exit/failure;
- window open/focus/close;
- lifecycle intent queued/accepted/rejected/executed;
- Runtime Manager command submission and result;
- Electron provider fallback or failure.

Do not log:

- full prompts;
- secrets;
- full environment variables;
- unbounded stdout/stderr;
- full file contents.

## Version Impact

This migration is user-visible and packaging-visible.

Recommended version treatment:

- Planning document only: no version bump.
- Electron scaffold behind non-default path: patch-level or no release bump until user-facing.
- Electron becomes default entrypoint: minor version, because packaging and startup behavior change.
- Removing Edge compatibility path: minor version if compatible, major only if existing supported launch workflows are intentionally dropped.

## Project Memory Update

When this plan is committed or implementation starts, sync `agent-runtime-core` memory with:

```text
Electron Launcher supervisor plan created: single visible entry, Electron main as lifecycle supervisor, Workbench/backend/Runtime Manager/self-evolution workers as managed children, lifecycle intents for self-evolution restart/resume, and window provider migration from Edge app to Electron.
```

## Execution Handoff

Plan complete when saved to:

```text
docs/plans/2026-06-26-electron-launcher-supervisor-plan.md
```

Recommended execution mode:

1. Subagent-driven execution: one task per implementation slice, with review after each commit.
2. Inline execution: only for Tasks 1-4, because later tasks touch lifecycle, packaging, Runtime Manager, self-evolution, and tests across multiple surfaces.

First implementation slice should be Tasks 1-4 only. Do not start with packaging or self-evolution restart automation before the generic window provider and test alignment are stable.
