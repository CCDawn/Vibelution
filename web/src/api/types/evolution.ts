import type { ConversationMessage } from "./chat";

export type EvolutionActionState = {
  enabled: boolean;
  reason: string;
};

export type EvolutionOutcomeSemantics = {
  decision: string;
  decisionLabel: string;
  proposalStatus: string;
  proposalStatusLabel: string;
  runtimeEffect: string;
  runtimeEffectLabel: string;
  runtimeExplanation: string;
  isRuntimeApplied: boolean;
};

export type EvolutionWorkbenchStorage = {
  relativeWorkspaceRoot: string;
  relativeEvidenceRoot: string;
  formalWorkspaceRoot: string;
  formalEvidenceRoot: string;
  activeWorkspaceRoot: string;
  activeEvidenceRoot: string;
  formalEvidenceRootExists: boolean;
  activeEvidenceRootExists: boolean;
  usesExternalDataWorkspace: boolean;
};

export type SupervisedRunSemantics = {
  runStatus: string;
  runStatusLabel: string;
  stage: string;
  stageLabel: string;
  diagnosis: string;
  nextAction: string;
};

export type SelfEvolutionSceneSemantics = {
  sceneState: string;
  sceneTitle: string;
  sceneSummary: string;
  blockers: string[];
  nextAction: string;
};

export type SelfEvolutionRunSemantics = {
  runStatus: string;
  runStatusLabel: string;
  phase: string;
  phaseLabel: string;
  rollbackState: string;
  rollbackStateLabel: string;
  rollbackSummary: string;
};

export type EvolutionOverview = {
  intakeMode: string;
  currentStatus: {
    state: string;
    stage: string;
    lastResult: string;
    decision: string;
    proposalStatus: string;
    runtimeEffect: string;
    riskLevel: string;
    latestRunId: string;
    nextAction: string;
    activeAdvisoryCount: number;
    runSemantics: SupervisedRunSemantics;
    outcomeSemantics: EvolutionOutcomeSemantics;
    actionStates: Record<string, EvolutionActionState>;
  };
  recentRuns: Array<{
    id: string;
    score: number;
    status: string;
    summary: string;
    decision: string;
    proposalStatus: string;
    runtimeEffect: string;
  }>;
  recentLibrary: Array<{
    id: string;
    title: string;
    source: string;
    sourceRun: string;
  }>;
  workbench: {
    source: string;
    bundleName: string;
    datasetName: string;
    datasetLimit: number | null;
    keepWorktree: boolean | null;
    availableDatasets: number;
    runnableDatasets: number;
    blockedDatasets: number;
    storage?: EvolutionWorkbenchStorage;
  };
};

export type EvolutionRun = {
  id: string;
  score: number;
  status: string;
  summary: string;
  diagnosis: string;
  decision: string;
  endedAt: string;
  bundleName: string;
  baselineScore: number;
  candidateScore: number;
  deltaScore: number;
  riskLevel: string;
  riskReasons: string[];
  proposalStatus: string;
  runtimeEffect: string;
  agentConsumption: string;
  availableActions: string[];
  nextAction: string;
  sourceDecisionPath: string;
  sourceProposalPath: string;
  activeAdvisoryCount: number;
  caseDiagnostics: EvolutionCaseDiagnostic[];
  canDelete: boolean;
  deleteBlockReason: string;
  runSemantics: SupervisedRunSemantics;
  outcomeSemantics: EvolutionOutcomeSemantics;
  actionStates: Record<string, EvolutionActionState>;
};

export type EvolutionCaseDiagnostic = {
  caseId: string;
  caseType?: string;
  baselineStatus: string;
  candidateStatus: string;
  decisionSignal: string;
  summary: string;
  metrics: Record<string, unknown>;
  reasons: string[];
  expectedFinalState?: Record<string, unknown>;
  expectedInfeasibleOutcome?: Record<string, unknown>;
  dynamicEvents?: Array<Record<string, unknown>>;
  evaluationMetadata?: Record<string, unknown>;
  harnessSummaries?: Partial<Record<"baseline" | "candidate", EvolutionHarnessRunSummary>>;
};

