import type { ProjectionEditContract, SourceAuthorityRef } from "./shared";
import type { TeamCaseState } from "./teams";
import type { AgentInboxMessage, AgentInstance, AgentSupervisionDecision, AgentToolGovernanceRequest, GroupContextEvent, MemoryPolicy, ToolPolicy } from "./agents";

export type SessionSummary = {
  id: string;
  title: string;
  agentId?: string;
  agentCode?: string;
  agentDisplayName?: string;
  agentAvatarImagePath?: string;
  agentAvatarImageUrl?: string;
  agentPrimaryMode?: string;
  agentRoleKey?: string;
  agentPromptTemplateId?: string;
  agentPromptSnapshot?: SessionAgentPromptSnapshot;
  lastPromptAssembly?: SessionPromptAssemblyManifest;
  experimentBinding?: SessionExperimentBinding | null;
  dialogueModelId?: string;
  reasoningEffort?: string;
  agentInboxPendingCount?: number;
  agentPrimaryDirectSessionId?: string;
  agentDirectSessionMismatch?: boolean;
  workspacePath?: string;
  agentWorkspacePath?: string;
  agentMissingId?: string;
  agentMissing?: boolean;
  agentStatusCode?: string;
  agentStatusMessage?: string;
  status: string;
  taskSummary: string;
  lastActive: string;
  updatedAt: string;
  /** Stable create timestamp for tab order; must not change with running activity. */
  createdAt?: string;
  currentPhase: string;
  /** Session is retained in storage but intentionally absent from normal chat navigation. */
  hiddenFromIndex?: boolean;
  /** Archive metadata is authoritative when a session must not be reopened. */
  archiveState?: {
    status?: string;
    source?: string;
    agentId?: string;
    archivedAt?: string;
    [key: string]: unknown;
  };
  readOnly?: boolean;
  lastTurnStatus?: string;
  /** Canonical turn terminal reason: success | failed_runtime | needs_continue | ... */
  terminalReason?: string;
  sessionKind?: "main" | "child" | string;
  sessionRole?: "primary" | "workspace" | "supervised" | string;
  parentSessionId?: string;
  rootSessionId?: string;
  childSessionIds?: string[];
  activeChildSessionId?: string;
  childStatus?: string;
  taskTitle?: string;
  resultCard?: {
    status?: string;
    title?: string;
    summary?: string;
    updatedAt?: string;
    [key: string]: unknown;
  } | null;
  sourceRef?: SourceAuthorityRef;
  projectionEdit?: ProjectionEditContract;
  agentSourceRef?: SourceAuthorityRef | null;
  conversationIndexVisibility?: ConversationIndexVisibility;
  conversationIndexKind?: ConversationIndexKind;
  conversationIndexErrors?: string[];
  teamId?: string;
  teamName?: string;
};

export type SessionExperimentBinding = {
  teamId: string;
  researchProjectId: string;
  experimentName: string;
  agentId: string;
  roleKey: string;
  roleLabel: string;
  attempt: number;
  retryOfSessionId: string;
  createdFromTaskId: string;
  createdAt: string;
};

export type SessionLlmReasoningEffortOption = {
  value: string;
  label: string;
  description: string;
};

export type SessionLlmModelOption = {
  modelId: string;
  modelRef: string;
  label: string;
  model: string;
  providerId: string;
  providerLabel: string;
  providerKind: string;
  apiKeyConfigured: boolean;
  missingApiKey: boolean;
  supportsReasoningEffort: boolean;
  reasoningEffortValues: string[];
  reasoningEffortOptions: SessionLlmReasoningEffortOption[];
  defaultReasoningEffort: string;
  isDefault: boolean;
  reasoningAdapter?: string;
  reasoningEffortMap?: Record<string, string>;
};

export type SessionLlmOptions = {
  sessionId: string;
  currentModelId: string;
  currentReasoningEffort: string;
  model: SessionLlmModelOption | null;
};

