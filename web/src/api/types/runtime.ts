import type { DomainAvailability, FileContent, FileTreeNode, ModeAvailability, ProjectionEditContract, ProjectionSourceRef, SourceAuthorityRef } from "./shared";
import type { ResetExecuteResponse, ResetPreviewResponse, ResetSummary } from "./config";

export type LogRoot = {
  id: string;
  path: string;
  exists: boolean;
  summary: {
    health: string;
    fileCount: number;
    directoryCount: number;
    sizeBytes: number;
    lastModifiedAt: string;
    latestPath: string;
    userGuide: string;
    agentGuide: string;
  };
};

export type LogDiagnostics = {
  severity: "error" | "warning" | "info" | string;
  lineCount: number;
  nonEmptyLineCount: number;
  errorCount: number;
  warningCount: number;
  ignoredSignalCount?: number;
  firstSignalLine: number | null;
  firstSignalPreview: string;
  lastSignalLine: number | null;
  lastSignalPreview: string;
  structuredEventCount: number;
  topEventTypes: Array<{
    type: string;
    count: number;
  }>;
  userSummary: string;
  agentHint: string;
  suggestedNextStep: string;
};

export type HealthDiagnostics = {
  status: "ok" | "warning" | "blocked" | string;
  summary: string;
  counts: {
    ok: number;
    warning: number;
    blocked: number;
  };
  findings: HealthFinding[];
  quickActions: HealthQuickAction[];
  sessionHelpers: SessionHelper[];
  logHelpers: LogHelper[];
};

export type HealthFindingEvidence = {
  label: string;
  value: string;
};

export type HealthFinding = {
  id: string;
  severity: "blocked" | "warning" | "info" | string;
  source: "session" | "logs" | "reset" | string;
  helperId: string;
  title: string;
  summary: string;
  evidence: HealthFindingEvidence[];
  recommendedAction: string;
  route: string;
  resetItemId: string;
  protected: boolean;
};

export type HealthQuickAction = {
  id: string;
  title: string;
  description: string;
  route: string;
  source: string;
  severity: "blocked" | "warning" | "info" | string;
  findingId: string;
  resetItemId: string;
  protected: boolean;
};

export type SessionHelper = {
  id: string;
  title: string;
  description: string;
  status: "ok" | "warning" | "blocked" | string;
  statusLabel: string;
  sessionCount: number;
  busyCount: number;
  failedCount: number;
  staleCount: number;
  activeSessionId: string;
  activeTitle: string;
  currentPhase: string;
  updatedAt: string;
  latestSignal: string;
  recommendedAction: string;
  route: string;
  protected: boolean;
  protectedReason: string;
  findingIds: string[];
  primaryFindingId: string;
};

export type LogHelper = {
  id: string;
  title: string;
  description: string;
  rootPath: string;
  exists: boolean;
  status: "ok" | "warning" | "blocked" | string;
  statusLabel: string;
  fileCount: number;
  directoryCount: number;
  sizeBytes: number;
  lastModifiedAt: string;
  latestPath: string;
  latestSignal: string;
  userGuide: string;
  agentGuide: string;
  recommendedAction: string;
  route: string;
  resetItemId: string;
  protected: boolean;
  protectedReason: string;
  findingIds: string[];
  primaryFindingId: string;
};

export type RuntimeSceneListItem = {
  runtimeSceneId: string;
  directoryName: string;
  title: string;
  displayName: string;
  packageIndex: RuntimeScenePackageIndex;
  startedAt: string;
  endedAt: string;
  status: string;
  result: string;
  stopReason: string;
  trigger: string;
  sessionMode: string;
  backendStatus: string;
  frontendStatus: string;
  browserStatus: string;
  eventCount: number;
  rawLogCount: number;
  conversationCount: number;
  agentLogCount: number;
  artifactCount: number;
  eventLogCount: number;
  researchLogCount: number;
  errorCount: number;
  warningCount: number;
  diagnosisSummary?: RuntimeSceneDiagnosisSummary;
};

export type RuntimeSceneEvent = {
  runtimeSceneId: string;
  component: string;
  phase: string;
  eventCode: string;
  level: string;
  message: string;
  timestamp: string;
  seq: number;
  outcome: string;
  fields: Record<string, unknown>;
  rawRefs: Array<{
    path: string;
    tail_lines?: number;
  }>;
};

