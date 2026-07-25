import type { ProjectionEditContract, SourceAuthorityRef } from "./shared";
import type { ConversationIndexKind, ConversationIndexVisibility } from "./chat";
import type { ConfigModelOption } from "./config";

export type ToolRegistrySource = "built_in" | "generated" | string;

export type ToolAgentScopeId = string;

export type ToolAgentScopeCounts = {
  total: number;
  visible: number;
  callable: number;
  blocked: number;
};

export type ToolAgentScopeSummary = {
  id: ToolAgentScopeId;
  label: string;
  kind: string;
  isSubagent: boolean;
  mode: string;
  description: string;
  counts: ToolAgentScopeCounts;
};

export type ToolAgentScopeState = {
  visible: boolean;
  callable: boolean;
  llmVisible: boolean;
  runtimeActive: boolean;
  testable: boolean;
  blockReason: string;
};

export type ToolTestPolicy = {
  mode: string;
  callable: boolean;
  runtimeCall: boolean;
  simulated: boolean;
  reason: string;
  argsPreview: Record<string, unknown>;
};

export type ToolPermissionPolicy = {
  requiresExplicitAllow: boolean;
  reason: string;
};

export type ToolResultFacts = {
  toolName?: string;
  transportStatus: string;
  semanticStatus: string;
  exitCode?: number | null;
  timedOut: boolean;
  failureClass?: string;
  resultKind?: string;
  truncated?: boolean;
  originalLength?: number;
  strategy?: string;
  rangeInfo?: string;
  continuationHint?: string;
  action?: string;
};

export type ToolAgentCompatibility = {
  status: string;
  callable: boolean;
  message: string;
  toolCall: {
    id: string;
    name: string;
    args: Record<string, unknown>;
  };
  argsParsed: Record<string, unknown>;
  messageType: string;
  resultPreview: string;
  resultFacts?: ToolResultFacts;
};

export type ToolTestTimeout = {
  timedOut: boolean;
  timeoutSeconds: number;
  durationMs: number;
};

export type ToolTestAgentSummary = {
  agentId?: string;
  agentCode?: string;
  displayName?: string;
  primaryMode?: string;
  roleKey?: string;
  toolPolicyId?: string;
};

export type ToolRegistryItem = {
  id: string;
  name: string;
  description: string;
  source: ToolRegistrySource;
  category: string;
  categoryLabel: string;
  bundleIds: string[];
  capabilityTags: string[];
  riskTags: string[];
  permissionTier: "low" | "medium" | "high" | "generated" | string;
  status: string;
  enabled: boolean;
  validated: boolean;
  llmVisible: boolean;
  runtimeActive: boolean;
  deleteAllowed: boolean;
  blockReason: string;
  validationError: string;
  argsSchema: Record<string, unknown>;
  testPolicy: ToolTestPolicy;
  permissionPolicy?: ToolPermissionPolicy;
  agentScopes: Record<ToolAgentScopeId, ToolAgentScopeState>;
  responseTemplate?: string;
  createdAt: string;
  updatedAt: string;
};

export type ToolBundle = {
  bundleId: string;
  label: string;
  description: string;
  category: string;
  toolNames: string[];
  preferredToolNames: string[];
  toolCount: number;
  preferredToolCount: number;
  highRiskToolCount: number;
  explicitAllowToolCount: number;
  riskTags: string[];
};

export type ToolRegistryPayload = {
  schemaVersion: number;
  mode: string;
  storagePath: string;
  counts: {
    total: number;
    builtIn: number;
    generated: number;
    llmVisible: number;
    runtimeActive: number;
    enabledGenerated: number;
    invalidGenerated: number;
  };
  agentScopes: ToolAgentScopeSummary[];
  toolBundles: ToolBundle[];
  tools: ToolRegistryItem[];
};

export type ToolDependencyHealth = {
  toolId: string;
  available: boolean;
  dependency: string;
  stage: string;
  status: string;
  tokenUrl?: string;
  searchApiCalled?: boolean;
  tokenPresent?: boolean;
  httpStatus?: number;
};

export type GeneratedToolDeleteResponse = {
  deleted: boolean;
  toolId: string;
  summary: string;
};

