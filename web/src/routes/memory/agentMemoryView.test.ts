import { describe, expect, it } from "vitest";

import {
  agentFormalBaseCount,
  agentPrivateFileCount,
  toAgentMemoryAgentView,
  toAgentMemorySummaryView,
  toSelectedAgentMemoryView,
} from "./agentMemoryView";

describe("agentMemoryView", () => {
  it("prefers backend fileCount and knowledgeSummary over leftover aliases", () => {
    const agent = {
      agentId: "agent-1",
      displayName: "Planner",
      agentCode: "planner",
      status: "active",
      hasPrivateMemory: true,
      workspacePath: "C:\\\\agents\\\\planner",
      privateMemoryRoot: "C:\\\\agents\\\\planner\\\\memory",
      fileCount: 4,
      privateFileCount: 0,
      formalKnowledgeBaseCount: 0,
      knowledgeSummary: {
        knowledgeBaseCount: 2,
        itemCount: 9,
        knowledgeBases: [{ knowledgeBaseId: "kb-1", name: "Private KB" }],
      },
    };

    expect(agentPrivateFileCount(agent)).toBe(4);
    expect(agentFormalBaseCount(agent)).toBe(2);
    expect(toAgentMemoryAgentView(agent, "agent-1")).toMatchObject({
      id: "agent-1",
      name: "Planner",
      privateFileCount: 4,
      formalKnowledgeBaseCount: 2,
      active: true,
    });
    expect(toSelectedAgentMemoryView(agent)).toMatchObject({
      fileCount: 4,
      formalKnowledgeItemCount: 9,
      formalKnowledgeBaseCount: 2,
      knowledgeBases: [{ id: "kb-1", label: "Private KB" }],
    });
  });

  it("counts inventory warnings for the summary strip", () => {
    expect(
      toAgentMemorySummaryView(
        { agentCount: 3, privateFileCount: 1, warnings: ["outside root"] },
        "12 B",
      ),
    ).toMatchObject({
      agentCount: 3,
      privateFileCount: 1,
      privateByteText: "12 B",
      warningCount: 1,
    });
  });
});