export type RuntimeSceneRawFile = {
  path: string;
  label: string;
  size: number;
  language: string;
  updatedAt?: string;
};

export type RuntimeScenePackageSummary = {
  schemaVersion: number;
  eventCount: number;
  lifecycleEventCount: number;
  rawLogCount: number;
  conversationLogCount: number;
  agentLogCount: number;
  artifactCount: number;
  eventLogCount: number;
  researchLogCount: number;
  errorCount: number;
  warningCount: number;
};

export type RuntimeSceneIssueSignal = {
  severity: "error" | "warning" | "info" | string;
  timestamp: string;
  component: string;
  phase: string;
  eventCode: string;
  message: string;
  rawRefs: Array<{
    path: string;
    tail_lines?: number;
  }>;
};

export type RuntimeSceneIssueCluster = {
  schemaVersion: number;
  severity: "error" | "warning" | "info" | string;
  component: string;
  phase: string;
  eventCode: string;
  label: string;
  repeatCount: number;
  firstTimestamp: string;
  lastTimestamp: string;
  representativeSignal?: RuntimeSceneIssueSignal & Record<string, unknown>;
  rawRefs: Array<{
    path: string;
    tail_lines?: number;
  }>;
  identity?: Record<string, string>;
};

export type RuntimeSceneWorkRunItem = {
  runKind: string;
  runId: string;
  snapshotCount: number;
  latestAt: string;
  latestStatus: string;
  latestPhase: string;
  activeRunId: string;
  runtimeStatus: string;
  snapshotPath: string;
  statusCounts: Record<string, number>;
};

export type RuntimeSceneWorkRunSummary = {
  schemaVersion: number;
  eventsPath: string;
  workRunEventCount: number;
  snapshotEventCount: number;
  runCount: number;
  activeRunCount: number;
  highFrequencyRunCount: number;
  latestRuns: RuntimeSceneWorkRunItem[];
  activeRuns: RuntimeSceneWorkRunItem[];
  highFrequencyRuns: RuntimeSceneWorkRunItem[];
};

export type RuntimeScenePackageDiagnosis = {
  schemaVersion: number;
  severity: "error" | "warning" | "info" | string;
  userSummary: string;
  agentNextStep: string;
  issueState?: {
    schemaVersion: number;
    severity: "error" | "warning" | "info" | string;
    activeErrorCount: number;
    activeWarningCount: number;
    policySignalCount?: number;
    historicalErrorCount: number;
    historicalWarningCount: number;
    activeClusterCount?: number;
    policyClusterCount?: number;
    historicalClusterCount?: number;
    controlSignalCount: number;
    activeClusters?: RuntimeSceneIssueCluster[];
    policyClusters?: RuntimeSceneIssueCluster[];
    historicalClusters?: RuntimeSceneIssueCluster[];
    firstActiveCluster?: RuntimeSceneIssueCluster | null;
    firstPolicyCluster?: RuntimeSceneIssueCluster | null;
    firstHistoricalCluster?: RuntimeSceneIssueCluster | null;
  };
  firstSignal: RuntimeSceneIssueSignal | null;
  startupTrace?: {
    schemaVersion: number;
    summary: string;
    missingStepIds: string[];
    steps: Array<{
      id: string;
      label: string;
      status: "recorded" | "missing" | string;
      timestamp: string;
      eventCode: string;
      message: string;
      evidencePath: string;
    }>;
  };
  workRunSummary?: RuntimeSceneWorkRunSummary;
  recommendedOrder: string[];
  evidencePaths?: string[];
  keyEntries: Array<{
    path: string;
    label: string;
    reason: string;
  }>;
};

export type RuntimeScenePackageIndex = {
  schemaVersion: number;
  packageId: string;
  displayName: string;
  indexKey: string;
  sortableTimestamp: string;
  startedAt: string;
  startedAtLocal: string;
  startedDate: string;
  startedTime: string;
  endedAt: string;
  durationSeconds: number | null;
  searchText: string;
  tags: string[];
  summaryRef: string;
};

