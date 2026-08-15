// @vitest-environment happy-dom
/**
 * Deterministic regression for the session-switch "Maximum update depth
 * exceeded" loop in ChatCodingRouteWorkbench.
 *
 * The active session detail query derives its placeholder from
 * `resolveSessionDetailPlaceholder` while the real detail fetch is still
 * unresolved. The previous implementation passed an inline
 * `placeholderData` callback that rebuilt that shell on every render, so a
 * no-op parent rerender handed React Query a fresh placeholder reference
 * each time and the observer snapshot churned until React bailed out with
 * "Maximum update depth exceeded" inside `forceStoreRerender`.
 *
 * `useStableSessionDetailPlaceholder` is the memoized seam: identical
 * `activeSessionId` / cached detail / summary inputs must return the same
 * placeholder reference across unrelated rerenders, and the placeholder may
 * only change when one of those inputs actually changes. This test mounts
 * only that hook.
 *
 * The pending tool-approvals poll uses the same pattern: the inline
 * `refetchInterval` closure rebuilt on every render and reset the 2s timer in
 * lockstep with `forceStoreRerender`. `useSessionToolApprovalsRefetchInterval`
 * is the `useCallback` seam: its reference must stay identical across
 * unrelated rerenders, recompute only when polling inputs change, and return
 * exactly 750ms pending / 2000ms busy / 4000ms idle / false when the panel is
 * inactive.
 */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import type { Query } from "@tanstack/react-query";
import { afterEach, describe, expect, it } from "vitest";

import type { SessionDetail, SessionSummary, SessionToolApprovalRequest } from "../../api/types";
import {
  sessionDetailStructuralSharing,
  useSessionToolApprovalsRefetchInterval,
  useStableSessionDetailPlaceholder,
} from "./ChatCodingRouteWorkbench";

type PlaceholderInput = {
  activeSessionId: string | null;
  cachedDetail: SessionDetail | undefined;
  summary: SessionSummary | null | undefined;
};

type RefetchIntervalInput = {
  directSessionPanelActive: boolean;
  runtimeActive: boolean;
  detailCurrentPhase: string | undefined;
  summaryCurrentPhase: string | undefined;
  summaryStatus: string | undefined;
};

type RefetchIntervalResolver = ReturnType<typeof useSessionToolApprovalsRefetchInterval>;

let snapshots: Array<{ placeholder: SessionDetail | undefined }> = [];
let intervalSnapshots: Array<{ refetchInterval: RefetchIntervalResolver }> = [];

function Host({ input }: { input: PlaceholderInput }) {
  const placeholder = useStableSessionDetailPlaceholder(input);
  snapshots.push({ placeholder });
  return null;
}

function IntervalHost({ input }: { input: RefetchIntervalInput }) {
  const refetchInterval = useSessionToolApprovalsRefetchInterval(input);
  intervalSnapshots.push({ refetchInterval });
  return null;
}

let root: Root | null = null;
let container: HTMLElement;

function summaryFor(id: string, title: string): SessionSummary {
  return {
    id,
    title,
    agentId: "agent-1",
    agentDisplayName: "Agent",
    status: "idle",
    currentPhase: "ready",
    taskSummary: "",
    lastActive: "",
    updatedAt: "",
  };
}

function mount(input: PlaceholderInput) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root!.render(React.createElement(Host, { input }));
  });
}

function rerender(input: PlaceholderInput) {
  act(() => {
    root!.render(React.createElement(Host, { input }));
  });
}

function mountInterval(input: RefetchIntervalInput) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root!.render(React.createElement(IntervalHost, { input }));
  });
}

function rerenderInterval(input: RefetchIntervalInput) {
  act(() => {
    root!.render(React.createElement(IntervalHost, { input }));
  });
}

function intervalFor(
  snapshot: { refetchInterval: RefetchIntervalResolver },
  data: SessionToolApprovalRequest[] | undefined,
): number | false {
  return snapshot.refetchInterval({
    state: { data },
  } as unknown as Query<SessionToolApprovalRequest[]>);
}

afterEach(() => {
  act(() => {
    root?.unmount();
  });
  root = null;
  container?.remove();
  snapshots = [];
  intervalSnapshots = [];
});

