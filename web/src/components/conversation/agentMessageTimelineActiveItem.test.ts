import { existsSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import type { AgentMessageTimelineItem } from "./agentMessageTimeline";

const conversationViewSource = readFileSync(new URL("./ConversationView.tsx", import.meta.url), "utf8");
const helperModuleUrl = new URL("./agentMessageTimelineActiveItem.ts", import.meta.url);

const assistantTextItem: AgentMessageTimelineItem = {
  id: "assistant-text",
  kind: "assistant_text",
  status: "running",
  text: "answer",
};

const runningOperationItem: AgentMessageTimelineItem = {
  id: "operation-running",
  kind: "operation",
  status: "running",
  title: "Run command",
  summary: "running command",
  operation: {
    id: "operation-a",
    kind: "tool",
    label: "shell",
    status: "running",
    summary: "running command",
    durationSeconds: null,
  },
};

const completedThoughtItem: AgentMessageTimelineItem = {
  id: "thought-completed",
  kind: "thought",
  status: "completed",
  text: "done",
  preview: "done",
  defaultExpanded: false,
  sourceOperationIds: ["thought-a"],
};

describe("agentMessageTimelineActiveItem", () => {
  it("keeps active timeline item selection outside ConversationView", () => {
    expect(existsSync(helperModuleUrl)).toBe(true);
    expect(conversationViewSource).toContain("from \"./agentMessageTimelineActiveItem\"");
    expect(conversationViewSource).not.toContain("function activeTimelineItemId(");
  });

  it("selects the latest running non-answer item only while the message streams", async () => {
    const { activeAgentMessageTimelineItemId } = await import("./agentMessageTimelineActiveItem");

    expect(activeAgentMessageTimelineItemId({ streaming: false }, [
      runningOperationItem,
    ])).toBe("");
    expect(activeAgentMessageTimelineItemId({ streaming: true }, [
      completedThoughtItem,
      assistantTextItem,
    ])).toBe("");
    expect(activeAgentMessageTimelineItemId({ streaming: true }, [
      runningOperationItem,
      {
        ...runningOperationItem,
        id: "operation-running-latest",
      },
      assistantTextItem,
    ])).toBe("operation-running-latest");
  });
});
