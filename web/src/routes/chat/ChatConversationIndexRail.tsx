import {
  BellRing,
  ChevronRight,
  MessageCircleHeart,
  Plus,
  Search,
  UsersRound,
} from "lucide-react";
import type { Dispatch, ReactNode, SetStateAction } from "react";

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
  VContextualHint,
  VInput,
  VNativeInput,
  VNativeSelect,
} from "../../components/vui";
import type { TranslationKey } from "../../i18n/dictionary";
import { agentDisplayInfo } from "../agentDisplay";
import {
  contextUsagePercent,
  formatContextUsage,
  formatRelativeTime,
} from "../chatShellFormat";
import styles from "../ChatCodingRoute.styles";

export type ConversationIndexPanelKey = "conversations" | "members";

export type ChatConversationIndexRailProps = {
  agentsById: Map<string, AgentInstance>;
  agentsPending: boolean;
  availableChatRoomPurposes: ChatRoomPurpose[];
  availableGroupParticipantCount: number;
  availableGroupParticipants: ChatRoomParticipant[];
  activeGroupRoom: ChatRoomDetail | null | undefined;
  chatRoomModesPending: boolean;
  chatRoomPurposesPending: boolean;
  conversationIndexCollapsed: boolean;
  conversationIndexOverlayOpen: boolean;
  conversationIndexPanel: ReactNode;
  conversationIndexPaneClassName: string;
  createGroupRoomPending: boolean;
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
  mentalModelEnabledForNextTurn: boolean;
  numberFormatter: Intl.NumberFormat;
  onCreateAgent: () => void;
  onCreateGroupRoom: () => void;
  onOpenDirectSession: (sessionId: string) => void;
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
  sessionFilter: string;
  sessionsById: Map<string, SessionSummary>;
  setExpandedGroupAgentSessionIds: Dispatch<SetStateAction<string[]>>;
  setGroupModeDraft: Dispatch<SetStateAction<string>>;
  setGroupPurposeDraft: Dispatch<SetStateAction<string>>;
  setGroupTitleDraft: Dispatch<SetStateAction<string>>;
  setRightIndexPanel: Dispatch<SetStateAction<ConversationIndexPanelKey>>;
  setSessionFilter: Dispatch<SetStateAction<string>>;
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
    chatRoomModesPending,
    chatRoomPurposesPending,
    conversationIndexCollapsed,
    conversationIndexOverlayOpen,
    conversationIndexPanel,
    conversationIndexPaneClassName,
    createGroupRoomPending,
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
    mentalModelEnabledForNextTurn,
    numberFormatter,
    onCreateAgent,
    onCreateGroupRoom,
    onOpenDirectSession,
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
    sessionFilter,
    sessionsById,
    setExpandedGroupAgentSessionIds,
    setGroupModeDraft,
    setGroupPurposeDraft,
    setGroupTitleDraft,
    setRightIndexPanel,
    setSessionFilter,
    standardGroupRoomActive,
    t,
    currentSessionLabel,
  } = props;

  return (
      <aside
        id="chat-conversation-index-pane"
        className={conversationIndexPaneClassName}
        aria-hidden={conversationIndexCollapsed}
        role={conversationIndexOverlayOpen ? "dialog" : undefined}
        aria-label={conversationIndexOverlayOpen ? (lang === "zh" ? "会话列表" : "Conversation list") : undefined}
      >
        {standardGroupRoomActive ? (
          <div
            className={styles.rightIndexTabs}
            role="tablist"
            aria-label={lang === "zh" ? "左侧索引" : "Left index"}
          >
            <VButton
              type="button"
              role="tab"
              aria-selected={rightIndexPanel === "conversations"}
              className={rightIndexPanel === "conversations" ? `${styles.rightIndexTab} ${styles.rightIndexTabActive}` : styles.rightIndexTab}
              onClick={() => setRightIndexPanel("conversations")}
            >
              <MessageCircleHeart size={14} />
              <span>{lang === "zh" ? "会话" : "Chats"}</span>
            </VButton>
            <VButton
              type="button"
              role="tab"
              aria-selected={rightIndexPanel === "members"}
              className={rightIndexPanel === "members" ? `${styles.rightIndexTab} ${styles.rightIndexTabActive}` : styles.rightIndexTab}
              onClick={() => setRightIndexPanel("members")}
            >
              <UsersRound size={14} />
              <span>{lang === "zh" ? "成员" : "Members"}</span>
            </VButton>
          </div>
        ) : null}

        {rightIndexPanel === "members" && standardGroupRoomActive ? (
          <div className={styles.memberIndexSummary}>
            <UsersRound size={15} />
            <span>
              {availableGroupParticipantCount} {lang === "zh" ? "位可用助手" : "available agents"}
            </span>
            <strong>{statusLabel(activeGroupRoom?.status ?? "ready")}</strong>
          </div>
        ) : (
          <div className={styles.panelSearch}>
            <Search size={15} aria-hidden="true" />
            <VInput
              className={styles.panelSearchInput}
              type="text"
              value={sessionFilter}
              onChange={(event) => setSessionFilter(event.target.value)}
              placeholder={t("searchSessionsPlaceholder")}
              aria-label={t("searchSessionsPlaceholder")}
            />
          </div>
        )}

        <div
          className={
            rightIndexPanel === "members" && standardGroupRoomActive
              ? styles.panelBody
              : `${styles.panelBody} ${styles.conversationIndexPanelBody}`
          }
        >
          {rightIndexPanel === "members" && standardGroupRoomActive ? (
            <section className={styles.agentIndexRoster} aria-label={lang === "zh" ? "群成员状态索引" : "Group member status index"}>
              <div className={styles.sectionHeader}>
                <div className={styles.sectionIdentity}>
                  <div className={styles.sectionEyebrowRow}>
                    <p className={styles.blockEyebrow}>{lang === "zh" ? "成员状态" : "Member status"}</p>
                    <VContextualHint
                      content={lang === "zh"
                        ? "只展示可用成员；已归档或断链的历史成员保留在日志里，不在这里打扰。"
                        : "Only available members are shown here; archived or broken historical members stay in diagnostics."}
                      label={lang === "zh" ? "成员状态筛选说明" : "Member status filter details"}
                      width="wide"
                    />
                  </div>
                  <h3 className={styles.sectionTitle}>{activeGroupRoom?.title ?? (lang === "zh" ? "群聊加载中" : "Loading group")}</h3>
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
                  const memberMental = mentalModelEnabledForNextTurn ? latestMentalSnapshot(memberDetail?.messages) : undefined;
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
                        >
                          <ChevronRight size={14} aria-hidden="true" />
                        </VButton>
                        <VButton
                          type="button"
                          contentLayout="plain"
                          className={styles.agentIndexOpenButton}
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
                              <em className={`${styles.agentRoleTag} ${styles[agentRoleClass(participantDisplay.tone)]}`}>
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
                            <p className={styles.contextLineCompact}>{t("loadingSession")}</p>
                          ) : expandedDetailQuery?.isError ? (
                            <p className={styles.panelNotice}>{describeError(expandedDetailQuery.error, t("loadFailed"))}</p>
                          ) : (
                            <>
                              <div className={styles.resourceSplit}>
                                <div className={styles.resourceMetric}>
                                  <span>{t("contextInUse")}</span>
                                  <strong>{formatContextUsage(memberContextUsed, memberContextLimit, locale)}</strong>
                                </div>
                                <div className={styles.resourceMetric}>
                                  <span>{lang === "zh" ? "上下文占比" : "Context ratio"}</span>
                                  <strong>{memberContextPercent}%</strong>
                                </div>
                              </div>
                              <p className={styles.oneLineValue}>
                                <span>{lang === "zh" ? "消息" : "Messages"}</span>
                                {memberContext
                                  ? `${numberFormatter.format(memberContext.messageCount)} ${lang === "zh" ? "条" : "messages"} · ${numberFormatter.format(memberContext.assistantMessageCount)} Agent`
                                  : (lang === "zh" ? "暂无上下文统计" : "No context stats yet")}
                              </p>
                              <div className={styles.agentIndexMentalBlock}>
                                <div className={styles.sectionHeader}>
                                  <div className={styles.sectionIdentity}>
                                    <p className={styles.blockEyebrow}>{t("mentalState")}</p>
                                    <p className={styles.sectionMetaLine}>
                                      {memberUpdated || (lang === "zh" ? "尚未更新" : "Not updated yet")}
                                    </p>
                                  </div>
                                  <span className={styles.mentalStateBadge}>{memberMentalState}</span>
                                </div>
                                <p className={styles.contextLineCompact}>{memberMentalSummary}</p>
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
          ) : (
            <div className={styles.conversationIndexLayout}>
            <div className={styles.sessionActionRow}>
              <VButton
                type="button"
                className={styles.newSessionButton}
                icon={<Plus size={15} />}
                onClick={onCreateAgent}
              >
                <span>{lang === "zh" ? "新建 Agent" : "New Agent"}</span>
              </VButton>
              <VButton
                type="button"
                className={styles.newGroupButton}
                icon={<UsersRound size={15} />}
                onClick={onToggleGroupComposer}
                aria-expanded={groupComposerOpen}
                isDisabled={createGroupRoomPending}
              >
                <span>{groupComposerOpen ? (lang === "zh" ? "收起" : "Close") : (lang === "zh" ? "新建群聊" : "New group")}</span>
              </VButton>
            </div>
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
                  <VNativeSelect
                    className={styles.groupComposerInput}
                    value={groupModeDraft}
                    onChange={(event) => setGroupModeDraft(event.target.value)}
                    disabled={chatRoomModesPending || createGroupRoomPending}
                  >
                    {readyChatRoomModes.map((mode) => (
                      <option key={mode.id} value={mode.id}>
                        {chatRoomModeLabel(mode, lang)}
                      </option>
                    ))}
                  </VNativeSelect>
                </label>
                <label className={styles.groupComposerField}>
                  <span>{lang === "zh" ? "对话目的" : "Purpose"}</span>
                  <VNativeSelect
                    className={styles.groupComposerInput}
                    value={groupPurposeDraft}
                    onChange={(event) => setGroupPurposeDraft(event.target.value)}
                    disabled={chatRoomPurposesPending || createGroupRoomPending}
                  >
                    {availableChatRoomPurposes.map((purpose) => (
                      <option key={purpose.id} value={purpose.id}>
                        {chatRoomPurposeLabel(purpose, lang)}
                      </option>
                    ))}
                  </VNativeSelect>
                </label>
                <div className={styles.groupAgentPicker} aria-label={lang === "zh" ? "选择参与助手" : "Choose agents"}>
                  {agentsPending ? (
                    <p className={styles.groupComposerEmpty}>{lang === "zh" ? "正在读取助手..." : "Loading agents..."}</p>
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
                            styles.agentOptionAvatar,
                            agent.avatarImageUrl,
                            avatarInitials(agent.agentCode, display.name),
                          )}
                          <span>
                            <strong>{display.name}</strong>
                            <span className={styles.agentOptionMeta}>
                              <small className={`${styles.agentRoleTag} ${styles[agentRoleClass(display.tone)]}`}>
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
                    <p className={styles.groupComposerEmpty}>{lang === "zh" ? "暂无可加入群聊的持久助手。" : "No persistent agents are available."}</p>
                  )}
                </div>
                <VButton
                  type="button"
                  className={styles.createGroupButton}
                  onClick={onCreateGroupRoom}
                  isDisabled={createGroupRoomPending || groupSelectedAgentIds.length < 2 || !groupTitleDraft.trim()}
                >
                  <UsersRound size={15} />
                  <span>{createGroupRoomPending ? (lang === "zh" ? "创建中" : "Creating") : (lang === "zh" ? "创建群聊" : "Create group")}</span>
                </VButton>
              </section>
            ) : null}
            </div>
            <section className={styles.systemEntryGroup} aria-label={lang === "zh" ? "系统入口" : "System entries"}>
              <div className={styles.conversationTreeRootHeader}>
                <span>{lang === "zh" ? "系统入口" : "System"}</span>
                <strong>1</strong>
              </div>
              <VButton
                type="button"
                contentLayout="plain"
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
        </aside>
  );
}