export type EvolutionHarnessRunSummary = {
  caseId?: string;
  caseType?: string;
  role?: string;
  status?: string;
  reason?: string;
  scenario?: string;
  mode?: string;
  durationSeconds?: number | null;
  timeoutSeconds?: number | null;
  maxSteps?: number | null;
  validation?: {
    passed?: number;
    failed?: number;
    last_tool?: string;
  };
  transaction?: {
    opened?: boolean;
    closed?: boolean;
    status?: string;
  };
  restart?: {
    expected?: boolean;
    triggered?: boolean;
    reentered?: boolean;
  };
  guardedTools?: number;
  llmFailureDetected?: boolean;
  llmFailureCategory?: string;
  newLogs?: {
    conversation?: number;
    debug?: number;
  };
  process?: {
    raw_count?: number;
    normalized_reentered_agent_count?: number;
    duplicate_families?: string[];
  };
  agent?: {
    agentId?: string;
    displayName?: string;
    dialogueModelId?: string;
  };
};

export type EvolutionDatasetOption = {
  name: string;
  bundleName: string;
  available: boolean;
  runnable: boolean;
  effective: boolean;
  caseCount: number | null;
  usabilityStatus: string;
  usabilityReason: string;
  officialVerifierStatus?: string;
  evaluationMode?: string;
  scoreLabel?: string;
  officialScoreAvailable?: boolean;
  visibility: string;
  visibilityReason: string;
  selectable: boolean;
  noiseLevel: string;
  adapterStatus: string;
  description: string;
  sourcePath: string;
  sourceExists: boolean;
  tags: string[];
  benchmarkFamily?: string;
  taskType?: string;
  verifierKind?: string;
  scoreSemantics?: string;
  runBudgetClass?: string;
  defaultVisibility?: string;
  reviewRequired: boolean;
  sourceTrack: string;
  allowedDownstreamUses: string[];
  holdoutAllowed: boolean;
  rawChatDirectTrainingAllowed: boolean;
};

export type EvolutionActiveRunEvent = {
  timestamp: string;
  event: string;
  title: string;
  summary: string;
  status: string;
  caseId?: string;
  caseIndex?: number | null;
  caseTotal?: number | null;
  role?: string;
  scenario?: string;
  mode?: string;
  bundleName?: string;
  sessionId?: string;
  decision?: string;
  reason?: string;
  errorType?: string;
  elapsedSeconds?: number | null;
  resultStatus?: string;
  sourceKind?: string;
  datasetName?: string;
  datasetLimit?: number | null;
  keepWorktree?: boolean;
  mentalModelMode?: string;
  mentalModelEnabled?: boolean | null;
  agentBinding?: EvolutionActiveRunAgentBinding;
};

export type EvolutionActiveRunIoEntry = {
  timestamp: string;
  kind: string;
  label: string;
  content: string;
  status?: string;
};

export type EvolutionActiveRunCaseIo = {
  conversationPath: string;
  conversationSessionId?: string;
  conversationTurnId?: string;
  latestInput: string;
  latestOutput: string;
  latestOutputKind: string;
  latestOutputLabel: string;
  updatedAt: string;
  transcript: EvolutionActiveRunIoEntry[];
  conversationMessages?: ConversationMessage[];
};

export type EvolutionWorkflowStep = {
  id: "baseline_eval" | "baseline_judge" | "improve" | "rerun_eval" | "rerun_judge" | "approval" | string;
  label: string;
  ownerKind: "agent" | "human" | string;
  role: string | null;
  status: string;
  current: boolean;
  summary: string;
  livePreview: string;
  metrics: Record<string, unknown>;
  conversationSessionId: string;
  conversationTurnId?: string;
  chatRoute: string;
  conversationMessages?: ConversationMessage[];
};

export type EvolutionActiveRunAgentBinding = {
  agentId?: string;
  agentCode?: string;
  displayName?: string;
  primaryMode?: string;
  roleKey?: string;
  promptTemplateId?: string;
  directSessionId?: string;
  workspacePath?: string;
  toolPolicyId?: string;
  memoryPolicyId?: string;
  role?: string;
  roleLabel?: string;
  dialogueModelId?: string;
  dialogueModelLabel?: string;
  dialogueModelName?: string;
  llmBindings?: Record<string, { modelId?: string }>;
};

