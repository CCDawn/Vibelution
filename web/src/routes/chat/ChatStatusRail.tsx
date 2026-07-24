import {
  Apple,
  ArrowUpRight,
  Check,
  ChevronRight,
  HeartHandshake,
  MessageCircleHeart,
  RotateCcw,
  Sparkles,
  Trash2,
} from "lucide-react";
import { lazy, Suspense, type Dispatch, type ReactNode, type SetStateAction } from "react";

import type {
  AgentInstance,
  ChatRoomDetail,
  ChatRoomMode,
  ChatRoomPurpose,
  PetSummary,
  SessionLlmPayloadTrace,
  SessionSummary,
} from "../../api/types";
import {
  VButton,
  VContextualHint,
  VNativeInput,
  VNativeSelect,
  VTooltip,
  type VButtonProps,
} from "../../components/vui";
import type { TranslationKey } from "../../i18n/dictionary";
import { sessionAgentDisplayInfo } from "../agentDisplay";
import {
  CHAT_FEATURE_PRESETS,
  chatFeaturePresetShortLabel,
  type FeaturePresetKey,
} from "./chatFeaturePresets";
import { TokenCoreStatusPanel, type TokenCoreStatusMetric } from "./TokenCoreStatusPanel";
import styles from "../ChatCodingRoute.styles";

/** Secondary-lazy: status-rail debug panel, not required for first Chat paint. */
const LlmPayloadTracePanel = lazy(() =>
  import("./LlmPayloadTracePanel").then((module) => ({
    default: module.LlmPayloadTracePanel,
  })),
);

export type ChatStatusRailProps = {
  statusRailClassName: string;
  statusRailCollapsed: boolean;
  statusRailOverlayOpen: boolean;
  standardGroupRoomActive: boolean;
  lang: "zh" | "en";
  t: (key: TranslationKey) => string;
  numberFormatter: Intl.NumberFormat;
  // group profile
  activeGroupRoom: ChatRoomDetail | null | undefined;
  activeGroupTeamOwned: boolean;
  activeGroupTeam: { teamId: string } | null | undefined;
  availableGroupParticipantCount: number;
  statusLabel: (status: string) => string;
  groupManageChanged: boolean;
  groupManageDisabled: boolean;
  groupDeleteDisabled: boolean;
  groupResetDisabled: boolean;
  groupRoundActive: boolean;
  groupRoundRunning: boolean;
  groupRoomActionError: string;
  setGroupRoomActionError: Dispatch<SetStateAction<string>>;
  groupManageTitleDraft: string;
  setGroupManageTitleDraft: Dispatch<SetStateAction<string>>;
  groupManageModeDraft: string;
  setGroupManageModeDraft: Dispatch<SetStateAction<string>>;
  groupManagePurposeDraft: string;
  setGroupManagePurposeDraft: Dispatch<SetStateAction<string>>;
  readyChatRoomModes: ChatRoomMode[];
  availableChatRoomPurposes: ChatRoomPurpose[];
  chatRoomModeLabel: (mode: ChatRoomMode, lang: "zh" | "en") => string;
  chatRoomPurposeLabel: (purpose: ChatRoomPurpose, lang: "zh" | "en") => string;
  groupManageSessionIds: string[];
  groupManageSessionSet: Set<string>;
  sessions: SessionSummary[] | undefined;
  agentsById: Map<string, AgentInstance>;
  resolveModelLabel: (modelId: string) => string | undefined;
  renderAgentAvatar: (className: string, imageUrl: string | undefined, fallback: string) => ReactNode;
  avatarInitials: (agentCode?: string, name?: string, fallback?: string) => string;
  agentRoleClass: (tone: string) => string;
  avatarImageUrlFrom: (...sources: unknown[]) => string | undefined;
  updateGroupRoomPending: boolean;
  deleteGroupRoomPending: boolean;
  resetGroupRoomPending: boolean;
  onOpenTeam: (teamId: string) => void;
  onApplyGroupRoomManagement: () => void;
  onDeleteActiveGroupRoom: () => void;
  onResetActiveGroupRoom: () => void;
  onToggleGroupManageSession: (sessionId: string) => void;
  // direct session status
  activeSurfaceTitle: string;
  sessionStateValue: string;
  sessionStateLabel: string;
  sessionStateLine: string;
  compactSessionStateLine: string;
  agentDirectSessionMismatch: boolean;
  agentPrimaryDirectSessionId: string | null | undefined;
  sessionBindingMismatchLine: string;
  onOpenDirectSession: (sessionId: string) => void;
  sessionCompactRows: Array<{ label: string; value: string; title?: string }>;
  activeSkillSummary: boolean;
  activeSkillStatusStyle: string;
  activeSkillTitle: string;
  activeSkillName: string;
  activeSkillCommand: string;
  activeSkillStatusLabel: string;
  activeSkillShortHash: string;
  mentalModelEnabledForNextTurn: boolean;
  activeSessionId: string | null | undefined;
  onMentalModelEnabledChange: (enabled: boolean) => void;
  featurePresetState: Record<FeaturePresetKey, boolean>;
  onToggleFeaturePreset: (key: FeaturePresetKey) => void;
  cacheDetailAvailable: boolean;
  cacheDetailOpen: boolean;
  cacheDetailOpenLabel: string;
  tokenStatusMetrics: TokenCoreStatusMetric[];
  onOpenCacheDetail: () => void;
  lastLlmPayloadTrace: SessionLlmPayloadTrace | null | undefined;
  mentalCompactLine: string;
  mentalSourceLabel: string;
  mentalCognitiveStateValue: string;
  mentalStateLabel: string;
  mentalSummary: string;
  mentalWhisper: string;
  mentalCognitiveStateLabel: string;
  mentalConfidence: string;
  mentalRelativeTime: string;
  formatTime: (value: string) => string;
  mental: { updatedAt?: string | null } | null | undefined;
  pet: PetSummary | null | undefined;
  petPresetLabel: string;
  petCompactLine: string;
  petAvatarSkinStyle: string;
  petAvatarSymbol: string;
  petVitals: Array<{ key: string; label: string; value: string | number }>;
  petInteractionLabels: {
    group: string;
    feed: string;
    feedTitle: string;
    talk: string;
    talkTitle: string;
    care: string;
    careTitle: string;
    pending: string;
  };
  petActionPending: boolean;
  petActionFeedback: string;
  onPetInteraction: (action: "feed" | "talk" | "care") => void;
};

