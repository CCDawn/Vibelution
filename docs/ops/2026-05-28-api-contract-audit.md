# API Contract Audit - 2026-05-28

This note records a read-only frontend/backend API contract scan for the
Vibelution Web Workbench. It is an operational coordination artifact, not a
source of runtime behavior.

## Scope

- Backend API surface: `core/web/app.py` and `core/web/routes/*.py`
- Frontend API consumers: `web/src/**/*.ts` and `web/src/**/*.tsx`
- Call patterns scanned: `fetchJson(...)`, `requestJson(...)`, and
  `new EventSource(...)`
- Normalization: dynamic path segments such as `${sessionId}` and
  `{session_id}` were collapsed to `{param}` for path matching.

## Snapshot

- Backend route decorators: 169
- Backend unique paths: 148
- Frontend API calls found: 185
- Frontend unique paths found: 115
- Frontend call kinds:
  - `fetchJson`: 165
  - `requestJson`: 15
  - `EventSource`: 5

Largest backend API groups:

| Prefix | Routes |
| --- | ---: |
| `evolution` | 42 |
| `research` | 26 |
| `config` | 15 |
| `sessions` | 13 |
| `agents` | 12 |

Largest frontend API consumer groups:

| Prefix | Calls |
| --- | ---: |
| `evolution` | 40 |
| `config` | 21 |
| `research` | 21 |
| `sessions` | 17 |
| `chat-rooms` | 16 |
| `agents` | 15 |

## Main Finding

No fixed frontend API call was confirmed to be missing a backend route.

The only apparent frontend-without-backend path was:

```text
/api/research/theme-discovery/sessions/{param}/{param}
```

Manual inspection showed this comes from `ResearchRoute.tsx` dynamic action
suffixes. The concrete suffixes map to existing backend routes:

- `run-broad-search`
- `run-deep-search`
- `extract-evidence`
- `generate-themes`
- theme selection and theme-card approval paths

Treat this as a scanner limitation, not a confirmed contract bug.

## Backend Routes Without Static Frontend Matches

The scanner found 31 backend paths without a static frontend JSON/SSE match.
This is not automatically a problem. Several categories are expected:

- Control and telemetry endpoints that use direct `fetch`, not `fetchJson`
  - `/api/control-token`
  - `/api/runtime/browser-telemetry`
- Binary or URL-backed resources
  - `/api/config/avatar-image/{param}`
  - `/api/sessions/{param}/artifacts/{param}`
- Dynamically assembled frontend actions
  - several `/api/research/theme-discovery/...` routes
  - some `/api/config/draft/...` routes through `requestJson`
- Internal or future-facing workbench affordances
  - agent inbox message routes
  - proposal creation routes
  - generated tool validation

Paths worth explicit ownership classification:

- `/api/agents/{param}/messages`
- `/api/agents/{param}/messages/{param}/consume`
- `/api/evolution/self/audit`
- `/api/evolution/self/candidates`
- `/api/research/knowledge-base`
- `/api/research/organization/proposals`
- `/api/runtime/events`
- `/api/sessions/agent-templates`
- `/api/tools/generated/{param}/validate`

Each should eventually be labeled as one of:

- actively used by UI through a dynamic or non-JSON path
- intentionally backend-only/internal
- planned UI surface
- deprecated candidate

## Contract Rules Going Forward

1. For every new or changed `/api/*` route, update the matching frontend type
   and call site, or document why it is backend-only.
2. For dynamic API suffixes, keep a stable code or test anchor that enumerates
   the valid suffixes. String-only scanners cannot reliably infer them.
3. For binary, artifact, telemetry, and control-token routes, keep them on an
   explicit ignore list if a contract scanner is promoted to CI.
4. For stateful routes, describe the visible state contract, not only the path:
   `busy`, `queued`, `running`, `failed`, `stopped`, `archived`, and `blocked`
   must have backend source, frontend display, and failure behavior.
5. Runtime behavior changes should include a logging decision. Prefer runtime
   scene events with safe summaries over full prompt, secret, or binary payloads.

## Recommended Next Step

`scripts/api_contract_audit.py` now provides an advisory v0 scanner:

```powershell
.\.venv\Scripts\python.exe scripts\api_contract_audit.py
.\.venv\Scripts\python.exe scripts\api_contract_audit.py --json
```

The scanner reports potential drift without failing by default. It supports
`--fail-on-drift`, but that should remain off in CI until the dynamic routes and
non-JSON routes are fully classified.

Current v0 output on this repository reports 0 unclassified potential drift
items. It classifies 29 backend routes without static frontend matches as known
ownership categories, including direct-fetch control/telemetry, binary URL
resources, dynamic research/config/memory helpers, agent inbox APIs, legacy chat
review actions, self-evolution auxiliary APIs, research organization proposal
APIs, generated tool validation, and worktree run detail/SSE APIs.

## Validation

The original audit was produced from read-only static inspection. The advisory
scanner v0 is covered by `tests/test_api_contract_audit.py`.
