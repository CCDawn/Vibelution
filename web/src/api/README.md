# Frontend domain API (`web/src/api`)

> **Stable product transport layer for JSON HTTP calls.**
> Routes and route-domain hooks import named functions from here — not `fetchJson`, not raw `/api/...` strings.
> Permanent guard: `fullStackApiBoundary.test.ts` (ledger `{}`, aggregate `0`).
> Authoritative rules: [`docs/standards/development-standard.md`](../../docs/standards/development-standard.md) §24.

## Rules

1. **One backend domain → one module** (`<domain>.ts`), unless an existing module already owns the URL prefix.
2. **Only `client.ts` calls `fetchJson` directly** for JSON (plus colocated domain modules). Routes must not import `api/client`.
3. **Export named functions** (`fetchX`, `createX`, `updateX`, …) with stable URL/method/body semantics. Preserve `encodeURIComponent`, query strings, and `AbortSignal` passthrough when replacing inline calls.
4. **DTOs live in `types/<domain>.ts`**, re-exported by `types.ts`. Domain modules import types; they do not define display-only view models. Knowledge / RAG DTOs live in `types/knowledge.ts` so `types/memory.ts` and `types/teams.ts` do not import each other.
5. **Query keys stay in `queryKeys.ts`**. Invalidation contracts remain in routes/hooks; transports stay dumb.
6. **Colocated contract tests** (`<domain>.test.ts`) use Vitest `?raw` imports: API source owns paths; route sources use function names and must not embed `/api/<domain>/` string literals (import paths like `../api/skills` are fine).

## Shared infrastructure (not domain catalogs)

| File | Role |
| --- | --- |
| `client.ts` | Shared `fetchJson` transport, error normalization |
| `types.ts` | Public DTO barrel (`types/<domain>.ts`) |
| `types/knowledge.ts` | Knowledge / RAG DTOs (not memory, not teams) |
| `queryKeys.ts` | React Query key factories |
| `fullStackApiBoundary.test.ts` | Route-layer `fetchJson` / `api/client` guard (budget zero) |

## Domain modules

| Module | Typical `/api` prefix / concern |
| --- | --- |
| `agents.ts` | `/api/agents`, prompt templates, tool governance |
| `chat.ts` | `/api/sessions`, `/api/chat-rooms`, session tool approvals |
| `cliAgents.ts` | `/api/cli-agents/terminal-sessions/*` (JSON only) |
| `config.ts` | `/api/config/*` workspace and draft mutations |
| `dataProcessing.ts` | `/api/data-processing/*` |
| `diagnostics.ts` | `/api/diagnostics/*` |
| `evolution.ts` | `/api/evolution/*` supervised/review JSON |
| `files.ts` | `/api/files/content` |
| `git.ts` | `/api/git/*` |
| `kernel.ts` | `/api/kernel/*` |
| `knowledge.ts` | `/api/knowledge/*`, `/api/knowledge-bases/*` (do not merge with `memory.ts`) |
| `launcher.ts` | Launcher/workbench control JSON |
| `logs.ts` | `/api/logs/*`, runtime scene list/detail/delete |
| `memory.ts` | `/api/memory/*` (do not merge with `knowledge.ts`) |
| `pet.ts` | `/api/pet/*` |
| `projectAgentBus.ts` | Project agent bus |
| `researchLoop.ts` | Research loop substrate |
| `researchProjectAgentTasks.ts` | Research project agent tasks |
| `researchWorkflow.ts` | Research workflow reads |
| `runtime.ts` | `/api/runtime/summary` |
| `selfEvolution.ts` | `/api/evolution/self/*` autonomous loop JSON |
| `skills.ts` | `/api/skills` library |
| `sourceCollection.ts` | Team source collection |
| `stageRounds.ts` | Stage rounds |
| `teamExperiment.ts` | Team experiments |
| `teamKnowledge.ts` | Team workflow knowledge ingestion (`/api/teams/.../knowledge-ingestion`); distinct from `knowledge.ts` |
| `teamMemberMessages.ts` | Team member messages |
| `teamResearchOps.ts` | Team research ops |
| `teams.ts` | `/api/teams/*` |
| `teamWorkflow.ts` | Team workflow orchestration |
| `tools.ts` | `/api/tools/*` |
| `usage.ts` | `/api/usage/summary` |
| `userContent.ts` | User content (memory panel) |
| `workbenchUiPreferences.ts` | Workbench UI preferences |

Add a row here when introducing a new `<domain>.ts`. Prefer extending an existing module when the URL prefix and owning product surface already match.

## Route-layer exceptions (not in this layer)

These stay in routes when they are not JSON `fetchJson` transports:

| Kind | Example | Owner surface |
| --- | --- | --- |
| SSE / `EventSource` | `/api/evolution/active-run/events` | `EvolutionRoute.tsx` |
| SSE / `EventSource` | `/api/cli-agents/terminal-sessions/{id}/events` | `CliAgentRunTerminalPanel.tsx` |
| Bounded browser adapters | `postBrowserTelemetry`, file upload streams | Named helpers under `web/src/app/` or domain API with explicit adapter docs |

New exceptions need the same explicit review as a new public endpoint: document the reason in the PR and add a contract test that prevents JSON paths from returning to the route.

## Contract tests

| Test | Asserts |
| --- | --- |
| `fullStackApiBoundary.test.ts` | Zero route `fetchJson`; zero route `api/client` imports |
| `<domain>.test.ts` | Named exports + API raw paths; consuming routes free of `/api/...` literals |
| `typesDomainModules.test.ts` | Type/domain module boundaries |

Run after transport changes:

```text
npx vitest run src/api/fullStackApiBoundary.test.ts src/api/<domain>.test.ts --fileParallelism=false
npx tsc -b --pretty false
```

If `fullStackApiBoundary.test.ts` times out in a wide parallel run, rerun that file alone.

## Adding a new JSON endpoint

1. Add or extend the owning `web/src/api/<domain>.ts` function.
2. Add matching DTO types in `types.ts` when the payload is shared.
3. Wire the route/hook to the named function; do not add `fetchJson` in `web/src/routes/`.
4. Extend `<domain>.test.ts` (or add one) with raw-source assertions.
5. Confirm `fullStackApiBoundary.test.ts` still passes with ledger `{}`.
