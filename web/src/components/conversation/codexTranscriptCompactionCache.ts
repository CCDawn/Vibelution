import {
  compactCodexTranscriptCellsAcrossMessages,
  type CodexTranscriptCell,
  type CodexTranscriptCellMessageGroup,
} from "./codexTranscriptCells";

/**
 * Memoized result of one cross-message compaction pass.
 *
 * `groups` keeps the exact inputs that produced `cellsByMessageId` so the next
 * frame can prove which prefix is still valid.
 */
export type CodexTranscriptCompactionCache = {
  groups: readonly CodexTranscriptCellMessageGroup[];
  cellsByMessageId: Map<string, CodexTranscriptCell[]>;
};

/**
 * Compaction is one forward pass whose only cross-message state
 * (`precedingCells`) is cleared at every `barrier` (a user row). A changed
 * group can therefore only influence groups up to the next barrier, and any
 * group before the nearest preceding barrier is independent of it.
 *
 * Streaming frames change only the active turn, so re-using the prefix keeps
 * each frame proportional to that turn instead of to the whole transcript.
 * Returning the previous cache object when nothing changed also keeps the
 * downstream row memo reference-stable.
 */
export function compactCodexTranscriptCellsIncrementally(
  previous: CodexTranscriptCompactionCache | null,
  groups: readonly CodexTranscriptCellMessageGroup[],
): CodexTranscriptCompactionCache {
  if (previous) {
    const changedIndex = firstChangedGroupIndex(previous.groups, groups);
    if (changedIndex < 0) {
      return previous;
    }
    const startIndex = compactionSegmentStartIndex(groups, changedIndex);
    if (startIndex > 0) {
      return {
        groups,
        cellsByMessageId: mergeCompactedSegment(
          previous.cellsByMessageId,
          groups,
          startIndex,
        ),
      };
    }
  }
  return {
    groups,
    cellsByMessageId: compactCodexTranscriptCellsAcrossMessages(groups),
  };
}

/**
 * Index of the first group whose inputs differ, or -1 when the whole list is
 * unchanged. Identity of the group object is irrelevant: the caller rebuilds
 * the array every frame, while `cells` arrays stay reference-stable whenever
 * `buildCodexTranscriptCells` served them from its own cache.
 */
function firstChangedGroupIndex(
  previousGroups: readonly CodexTranscriptCellMessageGroup[],
  groups: readonly CodexTranscriptCellMessageGroup[],
) {
  if (previousGroups.length !== groups.length) {
    return 0;
  }
  for (let index = 0; index < groups.length; index += 1) {
    const previous = previousGroups[index];
    const next = groups[index];
    if (previous.messageId !== next.messageId) {
      return 0;
    }
    if (Boolean(previous.barrier) !== Boolean(next.barrier)) {
      return 0;
    }
    if (previous.cells !== next.cells) {
      return index;
    }
  }
  return -1;
}

/**
 * Walk back to the nearest barrier at or before the changed group. That group
 * clears the compaction state on entry, so recomputing from it yields the same
 * result as a full pass.
 */
function compactionSegmentStartIndex(
  groups: readonly CodexTranscriptCellMessageGroup[],
  changedIndex: number,
) {
  for (let index = changedIndex; index >= 0; index -= 1) {
    if (groups[index].barrier) {
      return index;
    }
  }
  return 0;
}

function mergeCompactedSegment(
  previousCellsByMessageId: Map<string, CodexTranscriptCell[]>,
  groups: readonly CodexTranscriptCellMessageGroup[],
  startIndex: number,
) {
  const cellsByMessageId = new Map<string, CodexTranscriptCell[]>();
  for (let index = 0; index < startIndex; index += 1) {
    const group = groups[index];
    const cached = previousCellsByMessageId.get(group.messageId);
    if (cached) {
      cellsByMessageId.set(group.messageId, cached);
    }
  }
  const recomputed = compactCodexTranscriptCellsAcrossMessages(groups.slice(startIndex));
  for (const [messageId, cells] of recomputed) {
    cellsByMessageId.set(messageId, cells);
  }
  return cellsByMessageId;
}
