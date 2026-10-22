import { describe, expect, it } from "vitest";

import {
  compactCodexTranscriptCellsAcrossMessages,
  type CodexTranscriptCell,
  type CodexTranscriptCellMessageGroup,
} from "./codexTranscriptCells";
import { compactCodexTranscriptCellsIncrementally } from "./codexTranscriptCompactionCache";

function cell(
  id: string,
  messageId: string,
  overrides: Partial<CodexTranscriptCell> = {},
): CodexTranscriptCell {
  return {
    id,
    kind: "assistant_markdown",
    messageId,
    status: "completed",
    tone: "neutral",
    ...overrides,
  };
}

function group(
  messageId: string,
  cells: CodexTranscriptCell[],
  barrier = false,
): CodexTranscriptCellMessageGroup {
  return { messageId, cells, barrier };
}

function userCell(messageId: string) {
  return cell(messageId, messageId, { kind: "user" });
}

describe("codex transcript compaction cache", () => {
  it("runs a full pass for the first frame", () => {
    const groups = [
      group("u1", [userCell("u1")], true),
      group("a1", [cell("a1", "a1")]),
    ];

    const cache = compactCodexTranscriptCellsIncrementally(null, groups);

    expect([...cache.cellsByMessageId.keys()]).toEqual(["u1", "a1"]);
    expect(cache.cellsByMessageId).toEqual(compactCodexTranscriptCellsAcrossMessages(groups));
  });

  it("reuses the previous cache object when every group input is unchanged", () => {
    const first = [
      group("u1", [userCell("u1")], true),
      group("a1", [cell("a1", "a1")]),
    ];
    const cache = compactCodexTranscriptCellsIncrementally(null, first);

    // The caller rebuilds the group array every frame while the cell arrays
    // stay reference-stable, so only the array wrapper is new here.
    const next = [
      group("u1", [userCell("u1")], true),
      group("a1", [cell("a1", "a1")]),
    ];
    next[0] = { ...next[0], cells: first[0].cells };
    next[1] = { ...next[1], cells: first[1].cells };

    expect(compactCodexTranscriptCellsIncrementally(cache, next)).toBe(cache);
  });

  it("recomputes only the segment after the nearest user barrier", () => {
    const historyUserCells = [userCell("u1")];
    const historyAssistantCells = [cell("a1", "a1")];
    const activeUserCells = [userCell("u2")];
    const firstActiveCells = [cell("a2-old", "a2")];

    const cache = compactCodexTranscriptCellsIncrementally(null, [
      group("u1", historyUserCells, true),
      group("a1", historyAssistantCells),
      group("u2", activeUserCells, true),
      group("a2", firstActiveCells),
    ]);

    const streamingCells = [cell("a2-new", "a2")];
    const next = compactCodexTranscriptCellsIncrementally(cache, [
      group("u1", historyUserCells, true),
      group("a1", historyAssistantCells),
      group("u2", activeUserCells, true),
      group("a2", streamingCells),
    ]);

    // History before the active turn keeps its exact result arrays.
    expect(next.cellsByMessageId.get("u1")).toBe(cache.cellsByMessageId.get("u1"));
    expect(next.cellsByMessageId.get("a1")).toBe(cache.cellsByMessageId.get("a1"));
    // The active turn and its barrier are recomputed.
    expect(next.cellsByMessageId.get("u2")).not.toBe(cache.cellsByMessageId.get("u2"));
    expect(next.cellsByMessageId.get("a2")).not.toBe(cache.cellsByMessageId.get("a2"));
    expect(next.cellsByMessageId.get("a2")?.map((entry) => entry.id)).toEqual(["a2-new"]);
  });

  it("matches the full pass for every message after an incremental frame", () => {
    const historyUserCells = [userCell("u1")];
    const historyAssistantCells = [cell("a1", "a1")];
    const activeUserCells = [userCell("u2")];

    const cache = compactCodexTranscriptCellsIncrementally(null, [
      group("u1", historyUserCells, true),
      group("a1", historyAssistantCells),
      group("u2", activeUserCells, true),
      group("a2", [cell("a2-old", "a2")]),
    ]);

    const nextGroups = [
      group("u1", historyUserCells, true),
      group("a1", historyAssistantCells),
      group("u2", activeUserCells, true),
      group("a2", [cell("a2-new", "a2")]),
    ];
    const next = compactCodexTranscriptCellsIncrementally(cache, nextGroups);

    expect(next.cellsByMessageId).toEqual(compactCodexTranscriptCellsAcrossMessages(nextGroups));
  });

  it("falls back to a full pass when the message list identity changes", () => {
    const cache = compactCodexTranscriptCellsIncrementally(null, [
      group("u1", [userCell("u1")], true),
      group("a1", [cell("a1", "a1")]),
    ]);

    const nextGroups = [
      group("u1", [userCell("u1")], true),
      group("a9", [cell("a9", "a9")]),
    ];
    const next = compactCodexTranscriptCellsIncrementally(cache, nextGroups);

    expect([...next.cellsByMessageId.keys()]).toEqual(["u1", "a9"]);
    expect(next.cellsByMessageId).toEqual(compactCodexTranscriptCellsAcrossMessages(nextGroups));
  });

  it("treats a changed barrier flag as a full pass", () => {
    const cache = compactCodexTranscriptCellsIncrementally(null, [
      group("u1", [userCell("u1")], true),
      group("a1", [cell("a1", "a1")]),
    ]);

    const nextGroups = [
      group("u1", [userCell("u1")], false),
      group("a1", [cell("a1", "a1")]),
    ];
    const next = compactCodexTranscriptCellsIncrementally(cache, nextGroups);

    expect(next.cellsByMessageId).toEqual(compactCodexTranscriptCellsAcrossMessages(nextGroups));
  });
});
