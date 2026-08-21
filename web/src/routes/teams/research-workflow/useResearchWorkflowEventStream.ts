import { useEffect, useRef, useState } from "react";

import { consumeResearchWorkflowEventStream } from "../../../api/research-workflow/events";
import type { WorkflowEventEnvelope } from "../../../api/types/research-workflow/events";
import { RESEARCH_WORKFLOW_SSE_EVENT_TYPES } from "./researchWorkflowSseEventTypes";

export type ResearchWorkflowEventStreamState =
  | "idle"
  | "connecting"
  | "connected"
  | "reconnecting";

const RECONNECT_DELAY_MS = 1_000;
const KNOWN_EVENT_TYPES = new Set<string>(RESEARCH_WORKFLOW_SSE_EVENT_TYPES);

export function useResearchWorkflowEventStream(options: {
  teamId: string;
  runId: string;
  afterSequence: number;
  initialAfterSequence?: number;
  onEvent: (event: WorkflowEventEnvelope) => void;
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
    const controller = new AbortController();
    let reconnectTimer: number | null = null;
    let stopped = false;

    const scheduleReconnect = () => {
      if (stopped || controller.signal.aborted) return;
      setState("reconnecting");
      setError("工作流实时连接中断，正在重连");
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        void connect(true);
      }, RECONNECT_DELAY_MS);
    };

    const connect = async (reconnecting: boolean) => {
      if (stopped || controller.signal.aborted) return;
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
            setState("connected");
            setError(null);
          },
          onFrame: (frame) => {
            try {
              if (frame.event === "snapshot") {
                const payload = JSON.parse(frame.data) as { cursor?: number };
                cursorRef.current = Math.max(cursorRef.current, Number(payload.cursor) || 0);
                return;
              }
              const event = JSON.parse(frame.data) as WorkflowEventEnvelope;
              const sequence = Number(event.sequence) || 0;
              if (sequence <= cursorRef.current) return;
              cursorRef.current = sequence;
              if (KNOWN_EVENT_TYPES.has(frame.event)) onEventRef.current(event);
            } catch {
              setError("工作流事件格式无效");
            }
          },
        });
        scheduleReconnect();
      } catch {
        if (!controller.signal.aborted) scheduleReconnect();
      }
    };

    void connect(false);

    return () => {
      stopped = true;
      controller.abort();
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
    };
  }, [enabled, runId, teamId]);

  return { state, error };
}
