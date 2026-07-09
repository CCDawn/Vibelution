# Chat LLM Payload Trace Implementation Plan

> **Status:** implemented  
> **Owner:** codex-chat-llm-payload-trace  
> **Claim:** claim-89bf0d10463a  
> **Branch:** codex/chat-llm-payload-trace  
> **Worktree:** `C:\Users\17533\Desktop\Vibelution-worktrees\chat-llm-payload-trace`  
> **Scope:** safe LLM payload trace builder, LLM_STATUS propagation, session detail projection, and Chat/Coding diagnostic render.  
> **Validation:** root `main` follow-up validation passed: backend focused pytest 163 passed; frontend focused Vitest 114 passed; `npm --prefix web run build` passed; py_compile passed; scoped `git diff --check` clean.  
> **Close condition:** local `main` contains safe payload trace and hardening follow-up; remaining closeout is project-memory sync and guard claim release.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe, turn-level LLM payload trace that connects session turns, model payload shape, and frontend render diagnostics without exposing raw prompt content.

**Architecture:** Build the trace at the LLM payload boundary, emit it through the existing `LLM_STATUS` event bus, store the latest matching trace in session live/detail state, and render a compact frontend diagnostic panel. The implementation reuses existing safe summaries and does not change model routing or streaming semantics.

**Tech Stack:** Python 3.12, FastAPI/TestClient, existing `core.llm` client stack, React/TypeScript, Vite/Vitest, Tailwind/HeroUI/VUI.

## Global Constraints

- Use `C:\Users\17533\Desktop\Vibelution-worktrees\chat-llm-payload-trace` on branch `codex/chat-llm-payload-trace`.
- Do not log raw prompts, user content, system prompt content, secrets, full tool output, raw provider payloads, or unbounded model output.
- Reuse unified `core.llm` invocation path and `LLMInvocationContext`.
- Keep root `C:\Users\17533\Desktop\Vibelution` on `main`; do not stage unrelated root changes.
- Backend trace changes must have focused pytest coverage.
- Frontend API/render changes must have focused Vitest coverage and `npm --prefix web run build`.

---

## File Structure

- Create `core/llm/payload_trace.py`: safe trace builder and normalizer for LLM payload facts.
- Modify `core/llm/client.py`: call the trace builder in `invoke` and `stream_events`, then publish trace through `LLM_STATUS`.
- Modify `core/web/services/session_service.py`: normalize, store, checkpoint, and expose `lastLlmPayloadTrace`.
- Modify `web/src/api/types/chat.ts`: add `SessionLlmPayloadTrace` and `lastLlmPayloadTrace`.
- Create `web/src/routes/chat/LlmPayloadTracePanel.tsx`: compact diagnostic panel.
- Modify `web/src/routes/ChatCodingRoute.tsx`: derive the latest trace and render the panel near token/core status.
- Modify `web/src/routes/ChatCodingRoute.styles.ts`: add `llmPayloadTracePanel`, `llmPayloadTraceGrid`, `llmPayloadTraceItem`, and `llmPayloadTraceMuted` classes.
- Test `tests/test_llm_payload_trace.py`: payload trace builder does not leak content.
- Test `tests/test_session_detail_contract.py`: session detail exposes latest live trace.
- Test `web/src/routes/ChatCodingRoute.layout.test.ts`: route imports/renders the trace panel.
- Test `web/src/routes/chat/LlmPayloadTracePanel.test.tsx`: component shows safe facts and omits raw content.

---

### Task 1: Safe LLM Payload Trace Builder

**Files:**
- Create: `core/llm/payload_trace.py`
- Create: `tests/test_llm_payload_trace.py`

**Interfaces:**
- Produces: `build_llm_payload_trace(*, phase: str, stream: bool, role: str, profile_id: str, provider: str, model: str, message_count: int, tool_count: int, metadata: Mapping[str, Any] | None, summaries: Iterable[Mapping[str, Any]]) -> dict[str, Any]`
- Consumes: existing safe summary dicts from `core/llm/client.py`.

