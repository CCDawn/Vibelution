import { describe, expect, it } from "vitest";

import type { AgentConfigWorkspaceAgent } from "../../api/types";
import {
  DEFAULT_AGENT_CONTEXT_COMPRESSION_DRAFT,
  configDraftEqualsDraft,
  contextCompressionDraftFromAgent,
  contextCompressionPolicyChangedInDraft,
  contextCompressionPolicyFromDraft,
  draftFromAgent,
  draftEqualsAgent,
  expertiseFromDraft,
  isWorkSessionAgent,
  personaDraftEqualsDraft,
  personaDraftFromAgent,
  personaProfileFromDraft,
  sortedIds,
  taskDraftEqualsDraft,
  taskDraftFromAgent,
  taskProfileFromDraft,
} from "./agentRouteDraftModel";

describe("agentRouteDraftModel", () => {
  it("sorts ids and splits expertise lists", () => {
    expect(sortedIds(["b", "a", "a", ""])).toEqual(["a", "b"]);
    expect(expertiseFromDraft("alpha, beta；gamma")).toEqual(["alpha", "beta", "gamma"]);
  });

  it("round-trips persona and task drafts", () => {
    const agent = {
      agentId: "a1",
      displayName: "助手",
      personaProfile: {
        gender: "女",
        personality: "冷静",
        expertise: ["检索", "写作"],
      },
      taskProfile: {
        mission: "支持研究",
        taskTypes: ["综述"],
      },
      llmBindings: { dialogue: { modelId: "m1" } },
      status: "active",
    } as AgentConfigWorkspaceAgent;

    const persona = personaDraftFromAgent(agent);
    expect(persona.expertise).toContain("检索");
    expect(personaProfileFromDraft(persona).expertise).toEqual(sortedIds(["检索", "写作"]));

    const task = taskDraftFromAgent(agent);
    expect(task.taskTypes).toContain("综述");
    expect(taskProfileFromDraft(task).mission).toBe("支持研究");

    const draft = draftFromAgent(agent);
    expect(draft.displayName).toBe("助手");
    expect(draft.permissionPreset).toBe("request_approval");
    expect(draftEqualsAgent(draft, agent)).toBe(true);
  });

  it("maps inherit/custom context compression drafts", () => {
    const inherit = contextCompressionDraftFromAgent({
      contextCompressionPolicy: { mode: "inherit" },
    } as AgentConfigWorkspaceAgent);
    expect(inherit.mode).toBe("inherit");
    // Backend requires explicit custom; UI inherit materializes displayed values.
    expect(contextCompressionPolicyFromDraft(inherit).mode).toBe("custom");

    const customDraft = {
      ...inherit,
      mode: "custom" as const,
      enabled: true,
      maxTokenLimit: "8000",
      maxCompressionsPerSession: "10",
      lightThreshold: "50",
      standardThreshold: "70",
      deepThreshold: "85",
      emergencyThreshold: "95",
      lightSummaryChars: "400",
      standardSummaryChars: "800",
      deepSummaryChars: "1200",
      emergencySummaryChars: "1600",
      keepAiMessages: "4",
      preserveErrors: true,
      extractKeyDecisions: false,
    };
    const policy = contextCompressionPolicyFromDraft(customDraft);
    expect(policy.mode).toBe("custom");
    expect(policy.maxTokenLimit).toBe(8000);
  });

  it("does not treat an untouched compression form as a patch field", () => {
    const agent = {
      displayName: "助手",
      contextCompressionPolicy: { mode: "inherit" },
      contextCompressionEffectivePolicy: {
        mode: "custom",
        enabled: true,
        maxTokenLimit: 16000,
        maxCompressionsPerSession: 20,
        levels: { light: 0.6, standard: 0.8, deep: 0.9, emergency: 0.95 },
        summaryChars: { light: 400, standard: 800, deep: 1200, emergency: 1600 },
        preservation: { keepAiMessages: 4, preserveErrors: true, extractKeyDecisions: true },
      },
      permissionPreset: "request_approval",
      status: "active",
    } as AgentConfigWorkspaceAgent;
    const draft = draftFromAgent(agent);
    draft.displayName = "改个名字";
    expect(contextCompressionPolicyChangedInDraft(draft, agent)).toBe(false);
    draft.contextCompressionPolicy = {
      ...draft.contextCompressionPolicy,
      mode: "custom",
      maxTokenLimit: "99999",
    };
    expect(contextCompressionPolicyChangedInDraft(draft, agent)).toBe(true);
  });

  it("starts a new Agent with an explicit 262144 compression policy", () => {
    const draft = contextCompressionDraftFromAgent(undefined);

    expect(DEFAULT_AGENT_CONTEXT_COMPRESSION_DRAFT.mode).toBe("custom");
    expect(draft.mode).toBe("custom");
    expect(draft.enabled).toBe(true);
    expect(draft.maxTokenLimit).toBe("262144");
    expect(contextCompressionPolicyFromDraft(draft)).toMatchObject({
      mode: "custom",
      enabled: true,
      maxTokenLimit: 262144,
    });
  });

  it("detects work-session agents from boundary type", () => {
    expect(isWorkSessionAgent({
      agentBoundary: { type: "work_session" },
    } as AgentConfigWorkspaceAgent)).toBe(true);
    expect(isWorkSessionAgent({
      agentBoundary: { type: "team_role" },
    } as AgentConfigWorkspaceAgent)).toBe(false);
  });

  it("compares config/persona/task drafts for dirty-sync equality", () => {
    const agent = {
      agentId: "a1",
      displayName: "助手",
      promptTemplateId: "p1",
      toolPolicyId: "t1",
      memoryPolicyId: "m1",
      permissionPreset: "auto_review",
      status: "active",
      llmBindings: { dialogue: { modelId: "m1" } },
      personaProfile: { gender: "女", personality: "冷静" },
      taskProfile: { mission: "研究" },
    } as AgentConfigWorkspaceAgent;
    const config = draftFromAgent(agent);
    expect(config.permissionPreset).toBe("auto_review");
    expect(configDraftEqualsDraft(config, config)).toBe(true);
    expect(draftEqualsAgent({ ...config, permissionPreset: "full_access" }, agent)).toBe(false);
    expect(configDraftEqualsDraft(config, { ...config, displayName: "x" })).toBe(false);
    const persona = personaDraftFromAgent(agent);
    expect(personaDraftEqualsDraft(persona, persona)).toBe(true);
    const task = taskDraftFromAgent(agent);
    expect(taskDraftEqualsDraft(task, task)).toBe(true);
  });
});
