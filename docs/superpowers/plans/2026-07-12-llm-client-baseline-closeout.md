# LLM Client Baseline Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clear the 14 selected LLM-client baseline failures while preserving the canonical semantic/wire architecture and the hard failure for unimplemented native Anthropic/Gemini protocols.

**Architecture:** Keep `LLMClient` as semantic request owner, `compose_runtime_wire_payload()` as the only runtime envelope/cache-policy owner, and `_ChatTurnAssembler` as the Chat stream normalization owner. Repair supported Chat behavior in those owners, then move obsolete Anthropic-shaped tests to the adapter or supported Chat layer that actually owns each contract.

**Tech Stack:** Python 3.12, pytest, Pydantic configuration models, canonical semantic requests, Chat Completions wire adapter, Vibelution runtime-scene summaries.

## Global Constraints

- Do not register or implement an `anthropic_messages` or Gemini native wire adapter.
- Keep unsupported native protocols failing before provider I/O with no credential or prompt leakage.
- Do not restore `build_llm_payload()` as a second production payload owner.
- Do not delete, skip, xfail, or remove selected tests from the selector.
- Do not read or modify `C:\Users\17533\Documents\Vibelution\config\config.toml`.
- Do not refresh Launcher, edit version files, merge `main`, push, or create a PR in these tasks.
- Runtime-scene fields remain bounded summaries; never log prompt text, cache content, credentials, or raw responses.

---

### Task 1: Capability-aware explicit tool choice

**Files:**
- Modify: `core/llm/client.py:1460-1470`
- Test: `tests/test_llm_client.py:313-345`

**Interfaces:**
- Consumes: `LLMClient.capabilities.supports_explicit_tool_choice`, route policy, and route compatibility.
- Produces: `SemanticGenerationSettings.tool_choice` equal to `"auto"` only when all owners allow it; otherwise `"omit"`.

- [ ] **Step 1: Preserve the failing behavior test**

Keep the existing assertions:

```python
assert payload["temperature"] == 1.0
assert "tools" in payload
assert "tool_choice" not in payload
```

- [ ] **Step 2: Run RED**

```powershell
& '.venv\Scripts\python.exe' -m pytest tests\test_llm_client.py::test_openai_gpt5_payload_sanitizes_temperature_and_tool_choice -q
```

Expected: FAIL because `tool_choice="auto"` is present.

- [ ] **Step 3: Add the capability condition**

In `LLMClient._build_payload()` use:

```python
tool_choice=(
    "auto"
    if self.capabilities.supports_explicit_tool_choice
    and self.protocol_route.policy.allow_explicit_tool_choice
    and self.protocol_route.compat.tool_choice_mode != "omit"
    else "omit"
),
```

Do not change the Chat wire encoder.

- [ ] **Step 4: Run GREEN and adjacent coverage**

```powershell
& '.venv\Scripts\python.exe' -m pytest tests\test_llm_client.py -q -k "gpt5_payload_sanitizes or deepseek_payload_omits_explicit_tool_choice"
```

Expected: selected tests pass.

- [ ] **Step 5: Commit**

```powershell
git add -- core/llm/client.py tests/test_llm_client.py
git commit -m "fix(llm): honor explicit tool choice capability"
```

---

### Task 2: Canonical prompt-cache policy

**Files:**
- Modify: `core/llm/payload_builder.py:620-720,916-1031`
- Test: `tests/test_llm_client.py:2125-2410`
- Test: `tests/test_llm_payload_builder.py`

**Interfaces:**
- Consumes: `PayloadPolicyActions`, `_apply_qwen_explicit_prompt_cache_markers()`, and `wire_payload.body["messages"]`.
- Produces: copied Chat messages with disabled markers removed or one bounded Qwen history checkpoint added.

- [ ] **Step 1: Add copy-on-write RED**

Add a payload-builder test starting with:

