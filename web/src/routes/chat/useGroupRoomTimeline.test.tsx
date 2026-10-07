// @vitest-environment happy-dom
/**
 * Group-room timeline projection: flat timeline events fold into the existing
 * round view model (round_state opens/seals, message events cluster by
 * roundId), member_change events become system rows, empty logs fall back to
 * the detail rounds (legacy rooms), and the cursor chain walks to the tail /
 * resumes incrementally.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../../api/queryKeys";
import type { ChatRoomDetail, ChatRoomRound, ChatRoomTimelineEvent, ChatRoomTimelineResponse } from "../../api/types";
import {
  foldGroupTimelineEvents,
  useGroupRoomTimeline,
  type GroupRoomTimelineProjection,
  type UseGroupRoomTimelineOptions,
} from "./useGroupRoomTimeline";

const timelineReads = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("../../api/chat", () => ({
  fetchChatRoomTimeline: timelineReads.fetch,
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function eventOf(seq: number, type: string, payload: Record<string, unknown>, roundId = "", createdAt = ""): ChatRoomTimelineEvent {
  return {
    eventId: `tle-${seq}`,
    roomId: "room-1",
    seq,
    type,
    roundId,
    from: "",
    to: "",
    payload,
    createdAt: createdAt || new Date(Date.parse("2026-09-04T09:00:00Z") + seq * 1_000).toISOString(),
    schemaVersion: 1,
  };
}

function roundStart(seq: number, roundId: string, topic: string): ChatRoomTimelineEvent {
  return eventOf(seq, "round_state", {
    roundId,
    status: "running",
    topic,
    mode: "round_robin",
    purpose: "discussion",
    speakerOrder: ["p1"],
  }, roundId);
}

function messageEvent(seq: number, roundId: string, messageId: string, content: string): ChatRoomTimelineEvent {
  return eventOf(seq, "message", {
    messageId,
    participantId: "p1",
    sessionId: "s1",
    speakerCode: "A01",
    speakerTitle: "分析员",
    status: "completed",
    content,
    summary: "",
    timestamp: new Date(Date.parse("2026-09-04T09:00:00Z") + seq * 1_000).toISOString(),
  }, roundId);
}

function roundFinish(seq: number, roundId: string, status: string, summary: string): ChatRoomTimelineEvent {
  return eventOf(seq, "round_state", {
    roundId,
    status,
    topic: "",
    summary,
    messageCount: 2,
    completedCount: 2,
    finishedAt: new Date(Date.parse("2026-09-04T09:00:00Z") + seq * 1_000).toISOString(),
  }, roundId);
}

function memberChangeEvent(seq: number, added: string[], removed: string[] = []): ChatRoomTimelineEvent {
  return eventOf(seq, "member_change", {
    participantCount: 3,
    participantIds: ["p1", "p2", "p3"],
    addedParticipantIds: added,
    removedParticipantIds: removed,
  });
}

function pageOf(events: ChatRoomTimelineEvent[], options: { hasMore?: boolean } = {}): ChatRoomTimelineResponse {
  const seqs = events.map((event) => Number(event.seq) || 0);
  return {
    roomId: "room-1",
    cursor: 0,
    limit: 200,
    events,
    nextCursor: seqs.length ? Math.max(...seqs) : 0,
    hasMore: options.hasMore ?? false,
  };
}

function detailOf(rounds: ChatRoomRound[]): ChatRoomDetail {
  return {
    roomId: "room-1",
    title: "研究组",
    mode: "round_robin",
    purpose: "discussion",
    status: "ready",
    participants: [],
    rounds,
    activeRoundId: "",
    createdAt: "",
    updatedAt: "",
    availableModes: [],
    availablePurposes: [],
  } as ChatRoomDetail;
}

function legacyRound(roundId: string, topic: string): ChatRoomRound {
  return {
    roundId,
    roomId: "room-1",
    topic,
    mode: "round_robin",
    purpose: "discussion",
    config: {},
    status: "completed",
    speakerOrder: [],
    messages: [],
    summary: "旧纪要",
    startedAt: "2026-08-01T00:00:00Z",
    updatedAt: "2026-08-01T00:01:00Z",
    finishedAt: "2026-08-01T00:01:00Z",
  };
}

let results: GroupRoomTimelineProjection[] = [];
let currentRoot: Root | null = null;
let currentClient: QueryClient | null = null;
let container: HTMLElement | null = null;

function Host({ options }: { options: UseGroupRoomTimelineOptions }) {
  results.push(useGroupRoomTimeline(options));
  return null;
}

async function mount(options: UseGroupRoomTimelineOptions): Promise<void> {
  results = [];
  currentClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  container = document.createElement("div");
  document.body.appendChild(container);
  currentRoot = createRoot(container);
  await act(async () => {
    currentRoot?.render(
      <QueryClientProvider client={currentClient}>
        <Host options={options} />
      </QueryClientProvider>,
    );
  });
}

/**
 * Waits until the client-side query settled AND the projection reflects the
 * expected terminal state, so assertions never race the observer notification.
 */