export type ToolTestResponse = {
  toolId: string;
  source: string;
  status: string;
  called: boolean;
  callable: boolean;
  message: string;
  resultPreview: string;
  resultFacts?: ToolResultFacts;
  argsUsed: Record<string, unknown>;
  testPolicy: ToolTestPolicy;
  agentCompatibility: ToolAgentCompatibility;
  agentScope: ToolAgentScopeSummary;
  agent?: ToolTestAgentSummary;
  timeout: ToolTestTimeout;
};

export type ToolImage2ModelOption = {
  modelRef: string;
  label: string;
  model: string;
  configuredModel: string;
  resolvedModel: string;
  providerKind: string;
  source: string;
  apiKeyEnv: string;
  apiKeyConfigured: boolean;
  discoveredModels: string[];
  modelDiscoveryStatus: string;
  modelDiscoveryError: string;
  modelDiscoveryUrl: string;
};

export type ToolImage2ModelConfig = {
  schemaVersion: number;
  toolId: string;
  defaultModelRef: string;
  selectedModel: ToolImage2ModelOption;
  models: ToolImage2ModelOption[];
  fallbackModel: ToolImage2ModelOption;
};

export type ToolPolicy = {
  policyId: string;
  policyVersion?: number;
  allowedTools: string[];
  preferredTools: string[];
  blockedTools: string[];
  readScopes: string[];
  writeScopes: string[];
  allowedCommandKinds: string[];
  blockedCommandPatterns: string[];
  networkAccess: string;
  mutationAccess: string;
  maxCallsPerTurn: number;
  perToolRules: Record<string, unknown>;
};

export type AgentToolPolicyConfiguration = {
  schemaVersion: number;
  agent: Pick<AgentInstance, "agentId" | "agentCode" | "displayName" | "updatedAt">;
  policyId: string;
  policyVersion: number;
  policyFingerprint: string;
  proposedPolicyFingerprint: string;
  registryVersion: string;
  currentPolicy: ToolPolicy;
  proposedPolicy: ToolPolicy;
  validation: { valid: boolean; errors: string[]; warnings: string[] };
  impact: {
    sharedPolicy: boolean;
    affectedAgentCount: number;
    affectedAgents: Array<Pick<AgentInstance, "agentId" | "agentCode" | "displayName">>;
  };
  preview: {
    visibleTools: string[];
    executableTools: string[];
    preferredTools: string[];
    blockedTools: string[];
    unavailableTools: string[];
    unknownTools: string[];
    approvalRequiredTools: string[];
  };
  confirmation: {
    required: boolean;
    reasons: string[];
    highRiskTools: string[];
    summary: string;
  };
};

export type AgentToolPolicySource = {
  kind: string;
  label: string;
  description: string;
  policyId: string;
  isPrivate: boolean;
  isLegacyWide: boolean;
  allowedToolCount: number;
  preferredToolCount: number;
  mutatingToolCount: number;
  mutatingTools: string[];
};

export type AgentToolGovernanceRequest = {
  eventId: string;
  requestId: string;
  kind: string;
  status: "pending_review" | "applied" | "rejected" | string;
  grantScope?: "persistent" | "session" | "turn" | string;
  sourceSessionId?: string;
  sourceTurnId?: string;
  targetAgentId: string;
  targetAgentCode: string;
  targetAgentName: string;
  proposedByAgentId: string;
  proposedByAgentCode: string;
  proposedByAgentName: string;
  policyDelta: {
    grantTools: string[];
    revokeTools: string[];
    blockTools: string[];
    unblockTools: string[];
  };
  reason: string;
  authority: Record<string, unknown>;
  riskLevel: "low" | "medium" | "high" | string;
  riskTags: string[];
  requiresApproval: boolean;
  approvalReason: string;
  createdAt: string;
  resolvedAt: string;
  resolvedBy: string;
  resolutionNote: string;
  appliedToolPolicyId: string;
  temporaryGrant?: {
    scope?: "persistent" | "session" | "turn" | string;
    sessionId?: string;
    turnId?: string;
    grantTools?: string[];
    appliedAt?: string;
    [key: string]: unknown;
  };
  after?: Record<string, unknown>;
};

export type AgentProjectMemoryUpdateStatus = "pending" | "applied" | "rejected" | "conflict" | "superseded" | string;

export type AgentProjectMemoryUpdateProposal = {
  eventId: string;
  proposalId: string;
  kind: string;
  status: AgentProjectMemoryUpdateStatus;
  agentId: string;
  agentCode: string;
  agentName: string;
  sessionId: string;
  turnId: string;
  laneId: string;
  focus: string;
  update: string;
  details: string;
  relatedFiles: string[];
  createdAt: string;
  resolvedAt: string;
  resolvedBy: string;
  resolutionNote: string;
};