describe("ChatCodingRouteWorkbench update-depth regression", () => {
  it("keeps a stable placeholder reference across no-op parent rerenders while the detail query is unresolved", () => {
    const input = {
      activeSessionId: "s1",
      cachedDetail: undefined,
      summary: summaryFor("s1", "Session A"),
    };
    mount(input);
    const first = snapshots.at(-1)!;
    // Summary shell paints a provisional transcript while the fetch is pending.
    expect(first.placeholder).toBeDefined();
    expect(first.placeholder?.id).toBe("s1");
    expect(first.placeholder?.provisionalTranscript).toBe(true);

    // Same logical inputs behind a fresh props object: the no-op parent
    // rerender that previously handed React Query a brand-new shell.
    rerender({ ...input });
    expect(snapshots.at(-1)!.placeholder).toBe(first.placeholder);
    rerender({ ...input });
    expect(snapshots.at(-1)!.placeholder).toBe(first.placeholder);
    rerender({ ...input });
    expect(snapshots.at(-1)!.placeholder).toBe(first.placeholder);
  });

  it("recomputes the placeholder when activeSessionId changes", () => {
    mount({
      activeSessionId: "s1",
      cachedDetail: undefined,
      summary: summaryFor("s1", "Session A"),
    });
    const first = snapshots.at(-1)!.placeholder;

    rerender({
      activeSessionId: "s2",
      cachedDetail: undefined,
      summary: summaryFor("s2", "Session B"),
    });
    const second = snapshots.at(-1)!.placeholder;
    expect(second).not.toBe(first);
    expect(second?.id).toBe("s2");
    expect(second?.title).toBe("Session B");
  });

  it("recomputes the placeholder when the summary source changes for the same session", () => {
    mount({
      activeSessionId: "s1",
      cachedDetail: undefined,
      summary: summaryFor("s1", "Session A"),
    });
    const first = snapshots.at(-1)!.placeholder;

    rerender({
      activeSessionId: "s1",
      cachedDetail: undefined,
      summary: summaryFor("s1", "Session A renamed"),
    });
    const second = snapshots.at(-1)!.placeholder;
    expect(second).not.toBe(first);
    expect(second?.title).toBe("Session A renamed");
  });

  it("merges previous/next session detail windows through the stable structural-sharing function", () => {
    const previous = {
      id: "s1",
      title: "Session A",
      messages: [5, 6, 7, 8].map((index) => ({
        id: `s1-message-${index}`,
        role: index % 2 === 0 ? "assistant" : "user",
        content: `message ${index}`,
        timestamp: "2026-08-15T10:00:00Z",
      })),
      messageWindow: {
        mode: "window",
        totalMessages: 8,
        returnedMessages: 4,
        oldestMessageIndex: 5,
        newestMessageIndex: 8,
        hasEarlier: true,
        hasLater: false,
        nextBeforeMessageIndex: 5,
        transcriptScope: "window",
      },
    } as unknown as SessionDetail;
    const next = {
      id: "s1",
      title: "Session A",
      messages: [3, 4].map((index) => ({
        id: `s1-message-${index}`,
        role: index % 2 === 0 ? "assistant" : "user",
        content: `message ${index}`,
        timestamp: "2026-08-15T09:00:00Z",
      })),
      messageWindow: {
        mode: "window",
        totalMessages: 8,
        returnedMessages: 2,
        oldestMessageIndex: 3,
        newestMessageIndex: 4,
        hasEarlier: true,
        hasLater: true,
        nextBeforeMessageIndex: 3,
        transcriptScope: "window",
      },
    } as unknown as SessionDetail;

    const merged = sessionDetailStructuralSharing(previous, next);

    expect(merged.messages.map((message) => message.content)).toEqual([
      "message 3",
      "message 4",
      "message 5",
      "message 6",
      "message 7",
      "message 8",
    ]);
    expect(merged.messageWindow).toMatchObject({
      totalMessages: 8,
      returnedMessages: 6,
      oldestMessageIndex: 3,
      newestMessageIndex: 8,
      hasEarlier: true,
      hasLater: false,
      nextBeforeMessageIndex: 3,
    });
  });

  it("prefers the cached detail and keeps its reference stable", () => {
    const cached = { id: "s1", title: "Cached detail", messages: [] } as SessionDetail;
    const input = {
      activeSessionId: "s1",
      cachedDetail: cached,
      summary: summaryFor("s1", "Session A"),
    };
    mount(input);
    expect(snapshots.at(-1)!.placeholder).toBe(cached);

    // A summary-only change must not replace the cached detail placeholder.
    rerender({
      activeSessionId: "s1",
      cachedDetail: cached,
      summary: summaryFor("s1", "Session A renamed"),
    });
    expect(snapshots.at(-1)!.placeholder).toBe(cached);
  });
});

describe("sessionToolApprovals refetchInterval stability", () => {
  const idleInput: RefetchIntervalInput = {
    directSessionPanelActive: true,
    runtimeActive: false,
    detailCurrentPhase: "ready",
    summaryCurrentPhase: "ready",
    summaryStatus: "idle",
  };
  const pendingApproval = {
    requestId: "r1",
    sessionId: "s1",
    turnId: "t1",
    agentId: "agent-1",
    callId: "c1",
    toolName: "read",
    approval: "required",
    risk: "low",
    argumentsHash: "h",
    argumentSummary: {},
    sessionGrantScope: {},
    decisionFingerprint: "fp",
    configRevision: 0,
    configHash: "cfg",
    permissionPreset: "default",
    availableDecisions: ["accept", "decline"],
    createdAt: "2026-08-15T10:00:00Z",
    status: "pending",
    decision: null,
    resolvedAt: null,
  } as SessionToolApprovalRequest;

  it("keeps a stable refetchInterval across unrelated rerenders with exact false/750/2000/4000 timing", () => {
    mountInterval(idleInput);
    const first = intervalSnapshots.at(-1)!;

    // Same logical inputs behind a fresh props object: the no-op parent
    // rerender that previously handed React Query a brand-new closure.
    rerenderInterval({ ...idleInput });
    expect(intervalSnapshots.at(-1)!.refetchInterval).toBe(first.refetchInterval);
    rerenderInterval({ ...idleInput });
    expect(intervalSnapshots.at(-1)!.refetchInterval).toBe(first.refetchInterval);

    // Idle (panel active, no pending, not busy) polls every 4s.
    expect(intervalFor(first, [])).toBe(4_000);

    // A busy input recomputes the callback and returns 2s.
    rerenderInterval({ ...idleInput, runtimeActive: true });
    const busy = intervalSnapshots.at(-1)!;
    expect(busy.refetchInterval).not.toBe(first.refetchInterval);
    expect(intervalFor(busy, undefined)).toBe(2_000);

    // Pending approvals poll every 750ms, busy or not.
    expect(intervalFor(busy, [pendingApproval])).toBe(750);

    // Panel inactive disables polling entirely.
    rerenderInterval({ ...idleInput, directSessionPanelActive: false, runtimeActive: true });
    const inactive = intervalSnapshots.at(-1)!;
    expect(inactive.refetchInterval).not.toBe(busy.refetchInterval);
    expect(intervalFor(inactive, [pendingApproval])).toBe(false);
    expect(intervalFor(inactive, undefined)).toBe(false);
  });
});
