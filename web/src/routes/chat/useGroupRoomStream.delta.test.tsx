// @vitest-environment happy-dom
/**
 * Speaker streaming delta consumption for the group room SSE stream: delta
 * frames fill a per-(roundId, participantId) streaming buffer published on a
 * short trailing-edge schedule; late/reordered seq frames are dropped; the
 * authoritative chat_room_detail snapshot and done terminals clear the buffer;
 * reconnects clear every buffer while a disconnect freezes the display.
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

let hookResults: {
  groupStreamConnected: boolean;
  groupSpeakerStreams: Record<string, Record<string, {
    content: string;
    seq: number;
    lastDeltaAtMs: number;
  }>>;
}[] = [];

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

function deltaFrame(overrides: Record<string, unknown> = {}) {
  return JSON.stringify({
    type: "chat_room_speaker_delta",
    roomId: "room-1",
    roundId: "r1",
    participantId: "p1",
    sessionId: "s1",
    turnId: "t1",
    seq: 1,
    stage: "answer",
    content: "",
    done: false,
    status: "streaming",
    ...overrides,
  });
}

function detailFrame() {
  return JSON.stringify({
    type: "chat_room_detail",
    roomId: "room-1",
    detail: {
      roomId: "room-1",
      title: "研究组",
      status: "running",
      rounds: [],
      participants: [],
    },
  });
}

function openFirstConnection() {
  const first = hoisted.consumeCalls[0];
  act(() => {
    first.options.onOpen?.();
  });
  return first;
}

function streamsAt(index = -1) {
  return hookResults.at(index)?.groupSpeakerStreams ?? {};
}

async function advance(ms: number) {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
}

describe("useGroupRoomStream speaker delta streaming", () => {
  beforeEach(() => {
    hoisted.consumeCalls.length = 0;
    hoisted.rejectCurrent = null;
    hookResults = [];
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("publishes cumulative delta content per (roundId, participantId) on the low-latency schedule", async () => {
    const root = mount(baseOptions());
    const first = openFirstConnection();
    act(() => {
      first.options.onFrame({ event: "chat_room_speaker_delta", data: deltaFrame({ seq: 1, content: "你好" }) });
    });
    // Before the flush timer fires the buffer is not published yet.
    expect(streamsAt()).toEqual({});
    await advance(50);
    expect(streamsAt().r1?.p1?.content).toBe("你好");
    expect(streamsAt().r1?.p1?.seq).toBe(1);
    expect(streamsAt().r1?.p1?.lastDeltaAtMs).toBeGreaterThan(0);

    // content is a cumulative snapshot: a newer frame replaces, never appends.
    act(() => {
      first.options.onFrame({ event: "chat_room_speaker_delta", data: deltaFrame({ seq: 2, content: "你好，世界" }) });
    });
    await advance(50);
    expect(streamsAt().r1?.p1?.content).toBe("你好，世界");
    expect(streamsAt().r1?.p1?.seq).toBe(2);

    // A second speaker keeps an independent buffer.
    act(() => {
      first.options.onFrame({
        event: "chat_room_speaker_delta",
        data: deltaFrame({ seq: 1, participantId: "p2", roundId: "r1", content: "第二个发言" }),
      });
    });
    await advance(50);
    expect(streamsAt().r1?.p1?.content).toBe("你好，世界");
    expect(streamsAt().r1?.p2?.content).toBe("第二个发言");
    unmount(root);
  });

  it("drops late, duplicate, and out-of-order seq frames", async () => {
    const root = mount(baseOptions());
    const first = openFirstConnection();
    act(() => {
      first.options.onFrame({ event: "chat_room_speaker_delta", data: deltaFrame({ seq: 3, content: "最新快照" }) });
    });
    await advance(50);
    act(() => {
      first.options.onFrame({ event: "chat_room_speaker_delta", data: deltaFrame({ seq: 2, content: "迟到旧帧" }) });
      first.options.onFrame({ event: "chat_room_speaker_delta", data: deltaFrame({ seq: 3, content: "重复帧" }) });
    });
    await advance(50);
    expect(streamsAt().r1?.p1?.content).toBe("最新快照");
    expect(streamsAt().r1?.p1?.seq).toBe(3);
    unmount(root);
  });

  it("clears streaming buffers as soon as an authoritative room snapshot arrives", async () => {
    const root = mount(baseOptions());
    const first = openFirstConnection();
    act(() => {
      first.options.onFrame({ event: "chat_room_speaker_delta", data: deltaFrame({ seq: 1, content: "流式内容" }) });
    });
    await advance(50);
    expect(Object.keys(streamsAt()).length).toBeGreaterThan(0);

    act(() => {
      first.options.onFrame({ event: "chat_room_detail", data: detailFrame() });
    });
    await advance(50);
    expect(streamsAt()).toEqual({});
    // Deltas after the snapshot rebuild the text (cumulative semantics).
    act(() => {
      first.options.onFrame({ event: "chat_room_speaker_delta", data: deltaFrame({ seq: 2, content: "重建的文本" }) });
    });
    await advance(50);
    expect(streamsAt().r1?.p1?.content).toBe("重建的文本");
    unmount(root);
  });

  it("clears the buffer on a done terminal so the snapshot message replaces the streamed text", async () => {
    const root = mount(baseOptions());
    const first = openFirstConnection();
    act(() => {
      first.options.onFrame({ event: "chat_room_speaker_delta", data: deltaFrame({ seq: 1, content: "完成前的文本" }) });
    });
    await advance(50);
    expect(streamsAt().r1?.p1?.content).toBe("完成前的文本");
    act(() => {
      first.options.onFrame({
        event: "chat_room_speaker_delta",
        data: deltaFrame({ seq: 2, content: "完成前的文本", done: true, status: "completed" }),
      });
    });
    await advance(50);
    expect(streamsAt()).toEqual({});
    unmount(root);
  });

  it("clears the streamed text on failed and aborted terminals without leaving a half answer", async () => {
    for (const status of ["failed", "stopped", "aborted"]) {
      hoisted.consumeCalls.length = 0;
      hookResults = [];
      const root = mount(baseOptions());
      const first = openFirstConnection();
      act(() => {
        first.options.onFrame({ event: "chat_room_speaker_delta", data: deltaFrame({ seq: 1, content: "半截回答" }) });
      });
      await advance(50);
      expect(streamsAt().r1?.p1?.content).toBe("半截回答");
      act(() => {
        first.options.onFrame({
          event: "chat_room_speaker_delta",
          data: deltaFrame({ seq: 2, content: "半截回答", done: true, status }),
        });
      });
      await advance(50);
      expect(streamsAt()).toEqual({});
      unmount(root);
    }
  });

  it("freezes buffers while disconnected and clears them all when the stream reconnects", async () => {
    const root = mount(baseOptions());
    const first = openFirstConnection();
    act(() => {
      first.options.onFrame({ event: "chat_room_speaker_delta", data: deltaFrame({ seq: 1, content: "断连前文本" }) });
    });
    await advance(50);
    expect(hookResults.at(-1)?.groupStreamConnected).toBe(true);

    // Watchdog reset: the dead connection is aborted and the buffer stays
    // frozen on screen during the disconnected window.
    await advance(40_000);
    expect(first.aborted).toBe(true);
    expect(hookResults.at(-1)?.groupStreamConnected).toBe(false);
    expect(streamsAt().r1?.p1?.content).toBe("断连前文本");

    // Reconnect: fresh connection drops every buffer (no replay; cumulative
    // frames refill the text), and the connection reads as live again.
    await advance(1_000);
    expect(hoisted.consumeCalls).toHaveLength(2);
    act(() => {
      hoisted.consumeCalls[1]?.options.onOpen?.();
    });
    expect(hookResults.at(-1)?.groupStreamConnected).toBe(true);
    expect(streamsAt()).toEqual({});
    unmount(root);
  });

  it("does not leak buffers across a room switch", async () => {
    const root = mount(baseOptions());
    const first = openFirstConnection();
    act(() => {
      first.options.onFrame({ event: "chat_room_speaker_delta", data: deltaFrame({ seq: 1, content: "旧房间文本" }) });
    });
    await advance(50);
    expect(streamsAt().r1?.p1?.content).toBe("旧房间文本");
    // Same mounted hook, new room: the stream effect cleanup must clear the
    // published buffers so the old room's stream cannot leak into the new one.
    act(() => {
      root.render(<Host props={baseOptions({ activeGroupRoomId: "room-2" })} />);
    });
    await advance(50);
    expect(streamsAt()).toEqual({});
    unmount(root);
  });
});
