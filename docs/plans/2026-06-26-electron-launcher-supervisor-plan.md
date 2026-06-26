# Electron Launcher Supervisor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert Vibelution to a single-entry Electron desktop application where Electron is the desktop supervisor and single visible shell, while Python Launcher and Runtime Manager remain the runtime lifecycle authority.

**Architecture:** Vibelution keeps one user-visible entrypoint and one source of truth per authority domain. Electron replaces the current Edge app window provider and directly supervises desktop windows plus one Python Launcher Service child; Python Launcher owns active-work policy, lifecycle intent persistence, runtime command decisions, and Runtime Manager delegation. The Codex reference repo shows the useful pattern is not "put product logic into Electron"; it is a deep-linkable desktop entry backed by a typed app-server/runtime protocol. Vibelution must therefore reuse existing Launcher, Runtime Manager, FastAPI, runtime-scene, active-work guard, config, and control-token contracts instead of creating a parallel lifecycle system.

**Tech Stack:** Electron, Node.js, TypeScript, React/Vite web UI loaded through local HTTP, FastAPI backend, Python Runtime Manager, existing `scripts/vibelution_launcher.ps1` / `scripts/vibelution_launcher.py`, existing Launcher API, Vitest, pytest.

## Global Constraints

- Single visible user entrypoint: one packaged `Vibelution` launcher entry, not separate public Launcher and Workbench shortcuts.
- Two-layer supervision rule: Electron main is the desktop session supervisor; Python Launcher is the runtime policy and lifecycle command authority.
- Single-domain authority rule: Electron owns single-instance, protocol handler, BrowserWindow state, and the Python Launcher Service child; Python owns active-work, apply/rollback, Runtime Manager commands, lifecycle intents, and runtime-scene policy.
- Multi-process runtime: Electron main is the OS-visible root process, but backend, Runtime Manager, self-evolution workers, and tool workers remain Python-managed descendants or projections rather than Electron-owned direct children.
- Workbench cannot start the project directly; it is opened, focused, and closed only through Launcher commands.
- Self-evolution Agent cannot spawn or kill the project directly; it writes structured lifecycle intents that Launcher validates and executes.
- Electron main process must not contain product business logic, LLM calls, file scanning, agent execution, or tool execution; it supervises and delegates.
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
- Security baseline: renderer Node integration stays disabled; `contextIsolation` stays enabled; preload exposes only narrow lifecycle IPC calls.
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
   └─ Python Launcher Service
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
- Closing Launcher runs active-work checks before closing managed children.
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

- Tasks 0-4: documentation, protocol types, deep-link parsing, status state, and pure tests only. No runtime child process ownership change.
- Tasks 5-7: generic provider and long-lived Python Launcher Service supervision under feature flag. Existing Edge/Launcher path remains default.
- Tasks 8-11: Python-owned lifecycle intent store, desktop action queue, and narrow IPC. Electron consumes approved actions and returns ack/result; it does not read or write intent JSONL.
- Tasks 12-13: workspace-bound packaging and runtime-scene evidence. Packaging is last because it multiplies any earlier drift.

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

Implementation must add a small environment inventory output before child startup:

```ts
type LauncherEnvironmentSummary = {
  schemaVersion: 1;
  pythonSource: "launcher_resolver" | "env_override";
  pythonPath: string;
  operatorConfigPath: string;
  launcherUrl: string;
  workbenchUrl: string;
  controlTokenPresent: boolean;
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
      launcherServiceProcess.ts
      managedProcessTypes.ts
      pythonRuntime.ts
    protocol/
      deepLink.ts
      launcherProtocol.ts
      launcherProtocolSchema.ts
      lifecycleCommandOutput.ts
      desktopActionClient.ts
      environmentSummary.ts
    lifecycle/
      launcherStateAdapter.ts
      runtimeSceneBridge.ts
    windows/
      launcherWindow.ts
      workbenchWindow.ts
      windowProviderTypes.ts
      electronWindowProvider.ts
  tests/
    appLock.test.ts
    launcherServiceProcess.test.ts
    desktopActionClient.test.ts
    launcherProtocol.test.ts
    deepLink.test.ts
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

Self-evolution and other agents may request lifecycle actions only by submitting an intent to the Python Launcher API. They do not append files directly, and Electron never reads or writes the intent store.

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

- Python Launcher is the single writer of `intents.jsonl`; `index.json` is a projection.
- Launcher validates active work, worktree review state, apply/rollback safety, and duplicate idempotency keys before persistence changes state.
- Accepted intents become either Runtime Manager commands or Desktop Actions.
- Desktop Actions are consumed through a guarded Launcher API and acked by Electron with result metadata.
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

## Deep Link And Launcher Protocol Contract

Codex uses `codex://threads/new?path=...` as the bridge from CLI or OS entrypoint into the desktop app. Vibelution should use the same idea without copying Codex-specific routes:

