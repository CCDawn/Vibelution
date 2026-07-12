# LLM Turn Chain Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure each model route receives one identity-correct current submission while `LLMClient` owns same-route retries and `Agent` performs at most one fresh, distinct fallback route.

**Architecture:** Filter the active turn out of session history by `turnId` before seeding the Agent, then let the existing turn-message controller append the explicit current submission once. Expose a secret-free effective-route identity from `LLMClient`; replace Agent's retry loop with a two-route state machine that creates a fresh invocation ID for primary and fallback while preserving each route's native `WireAdapter` lifecycle.

**Tech Stack:** Python, pytest, Vibelution session context assembly, `SelfEvolvingAgent`, `LLMClient`, `LLMInvocationContext`, Chat/Responses `WireAdapter`, runtime-scene logging.

## Global Constraints

- Never deduplicate historical messages by text, normalized content, hash, role/content equality, or adjacency.
- The current submission is excluded from history only by exact `turnId`, then appended once from the explicit current input.
- Dynamic runtime context remains directly before the one canonical current user message.
- `LLMClient` is the only owner of retries within one effective route.
- `Agent` may use at most two effective routes: primary plus one distinct fallback.
- Primary and fallback use fresh clients/routes/adapters and different `invocationId` values while sharing the same parent turn identity.
- Chat routes remain Chat Completions; Responses routes remain Responses. Never reuse an encoded primary payload for fallback.
- Logs contain bounded IDs, counters, and reason codes only; no API keys, authorization headers, full prompts, wire bodies, or raw provider output.
- Do not modify frontend files, operator configuration, API keys, provider profiles, XML tool handling, `VERSION`, `CHANGELOG.md`, `web/package.json`, or `web/package-lock.json`.
- Do not make live Pixel/provider calls during implementation or verification.

---

## File Structure

**Production files modified:**

- `core/web/services/session_service.py`: remove the active turn from Agent seed history by exact `turnId`.
- `core/llm/client.py`: expose a stable, secret-free effective-route identity and short log ID.
- `agent.py`: generate a fresh invocation ID per route and replace same-route Agent retries with one optional fallback transition.

**Contract owners read but not modified unless a failing test proves necessary:**

- `core/orchestration/turn_outcome.py`: retains semantic ordering and explicit current-user append ownership.
- `core/llm/invocation.py`: continues merging invocation metadata and deriving `InvocationScope`.
- `core/llm/invocation_context.py`: continues carrying route invocation metadata.

**Tests modified:**

- `tests/test_web_app.py`: history filtering by turn identity and preservation of repeated historical text.
- `tests/test_agent_protocol.py`: current-input uniqueness, fresh fallback invocation, no same-route Agent retry, bounded route logs.
- `tests/test_llm_client.py`: effective-route identity and secret exclusion.
- `tests/test_llm_client_outbound_wire_bridge.py`: independent Chat/Responses encoding from the same semantic messages.

---

### Task 1: Exclude the active turn from seeded history by identity

**Files:**

- Modify: `core/web/services/session_service.py:8277`
- Modify: `core/web/services/session_service.py:13097`
- Test: `tests/test_web_app.py:306`
- Test: `tests/test_agent_protocol.py:6125`
- Reference only: `core/orchestration/turn_outcome.py:309`

**Interfaces:**

- Consumes: session message dictionaries with `metadata.turnId`, `metadata.turn_id`, `turnId`, or `turn_id`.
- Produces: `_history_messages_for_agent_seed(items, *, exclude_turn_id: str = "") -> list[dict[str, Any]]`.
- Preserves: `TurnOutcomeController.prepare_turn_messages(...) -> tuple[list, bool]` and its explicit current-user append behavior.

- [ ] **Step 1: Add failing identity-filter and repeated-text tests**

Add this focused test to `tests/test_web_app.py`:

```python
def test_history_seed_excludes_current_turn_by_identity_without_text_dedupe():
    history = session_service._history_messages_for_agent_seed(
        [
            {"role": "user", "content": "你好", "metadata": {"turnId": "turn-1"}},
            {"role": "assistant", "content": "第一轮", "metadata": {"turnId": "turn-1"}},
            {"role": "user", "content": "你好", "metadata": {"turnId": "turn-2"}},
            {"role": "assistant", "content": "第二轮", "metadata": {"turnId": "turn-2"}},
            {"role": "user", "content": "你好", "metadata": {"turnId": "turn-current"}},
        ],
        exclude_turn_id="turn-current",
    )

    assert [item["content"] for item in history if item["role"] == "user"] == ["你好", "你好"]
    assert all(
        str((item.get("metadata") or {}).get("turnId") or "") != "turn-current"
        for item in history
    )
```

