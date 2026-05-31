import { describe, expect, it } from "vitest";

import { agentDisplayInfo, participantAgentDisplayInfo, sessionAgentDisplayInfo } from "./agentDisplay";

describe("agent display helpers", () => {
  it("keeps person names while replacing noisy session labels with clear chat roles", () => {
    const info = agentDisplayInfo(
      {
        agentId: "agent-1",
        agentCode: "A001",
        displayName: "夏映白",
        primaryMode: "chat",
        profileId: "primary",
        metadata: { functionalDisplayName: "新会话" },
      },
      "zh",
    );

    expect(info.name).toBe("夏映白");
    expect(info.functionLabel).toBe("通用会话 Agent");
    expect(info.functionLabel).not.toBe("新会话");
    expect(info.tone).toBe("chat");
  });

  it("derives research roles from role keys and prompt templates", () => {
    expect(agentDisplayInfo({ displayName: "闻以宁", primaryMode: "research", roleKey: "research_review" }, "zh")).toMatchObject({
      name: "闻以宁",
      functionLabel: "证据审查 Agent",
      tone: "research",
    });
    expect(agentDisplayInfo({ displayName: "夏予安", primaryMode: "research", promptTemplateId: "prompt-research-card" }, "zh")).toMatchObject({
      functionLabel: "主题卡 Agent",
      tone: "research",
    });
  });

  it("uses the bound Agent instead of the session title for session display", () => {
    const info = sessionAgentDisplayInfo(
      {
        id: "session-1",
        title: "新会话",
        agentDisplayName: "新会话",
        agentTemplateLabel: "主 Agent",
        agentProfileId: "primary",
      },
      {
        agentId: "agent-1",
        displayName: "夏映白",
        primaryMode: "chat",
        profileId: "primary",
        metadata: { functionalDisplayName: "新会话" },
      },
      "zh",
    );

    expect(info.name).toBe("夏映白");
    expect(info.functionLabel).toBe("通用会话 Agent");
  });

  it("uses team participant role context before direct session role labels", () => {
    const info = participantAgentDisplayInfo(
      {
        participantId: "session-alpha",
        title: "Alpha",
        agentCode: "A011",
        teamRole: "research_lead",
        teamMemberPurpose: "科研负责人",
      },
      {
        agentId: "agent-alpha",
        agentCode: "A011",
        displayName: "Alpha",
        primaryMode: "chat",
      },
      "zh",
    );

    expect(info.name).toBe("Alpha");
    expect(info.functionLabel).toBe("科研负责人");
    expect(info.meta).toBe("科研负责人 · A011");
  });
});