export type SessionAgentPromptSnapshot = {
  schemaVersion?: number;
  promptTemplateId?: string;
  templateId?: string;
  name?: string;
  category?: string;
  sourcePath?: string;
  sourceExists?: boolean;
  contentHash?: string;
  contentLength?: number;
  corePromptSchemaVersion?: number;
  corePromptHash?: string;
  corePromptLength?: number;
  corePrompts?: Array<{
    name?: string;
    sourcePath?: string;
    contentHash?: string;
    contentLength?: number;
  }>;
  promptAssemblySchemaVersion?: number;
  promptAssembly?: SessionPromptAssemblyManifest;
  capturedAt?: string;
  agentId?: string;
  agentCode?: string;
  agentDisplayName?: string;
  reason?: string;
};

export type SessionPromptAssemblySegment = {
  key?: string;
  tier?: string;
  placement?: string;
  stability?: string;
  trust?: string;
  source?: string;
  required?: boolean;
  chars?: number;
  contentHash?: string;
  estimatedTokens?: number;
  budgetTokens?: number;
  cachePolicy?: string;
  capabilityRequirements?: string[];
  decision?: string;
  decisionReason?: string;
  cacheHit?: boolean;
};

export type SessionPromptAssemblyManifest = {
  schemaVersion?: number;
  assemblyMode?: string;
  modelProtocol?: string;
  capabilityFingerprint?: string;
  permissionFingerprint?: string;
  stablePrefixHash?: string;
  sessionSnapshotHash?: string;
  totalEstimatedTokens?: number;
  budgetTokens?: number;
  segments?: SessionPromptAssemblySegment[];
};

export type SessionQueryResponse = {
  items: SessionSummary[];
  nextCursor: string;
  totalEstimate?: number;
  filters: {
    q: string;
    agentId: string;
    sessionKind: string;
    state: string;
    sort: string;
    limit: number;
    cursor: string;
  };
};

export type ChatWorkbenchBootstrap = {
  activeSessionId: string;
  sessionPage: SessionQueryResponse;
  agents: AgentInstance[];
  conversations: ConversationSummary[];
};

export type SessionChildHandoffContext = {
  source: string;
  parentSessionId: string;
  sourceSessionId?: string;
  parentMessageId: string;
  triggeringUserMessage: string;
  splitReason: string;
  inheritedFacts: string[];
  relevantFiles: string[];
  relevantLogs: string[];
  constraints: string[];
  excludedContextSummary: string;
};

export type ConversationSummary = {
  conversationId: string;
  type: "direct_agent" | "group_room" | string;
  title: string;
  agentId?: string;
  agentCode?: string;
  agentDisplayName?: string;
  agentAvatarImagePath?: string;
  agentAvatarImageUrl?: string;
  directSessionId?: string;
  roomId?: string;
  status: string;
  summary: string;
  updatedAt: string;
  workspacePath: string;
  participantCount?: number;
  mode?: string;
  agentPrimaryMode?: string;
  agentRoleKey?: string;
  agentPromptTemplateId?: string;
  dialogueModelId?: string;
  agentInboxPendingCount?: number;
  conversationIndexVisibility?: ConversationIndexVisibility;
  conversationIndexKind?: ConversationIndexKind;
  conversationIndexErrors?: string[];
  agentMissing?: boolean;
  agentStatusCode?: string;
  agentStatusMessage?: string;
  sourceRef?: SourceAuthorityRef;
  projectionEdit?: ProjectionEditContract;
  agentSourceRef?: SourceAuthorityRef | null;
};

export type ConversationIndexVisibility =
  | "user_visible"
  | "team_private"
  | "internal_recovery"
  | "hidden"
  | string;

export type ConversationIndexKind =
  | "user_chat"
  | "personal_agent"
  | "team_agent"
  | "system_entry"
  | "hidden"
  | "invalid"
  | string;

export type SessionActiveTask = {
  taskId: string;
  kind: string;
  status: string;
  title: string;
  goal: string;
  readFiles: string[];
  changedFiles: string[];
  verificationStatus: string;
  verificationSummary: string;
  latestSummary: string;
  nextAction: string;
  lastUserMessage: string;
  turnCount: number;
  resumeCount: number;
  createdAt: string;
  updatedAt: string;
  defaultFileContext: string;
  previewTabs: string[];
  activePreviewPath: string;
  metadata: Record<string, unknown>;
};

