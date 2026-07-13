# Canonical LLM Lifecycle Single-Owner Design

**Date:** 2026-07-13
**Status:** Draft for user review
**Target release impact:** patch
**Required runtime refresh:** yes, before runtime acceptance

## 1. Confirmed Intent

Vibelution must expose one coherent conversation lifecycle across Chat Completions and Responses:

```text
commentary -> tool call -> tool result -> final answer -> terminal state
```

The model protocol may differ, but protocol-specific facts must enter one canonical event and outcome model before Agent orchestration, journal persistence, session projection, or frontend rendering. Production code must not down-convert canonical facts to compatibility messages and later reconstruct the canonical lifecycle from those projections.

This design is the first remaining alignment stage after commit `efd440af`, which added active-process Responses bookmark and opaque replay continuation plus strict explicit protocol resolution.

## 2. Scope

This stage includes:

1. Make `LLMProtocolEvent` the only process-fact stream consumed by the production Agent loop.
2. Make `TurnOutcome` the only terminal snapshot for each model invocation iteration.
3. Add an explicit canonical non-stream outcome API and keep streaming on the existing canonical event API.
4. Pass active-process replay state explicitly through the invocation contract instead of recovering it from `AIMessage.additional_kwargs`.
5. Route native and legacy XML tool calls through the same canonical tool execution and journal path.
6. Remove production reconstruction of canonical state from `AIMessage`, `AIMessageChunk`, raw XML text, assistant deltas, or frontend DTOs.
7. Preserve one-way compatibility wrappers for callers that still require LangChain message types.
8. Keep SessionTurnItem v2 as the backend public projection of journal truth.

This stage excludes:

1. Durable encrypted replay persistence across process restart.
2. React layout or frontend projection precedence changes.
3. Native Anthropic Messages or Gemini adapters.
4. Provider/model configuration, operator TOML, credentials, and model discovery.
5. Credential fixture isolation, which must wait for the active configuration claims to complete.
6. Removal of compatibility wrappers used by non-Agent callers.
7. Remote push, release publication, or version-file changes.

## 3. Current Evidence

The current code has the required canonical primitives but does not preserve their ownership end to end:

| Surface | Current behavior | Gap |
|---|---|---|
| `core/llm/wire/*` | Chat and Responses decode provider facts into canonical events and `TurnOutcome` | Correct canonical source exists |
| `core/llm/client.py` | Canonical outcomes are converted back to `AIMessage`; stream events are converted to `AIMessageChunk` | Agent production path consumes a compatibility projection |
| Active Responses continuation | Latest replay state is recovered by scanning `AIMessage.additional_kwargs["turn_outcome"]` | Canonical state is indirectly reconstructed from a compatibility message |
| `agent.py` normal path | Can consume canonical outcome facts | Ownership is mixed with compatibility message handling |
| `agent.py` XML path | Parses text, executes tools directly, appends raw XML assistant content, and continues | Bypasses canonical ordering, identity, journal, and replay rules |
| Journal/session path | SessionTurnItem v2 and idempotent canonical item persistence exist | Compatibility deltas/transcripts can still participate in reconstruction |
| Frontend | Canonical projection has precedence | Frontend cleanup belongs to the next stage, not this design |

The gap is therefore lifecycle ownership, not another wire adapter.

## 4. Reuse Decision

Decision: `ADAPT + REFERENCE_ONLY`.

| Reference | Pattern to adapt | What is not copied |
|---|---|---|
| OpenCode | Durable message parts and in-place tool-part lifecycle transitions | Provider SDK and storage implementation |
| Pi Agent | Internal AgentMessage/Event stream with provider conversion only at the LLM boundary | Package API and event naming |
| Hermes | Explicit provider API mode and strict tool-message sequencing | Provider-specific client code |
| Codex | ResponseItem/TurnItem/EventMsg separation, stable item identity, started/completed lifecycle | Rust protocol implementation |

Direct source reuse requires a later per-file license and dependency review. This stage reuses architectural boundaries only.

## 5. Canonical Ownership Model