Add this semantic-ordering regression to `tests/test_agent_protocol.py`:

```python
def test_prepare_turn_messages_preserves_same_text_across_distinct_turns():
    history = [
        SystemMessage(content="old system"),
        build_chat_user_message("你好"),
        AIMessage(content="第一轮"),
        build_chat_user_message("你好"),
        AIMessage(content="第二轮"),
    ]

    messages, resumed = TurnOutcomeController.prepare_turn_messages(
        system_prompt="new system",
        user_prompt="你好",
        effective_goal="你好",
        active_turn_messages=history,
        active_turn_goal="__chat_session__",
        build_system_message=agent_module.build_system_message,
        build_external_request_message=build_chat_user_message,
        allow_append_user_message=True,
    )

    user_messages = [item for item in messages if isinstance(item, dict) and item.get("role") == "user"]
    assert resumed is True
    assert len(user_messages) == 3
    assert all("你好" in str(item.get("content") or "") for item in user_messages)
    assert messages[-1] == build_chat_user_message("你好")
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_web_app.py tests/test_agent_protocol.py -k 'history_seed_excludes_current_turn_by_identity or prepare_turn_messages_preserves_same_text_across_distinct_turns' -q
```

Expected: the history test fails with `TypeError` because `exclude_turn_id` is not yet accepted; the semantic-ordering test passes and protects against later text-based deduplication.

- [ ] **Step 3: Add exact turn-identity extraction and filtering**

Add a private helper immediately before `_history_messages_for_agent_seed` in `core/web/services/session_service.py`:

```python
def _history_message_turn_id(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return str(
        metadata.get("turnId")
        or metadata.get("turn_id")
        or item.get("turnId")
        or item.get("turn_id")
        or ""
    ).strip()
```

Change the existing helper signature and insert identity filtering before its existing normalization logic:

```python
def _history_messages_for_agent_seed(
    items: Any,
    *,
    exclude_turn_id: str = "",
) -> list[dict[str, Any]]:
    excluded_turn_id = str(exclude_turn_id or "").strip()
    history: list[dict[str, Any]] = []
    for item in list(items or []):
        if excluded_turn_id and _history_message_turn_id(item) == excluded_turn_id:
            continue
        # Keep the existing role/content/tool normalization below unchanged.
```

Do not add content comparison, hash comparison, or tail-item removal.

- [ ] **Step 4: Pass the current `turn_id` at the session boundary**

Change the call near `session_service.py:13097` to:

```python
raw_history_messages = list(context.get("history_messages") or [])
seedable_history_messages = _history_messages_for_agent_seed(
    raw_history_messages,
    exclude_turn_id=turn_id,
)
```

