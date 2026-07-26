import { describe, expect, it } from "vitest";

import {
  compactConversationPreview,
  operationGroupTitle,
  operationStatusFallbackText,
  operationStatusToneClassNameFromTone,
  operationTimelineTitle,
  operationVisualTone,
  rolloutTraceEventLabel,
  shouldRenderCodexTranscriptSurface,
  shouldRenderCompactActiveTurnPlaceholder,
} from "./conversationOperationPresentation";

describe("conversationOperationPresentation", () => {
  it("compacts previews and maps operation tones", () => {
    expect(compactConversationPreview("  a   b  ", 10)).toBe("a b");
    expect(compactConversationPreview("x".repeat(20), 10)).toBe(`${"x".repeat(9)}...`);
    expect(operationVisualTone({ kind: "thought" })).toBe("thought");
    expect(operationVisualTone({ kind: "tool" })).toBe("tool");
    expect(operationStatusToneClassNameFromTone("done")).toBe("success");
    expect(operationStatusToneClassNameFromTone("degraded")).toBe("warning");
  });

  it("labels status fallbacks, rollout events, and group titles", () => {
    expect(operationStatusFallbackText("degraded", "zh", () => "x")).toBe("降级");
    expect(operationStatusFallbackText("running", "en", (status) => `lbl:${status}`)).toBe("lbl:running");
    expect(rolloutTraceEventLabel("ToolCallStarted", "zh")).toBe("调用开始");
    expect(operationGroupTitle("thought", 2, {
      thoughtProcess: "Thought",
      mentalProcess: "Mental",
      toolProcess: "Tool",
    })).toBe("Thought");
    expect(operationTimelineTitle([{ kind: "tool" }], "zh", {
      thoughtProcess: "Thought",
      mentalProcess: "Mental",
      toolProcess: "Tool",
    })).toBe("执行过程");
  });

  it("gates codex surface and compact active-turn placeholders", () => {
    expect(shouldRenderCodexTranscriptSurface({ mode: "native", cells: [{ id: "1" } as never] })).toBe(true);
    expect(shouldRenderCodexTranscriptSurface({ mode: "legacy", cells: [] } as never)).toBe(false);
    expect(shouldRenderCompactActiveTurnPlaceholder({
      role: "assistant",
      streaming: true,
      showResponseBlock: false,
      hasFeedbackTimeline: false,
      hasActiveProcess: false,
      turnErrorMessage: false,
    })).toBe(true);
    expect(shouldRenderCompactActiveTurnPlaceholder({
      role: "user",
      streaming: true,
      showResponseBlock: false,
      hasFeedbackTimeline: false,
      hasActiveProcess: false,
      turnErrorMessage: false,
    })).toBe(false);
  });
});
