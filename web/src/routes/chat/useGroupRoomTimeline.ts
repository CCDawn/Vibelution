/**
 * Read-only group-room transcript projection over the backend timeline API.
 *
 * Authority split (phase 2 timeline swap):
 * - The timeline query (queryKeys.chatRoomTimeline) owns the message list.
 *   The SSE `chat_room_detail` snapshot invalidates it; the query function
 *   resumes from the stored cursor, so every reconciliation is incremental.
 * - The room detail cache keeps metadata/participants/operation results. Its
 *   `rounds` are only read here as the LEGACY fallback for rooms whose
 *   history predates the timeline log — never as a live transcript source.
 * - Speaker delta/state SSE channels stay untouched (typing/streaming bubbles).
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo } from "react";

import { fetchChatRoomTimeline } from "../../api/chat";
import { queryKeys } from "../../api/queryKeys";
import type {
  ChatRoomDetail,
  ChatRoomMessage,
  ChatRoomRound,
  ChatRoomTimelineEvent,
} from "../../api/types";

/** Backend default page size (timeline.py DEFAULT_READ_LIMIT; max 500). */
export const GROUP_TIMELINE_PAGE_LIMIT = 200;
/**
 * One logical fetch walks at most this many forward pages before it reports
 * ``hasMore`` and waits for loadMore(); keeps a huge room from monopolizing
 * the network on first open.
 */
const GROUP_TIMELINE_MAX_CHAIN_PAGES = 10;

const ROUND_TERMINAL_STATUSES = new Set(["completed", "partial", "failed"]);

export type GroupTimelineMemberChangeRow = {
  key: string;
  seq: number;
  createdAt: string;
  addedParticipantIds: string[];
  removedParticipantIds: string[];
  participantCount: number;
};

export type GroupTimelineItem =
  | { kind: "round"; round: ChatRoomRound }
  | { kind: "member_change"; row: GroupTimelineMemberChangeRow };

/** One cursor-chain accumulation stored under queryKeys.chatRoomTimeline. */
export type GroupRoomTimelineAccumulation = {
  roomId: string;
  /** Deduplicated events, ascending by seq. */
  events: ChatRoomTimelineEvent[];
  /** Highest seq applied; next reconciliation resumes from here. */
  cursor: number;
  /** True when the chain budget cut the walk before the log tail. */
  hasMore: boolean;
};

export type GroupRoomTimelineProjection = {
  items: GroupTimelineItem[];
  /** True when the render fell back to detail rounds (timeline empty/loading/error). */
  legacyFromDetail: boolean;
  /** True while the very first chain is still in flight and nothing is bridged. */
  loading: boolean;
  /** Log tail not yet reached within the page budget; loadMore() resumes. */
  hasMore: boolean;
  loadingMore: boolean;
  loadMore: () => void;
};

function text(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}

function idList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.map((item) => text(item).trim()).filter(Boolean)
    : [];
}

function roundShell(event: ChatRoomTimelineEvent, payload: Record<string, unknown>, status: string): ChatRoomRound {
  const createdAt = text(event.createdAt);
  return {
    roundId: text(event.roundId ?? payload.roundId).trim(),
    roomId: text(event.roomId),
    topic: text(payload.topic),
    mode: text(payload.mode),
    purpose: text(payload.purpose),
    config: {},
    status,
    speakerOrder: idList(payload.speakerOrder),
    messages: [],
    summary: "",
    startedAt: createdAt,
    updatedAt: createdAt,
    finishedAt: "",
  };
}

function messageFromPayload(payload: Record<string, unknown>): ChatRoomMessage | null {
  const messageId = text(payload.messageId).trim();
  if (!messageId) return null;
  return { ...(payload as object), messageId } as ChatRoomMessage;
}

/**
 * Folds the flat append-only timeline into the surface's render view model:
 * round_state(start) opens a round section, message events cluster into their
 * round by roundId, round_state(finish) seals it with the digest, and
 * member_change events become lightweight system rows between sections.
 * Artifact events are kept as an explicit no-op branch (schema-only today).
 */
