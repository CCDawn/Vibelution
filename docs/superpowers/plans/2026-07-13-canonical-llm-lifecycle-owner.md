# Canonical LLM Lifecycle Single-Owner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the production Agent consume canonical LLM events and `TurnOutcome` directly, route native and legacy XML tool calls through one lifecycle, and persist each canonical conversation fact exactly once.

**Architecture:** `LLMClient` remains the provider boundary and gains a canonical non-stream API plus explicit replay-state input. `core/llm/invocation.py` becomes the only production Agent bridge, `TurnOutcomeController` decides from `TurnOutcome` rather than `AIMessage`, and XML compatibility produces canonical tool calls before the existing executor. Journal and SessionTurnItem v2 remain the persistence and public projection owners; LangChain messages remain one-way compatibility/model-history projections only.

**Tech Stack:** Python 3.12, pytest, LangChain message classes, dataclasses, JSONL conversation journal, existing Chat Completions and Responses wire adapters.

## Global Constraints

- Work in a dedicated worktree based on the latest local `main`; root `C:\Users\17533\Desktop\Vibelution` must remain on clean `main`.
- Run project-memory guard `status`, `check`, and `claim` before editing each task scope; release claims only after final memory sync.
- This plan modifies no file under `web/`, `config/`, provider discovery, operator configuration, or credential storage.
- `LLMProtocolEvent` is the process-fact owner and `TurnOutcome` is the terminal snapshot owner for each model invocation iteration.
- Active replay state is passed explicitly; production code must not recover canonical state from `AIMessage.additional_kwargs`.
- `invoke()` and `stream()` remain one-way compatibility wrappers for non-Agent callers until all consumers are inventoried.
- XML compatibility must enter the canonical tool executor and journal path; raw XML control syntax must not enter assistant history.
- Opaque replay state, raw response bookmarks, credentials, full prompts, raw provider payloads, and raw XML arguments must not enter logs or Session DTOs.
- Use PowerShell-safe commands and explicit file paths. Never stage with `git add .`.
- Each task uses compact TDD and ends in a focused commit. Do not combine tasks that share hot files into parallel edits.
- Runtime refresh is required before live acceptance. Never bypass active-work guards without the exact project confirmation phrase.
- Version impact for this implementation is `patch`; do not edit version files from task branches.

---

## File Responsibility Map

| File | Responsibility in this plan |
|---|---|
| `core/llm/client.py` | Canonical invoke outcome, canonical event stream, explicit replay input, one-way compatibility wrappers |
| `core/llm/invocation.py` | Prompt/cache context plus the production canonical Agent bridge |
| `core/llm/types.py` | Existing canonical event/outcome contracts; only add fields proven necessary by tests |
| `core/llm/provider_replay_state.py` | Existing bounded route-scoped active continuation state; no persistence |
| `core/chat/model_messages.py` | One-way canonical outcome to model-history projection |
| `core/orchestration/turn_outcome.py` | Agent lifecycle decision from `TurnOutcome`, never from `AIMessage` |
| `agent.py` | Turn policy, canonical tool execution, continuation, completion, cancellation, bounded fallback |
| `core/llm/legacy_xml_tool_decoder.py` | New isolated XML compatibility decoder that produces canonical tool calls |
| `core/chat/turn_journal.py` | Idempotent canonical event/outcome persistence |
| `core/chat/conversation_ledger.py` | Canonical model and visible projections from the journal |
| `core/web/services/session_service.py` | Canonical SessionTurnItem v2 projection with legacy-only read fallback |
| `tests/test_llm_canonical_invocation.py` | New client and invocation bridge contract tests |
| `tests/test_legacy_xml_tool_decoder.py` | New XML decoder contract tests |
| `tests/test_agent_protocol.py` | Agent decision, native/XML tool loop, history, cancellation, and fallback regression tests |
| `tests/test_session_turn_journal.py` | Canonical persistence identity/order/idempotency tests |
| `tests/test_session_codex_transcript_projection.py` | SessionTurnItem v2 precedence and legacy fallback tests |

## Dependency And Merge Order

```text
Task 1 canonical client API
  -> Task 2 invocation bridge
  -> Task 3 Agent canonical cutover
  -> Task 4 XML decoder cutover
  -> Task 5 journal/session single ownership
  -> Task 6 diagnostics and closeout
```

Tasks 1 through 5 are serialized because later tasks consume the exact interfaces created earlier. Do not implement native protocols, durable replay, or React cleanup in parallel inside this branch.

### Task 1: Canonical Client API And Explicit Replay Input

**Files:**
- Create: `tests/test_llm_canonical_invocation.py`
- Modify: `core/llm/client.py`
- Modify: `tests/test_llm_responses_replay_continuation.py`
- Test: `tests/test_llm_client_outbound_wire_bridge.py`
- Test: `tests/test_llm_wire_responses.py`

**Interfaces:**
- Consumes: existing `TurnOutcome`, `ProviderReplayState`, `InvocationScope`, `LLMClient.stream_events()`.
- Produces: `LLMClient.invoke_outcome(messages, *, tools=None, metadata=None, replay_state=None) -> TurnOutcome`.
- Produces: `LLMClient.stream_events(..., replay_state=None) -> Iterator[LLMProtocolEvent]`.
- Produces: `_build_payload(..., replay_state=None)` with Responses bookmark continuation based on explicit state rather than compatibility-message metadata.

- [ ] **Step 1: Add failing canonical invoke and explicit replay tests**

Create `tests/test_llm_canonical_invocation.py` with a local isolated Responses configuration and deterministic backend:

```python
import inspect

from core.llm.client import LLMClient
from core.llm.types import TurnOutcome
from tests.helpers.isolated_config import isolated_settings_config


def _config():
    return isolated_settings_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://relay.example.test/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.6-luna",
            "llm.profiles.primary.transport": "responses",
            "llm.profiles.primary.contract": "tool_chat",
        }
    )


def _metadata(iteration=0):
    return {
        "sessionId": "session-canonical",
        "turnId": "turn-canonical",
        "invocationId": "invocation-canonical",
        "iteration": iteration,
        "promptPurpose": "main_reply",
    }


def test_invoke_outcome_returns_canonical_terminal_snapshot():
    client = LLMClient(
        config=_config(),
        backend=lambda _payload: {
            "id": "resp-final",
            "status": "completed",
            "output": [
                {
                    "id": "answer-final",
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "final"}],
                }
            ],
        },
    )

    outcome = client.invoke_outcome(
        [{"role": "user", "content": "answer"}],
        metadata=_metadata(),
    )

    assert isinstance(outcome, TurnOutcome)
    assert outcome.kind == "final_answer"
    assert outcome.final_text == "final"
    assert outcome.terminal_event_seen is True


def test_production_replay_is_not_recovered_from_compatibility_messages():
    source = inspect.getsource(LLMClient._build_payload)
    assert "additional_kwargs" not in source
    assert "turn_outcome" not in source
```

Update `tests/test_llm_responses_replay_continuation.py` so the continuation payload passes `replay_state=outcome.replay_state` explicitly. Keep the existing assertions for `previous_response_id`, opaque reasoning replay, `function_call_output`, and safe summary redaction.

- [ ] **Step 2: Run the focused RED tests**

Run:

```powershell
py -3 -m pytest tests\test_llm_canonical_invocation.py tests\test_llm_responses_replay_continuation.py -q
```

Expected: FAIL because `LLMClient.invoke_outcome` and explicit `_build_payload(..., replay_state=...)` do not exist, and the current payload path still recovers replay state from compatibility messages.

- [ ] **Step 3: Add the canonical API and remove compatibility-message replay recovery**

In `core/llm/client.py`, make replay state an explicit payload input:

```python
def _build_payload(
    self,
    messages: List[Any],
    *,
    tools: Optional[List[Any]] = None,
    stream: bool = False,
    metadata: Optional[Dict[str, Any]] = None,
    invocation_scope: Any = None,
    replay_state: Any = None,
) -> Dict[str, Any]:
    projection_messages = list(messages or [])
    provider_messages = (
        projection_messages
        if self.protocol_route.wire_protocol == WireProtocol.RESPONSES
        else _normalize_semantic_messages_with_adapter(
            normalize_messages_for_provider(projection_messages),
            self.adapter,
        )
    )
    semantic_request = self._project_semantic_request_or_raise(
        SemanticProjectionInput(
            messages=tuple(provider_messages),
            tools=tuple(selected_tools),
            scope=invocation_scope or invocation_scope_from_metadata(metadata),
            settings=SemanticGenerationSettings(
                max_output_tokens=self.profile.max_output_tokens,
                stream=stream,
                tool_choice=(
                    "auto"
                    if self.capabilities.supports_explicit_tool_choice
                    and self.protocol_route.policy.allow_explicit_tool_choice
                    and self.protocol_route.compat.tool_choice_mode != "omit"
                    else "omit"
                ),
            ),
            tool_to_schema=lambda tool: (
                sanitize_tool_schema(self.adapter.sanitize_tool_schema(_tool_to_schema(tool)))
                if self.protocol_route.policy.tool_schema_policy == "minimal"
                or self.protocol_route.compat.strict_message_keys
                else self.adapter.sanitize_tool_schema(_tool_to_schema(tool))
            ),
            system_message_policy=self.protocol_route.policy.system_message_policy,
            allow_assistant_prefill=self.protocol_route.policy.allow_assistant_prefill,
            reasoning_roundtrip=self.protocol_route.compat.reasoning_roundtrip,
            replay_state=replay_state,
        )
    )
```

Keep the existing settings and tool-schema expressions in their current helpers; the code above fixes the ownership and parameter flow. When a Responses replay bookmark is present, locate the latest assistant anchor by canonical message role, project the assistant/tool pair for validation, then remove only that projected anchor before wire encoding. Delete `_responses_replay_context` and every read of `additional_kwargs["turn_outcome"]` from payload construction.

Add the canonical non-stream method by moving the existing provider call, decode, trace, usage-ledger, and error handling from `invoke()` into `invoke_outcome()`:

```python
def invoke_outcome(
    self,
    messages: List[Any],
    *,
    tools: Optional[List[Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    replay_state: Any = None,
) -> TurnOutcome:
    invocation_scope = invocation_scope_from_metadata(metadata)
    payload = self._build_payload(
        messages,
        tools=tools,
        stream=False,
        metadata=metadata,
        invocation_scope=invocation_scope,
        replay_state=replay_state,
    )
    response = self._invoke_backend_with_retry(
        payload,
        phase="invoke",
        event_code="llm.invoke.failed",
        message_count=len(messages or []),
        tool_count=len(tools if tools is not None else self.bound_tools),
        metadata=self._canonical_event_metadata(payload, messages, tools, metadata),
    )
    outcome = self._decode_canonical_response(
        response,
        metadata,
        invocation_scope=invocation_scope,
    )
    if not isinstance(outcome, TurnOutcome):
        raise LLMError(
            "payload_protocol_error",
            "LLM response did not produce a canonical TurnOutcome.",
            retryable=False,
            provider=self.provider.kind,
            model=self.profile.model,
        )
    self._record_canonical_usage(response, outcome, messages, metadata)
    return outcome
```

Extract `_canonical_event_metadata()` and `_record_canonical_usage()` from the existing `invoke()` body without changing their observable trace or usage-ledger fields. Convert `invoke()` into a wrapper that calls `invoke_outcome()` and projects one `AIMessage` using existing `_canonical_compatibility_text()` and `_canonical_compatibility_tool_calls()` helpers. Keep `turn_outcome` in the wrapper's `additional_kwargs` only for legacy callers; production Agent code will stop reading it in Task 3.