export type RuntimeSceneDiagnosisSummary = {
  status: string;
  severity: "error" | "warning" | "info" | string;
  primaryIssue: string;
  needsAction: boolean;
  activeClusterCount: number;
  activeErrorCount: number;
  activeWarningCount: number;
  policyClusterCount: number;
  policySignalCount: number;
  historicalClusterCount: number;
  historicalErrorCount: number;
  historicalWarningCount: number;
  controlSignalCount: number;
};

export type RuntimeSceneDetail = {
  runtimeSceneId: string;
  directoryName: string;
  displayName: string;
  packageIndex: RuntimeScenePackageIndex;
  manifestPath: string;
  manifest: Record<string, unknown>;
  startedAt: string;
  endedAt: string;
  status: string;
  result: string;
  stopReason: string;
  trigger: string;
  sessionMode: string;
  host: string;
  port: number;
  url: string;
  frontend: Record<string, unknown>;
  backend: Record<string, unknown>;
  browser: Record<string, unknown>;
  supervisor: Record<string, unknown>;
  timeline: RuntimeSceneEvent[];
  lifecycle: RuntimeSceneEvent[];
  rawFiles: RuntimeSceneRawFile[];
  conversationLogs: RuntimeSceneRawFile[];
  agentLogs: RuntimeSceneRawFile[];
  artifacts: RuntimeSceneRawFile[];
  eventLogs: RuntimeSceneRawFile[];
  researchLogs: RuntimeSceneRawFile[];
  packageSummary: RuntimeScenePackageSummary;
  packageDiagnosis: RuntimeScenePackageDiagnosis;
  diagnosisSummary?: RuntimeSceneDiagnosisSummary;
};

export type RuntimeSceneDeleteResponse = {
  requestedCount: number;
  deletedCount: number;
  missingCount: number;
  deletedSceneIds: string[];
  missingSceneIds: string[];
  summary: string;
};

export type GitStatusFile = {
  path: string;
  status: string;
  statusLabel: string;
  staged: boolean;
  unstaged: boolean;
  untracked: boolean;
  deleted: boolean;
  oldPath: string;
};

export type GitStatusSummary = {
  available: boolean;
  error: string;
  branch: string;
  headRev: string;
  headRevShort: string;
  upstream: {
    name: string;
    remote: string;
    ahead: number;
    behind: number;
    hasUpstream: boolean;
  };
  snapshotId: string;
  createdAt: string;
  dirty: boolean;
  requiresAttention: boolean;
  statusLevel: "clean" | "dirty" | "local_commits" | "worktree_commits" | "behind" | "diverged" | "unavailable";
  summary: string;
  counts: {
    total: number;
    staged: number;
    unstaged: number;
    untracked: number;
    deleted: number;
  };
  localCommits: {
    available: boolean;
    error: string;
    total: number;
    commits: GitCommitSummary[];
    truncated: boolean;
  };
  worktrees: {
    available: boolean;
    error: string;
    total: number;
    external: number;
    withCommits: number;
    items: Array<{
      path: string;
      branch: string;
      branchRef: string;
      headRev: string;
      headRevShort: string;
      isMain: boolean;
      isCurrent: boolean;
      aheadMain: number;
      behindMain: number;
      hasCommits: boolean;
    }>;
    truncated: boolean;
  };
  files: GitStatusFile[];
  totalFiles: number;
  truncated: boolean;
};

export type GitCommitSummary = {
  sha: string;
  shortSha: string;
  author: string;
  authoredAt: string;
  subject: string;
};

export type GitCommitsResponse = {
  available: boolean;
  error: string;
  commits: GitCommitSummary[];
};

export type GitFileDiff = {
  available: boolean;
  error: string;
  path: string;
  status: string;
  statusLabel: string;
  summary: string;
  diff: string;
  content: string;
  language: string;
  truncated: boolean;
  binary: boolean;
};

export type GitObjectDetail = GitFileDiff & {
  kind: "commit" | "branch" | "worktree" | string;
  ref: string;
  meta: Record<string, unknown>;
};

export type GitCommitMessageResponse = {
  message: string;
  modelId: string;
  prompt: string;
  files: string[];
  diffSummary: string;
};

export type GitCommitResponse = {
  committed: boolean;
  commitSha: string;
  shortSha: string;
  summary: string;
  files: string[];
};

