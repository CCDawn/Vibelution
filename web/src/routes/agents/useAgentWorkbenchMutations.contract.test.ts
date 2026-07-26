import { describe, expect, it } from "vitest";

import routeSource from "../AgentsRoute.tsx?raw";
import mutationsSource from "./useAgentWorkbenchMutations.ts?raw";

const owners = [
  "updatePersonaMutation",
  "updateTaskMutation",
  "archiveAgentMutation",
  "purgeAgentMutation",
  "resetAgentMutation",
  "updateAvatarMutation",
  "uploadAvatarMutation",
  "updateMembershipMutation",
  "updateToolPolicyMutation",
  "createToolGovernanceMutation",
  "resolveToolGovernanceMutation",
  "updateMemoryPolicyMutation",
  "updateRuntimePolicyMutation",
  "consumeMessageMutation",
  "consumeAllMessagesMutation",
] as const;

describe("agent workbench mutations contract", () => {
  it("owns profile/lifecycle/policy/inbox write mutations", () => {
    expect(mutationsSource.match(/\buseMutation\(/g) ?? []).toHaveLength(owners.length);
    owners.forEach((owner) => {
      expect(mutationsSource).toContain(`const ${owner} = useMutation({`);
    });
  });

  it("is wired from AgentsRoute without inline definitions", () => {
    expect(routeSource).toContain("useAgentWorkbenchMutations({");
    expect(routeSource).not.toMatch(/\bconst \w+Mutation = useMutation\(/);
    owners.forEach((owner) => {
      expect(routeSource).not.toContain(`const ${owner} = useMutation({`);
      expect(routeSource).toContain(owner);
    });
  });
});