Add `replay_state` to `stream_events()` and pass it into `_build_payload()`. Type the method as `Generator[LLMProtocolEvent, None, TurnOutcome]`: yield canonical process events, then return the terminal `TurnOutcome` as the generator return value. Do not place the outcome in `event.provider_payload`. Keep `stream()` as a one-way compatibility wrapper over `stream_events()`; it may intentionally ignore the generator return value after projecting compatibility chunks.

- [ ] **Step 4: Run canonical client GREEN tests**

Run:

```powershell
py -3 -m pytest tests\test_llm_canonical_invocation.py tests\test_llm_responses_replay_continuation.py tests\test_llm_wire_responses.py -q
```

Expected: all selected tests PASS; continuation contains `previous_response_id`, safe replay items, and `function_call_output` without scanning compatibility metadata.

- [ ] **Step 5: Run compatibility regression tests**

Run with the real credential environment isolated from the process:

```powershell
$env:OPENAI_API_KEY = $null
$env:ANTHROPIC_API_KEY = $null
py -3 -m pytest tests\test_llm_client_outbound_wire_bridge.py tests\test_llm_protocol_resolver.py tests\test_llm_payload_validator.py -q
```

Expected: PASS. If the two known fixture assertions still resolve operator credentials, record them as a baseline isolation blocker and do not alter configuration files in this task.

- [ ] **Step 6: Commit Task 1**

```powershell
git add -- core/llm/client.py tests/test_llm_canonical_invocation.py tests/test_llm_responses_replay_continuation.py
git commit -m "refactor(llm): expose canonical invocation outcome"
```

### Task 2: Canonical Agent Invocation Bridge

**Files:**
- Modify: `core/llm/invocation.py`
- Modify: `tests/test_llm_canonical_invocation.py`

**Interfaces:**
- Consumes: `LLMClient.invoke_outcome()`, `LLMClient.stream_events()`, `LLMInvocationContext`, `ProviderReplayState`.
- Produces: `invoke_llm_outcome(...) -> TurnOutcome`.
- Produces: `run_streaming_llm_outcome(..., on_event, replay_state=None) -> TurnOutcome`.
- Preserves: `invoke_llm()` and `stream_llm()` compatibility functions for non-Agent callers.

- [ ] **Step 1: Add failing invocation-bridge tests**

Append to `tests/test_llm_canonical_invocation.py`:

```python
from core.llm.client import LLMClient
from core.llm.invocation import invoke_llm_outcome, run_streaming_llm_outcome
from core.llm.invocation_context import LLMInvocationContext
from core.llm.types import CanonicalItemIdentity, LLMProtocolEvent, TurnOutcome


def _final_outcome() -> TurnOutcome:
    return TurnOutcome.final_answer(
        identity=CanonicalItemIdentity(
            session_id="session-canonical",
            turn_id="turn-canonical",
            invocation_id="invocation-canonical",
            iteration=0,
            item_id="answer-1",
        ),
        text="final",
    )


def test_invoke_bridge_returns_outcome_and_forwards_replay_state(monkeypatch):
    client = LLMClient(config=_config())
    expected = _final_outcome()
    observed = {}

    def fake_invoke_outcome(messages, *, tools=None, metadata=None, replay_state=None):
        observed["replay_state"] = replay_state
        return expected

    monkeypatch.setattr(client, "invoke_outcome", fake_invoke_outcome)
    replay_state = object()
    outcome = invoke_llm_outcome(
        client,
        [{"role": "user", "content": "answer"}],
        context=LLMInvocationContext(prompt_purpose="main_reply"),
        metadata=_metadata(),
        replay_state=replay_state,
    )
    assert outcome.kind == "final_answer"
    assert outcome is expected
    assert observed["replay_state"] is replay_state


def test_streaming_bridge_publishes_events_and_returns_generator_outcome(monkeypatch):
    client = LLMClient(config=_config())
    expected = _final_outcome()

    def fake_stream_events(messages, *, tools=None, metadata=None, replay_state=None):
        yield LLMProtocolEvent(
            kind="answer_delta",
            sequence=0,
            session_id="session-canonical",
            turn_id="turn-canonical",
            invocation_id="invocation-canonical",
            iteration=0,
            item_id="answer-1",
            text="final",
        )
        yield LLMProtocolEvent(
            kind="turn_completed",
            sequence=1,
            session_id="session-canonical",
            turn_id="turn-canonical",
            invocation_id="invocation-canonical",
            iteration=0,
            terminal=True,
        )
        return expected

    monkeypatch.setattr(client, "stream_events", fake_stream_events)
    observed = []
    result = run_streaming_llm_outcome(
        client,
        [],
        context=LLMInvocationContext(prompt_purpose="main_reply"),
        metadata=_metadata(),
        on_event=observed.append,
    )
    assert [event.kind for event in observed] == ["answer_delta", "turn_completed"]
    assert result is expected
```

- [ ] **Step 2: Run bridge RED tests**

```powershell
py -3 -m pytest tests\test_llm_canonical_invocation.py -q
```

Expected: FAIL because the two canonical bridge functions do not exist.

- [ ] **Step 3: Implement canonical bridge functions**

Add to `core/llm/invocation.py`:

```python
from collections.abc import Callable, Iterator

from .provider_replay_state import ProviderReplayState
from .types import LLMProtocolEvent, TurnOutcome


def invoke_llm_outcome(
    client: Any,
    messages: list[Any],
    *,
    context: LLMInvocationContext,
    tools: list[Any] | None = None,
    metadata: dict[str, Any] | None = None,
    replay_state: ProviderReplayState | None = None,
) -> TurnOutcome:
    effective_context = _context_with_effective_partition(context)
    effective_metadata = _merged_metadata(effective_context, client, metadata)
    partition = str(effective_context.cache_partition or "").strip()
    scope = prompt_cache_partition_scope(partition) if partition else nullcontext()
    with scope:
        return client.invoke_outcome(
            messages,
            tools=tools,
            metadata=effective_metadata,
            replay_state=replay_state,
        )


def run_streaming_llm_outcome(
    client: Any,
    messages: list[Any],
    *,
    context: LLMInvocationContext,
    on_event: Callable[[LLMProtocolEvent], None],
    tools: list[Any] | None = None,
    metadata: dict[str, Any] | None = None,
    replay_state: ProviderReplayState | None = None,
) -> TurnOutcome:
    effective_context = _context_with_effective_partition(context)
    effective_metadata = _merged_metadata(effective_context, client, metadata)
    partition = str(effective_context.cache_partition or "").strip()
    scope = prompt_cache_partition_scope(partition) if partition else nullcontext()
    with scope:
        event_stream: Iterator[LLMProtocolEvent] = iter(
            client.stream_events(
                messages,
                tools=tools,
                metadata=effective_metadata,
                replay_state=replay_state,
            )
        )
        while True:
            try:
                on_event(next(event_stream))
            except StopIteration as completed:
                outcome = completed.value
                break
    if not isinstance(outcome, TurnOutcome) or not outcome.terminal_event_seen:
        raise ValueError("canonical LLM stream completed without TurnOutcome")
    return outcome
```

Export both functions in `__all__`. Do not change the semantics of `invoke_llm()` or `stream_llm()` in this task.

- [ ] **Step 4: Run bridge GREEN tests**

```powershell
py -3 -m pytest tests\test_llm_canonical_invocation.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```powershell
git add -- core/llm/invocation.py tests/test_llm_canonical_invocation.py
git commit -m "refactor(llm): add canonical agent invocation bridge"
```

### Task 3: Cut The Normal Agent Path Over To TurnOutcome

**Files:**
- Modify: `core/orchestration/turn_outcome.py`
- Modify: `core/chat/model_messages.py`
- Modify: `agent.py`
- Modify: `tests/test_agent_protocol.py`
- Test: `tests/test_provider_error_recovery.py`

**Interfaces:**
- Consumes: Task 2 `invoke_llm_outcome()` and `run_streaming_llm_outcome()`.
- Produces: `TurnOutcomeController.decide_llm_iteration(outcome: TurnOutcome) -> LLMIterationDecision`.
- Produces: `assistant_model_message_from_outcome(outcome: TurnOutcome) -> AIMessage`, a one-way model-history projection with no canonical back-reference.
- Produces: active Agent variable `replay_state`, assigned only from the previous canonical outcome.

- [ ] **Step 1: Convert lifecycle-decision tests to direct TurnOutcome input**

Replace compatibility-message setup in the canonical decision tests near the end of `tests/test_agent_protocol.py`:

```python
def test_iteration_decision_accepts_turn_outcome_directly():
    canonical_call = CanonicalToolCall(
        identity=CanonicalItemIdentity(
            session_id="session-1",
            turn_id="turn-1",
            invocation_id="invocation-1",
            iteration=0,
            item_id="tool-1",
        ),
        call_id="call-1",
        name="read_file_tool",
        arguments={"path": "README.md"},
    )
    outcome = TurnOutcome(
        kind="tool_calls",
        identity=canonical_call.identity,
        tool_calls=(canonical_call,),
        pending_tool_call_ids=("call-1",),
        terminal_event_seen=True,
    )

    decision = TurnOutcomeController.decide_llm_iteration(outcome)

    assert decision.outcome is outcome
    assert decision.should_execute_tools is True
    assert decision.tool_calls[0]["canonical_tool_call"] is canonical_call
```

Add a structural regression:

```python
def test_turn_outcome_controller_does_not_read_compatibility_metadata():
    source = inspect.getsource(TurnOutcomeController.decide_llm_iteration)
    assert "additional_kwargs" not in source
    assert "turn_outcome" not in source
```

- [ ] **Step 2: Run Agent decision RED tests**

```powershell
py -3 -m pytest tests\test_agent_protocol.py -q -k "iteration_decision or canonical_outcome"
```

Expected: FAIL because `decide_llm_iteration()` still expects an `AIMessage` and extracts `additional_kwargs`.

- [ ] **Step 3: Make TurnOutcomeController consume canonical outcome directly**

In `core/orchestration/turn_outcome.py`:

```python
@staticmethod
def decide_llm_iteration(outcome: LLMTurnOutcome) -> LLMIterationDecision:
    if not isinstance(outcome, LLMTurnOutcome):
        raise TypeError("LLM iteration decision requires TurnOutcome")
    if not outcome.terminal_event_seen:
        raise ValueError("canonical TurnOutcome is missing terminal evidence")
    tool_calls = tuple(
        {
            "id": call.call_id,
            "name": call.name,
            "args": dict(call.arguments),
            "canonical_tool_call": call,
        }
        for call in outcome.tool_calls
    )
    return LLMIterationDecision(
        outcome=outcome,
        tool_calls=tool_calls,
        should_execute_tools=outcome.kind == "tool_calls" and bool(tool_calls),
        should_finish=outcome.kind == "final_answer",
        should_stop_unsuccessfully=outcome.kind in {"incomplete", "failed", "cancelled"},
    )
```

- [ ] **Step 4: Add the one-way model-history projector**

In `core/chat/model_messages.py`, add:

```python
from langchain_core.messages import AIMessage

from core.llm.types import TurnOutcome


def assistant_model_message_from_outcome(outcome: TurnOutcome) -> AIMessage:
    return AIMessage(
        content=outcome.final_text if outcome.kind == "final_answer" else "",
        tool_calls=[
            {
                "id": call.call_id,
                "name": call.name,
                "args": dict(call.arguments),
                "type": "tool_call",
            }
            for call in outcome.tool_calls
        ],
    )
```

This model-history message deliberately omits `additional_kwargs["turn_outcome"]`, provider payloads, replay state, commentary, and reasoning.

Add a focused test in `tests/test_agent_protocol.py` asserting those omissions and exact tool-call identity.

- [ ] **Step 5: Cut the normal Agent invocation path over to canonical APIs**

In `agent.py`, replace production calls that expect `AIMessage`/chunks with the Task 2 bridge:

```python
replay_state = None

