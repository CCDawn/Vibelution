# Outbound Semantic Adapter Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route production Responses and Chat Completions requests through one provider-neutral `SemanticModelRequest` and the immutable route's required `WireAdapter`, while preserving the existing runtime envelope and rejecting unsupported protocols before provider I/O.

**Architecture:** Existing model messages are converted once by a focused semantic projector. The selected wire adapter owns `input/messages`, protocol tool schemas, and tool-result encoding; `payload_builder` continues to own credentials, timeout, provider model naming, prompt-cache/thinking parameters, headers, validation, and bounded summaries. Responses switches first, Chat switches second, and every invocation has exactly one outbound payload owner.

**Tech Stack:** Python 3.11+, dataclasses, LangChain message types, LiteLLM/OpenAI backends, pytest, Vibelution runtime-scene logging.

## Global Constraints

- Do not modify `agent.py`, XML tool fallback, tool execution, approval policy, journal, SessionTurnItem v2, React, or operator configuration.
- Do not enable Anthropic Messages or Gemini; selecting an unregistered adapter must hard-fail before provider I/O.
- Do not log prompts, messages, raw payloads, replay blobs, credentials, or full tool arguments.
- Preserve configured endpoint versus runtime endpoint separation.
- Preserve provider-prefixed transport model names, timeout, prompt cache, thinking parameters, sampling, headers, stream usage options, capability gates, and payload validation.
- Production must never build or send both legacy and semantic payloads for one invocation.
- Responses and Chat ownership changes are separate commits and separate review gates.
- Use an isolated worktree based on current local `main`, claim only the files for the active task, and serialize all edits to `core/llm/client.py` and `core/llm/payload_builder.py`.
- Version impact is patch-level; task agents report impact but do not edit `VERSION`, `CHANGELOG.md`, or package versions.

---

## File Structure

- Create `core/llm/semantic_projector.py`: compatibility bridge from existing model messages/tools to provider-neutral semantic parts.
- Modify `core/llm/semantic_messages.py`: add safe cache-hint metadata required to preserve explicit cache-control semantics.
- Modify `core/llm/wire/registry.py`: expose required-adapter preflight with a stable error boundary.
- Modify `core/llm/wire/chat_completions.py`: encode safe cache hints and proven Chat parity gaps only.
- Modify `core/llm/wire/responses.py`: encode safe cache hints and proven Responses parity gaps only.
- Modify `core/llm/payload_builder.py`: compose one adapter-owned protocol body with the existing runtime envelope and validator.
- Modify `core/llm/client.py`: construct semantic requests, require the route adapter, select one outbound owner, and remove decode fallback after both cutovers.
- Create `tests/test_llm_semantic_projector.py`: semantic role/part/tool/replay/cache contract tests.
- Create `tests/test_llm_client_outbound_wire_bridge.py`: production client dispatch, hard-fail, one-owner, envelope, and parity tests.
- Extend `tests/test_llm_wire_responses.py`, `tests/test_llm_wire_chat_completions.py`, `tests/test_llm_payload_builder.py`, `tests/test_llm_payload_validator.py`, and `tests/test_llm_client_outcome_bridge.py` only for behavior owned by the corresponding task.

---

### Task 1: Provider-Neutral Semantic Projector

**Files:**
- Create: `core/llm/semantic_projector.py`
- Modify: `core/llm/semantic_messages.py`
- Test: `tests/test_llm_semantic_projector.py`
- Test: `tests/test_llm_semantic_messages.py`

**Interfaces:**
- Consumes: existing dict/LangChain model messages, `InvocationScope`, selected tools, `ProviderReplayState`, and a caller-provided safe tool-schema function.
- Produces: `SemanticProjectionInput`, `SemanticProjectionError`, and `project_semantic_request(input: SemanticProjectionInput) -> SemanticModelRequest`.
- Produces: `CacheHint`, plus optional `cache_hint` on `TextPart` and `ImagePart`.

- [ ] **Step 1: Write failing semantic projection tests**

Create tests that lock role, content, tool identity, ordering, and rejection behavior:

