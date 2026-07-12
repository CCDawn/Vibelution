# Codex Chat Frontend Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make canonical v2 turn items the single visible owner of commentary, tools, final answers, and terminal errors while restoring a readable Codex-like desktop and mobile conversation surface.

**Architecture:** Keep each wire protocol standard and unchanged. Preserve `SessionTurnItem[]` as the authoritative ordered item stream, derive `codexTranscript` one way, and let `ConversationView` render that transcript exactly once. Implement contract/error ownership first, then responsive layout and visual hierarchy, with legacy history retained only at the normalization boundary.

**Tech Stack:** Python 3, pytest, React 19, TypeScript 5.9, Vitest 3, Tailwind/VUI style maps, SSE session stream, existing browser telemetry, Launcher runtime refresh, in-app Browser visual QA.

## Global Constraints

- Execute in `C:\Users\17533\Desktop\Vibelution-worktrees\codex-chat-frontend-alignment` on branch `codex/codex-chat-frontend-alignment`; keep root local `main` as the integration checkout.
- Run project-memory `status`, `check`, and `claim` before editing hot/shared files; release the claim only after tests, evidence, memory sync, and integration are resolved.
- Keep Responses, Chat Completions, Hermes, and other wire adapters protocol-native; do not edit their standard wire contracts in this plan.
- Keep `SessionTurnItem[]` authoritative and `codexTranscript` derived; do not introduce a second transcript model.
- New producers write `CodexTranscriptCell.text`; legacy `markdown` is read only at the normalization boundary.
- Do not expose raw provider payloads, raw reasoning, prompts, tool arguments/results, replay blobs, API keys, or secrets in frontend DTOs or logs.
- Do not aggregate separate historical turns; each turn remains independently traceable.
- Do not modify `VERSION`, `CHANGELOG.md`, `web/package.json`, or `web/package-lock.json` in task commits.
- Use TDD for Tasks 1-6; observe the focused RED before implementation and the focused GREEN after implementation.
- Never use `git add .`; stage only the files named by the current task.
- Frontend/API/session projection changes require `npm --prefix web run build` and a Launcher refresh before live visual verification.
- If Launcher reports active work, stop and report exactly `有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。`
- Capture seven prescribed browser screenshots and bounded runtime-scene evidence before completion.

---

## File Structure

| Responsibility | Files |
| --- | --- |
| Canonical frontend DTO and item-to-cell mapping | `web/src/api/types/chat.ts`, `web/src/components/conversation/codexTranscriptCells.ts`, `web/src/routes/chatTurnProtocol.ts` |
| Backend terminal-error item projection | `core/web/services/session_service.py` |
| SSE routing, active-layer settlement, bounded trace | `web/src/routes/chatSessionStreamProtocol.ts`, `web/src/routes/chatActiveTurnLayer.ts` |
| Single transcript/error renderer | `web/src/components/conversation/codexNativeTranscriptSurface.ts`, `web/src/components/conversation/ConversationView.tsx`, `web/src/components/conversation/conversationTurnErrorPresentation.ts` |
| Responsive workbench and AppShell | `web/src/routes/chatCompactPanel.ts`, `web/src/routes/ChatCodingRoute.tsx`, `web/src/routes/ChatCodingRoute.styles.ts`, `web/src/app/AppShell.tsx`, `web/src/app/AppShell.styles.ts` |
| Conversation visual hierarchy | `web/src/components/conversation/ConversationView.styles.ts`, `web/src/components/conversation/AgentMessageTurnView.tsx`, `web/src/components/conversation/AgentMessageTurnView.styles.ts` |
| Runtime and visual evidence | `logs/runtime_scenes/<timestamp>-codex-chat-frontend-alignment/` |

## Task Graph

```text
Task 1 ─┐
        ├─> Task 3 ─> Task 4 ─> Task 6 ─┐
Task 2 ─┘               └────> Task 5 ─┴─> Task 7
```

- Task 1 and Task 2 may run in parallel because their owned files do not overlap.
- Task 4 and Task 5 may run in parallel after Task 3 because one owns transcript rendering and the other owns route/AppShell layout.
- Task 6 starts only after Task 4 because it styles the phase-specific renderer introduced there.
- Task 7 starts only after Tasks 5 and 6 are integrated.

---

### Task 1: Normalize the canonical frontend transcript contract

**Files:**

- Modify: `web/src/api/types/chat.ts:239-424`
- Modify: `web/src/components/conversation/codexTranscriptCells.ts:9-33`
- Modify: `web/src/routes/chatTurnProtocol.ts:123-267`
- Test: `web/src/routes/chatTurnProtocol.test.ts`

**Interfaces:**

- Consumes: existing `SessionTurnItem[]` v2 with `kind`, `channel`, `phase`, `status`, `terminal`, `provisional`, `text`, and `diagnosticSummary`.
- Produces: `projectConversationMessageFromTurnItemsV2(message)` with ordered cells that use `text`, preserve phase/channel, and map terminal errors to `error_notice`.
- Produces: `hasTerminalCanonicalTurnOutcome(message)` for Task 3.

- [ ] **Step 1: Write failing contract tests**

Add cases that preserve commentary/tool/final semantics and map terminal errors:

