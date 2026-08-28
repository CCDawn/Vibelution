import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  fetchVirtualHumanDiary,
  fetchVirtualHumanEvents,
  fetchVirtualHumanMemories,
  fetchVirtualHumanRelationships,
} from "../../api/virtualHumanLife";
import { queryKeys } from "../../api/queryKeys";
import type {
  VirtualHumanActivity,
  VirtualHumanCompanion,
  VirtualHumanDiaryEntry,
  VirtualHumanEpisodicMemory,
  VirtualHumanLifeEvent,
  VirtualHumanRelationship,
} from "../../api/types";
import { usePageVisibility } from "../../app/pollingPolicy";
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

function EventRows({ events, lang }: { events: VirtualHumanLifeEvent[]; lang: "zh" | "en" }) {
  if (!events.length) {
    return <p className={styles.cardCopy}>{lang === "zh" ? "今天还没有已记录的实际经历。" : "No lived events have been recorded today."}</p>;
  }
  return (
    <div className={styles.eventList}>
      {events.slice(-4).reverse().map((event) => (
        <article key={event.eventId} className={styles.eventItem}>
          <time className={styles.eventTime}>{formatLifeTime(event.occurredAt || "", lang)}</time>
          <div className={styles.eventCopy}>
            <strong>{event.title || (lang === "zh" ? "生活经历" : "Life event")}</strong>
            <span>{event.outcome?.summary || event.failureReason || event.kind}</span>
          </div>
        </article>
      ))}
    </div>
  );
}

function DiaryRows({ entries, lang }: { entries: VirtualHumanDiaryEntry[]; lang: "zh" | "en" }) {
  if (!entries.length) {
    return <p className={styles.cardCopy}>{lang === "zh" ? "还没有从实际经历写下日记。" : "No diary entries have been derived from lived events yet."}</p>;
  }
  return (
    <div className={styles.memoryList}>
      {entries.slice(-4).reverse().map((entry) => (
        <article key={entry.diaryEntryId} className={styles.memoryItem}>
          <div className={styles.memoryItemHeader}>
            <strong>{entry.title || (lang === "zh" ? "生活记录" : "Life note")}</strong>
            <time>{entry.localDate || "--"}</time>
          </div>
          <p className={styles.cardCopy}>{entry.content || (lang === "zh" ? "这条记录暂时没有正文。" : "This note has no body yet.")}</p>
          <span className={styles.memoryMeta}>
            {entry.sourceEventIds.length} {lang === "zh" ? "条实际经历" : "lived event(s)"}
          </span>
        </article>
      ))}
    </div>
  );
}

function formatMemoryTimestamp(value: string | null | undefined, lang: "zh" | "en"): string {
  if (!value) return "--";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "--";
  try {
    return new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(parsed);
  } catch {
    return "--";
  }
}

