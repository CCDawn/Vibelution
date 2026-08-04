/**
 * Research experiment + research-loop workspace state machine for Teams.
 * Phase 2: owns experiment/loop drafts, preferred method, and secondary status queries.
 *
 * Mutations and workspace action adapters stay in TeamsRoute and receive setters from here.
 */
import { useState } from "react";

import type { ExperimentMethodId } from "../../api/types";
import type { ResearchWorkspaceView } from "./researchWorkspaceModel";
import type {
  ExperimentBaselineArtifactDraft,
  ExperimentFullRunResultDraft,
  ExperimentKnowledgeIngestionDraft,
  ExperimentSmokeResultDraft,
  ResearchLoopCreateDraft,
  ResearchLoopDecisionDraft,
  ResearchLoopEvidenceDraft,
} from "./experimentLoopModel";
import { useTeamResearchSecondaryQueries } from "./useTeamResearchSecondaryQueries";

export type UseResearchExperimentWorkspaceInput = {
  effectiveTeamId: string;
  researchWorkflowTeamSelected: boolean;
  researchWorkspaceView: ResearchWorkspaceView;
  sourceCollectionStandalone: boolean;
  researchSecondaryStatusQueryEnabled: boolean;
};

const EMPTY_BASELINE_ARTIFACT_DRAFT: ExperimentBaselineArtifactDraft = {
  artifactPath: "",
  reproductionCommand: "",
  evaluationCommand: "",
  metricValue: "",
};

const EMPTY_SMOKE_RESULT_DRAFT: ExperimentSmokeResultDraft = {
  status: "needs_review",
  metricValue: "",
  baselineMetricValue: "",
  delta: "",
  resultPath: "",
  logRef: "",
  evaluationCommand: "",
  notes: "",
};

const EMPTY_FULL_RUN_RESULT_DRAFT: ExperimentFullRunResultDraft = {
  status: "needs_review",
  metricValue: "",
  baselineMetricValue: "",
  smokeMetricValue: "",
  delta: "",
  resultPath: "",
  logRef: "",
  configPath: "",
  reproductionCommand: "",
  evaluationCommand: "",
  notes: "",
};

const EMPTY_KNOWLEDGE_INGESTION_DRAFT: ExperimentKnowledgeIngestionDraft = {
  knowledgeBaseId: "research-team-experiment-kb",
  targetDomain: "挑战杯实验结果",
  title: "",
  summary: "",
  notes: "",
  wakeStewardAgent: true,
};

const EMPTY_RESEARCH_LOOP_CREATE_DRAFT: ResearchLoopCreateDraft = {
  researchQuestion: "",
  constraints: "",
  datasetRefs: "",
  environmentRefs: "",
};

const EMPTY_RESEARCH_LOOP_EVIDENCE_DRAFT: ResearchLoopEvidenceDraft = {
  evidenceType: "",
  status: "needs_review",
  summary: "",
  metricName: "",
  metricValue: "",
  baselineMetricValue: "",
  delta: "",
  artifactRef: "",
  datasetRefs: "",
  environmentRefs: "",
  logRefs: "",
  commandPreview: "",
};

const EMPTY_RESEARCH_LOOP_DECISION_DRAFT: ResearchLoopDecisionDraft = {
  decision: "needs_more_evidence",
  rationale: "",
  nextTemplateId: "",
  nextActions: "",
  allowedVariableChanges: "",
  frozenControls: "",
};

export function useResearchExperimentWorkspace(input: UseResearchExperimentWorkspaceInput) {
  const {
    effectiveTeamId,
    researchWorkflowTeamSelected,
    researchWorkspaceView,
    sourceCollectionStandalone,
    researchSecondaryStatusQueryEnabled,
  } = input;

  const [preferredExperimentMethod, setPreferredExperimentMethod] = useState<ExperimentMethodId | "">("");
  const [experimentBaselineArtifactDraft, setExperimentBaselineArtifactDraft] =
    useState<ExperimentBaselineArtifactDraft>(EMPTY_BASELINE_ARTIFACT_DRAFT);
  const [experimentSmokeResultDraft, setExperimentSmokeResultDraft] =
    useState<ExperimentSmokeResultDraft>(EMPTY_SMOKE_RESULT_DRAFT);
  const [experimentFullRunResultDraft, setExperimentFullRunResultDraft] =
    useState<ExperimentFullRunResultDraft>(EMPTY_FULL_RUN_RESULT_DRAFT);
  const [experimentKnowledgeIngestionDraft, setExperimentKnowledgeIngestionDraft] =
    useState<ExperimentKnowledgeIngestionDraft>(EMPTY_KNOWLEDGE_INGESTION_DRAFT);
  const [selectedResearchLoopTemplateId, setSelectedResearchLoopTemplateId] =
    useState("algorithm_model_experiment");
  const [researchLoopCreateDraft, setResearchLoopCreateDraft] =
    useState<ResearchLoopCreateDraft>(EMPTY_RESEARCH_LOOP_CREATE_DRAFT);
  const [researchLoopEvidenceDraft, setResearchLoopEvidenceDraft] =
    useState<ResearchLoopEvidenceDraft>(EMPTY_RESEARCH_LOOP_EVIDENCE_DRAFT);
  const [researchLoopDecisionDraft, setResearchLoopDecisionDraft] =
    useState<ResearchLoopDecisionDraft>(EMPTY_RESEARCH_LOOP_DECISION_DRAFT);

  const {
    experimentPlanningStatusQuery,
    experimentMethodCatalogQuery,
    researchLoopTemplatesQuery,
    researchLoopStatusQuery,
  } = useTeamResearchSecondaryQueries({
    effectiveTeamId,
    researchWorkflowTeamSelected,
    researchWorkspaceView,
    sourceCollectionStandalone,
    researchSecondaryStatusQueryEnabled,
  });

  return {
    preferredExperimentMethod,
    setPreferredExperimentMethod,
    experimentBaselineArtifactDraft,
    setExperimentBaselineArtifactDraft,
    experimentSmokeResultDraft,
    setExperimentSmokeResultDraft,
    experimentFullRunResultDraft,
    setExperimentFullRunResultDraft,
    experimentKnowledgeIngestionDraft,
    setExperimentKnowledgeIngestionDraft,
    selectedResearchLoopTemplateId,
    setSelectedResearchLoopTemplateId,
    researchLoopCreateDraft,
    setResearchLoopCreateDraft,
    researchLoopEvidenceDraft,
    setResearchLoopEvidenceDraft,
    researchLoopDecisionDraft,
    setResearchLoopDecisionDraft,
    experimentPlanningStatusQuery,
    experimentMethodCatalogQuery,
    researchLoopTemplatesQuery,
    researchLoopStatusQuery,
  };
}

export type ResearchExperimentWorkspaceApi = ReturnType<typeof useResearchExperimentWorkspace>;