export type ToolCall = {
  callId?: string;
  name: string;
  rawToolName?: string;
  title?: string;
  sequence?: number;
  status: string;
  summary?: string;
  arguments?: Record<string, unknown>;
  resultPreview?: string;
  resultType?: string;
  resultLength?: number;
  error?: string;
  durationMs?: number;
  durationSeconds?: number;
  timeoutSeconds?: number;
  transportStatus?: string;
  semanticStatus?: string;
  exitCode?: number | null;
  timedOut?: boolean;
  failureClass?: string;
  resultKind?: string;
  truncated?: boolean;
  originalLength?: number;
  tracePath?: string;
};

export type ConversationFeedbackEvent = {
  callId?: string;
  sequence: number;
  kind: "thought" | "mental" | "tool" | "status";
  status: string;
  timestamp?: string;
  name?: string;
  summary?: string;
  arguments?: Record<string, unknown>;
  resultPreview?: string;
  resultType?: string;
  resultLength?: number;
  error?: string;
  durationMs?: number;
  durationSeconds?: number;
  timeoutSeconds?: number;
  transportStatus?: string;
  semanticStatus?: string;
  exitCode?: number | null;
  timedOut?: boolean;
  failureClass?: string;
  resultKind?: string;
  truncated?: boolean;
  originalLength?: number;
  tracePath?: string;
  relatedThoughtSequence?: number;
};

export type ConversationTimelineItem = {
  id: string;
  turnId?: string;
  messageId?: string;
  sequence?: number;
  kind: "thought" | "assistant_text" | "operation" | "command_group" | string;
  status?: "pending" | "running" | "completed" | "failed" | string;
  title?: string;
  summary?: string;
  text?: string;
  preview?: string;
  defaultExpanded?: boolean;
  sourceOperationIds?: string[];
  operationIds?: string[];
  metadata?: Record<string, unknown>;
};

export type CodexTranscriptCellKind =
  | "user"
  | "assistant_markdown"
  | "reasoning_summary"
  | "tool_call"
  | "status"
  | "error_notice"
  | "stream_tail"
  | string;

export type CodexTranscriptCellStatus = "pending" | "running" | "completed" | "failed" | "degraded" | string;

export type CodexTranscriptCellTone = "neutral" | "running" | "warning" | "error" | string;

export type CodexRolloutTraceEventKind =
  | "ToolCallStarted"
  | "RuntimeStarted"
  | "RuntimeEnded"
  | "ToolCallEnded"
  | string;

export type CodexRolloutTraceEvent = {
  id: string;
  kind: CodexRolloutTraceEventKind;
  operationId: string;
  toolCallId?: string;
  terminalOperationId?: string;
  terminalId?: string;
  sequence?: number;
  timestamp?: string;
  status: CodexTranscriptCellStatus;
  title: string;
  summary?: string;
  runtimeKind: "terminal" | "tool" | "status" | string;
  rawToolName?: string;
  durationSeconds?: number | null;
  exitCode?: number | null;
  timedOut?: boolean;
  tracePath?: string;
  error?: string;
  modelObservationSource?: "DirectToolCall" | string;
};

export type CodexToolCall = {
  toolCallId: string;
  rawOperationId: string;
  status: CodexTranscriptCellStatus;
  title: string;
  summary?: string;
  rawToolName?: string;
  runtimeKind: "terminal" | "tool" | string;
  sequence?: number;
  timestamp?: string;
  terminalOperationId?: string;
  tracePath?: string;
  error?: string;
  resultPreview?: string;
  resultType?: string;
  resultLength?: number | null;
  resultKind?: string;
  truncated?: boolean;
  originalLength?: number | null;
};

export type CodexTerminalRequest = {
  displayCommand?: string;
  command?: string[];
  cwd?: string;
};

export type CodexTerminalResult = {
  exitCode?: number | null;
  stdout?: string;
  stderr?: string;
  formattedOutput?: string;
  timedOut?: boolean;
};

export type CodexTerminalOperation = {
  operationId: string;
  toolCallId: string;
  terminalId: string;
  kind: "ExecCommand" | "WriteStdin" | string;
  status: CodexTranscriptCellStatus;
  request?: CodexTerminalRequest;
  result?: CodexTerminalResult;
  durationSeconds?: number | null;
  rawOperationId: string;
  tracePath?: string;
};