Leave the existing conversation-ledger filter by `event.turn_id != turn_id` intact.

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run:

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_web_app.py tests/test_agent_protocol.py -k 'history_seed or prepare_turn_messages or dynamic_system_context' -q
```

Expected: all selected tests pass; two older `你好` messages remain and the active `turnId` is absent from seeded history.

- [ ] **Step 6: Commit the identity-safe history slice**

```powershell
git add -- core/web/services/session_service.py tests/test_web_app.py tests/test_agent_protocol.py
git commit -m 'fix(chat): exclude active turn from model history'
```

---

### Task 2: Expose a secret-free effective-route identity

**Files:**

- Modify: `core/llm/client.py:1793`
- Test: `tests/test_llm_client.py:3262`

**Interfaces:**

- Consumes: resolved `provider`, `profile`, `profile_id`, and `protocol_route` already owned by `LLMClient`.
- Produces: `LLMClient.effective_route_identity() -> tuple[str, ...]` for equality checks.
- Produces: `LLMClient.effective_route_id() -> str` for bounded logs.

- [ ] **Step 1: Add failing identity and secret-exclusion tests**

Add to `tests/test_llm_client.py`:

```python
def test_effective_route_identity_distinguishes_profiles_without_secrets():
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "primary-secret",
            "llm.providers.default.base_url": "https://relay.example.test/v1/",
            "llm.providers.backup.kind": "local",
            "llm.providers.backup.requires_api_key": False,
            "llm.providers.backup.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.6-luna",
            "llm.profiles.primary.transport": "responses",
            "llm.profiles.fallback_backup.provider_id": "backup",
            "llm.profiles.fallback_backup.model": "qwen-32b-awq",
            "llm.profiles.fallback_backup.transport": "chat_completions",
        }
    )
    primary = LLMClient(config=config, profile_id="primary", backend=lambda payload: payload)
    fallback = LLMClient(config=config, profile_id="fallback_backup", backend=lambda payload: payload)

    assert primary.effective_route_identity() != fallback.effective_route_identity()
    assert primary.effective_route_id() != fallback.effective_route_id()
    assert "primary-secret" not in repr(primary.effective_route_identity())
    assert "primary-secret" not in primary.effective_route_id()
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_llm_client.py -k 'effective_route_identity_distinguishes_profiles_without_secrets' -q
```

Expected: FAIL with `AttributeError: 'LLMClient' object has no attribute 'effective_route_identity'`.

- [ ] **Step 3: Implement canonical identity and bounded route ID**

Add `hashlib` to the existing imports in `core/llm/client.py`, then add these methods to `LLMClient` before `_invoke_payload_once`:

```python
def effective_route_identity(self) -> tuple[str, ...]:
    wire_protocol = str(
        getattr(getattr(self.protocol_route, "wire_protocol", None), "value", "")
        or getattr(self.protocol_route, "protocol", "")
        or ""
    ).strip()
    return (
        str(getattr(self.profile, "provider_id", "") or "").strip(),
        str(getattr(self.provider, "kind", "") or "").strip(),
        str(getattr(self.provider, "base_url", "") or "").strip().rstrip("/").lower(),
        str(self.profile_id or "").strip(),
        str(getattr(self.profile, "model", "") or "").strip(),
        wire_protocol,
        str(getattr(self.protocol_route, "adapter_id", "") or "").strip(),
    )

def effective_route_id(self) -> str:
    material = "\x1f".join(self.effective_route_identity()).encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:16]
```

Do not include API keys, headers, timeout values, prompt content, or tool definitions in the identity.

- [ ] **Step 4: Run route identity and existing retry-policy tests**

Run:

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_llm_client.py -k 'effective_route_identity or recovery_decision or retry' -q
```

Expected: all selected tests pass; existing `_invoke_backend_with_retry` behavior remains unchanged.

- [ ] **Step 5: Commit the route identity slice**

```powershell
git add -- core/llm/client.py tests/test_llm_client.py
git commit -m 'refactor(llm): expose effective route identity'
```

---

### Task 3: Replace Agent same-route retries with one fresh fallback transition

**Files:**

- Modify: `agent.py:2895`
- Modify: `agent.py:2928`
- Test: `tests/test_agent_protocol.py:422`
- Test: `tests/test_agent_protocol.py:504`

**Interfaces:**

- Consumes: `LLMClient.effective_route_identity()` and `effective_route_id()` from Task 2.
- Consumes: `plan_llm_recovery(...).fallback_profile_id` as a route-selection recommendation only.
- Produces: `_build_llm_invocation_context(prompt_purpose="main_reply", *, route_attempt=1) -> LLMInvocationContext` with a fresh `metadata.invocationId`.
- Produces: at most two route executions and bounded `llm_route_attempt_*` / `llm_fallback_selected` scene events.

- [ ] **Step 1: Add failing fresh-fallback and no-same-route-retry tests**

Extend the existing fallback tests in `tests/test_agent_protocol.py` with a route-aware fake:

```python
def test_invoke_llm_uses_fresh_invocation_for_one_distinct_fallback(monkeypatch):
    calls = []
    events = []

    class RouteLLM:
        def __init__(self, profile_id, route_identity, result=None):
            self.profile_id = profile_id
            self._route_identity = route_identity
            self._result = result

        def effective_route_identity(self):
            return self._route_identity

        def effective_route_id(self):
            return self.profile_id

        def invoke(self, _messages, **kwargs):
            calls.append((self.profile_id, kwargs["metadata"]["invocationId"]))
            if self._result is None:
                raise LLMError(
                    "server_error",
                    "primary exhausted",
                    retryable=True,
                    details={"attempt": 3, "max_attempts": 3, "retry_budget_exhausted": True},
                )
            return AIMessage(content=self._result)

    class DummyThinking:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class DummyUI:
        def thinking(self, *_args, **_kwargs):
            return DummyThinking()

        def add_log(self, *_args, **_kwargs):
            return None

    primary = RouteLLM("primary", ("relay", "responses", "gpt-5.6-luna"))
    fallback = RouteLLM("fallback_backup", ("local", "chat", "qwen-32b"), result="fallback ok")
    agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
    agent.llm_with_tools = primary
    agent._base_llm = primary
    agent.config = SimpleNamespace(
        llm=SimpleNamespace(
            model_name="gpt-5.6-luna",
            provider="relay",
            api_base="https://relay.example.test/v1",
            api_timeout=30,
        )
    )
    agent.mode_policy = ModePolicy(
        mode=AgentMode.CHAT,
        orchestrator_kind="chat",
        keep_multi_turn_context=True,
        allow_auto_loop=False,
        capture_chat_dataset_candidates=False,
        reset_context_before_turn=False,
        reset_context_between_cases=False,
        allow_direct_supervised_payload=False,
        finish_after_direct_response=False,
        runtime_input_builder=build_chat_user_message,
    )
    agent.runtime_agent_binding = {}
    agent._pending_supervised_case_id = ""
    agent._should_stream_llm_for_turn = lambda *_args, **_kwargs: False
    agent._get_llm_for_current_mode = lambda **kwargs: (
        fallback if kwargs.get("profile_id") == "fallback_backup" else primary
    )
    monkeypatch.setattr(agent_module, "get_ui", lambda: DummyUI())
    monkeypatch.setattr(agent_module.logger, "log_error", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        agent_module,
        "plan_llm_recovery",
        lambda *_args, **_kwargs: SimpleNamespace(
            category="server_error",
            retryable=True,
            action="retry_with_backoff",
            user_message="provider 服务异常",
            wait_seconds=0,
            stop_current_turn=True,
            disable_streaming=False,
            disable_tools=False,
            request_context_compression=False,
            fallback_profile_id="fallback_backup",
        ),
    )
    monkeypatch.setattr(
        agent_module,
        "_record_agent_scene_event",
        lambda phase, code, **kwargs: events.append((phase, code, kwargs.get("fields") or {})),
    )

    result = agent._invoke_llm([AIMessage(content="hello")])

    assert result.content == "fallback ok"
    assert [profile for profile, _ in calls] == ["primary", "fallback_backup"]
    assert calls[0][1] != calls[1][1]
    assert [code for _, code, _ in events].count("llm_fallback_selected") == 1
```

Replace the old expectation that an exhausted streaming route is retried without streaming. Keep that test's existing streaming fake and recovery fixture, rename the test, set `fallback_profile_id=None`, and replace its final assertions with:

```python
def test_invoke_llm_does_not_retry_exhausted_stream_route_without_fallback(monkeypatch):
    result = agent._invoke_llm([AIMessage(content="hello")])

    assert result is None
    assert stream_calls == ["primary"]
    assert invoke_calls == []
```

Add a duplicate-route guard test where the fallback profile resolves to the same `effective_route_identity()` and assert the provider is called once.

- [ ] **Step 2: Run the Agent recovery tests and verify RED**

Run:

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_agent_protocol.py -k 'fresh_invocation_for_one_distinct_fallback or does_not_retry_exhausted_stream_route or rejects_duplicate_fallback_route' -q
```

Expected: the fresh-invocation assertion fails because one invocation context is currently reused; the stream test fails because Agent currently performs a same-route nonstream retry.

- [ ] **Step 3: Generate one fresh invocation ID per effective route**

Import `uuid4` from `uuid` in `agent.py`. Change the context builder signature and metadata:

```python
def _build_llm_invocation_context(
    self,
    *,
    prompt_purpose: str = "main_reply",
    route_attempt: int = 1,
) -> LLMInvocationContext:
    return LLMInvocationContext(
        surface=surface,
        run_kind=run_kind,
        run_id=str(runtime.get("runId") or getattr(self, "_pending_supervised_case_id", "") or "").strip(),
        session_id=str(runtime.get("sessionId") or binding.get("directSessionId") or "").strip(),
        agent_id=str(runtime.get("agentId") or binding.get("agentId") or "").strip(),
        llm_slot=str(runtime.get("llmSlot") or binding.get("llmSlot") or "dialogue").strip() or "dialogue",
        model_id=str(runtime.get("modelId") or os.environ.get("VIBELUTION_AGENT_LLM_MODEL_ID") or "").strip(),
        cache_scope=str(runtime.get("cacheScope") or "").strip(),
        cache_partition=str(runtime.get("promptCachePartition") or "").strip(),
        prompt_purpose=prompt_purpose,
        conversation_bound=surface == "chat_turn",
        metadata={
            "agentMode": mode_value,
            "orchestratorKind": orchestrator_kind,
            "invocationId": uuid4().hex,
            "routeAttempt": max(1, int(route_attempt)),
        },
    )
