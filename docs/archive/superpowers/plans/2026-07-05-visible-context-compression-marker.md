# Visible Context Compression Marker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show Codex-style centered context-compression markers in conversation timelines without treating them as assistant chat messages.

**Architecture:** Keep conversation ledger as the durable source. Backend visible projection converts compression ledger events into `metadata.kind="context_compression_marker"` messages, while model projection continues to use checkpoint summaries only. Frontend AgentThread recognizes that metadata and renders a centered timeline divider instead of the normal user/assistant message shell.

**Tech Stack:** Python conversation ledger and pytest; React/TypeScript AgentThread components and Vitest; existing Tailwind scanned style maps; existing runtime-scene logging and session ledger cache.

**Status:** active-plan

**Owner:** codex-visible-context-compression-marker

**Claim:** `claim-573ca2d08e8a`

**Branch:** `codex/visible-context-compression-marker`

**Worktree:** `C:\Users\17533\Desktop\Vibelution-worktrees\visible-context-compression-marker`

**Scope:** `agent.py`, `core/chat/**`, conversation session projection surfaces, `web/src/agent-thread/**`, conversation timeline projection tests, and focused backend/frontend validation.

**Supersedes:** none

**Implementation Link:** pending implementation branch commits

**Validation:** plan self-review, red-flag scan, conditional wording scan, `git diff --check`

**Close Condition:** implementation produces centered visible compression markers, preserves model checkpoint projection, records skipped/failed attempts without covering history, passes focused backend/frontend tests and web build, and records Launcher refresh decision.

## Global Constraints

- Adopt Codex-style centered timeline divider presentation.
- Compression marker is not an assistant bubble, not left/right aligned, and not ordinary conversation semantics.
- Reuse conversation ledger and context compression checkpoint; do not create a parallel history store.
- Model context uses checkpoint projection; raw ledger remains append-only for audit and recovery.
- Automatic threshold compression, tool-requested compression, and provider context-length reactive compression use one marker schema.
- Do not change GPT context-window config; `40000` token limit and `80%` standard threshold are already handled.
- Do not delete, truncate, or rewrite raw conversation ledger history.
- Do not put compression summary in ordinary chat `content`.
- Any implementation work must first acquire fresh guard claims for hot files in `agent-runtime-core` and `chat-coding-surface`.

---

## File Structure

**Backend projection**

- Modify `core/chat/turn_journal.py`: replace `_checkpoint_message_from_event()` assistant text with a marker payload helper.
- Modify `core/chat/context_compression_ledger.py`: add a durable non-covering `context_compression_attempt` event for skipped low-savings and failed preserved attempts.
- Modify `core/chat/conversation_ledger.py`: export any new event/helper needed by tests and tools.
- Modify `agent.py`: ensure low-savings and failed ledger write paths emit bounded ledger/runtime evidence where required.

**Frontend projection and rendering**

- Keep `web/src/api/types.ts` unchanged for `ConversationMessage.role`; this implementation keeps the DTO role stable and relies on `metadata.kind`.
- Modify `web/src/agent-thread/types.ts`: add `AgentCompressionMarkerMetadata` and a marker discriminator on `AgentMessage.metadata`; do not import API DTO types here.
- Modify `web/src/agent-thread/adapters.ts`: identify `metadata.kind === "context_compression_marker"` and produce an AgentMessage that the view can render as a marker.
- Modify `web/src/agent-thread/AgentThreadView.tsx`: branch marker messages to a centered timeline divider.
- Modify `web/src/agent-thread/AgentThreadView.styles.ts`: add centered marker classes.

**Tests**

- Modify `tests/test_conversation_ledger.py`: visible marker projection and model projection exclusion.
- Modify `tests/test_session_context_pipeline.py`: current-turn protection and checkpoint summary behavior remain intact.
- Modify `tests/test_agent_protocol.py`: add low-savings and failure durable event behavior coverage when Agent-level compression tests are already in this file.
- Modify `tests/test_web_runtime_routes.py`: runtime summary continues to prefer ledger compression projection.
- Modify `web/src/agent-thread/agentThreadAdapters.test.ts`: metadata marker maps without assistant text parts.
- Modify `web/src/agent-thread/AgentThreadView.test.tsx`: centered marker render, no role header, no assistant bubble.

## Task 1: Backend Marker Projection For Successful Checkpoints

