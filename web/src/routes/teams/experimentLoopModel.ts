import type {
  ExperimentContractV2,
  ExperimentContractValidation,
  TeamWorkflowOrchestration,
} from "../../api/types";
import type { ResearchMemoryContextSummary } from "./ResearchMemoryEvidencePanel";
import type {
  ResearchStageRound,
  ResearchStageRoundStatusPayload,
} from "./source-collection/stageProjection";

export type ExperimentPlanChecklistItem = {
  item: string;
  label: string;
  status: "pass" | "needs_attention" | string;
  note: string;
};

export type ExperimentHypothesisCandidateSummary = {
  candidateId: string;
  title: string;
  summary: string;
  currentState: string;
  qualityStatus: string;
  valid: boolean;
  validationIssueCount: number;
  hypothesis: string;
  baseline: string;
  expectedBenefit: string;
  expectedComputeCost: string;
  experimentPlan: {
    dataset: string;
    metric: string;
    baseline: string;
    smokePlan: string;
  };
  missingExperimentPlanFields: string[];
  updatedAt: string;
};

export type ExperimentBaselineArtifactRecord = {
  artifactId: string;
  status: string;
  baseline: string;
  dataset: string;
  metric: string;
  metricValue: string;
  artifactPath: string;
  evidenceRef: string;
  reproductionCommand: string;
  evaluationCommand: string;
  registeredByAgent: string;
  registeredAt: string;
};

export type ExperimentSmokeResultStatus = "passed" | "failed" | "needs_review";

export const EXPERIMENT_SMOKE_RESULT_STATUSES: ExperimentSmokeResultStatus[] = ["needs_review", "passed", "failed"];

export type ExperimentSmokeResultRecord = {
  smokeResultId: string;
  status: ExperimentSmokeResultStatus | string;
  gateDecision: string;
  planId: string;
  baselineArtifactId: string;
  baselineMetricValue: string;
  metricName: string;
  metricValue: string;
  delta: string;
  resultPath: string;
  logRef: string;
  evaluationCommand: string;
  notes: string;
  recordedByAgent: string;
  recordedAt: string;
};

export type ExperimentFullRunResultStatus = "passed" | "failed" | "needs_review";

export const EXPERIMENT_FULL_RUN_RESULT_STATUSES: ExperimentFullRunResultStatus[] = ["needs_review", "passed", "failed"];

export type ExperimentFullRunResultRecord = {
  fullRunResultId: string;
  status: ExperimentFullRunResultStatus | string;
  gateDecision: string;
  planId: string;
  smokeResultId: string;
  baselineArtifactId: string;
  baselineMetricValue: string;
  smokeMetricValue: string;
  metricName: string;
  metricValue: string;
  delta: string;
  resultPath: string;
  logRef: string;
  configPath: string;
  reproductionCommand: string;
  evaluationCommand: string;
  notes: string;
  recordedByAgent: string;
  recordedAt: string;
};

export type ExperimentResultPackRecord = {
  packId: string;
  kind: string;
  status: string;
  planId: string;
  fullRunResultId: string;
  knowledgeBaseId: string;
  targetDomain: string;
  title: string;
  summary: string;
  metrics?: Record<string, string>;
  artifactRefs?: Array<Record<string, unknown>>;
  officialBoundary?: Record<string, unknown>;
  requestedByAgent: string;
  createdAt: string;
};

export type ExperimentKnowledgeIngestionRecord = {
  status: string;
  experimentResultPack?: ExperimentResultPackRecord;
  knowledgeStewardActivation?: Record<string, unknown>;
  knowledgeBaseId: string;
  targetDomain: string;
  updatedAt: string;
  officialBoundary?: Record<string, unknown>;
};

