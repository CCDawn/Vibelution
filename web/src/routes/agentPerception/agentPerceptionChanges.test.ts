import { describe, expect, it } from "vitest";

import { defaultAgentPerceptionPolicy } from "./agentPerceptionDraft";
import { perceptionPolicyChanges } from "./agentPerceptionChanges";

describe("perceptionPolicyChanges", () => {
  it("returns no changes for policies equal after canonical normalization", () => {
    const saved = defaultAgentPerceptionPolicy();
    const draft = defaultAgentPerceptionPolicy();
    saved.sources.team.teamIds = ["team-a", "team-b"];
    draft.sources.team.teamIds = [" team-b ", "team-a", "team-a"];
    saved.sources.knowledge.scope = "all_authorized";
    saved.sources.knowledge.knowledgeBaseIds = [];
    draft.sources.knowledge.scope = "all_authorized";
    draft.sources.knowledge.knowledgeBaseIds = ["ignored-by-all-authorized-scope"];
    saved.sources.knowledge.excludedKnowledgeBaseIds = ["base-a", "base-b"];
    draft.sources.knowledge.excludedKnowledgeBaseIds = ["base-b", "base-a", "base-a"];
    saved.background.topics = ["依赖 审计", "仓库 安全"];
    draft.background.topics = [" 仓库   安全 ", "依赖\t审计"];

    expect(perceptionPolicyChanges(draft, saved, "zh")).toEqual([]);
  });

  it("names each affected source and separates source, background, and notification changes", () => {
    const saved = defaultAgentPerceptionPolicy();
    const draft = defaultAgentPerceptionPolicy();
    draft.enabled = true;
    draft.sources.personal.mode = "manual";
    draft.sources.team.mode = "auto";
    draft.sources.team.teamIds = ["team-a"];
    draft.sources.knowledge.mode = "auto";
    draft.sources.knowledge.scope = "all_authorized";
    draft.sources.knowledge.excludedKnowledgeBaseIds = ["base-a"];
    draft.sources.projects.mode = "manual";
    draft.background.enabled = true;
    draft.background.intervalMinutes = 120;
    draft.background.topics = ["依赖安全审计"];
    draft.notifications.mode = "quiet";

    const changes = perceptionPolicyChanges(draft, saved, "zh");
    const summary = changes.join("\n");

    expect(changes.length).toBeGreaterThanOrEqual(6);
    expect(summary).toContain("个人记忆与私有知识库");
    expect(summary).toContain("指定团队");
    expect(summary).toContain("授权知识库");
    expect(summary).toContain("本地成熟项目索引");
    expect(summary).toContain("按需查询");
    expect(summary).toContain("自动感知");
    expect(summary).toContain("后台调研");
    expect(summary).toContain("通知");
  });

  it("returns user-readable English labels when the Agent center uses English", () => {
    const saved = defaultAgentPerceptionPolicy();
    const draft = defaultAgentPerceptionPolicy();
    draft.sources.team.mode = "manual";
    draft.background.enabled = true;
    draft.background.topics = ["Review dependency advisories"];

    const summary = perceptionPolicyChanges(draft, saved, "en").join("\n");

    expect(summary).toContain("Selected teams");
    expect(summary).toContain("On demand");
    expect(summary).toContain("Background research");
  });
});
