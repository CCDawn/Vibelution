# Electron Launcher Supervisor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert Vibelution to a single-entry Electron desktop application where Electron is the desktop supervisor and single visible shell, while Python Launcher and Runtime Manager remain the runtime lifecycle authority.

**Architecture:** Vibelution keeps one user-visible entrypoint and one source of truth per authority domain. Electron replaces the current Edge app window provider, owns only the desktop shell/window layer, and bootstraps or attaches to the Python Launcher control service; Python Launcher owns active-work policy, lifecycle intent persistence, runtime command decisions, and Runtime Manager delegation. The Codex reference repo shows the useful pattern is not "put product logic into Electron"; it is a deep-linkable desktop entry backed by a typed app-server/runtime protocol. Vibelution must therefore reuse existing Launcher, Runtime Manager, FastAPI, runtime-scene, active-work guard, config, and control-token contracts instead of creating a parallel lifecycle system.

**Tech Stack:** Electron, Node.js, TypeScript, React/Vite web UI loaded through local HTTP, FastAPI backend, Python Runtime Manager, existing `scripts/vibelution_launcher.ps1` / `scripts/vibelution_launcher.py`, existing Launcher API, Vitest, pytest.

## Global Constraints

- Single visible user entrypoint: one packaged `Vibelution` launcher entry, not separate public Launcher and Workbench shortcuts.
- Two-layer supervision rule: Electron main is the desktop session supervisor only; Python Launcher is the runtime policy and lifecycle command authority.
- Single-domain authority rule: Electron owns single-instance, protocol handler, BrowserWindow state, and the Launcher bootstrap/attach handle; Python owns active-work, apply/rollback, Runtime Manager commands, lifecycle intents, runtime-scene policy, and runtime child ownership.
- Multi-process runtime: Electron main is the packaged OS-visible entry process, but backend, Runtime Manager, self-evolution workers, and tool workers remain Python-owned runtime processes. They must not become Electron-owned direct children in the product authority model, even if a development bootstrap temporarily creates an OS process tree under the desktop entry.
- Workbench cannot start the project directly; it is opened, focused, and closed only through Launcher commands.
- Self-evolution Agent cannot spawn or kill the project directly; it writes structured lifecycle intents that Launcher validates and executes.
- Electron main process must not contain product business logic, LLM calls, file scanning, agent execution, runtime command interpretation, lifecycle intent interpretation, or tool execution; it supervises desktop windows and delegates all runtime authority to Python.
- Reuse-first rule: reuse current Launcher APIs, Runtime Manager commands, runtime-scene logging, control-token guard, and web build output before adding new paths.
- Codex reference rule: do not assume the reference repo contains reusable Electron packaging code. Its reusable idea is the separation between desktop entry, deep link, app-server protocol, daemon lifecycle commands, and packaged runtime artifacts.
- Protocol-first rule: before adding Electron IPC or child-process behavior, define the machine-readable Launcher protocol shape that Electron, web UI, self-evolution, and tests all consume.
- Deep-link rule: secondary entrypoints may only wake or focus the single Launcher supervisor through a deep link such as `vibelution://threads/new?path=...`; they must not start backend or Workbench directly.
- Machine-readable lifecycle rule: every start, stop, restart, status, and lifecycle-intent command must return bounded JSON that tests can parse, following the Codex app-server daemon style.
- Low-risk/high-ROI rule: prefer protocol adapters, status projections, tests, and feature-flagged Electron windows before changing startup ownership, packaging, or self-evolution restart execution.
- V1 packaging scope rule: version 1 is a Windows workspace-bound desktop package, not a zero-dependency installer. It may require the external Vibelution workspace, existing Python environment, and operator config until a separate V2 packaging project proves bundled runtime parity.
- No-drift rule: any compatibility field, adapter, feature flag, or legacy provider must have an owner, removal trigger, and test that proves it does not become a second source of truth.
- Config/environment rule: Electron must resolve Python, Node, ports, control tokens, user data, and operator config through existing project contracts or explicit environment adapters; it must not introduce hidden defaults that compete with `C:\Users\17533\Documents\Vibelution\config\config.toml`.
- Architecture/test alignment rule: update old tests that assert `msedge.exe`, `--app=`, `browserManaged`, or Edge profile details so they protect the new window-provider contract instead of the retired implementation.
- Security baseline: renderer Node integration stays disabled; `contextIsolation` stays enabled; preload exposes only narrow desktop-shell IPC calls.
- Package manager baseline: use `npm` and lockfiles; Bun remains auxiliary and must not become the release build path.
- Runtime refresh during implementation remains Launcher-gated; do not use ad hoc process killing as the normal validation path.

---

## Confirmed Product Contract

This plan is based on the aligned requirement:

```text
Vibelution.exe
└─ Electron Main Process: Desktop Supervisor
   ├─ Launcher Renderer Window
   ├─ Workbench Renderer Window
   └─ Python Launcher Control Service (bootstrap/attach handle; runtime authority remains in Python)
      ├─ FastAPI Backend / Launcher API
      ├─ Runtime Manager Daemon
      ├─ Self-Evolution Agent Worker(s)
      ├─ Supervised/Coding/Tool Worker(s)
      └─ Lifecycle Intent Store / Desktop Action Queue
```

The product behavior must feel like one app:

- User opens one `Vibelution` entry.
- Launcher control surface appears first.
- User starts or focuses Workbench through Launcher.
- Closing Workbench does not necessarily close Launcher.
- Closing Launcher runs Python active-work checks before closing desktop windows or requesting any Python-owned runtime shutdown.
- Self-evolution can request a restart or resume only by writing a lifecycle intent.
- Python Launcher records who requested a lifecycle action, why it was accepted or rejected, which runtime command or desktop action was emitted, and what happened.

## Codex Reference Audit

The local reference project at `C:\Users\17533\Desktop\Agent论文\projects\60_openai_codex` did not contain an Electron app source tree, Electron main process, preload script, or `electron-builder` / `electron-forge` packaging config. Its useful desktop pattern is a different one:

- `codex app` is a CLI bridge. On Windows/macOS it detects or installs the external Codex Desktop app, then opens a deep link like `codex://threads/new?path=...`.
- The desktop experience is treated as a client of `codex app-server`, not as the owner of agent/runtime semantics.
- `codex app-server` exposes a JSON-RPC-like protocol over stdio, websocket, unix socket, or off mode, with generated TypeScript and JSON schema fixtures.
- `codex app-server daemon` owns machine-readable lifecycle commands such as `start`, `restart`, `stop`, `version`, and `bootstrap`, returning one JSON object on success.
- The package builder packages `codex` and `codex-app-server` runtime artifacts and resources. It does not collapse desktop UI, CLI, app-server, and agent logic into one process.

Implication for Vibelution:

- Electron is still feasible, but it should be the single visible shell and Desktop Supervisor, not a new business runtime.
- The first architecture slice should harden deep-link, protocol, status, and lifecycle command contracts before packaging.
- Vibelution should not add a second app-server if FastAPI + Runtime Manager already provide the needed authority. Instead, define a narrow Launcher protocol adapter over the existing routes and command queue.
- External review follow-up: avoid the phrase "Electron owns lifecycle authority" unless the scope is explicitly desktop-only. The safer contract is "Electron Desktop Supervisor + Python Runtime Authority".

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
| Desktop session state | Electron Desktop Supervisor | Single-instance lock, deep-link protocol handler, BrowserWindow lifecycle, and Python Launcher Service child state. |
| Runtime lifecycle state | Python Launcher + Runtime Manager | Active-work, start/stop/restart/recover policy, Runtime Manager command queue, and runtime reconciliation. |
| Runtime commands | Runtime Manager command queue | Launcher submits commands; Runtime Manager executes workbench lifecycle operations. |
| Backend API | FastAPI backend | Electron loads the backend URL and does not replace API routes. |
| UI surface | React/Vite web UI served by the existing local HTTP stack | Existing web app remains the UI implementation; Electron does not bundle or replace it in V1. |
| Self-evolution restart intent | Python Launcher Lifecycle Intent Store | Agent submits an intent; Python Launcher validates, deduplicates, persists, and emits runtime commands or desktop actions. |
| Deep links | Electron protocol handler + Python Launcher validation | `vibelution://...` wakes or focuses the single desktop supervisor and submits typed requests; it never starts runtime children directly. |
| Launcher protocol | Existing Launcher / Runtime Manager / FastAPI contracts | Electron consumes a typed adapter; it does not invent a second command or status model. |
| Protocol schema | Generated TypeScript / JSON schema or equivalent fixtures | Protocol drift must be caught by tests before Electron packaging is trusted. |
| Evidence | Runtime scene package | Every branch, rejection, child exit, restart, and recovery is diagnosable. |
| Operator config | External config at `C:\Users\17533\Documents\Vibelution\config\config.toml` | Package must not move this source of truth. |
| Environment resolution | Existing Launcher/runtime-manager environment resolver | Electron may pass through resolved values, but it must not invent separate Python, port, token, or config defaults. |

## Project Impact And Risk Budget

The Electron migration touches core lifecycle surfaces. Treat it as a sequence of low-risk, high-ROI contracts, not a single replacement.

| Impact area | Current authority | Risk if changed too early | Low-risk/high-ROI action | Guardrail |
|---|---|---|---|---|
| Launcher startup | Existing PowerShell/Python Launcher | Duplicate starts, stale child processes, active-work bypass | Add typed status/protocol adapter first | Active-work guard tests must pass before Electron starts Python Launcher Service |
| Runtime Manager | Python daemon and command queue | Runtime commands split between Node and Python | Keep Runtime Manager as executor; Electron submits commands only | No direct `uvicorn`, port kill, or tool-worker spawn as normal path |
| Workbench window | Edge app provider | UI status and process detection regressions | Add generic `windowProvider/windowManaged` projection | Keep `browserManaged` compatibility until tests move |
| Backend/FastAPI | Existing routes and SSE/control-token flow | Broken API auth, SSE, runtime telemetry | Keep local HTTP loading; do not replace routes with IPC | `/api/*`, SSE, and control-token tests remain unchanged or stronger |
| Self-evolution | Existing self-evolution services | Agent gains unsafe process authority | Agent writes lifecycle intents only | Launcher validates intent, idempotency, worktree, and active-work state |
| Config | External operator config | Packaged app silently uses root template config | Reuse existing config loader/resolution | Tests prove external config path remains authoritative |
| Environment | Launcher/runtime env preparation | Wrong Python/Node, missing PATH, port conflicts, visible terminals | Add explicit environment inventory and adapter tests | No hidden hard-coded port or executable defaults |
| Packaging | Current dev/run scripts | Installer ships stale web/backend files or exposes extra entrypoints | Package only after protocol/window gates pass | Unpacked package smoke proves one public entry |

Risk budget by phase:

- Tasks 0-1: executable now. Documentation and test-ledger work can start immediately.
- Task 2: executable only after the four-root path model below replaces `resolveProjectRoot()` as the runtime authority.
- Tasks 3-4: executable after Task 2 proves deep-link parsing, bundle paths, and Launcher Service state are path-safe.
- Tasks 5-13: not executable as originally drafted until the review corrections below are present. Do not implement the old window-provider, lifecycle-intent, shutdown, or package steps by literal copy.

## Second Review Execution Gate

The second architecture review changes this plan from "direction approved" to "implementation conditionally approved." The following corrections are blocking:

| Blocker | Required correction | First task allowed after correction |
|---|---|---|
| Packaged paths point at the install directory instead of the external workspace | Separate Electron bundle, resources, workspace, and userData roots | Task 2 |
| `vibelution_launcher.py --action launcher` is not proven to be a long-lived service | Add a machine-readable bootstrap/attach/start handshake with ownership mode | Task 7 |
| Desktop Action ACK does not update pending state | Use transactional claim/lease/ack/fail semantics instead of append-only pending JSONL | Task 8 / Task 10 |
| Runtime-effect intents can be accepted without executing | Add Python runtime-action dispatcher and terminal statuses | Task 8 |
| Launcher close can bypass active-work guard | Add a ShutdownCoordinator with attach/owner semantics | Task 11 |
| Electron window state is not reported back to Python | Add Desktop Session registration, heartbeat, window lease, and revisioned state | Task 5 / Task 6 |
| Generic provider defaults fabricate an Edge window | Default provider is `none`; `browserManaged` is an Edge-only compatibility projection | Task 5 |
| Normal Launcher "open Workbench" can still call Edge while Electron also opens a window | Add a Python WindowProviderDispatcher shared by UI, deep link, self-evolution, and recovery | Task 5 |
| Deep link can request sensitive lifecycle actions | V1 deep links are limited to focus/open; restart/exit intents require authenticated Launcher UI or internal services | Task 3 |
| Gate filters may select zero tests | Gates must use explicit node ids or `-k` expressions that match planned test names | Gate 0 / Gate 4 |

## Reuse And Test-Alignment Entry Gate

Every implementation task in this plan starts with two checks before writing code:

1. Reuse check: search for the existing Vibelution owner of the behavior and either reuse/extend it or record why it cannot support the new requirement. Default reuse anchors for this plan are `scripts/vibelution_desktop_entry.py`, `scripts/vibelution_launcher.py`, `core.runtime_manager.command_queue`, `core.runtime_manager.workbench_controller`, `core.web.control`, `core.web.services.runtime_scene_service`, existing Launcher routes, and current web API type/test patterns.
2. Test alignment check: classify affected old tests as `keep`, `update`, `migrate/remove`, or `add`. Passing old tests is not enough when the old test protects Edge-specific process shape, append-only JSONL, hard-coded ports, or a retired projection. Each structural task must include at least one new test for the new source-of-truth or boundary invariant.

No task may introduce a parallel helper, route, cache, process starter, action queue, window state store, or config resolver unless the reuse check shows the current project-native path cannot carry the behavior without increasing drift.

## Config And Environment Contract

Electron must not become a new configuration layer. It can read or pass through resolved values, but the existing project resolver remains authoritative.

Required environment/config decisions before implementation:

| Concern | Required source | Allowed Electron behavior | Disallowed behavior |
|---|---|---|---|
| Operator config | `C:\Users\17533\Documents\Vibelution\config\config.toml` via existing config loader | Display resolved path, pass it to existing Launcher adapter if already supported | Reading root `config.toml` or `config.example.toml` as active runtime config |
| Python executable | Existing Launcher/runtime-manager resolver, then explicit `VIBELUTION_PYTHON_EXE` only for dev/test override | Validate path exists and record source in status JSON | Silently falling back to arbitrary `python` on PATH for packaged runtime |
| Node/npm | Project package manager contract (`npm`, lockfiles) | Use `npm --prefix web` and `npm --prefix desktop/electron` during build | Replacing npm/package-lock flow with Bun or ad hoc package installs |
| Ports and URLs | Existing Launcher status/control surface | Read resolved Launcher/Workbench URLs from status or explicit dev env | Hard-coding `127.0.0.1:8765` as production default |
| Control tokens | Existing Launcher/FastAPI control-token contract | Send token through existing guarded API path | Creating an Electron-only privileged bypass |
| User data/cache | Existing `.runtime/launcher` and explicit Electron app data path | Keep Electron window/profile cache separate from project source data | Writing cache/state into source files or operator config |
| Child process env | Existing redacted runtime env builder | Pass allowlisted env vars and redact status/log fields | Dumping full env, secrets, prompts, or provider keys into logs |
| Windows no-console behavior | Existing no-window process helper policy | Reuse no-console helpers or prove equivalent startup flags | Spawning `.cmd`, `taskkill.exe`, shell wrappers, or Git wrappers as normal lifecycle path |

Implementation must first separate path authorities. Never derive the external workspace by walking up from `import.meta.url` in packaged builds:

```ts
type DesktopPaths = {
  schemaVersion: 1;
  desktopBundleRoot: string; // app.getAppPath(): Electron JS bundle and preload.
  resourcesRoot: string; // process.resourcesPath: packaged resources root.
  workspaceRoot: string; // external Vibelution workspace.
  userDataRoot: string; // app.getPath("userData"): Electron cache/config/window state.
};
```

`workspaceRoot` resolution priority:

```text
--workspace CLI argument
→ VIBELUTION_WORKSPACE_ROOT
→ validated deep-link path
→ last workspace saved in Electron userData
→ first-run directory selection or safe startup failure page
```

The workspace resolver must validate:

```text
workspaceRoot/scripts/vibelution_launcher.py
workspaceRoot/core/
workspaceRoot/.venv/Scripts/python.exe or an explicit Launcher-resolved Python path
```

Preload must be resolved from the Electron bundle, not from `workspaceRoot`:

```ts
resolve(dirname(fileURLToPath(import.meta.url)), "preload.cjs")
```

Implementation must add a small environment inventory output before child startup:

```ts
type LauncherEnvironmentSummary = {
  schemaVersion: 1;
  paths: DesktopPaths;
  pythonSource: "launcher_resolver" | "env_override";
  pythonPath: string;
  operatorConfigPath: string;
  launcherUrl: string;
  workbenchUrl: string;
  controlTokenPresent: boolean;
  workspaceId: string;
  launcherInstanceId: string;
  protocolVersion: number;
  minDesktopProtocolVersion: number;
  maxDesktopProtocolVersion: number;
  capabilities: string[];
  nodeEnv: "development" | "production" | "test";
};
```

This summary is safe to log only after redaction. It must never include token values, API keys, full environment variables, or full command output.

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
      launcherBootstrap.ts
      launcherServiceClient.ts
      launcherServiceProcess.ts
      managedProcessTypes.ts
    protocol/
      deepLink.ts
      deepLinkRegistration.ts
      launcherProtocol.ts
      launcherProtocolSchema.ts
      lifecycleCommandOutput.ts
      desktopActionClient.ts
      environmentSummary.ts
    lifecycle/
      launcherStateAdapter.ts
      runtimeSceneBridge.ts
    security/
      urlPolicy.ts
      ipcSenderValidation.ts
    shutdown/
      shutdownCoordinator.ts
    windows/
      launcherWindow.ts
      workbenchWindow.ts
      windowProviderTypes.ts
      electronWindowProvider.ts
      desktopSessionClient.ts
  tests/
    appLock.test.ts
    launcherServiceProcess.test.ts
    desktopActionClient.test.ts
    desktopPaths.test.ts
    desktopSessionClient.test.ts
    shutdownCoordinator.test.ts
    launcherProtocol.test.ts
    deepLink.test.ts
    windowProvider.test.ts
```

Modify existing Python and web layers only where the Electron provider must integrate with existing contracts:

```text
core/runtime_manager/workbench_controller.py
core/runtime_manager/process_inventory.py
core/launcher/service.py
core/launcher/lifecycle_intent_store.py
core/launcher/desktop_session_store.py
core/launcher/window_provider_dispatcher.py
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
type WorkbenchWindowProvider = "none" | "edge_app" | "electron";

type WorkbenchWindowState = {
  windowManaged: boolean;
  windowProvider: WorkbenchWindowProvider;
  windowId: number;
  rendererProcessId: number;
  windowLaunchProcessId: number;
  windowProfileDir: string;
  browserManaged?: boolean; // Edge-only compatibility projection during migration.
};
```

## Lifecycle Intent Contract

Self-evolution and other agents may request lifecycle actions only by submitting an intent to the Python Launcher API. They do not append files directly, and Electron never reads or writes the intent store.

```ts
type LifecycleIntent = {
  intentId: string;
  schemaVersion: 1;
  requestedBy: {
    actorType: "self_evolution_agent" | "supervised_agent" | "user" | "desktop_supervisor" | "system";
    actorId: string;
  };
  action:
    | "open_workbench"
    | "focus_workbench"
    | "close_workbench"
    | "restart_after_apply"
    | "resume_self_evolution"
    | "recover_after_crash"
    | "request_app_exit";
  reason: string;
  sourceRunId?: string;
  sourceTaskId?: string;
  sourceWorktree?: string;
  idempotencyKey: string;
  status: "queued" | "validated" | "accepted" | "rejected" | "executing" | "succeeded" | "failed" | "superseded";
  createdAt: string;
  updatedAt: string;
  rejectionReason?: string;
  commandId?: string;
  runtimeSceneRef?: string;
};
```

Storage:

```text
.runtime/launcher/lifecycle.sqlite3
```

Rules:

- Python Launcher is the single writer of `lifecycle.sqlite3`.
- Server code derives `requestedBy`, `sourceRunId`, and `sourceWorktree`; callers cannot self-declare trusted actor identity or arbitrary worktree paths.
- Launcher validates active work, worktree review state, apply/rollback safety, source run existence, source worktree ownership, retry budget, rollback conflicts, and duplicate idempotency keys before persistence changes state.
- Every accepted intent is routed through one Python Policy Engine decision before any side effect occurs.
- The Python Policy Engine must emit exactly one terminal dispatch output per intent: `RuntimeCommand`, `DesktopAction`, `Rejected`, or `Superseded`. A single intent must never emit both a Runtime Manager command and a Desktop Action.
- Desktop Actions are created only by the Python Policy Engine, claimed through a guarded Launcher API with lease semantics, and acked by Electron with result metadata.
- Electron never interprets lifecycle intents, never reads the intent store, and never decides whether an intent becomes a runtime command or a desktop action.
- Rejected intents stay visible with a safe reason.
- Intent execution records runtime-scene events before and after command submission.

SQLite tables:

```text
lifecycle_intents
  intent_id TEXT PRIMARY KEY
  idempotency_key TEXT NOT NULL UNIQUE
  action TEXT NOT NULL
  actor_type TEXT NOT NULL
  actor_id TEXT NOT NULL
  status TEXT NOT NULL
  rejection_reason TEXT NOT NULL DEFAULT ''
  command_id TEXT NOT NULL DEFAULT ''
  created_at TEXT NOT NULL
  updated_at TEXT NOT NULL

desktop_actions
  action_id TEXT PRIMARY KEY
  intent_id TEXT NOT NULL
  action TEXT NOT NULL
  status TEXT NOT NULL
  payload_json TEXT NOT NULL
  claimed_by TEXT NOT NULL DEFAULT ''
  claimed_at TEXT NOT NULL DEFAULT ''
  lease_expires_at TEXT NOT NULL DEFAULT ''
  claim_attempt INTEGER NOT NULL DEFAULT 0
  result_json TEXT NOT NULL DEFAULT '{}'
  created_at TEXT NOT NULL
  updated_at TEXT NOT NULL

lifecycle_events
  event_id TEXT PRIMARY KEY
  entity_id TEXT NOT NULL
  event_type TEXT NOT NULL
  payload_json TEXT NOT NULL
  created_at TEXT NOT NULL
```

Desktop Action API:

```text
POST /api/launcher/desktop-actions/claim
POST /api/launcher/desktop-actions/{actionId}/ack
POST /api/launcher/desktop-actions/{actionId}/fail
```

The claim endpoint must atomically transition one row from `pending` to `claimed`, set `claimed_by`, set `claimed_at`, set `lease_expires_at`, and increment `claim_attempt`. ACK/fail must transition the same action to a terminal status so it cannot be re-delivered. Expired claimed actions may be retried only while `claim_attempt` remains within the retry budget.

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
  provider: "none" | "edge_app" | "electron";
  windowId?: number;
  rendererProcessId?: number;
  launcherWindowPid?: number; // Edge compatibility only.
  workbenchWindowPid?: number; // Edge compatibility only.
  reason?: string;
};
```

The first Electron implementation can live in the desktop layer, but Python must expose only lease-backed generic provider state. Missing evidence must default to:

```python
window_provider = "none"
window_managed = False
browser_managed = window_provider == "edge_app" and window_managed
browser_window_pid = int(workbench.get("browserWindowPid") or renderer_process_id) if window_provider == "edge_app" else 0
```

Desktop Session API:

```text
POST /api/launcher/desktop-sessions
PUT  /api/launcher/desktop-sessions/{desktopSessionId}/windows/{role}
POST /api/launcher/desktop-sessions/{desktopSessionId}/heartbeat
DELETE /api/launcher/desktop-sessions/{desktopSessionId}
```

Window state payload:

```json
{
  "schemaVersion": 1,
  "desktopSessionId": "desktop-...",
  "revision": 12,
  "role": "workbench",
  "provider": "electron",
  "windowId": 2,
  "rendererProcessId": 12345,
  "state": "ready",
  "url": "http://127.0.0.1:8765/",
  "observedAt": "2026-06-26T00:00:00Z"
}
```

Python publishes Electron window projections only while the desktop session heartbeat lease is valid. `webContents.getOSProcessId()` is renderer evidence, not a stable generic window PID, so status payloads must carry both `windowId` and `rendererProcessId`.

All Workbench open/focus/close sources must converge through a Python `WindowProviderDispatcher`:

```text
Launcher UI
Deep Link
Self-evolution intent
Crash recovery
Runtime reconciliation
```

`windowProvider=edge_app` uses the existing Edge provider. `windowProvider=electron` creates a Desktop Action. There must be no path where the Launcher UI opens Edge while Electron also consumes an action for the same request.

## Deep Link And Launcher Protocol Contract

Codex uses `codex://threads/new?path=...` as the bridge from CLI or OS entrypoint into the desktop app. Vibelution should use the same idea without copying Codex-specific routes:

```text
vibelution://launcher/focus
vibelution://workbench/open?path=C%3A%5CUsers%5C17533%5CDesktop%5CVibelution
```

Rules:

- Deep links are entry intents, not runtime execution authority.
- V1 deep links allow only safe focus/open requests. Sensitive lifecycle actions such as restart, recover, app exit, apply, rollback, and self-evolution resume must come from authenticated Launcher UI or internal services.
- Electron main parses and validates the link, then translates it into a Launcher protocol request after Launcher readiness.
- Unsupported links return or record a safe machine-readable rejection.
- Path values must be canonicalized and never replace the active operator config source.
- Tests must cover Windows path encoding, protocol registration, initial argv handling, second-instance `additionalData`, duplicate secondary launch focus, pending deep links before Launcher readiness, invalid action rejection, and idempotency.

Launcher protocol response shape:

```ts
type LauncherCommandStatus = "ok" | "accepted" | "rejected" | "failed";

type LauncherCommandResponse = {
  schemaVersion: 1;
  commandId: string;
  command: "status" | "start" | "stop" | "restart" | "focus" | "lifecycle_intent";
  status: LauncherCommandStatus;
  provider: "edge_app" | "electron" | "launcher_protocol";
  message: string;
  activeWorkBlocked: boolean;
  runtimeSceneRef?: string;
  childProcesses?: Array<{
    role: "fastapi_backend" | "runtime_manager" | "self_evolution_worker" | "tool_worker";
    pid: number;
    status: "starting" | "running" | "stopping" | "exited" | "failed";
  }>;
};
```

This contract lets Electron stay thin: it displays, focuses, and supervises, while the existing backend and Runtime Manager continue to own product behavior.

## Phase Plan

### Task 0: Codex-Informed Protocol, Impact, And Environment Boundary Audit

**Files:**
- Create: `docs/testing/electron-launcher-protocol-contract.md`
- Create: `docs/testing/electron-launcher-impact-and-environment-ledger.md`
- Test: none

**Interfaces:**
- Consumes: current Launcher routes, Runtime Manager commands, self-evolution lifecycle calls, and existing tests for `browserManaged` / Launcher control tokens.
- Produces: protocol, impact, and environment ledgers that prevent Electron from becoming a duplicate backend or hidden configuration source.

- [ ] **Step 1: Record the reference finding**

Create `docs/testing/electron-launcher-protocol-contract.md`:

```markdown
# Electron Launcher Protocol Contract

日期：2026-06-26
参考：`C:\Users\17533\Desktop\Agent论文\projects\60_openai_codex`

## Reference Findings

- The reference repo has no Electron source packaging to copy.
- `codex app` opens or installs an external desktop app and passes workspace context through a deep link.
- Runtime behavior is exposed through an app-server protocol and daemon lifecycle commands.
- Protocol schemas and app-server integration tests are first-class review surfaces.

## Vibelution Contract

- Electron main is the single visible shell and Desktop Supervisor.
- Existing Launcher, Runtime Manager, FastAPI routes, runtime-scene logging, and active-work guard remain authoritative.
- Deep links submit typed requests for Launcher validation; they do not directly start backend, Workbench, or agent workers.
- Lifecycle command responses are machine-readable JSON with `schemaVersion`, `commandId`, `status`, `provider`, `message`, and `runtimeSceneRef`.
- Protocol drift must be caught by TypeScript tests and focused pytest route/service tests.
```

- [ ] **Step 2: Record impact and environment boundaries**

Create `docs/testing/electron-launcher-impact-and-environment-ledger.md`:

```markdown
# Electron Launcher Impact And Environment Ledger

日期：2026-06-26
范围：low-risk Electron Launcher supervisor migration

## Impact Rules

- Do not change startup ownership before protocol, active-work guard, and generic provider tests pass.
- Do not remove Edge provider or `browserManaged` compatibility before Electron is default and old tests are migrated.
- Do not let Electron main own product semantics, LLM routing, tool execution, Git execution, memory writes, or self-evolution decisions.
- Do not package until unpacked smoke proves one public entry and no independent Workbench shortcut.

## Config And Environment Rules

- Active operator config remains `C:\Users\17533\Documents\Vibelution\config\config.toml`.
- Root `config.toml` and `config.example.toml` are legacy/template surfaces, not packaged runtime authority.
- Python path, ports, Launcher URL, Workbench URL, and control-token presence come from existing Launcher/runtime-manager resolution or explicit dev/test override.
- Electron must not hard-code production ports, spawn shell wrappers as normal lifecycle, or log full environment variables.

## Exit Condition

Implementation can move past Tasks 0-4 only when tests prove protocol shape, deep-link parsing, generic provider state, and config/environment resolution are stable without starting runtime children.
```

- [ ] **Step 3: Record contract checks for the ledger**

Task 1 must include these rows when it creates `docs/testing/electron-launcher-window-provider-test-alignment.md`:

```markdown
| `desktop/electron/tests/desktopPaths.test.ts` | Electron bundle/workspace/userData/resources root separation | add | Validate development and packaged path fixtures without using install dir as workspace | Packaged path tests prove preload and workspace are resolved from different roots |
| `desktop/electron/tests/deepLink.test.ts` | `vibelution://` parsing, registration, and Windows path encoding | add | Validate focus/open links, initial argv, and second-instance additionalData without launching children | Invalid or duplicate links become safe typed responses |
| `desktop/electron/tests/launcherProtocol.test.ts` | Machine-readable Launcher command response | add | Assert schema fields and command/status/provider enums | Electron and backend adapter share one response shape |
| `tests/test_web_runtime_routes.py` | Launcher command adapter and active-work guard | add/update | Assert JSON lifecycle responses and blocked active-work states | Runtime commands stay Launcher-gated |
| `desktop/electron/tests/environmentSummary.test.ts` | Config/environment resolution summary | add | Assert external operator config, URL, Python source, and token presence are reported without secrets | Electron does not invent hidden config/env defaults |
| `desktop/electron/tests/shutdownCoordinator.test.ts` | Launcher close and active-work guard | add | Assert close is blocked when active work exists and attach mode detaches instead of killing Launcher | Launcher close cannot bypass Python guard |
```

- [ ] **Step 4: Commit**

```powershell
git add docs/testing/electron-launcher-protocol-contract.md docs/testing/electron-launcher-impact-and-environment-ledger.md
git commit -m "docs: define electron launcher protocol and risk boundary"
```

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
rg -n "msedge|--app=|browserManaged|workbench-app-profile|launcher_control_surface|open_workbench|restart_workbench|lifecycle_intent|control-token|runtime_scene" tests web/src desktop -g "*.py" -g "*.ts" -g "*.tsx" -g "*.md"
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
| `desktop/electron/tests/desktopPaths.test.ts` | Electron bundle/workspace/userData/resources root separation | add | Validate development and packaged path fixtures without using install dir as workspace | Packaged path tests prove preload and workspace are resolved from different roots |
| `desktop/electron/tests/deepLink.test.ts` | `vibelution://` parsing and Windows path encoding | add | Validate focus/open links without launching children; lifecycle links are rejected in V1 | Invalid or duplicate links become safe typed responses |
| `desktop/electron/tests/launcherProtocol.test.ts` | Machine-readable Launcher command response | add | Assert schema fields and command/status/provider enums | Electron and backend adapter share one response shape |
| `tests/test_web_runtime_routes.py` | Launcher command adapter and active-work guard | add/update | Assert JSON lifecycle responses and blocked active-work states | Runtime commands stay Launcher-gated |
| `desktop/electron/tests/environmentSummary.test.ts` | Config/environment resolution summary | add | Assert external operator config, URL, Python source, and token presence are reported without secrets | Electron does not invent hidden config/env defaults |
| `desktop/electron/tests/desktopActionClient.test.ts` | Desktop Action claim/ack/fail semantics | add | Assert claimed actions are not re-delivered and runtime-effect actions are not executed by Electron | No infinite ACK replay or Node-side runtime commands |
| `desktop/electron/tests/desktopSessionClient.test.ts` | Electron window state writeback | add | Assert window state updates use Desktop Session API with `windowId`, `rendererProcessId`, and revision | Python status projection is lease-backed instead of stale local Electron state |
| `desktop/electron/tests/shutdownCoordinator.test.ts` | Launcher close and active-work guard | add | Assert close is blocked when active work exists and attach mode detaches instead of killing Launcher | Launcher close cannot bypass Python guard |
| `desktop/electron/tests/runtimeSceneBridge.test.ts` | Electron supervisor evidence transport | add | Assert bounded events post to guarded Launcher runtime-scene route and buffer only briefly on failure | Electron lifecycle decisions are diagnosable without full env or prompt logs |
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
- Create: `desktop/electron/src/protocol/deepLink.ts`
- Create: `desktop/electron/src/protocol/environmentSummary.ts`
- Create: `desktop/electron/src/protocol/launcherProtocol.ts`
- Create: `desktop/electron/tests/appLock.test.ts`
- Create: `desktop/electron/tests/desktopPaths.test.ts`
- Create: `desktop/electron/tests/deepLink.test.ts`
- Create: `desktop/electron/tests/environmentSummary.test.ts`
- Create: `desktop/electron/tests/launcherProtocol.test.ts`
- Modify: none