- [ ] **Step 1: Write the failing trace-builder tests**

Add tests with this behavior:

```python
def test_llm_payload_trace_uses_safe_payload_facts_without_message_content():
    trace = build_llm_payload_trace(
        phase="stream",
        stream=True,
        role="primary",
        profile_id="primary",
        provider="relay",
        model="gpt-5.5",
        message_count=2,
        tool_count=1,
        metadata={
            "sessionId": "session-1",
            "llmRunId": "turn-1",
            "agentId": "agent-1",
            "llmSlot": "dialogue",
            "llmModelId": "agent-model",
            "promptPurpose": "main_reply",
            "dialogueChainMode": "responses_agent",
            "promptCachePartition": "secret-partition-text",
            "promptCachePartitionHash": "abc123",
        },
        summaries=[
            {"messageRoleCounts": {"system": 1, "user": 1}, "messageRoles": ["system", "user"]},
            {"transport": "responses", "selectedProtocol": "relay_responses", "protocolSource": "explicit_model"},
            {"inputItemCount": 2, "imageBlockCount": 0, "toolDefinitionCount": 1},
            {"promptCacheMode": "automatic", "promptCachePayloadEnabled": True},
            {"thinkingRequested": True, "thinkingType": "enabled", "thinkingDisplay": "hidden"},
        ],
    )

    assert trace["sessionId"] == "session-1"
    assert trace["turnId"] == "turn-1"
    assert trace["provider"] == "relay"
    assert trace["selectedProtocol"] == "relay_responses"
    assert trace["messageRoleCounts"] == {"system": 1, "user": 1}
    assert trace["messageRoles"] == ["system", "user"]
    assert trace["promptCache"]["promptCachePartitionHash"] == "abc123"
    serialized = json.dumps(trace, ensure_ascii=False)
    assert "secret-partition-text" not in serialized
    assert "raw prompt" not in serialized
```

- [ ] **Step 2: Run the failing test**

Run: `& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" -m pytest tests/test_llm_payload_trace.py -q`

Expected: FAIL because `core.llm.payload_trace` does not exist.

- [ ] **Step 3: Implement the trace builder**

Create `core/llm/payload_trace.py` with:

```python
from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

_CONTEXT_KEYS = {"sessionId", "llmRunId", "turnId", "agentId", "llmSlot", "llmModelId", "promptPurpose", "dialogueChainMode"}
_ROUTE_KEYS = {"transport", "selectedProtocol", "protocolSource"}
_SHAPE_KEYS = {"inputItemCount", "messagePayloadCount", "toolDefinitionCount", "imageBlockCount", "hasTools", "usesResponsesPayload"}
_CACHE_KEYS = {"promptCacheMode", "promptCacheEnabled", "promptCachePayloadEnabled", "promptCachePartitionHash", "promptCachePartitionChars", "cacheControlMessageCount"}
_THINKING_KEYS = {"thinkingRequested", "thinkingType", "thinkingDisplay"}

def _safe_dict(source: Mapping[str, Any] | None, keys: set[str]) -> dict[str, Any]:
    if not isinstance(source, Mapping):
        return {}
    result = {key: source.get(key) for key in keys if source.get(key) not in (None, "")}
    return dict(result)

def _merge_summaries(summaries: Iterable[Mapping[str, Any]] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for summary in summaries or []:
        if isinstance(summary, Mapping):
            merged.update({str(key): value for key, value in summary.items() if value not in (None, "")})
    return merged

def build_llm_payload_trace(
    *,
    phase: str,
    stream: bool,
    role: str,
    profile_id: str,
    provider: str,
    model: str,
    message_count: int,
    tool_count: int,
    metadata: Mapping[str, Any] | None,
    summaries: Iterable[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    merged = _merge_summaries(summaries)
    meta = metadata if isinstance(metadata, Mapping) else {}
    prompt_cache = _safe_dict({**merged, **meta}, _CACHE_KEYS)
    trace = {
        "schemaVersion": 1,
        "traceId": uuid4().hex[:12],
        "recordedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "phase": str(phase or "").strip(),
        "stream": bool(stream),
        "role": str(role or "").strip(),
        "profileId": str(profile_id or "").strip(),
        "provider": str(provider or "").strip(),
        "model": str(model or "").strip(),
        "sessionId": str(meta.get("sessionId") or "").strip(),
        "turnId": str(meta.get("turnId") or meta.get("llmRunId") or "").strip(),
        "agentId": str(meta.get("agentId") or "").strip(),
        "llmSlot": str(meta.get("llmSlot") or "").strip(),
        "modelId": str(meta.get("llmModelId") or "").strip(),
        "promptPurpose": str(meta.get("promptPurpose") or "").strip(),
        "dialogueChainMode": str(meta.get("dialogueChainMode") or "").strip(),
        "messageCount": max(0, int(message_count or 0)),
        "toolCount": max(0, int(tool_count or 0)),
        "messageRoleCounts": dict(merged.get("messageRoleCounts") or {}),
        "messageRoles": list(merged.get("messageRoles") or []),
        "imageBlockCount": max(0, int(merged.get("imageBlockCount") or 0)),
        "transport": str(merged.get("transport") or "").strip(),
        "selectedProtocol": str(merged.get("selectedProtocol") or "").strip(),
        "protocolSource": str(merged.get("protocolSource") or "").strip(),
        "payloadShape": _safe_dict(merged, _SHAPE_KEYS),
        "promptCache": prompt_cache,
        "thinking": _safe_dict(merged, _THINKING_KEYS),
    }
    return {key: value for key, value in trace.items() if value not in (None, "", {}, [])}
```

