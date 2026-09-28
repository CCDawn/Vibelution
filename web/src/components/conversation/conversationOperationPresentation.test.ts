import { describe, expect, it } from "vitest";

import {
  compactConversationPreview,
  hasOperationDetails,
  operationGroupTitle,
  operationStatusFallbackText,
  operationStatusIconKind,
  operationStatusToneClassNameFromTone,
  operationTimelineTitle,
  operationVisualTone,
  processSummaryIconKind,
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
      role: "assistant",
      streaming: false,
      inFlight: true,
      showResponseBlock: false,
      hasFeedbackTimeline: false,
      hasActiveProcess: false,
      turnErrorMessage: false,
    })).toBe(true);
    expect(shouldRenderCompactActiveTurnPlaceholder({
      role: "assistant",
      streaming: false,
      inFlight: false,
      showResponseBlock: false,
      hasFeedbackTimeline: false,
      hasActiveProcess: false,
      turnErrorMessage: false,
    })).toBe(false);
    expect(shouldRenderCompactActiveTurnPlaceholder({
      role: "assistant",
      streaming: true,
      showResponseBlock: true,
      hasFeedbackTimeline: true,
      hasActiveProcess: true,
      turnErrorMessage: false,
      hasCodexSurface: true,
    })).toBe(false);
    expect(shouldRenderCompactActiveTurnPlaceholder({
      role: "assistant",
      streaming: true,
      showResponseBlock: false,
      hasFeedbackTimeline: false,
      hasActiveProcess: true,
      turnErrorMessage: false,
      hasCodexSurface: false,
    })).toBe(false);
    // Defect 7b: a feedback timeline alone (batched reasoning trail published
    // with the first content flush) no longer retires the in-flight shell.
    expect(shouldRenderCompactActiveTurnPlaceholder({
      role: "assistant",
      streaming: true,
      showResponseBlock: false,
      hasFeedbackTimeline: true,
      hasActiveProcess: false,
      turnErrorMessage: false,
      hasCodexSurface: false,
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

  it("keeps the shell through the answer-streaming window (defect 7b)", () => {
    // Visible answer text alone must not retire the shell: the first content
    // flush lands a frame before the backend's responding status row, and the
    // responding stage has to stay observable while the answer streams.
    expect(shouldRenderCompactActiveTurnPlaceholder({
      role: "assistant",
      streaming: true,
      showResponseBlock: true,
      hasFeedbackTimeline: false,
      hasActiveProcess: false,
      turnErrorMessage: false,
    })).toBe(true);
    // Other gating conjuncts still retire the shell.
    expect(shouldRenderCompactActiveTurnPlaceholder({
      role: "assistant",
      streaming: true,
      showResponseBlock: true,
      hasFeedbackTimeline: false,
      hasActiveProcess: false,
      turnErrorMessage: true,
    })).toBe(false);
    expect(shouldRenderCompactActiveTurnPlaceholder({
      role: "assistant",
      streaming: true,
      showResponseBlock: true,
      hasFeedbackTimeline: true,
      hasActiveProcess: true,
      turnErrorMessage: false,
    })).toBe(false);
    expect(shouldRenderCompactActiveTurnPlaceholder({
      role: "assistant",
      streaming: false,
      inFlight: false,
      showResponseBlock: true,
      hasFeedbackTimeline: false,
      hasActiveProcess: false,
      turnErrorMessage: false,
    })).toBe(false);
    // The native codex answer cell alone (streaming answer, no richer surfaces)
    // does not retire the shell either.
    expect(shouldRenderCompactActiveTurnPlaceholder({
      role: "assistant",
      streaming: true,
      showResponseBlock: true,
      hasFeedbackTimeline: false,
      hasActiveProcess: false,
      turnErrorMessage: false,
      hasCodexSurface: true,
    })).toBe(true);
  });

  it("shows compact placeholder for optimistic pending + empty turnItems (inFlight)", () => {
    expect(shouldRenderCompactActiveTurnPlaceholder({
      role: "assistant",
      streaming: false,
      inFlight: true,
      showResponseBlock: false,
      hasFeedbackTimeline: false,
      hasActiveProcess: false,
      turnErrorMessage: false,
      hasCodexSurface: false,
    })).toBe(true);
  });

  it("keeps compact false for inFlight + hasActiveProcess (no force-OR stacking)", () => {
    expect(shouldRenderCompactActiveTurnPlaceholder({
      role: "assistant",
      streaming: false,
      inFlight: true,
      showResponseBlock: false,
      hasFeedbackTimeline: false,
      hasActiveProcess: true,
      turnErrorMessage: false,
      hasCodexSurface: false,
    })).toBe(false);
  });

  it("classifies status/process icons and detects operation details", () => {
    expect(operationStatusIconKind("done", false, true)).toBe("done");
    expect(operationStatusIconKind("running", true, true)).toBe("running");
    expect(operationStatusIconKind("running", true, false)).toBe("running_static");
    expect(processSummaryIconKind("failed")).toBe("failed");
    expect(processSummaryIconKind("done")).toBe("done");
    expect(hasOperationDetails({ arguments: { a: 1 } })).toBe(true);
    expect(hasOperationDetails({})).toBe(false);
  });
});
