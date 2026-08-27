/**
 * Experiment planning + research-loop write mutations for Teams.
 * EventSource-free; Route remains the draft/view orchestration boundary.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Dispatch, SetStateAction } from "react";

import { queryKeys } from "../../api/queryKeys";
import {
  createResearchLoop,
  materializeResearchLoopIterationDesign,
  recordResearchLoopDecision,
  recordResearchLoopEvidence,
} from "../../api/researchLoop";
import {
  completeTeamScientificHypothesisFromDesign,
  createTeamExperimentHypothesisRevision,
  createTeamExperimentPlan,
  freezeTeamExperimentDesign,
  materializeTeamEngineeringProxyHypothesis,
  registerTeamExperimentBaselineArtifact,
  registerTeamExperimentFullRunResult,
  registerTeamExperimentSmokeResult,
  requestTeamExperimentKnowledgeIngestion,
  resumeTeamExperimentHypothesis,
  reviewTeamExperimentHypothesis,
  runTeamExperimentSmoke,
} from "../../api/teamExperiment";
import type { ExperimentPlanMethodRequest } from "../TeamExperimentMethodPanel";
import {
  trackEngineeringProxyMaterialize,
  trackExperimentBaselineRegister,
  trackExperimentDesignFreeze,
  trackExperimentFullRunResultRegister,
  trackExperimentHypothesisResume,
  trackExperimentHypothesisReview,
  trackExperimentHypothesisRevisionCreate,
  trackExperimentKnowledgeIngestionRequest,
  trackExperimentPlanCreate,
  trackExperimentSmokeResultRegister,
  trackExperimentSmokeRun,
  trackResearchLoopCreate,
  trackResearchLoopDecisionRecord,
  trackResearchLoopEvidenceRecord,
  trackResearchLoopIterationMaterialize,
  trackScientificHypothesisComplete,
} from "./challengeCupTelemetry";
import type { UserActionTracker } from "../../app/userActionTelemetry";
import {
  experimentPlanningStatusQueryKey,
  researchLoopStatusQueryKey,
  type EngineeringProxyHypothesisDraft,
  type ExperimentBaselineArtifactDraft,
  type ExperimentBaselineArtifactRegisterPayload,
  type ExperimentDesignFreezePayload,
  type ExperimentFullRunResultDraft,
  type ExperimentFullRunResultRegisterPayload,
  type ExperimentHypothesisResumePayload,
  type ExperimentKnowledgeIngestionDraft,
  type ExperimentPlanCreatePayload,
  type ExperimentPlanRecord,
  type ExperimentResultKnowledgeIngestionPayload,
  type ExperimentSmokeResultDraft,
  type ExperimentSmokeResultRegisterPayload,
  type ResearchLoopCreateDraft,
  type ResearchLoopCreatePayload,
  type ResearchLoopDecisionDraft,
  type ResearchLoopDecisionPayload,
  type ResearchLoopEvidenceDraft,
  type ResearchLoopEvidencePayload,
  type ResearchLoopRecord,
} from "./experimentLoopModel";
import { splitDraftList } from "./source-collection/presentationModel";
import { researchStageRoundStatusQueryKey } from "./useResearchWorkflowResources";

export type UseTeamExperimentLoopMutationsOptions = {
  sourceCollectionOwnerAgentId: string;
  sourceCollectionIngestorAgentId: string;
  sourceCollectionDraftGoal: string;
  latestExperimentStageRoundId: string;
  setExperimentSmokeResultDraft: Dispatch<SetStateAction<ExperimentSmokeResultDraft>>;
  setExperimentFullRunResultDraft: Dispatch<SetStateAction<ExperimentFullRunResultDraft>>;
  setExperimentKnowledgeIngestionDraft: Dispatch<SetStateAction<ExperimentKnowledgeIngestionDraft>>;
  setResearchLoopEvidenceDraft: Dispatch<SetStateAction<ResearchLoopEvidenceDraft>>;
  setResearchLoopDecisionDraft: Dispatch<SetStateAction<ResearchLoopDecisionDraft>>;
};

export function buildResearchLoopDecisionIdempotencyKey(payload: {
  loopId: string;
  loopUpdatedAt: string;
  nextTemplateId: string;
  draft: Pick<
    ResearchLoopDecisionDraft,
    "decision" | "rationale" | "nextActions" | "allowedVariableChanges" | "frozenControls"
  >;
}): string {
  const fingerprint = JSON.stringify([
    payload.loopUpdatedAt,
    payload.nextTemplateId,
    payload.draft.decision,
    payload.draft.rationale.trim(),
    payload.draft.nextActions.trim(),
    payload.draft.allowedVariableChanges.trim(),
    payload.draft.frozenControls.trim(),
  ]);
  let hash = 2166136261;
  for (let index = 0; index < fingerprint.length; index += 1) {
    hash ^= fingerprint.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `${payload.loopId}:${payload.draft.decision}:${(hash >>> 0).toString(16).padStart(8, "0")}`.slice(0, 240);
}

// Shared failure plumbing for the experiment-loop telemetry: each mutation starts a
// tracker in its inline onMutate context; onSuccess closes it with succeeded() and
// this handler closes it as failed. Inlined per mutation (not a spread helper) so
// React Query keeps inferring the mutation variables type.
function experimentTelemetryOnError(
  reason: unknown,
  _vars: unknown,
  ctx: { telemetry?: UserActionTracker } | undefined,
): void {
  ctx?.telemetry?.failed(reason);
}

export function useTeamExperimentLoopMutations(options: UseTeamExperimentLoopMutationsOptions) {
  const queryClient = useQueryClient();

  const createExperimentPlanMutation = useMutation({
    onMutate: (vars) => ({
      telemetry: trackExperimentPlanCreate({
        teamId: vars.teamId,
        stageRoundId: vars.stageRoundId ?? "",
        titleLength: (vars.title ?? "").trim().length,
        hasMethodRequest: Boolean(vars.methodRequest),
      }),
    }),
    onError: experimentTelemetryOnError,
    mutationFn: (payload: { teamId: string; stageRoundId?: string; title?: string; methodRequest?: ExperimentPlanMethodRequest }) =>
      createTeamExperimentPlan<ExperimentPlanCreatePayload>(payload.teamId, {
        stageRoundId: payload.stageRoundId || "",
        title: payload.title || "",
        createdByAgent: options.sourceCollectionOwnerAgentId,
        ...(payload.methodRequest ?? {}),
        notes: "Created from the experiment planning workspace. No training execution was triggered.",
      }),
    onSuccess: (payload, variables, ctx) => {
      ctx?.telemetry?.succeeded();
      queryClient.setQueryData(experimentPlanningStatusQueryKey(variables.teamId), payload.status);
      queryClient.setQueryData(researchStageRoundStatusQueryKey(variables.teamId), payload.stageRoundStatus);
      queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      void queryClient.invalidateQueries({ queryKey: experimentPlanningStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: researchStageRoundStatusQueryKey(variables.teamId) });
    },
  });

  const materializeEngineeringProxyHypothesisMutation = useMutation({
    onMutate: (vars) => ({
      telemetry: trackEngineeringProxyMaterialize({
        teamId: vars.teamId,
        planId: vars.plan.planId,
      }),
    }),
    onError: experimentTelemetryOnError,
    mutationFn: (payload: {
      teamId: string;
      plan: ExperimentPlanRecord;
      draft: EngineeringProxyHypothesisDraft;
    }) =>
      materializeTeamEngineeringProxyHypothesis(
        payload.teamId,
        payload.plan.planId,
        {
          ...payload.draft,
          createdByAgent: options.sourceCollectionOwnerAgentId,
          idempotencyKey: `${payload.plan.planId}:engineering-proxy`,
        },
      ),
    onSuccess: (payload, variables, ctx) => {
      ctx?.telemetry?.succeeded();
      if (payload.experimentStatus) {
        queryClient.setQueryData(
          experimentPlanningStatusQueryKey(variables.teamId),
          payload.experimentStatus,
        );
      }
      if (payload.workflow) {
        queryClient.setQueryData(
          queryKeys.teamWorkflow(variables.teamId),
          payload.workflow,
        );
      }
      void queryClient.invalidateQueries({
        queryKey: experimentPlanningStatusQueryKey(variables.teamId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.teamWorkflow(variables.teamId),
      });
    },
  });

  const reviewExperimentHypothesisMutation = useMutation({
    onMutate: (vars) => ({
      telemetry: trackExperimentHypothesisReview({
        teamId: vars.teamId,
        candidateId: vars.candidateId,
        decision: "approve",
      }),
    }),
    onError: experimentTelemetryOnError,
    mutationFn: (payload: { teamId: string; candidateId: string }) =>
      reviewTeamExperimentHypothesis(
        payload.teamId,
        payload.candidateId,
        {
          reviewedByAgent: "Human Operator",
          decision: "approve",
          comments: (
            "The operator explicitly approved this bounded hypothesis for "
            + "experiment-design use. Scientific promotion remains prohibited."
          ),
          requiredChanges: [],
        },
      ),
    onSuccess: (payload, variables, ctx) => {
      ctx?.telemetry?.succeeded();
      if (payload.experimentStatus) {
        queryClient.setQueryData(
          experimentPlanningStatusQueryKey(variables.teamId),
          payload.experimentStatus,
        );
      }
      if (payload.workflow) {
        queryClient.setQueryData(
          queryKeys.teamWorkflow(variables.teamId),
          payload.workflow,
        );
      }
      void queryClient.invalidateQueries({
        queryKey: experimentPlanningStatusQueryKey(variables.teamId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.teamWorkflow(variables.teamId),
      });
    },
  });

  const completeScientificHypothesisFromDesignMutation = useMutation({
    onMutate: (vars) => ({
      telemetry: trackScientificHypothesisComplete({
        teamId: vars.teamId,
        planId: vars.plan.planId,
        candidateId: vars.candidateId,
      }),
    }),
    onError: experimentTelemetryOnError,
    mutationFn: (payload: {
      teamId: string;
      plan: ExperimentPlanRecord;
      candidateId: string;
      methodRequest: ExperimentPlanMethodRequest;
    }) =>
      completeTeamScientificHypothesisFromDesign(
        payload.teamId,
        payload.plan.planId,
        payload.candidateId,
        {
          ...payload.methodRequest,
          createdByAgent: options.sourceCollectionOwnerAgentId,
        },
      ),
    onSuccess: (payload, variables, ctx) => {
      ctx?.telemetry?.succeeded();
      if (payload.experimentStatus) {
        queryClient.setQueryData(
          experimentPlanningStatusQueryKey(variables.teamId),
          payload.experimentStatus,
        );
      }
      if (payload.workflow) {
        queryClient.setQueryData(
          queryKeys.teamWorkflow(variables.teamId),
          payload.workflow,
        );
      }
      void queryClient.invalidateQueries({
        queryKey: experimentPlanningStatusQueryKey(variables.teamId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.teamWorkflow(variables.teamId),
      });
    },
  });

  const createExperimentHypothesisRevisionMutation = useMutation({
    onMutate: (vars) => ({
      telemetry: trackExperimentHypothesisRevisionCreate({
        teamId: vars.teamId,
        planId: vars.plan.planId,
        candidateId: vars.candidateId,
      }),
    }),
    onError: experimentTelemetryOnError,
    mutationFn: (payload: {
      teamId: string;
      plan: ExperimentPlanRecord;
      candidateId: string;
    }) =>
      createTeamExperimentHypothesisRevision(
        payload.teamId,
        payload.plan.planId,
        payload.candidateId,
        {
          createdByAgent: options.sourceCollectionOwnerAgentId,
          idempotencyKey: (
            `${payload.plan.planId}:${payload.candidateId}:hypothesis-revision`
          ),
        },
      ),
    onSuccess: (payload, variables, ctx) => {
      ctx?.telemetry?.succeeded();
      if (payload.experimentStatus) {
        queryClient.setQueryData(
          experimentPlanningStatusQueryKey(variables.teamId),
          payload.experimentStatus,
        );
      }
      if (payload.stageRoundStatus) {
        queryClient.setQueryData(
          researchStageRoundStatusQueryKey(variables.teamId),
          payload.stageRoundStatus,
        );
      }
      if (payload.workflow) {
        queryClient.setQueryData(
          queryKeys.teamWorkflow(variables.teamId),
          payload.workflow,
        );
      }
      void queryClient.invalidateQueries({
        queryKey: experimentPlanningStatusQueryKey(variables.teamId),
      });
      void queryClient.invalidateQueries({
        queryKey: researchStageRoundStatusQueryKey(variables.teamId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.teamWorkflow(variables.teamId),
      });
    },
  });

  const freezeExperimentDesignMutation = useMutation({
    onMutate: (vars) => ({
      telemetry: trackExperimentDesignFreeze({
        teamId: vars.teamId,
        planId: vars.plan.planId,
      }),
    }),
    onError: experimentTelemetryOnError,
    mutationFn: (payload: { teamId: string; plan: ExperimentPlanRecord }) =>
      freezeTeamExperimentDesign<ExperimentDesignFreezePayload>(payload.teamId, payload.plan.planId, {
        frozenByAgent: options.sourceCollectionOwnerAgentId,
      }),
    onSuccess: (payload, variables, ctx) => {
      ctx?.telemetry?.succeeded();
      if (payload.experimentStatus) {
        queryClient.setQueryData(experimentPlanningStatusQueryKey(variables.teamId), payload.experimentStatus);
      }
      void queryClient.invalidateQueries({ queryKey: experimentPlanningStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: researchStageRoundStatusQueryKey(variables.teamId) });
    },
  });

  const resumeExperimentHypothesisMutation = useMutation({
    onMutate: (vars) => ({
      telemetry: trackExperimentHypothesisResume({
        teamId: vars.teamId,
        hypothesisCandidateId: vars.hypothesisCandidateId,
      }),
    }),
    onError: experimentTelemetryOnError,
    mutationFn: (payload: { teamId: string; hypothesisCandidateId: string }) =>
      resumeTeamExperimentHypothesis<ExperimentHypothesisResumePayload>(payload.teamId, {
        hypothesisCandidateId: payload.hypothesisCandidateId,
      }),
    onSuccess: (payload, variables, ctx) => {
      ctx?.telemetry?.succeeded();
      if (payload.experimentStatus) {
        queryClient.setQueryData(experimentPlanningStatusQueryKey(variables.teamId), payload.experimentStatus);
      }
      void queryClient.invalidateQueries({ queryKey: experimentPlanningStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: researchStageRoundStatusQueryKey(variables.teamId) });
    },
  });

  const registerExperimentBaselineArtifactMutation = useMutation({
    onMutate: (vars) => ({
      telemetry: trackExperimentBaselineRegister({
        teamId: vars.teamId,
        planId: vars.plan.planId,
        baselineName: vars.plan.experimentPlan.baseline || vars.plan.baselineSelection.baseline || "",
        metricName: vars.plan.experimentPlan.metric || "",
        hasArtifactPath: vars.draft.artifactPath.trim().length > 0,
      }),
    }),
    onError: experimentTelemetryOnError,
    mutationFn: (payload: {
      teamId: string;
      plan: ExperimentPlanRecord;
      draft: ExperimentBaselineArtifactDraft;
    }) =>
      registerTeamExperimentBaselineArtifact<ExperimentBaselineArtifactRegisterPayload>(
        payload.teamId,
        payload.plan.planId,
        {
          registeredByAgent: options.sourceCollectionOwnerAgentId,
          baselineName: payload.plan.experimentPlan.baseline || payload.plan.baselineSelection.baseline || "",
          datasetRef: payload.plan.experimentPlan.dataset || "",
          metricName: payload.plan.experimentPlan.metric || "",
          metricValue: payload.draft.metricValue.trim(),
          artifactPath: payload.draft.artifactPath.trim(),
          reproductionCommand: payload.draft.reproductionCommand.trim(),
          evaluationCommand: payload.draft.evaluationCommand.trim(),
          notes: "Registered from the experiment planning workspace. No training execution was triggered.",
        },
      ),
    onSuccess: (payload, variables, ctx) => {
      ctx?.telemetry?.succeeded();
      queryClient.setQueryData(experimentPlanningStatusQueryKey(variables.teamId), payload.status);
      queryClient.setQueryData(researchStageRoundStatusQueryKey(variables.teamId), payload.stageRoundStatus);
      queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      void queryClient.invalidateQueries({ queryKey: experimentPlanningStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: researchStageRoundStatusQueryKey(variables.teamId) });
    },
  });

  const runExperimentSmokeMutation = useMutation({
    onMutate: (vars) => ({
      telemetry: trackExperimentSmokeRun({
        teamId: vars.teamId,
        planId: vars.plan.planId,
        adapter: vars.adapter,
        seed: vars.seed,
      }),
    }),
    onError: experimentTelemetryOnError,
    mutationFn: (payload: {
      teamId: string;
      plan: ExperimentPlanRecord;
      adapter: string;
      seed: number;
    }) =>
      runTeamExperimentSmoke(payload.teamId, payload.plan.planId, {
        adapter: payload.adapter,
        seed: payload.seed,
        recordedByAgent: options.sourceCollectionOwnerAgentId,
      }),
    onSuccess: (_payload, variables, ctx) => {
      ctx?.telemetry?.succeeded();
      void queryClient.invalidateQueries({ queryKey: experimentPlanningStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: researchStageRoundStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflow(variables.teamId) });
    },
  });

  const registerExperimentSmokeResultMutation = useMutation({
    onMutate: (vars) => ({
      telemetry: trackExperimentSmokeResultRegister({
        teamId: vars.teamId,
        planId: vars.plan.planId,
        status: vars.draft.status,
        metricName: vars.plan.experimentPlan.metric || "",
      }),
    }),
    onError: experimentTelemetryOnError,
    mutationFn: (payload: {
      teamId: string;
      plan: ExperimentPlanRecord;
      draft: ExperimentSmokeResultDraft;
    }) =>
      registerTeamExperimentSmokeResult<ExperimentSmokeResultRegisterPayload>(
        payload.teamId,
        payload.plan.planId,
        {
          recordedByAgent: options.sourceCollectionOwnerAgentId,
          status: payload.draft.status,
          metricName: payload.plan.experimentPlan.metric || "",
          metricValue: payload.draft.metricValue.trim(),
          baselineMetricValue: payload.draft.baselineMetricValue.trim(),
          delta: payload.draft.delta.trim(),
          resultPath: payload.draft.resultPath.trim(),
          logRef: payload.draft.logRef.trim(),
          evaluationCommand: payload.draft.evaluationCommand.trim(),
          notes: payload.draft.notes.trim() || "Registered from the experiment planning workspace. No training execution was triggered.",
          metadata: {
            enteredFrom: "teams_experiment_ledger",
            noTrainingExecution: true,
          },
        },
      ),
    onSuccess: (payload, variables, ctx) => {
      ctx?.telemetry?.succeeded();
      queryClient.setQueryData(experimentPlanningStatusQueryKey(variables.teamId), payload.status);
      queryClient.setQueryData(researchStageRoundStatusQueryKey(variables.teamId), payload.stageRoundStatus);
      queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      options.setExperimentSmokeResultDraft((draft) => ({
        ...draft,
        metricValue: "",
        delta: "",
        resultPath: "",
        logRef: "",
        notes: "",
      }));
      void queryClient.invalidateQueries({ queryKey: experimentPlanningStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: researchStageRoundStatusQueryKey(variables.teamId) });
    },
  });

  const registerExperimentFullRunResultMutation = useMutation({
    onMutate: (vars) => ({
      telemetry: trackExperimentFullRunResultRegister({
        teamId: vars.teamId,
        planId: vars.plan.planId,
        status: vars.draft.status,
        metricName: vars.plan.experimentPlan.metric || "",
      }),
    }),
    onError: experimentTelemetryOnError,
    mutationFn: (payload: {
      teamId: string;
      plan: ExperimentPlanRecord;
      draft: ExperimentFullRunResultDraft;
    }) =>
      registerTeamExperimentFullRunResult<ExperimentFullRunResultRegisterPayload>(
        payload.teamId,
        payload.plan.planId,
        {
          evidenceKind: "external_manual",
          recordedByAgent: options.sourceCollectionOwnerAgentId,
          status: payload.draft.status,
          metricName: payload.plan.experimentPlan.metric || "",
          metricValue: payload.draft.metricValue.trim(),
          baselineMetricValue: payload.draft.baselineMetricValue.trim(),
          smokeMetricValue: payload.draft.smokeMetricValue.trim(),
          delta: payload.draft.delta.trim(),
          resultPath: payload.draft.resultPath.trim(),
          logRef: payload.draft.logRef.trim(),
          configPath: payload.draft.configPath.trim(),
          reproductionCommand: payload.draft.reproductionCommand.trim(),
          evaluationCommand: payload.draft.evaluationCommand.trim(),
          notes: payload.draft.notes.trim() || "Registered from the experiment planning workspace. No full-run execution was triggered.",
          metadata: {
            enteredFrom: "teams_experiment_ledger",
            manualFullRunResult: true,
            noTrainingExecution: true,
          },
        },
      ),
    onSuccess: (payload, variables, ctx) => {
      ctx?.telemetry?.succeeded();
      queryClient.setQueryData(experimentPlanningStatusQueryKey(variables.teamId), payload.status);
      queryClient.setQueryData(researchStageRoundStatusQueryKey(variables.teamId), payload.stageRoundStatus);
      queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      options.setExperimentFullRunResultDraft((draft) => ({
        ...draft,
        metricValue: "",
        delta: "",
        resultPath: "",
        logRef: "",
        configPath: "",
        notes: "",
      }));
      options.setExperimentKnowledgeIngestionDraft((draft) => ({
        ...draft,
        title: payload.plan.title || draft.title,
        summary:
          payload.fullRunResult.status === "passed"
            ? `${payload.fullRunResult.metricName || payload.plan.experimentPlan.metric || "metric"} = ${payload.fullRunResult.metricValue}`
            : draft.summary,
      }));
      void queryClient.invalidateQueries({ queryKey: experimentPlanningStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: researchStageRoundStatusQueryKey(variables.teamId) });
    },
  });

  const requestExperimentKnowledgeIngestionMutation = useMutation({
    onMutate: (vars) => ({
      telemetry: trackExperimentKnowledgeIngestionRequest({
        teamId: vars.teamId,
        planId: vars.plan.planId,
        wakeStewardAgent: vars.draft.wakeStewardAgent,
        knowledgeBaseId: vars.draft.knowledgeBaseId.trim() || `${vars.teamId}-challenge-cup-experiments`,
      }),
    }),
    onError: experimentTelemetryOnError,
    mutationFn: (payload: {
      teamId: string;
      plan: ExperimentPlanRecord;
      draft: ExperimentKnowledgeIngestionDraft;
    }) =>
      requestTeamExperimentKnowledgeIngestion<ExperimentResultKnowledgeIngestionPayload>(
        payload.teamId,
        payload.plan.planId,
        {
          requestedByAgent: options.sourceCollectionOwnerAgentId,
          stewardAgentId: options.sourceCollectionIngestorAgentId,
          knowledgeBaseId: payload.draft.knowledgeBaseId.trim() || `${payload.teamId}-challenge-cup-experiments`,
          targetDomain: payload.draft.targetDomain.trim() || "挑战杯实验结果",
          wakeStewardAgent: payload.draft.wakeStewardAgent,
          title: payload.draft.title.trim() || payload.plan.title || "",
          summary: payload.draft.summary.trim(),
          notes: payload.draft.notes.trim(),
          metadata: {
            enteredFrom: "teams_experiment_ledger",
            explicitUserBoundary: true,
            stewardReviewRequired: true,
            rawLogsStayReferenced: true,
          },
        },
      ),
    onSuccess: (payload, variables, ctx) => {
      ctx?.telemetry?.succeeded();
      queryClient.setQueryData(experimentPlanningStatusQueryKey(variables.teamId), payload.status);
      queryClient.setQueryData(researchStageRoundStatusQueryKey(variables.teamId), payload.stageRoundStatus);
      queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      void queryClient.invalidateQueries({ queryKey: experimentPlanningStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: researchStageRoundStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId) });
    },
  });

  const createResearchLoopMutation = useMutation({
    onMutate: (vars) => ({
      telemetry: trackResearchLoopCreate({
        teamId: vars.teamId,
        templateId: vars.templateId,
        planId: vars.plan?.planId ?? "",
        hypothesisCount: vars.plan?.hypothesisCandidateIds?.length
          ?? vars.plan?.selectedHypotheses.length
          ?? 0,
        datasetRefCount: splitDraftList(vars.draft.datasetRefs, 24).length,
      }),
    }),
    onError: experimentTelemetryOnError,
    mutationFn: (payload: {
      teamId: string;
      plan: ExperimentPlanRecord | null;
      templateId: string;
      draft: ResearchLoopCreateDraft;
    }) => {
      const selectedHypothesisIds = payload.plan?.hypothesisCandidateIds?.length
        ? payload.plan.hypothesisCandidateIds
        : payload.plan?.selectedHypotheses.map((candidate) => candidate.candidateId) ?? [];
      return createResearchLoop<ResearchLoopCreatePayload>(payload.teamId, {
        templateId: payload.templateId,
        title: payload.plan?.title || "",
        researchQuestion:
          payload.draft.researchQuestion.trim()
          || payload.plan?.goal
          || payload.plan?.topic
          || options.sourceCollectionDraftGoal,
        stageRoundId: payload.plan?.stageRoundId || options.latestExperimentStageRoundId,
        planId: payload.plan?.planId || "",
        targetRef: payload.plan?.planId || payload.plan?.stageRoundId || "",
        candidateIds: selectedHypothesisIds,
        datasetRefs: splitDraftList(payload.draft.datasetRefs, 24),
        environmentRefs: splitDraftList(payload.draft.environmentRefs, 24),
        constraints: payload.draft.constraints.trim(),
        createdByAgent: options.sourceCollectionOwnerAgentId,
        metadata: {
          enteredFrom: "teams_research_loop_panel",
          noSandboxRunner: true,
          noTrainingExecution: true,
        },
      });
    },
    onSuccess: (payload, variables, ctx) => {
      ctx?.telemetry?.succeeded({ loopId: payload.loop.loopId });
      queryClient.setQueryData(researchLoopStatusQueryKey(variables.teamId), payload.status);
      options.setResearchLoopEvidenceDraft((draft) => ({
        ...draft,
        evidenceType: payload.loop.readiness.missingEvidenceTypes[0] || payload.loop.readiness.requiredEvidenceTypes[0] || draft.evidenceType,
        metricName: variables.plan?.experimentPlan.metric || draft.metricName,
      }));
      void queryClient.invalidateQueries({ queryKey: researchLoopStatusQueryKey(variables.teamId) });
    },
  });

  const recordResearchLoopEvidenceMutation = useMutation({
    onMutate: (vars) => ({
      telemetry: trackResearchLoopEvidenceRecord({
        teamId: vars.teamId,
        loopId: vars.loop.loopId,
        evidenceType: vars.evidenceType,
        status: vars.draft.status,
      }),
    }),
    onError: experimentTelemetryOnError,
    mutationFn: (payload: { teamId: string; loop: ResearchLoopRecord; draft: ResearchLoopEvidenceDraft; evidenceType: string }) =>
      recordResearchLoopEvidence<ResearchLoopEvidencePayload>(
        payload.teamId,
        payload.loop.loopId,
        {
          evidenceType: payload.evidenceType,
          status: payload.draft.status,
          summary: payload.draft.summary.trim(),
          metricName: payload.draft.metricName.trim(),
          metricValue: payload.draft.metricValue.trim(),
          baselineMetricValue: payload.draft.baselineMetricValue.trim(),
          delta: payload.draft.delta.trim(),
          artifactRefs: payload.draft.artifactRef.trim() ? [{ path: payload.draft.artifactRef.trim() }] : [],
          datasetRefs: splitDraftList(payload.draft.datasetRefs, 24),
          environmentRefs: splitDraftList(payload.draft.environmentRefs, 24),
          logRefs: splitDraftList(payload.draft.logRefs, 24),
          commandPreview: payload.draft.commandPreview.trim(),
          recordedByAgent: options.sourceCollectionOwnerAgentId,
          metadata: {
            enteredFrom: "teams_research_loop_panel",
            commandPreviewOnly: true,
          },
        },
      ),
    onSuccess: (payload, variables, ctx) => {
      ctx?.telemetry?.succeeded();
      queryClient.setQueryData(researchLoopStatusQueryKey(variables.teamId), payload.status);
      const nextMissing = payload.loop.readiness.missingEvidenceTypes.find((item) => item !== variables.evidenceType) || "";
      options.setResearchLoopEvidenceDraft((draft) => ({
        ...draft,
        evidenceType: nextMissing || draft.evidenceType,
        summary: "",
        metricValue: "",
        delta: "",
        artifactRef: "",
        logRefs: "",
        commandPreview: "",
      }));
      void queryClient.invalidateQueries({ queryKey: researchLoopStatusQueryKey(variables.teamId) });
    },
  });

  const recordResearchLoopDecisionMutation = useMutation({
    onMutate: (vars) => ({
      telemetry: trackResearchLoopDecisionRecord({
        teamId: vars.teamId,
        loopId: vars.loop.loopId,
        decision: vars.draft.decision,
        nextTemplateId: vars.nextTemplateId,
        rationaleLength: vars.draft.rationale.trim().length,
      }),
    }),
    onError: experimentTelemetryOnError,
    mutationFn: (payload: { teamId: string; loop: ResearchLoopRecord; draft: ResearchLoopDecisionDraft; nextTemplateId: string }) =>
      recordResearchLoopDecision<ResearchLoopDecisionPayload>(
        payload.teamId,
        payload.loop.loopId,
        {
          decision: payload.draft.decision,
          rationale: payload.draft.rationale.trim(),
          nextTemplateId: payload.nextTemplateId,
          nextActions: splitDraftList(payload.draft.nextActions, 24),
          allowedVariableChanges: splitDraftList(payload.draft.allowedVariableChanges, 24),
          frozenControls: splitDraftList(payload.draft.frozenControls, 24),
          decidedByAgent: options.sourceCollectionOwnerAgentId,
          createNextDesignDraft:
            payload.draft.decision === "promote_to_iteration"
            || payload.draft.decision === "repair_and_repeat",
          idempotencyKey: buildResearchLoopDecisionIdempotencyKey({
            loopId: payload.loop.loopId,
            loopUpdatedAt: payload.loop.updatedAt,
            nextTemplateId: payload.nextTemplateId,
            draft: payload.draft,
          }),
          metadata: {
            enteredFrom: "teams_research_loop_panel",
            noAutomaticIterationExecution: true,
          },
        },
      ),
    onSuccess: (payload, variables, ctx) => {
      ctx?.telemetry?.succeeded();
      queryClient.setQueryData(researchLoopStatusQueryKey(variables.teamId), payload.status);
      options.setResearchLoopDecisionDraft((draft) => ({
        ...draft,
        rationale: "",
        nextActions: "",
        allowedVariableChanges: "",
        frozenControls: "",
      }));
      void queryClient.invalidateQueries({ queryKey: researchLoopStatusQueryKey(variables.teamId) });
      if (payload.nextDesignDraft) {
        void queryClient.invalidateQueries({ queryKey: experimentPlanningStatusQueryKey(variables.teamId) });
      }
    },
  });

  const materializeResearchLoopIterationDesignMutation = useMutation({
    onMutate: (vars) => ({
      telemetry: trackResearchLoopIterationMaterialize({
        teamId: vars.teamId,
        loopId: vars.loopId,
        proposalId: vars.proposalId,
      }),
    }),
    onError: experimentTelemetryOnError,
    mutationFn: (payload: { teamId: string; loopId: string; proposalId: string }) =>
      materializeResearchLoopIterationDesign<ResearchLoopDecisionPayload>(
        payload.teamId,
        payload.loopId,
        payload.proposalId,
        { createdByAgent: options.sourceCollectionOwnerAgentId },
      ),
    onSuccess: (payload, variables, ctx) => {
      ctx?.telemetry?.succeeded();
      queryClient.setQueryData(researchLoopStatusQueryKey(variables.teamId), payload.status);
      void queryClient.invalidateQueries({ queryKey: researchLoopStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: experimentPlanningStatusQueryKey(variables.teamId) });
    },
  });


  return {
    createExperimentPlanMutation,
    materializeEngineeringProxyHypothesisMutation,
    completeScientificHypothesisFromDesignMutation,
    reviewExperimentHypothesisMutation,
    createExperimentHypothesisRevisionMutation,
    freezeExperimentDesignMutation,
    resumeExperimentHypothesisMutation,
    registerExperimentBaselineArtifactMutation,
    runExperimentSmokeMutation,
    registerExperimentSmokeResultMutation,
    registerExperimentFullRunResultMutation,
    requestExperimentKnowledgeIngestionMutation,
    createResearchLoopMutation,
    recordResearchLoopEvidenceMutation,
    recordResearchLoopDecisionMutation,
    materializeResearchLoopIterationDesignMutation,
  };
}