export type EvolutionRoleConversationSession = {
  role: string;
  status: string;
  agentId?: string;
  displayName?: string;
  roleLabel?: string;
  conversationPath?: string;
  conversationSessionId?: string;
  conversationTurnId?: string;
  caseId?: string;
  caseIndex?: number | null;
  caseTotal?: number | null;
  scenario?: string;
  mode?: string;
  latestMessage?: string;
  latestOutputKind?: string;
  latestOutputLabel?: string;
  updatedAt?: string;
};

export type EvolutionClosedLoopRoleSession = EvolutionRoleConversationSession;

export type EvolutionClosedLoopEvidence = {
  decisionPath: string;
  policyRecordPath: string;
  lineageIndexPath: string;
  proposalPaths: string[];
  touchedFiles: string[];
};

export type EvolutionClosedLoopCounts = {
  roleSessionCount: number;
  proposalCount: number;
  touchedFileCount: number;
  caseEvidenceCount: number;
};

export type EvolutionClosedLoopNextAction = {
  kind: string;
  label: string;
  description: string;
  action: string;
  enabled: boolean;
};

export type EvolutionClosedLoopRecord = {
  runId: string;
  sessionId: string;
  status: string;
  currentPhase: string;
  sourceKind: string;
  bundleName: string;
  datasetName: string;
  datasetLimit: number | null;
  startedAt: string;
  updatedAt: string;
  finishedAt: string;
  decision: string;
  reason: string;
  policyAction: string;
  policySummary: string;
  lineageSummary: string;
  recordStatus: string;
  roleSessions: Record<string, EvolutionClosedLoopRoleSession>;
  evidence: EvolutionClosedLoopEvidence;
  counts: EvolutionClosedLoopCounts;
  nextAction: EvolutionClosedLoopNextAction;
};

export type EvolutionCurrentAgentBindingIssue = {
  role?: string;
  agentId?: string;
  modelId?: string;
  reason?: string;
  message?: string;
};

export type EvolutionActiveRun = {
  runId: string;
  status: string;
  currentPhase: string;
  runtimeStatus: string;
  sourceKind: string;
  sessionId: string;
  bundleName: string;
  datasetName: string;
  datasetLimit: number | null;
  keepWorktree: boolean;
  mentalModelMode?: string;
  mentalModelEnabled?: boolean | null;
  retryOfRunId?: string;
  resumeFromDecisionPath?: string;
  startedAt: string;
  updatedAt: string;
  finishedAt: string;
  caseTotal: number;
  currentCaseIndex: number;
  currentCaseId: string;
  currentRole: string;
  currentCaseScenario: string;
  currentCaseMode: string;
  currentCasePrompt: string;
  currentAgentBinding: EvolutionActiveRunAgentBinding;
  currentCaseIo: EvolutionActiveRunCaseIo | null;
  roleConversationSessions?: Record<string, EvolutionRoleConversationSession>;
  workflowSteps?: EvolutionWorkflowStep[];
  closedLoopRecord?: EvolutionClosedLoopRecord | null;
  currentTask: string;
  decision: string;
  reason: string;
  decisionPath: string;
  policyAction: string;
  lineageIndexPath: string;
  lineageSummary: string;
  activeAdvisoryCount: number;
  pauseRequested: boolean;
  pauseRequestedAt: string;
  pausedAt: string;
  stopRequested: boolean;
  stopRequestedAt: string;
  latestMessage: string;
  eventTail: EvolutionActiveRunEvent[];
  agentBindings: Record<string, EvolutionActiveRunAgentBinding>;
  actionStates: Record<string, EvolutionActionState>;
};

export type EvolutionActiveRunStreamEvent = {
  type: "supervised_run";
  runId: string;
  snapshot: EvolutionActiveRun;
  terminal?: boolean;
};

export type EvolutionRunCommandAccepted = {
  accepted: true;
  commandId: string;
  commandType: string;
  runId?: string;
  status: "queued";
  summary: string;
  completed?: boolean;
};

export type EvolutionRunCommandStatus = {
  commandId: string;
  accepted: boolean;
  completed: boolean;
  ok: boolean | null;
  status: "pending" | "succeeded" | "failed";
  message: string;
  errorType: string;
  runId?: string;
  snapshot?: EvolutionActiveRun;
};

export type EvolutionRunStartResponse = EvolutionActiveRun | EvolutionRunCommandAccepted;

