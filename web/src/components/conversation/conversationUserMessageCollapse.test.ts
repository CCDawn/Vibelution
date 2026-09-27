import { describe, expect, it } from "vitest";

import {
  shouldCollapseUserMessage,
  USER_MESSAGE_COLLAPSE_THRESHOLD_PX,
} from "./conversationUserMessageCollapse";

describe("conversationUserMessageCollapse", () => {
  it("keeps the ZCode-aligned collapse threshold at 120px", () => {
    expect(USER_MESSAGE_COLLAPSE_THRESHOLD_PX).toBe(120);
  });

  it("collapses only when the measured height exceeds the threshold", () => {
    expect(shouldCollapseUserMessage(0)).toBe(false);
    expect(shouldCollapseUserMessage(80)).toBe(false);
    expect(shouldCollapseUserMessage(USER_MESSAGE_COLLAPSE_THRESHOLD_PX)).toBe(false);
    expect(shouldCollapseUserMessage(USER_MESSAGE_COLLAPSE_THRESHOLD_PX + 1)).toBe(true);
    expect(shouldCollapseUserMessage(2000)).toBe(true);
  });
});