export function ChatStatusRail(props: ChatStatusRailProps) {
  const {
    statusRailClassName,
    statusRailCollapsed,
    statusRailOverlayOpen,
    standardGroupRoomActive,
    lang,
    t,
    numberFormatter,
    activeGroupRoom,
    activeGroupTeamOwned,
    activeGroupTeam,
    availableGroupParticipantCount,
    statusLabel,
    groupManageChanged,
    groupManageDisabled,
    groupDeleteDisabled,
    groupResetDisabled,
    groupRoundActive,
    groupRoundRunning,
    groupRoomActionError,
    setGroupRoomActionError,
    groupManageTitleDraft,
    setGroupManageTitleDraft,
    groupManageModeDraft,
    setGroupManageModeDraft,
    groupManagePurposeDraft,
    setGroupManagePurposeDraft,
    readyChatRoomModes,
    availableChatRoomPurposes,
    chatRoomModeLabel,
    chatRoomPurposeLabel,
    groupManageSessionIds,
    groupManageSessionSet,
    sessions,
    agentsById,
    resolveModelLabel,
    renderAgentAvatar,
    avatarInitials,
    agentRoleClass,
    avatarImageUrlFrom,
    updateGroupRoomPending,
    deleteGroupRoomPending,
    resetGroupRoomPending,
    onOpenTeam,
    onApplyGroupRoomManagement,
    onDeleteActiveGroupRoom,
    onResetActiveGroupRoom,
    onToggleGroupManageSession,
    activeSurfaceTitle,
    sessionStateValue,
    sessionStateLabel,
    sessionStateLine,
    compactSessionStateLine,
    agentDirectSessionMismatch,
    agentPrimaryDirectSessionId,
    sessionBindingMismatchLine,
    onOpenDirectSession,
    sessionCompactRows,
    activeSkillSummary,
    activeSkillStatusStyle,
    activeSkillTitle,
    activeSkillName,
    activeSkillCommand,
    activeSkillStatusLabel,
    activeSkillShortHash,
    mentalModelEnabledForNextTurn,
    activeSessionId,
    onMentalModelEnabledChange,
    featurePresetState,
    onToggleFeaturePreset,
    cacheDetailAvailable,
    cacheDetailOpen,
    cacheDetailOpenLabel,
    tokenStatusMetrics,
    onOpenCacheDetail,
    lastLlmPayloadTrace,
    mentalCompactLine,
    mentalSourceLabel,
    mentalCognitiveStateValue,
    mentalStateLabel,
    mentalSummary,
    mentalWhisper,
    mentalCognitiveStateLabel,
    mentalConfidence,
    mentalRelativeTime,
    formatTime,
    mental,
    pet,
    petPresetLabel,
    petCompactLine,
    petAvatarSkinStyle,
    petAvatarSymbol,
    petVitals,
    petInteractionLabels,
    petActionPending,
    petActionFeedback,
    onPetInteraction,
  } = props;

  return (
      <aside
        id="chat-status-pane"
        className={statusRailClassName}
        aria-hidden={statusRailCollapsed}
        role={statusRailOverlayOpen ? "dialog" : undefined}
        aria-label={statusRailOverlayOpen ? (lang === "zh" ? "状态栏" : "Status panel") : undefined}
      >
        {standardGroupRoomActive ? (
          <section className={`${styles.leftBlock} ${styles.groupProfileBlock}`}>
            <div className={styles.sectionHeader}>
              <div className={styles.sectionIdentity}>
                <div className={styles.sectionEyebrowRow}>
                  <p className={styles.blockEyebrow}>{lang === "zh" ? "群资料与设置" : "Group profile"}</p>
                  <VContextualHint
                    content={activeGroupTeamOwned
                      ? (lang === "zh"
                        ? "这是团队关联群聊；成员、角色和同步关系由团队页维护，这里只负责讨论运行与成员状态观察。"
                        : "This room is owned by a Team. Membership, roles, and sync stay in Teams; Chat only runs discussion and shows member status.")
                      : (lang === "zh"
                        ? "这里管理当前普通群聊的资料、成员和调度；成员状态索引放在左侧会话列。"
                        : "Manage this standalone group's info, members, and scheduling here. Member status lives in the left conversation column.")}
                    label={lang === "zh" ? "群资料与设置说明" : "Group profile details"}
                    width="wide"
                  />
                </div>
                <h3 className={styles.sectionTitle}>{activeGroupRoom?.title ?? (lang === "zh" ? "群聊加载中" : "Loading group")}</h3>
              </div>
              <span className={`${styles.sessionStatePill} ${styles[`sessionStatePill_${String(activeGroupRoom?.status ?? "ready").trim().toLowerCase()}`]}`}>
                {statusLabel(activeGroupRoom?.status ?? "ready")}
              </span>
            </div>
            <div className={styles.resourceSplit}>
              <div className={styles.resourceMetric}>
                <span>{lang === "zh" ? "可用成员" : "Available"}</span>
                <strong>{numberFormatter.format(availableGroupParticipantCount)}</strong>
              </div>
              <div className={styles.resourceMetric}>
                <span>{lang === "zh" ? "调度" : "Mode"}</span>
                <strong>{activeGroupRoom?.mode ?? "round_robin"}</strong>
              </div>
              <div className={styles.resourceMetric}>
                <span>{lang === "zh" ? "目的" : "Purpose"}</span>
                <strong>{activeGroupRoom?.purpose ?? "discussion"}</strong>
              </div>
            </div>
            <section className={styles.groupManagementPanel} aria-label={lang === "zh" ? "群聊管理" : "Group management"}>
              <div className={styles.groupManagementHeader}>
                <div>
                  <span className={styles.groupManagementTitleRow}>
                    <strong>{activeGroupTeamOwned ? (lang === "zh" ? "团队群聊引用" : "Team room reference") : (lang === "zh" ? "群设置" : "Group settings")}</strong>
                    {activeGroupTeamOwned ? (
                      <VContextualHint
                        content={lang === "zh"
                          ? "团队关联群聊的成员来自团队组织画布；如需调整成员、角色或同步关系，请打开团队页。"
                          : "Team-owned room members come from the Team canvas. Open Teams to change members, roles, or sync."}
                        label={lang === "zh" ? "团队群聊引用说明" : "Team room reference details"}
                        width="wide"
                      />
                    ) : null}
                  </span>
                  <span title={activeGroupRoom?.title ?? ""}>
                    {activeGroupRoom?.title ?? (lang === "zh" ? "群聊加载中" : "Loading group")}
                  </span>
                </div>
                <div className={styles.groupManagementActions}>
                  {activeGroupTeamOwned && activeGroupTeam ? (
                    <VButton
                      type="button"
                      className={styles.groupSecondaryButton}
                      onClick={() => onOpenTeam(activeGroupTeam.teamId)}
                    >
                      <ArrowUpRight size={14} />
                      <span>{lang === "zh" ? "打开团队" : "Open team"}</span>
                    </VButton>
                  ) : null}
                  <VButton
                    type="button"
                    className={groupManageChanged ? styles.groupApplyButton : styles.groupSecondaryButton}
                    isDisabled={groupManageDisabled || !groupManageChanged}
                    onClick={onApplyGroupRoomManagement}
                  >
                    <Check size={14} />
                    <span>
                      {updateGroupRoomPending
                        ? (lang === "zh" ? "应用中" : "Applying")
                        : (lang === "zh" ? "应用变更" : "Apply")}
                    </span>
                  </VButton>
                  <VButton
                    type="button"
                    className={styles.groupDeleteButton}
                    isDisabled={groupDeleteDisabled}
                    onClick={onDeleteActiveGroupRoom}
                  >
                    <Trash2 size={14} />
                    <span>
                      {deleteGroupRoomPending
                        ? (lang === "zh" ? "删除中" : "Deleting")
                        : (lang === "zh" ? "删除" : "Delete")}
                    </span>
                  </VButton>
                  <VButton
                    type="button"
                    className={styles.groupSecondaryButton}
                    isDisabled={groupResetDisabled}
                    onClick={onResetActiveGroupRoom}
                  >
                    <RotateCcw size={14} />
                    <span>
                      {resetGroupRoomPending
                        ? (lang === "zh" ? "重置中" : "Resetting")
                        : (lang === "zh" ? "重置消息" : "Reset messages")}
                    </span>
                  </VButton>
                </div>
              </div>
              {groupRoomActionError ? (
                <div className={styles.panelNotice}>{groupRoomActionError}</div>
              ) : null}
              <div className={styles.groupManagementControls}>
                <label className={styles.groupTitleField}>
                  <span>{lang === "zh" ? "群名" : "Name"}</span>
                  <VNativeInput
                    value={groupManageTitleDraft}
                    maxLength={80}
                    disabled={activeGroupTeamOwned || groupRoundActive || updateGroupRoomPending}
                    onChange={(event) => {
                      setGroupRoomActionError("");
                      setGroupManageTitleDraft(event.target.value);
                    }}
                  />
                </label>
                <label className={styles.groupModeSelect}>
                  <span>{lang === "zh" ? "调度模式" : "Mode"}</span>
                  <VNativeSelect
                    value={groupManageModeDraft}
                    disabled={activeGroupTeamOwned || groupRoundActive || updateGroupRoomPending}
                    onChange={(event) => {
                      setGroupRoomActionError("");
                      setGroupManageModeDraft(event.target.value);
                    }}
                  >
                    {readyChatRoomModes.map((mode) => (
                      <option key={mode.id} value={mode.id}>
                        {chatRoomModeLabel(mode, lang)}
                      </option>
                    ))}
                  </VNativeSelect>
                </label>
                <label className={styles.groupModeSelect}>
                  <span>{lang === "zh" ? "对话目的" : "Purpose"}</span>
                  <VNativeSelect
                    value={groupManagePurposeDraft}
                    disabled={activeGroupTeamOwned || groupRoundRunning || updateGroupRoomPending}
                    onChange={(event) => {
                      setGroupRoomActionError("");
                      setGroupManagePurposeDraft(event.target.value);
                    }}
                  >
                    {availableChatRoomPurposes.map((purpose) => (
                      <option key={purpose.id} value={purpose.id}>
                        {chatRoomPurposeLabel(purpose, lang)}
                      </option>
                    ))}
                  </VNativeSelect>
                </label>
                <div className={styles.groupManagementCount}>
                  <span>{lang === "zh" ? "已选" : "Selected"}</span>
                  <strong>
                    {groupManageSessionIds.length}/{sessions?.length ?? 0}
                  </strong>
                </div>
                <div className={styles.groupMemberPicker}>
                  {(sessions ?? []).map((session) => {
                    const selected = groupManageSessionSet.has(session.id);
                    const sessionAgent = session.agentId ? agentsById.get(session.agentId) : undefined;
                    const display = sessionAgentDisplayInfo(session, sessionAgent, lang, resolveModelLabel);
                    const sessionAvatarImageUrl = avatarImageUrlFrom(sessionAgent, session);
                    const missingMessage = session.agentMissing
                      ? session.agentStatusMessage || (lang === "zh" ? "缺少有效 Agent" : "Missing valid Agent")
                      : "";
                    return (
                      <label
                        key={session.id}
                        className={
                          selected
                            ? `${styles.groupMemberChip} ${styles.groupMemberChipSelected}`
                            : styles.groupMemberChip
                        }
                      >
                        <VNativeInput
                          type="checkbox"
                          checked={selected}
                          disabled={activeGroupTeamOwned || groupRoundActive || updateGroupRoomPending}
                          onChange={() => onToggleGroupManageSession(session.id)}
                        />
                        {renderAgentAvatar(
                          styles.agentOptionAvatar,
                          sessionAvatarImageUrl,
                          avatarInitials(session.agentCode, display.name),
                        )}
                        <span className={styles.groupMemberCopy}>
                          <strong>{display.name}</strong>
                          <small className={`${styles.agentRoleTag} ${styles[agentRoleClass(display.tone)]}`}>
                            {display.functionLabel}
                          </small>
                        </span>
                        {missingMessage ? (
                          <span className={styles.agentMissingInline} title={missingMessage}>
                            {lang === "zh" ? "缺少有效 Agent" : "Missing Agent"}
                          </span>
                        ) : null}
                      </label>
                    );
                  })}
                </div>
              </div>
              {groupRoundActive ? (
                <p className={styles.groupManagementHint}>
                  {lang === "zh" ? "群聊运行中，成员和模式会在本轮结束后允许修改。" : "The group is running. Members and mode can be changed after this round finishes."}
                </p>
              ) : groupManageSessionIds.length < 2 ? (
                <p className={styles.groupManagementHint}>
                  {lang === "zh" ? "群聊至少需要保留 2 位 Agent。" : "A group needs at least 2 agents."}
                </p>
              ) : null}
            </section>
          </section>
        ) : (
          <>
        <section className={`${styles.leftBlock} ${styles.currentSessionBlock}`}>
          <div className={styles.sectionHeader}>
            <div className={styles.sectionIdentity}>
              <p className={styles.blockEyebrow}>{t("currentSession")}</p>
              <h3 className={styles.sectionTitle}>{activeSurfaceTitle}</h3>
            </div>
            <span className={`${styles.sessionStatePill} ${styles[`sessionStatePill_${sessionStateValue}`]}`}>
              {sessionStateLabel}
            </span>
          </div>
          <p className={`${styles.contextLineCompact} ${styles.currentSessionLine}`} title={sessionStateLine}>
            {compactSessionStateLine}
          </p>
          {agentDirectSessionMismatch && agentPrimaryDirectSessionId ? (
            <div className={styles.sessionBindingNotice} role="status">
              <span>{sessionBindingMismatchLine}</span>
              <VButton
                type="button"
                onClick={() => onOpenDirectSession(agentPrimaryDirectSessionId)}
                title={`${t("openCurrentDirectSession")} · ${agentPrimaryDirectSessionId}`}
              >
                <ArrowUpRight size={13} />
                <span>{t("openCurrentDirectSession")}</span>
              </VButton>
            </div>
          ) : null}
          {sessionCompactRows.length > 0 ? (
            <div className={`${styles.inlineMetaList} ${styles.currentSessionMetaList}`}>
              {sessionCompactRows.map((row) => (
                <span key={row.label} className={styles.inlineMetaPill} title={row.title ?? row.value}>
                  <span>{row.label}</span>
                  <strong>{row.value}</strong>
                </span>
              ))}
            </div>
          ) : null}
          {activeSkillSummary ? (
            <section
              className={`${styles.activeSkillStatus} ${activeSkillStatusStyle}`}
              title={activeSkillTitle}
              aria-label={lang === "zh" ? "当前 active skill 状态" : "Current active skill status"}
            >
              <div className={styles.activeSkillIdentity}>
                <span className={styles.activeSkillEyebrow}>
                  {lang === "zh" ? "当前 Skill" : "Active skill"}
                </span>
                <strong>{activeSkillName || activeSkillCommand}</strong>
              </div>
              <div className={styles.activeSkillMeta}>
                {activeSkillCommand ? <span>/{activeSkillCommand}</span> : null}
                <span className={styles.activeSkillState}>{activeSkillStatusLabel}</span>
                {activeSkillShortHash ? <span>#{activeSkillShortHash}</span> : null}
              </div>
            </section>
          ) : null}
        </section>

        <section className={`${styles.leftBlock} ${styles.featurePresetBlock} ${styles.runModeBlock}`}>
          <div className={styles.sectionHeader}>
            <h3 className={styles.railSectionHeading}>{lang === "zh" ? "运行模式" : "Run modes"}</h3>
            <span className={styles.featurePresetScope} title={t("chatFeaturePanelHint")}>{lang === "zh" ? "下轮生效" : "Next turn"}</span>
          </div>
          <div className={styles.featureChipRow}>
            <VButton
              type="button"
              contentLayout="plain"
              className={
                mentalModelEnabledForNextTurn
                  ? `${styles.featureChip} ${styles.featureChipPrimary} ${styles.featureChipPrimaryActive}`
                  : `${styles.featureChip} ${styles.featureChipPrimary}`
              }
              aria-pressed={mentalModelEnabledForNextTurn}
              isDisabled={!activeSessionId}
              onClick={() => onMentalModelEnabledChange(!mentalModelEnabledForNextTurn)}
              title={t("chatFeatureMentalModelHint")}
            >
              <strong>{lang === "zh" ? "心智" : t("chatFeatureMentalModel")}</strong>
              <em>{mentalModelEnabledForNextTurn ? (lang === "zh" ? "开" : "On") : (lang === "zh" ? "关" : "Off")}</em>
            </VButton>
            {CHAT_FEATURE_PRESETS.map((item) => {
              const enabled = featurePresetState[item.key];
              const featureLabel = t(item.labelKey);
              return (
                <VButton
                  key={item.key}
                  type="button"
                  contentLayout="plain"
                  className={enabled ? `${styles.featureChip} ${styles.featureChipActive}` : styles.featureChip}
                  aria-pressed={enabled}
                  onClick={() => onToggleFeaturePreset(item.key)}
                  title={t(item.hintKey)}
                >
                  <strong>{chatFeaturePresetShortLabel(item.key, lang, featureLabel)}</strong>
                  <em>{enabled ? (lang === "zh" ? "开" : "On") : (lang === "zh" ? "关" : "Off")}</em>
                </VButton>
              );
            })}
          </div>
        </section>

        <TokenCoreStatusPanel
          cacheDetailAvailable={cacheDetailAvailable}
          cacheDetailOpen={cacheDetailOpen}
          cacheDetailOpenLabel={cacheDetailOpenLabel}
          lang={lang}
          metrics={tokenStatusMetrics}
          onOpenCacheDetail={onOpenCacheDetail}
        />

        {lastLlmPayloadTrace ? (
          <Suspense fallback={null}>
            <LlmPayloadTracePanel lang={lang} trace={lastLlmPayloadTrace} />
          </Suspense>
        ) : null}

        <section className={`${styles.leftBlock} ${styles.companionBlock}`}>
          <div className={styles.sectionHeader}>
            <h3 className={styles.railSectionHeading}>{lang === "zh" ? "陪伴" : "Companion"}</h3>
            {mentalModelEnabledForNextTurn ? (
              <VTooltip
                content={mentalCompactLine || mentalSourceLabel}
                renderTrigger={(tooltipTriggerProps) => {
                  const {
                    children: _triggerChildren,
                    className: triggerClassName,
                    role: _triggerRole,
                    tabIndex: _triggerTabIndex,
                    ...triggerProps
                  } = tooltipTriggerProps;

                  return (
                    <VButton
                      {...(triggerProps as unknown as VButtonProps)}
                      type="button"
                      className={[
                        triggerClassName,
                        styles.mentalStateBadge,
                        styles[`mentalStateBadge_${mentalCognitiveStateValue}`],
                      ].filter(Boolean).join(" ")}
                      aria-label={`${mentalStateLabel}. ${mentalCompactLine || mentalSourceLabel}`}
                    >
                      {mentalStateLabel}
                    </VButton>
                  );
                }}
              >
                {mentalStateLabel}
              </VTooltip>
            ) : (
              <span className={styles.mentalStateBadge} title={mentalSummary}>
                {lang === "zh" ? "心智关" : "Mental off"}
              </span>
            )}
          </div>
          <div className={styles.companionCompact}>
            <div className={styles.petMiniAvatar} aria-hidden="true">
              <div className={`${styles.petShowcaseAvatar} ${petAvatarSkinStyle}`}>
                <span className={styles.petShowcaseEarLeft} />
                <span className={styles.petShowcaseEarRight} />
                <span className={styles.petShowcaseFace}>
                  <span className={styles.petShowcaseEye} />
                  <span className={styles.petShowcaseMuzzle} />
                  <span className={styles.petShowcaseEye} />
                </span>
                <span className={styles.petShowcaseSymbol}>{petAvatarSymbol}</span>
                <span className={styles.petShowcaseFootLeft} />
                <span className={styles.petShowcaseFootRight} />
              </div>
            </div>
            <div className={styles.companionCopy}>
              <div className={styles.companionTopLine}>
                <strong>{pet?.name ?? t("loadingPetState")}</strong>
                <span>{t("level")} {pet?.level ?? 0} · {petPresetLabel}</span>
              </div>
              <p title={petCompactLine || mentalSummary}>{petCompactLine || mentalSummary}</p>
            </div>
          </div>
          <details className={styles.compactDetails}>
            <summary>
              <ChevronRight size={14} aria-hidden="true" />
              <span className={styles.compactDetailsClosedLabel}>{lang === "zh" ? "明细" : "Details"}</span>
              <span className={styles.compactDetailsOpenLabel}>{t("collapseSection")}</span>
            </summary>
            {mentalModelEnabledForNextTurn ? (
              <>
                <p className={styles.oneLineValue} title={mentalWhisper}>
                  <span>{t("mentalWhisper")}</span>
                  {mentalWhisper}
                </p>
                <div className={styles.inlineStatGrid}>
                  <div className={styles.inlineStat}>
                    <span>{t("state")}</span>
                    <strong>{mentalCognitiveStateLabel}</strong>
                  </div>
                  <div className={styles.inlineStat}>
                    <span>{t("mentalConfidence")}</span>
                    <strong>{mentalConfidence}</strong>
                  </div>
                  <div className={styles.inlineStat}>
                    <span>{t("mentalSource")}</span>
                    <strong>{mentalSourceLabel}</strong>
                  </div>
                  <div className={styles.inlineStat}>
                    <span>{t("mentalLastUpdated")}</span>
                    <strong title={formatTime(mental?.updatedAt ?? "")}>{mentalRelativeTime}</strong>
                  </div>
                </div>
              </>
            ) : (
              <p className={styles.contextLineCompact}>{mentalSummary}</p>
            )}
            <div className={styles.inlineMetaList}>
              <span className={styles.inlineMetaPill}>
                <span>{t("dailyTokens")}</span>
                <strong>{numberFormatter.format(pet?.dailyTokens ?? 0)}</strong>
              </span>
              {petVitals.map((vital) => (
                <span key={vital.key} className={styles.inlineMetaPill}>
                  <span>{vital.label}</span>
                  <strong>{vital.value}</strong>
                </span>
              ))}
            </div>
            <div className={styles.petShowcaseActions} aria-label={petInteractionLabels.group}>
              <VButton
                type="button"
                contentLayout="plain"
                className={styles.petShowcaseAction}
                onClick={() => onPetInteraction("feed")}
                isDisabled={petActionPending}
                title={petInteractionLabels.feedTitle}
              >
                <Apple size={14} />
                <span>{petInteractionLabels.feed}</span>
              </VButton>
              <VButton
                type="button"
                contentLayout="plain"
                className={styles.petShowcaseAction}
                onClick={() => onPetInteraction("talk")}
                isDisabled={petActionPending}
                title={petInteractionLabels.talkTitle}
              >
                <MessageCircleHeart size={14} />
                <span>{petInteractionLabels.talk}</span>
              </VButton>
              <VButton
                type="button"
                contentLayout="plain"
                className={styles.petShowcaseAction}
                onClick={() => onPetInteraction("care")}
                isDisabled={petActionPending}
                title={petInteractionLabels.careTitle}
              >
                <HeartHandshake size={14} />
                <span>{petInteractionLabels.care}</span>
              </VButton>
            </div>
            {petActionPending ? (
              <span className={styles.petShowcaseActionHint}>
                <Sparkles size={13} />
                <span>{petInteractionLabels.pending}</span>
              </span>
            ) : null}
            {petActionFeedback ? <p className={styles.petShowcaseFeedback}>{petActionFeedback}</p> : null}
          </details>
        </section>
          </>
        )}
      </aside>
  );
}
