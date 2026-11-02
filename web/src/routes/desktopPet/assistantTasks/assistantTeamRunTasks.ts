import type { LauncherAssistantTeamRun, LauncherAssistantTeamRunsPage } from "../../../api/launcherAssistant";
import type { AssistantDispatchTask, AssistantDispatchTaskState } from "./assistantDispatchTasks";

/** A local association points to the owning team run; it is never an execution
 * store or evidence that the user's business goal has been accepted. */
type LastVerifiedTeamRunDisplay = {
  teamId: string;
  flowId: string;
  runId: string;
  revision: string | null;
  observedAt: string | null;
  title: string;
};

/** Query-cache presentation metadata only. Native wire fields stay unchanged. */
export type AssistantTeamRunObservation = LauncherAssistantTeamRun & { lastKnown?: LastVerifiedTeamRunDisplay };
export type AssistantTeamRunObservationPage = Omit<LauncherAssistantTeamRunsPage, "teamRuns"> & {
  teamRuns: AssistantTeamRunObservation[];
};

export type AssistantTeamRunTask = {
  kind: "team_run";
  id: string;
  projectId: string | null;
  requestId: string;
  originAction: "team_run" | "flow_start";
  sourceRefs: { requestId: string; originAction: "team_run" | "flow_start" }[];
  teamId: string | null;
  flowId: string | null;
  runId: string | null;
  nativeStatus: string | null;
  revision: string | null;
  observedAt: string | null;
  title: string;
  lastKnown: LastVerifiedTeamRunDisplay | null;
  state: Exclude<AssistantDispatchTaskState, "waiting_user"> | "waiting_input";
  shouldPoll: boolean;
  sourceAvailable: boolean;
  receiptBound: boolean;
  conflictingObservations: boolean;
  businessAcceptance: "not_evaluated";
};

export type AssistantTask = (AssistantDispatchTask & { kind: "dispatch" }) | AssistantTeamRunTask;

function identity(value: unknown): string | null {
  return typeof value === "string" && value.trim() && value.length <= 256 ? value : null;
}

function titleText(value: unknown): string {
  if (typeof value !== "string") return "";
  const text = value.replace(/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/g, " ").replace(/\s+/g, " ").trim();
  const characters = Array.from(text);
  return characters.length > 100 ? `${characters.slice(0, 99).join("")}…` : text;
}

function lastVerifiedDisplay(row: AssistantTeamRunObservation): LastVerifiedTeamRunDisplay | null {
  const teamId = identity(row.teamId), flowId = identity(row.flowId), runId = identity(row.runId);
  return row.readState === "ready" && teamId && flowId && runId
    ? { teamId, flowId, runId, revision: identity(row.revision), observedAt: identity(row.observedAt), title: titleText(row.title) }
    : row.lastKnown ?? null;
}

/** Retain display facts only for associations still present in this snapshot.
 * No old row or status is copied into the current native response. */
export function retainAssistantTeamRunDisplay(
  page: LauncherAssistantTeamRunsPage, previousPages: readonly AssistantTeamRunObservationPage[],
): AssistantTeamRunObservationPage {
  const key = (row: LauncherAssistantTeamRun) => JSON.stringify([row.projectId, row.originAction, row.requestId]);
  const previous = new Map(previousPages.filter(previousPage => previousPage.assistant.agentId === page.assistant.agentId
    && previousPage.assistant.directSessionId === page.assistant.directSessionId)
    .flatMap(previousPage => previousPage.teamRuns).map(row => [key(row), row]));
  return { ...page, teamRuns: page.teamRuns.map(row => {
    const prior = previous.get(key(row));
    const lastKnown = row.readState === "unknown" && prior ? lastVerifiedDisplay(prior) : null;
    return lastKnown ? { ...row, lastKnown } : row;
  }) };
}

