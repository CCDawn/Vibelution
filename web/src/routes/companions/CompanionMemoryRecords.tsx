import { useRef, useState } from "react";
import { useQueries } from "@tanstack/react-query";

import { fetchVirtualHumanEvents } from "../../api/virtualHumanLife";
import { queryKeys } from "../../api/queryKeys";
import type { VirtualHumanEpisodicMemory, VirtualHumanLifeEvent } from "../../api/types";
import { usePageVisibility } from "../../app/pollingPolicy";
import { VButton, VDialog } from "../../components/vui";
import styles from "./CompanionMemoryRecords.styles";

type Language = "zh" | "en";

function memoryTimestamp(memory: VirtualHumanEpisodicMemory): number {
  const timestamp = Date.parse(memory.promotedAt || memory.occurredAt || "");
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function formatTimestamp(value: string | null | undefined, lang: Language): string {
  const parsed = value ? new Date(value) : null;
  return parsed && !Number.isNaN(parsed.getTime())
    ? new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
      year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false,
    }).format(parsed)
    : "--";
}

function sourceIds(memory: VirtualHumanEpisodicMemory): string[] {
  return [...new Set((memory.sourceEventIds ?? []).filter((id) => typeof id === "string" && id.trim()).map((id) => id.trim()))];
}

function sourceDates(memory: VirtualHumanEpisodicMemory | undefined): string[] {
  const timestamp = Date.parse(memory?.occurredAt || "");
  if (!Number.isFinite(timestamp)) return [];
  // Events are partitioned by the character's local date while occurredAt is
  // UTC. Adjacent UTC dates cover timezone boundaries without guessing a zone.
  return [-1, 0, 1].map((offset) => new Date(timestamp + offset * 86_400_000).toISOString().slice(0, 10));
}

function rawMemorySource(memory: VirtualHumanEpisodicMemory): string {
  // Legacy responses may carry a source field outside the current DTO. Keep
  // its original value as provenance, never infer an event from its wording.
  return ["source", "sourceKind", "sourceRef"].flatMap((key) => {
    const value: unknown = Reflect.get(memory, key);
    return typeof value === "string" && value.trim() ? [`${key}: ${value}`] : [];
  }).join(" · ");
}

function isSimulation(event: VirtualHumanLifeEvent): boolean {
  return event.outcome?.kind === "deterministic_simulation"
    || event.activityKind === "simulated"
    || event.simulatedAfterRestart === true;
}

function eventSourceLabel(event: VirtualHumanLifeEvent, lang: Language): string {
  if (isSimulation(event)) return lang === "zh" ? "日程模拟记录" : "Schedule simulation record";
  return lang === "zh" ? "来源事件记录" : "Source event record";
}

