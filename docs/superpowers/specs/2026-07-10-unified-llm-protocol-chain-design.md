# Unified LLM Protocol Chain Design

Date: 2026-07-10
Status: revised after high-risk review, implementation not started
Owner: LLM protocol runtime / chat runtime
Risk tier: HIGH_RISK

## Confirmed Intent

Vibelution must stop treating every provider response as if it were an OpenAI Chat Completion. Each upstream protocol must keep its native request, stream, tool-call, reasoning, and terminal semantics until those facts have been converted into one canonical internal event model.

The required observable behavior is:

```text
short progress/commentary
  -> tool call
  -> tool execution and result
  -> model continuation
  -> one final answer
```

For a direct answer without tools, the chain may complete after one final answer. Commentary, analysis, reasoning, or pre-tool text must never complete the turn by itself.

The same route resolver and adapter factory must be used by main chat, compression, mental-model calls, research Agents, self-evolution, Git message generation, probes, fallback calls, and future auxiliary model tasks.

## Evidence And Current State

The repository already has important foundations:

- `core/llm/protocols.py` defines model compatibility policies.
- `core/llm/protocol_resolver.py` resolves a `ResolvedProtocolRoute`.
- `core/llm/payload_builder.py` and `payload_validator.py` separate payload construction and validation.
- `core/chat/turn_journal.py` already provides `eventId`, `sequence`, `turnId`, `toolCallId`, and terminal-event protection.
- `session_service.py` publishes stable `itemId` and `turnItems` with assistant deltas.
- React already has an SSE router, assistant-delta scheduler, apply controller, turn render protocol, and native transcript projection.
- All identified model invocation surfaces use `LLMClient` or `get_llm_client`; no independent direct provider client was found outside `core/llm/client.py`.

The remaining structural gaps are:

1. `core/llm/message_projector.py` explicitly projects all model messages into OpenAI-style dictionaries.
2. `ResponsesStreamNormalizer` emits only `reasoning_delta`, `text_delta`, `tool_call_final`, and `done`.
3. Responses `message.phase`, item status, item identity, terminal status, and incomplete state are discarded.
4. `agent.py` merges stream chunks into `AIMessageChunk`, then decides completion from visible text plus the flattened `tool_calls` list.
5. Any Responses output text is currently treated as answer text, including text that should be commentary or analysis.
6. `session_service.py` still contains text-based assistant projection suppression, while stable item identity is available elsewhere.
7. `ModelProtocol` currently mixes wire protocol and model compatibility policy.
8. There is no OpenCode Zen/Go provider-model route rule. The same provider can therefore not safely select different wire protocols per effective model.

The captured AMD395 run contains one provider response and one final model message. The duplicate visible answer was produced downstream by provisional and final projections, not by two provider completions. This confirms that protocol facts and projection ownership must be fixed separately.

## External Reuse Decision

Overall decision: `ADAPT`.

Hermes Agent is useful for four focused patterns:

- provider plus effective-model resolution into `api_mode`;
- Responses reconstruction from `response.output_item.done` rather than terminal `response.output`;
- phase-aware routing of `commentary` and `analysis` away from final answer text;
- Anthropic `tool_use` and immediately-following `tool_result` pairing.

The following are not adopted:

- the whole Hermes `AIAgent` loop;
- its OpenAI-style message format as the universal internal truth;
- duplicated main and auxiliary provider-resolution paths;
- provider/model branches copied wholesale from its large runtime resolver.

Hermes Agent is MIT licensed. Any substantial copied helper must retain the upstream copyright and license notice and identify its source file and commit.

## Core Architectural Decision

Separate three concepts that are currently partially conflated:

```text
WireProtocol
  What upstream API and event contract is used?

ModelProtocol
  What model-family compatibility policy applies?

TurnOutcome
  What did this model iteration actually produce?
```

### WireProtocol

Initial enum:

```text
chat_completions
responses
anthropic_messages
gemini_generate_content
```

