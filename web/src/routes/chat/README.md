# Chat route modules (`web/src/routes/chat`)

Agent-oriented map for Chat workbench development. Prefer editing a **module** over `ChatCodingRoute.tsx` when possible.

## Ownership map (claim scopes)

| Task type | Prefer these files | Avoid |
|-----------|-------------------|--------|
| CLI terminal tabs / lifecycle | `cliAgentRunModel.ts`, `CliAgentRunTerminalPanel.tsx` | composer submit |
| Cache / token donut pure math | `sessionCacheComposition.ts`, `CacheDetailDialog.tsx`, `TokenCoreStatusPanel.tsx` | stream apply |
| Feature presets labels | `chatFeaturePresets.ts` | detail stream |
| Tool approval copy | `toolApprovalLabels.ts`, `ChatToolApprovalDialog.tsx` | left rail JSX |
| Submit telemetry fields | `chatSubmitTelemetry.ts` | layout resize |
| Composer draft/attachments/submit pure helpers | `chatComposerSubmitModel.ts` | stream apply, dual EventSource |
| Composer turn mutations + submit actions | `useChatComposerSubmit.ts` | session EventSource ownership |
| Session stream connect/grace pure helpers | `chatSessionStreamConnect.ts` | opening EventSource |
| Direct session detail SSE (sole EventSource) | `useSessionDetailStream.ts` | second session EventSource, group stream |
| Group room SSE (sole EventSource) | `useGroupRoomStream.ts` | second group EventSource, session stream |
| Session select / URL / bootstrap | `useChatSessionSelection.ts` | EventSource ownership |
| Session detail window / ledger / conversation merge | `chatSessionDetailHelpers.ts` | stream EventSource |
| Labels / avatar / group message presentation | `chatRoutePresentation.tsx` | mutations / stream |
| Session/group lifecycle mutations | `useChatWorkspaceLifecycle.ts` | EventSource, composer submit |
| Composer bridge UI | `ChatConversationComposerBridge.tsx` | CLI model |
| Center workspace shell | `ChatSessionWorkspacePanel.tsx` | index rail |
| Layout width math | `chatCodingRouteViewModel.ts` | session protocol |
| Shell layout / resize / responsive panes | `useChatWorkbenchLayout.ts` | stream/submit |
| Left index / new Agent / group / system entry UI | `ChatConversationIndexRail.tsx` | stream/submit |
| Right status / run modes / token / pet / group settings | `ChatStatusRail.tsx` | left index, stream apply |
| Orchestration / wiring only | `../ChatCodingRoute.tsx` | — |

## Phase A (done)

Pure helpers extracted from `ChatCodingRoute.tsx`:

- `cliAgentRunModel.ts` — CLI run views, lifecycle, terminal input rules
- `sessionCacheComposition.ts` — cache donut segment geometry
- `chatFeaturePresets.ts` — run-mode preset keys/labels
- `toolApprovalLabels.ts` — governance tool display labels
- `chatSubmitTelemetry.ts` — submit browser telemetry fields

## Phase B (done)

- `ChatConversationIndexRail.tsx` — left conversation index pane (tabs, member status, new Agent/group, system entry)

## Phase C (done)

- `ChatStatusRail.tsx` — right status pane (group profile/settings, current session, run modes, token/LLM panels, companion/pet)

## Phase D (done)

- `useChatWorkbenchLayout.ts` — panel widths, resize drag/keyboard, responsive collapse/overlay, layout CSS vars/class names
- `chatComposerSubmitModel.ts` — composer draft/attachment/reference pure helpers, image classify, submit guards, mental-model toggle storage, optimistic turn id
- `useChatComposerSubmit.ts` — `useChatComposerTurnMutations` (submit/edit/stop/guidance) + `useChatComposerSubmitActions` (handlers/upload pipeline); no second EventSource

## Phase E (in progress)

Plan: `docs/superpowers/plans/2026-07-19-chat-coding-route-stream-selection-split.md`

- **E1 done:** `chatSessionStreamConnect.ts` + `useSessionDetailStream.ts` — sole owner of `/api/sessions/:id/events` EventSource; connect/grace pure helpers
- **E2 done:** `useGroupRoomStream.ts` — sole owner of `/api/chat-rooms/:id/events` EventSource
- **E3 done:** `useChatSessionSelection.ts` — select mutation + URL/bootstrap selection effects
- **E4a done:** `chatSessionDetailHelpers.ts` + `chatRoutePresentation.tsx` — pure detail/presentation helpers
- **E4b done:** `useChatWorkspaceLifecycle.ts` — create/delete/rename session, group CRUD/rounds, project-bus send/revoke

## Next (planned)

- Remaining route-local mutations (reasoning effort, load earlier, tool approval, pet)
- Thin `ChatCodingRoute` composition toward ~800–1500 LOC

## Rules

1. Do not open a second session stream; reuse existing stream controllers.
2. Do not change React Query key shapes in drive-by refactors.
3. Multi-line `VButton` cards use `contentLayout="plain"`.
4. Font tokens: `[font-size:var(--vui-font-*)]`, never `text-[var(--vui-font-*)]` as size.
