import {
  Bot,
  ChevronRight,
  MessageSquarePlus,
  MessageCircleHeart,
  UsersRound,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type Dispatch, type ReactNode, type Ref, type SetStateAction } from "react";

import type {
  AgentInstance,
  ChatRoomDetail,
  ChatRoomMode,
  ChatRoomParticipant,
  ChatRoomPurpose,
  SessionDetail,
  SessionSummary,
  Team,
} from "../../api/types";
import {
  VButton,
  VContextualHint,
  VNativeButton,
  VNativeInput,
  VStateSurface,
  VStringSelect,
  VTabs,
} from "../../components/vui";
import type { VDropdownMenuItem } from "../../components/vui";
import type { TranslationKey } from "../../i18n/dictionary";
import { agentDisplayInfo } from "../agentDisplay";
import {
  contextUsagePercent,
  formatContextUsage,
  formatRelativeTime,
} from "../chatShellFormat";
import routeStyles from "../ChatCodingRoute.styles";
import { ProgressiveRegionSkeleton } from "../shared/ProgressiveRegionSkeleton";
import styles from "./ChatConversationIndexRail.styles";
import { ChatSessionIndexToolbar } from "./ChatSessionIndexToolbar";
import { ChatSessionIndexSearch } from "./ChatSessionIndexSearch";
import type { SessionListPreferences } from "./sessionListPreferences";
import { SESSION_INDEX_SEARCH_EVENT } from "../../shortcuts/sessionSearchDispatch";

export type ConversationIndexPanelKey = "conversations" | "members";

export type ChatConversationIndexRailProps = {
  agentsById: Map<string, AgentInstance>;
  agentsPending: boolean;
  availableChatRoomPurposes: ChatRoomPurpose[];
  availableGroupParticipantCount: number;
  availableGroupParticipants: ChatRoomParticipant[];
  activeGroupRoom: ChatRoomDetail | null | undefined;
  groupRoomInitialLoading: boolean;
  groupRoomLoadError?: string;
  chatRoomModesPending: boolean;
  chatRoomPurposesPending: boolean;
  conversationIndexCollapsed: boolean;
  onCollapseConversationIndex: () => void;
  conversationIndexOverlayOpen: boolean;
  conversationIndexPanel: ReactNode;
  sessionListPreferences: SessionListPreferences;
  onSessionListPreferencesChange: (patch: Partial<SessionListPreferences>) => void;
  onOpenSearchAgent: (agent: AgentInstance) => void;
  onOpenSearchTeam: (team: Team) => void;
  showArchivedSessions: boolean;
  onToggleShowArchivedSessions: () => void;
  conversationIndexPaneClassName: string;
  createGroupRoomPending: boolean;
  createSessionPending: boolean;
  createAgentButtonRef?: Ref<HTMLButtonElement>;
  describeError: (error: unknown, fallback: string) => string;
  expandedGroupAgentDetailsBySessionId: Map<string, { data?: SessionDetail; isPending?: boolean; isError?: boolean; error?: unknown }>;
  expandedGroupAgentSessionIds: string[];
  groupCandidateAgents: AgentInstance[];
  groupComposerOpen: boolean;
  groupModeDraft: string;
  groupPurposeDraft: string;
  groupSelectedAgentIds: string[];
  groupTitleDraft: string;
  lang: "zh" | "en";
  locale: string;
  numberFormatter: Intl.NumberFormat;
  onCreateAgent: () => void;
  onCreateSession: () => void;
  onCreateGroupRoom: () => void;
  onOpenDirectSession: (sessionId: string) => void;
  onPrefetchDirectSession?: (sessionId: string) => void;
  activeSessionId: string | null;
  onSetActiveTab: (sessionId: string, tab: "agent") => void;
  sessionIdsNeedingApproval?: readonly string[];
  runtimeRunningSessionIds?: readonly string[];
  teams?: Team[];
  onToggleGroupAgent: (agentId: string) => void;
  onToggleGroupComposer: () => void;
  readyChatRoomModes: ChatRoomMode[];
  renderAgentAvatar: (className: string, imageUrl: string | undefined, fallback: string) => ReactNode;
  avatarInitials: (agentCode?: string, name?: string, fallback?: string) => string;
  agentRoleClass: (tone: string) => string;
  avatarImageUrlFrom: (...sources: unknown[]) => string | undefined;
  groupParticipantIdentity: (
    participant: ChatRoomParticipant | undefined,
    fallback?: {
      agentId?: string;
      agentCode?: string;
      title?: string;
      participantId?: string;
      agentAvatarImageUrl?: string;
    },
  ) => {
    name: string;
    functionLabel: string;
    tone: string;
    modelLabel?: string;
  };
  latestMentalSnapshot: (messages: SessionDetail["messages"] | undefined) => {
    mood?: string | null;
    cognitiveState?: string | null;
    feeling?: string | null;
    summary?: string | null;
    updatedAt?: string | null;
  } | undefined;
  chatRoomModeLabel: (mode: ChatRoomMode, lang: "zh" | "en") => string;
  chatRoomPurposeLabel: (purpose: ChatRoomPurpose, lang: "zh" | "en") => string;
  statusLabel: (status: string) => string;
  resolveModelLabel: (modelId: string) => string | undefined;
  rightIndexPanel: ConversationIndexPanelKey;
  sessionsById: Map<string, SessionSummary>;
  setExpandedGroupAgentSessionIds: Dispatch<SetStateAction<string[]>>;
  setGroupModeDraft: Dispatch<SetStateAction<string>>;
  setGroupPurposeDraft: Dispatch<SetStateAction<string>>;
  setGroupTitleDraft: Dispatch<SetStateAction<string>>;
  setRightIndexPanel: Dispatch<SetStateAction<ConversationIndexPanelKey>>;
  standardGroupRoomActive: boolean;
  t: (key: TranslationKey) => string;
};