| Fact | Single owner | Consumers | Forbidden reconstruction source |
|---|---|---|---|
| Effective provider/model/wire route | `ResolvedProtocolRoute` | projector, adapter, retry, logging | model-name heuristic after route resolution |
| Invocation identity | `InvocationScope` | events, outcome, journal, logs | UI message IDs or timestamps |
| Streaming process facts | `LLMProtocolEvent` | Agent observer, journal bridge, runtime diagnostics | text-delta concatenation |
| Invocation terminal snapshot | `TurnOutcome` | Agent decision, tool loop, compatibility projection | `AIMessage.tool_calls` or finish reason reparsing |
| Active replay continuation | Explicit invocation argument carrying `ProviderReplayState` | semantic request projector | scanning compatibility messages |
| Tool execution result | Canonical tool executor result | next semantic request, journal | rendered tool text |
| Persisted public conversation | Conversation ledger and turn journal | SessionTurnItem v2 projection | frontend transcript or assistant delta |
| Compatibility message | `TurnOutcome` one-way projector | legacy/non-Agent callers | any production canonical owner |

No component may own both canonical state and a reverse parser from its own compatibility projection.

## 6. Invocation Contract

### 6.1 Canonical APIs

`LLMClient` exposes two production canonical entrypoints:

```python
def invoke_outcome(
    messages,
    *,
    tools=None,
    metadata=None,
    replay_state=None,
) -> TurnOutcome: ...

def stream_events(
    messages,
    *,
    tools=None,
    metadata=None,
    replay_state=None,
) -> Iterator[LLMProtocolEvent]: ...
```

The completed streaming iterator must expose exactly one `TurnOutcome` through its existing normalized stream outcome contract. The Agent orchestration helper, not `agent.py`, owns consuming the iterator and returning that outcome.

Existing `invoke()` and `stream()` remain one-way compatibility wrappers:

```text
canonical request -> canonical events/outcome -> compatibility AIMessage/AIMessageChunk
```

The reverse direction is forbidden in the production Agent path.

### 6.2 Explicit continuation

Within one effective route attempt:

1. `turnId` remains stable for the user-visible turn.
2. `invocationId` remains stable across tool iterations on the same route.
3. `iteration` increments for every model call after a tool result.
4. `ProviderReplayState` is passed directly from the previous `TurnOutcome` to the next canonical invocation.
5. A distinct fallback route receives a fresh `invocationId` with the existing lineage metadata.
6. Route compatibility is checked before provider I/O.

This stage keeps replay state in process memory only. A missing replay state after restoration must fall back to the complete canonical model projection or fail with a typed non-retryable compatibility error when the provider requires opaque state.

## 7. Lifecycle State Machine

Each model invocation iteration follows exactly one path:

```text
prepared
  -> streaming
  -> tool_calls | final_answer | incomplete | failed | cancelled
```

`tool_calls` is terminal for the current model invocation but non-terminal for the overall user turn. The Agent executes tools, appends canonical tool results, increments `iteration`, and starts the next invocation on the same route.

The overall user turn reaches exactly one terminal state:

```text
completed | incomplete | failed | cancelled
```

Lifecycle invariants:

1. Commentary and reasoning items may precede tool calls or the final answer but never become final history text.
2. A tool call is committed before its tool result.
3. Every tool result references an existing canonical `callId` or an approved provider bookmark continuation.
4. A final answer is committed once and only after all pending tool calls are resolved.
5. Exactly one terminal event is committed for an invocation.
6. Repeated stream chunks, provider terminal events, SSE reconnects, and journal retries are idempotent by canonical identity.
7. Cancellation cannot later be upgraded to completion by a late provider event.

Canonical item identity remains:

```text
(sessionId, turnId, invocationId, iteration, itemId, revision, kind, callId)
```

## 8. Agent Orchestration Boundary

`core/llm/invocation.py` becomes the narrow production bridge between Agent orchestration and `LLMClient`.

It owns:

1. Constructing or accepting `InvocationScope`.
2. Passing explicit replay state.
3. Publishing canonical process events to existing observers.
4. Returning exactly one `TurnOutcome`.
5. Mapping typed provider or protocol errors without reparsing provider text.

`agent.py` owns only turn policy:

1. Decide whether to execute returned canonical tool calls.
2. Execute tools through the existing canonical executor.
3. Add canonical tool results to the model projection.
4. Continue, finish, cancel, or invoke the already-designed bounded fallback route.

