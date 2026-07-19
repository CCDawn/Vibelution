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

## Phase D (done / in progress)

- `useChatWorkbenchLayout.ts` — panel widths, resize drag/keyboard, responsive collapse/overlay, layout CSS vars/class names
- `chatComposerSubmitModel.ts` — composer draft/attachment/reference pure helpers, image classify, submit guards, mental-model toggle storage, optimistic turn id

## Next (planned)

- Hooks: selection/detail+stream, full composer submit/mutation hook, group room
- Thin `ChatCodingRoute` composition + layout test split

## Rules

1. Do not open a second session stream; reuse existing stream controllers.
2. Do not change React Query key shapes in drive-by refactors.
3. Multi-line `VButton` cards use `contentLayout="plain"`.
4. Font tokens: `[font-size:var(--vui-font-*)]`, never `text-[var(--vui-font-*)]` as size.
