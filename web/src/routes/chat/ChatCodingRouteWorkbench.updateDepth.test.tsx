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
import { QueryClient, QueryClientProvider, type Query } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../../api/queryKeys";
import type { SessionDetail, SessionSummary, SessionToolApprovalRequest } from "../../api/types";
import {
  clearSessionDetailPaintCacheForTests,
  rememberSessionDetailPaint,
  resolveStickySessionDetailPaint,
} from "./chatSessionPaintCache";
import {
  sessionDetailStructuralSharing,
  useSessionToolApprovalsQuery,
  useSessionToolApprovalsRefetchInterval,
  useStableSessionDetailPaint,
  useStableSessionDetailPlaceholder,
  type SessionToolApprovalPollingInput,
  type SessionToolApprovalsQueryOptions,
} from "./ChatCodingRouteWorkbench";

// happy-dom needs an explicit act environment; without it act() only warns.
// Repo pattern: (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// vi.mock factories are hoisted above imports; vi.hoisted guarantees the mock
// binding exists before the factory is first invoked.
const { fetchJsonMock } = vi.hoisted(() => ({
  fetchJsonMock: vi.fn(),
}));

vi.mock("../../api/client", () => ({
  fetchJson: (...args: unknown[]) => fetchJsonMock(...args),
}));

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

type PaintInput = {
  activeSessionId: string | null;
  detail: SessionDetail | undefined;
};

let snapshots: Array<{ placeholder: SessionDetail | undefined }> = [];
let intervalSnapshots: Array<{ refetchInterval: RefetchIntervalResolver }> = [];
let paintSnapshots: Array<{ detail: SessionDetail | undefined }> = [];
let approvalSnapshots: Array<ReturnType<typeof useSessionToolApprovalsQuery>> = [];
let approvalQueryClient: QueryClient;

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

function PaintHost({ input }: { input: PaintInput }) {
  const detail = useStableSessionDetailPaint(input);
  paintSnapshots.push({ detail });
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

function mountPaint(input: PaintInput) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root!.render(React.createElement(PaintHost, { input }));
  });
}

function rerenderPaint(input: PaintInput) {
  act(() => {
    root!.render(React.createElement(PaintHost, { input }));
  });
}

function stickyDetailFor(id: string, count: number): SessionDetail {
  return {
    id,
    title: id,
    messages: Array.from({ length: count }, (_, index) => ({
      id: `${id}-m${index}`,
      role: index % 2 === 0 ? "assistant" : "user",
      content: `message ${index}`,
      timestamp: "2026-08-15T10:00:00Z",
    })),
    messageWindow: {
      mode: "window",
      totalMessages: count,
      returnedMessages: count,
      oldestMessageIndex: 0,
      newestMessageIndex: count - 1,
      hasEarlier: false,
      hasLater: false,
      transcriptScope: "window",
    },
    provisionalTranscript: undefined,
  } as SessionDetail;
}

function intervalFor(
  snapshot: { refetchInterval: RefetchIntervalResolver },
  data: SessionToolApprovalRequest[] | undefined,
): number | false {
  return snapshot.refetchInterval({
    state: { data },
  } as unknown as Query<SessionToolApprovalRequest[]>);
}

const pendingApproval: SessionToolApprovalRequest = {
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

const idlePollingInput: SessionToolApprovalPollingInput = {
  directSessionPanelActive: true,
  runtimeActive: false,
  detailCurrentPhase: "ready",
  summaryCurrentPhase: "ready",
  summaryStatus: "idle",
};

function approvalsOptions(
  sessionId: string | null | undefined,
  overrides: Partial<SessionToolApprovalsQueryOptions> = {},
): SessionToolApprovalsQueryOptions {
  return {
    sessionId,
    enabled: Boolean(sessionId),
    polling: idlePollingInput,
    ...overrides,
  };
}

function ApprovalHost({ options }: { options: SessionToolApprovalsQueryOptions }) {
  approvalSnapshots.push(useSessionToolApprovalsQuery(options));
  return null;
}

function mountApprovals(options: SessionToolApprovalsQueryOptions) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root!.render(
      React.createElement(
        QueryClientProvider,
        { client: approvalQueryClient },
        React.createElement(ApprovalHost, { options }),
      ),
    );
  });
}

function rerenderApprovals(options: SessionToolApprovalsQueryOptions) {
  act(() => {
    root!.render(
      React.createElement(
        QueryClientProvider,
        { client: approvalQueryClient },
        React.createElement(ApprovalHost, { options }),
      ),
    );
  });
}

async function flushApprovals() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    vi.advanceTimersByTime(0);
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function advanceApprovals(ms: number) {
  await act(async () => {
    vi.advanceTimersByTime(ms);
    await Promise.resolve();
    await Promise.resolve();
  });
}