export type MemoryPolicy = {
  policyId: string;
  privateMemoryRoot: string;
  episodicEventsPath: string;
  groupContextEventsPath: string;
  agentInboxMessagesPath?: string;
  toolObservationsPath: string;
  summariesPath: string;
  readSharedGroups: string[];
  writeSharedGroups: string[];
  readKnowledgeBaseIds: string[];
  proposeKnowledgeBaseIds: string[];
  reviewKnowledgeBaseIds: string[];
  rateKnowledgeBaseIds: string[];
};

export type AgentWorkspaceTerritory = {
  schemaVersion: number;
  agentId: string;
  privateRoot: string;
  sharedRoot: string;
  defaultWriteScope: "private" | "shared" | string;
  readScopes: string[];
  writeScopes: string[];
  subdirs: Record<string, string>;
  memoryRoot: string;
  eventsRoot: string;
  artifactsRoot: string;
  scratchRoot: string;
  inboxRoot: string;
  outboxRoot: string;
  runsRoot: string;
  legacyWorkspacePath?: string;
};

export type GroupContextEvent = {
  eventId: string;
  sourceRoomId: string;
  sourceRoundId: string;
  targetAgentId: string;
  targetSessionId: string;
  topic: string;
  summary: string;
  ownMessage: string;
  peerHighlights: string[];
  promptEligible: boolean;
  createdAt: string;
};

export type AgentInboxMessage = {
  eventId: string;
  messageId: string;
  threadId: string;
  kind: string;
  status: "pending" | "consumed" | string;
  sourceAgentId: string;
  sourceAgentCode: string;
  sourceAgentName: string;
  sourceSessionId: string;
  sourceRoomId: string;
  sourceRoundId: string;
  targetAgentId: string;
  targetAgentCode: string;
  targetAgentName: string;
  targetSessionId: string;
  content: string;
  summary: string;
  promptEligible: boolean;
  createdBy: string;
  createdAt: string;
  consumedAt: string;
  consumedBySessionId: string;
  consumedByTurnId: string;
  metadata: Record<string, unknown>;
  delivery?: {
    wakeRequested: boolean;
    wakeStatus: string;
    messageId: string;
    targetAgentId: string;
    targetSessionId: string;
    turnId: string;
    reason: string;
  };
};

export type AgentDelegationPolicy = {
  allowSubagents: boolean;
  maxConcurrent: number;
  maxDepth: number;
  allowWakeMessages: boolean;
  allowedContextModes: string[];
};

export type AgentSupervisionPolicy = {
  supervisionEnabled: boolean;
  requiresReview: boolean;
  reviewMode: "advisory" | "required" | "disabled" | string;
  evidenceLevel: "light" | "standard" | "strict" | string;
};

export type AgentSupervisionDecision = {
  allowed: boolean;
  reason: string;
  supervisionEnabled: boolean;
  requiresReview: boolean;
  reviewMode: "advisory" | "required" | "disabled" | string;
  evidenceLevel: "light" | "standard" | "strict" | string;
};

export type AgentRuntimeStatus = {
  state: "idle" | "running" | "failed" | "blocked" | "stopped" | "archived" | "unknown" | string;
  label: string;
  reason: string;
  runId: string;
  runKind: string;
  sessionId: string;
  summary: string;
  updatedAt: string;
  staleRuntimeRunCount?: number;
  latestHistoricalRunId?: string;
  latestHistoricalSessionId?: string;
  latestHistoricalUpdatedAt?: string;
};

export type AgentPersonaProfile = {
  gender: string;
  age: string;
  pronouns: string;
  personality: string;
  communicationStyle: string;
  background: string;
  expertise: string[];
  collaborationPreference: string;
  identityNotes: string;
};

export type AgentTaskProfile = {
  mission: string;
  taskTypes: string[];
  responsibilities: string;
  preferredTasks: string;
  avoidTasks: string;
  successCriteria: string;
  deliverables: string;
  constraints: string;
  handoffNotes: string;
};