export type CodexTerminalSession = {
  terminalId: string;
  createdByOperationId: string;
  operationIds: string[];
  status: CodexTranscriptCellStatus;
};

export type CodexTerminalModelObservation = {
  operationId: string;
  toolCallId: string;
  source: "DirectToolCall" | string;
  callItemIds: string[];
  outputItemIds: string[];
};

export type CodexToolLifecycleModel = {
  toolCalls: CodexToolCall[];
  terminalOperations: CodexTerminalOperation[];
  terminalSessions: CodexTerminalSession[];
  modelObservations: CodexTerminalModelObservation[];
};

export type CodexTranscriptCell = {
  id: string;
  kind: CodexTranscriptCellKind;
  messageId: string;
  status: CodexTranscriptCellStatus;
  tone: CodexTranscriptCellTone;
  channel?: string;
  phase?: string;
  terminal?: boolean;
  provisional?: boolean;
  diagnosticSummary?: Record<string, unknown>;
  title?: string;
  text?: string;
  summary?: string;
  operationIds?: string[];
  rolloutTraceEvents?: CodexRolloutTraceEvent[];
  toolLifecycleModel?: CodexToolLifecycleModel;
  sourceItemId?: string;
};

export type CodexTranscriptProjection = CodexToolLifecycleModel & {
  version: 1 | number;
  source: "native" | "legacy" | string;
  messageId: string;
  streaming?: boolean;
  cells: CodexTranscriptCell[];
  rolloutEvents?: CodexRolloutTraceEvent[];
};

/**
 * One immutable item within an assistant turn.
 *
 * A turn is the only assistant conversation record.  Text, reasoning, tools,
 * retries and terminal state are separate revisioned items; callers must not
 * reconstruct a second assistant state from top-level message fields.
 */
export type SessionTurnItemStatus = "pending" | "running" | "completed" | "failed";

type SessionTurnItemBase = {
  /** Stable logical identity; `id` changes only when an item revision is emitted. */
  id: string;
  itemId: string;
  version: 3;
  sessionId: string;
  turnId: string;
  status: SessionTurnItemStatus;
  revision: number;
  sequence: number;
  createdAt?: string;
  updatedAt?: string;
  terminal?: boolean;
  title?: string;
  summary?: string;
  diagnosticSummary?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
};

export type AgentMessageTurnItem = SessionTurnItemBase & {
  type: "agent_message";
  phase: "commentary" | "final_answer";
  text: string;
};

export type ReasoningTurnItem = SessionTurnItemBase & {
  type: "reasoning";
  text: string;
};

export type ToolCallTurnItem = SessionTurnItemBase & {
  type: "tool_call";
  callId: string;
  toolName: string;
  input?: string;
  output?: string;
};

export type RetryTurnItem = SessionTurnItemBase & {
  type: "retry";
  attempt: number;
  targetItemId: string;
  reason: string;
};

export type StatusTurnItem = SessionTurnItemBase & {
  type: "status";
  code: string;
  text: string;
};

export type ErrorTurnItem = SessionTurnItemBase & {
  type: "error";
  code: string;
  text: string;
};

export type SessionTurnItem =
  | AgentMessageTurnItem
  | ReasoningTurnItem
  | ToolCallTurnItem
  | RetryTurnItem
  | StatusTurnItem
  | ErrorTurnItem;

export type MentalStateSnapshot = {
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
  intervention?: string;
  metrics?: Record<string, unknown>;
  historyTail?: Array<{
    cognitiveState: string;
    confidence: number;
    timestamp: string;
  }>;
};

export type SessionReferenceAttachment = {
  referenceId?: string;
  kind: "session" | string;
  sessionId: string;
  title?: string;
  agentId?: string;
  agentCode?: string;
  agentDisplayName?: string;
  summary?: string;
  createdAt?: string;
};

type ConversationMessageBase = {
  id: string;
  timestamp: string;
  metadata?: Record<string, unknown>;
};

export type UserConversationMessage = ConversationMessageBase & {
  role: "user";
  content: string;
  attachments?: ConversationAttachment[];
  references?: SessionReferenceAttachment[];
};