`WireProtocol` controls endpoint shape, request encoding, stream decoding, tool result encoding, and terminal semantics.

### ModelProtocol

Existing values such as `qwen_thinking_no_prefill`, `deepseek_reasoning`, and `llamacpp_qwen_thinking` remain compatibility policies. They must not be used as substitutes for the wire protocol.

Examples:

```text
WireProtocol=chat_completions + ModelProtocol=deepseek_reasoning
WireProtocol=responses + ModelProtocol=openai_responses
WireProtocol=anthropic_messages + ModelProtocol=anthropic_thinking
```

Existing wire-shaped `ModelProtocol` members remain temporary read-only migration aliases. At route construction they are translated once into `WireProtocol` plus a compatibility `ModelProtocol`; no new code may branch on those aliases, and they are removed only after persisted configuration migration is complete.

### ResolvedProtocolRoute

The route becomes immutable and invocation-specific:

```python
@dataclass(frozen=True)
class ResolvedProtocolRoute:
    provider_id: str
    provider_kind: str
    model_id: str
    effective_model: str
    wire_protocol: WireProtocol
    model_protocol: ModelProtocol
    configured_endpoint: str
    runtime_endpoint: str
    adapter_id: str
    policy: ProtocolPolicy
    compat: CompatPolicy
    capabilities: LLMCapabilities
    source: str
    source_scope: str        # model | provider_model | provider | profile | heuristic | fallback
    warnings: tuple[str, ...]
```

The effective model must be supplied for every call and every model switch. A persisted mode from a previous model must never override the target model.

## Route Resolution

Resolution order:

```text
1. explicit wire protocol on the effective model
2. provider plus effective-model route rule for mixed-protocol providers
3. explicit provider API contract
4. profile default transport
5. endpoint URL heuristic
6. explicit OpenAI-compatible Chat fallback
7. configuration error for unknown native routes
```

A generic unknown endpoint must not silently become Chat Completions. Conservative Chat fallback is allowed only when the provider or profile explicitly declares OpenAI compatibility.

Every resolution records `source_scope`. A profile default is never reported or treated as a model-explicit decision. Fallback and retry create a fresh immutable route from the current effective model; they do not mutate or reuse a previous invocation route.

### OpenCode Route Rule

Adapt the Hermes model rule as a provider plugin/rule, not scattered conditionals:

| Provider/model family | Wire protocol |
| --- | --- |
| OpenCode Zen GPT/Codex | `responses` |
| OpenCode Zen Claude | `anthropic_messages` |
| OpenCode Zen Qwen | `anthropic_messages` |
| OpenCode Zen other supported models | `chat_completions` |
| OpenCode Go MiniMax/Qwen | `anthropic_messages` |
| OpenCode Go GLM/Kimi/DeepSeek/MiMo | `chat_completions` |

Base URL normalization is symmetric:

- remove `/v1` for `anthropic_messages` when the SDK appends `/v1/messages`;
- restore `/v1` for `chat_completions` and `responses` on official OpenCode hosts;
- do not rewrite custom proxy URLs unless their provider rule explicitly owns that rewrite.

`configured_endpoint` is the operator value and is never rewritten or persisted by runtime routing. `runtime_endpoint` is derived for one invocation and may be normalized only by the selected provider-model rule.

## Semantic Request IR

Wire adapters receive a provider-neutral semantic request, not OpenAI-shaped dictionaries:

```python
@dataclass(frozen=True)
class SemanticModelRequest:
    messages: tuple[SemanticMessage, ...]
    tools: tuple[SemanticToolDefinition, ...]
    replay_state: ProviderReplayState | None
    settings: SemanticGenerationSettings

@dataclass(frozen=True)
class SemanticMessage:
    role: str
    parts: tuple[TextPart | ImagePart | ToolCallPart | ToolResultPart | ReasoningReplayPart, ...]
```