outcome = (
    run_streaming_llm_outcome(
        llm,
        messages,
        context=invocation_context,
        metadata=invocation_metadata,
        tools=bound_tools,
        replay_state=replay_state,
        on_event=publish_canonical_event,
    )
    if profile.streaming
    else invoke_llm_outcome(
        llm,
        messages,
        context=invocation_context,
        metadata=invocation_metadata,
        tools=bound_tools,
        replay_state=replay_state,
    )
)
decision = turn_outcome_controller.decide_llm_iteration(outcome)
replay_state = outcome.replay_state
messages.append(assistant_model_message_from_outcome(outcome))
```

Use the existing canonical event publisher and existing invocation metadata variables at the call site. Preserve the current same-route retry and distinct fallback policy. On a distinct fallback route, clear `replay_state` before the new invocation and retain the existing lineage metadata.

Replace final text reads with `outcome.final_text`, tool decisions with `decision.tool_calls`, and unsuccessful-stop handling with `decision.should_stop_unsuccessfully`. Do not delete compatibility helpers used outside the main Agent path.

- [ ] **Step 6: Run normal-path GREEN and recovery tests**

```powershell
py -3 -m pytest tests\test_agent_protocol.py -q -k "iteration_decision or canonical_outcome or round_success or tool_message"
py -3 -m pytest tests\test_provider_error_recovery.py -q
```

Expected: PASS. Same-route tool iterations retain `invocationId`, increment `iteration`, and pass replay explicitly; fallback clears incompatible replay state.

- [ ] **Step 7: Commit Task 3**

```powershell
git add -- core/orchestration/turn_outcome.py core/chat/model_messages.py agent.py tests/test_agent_protocol.py
git commit -m "refactor(agent): consume canonical turn outcomes"
```

### Task 4: Quarantine XML Tool Compatibility Behind Canonical Calls

**Files:**
- Create: `core/llm/legacy_xml_tool_decoder.py`
- Create: `tests/test_legacy_xml_tool_decoder.py`
- Modify: `agent.py`
- Modify: `tests/test_agent_protocol.py`

**Interfaces:**
- Consumes: existing accepted XML tool syntax and `CanonicalItemIdentity`, `CanonicalToolCall`, `TurnOutcome`.
- Produces: `LegacyXmlDecodeResult(matched, commentary, tool_calls, error)`.
- Produces: `decode_legacy_xml_tool_calls(text, *, scope) -> LegacyXmlDecodeResult`.
- Preserves: existing XML-dependent routes only when their resolved compatibility policy explicitly enables XML tool parsing.

- [ ] **Step 1: Characterize accepted XML forms and add decoder RED tests**

Move the existing accepted XML examples from `tests/test_agent_protocol.py` into table-driven tests in `tests/test_legacy_xml_tool_decoder.py`. Preserve each exact historical XML form. Add these contract assertions:

```python
import pytest

from core.llm.legacy_xml_tool_decoder import decode_legacy_xml_tool_calls
from core.llm.semantic_messages import InvocationScope


def _scope():
    return InvocationScope(
        session_id="session-xml",
        turn_id="turn-xml",
        invocation_id="invocation-xml",
        iteration=2,
    )


@pytest.mark.parametrize(
    ("raw_xml", "call_id", "tool_name", "arguments"),
    [
        (
            '<invoke name="read_memory_tool"><parameter name="scope">core_wisdom</parameter></invoke>',
            "xml_0",
            "read_memory_tool",
            {"scope": "core_wisdom"},
        ),
        (
            '<invoke name="hidden_tool"><parameter name="scope">x</parameter></invoke>',
            "xml_hidden",
            "hidden_tool",
            {"scope": "x"},
        ),
        (
            '<invoke name="close_evolution_transaction_tool"><parameter name="status">success</parameter></invoke>',
            "xml_1",
            "close_evolution_transaction_tool",
            {"status": "success"},
        ),
    ],
)
def test_valid_xml_becomes_canonical_tool_call(raw_xml, call_id, tool_name, arguments):
    result = decode_legacy_xml_tool_calls(raw_xml, scope=_scope())
    assert result.matched is True
    assert result.error == ""
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].identity.iteration == 2
    assert result.tool_calls[0].call_id == call_id
    assert result.tool_calls[0].name == tool_name
    assert result.tool_calls[0].arguments == arguments


def test_control_xml_is_not_returned_as_commentary():
    raw_xml = '<invoke name="read_memory_tool"><parameter name="scope">core_wisdom</parameter></invoke>'
    result = decode_legacy_xml_tool_calls(raw_xml, scope=_scope())
    assert result.commentary == ""


def test_malformed_recognized_xml_returns_bounded_error():
    raw_xml = '<invoke name="read_memory_tool"><parameter name="scope">core_wisdom</invoke>'
    result = decode_legacy_xml_tool_calls(raw_xml, scope=_scope())
    assert result.matched is True
    assert result.tool_calls == ()
    assert result.error == "tool_call_decode_error"
```

- [ ] **Step 2: Run decoder RED tests**

```powershell
py -3 -m pytest tests\test_legacy_xml_tool_decoder.py -q
```

Expected: FAIL because the decoder module does not exist.

- [ ] **Step 3: Extract the existing parser and normalize canonical output**

Create `core/llm/legacy_xml_tool_decoder.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .semantic_messages import InvocationScope
from .types import CanonicalItemIdentity, CanonicalToolCall


@dataclass(frozen=True)
class LegacyXmlDecodeResult:
    matched: bool
    commentary: str = ""
    tool_calls: tuple[CanonicalToolCall, ...] = ()
    error: str = ""