export type EvolutionRunDeleteResponse = {
  deleted?: boolean;
  runId?: string;
  clearedActive?: boolean;
  clearedLatest?: boolean;
  activeRunId?: string;
  latestRunId?: string;
  summary: string;
} | EvolutionRunCommandAccepted;

export type SupervisedWorktreeRun = {
  runId: string;
  runKind: string;
  status: string;
  phase: string;
  runtimeStatus: string;
  outcome: string;
  mode: string;
  executionMode: string;
  sourceKind: string;
  datasetName: string;
  datasetLimit: number | null;
  bundleName: string;
  keepWorktree: boolean;
  agentBindings?: Record<string, EvolutionActiveRunAgentBinding>;
  mentalModelMode?: string;
  mentalModelEnabled?: boolean | null;
  startRequest?: {
    requestSource?: string;
    uiRoute?: string;
    initiator?: string;
    clientAction?: string;
  };
  selfEvolutionOrigin?: {
    sourceTrack?: string;
    goal?: string;
    riskReason?: string;
    sourceSelfRunId?: string;
    sourceCandidateId?: string;
    requiresSupervisedReview?: boolean;
  };
  reviewGate?: {
    required?: boolean;
    status?: string;
    reason?: string;
    approvedAt?: string;
    reviewerNote?: string;
  };
  startedAt: string;
  updatedAt: string;
  finishedAt: string;
  latestMessage: string;
  workflowSteps?: EvolutionWorkflowStep[];
  costEstimate: {
    caseCount: number;
    evaluationCalls: number;
    judgeCalls?: number;
    selfEditCalls: number;
    modelCalls: number;
    estimatedInputTokens: number;
    estimatedOutputTokens: number;
    estimatedTotalTokens: number;
    note: string;
  };
  decision: {
    mode?: string;
    scoreSource?: string;
    judgeDecision?: string;
    baselineScore?: number;
    candidateScore?: number;
    scoreDelta?: number;
    recommendedAction?: string;
    reason?: string;
    highRisk?: boolean;
  };
  baselineConversationSessionId?: string;
  rerunConversationSessionId?: string;
  judgeConversationSessionId?: string;
  judgeMergeTrigger?: {
    status?: string;
    mergeRequested?: boolean;
    decision?: string;
    reason?: string;
    evidenceRefs?: string[];
    conversationSessionId?: string;
    force?: boolean;
    mechanism?: string;
    requestedAt?: string;
  };
  baselineJudgment?: {
    status?: string;
    phase?: string;
    decision?: string;
    score?: number;
    baselineScore?: number;
    problems?: string[];
    improvementInstructions?: string[];
    dimensions?: Record<string, number>;
    evidenceRefs?: string[];
    conversationSessionId?: string;
  };
  candidateJudgment?: {
    status?: string;
    phase?: string;
    decision?: string;
    score?: number;
    baselineScore?: number;
    problems?: string[];
    improvementInstructions?: string[];
    dimensions?: Record<string, number>;
    evidenceRefs?: string[];
    conversationSessionId?: string;
  };
  mergeAnalysis: {
    status?: string;
    mergeAllowed?: boolean;
    reason?: string;
    blockers?: string[];
    overlapFiles?: string[];
    highRiskFiles?: string[];
    reviewGate?: {
      required?: boolean;
      status?: string;
      reason?: string;
      approvedAt?: string;
      reviewerNote?: string;
    };
    changedFiles?: Array<{
      path: string;
      status: string;
      changeType: string;
      highRisk: boolean;
    }>;
  };
  merge?: {
    status?: string;
    mergedAt?: string;
    force?: boolean;
    triggeredBy?: {
      role?: string;
      conversationSessionId?: string;
      decision?: string;
      mechanism?: string;
    };
    changedFiles?: string[];
    rollbackManifestPath?: string;
  };
  rollback?: {
    status?: string;
    manifestPath?: string;
    rolledBackAt?: string;
    reason?: string;
  };
  actionStates: Record<string, EvolutionActionState>;
};

export type SupervisedWorktreeRunStreamEvent = {
  type: "supervised_worktree_run";
  runId: string;
  snapshot: SupervisedWorktreeRun;
  terminal?: boolean;
};

