import { useEffect, useRef, useState } from "react";

import { researchWorkflowStreamUrl } from "../../../api/research-workflow/events";
import type { WorkflowEventEnvelope } from "../../../api/types/research-workflow/events";
import { RESEARCH_WORKFLOW_SSE_EVENT_TYPES } from "./researchWorkflowSseEventTypes";

export type ResearchWorkflowEventStreamState =
  | "idle"
  | "connecting"
  | "connected"
  | "reconnecting";

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
    if (typeof EventSource === "undefined") {
      setState("idle");
      setError("当前浏览器不支持工作流实时连接");
      return;
    }

    setState("connecting");
    setError(null);

    const source = new EventSource(
      researchWorkflowStreamUrl({
        teamId,
        runId,
        afterSequence: cursorRef.current,
      }),
    );

    source.onopen = () => {
      setState("connected");
      setError(null);
    };
    source.onerror = () => {
      setState("reconnecting");
      setError("工作流实时连接中断，正在重连");
    };

    source.addEventListener("snapshot", (raw) => {
      const message = raw as MessageEvent<string>;
      try {
        const payload = JSON.parse(message.data) as { cursor?: number };
        const cursor = Number(payload.cursor) || 0;
        cursorRef.current = Math.max(cursorRef.current, cursor);
      } catch {
        setError("工作流快照格式无效");
      }
    });

    const onTypedEvent = (raw: Event) => {
      const message = raw as MessageEvent<string>;
      try {
        const event = JSON.parse(message.data) as WorkflowEventEnvelope;
        const sequence = Number(event.sequence) || 0;
        if (sequence <= cursorRef.current) return;
        cursorRef.current = sequence;
        onEventRef.current(event);
      } catch {
        setError("工作流事件格式无效");
      }
    };

    for (const type of RESEARCH_WORKFLOW_SSE_EVENT_TYPES) {
      source.addEventListener(type, onTypedEvent);
    }

    return () => {
      source.close();
    };
  }, [enabled, runId, teamId]);

  return { state, error };
}
