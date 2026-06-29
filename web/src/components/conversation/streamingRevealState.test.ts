import { describe, expect, it } from "vitest";

import {
  appendStableText,
  EMPTY_STREAMING_REVEAL_STATE,
  nextStreamingRevealLength,
  streamingRevealText,
  STREAMING_RESPONSE_CATCH_UP_BACKLOG_CHARS,
  STREAMING_RESPONSE_CATCH_UP_MAX_CHARS,
  STREAMING_RESPONSE_REVEAL_MAX_CHARS,
  STREAMING_RESPONSE_STABLE_TAIL_CHARS,
} from "./streamingRevealState";

describe("streaming reveal state", () => {
  it("keeps a stable prefix and a bounded mutable reveal tail", () => {
    const content = "x".repeat(STREAMING_RESPONSE_STABLE_TAIL_CHARS + 12);
    const state = appendStableText(EMPTY_STREAMING_REVEAL_STATE, content);

    expect(state.stableText).toHaveLength(12);
    expect(state.revealTail).toHaveLength(STREAMING_RESPONSE_STABLE_TAIL_CHARS);
    expect(streamingRevealText(state)).toBe(content);
  });

  it("advances small backlogs smoothly instead of revealing everything at once", () => {
    const nextLength = nextStreamingRevealLength(10, 80);

    expect(nextLength).toBeGreaterThan(10);
    expect(nextLength - 10).toBeLessThanOrEqual(STREAMING_RESPONSE_REVEAL_MAX_CHARS);
    expect(nextLength).toBeLessThan(80);
  });

  it("switches to catch-up steps for large accumulated backlogs", () => {
    const nextLength = nextStreamingRevealLength(0, STREAMING_RESPONSE_CATCH_UP_BACKLOG_CHARS + 200);

    expect(nextLength).toBe(STREAMING_RESPONSE_CATCH_UP_MAX_CHARS);
  });
});