export type EvolutionWorkbench = {
  defaultBundleName: string;
  savedState: EvolutionOverview["workbench"];
  storage?: EvolutionWorkbenchStorage;
  bundles: Array<{
    name: string;
    declaredName: string;
    path: string;
    caseCount: number;
    benchmark: string;
  }>;
  datasets: EvolutionDatasetOption[];
  datasetCatalog: EvolutionDatasetOption[];
  activeRun: EvolutionActiveRun | null;
};

export type EvolutionChatReviewCandidate = {
  candidateId: string;
  status: string;
  sessionId: string;
  topicSummary: string;
  startTurn: number;
  endTurn: number;
  turnCount: number;
  qualitySignals: string[];
  sourceLogPath: string;
  rawExcerptPath: string;
  reviewerNote: string;
  reviewedAt: string;
  conversationTurns: Array<{
    turnNumber: number;
    userMessage: string;
    assistantMessage: string;
    toolCalls: string[];
  }>;
  reviewProfile: {
    suggestedDecision: string;
    suggestedReason: string;
    learningFocus: string;
    taskClarity: {
      level: string;
      note: string;
    };
    goalStability: {
      level: string;
      note: string;
    };
    assistantLearningValue: {
      level: string;
      note: string;
    };
    antiPatternRisk: {
      level: string;
      note: string;
    };
    positiveSignals: string[];
    negativeSignals: string[];
    evidenceTurnNumbers: number[];
  };
  reviewDecision: {
    reasonCode: string;
    errorType: string;
    correctPrinciple: string;
    idealBehavior: string;
  };
  structuredSample: {
    caseId: string;
    mode: string;
    scenario: string;
    trainingTier: string;
    promptSeed: string;
    promptPreview: string;
  };
};

export type EvolutionChatReviewQueue = {
  datasetName: string;
  bundleName: string;
  positiveDatasetName: string;
  positiveBundleName: string;
  positiveDatasetPath: string;
  positiveDatasetExists: boolean;
  negativeDatasetName: string;
  negativeBundleName: string;
  negativeDatasetPath: string;
  negativeDatasetExists: boolean;
  discardAuditPath: string;
  approvedDatasetPath: string;
  approvedDatasetExists: boolean;
  pendingCount: number;
  positiveCount: number;
  negativeCount: number;
  discardCount: number;
  countsByStatus: {
    pending: number;
    positive: number;
    negative: number;
    discard: number;
  };
  approvedCount: number;
  rejectedCount: number;
  lifecycle: {
    rawChatDirectTrainingAllowed: boolean;
    candidateStage: string;
    reviewedCaseStage: string;
    datasetTarget: string;
    negativeTarget: string;
    allowedDownstreamUses: string[];
  };
  items: EvolutionChatReviewCandidate[];
};

export type EvolutionChatReviewDecisionResponse = {
  candidateId: string;
  status: string;
  datasetName: string;
  bundleName: string;
  datasetPath: string;
  caseId: string;
  summary: string;
};

export type EvolutionChatReviewBulkDeleteResponse = {
  requestedCount: number;
  discardedCount: number;
  skippedCount: number;
  failedCount: number;
  summary: string;
  results: Array<{
    candidateId: string;
    status: string;
    reason: string;
  }>;
};

export type EvolutionLibraryEntry = {
  id: string;
  title: string;
  type: string;
  sourceRun: string;
  ingestMode?: string;
  proposalStatus: string;
  runtimeEffect: string;
  decision: string;
  targetKey: string;
  targetLabel: string;
  headline: string;
  changeSummary: string;
  summary: string;
  reason?: string;
  availableActions: string[];
  updatedAt: string;
  canDelete: boolean;
  deleteBlockReason: string;
  riskLevel?: string;
  candidateType?: string;
  reviewState?: string;
  supervisedRequired?: boolean;
  candidateOnly?: boolean;
  autoApply?: boolean;
  allowedDownstreamUses?: string[];
  blockedDownstreamUses?: string[];
  provenance?: Record<string, unknown>;
  evidenceRefs?: string[];
  sourceExperienceId?: string;
  sourceReflectionId?: string;
  sourceSelfRunId?: string;
  txnId?: string;
  payload?: Record<string, unknown>;
  outcomeSemantics: EvolutionOutcomeSemantics;
  actionStates: Record<string, EvolutionActionState>;
};