export function ChatConversationIndexRail(props: ChatConversationIndexRailProps) {
  const {
    agentsById,
    agentsPending,
    availableChatRoomPurposes,
    availableGroupParticipantCount,
    availableGroupParticipants,
    activeGroupRoom,
    groupRoomInitialLoading,
    groupRoomLoadError,
    chatRoomModesPending,
    chatRoomPurposesPending,
    conversationIndexCollapsed,
    onCollapseConversationIndex,
    conversationIndexOverlayOpen,
    conversationIndexPanel,
    sessionListPreferences,
    onSessionListPreferencesChange,
    onOpenSearchAgent,
    onOpenSearchTeam,
    showArchivedSessions,
    onToggleShowArchivedSessions,
    conversationIndexPaneClassName,
    createGroupRoomPending,
    createSessionPending,
    createAgentButtonRef,
    describeError,
    expandedGroupAgentDetailsBySessionId,
    expandedGroupAgentSessionIds,
    groupCandidateAgents,
    groupComposerOpen,
    groupModeDraft,
    groupPurposeDraft,
    groupSelectedAgentIds,
    groupTitleDraft,
    lang,
    locale,
    numberFormatter,
    onCreateAgent,
    onCreateSession,
    onCreateGroupRoom,
    onOpenDirectSession,
    onPrefetchDirectSession,
    activeSessionId,
    onSetActiveTab,
    sessionIdsNeedingApproval = [],
    runtimeRunningSessionIds = [],
    teams = [],
    onToggleGroupAgent,
    onToggleGroupComposer,
    readyChatRoomModes,
    renderAgentAvatar,
    avatarInitials,
    agentRoleClass,
    avatarImageUrlFrom,
    groupParticipantIdentity,
    latestMentalSnapshot,
    chatRoomModeLabel,
    chatRoomPurposeLabel,
    statusLabel,
    resolveModelLabel,
    rightIndexPanel,
    sessionsById,
    setExpandedGroupAgentSessionIds,
    setGroupModeDraft,
    setGroupPurposeDraft,
    setGroupTitleDraft,
    setRightIndexPanel,
    standardGroupRoomActive,
    t,
  } = props;

  const [createMenuOpen, setCreateMenuOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [indexScrolling, setIndexScrolling] = useState(false);
  const [indexScrollbarDragging, setIndexScrollbarDragging] = useState(false);
  const indexScrollTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const onIndexScroll = () => {
    setIndexScrolling(true);
    clearTimeout(indexScrollTimer.current);
    indexScrollTimer.current = setTimeout(() => setIndexScrolling(false), 800);
  };

  useEffect(() => () => clearTimeout(indexScrollTimer.current), []);
  useEffect(() => {
    if (!indexScrollbarDragging) return;
    const stopDragging = () => setIndexScrollbarDragging(false);
    window.addEventListener("pointerup", stopDragging);
    window.addEventListener("pointercancel", stopDragging);
    window.addEventListener("blur", stopDragging);
    return () => {
      window.removeEventListener("pointerup", stopDragging);
      window.removeEventListener("pointercancel", stopDragging);
      window.removeEventListener("blur", stopDragging);
    };
  }, [indexScrollbarDragging]);

  const createItems = useMemo<VDropdownMenuItem[]>(() => [
    {
      id: "new-session",
      icon: <MessageSquarePlus size={14} />,
      label: lang === "zh" ? "新建会话" : "New session",
      disabled: createSessionPending,
      onSelect: onCreateSession,
    },
    {
      id: "new-agent",
      icon: <Bot size={14} />,
      label: lang === "zh" ? "新建 Agent" : "New Agent",
      onSelect: onCreateAgent,
    },
    {
      id: "new-group",
      icon: <UsersRound size={14} />,
      label: lang === "zh" ? "新建群聊" : "New group",
      disabled: createGroupRoomPending,
      onSelect: onToggleGroupComposer,
    },
  ], [createGroupRoomPending, createSessionPending, lang, onCreateAgent, onCreateSession, onToggleGroupComposer]);

  useEffect(() => {
    const openIndexSearch = (event: Event) => {
      event.preventDefault();
      setOptionsOpen(false);
      setCreateMenuOpen(false);
      setSearchOpen(true);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.isComposing || !(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey) {
        return;
      }
      const key = event.key.toLocaleLowerCase();
      if (key === "n") {
        event.preventDefault();
        setOptionsOpen(false);
        if (showArchivedSessions) onToggleShowArchivedSessions();
        setCreateMenuOpen(true);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener(SESSION_INDEX_SEARCH_EVENT, openIndexSearch);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener(SESSION_INDEX_SEARCH_EVENT, openIndexSearch);
    };
  }, [showArchivedSessions, onToggleShowArchivedSessions]);

  return (
      <aside
        id="chat-conversation-index-pane"
        className={conversationIndexOverlayOpen ? `${conversationIndexPaneClassName} ${styles.railOverlay}` : conversationIndexPaneClassName}
        data-vui-region="chat-session-index"
        aria-keyshortcuts="Control+K Meta+K"
        aria-hidden={conversationIndexCollapsed}
        role={conversationIndexOverlayOpen ? "dialog" : undefined}
        aria-label={conversationIndexOverlayOpen ? (lang === "zh" ? "会话列表" : "Conversation list") : undefined}
      >
          <ChatSessionIndexToolbar
            lang={lang} archived={showArchivedSessions} preferences={sessionListPreferences}
            onPreferencesChange={onSessionListPreferencesChange} onToggleArchive={onToggleShowArchivedSessions}
            onSearch={() => { setOptionsOpen(false); setCreateMenuOpen(false); setSearchOpen(true); }} onCollapse={onCollapseConversationIndex}
            createItems={createItems} createOpen={createMenuOpen} onCreateOpenChange={setCreateMenuOpen}
            createButtonRef={createAgentButtonRef} optionsOpen={optionsOpen} onOptionsOpenChange={setOptionsOpen}
          />

        {standardGroupRoomActive ? (
          <div className={styles.railGroupHeader}>
          <VTabs
            aria-label={lang === "zh" ? "左侧索引" : "Left index"}
            value={rightIndexPanel}
            onValueChange={(value) => {
              if (value === "conversations" || value === "members") {
                setRightIndexPanel(value);
              }
            }}
            className="min-w-0"
            listClassName={styles.rightIndexTabs}
            triggerClassName={styles.rightIndexTab}
            items={[
              {
                id: "conversations",
                label: (
                  <>
                    <MessageCircleHeart size={14} aria-hidden="true" />
                    <span>{lang === "zh" ? "会话" : "Chats"}</span>
                  </>
                ),
              },
              {
                id: "members",
                label: (
                  <>
                    <UsersRound size={14} aria-hidden="true" />
                    <span>{lang === "zh" ? "成员" : "Members"}</span>
                  </>
                ),
              },
            ]}
          />

        {rightIndexPanel === "members" ? (
          groupRoomInitialLoading ? (
            <ProgressiveRegionSkeleton
              variant="detail"
              label={lang === "zh" ? "正在加载群聊成员摘要" : "Loading group member summary"}
            />
          ) : (
            <div className={styles.memberIndexSummary}>
              <UsersRound size={15} />
              <span>
                {availableGroupParticipantCount} {lang === "zh" ? "位可用助手" : "available agents"}
              </span>
              <strong>{statusLabel(activeGroupRoom?.status ?? "ready")}</strong>
            </div>
          )
        ) : null}
          </div>
        ) : null}

        <div
          className={
            rightIndexPanel === "members" && standardGroupRoomActive
              ? styles.panelBody
              : `${styles.panelBody} ${styles.conversationIndexPanelBody}`
          }
        >
          {rightIndexPanel === "members" && standardGroupRoomActive ? (
            groupRoomInitialLoading ? (
              <ProgressiveRegionSkeleton
                variant="list"
                label={lang === "zh" ? "正在加载群聊成员" : "Loading group members"}
              />
            ) : (
              <section className={styles.agentIndexRoster} aria-label={lang === "zh" ? "群成员状态索引" : "Group member status index"}>
              <div className={routeStyles.sectionHeader}>
                <div className={routeStyles.sectionIdentity}>
                  <div className={routeStyles.sectionEyebrowRow}>
                    <p className={routeStyles.blockEyebrow}>{lang === "zh" ? "成员状态" : "Member status"}</p>
                    <VContextualHint
                      content={lang === "zh"
                        ? "只展示可用成员；已归档或断链的历史成员保留在日志里，不在这里打扰。"
                        : "Only available members are shown here; archived or broken historical members stay in diagnostics."}
                      label={lang === "zh" ? "成员状态筛选说明" : "Member status filter details"}
                      width="wide"
                    />
                  </div>
                  <h3 className={routeStyles.sectionTitle}>{activeGroupRoom?.title
                    ?? (groupRoomInitialLoading
                      ? (lang === "zh" ? "群聊加载中" : "Loading group")
                      : groupRoomLoadError
                        ? (lang === "zh" ? "群聊加载失败" : "Group failed to load")
                        : (lang === "zh" ? "暂无群聊" : "No group room"))}</h3>
                </div>
              </div>
              {availableGroupParticipants.length ? (
                <div className={styles.agentIndexList}>
                  {availableGroupParticipants.map((participant) => {
                  const expanded = expandedGroupAgentSessionIds.includes(participant.sessionId);
                  const participantSession = sessionsById.get(participant.sessionId);
                  const expandedDetailQuery = expandedGroupAgentDetailsBySessionId.get(participant.sessionId);
                  const memberDetail = expanded ? expandedDetailQuery?.data : undefined;
                  const memberContext = memberDetail?.contextUsage;
                  const memberContextUsed = memberContext?.used ?? 0;
                  const memberContextLimit = memberContext?.limit ?? 0;
                  const memberContextPercent = contextUsagePercent(memberContextUsed, memberContextLimit);
                  const memberMental = latestMentalSnapshot(memberDetail?.messages);
                  const memberMentalState = memberMental?.mood?.trim()
                    || memberMental?.cognitiveState?.trim()
                    || (lang === "zh" ? "未记录" : "No snapshot");
                  const memberMentalSummary = memberMental?.feeling?.trim()
                    || memberMental?.summary?.trim()
                    || (lang === "zh" ? "该助手尚未形成可展示的心智快照。" : "This agent has no visible mental snapshot yet.");
                  const participantDisplay = groupParticipantIdentity(participant);
                  const participantAgent = participant.agentId ? agentsById.get(participant.agentId) : undefined;
                  const participantAvatarImageUrl = avatarImageUrlFrom(participantAgent, participant);
                  const memberUpdated = formatRelativeTime(
                    memberMental?.updatedAt || memberDetail?.updatedAt || participantSession?.updatedAt || "",
                    Date.now(),
                    locale,
                  );
                  return (
                    <article key={participant.participantId || participant.sessionId} className={styles.agentIndexCard}>
                      <div className={styles.agentIndexHeader}>
                        <VButton
                          type="button"
                          className={styles.agentIndexExpandButton}
                          aria-expanded={expanded}
                          aria-label={expanded
                            ? (lang === "zh" ? `收起 ${participantDisplay.name} 状态` : `Collapse ${participantDisplay.name} status`)
                            : (lang === "zh" ? `展开 ${participantDisplay.name} 状态` : `Expand ${participantDisplay.name} status`)}
                          onClick={() =>
                            setExpandedGroupAgentSessionIds((current) =>
                              current.includes(participant.sessionId)
                                ? current.filter((sessionId) => sessionId !== participant.sessionId)
                                : [...current, participant.sessionId],
                            )}
                            isIconOnly
                            icon={<ChevronRight size={14} aria-hidden="true"/>} />
                        <VButton
                          type="button"
                          contentLayout="plain"
                          className={styles.agentIndexOpenButton}
                          onPointerEnter={() => onPrefetchDirectSession?.(participant.sessionId)}
                          onFocus={() => onPrefetchDirectSession?.(participant.sessionId)}
                          onClick={() => onOpenDirectSession(participant.sessionId)}
                          aria-label={lang === "zh" ? `打开 ${participantDisplay.name} 单聊` : `Open direct chat with ${participantDisplay.name}`}
                          tooltip={lang === "zh"
                            ? "打开该助手的单聊。群聊成员由群聊调度驱动；需要单独调整下一轮功能时，请在单聊中完成。"
                            : "Open this Agent direct chat. Group members are driven by group scheduling; tune next-turn features in the direct chat."}
                        >
                          {renderAgentAvatar(
                            styles.agentIndexAvatar,
                            participantAvatarImageUrl,
                            avatarInitials(participant.agentCode, participant.title),
                          )}
                          <span className={styles.agentIndexCopy}>
                            <strong className={styles.agentIndexNameLine}>
                              <span>{participantDisplay.name}</span>
                              <em className={`${routeStyles.agentRoleTag} ${styles[agentRoleClass(participantDisplay.tone)]}`}>
                                {participantDisplay.functionLabel}
                              </em>
                            </strong>
                            {participantDisplay.modelLabel ? (
                              <span className={styles.agentModelLine} title={participantDisplay.modelLabel}>
                                {participantDisplay.modelLabel}
                              </span>
                            ) : null}
                          </span>
                        </VButton>
                        <span className={styles.agentIndexStatus}>
                          {statusLabel(participant.status || participantSession?.status || "ready")}
                        </span>
                      </div>
                      {expanded ? (
                        <div className={styles.agentIndexDetails}>
                          {expandedDetailQuery?.isPending ? (
                            <ProgressiveRegionSkeleton variant="list" label={t("loadingSession")} />
                          ) : expandedDetailQuery?.isError ? (
                            <VStateSurface
                              tone="error"
                              title={describeError(expandedDetailQuery.error, t("loadFailed"))}
                            />
                          ) : (
                            <>
                              <div className={routeStyles.resourceSplit}>
                                <div className={routeStyles.resourceMetric}>
                                  <span>{t("contextInUse")}</span>
                                  <strong>{formatContextUsage(memberContextUsed, memberContextLimit, locale)}</strong>
                                </div>
                                <div className={routeStyles.resourceMetric}>
                                  <span>{lang === "zh" ? "上下文占比" : "Context ratio"}</span>
                                  <strong>{memberContextPercent}%</strong>
                                </div>
                              </div>
                              <p className={routeStyles.oneLineValue}>
                                <span>{lang === "zh" ? "消息" : "Messages"}</span>
                                {memberContext
                                  ? `${numberFormatter.format(memberContext.messageCount)} ${lang === "zh" ? "条" : "messages"} · ${numberFormatter.format(memberContext.assistantMessageCount)} Agent`
                                  : (lang === "zh" ? "暂无上下文统计" : "No context stats yet")}
                              </p>
                              <div className={styles.agentIndexMentalBlock}>
                                <div className={routeStyles.sectionHeader}>
                                  <div className={routeStyles.sectionIdentity}>
                                    <p className={routeStyles.blockEyebrow}>{t("mentalState")}</p>
                                    <p className={styles.sectionMetaLine}>
                                      {memberUpdated || (lang === "zh" ? "尚未更新" : "Not updated yet")}
                                    </p>
                                  </div>
                                  <span className={routeStyles.mentalStateBadge}>{memberMentalState}</span>
                                </div>
                                <p className={routeStyles.contextLineCompact}>{memberMentalSummary}</p>
                              </div>
                            </>
                          )}
                        </div>
                      ) : null}
                    </article>
                  );
                  })}
                </div>
              ) : (
                <div className={styles.agentIndexEmptyState}>
                  <UsersRound size={24} />
                  <p>
                    {lang === "zh"
                      ? "暂无可用群成员。请在右侧群设置中选择成员并应用变更。"
                      : "No available group members. Choose members in the right group settings and apply the change."}
                  </p>
                </div>
              )}
              </section>
            )
          ) : (
            <div className={styles.conversationIndexLayout}>
            <div
              className={styles.conversationIndexScrollRegion}
              role="region"
              aria-label={lang === "zh" ? "会话目录" : "Conversation directory"}
              tabIndex={0}
              data-scroll-active={indexScrolling ? "true" : undefined}
              data-scroll-dragging={indexScrollbarDragging ? "true" : undefined}
              onScroll={onIndexScroll}
              onPointerDown={(event) => {
                if (event.pointerType !== "mouse" || event.button !== 0) return;
                const region = event.currentTarget;
                if (region.scrollHeight <= region.clientHeight) return;
                const bounds = region.getBoundingClientRect();
                if (event.clientX >= bounds.right - (region.offsetWidth - region.clientWidth)) {
                  setIndexScrollbarDragging(true);
                }
              }}
            >
            {conversationIndexPanel}
            {groupComposerOpen ? (
              <section className={styles.groupComposerPanel} aria-label={lang === "zh" ? "新建群聊" : "New group chat"}>
                <label className={styles.groupComposerField}>
                  <span>{lang === "zh" ? "群名" : "Name"}</span>
                  <VNativeInput
                    className={styles.groupComposerInput}
                    value={groupTitleDraft}
                    maxLength={80}
                    onChange={(event) => setGroupTitleDraft(event.target.value)}
                  />
                </label>
                <label className={styles.groupComposerField}>
                  <span>{lang === "zh" ? "调度模式" : "Mode"}</span>
                  <VStringSelect
                    className={styles.groupComposerInput}
                    ariaLabel={lang === "zh" ? "调度模式" : "Mode"}
                    value={groupModeDraft}
                    onValueChange={setGroupModeDraft}
                    isDisabled={chatRoomModesPending || createGroupRoomPending}
                    options={readyChatRoomModes.map((mode) => ({
                      value: mode.id,
                      label: chatRoomModeLabel(mode, lang),
                    }))}
                  />
                </label>
                <label className={styles.groupComposerField}>
                  <span>{lang === "zh" ? "对话目的" : "Purpose"}</span>
                  <VStringSelect
                    className={styles.groupComposerInput}
                    ariaLabel={lang === "zh" ? "对话目的" : "Purpose"}
                    value={groupPurposeDraft}
                    onValueChange={setGroupPurposeDraft}
                    isDisabled={chatRoomPurposesPending || createGroupRoomPending}
                    options={availableChatRoomPurposes.map((purpose) => ({
                      value: purpose.id,
                      label: chatRoomPurposeLabel(purpose, lang),
                    }))}
                  />
                </label>
                <div className={styles.groupAgentPicker} aria-label={lang === "zh" ? "选择参与助手" : "Choose agents"}>
                  {agentsPending ? (
                    <ProgressiveRegionSkeleton
                      variant="list"
                      label={lang === "zh" ? "正在读取助手" : "Loading agents"}
                    />
                  ) : groupCandidateAgents.length ? (
                    groupCandidateAgents.map((agent) => {
                      const selected = groupSelectedAgentIds.includes(agent.agentId);
                      const display = agentDisplayInfo(agent, lang, { resolveModelLabel });
                      return (
                        <label key={agent.agentId} className={selected ? `${styles.groupAgentOption} ${styles.groupAgentOptionSelected}` : styles.groupAgentOption}>
                          <VNativeInput
                            type="checkbox"
                            checked={selected}
                            disabled={createGroupRoomPending}
                            onChange={() => onToggleGroupAgent(agent.agentId)}
                          />
                          {renderAgentAvatar(
                            routeStyles.agentOptionAvatar,
                            agent.avatarImageUrl,
                            avatarInitials(agent.agentCode, display.name),
                          )}
                          <span>
                            <strong>{display.name}</strong>
                            <span className={styles.agentOptionMeta}>
                              <small className={`${routeStyles.agentRoleTag} ${styles[agentRoleClass(display.tone)]}`}>
                                {display.functionLabel}
                              </small>
                              {display.modelLabel ? (
                                <small className={styles.agentModelTag} title={display.modelLabel}>
                                  {display.modelLabel}
                                </small>
                              ) : null}
                            </span>
                          </span>
                        </label>
                      );
                    })
                  ) : (
                    <VStateSurface
                      tone="empty"
                      title={lang === "zh" ? "暂无可加入群聊的持久助手" : "No persistent agents are available"}
                    />
                  )}
                </div>
                <VButton
                  type="button"
                  className={styles.createGroupButton}
                  onClick={onCreateGroupRoom}
                  isDisabled={createGroupRoomPending || groupSelectedAgentIds.length < 2 || !groupTitleDraft.trim()}

                  icon={<UsersRound size={15} />}
                >
                  <span>{createGroupRoomPending ? (lang === "zh" ? "创建中" : "Creating") : (lang === "zh" ? "创建群聊" : "Create group")}</span>
                </VButton>
              </section>
            ) : null}
            </div>
            </div>
          )}
          </div>
          <ChatSessionIndexSearch
            open={searchOpen} onOpenChange={setSearchOpen} lang={lang} agentsById={agentsById} teams={teams}
            activeSessionId={activeSessionId} approvalSessionIds={sessionIdsNeedingApproval}
            runningSessionIds={runtimeRunningSessionIds} knownSessions={sessionsById}
            onOpenSession={(id) => id === activeSessionId ? onSetActiveTab(id, "agent") : onOpenDirectSession(id)}
            onOpenAgent={onOpenSearchAgent} onOpenTeam={onOpenSearchTeam}
          />
        </aside>
  );
}
