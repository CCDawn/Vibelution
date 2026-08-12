import type { WorkflowEventEnvelope } from "../types/research-workflow/events";

function requireTeamId(teamId: string): string {
  const normalized = String(teamId || "").trim();
  if (!normalized) {
    throw new Error("teamId is required");
  }
  return normalized;
}

export type EventPage = {
  runId: string;
  teamId: string;
  runVersion: number;
  latestEventSequence: number;
  afterSequence: number;
  lastReturnedSequence: number;
  hasMore: boolean;
  nextAfterSequence: number | null;
  events: WorkflowEventEnvelope[];
};

export async function fetchResearchWorkflowEvents(options: {
  runId: string;
  teamId: string;
  afterSequence?: number;
  signal?: AbortSignal;
}): Promise<EventPage> {
  const teamId = requireTeamId(options.teamId);
  const runId = String(options.runId || "").trim();
  const after = Number(options.afterSequence || 0);
  const qs = new URLSearchParams({
    teamId,
    afterSequence: String(Number.isFinite(after) ? after : 0),
  });
  const response = await fetch(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}/events?${qs.toString()}`,
    { signal: options.signal, headers: { Accept: "application/json" } },
  );
  if (!response.ok) {
    throw new Error(`events_http_${response.status}`);
  }
  return (await response.json()) as EventPage;
}

const MAX_REPLAY_PAGES = 32;

export async function replayResearchWorkflowEvents(options: {
  runId: string;
  teamId: string;
  signal?: AbortSignal;
}): Promise<WorkflowEventEnvelope[]> {
  const events: WorkflowEventEnvelope[] = [];
  let afterSequence = 0;
  for (let pageIndex = 0; pageIndex < MAX_REPLAY_PAGES; pageIndex += 1) {
    const page = await fetchResearchWorkflowEvents({
      runId: options.runId,
      teamId: options.teamId,
      afterSequence,
      signal: options.signal,
    });
    events.push(...(page.events ?? []));
    if (!page.hasMore || page.nextAfterSequence == null) {
      return events.sort((left, right) => left.sequence - right.sequence);
    }
    if (page.nextAfterSequence <= afterSequence) {
      throw new Error("events_replay_cursor_stuck");
    }
    afterSequence = page.nextAfterSequence;
  }
  throw new Error("events_replay_truncated");
}

export function researchWorkflowStreamUrl(options: {
  runId: string;
  teamId: string;
  afterSequence?: number;
}): string {
  const teamId = requireTeamId(options.teamId);
  const runId = String(options.runId || "").trim();
  const qs = new URLSearchParams({ teamId });
  if (options.afterSequence != null) {
    qs.set("afterSequence", String(options.afterSequence));
  }
  return `/api/research/workflow-runs/${encodeURIComponent(runId)}/stream?${qs.toString()}`;
}