**Interfaces:**
- Consumes: existing local HTTP Launcher/Workbench URLs and existing web UI served by the Python workspace.
- Produces: a compilable Electron desktop package plus deep-link and Launcher protocol types that do not start backend processes.

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
    "build": "tsc -p tsconfig.json && npm run build:preload",
    "build:preload": "esbuild src/preload.ts --bundle --platform=node --format=cjs --outfile=dist/preload.cjs --external:electron",
    "test": "vitest run tests",
    "dev": "npm run build && electron dist/main.js"
  },
  "dependencies": {},
  "devDependencies": {
    "@types/node": "^24.0.0",
    "electron": "42.5.0",
    "esbuild": "^0.25.12",
    "typescript": "^5.9.3",
    "vitest": "^3.2.4"
  }
}
```

Electron is an exact dev dependency because the desktop runtime is built and packaged from this project; do not use an unsupported major or a floating `^` range for the shell. The preload script is bundled to CommonJS so it can run under Electron sandbox preload constraints.

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
    "rootDir": "src",
    "types": ["node", "vitest"],
    "skipLibCheck": true
  },
  "include": ["src/**/*.ts"],
  "exclude": ["tests/**/*.ts"]
}
```

- [ ] **Step 3: Add path resolver**

Create `desktop/electron/src/paths.ts`:

```ts
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export type DesktopPaths = {
  schemaVersion: 1;
  desktopBundleRoot: string;
  resourcesRoot: string;
  workspaceRoot: string;
  userDataRoot: string;
};

export type DesktopPathInput = {
  importMetaUrl: string;
  resourcesRoot: string;
  userDataRoot: string;
  workspaceRoot: string;
};

export function resolveDesktopBundleRoot(importMetaUrl: string): string {
  return dirname(fileURLToPath(importMetaUrl));
}

export function createDesktopPaths(input: DesktopPathInput): DesktopPaths {
  const workspaceRoot = resolve(input.workspaceRoot);
  return {
    schemaVersion: 1,
    desktopBundleRoot: resolveDesktopBundleRoot(input.importMetaUrl),
    resourcesRoot: resolve(input.resourcesRoot),
    workspaceRoot,
    userDataRoot: resolve(input.userDataRoot)
  };
}

export function resolvePreloadPath(paths: DesktopPaths): string {
  return resolve(paths.desktopBundleRoot, "preload.cjs");
}

export function resolveWorkspaceRuntimeDir(paths: DesktopPaths): string {
  return resolve(paths.workspaceRoot, ".runtime", "launcher");
}
```

Create `desktop/electron/tests/desktopPaths.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { createDesktopPaths, resolvePreloadPath, resolveWorkspaceRuntimeDir } from "../src/paths.js";

describe("Electron desktop paths", () => {
  it("keeps packaged bundle path separate from external workspace", () => {
    const paths = createDesktopPaths({
      importMetaUrl: "file:///C:/Program%20Files/Vibelution/resources/app.asar/dist/main.js",
      resourcesRoot: "C:/Program Files/Vibelution/resources",
      userDataRoot: "C:/Users/17533/AppData/Roaming/Vibelution",
      workspaceRoot: "C:/Users/17533/Desktop/Vibelution"
    });

    expect(resolvePreloadPath(paths).replace(/\\/g, "/")).toBe(
      "C:/Program Files/Vibelution/resources/app.asar/dist/preload.cjs"
    );
    expect(resolveWorkspaceRuntimeDir(paths).replace(/\\/g, "/")).toBe(
      "C:/Users/17533/Desktop/Vibelution/.runtime/launcher"
    );
  });
});
```

- [ ] **Step 4: Add machine-readable Launcher protocol types**

Create `desktop/electron/src/protocol/launcherProtocol.ts`:

```ts
export type LauncherCommand =
  | "status"
  | "start"
  | "stop"
  | "restart"
  | "focus"
  | "lifecycle_intent";

export type LauncherCommandStatus = "ok" | "accepted" | "rejected" | "failed";

export type LauncherProvider = "edge_app" | "electron" | "launcher_protocol";

export type LauncherChildProcessStatus = "starting" | "running" | "stopping" | "exited" | "failed";

export type LauncherCommandResponse = {
  schemaVersion: 1;
  commandId: string;
  command: LauncherCommand;
  status: LauncherCommandStatus;
  provider: LauncherProvider;
  message: string;
  activeWorkBlocked: boolean;
  runtimeSceneRef?: string;
  childProcesses?: Array<{
    role: "fastapi_backend" | "runtime_manager" | "self_evolution_worker" | "tool_worker";
    pid: number;
    status: LauncherChildProcessStatus;
  }>;
};

export function launcherCommandAccepted(
  commandId: string,
  command: LauncherCommand,
  message: string
): LauncherCommandResponse {
  return {
    schemaVersion: 1,
    commandId,
    command,
    status: "accepted",
    provider: "launcher_protocol",
    message,
    activeWorkBlocked: false
  };
}
```

- [ ] **Step 5: Add deep-link parser**

Create `desktop/electron/src/protocol/deepLink.ts`:

```ts
export type VibelutionDeepLink =
  | { kind: "focus_launcher" }
  | { kind: "open_workbench"; path: string };

export function parseVibelutionDeepLink(rawUrl: string): VibelutionDeepLink {
  const url = new URL(rawUrl);
  if (url.protocol !== "vibelution:") {
    throw new Error(`unsupported protocol: ${url.protocol}`);
  }
  const route = `${url.hostname}${url.pathname}`;
  if (route === "launcher/focus") {
    return { kind: "focus_launcher" };
  }
  if (route === "workbench/open") {
    const path = url.searchParams.get("path");
    if (!path) {
      throw new Error("missing workbench path");
    }
    return { kind: "open_workbench", path };
  }
  throw new Error(`unsupported deep link route: ${route}`);
}
```

- [ ] **Step 6: Add protocol tests**

Create `desktop/electron/tests/launcherProtocol.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { launcherCommandAccepted } from "../src/protocol/launcherProtocol.js";

describe("Launcher protocol", () => {
  it("returns a machine-readable accepted response", () => {
    expect(launcherCommandAccepted("cmd-1", "focus", "focusing launcher")).toEqual({
      schemaVersion: 1,
      commandId: "cmd-1",
      command: "focus",
      status: "accepted",
      provider: "launcher_protocol",
      message: "focusing launcher",
      activeWorkBlocked: false
    });
  });
});
```

Create `desktop/electron/tests/deepLink.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { parseVibelutionDeepLink } from "../src/protocol/deepLink.js";

describe("Vibelution deep links", () => {
  it("parses launcher focus links", () => {
    expect(parseVibelutionDeepLink("vibelution://launcher/focus")).toEqual({ kind: "focus_launcher" });
  });

  it("preserves Windows workspace paths", () => {
    expect(
      parseVibelutionDeepLink("vibelution://workbench/open?path=C%3A%5CUsers%5C17533%5CDesktop%5CVibelution")
    ).toEqual({ kind: "open_workbench", path: "C:\\Users\\17533\\Desktop\\Vibelution" });
  });

  it("rejects unsupported protocols", () => {
    expect(() => parseVibelutionDeepLink("https://example.com")).toThrow("unsupported protocol");
  });

  it("rejects lifecycle intent links in version 1", () => {
    expect(() =>
      parseVibelutionDeepLink("vibelution://lifecycle/intent?action=restart_after_apply&idempotencyKey=x")
    ).toThrow("unsupported deep link route");
  });
});
```

- [ ] **Step 7: Add environment summary contract**

Create `desktop/electron/src/protocol/environmentSummary.ts`:

```ts
export type LauncherEnvironmentSummary = {
  schemaVersion: 1;
  paths: {
    desktopBundleRoot: string;
    resourcesRoot: string;
    workspaceRoot: string;
    userDataRoot: string;
  };
  pythonSource: "launcher_resolver" | "env_override";
  pythonPath: string;
  operatorConfigPath: string;
  launcherUrl: string;
  workbenchUrl: string;
  controlTokenPresent: boolean;
  workspaceId: string;
  launcherInstanceId: string;
  protocolVersion: number;
  minDesktopProtocolVersion: number;
  maxDesktopProtocolVersion: number;
  capabilities: string[];
  nodeEnv: "development" | "production" | "test";
};

export function createLauncherEnvironmentSummary(input: LauncherEnvironmentSummary): LauncherEnvironmentSummary {
  return { ...input, schemaVersion: 1 };
}

export function redactEnvironmentSummary(summary: LauncherEnvironmentSummary): LauncherEnvironmentSummary {
  return { ...summary, controlTokenPresent: summary.controlTokenPresent };
}
```

Create `desktop/electron/tests/environmentSummary.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { createLauncherEnvironmentSummary, redactEnvironmentSummary } from "../src/protocol/environmentSummary.js";

describe("Launcher environment summary", () => {
  it("keeps external operator config explicit", () => {
    const summary = createLauncherEnvironmentSummary({
      schemaVersion: 1,
      paths: {
        desktopBundleRoot: "C:/Program Files/Vibelution/resources/app.asar/dist",
        resourcesRoot: "C:/Program Files/Vibelution/resources",
        workspaceRoot: "C:/Users/17533/Desktop/Vibelution",
        userDataRoot: "C:/Users/17533/AppData/Roaming/Vibelution"
      },
      pythonSource: "launcher_resolver",
      pythonPath: "C:/repo/.venv/Scripts/python.exe",
      operatorConfigPath: "C:/Users/17533/Documents/Vibelution/config/config.toml",
      launcherUrl: "http://127.0.0.1:8765/launcher",
      workbenchUrl: "http://127.0.0.1:8765/",
      controlTokenPresent: true,
      workspaceId: "workspace-vibelution",
      launcherInstanceId: "launcher-1",
      protocolVersion: 1,
      minDesktopProtocolVersion: 1,
      maxDesktopProtocolVersion: 1,
      capabilities: ["desktop_actions_v1", "window_state_lease_v1"],
      nodeEnv: "test"
    });

    expect(summary.operatorConfigPath.replace(/\\/g, "/")).toBe(
      "C:/Users/17533/Documents/Vibelution/config/config.toml"
    );
    expect(summary).not.toHaveProperty("controlToken");
  });

  it("redacts by reporting token presence only", () => {
    const summary = createLauncherEnvironmentSummary({
      schemaVersion: 1,
      paths: {
        desktopBundleRoot: "C:/Program Files/Vibelution/resources/app.asar/dist",
        resourcesRoot: "C:/Program Files/Vibelution/resources",
        workspaceRoot: "C:/Users/17533/Desktop/Vibelution",
        userDataRoot: "C:/Users/17533/AppData/Roaming/Vibelution"
      },
      pythonSource: "env_override",
      pythonPath: "C:/Python/python.exe",
      operatorConfigPath: "C:/Users/17533/Documents/Vibelution/config/config.toml",
      launcherUrl: "http://127.0.0.1:8765/launcher",
      workbenchUrl: "http://127.0.0.1:8765/",
      controlTokenPresent: true,
      workspaceId: "workspace-vibelution",
      launcherInstanceId: "launcher-1",
      protocolVersion: 1,
      minDesktopProtocolVersion: 1,
      maxDesktopProtocolVersion: 1,
      capabilities: ["desktop_actions_v1", "window_state_lease_v1"],
      nodeEnv: "test"
    });

    expect(redactEnvironmentSummary(summary)).toEqual(summary);
  });
});
```

- [ ] **Step 8: Add minimal preload**

Create `desktop/electron/src/preload.ts`:

```ts
import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("vibelutionLauncher", {
  getVersion: () => ipcRenderer.invoke("launcher:get-version"),
});
```

- [ ] **Step 9: Add minimal main process**

Create `desktop/electron/src/main.ts`:

```ts
import { app, BrowserWindow, ipcMain } from "electron";
import { createDesktopPaths, resolvePreloadPath } from "./paths.js";

let launcherWindow: BrowserWindow | null = null;

function createLauncherWindow(): BrowserWindow {
  const workspaceRoot = process.env.VIBELUTION_WORKSPACE_ROOT;
  if (!workspaceRoot) {
    throw new Error("VIBELUTION_WORKSPACE_ROOT is required until the first-run workspace picker exists");
  }
  const paths = createDesktopPaths({
    importMetaUrl: import.meta.url,
    resourcesRoot: process.resourcesPath,
    userDataRoot: app.getPath("userData"),
    workspaceRoot
  });
  const window = new BrowserWindow({
    width: 1180,
    height: 760,
    title: "Vibelution Launcher",
    webPreferences: {
      preload: resolvePreloadPath(paths),
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
  // Task 11 replaces this with ShutdownCoordinator; scaffold must not bypass active-work guard.
});
```

- [ ] **Step 10: Add a path test**

Create `desktop/electron/tests/appLock.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { createDesktopPaths, resolveWorkspaceRuntimeDir } from "../src/paths.js";

describe("Electron desktop paths", () => {
  it("keeps launcher runtime state under the external workspace", () => {
    const paths = createDesktopPaths({
      importMetaUrl: "file:///C:/Program%20Files/Vibelution/resources/app.asar/dist/main.js",
      resourcesRoot: "C:/Program Files/Vibelution/resources",
      userDataRoot: "C:/Users/17533/AppData/Roaming/Vibelution",
      workspaceRoot: "C:/repo"
    });
    expect(resolveWorkspaceRuntimeDir(paths).replace(/\\/g, "/")).toBe("C:/repo/.runtime/launcher");
  });
});
```

- [ ] **Step 11: Verify**

Run:

```powershell
npm --prefix desktop/electron install
npm --prefix desktop/electron run build
npm --prefix desktop/electron test -- --run
```

Expected: TypeScript build passes and the Vitest path test passes.

- [ ] **Step 12: Commit**

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

### Task 4: Python Launcher Service Supervisor

**Files:**
- Create: `desktop/electron/src/process/managedProcessTypes.ts`
- Create: `desktop/electron/src/process/launcherServiceProcess.ts`
- Test: `desktop/electron/tests/launcherServiceProcess.test.ts`

**Interfaces:**
- Consumes: Node child process lifecycle events for the one Python Launcher Service that Electron directly owns.
- Produces: desktop-supervisor state for the Launcher Service only; backend, Runtime Manager, and worker states remain Python-owned projections.

- [ ] **Step 1: Add Launcher Service state types**

Create `desktop/electron/src/process/managedProcessTypes.ts`:

```ts
export type ManagedProcessRole = "python_launcher_service";

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

- [ ] **Step 2: Add Launcher Service transition helpers**

Create `desktop/electron/src/process/launcherServiceProcess.ts`:

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

Create `desktop/electron/tests/launcherServiceProcess.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { initialManagedProcessState } from "../src/process/managedProcessTypes.js";
import { markProcessExited, markProcessFailed, markProcessRunning, markProcessStarting } from "../src/process/launcherServiceProcess.js";

