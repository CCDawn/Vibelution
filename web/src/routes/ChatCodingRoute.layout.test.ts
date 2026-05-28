import { describe, expect, it } from "vitest";

import conversationStyles from "../components/conversation/ConversationView.module.css";
import routeSource from "./ChatCodingRoute.tsx?raw";
import routeStyles from "./ChatCodingRoute.module.css";

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

  it("keeps side panes collapsible while allowing narrow screens to prioritize the center pane", () => {
    expect(routeSource).toContain("CHAT_CENTER_FIRST_MEDIA_QUERY");
    expect(routeSource).toContain("centerFirstLayout");
    expect(routeSource).toContain("centerFirstAutoCollapseRef");
    expect(routeSource).toContain("window.matchMedia(CHAT_CENTER_FIRST_MEDIA_QUERY)");
    expect(routeSource).toContain("styles.layoutCenterFirst");
    expect(routeStyles.layout).toBeTypeOf("string");
    expect(routeStyles.layoutCenterFirst).toBeTypeOf("string");
    expect(routeStyles.leftRail).toBeTypeOf("string");
    expect(routeStyles.rightPane).toBeTypeOf("string");
    expect(routeStyles.resizeHandle).toBeTypeOf("string");
    expect(routeStyles.centerPane).toBeTypeOf("string");
  });

  it("compresses the left rail into primary controls plus auxiliary status groups", () => {
    expect(routeSource).toContain("styles.resourceBlock");
    expect(routeSource).toContain("styles.resourceSplit");
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
    expect(routeStyles.companionBlock).toBeTypeOf("string");
    expect(routeStyles.companionCompact).toBeTypeOf("string");
    expect(routeStyles.petMiniAvatar).toBeTypeOf("string");
    expect(routeStyles.featurePrimarySlot).toBeTypeOf("string");
    expect(routeStyles.featureChipRow).toBeTypeOf("string");
    expect(routeStyles.featureChip).toBeTypeOf("string");
  });

  it("keeps group settings in the left rail and moves member status into the right index", () => {
    expect(routeSource).toContain("expandedGroupAgentSessionId");
    expect(routeSource).toContain("expandedGroupAgentDetailQuery");
    expect(routeSource).toContain("rightIndexPanel");
    expect(routeSource).toContain("setRightIndexPanel(\"members\")");
    expect(routeSource).toContain("latestMentalSnapshot");
    expect(routeSource).toContain("styles.groupProfileBlock");
    expect(routeSource).toContain("styles.rightIndexTabs");
    expect(routeSource).toContain("styles.agentIndexRoster");
    expect(routeSource).toContain("styles.agentIndexHeader");
    expect(routeSource).toContain("aria-expanded={expanded}");
    expect(routeSource).toContain("展开成员查看该 Agent 自己的上下文、心智快照和会话状态。");
    expect(routeSource.indexOf("styles.groupProfileBlock")).toBeLessThan(
      routeSource.indexOf("<aside className={rightPaneCollapsed"),
    );
    expect(routeSource.indexOf("styles.agentIndexRoster")).toBeGreaterThan(
      routeSource.indexOf("<aside className={rightPaneCollapsed"),
    );

    expect(routeStyles.groupProfileBlock).toBeTypeOf("string");
    expect(routeStyles.rightIndexTabs).toBeTypeOf("string");
    expect(routeStyles.rightIndexTabsSingle).toBeTypeOf("string");
    expect(routeStyles.rightIndexTab).toBeTypeOf("string");
    expect(routeStyles.memberIndexSummary).toBeTypeOf("string");
    expect(routeStyles.agentIndexRoster).toBeTypeOf("string");
    expect(routeStyles.agentIndexList).toBeTypeOf("string");
    expect(routeStyles.agentIndexCard).toBeTypeOf("string");
    expect(routeStyles.agentIndexHeader).toBeTypeOf("string");
    expect(routeStyles.agentIndexDetails).toBeTypeOf("string");
    expect(routeStyles.agentIndexMentalBlock).toBeTypeOf("string");
  });

  it("keeps prompt cache observation visible in the current session status strip", () => {
    expect(routeSource).toContain("const sessionCacheUsage = detail?.cacheUsage");
    expect(routeSource).toContain("label: t(\"promptCache\")");
    expect(routeSource).toContain("turnCachedInputTokens");
    expect(routeSource).toContain("turnInputTokens");
    expect(routeSource).toContain("turnCacheHitRate");
    expect(routeSource).toContain("lastCachedInputTokens");
    expect(routeSource).toContain("lastInputTokens");
    expect(routeSource).toContain("totalCachedInputTokens");
    expect(routeSource).toContain("totalInputTokens");
    expect(routeSource).toContain("cacheObservationPending");
  });

  it("exposes dynamic group creation from the unified conversation list", () => {
    expect(routeSource).toContain("handleToggleGroupComposer");
    expect(routeSource).toContain("handleCreateGroupRoom");
    expect(routeSource).toContain("fetchJson<AgentInstance[]>(\"/api/agents\")");
    expect(routeSource).toContain("body: JSON.stringify({ title, agentIds, mode })");
    expect(routeSource).toContain("styles.groupComposerPanel");
    expect(routeSource).toContain("styles.groupAgentPicker");
    expect(routeSource).toContain("styles.createGroupButton");

    expect(routeStyles.sessionActionRow).toBeTypeOf("string");
    expect(routeStyles.newGroupButton).toBeTypeOf("string");
    expect(routeStyles.groupComposerPanel).toBeTypeOf("string");
    expect(routeStyles.groupAgentOption).toBeTypeOf("string");
    expect(routeStyles.createGroupButton).toBeTypeOf("string");
  });

  it("binds chat sessions through AgentInstance ids instead of model-profile templates", () => {
    expect(routeSource).toContain("body: JSON.stringify({ agentId })");
    expect(routeSource).toContain("sessionAgentOptions");
    expect(routeSource).toContain("value={activeAgentId}");
    expect(routeSource).not.toContain("fetchJson<SessionAgentTemplate[]>");
    expect(routeSource).not.toContain("body: JSON.stringify({ agentProfileId })");
  });

  it("opens group conversations inside the chat page instead of navigating away", () => {
    expect(routeSource).toContain("activeGroupRoomId");
    expect(routeSource).toContain("handleOpenGroupRoom");
    expect(routeSource).toContain("setRightPaneCollapsed(false)");
    expect(routeSource).toContain("chatRoomModeLabel(mode, lang)");
    expect(routeSource).toContain("抢占式讨论");
    expect(routeSource).toContain("fetchJson<ChatRoomDetail>(`/api/chat-rooms/${activeGroupRoomId}`)");
    expect(routeSource).toContain("new EventSource(`/api/chat-rooms/${streamRoomId}/events`)");
    expect(routeSource).toContain("syncChatRoomDetail(payload.detail)");
    expect(routeSource).toContain("browser.chat_room_stream.closed");
    expect(routeSource).toContain("handleStartGroupRound");
    expect(routeSource).toContain("stopGroupRoundMutation");
    expect(routeSource).toContain("fetchJson<ChatRoomDetail>(`/api/chat-rooms/${roomId}/stop`");
    expect(routeSource).toContain("handleStopGroupRound");
    expect(routeSource).toContain("disabled={startGroupRoundMutation.isPending}");
    expect(routeSource).toContain("updateGroupRoomMutation");
    expect(routeSource).toContain("deleteGroupRoomMutation");
    expect(routeSource).toContain("groupManageTitleDraft");
    expect(routeSource).toContain("title: groupManageTitleDraft.trim()");
    expect(routeSource).toContain("participantSessionIds: sessionIds");
    expect(routeSource).toContain("groupManageSessionIds.length < 2");
    expect(routeSource).toContain("setGroupManageSessionIds((current) => current.filter((sessionId) => sessionId !== variables.sessionId))");
    expect(routeSource).toContain("styles.groupManagementPanel");
    expect(routeSource).toContain("styles.groupConversationFrame");
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
    expect(routeStyles.groupTypingDots).toBeTypeOf("string");
    expect(routeStyles.groupComposerBar).toBeTypeOf("string");
    expect(routeStyles.groupStopButton).toBeTypeOf("string");
  });

  it("logs direct session stream close events for lifecycle diagnosis", () => {
    expect(routeSource).toContain("browser.session_stream.opened");
    expect(routeSource).toContain("browser.session_stream.closed");
    expect(routeSource).toContain("readyStateBeforeClose");
    expect(routeSource).toContain("stream.close()");
  });

  it("visually distinguishes direct sessions from group chats in the conversation list", () => {
    expect(routeSource).toContain("avatarInitials");
    expect(routeSource).toContain("styles.conversationAvatarDirect");
    expect(routeSource).toContain("styles.conversationAvatarGroup");
    expect(routeSource).toContain("styles.directSessionItem");
    expect(routeSource).toContain("styles.groupSessionItem");
    expect(routeSource).toContain("styles.conversationKindBadgeDirect");
    expect(routeSource).toContain("styles.conversationKindBadgeGroup");

    expect(routeStyles.conversationAvatar).toBeTypeOf("string");
    expect(routeStyles.conversationAvatarDirect).toBeTypeOf("string");
    expect(routeStyles.conversationAvatarGroup).toBeTypeOf("string");
    expect(routeStyles.conversationTitleRow).toBeTypeOf("string");
    expect(routeStyles.conversationMetaRow).toBeTypeOf("string");
    expect(routeStyles.sessionActionStack).toBeTypeOf("string");
    expect(routeStyles.directSessionItem).toBeTypeOf("string");
    expect(routeStyles.groupSessionItem).toBeTypeOf("string");
    expect(routeStyles.conversationKindBadge).toBeTypeOf("string");
    expect(routeStyles.conversationKindBadgeDirect).toBeTypeOf("string");
    expect(routeStyles.conversationKindBadgeGroup).toBeTypeOf("string");
  });

  it("shows each visible agent with a functional role label, not only a person name", () => {
    expect(routeSource).toContain("metadataString(agent, \"functionalDisplayName\")");
    expect(routeSource).toContain("formatAgentFunctionFromInstance");
    expect(routeSource).toContain("formatAgentIdentityWithFunction");
    expect(routeSource).toContain("const sessionAgent = session.agentId ? agentsById.get(session.agentId) : undefined");
    expect(routeSource).toContain("const sessionAgentMeta = formatAgentMeta(session.agentCode, sessionAgentFunction, session.agentProfileId)");
    expect(routeSource).toContain("const participantFunction = formatAgentFunction(");
    expect(routeSource).toContain("styles.groupMemberCopy");

    expect(routeStyles.groupMemberCopy).toBeTypeOf("string");
  });

  it("groups the unified conversation list like expandable contact folders", () => {
    expect(routeSource).toContain("DEFAULT_COLLAPSED_CONVERSATION_GROUPS");
    expect(routeSource).toContain("CONVERSATION_GROUP_ORDER");
    expect(routeSource).toContain("classifyConversation");
    expect(routeSource).toContain("conversationGroupLabel");
    expect(routeSource).toContain("groupedConversations.map");
    expect(routeSource).toContain("toggleConversationGroup");
    expect(routeSource).toContain("styles.conversationGroupHeader");
    expect(routeSource).toContain("aria-expanded={!collapsed}");
    expect(routeSource).toContain("searchHasTerm");

    expect(routeStyles.conversationGroup).toBeTypeOf("string");
    expect(routeStyles.conversationGroupHeader).toBeTypeOf("string");
    expect(routeStyles.conversationGroupList).toBeTypeOf("string");
  });

  it("asks for confirmation before deleting conversations", () => {
    expect(routeSource).toContain("t(\"deleteSessionConfirm\").replace(\"{title}\"");
    expect(routeSource).toContain("t(\"deleteGroupConfirm\").replace(\"{title}\"");
    expect(routeSource).toContain("if (!window.confirm(sessionConfirmMessage))");
    expect(routeSource).toContain("if (!window.confirm(groupConfirmMessage))");
    expect(routeSource.indexOf("window.confirm(sessionConfirmMessage)")).toBeLessThan(
      routeSource.indexOf("deleteSessionMutation.mutate({ sessionId: session.id })"),
    );
    expect(routeSource.indexOf("window.confirm(groupConfirmMessage)")).toBeLessThan(
      routeSource.indexOf("deleteGroupRoomMutation.mutate({ roomId: activeGroupRoomId })"),
    );
  });

  it("removes deleted direct sessions from cached lists before refetch", () => {
    const deleteMutationSource = routeSource.slice(routeSource.indexOf("const deleteSessionMutation"));
    expect(routeSource).toContain("removeDeletedSessionFromSummaries");
    expect(routeSource).toContain("removeDeletedSessionFromConversations");
    expect(deleteMutationSource).toContain("queryClient.setQueryData<SessionSummary[]>(queryKeys.sessions()");
    expect(deleteMutationSource).toContain("queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations()");
    expect(routeSource).toContain("conversation.type !== \"direct_agent\"");
    expect(routeSource).toContain("conversation.directSessionId !== deletedSessionId && conversation.conversationId !== deletedSessionId");
    expect(deleteMutationSource.indexOf("queryClient.setQueryData<SessionSummary[]>(queryKeys.sessions()")).toBeLessThan(
      deleteMutationSource.indexOf("void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() })"),
    );
    expect(deleteMutationSource.indexOf("queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations()")).toBeLessThan(
      deleteMutationSource.indexOf("void queryClient.invalidateQueries({ queryKey: queryKeys.conversations() })"),
    );
  });
});