export type EvolutionLibraryPayload = {
  items: EvolutionLibraryEntry[];
  pending: EvolutionLibraryEntry[];
};

export type EvolutionWorkspaceSnapshot = {
  overview: EvolutionOverview;
  runs: EvolutionRun[];
  library: EvolutionLibraryPayload;
  workbench: EvolutionWorkbench;
  activeRun: EvolutionActiveRun | null;
  latestRun: EvolutionActiveRun | null;
  latestClosedLoopRecord: EvolutionClosedLoopRecord | null;
  currentAgentBindings: Record<string, EvolutionActiveRunAgentBinding>;
  currentAgentBindingSource?: string;
  currentAgentBindingStatus?: string;
  currentAgentBindingIssues?: EvolutionCurrentAgentBindingIssue[];
  worktreeActiveRun: SupervisedWorktreeRun | null;
  worktreeRuns: SupervisedWorktreeRun[];
  selfOverview: SelfEvolutionOverview;
  selfWorktreeActiveRun?: SupervisedWorktreeRun | null;
  selfWorktreeRuns?: SupervisedWorktreeRun[];
  selfObservationActiveRun?: SelfObservationRun | null;
  selfTransactions: SelfEvolutionTransaction[];
};

export type EvolutionRunActionResponse = {
  action: string;
  summary: string;
  run: EvolutionRun | null;
  lifecycle: {
    status: string;
    proposalId: string | null;
    targetKey: string | null;
    runtimeEffect: string;
    agentConsumption: string;
    availableActions: string[];
    note: string;
    error: string;
  };
};

export type EvolutionProposalDetail = {
  sessionId: string;
  sourceRun: string;
  title: string;
  type: string;
  updatedAt: string;
  decision: string;
  proposalStatus: string;
  runtimeEffect: string;
  targetKey: string;
  targetLabel: string;
  availableActions: string[];
  canDelete: boolean;
  deleteBlockReason: string;
  canEdit: boolean;
  editBlockReason: string;
  runSemantics: SupervisedRunSemantics;
  outcomeSemantics: EvolutionOutcomeSemantics;
  actionStates: Record<string, EvolutionActionState>;
  review: {
    headline: string;
    changeSummary: string;
    whatChanged: string[];
    whyCreated: string[];
    currentState: string[];
    nextAction: string;
    deleteImpact: string;
    canDelete: boolean;
    deleteBlockReason: string;
    evidenceNotes: string[];
  };
  supervised: {
    baselineScore: number;
    candidateScore: number;
    deltaScore: number;
    riskLevel: string;
    riskReasons: string[];
    decisionReason: string;
    activeAdvisoryCount: number;
    caseDiagnostics: EvolutionCaseDiagnostic[];
  };
  proposal: {
    proposalId: string | null;
    episodeId: string | null;
    candidateImprovementId: string | null;
    improvementType: string;
    expectedEffect: string;
    summary: string;
    candidatePrompt: string;
    baselinePrompt: string;
    editNote: string;
    editedAt: string;
    editedBy: string;
    targetLabel: string;
    target: Record<string, unknown> | null;
    payload: Record<string, unknown> | null;
    targetKey: string;
  };
  paths: {
    supervisedDecisionPath: string;
    gymProposalPath: string;
    gymDecisionPath: string;
    traceIndexPath: string;
    lineageIndexPath: string;
    selfEvolutionCandidatePath?: string;
  };
  rawProposal: Record<string, unknown> | null;
  rawGymDecision: Record<string, unknown> | null;
  rawSupervisedDecision: Record<string, unknown> | null;
};

export type EvolutionProposalUpdateResponse = {
  sessionId: string;
  updated: boolean;
  changedFields: string[];
  summary: string;
  proposal: EvolutionProposalDetail;
};

export type EvolutionProposalDeleteResponse = {
  sessionId: string;
  title: string;
  deleted: boolean;
  deletedPaths: string[];
  summary: string;
};

export type EvolutionProposalBulkDeleteResponse = {
  requestedCount: number;
  deletedCount: number;
  skippedCount: number;
  errorCount: number;
  summary: string;
  results: Array<{
    sessionId: string;
    status: string;
    summary: string;
    deletedPaths?: string[];
  }>;
};

