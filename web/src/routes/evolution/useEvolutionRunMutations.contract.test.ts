import { describe, expect, it } from "vitest";

import routeSource from "../EvolutionRoute.tsx?raw";
import autonomousApiSource from "../../api/selfEvolution.ts?raw";
import runSource from "./useEvolutionRunMutations.ts?raw";
import proposalSource from "./useEvolutionProposalMutations.ts?raw";

describe("evolution mutations contract (T3)", () => {
  it("owns run and proposal write mutations", () => {
    expect(runSource.match(/\buseMutation\(/g) ?? []).toHaveLength(10);
    expect(proposalSource.match(/\buseMutation\(/g) ?? []).toHaveLength(5);
  });

  it("keeps autonomous self-evolution transport in the domain API layer", () => {
    expect(runSource).toContain("startSelfEvolutionAutonomousLoop(payload)");
    expect(runSource).toContain("executeSelfEvolutionAutonomousLoopAction(payload)");
    expect(runSource).not.toContain('fetchJson<SelfEvolutionAutonomousLoopRun>');
    expect(autonomousApiSource).toContain('"/api/evolution/self/autonomous-runs"');
    expect(autonomousApiSource).toContain("encodeURIComponent(payload.runId)");
    expect(autonomousApiSource).toContain("comment: payload.comment ?? \"\"");
  });

  it("is wired from EvolutionRoute without inline useMutation definitions", () => {
    expect(routeSource).toContain("useEvolutionRunMutations({");
    expect(routeSource).toContain("useEvolutionProposalMutations({");
    expect(routeSource).not.toMatch(/\bconst \w+Mutation = useMutation\(/);
  });

  it("keeps self-observation status in the canonical selected run projection", () => {
    const observationMutations = runSource.slice(
      runSource.indexOf("const startSelfObservationMutation"),
      runSource.indexOf("const startSelfAutonomousLoopMutation"),
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

  it("freezes the selected approval mode into real and simulation start requests", () => {
    expect(runSource).toContain('approvalMode: "human" | "agent"');
    expect(runSource.match(/approvalMode: payload\.approvalMode/g) ?? []).toHaveLength(3);
    expect(routeSource).toContain('useState<"human" | "agent">("human")');
    // The approval-mode picker UI lives in EvolutionSupervisedLiveSetupPanel
    // (thin-route split); the route keeps the state + freeze wiring.
    expect(routeSource).toContain('approvalMode={approvalMode}');
  });
});
