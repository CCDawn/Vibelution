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
  VirtualHumanDriveItem,
  VirtualHumanEnvironmentFact,
  VirtualHumanEpisodicMemory,
  VirtualHumanLifeEvent,
  VirtualHumanOpenLoop,
  VirtualHumanProactiveCandidate,
  VirtualHumanReflection,
  VirtualHumanRelationship,
} from "../../api/types";
import { usePageVisibility } from "../../app/pollingPolicy";
import { VStateSurface, VStatusChip, VTabs } from "../../components/vui";
import {
  currentLifeActivity,
  currentLifeActivityLabel,
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

function boundedPercent(value: number | null | undefined): number {
  if (typeof value !== "number" || Number.isNaN(value)) return 0;
  return Math.max(0, Math.min(100, Math.round(value)));
}

function factValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (value == null) return "--";
  try {
    return JSON.stringify(value);
  } catch {
    return "--";
  }
}

function sourceKindLabel(sourceKind: string, lang: "zh" | "en"): string {
  const labels: Record<string, [string, string]> = {
    operator: ["由你确认", "Confirmed by you"],
    sensor: ["设备感知", "Device observation"],
    tool: ["工具观察", "Tool observation"],
    schedule_outcome: ["实际活动结果", "Lived activity outcome"],
    initial_state: ["初始状态", "Initial state"],
  };
  const pair = labels[sourceKind] ?? ["有来源记录", "Source recorded"];
  return lang === "zh" ? pair[0] : pair[1];
}

function environmentFactLabel(factKey: string, lang: "zh" | "en"): string {
  if (factKey === "weather.current") return lang === "zh" ? "天气" : "Weather";
  if (factKey.startsWith("location.")) return lang === "zh" ? "地点" : "Location";
  const readable = factKey.split(".").filter(Boolean).at(-1) || factKey;
  return readable || (lang === "zh" ? "环境" : "Environment");
}

function EnvironmentRows({ facts, lang }: { facts: VirtualHumanEnvironmentFact[]; lang: "zh" | "en" }) {
  if (!facts.length) {
    return <p className={styles.cardCopy}>{lang === "zh" ? "还没有经过确认的环境信息。" : "No source-backed environment facts yet."}</p>;
  }
  return (
    <div className={styles.compactList}>
      {facts.slice(0, 4).map((fact) => (
        <div key={fact.factId} className={styles.compactItem}>
          <div className={styles.compactItemHeader}>
            <strong>{environmentFactLabel(fact.factKey, lang)}</strong>
            <span>{factValue(fact.value)}</span>
          </div>
          <small title={fact.sourceRef} aria-label={`${sourceKindLabel(fact.sourceKind, lang)}: ${fact.sourceRef}`}>
            {sourceKindLabel(fact.sourceKind, lang)}
            {typeof fact.confidence === "number" ? ` · ${boundedPercent(fact.confidence)}%` : ""}
          </small>
        </div>
      ))}
    </div>
  );
}

