// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../../api/queryKeys";
import { disposeSessionStreams } from "./sessionStreamWarmRegistry";
import {
  useSessionDetailStream,
  type UseSessionDetailStreamOptions,
} from "./useSessionDetailStream";

vi.mock("../../app/browserTelemetry", () => ({
  collectBrowserPageSnapshot: () => ({}),
  postBrowserTelemetry: vi.fn(),
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

class FakeEventSource {
  readonly listeners = new Map<string, Set<(event: { data: string }) => void>>();
  readyState = 1;
  closed = false;
  onopen: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  addEventListener(type: string, callback: (event: { data: string }) => void) {
    const listeners = this.listeners.get(type) ?? new Set();
    listeners.add(callback);
    this.listeners.set(type, listeners);
  }

  removeEventListener(type: string, callback: (event: { data: string }) => void) {
    this.listeners.get(type)?.delete(callback);
  }

  emit(type: string, data: unknown) {
    for (const listener of this.listeners.get(type) ?? []) {
      listener({ data: JSON.stringify(data) });
    }
  }

  close() {
    this.closed = true;
    this.readyState = 2;
  }
}

function Host({ props }: { props: UseSessionDetailStreamOptions }) {
  useSessionDetailStream(props);
  return null;
}

function baseOptions(shouldConnect: boolean) {
  const queryClient = new QueryClient();
  const streams: FakeEventSource[] = [];
  const syncSessionDetail = vi.fn();
  const decisionSnapshotRef = {
    current: {
      sessionId: "s1",
      shouldConnect,
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
    sessionStreamShouldConnect: shouldConnect,
    queryClient,
    syncSessionDetail,
    setActiveTurnLayersBySession: vi.fn(),
    activeTurnLayersBySessionRef: { current: {} },
    lastAssistantDeltaAppliedAtRef: { current: {} },
    lastStreamActivityAppliedAtRef: { current: {} },
    sessionStreamDecisionSnapshotRef: decisionSnapshotRef as never,
    desktopConversationNotifierRef: {
      current: { handleSessionDetail: vi.fn(), handleAssistantDelta: vi.fn() },
    },
    createSessionEventStream: () => {
      const stream = new FakeEventSource();
      streams.push(stream);
      return stream as never;
    },
    sessionTitleForNotifications: "Session 1",
  };
  return { options, queryClient, streams, syncSessionDetail, decisionSnapshotRef };
}

function mount(options: UseSessionDetailStreamOptions): { root: Root; container: HTMLDivElement } {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(<Host props={options} />));
  return { root, container };
}

function unmount(root: Root, container: HTMLDivElement) {
  act(() => root.unmount());
  container.remove();
}

afterEach(() => {
  disposeSessionStreams();
  document.body.replaceChildren();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("useSessionDetailStream lifecycle recovery", () => {
  it("opens the stream when shouldConnect becomes true before any stream existed", () => {
    const { options, streams, decisionSnapshotRef } = baseOptions(false);
    const mounted = mount(options);
    expect(streams).toHaveLength(0);

    decisionSnapshotRef.current.shouldConnect = true;
    act(() => {
      mounted.root.render(<Host props={{ ...options, sessionStreamShouldConnect: true }} />);
    });

    expect(streams).toHaveLength(1);
    expect(streams[0].closed).toBe(false);
    unmount(mounted.root, mounted.container);
  });

  it.each(["replayed", "partial"] as const)(
    "refetches the authoritative session detail after a %s stream resume",
    (resume) => {
      const { options, queryClient, streams, syncSessionDetail } = baseOptions(true);
      const invalidate = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue(undefined);
      const mounted = mount(options);

      act(() => {
        streams[0].emit("stream_resume", {
          type: "stream_resume",
          sessionId: "s1",
          resume,
          fromSeq: 4,
          toSeq: 8,
          replayedCount: resume === "replayed" ? 4 : 0,
        });
      });

      expect(invalidate).toHaveBeenCalledTimes(1);
      expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.session("s1") });
      // Replayed journal events remain telemetry/cursor information. The
      // authoritative detail query supplies the conversation projection.
      expect(syncSessionDetail).not.toHaveBeenCalled();
      unmount(mounted.root, mounted.container);
    },
  );
});