**Files:**
- Modify: `core/chat/turn_journal.py`
- Modify: `tests/test_conversation_ledger.py`

**Interfaces:**
- Consumes: existing `EVENT_COMPACTION_CHECKPOINT`, `TurnJournalEvent`, `append_context_compression_checkpoint()`, `conversation_visible_messages_from_events()`, `conversation_model_messages_from_events()`.
- Produces: visible message metadata with `kind: "context_compression_marker"` and `status: "applied"`.

- [ ] **Step 1: Add failing visible projection test**

Add this test near `test_conversation_ledger_checkpoint_replaces_covered_history_for_model` in `tests/test_conversation_ledger.py`:

```python
def test_conversation_ledger_projects_compression_checkpoint_as_visible_marker(tmp_path):
    append_conversation_event(
        tmp_path,
        "session-marker",
        "turn-old",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "旧请求会被 checkpoint 覆盖"},
    )
    event = append_context_compression_checkpoint(
        tmp_path,
        "session-marker",
        turn_id="turn-checkpoint",
        current_turn_id="turn-current",
        summary="旧阶段已经压缩成摘要。",
        level="standard",
        reason="context_pressure",
        before_tokens=10000,
        after_tokens=4200,
        iteration=2,
        trigger_source="automatic_threshold",
        effectiveness_threshold=0.0,
        effectiveness_ratio=0.58,
        effective=True,
        source_message_count=1,
    )

    projection = project_conversation_ledger(
        load_conversation_events(tmp_path, "session-marker"),
        include_model_messages=True,
        include_visible_messages=True,
    )

    assert event is not None
    marker = next(
        message
        for message in projection.visible_messages
        if message.get("metadata", {}).get("kind") == "context_compression_marker"
    )
    assert marker["content"] == ""
    assert marker["metadata"]["status"] == "applied"
    assert marker["metadata"]["title"] == "上下文已压缩"
    assert marker["metadata"]["level"] == "standard"
    assert marker["metadata"]["beforeTokens"] == 10000
    assert marker["metadata"]["afterTokens"] == 4200
    assert marker["metadata"]["savedTokens"] == 5800
    assert marker["metadata"]["summaryAvailable"] is True
    assert "旧阶段已经压缩成摘要" in marker["metadata"]["summaryPreview"]
    assert "历史检查点" not in "\n".join(
        str(message.get("content") or "") for message in projection.visible_messages
    )
```

- [ ] **Step 2: Add failing model exclusion test**

Add this test in the same file:

```python
def test_context_compression_marker_metadata_does_not_enter_model_messages(tmp_path):
    append_conversation_event(
        tmp_path,
        "session-model-marker",
        "turn-old",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "旧上下文明细"},
    )
    append_context_compression_checkpoint(
        tmp_path,
        "session-model-marker",
        turn_id="turn-checkpoint",
        current_turn_id="turn-current",
        summary="旧上下文 summary for model only。",
        level="standard",
        reason="context_pressure",
        before_tokens=9000,
        after_tokens=3000,
        trigger_source="automatic_threshold",
    )

    messages = conversation_model_messages_from_events(
        load_conversation_events(tmp_path, "session-model-marker")
    )
    serialized = json.dumps(messages, ensure_ascii=False)

    assert "旧上下文 summary for model only" in serialized
    assert "context_compression_marker" not in serialized
    assert "上下文已压缩" not in serialized
    assert "历史检查点" not in serialized
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```powershell
& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" -m pytest tests/test_conversation_ledger.py -q
```

Expected: the new visible marker test fails because current projection has `role="assistant"` and content starting with `历史检查点：`.

- [ ] **Step 4: Implement marker helper**

In `core/chat/turn_journal.py`, replace `_checkpoint_message_from_event()` with this behavior:

```python
def _checkpoint_message_from_event(event: TurnJournalEvent) -> dict[str, Any]:
    payload = dict(event.payload or {})
    metadata = _context_compression_marker_metadata(event, payload)
    if not metadata:
        return {}
    return {
        "role": "assistant",
        "content": "",
        "timestamp": event.timestamp,
        "metadata": metadata,
    }


