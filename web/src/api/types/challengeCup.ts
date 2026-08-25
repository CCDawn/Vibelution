/** Competition Program v2 read model returned by the Team experiment status API. */

export type CompetitionProgramDirection = {
  directionId: string;
  name: string;
  required: boolean;
  role: string;
};

export type CompetitionQuestionCatalogItem = {
  questionId: string;
  domain: string;
  questionEn: string;
};

export type CompetitionRequiredDeepExperiment = {
  experimentId: string;
  questionId: string;
  name: string;
  themeId: string;
  campaignId: string;
  required: boolean;
  questionResultApproved: boolean;
  approved: boolean;
};

export type CompetitionProgramProjection = {
  schemaVersion: number;
  contractVersion: string;
  contractId: string;
  status: string;
  program: {
    problemId: string;
    title: string;
    track: string;
    direction: string;
    dimensions: string[];
    directionMode: string;
    foundationModelFamily: string;
    officialQuestionCount: number;
    catalogId: string;
    catalogSha256: string;
    questionSchemaVersion: number;
    completed: boolean;
  };
  directions: CompetitionProgramDirection[];
  programContract: {
    version: string;
    coreBehaviorHash: string;
  };
  fullCatalogPolicy: {
    version: string;
    corePolicyHash: string;
  };
  questionSchema: {
    activeVersion: number;
    readOnlyVersions: number[];
    migrationMode: string;
  };
  fullCatalogResultSet: {
    questionCount: number;
    requiredApprovedQuestionCount: number;
    approvedQuestionCount: number;
    approvedQuestionIds: string[];
    missingQuestionCount: number;
    complete: boolean;
  };
  questionCatalog: {
    catalogId: string;
    catalogSha256: string;
    questionCount: number;
    questions: CompetitionQuestionCatalogItem[];
  };
  requiredDeepExperiments: CompetitionRequiredDeepExperiment[];
  allRequiredDeepExperimentsApproved: boolean;
  independentThemeBoundaries: {
    separateThemes: boolean;
    separateCampaigns: boolean;
    crossExperimentScientificEvidenceReuse: string;
  };
  completion: {
    programRule: string;
    fullCatalogResultSetRequired: unknown;
    allRequiredDeepExperimentsRequired: unknown;
    projectCompletedDerivedOnly: boolean;
    legacyQuestionCountsAffectCompletion: boolean;
    legacyRepresentativeCaseCountsAffectCompletion: boolean;
    completed: boolean;
  };
  directionSubmissionRequirement: {
    captured: boolean;
    officialPageObservedState: string;
    blocksSubmissionReady: boolean;
  };
  legacyProjection: {
    mode: string;
    schemaVersion: number;
    affectsCompletion: boolean;
    deprecated: boolean;
  };
  isolationPolicy: {
    separateThemeContracts: boolean;
    separateCampaigns: boolean;
    separateTeams: boolean;
  };
};

export type ChallengeSubmissionReadinessAction = {
  kind: "repair" | "inspect" | "export" | string;
  target: string;
  label: string;
  questionId?: string;
};

export type ChallengeDeliverablesInspection = {
  status: "ready" | "blocked" | string;
  blockers: Array<{ code: string; message: string }>;
  deliverableManifest?: { status: "ready" | "blocked" | string };
};

export type ChallengeSubmissionReadinessArtifact = {
  key: string;
  label: string;
  required: boolean;
  status: "ready" | "blocked" | "optional" | string;
  detail: string;
  blocker: string;
  primaryAction: ChallengeSubmissionReadinessAction;
};

export type ChallengeSubmissionReadiness = {
  schemaVersion: number;
  teamId: string;
  status: "ready" | "blocked" | string;
  readyCount: number;
  requiredCount: number;
  blockerCount: number;
  artifacts: ChallengeSubmissionReadinessArtifact[];
  blockers: Array<{
    code: string;
    label: string;
    action: ChallengeSubmissionReadinessAction;
  }>;
  programSummary: {
    title: string;
    questionCount: number;
    approvedQuestionCount: number;
    deepExperimentCount: number;
    approvedDeepExperimentCount: number;
  };
};

export type ChallengeCatalogReadinessEvidenceStatus =
  | "PASS"
  | "FAIL"
  | "BLOCKED"
  | "MISSING"
  | string;

export type ChallengeCatalogReadinessEvidence = {
  status: ChallengeCatalogReadinessEvidenceStatus;
  locator: string;
};