```text
vibelution://launcher/focus
vibelution://workbench/open?path=C%3A%5CUsers%5C17533%5CDesktop%5CVibelution
vibelution://lifecycle/intent?action=restart_after_apply&idempotencyKey=...
```

Rules:

- Deep links are entry intents, not runtime execution authority.
- Electron main parses and validates the link, then translates it into a Launcher protocol request.
- Unsupported links return or record a safe machine-readable rejection.
- Path values must be canonicalized and never replace the active operator config source.
- Tests must cover Windows path encoding, duplicate secondary launch focus, invalid action rejection, and idempotency.

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
| `desktop/electron/tests/deepLink.test.ts` | `vibelution://` parsing and Windows path encoding | add | Validate focus/open/lifecycle links without launching children | Invalid or duplicate links become safe typed responses |
| `desktop/electron/tests/launcherProtocol.test.ts` | Machine-readable Launcher command response | add | Assert schema fields and command/status/provider enums | Electron and backend adapter share one response shape |
| `tests/test_web_runtime_routes.py` | Launcher command adapter and active-work guard | add/update | Assert JSON lifecycle responses and blocked active-work states | Runtime commands stay Launcher-gated |
| `desktop/electron/tests/environmentSummary.test.ts` | Config/environment resolution summary | add | Assert external operator config, URL, Python source, and token presence are reported without secrets | Electron does not invent hidden config/env defaults |
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
| `desktop/electron/tests/deepLink.test.ts` | `vibelution://` parsing and Windows path encoding | add | Validate focus/open/lifecycle links without launching children | Invalid or duplicate links become safe typed responses |
| `desktop/electron/tests/launcherProtocol.test.ts` | Machine-readable Launcher command response | add | Assert schema fields and command/status/provider enums | Electron and backend adapter share one response shape |
| `tests/test_web_runtime_routes.py` | Launcher command adapter and active-work guard | add/update | Assert JSON lifecycle responses and blocked active-work states | Runtime commands stay Launcher-gated |
| `desktop/electron/tests/environmentSummary.test.ts` | Config/environment resolution summary | add | Assert external operator config, URL, Python source, and token presence are reported without secrets | Electron does not invent hidden config/env defaults |
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

const here = dirname(fileURLToPath(import.meta.url));

export function resolveProjectRoot(): string {
  return resolve(here, "..", "..", "..");
}

