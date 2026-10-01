import { describe, expect, it } from "vitest";

import {
  agentMemoryDetailRevision,
  agentFormalBaseCount,
  agentPrivateFileCount,
  resolveDefaultAgentMemoryId,
  toAgentMemoryAgentView,
  toAgentMemorySummaryView,
  toSelectedAgentMemoryView,
  type AgentMemoryInventoryAgent,
} from "./agentMemoryView";

describe("agentMemoryView", () => {
  it("tracks detail metadata without including file bodies or file ordering", () => {
    const agent = {
      agentId: "owner", displayName: "Owner",
      items: [{ id: "b", revision: "b1", content: "private body" }, { id: "a", revision: "a1" }],
      knowledgeSummary: { itemCount: 1 },
    };
    const revision = agentMemoryDetailRevision(agent);
    expect(revision).toBe(agentMemoryDetailRevision({ ...agent, items: [...agent.items].reverse() }));
    expect(revision).not.toContain("private body");
    expect(revision).not.toBe(agentMemoryDetailRevision({ ...agent, items: [{ id: "b", revision: "b2" }] }));
    expect(revision).not.toBe(agentMemoryDetailRevision({ ...agent, knowledgeSummary: { itemCount: 2 } }));
    expect(agentMemoryDetailRevision(undefined)).toBe("");
  });

  it("defaults to the first Agent with private memory and otherwise the first Agent", () => {
    const agents: AgentMemoryInventoryAgent[] = [
      { agentId: "empty-first", hasPrivateMemory: false, fileCount: 0 },
      { agentId: "private-first", hasPrivateMemory: true, fileCount: 2 },
      { agentId: "private-second", hasPrivateMemory: true, fileCount: 1 },
    ];

    expect(resolveDefaultAgentMemoryId(agents, "")).toBe("private-first");
    expect(resolveDefaultAgentMemoryId([], "")).toBe("");
    expect(resolveDefaultAgentMemoryId([{ agentId: "only-agent" }], "")).toBe("only-agent");
  });

  it("preserves an explicit Agent selection and does not fall back for an invalid id", () => {
    const agents: AgentMemoryInventoryAgent[] = [
      { agentId: "with-memory", hasPrivateMemory: true, fileCount: 1 },
      { agentId: "without-memory", hasPrivateMemory: false, fileCount: 0 },
    ];

    expect(resolveDefaultAgentMemoryId(agents, "without-memory")).toBe("without-memory");
    expect(resolveDefaultAgentMemoryId(agents, "missing-agent")).toBe("");
  });

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
      hasPrivateMemory: true,
      primaryMode: "",
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
