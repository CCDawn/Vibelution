import { ArrowLeft, Heart, MapPin, Settings, Sparkles } from "lucide-react";

import type { VirtualHumanCompanion } from "../../api/types";
import { VRouteLinkButton, VStateSurface, VStatusChip } from "../../components/vui";
import { agentCenterConfigRoute } from "../agentCenterRoutes";
import { CompanionPortrait } from "./CompanionPortrait";
import {
  formatCompanionLocalTime,
  companionReturnTarget,
  currentLifeActivityLabel,
  lifeMoodLabel,
  lifeMoodSymbol,
} from "./companionPresentation";
import styles from "./CompanionChatRails.styles";

export type CompanionRailState = "loading" | "error" | "missing" | "ready";

export function CompanionPersonRail({
  className,
  collapsed,
  overlayOpen,
  companion,
  state,
  errorMessage,
  lang,
}: {
  className: string;
  collapsed: boolean;
  overlayOpen: boolean;
  companion: VirtualHumanCompanion | null;
  state: CompanionRailState;
  errorMessage?: string;
  lang: "zh" | "en";
}) {
  const unavailableTitle = state === "loading"
    ? (lang === "zh" ? "正在载入人物" : "Loading person")
    : state === "error"
      ? (lang === "zh" ? "人物状态载入失败" : "Failed to load person")
      : (lang === "zh" ? "这个人物当前不可进入" : "This person is unavailable");
  const activityLabel = companion ? currentLifeActivityLabel(companion.snapshot, lang) : "";
  const locationLabel = companion?.snapshot.state?.currentLocation || (lang === "zh" ? "未记录" : "Not recorded");
  const relationshipLabel = companion?.snapshot.state?.relationshipSummary || (lang === "zh" ? "慢慢熟悉" : "Getting closer");
  const localTime = companion ? formatCompanionLocalTime(companion.snapshot, lang) : "--:--";
  return (
    <aside
      className={`${className} ${styles.personRail}`}
      aria-hidden={collapsed}
      role={overlayOpen ? "dialog" : undefined}
      aria-label={companion ? `${companion.displayName} 人物栏` : unavailableTitle}
      data-companion-person-rail="true"
    >
      <div className={styles.railActions}>
        <VRouteLinkButton
          to="/companions"
          variant="ghost"
          className={styles.railIconButton}
          aria-label={lang === "zh" ? "返回人物大厅" : "Back to companion lobby"}
          icon={<ArrowLeft size={16} aria-hidden="true" />}
        />
        {companion ? (
          <VRouteLinkButton
            to={agentCenterConfigRoute({
              agentId: companion.agentId,
              pane: "config",
              returnTo: companionReturnTarget(companion),
              returnLabel: companion.displayName,
            })}
            variant="ghost"
            className={styles.railIconButton}
            aria-label={lang === "zh" ? "虚拟人设置" : "Virtual human settings"}
            icon={<Settings size={16} aria-hidden="true" />}
          />
        ) : null}
      </div>

      {state !== "ready" || !companion ? (
        <VStateSurface
          className={styles.state}
          title={unavailableTitle}
          tone={state === "loading" ? "loading" : state === "error" ? "error" : "unavailable"}
          busy={state === "loading"}
          skeletonLines={state === "loading" ? 3 : false}
          actions={<VRouteLinkButton to="/companions">{lang === "zh" ? "返回大厅" : "Back to lobby"}</VRouteLinkButton>}
        >
          {errorMessage || (lang === "zh" ? "请从人物大厅重新进入。" : "Open this person again from the lobby.")}
        </VStateSurface>
      ) : (
        <div className={styles.profile}>
          <CompanionPortrait companion={companion} className={styles.railPortrait} />
          <div className={styles.personSummary}>
            <div className={styles.personPresence}>
              <VStatusChip tone={companion.snapshot.state?.lifePaused ? "warning" : "success"}>
                {companion.snapshot.state?.lifePaused
                  ? (lang === "zh" ? "已暂停" : "Paused")
                  : (lang === "zh" ? "在线" : "Online")}
              </VStatusChip>
              <time>{localTime}</time>
            </div>
            <div className={styles.personNameCopy}>
              <h1>{companion.displayName}</h1>
              <span title={`${lang === "zh" ? "心情" : "Mood"}: ${lifeMoodLabel(companion.snapshot, lang)}`} aria-label={`${lang === "zh" ? "心情" : "Mood"}: ${lifeMoodLabel(companion.snapshot, lang)}`}>{lifeMoodSymbol(companion.snapshot)}</span>
            </div>
            <p className={styles.personStatus}>{activityLabel}</p>
            <div className={styles.personFacts} aria-label={lang === "zh" ? "人物状态摘要" : "Person status summary"}>
              <span title={locationLabel}><MapPin size={14} aria-hidden="true" /><strong>{locationLabel}</strong></span>
              <span title={activityLabel}><Sparkles size={14} aria-hidden="true" /><strong>{activityLabel}</strong></span>
              <span title={relationshipLabel}><Heart size={14} aria-hidden="true" /><strong>{relationshipLabel}</strong></span>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