`core/llm/message_projector.py` and `core/chat/model_messages.py` become compatibility inputs to this IR. OpenAI role/content/tool dictionaries are generated only inside the Chat Completions adapter. Provider-native replay items are represented by opaque `ReasoningReplayPart` references and are never flattened into user-visible text.

`CanonicalToolResult` is the sole semantic tool-result owner. `ToolLifecycleBridge` creates it after execution and records lifecycle state; the selected `WireAdapter.encode_tool_results` alone converts it into provider wire messages. No layer may also append an independently encoded `ToolMessage` for the same call.

## Wire Adapter Contract

Create a `core/llm/wire/` package. Provider quirks remain in the existing provider adapter layer, while wire semantics live here.

```python
class WireAdapter(Protocol):
    wire_protocol: WireProtocol

    def encode_request(self, request: SemanticModelRequest) -> BuiltPayload: ...
    def decode_response(self, response: Any) -> TurnOutcome: ...
    def decode_stream(self, events: Iterable[Any]) -> Iterator[LLMProtocolEvent]: ...
    def encode_tool_results(self, results: Sequence[CanonicalToolResult]) -> list[Any]: ...
```

`message_to_openai_dict` becomes an implementation detail of the Chat Completions adapter only. It must not be called by Responses, Anthropic Messages, or Gemini adapters.

## Canonical LLM Event IR

Add one provider-neutral event algebra above wire adapters:

```text
turn_started
reasoning_delta
commentary_delta
interim_text_delta
answer_delta
item_completed
tool_call_started
tool_arguments_delta
tool_call_ready
usage_updated
turn_completed
turn_incomplete
turn_failed
turn_cancelled
```

Canonical event fields:

```python
@dataclass(frozen=True)
class LLMProtocolEvent:
    kind: str
    sequence: int
    session_id: str
    invocation_id: str
    iteration: int
    turn_id: str = ""
    item_id: str = ""
    response_id: str = ""
    item_revision: int = 0
    call_id: str = ""
    channel: str = ""        # reasoning | commentary | answer | tool
    phase: str = ""
    status: str = ""
    text: str = ""
    tool_name: str = ""
    arguments_delta: str = ""
    provisional: bool = False
    terminal: bool = False
    provider_event_type: str = ""
    diagnostic_summary: Mapping[str, Any] = field(default_factory=dict)
```

Raw provider payloads are not stored in this object. Only bounded, secret-safe diagnostic summaries may cross the adapter boundary.

Canonical identity is `session_id + turn_id + invocation_id + iteration + item_id + item_revision`. `sequence` orders events only within one invocation and is not a globally unique identity. Provider item IDs and call IDs are preserved when present; deterministic fallbacks are scoped to the invocation.

## Provider Replay State

Some providers require opaque reasoning, signature, or encrypted continuation data. That data is not an `LLMProtocolEvent` diagnostic and must not be reconstructed from text:

```python
@dataclass(frozen=True)
class ProviderReplayState:
    issuer: str
    provider_id: str
    endpoint_fingerprint: str
    model_id: str
    wire_protocol: WireProtocol
    opaque_items: tuple[OpaqueReplayItem, ...]
    byte_size: int
```

The state is held by the model-history/replay store, referenced by semantic requests, and returned only to the same issuer/provider/endpoint fingerprint/model/wire tuple. Cross-issuer replay is rejected. Raw opaque data is excluded from frontend DTOs and runtime-scene logs, bounded by item and byte limits, cleared on turn/session deletion, and persisted only through an explicitly encrypted provider-replay store. Until that store exists, replay state is invocation/session-memory only.

## Protocol-Specific Semantics

### Responses

Rules:

- reconstruct output from `response.output_item.done` events;
- never require terminal `response.output` to be iterable;
- preserve item `id`, `call_id`, `phase`, and `status`;
- route `phase=commentary|analysis` text to `commentary_delta`;
- route reasoning events to `reasoning_delta`;
- route normal assistant output to `answer_delta`;
- emit `tool_call_ready` only after final arguments are available;
- preserve `response.incomplete` as `turn_incomplete`;
- accept completion only from a terminal Responses event;
- encode tool results as `function_call_output` with the original `call_id`.

