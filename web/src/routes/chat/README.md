# Chat route modules (`web/src/routes/chat`)

Agent-oriented map for Chat workbench development. Prefer editing a **module** over the workbench shell when possible.

## Entry (R01)

| Path | Role |
|------|------|
| `web/src/routes/ChatCodingRoute.tsx` | **Thin re-export only** (router/layout import path) |
| `web/src/routes/chat/ChatCodingRouteWorkbench.tsx` | Workbench implementation shell (still thick; do not grow without extract) |

```text
ChatCodingRoute.tsx → re-export ChatCodingRouteWorkbench
```

## Route selection authority (ADR 0009)

The committed React Router URL is the **single authority** for the current
Chat surface. Rules:

- Only `useChatRouteSelection.ts` writes Chat routes:
  `openSession` / `openRoom` / `openProjectBus` / `canonicalizeBareRoute` /
  `replaceIfStillViewing`. No other module may build `/chat?session=` or
  `/chat?room=` navigation, call `window.history.pushState/replaceState`, or
  store an active session in Zustand/local state.
- `chatSelectionProjection.ts` owns the `ChatRouteSelection` discriminated
  union (`session` / `room` / `project_bus` / `bare` / `invalid`) and the pure
  serialize/compare helpers; `activeSessionId` / `activeGroupRoomId` are
  derived locally from the route only.
- Async lifecycle results (create temp→real, delete, archive, clear history,
  group create/delete, late `/select`) must compare-and-swap via
  `replaceIfStillViewing`; a user who already navigated away keeps their page
  and only caches are updated.
- Explicit missing/archived session URLs stay put and render the unavailable
  surface; bare `/chat` canonicalizes once per `location.key` from
  localStorage → server pointer → first visible session.
- `chatWorkbenchStore` keeps per-session workspaces only (tabs, draft). Machine
  gates: `chatRouteWriteBoundary.test.ts`, `useChatRouteSelection.test.tsx`,
  `useChatSessionSelection.test.tsx`, `AppShellNavigationTelemetry.test.ts`.

## Ownership map (claim scopes)

| Task type | Prefer these files | Avoid |
|-----------|-------------------|--------|
| CLI terminal tabs / lifecycle | `cliAgentRunModel.ts`, `useChatCliAgentTerminal.ts`, `CliAgentRunTerminalPanel.tsx` | composer submit |
| Cache / token donut pure math | `sessionCacheComposition.ts`, `chatCacheDetailModel.ts`, `useChatCacheDetailDialog.ts`, `CacheDetailDialog.tsx`, `TokenCoreStatusPanel.tsx` | stream apply |
| Token status metrics (cache/input/compression/speed) | `chatTokenStatusModel.ts`, `TokenCoreStatusPanel.tsx` | stream apply |
| Feature presets labels | `chatFeaturePresets.ts` | detail stream |
| Tool approval copy | `toolApprovalLabels.ts`, `ChatToolApprovalDialog.tsx` | left rail JSX |
| Submit telemetry fields | `chatSubmitTelemetry.ts` | layout resize |
| Composer draft/attachments/submit pure helpers | `chatComposerSubmitModel.ts` | stream apply, dual EventSource |
| Running-turn follow-up queue | `../components/conversation/composerFollowupQueueModel.ts` + `ConversationFollowupQueueBar.tsx` | edit-resubmit, stream apply |
| Composer turn mutations + submit actions | `useChatComposerSubmit.ts` | session EventSource ownership |
| Session stream connect/grace pure helpers | `chatSessionStreamConnect.ts` | opening EventSource |
| Direct session detail SSE (sole EventSource) | `useSessionDetailStream.ts` | second session EventSource, group stream |
| Desktop conversation completion notifications | `../chatDesktopNotifications.ts` + `useDesktopConversationAttention.ts` | second EventSource, backend Windows APIs |
| Group room SSE (sole EventSource) | `useGroupRoomStream.ts` | second group EventSource, session stream |
| Catalog / secondary queries (runtime·pet·index·teams·skills·rooms) | `useChatWorkbenchCatalogQueries.ts` | session detail SSE, composer submit |
| Session select / URL / bootstrap | `useChatSessionSelection.ts` (committed-route preference sync) | EventSource ownership || Session detail window / ledger / conversation merge | `chatSessionDetailHelpers.ts` | stream EventSource |
| Labels / avatar / group message presentation | `chatRoutePresentation.tsx` | mutations / stream |
| Session catalog / tabs | `useChatVisibleSessionCatalog.ts` · `chatVisibleSessionCatalogModel.ts` · `useChatAgentSessionTabs.ts` | stream, confirm |
| Group room chrome / team linkage | `useChatGroupRoomChromeModel.ts` · `chatGroupTeamLinkageModel.ts` | stream, route writes |
| Session index rail chrome | `useChatSessionIndexRailModel.ts` · `chatSessionIndexRailPresentation.ts` | stream apply |
| Session bulk select / remove | `useChatSessionBulkSelection.ts` | stream, confirm dialog |
| Danger confirm dialogs | `useChatWorkbenchConfirmDialog.ts` | mutation implementations |
| Session detail mutations (reasoning/history/tool/pet) | `useChatSessionDetailMutations.ts` | EventSource, lifecycle |
| Workspace UI action handlers | `useChatWorkspaceActions.ts` | EventSource, JSX render |
| Group message / @mention presentation | `ChatGroupMessagePresentation.tsx` | mutations |
| Group / project-bus center surface | `ChatGroupCenterSurface.tsx` | stream EventSource, left rail |
| CLI terminal mount stack | `ChatCliAgentTerminalStack.tsx` | stream EventSource |
| Session surface / skill / mental / pet / tabs pure models | `chatSessionSurfaceModel.ts` | stream EventSource |
| Session rename + context menu | `useChatSessionRenameMenu.ts` | stream |
| Composer bridge UI | `ChatConversationComposerBridge.tsx` | CLI model |
| Center workspace shell | `ChatSessionWorkspacePanel.tsx` | index rail |
| Layout width math | `chatCodingRouteViewModel.ts` | session protocol |
| Shell layout / resize / responsive panes | `useChatWorkbenchLayout.ts` | stream/submit |
| Left index / new Agent / group / system entry UI | `ChatConversationIndexRail.tsx` | stream/submit |
| Right status / run modes / token / pet / group settings | `ChatStatusRail.tsx` | left index, stream apply |
| Orchestration / wiring only | `ChatCodingRouteWorkbench.tsx` (prefer extract first) | thin entry `ChatCodingRoute.tsx` |

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