function DriveRows({ drives, lang }: { drives: VirtualHumanDriveItem[]; lang: "zh" | "en" }) {
  if (!drives.length) {
    return <p className={styles.cardCopy}>{lang === "zh" ? "还没有形成稳定的个人目标。" : "No stable personal goal has formed yet."}</p>;
  }
  return (
    <div className={styles.compactList}>
      {drives.slice(0, 4).map((drive) => {
        const progress = boundedPercent(drive.progress);
        return (
          <div key={drive.driveId} className={styles.progressItem}>
            <div className={styles.progressHeader}>
              <strong>{drive.title}</strong>
              {typeof drive.progress === "number" ? <span>{progress}%</span> : null}
            </div>
            {typeof drive.progress === "number" ? (
              <div className={styles.progressTrack} aria-label={`${drive.title} ${progress}%`}>
                <span className={styles.progressFill} style={{ width: `${progress}%` }} />
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function ReflectionRows({ reflections, lang }: { reflections: VirtualHumanReflection[]; lang: "zh" | "en" }) {
  const accepted = reflections
    .filter((item) => item.status === "accepted" && item.sourceKind !== "dream")
    .slice(-4)
    .reverse();
  if (!accepted.length) {
    return <p className={styles.cardCopy}>{lang === "zh" ? "今晚还没有需要留下的回想。" : "No reflection needs to be kept tonight."}</p>;
  }
  return (
    <div className={styles.timelineList}>
      {accepted.map((reflection) => (
        <article key={reflection.proposalId} className={styles.timelineItem}>
          <span aria-hidden="true" />
          <div>
            <time>{reflection.localDate || formatMemoryTimestamp(reflection.createdAt, lang)}</time>
            <p>{reflection.text}</p>
            <small>{lang === "zh" ? `来自 ${reflection.sourceEventIds?.length ?? 0} 段真实经历` : `From ${reflection.sourceEventIds?.length ?? 0} lived event(s)`}</small>
          </div>
        </article>
      ))}
    </div>
  );
}

function OpenLoopRows({ loops, lang }: { loops: VirtualHumanOpenLoop[]; lang: "zh" | "en" }) {
  if (!loops.length) {
    return <p className={styles.cardCopy}>{lang === "zh" ? "今天没有悬着没说完的话。" : "No unfinished topic is hanging today."}</p>;
  }
  return (
    <div className={styles.compactList}>
      {loops.slice(0, 3).map((loop) => (
        <div key={loop.loopId} className={styles.compactItem}>
          <strong>{loop.summary}</strong>
          <small>{lang === "zh" ? "会在合适的时候自然接回" : "Will be resumed naturally at the right time"}</small>
        </div>
      ))}
    </div>
  );
}

function proactiveStateCopy(candidate: VirtualHumanProactiveCandidate | undefined, lang: "zh" | "en"): string {
  if (!candidate) return lang === "zh" ? "目前没有特别想打扰你的事。" : "Nothing feels worth interrupting you for right now.";
  const reason = candidate.suppressionReason || candidate.status || candidate.decision || "";
  const labels: Record<string, [string, string]> = {
    quiet_hours: ["夜深了，先把想说的话留到明天。", "It is late, so this thought can wait until tomorrow."],
    unanswered_backoff: ["你还没回复前，不连续打扰。", "Waiting for your reply instead of sending another interruption."],
    duplicate_topic: ["这个话题最近说过，先不重复。", "This topic came up recently, so it will not be repeated."],
    busy: ["正在做自己的事情，稍后再说。", "Busy with her own activity and will speak later."],
    sleeping: ["正在休息，醒来再说。", "Resting now and will speak after waking."],
    expired: ["错过了合适时机，这件事已经放下。", "The moment passed, so this thought was let go."],
    low_value: ["这件小事暂时不值得打扰你。", "This small thing is not worth interrupting you for."],
    eligible: ["有件事想自然地和你分享。", "There is something she would naturally like to share."],
    selected: ["正在找合适的时机和你说。", "Looking for a natural moment to tell you."],
    delivered: ["刚刚已经和你分享过了。", "This was just shared with you."],
  };
  const pair = labels[reason] ?? [candidate.reason || "正在判断要不要开口。", candidate.reason || "Deciding whether this is worth saying."];
  return lang === "zh" ? pair[0] : pair[1];
}

function relationshipInteractionLabel(kind: string | undefined, lang: "zh" | "en"): string {
  const labels: Record<string, [string, string]> = {
    supportive_conversation: ["互相支持地聊了聊", "had a supportive conversation"],
    shared_activity: ["一起经历了一件事", "shared an activity"],
    conflict: ["有过一次不愉快", "had a disagreement"],
    apology_repair: ["认真修复了不愉快", "made a sincere repair"],
    promise_kept: ["兑现了一个约定", "kept a promise"],
  };
  const pair = labels[kind || ""];
  if (pair) return lang === "zh" ? pair[0] : pair[1];
  return lang === "zh" ? "有过一次日常交流" : "had an everyday conversation";
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
        const strength = boundedPercent(memory.memoryStrengthScore ?? memory.salienceScore);
        const breakdown = memory.scoreBreakdown;
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
            <div className={styles.progressHeader}>
              <span>{lang === "zh" ? "记忆强度" : "Memory strength"}</span>
              <strong>{strength}%</strong>
            </div>
            <div className={styles.progressTrack} aria-label={`${lang === "zh" ? "记忆强度" : "Memory strength"} ${strength}%`}>
              <span className={styles.progressFill} style={{ width: `${strength}%` }} />
            </div>
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
              {breakdown && (breakdown.emotion || 0) > 0 ? (
                <span>{lang === "zh" ? `情绪余波 ${breakdown.emotion}` : `Emotion ${breakdown.emotion}`}</span>
              ) : null}
              {breakdown && (breakdown.unresolved || 0) > 0 ? (
                <span>{lang === "zh" ? "关联未完话题" : "Linked to an open topic"}</span>
              ) : null}
              {memory.reinforcedAt ? (
                <span>{lang === "zh" ? `回想于 ${formatMemoryTimestamp(memory.reinforcedAt, lang)}` : `Recalled ${formatMemoryTimestamp(memory.reinforcedAt, lang)}`}</span>
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
      {relationships.slice(0, 4).map((relationship) => {
        const target = relationship.targetId === "user"
          ? (lang === "zh" ? "你们之间" : "Between you")
          : relationship.targetId;
        const stage = relationship.relationshipStage;
        const stageCopy = stage === "close"
          ? (lang === "zh" ? "彼此信任，也保留各自的空间" : "Mutual trust with room for separate lives")
          : stage === "friend"
            ? (lang === "zh" ? "已经形成自然稳定的朋友关系" : "A natural and stable friendship")
            : (lang === "zh" ? "还在慢慢熟悉彼此" : "Still getting to know each other");
        return (
          <div key={relationship.targetId} className={styles.relationshipItem}>
            <span>{target}</span>
            <strong>{stageCopy}</strong>
            <small>
              {lang === "zh" ? "亲密" : "Intimacy"} {relationship.intimacy} · {lang === "zh" ? "信任" : "Trust"} {relationship.trust}
              {relationship.lastInteractionKind ? ` · ${relationshipInteractionLabel(relationship.lastInteractionKind, lang)}` : ""}
            </small>
          </div>
        );
      })}
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
  const activityLabel = companion ? currentLifeActivityLabel(companion.snapshot, lang) : "";
  const upcoming = companion ? upcomingLifeActivities(companion.snapshot, 3) : [];
  const today = companion?.snapshot.todaySchedule?.activities ?? [];
  const causal = companion?.snapshot.causal;
  const environment = causal?.environment;
  const environmentFacts = environment ? environment.currentFacts ?? [] : [];
  const recentReflections = causal?.reflections?.recent ?? [];
  const proactiveCandidates = causal?.proactiveCandidates ?? [];
  const latestProactiveCandidate = proactiveCandidates.at(-1);
  const openLoops = causal?.openLoops?.open ?? [];
  const personalDrives = [
    ...(causal?.drives?.goals ?? []),
    ...(causal?.drives?.projects ?? []),
  ];
  const activeAffectCount = causal?.affect?.activeEpisodeIds?.length ?? 0;
  const locationStatus = companion?.snapshot.state?.locationStatus ?? "stationary";
  const locationLabel = locationStatus === "moving" && companion?.snapshot.state?.movingTo
    ? `${companion.snapshot.state.currentLocation} → ${companion.snapshot.state.movingTo}`
    : (companion?.snapshot.state?.currentLocation || (lang === "zh" ? "未记录" : "Not recorded"));
  const locationSource = companion?.snapshot.state?.locationSource;
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
                <h3 className={styles.cardTitle}>{activityLabel}</h3>
                {activity ? (
                  <span className={styles.cardMeta}>
                    {formatLifeTime(activity.startAt, lang)}–{formatLifeTime(activity.endAt, lang)}
                  </span>
                ) : null}
                <div className={styles.locationRow}>
                  <span>{locationStatus === "moving" ? (lang === "zh" ? "在路上" : "On the way") : (lang === "zh" ? "所在地点" : "Location")}</span>
                  <strong>{locationLabel}</strong>
                </div>
                {locationSource?.sourceKind ? (
                  <small
                    className={styles.sourceCopy}
                    title={locationSource.sourceRef}
                    aria-label={`${sourceKindLabel(locationSource.sourceKind, lang)}: ${locationSource.sourceRef || "--"}`}
                  >
                    {sourceKindLabel(locationSource.sourceKind, lang)}
                    {locationSource.arrivedAt ? ` · ${formatMemoryTimestamp(locationSource.arrivedAt, lang)}` : ""}
                  </small>
                ) : null}
              </section>
              <section className={styles.lifeCard}>
                <p className={styles.cardLabel}>{lang === "zh" ? "心情" : "Mood"}</p>
                <div className={styles.moodRow}>
                  <strong>{lifeMoodLabel(companion.snapshot, lang)}</strong>
                  <span>
                    {activeAffectCount > 0
                      ? (lang === "zh" ? `${activeAffectCount} 段经历仍有余波` : `${activeAffectCount} lived afterglow(s)`)
                      : (lang === "zh" ? "已回到自己的日常基线" : "Back at her usual baseline")}
                  </span>
                </div>
                <div className={styles.facts}>
                  <span className={styles.fact}><span>{lang === "zh" ? "体力" : "Energy"}</span><strong>{companion.snapshot.state?.energy ?? 0}%</strong></span>
                  <span className={styles.fact}><span>{lang === "zh" ? "社交需要" : "Social"}</span><strong>{companion.snapshot.state?.socialNeed ?? 0}%</strong></span>
                </div>
              </section>
              <section className={styles.lifeCard}>
                <p className={styles.cardLabel}>{lang === "zh" ? "身边环境" : "Around her"}</p>
                <EnvironmentRows facts={environmentFacts} lang={lang} />
              </section>
              <section className={styles.lifeCard}>
                <p className={styles.cardLabel}>{lang === "zh" ? "接下来" : "Next"}</p>
                <ScheduleRows activities={upcoming.filter((item) => item.activityId !== activity?.activityId)} lang={lang} />
              </section>
              <section className={styles.lifeCard}>
                <p className={styles.cardLabel}>{lang === "zh" ? "想说的话" : "Something to say"}</p>
                <p className={styles.cardCopy}>{proactiveStateCopy(latestProactiveCandidate, lang)}</p>
                {latestProactiveCandidate?.reason ? (
                  <small className={styles.sourceCopy}>{latestProactiveCandidate.reason}</small>
                ) : null}
              </section>
              <section className={styles.lifeCard}>
                <p className={styles.cardLabel}>{lang === "zh" ? "与你的连续性" : "Continuity with you"}</p>
                <p className={styles.cardCopy}>{companion.snapshot.state?.relationshipSummary || (lang === "zh" ? "关系仍在自然形成中。" : "The relationship is still taking shape.")}</p>
              </section>
            </>
          ) : null}

          {activeTab === "today" ? (
            <>
              <section className={styles.lifeCardAccent}>
                <p className={styles.cardLabel}>{lang === "zh" ? "个人目标" : "Personal goals"}</p>
                <DriveRows drives={personalDrives} lang={lang} />
              </section>
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
              <section className={styles.lifeCard}>
                <p className={styles.cardLabel}>{lang === "zh" ? "未完话题" : "Open topics"}</p>
                <OpenLoopRows loops={openLoops} lang={lang} />
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
                <p className={styles.cardLabel}>{lang === "zh" ? "自我人生线" : "Self timeline"}</p>
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
                <p className={styles.cardLabel}>{lang === "zh" ? "夜间回想" : "Night reflection"}</p>
                <ReflectionRows reflections={recentReflections} lang={lang} />
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
