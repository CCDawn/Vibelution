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
