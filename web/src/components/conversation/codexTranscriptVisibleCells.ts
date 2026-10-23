import {
  dedupeCodexTranscriptCellsForDisplay,
  settleCodexTranscriptActiveStatuses,
  type CodexTranscriptCell,
} from "./codexTranscriptCells";

/**
 * Visible transcript cells come out of a four-stage chain: drop user rows,
 * settle still-running statuses, then the thought/tool/progress dedupe passes.
 *
 * The chain is pure and reads only the cell list plus the streaming flag, yet it
 * used to run again on every render of every turn row. A transcript surface
 * keeps its cells array reference stable across renders because
 * `buildCodexTranscriptCells` caches by message, so the projected result can be
 * memoized on that identity instead of being recomputed.
 */
const projectedCellsCache = new WeakMap<
  CodexTranscriptCell[],
  { turnStreaming: boolean; cells: CodexTranscriptCell[] }
>();

export function projectVisibleTranscriptCells(
  cells: CodexTranscriptCell[],
  turnStreaming: boolean,
): CodexTranscriptCell[] {
  const cached = projectedCellsCache.get(cells);
  if (cached && cached.turnStreaming === turnStreaming) {
    return cached.cells;
  }
  const projected = dedupeCodexTranscriptCellsForDisplay(
    settleCodexTranscriptActiveStatuses(
      cells.filter((cell) => cell.kind !== "user"),
      { turnStreaming },
    ),
  );
  projectedCellsCache.set(cells, { turnStreaming, cells: projected });
  return projected;
}
