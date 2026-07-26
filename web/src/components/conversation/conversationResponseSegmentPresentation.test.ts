import { describe, expect, it } from "vitest";

import {
  isResponseSegmentCodeLike,
  responseSegmentLabel,
  shouldShowAgentResponseBlock,
} from "./conversationResponseSegmentPresentation";

describe("conversationResponseSegmentPresentation", () => {
  const t = (key: string) => key;

  it("labels segments and detects code-like blocks", () => {
    expect(responseSegmentLabel({ kind: "status" }, t)).toBe("responseSegmentStatus");
    expect(responseSegmentLabel({ kind: "code", language: "ts" }, t)).toBe("ts");
    expect(isResponseSegmentCodeLike({ kind: "code", content: "x" })).toBe(true);
    expect(isResponseSegmentCodeLike({ kind: "commit", content: "line1\nline2" })).toBe(true);
    expect(isResponseSegmentCodeLike({ kind: "answer", content: "plain" })).toBe(false);
  });

  it("decides whether the agent response block should render", () => {
    expect(shouldShowAgentResponseBlock({
      hasResponseBlock: false,
      answerText: "hi",
      hasFeedbackTimeline: false,
      streaming: false,
      segments: [{ kind: "answer" }],
    })).toBe(false);

    expect(shouldShowAgentResponseBlock({
      hasResponseBlock: true,
      answerText: "final answer",
      hasFeedbackTimeline: true,
      streaming: false,
      segments: [{ kind: "status" }],
    })).toBe(false);

    expect(shouldShowAgentResponseBlock({
      hasResponseBlock: true,
      answerText: "final answer",
      hasFeedbackTimeline: true,
      streaming: false,
      segments: [{ kind: "answer" }],
    })).toBe(true);
  });
});
