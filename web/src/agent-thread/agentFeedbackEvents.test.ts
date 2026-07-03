import { existsSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import type { AgentFeedbackEvent } from "./agentFeedbackEvents";

const retiredConversationFeedbackEventsPath = new URL("../conversation-model/feedbackEvents.ts", import.meta.url);

function source(path: string) {
  return readFileSync(new URL(path, import.meta.url), "utf8");
}

describe("agent feedback event helpers", () => {
  it("merges duplicate feedback events through an AgentThread-owned helper", async () => {
    const {
      agentFeedbackEventIdentityKey,
      mergeAgentFeedbackEvents,
    } = await import("./agentFeedbackEvents");
    const firstTool: AgentFeedbackEvent = {
      kind: "tool",
      name: "read_file_tool",
      summary: "开始读取",
      sequence: 2,
      arguments: { path: "ConversationView.tsx" },
    };
    const replacementTool: AgentFeedbackEvent = {
      kind: "tool",
      name: "read_file_tool",
      summary: "读取完成",
      resultPreview: "export function ConversationView",
      sequence: 2,
    };
    const thought: AgentFeedbackEvent = {
      kind: "thought",
      summary: "先确认边界",
      sequence: 1,
    };

    expect(agentFeedbackEventIdentityKey(firstTool)).toBe("seq:2");
    expect(mergeAgentFeedbackEvents([firstTool], [thought, replacementTool])).toEqual([
      thought,
      {
        ...firstTool,
        ...replacementTool,
      },
    ]);
  });

  it("retires the old conversation-model feedback helper path from AgentThread callers", () => {
    expect(existsSync(retiredConversationFeedbackEventsPath)).toBe(false);
    expect(source("./adapters.ts")).not.toContain("../conversation-model/feedbackEvents");
    expect(source("../routes/chatActiveTurnLayer.ts")).not.toContain("../conversation-model/feedbackEvents");
    expect(source("../components/conversation/useAgentMessageTimelineProjection.ts")).not.toContain("../../conversation-model/feedbackEvents");
  });
});
