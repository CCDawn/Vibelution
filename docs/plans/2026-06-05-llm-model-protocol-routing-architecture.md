# LLM Model Protocol Routing Architecture

Date: 2026-06-05
Owner: agent runtime / LLM runtime
Status: implementation-ready design

## Background

Vibelution currently has a useful but incomplete LLM split:

- `LLMProfile` describes model, provider, transport, contract, tool mode, prompt cache, streaming, and thinking flags.
- `ProviderAdapter` handles provider-level differences such as Anthropic, DeepSeek, MiniMax, and OpenAI-compatible routing.
- `LLMClient` normalizes messages, builds payloads, invokes LiteLLM, records usage, extracts reasoning, and handles retry/error reporting.
- Agent model binding resolves through the model library before a chat turn starts.

The recent Gu Yunshu failure shows the missing boundary:

```text
provider_protocol_error:
Assistant response prefill is incompatible with enable_thinking.
```

The failed model was a local llama.cpp / Qwen-family model resolved from model library:

```text
providerKind = llamacpp
model = HiModel_xh2_qwen3.5_9b_256_256k_b1_1chip_2cores_v1.3.0_20260429.gguf
supportsThinking = true
```

The system knew the model supported thinking, but the request still reached the provider in a shape that the provider interpreted as assistant response prefill. This is not just one bad flag. It reveals that provider kind, transport, model family, thinking protocol, reasoning roundtrip, tool behavior, message shape, and final-message policy are not separated clearly enough.

## OpenClaw Reference

OpenClaw separates model selection into multiple explicit concepts:

- model references are provider-qualified, such as `anthropic/claude-sonnet-4-6`, `openai/gpt-5.4`, or `local/my-local-model`.
- provider configuration defines how to connect.
- API/protocol style is explicit, such as `openai-completions`, `openai-responses`, `anthropic-messages`, or `google-generative-ai`.
- model-level compatibility hints describe details such as string-only content, strict message keys, tool support, reasoning support, and thinking format.
- default model fallback and strict user selection are different behaviors.

Useful references:

- [OpenClaw Models](https://docs.openclaw.ai/concepts/models)
- [OpenClaw Model Failover](https://docs.openclaw.ai/concepts/model-failover)
- [OpenClaw Configuration / Custom Providers](https://docs.openclaw.ai/gateway/config-tools)
- [OpenClaw Local Models](https://docs.openclaw.ai/gateway/local-models)

Vibelution should borrow this boundary design without copying OpenClaw's storage layout directly.

## Goal

Introduce an explicit model protocol routing layer so every LLM call follows a declared, validated protocol path:

```text
Agent model binding
  -> model library entry
  -> provider connection
  -> model protocol resolver
  -> protocol policy
  -> payload builder
  -> payload validator
  -> provider adapter
  -> LiteLLM/provider call
  -> stream/response normalizer
```

The target state is not "more if statements in `LLMClient`". The target state is a maintainable protocol architecture where adding a model normally means choosing or adding a `ModelProtocol` and declaring compatibility rules.

## Non-Goals

This design does not solve these adjacent problems in the same implementation slice:

- chat history pollution from stale active tasks
- frontend reasoning display design
- group chat UX
- context compression policy
- agent task continuation semantics
- provider service stability
- prompt optimization

Those areas may use the new logs later, but they should not be mixed into this protocol refactor.

## Architecture Boundaries

### 1. Model Library

The model library answers:

```text
What model asset can be selected?
```

It should store model identity, provider reference, default protocol, declared capabilities, and compatibility hints.

Suggested normalized shape:

```json
{
  "modelId": "houmo_qwen35_9b_agent",
  "label": "Houmo Qwen 3.5 9B",
  "providerId": "houmo_local",
  "model": "HiModel_xh2_qwen3.5_9b_256_256k_b1_1chip_2cores_v1.3.0_20260429.gguf",
  "protocol": "llamacpp_qwen_thinking",
  "transport": "chat_completions",
  "contract": "tool_chat",
  "capabilities": {
    "streaming": true,
    "tools": true,
    "parallelTools": false,
    "imageInput": false,
    "promptCache": true,
    "thinking": true,
    "reasoningRoundtrip": false
  },
  "compat": {
    "requiresStringContent": true,
    "strictMessageKeys": true,
    "allowAssistantPrefill": false,
    "reasoningRoundtrip": false,
    "thinkingFormat": "qwen",
    "toolChoiceMode": "omit",
    "streamUsageOptions": false
  }
}
```

### 2. Provider Connection

The provider answers:

```text
How do we connect to the upstream API?
```

Provider config should not encode model behavior. It should describe connection target, auth, API family, and network trust boundary.

Suggested shape:

```json
{
  "providerId": "houmo_local",
  "kind": "llamacpp",
  "api": "openai-completions",
  "baseUrl": "http://192.168.20.30:8081/v1",
  "apiKeyEnv": "VIBELUTION_HOUMO_API_KEY",
  "compatMode": "openai_compatible"
}
```

`api` is intentionally separate from `kind`.

Examples:

```text
openai-completions
openai-responses
anthropic-messages
deepseek-chat
minimax-chat
local-openai-compatible
qwen-openai-compatible
```

### 3. Model Protocol

The protocol answers:

```text
What payload and response rules does this model route require?
```

New modules:

```text
core/llm/protocols.py
core/llm/protocol_resolver.py
```

First protocol set:

```text
basic_chat_no_tools
openai_chat_tools
openai_responses
anthropic_chat
anthropic_thinking
deepseek_reasoning
qwen_openai_compat
qwen_thinking_no_prefill
llamacpp_basic
llamacpp_qwen_thinking
minimax_chat
relay_responses
```

Each protocol maps to one immutable policy.

### 4. Provider Adapter

The adapter answers:

```text
What provider-level translation is needed after protocol policy has shaped the payload?
```

`ProviderAdapter` should keep responsibilities such as:

- LiteLLM model prefix
- provider-specific system message conversion
- provider-specific tool schema sanitization
- provider-specific sampling parameter adjustment
- provider-specific stream normalizer

It should stop owning broad model-family behavior such as:

- whether Qwen thinking allows assistant prefill
- whether DeepSeek reasoning content must be round-tripped
- whether a local OpenAI-compatible endpoint accepts structured content
- whether `stream_options.include_usage` is safe

Those are protocol/compat concerns.

### 5. LLMClient

`LLMClient` should become orchestration:

- load profile/provider/model route
- resolve protocol policy
- call payload builder
- call payload validator
- invoke backend with retry/concurrency gates
- record route and usage logs
- normalize response/stream events

It should not accumulate new provider/model-specific branches.

## Core Data Types

### `ModelProtocol`

```python
from enum import StrEnum


class ModelProtocol(StrEnum):
    BASIC_CHAT_NO_TOOLS = "basic_chat_no_tools"
    OPENAI_CHAT_TOOLS = "openai_chat_tools"
    OPENAI_RESPONSES = "openai_responses"
    ANTHROPIC_CHAT = "anthropic_chat"
    ANTHROPIC_THINKING = "anthropic_thinking"
    DEEPSEEK_REASONING = "deepseek_reasoning"
    QWEN_OPENAI_COMPAT = "qwen_openai_compat"
    QWEN_THINKING_NO_PREFILL = "qwen_thinking_no_prefill"
    LLAMACPP_BASIC = "llamacpp_basic"
    LLAMACPP_QWEN_THINKING = "llamacpp_qwen_thinking"
    MINIMAX_CHAT = "minimax_chat"
    RELAY_RESPONSES = "relay_responses"
```

### `CompatPolicy`

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class CompatPolicy:
    requires_string_content: bool = False
    strict_message_keys: bool = False
    allow_assistant_prefill: bool = True
    reasoning_roundtrip: bool = False
    thinking_format: str = ""
    tool_choice_mode: str = "auto"  # auto | omit | required | none
    stream_usage_options: bool = False
```

### `ProtocolPolicy`

```python
@dataclass(frozen=True)
class ProtocolPolicy:
    protocol: ModelProtocol
    transport: str
    allow_tools: bool
    allow_parallel_tools: bool
    allow_explicit_tool_choice: bool
    allow_stream_usage_options: bool
    allow_multiple_system_messages: bool
    allow_assistant_prefill: bool
    allow_reasoning_roundtrip: bool
    thinking_param_shape: str  # none | anthropic | qwen | qwen_chat_template
    system_message_policy: str  # preserve | first_only_rest_user | merge_to_user
    final_message_policy: str  # any | no_assistant_prefill | must_end_user_or_tool
    content_shape_policy: str  # preserve | string_only | responses_blocks
    reasoning_extract_policy: str  # generic | deepseek | think_tag | anthropic
    tool_schema_policy: str  # default | strict_json_schema | minimal
```

### `ResolvedProtocolRoute`

```python
@dataclass(frozen=True)
class ResolvedProtocolRoute:
    profile_id: str
    model_id: str
    provider_id: str
    provider_kind: str
    provider_api: str
    model: str
    protocol: ModelProtocol
    policy: ProtocolPolicy
    compat: CompatPolicy
    source: str  # explicit_model | provider_api | inferred | fallback
    warnings: tuple[str, ...] = ()
```

## Protocol Policy Examples

### `llamacpp_qwen_thinking`

Used for local OpenAI-compatible Qwen-family models that expose thinking behavior.

```text
transport = chat_completions
allow_tools = true, if model library declares tools
allow_explicit_tool_choice = false by default
allow_stream_usage_options = false by default
allow_assistant_prefill = false
allow_reasoning_roundtrip = false
thinking_param_shape = qwen
system_message_policy = first_only_rest_user
final_message_policy = no_assistant_prefill
content_shape_policy = string_only
reasoning_extract_policy = think_tag
tool_schema_policy = minimal
```

This protocol should prevent the Gu Yunshu failure before provider call.

### `deepseek_reasoning`

Used for official DeepSeek reasoning models.

```text
transport = chat_completions
allow_tools = true
allow_explicit_tool_choice = false
allow_assistant_prefill = true, unless provider says otherwise
allow_reasoning_roundtrip = true
thinking_param_shape = none
reasoning_extract_policy = deepseek
```

DeepSeek is the main route where `reasoning_content` roundtrip is expected and protected.

### `anthropic_thinking`

Used for Anthropic native thinking routes.

```text
transport = chat_completions
allow_tools = true
allow_explicit_tool_choice = true
allow_reasoning_roundtrip = false
thinking_param_shape = anthropic
content_shape_policy = preserve
reasoning_extract_policy = anthropic
```

### `basic_chat_no_tools`

Used for conservative fallback.

```text
transport = chat_completions
allow_tools = false
allow_explicit_tool_choice = false
allow_stream_usage_options = false
allow_reasoning_roundtrip = false
thinking_param_shape = none
content_shape_policy = string_only
```

This route should be boring and hard to break.

## Protocol Resolver

Resolver priority:

```text
1. model library explicit `protocol`
2. provider explicit `api`
3. profile `transport` + `contract`
4. provider kind + model family hints
5. conservative fallback
```

Explicit model protocol always wins. Model-name inference should be a fallback, not the primary system.

Pseudo-code:

```python
def resolve_model_protocol(profile, provider, model_entry=None) -> ResolvedProtocolRoute:
    if model_entry and model_entry.protocol:
        protocol = ModelProtocol(model_entry.protocol)
        return route(protocol, source="explicit_model")

    provider_api = normalize_provider_api(provider.api)
    if provider_api:
        protocol = protocol_from_provider_api(provider_api, profile, model_entry)
        if protocol:
            return route(protocol, source="provider_api")

    protocol = protocol_from_transport_contract(profile.transport, profile.contract, provider.kind)
    if protocol:
        return route(protocol, source="profile_contract")

    protocol = infer_protocol_from_model_name(provider.kind, provider.base_url, profile.model, profile)
    if protocol:
        return route(protocol, source="inferred")

    return route(ModelProtocol.BASIC_CHAT_NO_TOOLS, source="fallback")
```

Important inference rules:

- `provider.kind == "anthropic"` and `thinking_type` set -> `anthropic_thinking`
- `provider.kind == "deepseek"` and `contract == "reasoning_chat"` -> `deepseek_reasoning`
- `transport == "responses"` and provider is OpenAI/relay -> `openai_responses` or `relay_responses`
- model name contains `qwen` and thinking enabled -> `qwen_thinking_no_prefill`
- provider kind is `llamacpp` or local network OpenAI-compatible and model name contains `qwen` with thinking enabled -> `llamacpp_qwen_thinking`
- provider kind is local/llamacpp and tools disabled -> `llamacpp_basic`

## Payload Builder

New module:

```text
core/llm/payload_builder.py
```

Target steps:

```text
1. Convert internal LangChain messages to neutral payload messages.
2. Apply content shape policy.
3. Apply system message policy.
4. Apply reasoning roundtrip policy.
5. Apply thinking parameter policy.
6. Apply tool policy.
7. Apply streaming policy.
8. Apply provider adapter final shaping.
```

Builder input:

```python
@dataclass(frozen=True)
class PayloadBuildInput:
    messages: list[Any]
    tools: list[Any]
    profile: LLMProfile
    provider: ProviderConfig
    route: ResolvedProtocolRoute
    stream: bool
    api_key: str
```

Builder output:

```python
@dataclass(frozen=True)
class BuiltPayload:
    payload: dict[str, Any]
    route: ResolvedProtocolRoute
    summary: dict[str, Any]
    warnings: tuple[str, ...]
```

The builder must not call the provider and must be unit-testable.

## Payload Validator

New module:

```text
core/llm/payload_validator.py
```

Validator input:

```python
@dataclass(frozen=True)
class PayloadValidationResult:
    ok: bool
    error_type: str = ""
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
```

Validation rules:

### Message role rules

- `strict_message_keys=true` removes unexpected fields from messages before validation.
- `allow_multiple_system_messages=false` requires adapter/builder to convert later system messages.
- `final_message_policy=no_assistant_prefill` rejects final assistant messages that look like prefill.
- `final_message_policy=must_end_user_or_tool` rejects final assistant messages even if non-empty.

### Thinking rules

- If `thinkingRequested=true` and `allowAssistantPrefill=false`, assistant prefill must be rejected.
- If `thinking_param_shape=none`, no `thinking`, `enable_thinking`, or related provider parameter may be sent.
- If `thinking_param_shape=qwen`, only Qwen-compatible thinking fields may be emitted.
- If `thinking_param_shape=anthropic`, only Anthropic-compatible thinking fields may be emitted.

### Reasoning rules

- If `allow_reasoning_roundtrip=false`, outgoing assistant messages must not include `reasoning_content`.
- If `allow_reasoning_roundtrip=true`, only assistant history messages may carry `reasoning_content`; user/tool/system messages may not.

### Tool rules

- If `allow_tools=false`, no `tools` or `tool_choice` may be present.
- If `allow_explicit_tool_choice=false`, `tool_choice` must be omitted.
- If `toolChoiceMode=omit`, `tool_choice` must be omitted even if tools are present.

### Stream rules

- If `allow_stream_usage_options=false`, `stream_options.include_usage` must not be sent.

Validation failure should raise `LLMError` before provider call:

```text
category = payload_protocol_error
retryable = false
```

This is different from provider errors. It means Vibelution built an invalid payload for the selected protocol.

## Logging

Every LLM call must record a safe final payload summary after builder/validator and before provider call.

Required fields:

```text
profileId
modelId
providerId
providerKind
providerApi
runtimeRoute
protocol
protocolSource
transport
contract
thinkingRequested
thinkingFormat
toolCount
toolChoiceMode
messageCount
messageRoles
messageRoleTail
lastMessageRole
assistantPrefillDetected
reasoningRoundtripEnabled
strictMessageKeys
requiresStringContent
payloadValidationResult
payloadValidationErrorType
```

Do not log:

- full prompt
- full tool schemas
- API keys
- full provider payload
- full model output

Gu Yunshu's failure should become diagnosable from one safe event:

```text
selectedProtocol=llamacpp_qwen_thinking
thinkingRequested=true
assistantPrefillDetected=true
payloadValidationResult=blocked_before_provider
payloadValidationErrorType=payload_protocol_error
```

## Error Taxonomy

Add a local category:

```text
payload_protocol_error
```

Meaning:

```text
Vibelution selected a protocol and then produced a payload that violates that protocol.
```

Difference from existing categories:

- `provider_protocol_error`: provider rejected the request after network call.
- `payload_protocol_error`: local validator blocked the request before network call.
- `capability_error`: the requested capability is unavailable for the selected model.
- `configuration_error`: required config/key/base URL/model entry is missing or invalid.

## Fallback Semantics

Borrow the OpenClaw distinction between default fallback and strict user selection.

### Default agent binding

If an Agent uses a default model chain, fallback may be allowed when configured:

```text
primary -> fallback_1 -> fallback_2
```

Every fallback must log:

```text
fallbackSource=agent_default
fromModelId
toModelId
reason
```

### Explicit user or Agent model selection

If the user explicitly selected a model for an Agent slot, the run is strict by default.

Failure should not silently switch models unless the slot explicitly declares a fallback chain.

Reason:

```text
User-selected model identity is part of the Agent's expected behavior.
```

## Configuration Migration

Migration should be backward-compatible and staged.

### Stage 1: Read support

Add optional fields to config models:

```text
LLMProfile.protocol
LLMProfile.compat
ProviderConfig.api
model_library[].protocol
model_library[].capabilities
model_library[].compat
```

Existing config without these fields must still load.

### Stage 2: Inference and diagnostics

When fields are missing, infer route and emit warnings:

```text
model_protocol.inferred
model_protocol.missing_explicit_protocol
model_protocol.local_advanced_route_warning
```

### Stage 3: UI/API surfacing

Settings should show:

```text
Provider
API
Protocol
Capabilities
Compat
```

Editing can remain conservative initially. It is enough to display diagnostics and allow explicit protocol selection for advanced model entries.

### Stage 4: Strict mode

After migration, new model entries should require explicit `protocol` or `provider.api`.

## Implementation Plan

### Phase 1: Protocol skeleton

Files:

```text
core/llm/protocols.py
core/llm/protocol_resolver.py
tests/test_llm_protocol_resolver.py
```

Deliverables:

- `ModelProtocol`
- `ProtocolPolicy`
- `CompatPolicy`
- `ResolvedProtocolRoute`
- resolver with priority rules
- tests for explicit, provider API, inferred, and fallback routes

No runtime behavior change yet.

### Phase 2: Config model support

Files:

```text
config/models.py
config/public_config.py
config/settings.py
core/web/services/config_service.py
tests/test_public_config_model_refs.py
tests/test_config_sync.py
```

Deliverables:

- optional protocol/compat fields
- public config roundtrip
- model library option decoration includes protocol and compat summary
- migration keeps old config valid

### Phase 3: Payload builder extraction

Files:

```text
core/llm/payload_builder.py
core/llm/client.py
tests/test_llm_payload_builder.py
tests/test_llm_client.py
```

Deliverables:

- `_build_payload` logic moved out of `LLMClient`
- client calls builder with resolved protocol route
- existing behavior preserved for current common routes

### Phase 4: Payload validator

Files:

```text
core/llm/payload_validator.py
core/llm/client.py
core/llm/errors.py
tests/test_llm_payload_validator.py
tests/test_provider_error_recovery.py
```

Deliverables:

- `payload_protocol_error`
- validator blocks invalid protocol payloads before provider call
- Gu Yunshu failure is blocked locally with actionable detail

### Phase 5: Protocol-specific normalization

Files:

```text
core/llm/payload_builder.py
core/llm/adapters.py
core/llm/streaming.py
tests/test_llm_client_protocol_integration.py
```

Deliverables:

- DeepSeek reasoning roundtrip isolated
- Anthropic thinking isolated
- Qwen/llama.cpp thinking no-prefill isolated
- MiniMax system-message behavior preserved
- Responses transport content conversion preserved

### Phase 6: Logs and diagnostics

Files:

```text
core/llm/client.py
core/web/services/runtime_scene_service.py
tests/test_runtime_scene_package_diagnosis.py
```

Deliverables:

- safe final payload route summary
- protocol source in logs
- validation result in logs
- diagnostics no longer require guessing from provider 400

## Test Plan

### Unit tests

```text
tests/test_llm_protocol_resolver.py
tests/test_llm_payload_builder.py
tests/test_llm_payload_validator.py
```

Must cover:

- explicit `protocol` wins over inference
- provider `api=openai-responses` selects responses protocol
- `llamacpp + qwen + thinking` selects `llamacpp_qwen_thinking`
- `deepseek + reasoning_chat` selects `deepseek_reasoning`
- unknown local model falls back to `basic_chat_no_tools`
- Qwen thinking rejects assistant prefill
- Qwen thinking strips or blocks `reasoning_content` roundtrip
- DeepSeek reasoning preserves `reasoning_content`
- basic chat emits no tools/thinking/stream usage options
- MiniMax converts later system messages

### Integration tests

```text
tests/test_llm_client.py
tests/test_provider_error_recovery.py
tests/test_agent_llm_runtime.py
```

Must cover:

- `LLMClient` records selected protocol in failure metadata
- provider call is not attempted when validator blocks payload
- explicit user-selected model does not silently fallback
- default fallback chain still works when configured

### Regression replay

Create a focused replay from the Gu Yunshu failure:

```text
session = session-20260604-184016
turn = session-20260604-184016-20260605160542272834
user = 今天是星期几
modelId = houmo_qwen35_9b_agent
expectedProtocol = llamacpp_qwen_thinking
```

Expected result:

- request payload does not contain assistant prefill
- if invalid assistant prefill is present, validator blocks before provider
- no `Assistant response prefill is incompatible with enable_thinking` provider 400

## Acceptance Criteria

The refactor is complete when:

- every LLM call logs `selectedProtocol`
- `LLMClient` no longer owns broad model-family branching
- provider adapters only own provider-specific translation
- local Qwen thinking routes cannot send assistant prefill
- DeepSeek reasoning roundtrip is isolated to DeepSeek-compatible protocols
- Anthropic thinking parameters are isolated to Anthropic-compatible protocols
- basic local models can run without tools/thinking/reasoning extras
- explicit model selection is strict unless fallback is configured
- all new protocol resolver/builder/validator tests pass
- Gu Yunshu's failure class is covered by a regression test

## Risk Review

### Risk: breaking existing working providers

Mitigation:

- Phase 1 has no runtime behavior change.
- Payload builder extraction should preserve existing route output first.
- Add golden payload summaries for common providers.

### Risk: overfitting model name inference

Mitigation:

- Explicit `protocol` wins.
- Inference is only fallback.
- Logs must show `protocolSource`.

### Risk: config UI becomes too complex

Mitigation:

- Advanced protocol/compat fields can be collapsed.
- Default presets handle common routes.
- Diagnostics explain why a protocol was inferred.

### Risk: false-positive payload blocking

Mitigation:

- Validator failures must include protocol, rule, and message tail summary.
- Validator starts strict only for protocols with known provider failures.
- Unknown routes can use conservative `basic_chat_no_tools`.

### Risk: mixing this refactor with chat task pollution

Mitigation:

- This plan explicitly excludes session task pollution.
- New logs will make that later bug easier to diagnose.

## Recommended First Slice

Start with a minimal behavior-preserving skeleton:

```text
1. Add protocols.py and protocol_resolver.py.
2. Add tests for route selection.
3. Wire resolver into LLMClient logs only.
4. Do not change outgoing payload yet.
```

This creates the architectural boundary without risking all providers at once.

The second slice should add the validator for only the known failing route:

```text
llamacpp_qwen_thinking forbids assistant prefill with thinking enabled.
```

After that, move payload construction out of `LLMClient` and expand protocol coverage.
