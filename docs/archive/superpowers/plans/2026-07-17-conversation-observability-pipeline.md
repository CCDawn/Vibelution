# Conversation Observability Pipeline Implementation Plan

**Status:** proposed-plan

**Owner:** conversation-chain observability lane

**Scope:** Unify Vibelution conversation logging into one traceable, bounded, secret-safe, low-overhead pipeline from browser submit through API, turn orchestration, LLM, tools, canonical outcome, frontend projection, and final paint.

**Supersedes:** the logging portions of `2026-07-06-self-observation-time-machine.md`, `2026-07-10-chat-llm-payload-trace.md`, and `2026-07-13-codex-conversation-chain-alignment-closure.md`. Their business behavior remains valid; this plan consolidates their observability mechanisms.

## 1. Observable outcome

Given any one of `traceId`, `sessionId`, or `turnId`, an Agent must be able to answer, without broad log scans:

1. Did the user request reach the backend and get accepted?
2. Which model route and protocol were used, including retries and fallback?
3. Where was time spent: queue, context, provider TTFT, generation, tools, persistence, SSE, projection, or paint?
4. Which tools were visible, authorized, invoked, completed, denied, timed out, or rebound?
5. Which assistant items became canonical and which frontend items were merged, suppressed, replaced, or rendered?
6. What terminal state was reached, and which evidence is missing or degraded?
7. Did logging itself materially affect the turn?

The default diagnostic result must be a compact structured summary. Raw events are follow-up evidence, not the first analysis surface.

## 2. Non-goals

- Do not log full prompts, full model payloads, secrets, credentials, complete tool output, large diffs, or arbitrary user content.
- Do not make OpenTelemetry or an external collector a runtime dependency.
- Do not replace the canonical conversation ledger or turn journal with telemetry.
- Do not emit one log event per streamed token or React render.
- Do not build another parallel runtime-scene store.
- Do not make successful conversation execution depend on best-effort telemetry persistence.

## 3. Architecture decision

Use one project-native pipeline:

```text
Instrumentation call
  -> TraceContext enrichment
  -> Event schema validation and redaction
  -> Priority-aware bounded queue
  -> Single async writer
  -> Canonical segmented event stream
  -> Async derived projections
       -> runtime-scene timeline/component views
       -> per-turn diagnostic summary
       -> Agent query index
       -> optional external OTEL adapter later
```

The existing `unified_logger` becomes the producer facade. The existing runtime-scene package remains the evidence bundle. Existing timeline, lifecycle, component, and conversation files become derived compatibility views instead of independent producer writes.

Adopt W3C-compatible `traceId`, `spanId`, and `parentSpanId` semantics without adding a new dependency. This aligns with Codex trace propagation while keeping local logging fully functional when external tracing is disabled.

## 4. Sources of truth

| Fact | Canonical source | Writer | Derived views | Failure behavior |
| --- | --- | --- | --- | --- |
| Conversation state and visible history | conversation ledger and turn journal | session/conversation services | UI messages, visible message evidence | state write failure remains a conversation error |
| Turn terminal state | turn journal terminal event | turn persistence owner | turn result, diagnostics, UI terminal state | must not silently degrade |
| Operational telemetry event | canonical segmented scene event stream | single event writer | timeline, lifecycle, component files, summaries | best effort by priority |
| Trace identity | immutable `TraceContext` created at request acceptance | request/turn boundary | every child event/span | missing propagation records an invariant violation |
| Per-turn diagnosis | projection of journal plus canonical telemetry | diagnostic projector | Agent tool, CLI, API | rebuildable; never overrides canonical facts |
| Logging performance | event-pipeline self metrics | writer and queue | runtime summary, diagnostics | metrics failure cannot recurse into the same logger |

## 5. Canonical identity model

Every conversation event uses the same envelope:

```json
{
  "schemaVersion": 3,
  "eventId": "evt_...",
  "timestamp": "2026-07-17T00:00:00.000Z",
  "sequence": 123,
  "runtimeSceneId": "...",
  "traceId": "32-lowercase-hex",
  "spanId": "16-lowercase-hex",
  "parentSpanId": "16-lowercase-hex-or-empty",
  "requestId": "...",
  "sessionId": "...",
  "turnId": "...",
  "invocationId": "...",
  "routeAttemptId": "...",
  "toolCallId": "...",
  "itemId": "...",
  "component": "llm",
  "phase": "stream",
  "eventCode": "llm.stream.first_content_delta",
  "level": "info",
  "outcome": "observed",
  "priority": "operational",
  "durationMs": 12.3,
  "fields": {}
}
```

Identity rules:

- `traceId` is created once when a user turn is accepted and remains stable through final browser paint.
- `spanId` changes for each bounded phase. `parentSpanId` represents causal ownership, not merely temporal adjacency.
- `sessionId` groups conversation history; `turnId` is the canonical business execution unit.
- `invocationId` identifies one logical LLM invocation; `routeAttemptId` identifies retries or fallback routes.
- `toolCallId` is mandatory for tool proposal, authorization, execution, result, projection, and replay events.
- `itemId` is mandatory for assistant item commit and frontend projection decisions.
- No component may generate a replacement `traceId` after request acceptance.

## 6. Event priorities and durability

| Priority | Examples | Queue/full behavior | Flush behavior |
| --- | --- | --- | --- |
| `state` | turn journal terminal event, canonical outcome persistence | never routed through lossy telemetry queue | synchronous state contract |
| `critical` | errors, invariant violations, authorization denial, writer degradation | reserve queue capacity; spill to emergency bounded file | flush at terminal/error boundary |
| `operational` | phase start/end, route attempt, tool lifecycle, first chunk/content | batch; backpressure for a short bounded interval | periodic batch or turn terminal |
| `diagnostic` | successful API request, browser long task, cache detail | sample/coalesce/drop under pressure | periodic batch |
| `debug` | verbose implementation details | disabled by default | no durability guarantee |

Only state facts may block the conversation by contract. Telemetry failures must produce a bounded degradation marker and must not recursively log through the failed sink.

## 7. Required phase spans

The critical path for each turn is represented by spans:

```text
browser.submit
api.request
turn.accept
turn.queue_wait
context.prepare
llm.preflight
llm.route_attempt
llm.provider_wait_first_chunk
llm.provider_wait_first_content
llm.generate
tool.authorize
tool.execute
tool.bind_result
outcome.finalize
turn.persist
sse.commit
frontend.project
frontend.paint_terminal
```

Each span records start, end, outcome, duration, and bounded categorical fields. Open spans at interruption or restart are closed as `abandoned`, `interrupted`, or `recovered`; they are never silently reported as successful.

## 8. Recording effectiveness contract

### LLM

Record effective provider/model/profile/protocol, cache composition, bounded token usage, route attempt, retry reason code, first chunk/content latency, generation duration, canonical item count, and terminal outcome. Preserve protocol-native semantics for Responses and Chat; do not normalize wire payloads into each other.

### Tools

Record exposed tool-set digest and count once per turn, then proposal, authorization decision, execution start/end, timeout/cancel/error classification, result digest/size, and binding/replay outcome by `toolCallId`. Do not repeatedly log the entire allowed tool list.

### Frontend

Record submit acknowledgement, SSE connection state, stable `itemId`, projection source, merge/dedupe/suppression decision, render key, terminal projection, and final paint. Coalesce streamed updates; record first meaningful item, structural transitions, anomalies, and terminal paint rather than every delta/render.

### API and polling

Record failures and slow requests at 100%. Aggregate ordinary successful polling by route and time window. Preserve individual successful requests only when they belong to an active trace or exceed the slow threshold.

### Errors and fallbacks

Use stable `errorCode`, `failureClass`, `upstreamCauseCode`, `retryable`, `degradedScope`, and `evidenceRefs`. Human text is supplemental and bounded. Fallback, partial, recovered, and compatibility states must not be logged as normal success.

## 9. Per-turn diagnostic summary

At terminal, interruption, timeout, or stale-turn repair, project `diagnostic_summary.json`:

```json
{
  "schemaVersion": 1,
  "traceId": "...",
  "sessionId": "...",
  "turnId": "...",
  "status": "completed",
  "terminalAuthority": "turn_journal",
  "criticalPathMs": 18420,
  "slowestPhase": "llm.provider_wait_first_content",
  "phaseDurations": {},
  "routeAttempts": [],
  "toolSummary": {},
  "frontendSummary": {},
  "loggingOverhead": {},
  "invariantViolations": [],
  "missingEvidence": [],
  "evidenceRefs": []
}
```

The diagnosis is deterministic and rebuildable. It may identify a bottleneck or violated invariant, but it must distinguish facts from hypotheses.

## 10. Agent analysis interface

Upgrade `conversation_log_inspect_tool` and `diagnose_session_turn.py` to use exact identity lookup:

- Input accepts one or more of `traceId`, `sessionId`, `turnId`, `toolCallId`, and a bounded time range.
- Exact per-turn artifacts and journal are searched before scene-wide indexes.
- Output starts with status, bottleneck, failure chain, missing evidence, logging health, and evidence references.
- Raw text search is a final fallback and is labeled `degraded_lookup`.
- Query miss never falls back to an unrelated latest turn.
- Tool output remains bounded, redacted, and available only to Agent profiles explicitly assigned the diagnostic tool.

