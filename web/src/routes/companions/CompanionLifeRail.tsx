import { useState } from "react";

import type { VirtualHumanActivity, VirtualHumanCompanion } from "../../api/types";
import { VStateSurface, VStatusChip, VTabs } from "../../components/vui";
import {
  currentLifeActivity,
  formatLifeTime,
  lifeMoodLabel,
  upcomingLifeActivities,
} from "./companionPresentation";
import type { CompanionRailState } from "./CompanionPersonRail";
import styles from "./CompanionChatRails.styles";

function ScheduleRows({ activities, lang }: { activities: VirtualHumanActivity[]; lang: "zh" | "en" }) {
  if (!activities.length) {
    return <p className={styles.cardCopy}>{lang === "zh" ? "今天暂时没有后续安排。" : "Nothing else is scheduled today."}</p>;
  }
  return (
    <div className={styles.scheduleList}>
      {activities.map((activity) => (
        <div key={activity.activityId} className={styles.scheduleItem}>
          <time>{formatLifeTime(activity.startAt, lang)}</time>
          <div>
            <strong>{activity.title}</strong>
            <span>{formatLifeTime(activity.startAt, lang)}–{formatLifeTime(activity.endAt, lang)} · {activity.status}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

export function CompanionLifeRail({
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
  const [activeTab, setActiveTab] = useState("now");
  const activity = companion ? currentLifeActivity(companion.snapshot) : null;
  const upcoming = companion ? upcomingLifeActivities(companion.snapshot, 3) : [];
  const today = companion?.snapshot.todaySchedule?.activities ?? [];
  const stateCopy = state === "loading"
    ? (lang === "zh" ? "正在载入生活状态" : "Loading life state")
    : state === "error"
      ? (lang === "zh" ? "生活状态载入失败" : "Failed to load life state")
      : (lang === "zh" ? "没有可展示的生活状态" : "No life state is available");

  return (
    <aside
      className={`${className} ${styles.lifeRail}`}
      aria-hidden={collapsed}
      role={overlayOpen ? "dialog" : undefined}
      aria-label={companion ? `${companion.displayName} 的生活` : stateCopy}
      data-companion-life-rail="true"
    >
      <header className={styles.lifeHeader}>
        <div className={styles.lifeTitleRow}>
          <div className={styles.lifeTitleCopy}>
            <p>Life context</p>
            <h2>{companion ? `${companion.displayName} ${lang === "zh" ? "的生活" : "life"}` : stateCopy}</h2>
          </div>
          {companion ? (
            <VStatusChip tone={companion.snapshot.state?.lifePaused ? "warning" : "success"}>
              {companion.snapshot.state?.lifePaused
                ? (lang === "zh" ? "已暂停" : "Paused")
                : (lang === "zh" ? "心跳在线" : "Live")}
            </VStatusChip>
          ) : null}
        </div>
        <VTabs
          className={styles.tabs}
          listClassName={styles.tabList}
          triggerClassName={styles.tabTrigger}
          aria-label={lang === "zh" ? "生活内容" : "Life sections"}
          value={activeTab}
          onValueChange={setActiveTab}
          items={[
            { id: "now", label: lang === "zh" ? "现在" : "Now" },
            { id: "today", label: lang === "zh" ? "今天" : "Today" },
            { id: "memory", label: lang === "zh" ? "记忆" : "Memory" },
          ]}
        />
      </header>

      {state !== "ready" || !companion ? (
        <VStateSurface
          className={styles.state}
          title={stateCopy}
          tone={state === "loading" ? "loading" : state === "error" ? "error" : "unavailable"}
          busy={state === "loading"}
          skeletonLines={state === "loading" ? 3 : false}
        >
          {errorMessage}
        </VStateSurface>
      ) : (
        <div className={styles.lifeContent}>
          {activeTab === "now" ? (
            <>
              <section className={styles.lifeCardAccent}>
                <p className={styles.cardLabel}>{lang === "zh" ? "现在" : "Now"}</p>
                <h3 className={styles.cardTitle}>{activity?.title || (lang === "zh" ? "自由活动" : "Unscheduled time")}</h3>
                {activity ? (
                  <span className={styles.cardMeta}>
                    {formatLifeTime(activity.startAt, lang)}–{formatLifeTime(activity.endAt, lang)}
                  </span>
                ) : null}
              </section>
              <section className={styles.lifeCard}>
                <p className={styles.cardLabel}>{lang === "zh" ? "心情" : "Mood"}</p>
                <div className={styles.moodRow}>
                  <strong>{lifeMoodLabel(companion.snapshot, lang)}</strong>
                  <span>{lang === "zh" ? "自然影响表达" : "Shapes expression"}</span>
                </div>
                <div className={styles.facts}>
                  <span className={styles.fact}><span>{lang === "zh" ? "体力" : "Energy"}</span><strong>{companion.snapshot.state?.energy ?? 0}%</strong></span>
                  <span className={styles.fact}><span>{lang === "zh" ? "社交需要" : "Social"}</span><strong>{companion.snapshot.state?.socialNeed ?? 0}%</strong></span>
                </div>
              </section>
              <section className={styles.lifeCard}>
                <p className={styles.cardLabel}>{lang === "zh" ? "接下来" : "Next"}</p>
                <ScheduleRows activities={upcoming.filter((item) => item.activityId !== activity?.activityId)} lang={lang} />
              </section>
              <section className={styles.lifeCard}>
                <p className={styles.cardLabel}>{lang === "zh" ? "与你的连续性" : "Continuity with you"}</p>
                <p className={styles.cardCopy}>{companion.snapshot.state?.relationshipSummary || (lang === "zh" ? "关系仍在自然形成中。" : "The relationship is still taking shape.")}</p>
              </section>
            </>
          ) : null}

          {activeTab === "today" ? (
            <section className={styles.lifeCard}>
              <p className={styles.cardLabel}>{companion.snapshot.todaySchedule?.localDate || (lang === "zh" ? "今天" : "Today")}</p>
              <ScheduleRows activities={today} lang={lang} />
            </section>
          ) : null}

          {activeTab === "memory" ? (
            <>
              <section className={styles.lifeCard}>
                <p className={styles.cardLabel}>{lang === "zh" ? "共同记忆" : "Shared memory"}</p>
                <p className={styles.cardCopy}>{companion.snapshot.state?.relationshipSummary || (lang === "zh" ? "暂时还没有形成稳定的关系摘要。" : "No stable relationship summary yet.")}</p>
              </section>
              <section className={styles.lifeCard}>
                <p className={styles.cardLabel}>{lang === "zh" ? "事实边界" : "Fact boundary"}</p>
                <p className={styles.cardCopy}>{lang === "zh" ? "这里只显示生活与关系摘要；原始对话历史仍由当前 Session 拥有。" : "Only life and relationship summaries appear here. The current Session still owns conversation history."}</p>
              </section>
            </>
          ) : null}
        </div>
      )}
    </aside>
  );
}
