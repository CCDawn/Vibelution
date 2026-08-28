import { Settings } from "lucide-react";

import type { VirtualHumanCompanion } from "../../api/types";
import { VRouteLinkButton, VStateSurface, VStatusChip } from "../../components/vui";
import { agentCenterConfigRoute } from "../agentCenterRoutes";
import { CompanionPortrait } from "./CompanionPortrait";
import {
  companionAbout,
  companionIdentity,
  companionReturnTarget,
  currentLifeActivity,
  lifeMoodLabel,
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
  const activity = companion ? currentLifeActivity(companion.snapshot) : null;
  return (
    <aside
      className={`${className} ${styles.personRail}`}
      aria-hidden={collapsed}
      role={overlayOpen ? "dialog" : undefined}
      aria-label={companion ? `${companion.displayName} 人物栏` : unavailableTitle}
      data-companion-person-rail="true"
    >
      <div className={styles.railActions}>
        <VRouteLinkButton to="/companions" variant="ghost" className={styles.quietLink}>
          ← {lang === "zh" ? "人物大厅" : "Companion lobby"}
        </VRouteLinkButton>
        {companion ? (
          <VRouteLinkButton
            to={agentCenterConfigRoute({
              agentId: companion.agentId,
              pane: "config",
              returnTo: companionReturnTarget(companion),
              returnLabel: companion.displayName,
            })}
            variant="ghost"
            className={styles.quietLink}
            aria-label={lang === "zh" ? "虚拟人设置" : "Virtual human settings"}
            icon={<Settings size={14} />}
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
        <>
          <div className={styles.profile}>
            <CompanionPortrait companion={companion} className={styles.railPortrait} />
            <div className={styles.personPresence}>
              <span>{companion.agentCode}</span>
              <VStatusChip tone={companion.snapshot.state?.lifePaused ? "warning" : "success"}>
                {companion.snapshot.state?.lifePaused
                  ? (lang === "zh" ? "已暂停" : "Paused")
                  : (lang === "zh" ? "和你在一起" : "Here with you")}
              </VStatusChip>
            </div>
            <div className={styles.personNameCopy}>
              <h1>{companion.displayName}</h1>
              <p>{companionIdentity(companion)}</p>
            </div>
            <blockquote className={styles.personQuote}>{companionAbout(companion)}</blockquote>
            <div className={styles.personFacts}>
              <span><small>{lang === "zh" ? "心情" : "Mood"}</small><strong>{lifeMoodLabel(companion.snapshot, lang)}</strong></span>
              <span><small>{lang === "zh" ? "关系" : "Relationship"}</small><strong>{companion.snapshot.state?.relationshipSummary || (lang === "zh" ? "慢慢熟悉中" : "Getting acquainted")}</strong></span>
              <span><small>{lang === "zh" ? "此刻" : "Now"}</small><strong>{activity?.title || (lang === "zh" ? "按自己的节奏生活" : "Living at her own pace")}</strong></span>
            </div>
            <VRouteLinkButton
              to={agentCenterConfigRoute({
                agentId: companion.agentId,
                pane: "config",
                returnTo: companionReturnTarget(companion),
                returnLabel: companion.displayName,
              })}
              variant="secondary"
              className={styles.profileLink}
            >
              {lang === "zh" ? "打开她的完整档案" : "Open full profile"}
            </VRouteLinkButton>
          </div>

          <footer className={styles.personFooter}>
            <strong>{lang === "zh" ? "当前人物专属栏" : "Current-person rail"}</strong>
            <span>{lang === "zh" ? "这里不选择其他人；切换人物请返回人物大厅。" : "There is no person picker here. Return to the lobby to switch."}</span>
          </footer>
        </>
      )}
    </aside>
  );
}