export type ChallengeCatalogReadinessCounts = {
  present_count: number;
  missing_count: number;
  duplicate_count: number;
  submission_eligible_count: number;
  package_backed_count: number;
  quality_approved_count: number;
  human_gate_approved_count: number;
  receipt_complete_count: number;
  required_question_count: number;
  submission_ready?: boolean;
};

export type ChallengeCatalogReadinessResultSet = {
  catalogId: string;
  catalogVersion: string;
  scopeHash: string;
  counts: ChallengeCatalogReadinessCounts;
  selectionApprovedCount: number;
  researchPlanApprovedCount: number;
  receiptCompleteCount: number;
  modelPolicyMatchedCount: number;
  resultManifest: Record<string, unknown>;
};

/** Server-owned formal 125-question readiness; separate from submission readiness. */
export type ChallengeCatalogReadiness = {
  schemaVersion: number;
  reportKind: string;
  status: "READY" | "NOT_READY" | string;
  researchAuthorizationRequired: boolean;
  realCampaignAllowed: boolean;
  nextLegalAction: string;
  sourceCommit: string;
  programContract: Record<string, unknown>;
  catalogPolicy: Record<string, unknown>;
  modelPolicySha256: string;
  catalogResultSet: ChallengeCatalogReadinessResultSet;
  evidence: Record<"r0" | "r1" | "api" | "frontend" | "browser", ChallengeCatalogReadinessEvidence>;
  blockers: string[];
  readinessReportSha256: string;
  generatedAt: string;
};

/** Known legal next actions of the DEV-only Challenge Cup control surface. */
export type ChallengeCupDevNextLegalAction =
  | "run_dev_readiness"
  | "repair_failed_platform_gates"
  | "run_dev_1_fixture_batch"
  | "repair_dev_1_fixture_batch"
  | "run_dev_5_fixture_batch"
  | "resume_dev_5_fixture_batch"
  | "repair_dev_5_fixture_batch"
  | "RESEARCH_AUTHORIZATION_REQUIRED";

export type ChallengeCupDevGate = {
  gateId: string;
  status: string;
  detail: string;
};

export type ChallengeCupDevReadinessProjection = {
  schemaVersion: number;
  reportKind: string;
  status: string;
  mode: string;
  realCampaignAllowed: boolean;
  researchAuthorizationRequired: boolean;
  nextLegalAction: string;
  generatedAt: string;
  updatedAt: string;
  gates: ChallengeCupDevGate[];
};

export type ChallengeCupDevStatusSummary = {
  pending: number;
  running: number;
  succeeded: number;
  failed: number;
  blocked: number;
};

export type ChallengeCupDevBatchProjection = {
  schemaVersion: number;
  planId: string;
  gateId: string;
  questionCount: number;
  statusSummary: ChallengeCupDevStatusSummary;
  pendingCount: number;
  succeededCount: number;
  failedCount: number;
  blockedCount: number;
  totalAttempts: number;
  completedQuestionIds: string[];
  pendingQuestionIds: string[];
  lastUpdatedAt: string;
  canResume: boolean;
};

export type ChallengeCupDevBoundary = {
  mode: string;
  realCampaignAllowed: boolean;
  authorizedPlans: string[];
  forbiddenPlans: string[];
  forbiddenFeatures: string[];
  fixtureOnly: boolean;
};

export type ChallengeCupDevControlSnapshot = {
  schemaVersion: number;
  teamId: string;
  generatedAt: string;
  mode: string;
  realCampaignAllowed: boolean;
  nextLegalAction: ChallengeCupDevNextLegalAction | string;
  report: ChallengeCupDevReadinessProjection | null;
  batches: Record<string, ChallengeCupDevBatchProjection>;
  boundary: ChallengeCupDevBoundary;
};

export type ChallengeCupDevReadinessRunRequest = {
  mode: string;
};

export type ChallengeCupDevReadinessRunResponse = {
  schemaVersion: number;
  teamId: string;
  report: ChallengeCupDevReadinessProjection;
  cleanedUp: boolean;
  updatedAt: string;
};

export type ChallengeCupDevBatchRunRequest = {
  maxItems: number | null;
  /** True only for repair POSTs; normal batch runs always send false. */
  retryFailed: boolean;
};

export type ChallengeCupDevBatchOutcome = {
  questionId: string;
  outcome: string;
};

