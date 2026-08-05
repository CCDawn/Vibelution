import { describe, expect, it } from "vitest";

import {
  agentMessageTimelineRowIdentityIsEqual,
  conversationPerformanceNowMs,
  transcriptCellSequenceMatches,
} from "./conversationTurnRowMemo";

describe("conversationTurnRowMemo", () => {
  it("matches identical transcript cell sequences by reference", () => {
    const cell = { id: "a" } as any;
    expect(transcriptCellSequenceMatches([cell], [cell])).toBe(true);
    expect(transcriptCellSequenceMatches([cell], [{ id: "a" } as any])).toBe(false);
  });

  it("compares timeline row identities", () => {
    const base = {
      messageId: "m1",
      rowKey: "r1",
      messageKey: "k1",
      processKey: "p1",
      answerKey: "a1",
    };
    expect(agentMessageTimelineRowIdentityIsEqual(base, { ...base })).toBe(true);
    expect(agentMessageTimelineRowIdentityIsEqual(base, { ...base, answerKey: "a2" })).toBe(false);
  });

  it("returns a finite performance clock", () => {
    expect(Number.isFinite(conversationPerformanceNowMs())).toBe(true);
  });
});
