import { describe, expect, it } from "vitest";

import type { RetryTurnItem } from "../../api/types";
import {
  feedbackStatusPlaceholderLabel,
  shouldUseFeedbackStatusPlaceholder,
} from "./conversationFeedbackStatusPresentation";

describe("conversationFeedbackStatusPresentation canonical status", () => {
  const retry: RetryTurnItem = {
    id: "retry-1-r1", itemId: "retry-1", version: 3, sessionId: "session-1", turnId: "turn-1",
    type: "retry", status: "running", revision: 1, sequence: 1,
    attempt: 2, targetItemId: "request-1", reason: "network_error",
  };

  it("keeps a running retry visible as process state", () => {
    expect(shouldUseFeedbackStatusPlaceholder(retry, true)).toBe(true);
    expect(feedbackStatusPlaceholderLabel(retry, "zh")).toContain("重试");
  });

  it("leaves internal running stages to the single compact active status line", () => {
    expect(shouldUseFeedbackStatusPlaceholder({
      id: "status-1-r0",
      itemId: "status-1",
      version: 3,
      sessionId: "session-1",
      turnId: "turn-1",
      type: "status",
      code: "model_request",
      text: "正在请求模型",
      status: "running",
      revision: 0,
      sequence: 2,
    }, true)).toBe(false);
  });
});