```python
messages = [{
    "role": "system",
    "content": [
        {"type": "text", "text": "stable", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "dynamic"},
    ],
}]
original = copy.deepcopy(messages)
```

Assert disabled mode removes all `cache_control` from the payload and leaves `messages == original`.

- [ ] **Step 2: Run the diagnosed cache failures**

```powershell
& '.venv\Scripts\python.exe' -m pytest tests\test_llm_client.py -q -k "prompt_cache_disabled_strips or adds_history_checkpoint_marker or local_qwen_disabled"
```

Expected: 3 failures before implementation.

- [ ] **Step 3: Add bounded copy helpers**

Add beside the Qwen marker helpers:

```python
def _strip_cache_control_from_content_copy(content: Any) -> Any:
    if not isinstance(content, list):
        return content
    normalized: list[Any] = []
    for block in content:
        if isinstance(block, dict):
            copied = dict(block)
            copied.pop("cache_control", None)
            normalized.append(copied)
        else:
            normalized.append(block)
    return normalized


def _strip_cache_control_from_messages_copy(
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for message in messages:
        copied = dict(message)
        copied["content"] = _strip_cache_control_from_content_copy(copied.get("content"))
        normalized.append(copied)
    return normalized
```

- [ ] **Step 4: Apply policy in `compose_runtime_wire_payload()`**

Immediately after `payload = dict(wire_payload.body)`:

```python
payload_messages = payload.get("messages")
if isinstance(payload_messages, list) and all(isinstance(item, dict) for item in payload_messages):
    normalized_messages = [dict(item) for item in payload_messages]
    if prompt_cache_mode == "disabled":
        normalized_messages = _strip_cache_control_from_messages_copy(normalized_messages)
    elif prompt_cache_mode == "explicit_cache_control":
        normalized_messages = _apply_qwen_explicit_prompt_cache_markers(
            normalized_messages, actions, marker_limit=4
        )
    payload["messages"] = normalized_messages
```

Do not modify Responses payloads without `messages`; keep unsupported rejection and automatic keys in this composer.

- [ ] **Step 5: Run GREEN**

```powershell
& '.venv\Scripts\python.exe' -m pytest tests\test_llm_client.py tests\test_llm_payload_builder.py -q -k "prompt_cache or cache_control"
```

Expected: disabled, unsupported, Qwen checkpoint, and four-marker-limit coverage pass.

- [ ] **Step 6: Commit**

```powershell
git add -- core/llm/payload_builder.py tests/test_llm_client.py tests/test_llm_payload_builder.py
git commit -m "fix(llm): restore canonical prompt cache policy"
```

---

### Task 3: Chat reasoning prefix deltas and source

**Files:**
- Modify: `core/llm/wire/chat_completions.py:230-350`
- Modify: `core/llm/client.py:1995-2010`
- Test: `tests/test_llm_wire_chat_completions.py`
- Test: `tests/test_llm_client.py:2980-3120`

**Interfaces:**
- Consumes: `ReasoningExtraction(text, source)`.
- Produces: true reasoning deltas plus bounded `diagnostic_summary["reasoningSource"]`; client preserves it in `StreamChunk.provider_payload`.

- [ ] **Step 1: Add cumulative/source RED**

Feed one Chat choice:

```python
chunks = [
    {"choices": [{"index": 0, "delta": {"reasoning": "先看"}}]},
    {"choices": [{"index": 0, "delta": {"reasoning": "先看日志"}}]},
    {"choices": [{"index": 0, "delta": {"reasoning": "先看日志再回答"}}]},
    {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
]
```

Assert reasoning texts are `['先看', '日志', '再回答']` and every source is `reasoning`. Also assert explicit `reasoning_delta` values `A`, `B` stay `A`, `B`, and a non-prefix replacement is emitted whole.

- [ ] **Step 2: Run RED**

```powershell
& '.venv\Scripts\python.exe' -m pytest tests\test_llm_wire_chat_completions.py -q
```

