# Session service modules (`core/web/services/session`)

Agent-oriented ownership map for the Chat/Coding **session hot path**.
Prefer editing a **slice module** over growing `session_service.py` when possible.

Canonical product flow: `docs/agents/conversation-flow-map.md`.

`session_service.py` remains the **public import facade** for routes and other services
(`from core.web.services.session_service import ...`). New hot-path logic should land in
this package and be re-exported from the facade when it is part of the public API.

**P0 structure closed** (2026-07-21): see `docs/plans/2026-07-21-backend-structure-p0-completion.md`.

**Service optimization Phase 3** (2026-07-21): projection + SSE publish packs — `docs/plans/2026-07-21-service-optimization-phase3-session-projection.md`.

**Service optimization Phase 4** (2026-07-21): stop control + agent session lifecycle — `docs/plans/2026-07-21-service-optimization-phase4-session-lifecycle.md`.

## Ownership map (claim scopes)

| Task type | Prefer these files | Avoid |
|-----------|-------------------|--------|
| Session list index cache / prewarm signatures | `list_cache.py` | stream capture, agent turn |
| Live output checkpoint / recovery state | `live_output.py` | submit validation, stream publish |
| Conversation events cache, ledger seq helpers | `journal_bridge.py` | LLM invoke, live recovery reconcile |
| `submit_session_message*` / guidance / edit-resubmit entry | `submit.py` | team workflow orchestration, worker loop |
| Turn queue / schedule / executor handoff | `schedule.py` | candidate store, full worker loop |
| `_run_session_turn` / continuation loop | `worker.py` | team SC search, SSE transport |
| UI stream to journal / live_output batching | `stream_capture.py` | list cache, SSE transport publish |
| Persist turn outcome / final assistant + turn_* | `persist.py` | agent directory CRUD, SSE transport |
| Session detail/list DTO projection | `projection.py` | SSE transport publish |
| SSE `assistant_delta` / `session_detail` publish | `publish.py` | DTO projection builders |
| Stop / interrupt turn control | `control.py` | agent purge/archive |
| Agent session purge/archive/child/inbox/cli lifecycle | `agent_sessions.py` | list/detail projection |
| Conversation/agent index create/repair/metadata | `conversation_index.py` | SSE publish |
| Live-output write / checkpoint bridge | `live_output_write.py` | pure store in `live_output.py` |
| Timeline / tool / mental-snapshot normalizers | `timeline.py` | turn diagnostics |
| Turn errors / work-runs / review / ledger reconcile | `turn_diagnostics.py` | timeline normalizers |
| Agent binding / prompt snapshot / LLM runtime | `agent_runtime.py` | image store |
| Context segment / provider cache estimation | `cache_context.py` | agent binding |
| Image artifact / attachment store-resolve | `image_attachments.py` | agent image-input policy |
| Runtime-scene session event logging | `events.py` | session ops/update helpers |
| Session update / prewarm / transcript / repair ops | `session_ops.py` | pure event recorders |
| Residual helpers | `../session_service.py` (facade remainder) | new mega public APIs on facade |
| Public HTTP-facing API surface | `../session_service.py` (facade) | bypassing re-exports |

## Flow map to modules

| Flow map step | Owner |
|---------------|--------|
| POST messages / Prefer async | `submit.py` |
| turn_started / user_message journal | submit + `journal_bridge.py` |
| schedule background turn | `schedule.py` |
| run turn / create agent | `worker.py` |
| UI stream capture | `stream_capture.py` |
| persist assistant_message / turn_* | `persist.py` |
| list/detail index cache | `list_cache.py` |
| live output checkpoint | `live_output.py` |
| SSE `assistant_delta` / `session_detail` publish | `publish.py` |
| detail/list DTO projection | `projection.py` |

## Sole-owner rules

1. **One schedule/worker path** for a session turn — do not add a second executor that runs `run_single_turn` for the same session family.
2. **`turn_journal` / conversation ledger** is the durable fact source; SSE is transport.
3. Do not open a second session EventSource protocol; stream ownership stays on `stream_session_events` + capture pipeline.
4. Do not change journal event type strings or SSE event names in mechanical splits.
5. Prefer re-export from `session_service.py` over updating every importer until a later import-migration stage.