export type AgentContextCompressionPolicy = {
  mode: "inherit" | "custom" | string;
  enabled?: boolean;
  maxTokenLimit?: number;
  maxCompressionsPerSession?: number;
  levels?: {
    light?: number;
    standard?: number;
    deep?: number;
    emergency?: number;
  };
  summaryChars?: {
    light?: number;
    standard?: number;
    deep?: number;
    emergency?: number;
  };
  preservation?: {
    keepAiMessages?: number;
    preserveErrors?: boolean;
    extractKeyDecisions?: boolean;
  };
};

export type AgentContextCompressionEffectivePolicy = AgentContextCompressionPolicy & {
  source: "global" | "agent_custom" | string;
  effectiveTokenLimit: number;
  compressionTriggerTokenLimit?: number;
  contextWindowLimit: number;
  modelContextWindowLimit?: number;
  agentPolicy?: AgentContextCompressionPolicy;
};

export type AgentInstance = {
  agentId: string;
  agentCode: string;
  displayName: string;
  kind: "persistent" | string;
  primaryMode: "chat" | "research" | "self_evolution" | "supervised_evolution" | "general" | string;
  roleKey: string;
  llmBindings: AgentLlmBindings;
  contextCompressionPolicy?: AgentContextCompressionPolicy;
  contextCompressionEffectivePolicy?: AgentContextCompressionEffectivePolicy;
  promptTemplateId: string;
  defaultPromptTemplateId?: string;
  promptTemplateCustomized?: boolean;
  directSessionId: string;
  conversationIndexVisibility?: ConversationIndexVisibility;
  conversationIndexKind?: ConversationIndexKind;
  conversationIndexErrors?: string[];
  workspacePath: string;
  workspaceTerritory?: AgentWorkspaceTerritory;
  toolPolicyId: string;
  toolPolicySource?: AgentToolPolicySource;
  memoryPolicyId: string;
  avatarImagePath?: string;
  avatarImageUrl?: string;
  personaProfile?: AgentPersonaProfile;
  taskProfile?: AgentTaskProfile;
  createdBy: string;
  status: string;
  metadata: Record<string, unknown> & {
    delegationPolicy?: AgentDelegationPolicy;
    supervisionPolicy?: AgentSupervisionPolicy;
  };
  createdAt: string;
  updatedAt: string;
  runtimeStatus?: AgentRuntimeStatus;
  memoryPolicy?: MemoryPolicy;
  toolPolicy?: ToolPolicy;
  toolGovernanceRequests?: AgentToolGovernanceRequest[];
  groupContextEvents?: GroupContextEvent[];
  agentInboxMessages?: AgentInboxMessage[];
  agentInboxPendingCount?: number;
  sourceRef?: SourceAuthorityRef;
  projectionEdit?: ProjectionEditContract;
};

export type AgentLlmBinding = {
  modelId: string;
};

export type AgentLlmBindings = Partial<
  Record<"dialogue" | "mentalModel" | "summary" | "subagentPlanning" | "subagentExecution" | "vision", AgentLlmBinding>
>;

export type AgentLlmSlotKey = keyof AgentLlmBindings;

export type AgentLlmSlotDefinition = {
  slot: AgentLlmSlotKey;
  label: string;
  description: string;
  required: boolean;
  requiresImageInput: boolean;
};

export type AgentAvatarOption = {
  filename: string;
  path: string;
  url: string;
  source: string;
  sizeBytes: number;
};

export type AgentAvatarOptionsPayload = {
  directory: string;
  options: AgentAvatarOption[];
  count: number;
};

export type AgentAvatarUploadResponse = {
  path: string;
  url: string;
  contentType: string;
  sizeBytes: number;
  agent: AgentInstance;
};

export type AgentRunSnapshot = {
  runId: string;
  runKind: "agent_run" | string;
  sourceRunId: string;
  agentId: string;
  agentCode: string;
  displayName: string;
  primaryMode: string;
  roleKey: string;
  promptTemplateId: string;
  toolPolicyId: string;
  memoryPolicyId: string;
  workspacePath: string;
  sessionId: string;
  status: string;
  currentPhase: string;
  summary: string;
  toolCallCount: number;
  startedAt: string;
  updatedAt: string;
  finishedAt: string;
};

export type SubAgentRunSnapshot = {
  runId: string;
  runKind: "sub_agent_run" | string;
  parentRunId: string;
  subRunId: string;
  parentAgentId: string;
  parentSessionId: string;
  agentId: string;
  contextMode: string;
  status: string;
  currentPhase: string;
  summary: string;
  toolCallCount: number;
  depth: number;
  maxDepth: number;
  resultRef: string;
  createdAt: string;
  updatedAt: string;
  endedAt: string;
};