`agent.py` must not parse provider payloads, inspect finish reasons, recover replay state from `AIMessage`, or persist assistant facts independently of the canonical event/outcome bridge.

## 9. XML Tool Compatibility

The legacy XML path is quarantined behind a dedicated `LegacyXmlToolCallDecoder` in `core/llm/legacy_xml_tool_decoder.py`.

Rules:

1. It is selected only by an explicit existing route compatibility policy, never by model-name inference.
2. It accepts final model text and produces canonical tool-call objects with stable call IDs and parsed arguments.
3. Recognized malformed XML produces a typed `tool_call_decode_error` with a bounded safe summary.
4. Decoded calls enter the same `TurnOutcome`, tool executor, journal, iteration, replay, cancellation, and terminal logic as native calls.
5. Raw XML is never appended as an assistant history message when it represents tool control syntax.
6. Non-control text surrounding valid XML may be preserved only as commentary, not as a final answer.
7. The decoder emits a bounded deprecation observation so remaining XML-dependent routes can be measured before removal.

The current direct XML execute-and-continue branch is removed after parity tests pass. No second tool loop remains.

## 10. Journal And Session Projection

The journal bridge consumes canonical events and outcomes only.

Persistence rules:

1. Process events update or commit the matching SessionTurnItem v2 identity.
2. `TurnOutcome` closes the invocation state but does not duplicate already-committed items.
3. Canonical tool calls and tool results retain `callId` and ordering.
4. Commentary remains visible process history where allowed but is excluded from final model history.
5. Opaque replay bytes and raw provider payloads are never written to the journal or Session DTO.
6. `session_service.py` uses canonical v2 items when present and may read legacy delta/transcript data only when no canonical item exists for that historical turn.
7. Production code never creates new canonical items by parsing frontend DTOs.

The React rendering policy is unchanged in this stage. The next frontend stage will remove remaining projection competition after the backend contract is stable.

## 11. Error, Retry, And Cancellation Semantics

| Condition | Canonical result | Retry owner |
|---|---|---|
| Semantic projection failure | typed `payload_protocol_error` before provider I/O | none |
| Unsupported wire adapter | typed `unsupported_wire_protocol` before provider I/O | none |
| Provider retryable failure | failed route attempt with bounded diagnostics | existing `LLMClient` same-route retry |
| Distinct fallback | new invocation lineage and fresh route projection | Agent recovery policy |
| XML decode failure | typed non-provider `tool_call_decode_error` | none unless turn policy explicitly requests a new model attempt |
| User cancellation | canonical cancelled outcome and one terminal commit | none |
| Stream exhaustion without terminal | canonical incomplete outcome | existing recovery policy |

Retry and fallback code must consume typed categories and canonical outcomes. It must not infer retryability from rendered error text.

## 12. Bounded Observability

Required diagnostic facts:

```text
sessionId
turnId
invocationId
iteration
routeAttempt
provider/profile/model/wire identifiers
canonical event kind
itemId/revision/callId when applicable
outcome kind
replay state present/item count/byte count
compatibility projection emitted
legacy XML decoder selected/accepted/rejected
```

Forbidden diagnostic content:

```text
credentials
full prompts
full message content
raw provider payloads
raw opaque replay state
raw response bookmarks
large tool output
raw XML arguments when they may contain user data
```

Runtime-scene logs must permit an Agent to reconstruct lifecycle ordering from safe metadata without requiring the original prompt or provider response.

## 13. Planned Impact Surface

| File or module | Planned responsibility change |
|---|---|
| `core/llm/types.py` | Keep canonical event/outcome contracts authoritative; add only fields required by explicit lifecycle handoff |
| `core/llm/client.py` | Add canonical non-stream entrypoint; keep compatibility wrappers one-way; stop production replay recovery from messages |
| `core/llm/invocation.py` | Own canonical Agent invocation bridge and streaming outcome collection |
| `core/llm/provider_replay_state.py` | Remain route-scoped active continuation state; no persistence in this stage |
| `core/llm/legacy_xml_tool_decoder.py` | New isolated compatibility decoder producing canonical tool calls |
| `core/orchestration/turn_outcome.py` | Reconcile orchestration helpers with `core.llm.types.TurnOutcome`; do not create a second terminal truth model |
| `agent.py` | Consume canonical outcome, execute canonical tools, remove direct XML side loop and compatibility reparsing |
| `core/chat/conversation_ledger.py` | Keep model projection and canonical tool result ordering authoritative |
| `core/chat/turn_journal.py` | Persist canonical item lifecycle idempotently |
| `core/web/services/session_service.py` | Stop reconstructing canonical v2 facts when canonical journal items exist |