export type SelfEvolutionTransaction = {
  txnId: string;
  openedAt: string;
  closedAt: string;
  baseRev: string;
  baseRevShort: string;
  status: string;
  summary: string;
  isOpen: boolean;
  goalPreview: string;
  durationSeconds: number | null;
  validationPassed: number;
  validationFailed: number;
  mutationsRecorded: number;
  mutationsBlocked: number;
  auditEventCount: number;
  lastAuditEvent: string;
};

export type SelfObservationRunEvent = {
  timestamp: string;
  event: string;
  status: string;
  message: string;
  conversationSessionId?: string;
  turnId?: string;
};

export type SelfObservationRun = {
  runId: string;
  runKind: "self_observation_run" | string;
  selfMode: "observation" | string;
  status: string;
  phase: string;
  runtimeStatus: string;
  goal: string;
  durationSeconds: number;
  allowedTools: string[];
  writeLeases: string[];
  worktreeCreated: boolean;
  conversationSessionId: string;
  startedAt: string;
  updatedAt: string;
  finishedAt: string;
  latestMessage: string;
  messages?: string[];
  report: string;
  boundaryViolation: string;
  eventTail?: SelfObservationRunEvent[];
  actionStates: Record<string, EvolutionActionState>;
};

export type SelfObservationRunStartRequest = {
  goal: string;
  durationSeconds: number;
  uiRoute?: string;
};

export type SelfObservationRunActionRequest = {
  action: "terminate" | "stop" | "cancel" | string;
};

export type SelfEvolutionHistoryDeleteResponse = {
  requestedCount: number;
  deletedGroupCount: number;
  deletedAuditCount: number;
  summary: string;
  deletedTxnIds: string[];
  blockedTxnIds: string[];
};

export type SelfEvolutionAuditEvent = {
  timestamp: string;
  event: string;
  txnId: string;
  status: string;
  kind: string;
  message: string;
  toolName: string;
  baseRev: string;
  passed: boolean | null;
  targetPaths: string[];
  summary: string;
};

export type SelfEvolutionOverview = {
  enabled: boolean;
  goal: string;
  readiness: {
    state: string;
    title: string;
    summary: string;
    nextAction: string;
    reasons: string[];
  };
  sceneSemantics: SelfEvolutionSceneSemantics;
  runSemantics: SelfEvolutionRunSemantics;
  actionStates: Record<string, EvolutionActionState>;
  guardrails: string[];
  metrics: {
    activeAdvisories: number;
    dirtyFiles: number;
    recentTransactions: number;
    successRate: number | null;
    validationPassRate: number | null;
  };
  advisory: {
    activeCount: number;
    entries: Array<{
      targetKey: string;
      targetLabel: string;
      proposalId: string;
      episodeId: string;
      candidateImprovementId: string;
      activatedAt: string;
      runtimeEffect: string;
      agentConsumption: string;
      proposalPath: string;
      decisionPath: string;
      traceIndexPath: string;
    }>;
  };
  gitStatus: {
    summary: string;
    lines: string[];
  };
  recentChanges: Array<{
    path: string;
    changeType: string;
    summary: string;
  }>;
  fitness: {
    transactions: {
      opened: number;
      closed: number;
      successful: number;
      failed: number;
      successRate: number | null;
      recent: Array<{
        txnId: string;
        status: string;
        validationPassed: number;
        validationFailed: number;
        mutationsRecorded: number;
      }>;
    };
    validation: {
      passed: number;
      failed: number;
      passRate: number | null;
    };
    mutations: {
      recorded: number;
      successful: number;
      failed: number;
      blocked: number;
    };
  };
  worktree: {
    available: boolean;
    error: string;
    snapshotId: string;
    createdAt: string;
    baseRev: string;
    hasStaged: boolean;
    hasUnstaged: boolean;
    hasUntracked: boolean;
    isDirty: boolean;
    dirtyFileCount: number;
    files: Array<{
      path: string;
      status: string;
      staged: boolean;
      unstaged: boolean;
      untracked: boolean;
      deleted: boolean;
    }>;
  };
  recentTransactions: SelfEvolutionTransaction[];
  auditTail: SelfEvolutionAuditEvent[];
};