export type AgentRunHistory = {
  agentId: string;
  limit: number;
  runs: AgentRunSnapshot[];
  subAgentRuns: SubAgentRunSnapshot[];
};

export type AgentRuntimeEvidenceMatch = {
  runtimeSceneId: string;
  directoryName: string;
  displayName: string;
  startedAt: string;
  status: string;
  eventCode: string;
  component: string;
  phase: string;
  level: string;
  outcome: string;
  message: string;
  timestamp: string;
  rawRefs: Array<{
    path: string;
    tail_lines?: number;
  }>;
  matchedFields: Record<string, string>;
};

export type AgentRuntimeEvidence = {
  agentId: string;
  sessionId: string;
  runId: string;
  matches: AgentRuntimeEvidenceMatch[];
};

export type PromptTemplate = {
  templateId?: string;
  promptTemplateId: string;
  name: string;
  category: "general" | "chat" | "research" | "self_evolution" | "supervised_evolution" | string;
  sourceType: "workspace_file" | "inline_record" | "empty" | string;
  sourcePath: string;
  sourceExists: boolean;
  sourceAuthority: "record_content" | "source_file" | "empty" | string;
  sourceDriftStatus: "synced" | "drifted" | "missing_source" | "source_authority" | "not_applicable" | string;
  sourceContentHash: string;
  content: string;
  contentHash: string;
  hasDefault: boolean;
  defaultContent: string;
  defaultContentHash: string;
  defaultContentPreview: string;
  status: "active" | "inactive" | "archived" | string;
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
};

export type PromptTemplateWorkspace = {
  schemaVersion: number;
  path: string;
  storagePath?: string;
  templates: PromptTemplate[];
  repairWarnings: Array<Record<string, unknown>>;
};

export type AgentModeBindingWarning = {
  mode: string;
  bindingKey?: string;
  field?: string;
  agentId: string;
  code?: string;
};

export type AgentModeBindingAgentRef = {
  agentId: string;
  agentCode: string;
  displayName: string;
  primaryMode: string;
  roleKey: string;
  llmBindings?: AgentLlmBindings;
  promptTemplateId: string;
  status: string;
  directSessionId?: string;
  metadata?: Record<string, unknown>;
};

export type AgentModeBindingItem = {
  mode: string;
  defaultAgentId: string;
  availableAgentIds: string[];
  pool: string[];
  flowBindings: Record<string, string>;
  slots: Record<string, string>;
  excludedAgentIds?: string[];
  excludedSlots?: string[];
  createdAt: string;
  updatedAt: string;
};

export type AgentModeBindings = {
  schemaVersion: number;
  path?: string;
  storagePath?: string;
  updatedAt?: string;
  bindings?: Record<string, AgentModeBindingItem>;
  modes: Record<string, AgentModeBindingItem> & {
    chat: {
      defaultAgentId: string;
      availableAgentIds: string[];
      pool?: string[];
      flowBindings?: Record<string, string>;
      slots?: Record<string, string>;
      excludedAgentIds?: string[];
      excludedSlots?: string[];
    };
    research: {
      pool: string[];
      flowBindings: Record<string, string>;
      defaultAgentId?: string;
      availableAgentIds?: string[];
      slots?: Record<string, string>;
      excludedAgentIds?: string[];
      excludedSlots?: string[];
    };
    self_evolution: {
      slots: Record<"executor" | "reviewer" | "observer" | "summarizer" | string, string>;
      excludedAgentIds?: string[];
      excludedSlots?: string[];
    };
    supervised_evolution: {
      slots: Record<"baseline" | "candidate" | "reviewer" | "auditor" | "judge" | string, string>;
      excludedAgentIds?: string[];
      excludedSlots?: string[];
    };
  };
  repairWarnings: AgentModeBindingWarning[];
  agentRefs: Record<string, AgentModeBindingAgentRef>;
  agents?: AgentModeBindingAgentRef[];
};

export type AgentConfigReference = {
  kind: string;
  sourceId: string;
  sourceLabel: string;
  mode: string;
  field: string;
  route: string;
  status: string;
  sourceRef?: SourceAuthorityRef;
  projectionEdit?: ProjectionEditContract;
  projectionCanWrite?: boolean;
};