def _canonical_call(
    raw: Mapping[str, Any],
    *,
    scope: InvocationScope,
    index: int,
) -> CanonicalToolCall:
    call_id = str(raw.get("id") or f"xml_{index}").strip()
    name = str(raw.get("name") or "").strip()
    arguments = raw.get("args") if isinstance(raw.get("args"), Mapping) else {}
    return CanonicalToolCall(
        identity=CanonicalItemIdentity(
            session_id=scope.session_id,
            turn_id=scope.turn_id,
            invocation_id=scope.invocation_id,
            iteration=scope.iteration,
            item_id=call_id,
        ),
        call_id=call_id,
        name=name,
        arguments=dict(arguments),
    )


def decode_legacy_xml_tool_calls(
    text: str,
    *,
    scope: InvocationScope,
) -> LegacyXmlDecodeResult:
    matched, commentary, raw_calls, malformed = _parse_existing_xml_tool_syntax(text)
    if not matched:
        return LegacyXmlDecodeResult(matched=False, commentary=str(text or ""))
    if malformed:
        return LegacyXmlDecodeResult(matched=True, error="tool_call_decode_error")
    calls = tuple(
        _canonical_call(raw, scope=scope, index=index)
        for index, raw in enumerate(raw_calls)
    )
    if any(not call.name for call in calls):
        return LegacyXmlDecodeResult(matched=True, error="tool_call_decode_error")
    return LegacyXmlDecodeResult(
        matched=True,
        commentary=commentary,
        tool_calls=calls,
    )
```

Implement `_parse_existing_xml_tool_syntax()` by relocating the current parser body from `agent.py` without broadening accepted syntax. It returns only bounded parsed names/arguments and control-syntax-free commentary. The module must not import Agent state, tool executors, journals, config, or UI services.

- [ ] **Step 4: Run decoder GREEN tests**

```powershell
py -3 -m pytest tests\test_legacy_xml_tool_decoder.py -q
```

Expected: PASS for every historical accepted XML fixture plus malformed and non-matching cases.

- [ ] **Step 5: Replace the direct XML side loop in Agent**

At the current XML branch in `agent.py`:

```python
xml_result = decode_legacy_xml_tool_calls(
    outcome.final_text,
    scope=invocation_scope,
)
if xml_result.error:
    raise LLMError(
        "tool_call_decode_error",
        "Legacy XML tool call could not be decoded.",
        retryable=False,
        details={"payloadValidationResult": "blocked_before_tool_execution"},
    )
if xml_result.tool_calls:
    outcome = replace(
        outcome,
        kind="tool_calls",
        tool_calls=xml_result.tool_calls,
        pending_tool_call_ids=tuple(call.call_id for call in xml_result.tool_calls),
        final_text="",
    )
    decision = turn_outcome_controller.decide_llm_iteration(outcome)
```

Continue through the same canonical executor and model-history projection used by native tool calls. Delete the direct XML execute/append/continue branch. Publish only bounded decoder selection/accept/reject metadata through the existing runtime-scene logger; do not log XML text or arguments.

- [ ] **Step 6: Add unified XML/native Agent regressions**

Update the existing XML tests in `tests/test_agent_protocol.py` to assert:

```python
assert executed_call_ids == ["xml_0"]
assert journal_call_ids == ["xml_0"]
assert all("<tool" not in str(message.content).lower() for message in history_messages)
assert final_answers == ["final after tool"]
```

Add a structural test:

```python
def test_agent_has_no_direct_xml_tool_execution_loop():
    source = inspect.getsource(agent.run_agent)
    assert "decode_legacy_xml_tool_calls" in source
    assert "tool_call_decode_error" in source
```

Use the actual Agent entry function containing the tool loop when writing this structural assertion; do not inspect the entire module as a string.

- [ ] **Step 7: Run XML and Agent GREEN tests**

```powershell
py -3 -m pytest tests\test_legacy_xml_tool_decoder.py tests\test_agent_protocol.py -q -k "xml or canonical_outcome or tool_message"
```

Expected: PASS. XML calls execute once through the canonical executor, raw control XML is absent from history, and the final answer is committed once.

- [ ] **Step 8: Commit Task 4**

```powershell
git add -- core/llm/legacy_xml_tool_decoder.py agent.py tests/test_legacy_xml_tool_decoder.py tests/test_agent_protocol.py
git commit -m "refactor(agent): canonicalize legacy XML tool calls"
```

### Task 5: Enforce Canonical Journal And Session Single Ownership

**Files:**
- Modify: `core/chat/turn_journal.py`
- Modify: `core/chat/conversation_ledger.py`
- Modify: `core/web/services/session_service.py`
- Modify: `tests/test_session_turn_journal.py`
- Modify: `tests/test_conversation_ledger.py`
- Modify: `tests/test_session_codex_transcript_projection.py`

**Interfaces:**
- Consumes: Task 3/4 canonical `TurnOutcome` and protocol events.
- Preserves: `append_canonical_turn_outcome()`, `session_turn_items_from_events()`, `append_conversation_turn_outcome()`.
- Produces: one canonical write path per outcome and legacy-only read fallback when no canonical v2 items exist for a historical turn.

- [ ] **Step 1: Add failing idempotency and no-reconstruction tests**

Append to `tests/test_session_turn_journal.py`:

```python
def test_repeated_canonical_outcome_commits_one_final_item(tmp_path):
    outcome = TurnOutcome.final_answer(
        identity=CanonicalItemIdentity(
            session_id="session-1",
            turn_id="turn-1",
            invocation_id="invocation-1",
            iteration=0,
            item_id="answer-1",
        ),
        text="final",
    )
    append_canonical_turn_outcome(tmp_path, "session-1", "turn-1", outcome)
    append_canonical_turn_outcome(tmp_path, "session-1", "turn-1", outcome)

    items = session_turn_items_from_events(load_turn_events(tmp_path, "session-1"), turn_id="turn-1")
    finals = [item for item in items if item["kind"] == "assistant_message" and item["phase"] == "final_answer"]
    assert len(finals) == 1
    assert finals[0]["itemId"] == "answer-1"
