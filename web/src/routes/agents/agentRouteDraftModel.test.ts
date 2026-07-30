import { describe, expect, it } from "vitest";

import type { AgentConfigWorkspaceAgent } from "../../api/types";
import {
  configDraftEqualsDraft,
  contextCompressionDraftFromAgent,
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
    expect(contextCompressionPolicyFromDraft(inherit)).toEqual({ mode: "inherit" });

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