export type LogTreeResponse = {
  root: LogRoot;
  nodes: FileTreeNode[];
};

export type LogFileContent = FileContent & {
  rootId: string;
  rootPath: string;
  relativePath: string;
  diagnostics: LogDiagnostics;
};

export type LogDeleteResponse = {
  rootId: string;
  rootPath: string;
  deletedPaths: string[];
  missingPaths: string[];
  deletedCount: number;
};

export type WorkRunSnapshot = {
  runId: string;
  runKind: "chat_turn" | "self_evolution_run" | "supervised_evolution_run" | string;
  status: string;
  leases: string[];
  sessionId?: string;
  track?: string;
  currentPhase?: string;
  summary?: string;
  startedAt?: string;
  updatedAt?: string;
  finishedAt?: string;
  [key: string]: unknown;
};

export type WorkRunSummary = {
  active: {
    chat_turn: WorkRunSnapshot | null;
    chat_room_round: WorkRunSnapshot | null;
    self_evolution_run: WorkRunSnapshot | null;
    supervised_evolution_run: WorkRunSnapshot | null;
    supervised_worktree_evolution_run: WorkRunSnapshot | null;
  };
  activeItems?: {
    chat_turn?: WorkRunSnapshot[];
    chat_room_round?: WorkRunSnapshot[];
    self_evolution_run?: WorkRunSnapshot[];
    supervised_evolution_run?: WorkRunSnapshot[];
    supervised_worktree_evolution_run?: WorkRunSnapshot[];
    [key: string]: WorkRunSnapshot[] | undefined;
  };
  latest: {
    chat_turn: WorkRunSnapshot | null;
    chat_room_round: WorkRunSnapshot | null;
    self_evolution_run: WorkRunSnapshot | null;
    supervised_evolution_run: WorkRunSnapshot | null;
    supervised_worktree_evolution_run: WorkRunSnapshot | null;
  };
};

export type RuntimeLifecycleProofComponent = {
  id: string;
  label: string;
  state: "verified" | "missing" | "closing" | "failed" | "unknown" | "running" | string;
  ok: boolean;
  requiredForOpen: boolean;
  requiredForClosed: boolean;
  detail: string;
  pid: number;
  verifiedAt: string;
};

export type RuntimeLifecycleProof = {
  overallState: "ready" | "starting" | "closing" | "closed" | "partial" | "failed" | string;
  overallLabel: string;
  summary: string;
  verifiedAt: string;
  desiredState: string;
  observedState: string;
  phase: string;
  browserManaged: boolean;
  projectRootMatches: boolean;
  components: RuntimeLifecycleProofComponent[];
  activeWorkRuns: {
    count: number;
    kinds: string[];
    items: Array<{
      kind: string;
      runId: string;
      status: string;
    }>;
  };
  residualProcesses: {
    count: number;
    items: Array<{
      pid: number;
      parentPid: number;
      kind: string;
      name: string;
      commandLine: string;
      cwd: string;
      port: number;
    }>;
  };
};

export type WindowProvider = "none" | "edge_app" | "electron";