```

Keep `run_id` as the parent turn/run identity. `invocation_scope_from_metadata` already gives explicit `invocationId` precedence over `llmRunId`, so no change is required in `core/llm/invocation.py` or `core/llm/invocation_context.py`.

- [ ] **Step 4: Convert `_invoke_llm` into a two-route state machine**

Keep the current stream decoding and nonstream response handling inside each route attempt. Replace the declarations and route-selection block at the start of the existing `with ui.thinking(...)` scope with:

```python
route_attempt = 0
fallback_client_for_retry = None
attempted_routes: set[tuple[str, ...]] = set()

while route_attempt < 2:
    route_attempt += 1
    llm_for_turn = fallback_client_for_retry or self._get_llm_for_current_mode(
        disable_tools=bool(getattr(self, "_force_disable_tools_for_turn", False)),
        profile_id=None,
    )
    fallback_client_for_retry = None
    route_identity = llm_for_turn.effective_route_identity()
    if route_identity in attempted_routes:
        return None
    attempted_routes.add(route_identity)
    invocation_context = self._build_llm_invocation_context(
        prompt_purpose="main_reply",
        route_attempt=route_attempt,
    )
    _record_agent_scene_event(
        "llm_route",
        "llm_route_attempt_started",
        message="LLM effective route attempt started.",
        fields={
            "routeAttempt": route_attempt,
            "routeId": llm_for_turn.effective_route_id(),
            "profileId": str(getattr(llm_for_turn, "profile_id", "") or ""),
            "invocationId": str(invocation_context.metadata.get("invocationId") or ""),
        },
    )
```

Leave the existing stream/nonstream branch directly after this block. In its exception handler, after computing `recovery` and updating `_last_llm_error_*`, replace all same-route retry selection with this exact fallback transition:

```python
fallback_profile_id = str(recovery.fallback_profile_id or "").strip()
if route_attempt == 1 and recovery.retryable and fallback_profile_id:
    candidate = self._get_llm_for_current_mode(profile_id=fallback_profile_id)
    if candidate.effective_route_identity() not in attempted_routes:
        fallback_client_for_retry = candidate
        _record_agent_scene_event(
            "llm_route",
            "llm_fallback_selected",
            message="Distinct LLM fallback route selected.",
            fields={
                "routeAttempt": 2,
                "primaryRouteId": llm_for_turn.effective_route_id(),
                "fallbackRouteId": candidate.effective_route_id(),
                "reasonCode": str(recovery.category or "provider_error"),
            },
            level="warning",
            outcome="fallback_selected",
        )

if recovery.request_context_compression:
    request_compression(f"LLM provider reported context limit: {recovery.category}")
    return None
if fallback_client_for_retry is None:
    return None
continue
```

Concrete deletion requirements:

- remove Agent-owned `disable_streaming_for_retry` and `retry_provider_failure_without_streaming` transitions;
- remove Agent backoff/sleep for provider retries;
- remove same-route retries caused by `recovery.disable_tools` or `recovery.disable_streaming`;
- retain context-compression terminal handling, cancellation handling, safe user-facing errors, and `_last_llm_error_*` updates;
- retain the fallback profile's own configured streaming/tool behavior;
- publish one exhausted/terminal event when no distinct fallback is selected or fallback fails.

- [ ] **Step 5: Run Agent recovery tests and verify GREEN**

Run:

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_agent_protocol.py -k 'invoke_llm or invocation_context' -q
```

Expected: primary is called once per Agent route, fallback is called at most once, invocation IDs differ, no same-route nonstream retry occurs, and one terminal result is produced.

- [ ] **Step 6: Commit the Agent route-transition slice**

```powershell
git add -- agent.py tests/test_agent_protocol.py
git commit -m 'fix(agent): allow one fresh fallback route'
```

---

### Task 4: Lock native protocol isolation and run focused regression

**Files:**

- Test: `tests/test_llm_client_outbound_wire_bridge.py:59`
- Test: `tests/test_agent_protocol.py:5792`