## 11. Performance budget

Initial acceptance budgets:

| Metric | Budget |
| --- | ---: |
| Producer enqueue p95 | <= 0.20 ms |
| Producer enqueue p99 | <= 1.00 ms |
| Critical terminal flush p95 | <= 20 ms |
| Total operational logging CPU per normal turn | <= 1% of turn wall time and <= 50 ms |
| Normal queue depth | < 25% capacity |
| Queue saturation duration | < 1 second |
| Canonical-to-physical write amplification | <= 1.5x before optional raw logs |
| Dropped `critical` or `operational` events | 0 |
| Dropped diagnostic events | reported, never silent |
| Default event serialized size | <= 4 KiB |
| Scene segment rotation | 4 hours or 64 MiB, whichever comes first |
| Agent exact-turn diagnosis p95 | <= 200 ms at 100k scene events |

Defaults: bounded queue 8192 events, batches up to 64 events or 50 ms, cached file handles, and terminal flush with a bounded timeout. Final defaults must be adjusted from measured baseline rather than assumed throughput.

## 12. Backpressure and degradation

- Reserve queue capacity for `critical` and `operational` events.
- Drop/coalesce `debug` first, then sampled `diagnostic`; never silently drop higher priorities.
- Emit non-recursive counters for queue depth, enqueue latency, batch size, write latency, bytes, rotations, drops, redaction failures, decode failures, and writer restarts.
- On writer failure, retain a bounded in-memory critical ring and write one emergency marker to a dedicated fallback file or stderr.
- On shutdown, flush in parallel with a hard timeout; telemetry timeout must not block Launcher indefinitely.
- On restart, detect and close orphan spans and rebuild missing summaries from canonical events plus turn journal.

## 13. Storage, retention, and privacy

- Canonical event streams are append-only and segmented by scene rotation.
- Timeline/component/lifecycle files are derived and rebuildable.
- Keep per-turn summaries longer than detailed operational telemetry.
- Apply retention by class: summaries and critical errors longest, operational events medium, sampled diagnostic/debug shortest.
- Redact before queueing so secrets never enter memory buffers or fallback files.
- Store hashes, lengths, counts, categories, and bounded identifiers instead of prompt/tool output content.
- Maintain explicit allowlists for field names and cardinality. Reject or truncate unknown high-cardinality fields.
- Record `redactionApplied`, `truncatedFields`, and payload byte counts without recording the removed value.

## 14. Configuration

Add operator-configurable logging policy through the existing config source of truth:

```toml
[logging.pipeline]
enabled = true
queue_capacity = 8192
batch_size = 64
flush_interval_ms = 50
terminal_flush_timeout_ms = 1000
segment_max_mib = 64
segment_max_hours = 4

[logging.sampling]
successful_polling = 0.02
browser_frame = 0.05
slow_request_ms = 250

[logging.retention]
critical_days = 30
operational_days = 14
diagnostic_days = 7
summary_days = 90
```

Safe defaults remain project-owned. Invalid or extreme values fail validation instead of silently producing unbounded logging.

## 15. Implementation task graph

### Task 1: Baseline and logging self-observability

- **Owner/Boundary:** logging core only; no producer migration.
- **Produces:** enqueue/write/flush/queue/bytes/drop metrics and a repeatable synthetic plus real-turn baseline report.
- **Files:** `core/logging/`, runtime-scene summary projection, focused logging tests.
- **Mode:** BDD_TDD.
- **Verification/Stop:** metrics must not recurse through the measured sink; stop if current call paths cannot distinguish state persistence from telemetry.

### Task 2: Canonical schema and trace propagation

- **Dependency:** Task 1 baseline.
- **Owner/Boundary:** identity and schema; no asynchronous storage cutover yet.
- **Produces:** immutable TraceContext, schema-v3 event validation, browser/API/turn/LLM/tool/projection propagation, invariant events for missing identity.
- **Files:** new focused modules under `core/logging/`, LLM invocation context, session request/turn boundaries, frontend stream protocol and API request helper.
- **Mode:** BDD_TDD.
- **Verification/Stop:** Responses and Chat golden chains must preserve one `traceId`; no secrets or full content may enter the envelope.

### Task 3: Priority-aware async canonical writer

- **Dependency:** Tasks 1-2.
- **Owner/Boundary:** replace telemetry fanout writes; do not change turn-journal durability.
- **Produces:** bounded queue, batching, cached handles, segment rotation, emergency degradation path, clean shutdown.
- **Files:** `core/logging/`, runtime-scene writer/service, Launcher shutdown integration.
- **Mode:** BDD_TDD.
- **Verification/Stop:** meet enqueue and terminal-flush budgets; forced writer failure must not deadlock a turn or Launcher.