export function foldGroupTimelineEvents(events: ChatRoomTimelineEvent[]): GroupTimelineItem[] {
  const items: GroupTimelineItem[] = [];
  const rounds = new Map<string, ChatRoomRound>();
  const ensureRound = (event: ChatRoomTimelineEvent, status: string): ChatRoomRound => {
    const roundId = text(event.roundId ?? event.payload?.roundId).trim();
    const existing = rounds.get(roundId);
    if (existing) return existing;
    const round = roundShell(event, event.payload ?? {}, status);
    rounds.set(roundId, round);
    items.push({ kind: "round", round });
    return round;
  };
  for (const event of events) {
    if (!event || typeof event !== "object") continue;
    const type = text(event.type).trim();
    const payload = (event.payload && typeof event.payload === "object" ? event.payload : {}) as Record<string, unknown>;
    const createdAt = text(event.createdAt);
    if (type === "round_state") {
      const status = text(payload.status).trim().toLowerCase();
      if (status === "running") {
        const round = ensureRound(event, status);
        // A re-delivered start may refine metadata; never regress a terminal round.
        if (round.status === "running") {
          round.topic = text(payload.topic) || round.topic;
          round.mode = text(payload.mode) || round.mode;
          round.purpose = text(payload.purpose) || round.purpose;
          round.speakerOrder = idList(payload.speakerOrder).length ? idList(payload.speakerOrder) : round.speakerOrder;
          round.updatedAt = createdAt || round.updatedAt;
        }
      } else if (status === "stopping") {
        const round = ensureRound(event, status);
        round.status = "stopping";
        round.updatedAt = createdAt || round.updatedAt;
      } else if (ROUND_TERMINAL_STATUSES.has(status)) {
        const round = ensureRound(event, status);
        round.status = status;
        round.summary = text(payload.summary) || round.summary;
        round.topic = text(payload.topic) || round.topic;
        round.finishedAt = text(payload.finishedAt) || createdAt || round.finishedAt;
        round.updatedAt = createdAt || round.updatedAt;
      }
      // Unknown round_state statuses stay unpainted (defensive).
    } else if (type === "message") {
      const message = messageFromPayload(payload);
      if (!message) continue;
      const round = ensureRound(event, "");
      if (!round.messages.some((item) => item.messageId === message.messageId)) {
        round.messages.push(message);
      }
      if (createdAt && (!round.updatedAt || createdAt > round.updatedAt)) {
        round.updatedAt = createdAt;
      }
    } else if (type === "member_change") {
      const added = idList(payload.addedParticipantIds);
      const removed = idList(payload.removedParticipantIds);
      if (!added.length && !removed.length) continue;
      const participantCount = Number(payload.participantCount);
      items.push({
        kind: "member_change",
        row: {
          key: text(event.eventId).trim() || `member-change:${event.seq}`,
          seq: Number(event.seq) || 0,
          createdAt,
          addedParticipantIds: added,
          removedParticipantIds: removed,
          participantCount: Number.isFinite(participantCount) ? participantCount : -1,
        },
      });
    } else if (type === "artifact") {
      // Schema-only today: no backend write point, no UI. Kept visible so a
      // future producer cannot silently fall through as an unknown type.
      continue;
    }
    // Unknown types are ignored: the timeline is append-only and forward
    // compatible by contract.
  }
  return items;
}

/** Legacy bridge: detail rounds expressed as timeline items (same view model). */
export function roundsToTimelineItems(rounds: ChatRoomRound[] | undefined): GroupTimelineItem[] {
  return (rounds ?? []).map((round) => ({ kind: "round", round }) as GroupTimelineItem);
}

export type UseGroupRoomTimelineOptions = {
  roomId: string;
  enabled: boolean;
  /** Room detail snapshot: legacy fallback source + reset reconciliation only. */
  detail: ChatRoomDetail | null | undefined;
};

