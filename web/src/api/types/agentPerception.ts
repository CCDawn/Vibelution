export type AgentPerceptionSourceId = "personal" | "team" | "knowledge" | "projects";
export type AgentPerceptionTriggerId = "task" | "update" | "background";
export type AgentPerceptionMode = "off" | "manual" | "auto";
export type AgentPerceptionNotificationMode = "important" | "all" | "quiet";

export type AgentPerceptionTriggers = Record<AgentPerceptionTriggerId, boolean>;

export type AgentPerceptionSourcePolicy = {
  mode: AgentPerceptionMode;
  triggers: AgentPerceptionTriggers;
};

export type AgentPerceptionKnowledgePolicy = AgentPerceptionSourcePolicy & {
  scope: "selected" | "all_authorized";
  knowledgeBaseIds: string[];
  excludedKnowledgeBaseIds: string[];
};

export type AgentPerceptionTeamPolicy = AgentPerceptionSourcePolicy & {
  teamIds: string[];
};

export type AgentPerceptionPolicy = {
  schemaVersion: 1;
  enabled: boolean;
  sources: {
    personal: AgentPerceptionSourcePolicy;
    team: AgentPerceptionTeamPolicy;
    knowledge: AgentPerceptionKnowledgePolicy;
    projects: AgentPerceptionSourcePolicy;
  };
  background: {
    enabled: boolean;
    intervalMinutes: number;
    dailyMaxRuns: number;
    maxCallsPerRun: number;
    maxInputTokensPerRun: number;
    maxConcurrent: 1;
    maxResultChars: number;
    topics: string[];
  };
  notifications: {
    mode: AgentPerceptionNotificationMode;
  };
};

export type AgentPerceptionScopeOption = {
  id: string;
  label: string;
  detail: string;
};

export type AgentPerceptionScope =
  | { kind: "selected"; ids: string[] }
  | { kind: "all_authorized"; excludedIds: string[] }
  | { kind: "personal" }
  | { kind: "project_index" };

export type AgentPerceptionSourceDecision = {
  enforced: boolean;
  allowed: boolean | null;
  reason: string;
  source: AgentPerceptionSourceId;
  trigger: AgentPerceptionTriggerId;
  mode: AgentPerceptionMode | null;
  scope: AgentPerceptionScope | null;
};

export type AgentPerceptionConfiguration = {
  schemaVersion: 1;
  agentId: string;
  agentUpdatedAt: string;
  configurationRevision: number;
  configured: boolean;
  policy: AgentPerceptionPolicy;
  sourceDecisions: AgentPerceptionSourceDecision[];
  policyFingerprint: string;
  availableScopes: {
    teams: AgentPerceptionScopeOption[];
    knowledgeBases: AgentPerceptionScopeOption[];
  };
};

export type AgentPerceptionRun = {
  runId: string;
  topicId: string;
  status: string;
  sessionId: string;
  turnId: string;
  startedAt: string;
  finishedAt: string | null;
  toolCallsUsed: number;
  inputTokensUsed: number;
  outputCharsUsed: number;
  sources: AgentPerceptionSourceId[];
  readCount: number;
  resultCount: number;
  sourceReadCallsUsed: number;
};

export type AgentPerceptionReadableSource = {
  source: AgentPerceptionSourceId;
  selectedCount: number;
  readableCount: number;
  mode: AgentPerceptionMode;
  triggers: AgentPerceptionTriggers;
  requiresUserRequest: boolean;
};

export type AgentPerceptionLastActivity = {
  trigger: AgentPerceptionTriggerId;
  sources: AgentPerceptionSourceId[];
  readCount: number;
  resultCount: number;
  completedAt: string;
  sessionId: string;
  turnId: string;
  runId: string;
};

export type AgentPerceptionNotification = {
  notificationId: string;
  source?: AgentPerceptionSourceId | null;
  knowledgeBaseId: string;
  knowledgeItemId: string;
  revision: string;
  contentHash: string;
  observedAt: string;
  sessionId: string;
  turnId: string;
  delivered: boolean;
};

export type AgentPerceptionRuntime = {
  schemaVersion: 1;
  agentId: string;
  enabled: boolean;
  status: "disabled" | "scheduled" | "running" | "stopping" | "completed" | "failed" | "interrupted" | "degraded";
  nextRunAt: string | null;
  readableSources: AgentPerceptionReadableSource[];
  activeRun: AgentPerceptionRun | null;
  lastRun: AgentPerceptionRun | null;
  lastActivity: AgentPerceptionLastActivity | null;
  dailyBudget: {
    date: string;
    used: number;
    limit: number;
    remaining: number;
  };
  caps: {
    maxCallsPerRun: number;
    maxInputTokensPerRun: number;
    maxResultChars: number;
    maxConcurrent: number;
  };
  cancelAvailable: boolean;
  notifications: {
    unreadCount: number;
    totalCount: number;
    suppressedCount: number;
    items: AgentPerceptionNotification[];
  };
  knowledgeScan: {
    basesScanned: number;
    cursorCount: number;
    pendingCount: number;
  };
  updatedAt: string;
};

export type AgentPerceptionCancelResult = {
  agentId: string;
  runId: string;
  status: string;
  sessionId: string;
  turnId: string;
  stopRequested: boolean;
  cancelled: boolean;
  reason: string;
};
