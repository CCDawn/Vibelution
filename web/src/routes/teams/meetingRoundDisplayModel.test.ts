import { describe, expect, it } from "vitest";

import {
  displayMeetingMessageText,
  isMachineAgentId,
  meetingMessageNeedsFullText,
  meetingSpeakerLabel,
} from "./meetingRoundDisplayModel";

describe("meetingRoundDisplayModel", () => {
  it("hides machine agent ids and prefers a human role", () => {
    expect(isMachineAgentId("agent-20260722-220514-082385")).toBe(true);
    expect(meetingSpeakerLabel({
      agentId: "agent-20260722-220514-082385",
      role: "评审",
    })).toBe("评审");
    expect(meetingSpeakerLabel({
      agentId: "agent-20260722-220514-082385",
    })).toBe("发言人");
    expect(meetingSpeakerLabel({ agentId: "白望舒" })).toBe("白望舒");
  });

  it("strips markdown markers so compact chrome is not source dumps", () => {
    expect(displayMeetingMessageText("**分布/密度组** artifactPath", { collapseWhitespace: true }))
      .toBe("分布/密度组 artifactPath");
    expect(displayMeetingMessageText("确认：\n\n- **下一步**", { collapseWhitespace: true }))
      .toBe("确认： - 下一步");
  });

  it("keeps long ledger dumps behind a full-text expander", () => {
    expect(meetingMessageNeedsFullText("短句")).toBe(false);
    expect(meetingMessageNeedsFullText("确认：\n本轮评审输入已闭合")).toBe(true);
    expect(meetingMessageNeedsFullText("a".repeat(81))).toBe(true);
  });
});
