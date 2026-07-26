import { describe, expect, it } from "vitest";

import type { EvolutionActiveRun, EvolutionLibraryEntry, EvolutionProposalDetail } from "../../api/types";
import {
  activeSupervisedWorkflowStep,
  canOpenProposalSourceRun,
  clampScore,
  compactTimestamp,
  isSelfEvolutionCandidateItem,
  proposalDisplaySourceRun,
  proposalEditDraftFromDetail,
  supervisedMemberChatRoute,
  supervisedProposalStatusLabel,
  supervisedWorkflowStepLabel,
  toLimitInput,
  SUPERVISED_WORKFLOW_STEPS,
} from "./evolutionRouteModel";

describe("evolutionRouteModel", () => {
  it("clamps scores and formats compact timestamps", () => {
    expect(clampScore(120)).toBe(100);
    expect(clampScore(-3)).toBe(0);
    expect(clampScore(42.4)).toBe(42);
    expect(toLimitInput(12)).toBe("12");
    expect(toLimitInput(0)).toBe("");
    expect(compactTimestamp("2026-07-26T12:34:56.789Z")).toBe("2026-07-26 12:34:56");
  });

  it("labels workflow steps and resolves active step from role/phase", () => {
    const step = SUPERVISED_WORKFLOW_STEPS[0];
    expect(supervisedWorkflowStepLabel(step, "zh")).toBe("基线评测");
    expect(activeSupervisedWorkflowStep({ currentRole: "candidate" } as EvolutionActiveRun)).toBe("rerun_score");
    expect(activeSupervisedWorkflowStep({ currentPhase: "reflection" } as EvolutionActiveRun)).toBe("improve");
  });

  it("maps proposal draft and self-evolution source display", () => {
    const detail = {
      proposal: {
        improvementType: "prompt",
        expectedEffect: "better",
        summary: "s",
        candidatePrompt: "c",
        baselinePrompt: "b",
        editNote: "n",
      },
      review: { changeSummary: "fallback" },
    } as EvolutionProposalDetail;
    expect(proposalEditDraftFromDetail(detail).candidatePrompt).toBe("c");

    const selfItem = {
      ingestMode: "self_evolution_candidate",
      sourceSelfRunId: "self-1",
      sourceRun: "sup-1",
    } as EvolutionLibraryEntry;
    expect(isSelfEvolutionCandidateItem(selfItem)).toBe(true);
    expect(proposalDisplaySourceRun(selfItem)).toBe("self-1");
    expect(canOpenProposalSourceRun(selfItem)).toBe(false);
    expect(supervisedProposalStatusLabel("rejected", "raw", "zh")).toBe("未入库");
    expect(supervisedMemberChatRoute("sess-1", "/evolution", "back")).toContain("session=sess-1");
  });
});