beforeEach(() => {
  clearSessionDetailPaintCacheForTests();
  paintSnapshots = [];
  fetchJsonMock.mockReset();
  approvalQueryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
});

afterEach(() => {
  act(() => {
    root?.unmount();
  });
  root = null;
  container?.remove();
  snapshots = [];
  intervalSnapshots = [];
  paintSnapshots = [];
  approvalSnapshots = [];
  vi.useRealTimers();
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

describe("useStableSessionDetailPaint sticky-paint stability", () => {
  it("reproduces the pre-fix churn where resolveStickySessionDetailPaint rebuilds detail/messages references for identical inputs", () => {
    rememberSessionDetailPaint(stickyDetailFor("s1", 4));
    const live = stickyDetailFor("s1", 2);

    const first = resolveStickySessionDetailPaint({ activeSessionId: "s1", detail: live });
    const second = resolveStickySessionDetailPaint({ activeSessionId: "s1", detail: live });

    expect(first).toBeDefined();
    // Pre-fix: the merged sticky+live paint is rebuilt on every call, so a no-op
    // parent rerender hands downstream effects a brand-new detail/messages pair
    // and the token-speed effect re-fires setTokenSpeedTracker endlessly.
    expect(second).not.toBe(first);
    expect(second?.messages).not.toBe(first?.messages);
  });

  it("keeps a stable sticky paint detail/messages reference across no-op parent rerenders", () => {
    rememberSessionDetailPaint(stickyDetailFor("s1", 4));
    const input: PaintInput = { activeSessionId: "s1", detail: stickyDetailFor("s1", 2) };
    mountPaint(input);
    const first = paintSnapshots.at(-1)!;
    expect(first.detail).toBeDefined();
    // Sticky transcript is folded into the paint while the live window hydrates.
    expect(first.detail?.messages?.length).toBeGreaterThanOrEqual(4);

    // Same logical inputs behind a fresh props object: the no-op parent rerender
    // that previously handed downstream effects a fresh detail/messages pair.
    rerenderPaint({ ...input });
    expect(paintSnapshots.at(-1)!.detail).toBe(first.detail);
    expect(paintSnapshots.at(-1)!.detail?.messages).toBe(first.detail?.messages);
    rerenderPaint({ ...input });
    expect(paintSnapshots.at(-1)!.detail).toBe(first.detail);
    expect(paintSnapshots.at(-1)!.detail?.messages).toBe(first.detail?.messages);
    rerenderPaint({ ...input });
    expect(paintSnapshots.at(-1)!.detail).toBe(first.detail);
    expect(paintSnapshots.at(-1)!.detail?.messages).toBe(first.detail?.messages);
  });

  it("recomputes the sticky paint when the raw session detail reference changes", () => {
    rememberSessionDetailPaint(stickyDetailFor("s1", 4));
    mountPaint({ activeSessionId: "s1", detail: stickyDetailFor("s1", 2) });
    const first = paintSnapshots.at(-1)!.detail;

    // A genuinely new live window (new reference) must re-resolve the paint.
    rerenderPaint({ activeSessionId: "s1", detail: stickyDetailFor("s1", 3) });
    const second = paintSnapshots.at(-1)!.detail;
    expect(second).not.toBe(first);
    // Sticky semantics preserved: the richer sticky history survives the merge.
    expect(second?.messages?.length).toBeGreaterThanOrEqual(4);
    expect(second?.messages?.some((message) => message.id === "s1-m3")).toBe(true);
  });

  it("recomputes the sticky paint when the active session id changes", () => {
    rememberSessionDetailPaint(stickyDetailFor("s1", 4));
    rememberSessionDetailPaint(stickyDetailFor("s2", 1));
    mountPaint({ activeSessionId: "s1", detail: stickyDetailFor("s1", 2) });
    const first = paintSnapshots.at(-1)!.detail;

    rerenderPaint({ activeSessionId: "s2", detail: stickyDetailFor("s2", 1) });
    const second = paintSnapshots.at(-1)!.detail;
    expect(second).not.toBe(first);
    expect(second?.id).toBe("s2");
    expect(second?.messages?.length).toBeGreaterThanOrEqual(1);
  });
});

describe("sessionToolApprovals real QueryClient observer seam", () => {
  it("fetches the pending approvals endpoint exactly once for an empty first result", async () => {
    vi.useFakeTimers();
    fetchJsonMock.mockImplementation((url: string) => {
      expect(url).toContain("/api/sessions/s1/tool-approvals?status=pending");
      return Promise.resolve([]);
    });

    mountApprovals(approvalsOptions("s1"));
    await flushApprovals();

    expect(fetchJsonMock).toHaveBeenCalledTimes(1);
    expect(approvalSnapshots.at(-1)?.data).toEqual([]);
  });

  it("does not refetch on no-op parent rerenders with identical sessionId and polling inputs", async () => {
    vi.useFakeTimers();
    fetchJsonMock.mockResolvedValue([]);
    const options = approvalsOptions("s1");

    mountApprovals(options);
    await flushApprovals();
    expect(fetchJsonMock).toHaveBeenCalledTimes(1);

    // Same logical inputs behind fresh props objects: the no-op parent rerender
    // that previously handed React Query a fresh queryFn/observer config must
    // not trigger another fetch or an update loop.
    rerenderApprovals({ ...options });
    rerenderApprovals({ ...options });
    rerenderApprovals({ ...options });
    await flushApprovals();
    expect(fetchJsonMock).toHaveBeenCalledTimes(1);
    expect(approvalSnapshots.length).toBeGreaterThan(1);
  });

  it("polls idle empty data exactly once at 4000ms and not a moment sooner", async () => {
    vi.useFakeTimers();
    fetchJsonMock.mockResolvedValue([]);

    mountApprovals(approvalsOptions("s1"));
    await flushApprovals();
    expect(fetchJsonMock).toHaveBeenCalledTimes(1);

    // 3999ms: idle interval (4000ms) must not have fired yet.
    await advanceApprovals(3999);
    expect(fetchJsonMock).toHaveBeenCalledTimes(1);

    // 4000ms total: exactly one more poll.
    await advanceApprovals(1);
    expect(fetchJsonMock).toHaveBeenCalledTimes(2);
  });

  it("polls busy empty data every 2000ms", async () => {
    vi.useFakeTimers();
    fetchJsonMock.mockResolvedValue([]);

    mountApprovals(
      approvalsOptions("s1", {
        polling: { ...idlePollingInput, runtimeActive: true },
      }),
    );
    await flushApprovals();
    expect(fetchJsonMock).toHaveBeenCalledTimes(1);

    await advanceApprovals(1999);
    expect(fetchJsonMock).toHaveBeenCalledTimes(1);

    await advanceApprovals(1);
    expect(fetchJsonMock).toHaveBeenCalledTimes(2);
  });

  it("polls pending approvals every 750ms", async () => {
    vi.useFakeTimers();
    fetchJsonMock.mockResolvedValue([pendingApproval]);

    mountApprovals(approvalsOptions("s1"));
    await flushApprovals();
    expect(fetchJsonMock).toHaveBeenCalledTimes(1);

    await advanceApprovals(749);
    expect(fetchJsonMock).toHaveBeenCalledTimes(1);

    await advanceApprovals(1);
    expect(fetchJsonMock).toHaveBeenCalledTimes(2);
  });

  it("disables polling entirely when the direct session panel is inactive", async () => {
    vi.useFakeTimers();
    fetchJsonMock.mockResolvedValue([pendingApproval]);

    mountApprovals(
      approvalsOptions("s1", {
        polling: { ...idlePollingInput, directSessionPanelActive: false },
      }),
    );
    await flushApprovals();
    expect(fetchJsonMock).toHaveBeenCalledTimes(1);

    await advanceApprovals(100_000);
    expect(fetchJsonMock).toHaveBeenCalledTimes(1);
  });

  it("switching sessionId re-keys the observer and only fetches the new session", async () => {
    vi.useFakeTimers();
    fetchJsonMock.mockImplementation((url: string) => Promise.resolve([]));

    mountApprovals(approvalsOptions("s1"));
    await flushApprovals();
    expect(fetchJsonMock).toHaveBeenCalledTimes(1);
    expect(String(fetchJsonMock.mock.calls[0][0])).toContain("/api/sessions/s1/tool-approvals");
    expect(approvalQueryClient.getQueryData(queryKeys.sessionToolApprovals("s1"))).toEqual([]);

    rerenderApprovals(approvalsOptions("s2"));
    await flushApprovals();
    expect(fetchJsonMock).toHaveBeenCalledTimes(2);
    expect(String(fetchJsonMock.mock.calls[1][0])).toContain("/api/sessions/s2/tool-approvals");
    expect(approvalQueryClient.getQueryData(queryKeys.sessionToolApprovals("s2"))).toEqual([]);
    expect(approvalSnapshots.at(-1)?.data).toEqual([]);

    // The old session's observer is gone; every further poll targets s2 only.
    await advanceApprovals(4000);
    const afterSwitchCalls = fetchJsonMock.mock.calls
      .slice(1)
      .map((call) => String(call[0]));
    expect(afterSwitchCalls.length).toBeGreaterThan(1);
    expect(
      afterSwitchCalls.every((url) => url.includes("/api/sessions/s2/tool-approvals")),
    ).toBe(true);
  });
});
