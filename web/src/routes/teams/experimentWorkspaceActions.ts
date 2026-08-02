/**
 * Experiment + research-loop workspace action adapters for Teams shell.
 * Pure factory: mutations and drafts stay route-owned; this only binds guards.
 */
import type { ExperimentPlanMethodRequest } from "../TeamExperimentMethodPanel";
import type {
  EngineeringProxyHypothesisDraft,
  ExperimentBaselineArtifactDraft,
  ExperimentFullRunResultDraft,
  ExperimentKnowledgeIngestionDraft,
  ExperimentPlanRecord,
  ExperimentSmokeResultDraft,
  ResearchLoopCreateDraft,
  ResearchLoopDecisionDraft,
  ResearchLoopEvidenceDraft,
  ResearchLoopRecord,
  ResearchLoopStatusPayload,
  ResearchLoopTemplatesPayload,
  ExperimentPlanningStatusPayload,
} from "./experimentLoopModel";
import type { ResearchStagePhaseStatus } from "./source-collection/stageProjection";

type MutateFn<TVariables> = {
  mutate: (variables: TVariables) => void;
};

export type ExperimentWorkspaceActionDeps = {
  teamId: string;
  createExperimentPlanPending: boolean;
  materializeEngineeringProxyPending: boolean;
  completeScientificHypothesisCandidateId: string;
  reviewExperimentHypothesisCandidateId: string;
  createExperimentHypothesisRevisionCandidateId: string;
  freezeExperimentDesignPending: boolean;
  registerExperimentBaselineArtifactPending: boolean;
  registerExperimentSmokeResultPending: boolean;
  runExperimentSmokePending: boolean;
  registerExperimentFullRunResultPending: boolean;
  requestExperimentKnowledgeIngestionPending: boolean;
  createResearchLoopPending: boolean;
  recordResearchLoopEvidencePending: boolean;
  recordResearchLoopDecisionPending: boolean;
  researchStagePhases: ResearchStagePhaseStatus[];
  experimentPlanningStatus: ExperimentPlanningStatusPayload | null | undefined;
  sourceCollectionDraftTitle: string;
  sourceCollectionDraftGoal: string;
  experimentBaselineArtifactDraft: ExperimentBaselineArtifactDraft;
  experimentSmokeResultDraft: ExperimentSmokeResultDraft;
  experimentFullRunResultDraft: ExperimentFullRunResultDraft;
  experimentKnowledgeIngestionDraft: ExperimentKnowledgeIngestionDraft;
  selectedResearchLoopTemplateId: string;
  researchLoopCreateDraft: ResearchLoopCreateDraft;
  researchLoopEvidenceDraft: ResearchLoopEvidenceDraft;
  researchLoopDecisionDraft: ResearchLoopDecisionDraft;
  researchLoopTemplatesPayload: ResearchLoopTemplatesPayload | null | undefined;
  researchLoopStatus: ResearchLoopStatusPayload | null | undefined;
  createExperimentPlanMutation: MutateFn<{
    teamId: string;
    stageRoundId?: string;
    title?: string;
    methodRequest?: ExperimentPlanMethodRequest;
  }>;
  materializeEngineeringProxyHypothesisMutation: MutateFn<{
    teamId: string;
    plan: ExperimentPlanRecord;
    draft: EngineeringProxyHypothesisDraft;
  }>;
  completeScientificHypothesisFromDesignMutation: MutateFn<{
    teamId: string;
    plan: ExperimentPlanRecord;
    candidateId: string;
    methodRequest: ExperimentPlanMethodRequest;
  }>;
  reviewExperimentHypothesisMutation: MutateFn<{ teamId: string; candidateId: string }>;
  createExperimentHypothesisRevisionMutation: MutateFn<{
    teamId: string;
    plan: ExperimentPlanRecord;
    candidateId: string;
  }>;
  registerExperimentBaselineArtifactMutation: MutateFn<{
    teamId: string;
    plan: ExperimentPlanRecord;
    draft: ExperimentBaselineArtifactDraft;
  }>;
  freezeExperimentDesignMutation: MutateFn<{ teamId: string; plan: ExperimentPlanRecord }>;
  registerExperimentSmokeResultMutation: MutateFn<{
    teamId: string;
    plan: ExperimentPlanRecord;
    draft: ExperimentSmokeResultDraft;
  }>;
  runExperimentSmokeMutation: MutateFn<{
    teamId: string;
    plan: ExperimentPlanRecord;
    adapter: string;
    seed: number;
  }>;
  registerExperimentFullRunResultMutation: MutateFn<{
    teamId: string;
    plan: ExperimentPlanRecord;
    draft: ExperimentFullRunResultDraft;
  }>;
  requestExperimentKnowledgeIngestionMutation: MutateFn<{
    teamId: string;
    plan: ExperimentPlanRecord;
    draft: ExperimentKnowledgeIngestionDraft;
  }>;
  createResearchLoopMutation: MutateFn<{
    teamId: string;
    plan: ExperimentPlanRecord | null;
    templateId: string;
    draft: ResearchLoopCreateDraft;
  }>;
  recordResearchLoopEvidenceMutation: MutateFn<{
    teamId: string;
    loop: ResearchLoopRecord;
    draft: ResearchLoopEvidenceDraft;
    evidenceType: string;
  }>;
  recordResearchLoopDecisionMutation: MutateFn<{
    teamId: string;
    loop: ResearchLoopRecord;
    draft: ResearchLoopDecisionDraft;
    nextTemplateId: string;
  }>;
};

