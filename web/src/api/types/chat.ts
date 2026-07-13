import type { ProjectionEditContract, SourceAuthorityRef } from "./shared";
import type { TeamCaseState } from "./teams";
import type { AgentInboxMessage, AgentSupervisionDecision, AgentToolGovernanceRequest, GroupContextEvent, MemoryPolicy, ToolPolicy } from "./agents";

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
  currentPhase: string;
  sessionKind?: "main" | "child" | string;
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
};

export type SessionLlmReasoningEffortOption = {
  value: string;
  label: string;
  description: string;
};

export type SessionLlmModelOption = {
  modelId: string;
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
};

export type SessionLlmOptions = {
  sessionId: string;
  currentModelId: string;
  currentReasoningEffort: string;
  models: SessionLlmModelOption[];
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
  capturedAt?: string;
  agentId?: string;
  agentCode?: string;
  agentDisplayName?: string;
  reason?: string;
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
  name: string;
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
  displayCommand: string;
  command?: string[];
  cwd: string;
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
  request: CodexTerminalRequest;
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

export type SessionTurnItemType =
  | "agent_message"
  | "reasoning"
  | "tool_call"
  | "status"
  | "error"
  | string;

export type SessionTurnItemStatus =
  | "pending"
  | "running"
  | "in_progress"
  | "completed"
  | "failed"
  | "degraded"
  | string;

export type SessionTurnItem = {
  id: string;
  type: SessionTurnItemType;
  status: SessionTurnItemStatus;
  version?: number;
  sessionId?: string;
  turnId?: string;
  invocationId?: string;
  iteration?: number;
  itemId?: string;
  revision?: number;
  sequence?: number;
  kind?: string;
  channel?: string;
  phase?: string;
  protocol?: string;
  provisional?: boolean;
  terminal?: boolean;
  callId?: string;
  toolName?: string;
  messageId?: string;
  source?: string;
  sourceCellId?: string;
  sourceCellKind?: string;
  sourceItemId?: string;
  operationIds?: string[];
  title?: string;
  summary?: string;
  text?: string;
  diagnosticSummary?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
};

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

export type ConversationMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  thought?: string;
  streamStage?: string;
  mentalSnapshot?: MentalStateSnapshot;
  feedbackEvents?: ConversationFeedbackEvent[];
  timelineItems?: ConversationTimelineItem[];
  codexTranscript?: CodexTranscriptProjection;
  itemId?: string;
  turnItems?: SessionTurnItem[];
  streaming?: boolean;
  toolCalls?: ToolCall[];
  attachments?: ConversationAttachment[];
  references?: SessionReferenceAttachment[];
  metadata?: Record<string, unknown>;
};

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
  activeTask?: SessionActiveTask | null;
  defaultFileContext: string;
  previewTabs: string[];
  activePreviewPath: string;
  changedFiles: string[];
  readFiles: string[];
  messages: ConversationMessage[];
  messageWindow?: SessionMessageWindow;
  runtimeNotices?: SessionRuntimeNotice[];
  contextUsage?: {
    used: number;
    limit: number;
    limitSource?: string;
    limitModelId?: string;
    limitAgentId?: string;
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
  content: string;
  thought: string;
  contentDelta?: string;
  thoughtDelta?: string;
  replaceContent?: boolean;
  replaceThought?: boolean;
  feedbackEvents?: ConversationFeedbackEvent[];
  timelineItems?: ConversationTimelineItem[];
  codexTranscript?: CodexTranscriptProjection;
  itemId?: string;
  turnItems?: SessionTurnItem[];
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
