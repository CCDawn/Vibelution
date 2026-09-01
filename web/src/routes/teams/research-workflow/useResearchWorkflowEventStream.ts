import { useEffect, useRef, useState } from "react";

import { consumeResearchWorkflowEventStream } from "../../../api/research-workflow/events";
import type { WorkflowEventEnvelope } from "../../../api/types/research-workflow/events";
import {
  observeWorkflowStreamFrameInvalid,
  observeWorkflowStreamReconnected,
  observeWorkflowStreamInterrupted,
} from "../challengeCupTelemetry";

export type ResearchWorkflowEventStreamState =
  | "idle"
  | "connecting"
  | "connected"
  | "reconnecting";

const RECONNECT_DELAY_MS = 1_000;

export function useResearchWorkflowEventStream(options: {
  teamId: string;
  runId: string;
  afterSequence: number;
  initialAfterSequence?: number;
  onEvent: (event: WorkflowEventEnvelope) =>
    | void
    | boolean
    | { accepted: boolean; resyncRequired?: boolean };
  enabled?: boolean;
}): { state: ResearchWorkflowEventStreamState; error: string | null } {
  const {
    teamId,
    runId,
    afterSequence,
    initialAfterSequence,
    onEvent,
    enabled = true,
  } = options;

  const [state, setState] = useState<ResearchWorkflowEventStreamState>("idle");
  const [error, setError] = useState<string | null>(null);
  const cursorRef = useRef(0);
  const interruptedRef = useRef<{ attempts: number; startedAtMs: number } | null>(null);
  const frameInvalidReportedRef = useRef(false);
  const onEventRef = useRef(onEvent);

  onEventRef.current = onEvent;

  useEffect(() => {
    cursorRef.current = Math.max(
      0,
      Number(initialAfterSequence ?? afterSequence ?? 0) || 0,
    );
  }, [teamId, runId, initialAfterSequence]);

  useEffect(() => {
    if (!enabled || !teamId.trim() || !runId.trim()) {
      setState("idle");
      setError(null);
      return;
    }
    let activeController: AbortController | null = null;
    let reconnectTimer: number | null = null;
    let stopped = false;

    const scheduleReconnect = (reason?: string) => {
      if (stopped) return;
      if (reconnectTimer !== null) return;
      const interrupted = interruptedRef.current;
      if (interrupted) {
        interrupted.attempts += 1;
      } else {
        interruptedRef.current = { attempts: 1, startedAtMs: Date.now() };
        observeWorkflowStreamInterrupted({
          teamId,
          runId,
          reason: reason ?? "connection_lost",
        });
      }
      setState("reconnecting");
      setError("工作流实时连接中断，正在重连");
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        void connect(true);
      }, RECONNECT_DELAY_MS);
    };

    const connect = async (reconnecting: boolean) => {
      if (stopped) return;
      const controller = new AbortController();
      activeController?.abort();
      activeController = controller;
      setState(reconnecting ? "reconnecting" : "connecting");
      if (!reconnecting) setError(null);
      try {
        const afterSequence = cursorRef.current;
        await consumeResearchWorkflowEventStream({
          teamId,
          runId,
          afterSequence,
          ...(reconnecting && afterSequence > 0
            ? { lastEventId: `${runId}:${afterSequence}` }
            : {}),
          signal: controller.signal,
          onOpen: () => {
            if (stopped) return;
            const interrupted = interruptedRef.current;
            if (interrupted) {
              observeWorkflowStreamReconnected({
                teamId,
                runId,
                reconnectAttempts: interrupted.attempts,
                downtimeMs: Math.max(0, Math.round(Date.now() - interrupted.startedAtMs)),
              });
              interruptedRef.current = null;
            }
            frameInvalidReportedRef.current = false;
            setState("connected");
            setError(null);
          },
          onFrame: (frame) => {
            try {
              if (frame.event === "snapshot") {
                // The handshake advertises server position, not an accepted
                // client event. Keep cursorRef at the reducer-confirmed cursor.
                void (JSON.parse(frame.data) as { cursor?: number });
                return;
              }
              // Forward compatibility: every well-formed workflow event frame
              // is delivered, including event types this build does not know.
              // Unknown types flow through the reducer as generic events so
              // the cursor still advances and the snapshot gets refetched;
              // dropping them here would freeze the canvas on stale state
              // until an unrelated event arrived.
              const event = JSON.parse(frame.data) as WorkflowEventEnvelope;
              const sequence = Number(event.sequence) || 0;
              if (sequence <= cursorRef.current) return;
              const result = onEventRef.current(event);
              const accepted = typeof result === "object"
                ? result.accepted
                : result !== false;
              if (accepted) {
                cursorRef.current = sequence;
              } else if (typeof result === "object" && result.resyncRequired) {
                // Keep the last accepted cursor and force a fresh replay;
                // otherwise the gap event would be silently skipped forever.
                controller.abort();
                scheduleReconnect("resync_required");
              }
            } catch {
              if (!frameInvalidReportedRef.current) {
                frameInvalidReportedRef.current = true;
                observeWorkflowStreamFrameInvalid({ teamId, runId, eventType: frame.event });
              }
              setError("工作流事件格式无效");
            }
          },
        });
      } catch {
        // Abort is expected both during cleanup and when a gap asks for a
        // replay. The latter already scheduled a fresh controller above.
      } finally {
        if (activeController === controller) activeController = null;
        if (!stopped && !controller.signal.aborted) scheduleReconnect();
      }
    };

    void connect(false);

    return () => {
      stopped = true;
      activeController?.abort();
      activeController = null;
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
    };
  }, [enabled, runId, teamId]);

  return { state, error };
}