**Interfaces:**

- Consumes: canonical semantic messages plus explicit `invocationId` metadata.
- Proves: Responses and Chat clients encode independently and never share an encoded payload or invocation scope.

- [ ] **Step 1: Add a cross-route protocol-isolation regression**

Add to `tests/test_llm_client_outbound_wire_bridge.py`:

```python
def test_distinct_protocol_clients_reencode_semantic_input_with_fresh_scopes(monkeypatch):
    semantic_messages = [{"role": "user", "content": "ping"}]
    responses_client = LLMClient(
        config=_config(transport="responses"),
        backend=lambda payload: payload,
    )
    chat_client = LLMClient(
        config=_config(transport="chat_completions"),
        backend=lambda payload: payload,
    )
    scopes = []
    for label, client in (("responses", responses_client), ("chat", chat_client)):
        adapter = client._required_wire_adapter()
        original = adapter.encode_request

        def observed(request, *, route, _label=label, _original=original):
            scopes.append((_label, request.scope.invocation_id))
            return _original(request, route=route)

        monkeypatch.setattr(adapter, "encode_request", observed)

    responses_payload = responses_client._build_payload(
        semantic_messages,
        stream=False,
        metadata={**_metadata(), "invocationId": "invocation-primary"},
    )
    chat_payload = chat_client._build_payload(
        semantic_messages,
        stream=False,
        metadata={**_metadata(), "invocationId": "invocation-fallback"},
    )

    assert "input" in responses_payload and "messages" not in responses_payload
    assert "messages" in chat_payload and "input" not in chat_payload
    assert responses_payload is not chat_payload
    assert responses_payload["input"] is not chat_payload["messages"]
    assert scopes == [
        ("responses", "invocation-primary"),
        ("chat", "invocation-fallback"),
    ]
```

- [ ] **Step 2: Run the complete focused chain suite**

Run:

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_web_app.py tests/test_agent_protocol.py tests/test_llm_client.py tests/test_llm_client_outbound_wire_bridge.py -q
```

Expected: PASS. No test performs external provider I/O.

- [ ] **Step 3: Run bounded protocol regression tests**

Run:

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_llm_client_outbound_wire_bridge.py tests/test_llm_protocol_routes.py tests/test_llm_semantic_messages.py -q
```

Expected: PASS. Responses continues to emit `input`; Chat continues to emit `messages`; unsupported native adapters still fail before provider I/O.

- [ ] **Step 4: Commit the protocol-isolation regression**

```powershell
git add -- tests/test_llm_client_outbound_wire_bridge.py
git commit -m 'test(llm): lock fallback protocol isolation'
```

- [ ] **Step 5: Complete closeout gates**

Record these explicit judgments in the completion summary:

```text
runtime behavior: changed
version impact: patch-level; version files unchanged
frontend impact: none
operator config impact: none
secret impact: none
external provider probe: intentionally skipped
Launcher refresh: required before user-visible runtime verification
project memory: sync after merge evidence is available
```

Acquire the project-memory writer claim before syncing `.docs/project-memory/`; release both `llm-turn-chain-recovery` claims after merge or an explicit handoff.

---

## Acceptance Evidence Map

| Requirement | Evidence |
| --- | --- |
| Current submission appears once | `test_history_seed_excludes_current_turn_by_identity_without_text_dedupe` plus existing append contract |
| Repeated historical text remains | `test_prepare_turn_messages_preserves_same_text_across_distinct_turns` |
| Dynamic context precedes current user | existing `test_dynamic_system_context_is_after_history_and_not_carried_over` |
| Same-route retries remain client-owned | existing client retry tests plus new no-Agent-retry test |
| At most one distinct fallback | fresh-fallback and duplicate-route tests |
| Fresh fallback invocation | captured `invocationId` values differ |
| Native protocol lifecycle preserved | cross-route protocol-isolation and existing outbound bridge tests |
| Bounded safe logs | captured route events contain IDs/counters/reason codes only |
| One canonical terminal result | fallback-failure Agent test and existing TurnOutcome projection tests |

## Execution Notes

- Implement Tasks 1 and 2 independently; both must be green before Task 3.
- Task 3 is the only high-risk runtime edit and should receive a focused review before Task 4.
- Do not refresh Launcher until all focused tests pass and the user authorizes runtime verification.
- Do not use the Pixel endpoint as a success gate; its observed `502 upstream_error` is external to this implementation.