def _context_compression_marker_metadata(
    event: TurnJournalEvent,
    payload: dict[str, Any],
) -> dict[str, Any]:
    summary = str(payload.get("summary") or payload.get("content") or "").strip()
    summary_written = bool(payload.get("summaryWritten", bool(summary)))
    effective = bool(payload.get("effective", True))
    status = "applied" if effective and summary_written else "skipped_low_savings"
    title = "上下文已压缩" if status == "applied" else "压缩未应用 · 收益不足"
    before_tokens = _safe_int(payload.get("beforeTokens"))
    after_tokens = _safe_int(payload.get("afterTokens"))
    saved_tokens = _safe_int(payload.get("savedTokens"))
    if saved_tokens <= 0 and before_tokens > after_tokens:
        saved_tokens = before_tokens - after_tokens
    trigger_source = str(payload.get("triggerSource") or "").strip()
    level = str(payload.get("level") or "").strip()
    detail_parts = [
        level,
        f"节省 {saved_tokens:,} tokens" if saved_tokens > 0 else "",
        _context_compression_trigger_label(trigger_source),
    ]
    metadata = {
        "kind": "context_compression_marker",
        "turnId": event.turn_id,
        "eventId": event.event_id,
        "status": status,
        "title": title,
        "detail": " · ".join(part for part in detail_parts if part),
        "level": level,
        "triggerSource": trigger_source,
        "beforeTokens": before_tokens,
        "afterTokens": after_tokens,
        "savedTokens": max(0, saved_tokens),
        "effectivenessRatio": _safe_float(payload.get("effectivenessRatio")),
        "effectivenessThreshold": _safe_float(payload.get("effectivenessThreshold")),
        "summaryHash": str(payload.get("summaryHash") or "").strip(),
        "summaryAvailable": bool(summary),
        "summaryPreview": summary[:1200],
        "schema": "context_compression_marker.v1",
    }
    if "sourceMessageCount" in payload:
        metadata["sourceMessageCount"] = _safe_int(payload.get("sourceMessageCount"))
    if "coveredEventSeqStart" in payload:
        metadata["coveredEventSeqStart"] = _safe_int(payload.get("coveredEventSeqStart"))
    if "coveredEventSeqEnd" in payload:
        metadata["coveredEventSeqEnd"] = _safe_int(payload.get("coveredEventSeqEnd"))
    return metadata


def _context_compression_trigger_label(value: str) -> str:
    normalized = str(value or "").strip().lower()
    labels = {
        "automatic_threshold": "自动阈值",
        "auto": "自动阈值",
        "tool_request": "工具请求",
        "provider_context_length": "上下文长度恢复",
        "context_length_error": "上下文长度恢复",
    }
    return labels.get(normalized, normalized)


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
```

Keep `role="assistant"` for DTO compatibility in this task. The frontend task will render by `metadata.kind`.

- [ ] **Step 5: Run backend tests**

Run:

```powershell
& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" -m pytest tests/test_conversation_ledger.py tests/test_session_context_pipeline.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add -- core/chat/turn_journal.py tests/test_conversation_ledger.py
git commit -m "feat(chat): project compression checkpoints as markers"
```

## Task 2: Durable Low-Savings And Failure Compression Markers

**Files:**
- Modify: `core/chat/context_compression_ledger.py`
- Modify: `core/chat/conversation_ledger.py`
- Modify: `agent.py`
- Modify: `tests/test_conversation_ledger.py`
- Modify: `tests/test_agent_protocol.py`

**Interfaces:**
- Consumes: marker metadata helper from Task 1.
- Produces: `append_context_compression_attempt()` for non-covering `skipped_low_savings` and `failed_preserved` markers.

- [ ] **Step 1: Add failing ledger test for low-savings attempt**

Add this test to `tests/test_conversation_ledger.py`:

```python
def test_context_compression_low_savings_marker_does_not_cover_history(tmp_path):
    append_conversation_event(
        tmp_path,
        "session-low-savings",
        "turn-old",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "低收益时仍保留的旧上下文"},
    )
    from core.chat.conversation_ledger import append_context_compression_attempt

    append_context_compression_attempt(
        tmp_path,
        "session-low-savings",
        turn_id="turn-current",
        status="skipped_low_savings",
        summary="压缩摘要收益不足。",
        level="standard",
        reason="context_pressure",
        before_tokens=10000,
        after_tokens=9800,
        trigger_source="automatic_threshold",
        effectiveness_threshold=0.3,
        effectiveness_ratio=0.02,
    )

    projection = project_conversation_ledger(
        load_conversation_events(tmp_path, "session-low-savings"),
        include_model_messages=True,
        include_visible_messages=True,
    )
    marker = next(
        message for message in projection.visible_messages
        if message.get("metadata", {}).get("kind") == "context_compression_marker"
    )
    model_text = "\n".join(str(message.get("content") or "") for message in projection.model_messages)

    assert marker["metadata"]["status"] == "skipped_low_savings"
    assert marker["metadata"]["title"] == "压缩未应用 · 收益不足"
    assert "低收益时仍保留的旧上下文" in model_text
