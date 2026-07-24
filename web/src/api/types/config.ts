import type { DomainAvailability, ModeAvailability } from "./shared";
import type { AgentInstance, AgentSupervisionDecision, ToolPolicy } from "./agents";

export type ConfigSummary = {
  hash: string;
  language: "zh" | "en";
  runtimeProfile: string;
  defaultMode: string;
  defaultRoute: string;
  intakeMode: string;
  modeAvailability: ModeAvailability;
  domainAvailability: DomainAvailability;
  modelLibraryCount: number;
  modelLabels: Record<string, string>;
  modelImageInputSupport: Record<string, boolean | null>;
  blockingCount: number;
  warningCount: number;
  sections: Array<{
    id: string;
    title: string;
    summary: string;
  }>;
};

export type ConfigDraftMeta = {
  pending_api_keys: Record<string, string>;
  pending_cleared_api_keys: string[];
};

export type ConfigEditorOption = {
  value: string;
  label: string;
};

export type ConfigEditorMeta = {
  path: string;
  label: string;
  hint: string;
  kind:
    | "object"
    | "object_list"
    | "boolean"
    | "select"
    | "number"
    | "string_list"
    | "json"
    | "secret"
    | "url"
    | "path"
    | "image"
    | "text"
    | "multiline";
  badge: string;
  options: ConfigEditorOption[];
};

export type ConfigEditorSection = {
  id: string;
  path: string;
  title: string;
  summary: string;
  fieldCount: number;
};

export type ConfigDiagnosis = {
  blocking_issues: string[];
  warnings: string[];
  suggested_actions: string[];
};

export type ConfigModelPresetOption = {
  preset_id: string;
  label: string;
  category?: "official" | "relay" | "openai_compatible" | "local" | string;
  provider_id: string;
  model_id: string;
  provider: Record<string, unknown>;
  model: Record<string, unknown>;
};

export type ConfigProviderPresetOption = {
  provider_preset_id: string;
  label: string;
  vendor_id: string;
  vendor_label: string;
  category?: "official" | "relay" | "openai_compatible" | "local" | string;
  provider_id: string;
  source_preset_id: string;
  provider: Record<string, unknown>;
  default_model: Record<string, unknown>;
};

export type ConfigProviderStatus =
  | "configured"
  | "reachable"
  | "auth_failed"
  | "discovery_failed"
  | "not_discovered"
  | "stale"
  | "protocol_mismatch"
  | "blocked"
  | (string & {});

export type ConfigModelAvailability =
  | "observed"
  | "pinned"
  | "missing_remote"
  | "capability_unknown"
  | "protocol_unknown"
  | "disabled"
  | "unknown"
  | (string & {});

export type ConfigCapabilityObservation = {
  value: "supported" | "unsupported" | "unknown";
  source: "operator_override" | "runtime_probe" | "provider_endpoint" | "curated_snapshot" | "driver_default";
  confidence: string;
  checked_at: string;
};

export type ConfigProviderOption = {
  provider_id: string;
  label: string;
  service_class: "official_api" | "aggregator" | "relay" | "self_hosted" | "local_runtime" | (string & {});
  vendor: string;
  driver: "openai" | "anthropic" | "gemini" | (string & {});
  runtime_framework?: string;
  artifact_path?: string;
  base_url?: string;
  credential_state: "configured" | "missing" | "not_required" | (string & {});
  /** Provider-level max context window in tokens; omit/null when unconfigured. */
  context_window?: number | null;
  default_protocol: string;
  pinned_count: number;
};

export type ConfigCatalogModel = {
  availability: ConfigModelAvailability;
  label: string;
  modelKey: string;
  modelRef: string;
  status: string;
  upstreamId: string;
  capabilities: Record<string, ConfigCapabilityObservation>;
  verificationStatus?: "unverified" | "verified" | "failed" | string;
  verificationCheckedAt?: string;
  verificationErrorType?: string;
  verificationHttpStatus?: number | null;
  reasoningVerificationStatus?: "unverified" | "verified" | "failed" | "stale" | "declared" | string;
  reasoningEffortValues?: string[];
  defaultReasoningEffort?: string;
  reasoningAdapter?: string;
  reasoningCapabilitySource?: string;
  reasoningCheckedAt?: string;
};

export type ConfigCatalogWarning = {
  code: string;
  modelKeys: string[];
};

