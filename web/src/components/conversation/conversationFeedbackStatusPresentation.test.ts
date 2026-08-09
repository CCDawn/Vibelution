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
});
