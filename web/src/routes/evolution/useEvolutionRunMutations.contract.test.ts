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

  it("keeps self-observation status in the canonical selected run projection", () => {
    const observationMutations = runSource.slice(
      runSource.indexOf("const startSelfObservationMutation"),
      runSource.indexOf("const deleteSelfHistoryMutation"),
    );

    expect(observationMutations).not.toContain(
      "setSelfActionFeedback(snapshot.latestMessage",
    );
    expect(
      observationMutations.match(/setSelectedSelfObservationRunId\(snapshot\.runId\)/g) ?? [],
    ).toHaveLength(2);
    expect(
      observationMutations.match(
        /queryKeys\.evolutionSelfObservationRun\(snapshot\.runId\)/g,
      ) ?? [],
    ).toHaveLength(2);
    expect(
      observationMutations.match(/setSelfActionFeedback\(""\)/g) ?? [],
    ).toHaveLength(4);
  });
});