export type ConfigCatalogProvider = {
  catalogStale: boolean;
  lastAttemptAt: string;
  lastErrorType: string;
  lastSuccessAt: string;
  modelCount: number;
  observedCount: number;
  pinnedCount: number;
  providerId: string;
  refreshDue: boolean;
  status: ConfigProviderStatus;
  models: Record<string, ConfigCatalogModel>;
  warnings: ConfigCatalogWarning[];
};

export type ConfigModelCatalog = {
  schemaVersion: number;
  providerCount: number;
  modelCount: number;
  providers: Record<string, ConfigCatalogProvider>;
};

export type ConfigMigrationArtifactResolutionDecision =
  | "preserve_upstream_id"
  | "split_deployment_artifact";

export type ConfigMigrationArtifactResolution =
  | { modelId: string; decision: "preserve_upstream_id" }
  | { modelId: string; decision: "split_deployment_artifact"; upstreamId: string };

export type ConfigMigrationPreviewRequest = {
  artifactResolutions?: ConfigMigrationArtifactResolution[];
};

export type ConfigMigrationArtifactConflict = {
  code: "artifact_path_suspected";
  severity?: string;
  modelId: string;
  proposedProviderId?: string;
  requiresExplicitResolution: true;
  allowedResolutions: ConfigMigrationArtifactResolutionDecision[];
  verificationState: "unverified_offline";
};

export type ConfigMigrationOtherConflict = {
  code: string;
  severity?: string;
  modelId?: string;
  modelIds?: string[];
  fields?: string[];
  proposedProviderId?: string;
};

export type ConfigMigrationConflict =
  | ConfigMigrationArtifactConflict
  | ConfigMigrationOtherConflict;

export type ConfigMigrationProviderPreview = {
  providerId: string;
  label: string;
  serviceClass: string;
  vendor: string;
  driver: string;
  baseUrl: string;
  credentialState: "configured" | "missing" | "not_required" | "conflict" | (string & {});
  modelRefs: string[];
};

export type ConfigMigrationPreview = {
  previewId: string;
  baseHash: string;
  status: "READY" | "NEEDS_REVIEW";
  providers: ConfigMigrationProviderPreview[];
  modelRefMap: Record<string, string>;
  referenceImpact: {
    liveReferenceCount: number;
    historicalReferenceCount: number;
  };
  conflicts: ConfigMigrationConflict[];
};

export type ConfigModelAliasUsage = {
  aliases: Array<{
    alias: string;
    liveReferenceCount: number;
    historicalReferenceCount: number;
  }>;
  totalLiveReferenceCount: number;
  totalHistoricalReferenceCount: number;
  canRemoveAliases: boolean;
};

export type ConfigProviderWorkspaceFields = {
  schemaVersion: 1 | 2;
  providerOptions: ConfigProviderOption[];
  modelCatalog: ConfigModelCatalog;
  modelAliasUsage: ConfigModelAliasUsage;
};

export type ConfigProviderDraftMutationPayload = {
  publicConfig: Record<string, unknown>;
  baseConfig?: Record<string, unknown> | null;
  draftMeta: ConfigDraftMeta;
  baseHash: string;
  providerId: string;
  provider: Record<string, unknown>;
  credentialValue?: string;
  routePreviewToken?: string;
};

export type ConfigProviderModelMutationPayload = {
  publicConfig: Record<string, unknown>;
  baseConfig?: Record<string, unknown> | null;
  draftMeta: ConfigDraftMeta;
  baseHash: string;
  providerId: string;
  upstreamId: string;
  modelKey?: string;
  label?: string;
  overrides?: Record<string, unknown>;
};

export type ConfigProviderDiscoveryMutationPayload = {
  publicConfig: Record<string, unknown>;
  baseConfig?: Record<string, unknown> | null;
  draftMeta: ConfigDraftMeta;
  baseHash: string;
  providerId: string;
  credentialValue?: string;
};

export type ConfigProviderSuggestionMutationPayload = {
  publicConfig: Record<string, unknown>;
  baseConfig?: Record<string, unknown> | null;
  draftMeta: ConfigDraftMeta;
  baseHash: string;
  provider: Record<string, unknown>;
};

export type ConfigMigrationApplyPayload = {
  previewId: string;
  baseHash: string;
};

export type ConfigMigrationRollbackPayload = {
  migrationId: string;
  baseHash: string;
};

