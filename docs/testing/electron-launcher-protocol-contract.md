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
