import type { SessionStreamEvent } from "../api/types";
import { shouldAcceptSessionStreamEvent } from "./chatSessionState";
import {
  resolveAssistantTurnRenderProtocol,
  type ChatTurnRenderProtocol,
} from "./chatTurnProtocol";

// Pure SSE router: keep parsing, session/type rejection, and protocol tracing out of React state code.
export type SessionStreamEventType = SessionStreamEvent["type"];
export type SessionStreamEventForType<T extends SessionStreamEventType> = Extract<SessionStreamEvent, { type: T }>;
type SessionAssistantDeltaStreamEvent = Extract<SessionStreamEvent, { type: "assistant_delta" }>;

export type SessionStreamProtocolEventRoute =
  | "session_detail"
  | "session_initial"
  | "assistant_delta"
  | "rejected";

export type SessionStreamProtocolRejectReason =
  | "parse_error"
  | "session_mismatch"
  | "event_type_mismatch";

export type SessionStreamProtocolTrace = {
  expectedType: SessionStreamEventType;
  actualType: SessionStreamEventType | "unparseable" | "unknown";
  eventRoute: SessionStreamProtocolEventRoute;
  turnRenderProtocol?: ChatTurnRenderProtocol;
  rejectReason?: SessionStreamProtocolRejectReason;
  payloadLength: number;
  sessionId: string;
  ledgerSeq: number;
  turnId: string;
  stage: string;
  done: boolean;
};

export type AcceptedSessionStreamProtocolRoute<T extends SessionStreamEventType> = {
  accepted: true;
  payload: SessionStreamEventForType<T>;
  trace: SessionStreamProtocolTrace;
};

export type RejectedSessionStreamProtocolRoute = {
  accepted: false;
  payload?: SessionStreamEvent;
  trace: SessionStreamProtocolTrace;
};

export type SessionStreamProtocolRoute<T extends SessionStreamEventType> =
  | AcceptedSessionStreamProtocolRoute<T>
  | RejectedSessionStreamProtocolRoute;

export type RouteSessionStreamEventInput<T extends SessionStreamEventType> = {
  activeSessionId: string | null | undefined;
  expectedType: T;
  rawData: string;
};

export function routeSessionStreamEvent<T extends SessionStreamEventType>(
  input: RouteSessionStreamEventInput<T>,
): SessionStreamProtocolRoute<T> {
  let payload: SessionStreamEvent;
  try {
    payload = JSON.parse(input.rawData) as SessionStreamEvent;
  } catch {
    return {
      accepted: false,
      trace: rejectedTrace(input, undefined, "parse_error", "unparseable"),
    };
  }

  if (!shouldAcceptSessionStreamEvent(payload, input.activeSessionId)) {
    return {
      accepted: false,
      payload,
      trace: rejectedTrace(input, payload, "session_mismatch", eventType(payload)),
    };
  }

  if (payload.type !== input.expectedType) {
    return {
      accepted: false,
      payload,
      trace: rejectedTrace(input, payload, "event_type_mismatch", eventType(payload)),
    };
  }

  return {
    accepted: true,
    payload: payload as SessionStreamEventForType<T>,
    trace: acceptedTrace(input, payload as SessionStreamEventForType<T>),
  };
}

export function sessionStreamProtocolTelemetryFields(trace: SessionStreamProtocolTrace) {
  return {
    streamExpectedType: trace.expectedType,
    streamActualType: trace.actualType,
    streamEventRoute: trace.eventRoute,
    turnRenderProtocol: trace.turnRenderProtocol ?? "",
    streamRejectReason: trace.rejectReason ?? "",
    streamPayloadLength: trace.payloadLength,
    streamLedgerSeq: trace.ledgerSeq,
    streamTurnId: trace.turnId,
    streamStage: trace.stage,
    streamDone: trace.done,
  };
}

function acceptedTrace<T extends SessionStreamEventType>(
  input: RouteSessionStreamEventInput<T>,
  payload: SessionStreamEventForType<T>,
): SessionStreamProtocolTrace {
  return {
    ...baseTrace(input, payload, eventType(payload)),
    eventRoute: payload.type,
    turnRenderProtocol: payload.type === "assistant_delta"
      ? resolveAssistantDeltaProtocol(payload as SessionAssistantDeltaStreamEvent)
      : undefined,
  };
}

function rejectedTrace<T extends SessionStreamEventType>(
  input: RouteSessionStreamEventInput<T>,
  payload: SessionStreamEvent | undefined,
  rejectReason: SessionStreamProtocolRejectReason,
  actualType: SessionStreamProtocolTrace["actualType"],
): SessionStreamProtocolTrace {
  return {
    ...baseTrace(input, payload, actualType),
    eventRoute: "rejected",
    rejectReason,
  };
}

function baseTrace<T extends SessionStreamEventType>(
  input: RouteSessionStreamEventInput<T>,
  payload: SessionStreamEvent | undefined,
  actualType: SessionStreamProtocolTrace["actualType"],
): Omit<SessionStreamProtocolTrace, "eventRoute"> {
  const assistantPayload = payload?.type === "assistant_delta" ? payload : undefined;
  return {
    expectedType: input.expectedType,
    actualType,
    payloadLength: input.rawData.length,
    sessionId: String(payload?.sessionId ?? input.activeSessionId ?? ""),
    ledgerSeq: normalizedNumber(payload?.ledgerSeq),
    turnId: String(assistantPayload?.turnId ?? ""),
    stage: String(assistantPayload?.stage ?? ""),
    done: Boolean(assistantPayload?.done),
  };
}

function eventType(payload: SessionStreamEvent | undefined): SessionStreamProtocolTrace["actualType"] {
  const type = String(payload?.type ?? "").trim();
  return type === "session_detail" || type === "session_initial" || type === "assistant_delta"
    ? type
    : "unknown";
}

function resolveAssistantDeltaProtocol(payload: SessionAssistantDeltaStreamEvent) {
  return resolveAssistantTurnRenderProtocol({
    answerContent: payload.contentDelta ?? payload.content,
    thoughtContent: payload.thoughtDelta ?? payload.thought,
    feedbackEventCount: payload.feedbackEvents?.length ?? 0,
    codexTranscript: payload.codexTranscript,
  });
}

function normalizedNumber(value: unknown) {
  const numeric = Number(value ?? 0);
  return Number.isFinite(numeric) ? numeric : 0;
}
