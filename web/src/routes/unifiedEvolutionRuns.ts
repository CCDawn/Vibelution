import type {
  EvolutionActiveRun,
  SelfEvolutionAutonomousLoopRun,
  SelfEvolutionWorkspaceSnapshot,
  SelfObservationRun,
  SupervisedWorktreeRun,
} from "../api/types";
import { isSelfEvolutionWorktreeRun } from "./supervisedWorktreeReview";

export type UnifiedEvolutionTrack = "supervised" | "self";
export type UnifiedEvolutionRunKind = "worktree" | "session" | "autonomous" | "observation";

export type UnifiedEvolutionRun = {
  key: string;
  track: UnifiedEvolutionTrack;
  kind: UnifiedEvolutionRunKind;
  runId: string;
  title: string;
  status: string;
  worktreeRun?: SupervisedWorktreeRun;
  activeRun?: EvolutionActiveRun;
  autonomousRun?: SelfEvolutionAutonomousLoopRun;
  observationRun?: SelfObservationRun;
};

export type BuildUnifiedEvolutionRunsInput = {
  supervisedWorktreeRuns: SupervisedWorktreeRun[];
  supervisedActiveWorktreeRun?: SupervisedWorktreeRun | null;
  supervisedActiveRun?: EvolutionActiveRun | null;
  supervisedLatestRun?: EvolutionActiveRun | null;
  selfSnapshot?: SelfEvolutionWorkspaceSnapshot;
  observationRun?: SelfObservationRun | null;
};

const ACTIVE_STATUSES = new Set(["queued", "running", "paused", "stopping"]);

function normalizedText(value: unknown): string {
  return String(value ?? "").trim();
}

function datasetOrBundleTitle(
  sourceKind: unknown,
  datasetName: unknown,
  bundleName: unknown,
  fallback: string,
): string {
  const dataset = normalizedText(datasetName);
  const bundle = normalizedText(bundleName);
  const preferred = normalizedText(sourceKind).toLowerCase() === "bundle" ? bundle : dataset;
  return preferred || dataset || bundle || fallback;
}

function worktreeRow(run: SupervisedWorktreeRun, track: UnifiedEvolutionTrack): UnifiedEvolutionRun {
  const selfGoal = normalizedText(run.selfEvolutionOrigin?.goal);
  return {
    key: `${track}:worktree:${run.runId}`,
    track,
    kind: "worktree",
    runId: run.runId,
    title: track === "self" && selfGoal
      ? selfGoal
      : datasetOrBundleTitle(run.sourceKind, run.datasetName, run.bundleName, run.runId),
    status: normalizedText(run.status),
    worktreeRun: run,
  };
}

function sessionRow(run: EvolutionActiveRun): UnifiedEvolutionRun {
  return {
    key: `supervised:session:${run.runId}`,
    track: "supervised",
    kind: "session",
    runId: run.runId,
    title: datasetOrBundleTitle(run.sourceKind, run.datasetName, run.bundleName, run.runId),
    status: normalizedText(run.status),
    activeRun: run,
  };
}

function autonomousRow(run: SelfEvolutionAutonomousLoopRun): UnifiedEvolutionRun {
  return {
    key: `self:autonomous:${run.runId}`,
    track: "self",
    kind: "autonomous",
    runId: run.runId,
    title: normalizedText(run.request?.goal) || run.runId,
    status: normalizedText(run.status),
    autonomousRun: run,
  };
}

function observationRow(run: SelfObservationRun): UnifiedEvolutionRun {
  return {
    key: `self:observation:${run.runId}`,
    track: "self",
    kind: "observation",
    runId: run.runId,
    title: normalizedText(run.goal) || run.runId,
    status: normalizedText(run.status),
    observationRun: run,
  };
}

export function buildUnifiedEvolutionRuns({
  supervisedWorktreeRuns,
  supervisedActiveWorktreeRun,
  supervisedActiveRun,
  supervisedLatestRun,
  selfSnapshot,
  observationRun,
}: BuildUnifiedEvolutionRunsInput): UnifiedEvolutionRun[] {
  const rows: UnifiedEvolutionRun[] = [];
  const rowIndexByKey = new Map<string, number>();
  const priorityByKey = new Map<string, number>();

  const add = (row: UnifiedEvolutionRun, priority: number) => {
    const existingIndex = rowIndexByKey.get(row.key);
    if (existingIndex === undefined) {
      rowIndexByKey.set(row.key, rows.length);
      priorityByKey.set(row.key, priority);
      rows.push(row);
      return;
    }
    if (priority > (priorityByKey.get(row.key) ?? 0)) {
      rows[existingIndex] = row;
      priorityByKey.set(row.key, priority);
    }
  };

  // Add active snapshots first so they appear ahead of history rows; a later
  // duplicate summary cannot replace their full run payload.
  if (supervisedActiveWorktreeRun) {
    add(worktreeRow(
      supervisedActiveWorktreeRun,
      isSelfEvolutionWorktreeRun(supervisedActiveWorktreeRun) ? "self" : "supervised",
    ), 3);
  }
  if (selfSnapshot?.worktreeActiveRun) {
    add(worktreeRow(selfSnapshot.worktreeActiveRun, "self"), 3);
  }
  if (supervisedActiveRun) {
    add(sessionRow(supervisedActiveRun), 3);
  }
  if (selfSnapshot?.autonomousActiveRun) {
    add(autonomousRow(selfSnapshot.autonomousActiveRun), 3);
  }
  if (selfSnapshot?.observationActiveRun) {
    add(observationRow(selfSnapshot.observationActiveRun), 3);
  }

  // The latest autonomous loop is the self-track default when there is no
  // active loop. Keep it ahead of older self worktree history in list order.
  if (supervisedLatestRun) {
    add(sessionRow(supervisedLatestRun), 1);
  }
  if (selfSnapshot?.autonomousLatestRun) {
    add(autonomousRow(selfSnapshot.autonomousLatestRun), 1);
  }
  if (observationRun) {
    add(observationRow(observationRun), 2);
  }

  for (const run of supervisedWorktreeRuns) {
    add(worktreeRow(run, isSelfEvolutionWorktreeRun(run) ? "self" : "supervised"), 1);
  }

  return rows;
}

export function selectUnifiedEvolutionRun(
  runs: UnifiedEvolutionRun[],
  track: UnifiedEvolutionTrack,
  selectedKey: string | null,
): UnifiedEvolutionRun | null {
  const trackRuns = runs.filter((run) => run.track === track);
  if (selectedKey !== null) {
    return trackRuns.find((run) => run.key === selectedKey) ?? null;
  }
  return trackRuns.find((run) => ACTIVE_STATUSES.has(run.status.toLowerCase()))
    ?? trackRuns[0]
    ?? null;
}