async function settle(
  check?: (state: { status: string }, projection: GroupRoomTimelineProjection) => boolean,
): Promise<void> {
  await act(async () => {
    await vi.waitFor(() => {
      const state = currentClient?.getQueryState(queryKeys.chatRoomTimeline("room-1"));
      if (!state || state.fetchStatus !== "idle") {
        throw new Error("timeline query still fetching");
      }
      if (check && !check(state, projectionAt())) {
        throw new Error("projection not settled yet");
      }
    });
  });
}

function roundOf(projection: GroupRoomTimelineProjection) {
  return projection.items[0]?.kind === "round" ? projection.items[0].round : null;
}

async function unmount(): Promise<void> {
  if (currentRoot) {
    await act(async () => currentRoot.unmount());
  }
  container?.remove();
  currentRoot = null;
  currentClient = null;
  container = null;
}

function projectionAt(index = -1): GroupRoomTimelineProjection {
  const projection = results.at(index);
  if (!projection) throw new Error("no projection result recorded");
  return projection;
}

describe("foldGroupTimelineEvents", () => {
  it("opens rounds on round_state(start), clusters messages by roundId, seals with the finish digest", () => {
    const items = foldGroupTimelineEvents([
      roundStart(1, "r1", "讨论拆分"),
      messageEvent(2, "r1", "m1", "第一条"),
      messageEvent(3, "r1", "m2", "第二条"),
      roundFinish(4, "r1", "completed", "结论：可控"),
    ]);
    expect(items).toHaveLength(1);
    const round = items[0]?.kind === "round" ? items[0].round : null;
    expect(round?.roundId).toBe("r1");
    expect(round?.topic).toBe("讨论拆分");
    expect(round?.status).toBe("completed");
    expect(round?.summary).toBe("结论：可控");
    expect(round?.messages.map((message) => message.messageId)).toEqual(["m1", "m2"]);
    expect(round?.finishedAt).not.toBe("");
  });

  it("keeps member_change rows positioned between sections and drops pure-count updates", () => {
    const items = foldGroupTimelineEvents([
      roundStart(1, "r1", "议题一"),
      messageEvent(2, "r1", "m1", "发言"),
      memberChangeEvent(3, ["p2"]),
      memberChangeEvent(4, [], []),
      roundStart(5, "r2", "议题二"),
      messageEvent(6, "r2", "m2", "第二轮发言"),
    ]);
    expect(items.map((item) => item.kind)).toEqual(["round", "member_change", "round"]);
    const row = items[1]?.kind === "member_change" ? items[1].row : null;
    expect(row?.addedParticipantIds).toEqual(["p2"]);
    expect(row?.removedParticipantIds).toEqual([]);
    expect(items[0]?.kind === "round" && items[0].round.messages).toHaveLength(1);
    expect(items[2]?.kind === "round" && items[2].round.messages).toHaveLength(1);
  });

  it("ignores artifact events (schema-only today) and messages without an id", () => {
    const items = foldGroupTimelineEvents([
      eventOf(1, "artifact", { artifactId: "a1" }),
      eventOf(2, "message", { content: "no id" }, "r1"),
    ]);
    expect(items).toEqual([]);
  });
});

