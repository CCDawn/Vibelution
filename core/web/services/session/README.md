# Session service modules (`core/web/services/session`)

Agent-oriented ownership map for the Chat/Coding **session hot path**.
Prefer editing a **slice module** over growing `session_service.py` when possible.

Canonical product flow: `docs/agents/conversation-flow-map.md`.

During P0 structure work, `session_service.py` remains the **public import facade** for routes and other services (`from core.web.services.session_service import ...`). New logic should land in this package and be re-exported from the facade when it is part of the public API.

## Ownership map (claim scopes)

| Task type | Prefer these files | Avoid |
|-----------|-------------------|--------|
| Session list index cache / prewarm signatures | `list_cache.py` | stream capture, agent turn |
| Live output checkpoint / recovery state | `live_output.py` | submit validation, stream publish |
| Conversation events cache, ledger seq helpers | `journal_bridge.py` | LLM invoke, live recovery reconcile |
| `submit_session_message*` / guidance / edit-resubmit entry | `submit.py` | team workflow orchestration, worker loop |
| Turn queue / schedule / executor handoff | `schedule.py` | candidate store, full worker loop |
| `_run_session_turn` / continuation loop | `worker.py` (planned) | team SC search |
| UI stream to journal / `assistant_delta` batching | `stream_capture.py` | list cache, SSE transport publish |
| Persist turn outcome / final `session_detail` | `persist.py` (planned) | agent directory CRUD |
| Session detail/list DTO projection helpers | `projection.py` (planned) | runtime daemon |
| Public HTTP-facing API surface | `../session_service.py` (facade) | inlining new 500-line blocks |

## Flow map to planned modules

| Flow map step | Owner (target) |
|---------------|----------------|
| POST messages / Prefer async | `submit.py` |
| turn_started / user_message journal | submit + `journal_bridge.py` |
| schedule background turn | `schedule.py` |
| run turn / create agent | `worker.py` |
| UI stream capture | `stream_capture.py` |
| persist assistant_message / turn_* | `persist.py` |
| list/detail index cache | `list_cache.py` |
| live output checkpoint | `live_output.py` |

## Sole-owner rules

1. **One schedule/worker path** for a session turn — do not add a second executor that runs `run_single_turn` for the same session family.
2. **`turn_journal` / conversation ledger** is the durable fact source; SSE is transport.
3. Do not open a second session EventSource protocol; stream ownership stays on `stream_session_events` + capture pipeline.
4. Do not change journal event type strings or SSE event names in mechanical splits.
5. Prefer re-export from `session_service.py` over updating every importer until Stage 5.

## Extraction progress

- **Done:** `list_cache.py` (session list signature + inflight cache).
- **Done:** `live_output.py` (state dataclass, in-memory store, checkpoint I/O + visibility).
  - Facade still owns: timeline/codex payload enrichment, `_set_session_live_output` stream publish, chat-state recovery, progress/status labels.
- **Done:** `journal_bridge.py` (events signature cache, append, ledger seq, snapshot).
  - Facade thin-wraps with `project_root=PROJECT_ROOT` so monkeypatches / agent-kernel root binding keep working.
  - Still on facade: stale-ledger reconcile, visible-message projection, truncate-before-message.
- **Done:** `submit.py` (`submit_session_message*`, guidance, edit-resubmit, pure message resolve helpers).
  - Bodies late-bind facade helpers via `_service()` to avoid import cycles; schedule/worker still on facade.
- **Done:** `schedule.py` (queue/schedule/release adapters, external slot reserve, mark queued/dequeued).
  - Facade keeps `_SESSION_EXECUTOR` + `_SESSION_TURN_SCHEDULER` globals so conftest monkeypatches stay effective;
    schedule functions resolve them at call time via `_service()`.
  - Still on facade: running-session flags, `SessionTurnControl`, `_run_session_turn` worker.
- **Done:** `stream_capture.py` (`SessionTurnCapture`, text batcher, `_capture_session_ui_stream`, UI hooks).
  - Late-bound facade sanitizers/live_output/journal; ContextVar store re-exported from facade.
  - Still on facade: SSE `_publish_session_assistant_delta` / stream subscribers / detail snapshot publish.
- **Planned:** worker, persist, projection.

## Related

- Routes: `core/web/routes/sessions.py`
- Domain: `core/chat/*` (ledger, context assembler)
- Agent turn: `agent.py` (out of P0 deep cut)
- Structure plan: `docs/plans/2026-07-20-backend-structure-p0.md`