export type ConfigProviderMergeConflict = {
  code: string;
  providerId?: string;
  detail?: string;
};

export type ConfigProviderMergePreview = {
  previewId: string;
  status: "READY" | "NEEDS_REVIEW";
  baseHash: string;
  canonicalProviderId: string;
  duplicateProviderIds: string[];
  modelRefMap: Record<string, string>;
  modelsToAdd: Array<{
    modelKey: string;
    sourceProviderId: string;
  }>;
  liveReferenceCount: number;
  historicalReferenceCount: number;
  conflicts: ConfigProviderMergeConflict[];
  requiredProbeModelRef: string;
};

export type ConfigProviderMergeApplyPayload = {
  previewId: string;
  baseHash: string;
  confirmed: boolean;
};

export type ConfigProviderMergeResult = {
  migrationId: string;
  status: "applied" | "rolled_back";
  hash: string;
  updatedReferenceCount?: number;
};

export type ConfigModelOption = {
  model_ref?: string;
  provider_id?: string;
  upstream_id?: string;
  model_id: string;
  source: string;
  provider: Record<string, unknown>;
  contextWindow?: number;
  provider_kind: string;
  provider_api?: string;
  model: string;
  label: string;
  details: Record<string, unknown>;
  protocol?: string;
  compat?: Record<string, unknown>;
  resolved_protocol?: string;
  protocol_source?: string;
  protocol_warnings?: string[];
  resolved_provider_api?: string;
  resolved_compat?: Record<string, unknown>;
  api_key_env: string;
  api_key_configured: boolean;
  api_key_state: string;
  supports_image_input?: boolean | null;
  capability_status?: "supported" | "unsupported" | "unknown" | string;
  capability_source?: string;
  capability_checked_at?: string;
  capability_error?: string;
};

export type ConfigFeatureDecision = {
  configuredEnabled: boolean;
  effectiveEnabled: boolean;
  featureSource: string;
  featureDecisionReason: string;
};

export type ConfigFeatureDecisionSnapshot = {
  configRevision: string;
  source: string;
  features: Record<string, ConfigFeatureDecision>;
};

export type ConfigWorkspace = ConfigSummary & ConfigProviderWorkspaceFields & {
  message: string;
  baseHash: string;
  configPath: string;
  publicConfig: Record<string, unknown>;
  featureDecisions: ConfigFeatureDecisionSnapshot;
  rawToml: string;
  draftMeta: ConfigDraftMeta;
  diagnosis: ConfigDiagnosis;
  summary: Record<string, string | number | boolean | null>;
  editorSections: ConfigEditorSection[];
  editorMeta: Record<string, ConfigEditorMeta>;
  modelPresetOptions: ConfigModelPresetOption[];
  providerPresetOptions: ConfigProviderPresetOption[];
  modelOptions: ConfigModelOption[];
};

export type ConfigLlmTestResult = {
  ok: boolean;
  message: string;
  route_id: string;
  model_id: string;
  provider_id: string;
  provider_kind: string;
  base_url: string;
  model: string;
  transport: string;
  contract: string;
  api_key_source: string;
  config_scope: "saved" | "draft";
  requires_api_key: boolean;
  capability?: "text" | "image_input" | string;
  capability_status?: "supported" | "unsupported" | "unknown" | string;
  supports_image_input?: boolean | null;
  capability_reason?: string;
  verification_status?: "verified" | "failed" | string;
  verification_checked_at?: string;
  verification_error_type?: string;
  verification_http_status?: number | null;
  verification_persisted?: boolean;
  reasoning_effort_values?: string[];
  default_reasoning_effort?: string;
  reasoning_adapter?: string;
  reasoning_contract_persisted?: boolean;
};

export type ConfigDiscoveredModel = {
  id: string;
  label: string;
  contextWindow?: number;
};

export type ConfigModelDiscoveryResult = {
  models: ConfigDiscoveredModel[];
  providerKind: string;
  baseUrl: string;
  apiKeySource: string;
};

export type PetSummary = {
  name: string;
  avatarPreset: string;
  level: number;
  exp: number;
  expToNext: number;
  mood: number;
  hunger: number;
  energy: number;
  health: number;
  love: number;
  totalTasks: number;
  achievements: string[];
  heartActive: boolean;
  inDream: boolean;
  friendCount: number;
  dailyTokens: number;
  totalTokens: number;
  statusLine: string;
};

