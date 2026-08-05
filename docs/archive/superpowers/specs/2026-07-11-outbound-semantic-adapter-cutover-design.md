# Outbound Semantic Adapter Cutover Design

Date: 2026-07-11
Status: approved for implementation planning
Parent design: `2026-07-10-unified-llm-protocol-chain-design.md`
Decision: switch Responses first, then Chat Completions; keep one outbound payload owner per invocation

## Goal

Complete the missing outbound half of the unified LLM protocol chain:

```text
ConversationLedger ModelProjection
  -> provider-neutral SemanticModelRequest
  -> immutable route
  -> required WireAdapter
  -> protocol-native request body
  -> runtime envelope and bounded validation
  -> provider backend
  -> canonical decoder
  -> TurnOutcome
```

After the cutover, production `LLMClient` must use the same Chat Completions and Responses encoders already covered by wire-adapter tests. Unsupported native protocols must fail before provider I/O instead of falling back to a legacy normalizer.

## Current Gap

The canonical decoders, `TurnOutcome`, journal, SessionTurnItem v2, and React projection are live. The outbound path is not yet canonical:

- `LLMClient._build_payload()` still calls `normalize_messages_for_provider()` and `build_llm_payload()` with OpenAI-shaped compatibility messages.
- `WireAdapterRegistry.encode_request()` has no production caller.
- `ProviderReplayState` route compatibility is therefore enforced only in adapter tests, not all real sends.
- Missing native adapters are caught during decode and can enter a legacy normalizer path.

## Scope

This design covers:

- one provider-neutral projector from ledger/model messages into `SemanticModelRequest`;
- typed preflight resolution of the required wire adapter;
- Responses outbound cutover;
- Chat Completions outbound cutover after Responses stabilizes;
- preservation of provider/runtime envelope behavior;
- removal of decode-time adapter fallback for production invocations;
- focused parity, replay, continuation, cancellation, and error tests.

This design does not cover:

- XML text tool-call fallback in `agent.py`;
- Agent tool execution or approval policy changes;
- fallback-profile orchestration and auxiliary-call inventory from Task 9;
- Anthropic Messages or Gemini request/response adapters;
- journal, SessionTurnItem v2, React, model configuration, or historical migration;
- copying Hermes or OpenCode implementation code.

## Reuse Decision

Decision: `ADAPT`.

- Adapt Hermes' invariant that effective provider/model resolution selects one API mode before the shared Agent loop.
- Adapt OpenCode's parts-to-model projection boundary: durable message parts remain protocol-neutral until the selected model/provider transformation.
- Keep Vibelution's immutable `ResolvedProtocolRoute`, semantic types, payload security policy, prompt-cache behavior, canonical event algebra, and `TurnOutcome` ownership.
- Do not adopt Hermes' OpenAI-style message dictionaries as Vibelution's universal durable truth.

## Architecture

### 1. Semantic projector

Add `core/llm/semantic_projector.py` as the only compatibility bridge from existing model messages to semantic request parts.

It owns:

- `SystemMessage`, user, assistant, and tool role mapping;
- text and supported image parts;
- canonical tool call and tool result identity;
- ordered parallel tool results;
- controlled `InvocationScope` attachment;
- replay references represented as `ReasoningReplayPart`, never raw provider dictionaries;
- conversion of selected tools into `SemanticToolDefinition` after existing capability and schema policy checks.

It must reject:

- UI-only `toolCalls` input;
- orphan tool results;
- duplicate or empty call IDs;
- opaque replay data without compatible `ProviderReplayState`;
- unsupported message/content shapes rather than silently stringifying them.

The projector must not know Chat/Responses wire field names.

### 2. Required adapter preflight

Add one `LLMClient` helper that resolves and stores the adapter required by the immutable route before payload construction or provider I/O.

Failure contract:

```text
route selects known wire protocol
  + registry has no matching adapter
  -> LLMError(category="unsupported_wire_protocol", retryable=False)
```

