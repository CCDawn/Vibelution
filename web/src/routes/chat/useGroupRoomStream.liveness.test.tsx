// @vitest-environment happy-dom
/**
 * Liveness watchdog contract for the group room SSE stream: any frame
 * (including keep-alive comment frames, surfaced as onActivity) resets the
 * watchdog; silence past the threshold aborts the dead connection and hands
 * recovery back to the existing reconnect + polling fallback.
 */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useGroupRoomStream, type UseGroupRoomStreamOptions } from "./useGroupRoomStream";

type FakeConsumeOptions = {
  roomId: string;
  signal: AbortSignal;
  onOpen?: () => void;
  onActivity?: () => void;
  onFrame: (frame: { event: string; data: string }) => void;
};

type FakeConsumeCall = {
  options: FakeConsumeOptions;
  aborted: boolean;
};

const hoisted = vi.hoisted(() => ({
  consumeCalls: [] as FakeConsumeCall[],
  rejectCurrent: null as null | ((error: Error) => void),
}));

vi.mock("./chatRoomEventStream", () => ({
  consumeChatRoomEventStream: (options: FakeConsumeOptions) => {
    const entry: FakeConsumeCall = { options, aborted: false };
    options.signal.addEventListener("abort", () => {
      entry.aborted = true;
      const error = new Error("The operation was aborted.");
      error.name = "AbortError";
      hoisted.rejectCurrent?.(error);
    });
    hoisted.consumeCalls.push(entry);
    return new Promise<never>((_resolve, reject) => {
      hoisted.rejectCurrent = reject;
    });
  },
}));

vi.mock("../../app/browserTelemetry", () => ({
  postBrowserTelemetry: vi.fn(),
}));

let hookResults: { groupStreamConnected: boolean }[] = [];

function Host({ props }: { props: UseGroupRoomStreamOptions }) {
  hookResults.push(useGroupRoomStream(props));
  return null;
}

function baseOptions(overrides: Partial<UseGroupRoomStreamOptions> = {}): UseGroupRoomStreamOptions {
  return {
    activeGroupRoomId: "room-1",
    groupStreamShouldConnect: true,
    syncChatRoomDetail: vi.fn(),
    ...overrides,
  };
}

function mount(options: UseGroupRoomStreamOptions): Root {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(<Host props={options} />);
  });
  return root;
}

function unmount(root: Root) {
  act(() => {
    root.unmount();
  });
  document.body.textContent = "";
}

describe("useGroupRoomStream liveness watchdog", () => {
  beforeEach(() => {
    hoisted.consumeCalls.length = 0;
    hoisted.rejectCurrent = null;
    hookResults = [];
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("keeps the connection while keep-alive activity keeps feeding the watchdog", async () => {
    vi.useFakeTimers();
    const root = mount(baseOptions());
    expect(hoisted.consumeCalls).toHaveLength(1);
    const first = hoisted.consumeCalls[0];
    act(() => {
      first.options.onOpen?.();
    });
    expect(hookResults.at(-1)?.groupStreamConnected).toBe(true);

    // Three keep-alive periods (15s each): each frame must reset the watchdog.
    for (let period = 0; period < 3; period += 1) {
      await act(async () => {
        vi.advanceTimersByTime(15_000);
      });
      act(() => {
        first.options.onActivity?.();
      });
    }
    expect(first.aborted).toBe(false);
    expect(hoisted.consumeCalls).toHaveLength(1);
    expect(hookResults.at(-1)?.groupStreamConnected).toBe(true);
    unmount(root);
  });

  it("aborts a silent half-open connection and schedules the reconnect fallback", async () => {
    vi.useFakeTimers();
    const root = mount(baseOptions());
    const first = hoisted.consumeCalls[0];
    act(() => {
      first.options.onOpen?.();
    });
    expect(hookResults.at(-1)?.groupStreamConnected).toBe(true);

    // Below the threshold nothing happens.
    await act(async () => {
      vi.advanceTimersByTime(30_000);
    });
    expect(first.aborted).toBe(false);
    expect(hoisted.consumeCalls).toHaveLength(1);

    // Past the threshold: the dead connection is aborted, connected flips
    // false (which re-enables polling), and the reconnect timer fires.
    await act(async () => {
      vi.advanceTimersByTime(10_000);
    });
    expect(first.aborted).toBe(true);
    expect(hookResults.at(-1)?.groupStreamConnected).toBe(false);
    await act(async () => {
      vi.advanceTimersByTime(1_000);
    });
    expect(hoisted.consumeCalls).toHaveLength(2);
    expect(hoisted.consumeCalls[1]?.options.roomId).toBe("room-1");
    unmount(root);
  });

  it("covers a hung handshake before onOpen", async () => {
    vi.useFakeTimers();
    const root = mount(baseOptions());
    const first = hoisted.consumeCalls[0];
    await act(async () => {
      vi.advanceTimersByTime(40_000);
    });
    expect(first.aborted).toBe(true);
    expect(hookResults.at(-1)?.groupStreamConnected).toBe(false);
    await act(async () => {
      vi.advanceTimersByTime(1_000);
    });
    expect(hoisted.consumeCalls).toHaveLength(2);
    unmount(root);
  });

  it("does not reconnect after unmount cleared the watchdog", async () => {
    vi.useFakeTimers();
    const root = mount(baseOptions());
    act(() => {
      hoisted.consumeCalls[0]?.options.onOpen?.();
    });
    unmount(root);
    await act(async () => {
      vi.advanceTimersByTime(90_000);
    });
    expect(hoisted.consumeCalls).toHaveLength(1);
    expect(hoisted.consumeCalls[0]?.aborted).toBe(true);
  });
});