### Chat Completions

Rules:

- preserve `finish_reason` and choice index;
- accumulate tool name, ID, and arguments by tool index;
- while tools are enabled, text is buffered as provisional `interim_text_delta` until the terminal choice reason is known;
- when the terminal reason is `tool_calls`, buffered interim text is reclassified as commentary and cannot complete the turn;
- when the terminal reason is a successful no-tool completion, buffered interim text is promoted once to answer text under the same canonical item identity and next `item_revision`;
- emit `tool_call_ready` only after the stream finishes the call;
- complete only when `finish_reason` is terminal and no tool calls remain pending;
- encode tool results with `role=tool` and matching `tool_call_id`.

### Anthropic Messages

Rules:

- preserve ordered content blocks;
- map `thinking` and `redacted_thinking` to reasoning items without flattening signatures;
- map `tool_use` to canonical tool calls;
- group matching `tool_result` blocks in the immediately following user message;
- preserve `stop_reason`;
- detect and reject orphaned tool pairs before send;
- keep provider-issued thinking data scoped to the issuing endpoint/model policy.

### Gemini GenerateContent

Rules:

- preserve `functionCall`, `functionResponse`, and `thoughtSignature`;
- merge parallel function responses into the same user turn;
- enforce user/model alternation;
- map thought parts to reasoning and ordinary text parts to answer events.

## Turn Outcome State Machine

The agent loop must stop reading completion semantics from `AIMessage.content` and `AIMessage.tool_calls` directly.

```text
REQUESTING
  -> STREAMING
  -> WAITING_FOR_TOOLS
  -> EXECUTING_TOOLS
  -> CONTINUING_MODEL
  -> FINAL

Any state may also enter INCOMPLETE, FAILED, or CANCELLED.
```

`TurnOutcome` kinds:

```text
tool_calls
final_answer
incomplete
failed
cancelled
```

Completion invariant:

```text
terminal_event_seen
AND pending_tool_call_ids is empty
AND outcome.kind == final_answer
```

A commentary item, reasoning item, or visible text before a tool call cannot satisfy the invariant.

For Chat Completions, the turn assembler owns provisional-text promotion. Adapters emit interim text and terminal facts; neither the Agent nor React guesses the channel from arrival order. Cancellation or failure keeps the buffered item non-final and never promotes it to an answer.

`AIMessage` remains a compatibility projection for the existing tool executor and model history during migration. It is built from a completed `TurnOutcome`; it is not the source of turn completion.

## Journal And Frontend Projection

The runtime canonical source is the ordered `LLMProtocolEvent` stream. The new canonical journal write is `assistant_item_committed`; legacy `assistant_delta_committed` remains read-only for historical replay and must not be produced by the new bridge.

Mapping rules:

- coalesced live deltas update `SessionLiveOutputState` under composite identity;
- `assistant_item_committed` stores invocation, iteration, item/revision, channel, phase, status, protocol, provisional, and terminal facts;
- `assistant_message` stores only canonical final answer items;
- `tool_call_started` and `tool_result` keep canonical `call_id`;
- terminal journal events are emitted from `TurnOutcome`, not visible text heuristics.

Canonical write order is: live provisional update, item commit/reclassification, tool lifecycle events if any, terminal `TurnOutcome`, then the single final `assistant_message` projection. Commentary and reasoning items are excluded from model-visible answer history; provider replay state returns only through `ReasoningReplayPart`.

`SessionTurnItem` v2 has required fields `sessionId`, `turnId`, `invocationId`, `iteration`, `itemId`, `revision`, `sequence`, `kind`, `channel`, `phase`, `status`, `protocol`, `provisional`, `terminal`, `text`, and optional `callId`, `toolName`, and bounded diagnostics. Unknown v2 item kinds are retained as non-primary process items rather than coerced into assistant answers.