## Phase E (done for structure ROI)

Historical plan (archived): `docs/archive/superpowers/plans/2026-07-19-chat-coding-route-stream-selection-split.md`

- **E1–E4i done:** stream selection split, workspace hooks, surface models, center surfaces
- **D2 (ROI queue):** `conversationFeedbackStatusPresentation.ts` — feedback status placeholder pure boundary for `ConversationView` (projection vs shell)

## Phase F (R01c — Gate 3 done)

- **F1 done:** `useChatWorkbenchCatalogQueries.ts` — runtime/pet/config/session-index/conversations/teams/agents/skills/chat-room catalog + expanded agent detail queries
- **F2 done:** `useChatToolApprovalBridge.ts` (governance & session tool approval), `useChatComposerBridgeState.ts` (composer draft, follow-up queue & bridge state), `useChatGroupRoomViewModel.ts` (group room identity, candidate agents & modes). Index tree JSX stays in the workbench until a typed owner can take it without a fat prop dump.
- **F3 done (Gate 3):** `useChatGroupDraftState` + `chatGroupRoomActionModel` own group composer/manage drafts and action flags; `useChatWorkbenchContextMenus` owns session/agent menu chrome; `useChatConversationIndexChrome` owns collapsed groups / members tab; Agent create wizard open state lives in `useChatAgentDirectoryActions`; direct-session prefetch is wired through `useChatWorkspaceActions`. Shell remains `ChatSessionWorkbenchShell` → `VSessionWorkbenchPage` (`WORKBENCH_LAYOUT_IDS.chat`) with lazy secondary panels. **G3-3 closed without extra memoization** — no new render/interaction finding; `ChatCodingRouteWorkbench.updateDepth.test.tsx` remains the update-depth guard.
- **F4 (Wave 1-A):** `useChatSessionBulkSelection` owns session-list bulk select/remove; `useChatWorkbenchConfirmDialog` owns danger confirm state + presentation (delete session/history, delete/reset group).
- **F4b (Wave 1-A cont.):** `useChatVisibleSessionCatalog` owns visible session merge/map + activity seen; `useChatAgentSessionTabs` owns per-agent tab query; `useChatSessionIndexRailModel` owns group-only index groups + load-more progress labels.
- **F4c (Wave 1-A cont.):** `useChatGroupRoomChromeModel` owns team↔room linkage, group participant maps, expanded-agent detail sync, and group manage/delete/reset/stop disabled flags; pure linkage in `chatGroupTeamLinkageModel.ts`.
- **F4d (Wave 1-A alignment):** catalog/index pure boundaries — `chatVisibleSessionCatalogModel.ts`, `chatSessionIndexRailPresentation.ts`, explicit `toSessionIndexProgressQuerySlice`; hook exports trimmed to workbench-used fields.