### Task 4: Derived views and exact-turn diagnosis

- **Dependency:** Task 3 canonical stream.
- **Owner/Boundary:** rebuildable projections and Agent query surfaces.
- **Produces:** compatibility timeline/component/lifecycle views, per-turn diagnostic summary, exact identity index, corrected CLI and inspection tool.
- **Files:** runtime-scene projection/index service, `diagnose_session_turn.py`, conversation log tool, focused diagnostic tests.
- **Mode:** BDD_TDD.
- **Verification/Stop:** complete, failed, timed-out, interrupted, recovered, and missing-artifact fixtures must produce deterministic summaries with no unrelated matches.

### Task 5: Frontend projection and render evidence

- **Dependency:** Task 2 trace context and Task 4 diagnostic contract.
- **Owner/Boundary:** browser telemetry only; no rendering behavior changes unless a separately confirmed bug is found.
- **Produces:** projection decision, dedupe/suppression reason, structural stream transition, terminal paint and long-task correlation.
- **Files:** chat stream protocol, timeline projection hooks, ConversationView telemetry adapter, frontend tests.
- **Mode:** BDD_TDD.
- **Verification/Stop:** telemetry must be coalesced and sampled; render count must not materially increase.

### Task 6: Migration cleanup and production gate

- **Dependency:** Tasks 3-5 pass compatibility and performance gates.
- **Owner/Boundary:** remove direct legacy telemetry writes only after derived views prove parity.
- **Produces:** one producer facade, no dual-write drift, retention cleanup, operator config, documentation, refreshed runtime evidence.
- **Mode:** BDD_TDD.
- **Verification/Stop:** compare old/new event semantics and performance; rollback if any critical event is lost or p95 turn latency regresses beyond noise.

## 16. Serial and parallel boundaries

Critical path is Task 1 -> Task 2 -> Task 3 -> Task 4 -> Task 6.

Task 5 may run after Task 2 in parallel with the storage portion of Task 4, but its diagnostic contract must reconcile before Task 6. Shared schema, runtime-scene writer, session-service event boundaries, and frontend stream DTOs are serialized hot files.

## 17. Verification matrix

| Area | Required evidence |
| --- | --- |
| Schema | required IDs, bounded fields, version migration, invalid-field rejection |
| Propagation | browser-to-paint trace continuity across Responses, Chat, retry, fallback, and tool loops |
| Durability | terminal/error preservation, crash recovery, partial write handling, segment rotation |
| Backpressure | queue saturation, priority preservation, drop counters, shutdown timeout |
| Privacy | API keys, auth headers, URLs with credentials, prompt/tool output and exception strings redacted before enqueue |
| Diagnostics | complete, failed, interrupted, stopped, stale, replayed and projection-error golden fixtures |
| Performance | baseline versus candidate enqueue p95/p99, writer throughput, event bytes, physical amplification, turn wall time |
| Frontend | no per-token/per-render event storm, stable IDs, dedupe/suppression evidence, terminal paint correlation |
| Compatibility | existing runtime-scene consumers, log routes and Agent tool continue to work during migration |

Focused tests are followed by the affected backend suites, frontend stream/conversation suites, production web build, closeout gate, Launcher refresh, and one live short turn plus one tool turn. Live verification must report actual trace continuity and measured logging overhead rather than only health status.

## 18. Rollback strategy

- Each task lands independently behind internal compatibility boundaries.
- Task 2 identity fields are additive and can remain if later storage work rolls back.
- Task 3 keeps the previous sink available as a temporary fallback flag until Task 6, but only one sink is active for each event to avoid dual-write ambiguity.
- Derived views are rebuildable from canonical events; projection failure never deletes canonical data.
- Task 6 removes compatibility writers only after one complete runtime-scene rotation with parity evidence.
- No schema or storage cleanup is destructive until retention and rebuild tests pass.

## 19. Completion criteria

The migration is complete only when:

- one trace links browser submit through terminal paint;
- every turn has terminal or explicit interrupted/recovered evidence;
- the Agent inspection tool identifies the correct bottleneck and failure chain without broad scanning;
- logging self-metrics prove budget compliance;
- physical write amplification is within budget;
- critical/operational event loss is zero under tested pressure;
- secret-safety tests pass before enqueue and in emergency paths;
- legacy direct fanout writers are removed or explicitly retained as documented state owners;
- Launcher-refreshed live evidence confirms the running `main` uses the new pipeline.

## 20. Version and refresh impact

Version impact: patch-level runtime and diagnostic behavior change unless public API fields become externally committed, in which case reassess minor impact.

Launcher refresh: required after Tasks 2, 3, 5, and 6 before live verification. Planning-only changes do not require refresh.
