import type { CodexTranscriptCell } from "./codexTranscriptCells";

export type CodexTranscriptToolActivity = {
  id: string;
  cells: readonly CodexTranscriptCell[];
};

export type CodexTranscriptTimelineNode =
  | {
    kind: "cell";
    cell: CodexTranscriptCell;
  }
  | {
    kind: "tool_activity";
    activity: CodexTranscriptToolActivity;
  };

function isToolActivityCell(cell: CodexTranscriptCell) {
  return cell.kind === "tool_call";
}

function shouldIsolateToolCell(cell: CodexTranscriptCell) {
  return cell.status === "failed" || cell.status === "degraded" || cell.tone === "warning" || cell.tone === "error";
}

export function createCodexTranscriptToolActivity(cells: readonly CodexTranscriptCell[]): CodexTranscriptToolActivity {
  const firstCell = cells[0];
  if (!firstCell) {
    throw new Error("A tool activity requires at least one transcript cell.");
  }
  return {
    // The first canonical cell is stable while streaming appends later calls.
    id: `tool-activity:${firstCell.id}`,
    cells,
  };
}

/**
 * Preserves canonical cell order while replacing only contiguous, non-terminal
 * tool cells with a frontend-only activity node. Commentary, warnings, errors,
 * approvals and final answers always flush the pending tool sequence.
 */
export function buildCodexTranscriptTimelineNodes(
  cells: readonly CodexTranscriptCell[],
): CodexTranscriptTimelineNode[] {
  const nodes: CodexTranscriptTimelineNode[] = [];
  let pendingTools: CodexTranscriptCell[] = [];

  const flushPendingTools = () => {
    if (pendingTools.length === 0) {
      return;
    }
    nodes.push({
      kind: "tool_activity",
      activity: createCodexTranscriptToolActivity(pendingTools),
    });
    pendingTools = [];
  };

  for (const cell of cells) {
    if (!isToolActivityCell(cell)) {
      flushPendingTools();
      nodes.push({ kind: "cell", cell });
      continue;
    }
    if (shouldIsolateToolCell(cell)) {
      flushPendingTools();
      nodes.push({
        kind: "tool_activity",
        activity: createCodexTranscriptToolActivity([cell]),
      });
      continue;
    }
    pendingTools.push(cell);
  }
  flushPendingTools();
  return nodes;
}

export function codexTranscriptToolRawName(cell: CodexTranscriptCell) {
  const rawToolName = cell.toolLifecycleModel?.toolCalls?.[0]?.rawToolName?.trim() || "";
  // Some normalized lifecycle projections retain the generic event kind while
  // the canonical cell title still carries the real tool identity.
  if (rawToolName && rawToolName !== "tool_call" && rawToolName !== "tool") {
    return rawToolName;
  }
  return cell.title?.trim() || rawToolName;
}

export function codexTranscriptToolDurationSeconds(cell: CodexTranscriptCell) {
  const terminalDuration = cell.toolLifecycleModel?.terminalOperations
    ?.map((operation) => operation.durationSeconds)
    .find((duration): duration is number => typeof duration === "number" && Number.isFinite(duration) && duration >= 0);
  if (terminalDuration !== undefined) {
    return terminalDuration;
  }
  const rolloutDuration = cell.rolloutTraceEvents
    ?.filter((event) => event.kind === "RuntimeEnded" || event.kind === "ToolCallEnded")
    .map((event) => event.durationSeconds)
    .find((duration): duration is number => typeof duration === "number" && Number.isFinite(duration) && duration >= 0);
  return rolloutDuration ?? null;
}

export function formatCodexTranscriptDuration(seconds: number) {
  if (seconds < 1) {
    return `${Math.max(1, Math.round(seconds * 1000))}ms`;
  }
  if (seconds >= 60) {
    const minutes = Math.floor(seconds / 60);
    const remainder = Math.round(seconds % 60);
    return remainder > 0 ? `${minutes}m ${remainder}s` : `${minutes}m`;
  }
  return `${Number(seconds.toFixed(seconds < 10 ? 1 : 0))}s`;
}
