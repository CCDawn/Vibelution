import { describe, expect, it } from "vitest";

import type { AgentMessageOperation } from "./agentMessageOperations";
import type { AgentMessageReActOperationGroup } from "./agentMessageOperations";
import conversationViewSource from "./ConversationView.tsx?raw";
import {
  compactVisibleTimelineOperations,
  hasModelThinkingProcess,
  isCompactAnswerOnlyRequestProcess,
  isRunningOperationStatus,
  operationCollectionTone,
  operationDisplayLabel,
  operationStateLabel,
  operationStatusTone,
  processSummaryMeta,
  processSummaryPreview,
  processSummaryTitle,
  reActGroupTone,
  shouldShowTimelineOperation,
  type OperationStateLabels,
} from "./conversationOperationState";

const labels: OperationStateLabels = {
  running: "Running",
  failed: "Failed",
  done: "Done",
  pending: "Pending",
  requesting: "Requesting",
  requestFailed: "Request failed",
  pendingRequest: "Pending request",
  thinking: "Thinking",
  generating: "Generating",
  processFailed: "Process failed",
  process: "Process",
  processPending: "Process pending",
  thoughtProcess: "Thought",
  toolProcess: "Tool",
  mentalProcess: "Mental",
  status: "Status",
};

function operation(overrides: Partial<AgentMessageOperation>): AgentMessageOperation {
  return {
    id: overrides.id ?? "operation",
    kind: overrides.kind ?? "tool",
    label: overrides.label ?? "Tool",
    status: overrides.status ?? "done",
    summary: overrides.summary ?? "",
    durationSeconds: null,
    ...overrides,
  };
}

describe("conversation operation state helpers", () => {
  it("keeps operation state pure helpers out of ConversationView", () => {
    expect(conversationViewSource).toContain('from "./conversationOperationState"');
    expect(conversationViewSource).not.toMatch(/function operationStatusTone\(/);
    expect(conversationViewSource).not.toMatch(/function isRunningOperationStatus\(/);
    expect(conversationViewSource).not.toMatch(/function operationCollectionTone\(/);
    expect(conversationViewSource).not.toMatch(/function shouldShowTimelineOperation\(/);
    expect(conversationViewSource).not.toMatch(/function compactVisibleTimelineOperations\(/);
    expect(conversationViewSource).not.toMatch(/function processSummaryPreview\(/);
  });

  it("classifies operation statuses and collection tone", () => {
    expect(isRunningOperationStatus("thinking")).toBe(true);
    expect(operationStatusTone(operation({ status: "timeout" }))).toBe("failed");
    expect(operationStatusTone(operation({ status: "running" }))).toBe("running");
    expect(operationStatusTone(operation({ status: "completed" }))).toBe("done");
    expect(operationCollectionTone([
      operation({ id: "done", status: "done" }),
      operation({ id: "running", status: "running" }),
    ])).toBe("running");
    expect(operationCollectionTone([
      operation({ id: "done", status: "done" }),
      operation({ id: "failed", status: "failed" }),
    ])).toBe("failed");
  });

  it("shows long-loop status operations while hiding internal pipeline noise", () => {
    const internalStatus = operation({
      id: "context",
      kind: "status",
      rawLabel: "context_prepare",
      label: "Prepare context",
      status: "running",
      summary: "Reading session, agent, and tools",
    });
    const longLoopStatus = operation({
      id: "loop",
      kind: "status",
      rawLabel: "long_loop_progress",
      label: "Tool loop",
      status: "running",
      summary: "尚未形成最终回答",
    });

    expect(shouldShowTimelineOperation(internalStatus)).toBe(false);
    expect(shouldShowTimelineOperation({ ...internalStatus, error: "failed to prepare" })).toBe(true);
    expect(shouldShowTimelineOperation(longLoopStatus)).toBe(true);
  });

  it("deduplicates visible long-loop progress while preserving ordinary operations", () => {
    const compacted = compactVisibleTimelineOperations([
      operation({ id: "read", kind: "tool", label: "Read", status: "done" }),
      operation({
        id: "loop-1",
        kind: "status",
        rawLabel: "long_loop_progress",
        rawStatus: "running",
        label: "Tool loop",
        status: "running",
        summary: "first",
      }),
      operation({
        id: "loop-2",
        kind: "status",
        rawLabel: "long_loop_progress",
        rawStatus: "running",
        label: "Tool loop",
        status: "running",
        summary: "second",
      }),
    ]);

    expect(compacted.map((item) => item.id)).toEqual(["read", "loop-2"]);
  });

  it("builds localized operation labels and process summaries", () => {
    const internalThinking = operation({
      id: "thinking",
      kind: "status",
      rawLabel: "model_thinking",
      label: "Model thinking",
      status: "running",
      summary: "reasoning has started",
    });

    expect(operationDisplayLabel(operation({ label: "" }), labels)).toBe("Tool");
    expect(operationStateLabel("failed", labels)).toBe("Failed");
    expect(hasModelThinkingProcess([internalThinking])).toBe(true);
    expect(isCompactAnswerOnlyRequestProcess([internalThinking])).toBe(true);
    expect(processSummaryTitle("running", [internalThinking], labels)).toBe("Thinking");
    expect(processSummaryMeta([internalThinking], labels)).toBe("");
  });

  it("builds process summary meta and preview from visible operations", () => {
    const operations = [
      operation({ id: "thought", kind: "thought", label: "Thought", status: "done" }),
      operation({ id: "tool", kind: "tool", label: "Read", status: "done" }),
      operation({ id: "mental", kind: "mental", label: "Mental", status: "done" }),
      operation({
        id: "loop",
        kind: "status",
        rawLabel: "long_loop_progress",
        label: "Tool loop",
        status: "running",
        summary: "still collecting evidence",
      }),
    ];

    expect(processSummaryMeta(operations, labels)).toBe("Thought 1 · Tool 1 · Mental 1 · Status 1");
    expect(processSummaryPreview(operations, labels, (value, maxLength) => `${maxLength}:${value}`))
      .toBe("120:Tool loop · still collecting evidence");
  });

  it("computes ReAct group tone from grouped operations", () => {
    const group: AgentMessageReActOperationGroup = {
      id: "react",
      index: 1,
      operations: [
        operation({ id: "tool", kind: "tool", status: "done" }),
        operation({ id: "status", kind: "status", status: "failed", error: "tool failed" }),
      ],
      title: "Tool",
      primaryKind: "tool",
    };

    expect(reActGroupTone(group)).toBe("failed");
  });
});