export type ExperimentPlanRecord = {
  planId: string;
  stageRoundId: string;
  status: string;
  title: string;
  topic: string;
  goal: string;
  selectedHypotheses: ExperimentHypothesisCandidateSummary[];
  hypothesisCandidateIds: string[];
  experimentContract?: ExperimentContractV2;
  contractValidation?: ExperimentContractValidation;
  designGate?: {
    status: "draft" | "frozen" | string;
    requiresExplicitFreeze: boolean;
    source: string;
    sourceLoopId: string;
    sourceDecisionId: string;
    sourceProposalId: string;
    sourceIdempotencyKey?: string;
    frozenAt: string;
    frozenByAgent: string;
  };
  experimentPlan: {
    dataset: string;
    metric: string;
    baseline: string;
    smokePlan: string;
  };
  baselineSelection: {
    baseline: string;
    status: string;
    activeBaselineReady: boolean;
    activeBaselineArtifactId?: string;
    activeBaselineArtifact?: ExperimentBaselineArtifactRecord;
    artifacts?: ExperimentBaselineArtifactRecord[];
    reason: string;
  };
  activeSmokeResultId?: string;
  activeSmokeResult?: ExperimentSmokeResultRecord;
  smokeResults?: ExperimentSmokeResultRecord[];
  activeFullRunResultId?: string;
  activeFullRunResult?: ExperimentFullRunResultRecord;
  fullRunResults?: ExperimentFullRunResultRecord[];
  knowledgeIngestion?: ExperimentKnowledgeIngestionRecord;
  readinessChecklist: ExperimentPlanChecklistItem[];
  readiness: {
    readyForPlanReview: boolean;
    readyForSmoke: boolean;
    readyForFullRun: boolean;
    readyForKnowledgeIngestion?: boolean;
    blockers: string[];
    knowledgeBlockers?: string[];
  };
  updatedAt: string;
};

