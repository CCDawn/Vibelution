import { useEffect, useRef, useState } from "react";

import { postBrowserTelemetry } from "../../app/browserTelemetry";
import { isFetchAbortError } from "../../api/chat";
import type { ChatRoomDetail, ChatRoomStreamEvent } from "../../api/types";
import { consumeChatRoomEventStream } from "./chatRoomEventStream";

export type UseGroupRoomStreamOptions = {
  activeGroupRoomId: string | null | undefined;
  groupStreamShouldConnect: boolean;
  syncChatRoomDetail: (room: ChatRoomDetail) => void;
};

/**
 * Sole owner of the authenticated group chat-room event stream.
 * Do not open a second /api/chat-rooms/:id/events connection elsewhere.
 */
export function useGroupRoomStream({
  activeGroupRoomId,
  groupStreamShouldConnect,
  syncChatRoomDetail,
}: UseGroupRoomStreamOptions): { groupStreamConnected: boolean } {
  const [groupStreamConnected, setGroupStreamConnected] = useState(false);
  const groupStreamErrorLoggedRef = useRef<Record<string, boolean>>({});
  const groupStreamPayloadErrorLoggedRef = useRef<Record<string, boolean>>({});

  useEffect(() => {
    if (!groupStreamShouldConnect || typeof AbortController === "undefined") {
      setGroupStreamConnected(false);
      return;
    }

    let disposed = false;
    const streamRoomId = String(activeGroupRoomId || "");
    if (!streamRoomId) {
      setGroupStreamConnected(false);
      return;
    }
    // The backend publishes a full room detail snapshot on every speaker state
    // transition; coalesce bursts the same way the direct session stream does
    // (350ms) so a running round does not parse+write the whole room cache per
    // event.
    const MIN_APPLY_INTERVAL_MS = 350;
    const RECONNECT_DELAY_MS = 1_000;
    let pendingDetail: ChatRoomDetail | null = null;
    let applyTimer: number | null = null;
    let reconnectTimer: number | null = null;
    let streamController: AbortController | null = null;

    function flushPendingDetail() {
      if (applyTimer !== null) {
        window.clearTimeout(applyTimer);
        applyTimer = null;
      }
      const next = pendingDetail;
      pendingDetail = null;
      if (!disposed && next) {
        syncChatRoomDetail(next);
      }
    }

    function scheduleChatRoomDetail(detail: ChatRoomDetail) {
      pendingDetail = detail;
      if (applyTimer !== null) {
        return;
      }
      applyTimer = window.setTimeout(() => {
        applyTimer = null;
        flushPendingDetail();
      }, MIN_APPLY_INTERVAL_MS);
    }

    function handleOpen() {
      if (!disposed) {
        setGroupStreamConnected(true);
        groupStreamErrorLoggedRef.current[streamRoomId] = false;
        postBrowserTelemetry({
          phase: "chat_room_stream",
          eventCode: "browser.chat_room_stream.opened",
          message: "Chat room detail stream opened.",
          level: "info",
          fields: {
            roomId: streamRoomId,
          },
        });
      }
    }

    function reportStreamError() {
      setGroupStreamConnected(false);
      if (!groupStreamErrorLoggedRef.current[streamRoomId]) {
        groupStreamErrorLoggedRef.current[streamRoomId] = true;
        postBrowserTelemetry({
          phase: "chat_room_stream",
          eventCode: "browser.chat_room_stream.error",
          message: "Chat room detail stream reported an error.",
          level: "warning",
          fields: {
            roomId: streamRoomId,
            transport: "fetch",
          },
        });
      }
    }

    function handleChatRoomDetail(data: string) {
      let payload: ChatRoomStreamEvent;
      try {
        payload = JSON.parse(data) as ChatRoomStreamEvent;
      } catch {
        if (!groupStreamPayloadErrorLoggedRef.current[streamRoomId]) {
          groupStreamPayloadErrorLoggedRef.current[streamRoomId] = true;
          postBrowserTelemetry({
            phase: "chat_room_stream",
            eventCode: "browser.chat_room_stream.bad_payload",
            message: "Chat room detail stream payload could not be parsed.",
            level: "warning",
            fields: {
              roomId: streamRoomId,
              payloadLength: data.length,
            },
          });
        }
        return;
      }
      if (payload.roomId !== streamRoomId || payload.detail?.roomId !== streamRoomId) {
        return;
      }
      setGroupStreamConnected(true);
      scheduleChatRoomDetail(payload.detail);
    }

    function scheduleReconnect() {
      if (disposed || reconnectTimer !== null) return;
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        void connect();
      }, RECONNECT_DELAY_MS);
    }

    async function connect() {
      if (disposed) return;
      const controller = new AbortController();
      streamController = controller;
      try {
        await consumeChatRoomEventStream({
          roomId: streamRoomId,
          signal: controller.signal,
          onOpen: handleOpen,
          onFrame: (frame) => {
            if (frame.event === "chat_room_detail") {
              handleChatRoomDetail(frame.data);
            }
          },
        });
        if (!disposed) {
          setGroupStreamConnected(false);
          scheduleReconnect();
        }
      } catch (error) {
        if (!disposed && !isFetchAbortError(error)) {
          reportStreamError();
          scheduleReconnect();
        }
      } finally {
        if (streamController === controller) {
          streamController = null;
        }
      }
    }

    void connect();

    return () => {
      disposed = true;
      flushPendingDetail();
      setGroupStreamConnected(false);
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      streamController?.abort();
      postBrowserTelemetry({
        phase: "chat_room_stream",
        eventCode: "browser.chat_room_stream.closed",
        message: "Chat room detail stream closed.",
        fields: {
          roomId: streamRoomId,
          transport: "fetch",
        },
      });
    };
  }, [activeGroupRoomId, groupStreamShouldConnect, syncChatRoomDetail]);

  return { groupStreamConnected };
}