## Bundle note (secondary lazy)

`ChatCodingRoute` keeps these off the initial Chat chunk via `React.lazy` + conditional mount:

- `CliAgentRunTerminalPanel` (xterm graph)
- `AgentCreateWizardDialog` (create Agent modal)
- `CacheDetailDialog` / `SessionContextMenu`
- `LlmPayloadTracePanel` (from `ChatStatusRail` when trace present)

Do not re-add static imports of those modules into the Chat shell without a budget re-check.

## ConversationView boundary (D2 + M6)

Timeline message rendering lives under `web/src/components/conversation/`.
Prefer pure modules there over growing `ConversationView.tsx`.

**Full block map / 30-second routing:** `web/src/components/conversation/README.md` (M6).

| Task type | Prefer | Avoid |
|-----------|--------|--------|
| Feedback status placeholder / long-loop labels | `conversationFeedbackStatusPresentation.ts` | ConversationView JSX |
| Internal streaming status markers | `conversationInternalStatus.ts` | route shell |
| Operation groups / timeline rows | `agentMessageOperations.ts`, `agentMessageTimeline*.ts` | ChatCodingRoute |
| Virtual window / stick-bottom | `conversationHistoryWindow.ts`, `conversationTimelineFollowState.ts` | ChatCodingRoute |
| Stream EventSource ownership | `useSessionDetailStream.ts` / `useGroupRoomStream.ts` | ConversationView |

## Live load policy (P1/P5)

| Concern | Owner |
|---------|--------|
| When to open session SSE | `chatSessionStreamConnect.ts` + `useSessionDetailStream.ts` |
| Stop list/detail polling only when SSE is **open** | `chatLiveQueryPolicy.ts` (`sessionStreamConnected` / `groupStreamConnected`) |
| Session switch shell + cancel foreign detail fetches | `chatSessionDetailHelpers.ts` (`resolveSessionDetailPlaceholder`, `isForeignSessionDetailQueryKey`) |

Do not suppress polling on connect *intent* alone — wait for EventSource `onopen`.

## Perf program (scope A)

See `PERF_BASELINE.md` for F0 numbers and gaps.

| Phase | Status |
|---|---|
| F0 baseline | Done (`PERF_BASELINE.md`) |
| F1 soft chat preload (idle hover/focus, hard click) | Done in AppShell |
| F1 markdown / xterm lazy | Already in place (do not regress) |
| F2 expanded group agent polls honor SSE open | Done in ChatCodingRoute |
| F2 core session/list policy | Already in `chatLiveQueryPolicy` |
| R1 secondary chrome polls | `chatSecondaryPollPolicy` — runtime 20s / pet 30s / teams gated / project bus 8s |

## Next (planned)

- Prefer chunk wins over further pure LOC grind on `ChatCodingRoute` (already hook/panel split; Gate 3 closed)
- ConversationView block map is documented (M6); further pure extracts only when claimability requires it
- Target `ChatCodingRoute` toward ~800–1500 LOC only when a concrete claim needs it
- Agents structure M1–M3 and Teams/Evolution M4–M5 are on local main; see lane READMEs

## Hand-test substitutes

Prefer automated substitutes over manual click smoke when validating Chat split work:

```bash
npm --prefix web test -- --run src/routes/chat/chatHandTestSubstitute.test.ts src/routes/chat/ChatGroupCenterSurface.test.tsx src/routes/chat/cliAgentRunModel.test.ts src/routes/chat/chatGroupRoomActionModel.test.ts
```

- `chatHandTestSubstitute.test.ts` — maps hand checklist to pure models, stream ownership, wiring contracts, and optional live `/api`+SSE probe when workbench is up
- `ChatGroupCenterSurface.test.tsx` — SSR markup for group/bus empty/active states
- `cliAgentRunModel.test.ts` — CLI tab id / close-active / tool-call run extraction

## Rules

1. Do not open a second session stream; reuse existing stream controllers.
2. Do not change React Query key shapes in drive-by refactors.
3. Multi-line `VButton` cards use `contentLayout="plain"`.
4. Font tokens: `[font-size:var(--vui-font-*)]`, never `text-[var(--vui-font-*)]` as size.
