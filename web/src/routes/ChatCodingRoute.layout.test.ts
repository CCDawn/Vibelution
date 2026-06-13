import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import conversationStyles from "../components/conversation/ConversationView.module.css";
import shellStoreSource from "../store/shellStore.ts?raw";
import agentSessionTabStripSource from "./AgentSessionTabStrip.tsx?raw";
import routeSource from "./ChatCodingRoute.tsx?raw";
import conversationIndexModelSource from "./conversationIndexModel.ts?raw";
import conversationIndexTreeSource from "./ConversationIndexTree.tsx?raw";
import conversationIndexSectionSource from "./ConversationIndexSection.tsx?raw";
import directSessionIndexItemSource from "./DirectSessionIndexItem.tsx?raw";
import directSessionIndexListSource from "./DirectSessionIndexList.tsx?raw";
import groupSessionIndexItemsSource from "./GroupSessionIndexItems.tsx?raw";
import sessionContextMenuSource from "./SessionContextMenu.tsx?raw";
import routeStyles from "./ChatCodingRoute.module.css";

const routeCssSource = readFileSync(new URL("./ChatCodingRoute.module.css", import.meta.url), "utf-8");
const conversationCssSource = readFileSync(new URL("../components/conversation/ConversationView.module.css", import.meta.url), "utf-8");