describe("python launcher service supervisor transitions", () => {
  it("records start and running pid for the single directly owned child", () => {
    const idle = initialManagedProcessState("python_launcher_service");
    const starting = markProcessStarting(idle, "2026-06-26T00:00:00.000Z");
    const running = markProcessRunning(starting, 1234);
    expect(running).toMatchObject({
      role: "python_launcher_service",
      status: "running",
      pid: 1234,
      startedAt: "2026-06-26T00:00:00.000Z"
    });
  });

  it("clears pid and records exit evidence", () => {
    const running = markProcessRunning(markProcessStarting(initialManagedProcessState("python_launcher_service"), "start"), 2222);
    const exited = markProcessExited(running, 0, "", "end");
    expect(exited).toMatchObject({ status: "exited", pid: 0, exitCode: 0, exitedAt: "end" });
  });

  it("records failure reason", () => {
    const failed = markProcessFailed(initialManagedProcessState("python_launcher_service"), "spawn failed", "now");
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

Expected: all Electron unit tests pass, and no test implies Electron directly supervises backend, Runtime Manager, or worker processes.

- [ ] **Step 5: Commit**

```powershell
git add desktop/electron/src/process desktop/electron/tests/launcherServiceProcess.test.ts
git commit -m "feat: track python launcher service state"
```

### Task 5: Generic Window Provider State In Backend

**Files:**
- Create: `core/launcher/window_provider_dispatcher.py`
- Modify: `core/runtime_manager/workbench_controller.py`
- Modify: `core/launcher/service.py`
- Modify: `core/web/services/runtime_service.py`
- Modify: `web/src/api/types.ts`
- Test: `tests/test_runtime_manager.py`
- Test: `tests/test_launcher_service.py`
- Test: `tests/test_web_runtime_routes.py`

**Interfaces:**
- Consumes: current `browserManaged`, `browserWindowPid`, `browserProfileDir` fields plus future Desktop Session lease snapshots.
- Produces: generic `windowManaged`, `windowProvider`, `windowId`, `rendererProcessId`, and `windowProfileDir` fields while preserving Edge-only compatibility projections, plus a `WindowProviderDispatcher` that converges Launcher UI/deep-link/self-evolution/recovery window requests through the configured provider.

- [ ] **Step 1: Write failing backend tests**

Add assertions to focused tests so status payloads include:

```python
assert payload["workbench"]["windowProvider"] in {"none", "edge_app", "electron"}
assert isinstance(payload["workbench"]["windowManaged"], bool)
assert payload["workbench"]["browserManaged"] == (
    payload["workbench"]["windowProvider"] == "edge_app"
    and payload["workbench"]["windowManaged"]
)
```

Run:

```powershell
$env:TEMP="$PWD\\.tmp\\pytest-temp"; $env:TMP="$PWD\\.tmp\\pytest-temp"; pytest tests/test_runtime_manager.py tests/test_launcher_service.py tests/test_web_runtime_routes.py -k "launcher or workbench or browserManaged" -q --basetemp "$PWD\\.tmp\\pytest-basetemp"
```

Expected: failing assertions for missing generic window fields.

- [ ] **Step 2: Implement compatibility projection**

Update Python payload builders so existing state produces:

```python
legacy_browser_managed = bool(workbench.get("browserManaged", False))
window_provider = str(workbench.get("windowProvider") or ("edge_app" if legacy_browser_managed else "none"))
window_managed = bool(workbench.get("windowManaged", legacy_browser_managed if window_provider == "edge_app" else False))
window_id = int(workbench.get("windowId") or 0)
renderer_process_id = int(workbench.get("rendererProcessId") or workbench.get("windowProcessId") or 0)
window_profile_dir = str(workbench.get("windowProfileDir") or workbench.get("browserProfileDir") or "")
browser_managed = window_provider == "edge_app" and window_managed
```

Return both generic and compatibility fields during migration:

```python
"windowProvider": window_provider,
"windowManaged": window_managed,
"windowId": window_id,
"rendererProcessId": renderer_process_id,
"windowProfileDir": window_profile_dir,
"browserManaged": browser_managed,
"browserWindowPid": browser_window_pid,
"browserProfileDir": window_profile_dir,
```

- [ ] **Step 3: Add WindowProviderDispatcher**

Create `core/launcher/window_provider_dispatcher.py`:

```python
from __future__ import annotations

from typing import Any, Callable


WindowActionWriter = Callable[[str, dict[str, Any]], dict[str, Any]]


class WindowProviderDispatcher:
    def __init__(self, *, provider: str, desktop_action_writer: WindowActionWriter, edge_provider: Any) -> None:
        self.provider = provider or "none"
        self.desktop_action_writer = desktop_action_writer
        self.edge_provider = edge_provider

    def open_workbench(self, *, reason: str) -> dict[str, Any]:
        if self.provider == "electron":
            return self.desktop_action_writer("open_workbench", {"reason": reason})
        if self.provider == "edge_app":
            return self.edge_provider.open_workbench(reason=reason)
        return {"ok": False, "provider": "none", "reason": "window_provider_unavailable"}

    def focus_workbench(self, *, reason: str) -> dict[str, Any]:
        if self.provider == "electron":
            return self.desktop_action_writer("focus_workbench", {"reason": reason})
        if self.provider == "edge_app":
            return self.edge_provider.focus_workbench(reason=reason)
        return {"ok": False, "provider": "none", "reason": "window_provider_unavailable"}
```

Add a focused test proving `provider="electron"` writes one Desktop Action and does not call the Edge provider.

- [ ] **Step 4: Update TypeScript API types**

Extend the workbench state types in `web/src/api/types.ts` with:

```ts
windowManaged: boolean;
windowProvider: "none" | "edge_app" | "electron";
windowId: number;
rendererProcessId: number;
windowProfileDir: string;
```

Keep `browserManaged` as an optional compatibility projection until Edge-specific UI tests are migrated.

- [ ] **Step 5: Verify**

Run:

```powershell
$env:TEMP="$PWD\\.tmp\\pytest-temp"; $env:TMP="$PWD\\.tmp\\pytest-temp"; pytest tests/test_runtime_manager.py tests/test_launcher_service.py tests/test_web_runtime_routes.py -k "launcher or workbench or browserManaged or window_provider_dispatcher" -q --basetemp "$PWD\\.tmp\\pytest-basetemp"
npm --prefix web test -- src/app/systemStatus.test.ts src/api/launcher.test.ts --run
npm --prefix web run build
```

Expected: focused pytest passes, dispatcher tests prove Electron and Edge paths are mutually exclusive, focused web tests pass, web build passes.

- [ ] **Step 6: Commit**

```powershell
git add core/launcher/window_provider_dispatcher.py core/runtime_manager/workbench_controller.py core/launcher/service.py core/web/services/runtime_service.py web/src/api/types.ts tests/test_runtime_manager.py tests/test_launcher_service.py tests/test_web_runtime_routes.py
git commit -m "feat: expose generic workbench window provider state"
```

### Task 6: Electron Window Provider

**Files:**
- Create: `desktop/electron/src/windows/windowProviderTypes.ts`
- Create: `desktop/electron/src/windows/electronWindowProvider.ts`
- Create: `desktop/electron/src/windows/launcherWindow.ts`
- Create: `desktop/electron/src/windows/workbenchWindow.ts`
- Create: `desktop/electron/src/security/urlPolicy.ts`
- Create: `desktop/electron/src/windows/desktopSessionClient.ts`
- Modify: `desktop/electron/src/main.ts`
- Test: `desktop/electron/tests/windowProvider.test.ts`
- Test: `desktop/electron/tests/desktopSessionClient.test.ts`

**Interfaces:**
- Consumes: resolved Launcher URL and Workbench URL from existing Launcher status, or explicit development/test environment overrides.
- Produces: an `ElectronWindowProvider` that owns BrowserWindow references, URL allowlist checks, duplicate open/focus behavior, renderer failure handling, and Desktop Session state reports.

- [ ] **Step 1: Add provider types**

Create `desktop/electron/src/windows/windowProviderTypes.ts`:

```ts
export type ElectronWindowRole = "launcher" | "workbench";

export type ManagedWindowState = {
  role: ElectronWindowRole;
  provider: "electron";
  open: boolean;
  focused: boolean;
  windowId: number;
  rendererProcessId: number;
  url: string;
};

export function closedWindowState(role: ElectronWindowRole): ManagedWindowState {
  return { role, provider: "electron", open: false, focused: false, windowId: 0, rendererProcessId: 0, url: "" };
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
      windowId: 0,
      rendererProcessId: 0,
      url: ""
    });
  });
});
```

- [ ] **Step 3: Implement URL policy**

Create `desktop/electron/src/security/urlPolicy.ts`:

```ts
export function assertLocalHttpUrl(rawUrl: string, expectedOrigin: string): string {
  const url = new URL(rawUrl);
  if (url.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(url.hostname)) {
    throw new Error(`blocked non-local URL: ${rawUrl}`);
  }
  if (url.origin !== expectedOrigin) {
    throw new Error(`blocked unexpected origin: ${url.origin}`);
  }
  return url.toString();
}
```

- [ ] **Step 4: Implement Launcher window factory**

Create `desktop/electron/src/windows/launcherWindow.ts`:

```ts
import { BrowserWindow } from "electron";
import type { DesktopPaths } from "../paths.js";
import { resolvePreloadPath } from "../paths.js";

export function createLauncherWindow(url: string, paths: DesktopPaths): BrowserWindow {
  const window = new BrowserWindow({
    width: 1180,
    height: 760,
    title: "Vibelution Launcher",
    webPreferences: {
      preload: resolvePreloadPath(paths),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });
  void window.loadURL(url);
  return window;
}
```

- [ ] **Step 5: Implement Workbench window factory**

Create `desktop/electron/src/windows/workbenchWindow.ts`:

```ts
import { BrowserWindow } from "electron";
import type { DesktopPaths } from "../paths.js";
import { resolvePreloadPath } from "../paths.js";

export function createWorkbenchWindow(url: string, paths: DesktopPaths): BrowserWindow {
  const window = new BrowserWindow({
    width: 1440,
    height: 960,
    title: "Vibelution Workbench",
    webPreferences: {
      preload: resolvePreloadPath(paths),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });
  void window.loadURL(url);
  return window;
}
```

- [ ] **Step 6: Implement ElectronWindowProvider**

Create `desktop/electron/src/windows/electronWindowProvider.ts` with a class that owns all BrowserWindow references:

```ts
import type { DesktopPaths } from "../paths.js";
import type { BrowserWindow } from "electron";
import { createLauncherWindow } from "./launcherWindow.js";
import { createWorkbenchWindow } from "./workbenchWindow.js";
import { closedWindowState, type ManagedWindowState } from "./windowProviderTypes.js";

export class ElectronWindowProvider {
  private launcherWindow: BrowserWindow | null = null;
  private workbenchWindow: BrowserWindow | null = null;

  constructor(
    private readonly paths: DesktopPaths,
    private readonly launcherUrl: string,
    private readonly workbenchUrl: string
  ) {}

  async openLauncher(): Promise<ManagedWindowState> {
    if (!this.launcherWindow || this.launcherWindow.isDestroyed()) {
      this.launcherWindow = createLauncherWindow(this.launcherUrl, this.paths);
    }
    this.launcherWindow.focus();
    return this.stateFor("launcher");
  }

  async openOrFocusWorkbench(): Promise<ManagedWindowState> {
    if (!this.workbenchWindow || this.workbenchWindow.isDestroyed()) {
      this.workbenchWindow = createWorkbenchWindow(this.workbenchUrl, this.paths);
    }
    this.workbenchWindow.focus();
    return this.stateFor("workbench");
  }

  async focusWorkbench(): Promise<ManagedWindowState> {
    if (!this.workbenchWindow || this.workbenchWindow.isDestroyed()) {
      return closedWindowState("workbench");
    }
    this.workbenchWindow.focus();
    return this.stateFor("workbench");
  }

  async closeWorkbench(): Promise<ManagedWindowState> {
    if (this.workbenchWindow && !this.workbenchWindow.isDestroyed()) {
      this.workbenchWindow.close();
    }
    return closedWindowState("workbench");
  }

  snapshot(): { launcher: ManagedWindowState; workbench: ManagedWindowState } {
    return {
      launcher: this.stateFor("launcher"),
      workbench: this.stateFor("workbench")
    };
  }

  private stateFor(role: "launcher" | "workbench"): ManagedWindowState {
    const window = role === "launcher" ? this.launcherWindow : this.workbenchWindow;
    if (!window || window.isDestroyed()) {
      return closedWindowState(role);
    }
    return {
      role,
      provider: "electron",
      open: true,
      focused: window.isFocused(),
      windowId: window.id,
      rendererProcessId: window.webContents.getOSProcessId(),
      url: window.webContents.getURL()
    };
  }
}
```

The implementation in this task must extend this minimal class with loadURL failure, `closed`, `focus`, `blur`, `render-process-gone`, `unresponsive`, URL allowlist checks, and Desktop Session state reporting before Gate 3 can pass.

- [ ] **Step 7: Add Desktop Session client**

Create `desktop/electron/src/windows/desktopSessionClient.ts`:

```ts
import type { ManagedWindowState } from "./windowProviderTypes.js";

export type DesktopSessionRegistration = {
  desktopSessionId: string;
  revision: number;
};

export async function reportDesktopWindowState(input: {
  launcherOrigin: string;
  controlToken: string;
  desktopSessionId: string;
  role: "launcher" | "workbench";
  revision: number;
  state: ManagedWindowState;
  fetchImpl?: typeof fetch;
}): Promise<DesktopSessionRegistration> {
  const fetcher = input.fetchImpl ?? fetch;
  const response = await fetcher(
    `${new URL(input.launcherOrigin).origin}/api/launcher/desktop-sessions/${encodeURIComponent(input.desktopSessionId)}/windows/${input.role}`,
    {
      method: "PUT",
      headers: {
        "content-type": "application/json",
        "X-Vibelution-Control-Token": input.controlToken
      },
      body: JSON.stringify({
        revision: input.revision,
        provider: input.state.provider,
        open: input.state.open,
        focused: input.state.focused,
        windowId: input.state.windowId,
        rendererProcessId: input.state.rendererProcessId,
        url: input.state.url
      })
    }
  );
  if (!response.ok) {
    throw new Error(`desktop session window update failed: ${response.status}`);
  }
  return (await response.json()) as DesktopSessionRegistration;
}
```

Create `desktop/electron/tests/desktopSessionClient.test.ts` with a mocked `fetchImpl` that proves:

```ts
await reportDesktopWindowState({
  launcherOrigin: "http://127.0.0.1:8765/launcher",
  controlToken: "token",
  desktopSessionId: "desktop-session-1",
  role: "workbench",
  revision: 7,
  state: {
    role: "workbench",
    provider: "electron",
    open: true,
    focused: true,
    windowId: 42,
    rendererProcessId: 4242,
    url: "http://127.0.0.1:8000"
  },
  fetchImpl
});
```

Expected request URL:

```text
http://127.0.0.1:8765/api/launcher/desktop-sessions/desktop-session-1/windows/workbench
```

- [ ] **Step 8: Resolve Launcher URL without production hard-coding**

Add a resolver before wiring the provider:

```ts
import { assertLocalHttpUrl } from "./security/urlPolicy.js";

export function resolveLauncherUrl(env: NodeJS.ProcessEnv, launcherStatusUrl?: string): string {
  const explicit = String(env.VIBELUTION_LAUNCHER_URL || "").trim();
  if (explicit) {
    return assertLocalHttpUrl(explicit, new URL(explicit).origin);
  }
  if (launcherStatusUrl) {
    return assertLocalHttpUrl(launcherStatusUrl, new URL(launcherStatusUrl).origin);
  }
  if (env.NODE_ENV === "test" || env.NODE_ENV === "development") {
    return "http://127.0.0.1:8765/launcher";
  }
  throw new Error("Launcher URL is not resolved; start through existing Launcher status or explicit dev override");
}
```

Add tests that prove production does not silently hard-code a port:

```ts
expect(() => resolveLauncherUrl({ NODE_ENV: "production" } as NodeJS.ProcessEnv)).toThrow(
  "Launcher URL is not resolved"
);
expect(resolveLauncherUrl({ VIBELUTION_LAUNCHER_URL: "http://127.0.0.1:9000/launcher" } as NodeJS.ProcessEnv)).toBe(
  "http://127.0.0.1:9000/launcher"
);
```

- [ ] **Step 9: Wire provider into main process**

Update `desktop/electron/src/main.ts` to open the Launcher URL first:

```ts
const launcherUrl = resolveLauncherUrl(process.env, existingLauncherStatus?.launcherUrl);
```

Use `createLauncherWindow(launcherUrl)` instead of loading `about:blank`.

- [ ] **Step 10: Verify**

Run:

```powershell
npm --prefix desktop/electron run build
npm --prefix desktop/electron test -- --run
```

Expected: Electron package builds and window provider tests pass.

- [ ] **Step 11: Commit**

```powershell
git add desktop/electron/src/windows desktop/electron/src/security/urlPolicy.ts desktop/electron/src/main.ts desktop/electron/tests/windowProvider.test.ts desktop/electron/tests/desktopSessionClient.test.ts
git commit -m "feat: add electron window provider"
```

### Task 7: Long-Lived Python Launcher Service Handshake

**Files:**
- Create: `desktop/electron/src/process/launcherBootstrap.ts`
- Create: `desktop/electron/src/process/launcherServiceClient.ts`
- Modify: `scripts/vibelution_desktop_entry.py`
- Modify: `desktop/electron/src/main.ts`
- Test: `tests/test_launcher_scripts.py`
- Test: `desktop/electron/tests/launcherServiceProcess.test.ts`

**Interfaces:**
- Consumes: existing `scripts/vibelution_desktop_entry.py` no-console backend startup, source-signature freshness, Launcher control health check, operator config resolution, and existing Launcher status API.
- Produces: Electron main can attach to or start exactly one Python Launcher Service, receive one bounded JSON bootstrap record, wait for authenticated readiness, and then load Launcher UI without directly starting backend, Runtime Manager, or workers.

Before implementation, verify the current helper surface:

```powershell
rg -n "_start_launcher_backend|_launcher_control_healthy|_launcher_backend_source_current|_save_launcher_state|desktop_entry_python.backend" scripts/vibelution_desktop_entry.py tests/test_launcher_scripts.py
```

Expected: the plan reuses and extends the existing desktop-entry helper instead of adding a second backend starter.

- [ ] **Step 1: Add bootstrap contract tests**

Add to `tests/test_launcher_scripts.py`:

```python
import json


def test_desktop_entry_bootstrap_json_reports_attached_or_started(monkeypatch, tmp_path, capsys):
    from scripts import vibelution_desktop_entry as entry

    monkeypatch.setattr(entry, "RUNTIME_DIR", tmp_path / ".runtime" / "launcher")
    monkeypatch.setattr(entry, "_launcher_control_port", lambda: 8765)
    monkeypatch.setattr(entry, "_source_signature", lambda: "sig-1")
    monkeypatch.setattr(entry, "_launcher_control_healthy", lambda port: True)
    monkeypatch.setattr(entry, "_launcher_backend_source_current", lambda state, pid, signature: True)
    monkeypatch.setattr(entry, "_read_state", lambda: {"launcherBackendPid": 1234, "launcherControlSourceSignature": "sig-1"})
    monkeypatch.setattr(entry, "_save_launcher_state", lambda *args, **kwargs: None)

    assert entry.main(["--action", "bootstrap", "--output", "json", "--workspace", str(tmp_path), "--config", "C:/operator/config.toml", "--no-browser"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["schemaVersion"] == 1
    assert payload["mode"] == "attached"
    assert payload["workspaceRoot"] == str(tmp_path)
    assert payload["operatorConfigPath"] == "C:/operator/config.toml"
    assert payload["launcherBackendPid"] == 1234
    assert payload["launcherUrl"].startswith("http://127.0.0.1:")
    assert payload["protocolVersion"] >= 1
    assert "desktop_actions.claim" in payload["capabilities"]
```

Run:

```powershell
$env:TEMP="$PWD\\.tmp\\pytest-temp"; $env:TMP="$PWD\\.tmp\\pytest-temp"; pytest tests/test_launcher_scripts.py -k "desktop_entry_bootstrap_json" -q --basetemp "$PWD\\.tmp\\pytest-basetemp"
```

Expected: failure because bootstrap JSON mode is not implemented yet.

- [ ] **Step 2: Extend the existing desktop entry to bootstrap JSON**

Modify `scripts/vibelution_desktop_entry.py`; do not create a new Python backend launcher. Add CLI flags and return one JSON object:

```python
parser.add_argument("--output", choices=("text", "json"), default="text")
parser.add_argument("--workspace", default="")
parser.add_argument("--config", default="")
```

Add a bootstrap result builder that uses the existing `_open_launcher`, `_launcher_control_url`, `_read_state`, `_launcher_backend_source_current`, and `_launcher_control_healthy` helpers:

```python
def _bootstrap_launcher(args: argparse.Namespace) -> dict[str, object]:
    before = _read_state()
    before_pid = int(before.get("launcherBackendPid") or 0)
    _open_launcher(args)
    after = _read_state()
    backend_pid = int(after.get("launcherBackendPid") or 0)
    port = int(after.get("launcherControlPort") or _launcher_control_port())
    mode = "attached" if before_pid > 0 and before_pid == backend_pid else "started"
    return {
        "schemaVersion": 1,
        "workspaceRoot": str(args.workspace or PROJECT_ROOT),
        "operatorConfigPath": str(args.config or ""),
        "workspaceId": str(after.get("workspaceId") or ""),
        "launcherInstanceId": str(after.get("sessionId") or ""),
        "mode": mode,
        "launcherBackendPid": backend_pid,
        "launcherUrl": _launcher_control_url(port),
        "workbenchUrl": str(after.get("url") or ""),
        "ready": _launcher_control_healthy(port),
        "protocolVersion": 1,
        "minDesktopProtocolVersion": 1,
        "maxDesktopProtocolVersion": 1,
        "capabilities": ["desktop_actions.claim", "desktop_sessions.heartbeat", "runtime_scene.electron_event"],
    }
```

When `--output json` is set, print exactly this JSON to stdout and send diagnostic text to existing log files or stderr. Do not print banners before or after the JSON object.

- [ ] **Step 3: Add Electron bootstrap types**

Create `desktop/electron/src/process/launcherBootstrap.ts`:

```ts
export type LauncherBootstrapMode = "attached" | "started";

export type LauncherBootstrapResult = {
  schemaVersion: 1;
  workspaceRoot: string;
  operatorConfigPath: string;
  workspaceId: string;
  launcherInstanceId: string;
  mode: LauncherBootstrapMode;
  launcherBackendPid: number;
  launcherUrl: string;
  workbenchUrl: string;
  ready: boolean;
  protocolVersion: number;
  minDesktopProtocolVersion: number;
  maxDesktopProtocolVersion: number;
  capabilities: string[];
};

export function parseLauncherBootstrap(raw: string): LauncherBootstrapResult {
  const parsed = JSON.parse(raw) as LauncherBootstrapResult;
  if (parsed.schemaVersion !== 1 || !parsed.ready || !parsed.launcherUrl || !parsed.workspaceRoot) {
    throw new Error("invalid launcher bootstrap result");
  }
  if (!parsed.capabilities.includes("desktop_actions.claim")) {
    throw new Error("launcher bootstrap is missing desktop action capability");
  }
  return parsed;
}
```

- [ ] **Step 4: Add bootstrap parser tests**

Create or extend `desktop/electron/tests/launcherServiceProcess.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { parseLauncherBootstrap } from "../src/process/launcherBootstrap.js";

describe("parseLauncherBootstrap", () => {
  it("accepts a ready bootstrap result with required capabilities", () => {
    const parsed = parseLauncherBootstrap(JSON.stringify({
      schemaVersion: 1,
      workspaceRoot: "C:/repo",
      operatorConfigPath: "C:/Users/17533/Documents/Vibelution/config/config.toml",
      workspaceId: "workspace-1",
      launcherInstanceId: "launcher-1",
      mode: "attached",
      launcherBackendPid: 1234,
      launcherUrl: "http://127.0.0.1:8765/launcher",
      workbenchUrl: "http://127.0.0.1:8000",
      ready: true,
      protocolVersion: 1,
      minDesktopProtocolVersion: 1,
      maxDesktopProtocolVersion: 1,
      capabilities: ["desktop_actions.claim", "desktop_sessions.heartbeat"]
    }));

    expect(parsed.mode).toBe("attached");
    expect(parsed.launcherBackendPid).toBe(1234);
  });

  it("rejects unready or capability-incomplete bootstrap output", () => {
    expect(() => parseLauncherBootstrap(JSON.stringify({
      schemaVersion: 1,
      workspaceRoot: "C:/repo",
      operatorConfigPath: "",
      workspaceId: "",
      launcherInstanceId: "",
      mode: "started",
      launcherBackendPid: 0,
      launcherUrl: "",
      workbenchUrl: "",
      ready: false,
      protocolVersion: 1,
      minDesktopProtocolVersion: 1,
      maxDesktopProtocolVersion: 1,
      capabilities: []
    }))).toThrow("invalid launcher bootstrap result");
  });
});
```

- [ ] **Step 5: Add Launcher Service client**

Create `desktop/electron/src/process/launcherServiceClient.ts`:

```ts
import { spawn } from "node:child_process";
import { resolve } from "node:path";
import { parseLauncherBootstrap, type LauncherBootstrapResult } from "./launcherBootstrap.js";

export type LauncherServiceStartInput = {
  workspaceRoot: string;
  pythonPath: string;
  operatorConfigPath: string;
};

export async function bootstrapPythonLauncherService(input: LauncherServiceStartInput): Promise<LauncherBootstrapResult> {
  const child = spawn(
    input.pythonPath,
    [
      resolve(input.workspaceRoot, "scripts", "vibelution_desktop_entry.py"),
      "--action",
      "bootstrap",
      "--output",
      "json",
      "--workspace",
      input.workspaceRoot,
      "--config",
      input.operatorConfigPath,
      "--no-browser"
    ],
    {
      cwd: input.workspaceRoot,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"]
    }
  );
  const stdout = await readBoundedStdout(child, 64_000);
  return parseLauncherBootstrap(stdout);
}

async function readBoundedStdout(child: ReturnType<typeof spawn>, maxBytes: number): Promise<string> {
  return await new Promise((resolveOutput, reject) => {
    const chunks: Buffer[] = [];
    let total = 0;
    child.stdout?.on("data", (chunk: Buffer) => {
      total += chunk.length;
      if (total > maxBytes) {
        child.kill();
        reject(new Error("launcher bootstrap output exceeded limit"));
        return;
      }
      chunks.push(chunk);
    });
    child.stderr?.on("data", () => {
      // Drain stderr so stdio pipes cannot deadlock; detailed logs stay in Python launcher log files.
    });
    child.once("error", reject);
    child.once("exit", (code) => {
      if (code !== 0) {
        reject(new Error(`launcher bootstrap exited with code ${code ?? "unknown"}`));
        return;
      }
      resolveOutput(Buffer.concat(chunks).toString("utf8"));
    });
  });
}
```

- [ ] **Step 6: Wire startup as attach-or-start**

Update Electron main so startup follows this order:

1. acquire Electron single-instance lock;
2. resolve `DesktopPaths.workspaceRoot` and external operator config through existing project contract;
3. call `bootstrapPythonLauncherService(...)`;
4. store `workspaceId`, `launcherInstanceId`, `mode`, protocol version, and capabilities in Electron state;
5. load Launcher window only after bootstrap `ready=true`;
6. on shutdown, stop only children that this Electron instance started; if `mode="attached"`, detach windows without killing the Python Launcher Service.

Keep process startup behind an environment switch during the first implementation:

```ts
const shouldStartLauncher = process.env.VIBELUTION_ELECTRON_START_LAUNCHER !== "0";
```

This prevents local developer runs from spawning runtime processes while unit tests compile the package. Runtime commands after readiness still go through Python Launcher/Runtime Manager APIs; Electron does not spawn `start`, `stop`, or `restart` scripts per action.

- [ ] **Step 7: Verify**

Run:

```powershell
npm --prefix desktop/electron run build
npm --prefix desktop/electron test -- --run
$env:TEMP="$PWD\\.tmp\\pytest-temp"; $env:TMP="$PWD\\.tmp\\pytest-temp"; pytest tests/test_launcher_scripts.py -k "desktop_entry_bootstrap_json" -q --basetemp "$PWD\\.tmp\\pytest-basetemp"
```

Expected: Electron build/tests pass, Python desktop entry returns exactly one bootstrap JSON object, unresolved Python/config values fail closed, and stderr/stdout cannot deadlock Electron startup.

- [ ] **Step 8: Commit**

```powershell
git add scripts/vibelution_desktop_entry.py desktop/electron/src/process desktop/electron/src/main.ts desktop/electron/tests/launcherServiceProcess.test.ts tests/test_launcher_scripts.py
git commit -m "feat: bootstrap electron through python launcher service"
```

### Task 8: Python Lifecycle Intent Store And Desktop Action Contract

**Files:**
- Create: `core/launcher/lifecycle_intent_store.py`
- Create: `core/launcher/lifecycle_action_dispatcher.py`
- Modify: `core/launcher/service.py`
- Modify: `core/web/routes/launcher.py`
- Modify: `tests/test_web_runtime_routes.py`
- Test: `tests/test_web_runtime_routes.py`

**Interfaces:**
- Consumes: existing Launcher active-work checks, Runtime Manager `core.runtime_manager.command_queue`, control-token guarded Launcher routes, runtime-scene logging, and trusted run/worktree context from the owning service.
- Produces: Python-owned `submit_lifecycle_intent(...)`, `claim_desktop_action(...)`, `ack_desktop_action(...)`, `fail_desktop_action(...)`, and `dispatch_runtime_effect_intent(...)` APIs. Electron and agents do not write lifecycle files, do not choose actor authority, and do not submit Runtime Manager commands directly.

Reuse-first requirement: before creating a new helper, inspect `core.runtime_manager.command_queue.claim_next_command`, `core.runtime_manager.command_queue.submit_command`, and `core.web.services.runtime_scene_service.record_runtime_scene_event`. Reuse their event naming, command payload shape, and redaction helpers where practical; add the Launcher SQLite store only because Desktop Actions require transactional leases and append-only JSONL cannot update pending rows safely.

- [ ] **Step 1: Write failing SQLite claim/lease tests**

Add a test to `tests/test_web_runtime_routes.py`:

```python
import sqlite3
from datetime import datetime, timedelta, timezone

from core.launcher import lifecycle_intent_store


def test_launcher_lifecycle_intent_claim_ack_updates_pending_row(tmp_path, monkeypatch):
    db_path = tmp_path / "launcher" / "lifecycle.sqlite3"
    monkeypatch.setattr(lifecycle_intent_store, "LIFECYCLE_DB_PATH", db_path)

    result = lifecycle_intent_store.submit_lifecycle_intent(
        {
            "action": "focus_workbench",
            "reason": "recover focus after apply",
            "idempotencyKey": "self-run-1:focus",
        },
        actor_context={
            "actorType": "self_evolution_agent",
            "actorId": "self-agent",
            "sourceRunId": "self-run-1",
            "sourceTaskId": "task-1",
            "sourceWorktree": str(tmp_path / "worktree"),
        },
        active_work_runs=[],
    )

    assert result["status"] == "accepted"
    claimed = lifecycle_intent_store.claim_desktop_action(
        desktop_session_id="desktop-session-1",
        lease_seconds=30,
    )
    assert claimed["action"] == "focus_workbench"
    assert claimed["status"] == "claimed"
    assert lifecycle_intent_store.claim_desktop_action(desktop_session_id="desktop-session-2", lease_seconds=30) == {}

    acked = lifecycle_intent_store.ack_desktop_action(
        claimed["actionId"],
        desktop_session_id="desktop-session-1",
        result={"windowId": 42, "rendererProcessId": 4242},
    )
    assert acked["status"] == "succeeded"
    assert lifecycle_intent_store.claim_desktop_action(desktop_session_id="desktop-session-1", lease_seconds=30) == {}


def test_launcher_lifecycle_intent_rejects_runtime_effects_during_active_work(tmp_path, monkeypatch):
    monkeypatch.setattr(lifecycle_intent_store, "LIFECYCLE_DB_PATH", tmp_path / "launcher" / "lifecycle.sqlite3")

    result = lifecycle_intent_store.submit_lifecycle_intent(
        {
            "action": "restart_after_apply",
            "reason": "apply completed",
            "idempotencyKey": "self-run-1:restart",
        },
        actor_context={
            "actorType": "self_evolution_agent",
            "actorId": "self-agent",
            "sourceRunId": "self-run-1",
            "sourceTaskId": "task-1",
            "sourceWorktree": str(tmp_path / "worktree"),
        },
        active_work_runs=[{"runId": "active-1", "status": "running"}],
    )

    assert result["status"] == "rejected"
    assert result["rejectionReason"] == "active_work_running"
    assert lifecycle_intent_store.claim_desktop_action(desktop_session_id="desktop-session-1", lease_seconds=30) == {}


def test_launcher_lifecycle_intent_releases_expired_desktop_action_lease(tmp_path, monkeypatch):
    db_path = tmp_path / "launcher" / "lifecycle.sqlite3"
    monkeypatch.setattr(lifecycle_intent_store, "LIFECYCLE_DB_PATH", db_path)
    lifecycle_intent_store.submit_lifecycle_intent(
        {"action": "open_workbench", "reason": "focus", "idempotencyKey": "run-1:open"},
        actor_context={"actorType": "desktop_supervisor", "actorId": "desktop-1", "sourceRunId": "", "sourceTaskId": "", "sourceWorktree": ""},
        active_work_runs=[],
    )
    first = lifecycle_intent_store.claim_desktop_action(desktop_session_id="desktop-session-1", lease_seconds=1)
    expired = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE desktop_actions SET lease_expires_at = ? WHERE action_id = ?",
            (expired, first["actionId"]),
        )

    second = lifecycle_intent_store.claim_desktop_action(desktop_session_id="desktop-session-2", lease_seconds=30)
    assert second["actionId"] == first["actionId"]
    assert second["claimAttempt"] == 2
```

Run:

```powershell
$env:TEMP="$PWD\\.tmp\\pytest-temp"; $env:TMP="$PWD\\.tmp\\pytest-temp"; pytest tests/test_web_runtime_routes.py -k "launcher_lifecycle_intent" -q --basetemp "$PWD\\.tmp\\pytest-basetemp"
```

Expected: failure because `core.launcher.lifecycle_intent_store` is not implemented.

- [ ] **Step 2: Implement Python-owned SQLite store**

Create `core/launcher/lifecycle_intent_store.py`:

```python
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.runtime_manager.constants import PROJECT_ROOT


LIFECYCLE_DB_PATH = PROJECT_ROOT / ".runtime" / "launcher" / "lifecycle.sqlite3"
DESKTOP_ACTIONS = {"open_workbench", "focus_workbench", "close_workbench"}
RUNTIME_EFFECT_ACTIONS = {"restart_after_apply", "resume_self_evolution", "recover_after_crash", "request_app_exit"}
ALLOWED_ACTIONS = DESKTOP_ACTIONS | RUNTIME_EFFECT_ACTIONS


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any, *, max_length: int = 500) -> str:
    return str(value or "").strip()[:max_length]


def _connect() -> sqlite3.Connection:
    LIFECYCLE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(LIFECYCLE_DB_PATH), timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS lifecycle_intents (
          intent_id TEXT PRIMARY KEY,
          schema_version INTEGER NOT NULL,
          action TEXT NOT NULL,
          status TEXT NOT NULL,
          actor_type TEXT NOT NULL,
          actor_id TEXT NOT NULL,
          reason TEXT NOT NULL,
          source_run_id TEXT NOT NULL,
          source_task_id TEXT NOT NULL,
          source_worktree TEXT NOT NULL,
          idempotency_key TEXT NOT NULL UNIQUE,
          rejection_reason TEXT NOT NULL DEFAULT '',
          command_id TEXT NOT NULL DEFAULT '',
          runtime_scene_ref TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS desktop_actions (
          action_id TEXT PRIMARY KEY,
          intent_id TEXT NOT NULL REFERENCES lifecycle_intents(intent_id),
          action TEXT NOT NULL,
          status TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          claimed_by TEXT NOT NULL DEFAULT '',
          claimed_at TEXT NOT NULL DEFAULT '',
          lease_expires_at TEXT NOT NULL DEFAULT '',
          claim_attempt INTEGER NOT NULL DEFAULT 0,
          result_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_desktop_actions_claim
          ON desktop_actions(status, lease_expires_at, created_at);
        """
    )


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    return dict(row) if row is not None else {}


def submit_lifecycle_intent(
    payload: dict[str, Any],
    *,
    actor_context: dict[str, Any],
    active_work_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    action = _safe_text(payload.get("action"), max_length=80)
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"unsupported lifecycle intent action: {action}")
    now = _now_iso()
    active_work_running = bool(active_work_runs) and action in RUNTIME_EFFECT_ACTIONS
    intent_id = f"intent-{uuid4().hex}"
    status = "rejected" if active_work_running else "accepted"
    intent = {
        "intentId": intent_id,
        "schemaVersion": 1,
        "action": action,
        "status": status,
        "actorType": _safe_text(actor_context.get("actorType"), max_length=80),
        "actorId": _safe_text(actor_context.get("actorId"), max_length=160),
        "reason": _safe_text(payload.get("reason"), max_length=300),
        "sourceRunId": _safe_text(actor_context.get("sourceRunId"), max_length=160),
        "sourceTaskId": _safe_text(actor_context.get("sourceTaskId"), max_length=160),
        "sourceWorktree": _safe_text(actor_context.get("sourceWorktree")),
        "idempotencyKey": _safe_text(payload.get("idempotencyKey"), max_length=240),
        "createdAt": now,
        "updatedAt": now,
        "rejectionReason": "active_work_running" if active_work_running else "",
        "commandId": "",
        "runtimeSceneRef": "",
    }
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM lifecycle_intents WHERE idempotency_key = ?",
            (intent["idempotencyKey"],),
        ).fetchone()
        if existing is not None:
            conn.execute("COMMIT")
            return _public_intent(_row_to_dict(existing))
        conn.execute(
            """
            INSERT INTO lifecycle_intents (
              intent_id, schema_version, action, status, actor_type, actor_id, reason,
              source_run_id, source_task_id, source_worktree, idempotency_key,
              rejection_reason, command_id, runtime_scene_ref, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                intent_id, 1, action, status, intent["actorType"], intent["actorId"], intent["reason"],
                intent["sourceRunId"], intent["sourceTaskId"], intent["sourceWorktree"], intent["idempotencyKey"],
                intent["rejectionReason"], "", "", now, now,
            ),
        )
        if status == "accepted" and action in DESKTOP_ACTIONS:
            conn.execute(
                """
                INSERT INTO desktop_actions (
                  action_id, intent_id, action, status, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, 'pending', ?, ?, ?)
                """,
                (
                    f"desktop-action-{uuid4().hex}",
                    intent_id,
                    action,
                    json.dumps({"sourceRunId": intent["sourceRunId"], "sourceTaskId": intent["sourceTaskId"]}, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )
        conn.execute("COMMIT")
    return intent


def _public_intent(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "intentId": row.get("intent_id"),
        "schemaVersion": int(row.get("schema_version") or 1),
        "action": row.get("action"),
        "status": row.get("status"),
        "rejectionReason": row.get("rejection_reason") or "",
        "commandId": row.get("command_id") or "",
        "runtimeSceneRef": row.get("runtime_scene_ref") or "",
        "createdAt": row.get("created_at"),
        "updatedAt": row.get("updated_at"),
    }


def claim_desktop_action(*, desktop_session_id: str, lease_seconds: int = 30) -> dict[str, Any]:
    now = _now_iso()
    lease_expires_at = datetime.now(timezone.utc).timestamp() + max(1, int(lease_seconds))
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT * FROM desktop_actions
            WHERE status = 'pending' OR (status = 'claimed' AND lease_expires_at < ? AND claim_attempt < 3)
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (now,),
        ).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return {}
        action_id = str(row["action_id"])
        expires_iso = datetime.fromtimestamp(lease_expires_at, tz=timezone.utc).isoformat()
        conn.execute(
            """
            UPDATE desktop_actions
            SET status = 'claimed',
                claimed_by = ?,
                claimed_at = ?,
                lease_expires_at = ?,
                claim_attempt = claim_attempt + 1,
                updated_at = ?
            WHERE action_id = ?
            """,
            (desktop_session_id, now, expires_iso, now, action_id),
        )
        claimed = conn.execute("SELECT * FROM desktop_actions WHERE action_id = ?", (action_id,)).fetchone()
        conn.execute("COMMIT")
    return _public_desktop_action(claimed)


def ack_desktop_action(action_id: str, *, desktop_session_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return _finish_desktop_action(action_id, desktop_session_id=desktop_session_id, status="succeeded", result=result)


def fail_desktop_action(action_id: str, *, desktop_session_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return _finish_desktop_action(action_id, desktop_session_id=desktop_session_id, status="failed", result=result)


def _finish_desktop_action(action_id: str, *, desktop_session_id: str, status: str, result: dict[str, Any]) -> dict[str, Any]:
    now = _now_iso()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM desktop_actions WHERE action_id = ? AND status = 'claimed' AND claimed_by = ?",
            (_safe_text(action_id, max_length=160), _safe_text(desktop_session_id, max_length=160)),
        ).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return {}
        conn.execute(
            """
            UPDATE desktop_actions
            SET status = ?, result_json = ?, updated_at = ?
            WHERE action_id = ?
            """,
            (status, json.dumps(result, ensure_ascii=False, sort_keys=True), now, action_id),
        )
        updated = conn.execute("SELECT * FROM desktop_actions WHERE action_id = ?", (action_id,)).fetchone()
        conn.execute("COMMIT")
    return _public_desktop_action(updated)


def _public_desktop_action(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    return {
        "actionId": row["action_id"],
        "intentId": row["intent_id"],
        "action": row["action"],
        "status": row["status"],
        "payload": json.loads(row["payload_json"]),
        "claimedBy": row["claimed_by"],
        "leaseExpiresAt": row["lease_expires_at"],
        "claimAttempt": int(row["claim_attempt"] or 0),
        "result": json.loads(row["result_json"] or "{}"),
    }
```

- [ ] **Step 3: Add runtime-effect dispatcher**

Create `core/launcher/lifecycle_action_dispatcher.py`:

```python
from __future__ import annotations

from typing import Any

from core.runtime_manager import command_queue


RUNTIME_ACTION_COMMANDS = {
    "restart_after_apply": "hot_restart_workbench",
    "resume_self_evolution": "resume_self_evolution",
    "recover_after_crash": "recover_workbench",
    "request_app_exit": "close_workbench",
}


def dispatch_runtime_effect_intent(intent: dict[str, Any]) -> dict[str, Any]:
    action = str(intent.get("action") or "").strip()
    command_type = RUNTIME_ACTION_COMMANDS.get(action)
    if not command_type:
        return {"dispatched": False, "reason": "not_runtime_effect"}
    result = command_queue.submit_command(
        command_type,
        requested_by=str(intent.get("actorType") or "launcher_lifecycle"),
        args={
            "reason": str(intent.get("reason") or action),
            "sourceRunId": str(intent.get("sourceRunId") or ""),
            "sourceTaskId": str(intent.get("sourceTaskId") or ""),
            "sourceWorktree": str(intent.get("sourceWorktree") or ""),
            "lifecycleIntentId": str(intent.get("intentId") or ""),
        },
    )
    return {"dispatched": True, "commandId": str(result.get("commandId") or ""), "accepted": bool(result.get("accepted", True))}
```

If the existing command queue exposes a differently named submission helper, use that helper and adjust the test in the same task. Do not add a new direct Runtime Manager subprocess path.

- [ ] **Step 4: Add guarded Launcher routes**

Modify `core/web/routes/launcher.py`:

```python
from core.launcher import lifecycle_intent_store


class LifecycleIntentPayload(BaseModel):
    action: str
    reason: str = ""
    idempotencyKey: str


class DesktopActionClaimPayload(BaseModel):
    desktopSessionId: str
    leaseSeconds: int = 30


class DesktopActionResultPayload(BaseModel):
    desktopSessionId: str
    result: dict = Field(default_factory=dict)


@router.post("/launcher/lifecycle-intents", status_code=202)
def launcher_submit_lifecycle_intent(payload: LifecycleIntentPayload) -> dict:
    try:
        return launcher_service.submit_lifecycle_intent(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_lifecycle_intent", "message": str(exc)}) from exc


@router.post("/launcher/desktop-actions/claim")
def launcher_claim_desktop_action(payload: DesktopActionClaimPayload) -> dict:
    return launcher_service.claim_desktop_action(payload.desktopSessionId, lease_seconds=payload.leaseSeconds)


@router.post("/launcher/desktop-actions/{action_id}/ack", status_code=202)
def launcher_ack_desktop_action(action_id: str, payload: DesktopActionResultPayload) -> dict:
    return launcher_service.ack_desktop_action(action_id, payload.desktopSessionId, payload.result)


@router.post("/launcher/desktop-actions/{action_id}/fail", status_code=202)
def launcher_fail_desktop_action(action_id: str, payload: DesktopActionResultPayload) -> dict:
    return launcher_service.fail_desktop_action(action_id, payload.desktopSessionId, payload.result)
```

Add thin service wrappers to `core/launcher/service.py` so route code does not bypass Launcher active-work policy. The service must derive actor/source context from trusted local state, current run, desktop session, or authenticated internal caller, not from client payload fields:

```python
from core.launcher import lifecycle_intent_store


def submit_lifecycle_intent(payload: dict[str, Any], *, actor_context: dict[str, Any] | None = None) -> dict[str, Any]:
    return lifecycle_intent_store.submit_lifecycle_intent(
        payload,
        actor_context=actor_context or trusted_lifecycle_actor_context(),
        active_work_runs=launcher_active_work_runs(),
    )


def claim_desktop_action(desktop_session_id: str, *, lease_seconds: int = 30) -> dict[str, Any]:
    return lifecycle_intent_store.claim_desktop_action(
        desktop_session_id=desktop_session_id,
        lease_seconds=lease_seconds,
    )


def ack_desktop_action(action_id: str, desktop_session_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return lifecycle_intent_store.ack_desktop_action(action_id, desktop_session_id=desktop_session_id, result=result)


def fail_desktop_action(action_id: str, desktop_session_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return lifecycle_intent_store.fail_desktop_action(action_id, desktop_session_id=desktop_session_id, result=result)
```

- [ ] **Step 5: Verify**

Run:

```powershell
$env:TEMP="$PWD\\.tmp\\pytest-temp"; $env:TMP="$PWD\\.tmp\\pytest-temp"; pytest tests/test_web_runtime_routes.py -k "launcher_lifecycle_intent_claim_ack_updates_pending_row or launcher_lifecycle_intent_rejects_runtime_effects_during_active_work or launcher_lifecycle_intent_releases_expired_desktop_action_lease or launcher_control_token or active_work" -q --basetemp "$PWD\\.tmp\\pytest-basetemp"
```

Expected: lifecycle intent tests pass, Launcher route token/active-work behavior remains guarded, a claimed action cannot be claimed again until its lease expires, ack/fail updates the claimed row instead of appending a second result, runtime-effect actions dispatch through Python Runtime Manager paths, and no Electron file writer exists for intents.

- [ ] **Step 6: Commit**

```powershell
git add core/launcher/lifecycle_intent_store.py core/launcher/lifecycle_action_dispatcher.py core/launcher/service.py core/web/routes/launcher.py tests/test_web_runtime_routes.py
git commit -m "feat: add python-owned lifecycle intent actions"
```

### Task 9: Self-Evolution Lifecycle Intent Integration

**Files:**
- Modify: `core/web/services/self_evolution_control_service.py`
- Modify: `tests/test_web_runtime_routes.py`
- Test: `tests/test_web_runtime_routes.py`

**Interfaces:**
- Consumes: existing self-evolution run state and Task 8 `launcher_service.submit_lifecycle_intent(...)`.
- Produces: structured lifecycle requests from self-evolution without direct process control or direct JSONL writes.

- [ ] **Step 1: Write failing service test**

Add to `tests/test_web_runtime_routes.py`:

```python
def test_self_evolution_restart_request_uses_launcher_lifecycle_service(monkeypatch):
    captured: dict[str, object] = {}
    captured_context: dict[str, object] = {}

    def fake_submit(payload: dict[str, object], *, actor_context: dict[str, object]) -> dict[str, object]:
        captured.update(payload)
        captured_context.update(actor_context)
        return {"intentId": "intent-1", "status": "accepted", "action": payload["action"]}

    monkeypatch.setattr(self_evolution_control_service.launcher_service, "submit_lifecycle_intent", fake_submit)

    result = self_evolution_control_service.request_lifecycle_intent(
        action="restart_after_apply",
        reason="apply completed",
        run_id="self-run-1",
        task_id="task-1",
        worktree="C:/worktree",
    )

    assert result["intentId"] == "intent-1"
    assert captured["action"] == "restart_after_apply"
    assert captured_context["actorType"] == "self_evolution_agent"
    assert captured_context["sourceRunId"] == "self-run-1"
```

- [ ] **Step 2: Implement self-evolution adapter**

Add or update `core/web/services/self_evolution_control_service.py`:

```python
from core.launcher import service as launcher_service


def request_lifecycle_intent(*, action: str, reason: str, run_id: str, task_id: str, worktree: str) -> dict[str, Any]:
    return launcher_service.submit_lifecycle_intent(
        {
            "action": action,
            "reason": reason,
            "idempotencyKey": f"{run_id}:{action}",
        },
        actor_context={
            "actorType": "self_evolution_agent",
            "actorId": "self-evolution",
            "sourceRunId": run_id,
            "sourceTaskId": task_id,
            "sourceWorktree": worktree,
        },
    )
```

- [ ] **Step 3: Verify**

Run:

```powershell
$env:TEMP="$PWD\\.tmp\\pytest-temp"; $env:TMP="$PWD\\.tmp\\pytest-temp"; pytest tests/test_web_runtime_routes.py -k "self_evolution_restart_request_uses_launcher_lifecycle_service or launcher_lifecycle_intent" -q --basetemp "$PWD\\.tmp\\pytest-basetemp"
```

Expected: self-evolution uses Launcher service as the only lifecycle writer and existing Launcher lifecycle tests still pass.

- [ ] **Step 4: Commit**

```powershell
git add core/web/services/self_evolution_control_service.py tests/test_web_runtime_routes.py
git commit -m "feat: route self-evolution lifecycle intents through launcher"
```

### Task 10: Electron Consumes Approved Desktop Actions

**Files:**
- Create: `desktop/electron/src/protocol/desktopActionClient.ts`
- Modify: `desktop/electron/src/main.ts`
- Test: `desktop/electron/tests/desktopActionClient.test.ts`

**Interfaces:**
- Consumes: Task 8 guarded Launcher Desktop Action API.
- Produces: Electron claims one approved desktop action at a time, executes only BrowserWindow operations (`open_workbench`, `focus_workbench`, `close_workbench`), and returns `ack` or `fail` against the same leased row. Runtime-effect actions remain Python Launcher/Runtime Manager responsibilities.

- [ ] **Step 1: Add action mapping tests**

Create `desktop/electron/tests/desktopActionClient.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  desktopWindowOperationForAction,
  launcherDesktopActionEndpoints
} from "../src/protocol/desktopActionClient.js";

describe("desktopWindowOperationForAction", () => {
  it("maps approved desktop actions to window operations", () => {
    expect(desktopWindowOperationForAction("open_workbench")).toBe("open_or_focus_workbench");
    expect(desktopWindowOperationForAction("focus_workbench")).toBe("focus_workbench");
    expect(desktopWindowOperationForAction("close_workbench")).toBe("close_workbench");
  });

  it("does not map runtime-effect actions into Electron process commands", () => {
    expect(desktopWindowOperationForAction("restart_after_apply")).toBe("none");
    expect(desktopWindowOperationForAction("recover_after_crash")).toBe("none");
  });

  it("uses claim ack fail endpoints instead of next polling", () => {
    expect(launcherDesktopActionEndpoints("http://127.0.0.1:8765")).toEqual({
      claim: "http://127.0.0.1:8765/api/launcher/desktop-actions/claim",
      ack: "http://127.0.0.1:8765/api/launcher/desktop-actions/{actionId}/ack",
      fail: "http://127.0.0.1:8765/api/launcher/desktop-actions/{actionId}/fail"
    });
  });
});
```

- [ ] **Step 2: Implement Desktop Action client types and endpoints**

Create `desktop/electron/src/protocol/desktopActionClient.ts`:

```ts
export type DesktopActionName =
  | "open_workbench"
  | "focus_workbench"
  | "close_workbench"
  | "restart_after_apply"
  | "recover_after_crash";

export type DesktopWindowOperation = "open_or_focus_workbench" | "focus_workbench" | "close_workbench" | "none";

export type DesktopAction = {
  actionId: string;
  intentId: string;
  action: DesktopActionName;
  status: "claimed";
  payload: Record<string, string>;
  claimedBy: string;
  leaseExpiresAt: string;
  claimAttempt: number;
};

export function desktopWindowOperationForAction(action: string): DesktopWindowOperation {
  if (action === "open_workbench") {
    return "open_or_focus_workbench";
  }
  if (action === "focus_workbench") {
    return "focus_workbench";
  }
  if (action === "close_workbench") {
    return "close_workbench";
  }
  return "none";
}

export function launcherDesktopActionEndpoints(launcherOrigin: string) {
  const origin = new URL(launcherOrigin).origin;
  return {
    claim: `${origin}/api/launcher/desktop-actions/claim`,
    ack: `${origin}/api/launcher/desktop-actions/{actionId}/ack`,
    fail: `${origin}/api/launcher/desktop-actions/{actionId}/fail`
  };
}

export async function claimDesktopAction(input: {
  launcherOrigin: string;
  controlToken: string;
  desktopSessionId: string;
  leaseSeconds: number;
  fetchImpl?: typeof fetch;
}): Promise<DesktopAction | null> {
  const fetcher = input.fetchImpl ?? fetch;
  const response = await fetcher(launcherDesktopActionEndpoints(input.launcherOrigin).claim, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "X-Vibelution-Control-Token": input.controlToken
    },
    body: JSON.stringify({ desktopSessionId: input.desktopSessionId, leaseSeconds: input.leaseSeconds })
  });
  if (!response.ok) {
    throw new Error(`desktop action claim failed: ${response.status}`);
  }
  const payload = (await response.json()) as DesktopAction | Record<string, never>;
  return Object.keys(payload).length === 0 ? null : (payload as DesktopAction);
}

export async function finishDesktopAction(input: {
  launcherOrigin: string;
  controlToken: string;
  actionId: string;
  desktopSessionId: string;
  status: "ack" | "fail";
  result: Record<string, unknown>;
  fetchImpl?: typeof fetch;
}): Promise<void> {
  const fetcher = input.fetchImpl ?? fetch;
  const template = input.status === "ack"
    ? launcherDesktopActionEndpoints(input.launcherOrigin).ack
    : launcherDesktopActionEndpoints(input.launcherOrigin).fail;
  const response = await fetcher(template.replace("{actionId}", encodeURIComponent(input.actionId)), {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "X-Vibelution-Control-Token": input.controlToken
    },
    body: JSON.stringify({ desktopSessionId: input.desktopSessionId, result: input.result })
  });
  if (!response.ok) {
    throw new Error(`desktop action ${input.status} failed: ${response.status}`);
  }
}
```

- [ ] **Step 3: Add Electron action loop**

In `desktop/electron/src/main.ts`, add a bounded loop that:

1. calls `POST /api/launcher/desktop-actions/claim` with the existing control token and `desktopSessionId`;
2. maps the action through `desktopWindowOperationForAction`;
3. executes only BrowserWindow operations;
4. posts `POST /api/launcher/desktop-actions/{actionId}/ack` on success;
5. posts `POST /api/launcher/desktop-actions/{actionId}/fail` on failure;
6. treats unknown/runtime-effect actions as `fail` with `reason="unsupported_desktop_action"`;
7. does not read `.runtime/launcher/lifecycle.sqlite3` directly;
8. does not read legacy `.runtime/launcher/lifecycle-intents/*.jsonl`;
9. does not spawn Runtime Manager or worker processes.

Use a conservative interval:

```ts
const DESKTOP_ACTION_POLL_MS = 2000;
const DESKTOP_ACTION_LEASE_SECONDS = 30;
```

- [ ] **Step 4: Verify**

Run:

```powershell
npm --prefix desktop/electron run build
npm --prefix desktop/electron test -- --run
```

Expected: desktop action mapping and endpoint tests pass, build remains strict, Electron tests prove claim/ack/fail behavior, and no Electron test imports a lifecycle intent store or Runtime Manager command queue.

- [ ] **Step 5: Commit**

```powershell
git add desktop/electron/src/protocol/desktopActionClient.ts desktop/electron/src/main.ts desktop/electron/tests/desktopActionClient.test.ts
git commit -m "feat: consume launcher-approved desktop actions"
```

### Task 11: Security And IPC Boundary

**Files:**
- Modify: `desktop/electron/src/preload.ts`
- Create: `desktop/electron/src/ipc.ts`
- Create: `desktop/electron/src/security/ipcSenderValidation.ts`
- Create: `desktop/electron/src/shutdown/shutdownCoordinator.ts`
- Modify: `desktop/electron/src/main.ts`
- Test: `desktop/electron/tests/shutdownCoordinator.test.ts`
- Test: `desktop/electron/tests/windowProvider.test.ts`

**Interfaces:**
- Consumes: Electron IPC, verified local Launcher origin, Task 7 bootstrap ownership mode, and Python Launcher active-work status.
- Produces: narrow renderer-to-main desktop-shell bridge, validated IPC sender origin, and one shutdown path that cannot bypass active-work guard.

- [ ] **Step 1: Add IPC channel constants**

Create `desktop/electron/src/ipc.ts`:

```ts
export const IPC_CHANNELS = {
  getVersion: "launcher:get-version",
  getDesktopShellSummary: "launcher:get-desktop-shell-summary",
  focusWorkbenchWindow: "launcher:focus-workbench-window",
  requestDesktopShellExit: "launcher:request-desktop-shell-exit"
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
  getDesktopShellSummary: () => ipcRenderer.invoke(IPC_CHANNELS.getDesktopShellSummary),
  focusWorkbenchWindow: () => ipcRenderer.invoke(IPC_CHANNELS.focusWorkbenchWindow),
  requestDesktopShellExit: () => ipcRenderer.invoke(IPC_CHANNELS.requestDesktopShellExit)
});
```

`getDesktopShellSummary` may return only Electron shell facts such as window role, focus state, desktop session id, provider, revision, and bootstrap capability summary. It must not return Python lifecycle queues, active-work internals, Runtime Manager command state, or lifecycle intent records. Runtime lifecycle state visible to the web UI must continue to come from the existing authenticated Launcher/FastAPI routes.

- [ ] **Step 3: Add IPC sender validation**

Create `desktop/electron/src/security/ipcSenderValidation.ts`:

```ts
import type { IpcMainInvokeEvent } from "electron";

export function assertTrustedIpcSender(event: IpcMainInvokeEvent, allowedOrigins: string[]): void {
  const origin = new URL(event.senderFrame.url).origin;
  if (!allowedOrigins.includes(origin)) {
    throw new Error(`blocked ipc sender origin: ${origin}`);
  }
}
```

Register every IPC handler in `desktop/electron/src/main.ts` through this validator:

```ts
ipcMain.handle(IPC_CHANNELS.focusWorkbenchWindow, async (event) => {
  assertTrustedIpcSender(event, [launcherOrigin, workbenchOrigin]);
  return await electronWindowProvider.focusWorkbench();
});
```

Renderer IPC must not accept arbitrary URLs, process IDs, command names, Python paths, workspace paths, lifecycle action payloads, runtime action names, or Desktop Action ids. IPC handlers may request local window focus/navigation or request the desktop shell exit flow, but the exit flow must still call Python active-work status through `ShutdownCoordinator`.

- [ ] **Step 4: Add ShutdownCoordinator**

Create `desktop/electron/src/shutdown/shutdownCoordinator.ts`:

```ts
export type BootstrapOwnershipMode = "attached" | "started";

export type ActiveWorkStatus = {
  active: boolean;
  message: string;
};

export type ShutdownDecision =
  | { allowed: true; reason: "no_active_work"; stopPythonLauncher: boolean }
  | { allowed: false; reason: "active_work_running"; message: string };

export async function decideShutdown(input: {
  ownershipMode: BootstrapOwnershipMode;
  activeWorkStatus: () => Promise<ActiveWorkStatus>;
}): Promise<ShutdownDecision> {
  const activeWork = await input.activeWorkStatus();
  if (activeWork.active) {
    return {
      allowed: false,
      reason: "active_work_running",
      message: "有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。"
    };
  }
  return {
    allowed: true,
    reason: "no_active_work",
    stopPythonLauncher: input.ownershipMode === "started"
  };
}
```

Wire `before-quit`, `window-all-closed`, Launcher window close, renderer `requestDesktopShellExit`, and second-instance shutdown requests through `decideShutdown(...)`. `window-all-closed` must not call `app.quit()` directly.

- [ ] **Step 5: Add coordinator tests**

Create `desktop/electron/tests/shutdownCoordinator.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { decideShutdown } from "../src/shutdown/shutdownCoordinator.js";

describe("decideShutdown", () => {
  it("blocks shutdown while active work exists", async () => {
    await expect(decideShutdown({
      ownershipMode: "started",
      activeWorkStatus: async () => ({ active: true, message: "running" })
    })).resolves.toEqual({
      allowed: false,
      reason: "active_work_running",
      message: "有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。"
    });
  });

  it("detaches from attached launcher service without stopping it", async () => {
    await expect(decideShutdown({
      ownershipMode: "attached",
      activeWorkStatus: async () => ({ active: false, message: "" })
    })).resolves.toEqual({
      allowed: true,
      reason: "no_active_work",
      stopPythonLauncher: false
    });
  });
});
```

- [ ] **Step 6: Add channel test**

Append to `desktop/electron/tests/windowProvider.test.ts`:

```ts
import { IPC_CHANNELS } from "../src/ipc.js";

describe("IPC channels", () => {
  it("keeps the bridge narrow", () => {
    expect(Object.keys(IPC_CHANNELS).sort()).toEqual([
      "focusWorkbenchWindow",
      "getDesktopShellSummary",
      "getVersion",
      "requestDesktopShellExit"
    ]);
  });
});
```

- [ ] **Step 7: Verify**

Run:

```powershell
npm --prefix desktop/electron run build
npm --prefix desktop/electron test -- --run
```

Expected: bridge and shutdown tests pass, no Node APIs are exposed to renderer, untrusted sender origins are rejected, and no Electron close path bypasses Launcher active-work status.

- [ ] **Step 8: Commit**

```powershell
git add desktop/electron/src/preload.ts desktop/electron/src/ipc.ts desktop/electron/src/security/ipcSenderValidation.ts desktop/electron/src/shutdown/shutdownCoordinator.ts desktop/electron/src/main.ts desktop/electron/tests/windowProvider.test.ts desktop/electron/tests/shutdownCoordinator.test.ts
git commit -m "feat: guard electron ipc and shutdown"
```

### Task 12: Packaging Skeleton

**Files:**
- Create: `desktop/electron/electron-builder.json`
- Modify: `desktop/electron/package.json`
- Create: `scripts/build_desktop_package.ps1`
- Test: package directory smoke only; no installer or zero-dependency claim in version 1

**Interfaces:**
- Consumes: Electron desktop build output and an external Vibelution workspace/config at runtime.
- Produces: a local `win-unpacked` Electron shell that starts or attaches to the existing workspace-bound Python Launcher Service. It does not bundle Python, backend source, requirements, or a writable workspace.

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
  "win": {
    "target": ["dir"],
    "artifactName": "Vibelution-${version}-${arch}.${ext}"
  }
}
```

Do not add `core/`, `scripts/`, `requirements.txt`, or `web/dist` to `extraResources` in V1. Runtime code, web UI, Python, and operator config remain in the external workspace until a separate V2 bundled-runtime plan handles dependency freezing, writable data directories, update, and rollback.

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
npm --prefix (Join-Path $projectDir "desktop/electron") install
npm --prefix (Join-Path $projectDir "desktop/electron") run package:dir
```

- [ ] **Step 4: Verify**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_desktop_package.ps1
```

Expected: `dist/desktop/win-unpacked` or equivalent directory target is produced, and the package contains Electron desktop files only. It must not contain copied `core/`, `scripts/`, `requirements.txt`, root `config.toml`, or `config.example.toml`.

- [ ] **Step 5: Commit**

```powershell
git add desktop/electron/electron-builder.json desktop/electron/package.json desktop/electron/package-lock.json scripts/build_desktop_package.ps1
git commit -m "build: add electron desktop package skeleton"
```

### Task 13: Runtime Scene Evidence For Electron Supervisor

**Files:**
- Create: `desktop/electron/src/lifecycle/runtimeSceneBridge.ts`
- Modify: `core/web/routes/launcher.py`
- Modify: `core/web/services/runtime_scene_service.py`
- Modify: `tests/test_web_runtime_routes.py`
- Test: `desktop/electron/tests/runtimeSceneBridge.test.ts`
- Test: `tests/test_web_runtime_routes.py`

**Interfaces:**
- Consumes: existing runtime-scene package structure.
- Produces: bounded evidence for Electron supervisor lifecycle decisions through an authenticated Launcher route with retry and bounded offline buffering.

- [ ] **Step 1: Define event names**

Use these event codes:

```text
electron.launcher.supervisor.started
electron.launcher.window.opened
electron.workbench.window.opened
electron.launcher_service.started
electron.launcher_service.exited
electron.desktop_action.claimed
electron.desktop_action.succeeded
electron.desktop_action.failed
```

- [ ] **Step 2: Add backend helper test**

In `tests/test_web_runtime_routes.py`, add a route test that posts an Electron supervisor event through `POST /api/launcher/runtime-scene/events` and verifies it appears in `timeline.jsonl` and a bounded event file.

```python
def test_launcher_runtime_scene_event_records_electron_supervisor_event(tmp_path, monkeypatch):
    scene_dir = _seed_runtime_scene_bundle(tmp_path, scene_id="scene-electron", status="running")
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "LAUNCHER_STATE_PATH", tmp_path / ".runtime" / "launcher" / "state.json")

    response = client.post(
        "/api/launcher/runtime-scene/events",
        json={
            "eventCode": "electron.desktop_action.claimed",
            "message": "Desktop action claimed.",
            "fields": {"actionId": "desktop-action-1", "desktopSessionId": "desktop-session-1"},
        },
    )

    assert response.status_code == 202
    timeline = (scene_dir / "timeline.jsonl").read_text(encoding="utf-8")
    assert "electron.desktop_action.claimed" in timeline
```

Add route handling in `core/web/routes/launcher.py` that delegates to `runtime_scene_service.record_runtime_scene_event(component="electron_launcher", phase="desktop_supervisor", ...)`; keep the existing control-token guard and field redaction.

- [ ] **Step 3: Add Electron bridge**

Create `desktop/electron/src/lifecycle/runtimeSceneBridge.ts`:

```ts
export type RuntimeSceneElectronEvent = {
  eventCode: string;
  message: string;
  fields: Record<string, string | number | boolean>;
};

export type RuntimeSceneBridgeOptions = {
  launcherOrigin: string;
  controlToken: string;
  maxBufferedEvents: number;
  fetchImpl?: typeof fetch;
};

export function electronEventPayload(event: RuntimeSceneElectronEvent) {
  return {
    component: "electron_launcher",
    phase: "desktop_supervisor",
    eventCode: event.eventCode,
    message: event.message,
    fields: event.fields
  };
}

export class RuntimeSceneBridge {
  private readonly queue: RuntimeSceneElectronEvent[] = [];

  constructor(private readonly options: RuntimeSceneBridgeOptions) {}

  async record(event: RuntimeSceneElectronEvent): Promise<void> {
    const bounded = this.bound(event);
    try {
      await this.post(bounded);
      await this.flush();
    } catch {
      this.queue.push(bounded);
      while (this.queue.length > this.options.maxBufferedEvents) {
        this.queue.shift();
      }
    }
  }

  async flush(): Promise<void> {
    while (this.queue.length > 0) {
      const next = this.queue[0];
      await this.post(next);
      this.queue.shift();
    }
  }

  private async post(event: RuntimeSceneElectronEvent): Promise<void> {
    const fetcher = this.options.fetchImpl ?? fetch;
    const response = await fetcher(`${new URL(this.options.launcherOrigin).origin}/api/launcher/runtime-scene/events`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "X-Vibelution-Control-Token": this.options.controlToken
      },
      body: JSON.stringify(electronEventPayload(event))
    });
    if (!response.ok) {
      throw new Error(`runtime scene event rejected: ${response.status}`);
    }
  }

  private bound(event: RuntimeSceneElectronEvent): RuntimeSceneElectronEvent {
    return {
      eventCode: event.eventCode.slice(0, 120),
      message: event.message.slice(0, 500),
      fields: Object.fromEntries(
        Object.entries(event.fields).map(([key, value]) => [key.slice(0, 80), typeof value === "string" ? value.slice(0, 500) : value])
      )
    };
  }
}
```

- [ ] **Step 4: Add Electron bridge tests**

Create `desktop/electron/tests/runtimeSceneBridge.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";
import { RuntimeSceneBridge } from "../src/lifecycle/runtimeSceneBridge.js";