`SessionTurnItem` and stable `itemId` become the frontend source of truth. `codexTranscript` remains a derived renderer projection for compatibility and may not override `turnItems`.

React projection rules:

- reasoning and commentary render in secondary process surfaces;
- tool calls render as tool lifecycle rows;
- only answer items render as primary assistant markdown;
- provisional and final answer projections consolidate by `sessionId + turnId + itemId`;
- text equality is never a message identity;
- reconnect and event replay deduplicate by stable event/item identity and sequence.

## Single Source Of Truth

| Fact | Canonical source | Writer | Readers / derived surfaces | Refresh or invalidation | Old source cleanup |
| --- | --- | --- | --- | --- | --- |
| Effective provider/model/wire route | `ResolvedProtocolRoute` | `resolve_model_protocol` | payload builder, adapter registry, logs | recompute for every invocation/model switch | stop reading stale persisted mode after route creation |
| Request wire shape | selected `WireAdapter` | adapter `encode_request` | provider backend, safe payload trace | rebuilt per call | restrict `message_to_openai_dict` to Chat adapter |
| Stream semantics | ordered `LLMProtocolEvent` | selected wire adapter | turn assembler, live output, journal bridge | monotonic sequence per invocation | retire direct completion decisions from `StreamChunk` text |
| Semantic request/history | `SemanticModelRequest` and semantic parts | model-history projection | selected wire adapter | rebuilt for every invocation | retire provider-neutral OpenAI dicts |
| Provider opaque continuation | `ProviderReplayState` | selected wire adapter plus replay store | same issuer route only | bounded by session/turn lifecycle and endpoint fingerprint | never copy into journal/frontend diagnostics |
| Tool call identity/state | canonical call ID plus `ToolLifecycleBridge` | adapter and tool bridge | journal, model continuation, UI | terminal tool result closes call ID | remove generated fallback IDs when provider ID exists |
| Iteration completion | `TurnOutcome` | turn assembler | `agent.py`, round state, journal terminal event | immutable once terminal | remove visible-text completion heuristic |
| UI turn items | `SessionTurnItem[]` | session projection | SSE router, active layer, transcript renderer | replace by item ID and sequence | keep `codexTranscript` derived and non-authoritative |

## Auxiliary-Path Rule

Every model call must use this pipeline:

```text
get_llm_client / LLMClient
  -> ResolvedProtocolRoute
  -> WireAdapter registry
  -> request encoder
  -> provider backend
  -> canonical event/outcome decoder
```

No auxiliary component may create its own OpenAI, Anthropic, Gemini, or Responses client without going through the same resolver and adapter registry.

## Compatibility And Migration

Migration is phased but the final contract is not dual-protocol guessing.

1. Land the existing assistant-message consolidation identity fix as a mandatory prerequisite.
2. Introduce wire protocol, semantic request, replay-state, and canonical event types without changing common Chat behavior.
3. Move Responses decoding first and make phase/terminal semantics authoritative.
4. Convert Chat Completions, including interim-text promotion, to the same event/outcome interface.
5. Move Agent completion, canonical tool results, and journal projection to `TurnOutcome`.
6. Make frontend `turnItems` v2 authoritative and retain `codexTranscript` only as a derived view.
7. Audit every auxiliary model surface against the shared adapter factory.
8. Design native Anthropic/Gemini transport, authentication, dependency, and replay persistence separately before enabling those adapters.

Temporary compatibility projections must be one-way and read-only. No provider-native item may be reconstructed from frontend DTOs.

If substantial Hermes helpers are copied rather than independently adapted, add the MIT notice and source commit in `THIRD_PARTY_NOTICES.md` or the copied file header before merge.

## Logging Decision

Add bounded runtime-scene events at these decisions:

```text
llm.route.resolved
llm.protocol.item_finalized
llm.tool_call.ready
llm.turn_outcome.finalized
llm.protocol.fallback_or_rejection
```