function memoryTimestamp(memory: VirtualHumanEpisodicMemory): number {
  const value = memory.promotedAt || memory.occurredAt;
  if (!value) return 0;
  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function MemoryRows({ memories, lang }: { memories: VirtualHumanEpisodicMemory[]; lang: "zh" | "en" }) {
  if (!memories.length) {
    return (
      <p className={styles.cardCopy}>
        {lang === "zh"
          ? "还没有达到长期记忆重要性门槛的生活片段。"
          : "No lived moments have crossed the long-term memory threshold yet."}
      </p>
    );
  }
  return (
    <div className={styles.memoryList}>
      {[...memories].sort((left, right) => memoryTimestamp(right) - memoryTimestamp(left)).slice(0, 6).map((memory) => {
        const salience = typeof memory.salienceScore === "number"
          ? Math.round(memory.salienceScore)
          : null;
        const sourceCount = Array.isArray(memory.sourceEventIds) ? memory.sourceEventIds.length : 0;
        return (
          <article key={memory.episodeId} className={styles.memoryItem}>
            <div className={styles.memoryItemHeader}>
              <strong>{lang === "zh" ? "生活片段" : "Lived moment"}</strong>
              <time>{formatMemoryTimestamp(memory.occurredAt, lang)}</time>
            </div>
            <p className={styles.memoryText}>
              {memory.text || (lang === "zh" ? "这条记忆暂时没有正文。" : "This memory has no text yet.")}
            </p>
            <div className={styles.memoryMetaRow}>
              {salience !== null ? (
                <span>{lang === "zh" ? `重要性 ${salience}%` : `Salience ${salience}%`}</span>
              ) : null}
              {sourceCount > 0 ? (
                <span>{lang === "zh" ? `来自 ${sourceCount} 条经历` : `From ${sourceCount} event(s)`}</span>
              ) : null}
              {memory.promotedAt ? (
                <span>{lang === "zh" ? `晋升于 ${formatMemoryTimestamp(memory.promotedAt, lang)}` : `Promoted ${formatMemoryTimestamp(memory.promotedAt, lang)}`}</span>
              ) : null}
            </div>
          </article>
        );
      })}
    </div>
  );
}

function RelationshipRows({ relationships, lang }: { relationships: VirtualHumanRelationship[]; lang: "zh" | "en" }) {
  if (!relationships.length) {
    return <p className={styles.cardCopy}>{lang === "zh" ? "关系投影仍在自然形成中。" : "Relationship projections are still taking shape."}</p>;
  }
  return (
    <div className={styles.relationshipGrid}>
      {relationships.slice(0, 4).map((relationship) => (
        <div key={relationship.targetId} className={styles.relationshipItem}>
          <strong title={relationship.targetId}>{relationship.targetId}</strong>
          <span>
            {lang === "zh" ? "亲密" : "Intimacy"} {relationship.intimacy} · {lang === "zh" ? "信任" : "Trust"} {relationship.trust}
          </span>
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
  const pageVisible = usePageVisibility();
  const activity = companion ? currentLifeActivity(companion.snapshot) : null;
  const upcoming = companion ? upcomingLifeActivities(companion.snapshot, 3) : [];
  const today = companion?.snapshot.todaySchedule?.activities ?? [];
  const memoryQueriesEnabled = state === "ready" && Boolean(companion) && activeTab === "memory";
  const todayEventsQuery = useQuery({
    queryKey: queryKeys.virtualHumanEvents(companion?.agentId || "", companion?.snapshot.state?.localDate || "", 100),
    queryFn: ({ signal }) => fetchVirtualHumanEvents(companion!.agentId, {
      localDate: companion!.snapshot.state?.localDate,
      limit: 100,
      signal,
    }),
    enabled: state === "ready" && Boolean(companion) && activeTab === "today",
    refetchInterval: pageVisible ? 30_000 : false,
  });
  const diaryQuery = useQuery({
    queryKey: queryKeys.virtualHumanDiary(companion?.agentId || "", "", 100),
    queryFn: ({ signal }) => fetchVirtualHumanDiary(companion!.agentId, { limit: 100, signal }),
    enabled: memoryQueriesEnabled,
    refetchInterval: pageVisible ? 30_000 : false,
  });
  const relationshipsQuery = useQuery({
    queryKey: queryKeys.virtualHumanRelationships(companion?.agentId || ""),
    queryFn: ({ signal }) => fetchVirtualHumanRelationships(companion!.agentId, { signal }),
    enabled: memoryQueriesEnabled,
    refetchInterval: pageVisible ? 30_000 : false,
  });
  const memoriesQuery = useQuery({
    queryKey: queryKeys.virtualHumanMemories(companion?.agentId || "", 100),
    queryFn: ({ signal }) => fetchVirtualHumanMemories(companion!.agentId, { limit: 100, signal }),
    enabled: memoryQueriesEnabled,
    refetchInterval: pageVisible ? 30_000 : false,
    retry: false,
  });
  const memoryCount = companion?.snapshot.health?.memoryPromotionCount;
  const memoryCountLabel = typeof memoryCount === "number"
    ? `${memoryCount}`
    : memoriesQuery.data
      ? `${memoriesQuery.data.length}`
      : "--";
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
            <>
              <section className={styles.lifeCard}>
                <p className={styles.cardLabel}>{companion.snapshot.todaySchedule?.localDate || (lang === "zh" ? "今天" : "Today")}</p>
                <ScheduleRows activities={today} lang={lang} />
              </section>
              <section className={styles.lifeCard}>
                <p className={styles.cardLabel}>{lang === "zh" ? "实际经历" : "Lived events"}</p>
                {todayEventsQuery.isPending ? (
                  <VStateSurface density="compact" title={lang === "zh" ? "正在读取经历" : "Loading lived events"} tone="loading" busy skeletonLines={2} />
                ) : todayEventsQuery.isError ? (
                  <VStateSurface density="compact" title={lang === "zh" ? "经历暂时不可用" : "Lived events unavailable"} tone="error">
                    {todayEventsQuery.error instanceof Error ? todayEventsQuery.error.message : undefined}
                  </VStateSurface>
                ) : (
                  <EventRows events={todayEventsQuery.data ?? []} lang={lang} />
                )}
              </section>
            </>
          ) : null}

          {activeTab === "memory" ? (
            <>
              <section className={styles.lifeCardAccent}>
                <p className={styles.cardLabel}>{lang === "zh" ? "长期记忆" : "Long-term memory"}</p>
                <div className={styles.memoryOverview}>
                  <strong>{memoryCountLabel}</strong>
                  <span className={styles.cardMeta}>{lang === "zh" ? "条已晋升片段" : "promoted moment(s)"}</span>
                </div>
                <p className={styles.cardCopy}>
                  {lang === "zh"
                    ? "只展示从真实生活经历晋升的记忆；计划和未完成的活动不会直接出现在这里。"
                    : "Only memories promoted from lived events appear here; plans and unfinished activities stay out."}
                </p>
              </section>
              <section className={styles.lifeCard}>
                <p className={styles.cardLabel}>{lang === "zh" ? "记忆片段" : "Memory moments"}</p>
                {memoriesQuery.isPending ? (
                  <VStateSurface density="compact" title={lang === "zh" ? "正在读取长期记忆" : "Loading long-term memories"} tone="loading" busy skeletonLines={2} />
                ) : memoriesQuery.isError ? (
                  <VStateSurface density="compact" title={lang === "zh" ? "长期记忆暂不可用" : "Long-term memories unavailable"} tone="unavailable">
                    {lang === "zh" ? "记忆服务暂未提供，下面的日记和关系仍可查看。" : "The memory service is not available yet; diary and relationship projections remain available."}
                  </VStateSurface>
                ) : (
                  <MemoryRows memories={memoriesQuery.data ?? []} lang={lang} />
                )}
              </section>
              <section className={styles.lifeCard}>
                <p className={styles.cardLabel}>{lang === "zh" ? "共同记忆" : "Shared memory"}</p>
                <p className={styles.cardCopy}>{companion.snapshot.state?.relationshipSummary || (lang === "zh" ? "暂时还没有形成稳定的关系摘要。" : "No stable relationship summary yet.")}</p>
              </section>
              <section className={styles.lifeCard}>
                <p className={styles.cardLabel}>{lang === "zh" ? "关系" : "Relationships"}</p>
                {relationshipsQuery.isPending ? (
                  <VStateSurface density="compact" title={lang === "zh" ? "正在读取关系" : "Loading relationships"} tone="loading" busy skeletonLines={2} />
                ) : relationshipsQuery.isError ? (
                  <VStateSurface density="compact" title={lang === "zh" ? "关系暂时不可用" : "Relationships unavailable"} tone="error">
                    {relationshipsQuery.error instanceof Error ? relationshipsQuery.error.message : undefined}
                  </VStateSurface>
                ) : (
                  <RelationshipRows relationships={relationshipsQuery.data ?? []} lang={lang} />
                )}
              </section>
              <section className={styles.lifeCard}>
                <p className={styles.cardLabel}>{lang === "zh" ? "日记" : "Diary"}</p>
                {diaryQuery.isPending ? (
                  <VStateSurface density="compact" title={lang === "zh" ? "正在读取日记" : "Loading diary"} tone="loading" busy skeletonLines={2} />
                ) : diaryQuery.isError ? (
                  <VStateSurface density="compact" title={lang === "zh" ? "日记暂时不可用" : "Diary unavailable"} tone="error">
                    {diaryQuery.error instanceof Error ? diaryQuery.error.message : undefined}
                  </VStateSurface>
                ) : (
                  <DiaryRows entries={diaryQuery.data ?? []} lang={lang} />
                )}
              </section>
              <section className={styles.lifeCard}>
                <p className={styles.cardLabel}>{lang === "zh" ? "事实边界" : "Fact boundary"}</p>
                <p className={styles.cardCopy}>{lang === "zh" ? "这里只显示生活经历、晋升记忆和关系摘要；原始对话历史仍由当前 Session 拥有。" : "Only lived events, promoted memories, and relationship summaries appear here. The current Session still owns conversation history."}</p>
              </section>
            </>
          ) : null}
        </div>
      )}
    </aside>
  );
}