```

- [ ] **Step 2: Add failing ledger test for failed preserved attempt**

Add:

```python
def test_context_compression_failure_marker_preserves_model_history(tmp_path):
    append_conversation_event(
        tmp_path,
        "session-failed-compression",
        "turn-old",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "失败时仍保留的旧上下文"},
    )
    from core.chat.conversation_ledger import append_context_compression_attempt

    append_context_compression_attempt(
        tmp_path,
        "session-failed-compression",
        turn_id="turn-current",
        status="failed_preserved",
        summary="",
        level="standard",
        reason="compressor_error",
        before_tokens=10000,
        after_tokens=10000,
        trigger_source="provider_context_length",
        error_type="RuntimeError",
    )

    projection = project_conversation_ledger(
        load_conversation_events(tmp_path, "session-failed-compression"),
        include_model_messages=True,
        include_visible_messages=True,
    )
    marker = next(
        message for message in projection.visible_messages
        if message.get("metadata", {}).get("kind") == "context_compression_marker"
    )
    model_text = "\n".join(str(message.get("content") or "") for message in projection.model_messages)

    assert marker["metadata"]["status"] == "failed_preserved"
    assert marker["metadata"]["title"] == "压缩失败 · 已保留原上下文"
    assert marker["metadata"]["errorType"] == "RuntimeError"
    assert "失败时仍保留的旧上下文" in model_text
```

- [ ] **Step 3: Run tests to verify failure**

```powershell
& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" -m pytest tests/test_conversation_ledger.py -q
```

Expected: import fails because `append_context_compression_attempt` does not exist.

- [ ] **Step 4: Implement attempt event**

In `core/chat/turn_journal.py`, add a new event constant near `EVENT_COMPACTION_CHECKPOINT`:

```python
EVENT_COMPRESSION_ATTEMPT = "context_compression_attempt"
```

Do not add it to compression checkpoint replacement logic. Keep it out of `apply_context_compression_checkpoints()` and project it only through the visible-message branch in `model_visible_messages_from_events()`.

In `core/chat/context_compression_ledger.py`, add:

```python
def append_context_compression_attempt(
    project_root: Path,
    session_id: str,
    *,
    turn_id: str = "",
    status: str,
    summary: str = "",
    level: str = "",
    reason: str = "",
    before_tokens: int = 0,
    after_tokens: int = 0,
    trigger_source: str = "",
    effectiveness_threshold: float = 0.0,
    effectiveness_ratio: float = 0.0,
    error_type: str = "",
    source: str = "agent_context_compression",
) -> TurnJournalEvent | None:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    normalized_status = str(status or "").strip() or "skipped_low_savings"
    before = max(0, int(before_tokens or 0))
    after = max(0, int(after_tokens or 0))
    payload = {
        "summary": str(summary or "").strip(),
        "summaryHash": _short_hash(str(summary or "").strip()),
        "summaryWritten": bool(str(summary or "").strip()),
        "level": str(level or "").strip(),
        "reason": str(reason or "").strip(),
        "triggerSource": str(trigger_source or "").strip(),
        "beforeTokens": before,
        "afterTokens": after,
        "savedTokens": max(0, before - after),
        "effectivenessThreshold": max(0.0, float(effectiveness_threshold or 0.0)),
        "effectivenessRatio": max(0.0, float(effectiveness_ratio or 0.0)),
        "effective": False,
        "markerStatus": normalized_status,
        "errorType": str(error_type or "").strip(),
        "schema": "context_compression_attempt.v1",
    }
    return append_turn_event(
        Path(project_root),
        normalized_session_id,
        str(turn_id or "context-compression-attempt").strip(),
        EVENT_COMPRESSION_ATTEMPT,
        status=normalized_status,
        payload=payload,
        source=source,
        visible_in_model=False,
        projection_kind="context_compression_marker",
        source_kind="context_compression",
    )