Expected focused test surfaces:

```text
tests/test_llm_client_outbound_wire_bridge.py
tests/test_llm_turn_assembler.py
tests/test_agent_protocol.py
tests/test_conversation_ledger.py
tests/test_session_turn_journal.py
tests/test_session_codex_transcript_projection.py
tests/test_session_service.py
tests/test_provider_error_recovery.py
```

No file under `web/`, `config/`, provider discovery, or operator configuration is in this stage.

## 14. Implementation Sequence Constraints

The later implementation plan must preserve this order:

1. Add contract tests proving canonical stream/non-stream parity and explicit replay handoff.
2. Add the canonical non-stream client entrypoint and convert compatibility methods into wrappers.
3. Cut `core/llm/invocation.py` and the normal Agent path over to canonical outcomes.
4. Introduce the XML compatibility decoder and route its output through the same tool loop.
5. Remove the direct XML execute-and-history branch.
6. Make journal/session writes consume canonical events and outcomes only.
7. Add structural tests proving the production Agent path no longer reads canonical state from compatibility messages.
8. Run Chat and Responses lifecycle matrices before any compatibility cleanup.

No step may remove a compatibility wrapper before all known non-Agent callers are enumerated in the implementation plan.

## 15. Validation Strategy

### 15.1 Contract tests

1. Chat non-stream and stream produce equivalent canonical outcomes.
2. Responses non-stream and stream produce equivalent canonical outcomes.
3. Commentary, tool call, tool result, final answer, and terminal events retain stable identity and order.
4. Active replay state is passed explicitly and cross-route replay still fails before provider I/O.
5. Production Agent invocation does not scan `AIMessage.additional_kwargs` for canonical state.

### 15.2 Agent tool-loop tests

1. Native tool call executes once and continues with the matching result.
2. XML tool call follows the same event, executor, journal, and continuation path.
3. Raw XML control syntax is absent from assistant history.
4. Commentary before a tool call is not promoted to final history.
5. Multiple tool iterations increment `iteration` without changing the same-route `invocationId`.
6. Distinct fallback creates a new invocation lineage and does not reuse incompatible replay state.

### 15.3 Persistence and projection tests

1. Journal replay is idempotent for repeated events and revisions.
2. One canonical final answer is visible after SSE reconnect and session reload.
3. SessionTurnItem v2 is returned without reconstructing it from legacy transcript/delta data.
4. Legacy-only historical sessions remain readable.

### 15.4 Safety and diagnostics tests

1. Logs contain lifecycle identity and outcome kind.
2. Logs exclude credentials, prompts, response bookmarks, replay blobs, and raw XML arguments.
3. Cancelled and incomplete streams cannot produce a later completed state.
4. Unsupported protocols and malformed XML fail with typed, bounded errors.

### 15.5 Runtime acceptance

After merge and only when Launcher active-work guards permit refresh:

1. Run one Chat model turn with commentary, a read-only tool, and final answer.
2. Run one Responses model turn with the same visible sequence.
3. Inspect runtime-scene ordering by safe identity fields.
4. Reload the session and confirm one final answer with stable tool history.
5. Record provider/config failures separately from lifecycle failures.

## 16. Rollout And Rollback

The implementation must remain reversible by ownership boundary:

1. Canonical client APIs are additive before Agent cutover.
2. Compatibility wrappers remain until all consumers are enumerated and verified.
3. XML decoder cutover is isolated from native wire adapters.
4. Journal changes retain legacy read compatibility.
5. Frontend behavior is not changed in this stage.
6. Rollback restores the previous Agent caller while leaving additive canonical APIs harmless.

Rollback must not modify operator configuration, credentials, provider registry, session data, or unrelated frontend work.

## 17. Risk Decisions