The bounded error details may include profile ID, provider kind, model ID, wire protocol, adapter ID, and route source. They must not include credentials, prompts, messages, raw payloads, or replay blobs.

Decode paths must not catch this error and must not construct a legacy stream normalizer.

### 3. Protocol body versus runtime envelope

`WireAdapter.encode_request()` continues to own the protocol-native body:

- Chat: `messages`, Chat tool schemas, Chat tool results, `max_tokens`, stream shape;
- Responses: `input` items, Responses tools, `function_call_output`, `max_output_tokens`, stream shape.

`payload_builder` remains the runtime policy/envelope owner for:

- API key and configured/runtime endpoint handling;
- provider-specific model name required by the transport client;
- timeout and proxy-compatible fields;
- capability gates;
- prompt-cache policy and keys;
- thinking/sampling policy allowed by the selected route;
- extra headers and safe extra body;
- stream usage options;
- final bounded payload validation and summary logging.

The envelope may replace adapter body fields only where the field is explicitly runtime-owned, such as the transport client's provider-prefixed model name. It must not re-project `messages`, `input`, tools, or tool results.

### 4. One owner per invocation

The migration is serial by wire protocol:

```text
Stage A: common projector, required-adapter preflight, and parity tests
Stage B: Responses -> semantic adapter; Chat -> legacy builder
Stage C: Responses -> semantic adapter; Chat -> semantic adapter
Stage D: remove unreachable legacy protocol projection and decode fallback
```

There is no dual provider send and no runtime shadow payload containing raw content. During Stages B and C, route selection determines exactly one owner.

Tests may build both old and new payloads from synthetic fixtures and compare sanitized structural summaries. Production runtime must never build both payloads for one invocation.

## Responses Cutover

Responses switches first because its completed-item reconstruction and terminal semantics are already canonical.

Required behavior:

- stream and non-stream use the same semantic projector and Responses encoder;
- commentary, reasoning, function calls, tool results, and final answer remain distinct;
- `call_id` survives tool continuation;
- compatible replay items are sent only through `ProviderReplayState`;
- cross-provider, cross-endpoint, cross-model, or cross-protocol replay fails before provider I/O;
- terminal `output=null` remains recoverable from completed events on decode;
- cancelled, incomplete, and failed responses never become successful final answers.

## Chat Completions Cutover

Chat switches only after Responses tests and client integration pass.

Required behavior:

- Chat message and tool-result shapes are produced only by `ChatCompletionsWireAdapter`;
- provider model naming, prompt cache, thinking parameters, and compatibility policy remain envelope-owned;
- ordered and parallel tool calls retain provider call IDs;
- interim text followed by `finish_reason=tool_calls` remains commentary;
- successful no-tool terminal text is promoted once to final answer;
- cancellation/failure does not promote provisional text;
- reasoning replay is accepted only through compatible replay state.

## File Impact

Expected owned surface:

- Add `core/llm/semantic_projector.py`.
- Modify `core/llm/semantic_messages.py` only if a missing provider-neutral field is proven necessary.
- Modify `core/llm/wire/registry.py` for explicit capability/preflight helpers.
- Modify `core/llm/payload_builder.py` to compose adapter body with the runtime envelope without re-projecting protocol content.
- Modify `core/llm/client.py` to build semantic requests, require adapters, and remove decode fallback.
- Modify `core/llm/wire/responses.py` and `core/llm/wire/chat_completions.py` only for proven parity gaps.
- Add `tests/test_llm_semantic_projector.py` and `tests/test_llm_client_outbound_wire_bridge.py`.
- Extend existing resolver, wire adapter, payload builder, validator, and client outcome tests as required by behavior.

Protected surface:

- `agent.py` and XML tool fallback;
- `core/orchestration/**`;
- `core/chat/**` and `core/web/services/session_service.py`;
- `web/**`;
- `config/**` currently owned by another claim;
- tool implementation, approval, and lifecycle business logic;
- operator configuration and secrets.

## Error Handling