export type ExperimentPlanningStatusPayload = {
  schemaVersion: number;
  teamId: string;
  status: string;
  latestExperimentRound?: ResearchStageRound | null;
  latestKnowledgeCollectionRound?: ResearchStageRound | null;
  activePlan?: ExperimentPlanRecord | null;
  plans: ExperimentPlanRecord[];
  lifecycleProjection?: {
    schemaVersion: number;
    migrationMode: string;
    stage1: {
      status: string;
      latestRoundId: string;
      sourceCandidateCount: number;
      hypothesisCandidateCount: number;
      linkedExperimentKnowledgeItemCount: number;
    };
    stage2: {
      status: string;
      activeDesignPlanId: string;
      frozenDesignRevision: number;
      readyForExecution: boolean;
      completionDefinition: string;
      memoryContextSummary?: ResearchMemoryContextSummary;
    };
    stage3: {
      status: string;
      activeIterationId: string;
      bestCandidateId: string;
      bestValidatedResultId: string;
      bestValidatedPlanId: string;
      latestDiagnosticStatus: {
        planId: string;
        revision: number;
        status: string;
        title: string;
      };
      completionDefinition: string;
      memoryContextSummary?: ResearchMemoryContextSummary;
    };
    compatibility: {
      legacyActivePlanId: string;
      historyRewritten: boolean;
      appendOnlyEvidencePreserved: boolean;
    };
  };
  challengeProgramProjection?: {
    schemaVersion: number;
    migrationMode: string;
    program: {
      title: string;
      officialProblemId: string;
      track: string;
      officialQuestionCount: number;
      deliveryMode: "mvp" | string;
      immediateQuestionCount: number;
      directionBRole: string;
      completed: boolean;
    };
    stage1ComplianceReadiness: {
      status: string;
      completionDefinition: string;
      blockers: string[];
      dashscopeQwenProvider: { configured: boolean; providerIds: string[]; modelRefs: string[] };
      officialModelCallEvidence: { count: number; evidenceIds: string[] };
      singleQuestionSample: { required: number; completed: number; questionId: string; realCallsRequired: boolean };
      trialRun: {
        required: number;
        completed: number;
        realCallsRequired: boolean;
        completedQuestionIds: string[];
        outcomeCounts: Record<string, number>;
      };
      mvpManifest: {
        requiredQuestionCount: number;
        completedQuestionCount: number;
        goldenSampleQuestionId: string;
        testQuestionIds: string[];
        scaleUpDeferred: boolean;
      };
      independentEvaluationDimensions: string[];
      aggregateScoreAllowed: boolean;
      humanGates: string[];
      acceptance: {
        schemaValidation: boolean;
        citationValidation: boolean;
        minimumHypothesisCount: number;
        allSevenDimensionsReviewed: boolean;
        allFourHumanGatesApproved: boolean;
        researchPlanPresent: boolean;
        feedbackRevisionCount: number;
      };
    };
    stage2BatchGovernance: {
      status: string;
      completionDefinition: string;
      questionCount: number;
      completedQuestionCount: number;
      batchSize: number;
      batchCount: number;
      completedBatchCount: number;
      failedOrBlockedCountedAsComplete: boolean;
      aggregateScoreAllowed: boolean;
      pipeline: string[];
      ledger: { initialized: boolean; manifestHashVerified: boolean; citationAuditComplete: boolean };
    };
    stage3DeepResearchDelivery: {
      status: string;
      completionDefinition: string;
      representativeCaseCount: number;
      requiredRepresentativeCaseCount: number;
      caseRecords: Array<{
        caseId: string;
        title: string;
        internalStatus: string;
        projectCompletionStatus: string;
        bestValidatedResultId: string;
        claimBoundary: string;
      }>;
      projectCompleted: boolean;
    };
    compatibility: {
      legacyLifecycleProjectionPreserved: boolean;
      legacyStage2DesignStatus: string;
      legacyStage3CaseStatus: string;
      acceptedForWriteupMeansProgramComplete: boolean;
      appendOnlyEvidencePreserved: boolean;
      historyRewritten: boolean;
    };
  };
  hypothesisCandidates: ExperimentHypothesisCandidateSummary[];
  readyHypothesisCandidates: ExperimentHypothesisCandidateSummary[];
  gaps: Array<{ code: string; severity: string; message: string }>;
  summary: {
    experimentRoundCount: number;
    planCount: number;
    hypothesisCandidateCount: number;
    readyHypothesisCandidateCount: number;
    gapCount: number;
    activePlanId: string;
    activeFullRunResultId?: string;
    knowledgeIngestionStatus?: string;
    activeDesignPlanId?: string;
    frozenDesignRevision?: number;
    activeIterationId?: string;
    bestCandidateId?: string;
    bestValidatedResultId?: string;
    latestDiagnosticStatus?: {
      planId: string;
      revision: number;
      status: string;
      title: string;
    };
  };
  readiness: {
    readyToPlan: boolean;
    readyForSmoke: boolean;
    readyForFullRun: boolean;
    readyForKnowledgeIngestion?: boolean;
    reason: string;
  };
  boundaries: {
    autoExecution: boolean;
    writesFormalKnowledge: boolean;
    writesRag: boolean;
    writesOfficialGraph: boolean;
    createsExperimentAttempt: boolean;
    requiresUserDecision: boolean;
    boundary: string;
  };
  storagePath: string;
  nextActions: string[];
  updatedAt: string;
};

export type ExperimentPlanCreatePayload = {
  plan: ExperimentPlanRecord;
  status: ExperimentPlanningStatusPayload;
  stageRound: ResearchStageRound;
  stageRoundStatus: ResearchStageRoundStatusPayload;
  workflow: TeamWorkflowOrchestration;
  boundaries: ExperimentPlanningStatusPayload["boundaries"];
};

export type ExperimentBaselineArtifactRegisterPayload = {
  baselineArtifact: ExperimentBaselineArtifactRecord;
  plan: ExperimentPlanRecord;
  status: ExperimentPlanningStatusPayload;
  stageRoundStatus: ResearchStageRoundStatusPayload;
  workflow: TeamWorkflowOrchestration;
  boundaries: ExperimentPlanningStatusPayload["boundaries"];
};

export type ExperimentSmokeResultRegisterPayload = {
  smokeResult: ExperimentSmokeResultRecord;
  plan: ExperimentPlanRecord;
  status: ExperimentPlanningStatusPayload;
  stageRoundStatus: ResearchStageRoundStatusPayload;
  workflow: TeamWorkflowOrchestration;
  boundaries: ExperimentPlanningStatusPayload["boundaries"];
};

