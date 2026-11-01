import { useCallback, useMemo, useSyncExternalStore } from "react";
import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { fetchSessionDetail } from "../../api/chat";
import { getKernelTaskTimeline, listKernelTasks } from "../../api/kernel";
import { listProjectAgentBusTimeline } from "../../api/projectAgentBus";
import { queryKeys } from "../../api/queryKeys";
import type { AgentInstance, KernelTaskTimelinePayload, SessionDetail } from "../../api/types";
import { mergeSessionDetailMessageWindowWithOutcome } from "../chatSessionState";
import { isTempSessionId } from "../sessionOptimisticIds";
import { busMessageRecord, kernelMessageRecord, mergeAgentMessageRecords, messageObject, sessionMessageRecords } from "./agentMessageRecords";
import { useAgentMessageHistoryLimit, useAgentMessageSelection } from "./agentMessageSelectionStore";

export async function readAgentMessageDirectory(client: QueryClient, limit: number, signal?: AbortSignal) {
  const catalog = await listKernelTasks("", limit, { signal });
  const timelines: KernelTaskTimelinePayload[] = [];
  let unavailable = 0;
  // Bound parallel reads so opening the left rail cannot flood an active backend.
  for (let start = 0; start < catalog.tasks.length; start += 4) {
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    const batch = catalog.tasks.slice(start, start + 4);
    const results = await Promise.allSettled(batch.map((task) => {
      const key = queryKeys.kernelTaskTimeline(task.taskId);
      const terminal = ["succeeded", "completed", "failed", "cancelled", "blocked"].includes(task.status);
      const cached = client.getQueryData<KernelTaskTimelinePayload>(key);
      return client.fetchQuery({
        queryKey: key,
        queryFn: ({ signal: querySignal }) => getKernelTaskTimeline(task.taskId, { signal: querySignal }),
        // The directory can finish before its already-cached timeline does.
        staleTime: terminal ? (cached?.task?.status === task.status ? Infinity : 0) : 20_000,
        retry: false,
      });
    }));
    for (const result of results) {
      if (result.status === "fulfilled") timelines.push(result.value);
      else unavailable += 1;
    }
  }
  return { timelines, unavailable, scanned: catalog.tasks.length, hasMore: catalog.tasks.length >= limit && limit < 300, limit };
}

/** Read-only projection over existing public operator APIs and Session Journal cache. */
export function useAgentMessageRecords(options: { enabled?: boolean; sessionId?: string; agentsById?: Map<string, AgentInstance> } = {}) {
  const { enabled = true, sessionId = "", agentsById } = options;
  const client = useQueryClient(), cache = client.getQueryCache();
  const limit = useAgentMessageHistoryLimit(), selection = useAgentMessageSelection();
  const subscribe = useCallback((listener: () => void) => {
    let queued = false, mounted = true;
    const unsubscribe = cache.subscribe((event) => {
      const relevant = ["sessions", "agents", "agent-message-source-history"].includes(String(event.query.queryKey[0]));
      if (!relevant || !(event.type === "removed" || (event.type === "updated" && event.action.type === "success")) || queued) return;
      queued = true;
      queueMicrotask(() => { queued = false; if (mounted) listener(); });
    });
    return () => { mounted = false; unsubscribe(); };
  }, [cache]);
  const snapshot = useCallback(() => cache.getAll().filter((query) => query.state.data !== undefined && ["sessions", "agents", "agent-message-source-history"].includes(String(query.queryKey[0])))
    .map((query) => `${query.queryHash}:${query.state.dataUpdateCount}`).join("|"), [cache]);
  const cacheVersion = useSyncExternalStore(subscribe, snapshot, () => "");
  const directory = useQuery({
    queryKey: queryKeys.agentMessageDirectory(limit), queryFn: ({ signal }) => readAgentMessageDirectory(client, limit, signal),
    enabled, staleTime: 15_000, refetchInterval: enabled ? 15_000 : false, refetchIntervalInBackground: false,
  });
  const bus = useQuery({
    queryKey: queryKeys.projectAgentBus(), queryFn: ({ signal }) => listProjectAgentBusTimeline(undefined, { signal }),
    enabled, staleTime: 15_000, refetchInterval: enabled ? 15_000 : false, refetchIntervalInBackground: false,
  });
  const cached = useMemo(() => {
    const sessions = new Map<string, SessionDetail>(), agents = new Map(agentsById);
    const windows: Array<{ detail: SessionDetail; native: boolean }> = [];
    for (const query of cache.getAll()) {
      if (["sessions", "agent-message-source-history"].includes(String(query.queryKey[0])) && query.queryKey.length === 2) {
        const detail = query.state.data as SessionDetail | undefined;
        if (detail?.id && Array.isArray(detail.messages)) windows.push({ detail, native: query.queryKey[0] === "sessions" });
      }
      if (query.queryKey[0] === "agents") {
        const value = query.state.data;
        const list = Array.isArray(value) ? value : messageObject(value).agents;
        if (Array.isArray(list)) for (const item of list) {
          const row = messageObject(item);
          if (typeof row.agentId === "string" && typeof row.displayName === "string") agents.set(row.agentId, item as AgentInstance);
        }
      }
    }
    // Receive time is not a Session authority. Accumulate windows through the
    // existing ledger/edit/branch gates; native cache wins equal-ledger ties.
    windows.sort((a, b) => (Number(a.detail.ledgerSeq) || 0) - (Number(b.detail.ledgerSeq) || 0) || Number(a.native) - Number(b.native));
    for (const { detail } of windows) sessions.set(detail.id, mergeSessionDetailMessageWindowWithOutcome(sessions.get(detail.id), detail).detail);
    return { sessions, agents };
  // cacheVersion is the stable revision of native query data, not another transcript.
  }, [cache, cacheVersion, agentsById]);
  const baseRecords = useMemo(() => mergeAgentMessageRecords([
    ...(directory.data?.timelines ?? []).map((timeline) => kernelMessageRecord(timeline, cached.agents)).filter((record) => record !== null),
    ...(bus.data?.events ?? []).map((event) => busMessageRecord(event, cached.agents)).filter((record) => record !== null),
    ...[...cached.sessions.values()].flatMap((detail) => sessionMessageRecords(detail, cached.agents, cached.sessions)),
  ]), [directory.data, bus.data, cached]);
  const selected = baseRecords.find((record) => record.id === selection || record.aliases?.includes(selection ?? ""));
  const sourceSessionId = sessionId || selected?.sourceSessionId || "";
  const source = useQuery({
    queryKey: queryKeys.agentMessageSourceHistory(sourceSessionId),
    queryFn: ({ signal }) => fetchSessionDetail(sourceSessionId, { messageLimit: 200, includeSecondary: false, signal }),
    enabled: enabled && Boolean(sourceSessionId) && !isTempSessionId(sourceSessionId), staleTime: 15_000,
    refetchInterval: enabled && sourceSessionId ? 15_000 : false, refetchIntervalInBackground: false,
  });
  const failures = [directory, bus, source].filter((query) => query.isError);
  const error = failures.length ? failures.map((query) => query.error instanceof Error ? query.error.message : "消息来源读取失败").join("；")
    : directory.data?.unavailable ? `${directory.data.unavailable} 条消息来源暂不可用，已保留其他记录。` : "";
  return {
    records: baseRecords, loading: directory.isPending && bus.isPending, refreshing: directory.isFetching || bus.isFetching,
    error, hasMore: directory.data?.hasMore ?? false, limit, scanned: directory.data?.scanned ?? 0,
    refresh: () => { void directory.refetch(); void bus.refetch(); if (sourceSessionId) void source.refetch(); },
  };
}