export type PetActionResponse = {
  action: string;
  message: string;
  summary: PetSummary;
};

export type ResetSummary = {
  warning: string;
  mode: "custom" | string;
  items: ResetInventoryItem[];
  protected: ResetProtectedGroup[];
  presets: Array<{
    id: string;
    label: string;
    keys: string[];
  }>;
  categories: ResetInventoryItem[];
};

export type ResetInventoryItem = {
  id: string;
  name: string;
  description: string;
  detail: string;
  category: string;
  categoryLabel: string;
  risk: "low" | "medium" | "high" | string;
  defaultSelected: boolean;
  exists: boolean;
  sizeBytes: number;
  size: string;
  fileCount: number;
  scanTruncated: boolean;
  candidateCount: number;
  protectedCount: number;
  missingCount: number;
  rebuildHint: string;
};

export type ResetProtectedGroup = {
  id: string;
  label: string;
  paths: string[];
  reason: string;
};

export type ResetPathEntry = {
  path: string;
  kind: string;
  action: string;
  sizeBytes?: number;
  fileCount?: number;
  status?: string;
  message?: string;
};

export type ResetItemTotals = {
  deleteCount?: number;
  deleteFileCount?: number;
  deleteSizeBytes?: number;
  deletedCount?: number;
  deletedFileCount?: number;
  deletedSizeBytes?: number;
  skippedCount: number;
  protectedCount: number;
  failedCount: number;
};

export type ResetPreviewItem = {
  id: string;
  name: string;
  category: string;
  categoryLabel: string;
  risk: string;
  deleteCandidates: ResetPathEntry[];
  skipped: ResetPathEntry[];
  protected: ResetPathEntry[];
  failed: ResetPathEntry[];
  warnings: string[];
  truncated: boolean;
  summary: ResetItemTotals;
};

export type ResetExecuteItem = {
  id: string;
  name: string;
  category: string;
  categoryLabel: string;
  risk: string;
  deleted: ResetPathEntry[];
  skipped: ResetPathEntry[];
  protected: ResetPathEntry[];
  failed: ResetPathEntry[];
  warnings: string[];
  truncated: boolean;
  summary: ResetItemTotals;
};

export type ResetTotals = {
  deleteCount: number;
  deleteFileCount: number;
  deleteSizeBytes: number;
  deletedCount: number;
  deletedFileCount: number;
  deletedSizeBytes: number;
  skippedCount: number;
  protectedCount: number;
  failedCount: number;
};

export type ResetPreviewResponse = {
  selectedItemIds: string[];
  items: ResetPreviewItem[];
  totals: ResetTotals;
  warnings: string[];
  rebuildHints: string[];
  summary: string;
};

export type ResetExecuteResponse = {
  selectedItemIds: string[];
  items: ResetExecuteItem[];
  totals: ResetTotals;
  warnings: string[];
  rebuildHints: string[];
  summary: string;
};

export type ResearchDiscoverySessionSummary = ResearchDiscoverySession & {
  summary: ResearchDiscoverySummary;
};

export type ResearchDiscoverySessionList = {
  sessions: ResearchDiscoverySessionSummary[];
  summary: {
    sessionCount: number;
    selectedCount: number;
  };
};

export type ResearchDiscoverySessionPayload = {
  session: ResearchDiscoverySession;
  searchRuns: ResearchSearchRun[];
  sources: ResearchSource[];
  evidence: ResearchEvidenceRecord[];
  candidateThemes: ResearchCandidateTheme[];
  themeCards: ResearchThemeCard[];
  events: ResearchEvent[];
  summary: ResearchDiscoverySummary;
  agentReport: ResearchAgentReport;
};

export type ResearchPromptItem = {
  key: "broad" | "deep" | "review" | "themes" | "card" | string;
  filename: string;
  path: string;
  content: string;
  defaultContent: string;
};

export type ResearchAgentTemplate = {
  templateId: string;
  label: string;
  description: string;
};

export type ResearchAgentConfig = {
  key: "broad" | "deep" | "review" | "themes" | "card" | string;
  label: string;
  promptFilename: string;
  templateId: string;
  dialogueModelId?: string;
  llmBindings?: Record<string, { modelId?: string }>;
  roleKey?: string;
  promptTemplateId?: string;
  enabled: boolean;
  agentId?: string;
  agentInstanceId?: string;
  directSessionId?: string;
};