- [ ] **Step 4: Run the trace-builder test**

Run: `& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" -m pytest tests/test_llm_payload_trace.py -q`

Expected: PASS.

---

### Task 2: Emit Trace From LLM Client

**Files:**
- Modify: `core/llm/client.py`
- Modify: `tests/test_llm_payload_trace.py`

**Interfaces:**
- Consumes: `build_llm_payload_trace`.
- Produces: `LLM_STATUS` payloads with `status == "payload_trace"` and `llmPayloadTrace`.

- [ ] **Step 1: Add failing event emission test**

In `tests/test_llm_payload_trace.py`, subscribe to `EventNames.LLM_STATUS`, call `client.invoke(...)` with a backend that returns a minimal chat-completions response, and assert one event has `status == "payload_trace"` and contains `llmPayloadTrace.traceId`.

- [ ] **Step 2: Run the failing test**

Run: `& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" -m pytest tests/test_llm_payload_trace.py -q`

Expected: FAIL because no `payload_trace` event is emitted.

- [ ] **Step 3: Publish trace in `invoke` and `stream_events`**

Add an import:

```python
from core.llm.payload_trace import build_llm_payload_trace
```

After `event_metadata` or equivalent merged metadata is available, build:

```python
llm_payload_trace = build_llm_payload_trace(
    phase="stream",
    stream=True,
    role=self.role,
    profile_id=self.profile_id,
    provider=self.provider.kind,
    model=self.profile.model,
    message_count=message_count,
    tool_count=tool_count,
    metadata=event_metadata,
    summaries=[
        message_role_summary,
        message_order_summary,
        route_summary,
        payload_shape_summary,
        prompt_cache_design_summary,
        prompt_cache_payload_summary,
        thinking_summary,
        protocol_summary,
        capability_source_summary,
    ],
)
_publish_llm_status_event("payload_trace", traceId=llm_payload_trace.get("traceId"), llmPayloadTrace=llm_payload_trace)
```

Use `phase="invoke", stream=False` in `invoke`.

- [ ] **Step 4: Run the client event tests**

Run: `& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" -m pytest tests/test_llm_payload_trace.py tests/test_llm_client.py -q`

Expected: PASS.

---

### Task 3: Session Live State And Detail Projection