export type AssistantConversationTurn = ConversationMessageBase & {
  role: "assistant";
  turnId: string;
  status: SessionTurnItemStatus;
  turnItems: SessionTurnItem[];
};

export type ConversationMessage = UserConversationMessage | AssistantConversationTurn;

export type ConversationAttachment = {
  artifactId: string;
  filename: string;
  url: string;
  imageUrl: string;
  downloadUrl: string;
  contentType: string;
  sizeBytes: number;
  kind: string;
  status: string;
};

export type SessionTurnAcceptedResponse = {
  accepted: boolean;
  sessionId: string;
  turnId: string;
  clientSubmissionId: string;
  status: string;
  acceptedAt: string;
};

export type SessionGuidanceMode = "safe" | "interrupt";

export type SessionGuidancePayload = {
  content: string;
  mode: SessionGuidanceMode;
};

export type SessionDeleteResponse = {
  deleted: boolean;
  deletedSessionId: string;
  nextActiveSessionId: string;
};

export type SessionBulkDeleteResponse = {
  status: string;
  requestedSessionIds: string[];
  success: Array<{
    sessionId: string;
    deleted?: boolean;
    nextActiveSessionId?: string;
    replacementDirectSessionId?: string;
  }>;
  skipped: Array<{ sessionId: string; reason?: string; message?: string }>;
  failed: Array<{ sessionId: string; reason?: string; message?: string }>;
  summary: {
    requestedCount: number;
    successCount: number;
    skippedCount: number;
    failedCount: number;
  };
  nextActiveSessionId?: string;
  durationMs?: number;
};

export type SessionTurnError = {
  message: string;
  errorType: string;
  reasonCode?: string;
  reasonSummary?: string;
  reasonDetail?: string;
  httpStatus?: number | null;
  provider?: string;
  providerHost?: string;
  providerErrorType?: string;
  providerErrorMessage?: string;
  model?: string;
  chainStage?: string;
  eventCode?: string;
  traceId?: string;
  protocol?: string;
  recoverable: boolean;
  timestamp: string;
  turnId: string;
};

export type SessionRuntimeNotice = {
  id: string;
  kind: string;
  level: "info" | "warning" | "error" | "success";
  message: string;
  timestamp: string;
  source: string;
  turnId?: string;
  previousStatus?: string;
};

export type SessionToolApprovalRequest = {
  requestId: string;
  sessionId: string;
  turnId: string;
  agentId: string;
  callId: string;
  toolName: string;
  approval: string;
  risk: string;
  argumentsHash: string;
  argumentSummary: Record<string, unknown>;
  sessionGrantScope: Record<string, unknown>;
  decisionFingerprint: string;
  configRevision: number;
  configHash: string;
  permissionPreset: string;
  availableDecisions: Array<
    "accept" | "acceptForSession" | "acceptAlways" | "decline" | "cancel" | string
  >;
  createdAt: string;
  status: "pending" | "accepted" | "accepted_for_session" | "declined" | "cancelled" | "expired" | string;
  decision: string | null;
  resolvedAt: string | null;
};

export type ChatNextStateSignalSummary = {
  signalId: string;
  sessionId: string;
  turnId: string;
  source: string;
  kind: string;
  polarity: string;
  mode: string;
  relatedEventCode: string;
  createdAt: string;
  summary: string;
};

export type SessionContextCompositionSegment = {
  key: string;
  label: string;
  chars: number;
  tokens: number;
  itemCount: number;
  status: string;
  source: string;
  description: string;
};

export type SessionContextComposition = {
  turnId: string;
  recordedAt: string;
  source: string;
  totalChars: number;
  totalTokens: number;
  limitTokens: number;
  limitSource?: string;
  limitModelId?: string;
  limitAgentId?: string;
  segments: SessionContextCompositionSegment[];
};

export type SessionCacheCompositionSegment = {
  key: string;
  label: string;
  tokens: number;
  status: string;
  source?: string;
  description?: string;
  contentPreview?: string;
  cachePolicy?: string;
  order?: number;
  promptCategory?: string;
  segmentKind?: string;
  accuracy?: string;
  parentKey?: string;
  estimated?: boolean;
  observedStatus?: string;
  observedCachedInputTokens?: number;
  observedMissedInputTokens?: number;
  computedOverestimatedInputTokens?: number;
  providerExtraCachedInputTokens?: number;
  calibrationReason?: string;
};