```

Export it from `core/chat/context_compression_ledger.py` and `core/chat/conversation_ledger.py`.

- [ ] **Step 5: Teach visible projection to render attempts**

In `core/chat/turn_journal.py`, add a branch in `model_visible_messages_from_events()`:

```python
elif event.event_type in {EVENT_COMPACTION_CHECKPOINT, EVENT_COMPRESSION_ATTEMPT}:
    checkpoint_message = _checkpoint_message_from_event(event)
    if _message_has_visible_payload(checkpoint_message):
        messages.append(checkpoint_message)
```

Update `_context_compression_marker_metadata()` status selection:

```python
raw_status = str(payload.get("markerStatus") or event.status or "").strip()
if raw_status in {"skipped_low_savings", "failed_preserved"}:
    status = raw_status
elif bool(payload.get("effective", True)) and bool(payload.get("summaryWritten", bool(summary))):
    status = "applied"
else:
    status = "skipped_low_savings"
title_by_status = {
    "applied": "上下文已压缩",
    "skipped_low_savings": "压缩未应用 · 收益不足",
    "failed_preserved": "压缩失败 · 已保留原上下文",
}
```

Add `errorType` to metadata when present.

- [ ] **Step 6: Integrate Agent low-savings/failure paths**

In `agent.py`, after `compression_effective` is computed and `session_id` / `turn_id` are known:

- If `summary` exists and `compression_effective` is false, call `append_context_compression_attempt()` instead of `append_context_compression_checkpoint()` so model history is not covered.
- If checkpoint append raises, keep the existing runtime-scene error record and also attempt `append_context_compression_attempt(status="failed_preserved", error_type=type(exc).__name__)`.
- Keep `prompt_manager.update_state_memory()` fallback for non-chat or ledger-unavailable cases.

The implementation must not call `append_context_compression_checkpoint()` with `effective=False` if that event would still cover history.

- [ ] **Step 7: Run backend tests**

```powershell
& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" -m pytest tests/test_conversation_ledger.py tests/test_session_context_pipeline.py tests/test_agent_protocol.py -q
```

Expected: pass. If `tests/test_agent_protocol.py` is too broad or slow, first run the specific compression-related test class or `-k context_compression`; then run the broad file before task completion.

- [ ] **Step 8: Commit**

```powershell
git add -- agent.py core/chat/context_compression_ledger.py core/chat/conversation_ledger.py core/chat/turn_journal.py tests/test_conversation_ledger.py tests/test_agent_protocol.py
git commit -m "feat(agent): record compression attempt markers"
```

## Task 3: AgentThread Marker Model And Centered Rendering

**Files:**
- Modify: `web/src/agent-thread/types.ts`
- Modify: `web/src/agent-thread/adapters.ts`
- Modify: `web/src/agent-thread/AgentThreadView.tsx`
- Modify: `web/src/agent-thread/AgentThreadView.styles.ts`
- Modify: `web/src/agent-thread/agentThreadAdapters.test.ts`
- Modify: `web/src/agent-thread/AgentThreadView.test.tsx`

**Interfaces:**
- Consumes: Conversation messages with `metadata.kind === "context_compression_marker"`.
- Produces: centered marker DOM with `data-agent-message-kind="context_compression_marker"` and no normal role header.

- [ ] **Step 1: Add failing adapter test**

In `web/src/agent-thread/agentThreadAdapters.test.ts`, add:

```ts
  it("maps context compression markers without assistant text parts", () => {
    const message: ConversationMessage = {
      id: "compression:event-1",
      role: "assistant",
      content: "",
      timestamp: "2026-07-05T12:00:00Z",
      metadata: {
        kind: "context_compression_marker",
        status: "applied",
        title: "上下文已压缩",
        detail: "standard · 节省 12,340 tokens · 自动阈值",
        summaryPreview: "旧阶段摘要",
      },
    };

    const agentMessage = conversationMessageToAgentMessage(message);

    expect(agentMessage.metadata?.kind).toBe("context_compression_marker");
    expect(agentMessage.parts).toEqual([]);
    expect(agentMessage.role).toBe("assistant");
  });
