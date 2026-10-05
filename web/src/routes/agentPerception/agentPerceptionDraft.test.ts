import { describe, expect, it } from "vitest";

import {
  agentPerceptionPoliciesEqual,
  canonicalAgentPerceptionPolicy,
  defaultAgentPerceptionPolicy,
  setKnowledgeBaseScope,
  togglePerceptionScopeId,
  validateAgentPerceptionPolicy,
} from "./agentPerceptionDraft";

describe("agent perception policy drafts", () => {
  it("starts with a closed policy and stable source defaults", () => {
    const policy = defaultAgentPerceptionPolicy();
    expect(policy.enabled).toBe(false);
    expect(policy.sources.personal.mode).toBe("off");
    expect(policy.sources.team.triggers).toEqual({ task: false, update: false, background: false });
    expect(policy.background.maxConcurrent).toBe(1);
  });

  it("changes owner-scoped selections without mutating the source policy", () => {
    const initial = defaultAgentPerceptionPolicy();
    const next = togglePerceptionScopeId(initial, "team", "team:alpha", true);
    expect(initial.sources.team.teamIds).toEqual([]);
    expect(next.sources.team.teamIds).toEqual(["team:alpha"]);
  });

  it("clears selected IDs when switching to all-authorized while preserving exclusions", () => {
    const policy = defaultAgentPerceptionPolicy();
    policy.sources.knowledge.knowledgeBaseIds = ["team:a:kb1"];
    policy.sources.knowledge.excludedKnowledgeBaseIds = ["team:b:kb2"];
    const next = setKnowledgeBaseScope(policy, "all_authorized");
    expect(next.sources.knowledge.scope).toBe("all_authorized");
    expect(next.sources.knowledge.knowledgeBaseIds).toEqual([]);
    expect(next.sources.knowledge.excludedKnowledgeBaseIds).toEqual(["team:b:kb2"]);
  });

  it("compares canonical owner scopes independent of order and duplicates", () => {
    const left = defaultAgentPerceptionPolicy();
    const right = defaultAgentPerceptionPolicy();
    left.sources.team.teamIds = ["team:b", "team:a"];
    right.sources.team.teamIds = ["team:a", "team:b", "team:a"];
    expect(agentPerceptionPoliciesEqual(left, right)).toBe(true);
    expect(canonicalAgentPerceptionPolicy(right).sources.team.teamIds).toEqual(["team:a", "team:b"]);
  });

  it("requires a user-defined topic and bounded budgets for background research", () => {
    const policy = defaultAgentPerceptionPolicy();
    policy.background.enabled = true;
    expect(validateAgentPerceptionPolicy(policy)).toBe("background.topics.required");
    policy.background.topics = ["Review the local governance catalog"];
    expect(validateAgentPerceptionPolicy(policy)).toBeNull();
    policy.background.maxCallsPerRun = 33;
    expect(validateAgentPerceptionPolicy(policy)).toBe("background.maxCallsPerRun");
  });
});