export type RuntimeSummary = {
  status: string;
  mode: string;
  model: string;
  profile: string;
  modelSource?: string;
  profileSource?: string;
  modelId?: string;
  modelAgentId?: string;
  defaultRoute: string;
  intakeMode: string;
  modeAvailability: ModeAvailability;
  domainAvailability: DomainAvailability;
  agentName: string;
  userName: string;
  userProfile?: {
    displayName: string;
    bio: string;
    preferences: string[];
    avatarPreset: string;
    avatarImageUrl: string;
  };
  agentStatusLine: string;
  sessionTitle: string;
  taskSummary: string;
  currentPhase: string;
  sessionState: string;
  sessionStateLine: string;
  sessionNeedsResponse: boolean;
  sessionToolName: string;
  sessionUpdatedAt: string;
  mentalState: {
    mood: string;
    feeling: string;
    whisper: string;
    summary: string;
    cognitiveState: string;
    confidence: number;
    sampleSize: number;
    interventionCount: number;
    updatedAt: string;
    source: string;
  };
  contextUsage: { used: number; limit: number };
  contextCompression: {
    enabled: boolean;
    source?: "runtime_state" | string;
    policyMode?: "inherit" | "custom" | string;
    policySource?: "global" | "agent_custom" | string;
    policyAgentId?: string;
    scope?: "runtime_prompt_estimate" | string;
    tokenBasis?: "current_context_tokens" | string;
    limitBasis?: "effective_token_limit" | string;
    currentTokens: number;
    effectiveTokenLimit: number;
    contextWindowLimit: number;
    usageRatio: number;
    currentLevel: string;
    compressionCount: number;
    lastCompression: null | {
      level: string;
      reason: string;
      triggerSource: "manual" | "auto" | "provider_limit" | string;
      beforeTokens: number;
      afterTokens: number;
      savedTokens: number;
      iteration: number;
      summaryWritten: boolean;
      timestamp: string;
    };
    strategy: {
      levels: Array<{
        level: string;
        thresholdRatio: number;
        thresholdTokens: number;
        keepAiMessages: number;
        summaryMaxChars: number;
      }>;
      preserveErrors: boolean;
      errorProtectionKeywords: string[];
      summaryStorage: string;
      algorithm: string;
    };
    updatedAt: string;
  };
  activeTools: string[];
  changedFilesCount: number;
  recentAction: string;
  runtimeManager: {
    running: boolean;
    runtimeState: string;
    managerPid: number;
    stateVersion: number;
  };
  workbench: {
    desiredState: string;
    observedState: string;
    phase: string;
    backendPid: number;
    browserWindowPid: number;
    windowManaged: boolean;
    windowProvider: WindowProvider;
    windowId: number;
    rendererProcessId: number;
    windowProfileDir: string;
    backendAlive: boolean;
    backendHealthy: boolean;
    backendObserved: boolean;
    backendPort: number;
    backendPortListening: boolean;
    backendPortOwnerPid: number;
    backendPortOwnerTrusted: boolean;
    backendPortConflict: boolean;
    browserWindowAlive: boolean;
    browserManaged: boolean;
    backendMissing: boolean;
    frontendOrphaned: boolean;
    lifecycleConsistency: string;
    url: string;
    lastReason: string;
    statusLine: string;
    failureMessage: string;
  };
  workRuns: WorkRunSummary;
  lifecycleProof: RuntimeLifecycleProof;
};

export type BackendHealth = {
  status: string;
};

export type RuntimeControlResponse = {
  accepted: boolean;
  mode: string;
  commandId?: string;
  queued?: boolean;
  pendingRestart?: boolean;
  activeWorkCount?: number;
  activeWorkRuns?: Array<{
    kind?: string;
    runId?: string;
    sessionId?: string;
    status?: string;
  }>;
  message: string;
  chatTurns: Array<{
    sessionId: string;
    runId: string;
    status: string;
    error?: string;
  }>;
  evolutionRuns: Array<{
    kind: string;
    runId: string;
    status: string;
    error?: string;
  }>;
};

export type RuntimeControlBlockedDetail = {
  code?: string;
  message?: string;
  activeWorkRuns?: Array<{
    kind?: string;
    runId?: string;
    sessionId?: string;
    status?: string;
  }>;
};

export type ShutdownResponse = RuntimeControlResponse;

export type RuntimeRestartResponse = RuntimeControlResponse;

export type LauncherOperation = "start" | "stop" | "restart" | "force-stop";

export type RuntimeLifecycleCancelOperation = "restart" | "stop" | "close" | "shutdown";

export type RuntimeLifecycleCancelRequest = {
  commandId?: string;
  operation?: RuntimeLifecycleCancelOperation | "";
  source?: string;
};

export type RuntimeLifecycleCancelResponse = {
  cancelled: boolean;
  status: "cancelled" | "not_found" | "already_active" | "invalid_request" | string;
  commandId: string;
  operation: RuntimeLifecycleCancelOperation | "";
  message: string;
  stateVersion?: number;
};

export type WorkbenchWindowMode = "fullscreen" | "windowed";

export type WorkbenchWindowModeSetting = {
  mode: WorkbenchWindowMode;
  effectiveMode: WorkbenchWindowMode;
  envOverride: WorkbenchWindowMode | "";
  configPath: string;
  configHash: string;
  restartRequired: boolean;
  options: Array<{
    mode: WorkbenchWindowMode;
    label: {
      zh: string;
      en: string;
    };
    detail: {
      zh: string;
      en: string;
    };
  }>;
};