```

- [ ] **Step 2: Add failing view test**

In `web/src/agent-thread/AgentThreadView.test.tsx`, add:

```tsx
  it("renders context compression markers as centered timeline dividers", () => {
    const html = renderThread({
      id: "thread-compression",
      source: { kind: "session", id: "session-compression" },
      status: "idle",
      messages: [
        {
          id: "compression:event-1",
          role: "assistant",
          createdAt: "2026-07-05T12:00:00Z",
          streaming: false,
          source: {
            kind: "conversation-message",
            id: "compression:event-1",
            metadata: {
              kind: "context_compression_marker",
              status: "applied",
              title: "上下文已压缩",
              detail: "standard · 节省 12,340 tokens · 自动阈值",
              summaryPreview: "旧阶段摘要",
            },
          },
          metadata: {
            kind: "context_compression_marker",
            status: "applied",
            title: "上下文已压缩",
            detail: "standard · 节省 12,340 tokens · 自动阈值",
            summaryPreview: "旧阶段摘要",
          },
          parts: [],
        },
      ],
    });

    expect(html).toContain('data-agent-message-kind="context_compression_marker"');
    expect(html).toContain('data-agent-compression-status="applied"');
    expect(html).toContain("上下文已压缩");
    expect(html).toContain("standard · 节省 12,340 tokens · 自动阈值");
    expect(html).not.toContain("<span>assistant</span>");
    expect(html).not.toContain('data-agent-section-kind=');
  });
```

- [ ] **Step 3: Run Vitest to verify failure**

```powershell
npm --prefix web run test -- agentThreadAdapters.test.ts AgentThreadView.test.tsx
```

Expected: view test fails because marker still renders as an assistant message with role header.

- [ ] **Step 4: Add marker metadata type**

In `web/src/agent-thread/types.ts`, add:

```ts
export type AgentCompressionMarkerStatus = "applied" | "skipped_low_savings" | "failed_preserved" | string;

export type AgentCompressionMarkerMetadata = {
  kind: "context_compression_marker";
  status?: AgentCompressionMarkerStatus;
  title?: string;
  detail?: string;
  summaryPreview?: string;
  level?: string;
  triggerSource?: string;
  beforeTokens?: number;
  afterTokens?: number;
  savedTokens?: number;
};
```

Keep `AgentMessageRole = "user" | "assistant"` unchanged for the first implementation.

- [ ] **Step 5: Keep adapter marker messages content-free**

In `web/src/agent-thread/adapters.ts`, add helper:

```ts
function isContextCompressionMarker(message: ConversationMessage) {
  return message.metadata?.kind === "context_compression_marker";
}
```

Update `conversationMessageToAgentParts()`:

```ts
export function conversationMessageToAgentParts(message: ConversationMessage): AgentMessagePart[] {
  if (isContextCompressionMarker(message)) {
    return [];
  }
  ...
}
```

- [ ] **Step 6: Render marker branch**

In `web/src/agent-thread/AgentThreadView.tsx`, import `AgentCompressionMarkerMetadata` and add:

```tsx
function isCompressionMarkerMessage(message: AgentMessage) {
  return message.metadata?.kind === "context_compression_marker";
}
```

At the top of `AgentMessageView`:

```tsx
  if (isCompressionMarkerMessage(message)) {
    return <AgentCompressionMarkerView message={message} />;
  }
```

Add:

```tsx
function AgentCompressionMarkerView({ message }: { message: AgentMessage }) {
  const metadata = (message.metadata ?? {}) as AgentCompressionMarkerMetadata;
  const status = String(metadata.status || "applied");
  return (
    <div
      className={styles.compressionMarker}
      data-agent-message-id={message.id}
      data-agent-message-kind="context_compression_marker"
      data-agent-compression-status={status}
    >
      <span className={styles.compressionLine} aria-hidden="true" />
      <span className={styles.compressionBody}>
        <span className={styles.compressionTitle}>{metadata.title || compressionMarkerTitle(status)}</span>
        {metadata.detail ? <span className={styles.compressionDetail}>{metadata.detail}</span> : null}
      </span>
      <span className={styles.compressionLine} aria-hidden="true" />
    </div>
  );
}

function compressionMarkerTitle(status: string) {
  if (status === "skipped_low_savings") {
    return "压缩未应用 · 收益不足";
  }
  if (status === "failed_preserved") {
    return "压缩失败 · 已保留原上下文";
  }
  return "上下文已压缩";
}
```

- [ ] **Step 7: Add centered styles**

In `web/src/agent-thread/AgentThreadView.styles.ts`, add:

```ts
  compressionMarker:
    "grid min-w-0 grid-cols-[minmax(1rem,1fr)_auto_minmax(1rem,1fr)] items-center gap-2 px-1 py-1.5 text-center",
  compressionLine:
    "h-px min-w-0 bg-[color-mix(in_srgb,var(--vui-border-subtle)_78%,transparent)]",
  compressionBody:
    "inline-flex max-w-full min-w-0 flex-wrap items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[color-mix(in_srgb,var(--vui-control-muted)_72%,transparent)] px-2.5 py-1 text-[length:var(--vui-font-xs)] leading-[var(--vui-line-tight)] text-[var(--fg-secondary)]",
  compressionTitle:
    "min-w-0 font-semibold text-[var(--fg-secondary)]",
  compressionDetail:
    "min-w-0 text-[var(--fg-tertiary)] [overflow-wrap:anywhere]",