export type AgentConfigHealthIssue = {
  severity: "blocking" | "warning" | "info" | string;
  code: string;
  agentId: string;
  agentCode?: string;
  title: string;
  detail: string;
  source: string;
  action: string;
};

export type AgentBoundary = {
  type: "work_session" | "team_role" | "system_role" | "service_role" | "archived" | string;
  label: string;
  ownership: "user" | "team" | "system" | "service" | "archive" | string;
  directSessionRole: "primary_entry" | "recovery_channel" | "historical_recovery" | "none" | string;
  reason: string;
  configurationSurface: "work_session" | "team_role" | "system_role" | "service" | "archive" | string;
  requiresPersonaProfile: string;
  requiresTaskProfile: string;
  requiresTeamMembership: string;
};

export type AgentSessionLifecycleSummary = {
  status: "archived" | "staged" | "deleted" | string;
  agentId: string;
  sessionIds: string[];
  archivedCount?: number;
  deletedCount?: number;
  directSessionCount?: number;
  childSessionCount?: number;
  workspaceStagedCount?: number;
  workspaceDeletedCount?: number;
  workspacePendingCount?: number;
  cleanupPending?: boolean;
  cleanupFailureTypes?: string[];
  readOnly?: boolean;
  historyRetention: "sealed" | "deleted" | string;
};

export type AgentArchiveSummary = {
  modeBindingsRepaired: number;
  removedFromRoomIds: string[];
  removedFromTeamIds: string[];
  sessions: AgentSessionLifecycleSummary;
  dataRetention: "sealed" | string;
  source?: string;
};

export type AgentPurgeSummary = {
  modeBindingsRepaired: number;
  removedFromRoomIds: string[];
  removedFromTeamIds: string[];
  sessions: AgentSessionLifecycleSummary;
  dataRetention: "purged" | string;
};

export type AgentPurgeResponse = {
  agentId: string;
  status: "purged" | string;
  previousStatus: string;
  deleted: boolean;
  workspaceDeleted: boolean;
  purgeSummary: AgentPurgeSummary;
};

export type AgentConfigWorkspaceAgent = AgentInstance & {
  dialogueModel?: AgentModelChoice | null;
  llmBindingModels?: Partial<Record<keyof AgentLlmBindings, AgentModelChoice | null>>;
  promptTemplate?: PromptTemplate | null;
  agentBoundary?: AgentBoundary;
  archiveSummary?: AgentArchiveSummary;
  references: AgentConfigReference[];
  health: AgentConfigHealthIssue[];
  effectiveConfiguration?: AgentEffectiveConfiguration;
};

export type AgentEffectiveConfigurationSource = {
  kind: "agent" | "mode_default" | "global" | "shared_policy" | "system" | string;
  id: string;
  label: string;
};

export type AgentEffectiveConfigurationField = {
  key: "dialogueModel" | "promptTemplate" | "toolPolicy" | "memoryPolicy" | "contextCompression" | "delegation" | "supervision" | string;
  label: string;
  effectiveValue: unknown;
  source: AgentEffectiveConfigurationSource;
  inheritanceChain: Array<AgentEffectiveConfigurationSource & { value: unknown; active: boolean }>;
  status: "ready" | "warning" | "blocked" | string;
};

export type AgentEffectiveConfiguration = {
  fields: AgentEffectiveConfigurationField[];
};

export type AgentConfigChangeDraft = {
  draftId: string;
  status: "active" | string;
  baseUpdatedAt: string;
  createdAt: string;
  summary: string;
  changedFields: string[];
  stale: boolean;
};

export type AgentConfigRevision = {
  revisionId: string;
  revisionNumber: number;
  publishedAt: string;
  source: string;
  sourceDraftId: string;
  changedFields: string[];
  runtimeBinding: {
    directSessionId: string;
  };
};

export type AgentConfigChanges = {
  schemaVersion: number;
  agentId: string;
  activeDraft: AgentConfigChangeDraft | null;
  revisions: AgentConfigRevision[];
};