describe("ChatCodingRoute layout contract", () => {
  it("keeps the center conversation readable and the composer as a stable bottom layer", () => {
    expect(conversationStyles.timeline).toBeTypeOf("string");
    expect(conversationStyles.markdownBody).toBeTypeOf("string");
    expect(conversationStyles.operationSummary).toBeTypeOf("string");
    expect(conversationStyles.composer).toBeTypeOf("string");
    expect(conversationStyles.sendButton).toBeTypeOf("string");
    expect(conversationStyles.assistantTurn).toBeTypeOf("string");
    expect(conversationStyles.turnContent).toBeTypeOf("string");
    expect(conversationStyles.responseSegment_status).toBeTypeOf("string");
    expect(conversationStyles.userMessageBody).toBeTypeOf("string");
    expect(conversationStyles.messageBody).toBeTypeOf("string");
    expect(conversationStyles.imageArtifact).toBeTypeOf("string");
    expect(conversationStyles.imageDownloadButton).toBeTypeOf("string");
  });

  it("renders runtime notices outside the Agent reply timeline", () => {
    expect(routeSource).toContain("detail?.runtimeNotices");
    expect(routeSource).toContain(".slice(-1)");
    expect(routeSource).toContain("styles.runtimeNoticeStack");
    expect(routeSource).toContain("styles.runtimeNoticeMessage");
    expect(routeSource.indexOf("styles.runtimeNoticeStack")).toBeLessThan(
      routeSource.indexOf("<LazyConversationView"),
    );
    expect(routeStyles.runtimeNoticeStack).toBeTypeOf("string");
    expect(routeStyles.runtimeNotice).toBeTypeOf("string");
    expect(routeStyles.runtimeNotice_warning).toBeTypeOf("string");
    expect(routeStyles.runtimeNoticeMessage).toBeTypeOf("string");
  });

  it("loads the heavy conversation renderer through a lazy bridge", () => {
    expect(routeSource).toContain("LazyConversationView");
    expect(routeSource).toContain("conversationConstants");
    expect(routeSource).toContain("fallback={<div className={styles.emptySurface}>{t(\"loadingSession\")}</div>}");
    expect(routeSource).not.toContain('import { COMPOSER_SESSION_REFERENCE_MIME, ConversationView } from "../components/conversation/ConversationView"');
  });

  it("passes agent avatar context into the conversation timeline", () => {
    expect(routeSource).toContain("assistantAvatarImageUrl={activeAgentAvatarImageUrl}");
    expect(routeSource).toContain("assistantAvatarFallback={activeAgentAvatarFallback}");
    expect(routeSource).toContain("resolveTurnAvatar={resolveConversationTurnAvatar}");
    expect(routeSource).toContain("resolveConversationTurnAvatar");
    expect(routeSource).toContain("agentsByCode");
    expect(conversationStyles.turnAvatarImage).toBeTypeOf("string");
  });

  it("keeps side panes collapsible while allowing narrow screens to prioritize the center pane", () => {
    expect(routeSource).toContain("CHAT_CENTER_FIRST_MEDIA_QUERY");
    expect(routeSource).toContain("centerFirstLayout");
    expect(routeSource).toContain("centerFirstAutoCollapseRef");
    expect(routeSource).toContain("window.matchMedia(CHAT_CENTER_FIRST_MEDIA_QUERY)");
    expect(routeSource).toContain("const MIN_LEFT_PANEL_WIDTH = 192");
    expect(routeSource).toContain("const MIN_RIGHT_PANEL_WIDTH = 244");
    expect(routeSource).toContain("const TARGET_CENTER_PANE_WIDTH = 520");
    expect(routeSource).toContain("styles.layoutCenterFirst");
    expect(routeStyles.layout).toBeTypeOf("string");
    expect(routeStyles.layoutCenterFirst).toBeTypeOf("string");
    expect(routeStyles.leftRail).toBeTypeOf("string");
    expect(routeStyles.rightPane).toBeTypeOf("string");
    expect(routeStyles.resizeHandle).toBeTypeOf("string");
    expect(routeStyles.centerPane).toBeTypeOf("string");
    expect(routeCssSource).toContain("var(--chat-left-pane-width, 220px)");
    expect(routeCssSource).toContain("var(--chat-right-pane-width, 284px)");
  });

  it("defaults Chat to dense side panes so the center conversation has priority", () => {
    expect(shellStoreSource).toContain("leftPanelWidth: 220");
    expect(shellStoreSource).toContain("rightPanelWidth: 284");
    expect(routeSource).toContain('"--chat-left-pane-width": leftRailCollapsed ? "0px" : `${leftPanelWidth}px`');
    expect(routeSource).toContain('"--chat-right-pane-width": rightPaneCollapsed ? "0px" : `${rightPanelWidth}px`');
    expect(routeCssSource).toContain(".leftRail {\n  display: flex;\n  flex-direction: column;\n  gap: 5px;\n  padding: 6px;");
    expect(routeCssSource).toContain(".rightPane {\n  display: grid;\n  grid-template-rows: auto auto 1fr;\n  padding: 6px;");
    expect(routeCssSource).toContain("padding: 8px 10px 0");
    expect(routeCssSource).not.toContain(".sessionAgentStatusControl");
  });

  it("keeps the conversation index compact enough for 1024px workbench use", () => {
    expect(routeCssSource).toContain("grid-template-columns: 32px minmax(0, 1fr)");
    expect(routeCssSource).toContain("min-height: 46px");
    expect(routeCssSource).toContain("width: 32px");
    expect(routeCssSource).toContain("height: 32px");
    expect(routeCssSource).toContain("font-size: 0.7rem");
    expect(routeCssSource).toContain("font-size: 0.66rem");
    expect(routeCssSource).toContain("max-width: 124px");
    expect(conversationCssSource).toContain(".surfaceCompact .timeline {\n  padding: 10px 14px 12px;");
    expect(conversationCssSource).toContain(".surfaceCompact .composer {\n  gap: 8px;\n  padding: 7px 11px 9px;");
  });

  it("clamps responsive side panes so the center conversation remains visible near 1024px", () => {
    expect(routeCssSource).toContain("@media (max-width: 980px)");
    expect(routeCssSource).toContain("minmax(0, min(var(--chat-left-pane-width, 0px), 24vw))");
    expect(routeCssSource).toContain("minmax(360px, 1fr)");
    expect(routeCssSource).toContain("minmax(0, min(var(--chat-right-pane-width, 0px), 22vw))");
    expect(routeCssSource).toContain("minmax(280px, 1fr)");
  });

  it("compresses the left rail into primary controls plus auxiliary status groups", () => {
    expect(routeSource).toContain("styles.resourceBlock");
    expect(routeSource).toContain("styles.resourceSplit");
    expect(routeSource).toContain("styles.compressionFactGrid");
    expect(routeSource).toContain("styles.compressionFactWide");
    expect(routeSource).toContain("styles.sessionDiagnosticsDetails");
    expect(routeSource).toContain("styles.sessionResourceDiagnostics");
    expect(routeSource).toContain("styles.companionBlock");
    expect(routeSource).toContain("styles.companionCompact");
    expect(routeSource).toContain("styles.petMiniAvatar");
    expect(routeSource).toContain("styles.featurePrimarySlot");
    expect(routeSource).toContain("styles.featureChipRow");
    expect(routeSource).toContain("styles.featureChip");
    expect(routeSource).not.toContain("<section className={styles.petShowcase}");
    expect(routeSource).not.toContain("styles.featurePresetGrid");

    expect(routeStyles.resourceBlock).toBeTypeOf("string");
    expect(routeStyles.resourceSplit).toBeTypeOf("string");
    expect(routeStyles.compressionFactGrid).toBeTypeOf("string");
    expect(routeStyles.compressionFact).toBeTypeOf("string");
    expect(routeStyles.compressionFactWide).toBeTypeOf("string");
    expect(routeStyles.sessionDiagnosticsDetails).toBeTypeOf("string");
    expect(routeStyles.sessionDiagnosticsSummary).toBeTypeOf("string");
    expect(routeStyles.sessionDiagnosticsSnapshot).toBeTypeOf("string");
    expect(routeStyles.sessionDiagnosticsBody).toBeTypeOf("string");
    expect(routeStyles.sessionResourceDiagnostics).toBeTypeOf("string");
    expect(routeStyles.companionBlock).toBeTypeOf("string");
    expect(routeStyles.companionCompact).toBeTypeOf("string");
    expect(routeStyles.petMiniAvatar).toBeTypeOf("string");
    expect(routeStyles.featurePrimarySlot).toBeTypeOf("string");
    expect(routeStyles.featureChipRow).toBeTypeOf("string");
    expect(routeStyles.featureChip).toBeTypeOf("string");
  });

  it("keeps group settings in the left rail and moves member status into the right index", () => {
    expect(routeSource).toContain("expandedGroupAgentSessionIds");
    expect(routeSource).toContain("useQueries");
    expect(routeSource).toContain("expandedGroupAgentDetailQueries");
    expect(routeSource).toContain("isAvailableGroupParticipant");
    expect(routeSource).toContain("availableGroupParticipants");
    expect(routeSource).toContain("groupParticipantIdentity");
    expect(routeSource).toContain("formatAgentIdentityWithRole");
    expect(routeSource).toContain("rightIndexPanel");
    expect(routeSource).toContain("setRightIndexPanel(\"members\")");
    expect(routeSource).toContain("latestMentalSnapshot");
    expect(routeSource).toContain("styles.groupProfileBlock");
    expect(routeSource).toContain("styles.rightIndexTabs");
    expect(routeSource).toContain("styles.agentIndexRoster");
    expect(routeSource).toContain("styles.agentIndexHeader");
    expect(routeSource).toContain("styles.agentIndexExpandButton");
    expect(routeSource).toContain("styles.agentIndexOpenButton");
    expect(routeSource).toContain("onClick={() => handleOpenDirectSession(participant.sessionId)}");
    expect(routeSource).toContain("avatarImageUrlFrom(participantAgent, participant)");
    expect(routeSource).toContain("styles.agentAvatarImage");
    expect(routeSource).toContain("styles.agentIndexNameLine");
    expect(routeSource).toContain("styles.agentIndexEmptyState");
    expect(routeSource).toContain("aria-expanded={expanded}");
    expect(routeSource).toContain("只展示可用成员；已归档或断链的历史成员保留在日志里，不在这里打扰。");
    expect(routeSource).toContain("暂无可用群成员。请在左侧群设置中选择成员并应用变更。");
    expect(routeSource).not.toContain("添加群成员");
    expect(routeSource).not.toContain("Add members");
    expect(routeSource).not.toContain("已从群聊调度中停用");
    expect(routeSource.indexOf("styles.groupProfileBlock")).toBeLessThan(
      routeSource.indexOf("<aside className={rightPaneCollapsed"),
    );
    expect(routeSource.indexOf("styles.agentIndexRoster")).toBeGreaterThan(
      routeSource.indexOf("<aside className={rightPaneCollapsed"),
    );

    expect(routeStyles.groupProfileBlock).toBeTypeOf("string");
    expect(routeStyles.rightIndexTabs).toBeTypeOf("string");
    expect(routeStyles.rightIndexTab).toBeTypeOf("string");
    expect(routeStyles.memberIndexSummary).toBeTypeOf("string");
    expect(routeStyles.agentIndexRoster).toBeTypeOf("string");
    expect(routeStyles.agentIndexList).toBeTypeOf("string");
    expect(routeStyles.agentIndexCard).toBeTypeOf("string");
    expect(routeStyles.agentIndexHeader).toBeTypeOf("string");
    expect(routeStyles.agentIndexExpandButton).toBeTypeOf("string");
    expect(routeStyles.agentIndexOpenButton).toBeTypeOf("string");
    expect(routeStyles.agentIndexNameLine).toBeTypeOf("string");
    expect(routeStyles.agentIndexDetails).toBeTypeOf("string");
    expect(routeStyles.agentIndexMentalBlock).toBeTypeOf("string");
    expect(routeStyles.agentIndexEmptyState).toBeTypeOf("string");
  });

  it("hides the right index tab switcher when only the conversation index is available", () => {
    const rightAsideStart = routeSource.indexOf("<aside className={rightPaneCollapsed");
    const tabsRenderStart = routeSource.indexOf("{legacyGroupRoomActive ? (", rightAsideStart);
    const tabsClassStart = routeSource.indexOf("className={styles.rightIndexTabs}", tabsRenderStart);
    const memberSummaryStart = routeSource.indexOf("{rightIndexPanel === \"members\" && legacyGroupRoomActive", tabsClassStart);
    expect(rightAsideStart).toBeGreaterThan(-1);
    expect(tabsRenderStart).toBeGreaterThan(rightAsideStart);
    expect(tabsClassStart).toBeGreaterThan(tabsRenderStart);
    expect(tabsClassStart).toBeLessThan(memberSummaryStart);
    expect(routeSource).not.toContain("rightIndexTabsSingle");
  });

  it("keeps prompt cache observation visible in the current session status strip", () => {
    expect(routeSource).toContain("const sessionCacheUsage = detail?.cacheUsage");
    expect(routeSource).toContain("sessionCacheUsage?.source === \"provider_usage\"");
    expect(routeSource).toContain("sessionCacheUsage?.source === \"not_called\"");
    expect(routeSource).toContain("label: t(\"promptCache\")");
    expect(routeSource).toContain("turnCachedInputTokens");
    expect(routeSource).toContain("cacheCreationInputTokens");
    expect(routeSource).toContain("turnInputTokens");
    expect(routeSource).toContain("turnCacheHitRate");
    expect(routeSource).toContain("cacheHitNotCalled");
    expect(routeSource).toContain("cacheHitMissing");
  });

  it("folds previous-turn context and cache composition into session diagnostics", () => {
    expect(routeSource).toContain("const lastContextComposition = detail?.lastContextComposition ?? null");
    expect(routeSource).toContain("const lastCacheComposition = detail?.lastCacheComposition ?? null");
    expect(routeSource).toContain("<details className={styles.sessionDiagnosticsDetails}>");
    expect(routeSource).toContain("<summary className={styles.sessionDiagnosticsSummary}>");
    expect(routeSource).not.toContain("<details className={styles.sessionDiagnosticsDetails} open");
    expect(routeSource).toContain("t(\"contextDiagnostics\")");
    expect(routeSource).toContain("styles.sessionDiagnosticsSnapshot");
    expect(routeSource).toContain("styles.contextCompositionPanel");
    expect(routeSource).toContain("t(\"previousContextComposition\")");
    expect(routeSource).toContain("t(\"previousCacheHit\")");
    expect(routeSource).toContain("contextCompositionSegmentClass(segment.key)");
    expect(routeSource).toContain("const contextCompositionLimitTokens = Math.max(");
    expect(routeSource).toContain("contextWindowSegmentWidth(segment.tokens ?? 0, contextCompositionLimitTokens)");
    expect(routeSource).toContain("contextCompositionRemainingTokens");
    expect(routeSource).toContain("styles.contextCompositionSegmentExact");
    expect(routeSource).toContain("styles.contextCompositionSegmentUnused");
    expect(routeSource).toContain("cacheCompositionSegmentClass(segment.key)");
    expect(routeSource).toContain("case \"cache_write\"");
    expect(routeSource).toContain("cacheCreationInputTokens");
    expect(routeSource.indexOf("styles.sessionDiagnosticsDetails")).toBeGreaterThan(routeSource.indexOf("sessionCompactRows.map"));
    expect(routeSource.indexOf("styles.contextCompositionPanel")).toBeGreaterThan(routeSource.indexOf("styles.sessionDiagnosticsBody"));
    expect(routeSource).toContain("lastCacheComposition.source === \"not_called\"");
    expect(routeSource.indexOf("styles.contextCompositionPanel")).toBeGreaterThan(routeSource.indexOf("sessionCompactRows.map"));
    expect(routeSource.indexOf("styles.contextCompositionPanel")).toBeLessThan(routeSource.indexOf("<aside className={rightPaneCollapsed"));

    expect(routeStyles.sessionDiagnosticsDetails).toBeTypeOf("string");
    expect(routeStyles.sessionDiagnosticsSummary).toBeTypeOf("string");
    expect(routeStyles.sessionDiagnosticsSummaryText).toBeTypeOf("string");
    expect(routeStyles.sessionDiagnosticsSnapshot).toBeTypeOf("string");
    expect(routeStyles.sessionDiagnosticsBody).toBeTypeOf("string");
    expect(routeStyles.contextCompositionPanel).toBeTypeOf("string");
    expect(routeStyles.contextCompositionBar).toBeTypeOf("string");
    expect(routeStyles.contextCompositionLegend).toBeTypeOf("string");
    expect(routeStyles.contextCompositionSegmentCached).toBeTypeOf("string");
    expect(routeStyles.contextCompositionSegmentCacheWrite).toBeTypeOf("string");
    expect(routeStyles.contextCompositionSegmentUncached).toBeTypeOf("string");
    expect(routeStyles.contextCompositionSegmentMissing).toBeTypeOf("string");
    expect(routeStyles.contextCompositionSegmentExact).toBeTypeOf("string");
    expect(routeStyles.contextCompositionSegmentUnused).toBeTypeOf("string");
  });

  it("shows the active skill contract inside session diagnostics", () => {
    expect(routeSource).toContain("type ActiveSkillContract = {");
    expect(routeSource).toContain("type SessionDetailWithActiveSkill = SessionDetail &");
    expect(routeSource).toContain("const activeSkillContract = (detail as SessionDetailWithActiveSkill | undefined)?.activeSkillContract ?? null");
    expect(routeSource).toContain("const activeSkillStatusLabel = activeSkillStatus === \"stale\"");
    expect(routeSource).toContain("styles.activeSkillStatus_stale");
    expect(routeSource).toContain("styles.activeSkillStatus_missing");
    expect(routeSource).toContain("const activeSkillTitle = activeSkillContract");
    expect(routeSource).toContain("className={`${styles.activeSkillStatus} ${activeSkillStatusClass}`}");
    expect(routeSource).toContain("styles.activeSkillIdentity");
    expect(routeSource).toContain("styles.activeSkillMeta");
    expect(routeSource).toContain("case \"active_skill\":");
    const renderedActiveSkillIndex = routeSource.indexOf("className={`${styles.activeSkillStatus} ${activeSkillStatusClass}`}");
    expect(renderedActiveSkillIndex).toBeGreaterThan(routeSource.indexOf("styles.sessionDiagnosticsBody"));
    expect(renderedActiveSkillIndex).toBeLessThan(routeSource.indexOf("styles.contextCompositionPanel"));

    expect(routeStyles.activeSkillStatus).toBeTypeOf("string");
    expect(routeStyles.activeSkillStatus_active).toBeTypeOf("string");
    expect(routeStyles.activeSkillStatus_stale).toBeTypeOf("string");
    expect(routeStyles.activeSkillStatus_missing).toBeTypeOf("string");
    expect(routeStyles.activeSkillIdentity).toBeTypeOf("string");
    expect(routeStyles.activeSkillEyebrow).toBeTypeOf("string");
    expect(routeStyles.activeSkillMeta).toBeTypeOf("string");
    expect(routeStyles.activeSkillState).toBeTypeOf("string");
  });

  it("shows provider-observed LLM input separately from session context estimates", () => {
    expect(routeSource).toContain("const sessionLlmUsage = detail?.llmUsage ?? null");
    expect(routeSource).toContain("sessionLlmUsage?.source === \"provider_usage\"");
    expect(routeSource).toContain("sessionLlmUsage?.source === \"not_called\"");
    expect(routeSource).toContain("label: t(\"llmInputTokens\")");
    expect(routeSource).toContain("t(\"llmUsageNotCalled\")");
    expect(routeSource).toContain("t(\"llmUsageMissing\")");
    expect(routeSource).toContain("t(\"sessionContextEstimate\")");
  });

  it("labels runtime compression as a separate estimate from session message history", () => {
    expect(routeSource).toContain("const contextSourceLine = lastContextComposition");
    expect(routeSource).toContain("t(\"runtimeContextEstimate\")");
    expect(routeSource).toContain("t(\"compressionScopeRuntime\")");
    expect(routeSource).toContain("t(\"compressionLimitBasisEffective\")");
    expect(routeSource).toContain("t(\"compressionModelWindow\")");
    expect(routeSource).toContain("t(\"compressionThresholdBasis\")");
    expect(routeSource).toContain("const compressionModelWindowLine = compression");
    expect(routeSource).toContain("styles.compressionFactGrid");
    expect(routeSource).toContain("compressionTitleLine");
    expect(routeSource).toContain("compression.contextWindowLimit");
    expect(routeSource).toContain("compression.source || \"runtime_state\"");
  });

  it("keeps the current session status bar keyed to the selected session", () => {
    expect(routeSource).toContain("const rawSessionDetail = sessionDetailQuery.data");
    expect(routeSource).toContain("const selectedSessionDetail =");
    expect(routeSource).toContain("rawSessionDetail && rawSessionDetail.id === activeSessionId ? rawSessionDetail : undefined");
    expect(routeSource).toContain("const detail = selectedSessionDetail");
    expect(routeSource).toContain("const runtimeMatchesSelectedSession = Boolean(");
    expect(routeSource).toContain("runtimeActiveChatTurnSessionIds.has(activeSessionId)");
    expect(routeSource).toContain("const runtimeMismatchLine = runtimeActiveChatTurnSessionId && !runtimeMatchesSelectedSession");
    expect(routeSource).toContain("detail?.agentDisplayName ?? detail?.title ?? directSessionActiveSummary?.agentDisplayName ?? directSessionActiveSummary?.title ?? t(\"loadingSession\")");
    expect(routeSource).toContain("lastContextComposition?.totalTokens ?? sessionContextUsage?.used ?? 0");
    expect(routeSource).toContain("lastContextComposition?.limitTokens ?? sessionContextUsage?.limit ?? 0");
    expect(routeSource).toContain("const compression = runtimeMatchesSelectedSession ? runtime?.contextCompression : undefined");
    expect(routeSource).toContain("runtimeMatchesSelectedSession && runtime?.sessionStateLine");
    expect(routeSource).toContain("runtimeMismatchLine || (sessionDetailErrorState.blockingError");
    expect(routeSource).toContain("(runtimeMatchesSelectedSession ? runtime?.taskSummary : \"\")");
    expect(routeSource).toContain("detail?.defaultFileContext ?? (runtimeMatchesSelectedSession ? runtime?.defaultRoute : undefined) ?? \"workspace\"");

    expect(routeSource).not.toContain("detail?.title ?? runtime?.sessionTitle");
    expect(routeSource).not.toContain("sessionContextUsage?.used ?? runtime?.contextUsage.used");
    expect(routeSource).not.toContain("sessionContextUsage?.limit ?? runtime?.contextUsage.limit");
    expect(routeSource).not.toContain(": runtime?.sessionStateLine");
    expect(routeSource).not.toContain("|| runtime?.taskSummary");
    expect(routeSource).not.toContain("detail?.defaultFileContext ?? runtime?.defaultRoute");
  });

  it("keeps live token speed visible in the current session status strip", () => {
    expect(routeSource).toContain("tokenSpeedSampleFromMessages");
    expect(routeSource).toContain("updateTokenSpeedTracker");
    expect(routeSource).toContain("label: t(\"tokenSpeed\")");
    expect(routeSource).toContain("tokenSpeedSampling");
    expect(routeSource).toContain("tok/s");
    expect(routeSource.indexOf("label: t(\"tokenSpeed\")")).toBeLessThan(
      routeSource.indexOf("label: t(\"currentTask\")"),
    );
  });

  it("shows direct-session mismatch as a status-strip notice with a switch action", () => {
    expect(routeSource).toContain("agentDirectSessionMismatch");
    expect(routeSource).toContain("sessionBindingNotice");
    expect(routeSource).toContain("sessionBindingMismatchLine");
    expect(routeSource).toContain("handleOpenDirectSession(agentPrimaryDirectSessionId)");
    expect(routeSource).toContain("label: t(\"sessionBinding\")");
    expect(routeSource.indexOf("label: t(\"sessionBinding\")")).toBeLessThan(
      routeSource.indexOf("label: t(\"currentTask\")"),
    );
  });

  it("records direct chat submit lifecycle telemetry before backend acceptance", () => {
    expect(routeSource).toContain("postSubmitTelemetry");
    expect(routeSource).toContain("browser.chat_submit.requested");
    expect(routeSource).toContain("browser.chat_submit.blocked");
    expect(routeSource).toContain("browser.chat_submit.upload_started");
    expect(routeSource).toContain("browser.chat_submit.upload_failed");
    expect(routeSource).toContain("browser.chat_submit.mutate_called");
    expect(routeSource).toContain("browser.chat_submit.request_started");
    expect(routeSource).toContain("browser.chat_submit.accepted");
    expect(routeSource).toContain("browser.chat_submit.request_failed");
    expect(routeSource).toContain("contentLength");
    expect(routeSource).toContain("guardReason");
    expect(routeSource).not.toContain("fields: { content,");
  });

  it("clears the direct chat composer immediately after submit and restores only failed text", () => {
    const submitWithAttachmentsStart = routeSource.indexOf("async function submitTurnWithAttachments");
    const optimisticAppend = routeSource.indexOf("appendOptimisticUserMessage(detail, { sessionId, content, references })", submitWithAttachmentsStart);
    const immediateDraftClear = routeSource.indexOf("clearSessionDraftForSubmittedTurn(current, sessionId)", submitWithAttachmentsStart);
    const uploadFailureDraftRestore = routeSource.indexOf(
      "restoreSubmittedDraftIfComposerStillEmpty(current, sessionId, content)",
      submitWithAttachmentsStart,
    );
    expect(submitWithAttachmentsStart).toBeGreaterThan(-1);
    expect(immediateDraftClear).toBeGreaterThan(submitWithAttachmentsStart);
    expect(immediateDraftClear).toBeLessThan(optimisticAppend);
    expect(uploadFailureDraftRestore).toBeGreaterThan(optimisticAppend);

    const submitMutationStart = routeSource.indexOf("const submitTurnMutation = useMutation");
    const submitSuccessStart = routeSource.indexOf("onSuccess: (acceptedTurn, variables)", submitMutationStart);
    const submitErrorStart = routeSource.indexOf("onError: (error, variables)", submitSuccessStart);
    const submitSuccessBlock = routeSource.slice(submitSuccessStart, submitErrorStart);
    const submitErrorBlock = routeSource.slice(submitErrorStart, routeSource.indexOf("const editResubmitMutation", submitErrorStart));
    expect(submitSuccessBlock).not.toContain("setSessionDrafts");
    expect(submitErrorBlock).toContain("restoreSubmittedDraftIfComposerStillEmpty(current, variables.sessionId, variables.content)");
  });

  it("keeps mental model opt-in explicit and uses it to gate timeline snapshots", () => {
    expect(routeSource).toContain("readStoredMentalModelToggle() ?? false");
    expect(routeSource).not.toContain("const defaultEnabled = String(runtime.mentalState?.source");
    expect(routeSource).toContain("showMentalSnapshots={mentalModelEnabledForNextTurn}");
    expect(routeSource).toContain("mentalModelEnabled: mentalModelEnabledForNextTurn");
    expect(routeSource).toContain("const memberMental = mentalModelEnabledForNextTurn ? latestMentalSnapshot(memberDetail?.messages) : undefined");
  });

  it("exposes dynamic group creation from the unified conversation list", () => {
    expect(routeSource).toContain("handleToggleGroupComposer");
    expect(routeSource).toContain("handleCreateGroupRoom");
    expect(routeSource).toContain("fetchJson<AgentInstance[]>(\"/api/agents?detail=summary\")");
    expect(routeSource).toContain("body: JSON.stringify({ title, agentIds, mode, purpose })");
    expect(routeSource).toContain("styles.groupComposerPanel");
    expect(routeSource).toContain("styles.groupAgentPicker");
    expect(routeSource).toContain("styles.createGroupButton");
    expect(routeSource).toContain("styles.systemEntryGroup");
    expect(routeSource).toContain("styles.systemEntryButton");

    expect(routeStyles.sessionActionRow).toBeTypeOf("string");
    expect(routeStyles.newGroupButton).toBeTypeOf("string");
    expect(routeStyles.systemEntryGroup).toBeTypeOf("string");
    expect(routeStyles.systemEntryButton).toBeTypeOf("string");
    expect(routeStyles.systemEntryIcon).toBeTypeOf("string");
    expect(routeStyles.groupComposerPanel).toBeTypeOf("string");
    expect(routeStyles.groupAgentOption).toBeTypeOf("string");
    expect(routeStyles.createGroupButton).toBeTypeOf("string");
  });

  it("keeps Agent rebinding out of the chat conversation surface", () => {
    expect(routeSource).not.toContain("body: JSON.stringify({ agentId })");
    expect(routeSource).not.toContain("updateSessionAgentMutation");
    expect(routeSource).not.toContain("sessionAgentOptions");
    expect(routeSource).not.toContain("handleAgentTemplateChange");
    expect(routeSource).not.toContain("agentBindingSavePending");
    expect(routeSource).not.toContain("styles.sessionAgentStatusControl");
    expect(routeSource).not.toContain("styles.sessionAgentStatusSelect");
    expect(routeSource).not.toContain("styles.agentTemplatePanel");
    expect(routeSource).not.toContain("fetchJson<SessionAgentTemplate[]>");
    expect(routeSource).not.toContain("body: JSON.stringify({ agentProfileId })");
    expect(routeCssSource).not.toContain(".sessionAgentStatusControl");
    expect(routeCssSource).not.toContain(".sessionAgentStatusSelect");
    expect(routeCssSource).not.toContain(".sessionAgentStatusMeta");
  });

  it("opens group conversations inside the chat page instead of navigating away", () => {
    expect(routeSource).toContain("activeGroupRoomId");
    expect(routeSource).toContain("handleOpenGroupRoom");
    expect(routeSource).toContain('new URLSearchParams(location.search).get("room")');
    expect(routeSource).toContain("requestedRoomId && activeGroupRoomId !== requestedRoomId");
    expect(routeSource).toContain("navigate(`/chat?room=${encodeURIComponent(roomId)}`, { replace: false })");
    expect(routeSource).toContain("setRightPaneCollapsed(false)");
    expect(routeSource).toContain("chatRoomModeLabel(mode, lang)");
    expect(routeSource).toContain("chatRoomPurposeLabel(purpose, lang)");
    expect(routeSource).toContain("queryKeys.chatRoomPurposes()");
    expect(routeSource).toContain("fetchJson<ChatRoomPurpose[]>(\"/api/chat-rooms/purposes\")");
    expect(routeSource).toContain("抢占式讨论");
    expect(routeSource).toContain("协同问诊会诊");
    expect(routeSource).toContain("医疗分诊建议");
    expect(routeSource).toContain("medical_consultation_panel");
    expect(routeSource).toContain("medical_triage");
    expect(routeSource).toContain("对话目的");
    expect(routeSource).toContain("purpose: groupPurposeDraft || \"discussion\"");
    expect(routeSource).toContain("purpose: activeGroupRoom?.purpose || \"discussion\"");
    expect(routeSource).toContain("purpose: groupManagePurposeDraft || \"discussion\"");
    expect(routeSource).toContain("fetchJson<ChatRoomDetail>(`/api/chat-rooms/${activeGroupRoomId}`)");
    expect(routeSource).toContain("new EventSource(`/api/chat-rooms/${streamRoomId}/events`)");
    expect(routeSource).toContain("syncChatRoomDetail(payload.detail)");
    expect(routeSource).toContain("browser.chat_room_stream.closed");
    expect(routeSource).toContain("handleStartGroupRound");
    expect(routeSource).toContain("fetchJson<ChatRoomRoundAcceptedResponse>(`/api/chat-rooms/${roomId}/rounds`");
    expect(routeSource).toContain("Prefer\": \"respond-async\"");
    expect(routeSource).toContain("chatWorkspaceCache.afterGroupRoundStarted(accepted.roomId)");
    expect(routeSource).toContain("stopGroupRoundMutation");
    expect(routeSource).toContain("fetchJson<ChatRoomDetail>(`/api/chat-rooms/${roomId}/stop`");
    expect(routeSource).toContain("handleStopGroupRound");
    expect(routeSource).toContain("groupRoundStopping");
    expect(routeSource).toContain("groupRoundActive");
    expect(routeSource).toContain("sendProjectBusMessageMutation");
    expect(routeSource).toContain("updateGroupRoomMutation");
    expect(routeSource).toContain("deleteGroupRoomMutation");
    expect(routeSource).toContain("const activeGroupTeamOwned = Boolean(activeGroupTeam)");
    expect(routeSource).toContain("|| activeGroupTeamOwned");
    expect(routeSource).toContain("if (!sessionId || activeGroupTeamOwned || groupRoundActive || updateGroupRoomMutation.isPending)");
    expect(routeSource).toContain("团队群聊引用");
    expect(routeSource).toContain("Team room reference");
    expect(routeSource).toContain("onClick={() => navigate(`/teams?team=${encodeURIComponent(activeGroupTeam.teamId)}`)}");
    expect(routeSource).toContain("打开团队");
    expect(routeSource).toContain("disabled={activeGroupTeamOwned || groupRoundActive || updateGroupRoomMutation.isPending}");
    expect(routeSource).toContain("disabled={activeGroupTeamOwned || groupRoundRunning || updateGroupRoomMutation.isPending}");
    expect(routeSource).toContain("团队关联群聊的成员来自团队组织画布");
    expect(routeSource).toContain("groupManageTitleDraft");
    expect(routeSource).toContain("title: groupManageTitleDraft.trim()");
    expect(routeSource).toContain("groupManagePurposeDraft");
    expect(routeSource).toContain("participantSessionIds: sessionIds");
    expect(routeSource).toContain("groupManageSessionIds.length < 2");
    expect(routeSource).toContain("setGroupManageSessionIds((current) => current.filter((sessionId) => sessionId !== variables.sessionId))");
    expect(routeSource).toContain("styles.groupManagementPanel");
    expect(routeSource).toContain("styles.groupConversationFrame");
    expect(routeSource).toContain("compactAgentRoleLabel");
    expect(routeSource).toContain("shouldCollapseGroupMessage");
    expect(routeSource).toContain("shouldDefaultCollapseGroupMessage");
    expect(routeSource).toContain("message.audience === \"internal\"");
    expect(routeSource).toContain("展开讨论");
    expect(routeSource).toContain("expandedGroupMessageIds");
    expect(routeSource).toContain("stripGroupSpeakerPrefix(message, identityName)");
    expect(routeSource).toContain("renderGroupMessageBody(message, speakerIdentity.name)");
    expect(routeSource).toContain("title={speakerIdentity.fullIdentityLabel}");
    expect(routeSource).toContain("展开全文");
    expect(routeSource).toContain("收起");
    expect(routeSource).toContain("message.status !== \"completed\" ? <span>{statusLabel(message.status)}</span> : null");
    expect(routeSource).toContain("numericTail.slice(-2)");
    expect(routeSource).not.toContain("navigate(`/chat-rooms");
    expect(routeSource.indexOf("styles.groupManagementPanel")).toBeLessThan(
      routeSource.indexOf("<aside className={rightPaneCollapsed"),
    );

    expect(routeStyles.groupConversationFrame).toBeTypeOf("string");
    expect(routeStyles.groupManagementPanel).toBeTypeOf("string");
    expect(routeStyles.groupTitleField).toBeTypeOf("string");
    expect(routeStyles.groupManagementCount).toBeTypeOf("string");
    expect(routeStyles.groupMemberPicker).toBeTypeOf("string");
    expect(routeStyles.groupMemberChip).toBeTypeOf("string");
    expect(routeStyles.groupMessageTimeline).toBeTypeOf("string");
    expect(routeStyles.groupRoundBlock).toBeTypeOf("string");
    expect(routeStyles.groupRoundDivider).toBeTypeOf("string");
    expect(routeStyles.groupTopicBubble).toBeTypeOf("string");
    expect(routeStyles.groupBubbleRow).toBeTypeOf("string");
    expect(routeStyles.groupBubbleAvatar).toBeTypeOf("string");
    expect(routeStyles.groupBubble).toBeTypeOf("string");
    expect(routeStyles.groupBubbleBodyCollapsed).toBeTypeOf("string");
    expect(routeStyles.groupBubbleToggle).toBeTypeOf("string");
    expect(routeStyles.groupTypingDots).toBeTypeOf("string");
    expect(routeStyles.groupComposerBar).toBeTypeOf("string");
  });

  it("uses the group surface as a project Agent bus observation and @ guidance entry", () => {
    expect(routeSource).toContain("handleOpenProjectAgentBus");
    expect(routeSource).toContain("setActiveGroupRoomId(\"__project_agent_bus__\")");
    expect(routeSource).toContain("queryKeys.projectAgentBus()");
    expect(routeSource).toContain("listProjectAgentBusTimeline()");
    expect(routeSource).toContain("sendProjectAgentBusMessage({ content, interruptTargets })");
    expect(routeSource).toContain("revokeProjectAgentBusMessage({");
    expect(routeSource).toContain("isProjectAgentBusEventRevoked(event)");
    expect(routeSource).toContain("handleRevokeProjectBusMessage(event.eventId)");
    expect(routeSource).toContain("projectBusInterruptTargets");
    expect(routeSource).toContain("Agent 通知流");
    expect(routeSource).toContain("它不是团队群聊");
    expect(routeSource).toContain("全局广播/私信投递记录");
    expect(routeSource).toContain("不带 @ 默认投递全体");
    expect(routeSource).toContain("打断目标 Agent");
    expect(routeSource).toContain("buildChatMentionTargets(agentsQuery.data ?? [])");
    expect(routeSource).toContain("tokenizeChatMentions(text, chatMentionTargets)");
    expect(routeSource).toContain("handleOpenMentionTarget(segment.target)");
    expect(routeSource).toContain("styles.projectBusEvent");
    expect(routeSource).toContain("styles.projectBusEventRevoked");
    expect(routeSource).toContain("styles.projectBusEventActions");
    expect(routeSource).toContain("styles.agentMention");
    expect(routeSource).toContain("styles.projectBusInterruptToggle");

    expect(routeStyles.projectBusEvent).toBeTypeOf("string");
    expect(routeStyles.projectBusEventRevoked).toBeTypeOf("string");
    expect(routeStyles.projectBusEventHeader).toBeTypeOf("string");
    expect(routeStyles.projectBusEventActions).toBeTypeOf("string");
    expect(routeStyles.projectBusEventBody).toBeTypeOf("string");
    expect(routeStyles.agentMention).toBeTypeOf("string");
    expect(routeStyles.projectBusEventMeta).toBeTypeOf("string");
    expect(routeStyles.projectBusInterruptToggle).toBeTypeOf("string");
  });

  it("logs direct session stream close events for lifecycle diagnosis", () => {
    expect(routeSource).toContain("browser.session_stream.opened");
    expect(routeSource).toContain("browser.session_stream.closed");
    expect(routeSource).toContain("readyStateBeforeClose");
    expect(routeSource).toContain("stream.close()");
  });

  it("coalesces high-frequency direct session stream snapshots before updating UI cache", () => {
    expect(routeSource).toContain("const SESSION_STREAM_MIN_APPLY_INTERVAL_MS = 350");
    expect(routeSource).toContain("sessionDetailSnapshotKey(previous) === sessionDetailSnapshotKey(detail)");
    expect(routeSource).toContain("let pendingDetail: SessionDetail | null = null");
    expect(routeSource).toContain("function queueSessionDetail(detail: SessionDetail, payloadLength: number)");
    expect(routeSource).toContain("browser.session_stream.snapshot_queued");
    expect(routeSource).toContain("browser.session_stream.snapshot_applied");
    expect(routeSource).toContain("queueSessionDetail(payload.detail, event.data.length)");
  });

  it("applies lightweight assistant delta stream events without full detail sync", () => {
    expect(routeSource).toContain("function mergeAssistantDeltaIntoSessionDetail(");
    expect(routeSource).toContain("stream.addEventListener(\"assistant_delta\", handleAssistantDelta as EventListener)");
    expect(routeSource).toContain("stream.removeEventListener(\"assistant_delta\", handleAssistantDelta as EventListener)");
    expect(routeSource).toContain("queryClient.setQueryData<SessionDetail>(queryKeys.session(streamSessionId), (detail) =>");
    expect(routeSource).toContain("browser.session_stream.assistant_delta_applied");
  });

  it("backs off index polling when detail streams are connected", () => {
    expect(routeSource).toContain("const ACTIVE_INDEX_POLL_MS = 3_000");
    expect(routeSource).toContain("const directSessionPanelActive = Boolean(activeSessionId) && !groupPanelActive");
    expect(routeSource).toContain("sessionStreamConnected && directSessionPanelActive ? false : ACTIVE_INDEX_POLL_MS");
    expect(routeSource).toContain("groupStreamConnected && legacyGroupRoomActive");
    expect(routeSource).toContain("directSessionPanelActive ? false : ACTIVE_INDEX_POLL_MS");
    expect(routeSource).toContain("mergeSessionDetailIntoConversations(conversations, detail)");
  });

  it("keeps active chat streams stable during direct session route switches", () => {
    const sessionStreamEffectSource = routeSource.slice(
      routeSource.indexOf("const stream = new EventSource(`/api/sessions/${streamSessionId}/events`);"),
      routeSource.indexOf("useEffect(() => {\n    if (!groupStreamShouldConnect"),
    );

    expect(routeSource).toContain("const ACTIVE_BACKGROUND_SYNC_POLL_MS = 5_000");
    expect(routeSource).toContain("const SESSION_STREAM_ROUTE_SWITCH_GRACE_MS = 4_000");
    expect(routeSource).toContain("directSessionBackgroundSyncActive");
    expect(routeSource).toContain("groupBackgroundSyncActive");
    expect(routeSource).toContain("sessionStreamRouteTargetMatches");
    expect(routeSource).toContain("sessionStreamRouteSettling");
    expect(routeSource).toContain("sessionStreamRouteSwitchGraceActive");
    expect(routeSource).toContain("requestedSessionId !== activeSessionId");
    expect(routeSource).toContain("&& sessionStreamRouteTargetMatches");
    expect(routeSource).toContain("const chatStartupWarmupActive = useStartupWarmup(chatStartupDataReady)");
    expect(routeSource).toContain("const chatPollingVisible = pageVisible || chatStartupWarmupActive");
    expect(routeSource).toContain("chatPollingVisible || sessionStreamRouteSwitchGraceActive");
    expect(routeSource).not.toContain("pageVisible || directSessionBackgroundSyncActive || sessionStreamRouteSwitchGraceActive");
    expect(routeSource).toContain("&& (chatPollingVisible || groupBackgroundSyncActive)");
    expect(routeSource).toContain("if (!sessionStreamShouldConnect || typeof EventSource === \"undefined\")");
    expect(routeSource).toContain("sessionStreamDecisionSnapshotRef");
    expect(sessionStreamEffectSource).not.toContain("sessionStreamRouteSwitchGraceActive,");
    expect(sessionStreamEffectSource).not.toContain("chatStartupWarmupActive,");
    expect(sessionStreamEffectSource).not.toContain("directSessionBackgroundSyncActive,");
    expect(sessionStreamEffectSource).not.toContain("pageVisible,");
    expect(routeSource).toContain("if (!groupStreamShouldConnect || typeof EventSource === \"undefined\")");
    expect(routeSource).toContain("backgroundMs: directSessionBackgroundSyncActive && !sessionStreamConnected ? ACTIVE_BACKGROUND_SYNC_POLL_MS : false");
    expect(routeSource).toContain("backgroundMs: groupBackgroundSyncActive && !groupStreamConnected ? ACTIVE_BACKGROUND_SYNC_POLL_MS : false");
    expect(routeSource).toContain("refetchIntervalInBackground: chatStartupWarmupActive || directSessionBackgroundSyncActive");
    expect(routeSource).toContain("refetchIntervalInBackground: chatStartupWarmupActive || groupBackgroundSyncActive");
  });

  it("updates active direct session before pushing the route", () => {
    const openDirectSessionSource = routeSource.slice(
      routeSource.indexOf("function handleOpenDirectSession"),
      routeSource.indexOf("function handleOpenMentionTarget"),
    );

    expect(openDirectSessionSource).toContain("setActiveSession(sessionId)");
    expect(openDirectSessionSource).toContain("navigate(`/chat?session=${encodeURIComponent(sessionId)}`, { replace: false })");
    expect(openDirectSessionSource.indexOf("setActiveSession(sessionId)")).toBeLessThan(
      openDirectSessionSource.indexOf("navigate(`/chat?session=${encodeURIComponent(sessionId)}`, { replace: false })"),
    );
  });

  it("logs direct session stream connect decisions with visibility inputs", () => {
    expect(routeSource).toContain("browser.session_stream.effect_started");
    expect(routeSource).toContain("browser.session_stream.skipped");
    expect(routeSource).toContain("chatStartupWarmupActive");
    expect(routeSource).toContain("chatPollingVisible");
    expect(routeSource).toContain("routeTargetMatches");
    expect(routeSource).toContain("routeSettling");
    expect(routeSource).toContain("routeSwitchGraceActive");
    expect(routeSource).toContain("visibilityState: typeof document === \"undefined\" ? \"unknown\" : document.visibilityState");
  });

  it("visually distinguishes direct sessions from group chats in the conversation list", () => {
    expect(routeSource).toContain("avatarInitials");
    expect(directSessionIndexItemSource).toContain("styles.conversationAvatarDirect");
    expect(groupSessionIndexItemsSource).toContain("styles.conversationAvatarGroup");
    expect(directSessionIndexItemSource).toContain("styles.directSessionItem");
    expect(groupSessionIndexItemsSource).toContain("styles.groupSessionItem");
    expect(routeSource).toContain("navigate(`/chat?session=${encodeURIComponent(sessionId)}`, { replace: false })");
    expect(directSessionIndexItemSource).toContain("styles.conversationKindBadgeDirect");
    expect(directSessionIndexItemSource).toContain("styles.conversationKindBadgeChild");
    expect(groupSessionIndexItemsSource).toContain("styles.conversationKindBadgeGroup");

    expect(routeStyles.conversationAvatar).toBeTypeOf("string");
    expect(routeStyles.conversationAvatarDirect).toBeTypeOf("string");
    expect(routeStyles.conversationAvatarGroup).toBeTypeOf("string");
    expect(routeStyles.conversationTitleRow).toBeTypeOf("string");
    expect(routeStyles.conversationMetaRow).toBeTypeOf("string");
    expect(routeStyles.directSessionItem).toBeTypeOf("string");
    expect(routeStyles.groupSessionItem).toBeTypeOf("string");
    expect(routeStyles.conversationKindBadge).toBeTypeOf("string");
    expect(routeStyles.conversationKindBadgeDirect).toBeTypeOf("string");
    expect(routeStyles.conversationKindBadgeChild).toBeTypeOf("string");
    expect(routeStyles.conversationKindBadgeGroup).toBeTypeOf("string");
  });

  it("moves direct session actions into a right-click context menu", () => {
    expect(routeSource).toContain("type SessionContextMenuState");
    expect(routeSource).toContain("const [sessionContextMenu, setSessionContextMenu]");
    expect(routeSource).toContain("function openSessionContextMenu");
    expect(routeSource).toContain("onContextMenu={openSessionContextMenu}");
    expect(agentSessionTabStripSource).toContain("onContextMenu={(event) => onContextMenu(event, session)}");
    expect(routeSource).toContain("contextMenuSession");
    expect(routeSource).toContain("<SessionContextMenu");
    expect(routeSource).toContain("onAddToReview={handleAddSessionToReview}");
    expect(routeSource).toContain("onRename={beginRenameSession}");
    expect(routeSource).toContain("onDelete={handleDeleteSession}");
    expect(routeSource).toContain("event.key === \"Escape\"");
    expect(routeSource).not.toContain("const sessionContextMenuStyle: CSSProperties | undefined");
    expect(routeSource).not.toContain("onClick={() => handleAddSessionToReview(session)}");
    expect(routeSource).not.toContain("onClick={() => beginRenameSession(session)}");
    expect(routeSource).not.toContain("onClick={() => handleDeleteSession(session)}");
    expect(sessionContextMenuSource).toContain("styles.sessionContextMenu");
    expect(sessionContextMenuSource).toContain("styles.sessionContextMenuItem");
    expect(sessionContextMenuSource).toContain("styles.sessionContextMenuDanger");
    expect(sessionContextMenuSource).toContain("role=\"menu\"");
    expect(sessionContextMenuSource).toContain("role=\"menuitem\"");
    expect(sessionContextMenuSource).toContain("sessionContextMenuStyle");
    expect(sessionContextMenuSource).toContain("window.innerWidth");

    expect(routeStyles.sessionContextMenu).toBeTypeOf("string");
    expect(routeStyles.sessionContextMenuItem).toBeTypeOf("string");
    expect(routeStyles.sessionContextMenuDanger).toBeTypeOf("string");
  });

  it("shows each visible agent with a functional role label, not only a person name", () => {
    expect(routeSource).toContain("fetchJson<ConfigSummary>(\"/api/config/public\")");
    expect(routeSource).toContain("queryKeys.configPublic()");
    expect(routeSource).toContain("const modelLabelsById = useMemo");
    expect(routeSource).toContain("const resolveModelLabel = useCallback");
    expect(routeSource).toContain("agentDisplayInfo(agent, lang, { resolveModelLabel })");
    expect(agentSessionTabStripSource).toContain("sessionAgentDisplayInfo(session, sessionAgent, lang, resolveModelLabel)");
    expect(routeSource).toContain("participantAgentDisplayInfo(participantLike, participantAgent, lang, resolveModelLabel)");
    expect(conversationIndexModelSource).toContain("dialogueModelId: session.dialogueModelId");
    expect(agentSessionTabStripSource).toContain("sessionDisplay.modelLabel");
    expect(routeSource).toContain("participantDisplay.modelLabel");
    expect(routeSource).toContain("display.modelLabel");
    expect(agentSessionTabStripSource).toContain("const sessionAgent = session.agentId ? agentsById.get(session.agentId) : undefined");
    expect(agentSessionTabStripSource).toContain("const sessionDisplay = sessionAgentDisplayInfo(session, sessionAgent, lang, resolveModelLabel)");
    expect(routeSource).toContain("const participantDisplay = groupParticipantIdentity(participant)");
    expect(routeSource).toContain("identityLabel: formatAgentIdentityWithRole");
    expect(routeSource).toContain("styles.groupMemberCopy");
    expect(routeSource).toContain("styles.agentRoleTag");
    expect(routeSource).toContain("styles.agentModelTag");
    expect(routeSource).toContain("styles.agentModelLine");

    expect(routeStyles.groupMemberCopy).toBeTypeOf("string");
    expect(routeStyles.agentRoleTag).toBeTypeOf("string");
    expect(routeStyles.agentModelTag).toBeTypeOf("string");
    expect(routeStyles.agentModelLine).toBeTypeOf("string");
  });

  it("hides direct sessions whose Agent is no longer active in Agent Center", () => {
    expect(conversationIndexModelSource).toContain("export function isVisibleDirectSession");
    expect(conversationIndexModelSource).toContain("if (session.agentMissing)");
    expect(conversationIndexModelSource).toContain("return false;");
    expect(conversationIndexModelSource.indexOf("if (session.agentMissing)")).toBeLessThan(
      conversationIndexModelSource.indexOf("if (!String(session.agentId ?? \"\").trim())"),
    );
    expect(conversationIndexModelSource).toContain("export function isVisibleConversation");
    expect(conversationIndexModelSource).toContain("if (conversation.agentMissing)");
    expect(conversationIndexModelSource.indexOf("if (conversation.agentMissing)")).toBeLessThan(
      conversationIndexModelSource.indexOf("if (!String(conversation.agentId ?? \"\").trim())"),
    );
    expect(routeSource).toContain("const rawSessionsQuery = useSessionIndexQuery");
    expect(routeSource).toContain("const visibleSessionsData = useMemo");
    expect(routeSource).toContain("data: visibleSessionsData");
    expect(conversationIndexModelSource).toContain("const rawSessionsById = new Map");
    expect(conversationIndexModelSource).toContain("if (!isVisibleConversation(conversation, rawSessionsById))");
    expect(conversationIndexModelSource).toContain("if (rawSession && !session)");
    expect(routeSource).toContain("const allVisibleSessions = useMemo");
    expect(routeSource).toContain("const rightIndexSessions = useMemo");
    expect(conversationIndexModelSource).toContain("mergeVisibleSessionsIntoConversations(conversations, rightIndexSessions)");
    expect(conversationIndexModelSource).toContain("conversation.type !== \"group_room\"");
    expect(conversationIndexModelSource).toContain("if (!isVisibleConversation(conversation, rawSessionsById))");
  });

  it("renders child sessions in the top Agent session strip instead of the right conversation index", () => {
    expect(directSessionIndexItemSource).toContain("export function isChildSession");
    expect(conversationIndexModelSource).toContain("export function rootSessionIdFor");
    expect(conversationIndexModelSource).toContain("export function isRepresentedInAgentSessionTabs");
    expect(conversationIndexModelSource).toContain("export function hasInvalidChildSessionLink");
    expect(conversationIndexModelSource).toContain("export function mergeVisibleSessionsIntoConversations");
    expect(routeSource).toContain("const rightIndexSessions = useMemo");
    expect(routeSource).toContain("return allVisibleSessions.filter((session) => !isRepresentedInAgentSessionTabs(session))");
    expect(routeSource).toContain("const agentSessionTabs = useMemo");
    expect(routeSource).toContain("rootSessionIdFor(session) === activeRootSessionId");
    expect(conversationIndexModelSource).toContain("mergeVisibleSessionsIntoConversations(conversations, rightIndexSessions)");
    expect(conversationIndexModelSource).toContain("if (isRepresentedInAgentSessionTabs(session))");
    expect(routeSource).toContain("const invalidChildSessionLinkMessage = hasInvalidChildSessionLink(directSessionActiveSummary)");
    expect(routeSource).toContain("child_session_link_invalid");
    expect(routeSource).toContain("子对话缺少 parentSessionId/rootSessionId");
    expect(routeSource).not.toContain("rootSessionId || session.parentSessionId || session.id");
    expect(routeSource).not.toContain("const childSessionsByRootId = useMemo");
    expect(routeSource).not.toContain("function renderChildSessionItems");
    expect(routeSource).not.toContain("styles.childSessionList");
    expect(routeSource).toContain("<AgentSessionTabStrip");
    expect(routeSource).toContain("sessions={agentSessionTabs}");
    expect(routeSource).toContain("onContextMenu={openSessionContextMenu}");
    expect(routeSource).toContain("onOpenDirectSession={handleOpenDirectSession}");
    expect(routeSource).toContain("onSubmitRename={submitRenameSession}");
    expect(routeSource).toContain("onCancelRename={cancelRenameSession}");
    expect(agentSessionTabStripSource).toContain("styles.agentSessionTabGroup");
    expect(agentSessionTabStripSource).toContain("styles.agentSessionTabActive");
    expect(agentSessionTabStripSource).toContain("styles.agentSessionTabChild");
    expect(agentSessionTabStripSource).toContain("styles.agentSessionTabRoot");
    expect(agentSessionTabStripSource).toContain("styles.agentSessionTabEditing");
    expect(agentSessionTabStripSource).toContain("onContextMenu={(event) => onContextMenu(event, session)}");
    expect(agentSessionTabStripSource).toContain("sessionIsChild ? <MessageCircleHeart size={14} /> : <Bot size={14} />");
    expect(agentSessionTabStripSource).toContain("session.taskTitle || session.resultCard?.title || session.title");
    expect(agentSessionTabStripSource).toContain("session.resultCard?.summary || session.taskSummary");
    expect(agentSessionTabStripSource).toContain("onOpenDirectSession(session.id)");
    expect(agentSessionTabStripSource).toContain("const tabEditing = editingSessionId === session.id");
    expect(agentSessionTabStripSource).toContain("className={styles.agentSessionTabTitleInput}");
    expect(agentSessionTabStripSource).toContain("onSubmitRename(session)");
    expect(agentSessionTabStripSource).toContain("onCancelRename");

    expect(routeStyles.agentSessionTabGroup).toBeTypeOf("string");
    expect(routeStyles.agentSessionTab).toBeTypeOf("string");
    expect(routeStyles.agentSessionTabActive).toBeTypeOf("string");
    expect(routeStyles.agentSessionTabChild).toBeTypeOf("string");
    expect(routeStyles.agentSessionTabRoot).toBeTypeOf("string");
    expect(routeStyles.agentSessionTabEditing).toBeTypeOf("string");
    expect(routeStyles.agentSessionTabIcon).toBeTypeOf("string");
    expect(routeStyles.agentSessionTabTitle).toBeTypeOf("string");
    expect(routeStyles.agentSessionTabTitleInput).toBeTypeOf("string");
    expect(routeStyles.agentSessionTabEditActions).toBeTypeOf("string");
    expect(routeStyles.agentSessionTabEditButton).toBeTypeOf("string");
    expect(routeStyles.conversationKindBadgeChild).toBeTypeOf("string");
  });

  it("renders a QQ-style tree with direct sessions separate from Team-owned rooms", () => {
    expect(routeSource).toContain("fetchJson<TeamListPayload>(\"/api/teams\")");
    expect(routeSource).toContain("queryKeys.teams()");
    expect(routeSource).toContain("linkedTeamRoomIds");
    expect(routeSource).toContain("filteredTeams");
    expect(routeSource).toContain("filteredStandaloneGroupConversations");
    expect(conversationIndexTreeSource).toContain("TeamConversationIndexItem");
    expect(conversationIndexTreeSource).toContain("GroupConversationIndexItem");
    expect(groupSessionIndexItemsSource).toContain("export function teamStatusLabel");
    expect(groupSessionIndexItemsSource).toContain("teamStatusLabel(team.status, lang, statusLabel)");
    expect(groupSessionIndexItemsSource).toContain("team.linkedChatRoom?.title");
    expect(groupSessionIndexItemsSource).toContain("team.members ?? []");
    expect(groupSessionIndexItemsSource).toContain("team.teamCategory");
    expect(groupSessionIndexItemsSource).toContain("team.teamKind");
    expect(conversationIndexModelSource).toContain("team.teamSource");
    expect(conversationIndexModelSource).toContain("team.teamTemplateId");
    expect(groupSessionIndexItemsSource).toContain("群成员");
    expect(groupSessionIndexItemsSource).toContain("团队分类");
    expect(groupSessionIndexItemsSource).toContain("团队群聊");
    expect(groupSessionIndexItemsSource).toContain("待绑定");
    expect(groupSessionIndexItemsSource).toContain("styles.teamTreeLabelRow");
    expect(conversationIndexTreeSource).toContain("`/teams?team=${encodeURIComponent(team.teamId)}`");
    expect(conversationIndexTreeSource).toContain("未绑定团队的群聊");
    expect(conversationIndexTreeSource).toContain("onToggleConversationGroup(\"teams\")");
    expect(conversationIndexTreeSource).toContain("onToggleConversationGroup(\"standaloneGroups\")");
    expect(conversationIndexTreeSource).toContain("expanded={searchHasTerm || !collapsedConversationGroups.teams}");
    expect(conversationIndexTreeSource).toContain("expanded={searchHasTerm || !collapsedConversationGroups.standaloneGroups}");
    expect(conversationIndexTreeSource).toContain("conversationGroupLabel(\"teams\"");
    expect(conversationIndexTreeSource).toContain("conversationGroupLabel(\"standaloneGroups\"");
    expect(conversationIndexTreeSource).toContain("className={styles.teamTreeGroup}");
    expect(groupSessionIndexItemsSource).toContain("styles.teamTreeChildren");
    expect(groupSessionIndexItemsSource).toContain("styles.teamTreeChild");

    expect(routeStyles.conversationGroupHeader).toBeTypeOf("string");
    expect(routeStyles.teamTreeGroup).toBeTypeOf("string");
    expect(routeStyles.teamTreeItem).toBeTypeOf("string");
    expect(routeStyles.teamTreeLabelRow).toBeTypeOf("string");
    expect(routeStyles.teamTreeChildren).toBeTypeOf("string");
    expect(routeStyles.teamTreeChild).toBeTypeOf("string");
  });

  it("groups the unified conversation list like expandable contact folders", () => {
    expect(conversationIndexModelSource).toContain("DEFAULT_COLLAPSED_CONVERSATION_GROUPS");
    expect(conversationIndexModelSource).toContain("CONVERSATION_GROUP_ORDER");
    expect(conversationIndexModelSource).toContain("classifyConversation");
    expect(conversationIndexModelSource).toContain("conversationGroupLabel");
    expect(routeSource).toContain("useConversationIndexModel");
    expect(conversationIndexTreeSource).toContain("groupedConversations.map");
    expect(routeSource).toContain("toggleConversationGroup");
    expect(routeSource).toContain("ConversationIndexTree");
    expect(routeSource).toContain("<ConversationIndexTree");
    expect(conversationIndexTreeSource).toContain("ConversationIndexSection");
    expect(conversationIndexTreeSource).toContain("expanded={!collapsed}");
    expect(conversationIndexSectionSource).toContain("styles.conversationGroupHeader");
    expect(conversationIndexSectionSource).toContain("styles.conversationGroupList");
    expect(conversationIndexSectionSource).toContain("aria-expanded={expanded}");
    expect(conversationIndexSectionSource).toContain("<ChevronRight size={14} aria-hidden=\"true\" />");
    expect(routeSource).toContain("searchHasTerm");

    expect(routeStyles.conversationGroup).toBeTypeOf("string");
    expect(routeStyles.conversationGroupHeader).toBeTypeOf("string");
    expect(routeStyles.conversationGroupList).toBeTypeOf("string");
  });

  it("loads session index pages through the paginated query endpoint", () => {
    expect(routeSource).toContain("useSessionIndexQuery");
    expect(routeSource).toContain("queryText: sessionQueryText");
    expect(routeSource).toContain("sessionIndexHasMore");
    expect(routeSource).toContain("rawSessionsQuery.loadMore()");
    expect(routeSource).toContain("styles.sessionLoadMoreButton");
    expect(routeStyles.sessionLoadMoreButton).toBeTypeOf("string");
  });

  it("keeps paginated session query caches synchronized with optimistic list mutations", () => {
    expect(routeSource).toContain("updateSessionSummaryCaches(queryClient");
    expect(routeSource).toContain("captureSessionIndexCacheSnapshots(queryClient)");
    expect(routeSource).toContain("restoreSessionIndexCacheSnapshots(queryClient, context?.previousSessionIndexCaches)");
  });

  it("asks for confirmation before deleting conversations", () => {
    expect(routeSource).toContain("t(\"deleteSessionConfirm\").replace(\"{title}\"");
    expect(routeSource).toContain("t(\"deleteGroupConfirm\").replace(\"{title}\"");
    expect(routeSource).toContain("if (!window.confirm(sessionConfirmMessage))");
    expect(routeSource).toContain("if (!window.confirm(groupConfirmMessage))");
    expect(routeSource).toContain("[session.id]: t(\"deleteSessionBusy\")");
    expect(routeSource).toContain('deleteBusyLabel={t("deleteSessionBusy")}');
    expect(directSessionIndexListSource).toContain("deleteBusyLabel");
    expect(directSessionIndexItemSource).toContain("const deleteBusyReason = sessionBusy ? deleteBusyLabel : \"\"");
    expect(routeSource.indexOf("window.confirm(sessionConfirmMessage)")).toBeLessThan(
      routeSource.indexOf("deleteSessionMutation.mutate({ sessionId: session.id })"),
    );
    expect(routeSource.indexOf("window.confirm(groupConfirmMessage)")).toBeLessThan(
      routeSource.indexOf("deleteGroupRoomMutation.mutate({ roomId: activeGroupRoomId })"),
    );
  });

  it("removes deleted direct sessions from cached lists before refetch", () => {
    const deleteMutationSource = routeSource.slice(routeSource.indexOf("const deleteSessionMutation"));
    expect(routeSource).toContain("removeDeletedSessionFromConversations");
    expect(deleteMutationSource).toContain("updateSessionSummaryCaches(queryClient");
    expect(deleteMutationSource).toContain("queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations()");
    expect(routeSource).toContain("conversation.type !== \"direct_agent\"");
    expect(routeSource).toContain("conversation.directSessionId !== deletedSessionId && conversation.conversationId !== deletedSessionId");
    expect(deleteMutationSource.indexOf("updateSessionSummaryCaches(queryClient")).toBeLessThan(
      deleteMutationSource.indexOf("void chatWorkspaceCache.afterChatRoomsChanged()"),
    );
    expect(deleteMutationSource.indexOf("queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations()")).toBeLessThan(
      deleteMutationSource.indexOf("void chatWorkspaceCache.afterSessionChanged()"),
    );
    expect(deleteMutationSource).toContain("Prefer\": \"respond-async\"");
  });

  it("switches away when the active direct session disappears after reset or delete", () => {
    expect(routeSource).toContain("!sessionsQuery.data.some((session) => session.id === activeSessionId)");
    expect(routeSource).toContain("setActiveSession(sessionsQuery.data[0].id)");
  });

  it("keeps renamed direct session titles visible before conversation refetch finishes", () => {
    const renameStart = routeSource.indexOf("const renameSessionMutation");
    const renameEnd = routeSource.indexOf("const addSessionToReviewMutation", renameStart);
    const renameMutationSource = routeSource.slice(renameStart, renameEnd);
    const titleHelperStart = directSessionIndexItemSource.indexOf("export function sessionListTitle");
    const titleHelperEnd = directSessionIndexItemSource.indexOf("function compactAgentIdentifier", titleHelperStart);
    const titleHelperSource = directSessionIndexItemSource.slice(titleHelperStart, titleHelperEnd);
    const titleHelperChildEnd = titleHelperSource.indexOf(").trim();", titleHelperSource.indexOf('if (sessionKind === "child")'));
    const titleHelperRootSource = titleHelperSource.slice(titleHelperChildEnd + 1);
    expect(routeSource).toContain("mergeSessionDetailIntoConversations");
    expect(routeSource).toContain("renameSessionInSummaries");
    expect(routeSource).toContain("renameSessionInConversations");
    expect(routeSource).toContain("renameSessionDetail");
    expect(conversationIndexTreeSource).toContain("DirectSessionIndexList");
    expect(conversationIndexTreeSource).toContain("<DirectSessionIndexList");
    expect(directSessionIndexItemSource).toContain('export function sessionListTitle(');
    expect(directSessionIndexItemSource).toContain('"id" | "title" | "agentDisplayName" | "taskTitle" | "resultCard" | "sessionKind"');
    expect(titleHelperSource).toContain('if (sessionKind === "child")');
    expect(titleHelperSource).toContain("session.taskTitle");
    expect(titleHelperSource).toContain("session.resultCard?.title");
    expect(titleHelperRootSource).toContain("session.title");
    expect(titleHelperRootSource).toContain("session.agentDisplayName");
    expect(titleHelperRootSource).not.toContain("session.taskTitle");
    expect(titleHelperRootSource.indexOf("session.title")).toBeLessThan(titleHelperRootSource.indexOf("session.agentDisplayName"));
    expect(directSessionIndexListSource).toContain("title: conversation.title");
    expect(directSessionIndexListSource).toContain("agentDisplayName: conversation.agentDisplayName");
    expect(directSessionIndexListSource).toContain("buildDirectSessionIndexViewModel");
    expect(directSessionIndexListSource).toContain("const sessionView = buildDirectSessionIndexViewModel");
    expect(directSessionIndexListSource).toContain("conversationToSessionSummary");
    expect(directSessionIndexListSource).toContain("sessionComposerErrors[session.id]");
    expect(directSessionIndexItemSource).toContain("const sessionAgentMeta = sessionAgentMetaLabel(session)");
    expect(directSessionIndexItemSource).toContain("export function sessionAgentMetaLabel");
    expect(directSessionIndexItemSource).toContain("return `Agent ${code}`;");
    expect(directSessionIndexItemSource).toContain("export function showSessionFunctionLabel");
    expect(directSessionIndexItemSource).toContain('label === "会话入口"');
    expect(directSessionIndexItemSource).toContain("const sessionTitle = sessionListTitle(session) || sessionDisplay.name");
    expect(routeSource).toContain("agentDisplayName: title");
    expect(routeSource).toContain("targetSession");
    expect(directSessionIndexItemSource).toContain("{sessionTitle}");
    expect(renameMutationSource).toContain("onMutate: (variables) =>");
    expect(renameMutationSource).toContain("setEditingSessionId(null)");
    expect(renameMutationSource).toContain("updateSessionSummaryCaches(queryClient");
    expect(renameMutationSource).toContain("captureSessionIndexCacheSnapshots(queryClient)");
    expect(renameMutationSource).toContain("restoreSessionIndexCacheSnapshots(queryClient, context?.previousSessionIndexCaches)");
    expect(renameMutationSource).toContain("queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations()");
    expect(renameMutationSource).toContain("queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId)");
    expect(renameMutationSource).toContain("setEditingSessionId(variables.sessionId)");
    expect(renameMutationSource).toContain("setEditingSessionTitle(variables.title)");
    expect(renameMutationSource.indexOf("updateSessionSummaryCaches(queryClient")).toBeLessThan(
      renameMutationSource.indexOf("queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations()"),
    );
    expect(renameMutationSource.indexOf("queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations()")).toBeLessThan(
      renameMutationSource.indexOf("onError:"),
    );
    expect(renameMutationSource).toContain("const confirmedTitle =");
    expect(renameMutationSource).toContain("const confirmedUpdatedAt =");
    expect(renameMutationSource).not.toContain("mergeSessionDetailIntoSummaries(sessions, nextDetail)");
    expect(renameMutationSource).not.toContain("mergeSessionDetailIntoConversations(conversations, nextDetail)");
    expect(renameMutationSource).not.toContain("syncSessionDetail(nextDetail)");
    expect(renameMutationSource).not.toContain("void chatWorkspaceCache.afterSessionChanged({ sessionId: variables.sessionId })");
    expect(renameMutationSource).not.toContain("void chatWorkspaceCache.refreshSessionRuntime(variables.sessionId)");
  });

  it("classifies direct conversations from Agent Center role metadata", () => {
    expect(conversationIndexModelSource).toContain("agentPrimaryMode: session.agentPrimaryMode");
    expect(conversationIndexModelSource).toContain("agentRoleKey: session.agentRoleKey");
    expect(conversationIndexModelSource).toContain("agentPromptTemplateId: session.agentPromptTemplateId");
    expect(conversationIndexModelSource).toContain("primaryMode === \"research\"");
    expect(conversationIndexModelSource).toContain("roleKey.startsWith(\"research_\")");
    expect(conversationIndexModelSource).toContain("promptTemplateId.startsWith(\"prompt-research-\")");
  });
});
