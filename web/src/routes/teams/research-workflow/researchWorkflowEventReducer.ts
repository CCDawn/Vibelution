/**
 * Single owner for research workflow event merge / dedupe.
 * Used by the hook and future SSE apply path (applyEventBatch).
 */

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

/**
 * Merge events by eventId (preferred) or sequence; keep order by sequence then eventId.
 */
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

/**
 * Unified batch apply entry (polling + future SSE).
 * - Resets when runId changes
 * - Dedupes by eventId/sequence
 * - Does not invent a second run status authority
 */
export function applyEventBatch(
  state: EventReadModelState,
  options: {
    runId: string;
    events?: WorkflowEventLike[] | null;
    /** When true, treat `events` as the full authority list for this run. */
    replace?: boolean;
  },
): EventReadModelState {
  const runId = String(options.runId || "");
  const base =
    runId && state.runId === runId
      ? state
      : emptyEventReadModel(runId);

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

/**
 * Initial load: full record.events is authority; do not also concat the same
 * incremental page without dedupe (avoids 3 → 6 duplicates).
 */
export function applyInitialRunEvents(
  runId: string,
  recordEvents: WorkflowEventLike[] | null | undefined,
  incrementalEvents: WorkflowEventLike[] | null | undefined,
): EventReadModelState {
  const fromRecord = Array.isArray(recordEvents) ? recordEvents : [];
  const fromIncremental = Array.isArray(incrementalEvents) ? incrementalEvents : [];
  // Prefer record as base; merge incremental for any extra newer events only.
  return applyEventBatch(emptyEventReadModel(runId), {
    runId,
    events: [...fromRecord, ...fromIncremental],
    replace: true,
  });
}