export function resolveRuntimeDir(projectRoot = resolveProjectRoot()): string {
  return resolve(projectRoot, ".runtime", "launcher");
}
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
  | { kind: "open_workbench"; path: string }
  | { kind: "lifecycle_intent"; action: string; idempotencyKey: string };

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
  if (route === "lifecycle/intent") {
    const action = url.searchParams.get("action");
    const idempotencyKey = url.searchParams.get("idempotencyKey");
    if (!action || !idempotencyKey) {
      throw new Error("missing lifecycle intent action or idempotencyKey");
    }
    return { kind: "lifecycle_intent", action, idempotencyKey };
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
});
```

- [ ] **Step 7: Add environment summary contract**

Create `desktop/electron/src/protocol/environmentSummary.ts`:

```ts
export type LauncherEnvironmentSummary = {
  schemaVersion: 1;
  pythonSource: "launcher_resolver" | "env_override";
  pythonPath: string;
  operatorConfigPath: string;
  launcherUrl: string;
  workbenchUrl: string;
  controlTokenPresent: boolean;
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
      pythonSource: "launcher_resolver",
      pythonPath: "C:/repo/.venv/Scripts/python.exe",
      operatorConfigPath: "C:/Users/17533/Documents/Vibelution/config/config.toml",
      launcherUrl: "http://127.0.0.1:8765/launcher",
      workbenchUrl: "http://127.0.0.1:8765/",
      controlTokenPresent: true,
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
      pythonSource: "env_override",
      pythonPath: "C:/Python/python.exe",
      operatorConfigPath: "C:/Users/17533/Documents/Vibelution/config/config.toml",
      launcherUrl: "http://127.0.0.1:8765/launcher",
      workbenchUrl: "http://127.0.0.1:8765/",
      controlTokenPresent: true,
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
      preload: resolve(projectRoot, "desktop", "electron", "dist", "preload.cjs"),
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

- [ ] **Step 10: Add a path test**

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
- Consumes: resolved Launcher URL and Workbench URL from existing Launcher status, or explicit development/test environment overrides.
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
      preload: resolve(projectRoot, "desktop", "electron", "dist", "preload.cjs"),
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
      preload: resolve(projectRoot, "desktop", "electron", "dist", "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });
  void window.loadURL(url);
  return window;
}
```

- [ ] **Step 5: Resolve Launcher URL without production hard-coding**

Add a resolver before wiring the provider:

```ts
export function resolveLauncherUrl(env: NodeJS.ProcessEnv, launcherStatusUrl?: string): string {
  const explicit = String(env.VIBELUTION_LAUNCHER_URL || "").trim();
  if (explicit) {
    return explicit;
  }
  if (launcherStatusUrl) {
    return launcherStatusUrl;
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

- [ ] **Step 6: Wire provider into main process**

Update `desktop/electron/src/main.ts` to open the Launcher URL first:

```ts
const launcherUrl = resolveLauncherUrl(process.env, existingLauncherStatus?.launcherUrl);
```

Use `createLauncherWindow(launcherUrl)` instead of loading `about:blank`.

- [ ] **Step 7: Verify**

Run:

```powershell
npm --prefix desktop/electron run build
npm --prefix desktop/electron test -- --run
```

Expected: Electron package builds and window provider tests pass.

- [ ] **Step 8: Commit**

```powershell
git add desktop/electron/src/windows desktop/electron/src/main.ts desktop/electron/tests/windowProvider.test.ts
git commit -m "feat: add electron window provider"
```

### Task 7: Long-Lived Python Launcher Service Handshake

**Files:**
- Create: `desktop/electron/src/process/pythonRuntime.ts`
- Create: `desktop/electron/src/process/launcherServiceClient.ts`
- Modify: `desktop/electron/src/main.ts`
- Test: `desktop/electron/tests/launcherServiceProcess.test.ts`

**Interfaces:**
- Consumes: existing Python runtime resolution and existing Launcher startup/status API.
- Produces: Electron main can start or attach to one Python Launcher Service, wait for authenticated readiness, and then load Launcher UI without directly starting backend, Runtime Manager, or workers.

- [ ] **Step 1: Add Python runtime resolver**

Create `desktop/electron/src/process/pythonRuntime.ts`:

```ts
import { existsSync } from "node:fs";
import { resolve } from "node:path";

export type PythonRuntimeResolution = {
  pythonPath: string;
  source: "env_override" | "project_venv";
};

export function resolvePythonRuntime(projectRoot: string, env = process.env): PythonRuntimeResolution {
  const override = String(env.VIBELUTION_PYTHON_EXE || "").trim();
  if (override) {
    return { pythonPath: override, source: "env_override" };
  }
  const candidate = resolve(projectRoot, ".venv", "Scripts", "python.exe");
  if (existsSync(candidate)) {
    return { pythonPath: candidate, source: "project_venv" };
  }
  throw new Error("Python runtime is unresolved; use the existing Launcher resolver or set VIBELUTION_PYTHON_EXE for dev/test");
}
```

- [ ] **Step 2: Add tests for resolver**

Append to `desktop/electron/tests/launcherServiceProcess.test.ts`:

```ts
import { resolvePythonRuntime } from "../src/process/pythonRuntime.js";

describe("resolvePythonRuntime", () => {
  it("prefers VIBELUTION_PYTHON_EXE", () => {
    expect(resolvePythonRuntime("C:/repo", { VIBELUTION_PYTHON_EXE: "C:/Python/python.exe" } as NodeJS.ProcessEnv)).toEqual({
      pythonPath: "C:/Python/python.exe",
      source: "env_override"
    });
  });

  it("does not silently fall back to PATH python", () => {
    expect(() => resolvePythonRuntime("C:/missing", {} as NodeJS.ProcessEnv)).toThrow("Python runtime is unresolved");
  });
});
```

- [ ] **Step 3: Add Launcher Service client**

Create `desktop/electron/src/process/launcherServiceClient.ts`:

```ts
import { spawn } from "node:child_process";
import { resolve } from "node:path";

export type LauncherServiceStartInput = {
  projectRoot: string;
  pythonPath: string;
  operatorConfigPath: string;
};

export function spawnPythonLauncherService(input: LauncherServiceStartInput) {
  return spawn(
    input.pythonPath,
    [
      resolve(input.projectRoot, "scripts", "vibelution_launcher.py"),
      "--action",
      "launcher",
      "--no-browser",
      "--config",
      input.operatorConfigPath
    ],
    {
      cwd: input.projectRoot,
      windowsHide: true,
      stdio: "pipe"
    }
  );
}
```

- [ ] **Step 4: Wire startup as attach-or-start**

Update Electron main so startup follows this order:

1. acquire Electron single-instance lock;
2. resolve external operator config through existing project contract;
3. check whether an authenticated Launcher API for this workspace is already ready;
4. if not ready and feature flag allows it, spawn one Python Launcher Service;
5. poll health/readiness with a bounded timeout and control token;
6. load Launcher window only after readiness succeeds.

Keep process startup behind an environment switch during the first implementation:

```ts
const shouldStartLauncher = process.env.VIBELUTION_ELECTRON_START_LAUNCHER !== "0";
```

This prevents local developer runs from spawning runtime processes while unit tests compile the package. Runtime commands after readiness still go through Python Launcher/Runtime Manager APIs; Electron does not spawn `start`, `stop`, or `restart` scripts per action.

- [ ] **Step 5: Verify**

Run:

```powershell
npm --prefix desktop/electron run build
npm --prefix desktop/electron test -- --run
python scripts/vibelution_launcher.py --action status --no-browser
```

Expected: Electron build/tests pass, the existing Python launcher adapter still reports status, and tests prove unresolved Python/config values fail closed instead of using hidden defaults.

- [ ] **Step 6: Commit**

```powershell
git add desktop/electron/src/process desktop/electron/src/main.ts desktop/electron/tests/launcherServiceProcess.test.ts
git commit -m "feat: start electron through python launcher service"
```

### Task 8: Python Lifecycle Intent Store And Desktop Action Contract

**Files:**
- Create: `core/launcher/lifecycle_intent_store.py`
- Modify: `core/launcher/service.py`
- Modify: `core/web/routes/launcher.py`
- Modify: `tests/test_web_runtime_routes.py`
- Test: `tests/test_web_runtime_routes.py`

**Interfaces:**
- Consumes: existing Launcher active-work checks, Runtime Manager command queue, control-token guarded Launcher routes, and runtime-scene logging.
- Produces: Python-owned `submit_lifecycle_intent(...)`, `next_desktop_action(...)`, and `ack_desktop_action(...)` APIs. Electron and agents do not write lifecycle JSONL files.

- [ ] **Step 1: Write failing Python single-writer tests**

Add a test to `tests/test_web_runtime_routes.py`:

```python
from core.launcher import lifecycle_intent_store


def test_launcher_lifecycle_intent_store_is_python_single_writer(tmp_path, monkeypatch):
    monkeypatch.setattr(lifecycle_intent_store, "LIFECYCLE_INTENTS_DIR", tmp_path)

    result = lifecycle_intent_store.submit_lifecycle_intent(
        {
            "requestedBy": {"actorType": "self_evolution_agent", "actorId": "self-agent"},
            "action": "focus_workbench",
            "reason": "recover focus after apply",
            "sourceRunId": "self-run-1",
            "sourceTaskId": "task-1",
            "sourceWorktree": str(tmp_path / "worktree"),
            "idempotencyKey": "self-run-1:focus",
        },
        active_work_runs=[],
    )

    assert result["status"] == "accepted"
    assert (tmp_path / "intents.jsonl").exists()
    action = lifecycle_intent_store.next_desktop_action()
    assert action["action"] == "focus_workbench"
    assert action["intentId"] == result["intentId"]


def test_launcher_lifecycle_intent_rejects_runtime_effects_during_active_work(tmp_path, monkeypatch):
    monkeypatch.setattr(lifecycle_intent_store, "LIFECYCLE_INTENTS_DIR", tmp_path)

    result = lifecycle_intent_store.submit_lifecycle_intent(
        {
            "requestedBy": {"actorType": "self_evolution_agent", "actorId": "self-agent"},
            "action": "restart_after_apply",
            "reason": "apply completed",
            "sourceRunId": "self-run-1",
            "sourceTaskId": "task-1",
            "sourceWorktree": str(tmp_path / "worktree"),
            "idempotencyKey": "self-run-1:restart",
        },
        active_work_runs=[{"runId": "active-1", "status": "running"}],
    )

    assert result["status"] == "rejected"
    assert result["rejectionReason"] == "active_work_running"
    assert lifecycle_intent_store.next_desktop_action() == {}
```

Run:

```powershell
$env:TEMP="$PWD\\.tmp\\pytest-temp"; $env:TMP="$PWD\\.tmp\\pytest-temp"; pytest tests/test_web_runtime_routes.py -k "launcher_lifecycle_intent" -q --basetemp "$PWD\\.tmp\\pytest-basetemp"
```

Expected: failure because `core.launcher.lifecycle_intent_store` is not implemented.

- [ ] **Step 2: Implement Python-owned store and desktop action queue**

Create `core/launcher/lifecycle_intent_store.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.runtime_manager.constants import PROJECT_ROOT


LIFECYCLE_INTENTS_DIR = PROJECT_ROOT / ".runtime" / "launcher" / "lifecycle-intents"
DESKTOP_ACTIONS = {"open_workbench", "focus_workbench", "close_workbench"}
RUNTIME_EFFECT_ACTIONS = {"restart_after_apply", "resume_self_evolution", "recover_after_crash", "request_app_exit"}
ALLOWED_ACTIONS = DESKTOP_ACTIONS | RUNTIME_EFFECT_ACTIONS


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path(name: str) -> Path:
    return LIFECYCLE_INTENTS_DIR / name


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _safe_text(value: Any, *, max_length: int = 500) -> str:
    return str(value or "").strip()[:max_length]


def submit_lifecycle_intent(payload: dict[str, Any], *, active_work_runs: list[dict[str, Any]]) -> dict[str, Any]:
    action = _safe_text(payload.get("action"), max_length=80)
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"unsupported lifecycle intent action: {action}")
    now = _now_iso()
    active_work_running = bool(active_work_runs) and action in RUNTIME_EFFECT_ACTIONS
    intent = {
        "intentId": f"intent-{uuid4().hex}",
        "schemaVersion": 1,
        "requestedBy": payload.get("requestedBy") or {},
        "action": action,
        "reason": _safe_text(payload.get("reason")),
        "sourceRunId": _safe_text(payload.get("sourceRunId"), max_length=160),
        "sourceTaskId": _safe_text(payload.get("sourceTaskId"), max_length=160),
        "sourceWorktree": _safe_text(payload.get("sourceWorktree")),
        "idempotencyKey": _safe_text(payload.get("idempotencyKey"), max_length=240),
        "status": "rejected" if active_work_running else "accepted",
        "createdAt": now,
        "updatedAt": now,
        "rejectionReason": "active_work_running" if active_work_running else "",
        "commandId": "",
        "runtimeSceneRef": "",
    }
    _append_jsonl(_path("intents.jsonl"), intent)
    if intent["status"] == "accepted" and action in DESKTOP_ACTIONS:
        _append_jsonl(
            _path("desktop-actions.jsonl"),
            {
                "actionId": f"desktop-action-{uuid4().hex}",
                "intentId": intent["intentId"],
                "action": action,
                "status": "pending",
                "createdAt": now,
                "updatedAt": now,
                "payload": {"sourceRunId": intent["sourceRunId"], "sourceTaskId": intent["sourceTaskId"]},
            },
        )
    return intent


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def next_desktop_action() -> dict[str, Any]:
    for action in _read_jsonl(_path("desktop-actions.jsonl")):
        if action.get("status") == "pending":
            return action
    return {}


def ack_desktop_action(action_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    result = {
        "actionId": _safe_text(action_id, max_length=160),
        "status": _safe_text(payload.get("status"), max_length=40) or "succeeded",
        "message": _safe_text(payload.get("message")),
        "ackedAt": _now_iso(),
    }
    _append_jsonl(_path("desktop-action-results.jsonl"), result)
    return result
```

- [ ] **Step 3: Add guarded Launcher routes**

Modify `core/web/routes/launcher.py`:

```python
from core.launcher import lifecycle_intent_store


class LifecycleIntentPayload(BaseModel):
    requestedBy: dict = Field(default_factory=dict)
    action: str
    reason: str = ""
    sourceRunId: str = ""
    sourceTaskId: str = ""
    sourceWorktree: str = ""
    idempotencyKey: str


class DesktopActionAckPayload(BaseModel):
    status: str = "succeeded"
    message: str = ""


@router.post("/launcher/lifecycle-intents", status_code=202)
def launcher_submit_lifecycle_intent(payload: LifecycleIntentPayload) -> dict:
    try:
        return launcher_service.submit_lifecycle_intent(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_lifecycle_intent", "message": str(exc)}) from exc


@router.get("/launcher/desktop-actions/next")
def launcher_next_desktop_action() -> dict:
    return launcher_service.next_desktop_action()


@router.post("/launcher/desktop-actions/{action_id}/ack", status_code=202)
def launcher_ack_desktop_action(action_id: str, payload: DesktopActionAckPayload) -> dict:
    return launcher_service.ack_desktop_action(action_id, payload.model_dump())
```

Add thin service wrappers to `core/launcher/service.py` so route code does not bypass Launcher active-work policy:

```python
from core.launcher import lifecycle_intent_store


def submit_lifecycle_intent(payload: dict[str, Any]) -> dict[str, Any]:
    return lifecycle_intent_store.submit_lifecycle_intent(payload, active_work_runs=launcher_active_work_runs())


def next_desktop_action() -> dict[str, Any]:
    return lifecycle_intent_store.next_desktop_action()


def ack_desktop_action(action_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return lifecycle_intent_store.ack_desktop_action(action_id, payload)
```

- [ ] **Step 4: Verify**

Run:

```powershell
$env:TEMP="$PWD\\.tmp\\pytest-temp"; $env:TMP="$PWD\\.tmp\\pytest-temp"; pytest tests/test_web_runtime_routes.py -k "launcher_lifecycle_intent or launcher_control_token or active_work" -q --basetemp "$PWD\\.tmp\\pytest-basetemp"
```

Expected: lifecycle intent tests pass, Launcher route token/active-work behavior remains guarded, and no Electron file writer exists for intents.

- [ ] **Step 5: Commit**

```powershell
git add core/launcher/lifecycle_intent_store.py core/launcher/service.py core/web/routes/launcher.py tests/test_web_runtime_routes.py
git commit -m "feat: add python-owned lifecycle intent store"
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

    def fake_submit(payload: dict[str, object]) -> dict[str, object]:
        captured.update(payload)
        return {"intentId": "intent-1", "status": "accepted", "action": payload["action"]}

    monkeypatch.setattr(self_evolution_control_service.launcher_service, "submit_lifecycle_intent", fake_submit)

    result = self_evolution_control_service.request_lifecycle_intent(
        {
            "requestedBy": {"actorType": "self_evolution_agent", "actorId": "self-agent"},
            "action": "restart_after_apply",
            "reason": "apply completed",
            "sourceRunId": "self-run-1",
            "sourceTaskId": "task-1",
            "sourceWorktree": "C:/worktree",
            "idempotencyKey": "self-run-1:restart",
        }
    )

    assert result["intentId"] == "intent-1"
    assert captured["action"] == "restart_after_apply"
```

- [ ] **Step 2: Implement self-evolution adapter**

Add or update `core/web/services/self_evolution_control_service.py`:

```python
from core.launcher import service as launcher_service


def request_lifecycle_intent(payload: dict[str, Any]) -> dict[str, Any]:
    return launcher_service.submit_lifecycle_intent(payload)
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
- Produces: Electron executes only approved desktop actions (`open_workbench`, `focus_workbench`, `close_workbench`) and returns ack/result. Runtime-effect actions remain Python Launcher/Runtime Manager responsibilities.

- [ ] **Step 1: Add action mapping tests**

Create `desktop/electron/tests/desktopActionClient.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { desktopWindowOperationForAction } from "../src/protocol/desktopActionClient.js";

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
});
```

- [ ] **Step 2: Implement Desktop Action client types**

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
  status: "pending" | "claimed" | "succeeded" | "failed";
  payload: Record<string, string>;
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
```

- [ ] **Step 3: Add Electron action loop**

In `desktop/electron/src/main.ts`, add a bounded loop that:

1. calls `GET /api/launcher/desktop-actions/next` with the existing control token;
2. maps the action through `desktopWindowOperationForAction`;
3. executes only BrowserWindow operations;
4. posts `POST /api/launcher/desktop-actions/{actionId}/ack`;
5. does not read `.runtime/launcher/lifecycle-intents/*.jsonl`;
6. does not spawn Runtime Manager or worker processes.

Use a conservative interval:

```ts
const DESKTOP_ACTION_POLL_MS = 2000;
```

- [ ] **Step 4: Verify**

Run:

```powershell
npm --prefix desktop/electron run build
npm --prefix desktop/electron test -- --run
```

Expected: desktop action mapping tests pass, build remains strict, and no Electron test imports a lifecycle intent store.

- [ ] **Step 5: Commit**

```powershell
git add desktop/electron/src/protocol/desktopActionClient.ts desktop/electron/src/main.ts desktop/electron/tests/desktopActionClient.test.ts
git commit -m "feat: consume launcher-approved desktop actions"
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
electron.launcher_service.started
electron.launcher_service.exited
electron.desktop_action.claimed
electron.desktop_action.succeeded
electron.desktop_action.failed
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

### Gate 0: Protocol Boundary Ready

Evidence required:

```powershell
npm --prefix desktop/electron run build
npm --prefix desktop/electron test -- tests/deepLink.test.ts tests/launcherProtocol.test.ts tests/environmentSummary.test.ts
pytest tests/test_web_runtime_routes.py -k "launcher and protocol" -q
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
pytest tests/test_web_runtime_routes.py -k "self_evolution and lifecycle_intent" -q
npm --prefix desktop/electron test -- --run
```

Pass condition:

- Self-evolution restart request calls the Launcher lifecycle service instead of writing JSONL directly.
- Python Launcher is the only writer of lifecycle intent and desktop action files.
- Launcher accepts or rejects the intent with a safe reason and active-work evidence.
- Runtime-effect actions map to existing Runtime Manager / Launcher command paths inside Python.
- Desktop actions are exposed through guarded Launcher API, consumed by Electron, and acked with bounded result metadata.
- Runtime-scene evidence records request, decision, desktop action, command, and outcome at the owning layer.

### Gate 5: Packaging Skeleton Ready

Evidence required:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_desktop_package.ps1
```

Pass condition:

- Local unpacked desktop package is produced.
- Package uses one visible product entry.
- Workbench has no independent public shortcut.
- Package does not copy `core/`, `scripts/`, `requirements.txt`, root `config.toml`, or `config.example.toml`.
- Package requires an external workspace/Python/operator config unless a separate V2 bundled-runtime plan is approved.
- Packaged app does not read root `config.toml` or `config.example.toml` as active operator config.
- Package smoke records a redacted environment summary and no full env dump.

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

## Execution Handoff

Plan complete when saved to:

```text
docs/plans/2026-06-26-electron-launcher-supervisor-plan.md
```

Recommended execution mode:

1. Subagent-driven execution: one task per implementation slice, with review after each commit.
2. Inline execution: only for Tasks 0-4, because later tasks touch lifecycle, packaging, Runtime Manager, self-evolution, and tests across multiple surfaces.

First implementation slice should be Tasks 0-4 only. Do not start with packaging, Python Launcher Service startup, or self-evolution lifecycle automation before the deep-link contract, Launcher protocol response shape, Python Launcher Service state, generic window provider, and test alignment ledger are stable.