describe("useGroupRoomTimeline projection hook", () => {
  beforeEach(() => {
    timelineReads.fetch.mockReset();
  });

  afterEach(async () => {
    await unmount();
  });

  it("folds a settled timeline into round items", async () => {
    timelineReads.fetch.mockResolvedValue(pageOf([
      roundStart(1, "r1", "讨论拆分"),
      messageEvent(2, "r1", "m1", "发言内容"),
      roundFinish(3, "r1", "completed", "纪要"),
    ]));
    await mount({ roomId: "room-1", enabled: true, detail: detailOf([]) });
    await settle((state, projection) => state.status === "success" && !projection.legacyFromDetail);
    const projection = projectionAt();
    expect(timelineReads.fetch).toHaveBeenCalledTimes(1);
    expect(timelineReads.fetch.mock.calls[0]?.[1]).toMatchObject({ cursor: 0, limit: 200 });
    expect(projection.items).toHaveLength(1);
    expect(projection.legacyFromDetail).toBe(false);
    expect(projection.hasMore).toBe(false);
  });

  it("falls back to detail rounds when the first pull returns zero events (legacy room)", async () => {
    timelineReads.fetch.mockResolvedValue(pageOf([]));
    await mount({
      roomId: "room-1",
      enabled: true,
      detail: detailOf([legacyRound("old-1", "旧议题一"), legacyRound("old-2", "旧议题二")]),
    });
    await settle((state, projection) => state.status === "success" && projection.legacyFromDetail);
    const projection = projectionAt();
    expect(projection.items).toHaveLength(2);
    expect(projection.items.every((item) => item.kind === "round")).toBe(true);
    expect(projection.legacyFromDetail).toBe(true);
  });

  it("bridges with detail rounds while the first chain is in flight, then swaps to the fold", async () => {
    let resolveFirst!: (page: ChatRoomTimelineResponse) => void;
    timelineReads.fetch.mockImplementation(
      () => new Promise<ChatRoomTimelineResponse>((resolve) => {
        resolveFirst = resolve;
      }),
    );
    await mount({
      roomId: "room-1",
      enabled: true,
      detail: detailOf([legacyRound("old-1", "旧议题")]),
    });
    // First chain in flight: the detail rounds bridge the view instead of an
    // empty flash.
    expect(projectionAt().items).toHaveLength(1);
    expect(projectionAt().legacyFromDetail).toBe(true);

    resolveFirst(pageOf([
      roundStart(1, "r1", "新议题"),
      messageEvent(2, "r1", "m1", "新发言"),
    ]));
    await settle((state, projection) => state.status === "success" && !projection.legacyFromDetail);
    const projection = projectionAt();
    // The pre-timeline legacy round stays prefixed; the timeline fold follows.
    expect(projection.items.map((item) => (item.kind === "round" ? item.round.roundId : "row")))
      .toEqual(["old-1", "r1"]);
    expect(projection.items[1]?.kind === "round" && projection.items[1].round.topic).toBe("新议题");
    expect(projection.legacyFromDetail).toBe(false);
  });

  it("prepends pre-timeline detail rounds that the log does not cover", async () => {
    timelineReads.fetch.mockResolvedValue(pageOf([
      roundStart(1, "new-1", "新轮"),
      messageEvent(2, "new-1", "m1", "新发言"),
    ]));
    await mount({
      roomId: "room-1",
      enabled: true,
      detail: detailOf([legacyRound("old-1", "旧议题"), legacyRound("new-1", "被时间线覆盖的轮")]),
    });
    await settle((state, projection) => state.status === "success" && !projection.legacyFromDetail);
    const projection = projectionAt();
    expect(projection.items.map((item) => (item.kind === "round" ? item.round.roundId : "row")))
      .toEqual(["old-1", "new-1"]);
    expect(projection.legacyFromDetail).toBe(false);
  });

  it("walks the forward cursor chain to the tail and reconciles incrementally on invalidation", async () => {
    timelineReads.fetch
      .mockResolvedValueOnce(pageOf([roundStart(1, "r1", "一"), messageEvent(2, "r1", "m1", "甲")], { hasMore: true }))
      .mockResolvedValueOnce(pageOf([messageEvent(3, "r1", "m2", "乙"), roundFinish(4, "r1", "completed", "纪要")]));
    await mount({ roomId: "room-1", enabled: true, detail: detailOf([]) });
    await settle((state, projection) => state.status === "success" && roundOf(projection)?.messages.length === 2);
    expect(timelineReads.fetch).toHaveBeenCalledTimes(2);
    expect(timelineReads.fetch.mock.calls[1]?.[1]).toMatchObject({ cursor: 2 });
    expect(roundOf(projectionAt())?.messages.map((message) => message.messageId)).toEqual(["m1", "m2"]);

    // Live update: the SSE snapshot invalidates the key; the query resumes
    // from the stored cursor instead of replaying the log.
    timelineReads.fetch.mockResolvedValue(pageOf([messageEvent(5, "r1", "m3", "丙")]));
    await act(async () => {
      await currentClient?.invalidateQueries({ queryKey: queryKeys.chatRoomTimeline("room-1") });
    });
    await settle((state, projection) => roundOf(projection)?.messages.length === 3);
    expect(timelineReads.fetch).toHaveBeenCalledTimes(3);
    expect(timelineReads.fetch.mock.calls[2]?.[1]).toMatchObject({ cursor: 4 });
    expect(roundOf(projectionAt())?.messages.map((message) => message.messageId)).toEqual(["m1", "m2", "m3"]);
  });

  it("stops at the chain budget, reports hasMore, and loadMore resumes from the stored cursor", async () => {
    let calls = 0;
    timelineReads.fetch.mockImplementation(async (_roomId: string, options: { cursor?: number } = {}) => {
      calls += 1;
      const nextSeq = Number(options.cursor ?? 0) + 1;
      // The first ten pages keep hasMore so the budget (10 pages per chain)
      // cuts the walk; the 11th call reports the tail.
      return pageOf([messageEvent(nextSeq, "r1", `m${nextSeq}`, `内容${nextSeq}`)], { hasMore: calls <= 10 });
    });
    await mount({ roomId: "room-1", enabled: true, detail: detailOf([]) });
    await settle((state, projection) =>
      state.status === "success" && roundOf(projection)?.messages.length === 10 && projection.hasMore);
    expect(timelineReads.fetch).toHaveBeenCalledTimes(10);
    const projection = projectionAt();
    expect(projection.hasMore).toBe(true);
    expect(roundOf(projection)?.messages).toHaveLength(10);

    await act(async () => {
      projectionAt().loadMore();
    });
    await settle((state, projection2) =>
      state.status === "success" && roundOf(projection2)?.messages.length === 11 && !projection2.hasMore);
    expect(timelineReads.fetch).toHaveBeenCalledTimes(11);
    expect(timelineReads.fetch.mock.calls[10]?.[1]).toMatchObject({ cursor: 10 });
    const settled = projectionAt();
    expect(roundOf(settled)?.messages).toHaveLength(11);
    expect(settled.hasMore).toBe(false);
  });

  it("drops the accumulated cursor and refetches from zero when a reset empties the detail rounds", async () => {
    timelineReads.fetch.mockResolvedValue(pageOf([
      roundStart(1, "r1", "旧轮"),
      messageEvent(2, "r1", "m1", "旧发言"),
    ]));
    await mount({
      roomId: "room-1",
      enabled: true,
      detail: detailOf([legacyRound("r1", "旧轮")]),
    });
    await settle((state, projection) => state.status === "success" && roundOf(projection)?.messages.length === 1);
    expect(timelineReads.fetch).toHaveBeenCalledTimes(1);
    expect(roundOf(projectionAt())?.messages).toHaveLength(1);

    // Reset: detail cache now reports zero rounds while the stored cursor is 2.
    timelineReads.fetch.mockResolvedValue(pageOf([roundStart(1, "r2", "重置后的新轮")]));
    await act(async () => {
      currentRoot?.render(
        <QueryClientProvider client={currentClient!}>
          <Host options={{ roomId: "room-1", enabled: true, detail: detailOf([]) }} />
        </QueryClientProvider>,
      );
    });
    await settle((state, projection) => state.status === "success" && roundOf(projection)?.topic === "重置后的新轮");
    expect(timelineReads.fetch.mock.calls.at(-1)?.[1]).toMatchObject({ cursor: 0 });
    expect(roundOf(projectionAt())?.topic).toBe("重置后的新轮");
  });

  it("stays on the detail fallback when the timeline endpoint fails", async () => {
    timelineReads.fetch.mockRejectedValue(new Error("timeline unavailable"));
    await mount({
      roomId: "room-1",
      enabled: true,
      detail: detailOf([legacyRound("old-1", "旧议题")]),
    });
    await settle((state, projection) => state.status === "error" && projection.legacyFromDetail);
    const projection = projectionAt();
    expect(projection.items).toHaveLength(1);
    expect(projection.legacyFromDetail).toBe(true);
    expect(projection.hasMore).toBe(false);
  });
});
