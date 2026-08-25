# Session service modules (`core/web/services/session`)

Agent-oriented ownership map for the Chat/Coding **session hot path**.
Prefer editing a **slice module** over growing `session_service.py` when possible.

Canonical product flow: `docs/agents/conversation-flow-map.md`.

`session_service.py` remains the **public import facade** for routes and other services
(`from core.web.services.session_service import ...`). New hot-path logic should land in
this package and be re-exported from the facade when it is part of the public API.

Historical structure/optimization notes (non-authoritative): `docs/archive/plans/2026-06-07/`.

## 30-second routing (edit here first)

| You are changing… | Open first |
|-------------------|------------|
| Submit / guidance / edit-resubmit | `submit.py` |
| Turn schedule / executor handoff | `schedule.py` |
| Run turn / continuation loop | `worker.py` |
| Stream capture / UI batching | `stream_capture.py` |
| Persist turn result / failure | `persist.py` |
| List/detail DTO projection | `projection.py` |
| SSE publish / assistant_delta | `publish.py` |
| Stop / interrupt turn | `control.py` |
| Agent purge/archive/child/inbox/cli | `agent_sessions.py` |
| Create/select session / index repair | `conversation_index.py` |
| List cache / prewarm | `list_cache.py` + `session_ops.py` |
| SQLite session catalog reconcile | `catalog_bridge.py` |
| Live session directory store (ConversationStore) | `directory_runtime.py` + `directory_bridge.py` |
| Live overlay / checkpoint | `live_output.py` + `live_output_write.py` |
| Timeline / tool normalize | `timeline.py` |
| Turn errors / work-runs / review | `turn_diagnostics.py` |
| Agent bind / prompt snapshot / LLM slot | `agent_runtime.py` |
| Image store/resolve | `image_attachments.py` |
| Session runtime-scene events | `events.py` |
| Title / reasoning / prewarm / ops helpers | `session_ops.py` |
| Failure signals / visible reply / image-retry cues | `signals_format.py` |
| Running state / workspace / codex / SC bridge glue | `runtime_glue.py` |
| Public import surface only | `../session_service.py` (prefer re-export, not new business bodies) |

Product flow map: `docs/agents/conversation-flow-map.md`. Structure awareness (soft): `docs/standards/development-standard.md` §8.3.

## Ownership map (claim scopes)

| Task type | Prefer these files | Avoid |
|-----------|-------------------|--------|
| Session list index cache / prewarm signatures | `list_cache.py` | stream capture, agent turn |
| Session catalog source projection / reconcile | `catalog_bridge.py` | canonical writes, HTTP DTO projection |
| Live session directory (SQLite control plane) | `directory_runtime.py`, `directory_bridge.py` | turn journal transcript, Agent config authority; list/query use `LIST_QUERY_STARTUP_WAIT_SECONDS=0` and do not fall back to `chat_state`; default list hides `team_agent` / `team_private` unless experiment-bound; visible personal Agent stubs are merged from `directSessionId` |
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
| Failure signals / reply format / image-retry cues / cache metadata | `signals_format.py` | submit worker hot path |
| Agent/team/workspace / running state / codex / SC bridges | `runtime_glue.py` | lifecycle serializers |
| Residual helpers | `../session_service.py` (facade remainder: lifecycle serializers) | new mega public APIs on facade |
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

## 链路诊断约定

- 提交阶段将受管的 `trace_context_carrier` 透传到 `scheduled` / `accepted` / `started` 事件；worker 进入线程池后创建 child span，并在整个 turn 生命周期内绑定，生命周期与子包日志因此可用 `traceId`、`spanId`、`parentSpanId`、`requestId` 串联。
- SSE 连接记录 `session.stream.opened`、`session.stream.failed`、`session.stream.closed`，使用同一个 `streamConnectionId`，并保留 transport、initial mode、持续时间、发送事件数、心跳数和受控 `errorType`；不改变既有 SSE event 名称或 payload。
- conversation ledger 只在 `turn_completed` / `turn_failed` / `turn_interrupted` 完成 `fsync` 后记录 `conversation.ledger.terminal_committed`，携带 sequence、eventId、耗时和 durability；普通 append 不记录成功事件。append 失败只保留异常类型和消息长度，不记录异常正文。
- 诊断字段只记录边界元数据，不记录完整 Prompt、响应正文或异常消息；高频健康事件仍由既有采样/节流策略控制。

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
- Agent turn: `agent.py`
- Conversation map: `docs/agents/conversation-flow-map.md`
- Historical plans: `docs/archive/plans/2026-06-07/`


### Service optimization Phase 16 (signals + runtime glue)

| Module | ~LOC | Role |
|--------|------|------|
| `signals_format.py` | ~1.6k | failure signals, history/reply, image-retry, cache metadata |
| `runtime_glue.py` | ~2.4k | agent/team/workspace, running state, codex/SC bridges |
| `session_service.py` facade (after Phase 16) | ~1.4k | re-exports + lifecycle serializers only |