export type WorkbenchWindowModeUpdateRequest = {
  mode: WorkbenchWindowMode;
  baseHash: string;
};

export type LauncherDeveloperModeSetting = {
  schemaVersion: number;
  enabled: boolean;
  defaulted: boolean;
  updatedAt: string;
  updatedBy: string;
  controller: "launcher" | string;
  scope?: "global" | string;
  mode?: "ephemeral_sandbox" | string;
  configPath: string;
  configHash: string;
  sandbox?: {
    sandboxId: string;
    root: string;
    statePath: string;
    active: boolean;
    createdAt: string;
    persistedAcrossRestarts: boolean;
    clearOnDisable: boolean;
    clearOnReset: boolean;
  };
  policy: {
    settingsPageMutable: boolean;
    requiresLauncher: boolean;
    requiresPreview: boolean;
    requiresPlanHash: boolean;
    requiresConfirm: boolean;
    defaultWhenMissing: boolean;
    scope?: "global" | string;
    noTrace?: boolean;
    readsFormalState?: boolean;
    writesSandboxedState?: boolean;
    logsDiagnosticRecords?: boolean;
    debugRecordKind?: string;
    debugRetention?: string;
    sandboxSurvivesRestart?: boolean;
  };
};

export type LauncherDeveloperModeUpdateRequest = {
  enabled: boolean;
  baseHash: string;
};

export type LauncherDeveloperModeUpdateResponse = {
  ok: boolean;
  setting: LauncherDeveloperModeSetting;
  message: string;
};

export type LauncherDeveloperCleanupAction = "quick_clean" | "db_compact" | "worktree_cleanup";

export type LauncherDeveloperNoiseItem = {
  id: string;
  label: string;
  path: string;
  exists: boolean;
  sizeBytes: number;
  targetCount: number;
  skippedCount?: number;
  action: LauncherDeveloperCleanupAction | "manual_review" | string;
  protected: boolean;
  reason: string;
};

export type LauncherDeveloperNoiseOverview = {
  schemaVersion: number;
  developerMode: LauncherDeveloperModeSetting;
  projectRoot: string;
  items: LauncherDeveloperNoiseItem[];
  updatedAt: string;
};

export type LauncherDeveloperCleanupTarget = {
  path: string;
  relativePath: string;
  kind: "file" | "directory" | "missing" | string;
  operation: string;
  sizeBytes: number;
  mtimeNs: number;
  branch?: string;
  head?: string;
  dbStats?: Record<string, unknown>;
  beforeSizeBytes?: number;
  afterSizeBytes?: number;
};

export type LauncherDeveloperCleanupPlan = {
  schemaVersion: number;
  planId: string;
  planHash: string;
  action: LauncherDeveloperCleanupAction;
  createdAt: string;
  expiresAt: string;
  projectRoot: string;
  targetCount: number;
  estimatedBytes: number;
  targets: LauncherDeveloperCleanupTarget[];
  skipped: Array<Record<string, string>>;
  requiresConfirm: boolean;
  applyContract: {
    requiresDeveloperMode: boolean;
    requiresPlanId: boolean;
    requiresPlanHash: boolean;
    requiresConfirm: boolean;
  };
};

export type LauncherDeveloperCleanupPreviewResponse = {
  ok: boolean;
  mode: "preview" | string;
  developerMode: LauncherDeveloperModeSetting;
  plan: LauncherDeveloperCleanupPlan;
  message: string;
};

export type LauncherDeveloperCleanupApplyRequest = {
  action: LauncherDeveloperCleanupAction;
  planId: string;
  planHash: string;
  confirm: boolean;
};

export type LauncherDeveloperCleanupApplyResponse = {
  ok: boolean;
  mode: "apply" | string;
  developerMode: LauncherDeveloperModeSetting;
  planId: string;
  planHash: string;
  action: LauncherDeveloperCleanupAction;
  applied: LauncherDeveloperCleanupTarget[];
  reclaimedBytes: number;
  message: string;
};

