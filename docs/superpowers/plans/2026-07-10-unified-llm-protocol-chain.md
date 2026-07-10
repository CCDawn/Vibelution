# Unified LLM Protocol Chain Implementation Plan

Date: 2026-07-10
Status: second high-risk review passed, task graph split; implementation not started
Design: `docs/superpowers/specs/2026-07-10-unified-llm-protocol-chain-design.md`

## Goal

Implement protocol-native Chat Completions and Responses behind one route resolver, semantic request IR, canonical event/outcome model, tool loop, journal bridge, and frontend turn-item projection. Native Anthropic Messages and Gemini require a separate transport/authentication/replay design before implementation.

## Scope

This plan covers the protocol and projection ownership needed to guarantee:

```text
commentary/progress -> tool -> result -> continuation -> final answer
```

It does not replace the Agent, migrate historical journals, or redesign unrelated UI.

## Recommended Path

Use a phased adapter migration. Do not apply a Responses-only patch and do not replace the existing runtime with Hermes.

The first implementation worktree must be created from current local `main` after a fresh guard check. The root checkout remains integration-only.

## Dependency And Merge Order

1. Recheck and land `2026-07-10-assistant-message-consolidation` as a mandatory prerequisite; do not duplicate its ownership in this plan.
2. Confirm its stable identity contract before protocol work begins.
3. Land route/event types before changing runtime behavior.
4. Land Responses adapter and outcome assembly before frontend protocol changes.
5. Land Chat adapter parity before enabling model/provider switching.
6. Land journal and frontend item ownership after backend event identity is stable.
7. Audit fallback and auxiliary paths after the shared contracts are stable.
8. Open a separate design for native Anthropic/Gemini transport, auth, dependencies, replay persistence, and enablement.

Do not partially modify `agent.py` while the adapter/outcome contract is unstable.

## Planned File Impact

### Existing files to modify

```text
core/llm/types.py
core/llm/protocols.py
core/llm/protocol_resolver.py
core/llm/payload_builder.py
core/llm/payload_validator.py
core/llm/message_projector.py
core/llm/streaming.py
core/llm/client.py
core/llm/invocation_context.py
core/orchestration/response_processor.py
core/orchestration/turn_outcome.py
core/orchestration/round_state.py
core/orchestration/tool_lifecycle.py
core/chat/model_messages.py
core/chat/turn_journal.py
core/web/services/session_service.py
agent.py
config/models.py
web/src/api/types/chat.ts
web/src/routes/chatSessionStreamProtocol.ts
web/src/routes/chatTurnProtocol.ts
web/src/routes/chatActiveTurnLayer.ts
web/src/routes/sessionAssistantDeltaScheduler.ts
web/src/routes/chatStreamApplyController.ts
web/src/components/conversation/useAgentMessageTimelineProjection.ts
web/src/components/conversation/codexNativeTranscriptSurface.ts
web/src/components/conversation/codexTranscriptCells.ts
```

### New package/files

```text
core/llm/semantic_messages.py
core/llm/provider_replay_state.py
core/llm/wire/__init__.py
core/llm/wire/types.py
core/llm/wire/base.py
core/llm/wire/registry.py
core/llm/wire/chat_completions.py
core/llm/wire/responses.py
core/llm/turn_assembler.py
```

The task-splitting stage may reduce each implementation slice to a subset. No single change should modify all files at once.

## Phase A: Freeze Contracts And Characterize Existing Behavior

Purpose: add failing/characterization tests before moving ownership.

Test files:

```text
tests/test_llm_protocol_resolver.py
tests/test_llm_client.py
tests/test_llm_payload_builder.py
tests/test_llm_payload_validator.py
tests/test_agent_protocol.py
tests/test_session_turn_journal.py
tests/test_session_codex_transcript_projection.py
web/src/routes/chatSessionStreamProtocol.test.ts
web/src/routes/chatTurnProtocol.test.ts
web/src/routes/chatStreamApplyController.test.ts
web/src/components/conversation/useAgentMessageTimelineProjection.test.ts
```

Required new fixtures:

- Responses commentary text followed by a function call and final answer.
- Responses terminal object with `output=null` but completed output items.
- Responses `incomplete` terminal event.
- Responses non-stream final, tool, and incomplete responses.
- Chat text followed by `finish_reason=tool_calls`.
- Chat non-stream final and tool responses.
- duplicate stream replay with stable item identity.
- OpenCode model switch from Anthropic route to Chat route and back.
- route failure followed by a fresh fallback route and invocation.
- cancellation during interim Chat text and partial tool arguments.