```python
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
import pytest

from core.llm.semantic_messages import InvocationScope, SemanticGenerationSettings
from core.llm.semantic_projector import (
    SemanticProjectionError,
    SemanticProjectionInput,
    project_semantic_request,
)


def scope():
    return InvocationScope(
        session_id="session-1",
        turn_id="turn-1",
        invocation_id="invocation-1",
        iteration=0,
    )


def project(messages, tools=()):
    return project_semantic_request(
        SemanticProjectionInput(
            messages=tuple(messages),
            tools=tuple(tools),
            scope=scope(),
            settings=SemanticGenerationSettings(max_output_tokens=256),
            tool_to_schema=lambda tool: tool,
        )
    )


def test_projector_preserves_text_tool_call_and_result_identity_in_order():
    request = project([
        HumanMessage(content="查资料"),
        AIMessage(
            content="我先查询。",
            tool_calls=[{"id": "call-search", "name": "search", "args": {"q": "moon"}}],
        ),
        ToolMessage(content="result", tool_call_id="call-search", name="search"),
        HumanMessage(content="继续"),
    ])

    assert [message.role for message in request.messages] == ["user", "assistant", "tool", "user"]
    call = request.messages[1].parts[1].call
    result = request.messages[2].parts[0].result
    assert call.call_id == result.call_id == "call-search"
    assert call.identity.session_id == result.identity.session_id == "session-1"


def test_projector_rejects_orphan_tool_result_before_adapter_dispatch():
    with pytest.raises(SemanticProjectionError) as exc_info:
        project([ToolMessage(content="orphan", tool_call_id="missing", name="search")])
    assert exc_info.value.code == "orphan_tool_result"
    assert exc_info.value.message_index == 0


def test_projector_rejects_ui_tool_calls_field():
    with pytest.raises(SemanticProjectionError) as exc_info:
        project([{"role": "assistant", "content": "", "toolCalls": [{"id": "ui-only"}]}])
    assert exc_info.value.code == "ui_projection_not_model_input"
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_llm_semantic_projector.py tests/test_llm_semantic_messages.py -q
```

Expected: collection fails because `core.llm.semantic_projector` and `CacheHint` do not exist.

- [ ] **Step 3: Add cache-hint semantic types**

Add to `semantic_messages.py`:

```python
@dataclass(frozen=True)
class CacheHint:
    mode: str

    def __post_init__(self) -> None:
        if self.mode not in {"ephemeral"}:
            raise ValueError("unsupported semantic cache hint")


@dataclass(frozen=True)
class TextPart:
    text: str
    cache_hint: CacheHint | None = None


@dataclass(frozen=True)
class ImagePart:
    uri: str
    media_type: str
    detail: str = ""
    cache_hint: CacheHint | None = None
```

Export `CacheHint` in `__all__`. Do not add arbitrary provider metadata mappings.

- [ ] **Step 4: Implement the projector boundary**

Create `semantic_projector.py` with these public definitions:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .provider_replay_state import ProviderReplayState
from .semantic_messages import (
    InvocationScope,
    SemanticGenerationSettings,
    SemanticModelRequest,
)


