import { describe, expect, it } from "vitest";

import type { EvolutionActiveRun, EvolutionLibraryEntry, EvolutionProposalDetail, EvolutionWorkflowStep } from "../../api/types";
import {
  activeSupervisedWorkflowStep,
  canOpenProposalSourceRun,
  clampScore,
  compactTimestamp,
  isSelfEvolutionCandidateItem,
  proposalDisplaySourceRun,
  proposalEditDraftFromDetail,
  supervisedDatasetLimitFromInput,
  supervisedMemberChatRoute,
  supervisedProposalStatusLabel,
  supervisedRoleConversationSession,
  supervisedWorkflowStepLabel,
  toLimitInput,
  SUPERVISED_WORKFLOW_STEPS,
  SUPERVISED_RUN_MEMBER_ROLES,
} from "./evolutionRouteModel";

describe("evolutionRouteModel", () => {
  it("keeps every runtime conversation Agent available to the supervised UI", () => {
    expect(SUPERVISED_RUN_MEMBER_ROLES).toEqual(["baseline", "candidate", "judge"]);
  });

  it("clamps scores and formats compact timestamps", () => {
    expect(clampScore(120)).toBe(100);
    expect(clampScore(-3)).toBe(0);
    expect(clampScore(42.4)).toBe(42);
    expect(toLimitInput(12)).toBe("12");
    expect(toLimitInput(0)).toBe("");
    expect(compactTimestamp("2026-07-26T12:34:56.789Z")).toBe("2026-07-26 12:34:56");
  });

  it("submits the visible supervised dataset limit and ignores invalid limits", () => {
    expect(supervisedDatasetLimitFromInput("dataset", " 1 ")).toBe(1);
    expect(supervisedDatasetLimitFromInput("dataset", "4.8")).toBe(4);
    expect(supervisedDatasetLimitFromInput("dataset", "")).toBeNull();
    expect(supervisedDatasetLimitFromInput("dataset", "0")).toBeNull();
    expect(supervisedDatasetLimitFromInput("bundle", "1")).toBeNull();
  });

  it("projects the current worktree workflow session into its Agent conversation", () => {
    const steps = [
      {
        id: "baseline_eval",
        role: "baseline",
        status: "running",
        current: true,
        summary: "等待基线输出",
        livePreview: "hidden conversation",
        conversationSessionId: "session-live-baseline",
        conversationTurnId: "turn-1",
      },
    ] as EvolutionWorkflowStep[];

    expect(supervisedRoleConversationSession(steps, "baseline")).toMatchObject({
      role: "baseline",
      status: "running",
      conversationSessionId: "session-live-baseline",
      conversationTurnId: "turn-1",
      latestMessage: "hidden conversation",
    });
    expect(supervisedRoleConversationSession(steps, "candidate")).toBeUndefined();
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
