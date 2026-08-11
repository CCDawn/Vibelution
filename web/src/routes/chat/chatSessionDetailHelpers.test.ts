import { describe, expect, it } from "vitest";

import {
  buildSessionDetailShellFromSummary,
  fetchSessionDetailWindow,
  isForeignSessionDetailQueryKey,
  isProvisionalSessionTranscript,
  isSessionDetailHardLoading,
  isSessionNotFoundError,
  isStaleLedgerUpdate,
  resolveNeighborSessionIdsForPrefetch,
  resolveSessionDetailPlaceholder,
  sessionDetailSnapshotKey,
  shouldShowSessionTranscriptPending,
} from "./chatSessionDetailHelpers";
import type { SessionDetail, SessionSummary } from "../../api/types";
import * as client from "../../api/client";
import { vi } from "vitest";
import { resolveAssistantTurnRenderSurface } from "../chatTurnProtocol";

describe("chatSessionDetailHelpers", () => {
  it("detects session-not-found errors across locales", () => {
    expect(isSessionNotFoundError(new Error("Session not found"))).toBe(true);
    expect(isSessionNotFoundError(new Error("会话不存在"))).toBe(true);
    expect(isSessionNotFoundError(new Error("network down"))).toBe(false);
  });

  it("safely renders a deep-linked persisted turn item whose text is absent", () => {
    const surface = resolveAssistantTurnRenderSurface({
      turnItems: [{
        id: "item-1-rev-1",
        itemId: "item-1",
        sessionId: "session-1",
        turnId: "turn-1",
        version: 3,
        revision: 1,
        sequence: 1,
        type: "reasoning",
        status: "running",
        terminal: false,
        // Persisted legacy frames can omit text while the item is still live.
      }] as unknown as SessionDetail["messages"][number]["turnItems"],
    });

    expect(surface.thoughtContent).toBe("");
    expect(surface.codexTranscript.cells).toEqual([]);
  });

  it("treats only strictly lower ledger seq as stale", () => {
    expect(isStaleLedgerUpdate(5, 4)).toBe(true);
    expect(isStaleLedgerUpdate(5, 5)).toBe(false);
    expect(isStaleLedgerUpdate(5, 6)).toBe(false);
    expect(isStaleLedgerUpdate(0, 1)).toBe(false);
  });
  it("builds an empty detail shell from summary for optimistic switches", () => {
    const summary = {
      id: "s2",
      title: "Hello",
      status: "idle",
      currentPhase: "ready",
    } as SessionSummary;
    const shell = buildSessionDetailShellFromSummary(summary);
    expect(shell?.id).toBe("s2");
    expect(shell?.title).toBe("Hello");
    expect(shell?.messages).toEqual([]);
    expect(shell?.provisionalTranscript).toBe(true);
    expect(isProvisionalSessionTranscript(shell)).toBe(true);
    expect(shell?.messageWindow?.hasEarlier).toBe(false);
  });

  it("treats provisional shells as transcript-pending instead of empty-session hard loading", () => {
    const provisional = buildSessionDetailShellFromSummary({
      id: "s2",
      title: "Hello",
      status: "idle",
      currentPhase: "ready",
    } as SessionSummary);
    expect(
      isSessionDetailHardLoading({
        activeSessionId: "s2",
        detail: provisional,
        isFetching: true,
      }),
    ).toBe(false);
    expect(
      shouldShowSessionTranscriptPending({
        activeSessionId: "s2",
        detail: provisional,
        isFetching: true,
      }),
    ).toBe(true);
    expect(
      shouldShowSessionTranscriptPending({
        activeSessionId: "s2",
        detail: { id: "s2", messages: [], provisionalTranscript: false } as SessionDetail,
        isFetching: false,
      }),
    ).toBe(false);
    expect(
      shouldShowSessionTranscriptPending({
        activeSessionId: "s2",
        detail: undefined,
        isFetching: true,
      }),
    ).toBe(true);
  });

  it("prefers cached detail over summary shell and rejects foreign sessions", () => {
    const cached = { id: "s2", title: "Cached", messages: [{ id: "m" }] } as SessionDetail;
    const summary = { id: "s2", title: "Summary" } as SessionSummary;
    expect(
      resolveSessionDetailPlaceholder({
        activeSessionId: "s2",
        cachedDetail: cached,
        summary,
      })?.title,
    ).toBe("Cached");
    expect(
      resolveSessionDetailPlaceholder({
        activeSessionId: "s2",
        cachedDetail: { id: "other", title: "Nope" } as SessionDetail,
        summary,
      })?.title,
    ).toBe("Summary");
    expect(
      resolveSessionDetailPlaceholder({
        activeSessionId: "s2",
        cachedDetail: undefined,
        summary: { id: "other", title: "Nope" } as SessionSummary,
      }),
    ).toBeUndefined();
  });

  it("passes includeSecondary=false for light session detail polls", async () => {
    const spy = vi.spyOn(client, "fetchJson").mockResolvedValue({ id: "s1" } as SessionDetail);
    await fetchSessionDetailWindow("s1", { includeSecondary: false });
    expect(spy).toHaveBeenCalled();
    const url = String(spy.mock.calls[0]?.[0] || "");
    expect(url).toContain("includeSecondary=false");
    spy.mockRestore();
  });

  it("detects foreign session detail query keys for cancel-on-switch", () => {
    expect(isForeignSessionDetailQueryKey(["sessions", "old"], "new")).toBe(true);
    expect(isForeignSessionDetailQueryKey(["sessions", "new"], "new")).toBe(false);
    expect(isForeignSessionDetailQueryKey(["sessions", "new", "child-sessions"], "new")).toBe(false);
    expect(isForeignSessionDetailQueryKey(["sessions", "none"], "new")).toBe(false);
  });

  it("resolves neighbor session ids for idle prefetch without the active session", () => {
    expect(
      resolveNeighborSessionIdsForPrefetch({
        sessions: [{ id: "a" }, { id: "b" }, { id: "c" }, { id: "d" }],
        activeSessionId: "b",
        limit: 2,
      }),
    ).toEqual(["a", "c"]);
    expect(
      resolveNeighborSessionIdsForPrefetch({
        sessions: [{ id: "a" }],
        activeSessionId: "a",
      }),
    ).toEqual([]);
  });
});
