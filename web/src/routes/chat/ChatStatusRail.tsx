import { ChevronRight, Sparkles } from "lucide-react";
import { lazy, Suspense } from "react";

import type {
  ChatRoomDetail,
  PetSummary,
  SessionAgentPromptSnapshot,
  SessionLlmPayloadTrace,
  SessionPromptAssemblyManifest,
} from "../../api/types";
import { PersistedHeightListShell } from "../../components/layout/PersistedHeightListShell";
import { VContextualHint } from "../../components/vui";
import type { TranslationKey } from "../../i18n/dictionary";
import routeStyles from "../ChatCodingRoute.styles";
import { ProgressiveRegionSkeleton } from "../shared/ProgressiveRegionSkeleton";
import { isBusyPhase } from "./chatCodingRouteViewModel";
import { CHAT_COMPACT_DETAILS_HEIGHT_PANE, CHAT_LIST_HEIGHT_LAYOUT_ID } from "./chatListHeights";
import { ChatPromptAssemblyInspector } from "./ChatPromptAssemblyInspector";
import styles from "./ChatStatusRail.styles";

const LlmPayloadTracePanel = lazy(() =>
  import("./LlmPayloadTracePanel").then((module) => ({ default: module.LlmPayloadTracePanel })),
);

export type ChatStatusRailProps = {
  statusRailClassName: string;
  statusRailCollapsed: boolean;
  statusRailOverlayOpen: boolean;
  standardGroupRoomActive: boolean;
  groupRoomInitialLoading: boolean;
  lang: "zh" | "en";
  t: (key: TranslationKey) => string;
  numberFormatter: Intl.NumberFormat;
  activeGroupRoom: ChatRoomDetail | null | undefined;
  activeGroupTeamOwned: boolean;
  availableGroupParticipantCount: number;
  statusLabel: (status: string) => string;
  groupRoundRunning: boolean;
  activeSurfaceTitle: string;
  sessionStateValue: string;
  sessionStateLabel: string;
  sessionStateLine: string;
  compactSessionStateLine: string;
  agentDirectSessionMismatch: boolean;
  sessionBindingMismatchLine: string;
  sessionCompactRows: Array<{ label: string; value: string; title?: string }>;
  activeSkillSummary: boolean;
  activeSkillStatusStyle: string;
  activeSkillTitle: string;
  activeSkillName: string;
  activeSkillCommand: string;
  activeSkillStatusLabel: string;
  activeSkillShortHash: string;
  promptSnapshot?: SessionAgentPromptSnapshot;
  promptAssembly?: SessionPromptAssemblyManifest;
  lastLlmPayloadTrace: SessionLlmPayloadTrace | null | undefined;
  pet: PetSummary | null | undefined;
  petPresetLabel: string;
  petCompactLine: string;
  petAvatarSkinStyle: string;
  petAvatarSymbol: string;
  petVitals: Array<{ key: string; label: string; value: string | number }>;
  petInteractionLabels: { pending: string };
  petActionPending: boolean;
  petActionFeedback: string;
};