```

- [ ] **Step 8: Run frontend tests**

```powershell
npm --prefix web run test -- agentThreadAdapters.test.ts AgentThreadView.test.tsx
```

Expected: pass.

- [ ] **Step 9: Commit**

```powershell
git add -- web/src/agent-thread/types.ts web/src/agent-thread/adapters.ts web/src/agent-thread/AgentThreadView.tsx web/src/agent-thread/AgentThreadView.styles.ts web/src/agent-thread/agentThreadAdapters.test.ts web/src/agent-thread/AgentThreadView.test.tsx
git commit -m "feat(web): render compression markers as centered dividers"
```

## Task 4: Conversation Timeline Integration And Regression Coverage

**Files:**
- Modify: `web/src/components/conversation/useAgentMessageTimelineProjection.test.ts`
- Modify: `web/src/components/conversation/ConversationView.agentThreadBridge.test.tsx` or nearest active bridge test
- Modify: `web/src/components/conversation/timelineMessageProcessProjection.ts`
- Modify: `web/src/components/conversation/timelineMessageProcessProjection.test.ts`

**Interfaces:**
- Consumes: AgentThread marker rendering from Task 3.
- Produces: marker messages survive conversation display projection and are not merged into process-only assistant packets.

- [ ] **Step 1: Add timeline projection test**

In `web/src/components/conversation/useAgentMessageTimelineProjection.test.ts`, add a test with this shape:

```ts
  it("keeps context compression markers as standalone timeline messages", () => {
    const marker: ConversationMessage = {
      id: "compression:event-1",
      role: "assistant",
      content: "",
      timestamp: "2026-07-05T12:00:00Z",
      metadata: {
        kind: "context_compression_marker",
        status: "applied",
        title: "上下文已压缩",
        detail: "standard · 节省 12,340 tokens · 自动阈值",
      },
    };
    const projection = projectAgentMessageTimelineMessages({
      timelineMessages: [
        message({ id: "user-before", role: "user", content: "压缩前" }),
        marker,
        message({ id: "assistant-after", role: "assistant", content: "压缩后继续" }),
      ],
    });

    expect(projection.messages.map((item) => item.id)).toEqual([
      "user-before",
      "compression:event-1",
      "assistant-after",
    ]);
    expect(projection.agentMessages[1].metadata?.kind).toBe("context_compression_marker");
    expect(projection.agentMessages[1].parts).toEqual([]);
  });
```

Use the file's existing `message()` helper signature and keep the marker fields exactly as `id`, `role`, `content`, `timestamp`, and `metadata`.

- [ ] **Step 2: Run projection test**

```powershell
npm --prefix web run test -- useAgentMessageTimelineProjection.test.ts timelineMessageProcessProjection.test.ts
```

Expected: fail until `timelineMessageProcessProjection.ts` explicitly preserves marker messages as standalone timeline items.

- [ ] **Step 3: Guard process projection**

Add helper in `timelineMessageProcessProjection.ts`:

```ts
function isContextCompressionMarker(message: ConversationMessage) {
  return message.metadata?.kind === "context_compression_marker";
}
```

Ensure `projectTimelineProcessMessages()` directly pushes marker messages and does not pass them through process-only merge logic:

```ts
    if (isContextCompressionMarker(message)) {
      projected.push(message);
      continue;
    }