describe("RuntimeSceneBridge", () => {
  it("posts bounded events to the launcher runtime-scene route", async () => {
    const fetchImpl = vi.fn(async () => new Response("{}", { status: 202 }));
    const bridge = new RuntimeSceneBridge({
      launcherOrigin: "http://127.0.0.1:8765/launcher",
      controlToken: "token",
      maxBufferedEvents: 5,
      fetchImpl
    });

    await bridge.record({
      eventCode: "electron.desktop_action.claimed",
      message: "Desktop action claimed.",
      fields: { actionId: "desktop-action-1" }
    });

    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/api/launcher/runtime-scene/events",
      expect.objectContaining({ method: "POST" })
    );
  });
});
```

- [ ] **Step 5: Verify**

Run:

```powershell
npm --prefix desktop/electron run build
npm --prefix desktop/electron test -- --run
$env:TEMP="$PWD\\.tmp\\pytest-temp"; $env:TMP="$PWD\\.tmp\\pytest-temp"; pytest tests/test_web_runtime_routes.py -k "launcher_runtime_scene_event_records_electron_supervisor_event or runtime_scene_event_helper" -q --basetemp "$PWD\\.tmp\\pytest-basetemp"
```

Expected: Electron bridge tests and runtime-scene route tests pass, event payloads are bounded, auth is enforced by the existing Launcher route guard, and failed posts buffer only a small number of events.

- [ ] **Step 6: Commit**

```powershell
git add desktop/electron/src/lifecycle/runtimeSceneBridge.ts desktop/electron/tests/runtimeSceneBridge.test.ts core/web/routes/launcher.py core/web/services/runtime_scene_service.py tests/test_web_runtime_routes.py
git commit -m "feat: record electron launcher supervisor evidence"
```

## Migration Gates

### Gate 0: Protocol Boundary Ready

Evidence required:

```powershell
npm --prefix desktop/electron run build
npm --prefix desktop/electron test -- tests/deepLink.test.ts tests/launcherProtocol.test.ts tests/environmentSummary.test.ts
$env:TEMP="$PWD\\.tmp\\pytest-temp"; $env:TMP="$PWD\\.tmp\\pytest-temp"; pytest tests/test_web_runtime_routes.py -k "launcher_protocol or launcher_command_adapter or launcher_control_token or active_work" -q --basetemp "$PWD\\.tmp\\pytest-basetemp"
```

Pass condition:

- `vibelution://` deep links parse into typed Launcher requests without starting child processes.
- Launcher command responses have one machine-readable JSON shape.
- Unsupported deep links and blocked lifecycle actions produce safe rejections.
- Existing Launcher control-token and active-work guard semantics remain authoritative.
- Impact and environment ledgers exist and classify config, ports, Python path, control tokens, and provider compatibility.
- Environment summary reports token presence only and keeps external operator config authoritative.