export function ChatStatusRail(props: ChatStatusRailProps) {
  const {
    statusRailClassName,
    statusRailCollapsed,
    statusRailOverlayOpen,
    standardGroupRoomActive,
    groupRoomInitialLoading,
    lang,
    t,
    numberFormatter,
    activeGroupRoom,
    activeGroupTeamOwned,
    availableGroupParticipantCount,
    statusLabel,
    groupRoundRunning,
    activeSurfaceTitle,
    sessionStateValue,
    sessionStateLabel,
    sessionStateLine,
    compactSessionStateLine,
    agentDirectSessionMismatch,
    sessionBindingMismatchLine,
    sessionCompactRows,
    activeSkillSummary,
    activeSkillStatusStyle,
    activeSkillTitle,
    activeSkillName,
    activeSkillCommand,
    activeSkillStatusLabel,
    activeSkillShortHash,
    promptSnapshot,
    promptAssembly,
    lastLlmPayloadTrace,
    pet,
    petPresetLabel,
    petCompactLine,
    petAvatarSkinStyle,
    petAvatarSymbol,
    petVitals,
    petInteractionLabels,
    petActionPending,
    petActionFeedback,
  } = props;

  const sessionBusy = isBusyPhase(sessionStateValue);

  return (
    <aside
      id="chat-status-pane"
      className={statusRailClassName}
      data-vui-region="chat-status-rail"
      data-vui-layout-id={CHAT_LIST_HEIGHT_LAYOUT_ID}
      aria-hidden={statusRailCollapsed}
      role={statusRailOverlayOpen ? "dialog" : undefined}
      aria-label={statusRailOverlayOpen ? (lang === "zh" ? "状态栏" : "Status panel") : undefined}
    >
      {standardGroupRoomActive && groupRoomInitialLoading ? (
        <section className={`${routeStyles.leftBlock} ${styles.groupProfileBlock}`}>
          <ProgressiveRegionSkeleton
            variant="detail"
            label={lang === "zh" ? "正在加载群聊资料" : "Loading group profile"}
          />
        </section>
      ) : standardGroupRoomActive ? (
        <section className={`${routeStyles.leftBlock} ${styles.groupProfileBlock}${groupRoundRunning ? ` ${styles.railBlockActive}` : ""}`}>
          <div className={routeStyles.sectionHeader}>
            <div className={routeStyles.sectionIdentity}>
              <div className={routeStyles.sectionEyebrowRow}>
                <p className={routeStyles.blockEyebrow}>{lang === "zh" ? "群资料" : "Group profile"}</p>
                <VContextualHint
                  content={activeGroupTeamOwned
                    ? (lang === "zh" ? "团队关联群聊的成员、角色和同步关系由团队页维护。" : "Team membership, roles, and sync are managed in Teams.")
                    : (lang === "zh" ? "这里仅展示当前群聊资料；管理操作已移至输入框下方的加号菜单。" : "This panel is read-only. Management actions are in the composer plus menu.")}
                  label={lang === "zh" ? "群资料说明" : "Group profile details"}
                  width="wide"
                />
              </div>
              <h3 className={routeStyles.sectionTitle}>{activeGroupRoom?.title ?? (lang === "zh" ? "群聊加载中" : "Loading group")}</h3>
            </div>
            <span className={`${styles.sessionStatePill} ${styles[`sessionStatePill_${String(activeGroupRoom?.status ?? "ready").trim().toLowerCase()}`]}`}>
              {statusLabel(activeGroupRoom?.status ?? "ready")}
            </span>
          </div>
          <div className={routeStyles.resourceSplit}>
            <div className={routeStyles.resourceMetric}>
              <span>{lang === "zh" ? "可用成员" : "Available"}</span>
              <strong>{numberFormatter.format(availableGroupParticipantCount)}</strong>
            </div>
            <div className={routeStyles.resourceMetric}>
              <span>{lang === "zh" ? "调度" : "Mode"}</span>
              <strong>{activeGroupRoom?.mode ?? "round_robin"}</strong>
            </div>
            <div className={routeStyles.resourceMetric}>
              <span>{lang === "zh" ? "目的" : "Purpose"}</span>
              <strong>{activeGroupRoom?.purpose ?? "discussion"}</strong>
            </div>
          </div>
        </section>
      ) : (
        <>
          <section className={`${routeStyles.leftBlock} ${styles.currentSessionBlock}${sessionBusy ? ` ${styles.railBlockActive}` : ""}`}>
            <div className={routeStyles.sectionHeader}>
              <div className={routeStyles.sectionIdentity}>
                <p className={routeStyles.blockEyebrow}>{t("currentSession")}</p>
                <h3 className={routeStyles.sectionTitle}>{activeSurfaceTitle}</h3>
              </div>
              <span className={`${styles.sessionStatePill} ${styles[`sessionStatePill_${sessionStateValue}`]}`}>{sessionStateLabel}</span>
            </div>
            <p className={`${routeStyles.contextLineCompact} ${styles.currentSessionLine}`} title={sessionStateLine}>
              {compactSessionStateLine}
            </p>
            {agentDirectSessionMismatch ? (
              <div className={styles.sessionBindingNotice} role="status"><span>{sessionBindingMismatchLine}</span></div>
            ) : null}
            {sessionCompactRows.length > 0 ? (
              <div className={`${styles.inlineMetaList} ${styles.currentSessionMetaList}`}>
                {sessionCompactRows.map((row) => (
                  <span key={row.label} className={styles.inlineMetaPill} title={row.title ?? row.value}>
                    <span>{row.label}</span><strong>{row.value}</strong>
                  </span>
                ))}
              </div>
            ) : null}
            {activeSkillSummary ? (
              <section className={`${styles.activeSkillStatus} ${activeSkillStatusStyle}`} title={activeSkillTitle} aria-label={lang === "zh" ? "当前 active skill 状态" : "Current active skill status"}>
                <div className={styles.activeSkillIdentity}>
                  <span className={styles.activeSkillEyebrow}>{lang === "zh" ? "当前 Skill" : "Active skill"}</span>
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

          {promptSnapshot ? (
            <section className={routeStyles.leftBlock} aria-label={lang === "zh" ? "Prompt 装配状态" : "Prompt assembly status"}>
              <ChatPromptAssemblyInspector lang={lang} snapshot={promptSnapshot} manifest={promptAssembly} />
            </section>
          ) : null}

          {lastLlmPayloadTrace ? (
            <Suspense fallback={null}><LlmPayloadTracePanel lang={lang} trace={lastLlmPayloadTrace} /></Suspense>
          ) : null}

          <section className={`${routeStyles.leftBlock} ${styles.companionBlock}`}>
            <div className={routeStyles.sectionHeader}>
              <h3 className={routeStyles.railSectionHeading}>{lang === "zh" ? "陪伴" : "Companion"}</h3>
            </div>
            <div className={styles.companionCompact}>
              <div className={styles.petMiniAvatar} aria-hidden="true">
                <div className={`${styles.petShowcaseAvatar} ${petAvatarSkinStyle}`}>
                  <span className={styles.petShowcaseEarLeft} /><span className={styles.petShowcaseEarRight} />
                  <span className={styles.petShowcaseFace}><span className={styles.petShowcaseEye} /><span className={styles.petShowcaseMuzzle} /><span className={styles.petShowcaseEye} /></span>
                  <span className={styles.petShowcaseSymbol}>{petAvatarSymbol}</span>
                  <span className={styles.petShowcaseFootLeft} /><span className={styles.petShowcaseFootRight} />
                </div>
              </div>
              <div className={styles.companionCopy}>
                <div className={styles.companionTopLine}>
                  <strong>{pet?.name ?? t("loadingPetState")}</strong>
                  <span>{t("level")} {pet?.level ?? 0} · {petPresetLabel}</span>
                </div>
                <p title={petCompactLine}>{petCompactLine || (lang === "zh" ? "暂无陪伴状态" : "No companion state yet")}</p>
              </div>
            </div>
            {pet ? (
              <details className={styles.compactDetails}>
                <summary>
                  <ChevronRight size={14} aria-hidden="true" />
                  <span className={styles.compactDetailsClosedLabel}>{lang === "zh" ? "明细" : "Details"}</span>
                  <span className={styles.compactDetailsOpenLabel}>{t("collapseSection")}</span>
                </summary>
                <PersistedHeightListShell layoutId={CHAT_LIST_HEIGHT_LAYOUT_ID} pane={CHAT_COMPACT_DETAILS_HEIGHT_PANE} label={lang === "zh" ? "调整陪伴明细高度" : "Resize companion details height"} className={styles.compactDetailsBody} resizeHandleClassName={styles.compactDetailsResizeHandle}>
                  <div className={styles.inlineMetaList}>
                    <span className={styles.inlineMetaPill}><span>{t("dailyTokens")}</span><strong>{numberFormatter.format(pet.dailyTokens ?? 0)}</strong></span>
                    {petVitals.map((vital) => <span key={vital.key} className={styles.inlineMetaPill}><span>{vital.label}</span><strong>{vital.value}</strong></span>)}
                  </div>
                  {petActionPending ? <span className={styles.petShowcaseActionHint}><Sparkles size={13} /><span>{petInteractionLabels.pending}</span></span> : null}
                  {petActionFeedback ? <p className={styles.petShowcaseFeedback}>{petActionFeedback}</p> : null}
                </PersistedHeightListShell>
              </details>
            ) : null}
          </section>
        </>
      )}
    </aside>
  );
}