export type LauncherMaintenanceProfileId = "custom" | "clean_start" | "factory_runtime";

export type LauncherMaintenanceSummary = ResetSummary & {
  executionOwner: "launcher" | string;
  profiles: Array<{
    id: LauncherMaintenanceProfileId | string;
    label: string;
    description: string;
    itemIds: string[];
  }>;
  applyContract: {
    requiresLauncher: boolean;
    requiresPlanId: boolean;
    requiresPlanHash: boolean;
    requiresProfileId: boolean;
    requiresConfirm: boolean;
    blocksActiveWork: boolean;
    retiredWebApi: boolean;
  };
};

export type LauncherMaintenancePreviewRequest = {
  profileId: LauncherMaintenanceProfileId | string;
  itemIds?: string[];
};

export type LauncherMaintenancePlan = {
  schemaVersion: number;
  planId: string;
  planHash: string;
  profileId: LauncherMaintenanceProfileId | string;
  createdAt: string;
  expiresAt: string;
  projectRoot: string;
  selectedItemIds: string[];
  targetCount: number;
  estimatedBytes: number;
  requiresConfirm: boolean;
  blocksActiveWork: boolean;
  preview: ResetPreviewResponse;
};

export type LauncherMaintenancePreviewResponse = {
  ok: boolean;
  mode: "preview" | string;
  plan: LauncherMaintenancePlan;
  preview: ResetPreviewResponse;
  message: string;
};

export type LauncherMaintenanceApplyRequest = {
  planId: string;
  planHash: string;
  profileId: LauncherMaintenanceProfileId | string;
  confirm: boolean;
};

export type LauncherMaintenanceApplyResponse = {
  ok: boolean;
  mode: "apply" | string;
  planId: string;
  planHash: string;
  profileId: LauncherMaintenanceProfileId | string;
  result: ResetExecuteResponse;
  frontendInvalidation: {
    clearChatWorkspace: boolean;
    clearSessionUrl: boolean;
    invalidate: string[];
  };
  message: string;
};

export type LauncherStartupSettings = {
  runtime: {
    profile: string;
    preflightDoctor: boolean;
    requireVenv: boolean;
    profileOptions: string[];
  };
  workbench: {
    backendPort: number;
    frontendPort: number;
    effectiveBackendPort: number;
    effectiveFrontendPort: number;
    backendPortEnvOverride: number;
    frontendPortEnvOverride: number;
    windowMode: WorkbenchWindowMode;
    effectiveWindowMode: WorkbenchWindowMode;
    windowModeEnvOverride: WorkbenchWindowMode | "";
    windowModeOptions: WorkbenchWindowModeSetting["options"];
  };
  interface: {
    language: "zh" | "en" | string;
    languageOptions: Array<"zh" | "en" | string>;
  };
  configPath: string;
  configHash: string;
  restartRequired: boolean;
};

export type LauncherComponentState = {
  id: "backend" | "frontend" | "browser" | string;
  ok: boolean;
  state: string;
  requiredForRunning: boolean;
  pid: number;
  detail: string;
};

export type LauncherRequestAudit = {
  operation?: string;
  trigger?: string;
  endpoint?: string;
  method?: string;
  clientHost?: string;
  refererPath?: string;
  originHost?: string;
  userAgent?: string;
};

export type LauncherProjectBundleState = {
  schemaVersion: number;
  id: string;
  mode: "bundled" | string;
  desiredState: string;
  observedState: string;
  phase: string;
  overallState: string;
  lifecycleConsistency?: string;
  statusLine: string;
  url: string;
  lastReason: string;
  failureMessage: string;
  lastOperation: {
    reason: string;
    source: string;
    transitionAt: string;
    requestAudit?: LauncherRequestAudit;
  };
  components: LauncherComponentState[];
  backend: {
    pid: number;
    alive: boolean;
    healthy: boolean;
    port: number;
    portListening: boolean;
    portOwnerPid: number;
    portConflict: boolean;
  };
  frontend: {
    mode: "bundled_static_dist" | string;
    distReady: boolean;
    orphaned: boolean;
  };
  browser: {
    managed: boolean;
    windowPid: number;
    alive: boolean;
  };
};