Expected: new cumulative/source assertions fail.

- [ ] **Step 3: Add assembler state**

Import `REASONING_DELTA_FIELD_CANDIDATES`, initialize:

```python
self.reasoning_by_choice_source: dict[tuple[int, str], str] = {}
```

Add:

```python
def _reasoning_delta(self, choice_index: int, source: str, text: str) -> str:
    leaf_source = source.rsplit(".", 1)[-1]
    if leaf_source in REASONING_DELTA_FIELD_CANDIDATES:
        return text
    key = (choice_index, source)
    previous = self.reasoning_by_choice_source.get(key, "")
    self.reasoning_by_choice_source[key] = text
    if previous and text.startswith(previous):
        return text[len(previous):]
    return text
```

Emit only non-empty normalized text and attach:

```python
diagnostic_summary={"reasoningSource": reasoning.source}
```

- [ ] **Step 4: Preserve source in the client projection**

Replace the hard-coded `canonical` source with:

```python
reasoning_source = str(event.diagnostic_summary.get("reasoningSource") or "canonical").strip()
projected = StreamChunk(
    type="reasoning_delta",
    text=event.text,
    provider_payload={"reasoning_source": reasoning_source},
)
```

- [ ] **Step 5: Run GREEN**

```powershell
& '.venv\Scripts\python.exe' -m pytest tests\test_llm_wire_chat_completions.py tests\test_llm_client.py -q -k "reasoning or reasoning_source_summary"
```

Expected: true deltas and provider source summaries pass.

- [ ] **Step 6: Commit**

```powershell
git add -- core/llm/wire/chat_completions.py core/llm/client.py tests/test_llm_wire_chat_completions.py tests/test_llm_client.py
git commit -m "fix(llm): preserve chat reasoning deltas and source"
```

---

### Task 4: Align Anthropic tests with wire ownership

**Files:**
- Create: `tests/test_llm_adapters.py`
- Modify: `tests/test_llm_client.py:347-420,1119-1205,1536-1615,2105-2145,2980-3120`
- Verify: `tests/test_llm_client_outbound_wire_bridge.py`

**Interfaces:**
- Consumes: `AnthropicAdapter.payload_sampling_parameters()` and `.payload_thinking_parameters()`.
- Produces: adapter-scoped Anthropic tests, supported-Chat integration tests, and unchanged native hard-fail coverage.

- [ ] **Step 1: Move sampling/thinking to adapter tests**

Create adapter tests that assert:

```python
assert opus_adapter.payload_sampling_parameters() == {}
assert opus_adapter.payload_thinking_parameters() == {
    "thinking": {"type": "adaptive", "display": "summarized"}
}
assert disabled_adapter.payload_thinking_parameters() == {"thinking": {"type": "disabled"}}
assert older_adapter.payload_sampling_parameters()["temperature"] == 0.2
```

Remove only the three equivalent `_build_payload()` tests. Keep configuration validation for `thinking_display` without `thinking_type`.

- [ ] **Step 2: Re-home generic client behavior to supported Chat**

For usage, cache telemetry, redaction, structured content, and reasoning tests, use:

```python
{
    "llm.providers.default.kind": "relay",
    "llm.providers.default.api_key": "test-key",
    "llm.providers.default.base_url": "https://relay.example.test/v1",
    "llm.providers.default.compat_mode": "openai",
    "llm.profiles.primary.provider_id": "default",
    "llm.profiles.primary.model": "deepseek-chat",
    "llm.profiles.primary.transport": "chat_completions",
    "llm.profiles.primary.prompt_cache.mode": "explicit_cache_control",
}
```

Keep all assertions about usage totals, cache tokens, safe counts/hashes, absence of prompt text, structured blocks, reasoning deltas, and source summaries.

- [ ] **Step 3: Verify native hard-fail**