export type ExperimentFullRunResultRegisterPayload = {
  fullRunResult: ExperimentFullRunResultRecord;
  plan: ExperimentPlanRecord;
  status: ExperimentPlanningStatusPayload;
  stageRoundStatus: ResearchStageRoundStatusPayload;
  workflow: TeamWorkflowOrchestration;
  boundaries: ExperimentPlanningStatusPayload["boundaries"];
};

export type ExperimentResultKnowledgeIngestionPayload = {
  experimentResultPack: ExperimentResultPackRecord;
  knowledgeStewardActivation: Record<string, unknown>;
  plan: ExperimentPlanRecord;
  status: ExperimentPlanningStatusPayload;
  stageRoundStatus: ResearchStageRoundStatusPayload;
  workflow: TeamWorkflowOrchestration;
  boundaries: ExperimentPlanningStatusPayload["boundaries"];
};

export type ResearchLoopBoundary = {
  executionMode: string;
  autoExecution: boolean;
  externalExecution: boolean;
  sandboxRunner: boolean;
  trainingRunner: boolean;
  writesExperimentResult: boolean;
  writesFormalTeamKnowledge: boolean;
  writesFormalRag: boolean;
  writesOfficialGraph: boolean;
  requiresUserDecision: boolean;
  canCreateNextDesignDraft?: boolean;
  nextDesignDraftRequiresExplicitFreeze?: boolean;
  nextDesignDraftStartsExecution?: boolean;
};

export type ResearchLoopTemplate = {
  templateId: string;
  templateKind: string;
  label: string;
  labelZh: string;
  description: string;
  problemFits: string[];
  requiredInputs: string[];
  requiredEvidenceTypes: string[];
  decisionGates: string[];
  defaultIterationActions: string[];
};

export type ResearchLoopEvidenceStatus = "needs_review" | "passed" | "failed" | "not_applicable";

export const RESEARCH_LOOP_EVIDENCE_STATUSES: ResearchLoopEvidenceStatus[] = ["needs_review", "passed", "failed", "not_applicable"];

export type ResearchLoopDecisionValue = "needs_more_evidence" | "repair_and_repeat" | "promote_to_iteration" | "accept_for_writeup" | "reject_or_archive";

export const RESEARCH_LOOP_DECISION_VALUES: ResearchLoopDecisionValue[] = [
  "needs_more_evidence",
  "repair_and_repeat",
  "promote_to_iteration",
  "accept_for_writeup",
  "reject_or_archive",
];

export type ResearchLoopEvidenceRecord = {
  evidenceId: string;
  evidenceType: string;
  status: string;
  summary: string;
  metricName: string;
  metricValue: string;
  baselineMetricValue: string;
  delta: string;
  artifactRefs: Array<Record<string, unknown>>;
  sourceRefs: Array<Record<string, unknown>>;
  datasetRefs: string[];
  environmentRefs: string[];
  logRefs: string[];
  commandPreview: string;
  recordedAt: string;
  recordedByAgent: string;
};

export type ResearchLoopDecisionRecord = {
  decisionId: string;
  decision: string;
  statusAfterDecision: string;
  rationale: string;
  createdAt: string;
  decidedByAgent: string;
  iterationProposalId?: string;
  nextDesignPlanId?: string;
  idempotencyKey?: string;
};

export type ResearchLoopIterationProposal = {
  proposalId: string;
  loopId: string;
  sourceDecisionId: string;
  status: string;
  nextTemplateId: string;
  nextTemplateKind: string;
  nextActions: string[];
  createdAt: string;
  createdByAgent: string;
  nextDesignPlanId?: string;
  nextDesignRevision?: number;
  nextDesignGateStatus?: string;
};

export type ResearchLoopPendingDesignProposal = ResearchLoopIterationProposal & {
  loopTitle: string;
  researchQuestion: string;
  sourcePlanId: string;
};

