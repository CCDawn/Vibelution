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

  it("renders runtime notices outside the Agent reply timeline", () => {
    expect(routeSource).toContain("detail?.runtimeNotices");
    expect(routeSource).toContain(".slice(-1)");
    expect(routeSource).toContain("styles.runtimeNoticeStack");
    expect(routeSource).toContain("styles.runtimeNoticeMessage");
    expect(routeSource.indexOf("styles.runtimeNoticeStack")).toBeLessThan(
      routeSource.indexOf("<ConversationView"),
    );
    expect(routeStyles.runtimeNoticeStack).toBeTypeOf("string");
    expect(routeStyles.runtimeNotice).toBeTypeOf("string");
    expect(routeStyles.runtimeNotice_warning).toBeTypeOf("string");
    expect(routeStyles.runtimeNoticeMessage).toBeTypeOf("string");
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
    expect(routeStyles.rightIndexTabsSingle).toBeTypeOf("string");
    expect(routeStyles.rightIndexTab).toBeTypeOf("string");
    expect(routeStyles.memberIndexSummary).toBeTypeOf("string");
    expect(routeStyles.agentIndexRoster).toBeTypeOf("string");
    expect(routeStyles.agentIndexList).toBeTypeOf("string");
    expect(routeStyles.agentIndexCard).toBeTypeOf("string");
    expect(routeStyles.agentIndexHeader).toBeTypeOf("string");
    expect(routeStyles.agentIndexNameLine).toBeTypeOf("string");
    expect(routeStyles.agentIndexDetails).toBeTypeOf("string");
    expect(routeStyles.agentIndexMentalBlock).toBeTypeOf("string");
    expect(routeStyles.agentIndexEmptyState).toBeTypeOf("string");
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

  it("exposes dynamic group creation from the unified conversation list", () => {
    expect(routeSource).toContain("handleToggleGroupComposer");
    expect(routeSource).toContain("handleCreateGroupRoom");
    expect(routeSource).toContain("fetchJson<AgentInstance[]>(\"/api/agents\")");
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

  it("binds chat sessions through AgentInstance ids instead of model-profile templates", () => {
    expect(routeSource).toContain("body: JSON.stringify({ agentId })");
    expect(routeSource).toContain("sessionAgentOptions");
    expect(routeSource).toContain("value={activeAgentId}");
    expect(routeSource).toContain("styles.sessionAgentStatusControl");
    expect(routeSource).toContain("styles.sessionAgentStatusSelect");
    expect(routeSource).not.toContain("styles.agentTemplatePanel");
    expect(routeSource).not.toContain("fetchJson<SessionAgentTemplate[]>");
    expect(routeSource).not.toContain("body: JSON.stringify({ agentProfileId })");
    expect(routeStyles.sessionAgentStatusControl).toBeTypeOf("string");
    expect(routeStyles.sessionAgentStatusSelect).toBeTypeOf("string");
    expect(routeStyles.sessionAgentStatusMeta).toBeTypeOf("string");
  });

  it("opens group conversations inside the chat page instead of navigating away", () => {
    expect(routeSource).toContain("activeGroupRoomId");
    expect(routeSource).toContain("handleOpenGroupRoom");
    expect(routeSource).toContain('new URLSearchParams(location.search).get("room")');
    expect(routeSource).toContain("requestedRoomId && activeGroupRoomId !== requestedRoomId");
    expect(routeSource).toContain("setRightPaneCollapsed(false)");
    expect(routeSource).toContain("chatRoomModeLabel(mode, lang)");
    expect(routeSource).toContain("chatRoomPurposeLabel(purpose, lang)");
    expect(routeSource).toContain("queryKeys.chatRoomPurposes()");
    expect(routeSource).toContain("fetchJson<ChatRoomPurpose[]>(\"/api/chat-rooms/purposes\")");
    expect(routeSource).toContain("抢占式讨论");
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
    expect(routeSource).toContain("stripGroupSpeakerPrefix(message, speakerIdentity.name)");
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

  it("backs off index polling when detail streams are connected", () => {
    expect(routeSource).toContain("const ACTIVE_INDEX_POLL_MS = 3_000");
    expect(routeSource).toContain("const STREAM_BACKED_INDEX_POLL_MS = 15_000");
    expect(routeSource).toContain("sessionStreamConnected ? STREAM_BACKED_INDEX_POLL_MS : ACTIVE_INDEX_POLL_MS");
    expect(routeSource).toContain("sessionStreamConnected || groupStreamConnected ? STREAM_BACKED_INDEX_POLL_MS : ACTIVE_INDEX_POLL_MS");
    expect(routeSource).toContain("mergeSessionDetailIntoConversations(conversations, detail)");
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
    expect(routeSource).toContain("agentDisplayInfo(agent, lang)");
    expect(routeSource).toContain("sessionAgentDisplayInfo(session, sessionAgent, lang)");
    expect(routeSource).toContain("participantAgentDisplayInfo(participantLike, participantAgent, lang)");
    expect(routeSource).toContain("const sessionAgent = session.agentId ? agentsById.get(session.agentId) : undefined");
    expect(routeSource).toContain("const sessionDisplay = sessionAgentDisplayInfo(session, sessionAgent, lang)");
    expect(routeSource).toContain("const participantDisplay = groupParticipantIdentity(participant)");
    expect(routeSource).toContain("identityLabel: formatAgentIdentityWithRole");
    expect(routeSource).toContain("styles.groupMemberCopy");
    expect(routeSource).toContain("styles.agentRoleTag");

    expect(routeStyles.groupMemberCopy).toBeTypeOf("string");
    expect(routeStyles.agentRoleTag).toBeTypeOf("string");
  });

  it("hides direct sessions whose Agent is no longer active in Agent Center", () => {
    expect(routeSource).toContain("function isVisibleDirectSession");
    expect(routeSource).toContain("return !session.agentMissing");
    expect(routeSource).toContain("function isVisibleConversation");
    expect(routeSource).toContain("return !conversation.agentMissing");
    expect(routeSource).toContain("return sessions.filter(isVisibleDirectSession)");
    expect(routeSource).toContain("const visibleSessions = useMemo");
    expect(routeSource).toContain("visibleSessions.map(sessionToConversationSummary)");
    expect(routeSource).toContain("conversation.type !== \"group_room\"");
    expect(routeSource).toContain(".filter((conversation) => isVisibleConversation(conversation, sessionsById))");
  });

  it("renders a QQ-style tree with direct sessions separate from Team-owned rooms", () => {
    expect(routeSource).toContain("fetchJson<TeamListPayload>(\"/api/teams\")");
    expect(routeSource).toContain("queryKeys.teams()");
    expect(routeSource).toContain("linkedTeamRoomIds");
    expect(routeSource).toContain("filteredTeams");
    expect(routeSource).toContain("filteredStandaloneGroupConversations");
    expect(routeSource).toContain("team.linkedChatRoom?.title");
    expect(routeSource).toContain("team.members ?? []");
    expect(routeSource).toContain("群成员");
    expect(routeSource).toContain("未归属群聊");
    expect(routeSource).toContain("styles.conversationTreeRootHeader");
    expect(routeSource).toContain("styles.teamTreeGroup");
    expect(routeSource).toContain("styles.teamTreeChildren");
    expect(routeSource).toContain("styles.teamTreeChild");

    expect(routeStyles.conversationTreeRootHeader).toBeTypeOf("string");
    expect(routeStyles.teamTreeGroup).toBeTypeOf("string");
    expect(routeStyles.teamTreeItem).toBeTypeOf("string");
    expect(routeStyles.teamTreeChildren).toBeTypeOf("string");
    expect(routeStyles.teamTreeChild).toBeTypeOf("string");
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
    expect(routeSource).toContain("title={deleteDisabled ? t(\"deleteSessionBusy\") : t(\"deleteSession\")}");
    expect(routeSource).toContain("if (!window.confirm(sessionConfirmMessage))");
    expect(routeSource).toContain("if (!window.confirm(groupConfirmMessage))");
    expect(routeSource).toContain("[session.id]: t(\"deleteSessionBusy\")");
    expect(routeSource).toContain("const deleteBusyReason = sessionIsBusy ? t(\"deleteSessionBusy\") : \"\"");
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
    expect(deleteMutationSource).toContain("queryClient.setQueryData<SessionSummary[]>(queryKeys.sessions()");
    expect(deleteMutationSource).toContain("queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations()");
    expect(routeSource).toContain("conversation.type !== \"direct_agent\"");
    expect(routeSource).toContain("conversation.directSessionId !== deletedSessionId && conversation.conversationId !== deletedSessionId");
    expect(deleteMutationSource.indexOf("queryClient.setQueryData<SessionSummary[]>(queryKeys.sessions()")).toBeLessThan(
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
    const renameMutationSource = routeSource.slice(routeSource.indexOf("const renameSessionMutation"));
    expect(routeSource).toContain("mergeSessionDetailIntoConversations");
    expect(routeSource).toContain("title: String(session.title || session.agentDisplayName || session.id).trim()");
    expect(routeSource).toContain("agentDisplayName: conversation.agentDisplayName");
    expect(routeSource).toContain("const sessionAgentName =");
    expect(routeSource).toContain("{session.title || sessionDisplay.name}");
    expect(renameMutationSource).toContain("queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations()");
    expect(renameMutationSource.indexOf("queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations()")).toBeLessThan(
      renameMutationSource.indexOf("syncSessionDetail(nextDetail)"),
    );
    expect(renameMutationSource.indexOf("queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations()")).toBeLessThan(
      renameMutationSource.indexOf("void chatWorkspaceCache.afterSessionChanged({ sessionId: variables.sessionId })"),
    );
  });

  it("classifies direct conversations from Agent Center role metadata", () => {
    expect(routeSource).toContain("agentPrimaryMode: session.agentPrimaryMode");
    expect(routeSource).toContain("agentRoleKey: session.agentRoleKey");
    expect(routeSource).toContain("agentPromptTemplateId: session.agentPromptTemplateId");
    expect(routeSource).toContain("primaryMode === \"research\"");
    expect(routeSource).toContain("roleKey.startsWith(\"research_\")");
    expect(routeSource).toContain("promptTemplateId.startsWith(\"prompt-research-\")");
  });
});