export type AgentModelChoice = {
  modelId: string;
  modelRef: string;
  modelKey: string;
  upstreamId: string;
  label: string;
  model: string;
  contextWindow?: number;
  providerId: string;
  providerLabel: string;
  providerKind: string;
  providerBaseUrl: string;
  transport: string;
  source: "pinned" | "discovered" | "both";
  runtimeSelectable: boolean;
  availability: string;
  verificationStatus: string;
  catalogStale: boolean;
  slotCompatibility: Record<string, { allowed: boolean; reasonCode: string }>;
  capabilities: Record<string, unknown>;
  apiKeyEnv: string;
  apiKeyConfigured: boolean;
  apiKeyState: string;
  requiresApiKey: boolean;
  missingApiKey: boolean;
  supportsImageInput?: boolean | null;
  supportsReasoningEffort?: boolean;
  reasoningAdapter?: string;
  reasoningEffortMap?: Record<string, string>;
  reasoningDefaultSource?: string;
  reasoningEffortValues?: string[];
  reasoningEffortOptions?: Array<{
    value: string;
    label: string;
    description: string;
  }>;
  defaultReasoningEffort?: string;
  capabilityStatus: string;
  capabilitySource: string;
};

export type AgentToolPolicyOption = {
  policyId: string;
  agentCount: number;
  allowedToolCount: number;
  preferredToolCount: number;
  blockedToolCount: number;
  networkAccess: string;
  mutationAccess: string;
  maxCallsPerTurn: number;
};

export type AgentMemoryPolicyOption = {
  policyId: string;
  agentCount: number;
  privateMemoryRoot: string;
  readSharedGroupCount: number;
  writeSharedGroupCount: number;
  readKnowledgeBaseCount: number;
  proposeKnowledgeBaseCount: number;
  reviewKnowledgeBaseCount: number;
  hasInboxPath: boolean;
};

export type AgentConfigWorkspaceGroup = {
  id: string;
  label: string;
  section?: "status" | "mode" | "reference" | string;
  description?: string;
  agentIds: string[];
  count: number;
  healthCount: number;
};

export type AgentConfigWorkspace = {
  schemaVersion: number;
  operatorConfigHash?: string;
  generatedAt: string;
  storage: {
    agentRegistryPath: string;
    modeBindingPath: string;
    promptTemplatePath: string;
  };
  summary: {
    agentCount: number;
    activeAgentCount: number;
    archivedAgentCount: number;
    runningAgentCount: number;
    blockedAgentCount: number;
    modeCount: number;
    chatRoomCount: number;
    groupCount: number;
    healthIssueCount: number;
    blockingIssueCount: number;
    warningIssueCount: number;
    inboxPendingCount: number;
    teamCount?: number;
  };
  groups: AgentConfigWorkspaceGroup[];
  agents: AgentConfigWorkspaceAgent[];
  modeBindings: Record<string, AgentModeBindingItem>;
  promptTemplates: PromptTemplate[];
  agentLlmSlots: AgentLlmSlotDefinition[];
  agentModelChoices: AgentModelChoice[];
  modelOptions: ConfigModelOption[];
  toolPolicies: AgentToolPolicyOption[];
  memoryPolicies: AgentMemoryPolicyOption[];
  chatRooms: Array<{
    roomId: string;
    title: string;
    mode: string;
    status: string;
    activeRoundId: string;
    agentIds: string[];
    participantCount: number;
    roundCount: number;
    updatedAt: string;
    sourceRef?: SourceAuthorityRef;
    projectionEdit?: ProjectionEditContract;
    projectionCanWrite?: boolean;
  }>;
  teams?: Array<{
    teamId: string;
    name: string;
    purpose: string;
    status: string;
    agentIds: string[];
    memberCount: number;
    updatedAt: string;
    sourceRef?: SourceAuthorityRef;
    projectionEdit?: ProjectionEditContract;
    projectionCanWrite?: boolean;
  }>;
  references: Record<string, AgentConfigReference[]>;
  health: {
    status: "ok" | "warning" | "blocked" | string;
    issues: AgentConfigHealthIssue[];
    counts: {
      blocking: number;
      warning: number;
      info: number;
    };
    byAgent: Record<string, AgentConfigHealthIssue[]>;
  };
  repairWarnings: {
    modeBindings: AgentModeBindingWarning[];
    promptTemplates: Array<Record<string, unknown>>;
  };
  diagnostics?: {
    timingsMs?: Record<string, number>;
    loadModes?: Record<string, string>;
    cache?: {
      enabled?: boolean;
      hit?: boolean;
      waitMs?: number;
      ageMs?: number;
      ttlSeconds?: number;
    };
    source?: string;
  };
};
