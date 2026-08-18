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
