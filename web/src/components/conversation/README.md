# Conversation modules (`web/src/components/conversation`)

Agent-oriented map for the transcript / composer surface used by Chat and
other workbenches. Prefer editing a **pure module or turn panel** over growing
`ConversationView.tsx` when possible.

`ConversationView.tsx` remains the **shell**: props wiring, virtual timeline
window, and turn composition. Stick-bottom scroll lives in
`useConversationTimelineFollow.ts`. Process/response expansion state, the
segment parse cache, and prewarm live in `useConversationProcessExpansion.ts`.
The turn-navigator directory and live current-turn index live in
`useConversationTurnNav.ts`. In-chat SFT message curation (like/dislike) lives
in `useConversationMessageCuration.ts`. Pure presentation, timeline projection,
and tool rendering should live outside the shell.

## 30-second routing (Agent reading map)

| You are changing… | Open first |
|-------------------|------------|
| Virtual window / history window policy | `conversationHistoryWindow.ts` |
| Stick-bottom / follow-tail scroll | `useConversationTimelineFollow.ts`, `conversationTimelineFollowState.ts` |
| Process / response expansion, segment cache, prewarm | `useConversationProcessExpansion.ts`, `conversationExpansionDefaults.ts`, `conversationResponseSegmentCache.ts` |
| Turn navigator directory / current turn | `useConversationTurnNav.ts`, `conversationTurnNavigation.ts` |
| Scroll signals / anchor helpers | `conversationTimelineScrollSignals.ts`, `timelineScrollAnchor.ts` |
| Timeline rows / process projection | `agentMessageTimeline*.ts`, `timelineMessageProcessProjection.ts` |
| Operation groups / ReAct items | `agentMessageOperations.ts`, `conversationReActOperationItems.ts` |
| Operation status labels / tones | `conversationOperationState.ts` |
| Feedback / long-loop placeholders | `conversationFeedbackStatusPresentation.ts` |
| Internal streaming status markers | `conversationInternalStatus.ts` |
| Display protocol / special messages | `conversationDisplayProtocol.ts`, `conversationSpecialMessagePresentation.ts` |
| Markdown blocks / streaming markdown | `conversationMarkdownBlocks.ts`, `streamingMarkdown.ts`, `ConversationMarkdownRenderer.tsx` |
| JSON fenced code pretty-print | `conversationFormattedCodeBlock.ts` |
| Response segment labels / visibility | `conversationResponseSegmentPresentation.ts` |
| Operation / process labels & codex gates | `conversationOperationPresentation.ts` |
| Composer primary-action resolution | `conversationComposerActionModel.ts` |
| Response segment parse cache | `conversationResponseSegmentCache.ts` |
| Operation icon kind classification | `conversationOperationIconModel.ts` |
| Tool activity UI / registry | `ConversationToolActivity.tsx`, `conversationTool*`, `conversationToolRendererRegistry.tsx` |
| Task/plan tool checklists | `conversationToolChecklistModel.ts`, `ConversationToolChecklist.tsx` |
| Codex native transcript surface | `codexNativeTranscriptSurface.ts`, `codexTranscriptCells.ts`, `codexToolLifecycleModel.ts` |
| Progress/commentary narration lane | `codexTranscriptCells.ts` (lane dedupe/rules), `ConversationView.tsx` (`renderCodexProgressCell`) |
| Mental-state rows | `conversationMentalState.ts` |
| Composer shortcuts / slash commands | `composerShortcuts.ts`, `conversationSlashCommandSuggestions.ts` |
| Image artifacts / preview dialog | `ConversationImageArtifactView.tsx`, `ConversationImagePreviewDialog.tsx` |
| Turn file deliveries / recorded patches | `ConversationFileDeliveries.tsx`, `conversationFileDeliveryModel.ts`; successful native tool calls only, no session-level changed-file attribution. Content is a turn snapshot, patches are ordered operations rather than a net filesystem diff. HTML uses the shared static sandbox preview. |
| Turn navigator rail | `ConversationTurnNavigator.tsx`, `useConversationTurnNav.ts`, `conversationTurnNavigation.ts` |
| Turn avatar / header compaction | `conversationTurnAvatar.ts`, `ConversationTurnAvatarContent.tsx` |
| Agent thread bridge / projection hooks | `useAgentThread.ts`, `useAgentMessageTimelineProjection.ts` |
| Prefetch (idle warm, no mount) | `prefetchConversationView.ts`, `LazyConversationView.tsx` |
| Text-selection quote menu | `useConversationSelectionQuote.tsx` |
| Branch fork dialog state | `useConversationForkSession.ts`; dialog JSX stays in `ConversationView.tsx` |
| In-chat SFT message curation (like/dislike) | `useConversationMessageCuration.ts`, `conversationMessageCuration.ts` |
| Shell composition only | `ConversationView.tsx` |

