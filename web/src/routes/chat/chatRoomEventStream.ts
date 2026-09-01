import { fetchWithControl } from "../../api/chat";

export type ChatRoomSseFrame = {
  event: string;
  data: string;
};

export function chatRoomEventsUrl(roomId: string): string {
  return `/api/chat-rooms/${encodeURIComponent(String(roomId || "").trim())}/events`;
}

export function parseChatRoomSseFrame(rawFrame: string): ChatRoomSseFrame | null {
  let event = "message";
  const data: string[] = [];
  for (const line of rawFrame.split(/\r?\n/)) {
    if (!line || line.startsWith(":")) continue;
    const separator = line.indexOf(":");
    const field = separator >= 0 ? line.slice(0, separator) : line;
    let value = separator >= 0 ? line.slice(separator + 1) : "";
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value || "message";
    else if (field === "data") data.push(value);
  }
  return data.length ? { event, data: data.join("\n") } : null;
}

function splitCompleteSseFrames(buffer: string): { frames: string[]; rest: string } {
  const frames: string[] = [];
  let rest = buffer;
  while (true) {
    const boundary = /\r?\n\r?\n/.exec(rest);
    if (!boundary || boundary.index == null) break;
    frames.push(rest.slice(0, boundary.index));
    rest = rest.slice(boundary.index + boundary[0].length);
  }
  return { frames, rest };
}

/**
 * Consume a guarded room SSE stream through fetch so the web control token
 * stays in its required request header. Browser EventSource cannot provide
 * that header, while this preserves the server's normal SSE framing.
 */
export async function consumeChatRoomEventStream(options: {
  roomId: string;
  signal: AbortSignal;
  onOpen?: () => void;
  /**
   * Fired for every complete SSE frame received, including comment-only
   * keep-alive frames that never reach onFrame. Consumers use this as a
   * liveness heartbeat so a half-open TCP connection can be detected.
   */
  onActivity?: () => void;
  onFrame: (frame: ChatRoomSseFrame) => void;
}): Promise<void> {
  const response = await fetchWithControl(chatRoomEventsUrl(options.roomId), {
    headers: { Accept: "text/event-stream" },
    signal: options.signal,
  });
  if (!response.body) throw new Error("群聊实时连接没有返回事件流");
  options.onOpen?.();

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parsed = splitCompleteSseFrames(buffer);
      buffer = parsed.rest;
      for (const rawFrame of parsed.frames) {
        options.onActivity?.();
        const frame = parseChatRoomSseFrame(rawFrame);
        if (frame) options.onFrame(frame);
      }
    }
    buffer += decoder.decode();
    const parsed = splitCompleteSseFrames(buffer);
    for (const rawFrame of parsed.frames) {
      options.onActivity?.();
      const frame = parseChatRoomSseFrame(rawFrame);
      if (frame) options.onFrame(frame);
    }
  } finally {
    reader.releaseLock();
  }
}
