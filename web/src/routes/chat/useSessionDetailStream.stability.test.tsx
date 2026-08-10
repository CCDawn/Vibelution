// @vitest-environment happy-dom
/**
 * Behavior contract for direct-session stream lifecycle stability (perf root cause:
 * shouldConnect flapping on route settling must not close/reopen the EventSource
 * and must not trigger authoritative session detail refreshes).
 */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../../api/queryKeys";
import { SESSION_STREAM_ROUTE_SWITCH_GRACE_MS } from "./chatSessionStreamConnect";
import {
  useSessionDetailStream,
  type UseSessionDetailStreamOptions,
} from "./useSessionDetailStream";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  static reset() {
    FakeEventSource.instances = [];
  }

  readonly listeners = new Map<string, Set<(event: { data: string }) => void>>();
  closed = false;
  readyState = 1;
  onopen: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, callback: (event: { data: string }) => void) {
    if (!this.listeners.has(type)) {
      this.listeners.set(type, new Set());
    }
    this.listeners.get(type)!.add(callback);
  }

  removeEventListener(type: string, callback: (event: { data: string }) => void) {
    this.listeners.get(type)?.delete(callback);
  }

  close() {
    this.closed = true;
    this.readyState = 2;
  }

  open() {
    this.readyState = 1;
    this.onopen?.(new Event("open"));
  }

  fail() {
    this.onerror?.(new Event("error"));
  }
}

let hookResults: { sessionStreamConnected: boolean }[] = [];

function Host({ props }: { props: UseSessionDetailStreamOptions }) {
  hookResults.push(useSessionDetailStream(props));
  return null;
}

function baseOptions(overrides: Partial<UseSessionDetailStreamOptions> = {}): {
  options: UseSessionDetailStreamOptions;
  queryClient: QueryClient;
  invalidateSpy: ReturnType<typeof vi.spyOn>;
  decisionSnapshotRef: { current: SessionStreamDecisionSnapshotShape };
} {
  const queryClient = new QueryClient();
  const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
  const decisionSnapshotRef = {
    current: {
      sessionId: String(overrides.activeSessionId ?? "s1"),
      shouldConnect: overrides.sessionStreamShouldConnect ?? true,
      pageVisible: true,
      chatStartupWarmupActive: false,
      chatPollingVisible: true,
      directSessionBackgroundSyncActive: false,
      routeTargetMatches: true,
      routeSettling: false,
      routeSwitchGraceActive: false,
      routeSwitchGraceMsRemaining: 0,
    },
  };
  const options: UseSessionDetailStreamOptions = {
    activeSessionId: "s1",
    sessionStreamShouldConnect: true,
    queryClient,
    syncSessionDetail: vi.fn(),
    setActiveTurnLayersBySession: vi.fn(),
    activeTurnLayersBySessionRef: { current: {} },
    lastAssistantDeltaAppliedAtRef: { current: {} },
    sessionStreamDecisionSnapshotRef: decisionSnapshotRef as never,
    desktopConversationNotifierRef: {
      current: { handleSessionDetail: vi.fn(), handleAssistantDelta: vi.fn() },
    },
    sessionTitleForNotifications: "title",
    ...overrides,
  };
  return { options, queryClient, invalidateSpy, decisionSnapshotRef };
}

type SessionStreamDecisionSnapshotShape = {
  sessionId: string;
  shouldConnect: boolean;
  pageVisible: boolean;
  chatStartupWarmupActive: boolean;
  chatPollingVisible: boolean;
  directSessionBackgroundSyncActive: boolean;
  routeTargetMatches: boolean;
  routeSettling: boolean;
  routeSwitchGraceActive: boolean;
  routeSwitchGraceMsRemaining: number;
};

function mount(options: UseSessionDetailStreamOptions): Root {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(<Host props={options} />);
  });
  return root;
}

function rerender(root: Root, options: UseSessionDetailStreamOptions) {
  act(() => {
    root.render(<Host props={options} />);
  });
}

function unmount(root: Root) {
  act(() => {
    root.unmount();
  });
  document.body.textContent = "";
}

describe("useSessionDetailStream stream lifecycle stability", () => {
  beforeEach(() => {
    FakeEventSource.reset();
    hookResults = [];
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("keeps the open stream across shouldConnect flapping on the same session", () => {
    const { options, decisionSnapshotRef } = baseOptions({});
    const root = mount(options);
    expect(FakeEventSource.instances).toHaveLength(1);
    act(() => {
      FakeEventSource.instances[0].open();
    });
    expect(hookResults.at(-1)?.sessionStreamConnected).toBe(true);

    decisionSnapshotRef.current = { ...decisionSnapshotRef.current, shouldConnect: false };
    rerender(root, { ...options, sessionStreamShouldConnect: false });
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0].closed).toBe(false);
    expect(hookResults.at(-1)?.sessionStreamConnected).toBe(true);

    decisionSnapshotRef.current = { ...decisionSnapshotRef.current, shouldConnect: true };
    rerender(root, { ...options, sessionStreamShouldConnect: true });
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0].closed).toBe(false);
    unmount(root);
  });

  it("closes the stream only after grace when shouldConnect stays false", () => {
    vi.useFakeTimers();
    const { options, decisionSnapshotRef } = baseOptions({});
    const root = mount(options);
    act(() => {
      FakeEventSource.instances[0].open();
    });

    decisionSnapshotRef.current = { ...decisionSnapshotRef.current, shouldConnect: false };
    rerender(root, { ...options, sessionStreamShouldConnect: false });
    expect(FakeEventSource.instances[0].closed).toBe(false);

    act(() => {
      vi.advanceTimersByTime(SESSION_STREAM_ROUTE_SWITCH_GRACE_MS + 1_500);
    });
    expect(FakeEventSource.instances[0].closed).toBe(true);
    unmount(root);
  });

  it("reopens a fresh stream after a grace close when shouldConnect recovers", () => {
    vi.useFakeTimers();
    const { options, decisionSnapshotRef } = baseOptions({});
    const root = mount(options);
    act(() => {
      FakeEventSource.instances[0].open();
    });

    decisionSnapshotRef.current = { ...decisionSnapshotRef.current, shouldConnect: false };
    rerender(root, { ...options, sessionStreamShouldConnect: false });
    act(() => {
      vi.advanceTimersByTime(SESSION_STREAM_ROUTE_SWITCH_GRACE_MS + 1_500);
    });
    expect(FakeEventSource.instances[0].closed).toBe(true);

    decisionSnapshotRef.current = { ...decisionSnapshotRef.current, shouldConnect: true };
    rerender(root, { ...options, sessionStreamShouldConnect: true });
    expect(FakeEventSource.instances).toHaveLength(2);
    expect(FakeEventSource.instances[1].closed).toBe(false);
    unmount(root);
  });

  it("does not invalidate the session on lifecycle cleanup but does on stream error", () => {
    const { options, invalidateSpy } = baseOptions({ activeSessionId: "s1" });
    const root = mount(options);
    act(() => {
      FakeEventSource.instances[0].open();
    });

    const switchOptions = {
      ...options,
      activeSessionId: "s2",
    } as UseSessionDetailStreamOptions;
    rerender(root, switchOptions);
    expect(invalidateSpy).not.toHaveBeenCalled();

    expect(FakeEventSource.instances).toHaveLength(2);
    act(() => {
      FakeEventSource.instances[1].fail();
    });
    expect(invalidateSpy).toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: queryKeys.session("s2") }),
    );
    unmount(root);
  });
});