| Risk | Decision |
|---|---|
| Canonical API and compatibility wrapper both become writable truths | Compatibility projection is strictly one-way and production Agent code cannot read it back |
| XML support creates a second tool loop | XML decoder produces canonical tool calls and uses the existing executor and continuation loop |
| Stream and non-stream semantics diverge | Both are required to produce equivalent `TurnOutcome` contracts |
| Session history changes break old conversations | Canonical v2 wins when present; legacy data remains read-only fallback for old turns |
| Replay state leaks through persistence or logs | This stage keeps it memory-only and projects only bounded safe summaries |
| Large `agent.py` edit collides with unrelated work | Claim exact scopes, extract only XML decoding, and avoid unrelated orchestration refactors |
| Runtime verification is blocked by other Agents | Merge may complete with explicit `Launcher refresh required`; no force takeover without the exact confirmation phrase |

## 18. Success Criteria

This stage is complete only when:

1. The production Agent path consumes canonical events and `TurnOutcome` directly.
2. `invoke()` and `stream()` are compatibility wrappers rather than canonical owners.
3. Active replay continuation is explicit and no production path reconstructs it from `AIMessage`.
4. Native and XML tool calls share one execution, persistence, and continuation path.
5. Raw XML control syntax is not written as assistant history.
6. Journal and session projection commit each canonical item and terminal state once.
7. Chat and Responses pass stream/non-stream lifecycle matrices.
8. Error, cancellation, retry, fallback, and replay isolation tests pass.
9. Runtime-scene diagnostics are sufficient for Agent analysis and contain no secret or opaque content.
10. Launcher refresh decision, version impact, claim release, and project-memory sync are recorded.

## 19. Design Review

| Perspective | Challenge | Evidence and decision | Status |
|---|---|---|---|
| User-visible intent | Could backend cleanup leave the short-answer/tool/final chain unchanged? | Acceptance requires ordered canonical items, one final answer, reload parity, and runtime evidence | PASS |
| Existing architecture | Does this create another event or outcome model? | Existing `LLMProtocolEvent`, `TurnOutcome`, ledger, journal, and SessionTurnItem v2 remain the owners | PASS |
| Implementation | Could an engineer get stuck deciding where compatibility lives? | Canonical client/invocation APIs are production; LangChain messages are one-way wrappers; XML is an isolated decoder | PASS |
| Verification | Could unit tests pass while SSE/session behavior remains wrong? | Contract, Agent, journal, reconnect, reload, and live runtime matrices are all required | PASS |
| Security | Could replay state or XML arguments leak? | Opaque state remains memory-only; logs and DTOs expose safe bounded metadata only | PASS |
| Concurrency | Could this collide with active config or frontend work? | Config, provider discovery, credentials, React, and sidebar files are excluded | PASS |
| Maintainability | Is native protocol expansion being mixed into lifecycle repair? | Anthropic/Gemini remain separate later designs after canonical ownership is stable | PASS |

Design correction applied before publication: native adapter expansion, durable replay storage, credential isolation, and React cleanup were removed from this stage so the implementation has one lifecycle-ownership objective and a bounded rollback surface.

## 20. Workflow Ledger

- Confirmed intent: standard protocol-native requests and responses converge into one canonical, traceable conversation lifecycle.
- Current stage: design review.
- Accepted direction: canonical lifecycle single owner before durable replay, frontend projection cleanup, or native adapter expansion.
- Reuse decision: adapt architecture boundaries from OpenCode, Pi Agent, Hermes, and Codex; do not copy source without license review.
- Task graph: not yet created; it belongs to the implementation-planning stage after user approval.
- Decisions: direct canonical Agent APIs, explicit replay handoff, one-way compatibility wrappers, XML decoder quarantine, canonical journal ownership.
- Assumptions: current Chat/Responses wire adapters, route resolver, `TurnOutcome`, journal, and SessionTurnItem v2 remain the foundation.
- Unresolved implementation risk: all non-Agent consumers of `invoke()` and `stream()` must be enumerated before wrapper cleanup; this is an implementation-plan requirement, not a design ambiguity.
- Stop condition: overlapping claims on the planned implementation files, inability to preserve legacy history reads, or any need to persist opaque replay state in this stage.
- Recommended next stage: user review, then `writing-plans` for a file-level implementation plan.
