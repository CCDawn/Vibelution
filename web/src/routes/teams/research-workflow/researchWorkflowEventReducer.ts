/**
 * Formal event merge reducer (T6).
 * Keeps legacy helpers below for pre-T7 pages; formal path uses applyFormalEvent.
 */

import type { WorkflowEventEnvelope } from "../../../api/types/research-workflow/events";

export type FormalEventReadModel = {
  generation: number;
  teamId: string;
  runId: string;
  events: WorkflowEventEnvelope[];
  lastSequence: number;
  seenEventIds: Record<string, true>;
  resyncRequired: boolean;
  pendingRequestId: string | null;
  commandError: string | null;
};

export function emptyFormalEventReadModel(
  teamId = "",
  runId = "",
): FormalEventReadModel {
  return {
    generation: 0,
    teamId,
    runId,
    events: [],
    lastSequence: 0,
    seenEventIds: {},
    resyncRequired: false,
    pendingRequestId: null,
    commandError: null,
  };
}

export function switchFormalEventScope(
  state: FormalEventReadModel,
  options: { teamId: string; runId: string },
): FormalEventReadModel {
  return {
    ...emptyFormalEventReadModel(options.teamId, options.runId),
    generation: state.generation + 1,
  };
}

export function applyFormalEvent(
  state: FormalEventReadModel,
  event: WorkflowEventEnvelope,
): FormalEventReadModel {
  if (state.resyncRequired) {
    return state;
  }
  if (event.runId !== state.runId || event.teamId !== state.teamId) {
    return state;
  }
  const eventId = String(event.eventId || "").trim();
  if (eventId && state.seenEventIds[eventId]) {
    return state;
  }
  const sequence = Number(event.sequence);
  if (!Number.isFinite(sequence) || sequence <= 0) {
    return state;
  }
  if (sequence <= state.lastSequence) {
    return state;
  }
  if (sequence > state.lastSequence + 1) {
    return { ...state, resyncRequired: true };
  }
  const seenEventIds = eventId
    ? { ...state.seenEventIds, [eventId]: true as const }
    : state.seenEventIds;
  return {
    ...state,
    events: [...state.events, event],
    lastSequence: sequence,
    seenEventIds,
  };
}

export function applyFormalEventBatch(
  state: FormalEventReadModel,
  events: WorkflowEventEnvelope[],
): FormalEventReadModel {
  return events.reduce((current, event) => applyFormalEvent(current, event), state);
}

export function acceptFormalGeneration(
  state: FormalEventReadModel,
  generation: number,
): boolean {
  return state.generation === generation;
}

/* -------------------------------------------------------------------------- */
/* Legacy helpers retained for pre-T7 pages (not a conversion layer).         */
/* -------------------------------------------------------------------------- */

export type WorkflowEventLike = {
  eventId?: string;
  sequence?: number;
  [key: string]: unknown;
};

export type EventReadModelState = {
  events: WorkflowEventLike[];
  lastSequence: number;
  runId: string;
};

export function emptyEventReadModel(runId = ""): EventReadModelState {
  return { events: [], lastSequence: 0, runId };
}

function eventKey(event: WorkflowEventLike): string {
  const id = String(event.eventId || "").trim();
  if (id) return `id:${id}`;
  const seq = Number(event.sequence);
  if (Number.isFinite(seq) && seq > 0) return `seq:${seq}`;
  return `anon:${JSON.stringify(event)}`;
}

export function mergeEventsByIdentity(
  existing: WorkflowEventLike[],
  incoming: WorkflowEventLike[],
): WorkflowEventLike[] {
  const map = new Map<string, WorkflowEventLike>();
  for (const event of existing) {
    map.set(eventKey(event), event);
  }
  for (const event of incoming) {
    map.set(eventKey(event), event);
  }
  return [...map.values()].sort((a, b) => {
    const sa = Number(a.sequence) || 0;
    const sb = Number(b.sequence) || 0;
    if (sa !== sb) return sa - sb;
    return String(a.eventId || "").localeCompare(String(b.eventId || ""));
  });
}

export function maxSequence(events: WorkflowEventLike[]): number {
  return events.reduce((max, evt) => Math.max(max, Number(evt.sequence) || 0), 0);
}

export function applyEventBatch(
  state: EventReadModelState,
  options: {
    runId: string;
    events?: WorkflowEventLike[] | null;
    replace?: boolean;
  },
): EventReadModelState {
  const runId = String(options.runId || "");
  const base = runId && state.runId === runId ? state : emptyEventReadModel(runId);
  const incoming = Array.isArray(options.events) ? options.events : [];
  const merged = options.replace
    ? mergeEventsByIdentity([], incoming)
    : mergeEventsByIdentity(base.events, incoming);
  return {
    runId,
    events: merged,
    lastSequence: maxSequence(merged),
  };
}

export function applyInitialRunEvents(
  runId: string,
  recordEvents: WorkflowEventLike[] | null | undefined,
  incrementalEvents: WorkflowEventLike[] | null | undefined,
): EventReadModelState {
  const fromRecord = Array.isArray(recordEvents) ? recordEvents : [];
  const fromIncremental = Array.isArray(incrementalEvents) ? incrementalEvents : [];
  return applyEventBatch(emptyEventReadModel(runId), {
    runId,
    events: [...fromRecord, ...fromIncremental],
    replace: true,
  });
}
