# Codex Native Transcript Chain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade Chat/Coding to prefer backend-owned Codex-like transcript data and keep old process/timeline/response rendering only as legacy fallback.

**Architecture:** Add a compatibility `codexTranscript` projection in `session_service.py`, expose matching TypeScript DTOs, then add a frontend native transcript adapter that prefers backend cells and falls back to existing frontend projection. `ConversationView.tsx` uses that adapter to prevent duplicate old process/response rendering when native transcript cells exist.

**Tech Stack:** Python session service, pytest, TypeScript, React, Vitest, Tailwind/VUI class contracts already present in `ConversationView.styles.ts`.

## Global Constraints

- Work in `C:\Users\17533\Desktop\Vibelution-worktrees\codex-native-transcript-chain` on branch `codex/codex-native-transcript-chain`.
- Preserve root `main` as integration checkout.
- Do not edit `web/src/components/conversation/ConversationView.styles.ts`, `web/src/components/conversation/ConversationView.test.tsx`, `web/src/components/conversation/AgentResponseSectionView.styles.ts`, or `web/src/routes/ChatCodingRoute.layout.test.ts`.
- Use TDD: write failing tests and observe expected failure before production code.
- Keep `timelineItems`, `feedbackEvents`, and `toolCalls` compatible.
- Stage only task files; never use `git add .`.

---

### Task 1: Backend Native Transcript Projection

**Files:**
- Create: `tests/test_session_codex_transcript_projection.py`
- Modify: `core/web/services/session_service.py`

**Interfaces:**
- Produces: `_build_codex_transcript_projection(message_id: str, content: Any, feedback_events: Any, tool_calls: Any, streaming: bool = False) -> dict[str, Any] | None`
- Consumes: `_normalize_message_feedback_events`, `_normalize_message_tool_calls`, `_build_message_timeline_items`

- [ ] **Step 1: Write failing tests**

Cover:

- assistant message with content, one successful terminal-like tool, and one failed tool exposes `codexTranscript.source == "native"`;
- neutral completed tool cell and red failed error cell are represented as `tone: "neutral"` and `tone: "error"`;
- rollout lifecycle includes `ToolCallStarted`, `RuntimeStarted`, `RuntimeEnded`, `ToolCallEnded`;
- live output checkpoint and assistant delta payload include `codexTranscript` when feedback/tool facts exist.

- [ ] **Step 2: Run backend red tests**

Run: `C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_session_codex_transcript_projection.py -q`

Expected: FAIL because `codexTranscript` is absent.

- [ ] **Step 3: Implement minimal backend projection**

Add helper functions near `_build_message_timeline_items` and attach output in:

- `_live_output_checkpoint_payload`
- `_normalize_messages`
- `_build_live_output_message`
- `_publish_session_assistant_delta`
- `_merge_session_assistant_delta_events`

- [ ] **Step 4: Run backend green tests**

Run: `C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_session_codex_transcript_projection.py tests/test_session_service.py -q`

Expected: PASS or report any pre-existing unrelated failure with evidence.

### Task 2: Frontend DTO And Native Transcript Adapter

**Files:**
- Modify: `web/src/api/types.ts`
- Create: `web/src/components/conversation/codexNativeTranscriptSurface.ts`
- Create: `web/src/components/conversation/codexNativeTranscriptSurface.test.ts`
- Modify: `web/src/components/conversation/codexTranscriptCells.ts`

**Interfaces:**
- Produces: `resolveCodexTranscriptSurface(message, fallbackCells) -> { source: "native" | "legacy"; cells: CodexTranscriptCell[]; hasAssistantMarkdown: boolean }`
- Consumes: `ConversationMessage.codexTranscript`

- [ ] **Step 1: Write failing adapter tests**

Cover:

- native `codexTranscript.cells` wins over fallback cells;
- legacy messages without `codexTranscript` still use fallback cells;
- native tool lifecycle arrays are preserved on returned cells.

- [ ] **Step 2: Run frontend red tests**

Run: `npm --prefix web run test -- codexNativeTranscriptSurface.test.ts`

Expected: FAIL because file/API does not exist.

- [ ] **Step 3: Implement TypeScript DTO and adapter**

