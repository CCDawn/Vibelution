# Codex Native Transcript Chain Design

## Status

- Date: 2026-07-07
- Tier: HIGH_RISK
- Lane: chat-coding-surface
- Claim: claim-ff816481264e
- Goal: make Chat/Coding render a Codex-like transcript from backend-owned transcript data, with legacy process/timeline rendering only as compatibility fallback.

## Intent

The visible conversation should prioritize the assistant answer, then compact reasoning/tool/status cells. Completed normal process rows render neutral gray. Failed rows render red with concise diagnostics. The UI must stop stacking the old process/timeline/response renderer beside the Codex-like surface when native transcript data exists.

This round does not replace the whole Vibelution conversation persistence model with the official Codex Rust rollout trace. It adds a native compatibility DTO that carries the same core boundaries: transcript cells, tool calls, terminal operations/sessions, model observations, and rollout lifecycle events.

## Source Of Truth

| Fact | Canonical source | Writer | Readers / derived surfaces | Refresh or invalidation | Old source cleanup |
| --- | --- | --- | --- | --- | --- |
| Assistant visible transcript cells | `ConversationMessage.codexTranscript.cells` | `core/web/services/session_service.py` | `ConversationView`, native transcript adapter | Rebuilt when message/detail/live overlay/delta payload is built | `timelineItems` remains fallback only |
| Tool lifecycle facts | `ConversationMessage.codexTranscript.rolloutEvents`, `toolCalls`, `terminalOperations`, `terminalSessions`, `modelObservations` | `core/web/services/session_service.py` | frontend native transcript surface | Rebuilt from normalized `toolCalls` and `feedbackEvents` | frontend lifecycle inference remains legacy fallback |
| Streaming text source boundary | `assistant_delta` content/thought deltas plus optional `codexTranscript` snapshot | backend stream event + frontend source-boundary controller | `sessionAssistantDeltaScheduler`, streaming markdown renderer | `done=true` finalizes incomplete source | fixed batch/local chunking remains fallback behavior |
| Legacy operation timeline | `timelineItems` | existing backend projection | old process/timeline renderer and legacy adapter fallback | Existing rules | no deletion in this round |

## Design

### Backend projection

`session_service.py` adds a helper that builds `codexTranscript` from normalized message fields:

- `version: 1`
- `source: "native"`
- `messageId`
- `streaming`
- `cells`: `assistant_markdown`, `reasoning_summary`, `tool_call`, `status`, `error_notice`, `stream_tail`
- `toolCalls`
- `terminalOperations`
- `terminalSessions`
- `modelObservations`
- `rolloutEvents`

The projection is attached wherever conversation messages already attach `timelineItems`: persisted message normalization, live overlay message, live output checkpoint, and assistant delta events. Existing `timelineItems`, `toolCalls`, and `feedbackEvents` stay intact for compatibility.

### Frontend adapter

`codexNativeTranscriptSurface.ts` becomes the adapter between API DTO and render cells. It prefers `message.codexTranscript` when `source === "native"` and it has cells. It falls back to existing `buildCodexTranscriptCells(...)` only for legacy messages without native transcript data.

The adapter preserves the existing `CodexTranscriptCell` render contract so `ConversationView.tsx` does not need a visual rewrite and does not touch `ConversationView.styles.ts`.

### Conversation render path

For assistant messages with a native transcript surface:

- render the Codex-like transcript surface as the primary process/answer surface;
- do not render legacy `processNode`;
- do not render duplicate `responseSectionNode` when transcript already contains `assistant_markdown`;
- keep `turnErrorNotice`, user content, context sections, inbox/group transcript, and image artifact rendering unchanged;
- fall back to old process/timeline/response rendering only when no native transcript is available.

### Streaming

The existing stream controller already follows Codex's newline-boundary collector idea. This round strengthens the route scheduler/streaming path only where tests prove gaps:

- low pressure drains one delta per frame;
- backlog/oldest age drains catch-up batches;
- final close drains all and finalizes incomplete source;
- native transcript snapshots can ride assistant deltas without being lost by queue coalescing.

### UI polish

No style-file rewrite is included while `claim-2a961d666bbb` owns `ConversationView.styles.ts`. Polish in this round is structural:

- completed normal cells use `tone: "neutral"`;
- failed cells use `tone: "error"`;
- long tool output remains summarized in `summary`/`resultPreview`;
- full lifecycle events stay hidden unless running/warning/error logic already asks for them.

## Non Goals

- No Rust rewrite in this round.
- No direct copy of official Codex Rust code.
- No removal of persisted `AgentMessageOperation`, `feedbackEvents`, or `timelineItems`.
- No edits to `ConversationView.styles.ts`, `ConversationView.test.tsx`, `AgentResponseSectionView.styles.ts`, or `ChatCodingRoute.layout.test.ts` while the readable-width claim is active.
- No Launcher restart unless final verification requires live runtime acceptance.

## Verification

- Backend focused pytest for native transcript projection.
- Frontend Vitest for DTO adapter and ConversationView native render fallback behavior.
- Scheduler/streaming tests for native transcript preservation through delta coalescing or final drain.
- `npm --prefix web run build`.
- `git diff --check`.

## Review

- User intent: PASS. The design targets the user's explicit request to complete remaining Codex-like chain gaps.
- Source of truth: PASS. Backend owns native transcript facts; frontend inference is fallback only.
- Compatibility: PASS. Existing DTO fields stay intact.
- Concurrency: PASS. Claimed style files owned by another agent are excluded.
- Risk: ACCEPT_RISK. Shared DTO and session service are hot files, so focused backend/frontend tests plus build are required before merge.
