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
    expect(mutationsSource).toContain("/config-drafts");
    expect(mutationsSource).toContain("/promote");
  });
});
