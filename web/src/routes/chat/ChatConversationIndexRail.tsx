import {
  BellRing,
  Bot,
  ChevronRight,
  MessageSquarePlus,
  MessageCircleHeart,
  Search,
  Plus,
  PanelLeftClose,
  X,
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
} from "../../api/types";
import {
  VButton,
  VCommandPalette,
  VContextualHint,
  VDropdownMenu,
  VIconButton,
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
  directoryFilterText: string;
  onDirectoryFilterChange: (value: string) => void;
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
  onOpenProjectAgentBus: () => void;
  onToggleGroupAgent: (agentId: string) => void;
  onToggleGroupComposer: () => void;
  projectBusActive: boolean;
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
  currentSessionLabel: string;
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
    directoryFilterText,
    onDirectoryFilterChange,
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
    onOpenProjectAgentBus,
    onToggleGroupAgent,
    onToggleGroupComposer,
    projectBusActive,
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
    currentSessionLabel,
  } = props;

  const [createMenuOpen, setCreateMenuOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [directorySearchOpen, setDirectorySearchOpen] = useState(false);
  const directorySearchRef = useRef<HTMLButtonElement>(null);
  const closeDirectorySearch = () => {
    onDirectoryFilterChange("");
    setDirectorySearchOpen(false);
    directorySearchRef.current?.focus();
  };
  const searchItems = useMemo(() => Array.from(sessionsById.values()).map((session) => ({
    id: session.id,
    group: session.teamName || session.agentDisplayName || (lang === "zh" ? "会话" : "Chats"),
    label: String(session.taskTitle || session.resultCard?.title || session.title || session.id).trim(),
    detail: String(session.taskSummary || session.resultCard?.summary || session.agentDisplayName || "").trim() || undefined,
    keywords: [
      session.agentCode,
      session.agentDisplayName,
      session.workspacePath,
      session.currentPhase,
      session.status,
    ].filter(Boolean).join(" "),
    onRun: () => onOpenDirectSession(session.id),
  })), [lang, onOpenDirectSession, sessionsById]);

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
    const onKeyDown = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey) {
        return;
      }
      const key = event.key.toLocaleLowerCase();
      if (key === "k") {
        event.preventDefault();
        setSearchOpen(true);
      } else if (key === "n") {
        event.preventDefault();
        setCreateMenuOpen(true);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
      <aside
        id="chat-conversation-index-pane"
        className={conversationIndexPaneClassName}
        data-vui-region="chat-session-index"
        aria-keyshortcuts="Control+K Meta+K"
        aria-hidden={conversationIndexCollapsed}
        role={conversationIndexOverlayOpen ? "dialog" : undefined}
        aria-label={conversationIndexOverlayOpen ? (lang === "zh" ? "会话列表" : "Conversation list") : undefined}
      >
          <div className={styles.railTop}>
            <h2 className={styles.railTitle}>{lang === "zh" ? "会话" : "Chats"}</h2>
            <VNativeButton
              ref={directorySearchRef}
              type="button"
              data-vui="icon-button"
              className={styles.railActionButton}
              aria-label={directorySearchOpen ? (lang === "zh" ? "关闭搜索" : "Close search") : (lang === "zh" ? "搜索 Agent 或团队" : "Search Agents or teams")}
              aria-expanded={directorySearchOpen}
              aria-controls={directorySearchOpen ? "chat-directory-search" : undefined}
              onClick={() => directorySearchOpen ? closeDirectorySearch() : setDirectorySearchOpen(true)}
              title={lang === "zh" ? "搜索 Agent 或团队；Ctrl+K 搜索全部任务" : "Search Agents or teams; Ctrl+K searches all tasks"}
            >
              {directorySearchOpen ? <X size={16} aria-hidden="true" /> : <Search size={16} aria-hidden="true" />}
            </VNativeButton>
            <VDropdownMenu
              aria-label={lang === "zh" ? "新建任务" : "Create task"}
              align="start"
              side="bottom"
              open={createMenuOpen}
              onOpenChange={setCreateMenuOpen}
              items={createItems}
              trigger={(
                <VNativeButton
                  ref={createAgentButtonRef}
                  id="chat-agent-create-trigger"
                  type="button"
                  data-vui="icon-button"
                  className={styles.railActionButton}
                  aria-label={lang === "zh" ? "新建任务" : "Create task"}
                  aria-keyshortcuts="Control+N Meta+N"
                  title={lang === "zh" ? "新建任务（Ctrl+N）" : "Create task (Ctrl+N)"}
                >
                  <Plus size={16} aria-hidden="true" />
                </VNativeButton>
              )}
            />
            <VIconButton
              tooltip=""
              id="chat-conversation-index-collapse"
              type="button"
              className={styles.railActionButton}
              label={lang === "zh" ? "收起会话列" : "Collapse conversation column"}
              aria-expanded={true}
              aria-controls="chat-conversation-index-pane"
              onClick={onCollapseConversationIndex}
              icon={<PanelLeftClose size={16} aria-hidden="true" />}
            />
            {directorySearchOpen ? (
              <div id="chat-directory-search" className={styles.directorySearch}>
                <VNativeInput
                  autoFocus
                  aria-label={lang === "zh" ? "搜索 Agent 或团队" : "Search Agents or teams"}
                  placeholder={lang === "zh" ? "搜索 Agent 或团队" : "Search Agents or teams"}
                  value={directoryFilterText}
                  onChange={(event) => onDirectoryFilterChange(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Escape") {
                      event.preventDefault();
                      closeDirectorySearch();
                    }
                  }}
                  className={styles.directorySearchInput}
                />
              </div>
            ) : null}
          </div>

        {standardGroupRoomActive ? (
          <div className="grid min-w-0 gap-1">
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
            <div className={styles.conversationIndexScrollRegion}>
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
            <section className={styles.systemEntryGroup} aria-label={lang === "zh" ? "系统入口" : "System entries"}>
              <VButton
                type="button"
                contentLayout="plain"
                variant="ghost"
                aria-current={projectBusActive ? "true" : undefined}
                className={
                  projectBusActive
                    ? `${styles.systemEntryButton} ${styles.systemEntryButtonActive}`
                    : styles.systemEntryButton
                }
                onClick={onOpenProjectAgentBus}
              >
                <span className={styles.systemEntryIcon} aria-hidden="true">
                  <BellRing size={16} />
                </span>
                <span className={styles.systemEntryCopy}>
                  <span className={styles.systemEntryTitleRow}>
                    <span className={styles.systemEntryTitle}>{lang === "zh" ? "助手通知流" : "Agent notice stream"}</span>
                    {projectBusActive ? <span className={styles.sessionCurrentBadge}>{currentSessionLabel}</span> : null}
                  </span>
                  <span className={styles.systemEntryMeta}>
                    {lang === "zh" ? "全局广播 · 私信投递记录" : "Global broadcast · private delivery log"}
                  </span>
                </span>
              </VButton>
            </section>
            </div>
          )}
          </div>
          <VCommandPalette
            open={searchOpen}
            onOpenChange={setSearchOpen}
            items={searchItems}
            labels={{
              searchPlaceholder: lang === "zh" ? "搜索任务、会话摘要或工作区" : "Search tasks, summaries, or workspaces",
              emptyTitle: lang === "zh" ? "没有找到匹配任务" : "No matching tasks",
              hint: lang === "zh" ? "↑↓ 选择 · Enter 打开 · Esc 关闭" : "↑↓ Select · Enter open · Esc close",
            }}
            maxVisible={7}
            data-vui="chat-left-rail-search"
          />
        </aside>
  );
}
