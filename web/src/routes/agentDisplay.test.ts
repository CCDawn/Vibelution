import { describe, expect, it } from "vitest";

import { agentDisplayInfo, compactModelLabel, modelDisplayLabel, participantAgentDisplayInfo, sessionAgentDisplayInfo } from "./agentDisplay";

describe("agent display helpers", () => {
  it("keeps person names while replacing noisy session labels with clear chat roles", () => {
    const info = agentDisplayInfo(
      {
        agentId: "agent-1",
        agentCode: "A001",
        displayName: "夏映白",
        primaryMode: "chat",
        llmBindings: { dialogue: { modelId: "houmo_qwen3_30b_agent" } },
        metadata: { functionalDisplayName: "新会话" },
      },
      "zh",
    );

    expect(info.name).toBe("夏映白");
    expect(info.functionLabel).toBe("会话入口");
    expect(info.functionLabel).not.toBe("新会话");
    expect(info.modelLabel).toBe("houmo-qwen3-30b-agent");
    expect(info.meta).toContain("houmo-qwen3-30b-agent");
    expect(info.tone).toBe("chat");
  });

  it("compacts provider-prefixed model ids for dense chat surfaces", () => {
    expect(compactModelLabel("openai/gpt-5.1")).toBe("gpt-5.1");
    expect(compactModelLabel("HiModel_xh2_qwen3-2507_30b.gguf")).toBe("HiModel-xh2-qwen3-2507-30b");
  });

  it("prefers configured model labels before compacting raw ids", () => {
    const resolveModelLabel = (modelId: string) => {
      return modelId === "gpt_5_5_gpt_5_5" ? "gpt-5.5-share" : undefined;
    };

    expect(modelDisplayLabel("gpt_5_5_gpt_5_5", resolveModelLabel)).toBe("gpt-5.5-share");
    expect(modelDisplayLabel("openai/gpt-5.1", resolveModelLabel)).toBe("gpt-5.1");
  });

  it("derives research roles from role keys and prompt templates", () => {
    expect(agentDisplayInfo({ displayName: "闻以宁", primaryMode: "research", roleKey: "research_review" }, "zh")).toMatchObject({
      name: "闻以宁",
      functionLabel: "证据审查",
      tone: "research",
    });
    expect(agentDisplayInfo({ displayName: "夏予安", primaryMode: "research", promptTemplateId: "prompt-research-card" }, "zh")).toMatchObject({
      functionLabel: "主题卡片",
      tone: "research",
    });
  });

  it("maps current Agent Center role keys to clear responsibility labels", () => {
    expect(agentDisplayInfo({
      displayName: "程听澜",
      primaryMode: "chat",
      roleKey: "chat_session_entry",
      metadata: { functionalDisplayName: "新会话" },
    }, "zh")).toMatchObject({
      functionLabel: "会话入口",
      tone: "chat",
    });
    expect(agentDisplayInfo({
      displayName: "顾明澈",
      primaryMode: "chat",
      roleKey: "agent_center_review_session",
      metadata: { functionalDisplayName: "新会话" },
    }, "zh")).toMatchObject({
      functionLabel: "Agent 配置审查",
      tone: "chat",
    });
    expect(agentDisplayInfo({ displayName: "数据发现", primaryMode: "research", roleKey: "challenge_cup_data_discovery" }, "zh")).toMatchObject({
      functionLabel: "数据发现",
      tone: "research",
    });
    expect(agentDisplayInfo({ displayName: "来源获取", primaryMode: "research", roleKey: "challenge_cup_source_acquisition" }, "zh")).toMatchObject({
      functionLabel: "来源获取",
      tone: "research",
    });
    expect(agentDisplayInfo({ displayName: "内容抽取", primaryMode: "research", roleKey: "challenge_cup_content_extraction" }, "zh")).toMatchObject({
      functionLabel: "内容抽取",
      tone: "research",
    });
    expect(agentDisplayInfo({ displayName: "资料质量评估", primaryMode: "research", roleKey: "challenge_cup_source_quality" }, "zh")).toMatchObject({
      functionLabel: "资料质检",
      tone: "research",
    });
  });

  it("uses precise labels for search-source and stewardship roles", () => {
    expect(agentDisplayInfo({ displayName: "范围负责人", primaryMode: "research", roleKey: "ai_search_scope_lead" }, "zh")).toMatchObject({
      functionLabel: "搜索范围",
      tone: "research",
    });
    expect(agentDisplayInfo({ displayName: "全球源", primaryMode: "research", roleKey: "global_primary_sources" }, "zh")).toMatchObject({
      functionLabel: "全球官方源",
      tone: "research",
    });
    expect(agentDisplayInfo({ displayName: "中国源", primaryMode: "research", roleKey: "cn_primary_sources" }, "zh")).toMatchObject({
      functionLabel: "中国官方源",
      tone: "research",
    });
    expect(agentDisplayInfo({ displayName: "信号质检", primaryMode: "research", roleKey: "signal_quality_gate" }, "zh")).toMatchObject({
      functionLabel: "信号质检",
      tone: "research",
    });
    expect(agentDisplayInfo({ displayName: "能力管家", primaryMode: "research", roleKey: "research_capability_steward" }, "zh")).toMatchObject({
      functionLabel: "能力管家",
      tone: "research",
    });
    expect(agentDisplayInfo({ displayName: "知识管家", primaryMode: "general", roleKey: "knowledge_steward" }, "zh")).toMatchObject({
      functionLabel: "知识管理员",
      tone: "memory",
    });
  });

  it("shows compact job labels without internal ids or repeated Agent suffixes", () => {
    expect(agentDisplayInfo({ displayName: "程听澜", primaryMode: "chat", roleKey: "chat-default" }, "zh")).toMatchObject({
      functionLabel: "会话入口",
      tone: "chat",
    });
    expect(agentDisplayInfo({ displayName: "叶星辞", primaryMode: "self_evolution", roleKey: "self-evolution summarizer" }, "zh")).toMatchObject({
      functionLabel: "总结者",
      tone: "self",
    });
    expect(agentDisplayInfo({ displayName: "唐听澜", primaryMode: "self_evolution", metadata: { functionalDisplayName: "自进化执行 Agent" } }, "zh")).toMatchObject({
      functionLabel: "执行者",
      tone: "self",
    });
    expect(agentDisplayInfo({ displayName: "宋书遥", primaryMode: "supervised_evolution", roleKey: "supervised_judge" }, "zh")).toMatchObject({
      functionLabel: "监督裁判",
      tone: "supervised",
    });
    expect(agentDisplayInfo({ displayName: "顾映白", primaryMode: "memory", metadata: { functionalDisplayName: "知识库管理员" } }, "zh")).toMatchObject({
      functionLabel: "知识管理员",
      tone: "memory",
    });
  });

  it("uses the bound Agent instead of the session title for session display", () => {
    const info = sessionAgentDisplayInfo(
      {
        id: "session-1",
        title: "新会话",
        agentDisplayName: "新会话",
        dialogueModelId: "session_locked_model",
      },
      {
        agentId: "agent-1",
        displayName: "夏映白",
        primaryMode: "chat",
        llmBindings: { dialogue: { modelId: "current_agent_model" } },
        metadata: { functionalDisplayName: "新会话" },
      },
      "zh",
      (modelId) => modelId === "session_locked_model" ? "Session Locked Model" : undefined,
    );

    expect(info.name).toBe("夏映白");
    expect(info.functionLabel).toBe("会话入口");
    expect(info.modelLabel).toBe("Session Locked Model");
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
        llmBindings: { dialogue: { modelId: "claude-opus-4-7" } },
      },
      "zh",
      (modelId) => modelId === "claude-opus-4-7" ? "Claude Opus 4.7" : undefined,
    );

    expect(info.name).toBe("Alpha");
    expect(info.functionLabel).toBe("科研负责人");
    expect(info.modelLabel).toBe("Claude Opus 4.7");
    expect(info.meta).toBe("科研负责人 · Claude Opus 4.7 · A011");
  });
});
