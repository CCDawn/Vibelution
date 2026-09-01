import type { WorkflowEventEnvelope } from "../types/research-workflow/events";
import { detectUiLanguage, fetchJson, fetchWithControl } from "../client";

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
  return fetchJson<EventPage>(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}/events?${qs.toString()}`,
    { signal: options.signal },
  );
}

const MAX_REPLAY_PAGES = 32;

/**
 * Replay failures still surface through the run panel's error slot, but the
 * raw transport codes read like gibberish to operators; translate them into
 * the consequence plus the remediation instead.
 */
const REPLAY_ERROR_LABELS: Record<string, { zh: string; en: string }> = {
  events_replay_truncated: {
    zh: "历史事件过多，回放已截断，时间线可能不完整；最新状态以快照为准",
    en: "Too many historical events: the replay was truncated and the timeline may be incomplete. The latest state is authoritative in the snapshot.",
  },
  events_replay_cursor_stuck: {
    zh: "事件回放游标停滞，建议刷新页面获取最新状态",
    en: "The event replay cursor stopped advancing; refresh the page to load the latest state.",
  },
};

function replayError(code: keyof typeof REPLAY_ERROR_LABELS): Error {
  const label = REPLAY_ERROR_LABELS[code];
  return new Error(detectUiLanguage() === "en" ? label.en : label.zh);
}

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
      throw replayError("events_replay_cursor_stuck");
    }
    afterSequence = page.nextAfterSequence;
  }
  throw replayError("events_replay_truncated");
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

export type ResearchWorkflowSseFrame = {
  id: string;
  event: string;
  data: string;
};

export function parseResearchWorkflowSseFrame(rawFrame: string): ResearchWorkflowSseFrame | null {
  let id = "";
  let event = "message";
  const data: string[] = [];
  for (const line of rawFrame.split(/\r?\n/)) {
    if (!line || line.startsWith(":")) continue;
    const separator = line.indexOf(":");
    const field = separator >= 0 ? line.slice(0, separator) : line;
    let value = separator >= 0 ? line.slice(separator + 1) : "";
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "id") id = value;
    else if (field === "event") event = value || "message";
    else if (field === "data") data.push(value);
  }
  if (data.length === 0) return null;
  return { id, event, data: data.join("\n") };
}

function splitCompleteSseFrames(buffer: string): { frames: string[]; rest: string } {
  const frames: string[] = [];
  let rest = buffer;
  while (true) {
    const boundary = /\r?\n\r?\n/.exec(rest);
    if (!boundary || boundary.index == null) break;
    frames.push(rest.slice(0, boundary.index));
    rest = rest.slice(boundary.index + boundary[0].length);
  }
  return { frames, rest };
}

export async function consumeResearchWorkflowEventStream(options: {
  runId: string;
  teamId: string;
  afterSequence: number;
  lastEventId?: string;
  signal: AbortSignal;
  onOpen?: () => void;
  onFrame: (frame: ResearchWorkflowSseFrame) => void;
}): Promise<void> {
  const headers = new Headers({ Accept: "text/event-stream" });
  const lastEventId = String(options.lastEventId || "").trim();
  if (lastEventId) headers.set("Last-Event-ID", lastEventId);
  const response = await fetchWithControl(
    researchWorkflowStreamUrl({
      runId: options.runId,
      teamId: options.teamId,
      afterSequence: options.afterSequence,
    }),
    { headers, signal: options.signal },
  );
  if (!response.body) throw new Error("工作流实时连接没有返回事件流");
  options.onOpen?.();

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parsed = splitCompleteSseFrames(buffer);
      buffer = parsed.rest;
      for (const rawFrame of parsed.frames) {
        const frame = parseResearchWorkflowSseFrame(rawFrame);
        if (frame) options.onFrame(frame);
      }
    }
    buffer += decoder.decode();
    const parsed = splitCompleteSseFrames(buffer);
    for (const rawFrame of parsed.frames) {
      const frame = parseResearchWorkflowSseFrame(rawFrame);
      if (frame) options.onFrame(frame);
    }
  } finally {
    reader.releaseLock();
  }
}
