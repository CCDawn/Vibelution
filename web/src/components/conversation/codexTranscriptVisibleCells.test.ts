import { describe, expect, it } from "vitest";

import {
  dedupeCodexTranscriptCellsForDisplay,
  settleCodexTranscriptActiveStatuses,
  type CodexTranscriptCell,
} from "./codexTranscriptCells";
import { projectVisibleTranscriptCells } from "./codexTranscriptVisibleCells";

function markdownCell(id: string, overrides: Record<string, unknown> = {}): CodexTranscriptCell {
  return {
    id,
    kind: "assistant_markdown",
    messageId: "message-1",
    status: "completed",
    tone: "neutral",
    text: id,
    ...overrides,
  } as unknown as CodexTranscriptCell;
}

function uncachedProjection(cells: CodexTranscriptCell[], turnStreaming: boolean) {
  return dedupeCodexTranscriptCellsForDisplay(
    settleCodexTranscriptActiveStatuses(
      cells.filter((cell) => cell.kind !== "user"),
      { turnStreaming },
    ),
  );
}

describe("projectVisibleTranscriptCells", () => {
  it("reuses the settled projection while the cell list identity is stable", () => {
    const cells = [markdownCell("a"), markdownCell("b")];

    const first = projectVisibleTranscriptCells(cells, false);
    const second = projectVisibleTranscriptCells(cells, false);

    expect(second).toBe(first);
  });

  it("recomputes when the streaming flag flips on the same cell list", () => {
    const cells = [markdownCell("a")];

    const idle = projectVisibleTranscriptCells(cells, false);
    const streaming = projectVisibleTranscriptCells(cells, true);

    expect(streaming).not.toBe(idle);
  });

  it("keeps a fresh cell array independent of the cached one", () => {
    const first = projectVisibleTranscriptCells([markdownCell("a")], false);
    const second = projectVisibleTranscriptCells([markdownCell("a")], false);

    expect(second).not.toBe(first);
    expect(second).toEqual(first);
  });

  it("drops user rows and matches the uncached chain", () => {
    const cells = [markdownCell("a"), markdownCell("user-row", { kind: "user" })];

    const projected = projectVisibleTranscriptCells(cells, false);
    const expected = uncachedProjection(cells, false);

    expect(projected.map((cell) => cell.id)).toEqual(expected.map((cell) => cell.id));
    expect(projected.some((cell) => cell.kind === "user")).toBe(false);
  });
});