```

Reuse the file's existing `CanonicalItemIdentity` and `TurnOutcome` imports; do not add a second outcome fixture layer.

Strengthen the existing `test_turn_items_projection_prefers_explicit_canonical_v2` in `tests/test_session_codex_transcript_projection.py`. Keep its existing `canonical = SessionTurnItem(...)` fixture and use the real projection entrypoint:

```python
monkeypatch.setattr(session_service, "load_conversation_events", lambda *_args, **_kwargs: [object()])
monkeypatch.setattr(
    session_service,
    "conversation_turn_items_from_events",
    lambda _events, *, turn_id="": [canonical] if turn_id == "turn-1" else [],
)
items = session_service._build_session_turn_items_projection(
    session_id="session-live",
    turn_id="turn-1",
    message_id="legacy-message",
    content="legacy text",
)
assert items == [canonical]
assert len(items) == 1
```

- [ ] **Step 2: Run journal/session RED tests**

```powershell
py -3 -m pytest tests\test_session_turn_journal.py tests\test_session_codex_transcript_projection.py -q
```

Expected: at least one new assertion FAILS by duplicate commit or legacy projection invocation.

- [ ] **Step 3: Centralize canonical idempotency in the journal writer**

In `core/chat/turn_journal.py`, keep the canonical key at the writer boundary:

```python
def _canonical_commit_key(payload: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(payload.get("invocationId") or ""),
        int(payload.get("iteration") or 0),
        str(payload.get("itemId") or ""),
        int(payload.get("revision") or 0),
        str(payload.get("kind") or ""),
        str(payload.get("callId") or ""),
    )
```

Before appending each `assistant_item_committed` event, compare this key against canonical commits already loaded for the same turn. Keep revision replacement behavior deterministic: the same identity/revision is idempotent; a higher revision is appended and projected as the winner; a lower revision never replaces a higher one.

Do not deduplicate by text equality. Do not include provider replay state in the key or payload.

- [ ] **Step 4: Remove duplicate canonical write call sites**

In `core/chat/conversation_ledger.py` and `core/web/services/session_service.py`, keep `append_conversation_turn_outcome()` as the single facade over `append_canonical_turn_outcome()`. Ensure the Agent canonical event bridge calls that facade once per invocation outcome. Remove any second write caused by compatibility `AIMessage`, assistant delta, or transcript completion.

The production flow after this step is:

```text
LLMProtocolEvent/TurnOutcome
  -> append_conversation_turn_outcome
  -> append_canonical_turn_outcome
  -> assistant_item_committed
  -> SessionTurnItem v2
```

- [ ] **Step 5: Make canonical v2 projection short-circuit legacy reconstruction**

At the existing turn-item projection point in `core/web/services/session_service.py`:

```python
canonical_items = conversation_turn_items_from_events(events, turn_id=turn_id)
if canonical_items:
    return canonical_items
return legacy_turn_items_for_historical_session(events, turn_id=turn_id)
```

Use the current existing helper names and keep the fallback read-only. New writes must not create legacy assistant deltas/transcript facts after canonical items are committed.

- [ ] **Step 6: Run journal, ledger, and session GREEN tests**

```powershell
py -3 -m pytest tests\test_session_turn_journal.py tests\test_conversation_ledger.py tests\test_session_codex_transcript_projection.py -q
```

Expected: PASS. Repeated canonical events/outcomes remain idempotent, higher revision wins, one final answer is projected, and legacy-only history remains readable.

- [ ] **Step 7: Commit Task 5**

```powershell
git add -- core/chat/turn_journal.py core/chat/conversation_ledger.py core/web/services/session_service.py tests/test_session_turn_journal.py tests/test_conversation_ledger.py tests/test_session_codex_transcript_projection.py
git commit -m "refactor(chat): enforce canonical turn persistence"
```

### Task 6: Structural Guards, Bounded Diagnostics, And Closeout

**Files:**
- Modify: `core/llm/client.py`
- Modify: `agent.py`
- Modify: `tests/test_llm_canonical_invocation.py`
- Modify: `tests/test_agent_protocol.py`
- Modify: `tests/test_session_turn_journal.py`
- Modify: `.docs/project-memory/lanes/agent-runtime-core.json` during final guarded memory sync only

**Interfaces:**
- Consumes: all prior task contracts.
- Produces: structural regression guards, safe lifecycle diagnostic events, merge evidence, runtime refresh decision.

- [ ] **Step 1: Add structural ownership guards**

Add exact source-level assertions to `tests/test_llm_canonical_invocation.py` and `tests/test_agent_protocol.py`:

```python
def test_canonical_ownership_has_no_reverse_compatibility_path():
    payload_source = inspect.getsource(LLMClient._build_payload)
    controller_source = inspect.getsource(TurnOutcomeController.decide_llm_iteration)
    assert "additional_kwargs" not in payload_source
    assert "turn_outcome" not in payload_source
    assert "additional_kwargs" not in controller_source
    assert "AIMessage" not in controller_source


def test_compatibility_methods_are_one_way_wrappers():
    invoke_source = inspect.getsource(LLMClient.invoke)
    stream_source = inspect.getsource(LLMClient.stream)
    assert "invoke_outcome(" in invoke_source
    assert "stream_events(" in stream_source


def test_streaming_bridge_does_not_recover_outcome_from_event_payload():
    bridge_source = inspect.getsource(run_streaming_llm_outcome)
    assert "provider_payload" not in bridge_source
