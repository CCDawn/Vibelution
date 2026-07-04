import { describe, expect, it, vi } from "vitest";

import type {
  AgentMessageOperation,
  AgentMessageReActOperationGroup,
} from "./agentMessageOperations";
import conversationViewSource from "./ConversationView.tsx?raw";
import {
  reActActionOperations,
  reActGroupDurationLabel,
  reActResultItems,
  reActThoughtItems,
  shouldExpandReActGroupByDefault,
} from "./conversationReActOperationItems";

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

function group(operations: AgentMessageOperation[]): AgentMessageReActOperationGroup {
  return {
    id: "react-group",
    index: 1,
    operations,
    title: "Tool",
    primaryKind: "tool",
  };
}

describe("conversation ReAct operation item helpers", () => {
  it("keeps ReAct item derivation out of ConversationView", () => {
    expect(conversationViewSource).toContain('from "./conversationReActOperationItems"');
    expect(conversationViewSource).not.toMatch(/function reActGroupDurationLabel\(/);
    expect(conversationViewSource).not.toMatch(/function reActActionOperations\(/);
    expect(conversationViewSource).not.toMatch(/function reActThoughtItems\(/);
    expect(conversationViewSource).not.toMatch(/function reActResultItems\(/);
    expect(conversationViewSource).not.toMatch(/function shouldExpandReActGroupByDefault\(/);
  });

  it("formats total positive operation duration", () => {
    const formatDuration = vi.fn((seconds: number) => `${seconds}s`);

    expect(reActGroupDurationLabel(group([
      operation({ id: "a", durationSeconds: 1.5 }),
      operation({ id: "b", durationSeconds: 2 }),
      operation({ id: "zero", durationSeconds: 0 }),
      operation({ id: "negative", durationSeconds: -1 }),
      operation({ id: "missing", durationSeconds: null }),
    ]), formatDuration)).toBe("3.5s");

    expect(formatDuration).toHaveBeenCalledWith(3.5);
    expect(reActGroupDurationLabel(group([
      operation({ id: "missing", durationSeconds: null }),
    ]), formatDuration)).toBe("");
  });

  it("returns only tool actions from a ReAct group", () => {
    const actions = reActActionOperations(group([
      operation({ id: "thought", kind: "thought" }),
      operation({ id: "tool-1", kind: "tool" }),
      operation({ id: "status", kind: "status" }),
      operation({ id: "tool-2", kind: "tool" }),
    ]));

    expect(actions.map((item) => item.id)).toEqual(["tool-1", "tool-2"]);
  });

  it("deduplicates thought display items by trimmed content", () => {
    expect(reActThoughtItems(group([
      operation({ id: "thought-1", kind: "thought", resultPreview: " first thought " }),
      operation({ id: "thought-2", kind: "thought", summary: "first thought" }),
      operation({ id: "thought-empty", kind: "thought", resultPreview: "   " }),
      operation({ id: "thought-3", kind: "thought", summary: "second thought" }),
      operation({ id: "tool", kind: "tool", summary: "not a thought" }),
    ]))).toEqual([
      { id: "thought-1-thought", value: "first thought" },
      { id: "thought-3-thought", value: "second thought" },
    ]);
  });

  it("builds compact result items while keeping full details delegated", () => {
    const operationLabel = (item: AgentMessageOperation) => `label:${item.id}`;
    const readableOperationResult = (item: AgentMessageOperation) => {
      if (item.id === "tool-result") {
        return "created file";
      }
      if (item.id === "tool-same-summary") {
        return "already summarized";
      }
      return "";
    };

    expect(reActResultItems(group([
      operation({ id: "tool-error", kind: "tool", error: " failed to run " }),
      operation({ id: "tool-result", kind: "tool", summary: "tool ran" }),
      operation({ id: "tool-same-summary", kind: "tool", summary: "already summarized" }),
      operation({ id: "status-no-error", kind: "status", resultPreview: "ignored" }),
      operation({ id: "status-error", kind: "status", error: " status failed " }),
    ]), {
      operationLabel,
      readableOperationResult,
    })).toEqual([
      {
        id: "tool-error-error",
        label: "label:tool-error",
        value: "failed to run",
        tone: "failed",
      },
      {
        id: "tool-result-result",
        label: "label:tool-result",
        value: "created file",
        tone: "default",
      },
      {
        id: "status-error-error",
        label: "label:status-error",
        value: "status failed",
        tone: "failed",
      },
    ]);
  });

  it("expands active or failed ReAct groups by default", () => {
    expect(shouldExpandReActGroupByDefault(group([
      operation({ id: "running", status: "running" }),
    ]))).toBe(true);
    expect(shouldExpandReActGroupByDefault(group([
      operation({ id: "failed", status: "failed" }),
    ]))).toBe(true);
    expect(shouldExpandReActGroupByDefault(group([
      operation({ id: "pending", status: "waiting" }),
    ]))).toBe(true);
    expect(shouldExpandReActGroupByDefault(group([
      operation({ id: "done", status: "done" }),
    ]))).toBe(false);
  });
});