```

Add/adjust `timelineMessageProcessProjection.test.ts` accordingly.

- [ ] **Step 4: Run conversation frontend subset**

```powershell
npm --prefix web run test -- useAgentMessageTimelineProjection.test.ts timelineMessageProcessProjection.test.ts ConversationView.agentThreadBridge.test.tsx AgentThreadView.test.tsx
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add -- web/src/components/conversation/useAgentMessageTimelineProjection.test.ts web/src/components/conversation/timelineMessageProcessProjection.ts web/src/components/conversation/timelineMessageProcessProjection.test.ts web/src/components/conversation/ConversationView.agentThreadBridge.test.tsx
git commit -m "test(web): preserve compression markers in conversation timeline"
```

Stage the projection test and any projection implementation files changed by this task.

## Task 5: Runtime Summary And End-To-End Validation

**Files:**
- Modify: `tests/test_web_runtime_routes.py`
- No planned modification: `web/src/api/types.ts`; keep role typing stable and resolve marker typing inside AgentThread metadata.
- Modify: project memory after implementation completion, through normal memory workflow

**Interfaces:**
- Consumes: backend marker events and frontend rendering from prior tasks.
- Produces: final validation evidence and release/Launcher refresh decision.

- [ ] **Step 1: Extend runtime summary regression**

In `tests/test_web_runtime_routes.py`, add or update a focused assertion near `test_runtime_summary_prefers_ledger_context_compression_checkpoint`:

```python
    assert compression["lastCompression"]["triggerSource"] == "automatic_threshold"
    assert compression["lastCompression"]["effective"] is True
```

Add a separate test that failed attempts do not replace the latest successful `lastCompression`. Runtime summary remains about applied compression checkpoints; visible timeline shows attempts.

- [ ] **Step 2: Run backend focused suite**

```powershell
& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" -m pytest tests/test_conversation_ledger.py tests/test_session_context_pipeline.py tests/test_web_runtime_routes.py -q
```

Expected: pass.

- [ ] **Step 3: Run frontend focused suite**

```powershell
npm --prefix web run test -- agentThreadAdapters.test.ts AgentThreadView.test.tsx useAgentMessageTimelineProjection.test.ts timelineMessageProcessProjection.test.ts ConversationView.agentThreadBridge.test.tsx
```

Expected: pass.

- [ ] **Step 4: Run web build**

```powershell
npm --prefix web run build
```

Expected: build succeeds.

- [ ] **Step 5: Run diff check**

```powershell
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 6: Manual or browser visual check**

Do not start a dev server from this task worktree. Use the static markup evidence from `AgentThreadView.test.tsx` for this plan's minimum visual check. During implementation review, perform a Launcher-governed browser check on the running app before release/runtime verification and check:

- marker is centered;
- marker has no assistant role header;
- marker does not use assistant/user bubble border;
- long detail wraps without overflow;
- adjacent messages remain readable.

- [ ] **Step 7: Update project memory**

Use the project memory workflow after implementation:

```powershell
& "C:\Users\17533\AppData\Local\Programs\Python\Python312\python.exe" "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\sync_project_memory.py" "C:\Users\17533\Desktop\Vibelution" --lane "chat-coding-surface" --focus "Visible context compression marker implemented" --update "Conversation timeline now renders context compression checkpoints as Codex-style centered markers while model context continues using ledger checkpoint projection."
```

Run memory sync only after guard status shows no conflicting memory writer. When a conflict exists, record this exact update proposal in the final report instead of forcing: lane `chat-coding-surface`, focus `Visible context compression marker implemented`, update `Conversation timeline now renders context compression checkpoints as Codex-style centered markers while model context continues using ledger checkpoint projection.`

- [ ] **Step 8: Commit final validation/memory changes**

When Task 5 changes tests or memory files:

```powershell
git add -- tests/test_web_runtime_routes.py web/src/api/types.ts .docs/project-memory PROJECT_MEMORY.html
git commit -m "test: validate visible compression marker integration"
```

Stage only files actually changed.

## Final Verification Gate

Before reporting implementation complete, run:

```powershell
git status --short --branch
& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" -m pytest tests/test_conversation_ledger.py tests/test_session_context_pipeline.py tests/test_web_runtime_routes.py -q
npm --prefix web run test -- agentThreadAdapters.test.ts AgentThreadView.test.tsx useAgentMessageTimelineProjection.test.ts timelineMessageProcessProjection.test.ts ConversationView.agentThreadBridge.test.tsx
npm --prefix web run build
git diff --check
```

Expected:

- only current-task files are changed or committed;
- backend focused tests pass;
- frontend focused tests pass;
- web build succeeds;
- diff check is clean.

Launcher refresh decision:

- Required before release/runtime verification because backend conversation projection and frontend rendering changed.
- Recommended before user testing if the running UI is already open.
- Not required for the plan/spec-only stage.