```typescript
it("writes canonical transcript text and preserves commentary and final phases", () => {
  const projected = canonicalTurnProtocol.projectConversationMessageFromTurnItemsV2({
    id: "message-v2",
    role: "assistant",
    content: "legacy answer",
    timestamp: "2026-07-13T00:00:00.000Z",
    turnItems: [
      {
        version: 2,
        id: "commentary:0",
        itemId: "commentary",
        type: "assistant_message",
        kind: "assistant_message",
        status: "completed",
        sequence: 1,
        channel: "commentary",
        phase: "commentary",
        text: "I will inspect the file.",
      },
      {
        version: 2,
        id: "tool:0",
        itemId: "tool",
        type: "tool_call",
        kind: "tool_call",
        status: "completed",
        sequence: 2,
        channel: "tool",
        phase: "tool_call",
        toolName: "read_file",
        text: "VERSION",
      },
      {
        version: 2,
        id: "answer:0",
        itemId: "answer",
        type: "assistant_message",
        kind: "assistant_message",
        status: "completed",
        sequence: 3,
        channel: "answer",
        phase: "final_answer",
        terminal: true,
        text: "1.2.3",
      },
    ],
  } as never);

  expect(projected.content).toBe("1.2.3");
  expect(projected.codexTranscript?.cells).toMatchObject([
    { kind: "assistant_markdown", channel: "commentary", phase: "commentary", text: "I will inspect the file." },
    { kind: "tool_call", channel: "tool", phase: "tool_call", text: "VERSION" },
    { kind: "assistant_markdown", channel: "answer", phase: "final_answer", terminal: true, text: "1.2.3" },
  ]);
  expect(JSON.stringify(projected.codexTranscript)).not.toContain("markdown");
});

it("projects a terminal error without promoting it to a final answer", () => {
  const projected = canonicalTurnProtocol.projectConversationMessageFromTurnItemsV2({
    id: "message-error",
    role: "assistant",
    content: "legacy error",
    timestamp: "2026-07-13T00:00:00.000Z",
    turnItems: [{
      version: 2,
      id: "error:0",
      itemId: "error",
      type: "error",
      kind: "error",
      status: "failed",
      sequence: 1,
      phase: "turn_failed",
      terminal: true,
      provisional: false,
      text: "上游服务暂不可用。",
      diagnosticSummary: { reasonCode: "upstream_unavailable", httpStatus: 502 },
    }],
  } as never);

  expect(projected.content).toBe("");
  expect(projected.codexTranscript?.cells).toMatchObject([{
    kind: "error_notice",
    phase: "turn_failed",
    terminal: true,
    tone: "error",
    text: "上游服务暂不可用。",
  }]);
  expect(canonicalTurnProtocol.hasTerminalCanonicalTurnOutcome(projected)).toBe(true);
});
```

- [ ] **Step 2: Run the focused RED**

Run:

```powershell
npm --prefix web test -- src/routes/chatTurnProtocol.test.ts
```

Expected: FAIL because current canonical cells emit `markdown`, map commentary to `status`, drop error items, and do not export `hasTerminalCanonicalTurnOutcome`.

- [ ] **Step 3: Extend the shared cell type**

Add the same fields to both shared transcript-cell declarations:

```typescript
export type CodexTranscriptCell = {
  id: string;
  kind: CodexTranscriptCellKind;
  messageId: string;
  status: CodexTranscriptCellStatus;
  tone: CodexTranscriptCellTone;
  title?: string;
  text?: string;
  summary?: string;
  channel?: string;
  phase?: string;
  terminal?: boolean;
  provisional?: boolean;
  diagnosticSummary?: Record<string, unknown>;
  operationIds?: string[];
  rolloutTraceEvents?: CodexRolloutTraceEvent[];
  toolLifecycleModel?: CodexToolLifecycleModel;
  sourceItemId?: string;
};
```

- [ ] **Step 4: Replace the canonical item-to-cell mapping**

Implement a single mapping that writes `text` and preserves semantics:

```typescript
const canonicalCellTone = (item: CanonicalSessionTurnItem) => {
  if (item.status === "failed") return "error" as const;
  if (item.status === "degraded") return "warning" as const;
  if (item.status === "running" || item.status === "in_progress" || item.status === "pending") return "running" as const;
  return "neutral" as const;
};

const canonicalTranscript = (
  items: readonly CanonicalSessionTurnItem[],
): CanonicalConversationMessage["codexTranscript"] => ({
  version: 1,
  source: "native",
  messageId: items[0]?.messageId ?? items[0]?.itemId ?? items[0]?.id ?? "canonical-turn-items-v2",
  cells: items.flatMap<NonNullable<CanonicalConversationMessage["codexTranscript"]>["cells"][number]>((item) => {
    const text = itemText(item);
    if (!text) return [];
    const cellBase = {
      id: item.itemId ?? item.id,
      messageId: item.messageId ?? item.itemId ?? item.id,
      status: item.status,
      tone: canonicalCellTone(item),
      text,
      channel: item.channel,
      phase: item.phase,
      terminal: item.terminal,
      provisional: item.provisional,
      diagnosticSummary: item.diagnosticSummary,
      sourceItemId: item.itemId ?? item.id,
    };
    if (isCanonicalAnswer(item) || item.channel === "commentary") {
      return [{ ...cellBase, kind: "assistant_markdown" }];
    }
    if (item.kind === "reasoning" || item.channel === "analysis") {
      return [{ ...cellBase, kind: "reasoning_summary" }];
    }
    if (item.kind === "tool_call") {
      return [{ ...cellBase, kind: "tool_call", title: item.toolName ?? item.title ?? "Tool" }];
    }
    if (item.kind === "error" || item.type === "error") {
      return [{ ...cellBase, kind: "error_notice", title: item.title ?? "Turn failed" }];
    }
    if (item.kind === "status" || item.type === "status") {
      return [{ ...cellBase, kind: "status", title: item.title ?? "Status" }];
    }
    return [];
  }),
  toolCalls: [],
  terminalOperations: [],
  terminalSessions: [],
  modelObservations: [],
});

export const hasTerminalCanonicalTurnOutcome = (message: CanonicalConversationMessage): boolean =>
  consolidateSessionTurnItemsV2(message.turnItems).some((item) => (
    item.terminal === true
    && item.provisional !== true
    && (item.status === "completed" || item.status === "failed")
  ));
```

Update native-answer extraction to read `cell.text` only for newly produced cells.