export type ResearchLlmConfigOption = {
  configId: string;
  label: string;
  model: string;
  providerKind: string;
};

export type ResearchPromptWorkspace = {
  root: string;
  agentConfigPath: string;
  prompts: ResearchPromptItem[];
  agentTemplates: ResearchAgentTemplate[];
  llmConfigs: ResearchLlmConfigOption[];
  agents: ResearchAgentConfig[];
};

export type ResearchFlowNodeStatus =
  | "idle"
  | "ready"
  | "running"
  | "done"
  | "failed"
  | "stale"
  | "needs_review"
  | "needs_input"
  | "needs_evidence"
  | "blocked"
  | "skipped"
  | string;

export type ResearchFlowNode = {
  id: string;
  label: string;
  type: "agent" | "tool" | "human" | "artifact" | "decision" | "evaluation" | string;
  status: ResearchFlowNodeStatus;
  x: number;
  y: number;
  agentId?: string;
  agentKey: string;
  promptKey: string;
  description: string;
  routeCondition: string;
};

export type ResearchFlowEdge = {
  id: string;
  source: string;
  target: string;
  label: string;
  condition: string;
  type:
    | "success"
    | "evidence_loop"
    | "approval_gate"
    | "human_handoff"
    | "selection"
    | "failure"
    | "blocked"
    | string;
};

export type ResearchFlowValidationIssue = {
  severity: "error" | "warning" | string;
  code: string;
  message: string;
  nodeId?: string;
  edgeId?: string;
  source?: string;
  target?: string;
};

export type ResearchFlowValidation = {
  valid: boolean;
  summary: {
    errorCount: number;
    warningCount: number;
    issueCount?: number;
  };
  issues: ResearchFlowValidationIssue[];
};

export type ResearchFlowCanvas = {
  schemaVersion: number;
  canvasKind?: string;
  updatedAt: string;
  path: string;
  organizationPath?: string;
  projectBinding?: {
    projectKind?: string;
    projectId?: string;
    teamId?: string;
    teamName?: string;
    source?: string;
    organizationSource?: string;
    locked?: boolean;
    [key: string]: unknown;
  };
  viewport: {
    x: number;
    y: number;
    zoom: number;
  };
  nodes: ResearchFlowNode[];
  edges: ResearchFlowEdge[];
  validation?: ResearchFlowValidation;
};

export type ResearchFlowExecution = {
  sessionId: string;
  nodeId: string;
  nodeLabel: string;
  actionKey: string;
  status: "done" | "failed" | string;
  routeOutcome: string;
  activatedNodeIds: string[];
  message: string;
};

export type ResearchFlowExecutionResponse = {
  canvas: ResearchFlowCanvas;
  session: ResearchDiscoverySessionPayload;
  execution: ResearchFlowExecution;
};

export type ResearchOrgMessageType =
  | "notice"
  | "request"
  | "task"
  | "report"
  | "escalation"
  | "decision"
  | string;

export type CommunicationPolicy = {
  allowedMessageTypes: ResearchOrgMessageType[];
  allowedIntents: string[];
  wakeStrategy: "immediate" | "conditional" | "mailbox_only" | "never" | string;
  maxForwardDepth: number;
};

export type ResearchOrgAgentNode = {
  nodeId: string;
  agentId: string;
  agentCode: string;
  displayName: string;
  role: string;
  employeeRank: string;
  protected: boolean;
  zoneId: string;
  status: string;
  x: number;
  y: number;
  agent?: AgentInstance | null;
  toolPolicy?: ToolPolicy | null;
  allowedTools: string[];
  updatedAt: string;
};

export type ResearchOrgEdge = {
  edgeId: string;
  fromAgentId: string;
  toAgentId: string;
  label: string;
  communicationPolicy: CommunicationPolicy;
  status: string;
  createdAt: string;
  updatedAt: string;
};

export type ResearchOrgMessageDelivery = {
  targetAgentId: string;
  targetAgentCode: string;
  targetAgentName: string;
  allowed: boolean;
  reason: string;
  edgeId: string;
  policy: CommunicationPolicy | Record<string, unknown>;
  inboxMessageId: string;
  wakeRequested: boolean;
  wakeStatus: string;
  wakeReason: string;
  turnId: string;
  supervision?: AgentSupervisionDecision;
  deliveredAt: string;
};

