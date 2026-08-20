import { describe, expect, it } from "vitest";

import {
  displayMeetingMessageText,
  isMachineAgentId,
  meetingDiscussionProgress,
  meetingMessageNeedsFullText,
  meetingSpeakerLabel,
} from "./meetingRoundDisplayModel";
import type { MeetingSourceMessage } from "../../api/types/hypothesisFirst";

describe("meetingRoundDisplayModel", () => {
  it("hides machine agent ids and prefers a human role", () => {
    expect(isMachineAgentId("agent-20260722-220514-082385")).toBe(true);
    expect(meetingSpeakerLabel({
      agentId: "agent-20260722-220514-082385",
      role: "评审",
    })).toBe("评审");
    expect(meetingSpeakerLabel({
      agentId: "agent-20260722-220514-082385",
      role: "source_ingestor",
      speakerTitle: "A014 · 科研协调",
    })).toBe("A014 · 科研协调");
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

function speakers(count: number): string[] {
  return Array.from({ length: count }, (_, index) => `agent-${index + 1}`);
}

function spoken(ids: readonly string[]): MeetingSourceMessage[] {
  return ids.map((agentId, index) => ({
    messageId: `m-${index + 1}`,
    agentId,
    status: "completed",
    content: "free form",
  }));
}

describe("meetingDiscussionProgress", () => {
  it("renders 0/9 with the first speaker waiting", () => {
    const progress = meetingDiscussionProgress({
      participants: speakers(9),
      messages: [],
    });
    expect(progress).toMatchObject({ spoken: 0, expected: 9, complete: false, nextCode: "A001" });
    expect(progress.label).toBe("已发言 0/9 · 待 A001");
  });

  it("renders 3/9 with the next speaker code", () => {
    const order = speakers(9);
    const progress = meetingDiscussionProgress({
      speakerOrder: order,
      messages: spoken(order.slice(0, 3)),
    });
    expect(progress).toMatchObject({ spoken: 3, expected: 9, complete: false, nextCode: "A004" });
    expect(progress.label).toBe("已发言 3/9 · 待 A004");
  });

  it("renders 9/9 as discussion complete", () => {
    const order = speakers(9);
    const progress = meetingDiscussionProgress({
      speakerOrder: order,
      messages: spoken(order),
    });
    expect(progress).toMatchObject({ spoken: 9, expected: 9, complete: true, nextCode: null });
    expect(progress.label).toBe("讨论完成，待整理");
  });

  it("keeps explicit A0xx codes when the speaker id is already a display code", () => {
    const progress = meetingDiscussionProgress({
      speakerOrder: ["A018", "A019", "A020"],
      messages: spoken(["A018"]),
    });
    expect(progress.label).toBe("已发言 1/3 · 待 A019");
  });
});
