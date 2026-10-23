import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import type { SessionSummary } from "../../api/types";
import {
  applySessionIndexDeltaToQueryClient,
  parseSessionIndexDelta,
} from "./useSessionIndexEventStream";

function summary(id: string, overrides: Partial<SessionSummary> = {}): SessionSummary {
  return {
    id,
    title: `title-${id}`,
    status: "idle",
    taskSummary: "",
    lastActive: "2026-01-01T00:00:00+00:00",
    updatedAt: "2026-01-01T00:00:00+00:00",
    currentPhase: "idle",
    ...overrides,
  } as SessionSummary;
}

function clientWith(rows: SessionSummary[]): QueryClient {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  queryClient.setQueryData<SessionSummary[]>(["sessions"], rows);
  return queryClient;
}

describe("parseSessionIndexDelta", () => {
  it("drops ready and heartbeat frames, which carry no row change", () => {
    expect(parseSessionIndexDelta(JSON.stringify({ type: "ready", at: "t" }))).toBeNull();
    expect(parseSessionIndexDelta(JSON.stringify({ type: "heartbeat", at: "t" }))).toBeNull();
  });

  it("ignores malformed payloads instead of throwing into the stream loop", () => {
    expect(parseSessionIndexDelta("")).toBeNull();
    expect(parseSessionIndexDelta("not-json")).toBeNull();
    expect(parseSessionIndexDelta(JSON.stringify({ type: "session.upserted" }))).toBeNull();
  });

  it("keeps the patch only when it actually carries fields", () => {
    expect(
      parseSessionIndexDelta(JSON.stringify({ type: "session.upserted", sessionId: "s1" })),
    ).toEqual({ type: "session.upserted", sessionId: "s1" });

    expect(
      parseSessionIndexDelta(JSON.stringify({
        type: "session.upserted",
        sessionId: "s1",
        at: "2026-01-02T00:00:00Z",
        patch: { lastActive: "2026-01-02T00:00:00Z" },
      })),
    ).toEqual({
      type: "session.upserted",
      sessionId: "s1",
      at: "2026-01-02T00:00:00Z",
      patch: { lastActive: "2026-01-02T00:00:00Z" },
    });
  });
});

describe("applySessionIndexDeltaToQueryClient", () => {
  it("drops a removed row in place without refetching the index", () => {
    const queryClient = clientWith([summary("s1"), summary("s2")]);
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    applySessionIndexDeltaToQueryClient(queryClient, {
      type: "session.removed",
      sessionId: "s1",
    });

    const rows = queryClient.getQueryData<SessionSummary[]>(["sessions"]);
    expect(rows?.map((row) => row.id)).toEqual(["s2"]);
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("applies a patched upsert in place and leaves other rows reference-identical", () => {
    const untouched = summary("s2");
    const queryClient = clientWith([summary("s1"), untouched]);
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    applySessionIndexDeltaToQueryClient(queryClient, {
      type: "session.upserted",
      sessionId: "s1",
      patch: { lastActive: "2026-02-02T00:00:00Z", lastTurnStatus: "succeeded" },
    });

    const rows = queryClient.getQueryData<SessionSummary[]>(["sessions"]) ?? [];
    expect(rows[0]?.lastActive).toBe("2026-02-02T00:00:00Z");
    expect(rows[0]?.lastTurnStatus).toBe("succeeded");
    expect(rows[1]).toBe(untouched);
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("falls back to one index read when the server could not describe the change", () => {
    const queryClient = clientWith([summary("s1")]);
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    applySessionIndexDeltaToQueryClient(queryClient, {
      type: "session.upserted",
      sessionId: "s1",
    });

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["sessions"] });
  });

  it("keeps the cache value identical when the patched row is not loaded", () => {
    const queryClient = clientWith([summary("s1")]);
    const before = queryClient.getQueryData<SessionSummary[]>(["sessions"]);

    applySessionIndexDeltaToQueryClient(queryClient, {
      type: "session.upserted",
      sessionId: "missing",
      patch: { lastActive: "2026-03-03T00:00:00Z" },
    });

    expect(queryClient.getQueryData<SessionSummary[]>(["sessions"])).toBe(before);
  });
});