Do not emit one runtime-scene record per delta. Aggregate per item and terminal decision with bounded counters and sizes. Required safe fields include route source/scope, wire protocol, model protocol, provider event type, invocation/item/call IDs, phase, status, terminal event seen, pending call count, and outcome kind. Do not log prompt text, raw arguments, replay blobs, secrets, full payloads, or unbounded output.

## Verification Matrix

Every enabled adapter must pass:

| Scenario | Required evidence |
| --- | --- |
| final text only | one final answer and one terminal outcome |
| non-stream final/tool response | same canonical items and outcome as equivalent stream |
| reasoning then final | reasoning separate from answer |
| commentary then tool then final | commentary never completes turn; tool executes; final appears once |
| one tool call | call/result IDs pair across continuation |
| parallel tools | each ID pairs; result order follows declared policy |
| empty terminal output with completed items | output reconstructed from item events |
| incomplete response | explicit incomplete state, not success |
| stream reconnect/replay | no duplicate item or final answer |
| cancellation during interim text/tool arguments | cancelled outcome; no provisional answer promotion or partial tool execution |
| model switch across protocols | route and base URL recomputed from target model |
| fallback after route failure | fresh route, adapter, invocation identity, and runtime endpoint |
| auxiliary call | same resolver and adapter registry used |
| provider error | native reason retained in bounded diagnostics |

## Non-Goals

This design does not:

- replace the entire Agent loop with Hermes;
- migrate historical journal files;
- redesign the whole conversation UI;
- change tool business logic or approval policy;
- expose raw model reasoning to users by default;
- add every provider in one unreviewed change;
- implement native Anthropic/Gemini transport in the first Chat/Responses delivery;
- remove LiteLLM before native transport requirements justify it.

## Plan Review

| Perspective | Challenge | Evidence | Conclusion |
| --- | --- | --- | --- |
| User intent | Could a progress sentence still become the final answer? | completion requires terminal event plus `final_answer`; commentary is a separate channel | PASS |
| Existing architecture | Does this create a second resolver/journal/UI protocol? | reuses existing resolver, payload builder, journal, `turnItems`, SSE router, and transcript projection | PASS |
| Implementation | Is the change too large for one unsafe merge? | migration has independent adapter/outcome/journal/frontend gates | PASS with task splitting required |
| Verification | Could unit tests pass while the visible chain remains wrong? | matrix includes journal, SSE, React projection, and live model-switch smoke | PASS |
| Maintenance | Will provider quirks spread through `agent.py` again? | wire adapters own protocol semantics; provider adapters own connection quirks; Agent consumes `TurnOutcome` | PASS |
| Reuse/license | Can Hermes code be copied blindly? | reuse is selective and MIT attribution is required | PASS |
| High-risk revision | Are request semantics, identity, replay state, tool-result ownership, and projection schema explicit? | each now has one owner, lifecycle, and migration boundary | PASS, pending second review |

## Success Criteria

The design is implemented when:

- Chat Completions and Responses use separate standard wire adapters;
- Responses commentary/analysis cannot complete a turn;
- Responses output is recoverable from item events when terminal output is empty;
- tool calls and outputs retain stable IDs across continuations;
- `agent.py` completes iterations from `TurnOutcome`, not visible text;
- journal and frontend preserve item channel, phase, status, and identity;
- provisional and final text have one canonical visible owner;
- OpenCode model switches recompute wire protocol and normalize base URL;
- all auxiliary model calls pass through the shared route and adapter factory;
- focused backend, journal, SSE, frontend projection, and build checks pass;
- runtime logs can reconstruct why a turn continued, called tools, completed, or failed.

## Version And Runtime Impact

Version impact: major architectural behavior change, even if public HTTP compatibility fields remain temporarily available.

Launcher refresh: required for runtime verification after backend or frontend implementation. No refresh is needed for this design document alone.