export type ResearchOrgMessage = {
  messageId: string;
  sourceType: "user" | "agent" | string;
  sourceAgentId: string;
  sourceAgentCode: string;
  sourceAgentName: string;
  targetAgentIds: string[];
  deliveryMode: "private" | "broadcast" | "zone" | string;
  zoneId: string;
  messageType: ResearchOrgMessageType;
  intent: string;
  content: string;
  summary: string;
  threadId: string;
  humanOverride: boolean;
  wakeTarget: boolean;
  createdBy: string;
  createdAt: string;
  deliveries: ResearchOrgMessageDelivery[];
};

export type ResearchOrgProposal = {
  proposalId: string;
  title: string;
  description: string;
  proposedByAgentId: string;
  recommendedByAgentId: string;
  ceoApproved: boolean;
  ceoApprovalMode: string;
  requiresUserConfirmation: boolean;
  riskLevel: "low" | "medium" | "high" | string;
  status: string;
  actions: Array<Record<string, unknown>>;
  createdAt: string;
  updatedAt: string;
  appliedAt: string;
  auditTrail: Array<Record<string, unknown>>;
};

export type ResearchOrgAuditEvent = {
  auditEventId: string;
  eventType: string;
  messageId?: string;
  messageType?: string;
  proposalId?: string;
  sourceType?: string;
  sourceAgentId?: string;
  targetAgentId?: string;
  allowed: boolean;
  reason: string;
  edgeId?: string;
  inboxMessageId?: string;
  wakeRequested?: boolean;
  wakeStatus?: string;
  summary: string;
  createdAt: string;
};

export type ResearchOrgZone = {
  zoneId: string;
  label: string;
  description: string;
  agentIds: string[];
  createdAt: string;
};

export type ResearchOrganization = {
  schemaVersion: number;
  updatedAt: string;
  path: string;
  agents: ResearchOrgAgentNode[];
  edges: ResearchOrgEdge[];
  zones: ResearchOrgZone[];
  messages: ResearchOrgMessage[];
  proposals: ResearchOrgProposal[];
  auditEvents: ResearchOrgAuditEvent[];
};

export type ResearchOrgMessageResponse = {
  organization: ResearchOrganization;
  message: ResearchOrgMessage;
};

export type ResearchOrgProposalResponse = {
  organization: ResearchOrganization;
  proposal: ResearchOrgProposal;
  results?: Array<Record<string, unknown>>;
};

export type ResearchKnowledgeProvenance = {
  sourceId: string;
  sessionId: string;
  searchRunId: string;
  phase: string;
  provider: string;
  queries: string[];
  retrievedAt: string;
  seenAt: string;
};

export type ResearchKnowledgeEntry = {
  knowledgeId: string;
  dedupeKey: string;
  kind: "paper" | "github" | "dataset" | "web" | string;
  title: string;
  url: string;
  summary: string;
  reliability: "verified" | "normal" | "weak" | string;
  categories: string[];
  tags: string[];
  sourceIds: string[];
  sessionIds: string[];
  searchRunIds: string[];
  phases: string[];
  providers: string[];
  queries: string[];
  provenance: ResearchKnowledgeProvenance[];
  firstSeenAt: string;
  lastSeenAt: string;
  firstRetrievedAt: string;
  lastRetrievedAt: string;
  hitCount: number;
  metadata: Record<string, unknown>;
};

export type ResearchKnowledgeRecord = {
  recordId: string;
  dedupeKey: string;
  type: string;
  content: string;
  summary: string;
  status: string;
  confidence: number;
  sourceIds: string[];
  knowledgeIds: string[];
  sessionIds: string[];
  evidenceIds: string[];
  claimIds: string[];
  gapIds: string[];
  tags: string[];
  provenance: ResearchKnowledgeProvenance[];
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
};