export function useGroupRoomTimeline({
  roomId,
  enabled,
  detail,
}: UseGroupRoomTimelineOptions): GroupRoomTimelineProjection {
  const queryClient = useQueryClient();
  const normalizedRoomId = String(roomId || "").trim();
  const queryKey = useMemo(
    () => queryKeys.chatRoomTimeline(normalizedRoomId || "none"),
    [normalizedRoomId],
  );
  const query = useQuery({
    queryKey,
    queryFn: async ({ signal }): Promise<GroupRoomTimelineAccumulation> => {
      const previous = queryClient.getQueryData<GroupRoomTimelineAccumulation>(queryKey);
      const eventsBySeq = new Map<number, ChatRoomTimelineEvent>();
      for (const event of previous?.events ?? []) {
        const seq = Number(event?.seq);
        if (Number.isFinite(seq)) eventsBySeq.set(seq, event);
      }
      let cursor = Number(previous?.cursor ?? 0) || 0;
      let hasMore = false;
      let pages = 0;
      // The timeline API is forward-only (events with seq > cursor), so one
      // logical fetch walks pages until the log tail or the chain budget;
      // ``hasMore`` left true means the budget cut the walk and loadMore()
      // resumes from the stored cursor.
      for (;;) {
        const page = await fetchChatRoomTimeline(normalizedRoomId, {
          cursor,
          limit: GROUP_TIMELINE_PAGE_LIMIT,
          signal,
        });
        for (const event of page.events ?? []) {
          const seq = Number(event?.seq);
          if (Number.isFinite(seq) && seq > cursor) eventsBySeq.set(seq, event);
        }
        const nextCursor = Number(page.nextCursor);
        cursor = Number.isFinite(nextCursor) ? Math.max(cursor, nextCursor) : cursor;
        hasMore = Boolean(page.hasMore);
        pages += 1;
        if (!hasMore || pages >= GROUP_TIMELINE_MAX_CHAIN_PAGES) break;
      }
      return {
        roomId: normalizedRoomId,
        events: [...eventsBySeq.values()].sort((a, b) => Number(a.seq) - Number(b.seq)),
        cursor,
        hasMore,
      };
    },
    enabled: enabled && Boolean(normalizedRoomId),
    staleTime: 10_000,
  });

  const detailRoundCount = detail?.rounds?.length ?? -1;
  useEffect(() => {
    if (!enabled || !normalizedRoomId) return;
    const stored = queryClient.getQueryData<GroupRoomTimelineAccumulation>(queryKey);
    if (!stored || stored.cursor <= 0) return;
    if (detailRoundCount === 0) {
      // Room reset keeps the roomId but wipes the server-side timeline log;
      // resuming from the stored cursor would permanently skip the fresh log,
      // so reset the accumulation (active observers refetch from zero).
      void queryClient.resetQueries({ queryKey, exact: true });
    }
  }, [enabled, normalizedRoomId, queryClient, queryKey, detailRoundCount]);

  const events = query.data?.events ?? [];
  const legacyRounds = detail?.rounds;
  const items = useMemo<GroupTimelineItem[]>(() => {
    if (query.isPending || query.isError || events.length === 0) {
      // Bridge the first chain with the detail rounds so a room switch never
      // flashes empty; if the timeline stays empty (legacy room without log
      // events, or the endpoint unavailable) the bridge becomes the render.
      return roundsToTimelineItems(legacyRounds);
    }
    const folded = foldGroupTimelineEvents(events);
    // Pre-timeline history guard: a room may hold detail rounds that predate
    // the timeline log while new events only cover later activity. Prepend the
    // strictly older, timeline-unrepresented rounds so no old message vanishes.
    const timelineRoundIds = new Set(
      folded.flatMap((item) => (item.kind === "round" ? [String(item.round.roundId || "").trim()] : [])),
    );
    const firstTimelineAt = Date.parse(text(events[0]?.createdAt));
    const legacyPrefix = roundsToTimelineItems(legacyRounds).filter((item) => {
      if (item.kind !== "round") return false;
      const roundId = String(item.round.roundId || "").trim();
      if (!roundId || timelineRoundIds.has(roundId)) return false;
      const startedAt = Date.parse(item.round.startedAt || "");
      return Number.isFinite(firstTimelineAt) && Number.isFinite(startedAt) && startedAt < firstTimelineAt;
    });
    return [...legacyPrefix, ...folded];
  }, [query.isPending, query.isError, events, legacyRounds]);

  const loadMore = useCallback(() => {
    void query.refetch();
  }, [query]);

  const legacyFromDetail = query.isPending || query.isError || events.length === 0;

  return {
    items,
    legacyFromDetail,
    loading: query.isPending && (legacyRounds?.length ?? 0) === 0,
    hasMore: query.isSuccess && Boolean(query.data?.hasMore),
    loadingMore: query.isFetching && !query.isPending,
    loadMore,
  };
}