**Files:**
- Modify: `core/web/services/session_service.py`
- Modify: `tests/test_session_detail_contract.py`

**Interfaces:**
- Consumes: `LLM_STATUS` payload with `llmPayloadTrace`.
- Produces: `SessionDetail.lastLlmPayloadTrace`.

- [ ] **Step 1: Add failing session detail test**

Add a test that seeds `session-live`, calls `_set_session_llm_payload_trace_live_output("session-live", trace, turn_id="turn-trace")`, fetches `/api/sessions/session-live`, and asserts `lastLlmPayloadTrace.traceId == "trace-safe-1"` and raw prompt content is absent from serialized response.

- [ ] **Step 2: Run the failing test**

Run: `& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" -m pytest tests/test_session_detail_contract.py::test_session_detail_exposes_latest_llm_payload_trace -q`

Expected: FAIL because `_set_session_llm_payload_trace_live_output` is missing.

- [ ] **Step 3: Store and expose trace**

In `SessionLiveOutputState`, add:

```python
llm_payload_trace: dict[str, Any] | None = None
```

Add `_normalize_session_llm_payload_trace(value: Any) -> dict[str, Any] | None`, add `llmPayloadTrace` to checkpoint payload/load, add `llm_payload_trace` to `_set_session_live_output`, and expose:

```python
def _set_session_llm_payload_trace_live_output(session_id: str, trace: Any, *, turn_id: str = "") -> None:
    _set_session_live_output(session_id, turn_id=turn_id, llm_payload_trace=trace)

def _current_session_live_llm_payload_trace(session_id: str) -> dict[str, Any] | None:
    state = _load_or_get_live_output_state(session_id)
    return _normalize_session_llm_payload_trace(getattr(state, "llm_payload_trace", None)) if state else None
```

If there is no helper for loaded-or-current state, mirror `_current_session_live_context_composition`.

In `_capture_session_ui_stream.llm_status_event_proxy`, when `data["status"] == "payload_trace"` and `data["llmPayloadTrace"]` is a dict, call `_set_session_llm_payload_trace_live_output`.

In session detail construction, set:

```python
"lastLlmPayloadTrace": _current_session_live_llm_payload_trace(conversation["id"]) or _normalize_session_llm_payload_trace(conversation.get("lastLlmPayloadTrace") or conversation.get("last_llm_payload_trace")),
```

When persisting a completed turn result, store `conversation["last_llm_payload_trace"]` if the live trace exists.

- [ ] **Step 4: Run session tests**

Run: `& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" -m pytest tests/test_session_detail_contract.py tests/test_session_service.py -q`

Expected: PASS.

---

### Task 4: Frontend Types And Diagnostic Panel

**Files:**
- Modify: `web/src/api/types/chat.ts`
- Create: `web/src/routes/chat/LlmPayloadTracePanel.tsx`
- Modify: `web/src/routes/ChatCodingRoute.tsx`
- Modify: `web/src/routes/ChatCodingRoute.styles.ts`
- Modify: `web/src/routes/ChatCodingRoute.layout.test.ts`
- Create: `web/src/routes/chat/LlmPayloadTracePanel.test.tsx`

**Interfaces:**
- Consumes: `SessionDetail.lastLlmPayloadTrace`.
- Produces: compact panel rendering provider/model/protocol/role/cache/thinking facts.

- [ ] **Step 1: Add failing frontend tests**

Add a raw-source route test that expects:

```ts
expect(routeSource).toContain("LlmPayloadTracePanel");
expect(routeSource).toContain("lastLlmPayloadTrace");
```

Add component test that renders a sample trace and asserts provider/model/protocol are present while `"secret raw prompt"` is absent.

- [ ] **Step 2: Run failing frontend tests**

Run: `npm --prefix web run test -- ChatCodingRoute.layout.test.ts LlmPayloadTracePanel.test.tsx`

Expected: FAIL because panel/type do not exist.

- [ ] **Step 3: Add TypeScript type**

