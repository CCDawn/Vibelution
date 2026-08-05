import { describe, expect, it } from "vitest";

import {
  resolveResearchActiveStage,
  resolveResearchAdvanceAction,
  resolveResearchOverviewActions,
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

const knowledgeWithRound = phase("knowledge_collection", {
  roundCount: 1,
  latestRound: { stageRoundId: "r1" } as ResearchStagePhaseStatus["latestRound"],
});

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

  it("continues knowledge collection as primary even when experiment is ready to start", () => {
    const input = {
      hasActiveProject: true,
      sourceRunCount: 2,
      phases: [
        knowledgeWithRound,
        phase("experiment", { readiness: { ready: true }, canStart: true }),
        phase("iteration", { readiness: { ready: false } }),
      ],
    };
    const action = resolveResearchPrimaryAction(input);
    expect(action.kind).toBe("continue_knowledge_collection");
    expect(action.navigateView).toBe("knowledge_collection");
    expect(action.launchStageType).toBeUndefined();

    const advance = resolveResearchAdvanceAction(input);
    expect(advance?.kind).toBe("start_experiment");
    expect(advance?.navigateView).toBe("experiment");
    expect(advance?.labelZh).toContain("离开知识搜集");

    const handoff = resolveResearchStageHandoff(input);
    expect(handoff?.toStage).toBe("experiment");
    expect(handoff?.action.kind).toBe("start_experiment");
  });

  it("continues experiment when experiment rounds exist", () => {
    const action = resolveResearchPrimaryAction({
      hasActiveProject: true,
      sourceRunCount: 1,
      phases: [
        knowledgeWithRound,
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

  it("pins continue to URL stage when currentView is set", () => {
    const action = resolveResearchPrimaryAction({
      hasActiveProject: true,
      sourceRunCount: 1,
      currentView: "knowledge_collection",
      phases: [
        knowledgeWithRound,
        phase("experiment", {
          roundCount: 1,
          latestRound: { stageRoundId: "e1" } as ResearchStagePhaseStatus["latestRound"],
          readiness: { ready: true },
        }),
        phase("iteration", { readiness: { ready: false } }),
      ],
    });
    expect(action.kind).toBe("continue_knowledge_collection");
    expect(resolveResearchActiveStage({
      hasActiveProject: true,
      sourceRunCount: 1,
      currentView: "knowledge_collection",
      phases: [],
    })).toBe("knowledge_collection");
  });
});

describe("resolveResearchOverviewActions", () => {
  it("exposes continue primary and advance secondary without hijack", () => {
    const bag = resolveResearchOverviewActions({
      hasActiveProject: true,
      sourceRunCount: 2,
      phases: [
        knowledgeWithRound,
        phase("experiment", { readiness: { ready: true }, canStart: true }),
        phase("iteration", { readiness: { ready: false } }),
      ],
    });
    expect(bag.activeStage).toBe("knowledge_collection");
    expect(bag.continueAction.kind).toBe("continue_knowledge_collection");
    expect(bag.advanceAction?.kind).toBe("start_experiment");
    expect(bag.unlock.knowledge_collection).toBe(true);
    expect(bag.unlock.experiment).toBe(true);
  });
});
