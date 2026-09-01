import { afterEach, describe, expect, it, vi } from "vitest";

import {
  resetControlTokenForTests,
  seedControlTokenForTests,
} from "../../api/client";
import {
  chatRoomEventsUrl,
  consumeChatRoomEventStream,
  parseChatRoomSseFrame,
} from "./chatRoomEventStream";

afterEach(() => {
  resetControlTokenForTests();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("chat room event stream", () => {
  it("uses the canonical encoded room events URL", () => {
    expect(chatRoomEventsUrl("room a/1")).toBe("/api/chat-rooms/room%20a%2F1/events");
  });

  it("parses named frames and joins multi-line event data", () => {
    expect(parseChatRoomSseFrame("event: chat_room_detail\ndata: one\ndata: two")).toEqual({
      event: "chat_room_detail",
      data: "one\ntwo",
    });
    expect(parseChatRoomSseFrame(": keep-alive")).toBeNull();
  });

  it("opens the event stream through the control-token fetch boundary", async () => {
    seedControlTokenForTests("room-stream-token");
    const payload = JSON.stringify({
      type: "chat_room_detail",
      roomId: "room-1",
      detail: { roomId: "room-1" },
    });
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(`event: chat_room_detail\ndata: ${payload}\n\n`));
        controller.close();
      },
    });
    const fetchMock = vi.fn().mockResolvedValue(new Response(body, {
      status: 200,
      headers: { "content-type": "text/event-stream" },
    }));
    vi.stubGlobal("fetch", fetchMock);
    const opened = vi.fn();
    const frames: Array<{ event: string; data: string }> = [];

    await consumeChatRoomEventStream({
      roomId: "room-1",
      signal: new AbortController().signal,
      onOpen: opened,
      onFrame: (frame) => frames.push(frame),
    });

    expect(opened).toHaveBeenCalledTimes(1);
    expect(frames).toEqual([{ event: "chat_room_detail", data: payload }]);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/chat-rooms/room-1/events",
      expect.objectContaining({
        credentials: "same-origin",
      }),
    );
    const requestInit = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(requestInit.headers).get("X-Vibelution-Control-Token")).toBe("room-stream-token");
  });

  it("feeds keep-alive comment frames to onActivity while onFrame only sees data frames", async () => {
    seedControlTokenForTests("keep-alive-stream-token");
    const payload = JSON.stringify({ type: "chat_room_detail", roomId: "room-1" });
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(": keep-alive\n\n"));
        controller.enqueue(new TextEncoder().encode(`event: chat_room_detail\ndata: ${payload}\n\n`));
        controller.close();
      },
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, {
      status: 200,
      headers: { "content-type": "text/event-stream" },
    })));
    const activities = vi.fn();
    const frames: Array<{ event: string; data: string }> = [];

    await consumeChatRoomEventStream({
      roomId: "room-1",
      signal: new AbortController().signal,
      onActivity: activities,
      onFrame: (frame) => frames.push(frame),
    });

    expect(activities).toHaveBeenCalledTimes(2);
    expect(frames).toEqual([{ event: "chat_room_detail", data: payload }]);
  });
});
