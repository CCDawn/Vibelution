import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";

import type { AgentMessageOperation, AgentMessageOperationGroups } from "./agentMessageOperations";
import {
  feedbackStatusPlaceholderLabel,
  feedbackStatusPlaceholderOperation,
  operationGroupsWithFeedbackStatusPlaceholder,
  operationIsVisibleStatusProgress,
  shouldUseFeedbackStatusPlaceholder,
  statusEventHasDiagnostic,
} from "./conversationFeedbackStatusPresentation";

function emptyGroups(): AgentMessageOperationGroups {
  return { timeline: [], thoughts: [], mental: [], tools: [], status: [] };
}

describe("conversationFeedbackStatusPresentation", () => {
  it("labels long-loop and prepare stages", () => {
    expect(
      feedbackStatusPlaceholderLabel(
        { kind: "status", name: "context_prepare", status: "running" } as never,
        "zh",
      ),
    ).toBe("准备上下文");
    expect(
      feedbackStatusPlaceholderLabel(
        {
          kind: "status",
          name: "status",
          status: "running",
          summary: "long_loop_progress",
        } as never,
        "en",
      ),
    ).toBe("Tool loop");
  });

  it("detects diagnostics and visible status progress", () => {
    expect(statusEventHasDiagnostic({ kind: "status", status: "failed" } as never)).toBe(true);
    expect(
      operationIsVisibleStatusProgress({
        id: "1",
        kind: "status",
        label: "工具循环",
        status: "running",
        durationSeconds: null,
      }),
    ).toBe(true);
    expect(
      shouldUseFeedbackStatusPlaceholder(
        { kind: "status", name: "context_prepare", status: "running" } as never,
        true,
      ),
    ).toBe(true);
  });

  it("injects a placeholder status operation when timeline lacks progress", () => {
    const message = {
      id: "m1",
      role: "assistant",
      content: "",
      streaming: true,
      feedbackEvents: [
        {
          kind: "status",
          name: "agent_prepare",
          status: "running",
          sequence: 3,
          timestamp: "2026-01-01T00:00:00Z",
        },
      ],
    } as ConversationMessage;
    const groups = operationGroupsWithFeedbackStatusPlaceholder(emptyGroups(), message, "zh");
    expect(groups.timeline).toHaveLength(1);
    expect(groups.timeline[0]?.label).toBe("准备 Agent");
    expect(groups.status).toHaveLength(1);

    const withExisting: AgentMessageOperation[] = [
      {
        id: "existing",
        kind: "status",
        label: "工具循环",
        status: "running",
        durationSeconds: null,
      },
    ];
    expect(feedbackStatusPlaceholderOperation(message, withExisting, "zh")).toBeNull();
  });
});