In `web/src/api/types/chat.ts`, add `SessionLlmPayloadTrace` before `SessionDetail` and add:

```ts
lastLlmPayloadTrace?: SessionLlmPayloadTrace | null;
```

- [ ] **Step 4: Implement panel and route render**

Create `LlmPayloadTracePanel.tsx` with props:

```ts
type LlmPayloadTracePanelProps = {
  lang: "zh" | "en";
  trace: SessionLlmPayloadTrace | null | undefined;
};
```

Return `null` when no trace exists. Render compact rows for `provider`, `model`, `selectedProtocol`, `dialogueChainMode`, `messageCount`, `toolCount`, `imageBlockCount`, `promptCache.promptCacheMode`, and `thinking.thinkingRequested`.

In `ChatCodingRoute.tsx`, import and render:

```tsx
<LlmPayloadTracePanel lang={lang} trace={detail?.lastLlmPayloadTrace} />
```

Place it immediately after `TokenCoreStatusPanel`.

Add these style keys to `ChatCodingRoute.styles.ts`:

```ts
llmPayloadTracePanel: "vui-routes-chatcodingroute llmPayloadTracePanel min-w-0",
llmPayloadTraceGrid: "vui-routes-chatcodingroute llmPayloadTraceGrid grid grid-cols-2 gap-2",
llmPayloadTraceItem: "vui-routes-chatcodingroute llmPayloadTraceItem min-w-0 rounded-md border border-[color-mix(in_srgb,var(--border-subtle)_80%,transparent)] px-2 py-1",
llmPayloadTraceMuted: "vui-routes-chatcodingroute llmPayloadTraceMuted truncate text-[var(--text-muted)]",
```

- [ ] **Step 5: Run focused frontend tests**

Run: `npm --prefix web run test -- ChatCodingRoute.layout.test.ts LlmPayloadTracePanel.test.tsx chatSessionStreamProtocol.test.ts sessionAssistantDeltaScheduler.test.ts chatStreamApplyController.test.ts`

Expected: PASS.

---

### Task 5: Full Verification, Commit, Merge, Memory

**Files:**
- No new implementation files unless tests reveal a focused fix.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: validated branch merged into local `main`.

- [ ] **Step 1: Run backend verification**

Run: `& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" -m pytest tests/test_llm_payload_trace.py tests/test_session_detail_contract.py tests/test_session_service.py tests/test_llm_client.py -q`

Expected: PASS.

- [ ] **Step 2: Run frontend verification**

Run: `npm --prefix web run test -- ChatCodingRoute.layout.test.ts LlmPayloadTracePanel.test.tsx chatSessionStreamProtocol.test.ts sessionAssistantDeltaScheduler.test.ts chatStreamApplyController.test.ts`

Expected: PASS.

- [ ] **Step 3: Run build and whitespace checks**

Run: `npm --prefix web run build`

Expected: PASS.

Run: `git diff --check`

Expected: no output.

- [ ] **Step 4: Review diff and commit**

Run: `git status --short --branch`, review `git diff`, stage only current-task files, then commit:

```powershell
git add core/llm/payload_trace.py core/llm/client.py core/web/services/session_service.py tests/test_llm_payload_trace.py tests/test_session_detail_contract.py web/src/api/types/chat.ts web/src/routes/chat/LlmPayloadTracePanel.tsx web/src/routes/chat/LlmPayloadTracePanel.test.tsx web/src/routes/ChatCodingRoute.tsx web/src/routes/ChatCodingRoute.styles.ts web/src/routes/ChatCodingRoute.layout.test.ts docs/superpowers/plans/2026-07-10-chat-llm-payload-trace.md
git commit -m "feat: expose safe chat llm payload trace"
```

- [ ] **Step 5: Merge into local main and update memory**

From root `C:\Users\17533\Desktop\Vibelution`, merge `codex/chat-llm-payload-trace` into `main` after checking root dirty files are unrelated. Update project memory lane `chat-runtime`, render memory overview, release `claim-89bf0d10463a`, and report Launcher refresh decision.