export type ChallengeCupDevBatchRunResponse = {
  schemaVersion: number;
  teamId: string;
  planId: string;
  gateId: string;
  attempted: string[];
  outcomes: ChallengeCupDevBatchOutcome[];
  checkpoint: ChallengeCupDevBatchProjection;
  persistedAt: string;
  persisted: boolean;
};

export type ChallengeCupRealBatchPlanId = "real-1" | "real-5" | "real-12" | "real-125";

export type ChallengeCupRealBatchStatus = "pending" | "running" | "succeeded" | "failed" | "blocked";

export type ChallengeCupRealBatchStatusSummary = {
  pending: number;
  running: number;
  succeeded: number;
  failed: number;
  blocked: number;
};

export type ChallengeCupRealBatchRunRef = {
  runId: string;
  attempt: number;
};

/** Server-owned projection of one persisted real catalog gate. */
export type ChallengeCupRealBatchProjection = {
  schemaVersion: number;
  planId: string;
  gateId: string;
  exists: boolean;
  questionCount: number;
  statusSummary: ChallengeCupRealBatchStatusSummary;
  pendingCount: number;
  succeededCount: number;
  failedCount: number;
  blockedCount: number;
  totalAttempts: number;
  completedQuestionIds: string[];
  pendingQuestionIds: string[];
  runRefs: Record<string, ChallengeCupRealBatchRunRef>;
  awaitingApprovalQuestionIds: string[];
  consecutiveFailures: number;
  failureBudget: number;
  circuitBreakerOpen: boolean;
  cancelled: boolean;
  gateComplete: boolean;
  lastUpdatedAt: string;
  canResume: boolean;
};

export type ChallengeCupRealBatchOutcome = {
  questionId: string;
  outcome: string;
};

export type ChallengeCupRealBatchAuthorization = {
  authorizationId: string;
  teamId: string;
  planId: string;
  batchScope: Record<string, unknown>;
  scopeHash: string;
  approvedBy: string;
  approvedAtMs: number;
  readinessReportSha256: string;
  recordHash: string;
  createdAtMs: number;
};

export type ChallengeCupRealBatchStartResponse = ChallengeCupRealBatchProjection & {
  launched: ChallengeCupRealBatchOutcome[];
};

export type ChallengeCupRealBatchPollResponse = ChallengeCupRealBatchProjection & {
  harvested: ChallengeCupRealBatchOutcome[];
  launched: ChallengeCupRealBatchOutcome[];
};

export type ChallengeCupRealBatchStartRequest = {
  confirmed: boolean;
  concurrency?: number | null;
  maxItems?: number | null;
  failureBudget?: number | null;
};

export type ChallengeCupRealBatchCancelRequest = {
  confirmed: boolean;
};

export type ChallengeCupCatalogOverviewStatus = "queued" | "running" | "succeeded" | "failed";

export type ChallengeCupCatalogOverviewAction = "continue" | "retry" | "view";

export type ChallengeCupCatalogOverviewBlocker = {
  code: string;
  message: string;
  remediationLabel: string;
};

export type ChallengeCupCatalogOverviewQuestion = {
  questionId: string;
  title: string;
  domain: string;
  status: ChallengeCupCatalogOverviewStatus;
  executionStatus: string;
  currentStage: string;
  checkpointProgress: string;
  attempts: number;
  planId: string;
  action: ChallengeCupCatalogOverviewAction;
  blocker: ChallengeCupCatalogOverviewBlocker | null;
};

export type ChallengeCupCatalogOverview = {
  schemaVersion: number;
  teamId: string;
  generatedAt: string;
  questionCount: number;
  counts: {
    queued: number;
    running: number;
    succeeded: number;
    failed: number;
  };
  questions: ChallengeCupCatalogOverviewQuestion[];
};

export type ChallengeCupTokenUsageStage = {
  stageId: string;
  totalTokens: number;
  callCount: number;
};

export type ChallengeCupTokenUsageAnomaly = {
  stageId: string;
  message: string;
};

export type ChallengeCupTokenUsageQuestion = {
  questionId: string;
  totalTokens: number;
  callCount: number;
  inputTokens: number;
  outputTokens: number;
  stages: ChallengeCupTokenUsageStage[];
  anomaly: ChallengeCupTokenUsageAnomaly | null;
};

export type ChallengeCupTokenUsage = {
  schemaVersion: number;
  teamId: string;
  generatedAt: string;
  unit: "tokens";
  priced: boolean;
  program: {
    totalTokens: number;
    callCount: number;
    inputTokens: number;
    outputTokens: number;
  };
  questions: ChallengeCupTokenUsageQuestion[];
};