export function createExperimentWorkspaceActions(deps: ExperimentWorkspaceActionDeps) {
  function createExperimentPlanFromWorkspace(methodRequest?: ExperimentPlanMethodRequest) {
    if (!deps.teamId || deps.createExperimentPlanPending) {
      return;
    }
    const experimentPhase = deps.researchStagePhases.find((phase) => phase.stageType === "experiment");
    const stageRoundId =
      experimentPhase?.activeRoundId
      || experimentPhase?.latestRound?.stageRoundId
      || deps.experimentPlanningStatus?.latestExperimentRound?.stageRoundId
      || "";
    deps.createExperimentPlanMutation.mutate({
      teamId: deps.teamId,
      stageRoundId,
      title: deps.sourceCollectionDraftTitle.trim() || experimentPhase?.latestRound?.title || "",
      methodRequest,
    });
  }

  function materializeEngineeringProxyHypothesisFromWorkspace(
    plan: ExperimentPlanRecord,
    draft: EngineeringProxyHypothesisDraft,
  ) {
    if (!deps.teamId || deps.materializeEngineeringProxyPending) {
      return;
    }
    deps.materializeEngineeringProxyHypothesisMutation.mutate({
      teamId: deps.teamId,
      plan,
      draft,
    });
  }

  function reviewExperimentHypothesisFromWorkspace(candidateId: string) {
    if (!deps.teamId || deps.reviewExperimentHypothesisCandidateId) {
      return;
    }
    deps.reviewExperimentHypothesisMutation.mutate({
      teamId: deps.teamId,
      candidateId,
    });
  }

  function completeScientificHypothesisFromWorkspace(
    plan: ExperimentPlanRecord,
    candidateId: string,
    methodRequest: ExperimentPlanMethodRequest,
  ) {
    if (!deps.teamId || deps.completeScientificHypothesisCandidateId) {
      return;
    }
    deps.completeScientificHypothesisFromDesignMutation.mutate({
      teamId: deps.teamId,
      plan,
      candidateId,
      methodRequest,
    });
  }

  function createExperimentHypothesisRevisionFromWorkspace(
    plan: ExperimentPlanRecord,
    candidateId: string,
  ) {
    if (!deps.teamId) {
      return;
    }
    // The server de-duplicates revisions by plan and candidate. Keep the UI
    // pending marker presentational so a stale marker cannot swallow a click.
    deps.createExperimentHypothesisRevisionMutation.mutate({
      teamId: deps.teamId,
      plan,
      candidateId,
    });
  }

  function registerExperimentBaselineArtifactFromWorkspace(plan: ExperimentPlanRecord) {
    if (!deps.teamId || deps.registerExperimentBaselineArtifactPending) {
      return;
    }
    deps.registerExperimentBaselineArtifactMutation.mutate({
      teamId: deps.teamId,
      plan,
      draft: deps.experimentBaselineArtifactDraft,
    });
  }

  function freezeExperimentDesignFromWorkspace(plan: ExperimentPlanRecord) {
    if (!deps.teamId || deps.freezeExperimentDesignPending) {
      return;
    }
    deps.freezeExperimentDesignMutation.mutate({ teamId: deps.teamId, plan });
  }

  function registerExperimentSmokeResultFromWorkspace(plan: ExperimentPlanRecord) {
    if (!deps.teamId || deps.registerExperimentSmokeResultPending) {
      return;
    }
    deps.registerExperimentSmokeResultMutation.mutate({
      teamId: deps.teamId,
      plan,
      draft: deps.experimentSmokeResultDraft,
    });
  }

  function runExperimentSmokeFromWorkspace(plan: ExperimentPlanRecord, adapter: string, seed: number) {
    if (!deps.teamId || deps.runExperimentSmokePending) {
      return;
    }
    deps.runExperimentSmokeMutation.mutate({
      teamId: deps.teamId,
      plan,
      adapter,
      seed,
    });
  }

  function registerExperimentFullRunResultFromWorkspace(plan: ExperimentPlanRecord) {
    if (!deps.teamId || deps.registerExperimentFullRunResultPending) {
      return;
    }
    deps.registerExperimentFullRunResultMutation.mutate({
      teamId: deps.teamId,
      plan,
      draft: deps.experimentFullRunResultDraft,
    });
  }

  function requestExperimentKnowledgeIngestionFromWorkspace(plan: ExperimentPlanRecord) {
    if (!deps.teamId || deps.requestExperimentKnowledgeIngestionPending) {
      return;
    }
    deps.requestExperimentKnowledgeIngestionMutation.mutate({
      teamId: deps.teamId,
      plan,
      draft: deps.experimentKnowledgeIngestionDraft,
    });
  }

  function createResearchLoopFromWorkspace(plan: ExperimentPlanRecord | null) {
    if (!deps.teamId || deps.createResearchLoopPending) {
      return;
    }
    const templates = deps.researchLoopTemplatesPayload?.templates ?? deps.researchLoopStatus?.templates ?? [];
    const templateId =
      deps.selectedResearchLoopTemplateId
      || deps.researchLoopTemplatesPayload?.defaultTemplateId
      || templates[0]?.templateId
      || "algorithm_model_experiment";
    const researchQuestion =
      deps.researchLoopCreateDraft.researchQuestion.trim()
      || plan?.goal
      || plan?.topic
      || deps.sourceCollectionDraftGoal;
    if (!researchQuestion.trim()) {
      return;
    }
    deps.createResearchLoopMutation.mutate({
      teamId: deps.teamId,
      plan,
      templateId,
      draft: deps.researchLoopCreateDraft,
    });
  }

  function recordResearchLoopEvidenceFromWorkspace(loop: ResearchLoopRecord) {
    if (!deps.teamId || deps.recordResearchLoopEvidencePending) {
      return;
    }
    const evidenceType =
      deps.researchLoopEvidenceDraft.evidenceType
      || loop.readiness.missingEvidenceTypes[0]
      || loop.readiness.requiredEvidenceTypes[0]
      || "";
    const hasEvidencePayload = Boolean(
      deps.researchLoopEvidenceDraft.summary.trim()
      || deps.researchLoopEvidenceDraft.metricValue.trim()
      || deps.researchLoopEvidenceDraft.artifactRef.trim()
      || deps.researchLoopEvidenceDraft.datasetRefs.trim()
      || deps.researchLoopEvidenceDraft.environmentRefs.trim()
      || deps.researchLoopEvidenceDraft.logRefs.trim()
      || deps.researchLoopEvidenceDraft.commandPreview.trim(),
    );
    if (!evidenceType || !hasEvidencePayload) {
      return;
    }
    deps.recordResearchLoopEvidenceMutation.mutate({
      teamId: deps.teamId,
      loop,
      draft: deps.researchLoopEvidenceDraft,
      evidenceType,
    });
  }

  function recordResearchLoopDecisionFromWorkspace(loop: ResearchLoopRecord) {
    if (!deps.teamId || deps.recordResearchLoopDecisionPending || !deps.researchLoopDecisionDraft.rationale.trim()) {
      return;
    }
    const templates = deps.researchLoopTemplatesPayload?.templates ?? deps.researchLoopStatus?.templates ?? [];
    const nextTemplateId =
      deps.researchLoopDecisionDraft.nextTemplateId
      || deps.selectedResearchLoopTemplateId
      || loop.templateId
      || templates[0]?.templateId
      || "algorithm_model_experiment";
    deps.recordResearchLoopDecisionMutation.mutate({
      teamId: deps.teamId,
      loop,
      draft: deps.researchLoopDecisionDraft,
      nextTemplateId,
    });
  }

  return {
    createExperimentPlanFromWorkspace,
    materializeEngineeringProxyHypothesisFromWorkspace,
    completeScientificHypothesisFromWorkspace,
    reviewExperimentHypothesisFromWorkspace,
    createExperimentHypothesisRevisionFromWorkspace,
    registerExperimentBaselineArtifactFromWorkspace,
    freezeExperimentDesignFromWorkspace,
    registerExperimentSmokeResultFromWorkspace,
    runExperimentSmokeFromWorkspace,
    registerExperimentFullRunResultFromWorkspace,
    requestExperimentKnowledgeIngestionFromWorkspace,
    createResearchLoopFromWorkspace,
    recordResearchLoopEvidenceFromWorkspace,
    recordResearchLoopDecisionFromWorkspace,
  };
}
