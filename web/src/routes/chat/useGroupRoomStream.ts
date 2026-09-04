import { useEffect, useRef, useState } from "react";

import { postBrowserTelemetry } from "../../app/browserTelemetry";
import { isFetchAbortError } from "../../api/chat";
import type {
  ChatRoomDetail,
  ChatRoomSpeakerProgress,
  ChatRoomSpeakerDeltaEvent,
  ChatRoomSpeakerStateEvent,
  ChatRoomStreamEvent,
} from "../../api/types";
import { consumeChatRoomEventStream } from "./chatRoomEventStream";

export type UseGroupRoomStreamOptions = {
  activeGroupRoomId: string | null | undefined;
  groupStreamShouldConnect: boolean;
  syncChatRoomDetail: (room: ChatRoomDetail) => void;
};

/** Live streaming state for one (roundId, participantId) speaker. */
export type GroupSpeakerStreamEntry = {
  roundId: string;
  participantId: string;
  sessionId: string;
  turnId: string;
  seq: number;
  /** Cumulative answer text from the latest accepted delta frame. */
  content: string;
  /** Client arrival time (Date.now) of the last accepted delta frame. */
  lastDeltaAtMs: number;
};

/** Streaming buffers keyed by roundId then participantId. */
export type GroupSpeakerStreamMap = Record<string, Record<string, GroupSpeakerStreamEntry>>;

/** Latest lifecycle projection keyed by roundId then participantId. */
export type GroupSpeakerProgressMap = Record<string, Record<string, ChatRoomSpeakerProgress>>;

// Low-latency publish cadence for the streaming buffer: well below the 350ms
// detail coalescing, still batching delta bursts into one React commit.
const SPEAKER_STREAM_FLUSH_DELAY_MS = 50;

/**
 * Sole owner of the authenticated group chat-room event stream.
 * Do not open a second /api/chat-rooms/:id/events connection elsewhere.
 */