export function CompanionMemoryRecords({
  agentId,
  memories,
  lang,
}: {
  agentId: string;
  memories: VirtualHumanEpisodicMemory[];
  lang: Language;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const readButtonRef = useRef<HTMLButtonElement | null>(null);
  const pageVisible = usePageVisibility();
  const selected = memories.find((memory) => memory.episodeId === selectedId);
  const dates = selected && sourceIds(selected).length ? sourceDates(selected) : [];
  const eventQueries = useQueries({
    queries: dates.map((localDate) => ({
      queryKey: queryKeys.virtualHumanEvents(agentId, localDate, 500),
      queryFn: ({ signal }: { signal: AbortSignal }) => fetchVirtualHumanEvents(agentId, { localDate, limit: 500, signal }),
      enabled: Boolean(agentId),
      refetchInterval: pageVisible ? 30_000 : false,
      retry: false,
    })),
  });
  const sourcesPending = eventQueries.some((query) => query.isPending);
  const sourcesError = eventQueries.some((query) => query.isError);
  const eventsById = new Map(eventQueries.flatMap((query) => query.data ?? [])
    .filter((event) => event.agentId === agentId)
    .map((event) => [event.eventId, event]));

  function sourceSummary(memory: VirtualHumanEpisodicMemory): string {
    const ids = sourceIds(memory);
    if (!ids.length) return lang === "zh" ? "来源未知" : "Source unknown";
    const events = ids.flatMap((id) => eventsById.get(id) ? [eventsById.get(id)!] : []);
    if (events.some(isSimulation)) return lang === "zh" ? "含日程模拟记录" : "Includes schedule simulation";
    if (memory.episodeId !== selectedId) return lang === "zh" ? `${ids.length} 条关联来源 · 待核对` : `${ids.length} linked source(s) · unchecked`;
    if (sourcesPending) return lang === "zh" ? "正在读取来源" : "Loading source";
    if (sourcesError) return lang === "zh" ? "来源暂不可用" : "Source unavailable";
    if (events.length !== ids.length) return lang === "zh" ? "来源未完全确认" : "Source partly unknown";
    return lang === "zh" ? `${ids.length} 条来源事件记录` : `${ids.length} source event record(s)`;
  }

  if (!memories.length) {
    return <p className={styles.note}>{lang === "zh" ? "还没有保留的长期记忆。" : "No long-term memories have been kept yet."}</p>;
  }

  return (
    <div className={styles.list}>
      {[...memories].sort((left, right) => memoryTimestamp(right) - memoryTimestamp(left)).slice(0, 6).map((memory) => (
        <article key={memory.episodeId} className={styles.record}>
          <div className={styles.header}>
            <strong>{lang === "zh" ? "记忆记录" : "Memory record"}</strong>
            <time dateTime={memory.occurredAt || undefined}>{formatTimestamp(memory.occurredAt, lang)}</time>
          </div>
          <p className={styles.preview}>{memory.text || (lang === "zh" ? "这条记忆没有正文。" : "This memory has no body.")}</p>
          <div className={styles.footer}>
            <span className={styles.source}>{sourceSummary(memory)}</span>
            <VButton variant="ghost" density="compact" onPress={(event) => { readButtonRef.current = event.currentTarget; setSelectedId(memory.episodeId); }} aria-label={lang === "zh" ? "阅读记忆正文与来源" : "Read memory and source"}>
              {lang === "zh" ? "阅读" : "Read"}
            </VButton>
          </div>
        </article>
      ))}
      <VDialog open={Boolean(selected)} onOpenChange={(open) => { if (!open) setSelectedId(null); }} onCloseAutoFocus={(event) => { if (readButtonRef.current?.isConnected) { event.preventDefault(); readButtonRef.current.focus(); } }} title={lang === "zh" ? "记忆记录" : "Memory record"} description={lang === "zh" ? "现存正文与来源" : "Stored text and source"} size="lg">
        {selected ? (
          <div className={styles.content}>
            <p className={styles.body}>{selected.text || (lang === "zh" ? "这条记忆没有正文。" : "This memory has no body.")}</p>
            <p className={styles.note}>{lang === "zh" ? "当前接口只提供以上正文，未提供更长内容。" : "The current response supplies the text above; no longer body was provided."}</p>
            <div className={styles.metadata}>
              <p>{lang === "zh" ? "记录时间" : "Recorded"} · {formatTimestamp(selected.occurredAt, lang)}</p>
              {selected.promotedAt ? <p>{lang === "zh" ? "保留为长期记忆" : "Kept as long-term memory"} · {formatTimestamp(selected.promotedAt, lang)}</p> : null}
              {selected.reinforcedAt ? <p>{lang === "zh" ? "最近回想" : "Last recalled"} · {formatTimestamp(selected.reinforcedAt, lang)}</p> : null}
              {typeof selected.salienceScore === "number" ? <p>{lang === "zh" ? "重要性评分" : "Salience score"} · {selected.salienceScore}</p> : null}
            </div>
            <section className={styles.sources} aria-label={lang === "zh" ? "记忆来源" : "Memory source"}>
              <h3>{lang === "zh" ? "来源" : "Source"}</h3>
              {rawMemorySource(selected) ? <p className={styles.source}>{rawMemorySource(selected)}</p> : null}
              {!sourceIds(selected).length ? <p className={styles.note}>{lang === "zh" ? "来源未知：当前记录没有关联来源事件。" : "Source unknown: no source events are linked to this record."}</p> : null}
              {sourceIds(selected).length > 0 && !dates.length ? <p className={styles.note}>{lang === "zh" ? "记录时间缺失，无法定位来源事件；来源未知。" : "The record date is missing; source events cannot be located and their source is unknown."}</p> : null}
              {sourceIds(selected).length > 0 && sourcesPending ? <p role="status" className={styles.note}>{lang === "zh" ? "正在读取来源事件…" : "Loading source events…"}</p> : null}
              {sourceIds(selected).length > 0 && sourcesError ? (
                <div className={styles.metadata}>
                  <p role="status">{lang === "zh" ? "部分来源暂不可用，未读取的事件仍待确认。" : "Some sources are unavailable; unread events remain unconfirmed."}</p>
                  <VButton variant="ghost" density="compact" isPending={eventQueries.some((query) => query.isFetching)} onPress={() => { void Promise.all(eventQueries.filter((query) => query.isError).map((query) => query.refetch())); }}>{lang === "zh" ? "重试来源" : "Retry sources"}</VButton>
                </div>
              ) : null}
              {sourceIds(selected).map((id) => {
                const event = eventsById.get(id);
                return (
                  <article key={id} className={styles.event}>
                    <strong>{event ? eventSourceLabel(event, lang) : (lang === "zh" ? "来源事件待确认" : "Unconfirmed source event")}</strong>
                    {event ? (
                      <>
                        {event.title ? <p className={styles.note}>{event.title}</p> : null}
                        <time className={styles.source} dateTime={event.occurredAt}>{formatTimestamp(event.occurredAt, lang)}</time>
                        {event.outcome?.summary ? <p className={styles.body}>{event.outcome.summary}</p> : null}
                        {isSimulation(event) ? <p className={styles.note}>{lang === "zh" ? "这是日程模拟生成的记录，不能据此确认真实行动或共同经历。" : "This record was generated by schedule simulation and does not confirm a real action or shared experience."}</p> : null}
                      </>
                    ) : dates.length > 0 && !sourcesPending && !sourcesError ? (
                      <p className={styles.note}>{lang === "zh" ? "本次来源查询中未找到此事件，来源未知。" : "This event was not found in this source query; its source is unknown."}</p>
                    ) : null}
                    <details className={styles.source}>
                      <summary>{lang === "zh" ? "来源引用" : "Source reference"}</summary>
                      <p>{id}</p>
                      {event ? <p>{[event.kind, event.activityKind, event.outcome?.kind, event.outcome?.status].filter((value) => typeof value === "string" && value).join(" · ")}</p> : null}
                    </details>
                  </article>
                );
              })}
            </section>
          </div>
        ) : null}
      </VDialog>
    </div>
  );
}
