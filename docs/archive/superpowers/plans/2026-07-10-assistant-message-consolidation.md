# Assistant Message Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent a stale `session_live_overlay` and its completed same-turn assistant message from rendering as duplicate response text.

**Architecture:** Keep the backend journal and recovery events unchanged. Normalize the frontend timeline before process-message projection: when a committed assistant answer exists for a turn, remove only the `session_live_overlay` for that same normalized turn, then continue through the existing projection and row-building pipeline.

**Tech Stack:** React 19, TypeScript 5.9, Vitest 3, existing Vibelution conversation projection helpers.

## Global Constraints

- Preserve `assistant_delta_committed` and backend timeline events for recovery and diagnostics.
- Do not deduplicate by response text.
- Do not remove commentary, tool, status, reasoning, or distinct assistant messages.
- Use existing normalized turn identity through `conversationMessageTurnId` and `isSameConversationTurn`.
- The final committed assistant message is the visible owner once it exists.
- Frontend runtime refresh is required before manual user verification.

---

## File Structure

- Modify `web/src/components/conversation/useAgentMessageTimelineProjection.test.ts`: reproduce the stale-overlay/final-message sequence and preserve overlay-only recovery behavior.
- Modify `web/src/components/conversation/useAgentMessageTimelineProjection.ts`: remove superseded live overlays before the existing active-turn and process projection branches.
- Do not modify `core/web/services/session_service.py`: its existing `_filter_redundant_assistant_timeline_events` remains the historical/detail projection defense.

### Task 1: Consolidate completed assistant turns in the frontend timeline

**Files:**

- Modify: `web/src/components/conversation/useAgentMessageTimelineProjection.test.ts`
- Modify: `web/src/components/conversation/useAgentMessageTimelineProjection.ts`

**Interfaces:**

- Consumes: `ConversationMessage`, `isSessionLiveOverlayMessage`, `isSameConversationTurn`, `hasCommittedAssistantAnswerForActiveTurn`, and `projectTimelineProcessMessages`.
- Produces: unchanged `projectAgentMessageTimelineMessages(input): AgentMessageTimelineProjection` behavior with one visible assistant message after same-turn settlement.

- [ ] **Step 1: Add the failing duplicate-settlement test**

Add this case inside the existing `describe("projectAgentMessageTimelineMessages", ...)` block:

```typescript
it("drops a stale live overlay after a committed same-turn answer arrives", () => {
  const liveOverlay = assistantMessage("live-overlay", {
    content: "你好！我在。需要我帮你做什么？",
    streaming: true,
    metadata: { kind: "session_live_overlay", turnId: "live:turn-duplicate" },
  });
  const committed = assistantMessage("committed-answer", {
    content: "你好！我在。需要我帮你做什么？",
    streaming: false,
    metadata: { turnId: "turn-duplicate" },
  });

  const projection = projectAgentMessageTimelineMessages({
    timelineMessages: [liveOverlay, committed],
  });

  expect(projection.messages.map((message) => message.id)).toEqual(["committed-answer"]);
  expect(projection.agentMessages.map((message) => message.id)).toEqual(["committed-answer"]);
  expect(projection.rowIdentities).toHaveLength(1);
});
```

- [ ] **Step 2: Add the draft-only recovery characterization test**

Add a separate case proving that an overlay remains visible when no final answer exists:

```typescript
it("keeps a live overlay visible while no committed same-turn answer exists", () => {
  const liveOverlay = assistantMessage("live-overlay", {
    content: "尚未完成的回答",
    streaming: true,
    metadata: { kind: "session_live_overlay", turnId: "live:turn-interrupted" },
  });

  const projection = projectAgentMessageTimelineMessages({
    timelineMessages: [liveOverlay],
  });

  expect(projection.messages.map((message) => message.id)).toEqual(["live-overlay"]);
  expect(projection.streamingMessages.map((message) => message.id)).toEqual(["live-overlay"]);
});
```

- [ ] **Step 3: Run the focused test and verify RED**

Run:

```powershell
npm --prefix web test -- src/components/conversation/useAgentMessageTimelineProjection.test.ts
```

Expected result: the duplicate-settlement test fails because `projection.messages` still contains both `live-overlay` and `committed-answer`; the draft-only characterization passes.

- [ ] **Step 4: Add the minimal overlay-consolidation helper**

Insert this helper after `hasCommittedAssistantAnswerForActiveTurn`:

```typescript
function removeSupersededSessionLiveOverlays(messages: ConversationMessage[]) {
  return messages.filter((message) => (
    !isSessionLiveOverlayMessage(message)
    || !hasCommittedAssistantAnswerForActiveTurn(messages, message)
  ));
}
```

Update the start of `projectAgentMessageTimelineMessages` so the existing branches consume the consolidated list:

```typescript
const projectedMessages = (() => {
  const visibleTimelineMessages = removeSupersededSessionLiveOverlays(
    chronologicalConversationMessages(timelineMessages)
      .filter(hasVisibleProjectionMessageContent),
  );
  if (!activeTurnMessage || hasCommittedAssistantAnswerForActiveTurn(visibleTimelineMessages, activeTurnMessage)) {
    return projectTimelineProcessMessages(visibleTimelineMessages);
  }
```

Do not change `mergeLiveOverlayIntoActiveTurnMessage`; it remains responsible for merging a live overlay into an unfinished active layer.

- [ ] **Step 5: Run the focused test and verify GREEN**

Run:

```powershell
npm --prefix web test -- src/components/conversation/useAgentMessageTimelineProjection.test.ts
```

Expected result: all tests in the file pass, including the new settlement and draft-only cases.

- [ ] **Step 6: Run the neighboring conversation projection tests**

Run:

```powershell
npm --prefix web test -- src/components/conversation/agentMessageTimelineRows.test.ts src/components/conversation/ConversationView.nativeTranscript.test.tsx
```

Expected result: both files pass, proving stable row grouping and native transcript suppression remain intact.

- [ ] **Step 7: Build the frontend**

Run:

```powershell
npm --prefix web run build
```

Expected result: TypeScript compilation and Vite production build complete successfully.

- [ ] **Step 8: Decide and perform runtime refresh**

Use the project Launcher refresh path because frontend build inputs changed. If Launcher reports active work, stop and report exactly:

```text
有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。
```

After a successful refresh, reproduce with a short assistant response and confirm the final row contains one response body while an unfinished stream still remains visible.

## Completion Evidence

- Focused projection test failed before implementation for the expected duplicate-message assertion.
- Focused and neighboring tests pass after implementation.
- `npm --prefix web run build` passes.
- Runtime refresh decision and result are reported explicitly.
- Version impact: patch-level behavior fix; ordinary task implementation should report the impact without editing version files.