```

Add an Agent structural assertion targeting the actual main-loop helper:

```python
assert "invoke_llm_outcome(" in main_loop_source or "run_streaming_llm_outcome(" in main_loop_source
assert "decode_legacy_xml_tool_calls(" in main_loop_source
```

- [ ] **Step 2: Add bounded diagnostic tests**

Capture calls to the existing `_publish_llm_status_event("canonical_outcome", **fields)` publisher and assert safe fields:

```python
safe_event = next(event for name, event in observed if name == "canonical_outcome")
assert safe_event["sessionId"] == "session-1"
assert safe_event["turnId"] == "turn-1"
assert safe_event["invocationId"] == "invocation-1"
assert safe_event["iteration"] == 1
assert safe_event["outcomeKind"] == "tool_calls"
assert safe_event["replayStatePresent"] is True
assert "apiKey" not in safe_event
assert "responseId" not in safe_event
assert "opaque" not in str(safe_event).lower()
assert "<tool" not in str(safe_event).lower()
```

Emit this bounded event from the canonical completion owners in `core/llm/client.py` and `agent.py`. The required safe facts are identity, route summary, event/outcome kind, replay presence/count/bytes, and XML decoder accepted/rejected state.

- [ ] **Step 3: Run the focused ownership and lifecycle suite**

```powershell
py -3 -m pytest tests\test_llm_canonical_invocation.py tests\test_llm_responses_replay_continuation.py tests\test_llm_wire_responses.py tests\test_llm_wire_chat_completions.py tests\test_llm_turn_assembler.py tests\test_agent_protocol.py tests\test_provider_error_recovery.py tests\test_legacy_xml_tool_decoder.py tests\test_session_turn_journal.py tests\test_conversation_ledger.py tests\test_session_codex_transcript_projection.py -q
```

Expected: PASS with no deselected lifecycle tests. If credential-isolation assertions fail because operator credentials override fixtures, prove the same failure on unchanged `main`, redact output, and record the blocker without modifying active config scopes.

- [ ] **Step 4: Run syntax and diff gates**

```powershell
py -3 -m py_compile core\llm\client.py core\llm\invocation.py core\llm\legacy_xml_tool_decoder.py core\orchestration\turn_outcome.py core\chat\model_messages.py core\chat\turn_journal.py core\chat\conversation_ledger.py core\web\services\session_service.py agent.py
git diff --check main...HEAD
git status --short --branch
```

Expected: Python compilation succeeds, diff check is empty, and only current-task files are modified or committed.

- [ ] **Step 5: Perform scoped code and simplification review**

Review the actual diff against the design and reject the branch if any condition is true:

```text
Agent still reads canonical outcome from AIMessage.additional_kwargs
client payload construction scans compatibility messages for replay state
native and XML tools use different execution loops
raw XML or replay state reaches journal/log/DTO
session service reconstructs canonical v2 despite canonical items being present
new provider/model/config behavior appears in the diff
compatibility wrappers are removed without a caller inventory
```

No unrelated refactor is accepted merely because a hot file is already open.

- [ ] **Step 6: Commit final diagnostics and guards**

```powershell
git add -- core/llm/client.py agent.py tests/test_llm_canonical_invocation.py tests/test_agent_protocol.py tests/test_session_turn_journal.py
git commit -m "test(llm): guard canonical lifecycle ownership"
```

- [ ] **Step 7: Integrate through project gates**

1. Rebase or merge the latest local `main` into the task branch only after path-level overlap review.
2. Rerun the focused suite only when the incoming `main` touches a task file or dependency.
3. Fast-forward or non-conflicting merge into local `main` according to `DEVELOPMENT_STANDARD.md`.
4. Acquire the project-memory claim and sync `agent-runtime-core` with commit IDs, exact test counts, baseline failures, residual risks, version impact, and Launcher decision.
5. Release every implementation and memory claim.
6. Refresh through Launcher only when active-work guards permit it.

Expected runtime acceptance after refresh:

```text
Chat: commentary -> read-only tool -> tool result -> final answer -> terminal
Responses: commentary -> read-only tool -> tool result -> final answer -> terminal
session reload: one final answer, stable call IDs, no duplicate canonical items
runtime scene: complete safe identity ordering, no credential/replay/XML payload content
```

No frontend build is required because this plan does not modify `web/`. A Launcher refresh is required before claiming runtime acceptance.

## Plan Self-Review

| Check | Result |
|---|---|
| Spec coverage | Tasks cover canonical client APIs, explicit replay, Agent direct outcome consumption, XML canonicalization, journal/session single ownership, diagnostics, rollback, and runtime acceptance |
| Scope | Durable replay persistence, React cleanup, native protocols, config, credentials, and provider discovery remain excluded |
| Type consistency | Task 1 produces `invoke_outcome`; Task 2 consumes it and produces canonical Agent bridges; Task 3 consumes those bridges; Tasks 4 and 5 consume direct `TurnOutcome` |
| Ownership | No task introduces a second event, outcome, journal, tool executor, resolver, or UI protocol |
| TDD | Every behavioral task starts with a focused failing test and names the exact GREEN command |
| Buildability | File paths, signatures, dependencies, commit order, validation commands, and stop conditions are explicit |
| Concurrency | Hot files are serialized; active config/provider/frontend scopes are excluded |
| Rollback | Additive APIs precede cutover, compatibility wrappers remain, XML and journal changes are isolated commits |

## Execution Stop Conditions

Stop without broadening the branch when any condition occurs:

1. An active claim overlaps a task file.
2. `main` advances with changes to a task file before merge and semantic conflict is unclear.
3. Canonical stream completion cannot expose one `TurnOutcome` without changing the wire adapter contract.
4. XML compatibility requires accepting a new dialect rather than preserving current behavior.
5. Session compatibility requires migrating or rewriting historical journal data.
6. Replay state must be persisted to satisfy this stage.
7. A credential/config fix is required while the active configuration claims remain open.
8. Launcher reports active work and the exact force-takeover phrase has not been freshly confirmed for this refresh.

## Completion Evidence

The implementation handoff is complete when the branch contains the ordered task commits, all focused tests and syntax/diff gates pass or have a proven unchanged-main baseline exception, project memory is current, claims are released, version impact is recorded as `patch`, and runtime acceptance is either freshly verified after Launcher refresh or explicitly marked pending with the active-work reason.