### Gate 1: Electron Scaffold Ready

Evidence required:

```powershell
npm --prefix desktop/electron run build
npm --prefix desktop/electron test -- --run
```

Pass condition:

- Electron package compiles.
- Single-instance lock tests pass.
- Deep-link and Launcher protocol tests pass.
- Environment summary tests pass.
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
- Launcher protocol responses can report provider state without Edge-specific field names.
- Status APIs expose the resolved config/environment source without leaking secrets.
- UI status no longer depends on Edge-specific language.

### Gate 3: Electron Provider Can Open Launcher And Workbench

Evidence required:

```powershell
npm --prefix web run build
npm --prefix desktop/electron run build
npm --prefix desktop/electron run dev
$env:TEMP="$PWD\\.tmp\\pytest-temp"; $env:TMP="$PWD\\.tmp\\pytest-temp"; pytest tests/test_web_runtime_routes.py -k "desktop_session or window_provider_dispatcher" -q --basetemp "$PWD\\.tmp\\pytest-basetemp"
```

Manual check:

- One visible Vibelution entry starts.
- Launcher window appears first.
- Launcher URL and Workbench URL are resolved from existing Launcher status or explicit dev override.
- Workbench opens only from Launcher.
- Closing Workbench leaves Launcher alive.
- Closing Launcher runs active-work guard.
- Production mode refuses to start when Launcher URL, control token, or operator config path is unresolved.

