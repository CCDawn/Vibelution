import { describe, expect, it } from "vitest";

import routeSource from "../EvolutionRoute.tsx?raw";
import runSource from "./useEvolutionRunMutations.ts?raw";
import proposalSource from "./useEvolutionProposalMutations.ts?raw";

describe("evolution mutations contract (T3)", () => {
  it("owns run and proposal write mutations", () => {
    expect(runSource.match(/\buseMutation\(/g) ?? []).toHaveLength(8);
    expect(proposalSource.match(/\buseMutation\(/g) ?? []).toHaveLength(5);
  });

  it("is wired from EvolutionRoute without inline useMutation definitions", () => {
    expect(routeSource).toContain("useEvolutionRunMutations({");
    expect(routeSource).toContain("useEvolutionProposalMutations({");
    expect(routeSource).not.toMatch(/\bconst \w+Mutation = useMutation\(/);
  });
});