export type ResearchLoopRecord = {
  loopId: string;
  teamId: string;
  templateId: string;
  templateKind: string;
  templateSnapshot?: ResearchLoopTemplate;
  title: string;
  researchQuestion: string;
  status: string;
  createdAt: string;
  updatedAt: string;
  createdByAgent: string;
  linkedExperiment: {
    stageRoundId: string;
    planId: string;
    targetRef: string;
    candidateIds: string[];
  };
  inputs: {
    inputRefs: string[];
    sourceRefs: Array<Record<string, unknown>>;
    datasetRefs: string[];
    environmentRefs: string[];
    constraints: string;
    metadata: Record<string, unknown>;
  };
  evidenceRecords: ResearchLoopEvidenceRecord[];
  decisions: ResearchLoopDecisionRecord[];
  iterationProposals: ResearchLoopIterationProposal[];
  readiness: {
    requiredEvidenceTypes: string[];
    presentEvidenceTypes: string[];
    missingEvidenceTypes: string[];
    evidenceRecordCount: number;
    readyForDecision: boolean;
    readyForIteration: boolean;
    blockers: string[];
  };
  boundaries: ResearchLoopBoundary;
};

export type ResearchLoopSummary = {
  loopId: string;
  templateId: string;
  templateKind: string;
  title: string;
  researchQuestion: string;
  status: string;
  updatedAt: string;
  createdByAgent: string;
  evidenceRecordCount: number;
  decisionCount: number;
  readyForDecision: boolean;
  readyForIteration: boolean;
  missingEvidenceTypes: string[];
};

export type ResearchLoopStatusPayload = {
  schemaVersion: number;
  storeKind: string;
  teamId: string;
  activeLoopId: string;
  activeLoop: ResearchLoopRecord | null;
  loops: ResearchLoopSummary[];
  pendingDesignProposals: ResearchLoopPendingDesignProposal[];
  summary: {
    totalLoopCount: number;
    readyForDecisionCount: number;
    readyForIterationCount: number;
    blockedLoopCount: number;
  };
  templates: ResearchLoopTemplate[];
  storagePath: string;
  nextActions: Array<{ action: string; label: string; requiresUserDecision: boolean; missingEvidenceTypes?: string[] }>;
  boundaries: ResearchLoopBoundary;
};

export type ResearchLoopTemplatesPayload = {
  schemaVersion: number;
  templates: ResearchLoopTemplate[];
  defaultTemplateId: string;
  boundaries: ResearchLoopBoundary;
};

export type ResearchLoopCreatePayload = {
  loop: ResearchLoopRecord;
  status: ResearchLoopStatusPayload;
  boundaries: ResearchLoopBoundary;
};

export type ResearchLoopEvidencePayload = {
  evidence: ResearchLoopEvidenceRecord;
  loop: ResearchLoopRecord;
  status: ResearchLoopStatusPayload;
  boundaries: ResearchLoopBoundary;
};

export type ResearchLoopDecisionPayload = {
  decision: ResearchLoopDecisionRecord;
  iterationProposal: ResearchLoopIterationProposal | null;
  nextDesignDraft: { status: "created" | "reused" | string; plan: ExperimentPlanRecord } | null;
  loop: ResearchLoopRecord;
  status: ResearchLoopStatusPayload;
  boundaries: ResearchLoopBoundary;
};

export type ExperimentDesignFreezePayload = {
  status: "frozen" | "already_frozen" | string;
  plan: ExperimentPlanRecord;
  experimentStatus?: ExperimentPlanningStatusPayload;
};

export type ExperimentBaselineArtifactDraft = {
  artifactPath: string;
  reproductionCommand: string;
  evaluationCommand: string;
  metricValue: string;
};

export type ExperimentSmokeResultDraft = {
  status: ExperimentSmokeResultStatus;
  metricValue: string;
  baselineMetricValue: string;
  delta: string;
  resultPath: string;
  logRef: string;
  evaluationCommand: string;
  notes: string;
};

export type ExperimentFullRunResultDraft = {
  status: ExperimentFullRunResultStatus;
  metricValue: string;
  baselineMetricValue: string;
  smokeMetricValue: string;
  delta: string;
  resultPath: string;
  logRef: string;
  configPath: string;
  reproductionCommand: string;
  evaluationCommand: string;
  notes: string;
};