export type SessionCacheComposition = {
  turnId: string;
  recordedAt: string;
  source: string;
  provider?: string;
  model?: string;
  llmModelId?: string;
  promptCacheScope?: string;
  promptCachePartition?: string;
  inputTokens: number;
  cachedInputTokens: number;
  cacheReadInputTokens?: number;
  cacheCreationInputTokens: number;
  uncachedInputTokens: number;
  cacheHitRate: number;
  cacheUsageObserved?: boolean;
  cacheUsageMissingReason?: string;
  segments: SessionCacheCompositionSegment[];
  computedInputTokens?: number;
  computedCachedInputTokens?: number;
  computedUncachedInputTokens?: number;
  computedCacheHitRate?: number;
  computedSegments?: SessionCacheCompositionSegment[];
  calibratedInputTokens?: number;
  calibratedCachedInputTokens?: number;
  calibratedCacheHitRate?: number;
  calibratedSegments?: SessionCacheCompositionSegment[];
  computedOverestimatedInputTokens?: number;
  providerExtraCachedInputTokens?: number;
  calibrationStatus?: string;
  calibrationReason?: string;
  averageInputTokens?: number;
  averageCachedInputTokens?: number;
  averageCacheHitRate?: number;
  averageObservedTurnCount?: number;
};

export type SessionLlmPayloadTraceSafeMap = Record<string, string | number | boolean | string[] | number[] | Record<string, unknown>>;

export type SessionLlmPayloadTrace = {
  schemaVersion?: number;
  traceId?: string;
  recordedAt?: string;
  phase?: string;
  stream?: boolean;
  role?: string;
  profileId?: string;
  provider?: string;
  model?: string;
  sessionId?: string;
  turnId?: string;
  agentId?: string;
  llmSlot?: string;
  modelId?: string;
  promptPurpose?: string;
  dialogueChainMode?: string;
  messageCount?: number;
  toolCount?: number;
  imageBlockCount?: number;
  messageRoleCounts?: Record<string, number>;
  messageRoles?: string[];
  transport?: string;
  selectedProtocol?: string;
  protocolSource?: string;
  payloadShape?: SessionLlmPayloadTraceSafeMap;
  promptCache?: SessionLlmPayloadTraceSafeMap;
  thinking?: SessionLlmPayloadTraceSafeMap;
  contextAssembly?: SessionLlmPayloadTraceSafeMap;
};

export type SessionMessageWindow = {
  mode: "window" | string;
  totalMessages: number;
  returnedMessages: number;
  oldestMessageIndex: number;
  newestMessageIndex: number;
  hasEarlier: boolean;
  hasLater: boolean;
  nextBeforeMessageIndex?: number | null;
  transcriptScope: "all" | "window" | "none" | string;
};