## ConversationView block map (M6)

Approximate ownership inside the shell. Line ranges drift; use the map by
**concern**, not as a permanent LOC contract.

| Block | Concern | Prefer extract target |
|-------|---------|------------------------|
| Imports + lazy chrome | Image preview / Agent context dialogs stay lazy | keep lazy in shell |
| Row memo equality | `ConversationTurnRow` props compare | keep shell-local unless shared |
| Virtual range + heights | measured heights, prefix sums, min tail | `conversationHistoryWindow.ts` + shell measure |
| Stick-bottom follow | rAF follow / user scroll break | `useConversationTimelineFollow.ts` + `conversationTimelineFollowState.ts` |
| Turn navigator | preview text, directory, current-turn index | `useConversationTurnNav.ts` + `conversationTurnNavigation.ts` |
| Timeline projection | agent timeline items / codex cells | pure timeline modules |
| Process / response expansion | expanded tail, section defaults, segment cache, prewarm | `useConversationProcessExpansion.ts` |
| Response streaming render | streaming segments / markdown | streaming + markdown modules |
| Tool activity strip | tool lifecycle UI | `ConversationToolActivity.tsx` |
| Composer | draft, attachments, slash, submit keys | composer pure modules + Chat route hooks |
| Image preview mount | conditional React.lazy dialog | keep shell gate |
| Text-selection quote | quote / copy / reference / side-chat menu | `useConversationSelectionQuote.tsx` |
| Branch fork dialog | target message, scope, pending, open/close/submit | `useConversationForkSession.ts`; `ConversationForkSessionDialog` JSX stays in the shell |
| Message curation | optimistic overlay, failure rollback, ~3s 409/error title, session reset, companion query gate | `useConversationMessageCuration.ts`; like/dislike buttons stay in timeline rows |

## Ownership map

| Task type | Prefer | Avoid |
|-----------|--------|--------|
| Pure timeline / status / labels | matching `conversation*.ts` / `agentMessage*.ts` | shell JSX |
| Turn section UI | `Agent*SectionView.tsx`, `AgentMessageTurnView.tsx` | ChatCodingRoute |
| Stream EventSource ownership | Chat route stream hooks | ConversationView |
| Markdown / tool renderers | dedicated renderer modules | re-inlining into shell |
| Prefetch without mount | `prefetchConversationView.ts` | mounting ConversationView early |
| Timeline text-selection quote | `useConversationSelectionQuote.tsx` | stick-bottom / history-load scroll |
| Branch fork dialog state | `useConversationForkSession.ts` | route API call, or moving `ConversationForkSessionDialog` out of the shell |
| In-chat SFT message curation | `useConversationMessageCuration.ts` | copy-answer feedback, image preview, or inlining the query back into the shell |
| Process / response expansion state | `useConversationProcessExpansion.ts` | inlining section defaults back into the shell |
| Turn navigator directory | `useConversationTurnNav.ts` | inlining preview maps back into the shell |

## Structure program

| Wave | Goal | Status |
|------|------|--------|
| D2 virtual timeline | measured heights + stick-bottom | **Done** |
| M6 | ConversationView block boundaries / README | **Done** — this file |
| M8 | Shared JSON code-block pretty-print | **Done** — `conversationFormattedCodeBlock.ts` |
| C3 | Response segment label / show pure | **Done** — `conversationResponseSegmentPresentation.ts` |
| C3.1 | Operation labels / codex surface gates | **Done** — `conversationOperationPresentation.ts` |
| C3.2 | Composer action + segment-cache claims | **Done** — `conversationComposerActionModel` / `conversationResponseSegmentCache` |
| C3.3 | Operation icon kind pure claim | **Done** — `conversationOperationIconModel` |
| C3.4 | Status/process icon kinds + operation details pure | **Done** — `conversationOperationPresentation` |
| Further pure extract | only when a claim needs it | deferred |

## Rules

1. Keep pure modules free of React Query / DOM EventSource ownership.
2. Chat route owns SSE; ConversationView consumes message props / callbacks.
3. Prefer composing existing pure modules over new shell inlines.
4. Do not static-import heavy markdown/xterm graphs into the shell without a budget check.
5. Prefetch may warm the chunk; it must not mount transcript state.

## Related maps

- Chat shell ownership: `web/src/routes/chat/README.md`
- Perf baseline / chunk notes: `web/src/routes/chat/PERF_BASELINE.md`