function projectRow(row: AssistantTeamRunObservation, sourceAvailable: boolean): AssistantTeamRunTask {
  const projectId = identity(row.projectId);
  const teamId = identity(row.teamId);
  const flowId = identity(row.flowId);
  const runId = identity(row.runId);
  const hasReferences = Boolean(projectId && teamId && flowId && runId);
  const current = sourceAvailable && row.readState === "ready" && hasReferences;
  const lastKnown = current ? null : lastVerifiedDisplay(row);
  const group = hasReferences ? { teamId, flowId, runId } : lastKnown;
  const nativeStatus = current ? identity(row.status) : null;
  const state: AssistantTeamRunTask["state"] = !current ? "unknown"
    : nativeStatus === "running" ? "running"
      : nativeStatus === "waiting" ? "waiting_input"
        : nativeStatus === "completed" ? "awaiting_verification"
          : nativeStatus === "failed" ? "failed"
            : nativeStatus === "stopped" ? "stopped" : "unknown";
  return {
    kind: "team_run",
    id: group ? JSON.stringify([projectId, "team", group.teamId, group.flowId, group.runId])
      : JSON.stringify([projectId, row.originAction, row.requestId]),
    projectId, requestId: row.requestId, originAction: row.originAction,
    sourceRefs: [{ requestId: row.requestId, originAction: row.originAction }],
    teamId: current ? teamId : null, flowId: current ? flowId : null, runId: current ? runId : null,
    nativeStatus, revision: current ? identity(row.revision) : null, observedAt: current ? identity(row.observedAt) : null,
    title: titleText(row.title) || lastKnown?.title || "", lastKnown, state,
    shouldPoll: current && (state === "running" || state === "waiting_input"),
    sourceAvailable: sourceAvailable && row.readState === "ready", receiptBound: current,
    conflictingObservations: false, businessAcceptance: "not_evaluated",
  };
}

function fingerprint(task: AssistantTeamRunTask): string {
  // observedAt is the read time, not an ordering or conflict-resolution token.
  return JSON.stringify([task.teamId, task.flowId, task.runId,
    task.nativeStatus, task.revision, task.state, task.sourceAvailable, task.receiptBound]);
}

export function projectAssistantTeamRunTasks(
  rows: readonly AssistantTeamRunObservation[], options: { sourceAvailable?: boolean } = {},
): { tasks: AssistantTeamRunTask[]; invalidRecords: number } {
  const indexed = new Map<string, AssistantTeamRunTask>();
  let invalidRecords = 0;
  for (const row of rows) {
    if (!identity(row.requestId) || !identity(row.projectId)
      || !["team_run", "flow_start"].includes(row.originAction)) { invalidRecords += 1; continue; }
    const task = projectRow(row, options.sourceAvailable !== false);
    const previous = indexed.get(task.id);
    if (!previous) indexed.set(task.id, task);
    else {
      // Multiple assistant actions may refer to the same native run. Their
      // request IDs and optional display labels do not conflict with run facts.
      const sourceRefs = [...previous.sourceRefs];
      for (const reference of task.sourceRefs) {
        if (!sourceRefs.some(existing => existing.requestId === reference.requestId && existing.originAction === reference.originAction))
          sourceRefs.push(reference);
      }
      if (previous.conflictingObservations || fingerprint(previous) !== fingerprint(task)) {
        const lastKnown = previous.lastKnown ?? (previous.receiptBound && previous.teamId && previous.flowId && previous.runId
          ? { teamId: previous.teamId, flowId: previous.flowId, runId: previous.runId,
            revision: previous.revision, observedAt: previous.observedAt, title: previous.title } : task.lastKnown);
        indexed.set(task.id, { ...previous, sourceRefs, state: "unknown", nativeStatus: null, sourceAvailable: false,
          teamId: null, flowId: null, runId: null, revision: null, observedAt: null, lastKnown,
          receiptBound: false, conflictingObservations: true, shouldPoll: false });
      } else indexed.set(task.id, { ...previous, sourceRefs, title: previous.title || task.title });
    }
  }
  return { tasks: [...indexed.values()], invalidRecords };
}
