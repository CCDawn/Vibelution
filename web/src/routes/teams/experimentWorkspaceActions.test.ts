import { describe, expect, it, vi } from "vitest";

import { createExperimentWorkspaceActions } from "./experimentWorkspaceActions";
import type {
  ExperimentPlanRecord,
  ResearchLoopRecord,
} from "./experimentLoopModel";

function baseDeps(overrides: Record<string, unknown> = {}) {
  return {
    teamId: "research-team",
    createExperimentPlanPending: false,
    materializeEngineeringProxyPending: false,
    completeScientificHypothesisCandidateId: "",
    reviewExperimentHypothesisCandidateId: "",
    createExperimentHypothesisRevisionCandidateId: "",
    freezeExperimentDesignPending: false,
    registerExperimentBaselineArtifactPending: false,
    registerExperimentSmokeResultPending: false,
    runExperimentSmokePending: false,
    registerExperimentFullRunResultPending: false,
    requestExperimentKnowledgeIngestionPending: false,
    createResearchLoopPending: false,
    recordResearchLoopEvidencePending: false,
    recordResearchLoopDecisionPending: false,
    researchStagePhases: [
      {
        stageType: "experiment",
        activeRoundId: "round-1",
        latestRound: { stageRoundId: "round-legacy", title: "legacy title" },
      },
    ],
    experimentPlanningStatus: { latestExperimentRound: { stageRoundId: "round-status" } },
    sourceCollectionDraftTitle: "  draft title  ",
    sourceCollectionDraftGoal: "draft goal",
    experimentBaselineArtifactDraft: { name: "baseline" },
    experimentSmokeResultDraft: { summary: "smoke" },
    experimentFullRunResultDraft: { summary: "full" },
    experimentKnowledgeIngestionDraft: { notes: "ingest" },
    selectedResearchLoopTemplateId: "algorithm_model_experiment",
    researchLoopCreateDraft: { researchQuestion: "  " },
    researchLoopEvidenceDraft: {
      evidenceType: "metric",
      summary: "ok",
      metricValue: "",
      artifactRef: "",
      datasetRefs: "",
      environmentRefs: "",
      logRefs: "",
      commandPreview: "",
    },
    researchLoopDecisionDraft: {
      decision: "continue",
      rationale: "because",
      nextTemplateId: "",
    },
    researchLoopTemplatesPayload: {
      defaultTemplateId: "algorithm_model_experiment",
      templates: [{ templateId: "algorithm_model_experiment" }],
    },
    researchLoopStatus: null,
    createExperimentPlanMutation: { mutate: vi.fn() },
    materializeEngineeringProxyHypothesisMutation: { mutate: vi.fn() },
    completeScientificHypothesisFromDesignMutation: { mutate: vi.fn() },
    reviewExperimentHypothesisMutation: { mutate: vi.fn() },
    createExperimentHypothesisRevisionMutation: { mutate: vi.fn() },
    registerExperimentBaselineArtifactMutation: { mutate: vi.fn() },
    freezeExperimentDesignMutation: { mutate: vi.fn() },
    registerExperimentSmokeResultMutation: { mutate: vi.fn() },
    runExperimentSmokeMutation: { mutate: vi.fn() },
    registerExperimentFullRunResultMutation: { mutate: vi.fn() },
    requestExperimentKnowledgeIngestionMutation: { mutate: vi.fn() },
    createResearchLoopMutation: { mutate: vi.fn() },
    recordResearchLoopEvidenceMutation: { mutate: vi.fn() },
    recordResearchLoopDecisionMutation: { mutate: vi.fn() },
    ...overrides,
  } as any;
}

describe("createExperimentWorkspaceActions", () => {
  it("creates experiment plan from active stage round and draft title", () => {
    const deps = baseDeps();
    const actions = createExperimentWorkspaceActions(deps);
    actions.createExperimentPlanFromWorkspace({ methodFamily: "proxy" } as any);
    expect(deps.createExperimentPlanMutation.mutate).toHaveBeenCalledWith({
      teamId: "research-team",
      stageRoundId: "round-1",
      title: "draft title",
      methodRequest: { methodFamily: "proxy" },
    });
  });

  it("completes a scientific hypothesis from the current design without creating a plan", () => {
    const deps = baseDeps();
    const actions = createExperimentWorkspaceActions(deps);
    const plan = { planId: "plan-v6" } as ExperimentPlanRecord;
    const methodRequest = {
      researchQuestion: "Does stage coordination improve the target-data proxy?",
    } as any;

    actions.completeScientificHypothesisFromWorkspace(
      plan,
      "hypothesis-h2",
      methodRequest,
    );

    expect(
      deps.completeScientificHypothesisFromDesignMutation.mutate,
    ).toHaveBeenCalledWith({
      teamId: "research-team",
      plan,
      candidateId: "hypothesis-h2",
      methodRequest,
    });
    expect(deps.createExperimentPlanMutation.mutate).not.toHaveBeenCalled();
  });

  it("skips research loop create without a research question", () => {
    const deps = baseDeps({
      researchLoopCreateDraft: { researchQuestion: "   " },
      sourceCollectionDraftGoal: "",
    });
    const actions = createExperimentWorkspaceActions(deps);
    actions.createResearchLoopFromWorkspace({
      goal: "",
      topic: "",
    } as ExperimentPlanRecord);
    expect(deps.createResearchLoopMutation.mutate).not.toHaveBeenCalled();
  });

  it("records research loop evidence with readiness fallback type", () => {
    const deps = baseDeps({
      researchLoopEvidenceDraft: {
        evidenceType: "",
        summary: "metric summary",
        metricValue: "",
        artifactRef: "",
        datasetRefs: "",
        environmentRefs: "",
        logRefs: "",
        commandPreview: "",
      },
    });
    const loop = {
      readiness: {
        missingEvidenceTypes: ["artifact"],
        requiredEvidenceTypes: ["metric"],
      },
    } as ResearchLoopRecord;
    const actions = createExperimentWorkspaceActions(deps);
    actions.recordResearchLoopEvidenceFromWorkspace(loop);
    expect(deps.recordResearchLoopEvidenceMutation.mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        teamId: "research-team",
        evidenceType: "artifact",
      }),
    );
  });

  it("does not freeze design while pending", () => {
    const deps = baseDeps({ freezeExperimentDesignPending: true });
    const actions = createExperimentWorkspaceActions(deps);
    actions.freezeExperimentDesignFromWorkspace({ planId: "p1" } as ExperimentPlanRecord);
    expect(deps.freezeExperimentDesignMutation.mutate).not.toHaveBeenCalled();
  });
});
