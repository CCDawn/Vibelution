import { describe, expect, it } from "vitest";

import {
  resolveResearchPrimaryAction,
  resolveResearchStageHandoff,
} from "./researchPrimaryActionModel";
import type { ResearchStagePhaseStatus } from "./source-collection/stageProjection";

function phase(
  stageType: string,
  options: Partial<ResearchStagePhaseStatus> = {},
): ResearchStagePhaseStatus {
  return {
    stageType: stageType as ResearchStagePhaseStatus["stageType"],
    label: stageType,
    status: "idle",
    roundCount: 0,
    activeRoundId: "",
    primaryAction: "",
    secondaryAction: "",
    canStart: false,
    canContinue: false,
    canNewRound: false,
    requiresUserDecision: false,
    ...options,
  };
}

describe("resolveResearchPrimaryAction", () => {
  it("asks for a project when none is active", () => {
    const action = resolveResearchPrimaryAction({
      hasActiveProject: false,
      sourceRunCount: 0,
      phases: [],
    });
    expect(action.kind).toBe("blocked");
    expect(action.blocked).toBe(true);
  });

  it("starts knowledge collection on empty project", () => {
    const action = resolveResearchPrimaryAction({
      hasActiveProject: true,
      sourceRunCount: 0,
      sourceCandidateCount: 0,
      phases: [
        phase("knowledge_collection", { canStart: true, readiness: { ready: true } }),
        phase("experiment", { readiness: { ready: false } }),
        phase("iteration", { readiness: { ready: false } }),
      ],
    });
    expect(action.kind).toBe("start_knowledge_collection");
    expect(action.navigateView).toBe("knowledge_collection");
    expect(action.launchStageType).toBe("knowledge_collection");
  });

  it("continues knowledge collection when candidates exist without runs", () => {
    const action = resolveResearchPrimaryAction({
      hasActiveProject: true,
      sourceRunCount: 0,
      sourceCandidateCount: 23,
      phases: [
        phase("knowledge_collection", { canStart: true, readiness: { ready: true } }),
        phase("experiment", { readiness: { ready: false } }),
        phase("iteration", { readiness: { ready: false } }),
      ],
    });
    expect(action.kind).toBe("continue_knowledge_collection");
  });

  it("hands off to experiment when knowledge exists and experiment is ready", () => {
    const action = resolveResearchPrimaryAction({
      hasActiveProject: true,
      sourceRunCount: 2,
      phases: [
        phase("knowledge_collection", {
          roundCount: 1,
          latestRound: { stageRoundId: "r1" } as ResearchStagePhaseStatus["latestRound"],
        }),
        phase("experiment", { readiness: { ready: true }, canStart: true }),
        phase("iteration", { readiness: { ready: false } }),
      ],
    });
    expect(action.kind).toBe("start_experiment");
    expect(action.navigateView).toBe("experiment");
    const handoff = resolveResearchStageHandoff({
      hasActiveProject: true,
      sourceRunCount: 2,
      phases: [
        phase("knowledge_collection", {
          roundCount: 1,
          latestRound: { stageRoundId: "r1" } as ResearchStagePhaseStatus["latestRound"],
        }),
        phase("experiment", { readiness: { ready: true }, canStart: true }),
        phase("iteration", { readiness: { ready: false } }),
      ],
    });
    expect(handoff?.toStage).toBe("experiment");
  });

  it("continues experiment when experiment rounds exist", () => {
    const action = resolveResearchPrimaryAction({
      hasActiveProject: true,
      sourceRunCount: 1,
      phases: [
        phase("knowledge_collection", { roundCount: 1 }),
        phase("experiment", {
          roundCount: 1,
          latestRound: { stageRoundId: "e1" } as ResearchStagePhaseStatus["latestRound"],
          readiness: { ready: true },
        }),
        phase("iteration", { readiness: { ready: false } }),
      ],
    });
    expect(action.kind).toBe("continue_experiment");
  });
});
