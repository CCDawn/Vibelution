import { describe, expect, it } from "vitest";

import routeSource from "../AgentsRoute.tsx?raw";
import mutationsSource from "./useAgentConfigDraftMutations.ts?raw";

const owners = [
  "saveAgentConfigDraftMutation",
  "discardAgentConfigDraftMutation",
  "updateAgentMutation",
  "promoteAgentModelMutation",
] as const;

describe("agent config draft mutations contract", () => {
  it("owns the config-draft write mutations", () => {
    expect(mutationsSource.match(/\buseMutation\(/g) ?? []).toHaveLength(owners.length);
    owners.forEach((owner) => {
      expect(mutationsSource).toContain(`const ${owner} = useMutation({`);
    });
  });

  it("is wired from AgentsRoute without inline definitions", () => {
    expect(routeSource).toContain("useAgentConfigDraftMutations({");
    owners.forEach((owner) => {
      expect(routeSource).not.toContain(`const ${owner} = useMutation({`);
      expect(routeSource).toContain(owner);
    });
  });

  it("preserves draft and promote endpoints", () => {
    expect(mutationsSource).toContain("saveAgentConfigDraft(");
    expect(mutationsSource).toContain("discardAgentConfigDraft(");
    expect(mutationsSource).toContain("promoteAgentModel<AgentModelPromotionResult>(");
    expect(mutationsSource).not.toContain("fetchJson");
    expect(mutationsSource).not.toContain('from "../../api/client"');
  });

  it("sends the permission preset only with basic fields and preserves config revision concurrency", () => {
    expect(mutationsSource).toContain('payload.group === "basic"');
    expect(mutationsSource).toContain("body.permissionPreset = payload.draft.permissionPreset");
    expect(mutationsSource).toContain('payload.group === "models"');
    expect(mutationsSource).toContain("expectedConfigRevision: payload.agent.configRevision");
  });

  it("omits untouched context compression from agent config PATCH", () => {
    expect(mutationsSource).toContain("contextCompressionPolicyChangedInDraft");
    expect(mutationsSource).toContain("if (compressionChanged)");
    expect(routeSource).toContain("contextCompressionPolicyChangedInDraft");
  });

  it("gates basic saves on custom compression values without affecting model saves", () => {
    expect(routeSource).toContain("const canSaveConfigModels = Boolean(selectedAgent?.agentId && configModelsDirty);");
    expect(routeSource).toContain("isContextCompressionPolicyDraftValid(configDraft.contextCompressionPolicy)");
  });
});