export type SessionDetail = SessionSummary & {
  ledgerSeq?: number;
  activeTurnId?: string;
  activeTask?: SessionActiveTask | null;
  defaultFileContext: string;
  previewTabs: string[];
  activePreviewPath: string;
  changedFiles: string[];
  readFiles: string[];
  messages: ConversationMessage[];
  messageWindow?: SessionMessageWindow;
  /**
   * Client-only: summary shell painted while the message window is still loading.
   * Never set by the API; cleared when a real detail/select payload arrives.
   */
  provisionalTranscript?: boolean;
  /** False when GET used includeSecondary=false (light poll). */
  secondaryHydrated?: boolean;
  runtimeNotices?: SessionRuntimeNotice[];
  contextUsage?: {
    used: number;
    limit: number;
    limitSource?: string;
    limitModelId?: string;
    limitAgentId?: string;
    limitError?: string;
    estimatedTokens: number;
    messageCount: number;
    userMessageCount: number;
    assistantMessageCount: number;
    toolCallCount: number;
    source: string;
  };
  cacheUsage?: {
    lastInputTokens: number;
    lastCachedInputTokens: number;
    lastCacheReadInputTokens?: number;
    lastCacheCreationInputTokens?: number;
    lastUncachedInputTokens?: number;
    turnInputTokens: number;
    turnCachedInputTokens: number;
    turnCacheReadInputTokens?: number;
    turnCacheCreationInputTokens?: number;
    turnUncachedInputTokens?: number;
    turnCacheHitRate: number;
    totalInputTokens: number;
    totalCachedInputTokens: number;
    totalCacheReadInputTokens?: number;
    totalCacheCreationInputTokens?: number;
    totalUncachedInputTokens?: number;
    totalCacheHitRate: number;
    totalObservedTurnCount?: number;
    cacheUsageObserved?: boolean;
    cacheUsageMissingReason?: string;
    updatedAt: string;
    source: string;
  };
  llmUsage?: SessionLlmUsage | null;
  lastContextComposition?: SessionContextComposition | null;
  lastLlmPayloadTrace?: SessionLlmPayloadTrace | null;
  lastCacheComposition?: SessionCacheComposition | null;
  handoffContext?: SessionChildHandoffContext | null;
  lastTurnError?: SessionTurnError | null;
  nextStateSignals?: ChatNextStateSignalSummary[];
  groupContextEvents?: GroupContextEvent[];
  agentInboxMessages?: AgentInboxMessage[];
  pendingToolGovernanceRequests?: AgentToolGovernanceRequest[];
  toolPolicy?: ToolPolicy | null;
  memoryPolicy?: MemoryPolicy | null;
  stopRequested: boolean;
  stopRequestedAt: string;
  stopReason: string;
};

export type SessionLlmUsage = {
  source: "provider_usage" | "missing" | "not_called" | "estimated" | string;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  cachedInputTokens: number;
  cacheReadInputTokens?: number;
  cacheCreationInputTokens: number;
  uncachedInputTokens: number;
  cacheHitRate: number;
  cacheUsageObserved?: boolean;
  cacheUsageMissingReason?: string;
  provider: string;
  model: string;
  recordedAt: string;
};

export type SessionDetailStreamEvent = {
  type: "session_detail";
  sessionId: string;
  ledgerSeq?: number;
  detail: SessionDetail;
};

export type SessionInitialStreamEvent = {
  type: "session_initial";
  sessionId: string;
  ledgerSeq?: number;
  summary: SessionSummary;
  latestMessage?: {
    id: string;
    role: string;
    timestamp: string;
    contentLength: number;
    thoughtLength: number;
    feedbackEventCount: number;
    toolCallCount: number;
    streaming: boolean;
  };
  activeTurnId?: string;
  running?: boolean;
  currentPhase?: string;
  updatedAt?: string;
};

export type SessionAssistantDeltaStreamEvent = {
  type: "assistant_delta";
  sessionId: string;
  turnId: string;
  ledgerSeq?: number;
  stage: string;
  turnItems: SessionTurnItem[];
  updatedAt: string;
  done: boolean;
};

export type SessionStreamEvent = SessionDetailStreamEvent | SessionInitialStreamEvent | SessionAssistantDeltaStreamEvent;

export type SessionChatReviewCandidateResponse = {
  candidateId: string;
  status: string;
  sessionId: string;
  topicSummary: string;
  turnCount: number;
  qualitySignals: string[];
  rawExcerptPath: string;
  summary: string;
};

export type ChatRoomMode = {
  id: string;
  label: string;
  status: "ready" | "planned" | string;
};

export type ChatRoomPurpose = {
  id: "chat" | "discussion" | "meeting" | string;
  label: string;
  description?: string;
};

export type ChatRoomParticipant = {
  participantId: string;
  kind: string;
  agentId?: string;
  agentCode?: string;
  agentAvatarImageUrl?: string;
  directSessionId?: string;
  sessionId: string;
  title: string;
  workspacePath?: string;
  teamId?: string;
  teamName?: string;
  teamPurpose?: string;
  teamRole?: string;
  teamMemberPurpose?: string;
  teamResponsibilities?: string[];
  agentMissing?: boolean;
  agentStatusCode?: string;
  agentStatusMessage?: string;
  enabled: boolean;
  status: string;
  recentMessages?: Array<{
    role: string;
    content: string;
  }>;
};