export type ResearchKnowledgeBasePayload = {
  schemaVersion: number;
  updatedAt: string;
  path: string;
  entries: ResearchKnowledgeEntry[];
  claims: ResearchKnowledgeRecord[];
  evidence: ResearchKnowledgeRecord[];
  gaps: ResearchKnowledgeRecord[];
  hypotheses: ResearchKnowledgeRecord[];
  experiments: ResearchKnowledgeRecord[];
  agentEvolutionMemory: {
    schemaVersion: number;
    purpose: string;
    experienceRefs: string[];
    reflectionRefs: string[];
    candidateRefs: string[];
    strategyNotes: ResearchKnowledgeRecord[];
  };
  summary: {
    entryCount: number;
    visibleCount: number;
    kindCounts: Record<string, number>;
    categoryCounts: Record<string, number>;
    claimCount: number;
    visibleClaimCount: number;
    evidenceCount: number;
    visibleEvidenceCount: number;
    gapCount: number;
    visibleGapCount: number;
  };
  agentContext: {
    purpose: string;
    entryCount: number;
    visibleCount: number;
    claimCount: number;
    evidenceCount: number;
    gapCount: number;
    recentQueries: string[];
    recentSources: Array<{
      knowledgeId: string;
      kind: string;
      title: string;
      url: string;
      lastSeenAt: string;
      hitCount: number;
      tags: string[];
    }>;
    cognitiveLayers: string[];
    reusePolicy: string;
  };
};

export type ResearchDiscoverySession = {
  sessionId: string;
  openGoal: string;
  constraints: string;
  preferences: string;
  candidateCount: number;
  status: "draft" | "running" | "reviewing" | "selected" | "archived" | "failed" | string;
  createdAt: string;
  updatedAt: string;
  selectedThemeId: string | null;
};

export type ResearchSearchRun = {
  runId: string;
  sessionId: string;
  phase: "broad" | "deep" | string;
  queries: string[];
  provider: string;
  status: "draft" | "running" | "completed" | "failed" | string;
  startedAt: string;
  completedAt: string | null;
  modelProfile: Record<string, unknown>;
};

export type ResearchSource = {
  sourceId: string;
  sessionId: string;
  searchRunId: string;
  kind: "paper" | "github" | "dataset" | "web" | string;
  title: string;
  url: string;
  snippet: string;
  reliability: "verified" | "normal" | "weak" | string;
  retrievedAt: string;
};

export type ResearchEvidenceRecord = {
  evidenceId: string;
  sessionId: string;
  sourceId: string;
  claim: string;
  evidenceType: "method" | "dataset" | "result" | "gap" | "implementation" | "background" | string;
  confidence: "high" | "medium" | "low" | string;
  note: string;
};

export type ResearchCandidateTheme = {
  themeId: string;
  sessionId: string;
  title: string;
  oneLine: string;
  interdisciplinaryCombination: string[];
  coreQuestion: string;
  noveltyPath: "problem_perspective" | "method_transfer" | "discipline_combination" | "application_scenario" | string;
  scores: Record<string, number>;
  recommendationScore: number;
  sourceIds: string[];
  evidenceIds: string[];
  uncertainty: string;
  agentReview: string;
  status: "draft" | "shortlisted" | "selected" | "rejected" | "stale" | string;
  version: number;
  parentRunId: string;
};

export type ResearchThemeCard = {
  cardId: string;
  sessionId: string;
  themeId: string;
  title: string;
  oneLine: string;
  coreScientificQuestion: string;
  whyNovel: string;
  whyCompetitionFit: string;
  interdisciplinaryCombination: string[];
  possibleDatasets: string[];
  possibleMethods: string[];
  possibleExperiments: string[];
  risks: string[];
  references: string[];
  nextResearchSteps: string[];
  agentReview: string;
  status: "draft" | "approved" | "stale" | string;
  version: number;
};

export type ResearchEvent = {
  eventCode: string;
  timestamp: string;
  fields: Record<string, unknown>;
};

export type ResearchDiscoverySummary = {
  searchRunCount: number;
  sourceCount: number;
  evidenceCount: number;
  candidateThemeCount: number;
  staleThemeCount: number;
  themeCardCount: number;
  approvedThemeCardCount: number;
};

export type ResearchAgentReport = {
  mode: "live_public_network" | "mixed_or_legacy" | string;
  status: "idle" | "ready" | "partial" | "legacy_data" | string;
  provider: string;
  lastRunAt: string;
  queries: string[];
  plan: string[];
  observations: string[];
  warnings: string[];
  sourceKindCounts: Record<string, number>;
  evidenceTypeCounts: Record<string, number>;
  failedAttempts: Array<{
    runId?: string;
    phase?: string;
    kind?: string;
    query?: string;
    error?: string;
  }>;
  summary: string;
};