### Gate 4: Python Intent Store And Desktop Action Loop Ready

Evidence required:

```powershell
$env:TEMP="$PWD\\.tmp\\pytest-temp"; $env:TMP="$PWD\\.tmp\\pytest-temp"; pytest tests/test_web_runtime_routes.py -k "self_evolution_restart_request_uses_launcher_lifecycle_service or launcher_lifecycle_intent_claim_ack_updates_pending_row or launcher_lifecycle_intent_releases_expired_desktop_action_lease or launcher_runtime_scene_event_records_electron_supervisor_event" -q --basetemp "$PWD\\.tmp\\pytest-basetemp"
npm --prefix desktop/electron test -- --run
```

Pass condition:

- Self-evolution restart request calls the Launcher lifecycle service instead of writing JSONL directly.
- Python Launcher is the only writer of lifecycle intent and desktop action SQLite rows.
- Launcher accepts or rejects the intent with a safe reason and active-work evidence.
- Runtime-effect actions map to existing Runtime Manager / Launcher command paths inside Python.
- Desktop actions are exposed through guarded Launcher API, claimed by Electron with a lease, and acked/failed against the same row with bounded result metadata.
- Runtime-scene evidence records request, decision, desktop action, command, and outcome at the owning layer.

### Gate 5: Packaging Skeleton Ready

