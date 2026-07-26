# Conversation modules (`web/src/components/conversation`)

Agent-oriented map for the transcript / composer surface used by Chat and
other workbenches. Prefer editing a **pure module or turn panel** over growing
`ConversationView.tsx` when possible.

`ConversationView.tsx` remains the **shell**: props wiring, expansion state,
virtual timeline window, stick-bottom scroll, composer submit/edit, and turn
composition. Pure presentation, timeline projection, and tool rendering should
live outside the shell.

## 30-second routing (Agent reading map)

| You are changing… | Open first |
|-------------------|------------|
| Virtual window / history window policy | `conversationHistoryWindow.ts` |
| Stick-bottom / follow-tail scroll state | `conversationTimelineFollowState.ts` |
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
| Tool activity UI / registry | `ConversationToolActivity.tsx`, `conversationTool*`, `conversationToolRendererRegistry.tsx` |
| Codex native transcript surface | `codexNativeTranscriptSurface.ts`, `codexTranscriptCells.ts`, `codexToolLifecycleModel.ts` |
| Mental-state rows | `conversationMentalState.ts` |
| Composer shortcuts / slash commands | `composerShortcuts.ts`, `conversationSlashCommandSuggestions.ts` |
| Image artifacts / preview dialog | `ConversationImageArtifactView.tsx`, `ConversationImagePreviewDialog.tsx` |
| Turn avatar / header compaction | `conversationTurnAvatar.ts`, `ConversationTurnAvatarContent.tsx` |
| Agent thread bridge / projection hooks | `useAgentThread.ts`, `useAgentMessageTimelineProjection.ts` |
| Prefetch (idle warm, no mount) | `prefetchConversationView.ts`, `LazyConversationView.tsx` |
| Shell composition only | `ConversationView.tsx` |

## ConversationView block map (M6)

Approximate ownership inside the shell. Line ranges drift; use the map by
**concern**, not as a permanent LOC contract.

| Block | Concern | Prefer extract target |
|-------|---------|------------------------|
| Imports + lazy chrome | Image preview / Agent context dialogs stay lazy | keep lazy in shell |
| Row memo equality | `ConversationTurnRow` props compare | keep shell-local unless shared |
| Virtual range + heights | measured heights, prefix sums, min tail | `conversationHistoryWindow.ts` + shell measure |
| Stick-bottom follow | rAF follow / user scroll break | `conversationTimelineFollowState.ts` |
| Timeline projection | agent timeline items / codex cells | pure timeline modules |
| Process / operation expansion | process disclosure state | `ConversationProcessDisclosure.tsx` + pure state |
| Response streaming render | streaming segments / markdown | streaming + markdown modules |
| Tool activity strip | tool lifecycle UI | `ConversationToolActivity.tsx` |
| Composer | draft, attachments, slash, submit keys | composer pure modules + Chat route hooks |
| Image preview mount | conditional React.lazy dialog | keep shell gate |

## Ownership map

| Task type | Prefer | Avoid |
|-----------|--------|--------|
| Pure timeline / status / labels | matching `conversation*.ts` / `agentMessage*.ts` | shell JSX |
| Turn section UI | `Agent*SectionView.tsx`, `AgentMessageTurnView.tsx` | ChatCodingRoute |
| Stream EventSource ownership | Chat route stream hooks | ConversationView |
| Markdown / tool renderers | dedicated renderer modules | re-inlining into shell |
| Prefetch without mount | `prefetchConversationView.ts` | mounting ConversationView early |

## Structure program

| Wave | Goal | Status |
|------|------|--------|
| D2 virtual timeline | measured heights + stick-bottom | **Done** |
| M6 | ConversationView block boundaries / README | **Done** — this file |
| M8 | Shared JSON code-block pretty-print | **Done** — `conversationFormattedCodeBlock.ts` |
| C3 | Response segment label / show pure | **Done** — `conversationResponseSegmentPresentation.ts` |
| C3.1 | Operation labels / codex surface gates | **Done** — `conversationOperationPresentation.ts` |
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