export type ExperimentKnowledgeIngestionDraft = {
  knowledgeBaseId: string;
  targetDomain: string;
  title: string;
  summary: string;
  notes: string;
  wakeStewardAgent: boolean;
};

export type ResearchLoopCreateDraft = {
  researchQuestion: string;
  constraints: string;
  datasetRefs: string;
  environmentRefs: string;
};

export type ResearchLoopEvidenceDraft = {
  evidenceType: string;
  status: ResearchLoopEvidenceStatus;
  summary: string;
  metricName: string;
  metricValue: string;
  baselineMetricValue: string;
  delta: string;
  artifactRef: string;
  datasetRefs: string;
  environmentRefs: string;
  logRefs: string;
  commandPreview: string;
};

export type ResearchLoopDecisionDraft = {
  decision: ResearchLoopDecisionValue;
  rationale: string;
  nextTemplateId: string;
  nextActions: string;
};


export function researchIterationLifecycleStatusLabel(status: string, lang: "zh" | "en") {
  if (status === "accepted_for_writeup") {
    return lang === "zh" ? "已晋升" : "promoted";
  }
  if (status === "not_started") {
    return lang === "zh" ? "待执行" : "not started";
  }
  if (["needs_review", "ready_for_iteration", "repair_and_repeat"].includes(status)) {
    return lang === "zh" ? "待优化" : "needs iteration";
  }
  return lang === "zh" ? "执行中" : "executing";
}

export function researchDiagnosticStatusLabel(status: string, lang: "zh" | "en") {
  const normalizedStatus = status.trim().toLowerCase();
  if (!normalizedStatus) {
    return lang === "zh" ? "无" : "none";
  }
  const labelsMap: Record<string, { zh: string; en: string }> = {
    draft: { zh: "设计草稿", en: "design draft" },
    planned: { zh: "已完成规划", en: "planned" },
    baseline_ready: { zh: "Baseline 已就绪", en: "baseline ready" },
    ready_for_smoke: { zh: "可执行 Smoke", en: "ready for smoke" },
    smoke_running: { zh: "Smoke 执行中", en: "smoke running" },
    smoke_passed: { zh: "Smoke 已通过", en: "smoke passed" },
    smoke_partial: { zh: "Smoke 部分通过", en: "smoke partially passed" },
    smoke_needs_review: { zh: "Smoke 待复核", en: "smoke needs review" },
    ready_for_full_run: { zh: "可执行正式实验", en: "ready for formal run" },
    full_run_running: { zh: "正式实验执行中", en: "formal run in progress" },
    full_run_passed: { zh: "正式实验已通过", en: "formal run passed" },
    full_run_failed: { zh: "正式实验失败", en: "formal run failed" },
    full_run_needs_review: { zh: "正式实验待复核", en: "formal run needs review" },
    ready_for_knowledge_ingestion: { zh: "待知识回写", en: "ready for knowledge writeback" },
    knowledge_steward_notified: { zh: "已通知知识治理", en: "knowledge steward notified" },
    knowledge_steward_wake_pending: { zh: "等待知识治理响应", en: "waiting for knowledge steward" },
    knowledge_steward_notification_failed: { zh: "知识治理通知失败", en: "knowledge steward notification failed" },
    ingested: { zh: "已完成知识回写", en: "knowledge writeback complete" },
    needs_review: { zh: "待复核", en: "needs review" },
    blocked: { zh: "已阻塞", en: "blocked" },
  };
  return labelsMap[normalizedStatus]?.[lang] || status;
}

export function experimentPlanningStatusQueryKey(id: string) {
  return ["teams", id, "workflow-orchestration", "experiments", "status"] as const;
}

export function experimentMethodCatalogQueryKey(id: string) {
  return ["teams", id, "workflow-orchestration", "experiments", "methods"] as const;
}

export function researchLoopTemplatesQueryKey(id: string) {
  return ["teams", id, "workflow-orchestration", "research-loop", "templates"] as const;
}

export function researchLoopStatusQueryKey(id: string) {
  return ["teams", id, "workflow-orchestration", "research-loop", "status"] as const;
}