## Extraction progress

### Stage 2 closed (hot path)

| Module | ~LOC | Role |
|--------|------|------|
| `list_cache.py` | ~258 | list index signature + inflight cache |
| `live_output.py` | ~288 | live state store + checkpoint I/O |
| `journal_bridge.py` | ~238 | events cache + append + ledger seq |
| `submit.py` | ~916 | message / guidance / edit-resubmit entry |
| `schedule.py` | ~313 | queue / executor handoff / external slot |
| `stream_capture.py` | ~1179 | UI capture + batching + hooks |
| `worker.py` | ~1288 | run turn + continuation loop |
| `persist.py` | ~1001 | turn result / failure / terminal fallback |

### Service optimization Phase 3 (projection + publish)

| Module | ~LOC | Role |
|--------|------|------|
| `publish.py` | ~0.8k | SSE stream + detail/delta publish + queue coalesce |
| `projection.py` | ~3.1k | list/detail DTO + summary/cache composition builders |

### Service optimization Phase 4 (control + agent sessions)

| Module | ~LOC | Role |
|--------|------|------|
| `control.py` | ~0.35k | stop/interrupt turn + paused/stopped result builders |
| `agent_sessions.py` | ~3.2k | purge/archive/delete/reset, child sessions, inbox wake, CLI lifecycle |
| `session_service.py` facade (after Phase 4) | ~13.4k total lines | re-exports + remaining shared helpers |

### Service optimization Phase 7 (conversation index + live write)

| Module | ~LOC | Role |
|--------|------|------|
| `conversation_index.py` | ~1.8k | create/select/query session, agent metadata, index repair |
| `live_output_write.py` | ~0.7k | set live overlay + checkpoint bridge |
| `session_service.py` facade (after Phase 7) | ~11.1k total lines | re-exports + residual helpers |

### Service optimization Phase 8 (timeline + turn diagnostics)

| Module | ~LOC | Role |
|--------|------|------|
| `timeline.py` | ~1.1k | preflight, tool/feedback normalize, mental snapshot, assistant timeline |
| `turn_diagnostics.py` | ~1.7k | turn errors, work-runs, review candidates, ledger reconcile, SC post-turn bridge |
| `session_service.py` facade (after Phase 8) | ~8.5k total lines | re-exports + residual helpers |

### Service optimization Phase 9 (agent runtime / cache / image)

| Module | ~LOC | Role |
|--------|------|------|
| `agent_runtime.py` | ~1.1k | acquire agent, prompt snapshot, binding recovery, LLM diagnostics |
| `cache_context.py` | ~0.4k | context segments + provider cache estimation |
| `image_attachments.py` | ~0.5k | image artifact store/resolve + LLM attachments |
| `session_service.py` facade (after Phase 9) | ~6.8k total lines | re-exports + residual event/logging glue |

### Service optimization Phase 10 (events + session ops)

| Module | ~LOC | Role |
|--------|------|------|
| `events.py` | ~0.7k | list/query/prewarm/turn lifecycle/skill/delete/guidance runtime-scene events |
| `session_ops.py` | ~1.4k | update session/title/reasoning, prewarm, message builders, codex transcript, repair |
| `session_service.py` facade (after Phase 10) | ~4.8k total lines | re-exports + thinner residual glue |

**Stage 2 exit (met):** hot-path claims for submit → schedule → capture → worker → persist.

**Phase 3–10 exit:** projection/publish/control/lifecycle/index/live/timeline/turn/agent-runtime/cache/image/events/ops claimable.

**Still deferred:**

- Full facade slim to re-exports only (remaining shared constants/types/glue).
- Late-bind removal.
- Secondary gods (`runtime_scene`, `agent_directory`).

## Related

- Routes: `core/web/routes/sessions.py`
- Domain: `core/chat/*` (ledger, context assembler)
- Agent turn: `agent.py` (out of session P0 deep cut)
- Phase 3 plan: `docs/plans/2026-07-21-service-optimization-phase3-session-projection.md`
- Phase 4 plan: `docs/plans/2026-07-21-service-optimization-phase4-session-lifecycle.md`
- Structure plan: `docs/plans/2026-07-20-backend-structure-p0.md`