Gate: tests demonstrate the current premature-completion or information-loss behavior without changing production logic.

## Phase B: Wire Protocol And Route Resolution

Changes:

- add `WireProtocol`;
- separate wire protocol from `ModelProtocol`;
- translate old wire-shaped `ModelProtocol` values only at the migration boundary;
- extend `ResolvedProtocolRoute` with effective model, adapter ID, configured/runtime endpoints, capabilities, and source scope;
- add provider-model route-rule interface;
- add OpenCode Zen/Go rule adapted from Hermes;
- make base URL normalization symmetric and route-owned;
- enforce model explicit -> provider/model rule -> provider API -> profile default -> URL heuristic -> declared Chat fallback -> error priority;
- derive `runtime_endpoint` per invocation and never persist it over operator configuration;
- reject unknown native routes instead of silently assuming Chat.

Primary files:

```text
core/llm/protocols.py
core/llm/protocol_resolver.py
core/llm/invocation_context.py
config/models.py
tests/test_llm_protocol_resolver.py
```

Gate: explicit route, provider API, OpenCode effective-model rule, URL heuristic, Chat fallback, and unsupported-route tests pass.

## Phase C: Canonical Event IR And Adapter Registry

Changes:

- add `SemanticModelRequest`, semantic message parts, `ProviderReplayState`, `LLMProtocolEvent`, `CanonicalToolCall`, `CanonicalToolResult`, and `TurnOutcome` types;
- add composite session/turn/invocation/iteration/item/revision identity;
- add `WireAdapter` protocol and registry;
- move only dispatch ownership first;
- keep existing payload output unchanged for common Chat routes.

Primary files:

```text
core/llm/wire/types.py
core/llm/wire/base.py
core/llm/wire/registry.py
core/llm/semantic_messages.py
core/llm/provider_replay_state.py
core/llm/turn_assembler.py
core/llm/client.py
tests/test_llm_semantic_messages.py
tests/test_llm_provider_replay_state.py
tests/test_llm_client.py
```

Gate: current Chat payload and tool-call behavior remains byte/shape equivalent in focused tests, while the client selects an adapter by immutable route.

## Phase D: Responses Adapter

Changes:

- move Responses encoding/decoding out of generic projector/normalizer;
- preserve item ID, call ID, phase, status, and provider event type;
- reconstruct from `response.output_item.done`;
- classify commentary/analysis separately from answer text;
- emit explicit incomplete and terminal outcomes;
- use deterministic fallback call IDs only when provider IDs are absent;
- encode tool results as `function_call_output`.
- decode non-stream Responses through the same canonical item/outcome contract.

Primary files:

```text
core/llm/wire/responses.py
core/llm/payload_builder.py
core/llm/payload_validator.py
core/llm/streaming.py
core/llm/client.py
tests/test_llm_wire_responses.py
tests/test_llm_client.py
tests/test_llm_payload_builder.py
tests/test_llm_payload_validator.py
```

Gate: commentary -> tool -> result -> final fixture passes and no commentary text is returned as a final answer.

## Phase E: Chat Completions Adapter Parity

Changes:

- move generic LiteLLM/OpenAI delta accumulation into the Chat adapter;
- preserve finish reason and choice index;
- emit provisional `interim_text_delta` while the terminal reason is unknown;
- reclassify interim text as commentary for `tool_calls`, or promote it once to answer for a successful no-tool terminal reason;
- keep cancelled/failed interim text non-final;
- decode non-stream Chat responses through the same canonical contract;
- emit the same canonical tool and terminal events as Responses;
- restrict `message_to_openai_dict` to this adapter.

Primary files:

```text
core/llm/wire/chat_completions.py
core/llm/message_projector.py
core/llm/streaming.py
core/llm/client.py
tests/test_llm_wire_chat_completions.py
tests/test_llm_turn_assembler.py
tests/test_llm_client.py
```

Gate: final-only, tool-only, pre-tool text, parallel tool, malformed argument, and usage fixtures produce correct `TurnOutcome` values.

## Phase F: Agent Tool Loop And Completion Ownership

Changes:

- make `agent.py` consume `TurnOutcome`;
- execute tools only for `outcome.kind=tool_calls`;
- make `ToolLifecycleBridge` emit the sole `CanonicalToolResult` and continue the model only with adapter-encoded results;
- prohibit a second independently appended `ToolMessage` for the same call;
- complete only for terminal `final_answer`;
- preserve `AIMessage` as a derived compatibility message;
- update round state and stop diagnostics to record outcome kind and terminal evidence.

Primary files:

```text
agent.py
core/orchestration/response_processor.py
core/orchestration/turn_outcome.py
core/orchestration/round_state.py
core/orchestration/tool_lifecycle.py
core/chat/model_messages.py
tests/test_agent_protocol.py
tests/test_model_messages.py
tests/test_tool_pairing_validator.py
```

Gate: visible text without terminal final evidence cannot close a tool iteration; tool results return through the selected adapter and the next iteration preserves call identity.

## Phase G: Journal, Session DTO, And React Projection

Changes:

- bridge canonical event channels into live state and journal payloads;
- write new `assistant_item_committed` events and keep `assistant_delta_committed` read-only for legacy replay;
- persist invocation, iteration, item/revision, channel, phase, status, protocol, provisional/terminal state, and call ID;
- publish the explicit `SessionTurnItem` v2 schema;
- make `turnItems` authoritative;
- derive `codexTranscript` from turn items without reverse ownership;
- route reasoning/commentary/tool/answer items to separate React surfaces;
- consolidate provisional/final answer by stable identity;
- replace text-based dedupe with identity-based consolidation where the backend now provides identity.

Primary files:

```text
core/chat/turn_journal.py
core/web/services/session_service.py
web/src/api/types/chat.ts
web/src/routes/chatSessionStreamProtocol.ts
web/src/routes/chatTurnProtocol.ts
web/src/routes/chatActiveTurnLayer.ts
web/src/routes/sessionAssistantDeltaScheduler.ts
web/src/routes/chatStreamApplyController.ts
web/src/components/conversation/useAgentMessageTimelineProjection.ts
web/src/components/conversation/codexNativeTranscriptSurface.ts
web/src/components/conversation/codexTranscriptCells.ts
```

Gate: the AMD395 duplicate fixture renders one final answer, draft-only recovery remains visible, and commentary/tool rows remain independently visible.

## Phase H: Native Anthropic And Gemini Design Gate

Do not implement or enable native Anthropic/Gemini adapters in this delivery. Produce and approve a separate design covering SDK or HTTP transport, authentication headers, dependency policy, base URL ownership, opaque reasoning/signature replay persistence, content-block pairing, non-stream/stream parity, and operator enablement. Only then may new adapter files and provider fixtures be planned.

## Phase I: Auxiliary-Path Audit And Runtime Evidence

Audit these known call surfaces:

```text
agent.py primary/compression/mental-model slots
core/research/agent_runner.py
core/web/services/self_evolution_control_service.py
core/web/services/git_status_service.py
core/web/services/config_service.py probes
```

Required proof:

- each path resolves an immutable route;
- no path calls a provider client directly;
- model switches pass the effective target model;
- failures expose wire protocol, model protocol, adapter ID, and outcome kind;
- bounded runtime-scene logs show the complete chain without raw prompt/tool data.
- fallback creates a fresh route, adapter, invocation identity, and runtime endpoint instead of mutating the failed route.

## Validation Strategy

Backend focused suites:

```powershell
python -m pytest tests/test_llm_protocol_resolver.py tests/test_llm_payload_builder.py tests/test_llm_payload_validator.py tests/test_llm_client.py -q
python -m pytest tests/test_llm_semantic_messages.py tests/test_llm_provider_replay_state.py tests/test_llm_wire_responses.py tests/test_llm_wire_chat_completions.py tests/test_llm_turn_assembler.py -q
python -m pytest tests/test_agent_protocol.py tests/test_model_messages.py tests/test_tool_pairing_validator.py -q
python -m pytest tests/test_session_turn_journal.py tests/test_session_codex_transcript_projection.py tests/test_session_service.py -q
```

Frontend focused suites:

```powershell
npm --prefix web run test -- chatSessionStreamProtocol.test.ts chatTurnProtocol.test.ts sessionAssistantDeltaScheduler.test.ts chatStreamApplyController.test.ts
npm --prefix web run test -- useAgentMessageTimelineProjection.test.ts ConversationView.nativeTranscript.test.tsx codexNativeTranscriptSurface.test.ts codexTranscriptCells.test.ts
npm --prefix web run build
```

Runtime smoke matrix after Launcher refresh:

```text
Responses final-only
Responses commentary/tool/final
Chat final-only
Chat tool/final
Responses and Chat non-stream parity
OpenCode model switch across wire protocols
fallback route rebuild after a route/provider failure
cancel during interim text and partial tool arguments
interrupted stream recovery
SSE reconnect without duplicate final answer
one auxiliary/compression call on a non-Chat route
```

No validation command has been run during this planning stage.

## Protection Boundaries

- Do not change tool business logic or approval rules.
- Do not migrate historical journal files.
- Do not log raw prompts, secrets, complete tool arguments, or full model output.
- Do not force-edit chat or shared DTO hot files when an active claim overlaps.
- Do not implement or enable Anthropic/Gemini routes before the separate subdesign is approved.
- Do not remove public compatibility fields without an explicit version/API decision.
- Do not merge partial backend/frontend identity changes that leave two canonical owners.

## Rollback Boundary

Each phase must be independently reversible:

- route/event type phase has no provider behavior change;
- Responses and Chat adapter phases are selected by route and can be disabled independently;
- Agent outcome migration keeps compatibility projection until the new state machine passes;
- frontend continues to consume existing `codexTranscript` while `turnItems` ownership is established;
- native Anthropic/Gemini routes remain disabled until validated.

Rollback may revert only the named phase. It must not restore text-based identity as canonical behavior.

## Risk Decisions

| Risk | Decision |
| --- | --- |
| Breaking working Chat routes | preserve payload shape before moving semantics |
| New adapter layer duplicates existing adapters | wire adapters own protocol; provider adapters own connection quirks |
| Commentary still leaks into answer | canonical channel is assigned before Agent/UI projection |
| Stale model mode after switch | recompute route from effective target model every invocation |
| Auxiliary calls diverge | prohibit direct clients and audit known call surfaces |
| Frontend duplicates | stable item identity is canonical; text matching is forbidden |
| Huge single merge | mandatory task splitting and per-phase claims/validation |
| External-code license drift | copy only focused MIT helpers with attribution and local tests |
| Opaque replay data crosses providers or leaks | endpoint-fingerprinted `ProviderReplayState`, bounded storage, no DTO/log projection |
| Delta logging becomes unbounded | aggregate only at item and terminal decisions |

## Planning Review

| Perspective | Result | Challenge and evidence |
| --- | --- | --- |
| User intent | PASS | all target protocols retain their standard tool and terminal semantics |
| Pre-plan review | PASS | plan reuses current resolver, builder, journal, SSE router, and turn-item work |
| Implementer | PASS | phases name concrete owned files, interfaces, gates, and merge order |
| Test/verification | PASS | provider fixtures, journal/SSE projection, React visibility, and runtime smoke are all required |
| Maintainer | PASS | rejects whole-Hermes copy and prevents new branches in `agent.py` |
| Risk | PASS with split required | shared DTO, LLM routing, journal, and Agent loop must not be one unreviewed change |

## Workflow Ledger

- Current stage: PLAN_REVISION
- Confirmed intent: each provider protocol follows its native standard chain and converges through one canonical event/outcome model.
- Revised plan: first delivery is Chat Completions + Responses with semantic request IR, replay-state boundary, canonical events, `TurnOutcome`, journal bridge, and item-based frontend projection.
- Reuse decision: ADAPT Hermes route rules and protocol helpers; REFERENCE_ONLY for its Agent loop.
- Validation evidence: source inspection and historical runtime evidence only; no commands executed for validation.
- Unresolved risk: implementation claim ownership and exact phase split must be rechecked after the second high-risk review.
- Recommended next stage: second high-risk plan review; only a PASS may route to `ccdawn-task-splitting`.
- Stop condition: active claim overlap, route/interface ambiguity discovered by failing characterization tests, or required provider dependency decision not yet approved.

## Next Action

Execute Task 1 from `docs/superpowers/plans/2026-07-10-unified-llm-protocol-chain-tasks.md` through `ccdawn-bdd-tdd-development`. Create a dedicated worktree and claim before touching the frontend projection files.