```powershell
& '.venv\Scripts\python.exe' -m pytest tests\test_llm_client_outbound_wire_bridge.py::test_unsupported_native_adapter_fails_before_provider_io -q
```

Expected: 1 passed and backend calls stay empty.

- [ ] **Step 4: Run the client/adapters suites**

```powershell
& '.venv\Scripts\python.exe' -m pytest tests\test_llm_client.py tests\test_llm_adapters.py -q --maxfail=0
```

Expected: no failures; the diagnosed 109-test subset is fully green.

- [ ] **Step 5: Commit**

```powershell
git add -- tests/test_llm_adapters.py tests/test_llm_client.py
git commit -m "test(llm): align client coverage with wire ownership"
```

---

### Task 5: Aggregate verification and closeout

**Files:**
- Verify: `core/llm/client.py`
- Verify: `core/llm/payload_builder.py`
- Verify: `core/llm/wire/chat_completions.py`
- Verify: `tests/test_llm_client.py`
- Verify: `tests/test_llm_adapters.py`

**Interfaces:**
- Consumes: Tasks 1-4 and a claim covering every changed path.
- Produces: clean branch and a fresh claim-bound quality manifest.

- [ ] **Step 1: Run the complete LLM matrix**

```powershell
& '.venv\Scripts\python.exe' -m pytest tests\test_llm_client.py tests\test_llm_adapters.py tests\test_llm_payload_builder.py tests\test_llm_wire_chat_completions.py tests\test_llm_client_outbound_wire_bridge.py tests\test_llm_protocol_resolver.py tests\test_llm_invocation_context.py -q --maxfail=0
```

Expected: all selected tests pass without network/provider access.

- [ ] **Step 2: Re-run the command that blocked closeout**

```powershell
& '.venv\Scripts\python.exe' -m pytest tests\test_web_config_routes.py tests\test_config_panel.py tests\test_config_sync.py tests\test_public_config_model_refs.py tests\test_llm_client.py tests\test_prompt_cache_hit_optimization.py tests\test_llm_invocation_context.py -q --maxfail=0
```

Expected: previous `14 failed / 314 passed` becomes zero failed.

- [ ] **Step 3: Run hygiene**

```powershell
& '.venv\Scripts\python.exe' -m ruff check --select E9,F63,F7,F82 core/llm/client.py core/llm/payload_builder.py core/llm/wire/chat_completions.py tests/test_llm_client.py tests/test_llm_adapters.py
git diff --check
git status --short --branch
```

Expected: Ruff/diff pass and worktree is clean after commits.

- [ ] **Step 4: Run aggregate closeout**

```powershell
$guard = 'C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py'
& '.venv\Scripts\python.exe' $guard 'C:\Users\17533\Desktop\Vibelution' release --claim-id claim-b4a8e723b06a --status completed --reason 'Focused LLM baseline tasks reviewed and committed; transitioning to aggregate closeout.'
$claim = & '.venv\Scripts\python.exe' $guard 'C:\Users\17533\Desktop\Vibelution' claim --lane llm-provider-model-config-final-integration --agent codex-llm-provider-model-config --task 'Final provider config aggregate closeout' --ttl-minutes 180 --scope repo --note 'Integration-only claim after all task reviews.' --json | ConvertFrom-Json
$env:VIBELUTION_AGENT_CLAIM_ID = $claim.claim.id
& '.venv\Scripts\python.exe' scripts\local_quality_gate.py closeout --base main --claim-id $claim.claim.id
```

Expected: `outcome=passed`, `claimValid=true`, `mergePreflight=true`, and every command exits 0. Create a dedicated aggregate claim covering the cumulative branch diff; never weaken validation to fit the earlier narrow claim.

- [ ] **Step 5: Record closeout decisions**

```text
version impact: minor feature bundle; no version file edited
Launcher: required only after local-main integration for runtime/visual verification
operator migration: not performed
project memory: propose sync after successful main integration
```
