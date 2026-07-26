/**
 * Experiment planning + research-loop write mutations for Teams.
 * EventSource-free; Route remains the draft/view orchestration boundary.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Dispatch, SetStateAction } from "react";

import { fetchJson } from "../../api/client";
import { queryKeys } from "../../api/queryKeys";
import type { ExperimentPlanMethodRequest } from "../TeamExperimentMethodPanel";
import {
  experimentPlanningStatusQueryKey,
  researchLoopStatusQueryKey,
  type ExperimentBaselineArtifactDraft,
  type ExperimentBaselineArtifactRegisterPayload,
  type ExperimentDesignFreezePayload,
  type ExperimentFullRunResultDraft,
  type ExperimentFullRunResultRegisterPayload,
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

export function useTeamExperimentLoopMutations(options: UseTeamExperimentLoopMutationsOptions) {
  const queryClient = useQueryClient();

  const createExperimentPlanMutation = useMutation({
    mutationFn: (payload: { teamId: string; stageRoundId?: string; title?: string; methodRequest?: ExperimentPlanMethodRequest }) =>
      fetchJson<ExperimentPlanCreatePayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/experiments/plan`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            stageRoundId: payload.stageRoundId || "",
            title: payload.title || "",
            createdByAgent: options.sourceCollectionOwnerAgentId,
            ...(payload.methodRequest ?? {}),
            notes: "Created from the experiment planning workspace. No training execution was triggered.",
          }),
        },
      ),
    onSuccess: (payload, variables) => {
      queryClient.setQueryData(experimentPlanningStatusQueryKey(variables.teamId), payload.status);
      queryClient.setQueryData(researchStageRoundStatusQueryKey(variables.teamId), payload.stageRoundStatus);
      queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      void queryClient.invalidateQueries({ queryKey: experimentPlanningStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: researchStageRoundStatusQueryKey(variables.teamId) });
    },
  });

  const freezeExperimentDesignMutation = useMutation({
    mutationFn: (payload: { teamId: string; plan: ExperimentPlanRecord }) =>
      fetchJson<ExperimentDesignFreezePayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/experiments/plans/${encodeURIComponent(payload.plan.planId)}/freeze`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ frozenByAgent: options.sourceCollectionOwnerAgentId }),
        },
      ),
    onSuccess: (payload, variables) => {
      if (payload.experimentStatus) {
        queryClient.setQueryData(experimentPlanningStatusQueryKey(variables.teamId), payload.experimentStatus);
      }
      void queryClient.invalidateQueries({ queryKey: experimentPlanningStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: researchStageRoundStatusQueryKey(variables.teamId) });
    },
  });

  const registerExperimentBaselineArtifactMutation = useMutation({
    mutationFn: (payload: {
      teamId: string;
      plan: ExperimentPlanRecord;
      draft: ExperimentBaselineArtifactDraft;
    }) =>
      fetchJson<ExperimentBaselineArtifactRegisterPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/experiments/plans/${encodeURIComponent(payload.plan.planId)}/baseline-artifact`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            registeredByAgent: options.sourceCollectionOwnerAgentId,
            baselineName: payload.plan.experimentPlan.baseline || payload.plan.baselineSelection.baseline || "",
            datasetRef: payload.plan.experimentPlan.dataset || "",
            metricName: payload.plan.experimentPlan.metric || "",
            metricValue: payload.draft.metricValue.trim(),
            artifactPath: payload.draft.artifactPath.trim(),
            reproductionCommand: payload.draft.reproductionCommand.trim(),
            evaluationCommand: payload.draft.evaluationCommand.trim(),
            notes: "Registered from the experiment planning workspace. No training execution was triggered.",
          }),
        },
      ),
    onSuccess: (payload, variables) => {
      queryClient.setQueryData(experimentPlanningStatusQueryKey(variables.teamId), payload.status);
      queryClient.setQueryData(researchStageRoundStatusQueryKey(variables.teamId), payload.stageRoundStatus);
      queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      void queryClient.invalidateQueries({ queryKey: experimentPlanningStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: researchStageRoundStatusQueryKey(variables.teamId) });
    },
  });

  const registerExperimentSmokeResultMutation = useMutation({
    mutationFn: (payload: {
      teamId: string;
      plan: ExperimentPlanRecord;
      draft: ExperimentSmokeResultDraft;
    }) =>
      fetchJson<ExperimentSmokeResultRegisterPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/experiments/plans/${encodeURIComponent(payload.plan.planId)}/smoke-result`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
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
          }),
        },
      ),
    onSuccess: (payload, variables) => {
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
    mutationFn: (payload: {
      teamId: string;
      plan: ExperimentPlanRecord;
      draft: ExperimentFullRunResultDraft;
    }) =>
      fetchJson<ExperimentFullRunResultRegisterPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/experiments/plans/${encodeURIComponent(payload.plan.planId)}/full-run-result`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
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
          }),
        },
      ),
    onSuccess: (payload, variables) => {
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
    mutationFn: (payload: {
      teamId: string;
      plan: ExperimentPlanRecord;
      draft: ExperimentKnowledgeIngestionDraft;
    }) =>
      fetchJson<ExperimentResultKnowledgeIngestionPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/experiments/plans/${encodeURIComponent(payload.plan.planId)}/knowledge-ingestion-request`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
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
          }),
        },
      ),
    onSuccess: (payload, variables) => {
      queryClient.setQueryData(experimentPlanningStatusQueryKey(variables.teamId), payload.status);
      queryClient.setQueryData(researchStageRoundStatusQueryKey(variables.teamId), payload.stageRoundStatus);
      queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      void queryClient.invalidateQueries({ queryKey: experimentPlanningStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: researchStageRoundStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId) });
    },
  });

  const createResearchLoopMutation = useMutation({
    mutationFn: (payload: {
      teamId: string;
      plan: ExperimentPlanRecord | null;
      templateId: string;
      draft: ResearchLoopCreateDraft;
    }) => {
      const selectedHypothesisIds = payload.plan?.hypothesisCandidateIds?.length
        ? payload.plan.hypothesisCandidateIds
        : payload.plan?.selectedHypotheses.map((candidate) => candidate.candidateId) ?? [];
      return fetchJson<ResearchLoopCreatePayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/research-loop/loops`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
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
          }),
        },
      );
    },
    onSuccess: (payload, variables) => {
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
    mutationFn: (payload: { teamId: string; loop: ResearchLoopRecord; draft: ResearchLoopEvidenceDraft; evidenceType: string }) =>
      fetchJson<ResearchLoopEvidencePayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/research-loop/loops/${encodeURIComponent(payload.loop.loopId)}/evidence`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
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
          }),
        },
      ),
    onSuccess: (payload, variables) => {
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
    mutationFn: (payload: { teamId: string; loop: ResearchLoopRecord; draft: ResearchLoopDecisionDraft; nextTemplateId: string }) =>
      fetchJson<ResearchLoopDecisionPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/research-loop/loops/${encodeURIComponent(payload.loop.loopId)}/decision`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            decision: payload.draft.decision,
            rationale: payload.draft.rationale.trim(),
            nextTemplateId: payload.nextTemplateId,
            nextActions: splitDraftList(payload.draft.nextActions, 24),
            decidedByAgent: options.sourceCollectionOwnerAgentId,
            createNextDesignDraft:
              payload.draft.decision === "promote_to_iteration"
              || payload.draft.decision === "repair_and_repeat",
            idempotencyKey: `${payload.loop.loopId}:${payload.loop.updatedAt}:${payload.draft.decision}`,
            metadata: {
              enteredFrom: "teams_research_loop_panel",
              noAutomaticIterationExecution: true,
            },
          }),
        },
      ),
    onSuccess: (payload, variables) => {
      queryClient.setQueryData(researchLoopStatusQueryKey(variables.teamId), payload.status);
      options.setResearchLoopDecisionDraft((draft) => ({
        ...draft,
        rationale: "",
        nextActions: "",
      }));
      void queryClient.invalidateQueries({ queryKey: researchLoopStatusQueryKey(variables.teamId) });
      if (payload.nextDesignDraft) {
        void queryClient.invalidateQueries({ queryKey: experimentPlanningStatusQueryKey(variables.teamId) });
      }
    },
  });

  const materializeResearchLoopIterationDesignMutation = useMutation({
    mutationFn: (payload: { teamId: string; loopId: string; proposalId: string }) =>
      fetchJson<ResearchLoopDecisionPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/research-loop/loops/${encodeURIComponent(payload.loopId)}/proposals/${encodeURIComponent(payload.proposalId)}/design-draft`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ createdByAgent: options.sourceCollectionOwnerAgentId }),
        },
      ),
    onSuccess: (payload, variables) => {
      queryClient.setQueryData(researchLoopStatusQueryKey(variables.teamId), payload.status);
      void queryClient.invalidateQueries({ queryKey: researchLoopStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: experimentPlanningStatusQueryKey(variables.teamId) });
    },
  });


  return {
    createExperimentPlanMutation,
    freezeExperimentDesignMutation,
    registerExperimentBaselineArtifactMutation,
    registerExperimentSmokeResultMutation,
    registerExperimentFullRunResultMutation,
    requestExperimentKnowledgeIngestionMutation,
    createResearchLoopMutation,
    recordResearchLoopEvidenceMutation,
    recordResearchLoopDecisionMutation,
    materializeResearchLoopIterationDesignMutation,
  };
}