Add DTO types for cells, lifecycle model, rollout events, and `ConversationMessage.codexTranscript`. Keep names aligned with backend JSON keys.

- [ ] **Step 4: Run frontend green tests**

Run: `npm --prefix web run test -- codexNativeTranscriptSurface.test.ts codexTranscriptCells.test.ts`

Expected: PASS.

### Task 3: ConversationView Native Surface Primary Render

**Files:**
- Create: `web/src/components/conversation/ConversationView.nativeTranscript.test.tsx`
- Modify: `web/src/components/conversation/ConversationView.tsx`

**Interfaces:**
- Consumes: `resolveCodexTranscriptSurface`
- Preserves: existing `renderCodexTranscriptCell` and visual classes

- [ ] **Step 1: Write failing ConversationView tests**

Cover:

- assistant message with native `codexTranscript` renders transcript cells;
- legacy process/timeline sections are not duplicated for that message;
- assistant markdown in native transcript suppresses duplicate response section;
- message without native transcript still falls back to old rendering.

- [ ] **Step 2: Run red tests**

Run: `npm --prefix web run test -- ConversationView.nativeTranscript.test.tsx`

Expected: FAIL because `ConversationView` still builds cells from legacy projection and still renders `processNode`.

- [ ] **Step 3: Implement primary native render path**

Use `resolveCodexTranscriptSurface` in the existing `agentCodexCellsByMessageId` computation and render branch. Gate `processNode` and `responseSectionNode` when native transcript is primary.

- [ ] **Step 4: Run green tests**

Run: `npm --prefix web run test -- ConversationView.nativeTranscript.test.tsx`

Expected: PASS.

### Task 4: Assistant Delta Coalescing And Stream Boundary Guard

**Files:**
- Modify: `tests/test_session_codex_transcript_projection.py`
- Modify: `web/src/routes/sessionAssistantDeltaScheduler.test.ts`
- Modify: `web/src/routes/sessionAssistantDeltaScheduler.ts` only if tests prove needed
- Modify: `web/src/components/conversation/ConversationStreamingResponseContent.tsx` only if tests prove needed

**Interfaces:**
- Preserves: existing `createCodexStreamController`
- Adds: assistant-delta `codexTranscript` coalescing keeps newest native snapshot and final drain emits all queued deltas

- [ ] **Step 1: Write failing tests**

Cover:

- backend assistant delta event includes native transcript when feedback events are included;
- backend assistant delta coalescing keeps the newest `codexTranscript`;
- frontend scheduler telemetry accepts deltas carrying `codexTranscript` without changing content length math.

- [ ] **Step 2: Run red tests**

Run: `C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_session_codex_transcript_projection.py -q`

Run: `npm --prefix web run test -- sessionAssistantDeltaScheduler.test.ts`

- [ ] **Step 3: Implement only required changes**

If backend coalescing drops `codexTranscript`, merge it like feedback events with newest snapshot winning. If frontend scheduler already handles extra fields, keep production code unchanged and record test-only coverage.

- [ ] **Step 4: Run green tests**

Run the same backend and frontend focused tests.

### Task 5: Validation, Review, Commit, Memory

**Files:**
- All task files above
- `.docs/project-memory/**` only during final sync

- [ ] **Step 1: Run focused validation**

Run:

- `C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_session_codex_transcript_projection.py tests/test_session_service.py -q`
- `npm --prefix web run test -- codexNativeTranscriptSurface.test.ts ConversationView.nativeTranscript.test.tsx sessionAssistantDeltaScheduler.test.ts codexTranscriptCells.test.ts codexToolLifecycleModel.test.ts codexRolloutTrace.test.ts`
- `npm --prefix web run build`
- `git diff --check`

- [ ] **Step 2: Self-review diff**

Check hot files for unrelated formatting or scope creep.

- [ ] **Step 3: Commit implementation**

Stage exact task files and commit with: `feat: add native codex transcript chain`

- [ ] **Step 4: Merge gate**

If root `main` has no overlapping dirty changes or conflicting claims, merge locally. If blocked, mark claim ready/blocked with evidence.

- [ ] **Step 5: Sync memory and release claim**

Run project-memory sync for `chat-coding-surface`, render overview, release `claim-ff816481264e` as completed or blocked.