export function useGroupRoomStream({
  activeGroupRoomId,
  groupStreamShouldConnect,
  syncChatRoomDetail,
}: UseGroupRoomStreamOptions): {
  groupStreamConnected: boolean;
  groupSpeakerStreams: GroupSpeakerStreamMap;
  groupSpeakerProgress: GroupSpeakerProgressMap;
} {
  const [groupStreamConnected, setGroupStreamConnected] = useState(false);
  const [groupSpeakerStreams, setGroupSpeakerStreams] = useState<GroupSpeakerStreamMap>({});
  const [groupSpeakerProgress, setGroupSpeakerProgress] = useState<GroupSpeakerProgressMap>({});
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
    // Full room snapshots remain authoritative and are coalesced like the
    // direct session stream. Per-speaker lifecycle events use this same
    // connection but update their small projection immediately.
    const MIN_APPLY_INTERVAL_MS = 350;
    const RECONNECT_DELAY_MS = 1_000;
    // Liveness watchdog: the backend emits a keep-alive comment every 15s, so
    // 40s of silence means 2+ missed heartbeats. A half-open TCP connection
    // leaves reader.read() pending forever without this, freezing the UI on a
    // stale snapshot with polling disabled.
    const LIVENESS_TIMEOUT_MS = 40_000;
    let pendingDetail: ChatRoomDetail | null = null;
    let applyTimer: number | null = null;
    let reconnectTimer: number | null = null;
    let livenessTimer: number | null = null;
    let streamController: AbortController | null = null;
    // Speaker streaming buffers: source of truth lives in this closure and is
    // published to React state on a 50ms trailing-edge schedule, mirroring the
    // direct-chat assistant delta enqueue+drain pattern at a lighter weight.
    let speakerStreams: GroupSpeakerStreamMap = {};
    let speakerProgress: GroupSpeakerProgressMap = {};
    let speakerStreamFlushTimer: number | null = null;
    let speakerDeltaTelemetryLogged = false;

    function clearSpeakerProgress() {
      speakerProgress = {};
      setGroupSpeakerProgress((previous) => (Object.keys(previous).length ? {} : previous));
    }

    function replaceSpeakerProgressFromDetail(detail: ChatRoomDetail) {
      const next: GroupSpeakerProgressMap = {};
      for (const round of detail.rounds ?? []) {
        const roundId = String(round.roundId || "").trim();
        if (!roundId) continue;
        for (const item of round.speakerProgress ?? []) {
          const participantId = String(item.participantId || "").trim();
          if (!participantId) continue;
          next[roundId] = {
            ...next[roundId],
            [participantId]: { ...item, participantId },
          };
        }
      }
      speakerProgress = next;
      setGroupSpeakerProgress(next);
    }

    function handleSpeakerState(payload: ChatRoomSpeakerStateEvent) {
      const roundId = String(payload.roundId || "").trim();
      const participantId = String(payload.participantId || "").trim();
      if (!roundId || !participantId || !["queued", "running", "settled"].includes(payload.state)) {
        return;
      }
      speakerProgress = {
        ...speakerProgress,
        [roundId]: {
          ...speakerProgress[roundId],
          [participantId]: {
            participantId,
            sessionId: String(payload.sessionId || ""),
            state: payload.state,
            status: payload.status,
            updatedAt: String(payload.updatedAt || ""),
          },
        },
      };
      setGroupSpeakerProgress(speakerProgress);
    }

    function clearSpeakerStreams() {
      if (speakerStreamFlushTimer !== null) {
        window.clearTimeout(speakerStreamFlushTimer);
        speakerStreamFlushTimer = null;
      }
      speakerStreams = {};
      setGroupSpeakerStreams((previous) => (Object.keys(previous).length ? {} : previous));
    }

    function publishSpeakerStreams() {
      speakerStreamFlushTimer = null;
      setGroupSpeakerStreams({ ...speakerStreams });
    }

    function flushSpeakerStreamsNow() {
      if (speakerStreamFlushTimer !== null) {
        window.clearTimeout(speakerStreamFlushTimer);
        speakerStreamFlushTimer = null;
      }
      if (!disposed) {
        publishSpeakerStreams();
      }
    }

    function scheduleSpeakerStreamFlush() {
      if (speakerStreamFlushTimer !== null || disposed) return;
      speakerStreamFlushTimer = window.setTimeout(() => {
        publishSpeakerStreams();
      }, SPEAKER_STREAM_FLUSH_DELAY_MS);
    }

    function removeSpeakerStreamEntry(roundId: string, participantId: string) {
      const roundStreams = speakerStreams[roundId];
      if (!roundStreams || !roundStreams[participantId]) {
        return false;
      }
      const nextRoundStreams = { ...roundStreams };
      delete nextRoundStreams[participantId];
      const nextStreams = { ...speakerStreams };
      if (Object.keys(nextRoundStreams).length) {
        nextStreams[roundId] = nextRoundStreams;
      } else {
        delete nextStreams[roundId];
      }
      speakerStreams = nextStreams;
      return true;
    }

    function handleSpeakerDelta(payload: ChatRoomSpeakerDeltaEvent) {
      const roundId = String(payload?.roundId || "").trim();
      const participantId = String(payload?.participantId || "").trim();
      const seq = Number(payload?.seq);
      if (
        !roundId
        || !participantId
        || !Number.isInteger(seq)
      ) {
        return;
      }
      const existing = speakerStreams[roundId]?.[participantId];
      // content is a cumulative snapshot: only a strictly newer seq may move
      // the visible text, so late/reordered frames are dropped.
      if (existing && seq <= existing.seq) {
        return;
      }
      speakerStreams = {
        ...speakerStreams,
        [roundId]: {
          ...speakerStreams[roundId],
          [participantId]: {
            roundId,
            participantId,
            sessionId: String(payload.sessionId || ""),
            turnId: String(payload.turnId || ""),
            seq,
            content: String(payload.content ?? ""),
            lastDeltaAtMs: Date.now(),
          },
        },
      };
      if (!speakerDeltaTelemetryLogged) {
        speakerDeltaTelemetryLogged = true;
        postBrowserTelemetry({
          phase: "chat_room_stream",
          eventCode: "browser.chat_room_stream.speaker_delta_started",
          message: "Chat room speaker delta streaming started.",
          level: "info",
          fields: {
            roomId: streamRoomId,
            roundId,
            participantId,
            seq,
          },
        });
      }
      scheduleSpeakerStreamFlush();
    }

    function finishSpeakerDelta(payload: ChatRoomSpeakerDeltaEvent) {
      const roundId = String(payload.roundId || "").trim();
      const participantId = String(payload.participantId || "").trim();
      const hadEntry = removeSpeakerStreamEntry(roundId, participantId);
      if (!hadEntry) {
        return;
      }
      // Terminal frame: the authoritative snapshot message (or the failure
      // bubble) replaces the streamed text, so drop the buffer instead of
      // freezing half a turn on screen.
      flushSpeakerStreamsNow();
      postBrowserTelemetry({
        phase: "chat_room_stream",
        eventCode: "browser.chat_room_stream.speaker_delta_finished",
        message: "Chat room speaker delta streaming finished.",
        level: "info",
        fields: {
          roomId: streamRoomId,
          roundId,
          participantId,
          status: String(payload.status || ""),
        },
      });
    }

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

    function clearStreamLivenessWatchdog() {
      if (livenessTimer !== null) {
        window.clearTimeout(livenessTimer);
        livenessTimer = null;
      }
    }

    function feedStreamLivenessWatchdog() {
      clearStreamLivenessWatchdog();
      if (disposed) return;
      livenessTimer = window.setTimeout(() => {
        livenessTimer = null;
        if (disposed) return;
        setGroupStreamConnected(false);
        postBrowserTelemetry({
          phase: "chat_room_stream",
          eventCode: "browser.chat_room_stream.stalled",
          message: "Chat room detail stream went silent; forcing reconnect.",
          level: "warning",
          fields: {
            roomId: streamRoomId,
            transport: "fetch",
          },
        });
        streamController?.abort();
        scheduleReconnect();
      }, LIVENESS_TIMEOUT_MS);
    }

    function handleOpen() {
      if (!disposed) {
        // Fresh connection: drop every streaming buffer instead of replaying.
        // content is cumulative, so the next delta frames rebuild the text.
        clearSpeakerStreams();
        clearSpeakerProgress();
        setGroupStreamConnected(true);
        feedStreamLivenessWatchdog();
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
      // The snapshot is authoritative: it overrides any streaming buffer on
      // arrival, so delivered messages can never keep a stale streaming tail.
      clearSpeakerStreams();
      replaceSpeakerProgressFromDetail(payload.detail);
      setGroupStreamConnected(true);
      scheduleChatRoomDetail(payload.detail);
    }

    function handleSpeakerDeltaPayload(data: string) {
      let payload: ChatRoomSpeakerDeltaEvent;
      try {
        payload = JSON.parse(data) as ChatRoomSpeakerDeltaEvent;
      } catch {
        return;
      }
      if (payload?.type !== "chat_room_speaker_delta" || payload.roomId !== streamRoomId) {
        return;
      }
      if (payload.done) {
        finishSpeakerDelta(payload);
        return;
      }
      handleSpeakerDelta(payload);
    }

    function handleSpeakerStatePayload(data: string) {
      let payload: ChatRoomSpeakerStateEvent;
      try {
        payload = JSON.parse(data) as ChatRoomSpeakerStateEvent;
      } catch {
        return;
      }
      if (payload?.type !== "chat_room_speaker_state" || payload.roomId !== streamRoomId) {
        return;
      }
      handleSpeakerState(payload);
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
      // Arm before the fetch so a hung response/handshake is covered too.
      feedStreamLivenessWatchdog();
      try {
        await consumeChatRoomEventStream({
          roomId: streamRoomId,
          signal: controller.signal,
          onOpen: handleOpen,
          onActivity: feedStreamLivenessWatchdog,
          onFrame: (frame) => {
            if (frame.event === "chat_room_detail") {
              handleChatRoomDetail(frame.data);
            } else if (frame.event === "chat_room_speaker_delta") {
              handleSpeakerDeltaPayload(frame.data);
            } else if (frame.event === "chat_room_speaker_state") {
              handleSpeakerStatePayload(frame.data);
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
        clearStreamLivenessWatchdog();
        if (streamController === controller) {
          streamController = null;
        }
      }
    }

    void connect();

    return () => {
      disposed = true;
      flushPendingDetail();
      // Route switch/unmount: the buffers belong to the closed stream and must
      // not leak into the next room or reconnection cycle.
      clearSpeakerStreams();
      clearSpeakerProgress();
      setGroupStreamConnected(false);
      clearStreamLivenessWatchdog();
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

  return { groupStreamConnected, groupSpeakerStreams, groupSpeakerProgress };
}