export type LauncherStatus = {
  launcher: {
    mode: string;
    phase: string;
    stableControlPlane: boolean;
    controlPlane: {
      independent: boolean;
      adapter: string;
      nextPhase: string;
      url?: string;
      port?: number;
    };
    message: string;
  };
  projectBundle: LauncherProjectBundleState;
  runtimeManager: RuntimeSummary["runtimeManager"];
  lifecycleProof: RuntimeLifecycleProof;
  settings?: {
    startup?: LauncherStartupSettings;
    workbenchWindow?: WorkbenchWindowModeSetting;
    developerMode?: LauncherDeveloperModeSetting;
  };
};

export type LauncherControlResponse = RuntimeControlResponse & {
  launcherMode: string;
  operation: LauncherOperation;
};

export type WorkbenchWindowModeUpdateResponse = {
  ok: boolean;
  mode: WorkbenchWindowMode;
  setting: WorkbenchWindowModeSetting;
  message: string;
};

export type LauncherStartupSettingsUpdateResponse = {
  ok: boolean;
  setting: LauncherStartupSettings;
  message: string;
};

export type KernelTask = {
  taskId: string;
  creatorEventId: string;
  idempotencyKey: string;
  goal: string;
  assignedAgentIds: string[];
  status: string;
  workRunId: string;
  outcomeId: string;
  evidenceRefs: Array<Record<string, unknown>>;
  createdAt: string;
  updatedAt: string;
  [key: string]: unknown;
};

export type KernelEvent = {
  eventId: string;
  sender: Record<string, unknown>;
  senderAgentId: string;
  recipients: string[];
  status: string;
  correlationId: string;
  causationId: string;
  idempotencyKey: string;
  semanticPayload: {
    semanticType: string;
    payload: Record<string, unknown>;
  };
  deliveryPolicy: {
    wakeTarget: boolean;
  };
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
  [key: string]: unknown;
};

export type KernelExecution = {
  workRunId: string;
  taskId: string;
  agentId: string;
  status: string;
  startedAt: string;
  endedAt: string;
  evidenceRefs: Array<Record<string, unknown>>;
  deliveryRefs: Array<Record<string, unknown>>;
  createdAt: string;
  updatedAt: string;
  [key: string]: unknown;
};

export type KernelDelivery = {
  targetAgentId: string;
  status: string;
  inboxMessageId: string;
  targetSessionId: string;
  reason: string;
  wake: {
    wakeRequested: boolean;
    wakeStatus: string;
    messageId: string;
    targetAgentId: string;
    targetSessionId: string;
    turnId: string;
    reason: string;
  };
};

export type KernelOutcome = {
  outcomeId: string;
  taskId: string;
  workRunId: string;
  agentId: string;
  status: string;
  visibleReply: string;
  resultSummary: string;
  proposalRefs: string[];
  evidenceRefs: Array<Record<string, unknown>>;
  deliveries: KernelDelivery[];
  createdAt: string;
  [key: string]: unknown;
};

export type KernelProposal = {
  proposalId: string;
  sourceOutcomeId: string;
  proposalType: string;
  status: string;
  summary: string;
  createdAt: string;
  metadata: Record<string, unknown>;
};

export type KernelTimelineRef = {
  kind: string;
  id: string;
  [key: string]: string;
};

export type KernelTimelineItem = {
  kind: string;
  status: string;
  at: string;
  summary: string;
  refs: KernelTimelineRef[];
  targetAgentId?: string;
  inboxMessageId?: string;
  wakeStatus?: string;
};

export type KernelTaskListPayload = {
  tasks: KernelTask[];
  limit: number;
  status: string;
  updatedAt: string;
};

export type KernelTaskTimelinePayload = {
  taskId: string;
  task: KernelTask;
  event: KernelEvent;
  execution: KernelExecution;
  outcome: KernelOutcome;
  deliveries: KernelDelivery[];
  proposals: KernelProposal[];
  runtimeEvidenceRefs: Array<Record<string, string>>;
  projectionRefs: ProjectionSourceRef[];
  timeline: KernelTimelineItem[];
  readModel: {
    projection: boolean;
    factAuthority: boolean;
    truthSource: string;
    sourceRef?: SourceAuthorityRef;
    projectionEdit?: ProjectionEditContract;
    generatedAt: string;
  };
};