- Unsupported adapter: typed, non-retryable preflight error before provider I/O.
- Semantic projection failure: typed payload protocol error with message index and safe shape category only.
- Replay mismatch: non-retryable error from registry/adapter compatibility guard.
- Envelope validation failure: preserve existing typed `LLMError` category and bounded policy summary.
- Provider failure after send: preserve current retry classification; do not rebuild the route inside the same invocation.
- Model/profile fallback: outside this design; Task 9 must create a fresh client, route, adapter, scope, and endpoint.

## Testing Strategy

### Contract tests

- every supported model message part maps to one semantic part;
- tool call/result IDs and order survive projection;
- malformed or UI-only input fails before adapter dispatch;
- replay compatibility is checked at the registry boundary.

### Production integration tests

- spy on the registry to prove `LLMClient._build_payload()` calls the selected adapter encoder;
- prove provider I/O is not called when the adapter is unavailable;
- prove decode paths cannot select a legacy normalizer after successful preflight;
- compare sanitized body shape against existing Responses and Chat adapter fixtures;
- prove each invocation constructs one payload owner only.

### Protocol matrices

- Responses and Chat, stream and non-stream;
- no-tool final answer;
- commentary/text then tool call;
- one and parallel tool calls;
- tool result continuation;
- malformed tool arguments;
- cancel/incomplete/failure;
- retry with one stable invocation scope;
- replay match and mismatch.

### Regression gates

- focused semantic, wire, payload builder, payload validator, client, and outcome suites;
- existing Agent protocol tests that exercise real `LLMClient` responses;
- canonical journal tests to prove downstream outcome compatibility;
- bounded runtime-scene assertion for adapter selection and terminal outcome without raw payload data.

## Rollback

Each protocol cutover is a separate commit. If Responses fails, revert only the Responses ownership commit while retaining semantic projector and hard-fail tests if they remain valid. Chat does not begin until Responses is green.

No configuration migration, journal migration, or data rewrite is involved. Rollback must not restore decode-time silent fallback for known unsupported native protocols.

## Success Criteria

- Production Responses and Chat requests pass through `SemanticModelRequest` and the selected registry adapter.
- Exactly one outbound payload owner exists per invocation.
- Existing runtime envelope behavior is preserved and tested.
- Unsupported Anthropic/Gemini routes fail before provider I/O.
- No raw prompt, payload, replay blob, or tool arguments are added to logs.
- Stream/non-stream and tool continuation parity tests pass for both protocols.
- Existing canonical decoder, `TurnOutcome`, journal, SessionTurnItem v2, and React behavior remain unchanged.

## Design Review

- User intent: PASS. The design completes protocol-standard outbound ownership rather than adding another compatibility facade.
- Architecture: PASS after correction. Wire adapters own protocol bodies; `payload_builder` retains runtime envelope and security policy.
- Implementation risk: PASS with serial cutover. Responses and Chat do not change ownership in one commit.
- Verification: PASS. Tests prove the production caller uses the adapter, not merely that adapter unit fixtures pass.
- Maintenance: PASS. One semantic projector and one registry boundary replace protocol guessing in callers.
- Scope: PASS. XML fallback, Task 9, native Anthropic/Gemini, config, journal, and React are explicitly excluded.

## Workflow Ledger

- Current Stage: DESIGN_APPROVED
- Confirmed Intent: make each wire protocol follow its own standard request chain while sharing provider-neutral orchestration state
- Accepted Design: semantic projector plus required adapter preflight; cut over Responses first and Chat second; retain payload builder as runtime envelope owner
- Reuse Decision: ADAPT Hermes route invariants and OpenCode parts-to-model boundary
- Task Graph: pending implementation-plan decomposition
- Unresolved Risks: provider-prefixed Chat model naming and prompt-cache/thinking parity must be locked by fixtures before Chat cutover
- Recommended Next Stage: `writing-plans`, then `ccdawn-task-splitting`
- Stop Condition: claim overlap on `core/llm/client.py` or `payload_builder.py`, inability to preserve envelope parity, or any requirement to enable Anthropic/Gemini in this slice
