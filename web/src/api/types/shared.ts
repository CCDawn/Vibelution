export type ModeAvailability = {
  chat: boolean;
  self_evolution: boolean;
  supervised_evolution: boolean;
};

export type EvolutionTrack = "supervised" | "self";

export type DomainAvailability = {
  chat: boolean;
  evolution: boolean;
  config: boolean;
};

export type UsageSource = "provider_usage" | "estimated" | "missing" | "not_called" | string;

export type TokenUsageRollup = {
  inputTokens: number;
  cachedInputTokens: number;
  cacheReadInputTokens: number;
  cacheCreationInputTokens: number;
  uncachedInputTokens: number;
  outputTokens: number;
  reasoningOutputTokens: number;
  totalTokens: number;
  callCount: number;
  observedCallCount: number;
  estimatedCallCount: number;
  missingCallCount: number;
  notCalledCount: number;
  latencyMs: number;
  cacheHitRate: number;
};

export type TokenUsageSample = Partial<TokenUsageRollup> & {
  eventId?: string;
  recordedAt?: string;
  source: UsageSource;
  scopeKind?: string;
  sessionId?: string;
  conversationId?: string;
  turnId?: string;
  agentId?: string;
  teamId?: string;
  provider?: string;
  model?: string;
  profileId?: string;
  transport?: string;
  contextWindow?: number;
  runtimeSceneId?: string;
  providerUsageKeys?: string[];
};

export type TokenUsageBreakdownItem = Partial<TokenUsageRollup> & {
  key: string;
  label: string;
  provider?: string;
  model?: string;
  source?: UsageSource;
};

export type UsageSummaryResponse = {
  scope: "global" | "session" | "agent" | "model" | string;
  filters: {
    sessionId: string;
    agentId: string;
    provider: string;
    model: string;
  };
  rollupFilters: {
    sessionId: string;
    agentId: string;
  };
  lastTokenUsage: TokenUsageSample;
  sessionTokenUsage: TokenUsageRollup;
  agentTokenUsage: TokenUsageRollup;
  scopeTokenUsage: TokenUsageRollup;
  globalTokenUsage: {
    today: TokenUsageRollup;
    last7Days: TokenUsageRollup;
    allTime: TokenUsageRollup;
  };
  modelContextWindow: number;
  diagnostics: {
    source: string;
    skippedRecordCount: number;
    ledgerPath: string;
    schemaVersion: number;
  };
  updatedAt: string;
  breakdowns: {
    models: TokenUsageBreakdownItem[];
    providers: TokenUsageBreakdownItem[];
    sources: TokenUsageBreakdownItem[];
  };
};

export type SourceAuthorityRef = {
  kind: string;
  id: string;
  owner: string;
  factAuthority: boolean;
  canonicalEditRoute: string;
  canonicalMutationApi: string;
  projectionCanWrite: boolean;
  allowedProjectionActions: string[];
  sourceAuthorityVersion: number;
};

export type ProjectionEditContract = {
  canWrite: boolean;
  mode: string;
  reason: string;
  sourceOwner: string;
  canonicalEditRoute: string;
  canonicalMutationApi: string;
  sourceAuthorityVersion: number;
};

export type ProjectAgentBusDelivery = {
  targetAgentId: string;
  targetAgentCode: string;
  targetAgentName: string;
  targetSessionId: string;
  inboxMessageId: string;
  status: string;
  reason: string;
  kernelEventId?: string;
  kernelTaskId?: string;
  kernelOutcomeId?: string;
  revoked?: boolean;
  revokedAt?: string;
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

export type ProjectAgentBusInterruption = {
  targetAgentId: string;
  targetAgentCode: string;
  targetAgentName: string;
  targetSessionId: string;
  status: string;
  reason: string;
  sourceEventId?: string;
};

export type ProjectAgentBusEvent = {
  eventId: string;
  messageType: "project_observation" | "user_guidance" | "agent_private" | "agent_broadcast" | string;
  targetScope: "observe" | "agents" | "all" | string;
  targetAgentIds: string[];
  targetAgentCodes: string[];
  targetAgentNames: string[];
  mentionedTokens: string[];
  unresolvedMentions: string[];
  content: string;
  summary: string;
  status?: string;
  revokedAt?: string;
  revokedBy?: string;
  revokeReason?: string;
  createdBy: string;
  createdAt: string;
  updatedAt: string;
  metadata: Record<string, unknown>;
  kernel?: {
    enabled: boolean;
    adapterVersion: string;
    reused: boolean;
    eventId: string;
    taskId: string;
    workRunId: string;
    outcomeId: string;
    outcomeStatus: string;
  };
  deliveries: ProjectAgentBusDelivery[];
  interruptions: ProjectAgentBusInterruption[];
  revocations?: Array<{
    targetAgentId: string;
    targetSessionId: string;
    inboxMessageId: string;
    inboxStatus: string;
    stopStatus: string;
    reason: string;
  }>;
};

export type ProjectAgentBusTimeline = {
  events: ProjectAgentBusEvent[];
  activeAgentCount: number;
  updatedAt: string;
};

export type ProjectionSourceRef = Record<string, unknown> & {
  kind: string;
  id: string;
  sourceSurface?: string;
  metadataKey?: string;
  sourceRef: SourceAuthorityRef;
  projectionEdit: ProjectionEditContract;
  sourceOwner: string;
  canonicalEditRoute: string;
  projectionCanWrite: boolean;
};

export type FileTreeNode = {
  name: string;
  path: string;
  type: "directory" | "file";
  children?: FileTreeNode[];
};

export type FileContent = {
  path: string;
  language: string;
  content: string;
  truncated: boolean;
};
