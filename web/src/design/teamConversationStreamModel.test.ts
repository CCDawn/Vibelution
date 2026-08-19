import { describe, expect, it } from "vitest";

import { shouldCollapseGroupMessage } from "../routes/chat/chatRoutePresentation";
import {
  groupConsecutiveSpeakers,
  LONG_INTERNAL_COUNTER,
  LONG_INTERNAL_DISCUSSION,
  PREVIEW_SCENES,
  shouldClampStreamBody,
} from "./teamConversationStreamModel";

describe("team conversation stream model", () => {
  it("keeps the same length heuristic as the live group collapse rule", () => {
    expect(LONG_INTERNAL_DISCUSSION.length).toBeGreaterThan(260);
    expect(LONG_INTERNAL_COUNTER.length).toBeGreaterThan(260);
    expect(shouldClampStreamBody("short")).toBe(false);
    expect(shouldClampStreamBody("x".repeat(261))).toBe(true);
    expect(shouldClampStreamBody(LONG_INTERNAL_DISCUSSION)).toBe(true);
    expect(shouldClampStreamBody(LONG_INTERNAL_DISCUSSION)).toBe(
      shouldCollapseGroupMessage(LONG_INTERNAL_DISCUSSION),
    );
  });

  it("groups consecutive messages from the same speaker", () => {
    const groups = groupConsecutiveSpeakers(PREVIEW_SCENES.consecutive.messages);
    expect(groups).toHaveLength(2);
    expect(groups[0].map((message) => message.id)).toEqual(["c1", "c2", "c3"]);
    expect(groups[1].map((message) => message.id)).toEqual(["c4"]);
  });

  it("marks discuss-phase fixture messages as internal so the current column can hide them", () => {
    const discuss = PREVIEW_SCENES.discuss.messages.filter((message) => !message.pending);
    expect(discuss.every((message) => message.audience === "internal")).toBe(true);
    expect(discuss.every((message) => message.visibility === "collapsed_by_default")).toBe(true);
  });
});