Evidence required:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_desktop_package.ps1
dist/desktop/win-unpacked/Vibelution.exe --workspace "C:\Users\17533\Desktop\Vibelution" --smoke
```

Pass condition:

- Local unpacked desktop package is produced.
- Package uses one visible product entry.
- Workbench has no independent public shortcut.
- Package does not copy `core/`, `scripts/`, `requirements.txt`, root `config.toml`, or `config.example.toml`.
- Package requires an external workspace/Python/operator config unless a separate V2 bundled-runtime plan is approved.
- Packaged app does not read root `config.toml` or `config.example.toml` as active operator config.
- Package smoke records a redacted environment summary and no full env dump.
- Package smoke proves: bootstrap JSON is parsed, Launcher window opens first, Workbench opens only through Launcher, second instance focuses the existing desktop session, active work blocks app exit, and stale claimed Desktop Actions are not replayed after ack/fail.

## Old Test Alignment Rules

During implementation, old tests must be classified before being changed:

| Old assertion | Classification | Treatment |
|---|---|---|
| `msedge.exe` process exists | migrate | Move to Edge-provider compatibility tests only; Electron-default tests assert `windowProvider="electron"` and Desktop Session state. |
| `--app=http://...` exists | migrate/remove | Keep only while `windowProvider=edge_app`; remove once Edge fallback is retired. |
| `browserManaged is True` | update | New invariant is `windowManaged`; `browserManaged` remains Edge-only compatibility projection. |
| `windowProcessId` exists | update/remove | Replace with `windowId` and `rendererProcessId`; accept `windowProcessId` only as temporary read compatibility inside backend projection code. |
| `workbench-app-profile` exists | update | Replace with `windowProfileDir`; Edge profile path is provider-specific. |
| Launcher start/stop/restart active-work blockers | keep | Must also cover Electron `window-all-closed`, Launcher window close, and renderer `requestDesktopShellExit`. |
| control-token and `/api/launcher/*` guarded endpoints | keep | Add Desktop Action claim/ack/fail and Desktop Session route coverage under the same guard. |
| direct `uvicorn` or direct browser launch as normal lifecycle path | reject | Tests should fail if Electron introduces normal runtime process control outside Python Launcher/Runtime Manager. |
| JSONL lifecycle intent append path | migrate/remove | Replace with SQLite claim/lease tests; legacy JSONL tests must not keep append-only ACK semantics alive. |
| packaged path derived from `import.meta.url` parent walking | reject | Replace with four-root `DesktopPaths` tests and packaged fixtures. |
| protocol version mismatch ignored | add | Add version/capability handshake tests before packaging is trusted. |

No implementation step may claim correctness only because old tests pass. The new provider, intent, and supervisor contract tests must be present.

## Rollback Strategy

Version 1 must support fallback:

- Keep the Edge provider behind `windowProvider=edge_app`.
- Keep PowerShell and Python launcher adapters working.
- Keep `browserManaged` compatibility fields while frontend and tests migrate.
- Keep Electron startup behind a feature flag until Gate 3 passes.
- Keep feature flags scoped and named with removal triggers: `windowProvider=edge_app|electron` and `VIBELUTION_ELECTRON_START_LAUNCHER=0` are temporary migration controls, not long-term alternate products.
- If Electron startup fails, Launcher status must report `windowProvider=electron`, `phase=failed`, and a safe `failureMessage`.
- The user can still start the current Launcher path during the migration until the Electron path is selected as default.
- Roll back by selecting `windowProvider=edge_app`; do not delete Electron state files as the primary recovery path.
- Before removing fallback, run the full Gate 0-5 evidence set plus a manual Launcher refresh through the existing guarded path.

## Logging Decision

New logs are required because this plan changes desktop supervision, Launcher Service attachment, self-evolution lifecycle requests, packaging, and window management.

Log through existing runtime-scene helpers or bounded Electron bridge payloads:

- supervisor startup and shutdown;
- Python Launcher Service start/exit/failure;
- window open/focus/close;
- Python-owned lifecycle intent queued/accepted/rejected/executed;
- Electron desktop action claimed/succeeded/failed;
- Runtime Manager command submission and result from Python;
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
Electron Launcher supervisor plan refined after external review: Electron is the Desktop Supervisor and single visible shell; Python Launcher remains the runtime lifecycle, active-work, lifecycle-intent, and Runtime Manager authority. V1 is a Windows workspace-bound desktop package, not a zero-dependency installer. Lifecycle intents are Python single-writer records; Electron consumes only Launcher-approved Desktop Actions and acks results. The first implementation slice remains low risk: protocol, impact/environment ledger, deep-link parsing, environment summary, Python Launcher Service state, generic provider state, and test alignment before packaging or runtime ownership changes.
```

After the second review, include this refinement in the memory update proposal:

```text
Second-review gate added: Electron implementation is not executable by copying the old draft. It must first prove four-root DesktopPaths, JSON bootstrap attach/start ownership, SQLite Desktop Action claim/lease/ack/fail, Python runtime-effect dispatcher, ShutdownCoordinator active-work guard, Desktop Session window writeback, safe deep links, and non-zero validation filters. Reuse-first and test-alignment checks are now entry gates for every Electron task.
```

## Execution Handoff

Plan complete when saved to:

```text
docs/plans/2026-06-26-electron-launcher-supervisor-plan.md
```

Recommended execution mode:

1. Subagent-driven execution: one task per implementation slice, with review after each commit.
2. Inline execution: only for Tasks 0-2 first, because Task 2 establishes packaged path authority and the rest of the plan depends on it.

First implementation slice should be Tasks 0-2 only. Task 3 can follow after packaged path tests pass. Tasks 4-6 can follow after protocol/deep-link safety and DesktopPaths are stable. Task 7 requires the `scripts/vibelution_desktop_entry.py` bootstrap JSON contract. Tasks 8-10 require SQLite claim/lease/ack/fail and runtime-effect dispatcher tests. Task 11 requires ShutdownCoordinator tests before any runtime close behavior changes. Task 12 packaging waits for Gates 0-4. Do not start with packaging, Python Launcher Service ownership, or self-evolution lifecycle automation before the source-of-truth, reuse, and test-alignment gates are green.
