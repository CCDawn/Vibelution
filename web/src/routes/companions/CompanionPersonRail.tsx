import { Settings } from "lucide-react";

import type { VirtualHumanCompanion } from "../../api/types";
import { VRouteLinkButton, VStateSurface, VStatusChip } from "../../components/vui";
import { agentCenterConfigRoute } from "../agentCenterRoutes";
import { CompanionPortrait } from "./CompanionPortrait";
import {
  companionAbout,
  companionIdentity,
  currentLifeActivity,
  formatLifeTime,
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
              returnTo: "/companions",
              returnLabel: "companions",
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
            <div className={styles.personNameRow}>
              <div className={styles.personNameCopy}>
                <h1>{companion.displayName}</h1>
                <p>{companionIdentity(companion)}</p>
              </div>
              <VStatusChip tone={companion.snapshot.state?.lifePaused ? "warning" : "success"}>
                {companion.snapshot.state?.lifePaused
                  ? (lang === "zh" ? "已暂停" : "Paused")
                  : (lang === "zh" ? "心跳在线" : "Heartbeat")}
              </VStatusChip>
            </div>
            <p className={styles.about}>{companionAbout(companion)}</p>
          </div>

          <section className={styles.lifeCardAccent} aria-label={lang === "zh" ? "此刻" : "Now"}>
            <p className={styles.cardLabel}>{lang === "zh" ? "此刻" : "Now"}</p>
            <h2 className={styles.cardTitle}>{activity?.title || (lang === "zh" ? "按自己的节奏生活" : "Living at her own pace")}</h2>
            {activity ? (
              <span className={styles.cardMeta}>
                {formatLifeTime(activity.startAt, lang)}–{formatLifeTime(activity.endAt, lang)}
              </span>
            ) : null}
            <p className={styles.cardCopy}>
              {lang === "zh" ? "生活状态会自然影响表达，但不会让实时回复变慢。" : "Life state shapes expression without delaying replies."}
            </p>
          </section>

          <section className={styles.lifeCard} aria-label={lang === "zh" ? "心情" : "Mood"}>
            <p className={styles.cardLabel}>{lang === "zh" ? "心情" : "Mood"}</p>
            <div className={styles.moodRow}>
              <strong>{lifeMoodLabel(companion.snapshot, lang)}</strong>
              <span>{companion.snapshot.state?.energy ?? 0}% {lang === "zh" ? "体力" : "energy"}</span>
            </div>
          </section>

          <footer className={styles.personFooter}>
            <strong>{lang === "zh" ? "当前人物专属栏" : "Current-person rail"}</strong>
            <span>{lang === "zh" ? "这里不选择其他人；切换人物请返回人物大厅。" : "There is no person picker here. Return to the lobby to switch."}</span>
          </footer>
        </>
      )}
    </aside>
  );
}