- [ ] **Step 5: Run the focused GREEN**

Run:

```powershell
npm --prefix web test -- src/routes/chatTurnProtocol.test.ts
```

Expected: PASS with canonical commentary/tool/final/error cell order and no emitted `markdown` field.

- [ ] **Step 6: Commit Task 1**

```powershell
git add web/src/api/types/chat.ts web/src/components/conversation/codexTranscriptCells.ts web/src/routes/chatTurnProtocol.ts web/src/routes/chatTurnProtocol.test.ts
git commit -m "fix(chat): preserve canonical transcript phases"
```

**Review Gate:** Verify that `content` still contains final answers only and that no wire-adapter type changed.

---

### Task 2: Emit backend terminal-error turn items

**Files:**

- Modify: `core/web/services/session_service.py`
- Test: `tests/test_session_codex_transcript_projection.py`
- Test: `tests/test_provider_error_recovery.py`
- Test: `tests/test_session_detail_contract.py`

**Interfaces:**

- Consumes: sanitized `turn_error` message content and bounded error metadata already produced by session failure handling.
- Produces: `_build_terminal_error_turn_item(...) -> dict[str, Any]` and message/detail `turnItems` containing one v2 terminal error item.
- Preserves: existing raw-error runtime logging and legacy sanitized `message.content`.

- [ ] **Step 1: Write a failing pure projection test**

```python
def test_terminal_provider_error_builds_canonical_v2_item():
    item = session_service._build_terminal_error_turn_item(
        session_id="session-live",
        turn_id="turn-1",
        message_id="message-error",
        content="模型服务上游暂时失败，本轮没有完成。",
        metadata={
            "kind": "turn_error",
            "reasonCode": "upstream_unavailable",
            "reasonSummary": "provider 上游服务不可用或网关失败",
            "httpStatus": 502,
            "providerErrorType": "upstream_error",
            "provider": "ai-pixel_ad214f09",
            "model": "gpt-5.6-luna",
            "turnId": "turn-1",
        },
    )

    assert item == {
        "version": 2,
        "id": "session-live-turn-turn-1-error:0",
        "type": "error",
        "sessionId": "session-live",
        "turnId": "turn-1",
        "itemId": "session-live-turn-turn-1-error",
        "revision": 0,
        "sequence": 1,
        "kind": "error",
        "phase": "turn_failed",
        "status": "failed",
        "provisional": False,
        "terminal": True,
        "messageId": "message-error",
        "source": "session_turn_error",
        "text": "模型服务上游暂时失败，本轮没有完成。",
        "diagnosticSummary": {
            "reasonCode": "upstream_unavailable",
            "reasonSummary": "provider 上游服务不可用或网关失败",
            "httpStatus": 502,
            "providerErrorType": "upstream_error",
            "provider": "ai-pixel_ad214f09",
            "model": "gpt-5.6-luna",
        },
        "metadata": {"turnId": "turn-1"},
    }
```

- [ ] **Step 2: Extend provider-failure integration assertions**

In the existing provider-failure integration case, assert one canonical owner:

```python
assistant_messages = [message for message in payload["messages"] if message.get("role") == "assistant"]
latest_assistant = assistant_messages[-1]
assert latest_assistant["metadata"]["kind"] == "turn_error"
assert len(latest_assistant["turnItems"]) == 1
assert latest_assistant["turnItems"][0]["type"] == "error"
assert latest_assistant["turnItems"][0]["terminal"] is True
assert latest_assistant["turnItems"][0]["status"] == "failed"
assert latest_assistant["turnItems"][0]["text"] == latest_assistant["content"]
assert "litellm.BadGatewayError" not in str(latest_assistant["turnItems"])
```

Add a session-detail recovery assertion that the same error item survives reload without creating a second assistant message.

