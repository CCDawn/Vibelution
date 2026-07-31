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
  return cell.kind === "tool_call"
    || (cell.kind === "error_notice" && Boolean(cell.operationIds?.length));
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
 * Preserves canonical cell order while replacing contiguous tool work with a
 * frontend-only activity node. Operation-backed failures stay with the tools
 * they describe; narrative, system, approval and turn-level error cells remain
 * true timeline barriers.
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

function normalizeToolIdentity(value: string) {
  return value.trim().toLowerCase().replace(/[\s-]+/g, "_");
}

/** Whether a transcript tool cell matches a pending approval tool name. */
export function codexTranscriptCellMatchesToolName(
  cell: CodexTranscriptCell,
  toolName: string | null | undefined,
) {
  const expected = normalizeToolIdentity(String(toolName || ""));
  if (!expected) {
    return false;
  }
  const raw = normalizeToolIdentity(codexTranscriptToolRawName(cell));
  if (!raw) {
    return false;
  }
  return raw === expected
    || raw.endsWith(`_${expected}`)
    || expected.endsWith(`_${raw}`)
    || raw.includes(expected)
    || expected.includes(raw);
}

/**
 * Codex places approval under the active command. Prefer an open tool cell that
 * matches the pending tool name; otherwise the last open tool activity.
 */
export function shouldAttachToolApprovalToActivity(
  activity: CodexTranscriptToolActivity,
  toolName: string | null | undefined,
  options?: { preferAnyOpenWhenUnmatched?: boolean },
) {
  const openCells = activity.cells.filter(
    (cell) => cell.status === "running" || cell.status === "pending",
  );
  if (!openCells.length) {
    // Still attach when the approval is waiting and the cell briefly shows failed
    // after a timeout — prefer name match on any cell.
    if (toolName) {
      return activity.cells.some((cell) => codexTranscriptCellMatchesToolName(cell, toolName));
    }
    return false;
  }
  if (toolName) {
    const matched = openCells.some((cell) => codexTranscriptCellMatchesToolName(cell, toolName));
    if (matched) {
      return true;
    }
    return options?.preferAnyOpenWhenUnmatched === true;
  }
  return true;
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