class SemanticProjectionError(ValueError):
    def __init__(self, code: str, message_index: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message_index = message_index


@dataclass(frozen=True)
class SemanticProjectionInput:
    messages: Sequence[Any]
    tools: Sequence[Any]
    scope: InvocationScope
    settings: SemanticGenerationSettings
    tool_to_schema: Callable[[Any], Mapping[str, Any]]
    replay_state: ProviderReplayState | None = None


def project_semantic_request(input: SemanticProjectionInput) -> SemanticModelRequest:
    messages = _project_messages(input.messages, scope=input.scope)
    tools = _project_tools(input.tools, tool_to_schema=input.tool_to_schema)
    return SemanticModelRequest(
        scope=input.scope,
        messages=tuple(messages),
        tools=tuple(tools),
        settings=input.settings,
        replay_state=input.replay_state,
    )
```

Private helpers must:

- normalize dict and LangChain roles without protocol field names in returned values;
- derive deterministic `CanonicalItemIdentity.item_id` as `tool-call:{call_id}` and `tool-result:{call_id}`;
- reject duplicate/empty call IDs and orphan results;
- preserve multiple tool calls and adjacent results in source order;
- map text/image blocks and only the safe `cache_control={"type": "ephemeral"}` form;
- map explicit `reasoning_replay_item_id` references to `ReasoningReplayPart` without reading replay bytes;
- raise `SemanticProjectionError(code, message_index, safe_message)` for unsupported shapes.

- [ ] **Step 5: Run semantic tests to verify GREEN**

Run the Step 2 command.

Expected: all semantic projector and semantic message tests pass.

- [ ] **Step 6: Commit Task 1**

```powershell
git add -- core/llm/semantic_messages.py core/llm/semantic_projector.py tests/test_llm_semantic_messages.py tests/test_llm_semantic_projector.py
git commit -m "feat(llm): project model messages to semantic requests"
```

Review gate: no OpenAI `messages`, Responses `input`, `function_call_output`, credentials, endpoint logic, or raw replay bytes appear in the projector.

---

### Task 2: Required Wire Adapter Preflight

**Files:**
- Modify: `core/llm/wire/registry.py`
- Modify: `core/llm/client.py`
- Test: `tests/test_llm_client_outbound_wire_bridge.py`
- Test: `tests/test_llm_semantic_messages.py`

**Interfaces:**
- Consumes: immutable `ResolvedProtocolRoute` and default wire registry.
- Produces: `WireAdapterRegistry.require(route) -> WireAdapter`.
- Produces: `LLMClient._required_wire_adapter() -> WireAdapter`, raising typed non-retryable `LLMError` when unavailable.

- [ ] **Step 1: Write failing hard-fail tests**

```python
import pytest

from core.llm.client import LLMClient
from core.llm.errors import LLMError
from tests.helpers.isolated_config import isolated_settings_config


def test_unsupported_native_adapter_fails_before_provider_io():
    calls = []
    config = isolated_settings_config(**{
        "llm.providers.default.kind": "anthropic",
        "llm.providers.default.api": "anthropic-messages",
        "llm.providers.default.api_key": "test-key",
        "llm.providers.default.base_url": "https://api.anthropic.com",
        "llm.profiles.primary.provider_id": "default",
        "llm.profiles.primary.model": "claude-test",
    })
    client = LLMClient(config=config, backend=lambda payload: calls.append(payload))

    with pytest.raises(LLMError) as exc_info:
        client.invoke([{"role": "user", "content": "ping"}])

    assert exc_info.value.category == "unsupported_wire_protocol"
    assert exc_info.value.retryable is False
    assert calls == []
    assert "test-key" not in str(exc_info.value.details)
```

- [ ] **Step 2: Run the hard-fail test to verify RED**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_llm_client_outbound_wire_bridge.py -k "unsupported_native_adapter" -q
```

Expected: FAIL because the client reaches payload/backend compatibility handling instead of raising `unsupported_wire_protocol` at preflight.

- [ ] **Step 3: Add registry `require`**

```python
def require(self, route: Any) -> WireAdapter:
    adapter_id = str(getattr(route, "adapter_id", "") or "").strip()
    try:
        return self.resolve(route)
    except LookupError as exc:
        wire_protocol = str(getattr(getattr(route, "wire_protocol", None), "value", "") or "")
        raise LookupError(
            f"required wire adapter `{adapter_id or wire_protocol or 'unknown'}` is unavailable"
        ) from exc
```

Keep `resolve()` for existing registry contract tests; production client uses `require()`.

- [ ] **Step 4: Add typed client preflight**

```python
def _required_wire_adapter(self):
    try:
        return _CANONICAL_WIRE_ADAPTERS.require(self.protocol_route)
    except LookupError as exc:
        route = self.protocol_route
        raise LLMError(
            "unsupported_wire_protocol",
            str(exc),
            retryable=False,
            provider=self.provider.kind,
            model=self.profile.model,
            details={
                "profileId": self.profile_id,
                "providerKind": self.provider.kind,
                "modelId": route.model_id,
                "wireProtocol": route.wire_protocol.value,
                "adapterId": route.adapter_id,
                "routeSource": route.wire_source,
                "payloadValidationResult": "blocked_before_provider",
            },
        ) from exc
```

Call this helper at the beginning of `_build_payload()`. Do not yet remove decode compatibility branches; Task 5 removes them after both encoders own production sends.

- [ ] **Step 5: Run hard-fail and resolver tests**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_llm_client_outbound_wire_bridge.py tests/test_llm_protocol_resolver.py tests/test_llm_semantic_messages.py -q
```

Expected: all pass and backend call count remains zero for unsupported routes.

- [ ] **Step 6: Commit Task 2**

```powershell
git add -- core/llm/wire/registry.py core/llm/client.py tests/test_llm_client_outbound_wire_bridge.py tests/test_llm_semantic_messages.py
git commit -m "fix(llm): reject unavailable wire adapters before send"
```

Review gate: error details are bounded and no credential, prompt, raw payload, or replay content is present.

---

### Task 3: Responses Production Outbound Cutover

**Files:**
- Modify: `core/llm/payload_builder.py`
- Modify: `core/llm/client.py`
- Modify: `core/llm/wire/responses.py` only for fixture-proven parity gaps
- Test: `tests/test_llm_client_outbound_wire_bridge.py`
- Test: `tests/test_llm_wire_responses.py`
- Test: `tests/test_llm_payload_builder.py`
- Test: `tests/test_llm_payload_validator.py`
- Test: `tests/test_llm_client_outcome_bridge.py`

**Interfaces:**
- Consumes: `SemanticProjectionInput`, required adapter, existing `PayloadBuildInput`, payload policy helpers, and wire `BuiltPayload(body, endpoint, headers)`.
- Produces: `compose_runtime_wire_payload(...) -> payload_builder.BuiltPayload`.
- Produces: Responses `_build_payload()` branch whose sole protocol body owner is `ResponsesWireAdapter.encode_request()`.

- [ ] **Step 1: Write failing production dispatch and one-owner tests**

```python
def test_responses_client_uses_registry_encoder_once_and_preserves_runtime_envelope(monkeypatch):
    client = LLMClient(config=_config(transport="responses"), backend=lambda payload: payload)
    adapter = client._required_wire_adapter()
    calls = []
    original = adapter.encode_request

    def observed(request, *, route):
        calls.append((request, route))
        return original(request, route=route)

    monkeypatch.setattr(adapter, "encode_request", observed)
    payload = client._build_payload(
        [{"role": "user", "content": "ping"}],
        stream=True,
    )

    assert len(calls) == 1
    assert "input" in payload and "messages" not in payload
    assert payload["api_key"] == "test-key"
    assert payload["base_url"] == "https://relay.example.test/v1"
    assert payload["timeout"] > 0
    assert payload["stream"] is True
```

Add a paired function-call/result fixture asserting exact `call_id`, order, and validator summary.

- [ ] **Step 2: Run Responses integration tests to verify RED**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_llm_client_outbound_wire_bridge.py -k "responses" -q
```

Expected: FAIL because production `_build_payload()` does not call the registry encoder.

- [ ] **Step 3: Add runtime envelope composition**

Add a focused function to `payload_builder.py`:

```python
def compose_runtime_wire_payload(
    build_input: PayloadBuildInput,
    *,
    wire_payload: "WireBuiltPayload",
    protocol_summary: dict[str, Any],
    policy_actions: PayloadPolicyActions,
) -> BuiltPayload:
    payload = dict(wire_payload.body)
    payload["model"] = build_input.adapter.litellm_model_name()
    payload["timeout"] = _provider_timeout(build_input.profile)
    payload["api_key"] = build_input.api_key
    payload["base_url"] = wire_payload.endpoint or build_input.route.runtime_endpoint
    _apply_runtime_sampling_thinking_cache_and_headers(
        payload,
        build_input=build_input,
        policy_actions=policy_actions,
    )
    validated = assert_payload_valid(payload, build_input.route)
    summary = dict(protocol_summary)
    summary.update(validated)
    summary.update(policy_actions.to_log_dict())
    summary.update(_payload_message_snapshot(payload))
    return BuiltPayload(
        payload=payload,
        route=build_input.route,
        summary=summary,
        warnings=build_input.route.warnings,
    )
```

Extract `_apply_runtime_sampling_thinking_cache_and_headers()` from existing lines that own sampling, thinking, prompt cache, stream usage, and extra headers. It must not write `input`, `messages`, `tools`, `tool_choice`, or tool results.

- [ ] **Step 4: Route only Responses through semantic encoding**

In `LLMClient._build_payload()`:

```python
adapter = self._required_wire_adapter()
scope = invocation_scope_from_metadata(self._active_invocation_metadata())
if self.protocol_route.wire_protocol == WireProtocol.RESPONSES:
    semantic_request = project_semantic_request(
        SemanticProjectionInput(
            messages=tuple(messages or ()),
            tools=tuple(selected_tools),
            scope=scope,
            settings=_semantic_generation_settings(self.profile, stream=stream),
            tool_to_schema=_tool_to_schema,
            replay_state=self._provider_replay_state_for_scope(scope),
        )
    )
    wire_payload = _CANONICAL_WIRE_ADAPTERS.encode_request(self.protocol_route, semantic_request)
    built = compose_runtime_wire_payload(
        build_input,
        wire_payload=wire_payload,
        protocol_summary=self.protocol_route.log_summary(),
        policy_actions=policy_actions,
    )
else:
    built = build_llm_payload(build_input, ...existing callbacks...)
```

Do not introduce a feature flag. Route wire protocol is the only owner selector. If invocation metadata is unavailable, use the existing controlled synthetic scope helper, never empty identity fields.

- [ ] **Step 5: Preserve Responses envelope and cache behavior**

Add assertions for:

```python
assert payload["model"] == client.adapter.litellm_model_name()
assert payload["max_output_tokens"] == client.profile.max_output_tokens
assert payload["prompt_cache_key"]
assert payload.get("stream_options") == {"include_usage": True}
assert client._last_payload_protocol_summary["wireProtocol"] == "responses"
```

Only assert fields enabled by each fixture's profile/compat settings.

- [ ] **Step 6: Run Responses and downstream outcome tests**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_llm_client_outbound_wire_bridge.py tests/test_llm_wire_responses.py tests/test_llm_payload_builder.py tests/test_llm_payload_validator.py tests/test_llm_client_outcome_bridge.py tests/test_session_turn_journal.py -q
```

Expected: all pass. Chat legacy payload tests must remain unchanged and passing.

- [ ] **Step 7: Commit Task 3**

```powershell
git add -- core/llm/payload_builder.py core/llm/client.py core/llm/wire/responses.py tests/test_llm_client_outbound_wire_bridge.py tests/test_llm_wire_responses.py tests/test_llm_payload_builder.py tests/test_llm_payload_validator.py tests/test_llm_client_outcome_bridge.py
git commit -m "feat(llm): route Responses sends through semantic adapter"
```

Review gate: one Responses invocation calls one adapter encoder, no legacy Responses projector runs, and Chat behavior remains owned by the old builder.

---

### Task 4: Chat Completions Production Outbound Cutover

**Files:**
- Modify: `core/llm/payload_builder.py`
- Modify: `core/llm/client.py`
- Modify: `core/llm/wire/chat_completions.py`
- Test: `tests/test_llm_client_outbound_wire_bridge.py`
- Test: `tests/test_llm_wire_chat_completions.py`
- Test: `tests/test_llm_payload_builder.py`
- Test: `tests/test_llm_payload_validator.py`
- Test: `tests/test_llm_client_outcome_bridge.py`

**Interfaces:**
- Consumes: Task 1 projector, Task 2 required adapter, and Task 3 runtime envelope composer.
- Produces: Chat `_build_payload()` branch whose sole protocol body owner is `ChatCompletionsWireAdapter.encode_request()`.

- [ ] **Step 1: Write failing Chat production dispatch tests**

```python
def test_chat_client_uses_registry_encoder_once_and_keeps_provider_model_name(monkeypatch):
    client = LLMClient(config=_config(transport="chat_completions"), backend=lambda payload: payload)
    adapter = client._required_wire_adapter()
    calls = []
    original = adapter.encode_request

    def observed(request, *, route):
        calls.append(request)
        return original(request, route=route)

    monkeypatch.setattr(adapter, "encode_request", observed)
    payload = client._build_payload([{"role": "user", "content": "ping"}], stream=True)

    assert len(calls) == 1
    assert "messages" in payload and "input" not in payload
    assert payload["model"] == client.adapter.litellm_model_name()
    assert payload["api_key"] == "test-key"
```

Add fixtures for parallel tool calls, ordered tool results, image blocks, explicit ephemeral cache hint, Qwen thinking parameters, omitted tool choice, and assistant prefill rejection.

- [ ] **Step 2: Run Chat integration tests to verify RED**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_llm_client_outbound_wire_bridge.py -k "chat" -q
```

Expected: FAIL because Chat remains owned by the legacy payload builder.

- [ ] **Step 3: Teach Chat encoder safe cache hints**

When a text/image semantic part has `CacheHint(mode="ephemeral")`, emit only:

```python
{"type": "text", "text": part.text, "cache_control": {"type": "ephemeral"}}
```

Do not forward arbitrary mappings. Preserve plain string content when there is no image and no cache hint.

- [ ] **Step 4: Route Chat through the shared semantic path**

Replace the Task 3 protocol conditional with one adapter-owned path for both registered protocols:

```python
adapter = self._required_wire_adapter()
semantic_request = project_semantic_request(
    SemanticProjectionInput(
        messages=tuple(messages or ()),
        tools=tuple(selected_tools),
        scope=scope,
        settings=_semantic_generation_settings(self.profile, stream=stream),
        tool_to_schema=lambda tool: adapter_policy_tool_schema(
            self.adapter.sanitize_tool_schema(_tool_to_schema(tool)),
            route=self.protocol_route,
        ),
        replay_state=self._provider_replay_state_for_scope(scope),
    )
)
wire_payload = _CANONICAL_WIRE_ADAPTERS.encode_request(self.protocol_route, semantic_request)
built = compose_runtime_wire_payload(
    build_input,
    wire_payload=wire_payload,
    protocol_summary=self.protocol_route.log_summary(),
    policy_actions=policy_actions,
)
```

`adapter_policy_tool_schema()` is the extracted existing `_schema_for_tool_policy()` behavior. It remains a runtime policy helper and returns a semantic schema mapping; it must not emit Chat or Responses wrapper fields.

- [ ] **Step 5: Lock Chat policy parity**

Run and preserve existing assertions for:

- Qwen system-message conversion;
- Qwen/llama.cpp thinking parameters;
- empty assistant prefill removal and non-empty prefill rejection;
- reasoning roundtrip stripping when disabled;
- minimal tool schema and omitted tool choice;
- prompt cache markers;
- provider tool-chain pairing and order;
- image capability failure before provider I/O.

Add a structural summary assertion proving `payloadMessageMissingToolResultCount == 0` for parallel calls.

- [ ] **Step 6: Run full Chat/Responses payload matrix**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_llm_semantic_projector.py tests/test_llm_wire_chat_completions.py tests/test_llm_wire_responses.py tests/test_llm_client_outbound_wire_bridge.py tests/test_llm_payload_builder.py tests/test_llm_payload_validator.py tests/test_llm_client_outcome_bridge.py -q
```

Expected: all pass and every supported route uses one adapter encoder.

- [ ] **Step 7: Commit Task 4**

```powershell
git add -- core/llm/payload_builder.py core/llm/client.py core/llm/wire/chat_completions.py tests/test_llm_client_outbound_wire_bridge.py tests/test_llm_wire_chat_completions.py tests/test_llm_payload_builder.py tests/test_llm_payload_validator.py tests/test_llm_client_outcome_bridge.py
git commit -m "feat(llm): route Chat sends through semantic adapter"
```

Review gate: `message_to_openai_dict` is not called by production Chat or Responses send paths; only the Chat wire adapter emits OpenAI Chat message dictionaries.

---

### Task 5: Remove Legacy Decode Fallback And Close The Slice

**Files:**
- Modify: `core/llm/client.py`
- Modify: `core/llm/payload_builder.py`
- Modify: `core/llm/message_projector.py` only if exports become unreachable
- Test: `tests/test_llm_client_outbound_wire_bridge.py`
- Test: `tests/test_llm_client_outcome_bridge.py`
- Test: `tests/test_agent_protocol.py`
- Test: `tests/test_session_turn_journal.py`
- Test: `tests/test_llm_usage_ledger.py`

**Interfaces:**
- Consumes: both production semantic cutovers and required-adapter preflight.
- Produces: no decode-time `wire_adapter=None` branch, no legacy normalizer for known routes, and bounded adapter/outcome runtime evidence.

- [ ] **Step 1: Write failing no-fallback tests**

```python
def test_stream_never_constructs_legacy_normalizer_after_adapter_preflight(monkeypatch):
    client = LLMClient(config=_config(transport="responses"), backend=lambda payload: iter(()))

    def forbidden(*args, **kwargs):
        raise AssertionError("legacy normalizer must be unreachable")

    monkeypatch.setattr("core.llm.client.ResponsesStreamNormalizer", forbidden)
    list(client.stream_events([{"role": "user", "content": "ping"}], metadata=_metadata()))


def test_non_stream_decode_requires_canonical_adapter(monkeypatch):
    client = LLMClient(config=_config(transport="chat_completions"), backend=lambda payload: {})
    monkeypatch.setattr(client, "_required_wire_adapter", lambda: (_ for _ in ()).throw(RuntimeError("missing")))
    with pytest.raises(RuntimeError, match="missing"):
        client.invoke([{"role": "user", "content": "ping"}], metadata=_metadata())
```

Use a valid terminal fixture for the stream test so failure specifically proves legacy construction is unreachable.

- [ ] **Step 2: Run no-fallback tests to verify RED**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_llm_client_outbound_wire_bridge.py -k "legacy_normalizer or decode_requires" -q
```

Expected: at least one test fails while `_decode_canonical_response()` and `_stream_events_once()` still catch registry `LookupError`.

- [ ] **Step 3: Remove decode-time adapter fallback**

Replace optional resolution with required resolution:

```python
def _decode_canonical_response(self, response, metadata):
    from .invocation import invocation_scope_from_metadata

    adapter = self._required_wire_adapter()
    return adapter.decode_response(
        response,
        route=self.protocol_route,
        scope=invocation_scope_from_metadata(metadata),
    )
```

In stream handling, resolve `wire_adapter = self._required_wire_adapter()` and always call `wire_adapter.decode_stream(...)`. Delete the `wire_adapter is None` branch and its legacy normalizer construction.

- [ ] **Step 4: Remove unreachable outbound compatibility ownership**

Delete only helpers proven unreachable by search and tests. Keep `message_projector.py` functions still used by journal/model compatibility or test fixtures. The production invariant must be asserted by a static test:

```python
def test_client_production_payload_path_has_no_legacy_message_projector_call():
    source = inspect.getsource(LLMClient._build_payload)
    assert "message_to_openai_dict" not in source
    assert "build_llm_payload(" not in source
    assert "encode_request" in source
```

- [ ] **Step 5: Add bounded runtime-scene assertions**

Assert one lifecycle event per invocation includes only:

```python
{
    "wireProtocol": "responses",
    "adapterId": "responses",
    "routeSource": "provider_api",
    "outcomeKind": "final_answer",
    "terminalEventSeen": True,
    "toolCallCount": 0,
}
```

The assertion must reject fields named `messages`, `input`, `payload`, `prompt`, `arguments`, `apiKey`, or `replay`.

- [ ] **Step 6: Run closeout verification**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_llm_protocol_resolver.py tests/test_llm_semantic_messages.py tests/test_llm_semantic_projector.py tests/test_llm_provider_replay_state.py tests/test_llm_wire_responses.py tests/test_llm_wire_chat_completions.py tests/test_llm_client_outbound_wire_bridge.py tests/test_llm_payload_builder.py tests/test_llm_payload_validator.py tests/test_llm_client_outcome_bridge.py tests/test_session_turn_journal.py tests/test_llm_usage_ledger.py -q
& ".\.venv\Scripts\python.exe" -m pytest tests/test_agent_protocol.py -k "invoke_llm or iteration_decision or fallback_profile or tool_result" -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit Task 5**

```powershell
git add -- core/llm/client.py core/llm/payload_builder.py core/llm/message_projector.py tests/test_llm_client_outbound_wire_bridge.py tests/test_llm_client_outcome_bridge.py tests/test_agent_protocol.py tests/test_session_turn_journal.py tests/test_llm_usage_ledger.py
git commit -m "refactor(llm): remove legacy wire fallback ownership"
```

Stage only files actually changed; omit unchanged paths from `git add`.

Review gate: unsupported protocols fail before I/O; supported sends use one semantic adapter; canonical outcomes remain the only standard Agent completion input; XML fallback remains explicitly unchanged for its separate task.

---

## Final Integration And Handoff

- [ ] Run `git diff --check` and review the full base/head diff against the design.
- [ ] Run the Task 5 closeout verification on the task branch.
- [ ] Confirm no active claim overlaps the root `main` merge.
- [ ] Merge to local `main` only after all five task review gates pass.
- [ ] Rerun the Task 5 closeout verification on root `main`.
- [ ] Sync project memory under lane `agent-runtime-core` with commit IDs and verification counts.
- [ ] Release all task claims and safely remove worktree junctions before worktree cleanup.
- [ ] Use Launcher refresh because `core/llm/client.py` and runtime payload behavior changed.
- [ ] Run bounded Chat and Responses smoke calls only with currently valid credentials; classify external auth/network failures separately from protocol failures.
- [ ] Report Task 9 and XML canonicalization as remaining work, not as failures of this slice.

## Plan Self-Review

- Spec coverage: PASS. Semantic projection, preflight, runtime envelope, Responses-first cutover, Chat cutover, fallback removal, logging, validation, rollback, and protected boundaries each have an owning task.
- Placeholder scan: PASS. No unresolved implementation placeholders remain.
- Type consistency: PASS. `SemanticProjectionInput`, `project_semantic_request`, `WireAdapterRegistry.require`, `_required_wire_adapter`, and `compose_runtime_wire_payload` are defined before downstream use.
- Risk correction: PASS. Prompt-cache hints are represented as a bounded semantic type; provider-specific thinking/model/auth fields remain runtime-envelope concerns.
- Scope check: PASS. XML tool fallback, Task 9, native Anthropic/Gemini, config, journal, and React remain excluded.

## Workflow Ledger

- Current Stage: IMPLEMENTATION_PLAN_COMPLETE
- Accepted Plan: five serial tasks ending with one outbound semantic owner for Responses and Chat and no decode-time adapter fallback
- Task Graph: Task 1 -> Task 2 -> Task 3 -> Task 4 -> Task 5
- Development Mode: BDD_TDD for all tasks because shared payload/client ownership is regression-prone
- Reuse Decision: ADAPT Hermes routing invariants and OpenCode parts-to-model boundary; build Vibelution projector/envelope composition in house
- Verification Evidence: current pre-plan baseline has 63 focused backend protocol tests passing; prior frontend canonical projection has 43 focused tests and production build passing
- Unresolved Risks: valid external credentials may block runtime smoke but cannot block fixture-backed protocol verification
- Recommended Next Stage: `ccdawn-task-splitting`, then subagent-driven execution in one isolated worktree with serial claims on shared files
- Stop Condition: overlap claim on `core/llm/client.py` or `core/llm/payload_builder.py`, envelope parity failure, or scope expansion into XML/Task 9/native protocols
