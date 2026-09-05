import {
  consumeGuardedEventStream,
  parseGuardedSseFrame,
  type GuardedSseFrame,
} from "./guardedEventStream";

export type ChatRoomSseFrame = GuardedSseFrame;

export function chatRoomEventsUrl(roomId: string): string {
  return `/api/chat-rooms/${encodeURIComponent(String(roomId || "").trim())}/events`;
}

export function parseChatRoomSseFrame(rawFrame: string): ChatRoomSseFrame | null {
  return parseGuardedSseFrame(rawFrame);
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
  return consumeGuardedEventStream({
    url: chatRoomEventsUrl(options.roomId),
    signal: options.signal,
    onOpen: options.onOpen,
    onActivity: options.onActivity,
    onFrame: options.onFrame,
  });
}