- [ ] **Step 3: Run the focused RED**

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_session_codex_transcript_projection.py tests/test_provider_error_recovery.py tests/test_session_detail_contract.py -q
```

Expected: FAIL because `_build_terminal_error_turn_item` does not exist and provider-failure messages do not expose the canonical terminal error item.

- [ ] **Step 4: Implement the bounded error-item builder**

Add a pure helper beside the existing turn-item projection helpers:

```python
def _build_terminal_error_turn_item(
    *,
    session_id: str,
    turn_id: str,
    message_id: str,
    content: Any,
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    normalized_metadata = dict(metadata or {})
    item_id = f"{session_id}-turn-{turn_id}-error"
    diagnostic_summary = {
        key: normalized_metadata[key]
        for key in (
            "reasonCode",
            "reasonSummary",
            "reasonDetail",
            "httpStatus",
            "providerErrorType",
            "provider",
            "model",
            "retryable",
        )
        if normalized_metadata.get(key) not in (None, "")
    }
    return {
        "version": 2,
        "id": f"{item_id}:0",
        "type": "error",
        "sessionId": session_id,
        "turnId": turn_id,
        "itemId": item_id,
        "revision": 0,
        "sequence": 1,
        "kind": "error",
        "phase": "turn_failed",
        "status": "failed",
        "provisional": False,
        "terminal": True,
        "messageId": message_id,
        "source": "session_turn_error",
        "text": str(content or "").strip(),
        "diagnosticSummary": diagnostic_summary,
        "metadata": {"turnId": turn_id},
    }
```

Pass normalized message metadata into `_build_session_turn_items_projection`. After explicit canonical event items are checked and before legacy assistant-item synthesis, return this item when `metadata.kind == "turn_error"` or `metadata.providerFailure is True`.

Attach the returned list to normalized message detail, assistant-delta recovery snapshots, and persisted provider-failure messages through the existing `turnItems` field. Do not replace or weaken current raw-error runtime logging.

- [ ] **Step 5: Keep the compatibility native transcript one-way**

When backend detail also emits `codexTranscript`, derive one error cell from the canonical item:

```python
{
    "id": error_item["itemId"],
    "kind": "error_notice",
    "messageId": error_item["messageId"],
    "status": "failed",
    "tone": "error",
    "text": error_item["text"],
    "phase": "turn_failed",
    "terminal": True,
    "diagnosticSummary": error_item["diagnosticSummary"],
    "sourceItemId": error_item["itemId"],
}
```

- [ ] **Step 6: Run the focused GREEN**

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_session_codex_transcript_projection.py tests/test_provider_error_recovery.py tests/test_session_detail_contract.py -q
```

Expected: PASS; provider failures expose one sanitized terminal error item and preserve raw diagnostics only in runtime logs.

- [ ] **Step 7: Commit Task 2**

```powershell
git add core/web/services/session_service.py tests/test_session_codex_transcript_projection.py tests/test_provider_error_recovery.py tests/test_session_detail_contract.py
git commit -m "fix(chat): project terminal provider errors"
```

**Review Gate:** Reject the task if raw provider exception text appears in `turnItems`, `codexTranscript`, session detail, or browser telemetry.

---

### Task 3: Propagate terminal outcomes through SSE and the active layer

**Files:**

- Modify: `web/src/routes/chatSessionStreamProtocol.ts`
- Test: `web/src/routes/chatSessionStreamProtocol.test.ts`
- Modify: `web/src/routes/chatActiveTurnLayer.ts`
- Test: `web/src/routes/chatActiveTurnLayer.test.ts`
- Modify: `web/src/routes/chatStreamApplyController.ts`
- Test: `web/src/routes/chatStreamApplyController.test.ts`

**Interfaces:**

- Consumes: Task 1 canonical helpers and Task 2 terminal error items.
- Produces: stable revision replacement, terminal-error settlement, and bounded telemetry counts.

- [ ] **Step 1: Write failing stream and settlement tests**

Add one router test and one active-layer test:

```typescript
it("reports bounded canonical item counts for a terminal error delta", () => {
  const routed = routeSessionStreamEvent({
    activeSessionId: "session-live",
    expectedType: "assistant_delta",
    rawData: JSON.stringify({
      type: "assistant_delta",
      sessionId: "session-live",
      turnId: "turn-1",
      done: true,
      turnItems: [{
        version: 2,
        id: "error:0",
        itemId: "error",
        type: "error",
        kind: "error",
        status: "failed",
        terminal: true,
        text: "上游服务暂不可用。",
      }],
      updatedAt: "2026-07-13T00:00:00.000Z",
    }),
  });

  expect(routed.accepted).toBe(true);
  expect(routed.trace).toMatchObject({
    turnRenderProtocol: "canonical_turn_items_v2",
    turnItemCount: 1,
    terminalErrorItemCount: 1,
    finalAnswerItemCount: 0,
  });
  expect(JSON.stringify(routed.trace)).not.toContain("上游服务暂不可用");
});

it("settles an active layer after the committed detail receives a terminal error item", () => {
  const committed = messageWithTurnItems([{ type: "error", kind: "error", status: "failed", terminal: true }]);
  expect(shouldKeepActiveTurnLayer(activeLayer, [committed])).toBe(false);
});
```

- [ ] **Step 2: Run the focused RED**

```powershell
npm --prefix web test -- src/routes/chatSessionStreamProtocol.test.ts src/routes/chatActiveTurnLayer.test.ts src/routes/chatStreamApplyController.test.ts
```

Expected: FAIL because the trace lacks item-kind counts and active-layer settlement only recognizes committed final answers.

- [ ] **Step 3: Add bounded trace counts**

Extend `SessionStreamProtocolTrace` and calculate counts without text:

```typescript
function canonicalItemCounts(items: SessionAssistantDeltaStreamEvent["turnItems"]) {
  const canonical = consolidateSessionTurnItemsV2(items);
  return {
    finalAnswerItemCount: canonical.filter((item) => item.channel === "answer" && item.phase === "final_answer").length,
    commentaryItemCount: canonical.filter((item) => item.channel === "commentary").length,
    toolItemCount: canonical.filter((item) => item.kind === "tool_call").length,
    terminalErrorItemCount: canonical.filter((item) => (item.kind === "error" || item.type === "error") && item.terminal === true).length,
  };
}
```

Spread these counts into `baseTrace` for `assistant_delta` only. Keep existing `turnRenderProtocol`, `turnId`, `itemId`, and `turnItemCount` fields.

- [ ] **Step 4: Settle the active layer from terminal canonical outcomes**

Use Task 1's helper alongside the existing committed-answer check:

```typescript
const committedTurnSettled = committedMessages.some((message) => (
  isSameConversationTurn(activeMessage, message)
  && (hasCommittedAssistantProtocolAnswer(message) || hasTerminalCanonicalTurnOutcome(message))
));
```

Keep process-only same-turn packets and provisional commentary visible until a final answer or terminal error is committed.

- [ ] **Step 5: Carry the counts through apply telemetry**

Add the new numeric fields to the existing `browser.session_stream.assistant_delta_applied` telemetry payload. Do not add a new event per delta and do not include item text.

- [ ] **Step 6: Run the focused GREEN**

```powershell
npm --prefix web test -- src/routes/chatSessionStreamProtocol.test.ts src/routes/chatActiveTurnLayer.test.ts src/routes/chatStreamApplyController.test.ts
```

Expected: PASS; terminal errors settle the active layer, revision replacement remains stable, and traces contain only bounded counts.

- [ ] **Step 7: Commit Task 3**

```powershell
git add web/src/routes/chatSessionStreamProtocol.ts web/src/routes/chatSessionStreamProtocol.test.ts web/src/routes/chatActiveTurnLayer.ts web/src/routes/chatActiveTurnLayer.test.ts web/src/routes/chatStreamApplyController.ts web/src/routes/chatStreamApplyController.test.ts
git commit -m "fix(chat): settle terminal stream outcomes"
```

**Review Gate:** Replay and reconnect tests must show one item per canonical identity/revision and no stale active overlay after terminal error.

---

### Task 4: Make the native transcript the single visible owner

**Files:**

- Modify: `web/src/components/conversation/codexNativeTranscriptSurface.ts`
- Test: `web/src/components/conversation/codexNativeTranscriptSurface.test.ts`
- Modify: `web/src/components/conversation/ConversationView.tsx`
- Test: `web/src/components/conversation/ConversationView.nativeTranscript.test.tsx`
- Test: `web/src/components/conversation/ConversationView.test.tsx`
- Modify: `web/src/components/conversation/conversationTurnErrorPresentation.ts`
- Test: `web/src/components/conversation/conversationTurnErrorPresentation.test.ts`

**Interfaces:**

- Consumes: normalized cells from Tasks 1-3.
- Produces: one ordered transcript, one terminal error summary, collapsed diagnostics, and no legacy co-render.

- [ ] **Step 1: Write failing single-owner renderer tests**

Add a provider-error message with both compatibility content and canonical cells:

```typescript
it("renders a canonical terminal error once without legacy response or turn notice", () => {
  renderConversation({
    messages: [{
      id: "message-error",
      role: "assistant",
      content: "上游服务暂不可用。",
      timestamp: "2026-07-13T00:00:00.000Z",
      metadata: { kind: "turn_error", errorType: "provider_upstream_error", httpStatus: 502 },
      codexTranscript: {
        version: 1,
        source: "native",
        messageId: "message-error",
        cells: [{
          id: "error",
          kind: "error_notice",
          messageId: "message-error",
          status: "failed",
          tone: "error",
          phase: "turn_failed",
          terminal: true,
          text: "上游服务暂不可用。",
          diagnosticSummary: { httpStatus: 502, reasonCode: "upstream_unavailable" },
        }],
        toolCalls: [],
        terminalOperations: [],
        terminalSessions: [],
        modelObservations: [],
      },
    }],
  });

  expect(screen.getAllByText("上游服务暂不可用。")).toHaveLength(1);
  expect(screen.queryByText("运行提示")).not.toBeInTheDocument();
  expect(screen.getByText("诊断详情").closest("details")).not.toHaveAttribute("open");
});
```

Add a chain test asserting DOM order `commentary -> tool_call -> final_answer` and a tool disclosure that is closed by default.

- [ ] **Step 2: Run the focused RED**

```powershell
npm --prefix web test -- src/components/conversation/codexNativeTranscriptSurface.test.ts src/components/conversation/ConversationView.nativeTranscript.test.tsx src/components/conversation/ConversationView.test.tsx src/components/conversation/conversationTurnErrorPresentation.test.ts
```

Expected: FAIL because error content is co-rendered and native tool details are currently open.

- [ ] **Step 3: Normalize legacy `markdown` at one boundary**

In `codexNativeTranscriptToCells`, preserve new fields and read old snapshots safely:

```typescript
const legacyMarkdown = "markdown" in cell && typeof cell.markdown === "string" ? cell.markdown : "";
return {
  id: cell.id,
  kind: cell.kind as CodexTranscriptCellKind,
  messageId: cell.messageId || transcript.messageId,
  status: cell.status as CodexTranscriptCellStatus,
  tone: cell.tone as CodexTranscriptCellTone,
  title: cell.title,
  text: cell.text || legacyMarkdown,
  summary: cell.summary,
  channel: cell.channel,
  phase: cell.phase,
  terminal: cell.terminal,
  provisional: cell.provisional,
  diagnosticSummary: cell.diagnosticSummary,
  operationIds,
  rolloutTraceEvents: cellRolloutEvents,
  toolLifecycleModel: normalizeNativeToolLifecycleModel(cell.toolLifecycleModel ?? lifecycleModel),
  sourceItemId: cell.sourceItemId,
};
```

Add `suppressProjectedError` to the resolved surface and set it when a visible native cell is `error_notice` or terminal failed.

- [ ] **Step 4: Render phase-specific assistant cells and one error cell**

Use phase data in `renderCodexTranscriptCell`:

```typescript
const assistantPhaseClassName = cell.phase === "commentary"
  ? styles.codexTranscriptCommentaryCell
  : styles.codexTranscriptFinalCell;
```

For `error_notice`, render the sanitized `cell.text` once, then a closed diagnostic disclosure built from `cell.diagnosticSummary` and the existing bounded metadata formatter.

Gate the legacy error block:

```typescript
const shouldRenderLegacyTurnError = Boolean(
  turnErrorMessage
  && !codexTranscriptSurface?.suppressProjectedError
);
```

Remove `open` from `renderCodexTranscriptToolDetails`. Keep the page-level `lastTurnError` fallback only when no visible message-level terminal error exists.

- [ ] **Step 5: Run the focused GREEN**

```powershell
npm --prefix web test -- src/components/conversation/codexNativeTranscriptSurface.test.ts src/components/conversation/ConversationView.nativeTranscript.test.tsx src/components/conversation/ConversationView.test.tsx src/components/conversation/conversationTurnErrorPresentation.test.ts
```

Expected: PASS; one error summary is visible, diagnostics and completed tools are closed, and legacy history still renders.

- [ ] **Step 6: Commit Task 4**

```powershell
git add web/src/components/conversation/codexNativeTranscriptSurface.ts web/src/components/conversation/codexNativeTranscriptSurface.test.ts web/src/components/conversation/ConversationView.tsx web/src/components/conversation/ConversationView.nativeTranscript.test.tsx web/src/components/conversation/ConversationView.test.tsx web/src/components/conversation/conversationTurnErrorPresentation.ts web/src/components/conversation/conversationTurnErrorPresentation.test.ts
git commit -m "fix(chat): render canonical turns once"
```

**Review Gate:** Inspect the rendered query tree, not only helper output; the same error sentence must have one visible owner.

---

### Task 5: Replace fixed three-column overflow with responsive drawers

**Files:**

- Modify: `web/src/routes/chatCompactPanel.ts`
- Test: `web/src/routes/chatCompactPanel.test.ts`
- Modify: `web/src/routes/ChatCodingRoute.tsx`
- Modify: `web/src/routes/ChatCodingRoute.styles.ts`
- Test: `web/src/routes/ChatCodingRoute.layout.test.ts`
- Test: `web/src/routes/ChatCodingLeftStatus.layout.test.ts`
- Modify: `web/src/app/AppShell.tsx`
- Modify: `web/src/app/AppShell.styles.ts`
- Test: `web/src/app/AppShell.layout.test.ts`

**Interfaces:**

- Consumes: existing stored left/right panel preferences.
- Produces: effective layout mode `wide | compact | overlay | mobile` without overwriting stored desktop preferences.

- [ ] **Step 1: Write failing responsive-state tests**

Define the expected pure layout policy:

```typescript
it.each([
  [1440, "wide", true, false],
  [1024, "compact", true, false],
  [768, "overlay", false, false],
  [390, "mobile", false, false],
])("resolves %ipx to %s without forcing persistent pane preferences", (width, mode, leftVisible, rightVisible) => {
  expect(resolveChatResponsiveLayout(width)).toEqual({ mode, leftVisible, rightVisible });
});
```

Add structural tests requiring overlay drawer controls below `960px`, compact AppShell navigation below `640px`, and the absence of `minmax(260px` plus `minmax(420px` in narrow grid rules.

- [ ] **Step 2: Run the focused RED**

```powershell
npm --prefix web test -- src/routes/chatCompactPanel.test.ts src/routes/ChatCodingRoute.layout.test.ts src/routes/ChatCodingLeftStatus.layout.test.ts src/app/AppShell.layout.test.ts
```

Expected: FAIL because current compact layout preserves fixed `260px + 420px` columns and AppShell navigation does not collapse for mobile.

- [ ] **Step 3: Implement the pure responsive policy**

Add to `chatCompactPanel.ts`:

```typescript
export type ChatResponsiveLayoutMode = "wide" | "compact" | "overlay" | "mobile";

export function resolveChatResponsiveLayout(width: number) {
  if (width < 640) return { mode: "mobile" as const, leftVisible: false, rightVisible: false };
  if (width < 960) return { mode: "overlay" as const, leftVisible: false, rightVisible: false };
  if (width < 1280) return { mode: "compact" as const, leftVisible: true, rightVisible: false };
  return { mode: "wide" as const, leftVisible: true, rightVisible: false };
}
```

Use ResizeObserver width to derive effective visibility. Do not write auto-collapse results back to the stored desktop preference.

- [ ] **Step 4: Replace the narrow grid contract**

Keep the wide grid, add a compact two-column grid, and switch narrow modes to one full-width center column with fixed overlay drawers. The effective narrow layout must not contain a viewport-level minimum wider than `100%`.

Use these CSS/Tailwind invariants in `ChatCodingRoute.styles.ts`:

```typescript
layoutCompactDesktop:
  "vui-routes-chatcodingroute layoutCompactDesktop grid min-w-0 grid-cols-[minmax(220px,var(--chat-left-pane-width,248px))_1px_minmax(0,1fr)] overflow-hidden",
layoutOverlay:
  "vui-routes-chatcodingroute layoutOverlay relative grid min-w-0 grid-cols-[minmax(0,1fr)] overflow-hidden",
overlayPane:
  "vui-routes-chatcodingroute overlayPane fixed inset-y-[var(--shell-topbar-height)] z-40 w-[min(86vw,320px)] shadow-[var(--vui-elevation-panel)]",
overlayBackdrop:
  "vui-routes-chatcodingroute overlayBackdrop fixed inset-0 z-30 bg-black/35",
```

Add Escape close, backdrop close, `aria-expanded`, `aria-controls`, and focus return for both pane controls.

- [ ] **Step 5: Compact the status rail and user identity**

Render only a short failure state in the status rail:

```typescript
const compactSessionStateLine = detail?.lastTurnError
  ? [sessionStateLabel, detail.lastTurnError.httpStatus || detail.lastTurnError.reasonCode].filter(Boolean).join(" · ")
  : sessionStateLine;
```

Pass `操作者` when the candidate user display name is empty or only digits; do not expose an internal numeric ID as the message author.

- [ ] **Step 6: Add compact AppShell navigation**

At `<640px`, keep the active route label and move the full route list behind the existing utility/menu interaction. Preserve desktop nav markup and keyboard navigation above the breakpoint.

- [ ] **Step 7: Run the focused GREEN**

```powershell
npm --prefix web test -- src/routes/chatCompactPanel.test.ts src/routes/ChatCodingRoute.layout.test.ts src/routes/ChatCodingLeftStatus.layout.test.ts src/app/AppShell.layout.test.ts
```

Expected: PASS; responsive mode is pure/derived, narrow grids have one center column, drawers are accessible, and desktop behavior remains intact.

- [ ] **Step 8: Commit Task 5**

```powershell
git add web/src/routes/chatCompactPanel.ts web/src/routes/chatCompactPanel.test.ts web/src/routes/ChatCodingRoute.tsx web/src/routes/ChatCodingRoute.styles.ts web/src/routes/ChatCodingRoute.layout.test.ts web/src/routes/ChatCodingLeftStatus.layout.test.ts web/src/app/AppShell.tsx web/src/app/AppShell.styles.ts web/src/app/AppShell.layout.test.ts
git commit -m "feat(chat): add responsive conversation drawers"
```

**Review Gate:** A `390px` browser viewport must show the conversation and composer at full width before visual polish begins.

---

### Task 6: Establish Codex-like conversation visual hierarchy

**Files:**

- Modify: `web/src/components/conversation/ConversationView.styles.ts`
- Modify: `web/src/components/conversation/AgentMessageTurnView.tsx`
- Modify: `web/src/components/conversation/AgentMessageTurnView.styles.ts`
- Test: `web/src/components/conversation/AgentMessageTurnView.test.tsx`
- Test: `web/src/components/conversation/ConversationProcessTraceStyles.test.ts`
- Test: `web/src/components/conversation/ConversationView.nativeTranscript.test.tsx`

**Interfaces:**

- Consumes: Task 4 phase-specific class names and Task 5 full-width responsive shell.
- Produces: compact commentary/tool/error cells and dominant final answer without changing data flow.

- [ ] **Step 1: Write failing visual-contract tests**

Assert class ownership and collapsed detail defaults:

```typescript
it("gives final answers stronger hierarchy than commentary and completed tools", () => {
  expect(styles.codexTranscriptCommentaryCell).toContain("text-[var(--fg-secondary)]");
  expect(styles.codexTranscriptFinalCell).toContain("leading-[var(--vui-line-readable)]");
  expect(styles.codexTranscriptFinalCell).not.toContain("bg-[var(--state-error)]");
  expect(styles.codexTranscriptErrorCell).toContain("border-l");
  expect(styles.codexTranscriptSurface).toContain("max-w");
});
```

Add component assertions that assistant identity appears once per turn, timestamps remain secondary, and numeric user labels are not rendered.

- [ ] **Step 2: Run the focused RED**

```powershell
npm --prefix web test -- src/components/conversation/AgentMessageTurnView.test.tsx src/components/conversation/ConversationProcessTraceStyles.test.ts src/components/conversation/ConversationView.nativeTranscript.test.tsx
```

Expected: FAIL because phase-specific classes and the new reading-track contract do not exist.

- [ ] **Step 3: Add the phase-specific style contract**

Add style keys with one low-chrome visual grammar:

```typescript
codexTranscriptSurface:
  "vui-components-conversationview codexTranscriptSurface mx-auto grid w-full max-w-[880px] min-w-0 gap-2 px-3 sm:px-5",
codexTranscriptCommentaryCell:
  "vui-components-conversationview codexTranscriptCommentaryCell border-0 bg-transparent py-1 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
codexTranscriptFinalCell:
  "vui-components-conversationview codexTranscriptFinalCell border-0 bg-transparent py-2 text-[var(--fg-primary)] leading-[var(--vui-line-readable)]",
codexTranscriptErrorCell:
  "vui-components-conversationview codexTranscriptErrorCell border-0 border-l-2 border-l-[var(--state-error)] bg-[color-mix(in_srgb,var(--state-error)_5%,transparent)] px-3 py-2",
codexTranscriptProcessCell:
  "vui-components-conversationview codexTranscriptProcessCell border-0 bg-transparent py-1 text-[var(--vui-font-sm)]",
```

Keep code blocks, tables, images, and long URLs constrained inside the reading track. Avoid adding nested cards around each cell.

- [ ] **Step 4: Compact turn identity and metadata**

Keep one assistant avatar/name per turn, reduce timestamp contrast, and hide empty/internal actor labels. Do not remove edit-and-rerun affordances from the latest eligible user message.

- [ ] **Step 5: Run the focused GREEN**

```powershell
npm --prefix web test -- src/components/conversation/AgentMessageTurnView.test.tsx src/components/conversation/ConversationProcessTraceStyles.test.ts src/components/conversation/ConversationView.nativeTranscript.test.tsx
```

Expected: PASS; commentary, process, error, and final use distinct hierarchy while preserving Vibelution Agent identity.

- [ ] **Step 6: Commit Task 6**

```powershell
git add web/src/components/conversation/ConversationView.styles.ts web/src/components/conversation/AgentMessageTurnView.tsx web/src/components/conversation/AgentMessageTurnView.styles.ts web/src/components/conversation/AgentMessageTurnView.test.tsx web/src/components/conversation/ConversationProcessTraceStyles.test.ts web/src/components/conversation/ConversationView.nativeTranscript.test.tsx
git commit -m "style(chat): clarify transcript hierarchy"
```

**Review Gate:** Reject card proliferation, permanent diagnostic expansion, purple-biased redesign, or any style that makes final answers visually weaker than tools.

---

### Task 7: Integrate, refresh, and capture runtime evidence

**Files:**

- Create at runtime: `logs/runtime_scenes/<timestamp>-codex-chat-frontend-alignment/manifest.json`
- Create at runtime: seven prescribed PNG screenshots in the same evidence package
- Update only if required by project-memory owner: relevant `.docs/project-memory/` lane proposal or memory sync

**Interfaces:**

- Consumes: integrated Tasks 1-6.
- Produces: test/build output, Launcher runtime, seven screenshots, DOM assertions, bounded event evidence, self-review, and merge-readiness decision.

- [ ] **Step 1: Run the complete focused backend gate**

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_session_codex_transcript_projection.py tests/test_provider_error_recovery.py tests/test_session_detail_contract.py -q
```

Expected: PASS.

- [ ] **Step 2: Run the complete focused frontend gate**

```powershell
npm --prefix web test -- src/routes/chatTurnProtocol.test.ts src/routes/chatSessionStreamProtocol.test.ts src/routes/chatActiveTurnLayer.test.ts src/routes/chatStreamApplyController.test.ts src/components/conversation/codexNativeTranscriptSurface.test.ts src/components/conversation/ConversationView.nativeTranscript.test.tsx src/components/conversation/ConversationView.test.tsx src/components/conversation/conversationTurnErrorPresentation.test.ts src/routes/chatCompactPanel.test.ts src/routes/ChatCodingRoute.layout.test.ts src/routes/ChatCodingLeftStatus.layout.test.ts src/app/AppShell.layout.test.ts src/components/conversation/AgentMessageTurnView.test.tsx src/components/conversation/ConversationProcessTraceStyles.test.ts
```

Expected: PASS.

- [ ] **Step 3: Build the frontend**

```powershell
npm --prefix web run build
```

Expected: exit code `0` with no TypeScript or Vite build errors.

- [ ] **Step 4: Perform scoped self-review before refresh**

Review only the task diff for protocol ownership, raw-data leakage, stale legacy co-render, responsive preference mutation, accessibility, and unrelated changes. Resolve every actionable finding before continuing.

- [ ] **Step 5: Refresh through Launcher**

Use the project Launcher refresh path. Do not bypass active-work guards.

- [ ] **Step 6: Capture seven visual scenarios**

Save exactly:

```text
01-wide-canonical-chain-1440x900.png
02-desktop-provider-error-1280x720.png
03-compact-desktop-1024x768.png
04-tablet-drawers-768x1024.png
05-mobile-canonical-chain-390x844.png
06-mobile-provider-error-390x844.png
07-streaming-tool-1280x720.png
```

For every viewport assert:

```javascript
document.documentElement.scrollWidth <= window.innerWidth
```

For canonical/error scenarios also assert:

```text
final answer visible count = 1
terminal error transcript count = 1
terminal error status-rail prose count = 0
completed tool disclosure open = false
drawer controls have aria-expanded and aria-controls
visible user label is not a pure numeric ID
```

- [ ] **Step 7: Save bounded evidence**

Write `manifest.json` with viewport, theme, sessionId, turnId, model, build version, scenario ID, commands, exit codes, and screenshot filenames. Save bounded backend/frontend event summaries with item IDs, phases, statuses, counts, and trace IDs only.

- [ ] **Step 8: Reconcile project memory and claim state**

Sync or propose the chat-lane memory update according to the single-writer rule, record the runtime refresh result and evidence package path, then release the task claim.

- [ ] **Step 9: Commit evidence-owned documentation if tracked**

Stage only tracked project-memory or documentation files that belong to this task. Do not force-add ignored runtime logs.

**Review Gate:** Merge readiness requires focused backend/frontend GREEN, successful build, successful Launcher refresh, all seven visual scenarios, no horizontal overflow, and one visible owner for final/error content.

---

## Task Splitting Decision

**Decision:** `SPLIT`

**Critical Path:** `(Task 1 || Task 2) -> Task 3 -> (Task 4 || Task 5) -> Task 6 -> Task 7`

**Optional Path:** none. Numeric-user-label cleanup and compact AppShell behavior are included because they are required by the approved mobile acceptance contract.

**Parallelism:** Task 1 and Task 2 may run concurrently. Task 4 and Task 5 may run concurrently after Task 3. All other transitions are sequential.

| Task | Criticality | Development Mode | Test Anchor | Main Risk |
| --- | --- | --- | --- | --- |
| Task 1 | critical | `BDD_TDD` | canonical `text`, phase/channel, error mapping RED in `chatTurnProtocol.test.ts` | creating another transcript contract or changing wire semantics |
| Task 2 | critical, high risk | `BDD_TDD` | provider failure exposes one sanitized terminal error item | leaking raw provider data or breaking history recovery |
| Task 3 | critical, high risk | `BDD_TDD` | reconnect/revision replacement plus terminal-error settlement | stale overlay or premature settlement |
| Task 4 | critical, high risk | `BDD_TDD` | same error sentence visible exactly once | hiding useful diagnostics or retaining a second owner |
| Task 5 | critical, high risk | `BDD_TDD` | `390px` full-width chat and accessible drawers | overwriting stored pane preference or global nav regression |
| Task 6 | critical | `BDD_TDD` | final stronger than commentary/tool and no numeric actor | visual churn or card proliferation |
| Task 7 | critical | `SIMPLE` | focused gates, build, refresh, seven screenshots | claiming completion without live evidence |

## Split Self-Review

| Check | Evidence | Conclusion |
| --- | --- | --- |
| Plan coverage | Every approved contract, error, logging, layout, accessibility, identity, build, refresh, and screenshot requirement maps to Tasks 1-7 | PASS |
| Dependency clarity | Shared contracts precede stream/render work; visual styling follows renderer semantics; live QA follows integration | PASS |
| Granularity | Each task has one independently reviewable behavior result and its own RED/GREEN or evidence gate | PASS |
| File collision control | Parallel tasks have disjoint owned files; hot-file changes are serialized | PASS |
| Verification feasibility | Every critical task has a focused command and observable expected result | PASS |
| Placeholder scan | No unresolved implementation placeholders or undefined downstream interfaces remain | PASS |

## Ledger Update

| Field | Value |
| --- | --- |
| Current Stage | `TASK_SPLITTING` complete |
| Accepted Plan | One canonical v2 transcript owner, terminal-error normalization, single renderer, responsive drawers, Codex-like hierarchy, bounded logs, seven visual gates |
| Split Decision | `SPLIT` |
| Current Task | Task 1 and Task 2 are the first eligible tasks |
| Reuse Decision | `ADAPT + REFERENCE_ONLY` |
| Unresolved Risks | Execution must re-check worktree/claims; Launcher may be blocked by active work; live provider availability may prevent a real 502 replay, in which case use the existing deterministic provider-failure fixture for visual proof and record the limitation |
| Recommended Next Stage | Subagent-driven execution of Task 1 and Task 2 in parallel, with review before Task 3 |
| Route Out | `ccdawn-bdd-tdd-development` for Tasks 1-6, then `ccdawn-completion-summary` after Task 7 |