export type ChallengeMeetingDisplaySection = {
  title: string;
  bullets: string[];
};

export type ChallengeMeetingDisagreement = {
  issue: string;
  positions: string[];
  unresolvedReason?: string;
};

export type ChallengeMeetingActionItem = {
  ownerRoleId: string;
  action: string;
  dueGate?: string;
};

export type ChallengeMeetingEvidenceRequest = {
  rationale: string;
  candidateRefs?: string[];
  searchEnvelope?: {
    keywords?: string[];
    sourceTypes?: string[];
    evidenceLevels?: string[];
  };
  requirements?: {
    minEvidenceLevel?: string;
    completeness?: string;
  };
};

export type ChallengeMeetingMessagePayload = {
  schemaVersion: 1;
  kind: "challenge_meeting_message";
  display: {
    conclusion: string;
    sections: ChallengeMeetingDisplaySection[];
  };
  protocol: {
    agreements: string[];
    disagreements: ChallengeMeetingDisagreement[];
    risks: string[];
    actionItems: ChallengeMeetingActionItem[];
    knowledgeCandidates: unknown[];
    proposedCandidates: unknown[];
    evidenceRequests: ChallengeMeetingEvidenceRequest[];
  };
  audit: {
    parseStatus: "structured" | "invalid" | string;
    rawModelOutput: string;
    errorCode?: string;
    errorMessage?: string;
  };
};

export type ChatRoomMessage = {
  messageId: string;
  participantId: string;
  agentId?: string;
  speakerCode?: string;
  sessionId: string;
  speakerTitle: string;
  status: string;
  resultStatus?: string;
  content: string;
  summary: string;
  messageKind?: "user_clarification" | "team_discussion" | "team_message" | string;
  audience?: "user" | "internal" | string;
  visibility?: "collapsed_by_default" | "default" | string;
  messagePayload?: ChallengeMeetingMessagePayload;
  errorType?: string;
  supervision?: AgentSupervisionDecision;
  timestamp: string;
};

export type ChatRoomRound = {
  roundId: string;
  roomId: string;
  topic: string;
  mode: string;
  purpose: string;
  config: Record<string, unknown>;
  caseState?: TeamCaseState;
  status: string;
  speakerOrder: string[];
  messages: ChatRoomMessage[];
  messagesTruncated?: boolean;
  messagesTotalCount?: number;
  summary: string;
  startedAt: string;
  updatedAt: string;
  finishedAt: string;
};

export type ChatRoomRoundAcceptedResponse = {
  accepted: boolean;
  roomId: string;
  roundId: string;
  activeRoundId: string;
  status: string;
  topic: string;
  mode: string;
  purpose: string;
  speakerOrder: string[];
  acceptedAt: string;
};

export type ChatRoomDetail = {
  roomId: string;
  title: string;
  mode: string;
  purpose: string;
  config: Record<string, unknown>;
  participants: ChatRoomParticipant[];
  rounds: ChatRoomRound[];
  status: string;
  activeRoundId: string;
  createdAt: string;
  updatedAt: string;
  availableModes: ChatRoomMode[];
  availablePurposes: ChatRoomPurpose[];
};

export type ChatRoomStreamEvent = {
  type: "chat_room_detail" | string;
  roomId: string;
  detail: ChatRoomDetail;
};

/**
 * Speaker streaming delta frame pushed on the group room SSE stream.
 * Field-level contract with the backend chat_room_stream_capture fan-out:
 * `content` is the CUMULATIVE answer text (a full snapshot per frame, not an
 * append-only chunk); `seq` is monotonically increasing per
 * (roundId, participantId), so frames that are not strictly newer are dropped
 * as late/reordered; a `done` frame with a terminal `status` ends the stream,
 * and the authoritative `chat_room_detail` snapshot always overrides whatever
 * the streaming buffer holds.
 */
export type ChatRoomSpeakerDeltaEvent = {
  type: "chat_room_speaker_delta";
  roomId: string;
  roundId: string;
  participantId: string;
  sessionId: string;
  turnId: string;
  seq: number;
  stage: string;
  content: string;
  done: boolean;
  status: string;
};
