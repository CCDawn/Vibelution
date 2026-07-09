import type { ProjectionEditContract, SourceAuthorityRef } from "./shared";
import type { AgentInstance } from "./agents";
import type { KnowledgeGovernanceTask, KnowledgeGovernanceTasksPayload } from "./memory";

export type KnowledgeBasePermissions = {
  canRead: boolean;
  canPropose: boolean;
  canReview: boolean;
  canRate: boolean;
};

export type TeamKnowledgeBase = {
  knowledgeBaseId: string;
  scopedKnowledgeBaseId?: string;
  ownerType?: "team" | "agent" | "shared" | string;
  ownerId?: string;
  teamId: string;
  teamName: string;
  agentId?: string;
  agentName?: string;
  name: string;
  description: string;
  status: string;
  acl: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
  stats: {
    sourceArtifactCount: number;
    pendingProposalCount: number;
    proposalCount: number;
    itemCount: number;
    batchCount: number;
  };
  pendingProposals: KnowledgeRefinementProposal[];
  permissions: KnowledgeBasePermissions;
};

export type TeamKnowledgeOverview = {
  schemaVersion: number;
  agentId: string;
  summary: {
    knowledgeBaseCount: number;
    pendingProposalCount: number;
    itemCount: number;
    sourceArtifactCount: number;
  };
  knowledgeBases: TeamKnowledgeBase[];
  updatedAt: string;
};

export type KnowledgeStewardOverview = {
  schemaVersion: number;
  steward: {
    agentId: string;
    agentCode: string;
    displayName: string;
    functionalDisplayName: string;
    status: string;
    directSessionId: string;
    directChatPath: string;
    managedDomain: string;
    permissionBoundary: string;
    protected: boolean;
    taskProfile: {
      mission?: string;
      responsibilities?: string;
      preferredTasks?: string;
      avoidTasks?: string;
      successCriteria?: string;
      deliverables?: string;
      constraints?: string;
      handoffNotes?: string;
      taskTypes?: string[];
    };
    toolPolicy: {
      policyId: string;
      allowedTools: string[];
      preferredTools: string[];
      networkAccess: string;
      mutationAccess: string;
      maxCallsPerTurn: number;
    };
    memoryPolicy: {
      policyId: string;
      readSharedGroups: string[];
      writeSharedGroups: string[];
      readKnowledgeBaseIds: string[];
      proposeKnowledgeBaseIds: string[];
      reviewKnowledgeBaseIds: string[];
      rateKnowledgeBaseIds: string[];
    };
  };
  governance: {
    summary: {
      taskCount: number;
      openTaskCount: number;
      proposalReviewCount: number;
      ratingReviewCount: number;
      sourceNeedsProposalCount: number;
    };
    openTasks: KnowledgeGovernanceTask[];
  };
  operatingBoundary: {
    canDirectlyApplyKnowledge: boolean;
    canDirectlyIngestScreenedSources: boolean;
    canDeleteKnowledge: boolean;
    canChangeAcl: boolean;
    canBypassReviewer: boolean;
    formalKnowledgeRequiresReviewer: boolean;
    screeningAgentIsReviewer: boolean;
    knowledgeBodiesInPrompt: boolean;
  };
  updatedAt: string;
};

export type KnowledgeStewardRecommendation = {
  recommendationId: string;
  taskId: string;
  taskType: string;
  recommendedAction: "review_proposal" | "review_rating_suggestion" | "draft_refinement_proposal" | "inspect_task" | string;
  priority: string;
  teamId: string;
  teamName: string;
  knowledgeBaseId: string;
  knowledgeBaseName: string;
  targetId: string;
  targetStatus: string;
  title: string;
  summary: string;
  reason: string;
  nextStep: string;
  requiresReviewer: boolean;
  canExecuteWithCurrentActor: boolean;
  sourceArtifactIds: string[];
  createdAt: string;
  updatedAt: string;
};

export type KnowledgeStewardRecommendationsPayload = {
  schemaVersion: number;
  agentId: string;
  stewardAgentId: string;
  recommendations: KnowledgeStewardRecommendation[];
  summary: {
    recommendationCount: number;
    visibleRecommendationCount: number;
    proposalReviewCount: number;
    ratingReviewCount: number;
    proposalDraftCount: number;
  };
  operatingBoundary: {
    canDirectlyApplyKnowledge: boolean;
    canDeleteKnowledge: boolean;
    canChangeAcl: boolean;
    canBypassReviewer: boolean;
    recommendationsOnly: boolean;
    formalKnowledgeRequiresReviewer: boolean;
  };
  updatedAt: string;
};

export type KnowledgeStewardWorkbenchPayload = {
  schemaVersion: number;
  agentId: string;
  steward: KnowledgeStewardOverview["steward"];
  summary: KnowledgeGovernanceTasksPayload["summary"] & {
    recommendationCount: number;
    visibleRecommendationCount: number;
    stageCount: number;
    blockedStageCount: number;
  };
  stages: Array<{
    stageId: string;
    title: string;
    description: string;
    recommendedAction: string;
    nextTool: string;
    openCount: number;
    executableCount: number;
    blockedCount: number;
    status: "clear" | "actionable" | "needs_permission_or_reviewer" | string;
    items: KnowledgeStewardRecommendation[];
  }>;
  nextActions: Array<{
    actionId: string;
    recommendedAction: string;
    priority: string;
    title: string;
    knowledgeBaseId: string;
    knowledgeBaseName: string;
    targetId: string;
    requiresReviewer: boolean;
    canExecuteWithCurrentActor: boolean;
    nextStep: string;
  }>;
  acceptanceChecklist: Array<{
    id: string;
    label: string;
    required: boolean;
  }>;
  operatingBoundary: KnowledgeStewardRecommendationsPayload["operatingBoundary"] & {
    knowledgeBodiesInPrompt?: boolean;
  };
  updatedAt: string;
};

export type KnowledgeSourceArtifact = {
  sourceArtifactId: string;
  ownerType?: "team" | "agent" | "shared" | string;
  ownerId?: string;
  teamId: string;
  agentId?: string;
  knowledgeBaseId: string;
  sourceType: string;
  sourceRef: Record<string, unknown>;
  capturedAt: string;
  sourceCreatedAt: string;
  capturedBy: string;
  sourceHash: string;
  evidenceRange: Record<string, unknown>;
  title: string;
  summary: string;
  centralSourceId?: string;
  inboxSourceId?: string;
  curationStatus?: string;
};

export type KnowledgeRefinementProposal = {
  proposalId: string;
  teamId: string;
  targetKnowledgeBaseId: string;
  sourceArtifactIds: string[];
  centralSourceIds?: string[];
  proposedByAgentId: string;
  status: string;
  title: string;
  summary: string;
  content: string;
  tags: string[];
  createdAt: string;
  updatedAt: string;
  reviewedAt: string;
  reviewedByAgentId: string;
  resolutionNote: string;
  batchId: string;
  knowledgeItemIds: string[];
};

export type KnowledgeBatch = {
  batchId: string;
  teamId: string;
  knowledgeBaseId: string;
  proposalIds: string[];
  sourceArtifactIds: string[];
  centralSourceIds?: string[];
  reviewedByAgentId: string;
  appliedAt: string;
  status: string;
};

export type KnowledgeItem = {
  knowledgeItemId: string;
  teamId: string;
  knowledgeBaseId: string;
  batchId: string;
  sourceArtifactIds: string[];
  centralSourceIds?: string[];
  title: string;
  summary: string;
  content: string;
  tags: string[];
  importanceLevel: "low" | "medium" | "high" | "critical" | string;
  confidence: number;
  stability: "temporary" | "evolving" | "stable" | "deprecated" | string;
  scope: "agent" | "team" | "project" | "global" | string;
  reviewPriority: "normal" | "elevated" | "urgent" | string;
  createdAt: string;
  updatedAt: string;
  reviewedAt: string;
  appliedAt: string;
  reviewedByAgentId: string;
  markedBy: string;
  markedAt: string;
  markingReason: string;
};

export type KnowledgeReviewResponse = {
  proposal: KnowledgeRefinementProposal;
  batch: KnowledgeBatch | null;
  item: KnowledgeItem | null;
};

export type KnowledgeIngestionPackageResponse = {
  schemaVersion: number;
  teamId: string;
  knowledgeBaseId: string;
  status: string;
  sourceArtifact: KnowledgeSourceArtifact;
  proposal: KnowledgeRefinementProposal;
  updatedAt: string;
};

export type KnowledgeItemsPayload = {
  schemaVersion: number;
  teamId: string;
  knowledgeBase: TeamKnowledgeBase;
  items: KnowledgeItem[];
  summary: {
    itemCount: number;
  };
  updatedAt: string;
};

export type KnowledgeRatingSuggestion = {
  suggestionId: string;
  teamId: string;
  knowledgeBaseId: string;
  targetType: "proposal" | "knowledge_item" | string;
  knowledgeItemId: string;
  proposalId: string;
  suggestedByAgentId: string;
  importanceLevel: string;
  confidence: number;
  stability: string;
  reviewPriority: string;
  markingReason: string;
  status: "pending" | "applied" | "rejected" | string;
  createdAt: string;
  updatedAt: string;
  reviewedByAgentId: string;
  reviewedAt: string;
  resolutionNote: string;
};

export type KnowledgeRatingSuggestionsPayload = {
  schemaVersion: number;
  teamId: string;
  knowledgeBase: TeamKnowledgeBase;
  suggestions: KnowledgeRatingSuggestion[];
  summary: {
    suggestionCount: number;
    pendingSuggestionCount: number;
  };
  updatedAt: string;
};

export type KnowledgeRatingSuggestionReviewResponse = {
  suggestion: KnowledgeRatingSuggestion;
  item: KnowledgeItem | null;
};

export type KnowledgeRatingSuggestionBulkReviewResponse = {
  schemaVersion: number;
  teamId: string;
  knowledgeBaseId: string;
  status: string;
  reviewed: KnowledgeRatingSuggestionReviewResponse[];
  skipped: Array<{
    suggestionId: string;
    reason: string;
  }>;
  summary: {
    requestedCount: number;
    reviewedCount: number;
    skippedCount: number;
    appliedItemCount: number;
  };
  updatedAt: string;
};

export type KnowledgeSearchResult = KnowledgeItem & {
  knowledgeBaseName: string;
  ownerType?: "team" | "agent" | "shared" | string;
  ownerId?: string;
  teamName: string;
  agentName?: string;
  sourceTypes: string[];
  semanticScore: number;
  searchMode: "exact" | "semantic" | "hybrid" | string;
  matchReason: string;
  sourceSummaries: Array<{
    sourceArtifactId: string;
    centralSourceId?: string;
    sourceType: string;
    capturedAt: string;
    title: string;
    summary: string;
  }>;
};

export type KnowledgeSearchPayload = {
  schemaVersion: number;
  agentId: string;
  filters: Record<string, unknown>;
  summary: {
    resultCount: number;
    scannedKnowledgeBaseCount: number;
  };
  results: KnowledgeSearchResult[];
  updatedAt: string;
};

export type TeamMember = {
  memberId: string;
  agentId: string;
  agentCode: string;
  agentName: string;
  role: string;
  purpose: string;
  responsibilities?: string[];
  agentStatus: "active" | "stale" | string;
};

export type TeamCanvasNode = {
  id: string;
  label: string;
  type: "role" | "agent" | "group" | "user" | "external" | string;
  status: "bound" | "unbound" | "stale" | string;
  x: number;
  y: number;
  agentId: string;
  agentCode: string;
  agentName: string;
  agentSourceRef?: SourceAuthorityRef | null;
  agentProjectionEdit?: ProjectionEditContract | null;
  agentProjectionCanWrite?: boolean;
  role: string;
  purpose: string;
  responsibilities?: string[];
};

export type TeamCanvasEdge = {
  id: string;
  source: string;
  target: string;
  label: string;
  type: "reports_to" | "communication" | "collaborates_with" | "delegates_to" | "observes" | "supports" | string;
};

export type TeamCanvasValidationIssue = {
  severity: "error" | "warning" | string;
  code: string;
  message: string;
  nodeId?: string;
  edgeId?: string;
  source?: string;
  target?: string;
};

export type TeamCanvasValidation = {
  valid: boolean;
  summary: {
    errorCount: number;
    warningCount: number;
    issueCount?: number;
  };
  issues: TeamCanvasValidationIssue[];
};

export type TeamOrganizationCanvas = {
  schemaVersion: number;
  canvasKind: "team_organization_canvas" | string;
  teamId: string;
  updatedAt: string;
  path: string;
  viewport: {
    x: number;
    y: number;
    zoom: number;
  };
  nodes: TeamCanvasNode[];
  edges: TeamCanvasEdge[];
  validation?: TeamCanvasValidation;
};

export type TeamConversationProjection = {
  teamId: string;
  linkedRoomId: string;
  status: "unlinked" | "linked" | "room_missing" | "agent_missing" | "membership_conflict" | string;
  memberAgentIds: string[];
  roomAgentIds: string[];
  missingAgentIds: string[];
  missingAgentCount: number;
};

export type AiSearchSourceScopeSource = {
  sourceId: string;
  name: string;
  url: string;
  region: string;
  language: string;
  sourceType: string;
  tier: string;
  evidenceRole: string;
  enabledByDefault: boolean;
  ownerRole: string;
  tags: string[];
};

export type AiSearchSourceScopeGroup = {
  groupId: string;
  label: string;
  tier: string;
  evidenceRole: string;
  enabledByDefault: boolean;
  ownerRole: string;
  description: string;
  sourceCount: number;
  sources: AiSearchSourceScopeSource[];
};

export type AiSearchSourceScope = {
  schemaVersion: number;
  scopeId: string;
  teamId: string;
  title: string;
  description: string;
  curatedAt: string;
  policy: {
    defaultEnabledTiers: string[];
    signalTiers: string[];
    requiresPrimaryEvidenceForConclusion: boolean;
    dedupeBy: string[];
    writesFormalKnowledge: boolean;
  };
  summary: {
    groupCount: number;
    sourceCount: number;
    enabledByDefaultCount: number;
    signalOnlyCount: number;
  };
  groups: AiSearchSourceScopeGroup[];
  storage: {
    path: string;
  };
};

export type AiSearchRunReference = {
  title: string;
  url: string;
};

export type AiSearchRunQuery = {
  queryId: string;
  query: string;
  sourceId: string;
  sourceName: string;
  sourceUrl: string;
  sourceType: string;
  groupId: string;
  groupLabel: string;
  tier: string;
  evidenceRole: string;
  enabledByDefault: boolean;
};

export type AiSearchRunCard = {
  cardId: string;
  queryId: string;
  sourceId: string;
  sourceName: string;
  sourceUrl: string;
  sourceType: string;
  groupId: string;
  groupLabel: string;
  tier: string;
  evidenceRole: string;
  query: string;
  status: "succeeded" | "failed" | string;
  searchMode?: "web_search" | "source_page_fallback" | string;
  degraded?: boolean;
  fallbackReason?: string;
  summary: string;
  resultText?: string;
  references: AiSearchRunReference[];
  createdAt: string;
  updatedAt: string;
};

export type AiSearchRunSummary = {
  runId: string;
  teamId: string;
  title: string;
  topic: string;
  status: "running" | "completed" | "partial" | "failed" | string;
  createdAt: string;
  updatedAt: string;
  queryCount: number;
  cardCount: number;
  succeededCount: number;
  failedCount: number;
  degradedCount?: number;
  referenceCount: number;
  runPath: string;
  cards: AiSearchRunCard[];
};

export type AiSearchRun = {
  schemaVersion: number;
  runId: string;
  teamId: string;
  title: string;
  topic: string;
  status: "running" | "completed" | "partial" | "failed" | string;
  createdAt: string;
  updatedAt: string;
  sourceScope: {
    scopeId: string;
    sourceScopePath: string;
    defaultEnabledTiers: string[];
    requiresPrimaryEvidenceForConclusion: boolean;
  };
  queryPlan: {
    queryCount: number;
    sourceLimit: number;
    maxResultsPerQuery: number;
    includeSignals: boolean;
    queries: AiSearchRunQuery[];
  };
  cards: AiSearchRunCard[];
  errors: Array<{ queryId: string; sourceId: string; message: string }>;
  summary: {
    cardCount: number;
    succeededCount: number;
    failedCount: number;
    degradedCount?: number;
    referenceCount: number;
  };
  storage: {
    runPath: string;
    runsPath: string;
  };
};

export type AiSearchRunListPayload = {
  schemaVersion: number;
  teamId: string;
  runs: AiSearchRunSummary[];
  summary: {
    runCount: number;
    visibleRunCount: number;
  };
  storage: {
    runsPath: string;
    runsRoot: string;
  };
  updatedAt: string;
};

export type Team = {
  teamId: string;
  name: string;
  description: string;
  purpose: string;
  status: "active" | "archived" | string;
  teamKind: "custom" | "research" | "ai_search" | "self_evolution" | "supervised_evolution" | "template_demo" | string;
  teamCategory: string;
  teamSource: "manual" | "research_organization" | "ai_search" | "self_evolution" | "supervised_evolution" | "team_template" | string;
  teamTemplateId?: string;
  sourceScopePath?: string;
  sourceScope?: AiSearchSourceScope;
  members: TeamMember[];
  memberCount: number;
  linkedChatRoomId?: string;
  linkedChatRoom?: {
    roomId: string;
    title: string;
    status: string;
    mode: string;
    purpose: string;
    participantCount: number;
    updatedAt: string;
  } | null;
  conversation?: TeamConversationProjection;
  canvasPath: string;
  createdAt: string;
  updatedAt: string;
  canvas: TeamOrganizationCanvas | {
    path: string;
    nodeCount: number;
    edgeCount: number;
    validation?: TeamCanvasValidation;
  };
};

export type TeamListPayload = {
  schemaVersion: number;
  teams: Team[];
  summary: {
    teamCount: number;
    activeTeamCount: number;
    memberCount: number;
    staleMemberCount: number;
  };
  updatedAt: string;
  storage: {
    teamsPath: string;
    teamRoot: string;
  };
  systemTeamBootstrap?: {
    schemaVersion: number;
    status: "idle" | "ready" | "running" | "needs_retry" | "failed" | string;
    requiredSteps: string[];
    reason: string;
    startedAt: string;
    finishedAt: string;
    lastError: string;
    elapsedMs: number;
    attempt: number;
    requestId?: string;
  };
};

export type TeamTemplateSummary = {
  templateId: string;
  name: string;
  description: string;
  purpose: string;
  defaultTeamName: string;
  roleCount: number;
  safetyLevel: string;
  chatRoom: {
    mode: string;
    purpose: string;
  };
};

export type TeamTemplateListPayload = {
  schemaVersion: number;
  templates: TeamTemplateSummary[];
  summary: {
    templateCount: number;
  };
  updatedAt: string;
};

export type TeamTemplateInstantiatePayload = {
  schemaVersion: number;
  template: TeamTemplateSummary;
  team: Team;
  createdAgents: AgentInstance[];
  linkedChatRoom?: Team["linkedChatRoom"];
  updatedAt: string;
};

export type TeamWorkflowStateNode = {
  nodeId: string;
  label: string;
};

export type TeamWorkflowTransition = {
  from: string;
  to: string;
  type?: string;
};

export type TeamWorkflowActiveItem = {
  candidateId: string;
  currentNode: string;
  status: string;
  pendingTransferId: string;
  updatedAt: string;
};

export type TeamWorkflowCandidateStoreSummary = {
  schemaVersion: number;
  candidateCount: number;
  candidateTypes: string[];
  updatedAt: string;
  storagePath: string;
};

export type TeamWorkflowOrchestration = {
  schemaVersion: number;
  workflowId: string;
  teamId: string;
  workflowKind: "challenge_cup_research" | string;
  status: string;
  ownerAgentId: string;
  stateMachine: {
    currentStage: string;
    nodes: TeamWorkflowStateNode[];
    transitions: TeamWorkflowTransition[];
  };
  routingPolicy: {
    coordinationAgentId: string;
    functionalAgentsMayRequestTransfer: boolean;
    finalStateWriter: string;
  };
  transferPolicy: {
    requiresUserConfirmation: boolean;
    requestedBy: string;
    decidedBy: string;
    recordDecidedByAgent: boolean;
  };
  activeWorkflowItems: TeamWorkflowActiveItem[];
  candidateStore: TeamWorkflowCandidateStoreSummary;
  transferRecordsPath: string;
  storagePath: string;
  createdAt: string;
  updatedAt: string;
};

export type DataProcessingRecord = {
  schemaVersion: number;
  recordId: string;
  runId: string;
  sourceType: string;
  sourceRef: string;
  rawLocation: string;
  title: string;
  summary: string;
  status: string;
  metadata: Record<string, unknown>;
  qualitySignals: Record<string, unknown>;
  collectionTrace: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
};

export type DataProcessingRun = {
  schemaVersion: number;
  runId: string;
  profileId: string;
  title: string;
  status: string;
  scope: Record<string, unknown> & {
    teamId?: string;
    workflowKind?: string;
    topic?: string;
    goal?: string;
    dataSearchPlanRef?: {
      planId?: string;
      planKind?: string;
      status?: string;
      queryCount?: number;
      externalSearchTriggered?: boolean;
      promptCachePolicyId?: string;
      promptCacheRequirement?: string;
      promptCacheGateStatus?: string;
    };
    promptCachePolicyRef?: TeamWorkflowSourceCollectionPromptCachePolicyRef;
  };
  metadata: Record<string, unknown> & {
    startedFrom?: string;
    teamId?: string;
    requestedByAgent?: string;
    ownerAgentId?: string;
    searchPlanId?: string;
    queryCount?: number;
    querySeedCount?: number;
    promptCachePolicyId?: string;
    promptCacheRequirement?: string;
    promptCacheModelId?: string;
    promptCacheMode?: string;
    promptCacheGateStatus?: string;
  };
  summary?: DataProcessingStatus["summary"];
  storage: {
    runPath: string;
    recordsPath: string;
    collectionAssignmentsPath: string;
    collectionOutputsPath: string;
    eventsPath: string;
  };
  createdAt: string;
  updatedAt: string;
};

export type DataProcessingRunListPayload = {
  schemaVersion: number;
  runs: DataProcessingRun[];
  summary: {
    runCount: number;
    returnedCount: number;
  };
};

export type DataProcessingStatus = {
  schemaVersion: number;
  runId: string;
  profileId: string;
  runStatus: string;
  summary: {
    recordCount: number;
    assignmentCount: number;
    openAssignmentCount: number;
    searchAssignmentCount?: number;
    searchOpenAssignmentCount?: number;
    collectionAssignmentCount?: number;
    collectionOpenAssignmentCount?: number;
    downstreamAssignmentCount?: number;
    downstreamOpenAssignmentCount?: number;
    outputCount: number;
    recordStatusCounts: Record<string, number>;
    sourceTypeCounts: Record<string, number>;
    assignmentStatusCounts: Record<string, number>;
  };
  nextActions: Array<{
    action: string;
    reason: string;
  }>;
  boundaries: {
    generic: boolean;
    writesFormalKnowledge: boolean;
    writesRag: boolean;
    writesKnowledgeGraph: boolean;
    requiresDownstreamPublisher: boolean;
  };
};

export type DataProcessingCollectionAssignment = {
  schemaVersion: number;
  assignmentId: string;
  runId: string;
  agentRole: string;
  agentId: string;
  status: string;
  scope: Record<string, unknown> & {
    assignedQueries?: TeamWorkflowSourceCollectionQuery[];
    queryCount?: number;
    dataSearchPlanRef?: DataProcessingRun["scope"]["dataSearchPlanRef"];
    resultWritebackContract?: TeamWorkflowSourceCollectionWritebackContract;
    promptCachePolicyRef?: TeamWorkflowSourceCollectionPromptCachePolicyRef;
    promptCachePartition?: string;
    conversationTraceRequired?: boolean;
  };
  inputRefs: string[];
  expectedRecordTypes: string[];
  acceptance: Record<string, unknown> & {
    resultWritebackContract?: TeamWorkflowSourceCollectionWritebackContract;
    noFormalKnowledgeWrite?: boolean;
  };
  createdAt: string;
  updatedAt: string;
};

export type DataProcessingCollectionAssignmentListPayload = {
  schemaVersion: number;
  runId: string;
  assignments: DataProcessingCollectionAssignment[];
  summary: {
    assignmentCount: number;
    assignmentStatusCounts: Record<string, number>;
  };
};

export type DataProcessingCollectionOutputPayload = {
  output: {
    schemaVersion: number;
    outputId: string;
    runId: string;
    assignmentId: string;
    agentRole: string;
    agentId: string;
    status: string;
    recordIds: string[];
    notes: string;
    qualitySignals: Record<string, unknown>;
    blockingIssues: string[];
    createdAt: string;
  };
  createdRecords: DataProcessingRecord[];
};

export type TeamWorkflowSourceCollectionPromptCachePolicyRef = {
  policyId?: string;
  scope?: string;
  requirement?: string;
  modelId?: string;
  promptCacheMode?: string;
  gateStatus?: string;
};

export type TeamWorkflowSourceCollectionPromptCachePolicy = {
  schemaVersion: number;
  policyId: string;
  policyKind: string;
  scope: string;
  requirement: string;
  modelId: string;
  modelName: string;
  providerId: string;
  promptCacheMode: string;
  modelResolution?: {
    status?: string;
    requestedModelId?: string;
    reason?: string;
  };
  supportedPromptCacheModes: string[];
  partitionTemplate: string;
  rolePartitions: Array<{
    agentRole: string;
    agentId: string;
    promptCachePartition: string;
  }>;
  stablePrefixContract: {
    cacheableBlocks: string[];
    forbiddenDynamicFields: string[];
    expectedUsage: string;
  };
  dynamicDeltaContract: {
    allowedFields: string[];
    maxRawContentPolicy: string;
    conversationTraceRequired: boolean;
  };
  gate: {
    status: string;
    passed: boolean;
    hardBlock: boolean;
    reason: string;
    checkedAt: string;
  };
};

export type TeamWorkflowSourceCollectionQuery = {
  queryId: string;
  query: string;
  seed: string;
  language: string;
  sourceType: string;
  assignedAgentRole: string;
  maxResults: number;
  status: string;
  execution: {
    mode: string;
    externalSearchTriggered: boolean;
    conversationTraceRequired?: boolean;
    promptCacheRequired?: boolean;
    promptCachePartition?: string;
  };
  writeback: {
    target: string;
    recordStatus: string;
    candidateImportTarget: string;
  };
};

export type TeamWorkflowSourceCollectionWritebackContract = {
  schemaVersion: number;
  target: string;
  recordContract: {
    requiredAnyOf: string[];
    recordFields: string[];
    collectionTraceFields: string[];
  };
  candidateImport: {
    targetCandidateType: string;
    route: string;
    idempotencyKey: string;
  };
  formalKnowledgeWrites: boolean;
  ragWrites: boolean;
  officialGraphWrites: boolean;
};

export type TeamWorkflowSourceCollectionSearchPlan = {
  schemaVersion: number;
  planId: string;
  planKind: string;
  status: string;
  teamId: string;
  runId: string;
  topic: string;
  goal: string;
  querySeeds: string[];
  queryCount: number;
  sourceTypes: string[];
  searchLanguages: string[];
  maxResultsPerQuery: number;
  queries: TeamWorkflowSourceCollectionQuery[];
  roleAssignmentInputs: Array<{
    agentRole: string;
    agentId: string;
    queryIds: string[];
    queryCount: number;
    promptCachePartition?: string;
    conversationTraceRequired?: boolean;
    expectedAction: string;
  }>;
  promptCachePolicy: TeamWorkflowSourceCollectionPromptCachePolicy;
  resultWritebackContract: TeamWorkflowSourceCollectionWritebackContract;
  boundaries: {
    externalSearchTriggered: boolean;
    writesFormalKnowledge: boolean;
    writesRag: boolean;
    writesKnowledgeGraph: boolean;
    requiresPromptCacheForAgentExecution?: boolean;
  };
};

export type TeamWorkflowSourceCollectionRunStartPayload = {
  run: DataProcessingRun;
  searchPlan: TeamWorkflowSourceCollectionSearchPlan;
  assignments: DataProcessingCollectionAssignment[];
  assignmentCount: number;
  promptCachePolicy: TeamWorkflowSourceCollectionPromptCachePolicy;
  workflow: TeamWorkflowOrchestration;
  nextActions: string[];
};

export type TeamWorkflowSourceCollectionAgentSessionContextPayload = {
  schemaVersion: number;
  teamId: string;
  runId: string;
  stageId: string;
  agentId: string;
  agentRole: string;
  sessionId: string;
  contextKey: string;
  created: boolean;
  alreadyPresent: boolean;
  message: Record<string, unknown>;
};

export type TeamWorkflowSourceCollectionStageSessionTask = {
  schemaVersion: number;
  taskKind: "source_collection_stage_session_task" | string;
  taskId: string;
  idempotencyKey: string;
  teamId: string;
  runId: string;
  stageId: string;
  agentId: string;
  agentRole: string;
  sessionId: string;
  status: string;
  title: string;
  summary: string;
  returnTo: string;
  returnLabel: string;
  requestedByAgent: string;
  recordCount: number;
  candidateCount: number;
  assignmentCount: number;
  matchingAssignmentCount: number;
  storageArtifacts: Record<string, string>;
  writebackContract: {
    schemaVersion: number;
    contractKind: "source_collection_stage_session_task_writeback" | string;
    taskId: string;
    teamId: string;
    runId: string;
    stageId: string;
    agentId: string;
    agentRole: string;
    endpoint: string;
    acceptedStatuses: string[];
    requiredFields: string[];
    writesFormalKnowledge: boolean;
    writesRag: boolean;
    writesOfficialGraph: boolean;
    resultAuthority: string;
  };
  writesFormalKnowledge: boolean;
  writesRag: boolean;
  writesOfficialGraph: boolean;
  turn: {
    accepted?: boolean;
    turnId?: string;
    status?: string;
    acceptedAt?: string;
  };
  result: Record<string, unknown>;
  writeback: Record<string, unknown>;
  evidenceRefs?: Array<Record<string, unknown>>;
  nextActions?: string[];
  createdAt: string;
  updatedAt: string;
};

export type TeamWorkflowSourceCollectionStageSessionTaskPayload = {
  schemaVersion: number;
  teamId: string;
  runId: string;
  stageId: string;
  agentId: string;
  agentRole: string;
  sessionId: string;
  taskId: string;
  idempotencyKey: string;
  created: boolean;
  alreadyPresent: boolean;
  task: TeamWorkflowSourceCollectionStageSessionTask;
  turn: TeamWorkflowSourceCollectionStageSessionTask["turn"];
  chatRoute: string;
  writebackContract: TeamWorkflowSourceCollectionStageSessionTask["writebackContract"];
  boundaries: {
    writesFormalKnowledge: boolean;
    writesRag: boolean;
    writesOfficialGraph: boolean;
    updatesStageTaskResult: boolean;
    requiresStructuredWriteback: boolean;
  };
};

export type TeamWorkflowDataRecordSourceCandidateImportPayload = {
  created: boolean;
  candidate: TeamWorkflowCandidate;
  dataRecordRef: Record<string, unknown>;
  validation: TeamWorkflowCandidateValidation;
  workflow: TeamWorkflowOrchestration;
};

export type TeamWorkflowSourceCollectionExtractionPayload = {
  schemaVersion: number;
  teamId: string;
  runId: string;
  status: string;
  run: DataProcessingRun;
  runStatus: DataProcessingStatus;
  sourceCollectionSummary?: Record<string, number>;
  storageArtifacts: Record<string, string>;
  assignments: DataProcessingCollectionAssignment[];
  recordCount: number;
  candidateCount: number;
  pendingRecordCount: number;
  importedCount: number;
  skippedCount: number;
  failedCount: number;
  completedExtractionAssignmentCount: number;
  imported: TeamWorkflowDataRecordSourceCandidateImportPayload[];
  skipped: Array<Record<string, unknown>>;
  failed: Array<Record<string, unknown>>;
  executionEvents: Array<Record<string, unknown>>;
  workflow: TeamWorkflowOrchestration;
  boundaries: {
    externalSearchTriggered: boolean;
    metadataOnlyDownload: boolean;
    writesFormalKnowledge: boolean;
    writesRag: boolean;
    writesOfficialGraph: boolean;
  };
  nextActions: string[];
};

export type TeamWorkflowCandidateValidationIssue = {
  severity: "error" | "warning" | string;
  code: string;
  message: string;
};

export type TeamWorkflowCandidateValidation = {
  valid: boolean;
  issues: TeamWorkflowCandidateValidationIssue[];
};

export type TeamWorkflowCandidateGraphNode = {
  candidateId: string;
  candidateType: string;
  title: string;
  currentWorkflowNode: string;
  currentState: string;
  qualityStatus: string;
  valid: boolean;
  requiresReview: boolean;
  officialState: string;
};

export type TeamWorkflowCandidateGraphEdge = {
  sourceCandidateId: string;
  targetCandidateId: string;
  relation: string;
  edgeState: string;
};

export type TeamWorkflowCandidateGraphPayload = {
  schemaVersion: number;
  teamId: string;
  workflowId: string;
  graphKind: "candidate_only" | string;
  nodes: TeamWorkflowCandidateGraphNode[];
  edges: TeamWorkflowCandidateGraphEdge[];
  missingLinks: TeamWorkflowCandidateGraphEdge[];
  unreviewedNodes: Array<{
    candidateId: string;
    candidateType: string;
    currentState: string;
    reason: string;
  }>;
  officialBoundary: {
    writesOfficialKnowledge: boolean;
    writesOfficialRag: boolean;
    writesOfficialGraph: boolean;
    requiresIngestionApproval: boolean;
  };
  summary: {
    nodeCount: number;
    edgeCount: number;
    missingLinkCount: number;
    unreviewedNodeCount: number;
    archivedCandidateCount?: number;
    curationMode?: string;
    inputCandidateCount?: number;
    filteredCandidateCount?: number;
    createdByAgent?: string;
    stageAgentRole?: string;
  };
  createdAt: string;
};

export type TeamWorkflowCandidate = {
  schemaVersion: number;
  candidateId: string;
  candidateType: string;
  teamId: string;
  workflowId: string;
  title: string;
  summary: string;
  sourceKind?: string;
  currentWorkflowNode: string;
  currentState: string;
  qualityStatus: string;
  validation?: TeamWorkflowCandidateValidation;
  metadata?: Record<string, unknown> & {
    graph?: TeamWorkflowCandidateGraphPayload;
    missingLinkCount?: number;
    unreviewedNodeCount?: number;
    officialBoundary?: TeamWorkflowCandidateGraphPayload["officialBoundary"];
  };
  createdByAgent: string;
  createdAt: string;
  updatedAt: string;
};

export type TeamWorkflowValidationSummary = {
  candidateCount: number;
  validCandidateCount: number;
  invalidCandidateCount: number;
  errorCount: number;
  warningCount: number;
  skipped?: boolean;
  reason?: string;
};

export type TeamWorkflowCandidateListPayload = {
  teamId: string;
  workflowId: string;
  filters: {
    candidateType: string;
    currentState: string;
    qualityStatus: string;
    limit: number;
  };
  candidates: TeamWorkflowCandidate[];
  candidateCount: number;
  store?: TeamWorkflowCandidateStoreSummary;
  validationSummary: TeamWorkflowValidationSummary;
};

export type TeamWorkflowCandidateGraphBuildPayload = {
  candidateGraph: TeamWorkflowCandidate;
  graph: TeamWorkflowCandidateGraphPayload;
  workflow: TeamWorkflowOrchestration;
  reusedCandidateGraph?: boolean;
  ingestionFingerprint?: string;
};

export type TeamWorkflowKnowledgeIngestionStage = {
  stageId: string;
  label: string;
  status: "blocked" | "needs_review" | "ready" | "pending" | string;
  count: number;
  nextAction: string;
  reason: string;
};

export type TeamWorkflowKnowledgeIngestionActionItem = {
  code: string;
  severity: "blocked" | "needs_revision" | "needs_evidence" | "needs_review" | "pending" | "ready" | string;
  message: string;
  nextAction: string;
  workflowNode: string;
  candidateId?: string;
  issueCount?: number;
  proposalId?: string;
  knowledgeBaseId?: string;
};

export type TeamWorkflowKnowledgeIngestionStatus = {
  schemaVersion: number;
  teamId: string;
  workflowId: string;
  workflowKind: "challenge_cup_research" | string;
  status: "empty" | "blocked" | "needs_revision" | "needs_review" | "in_progress" | "ready" | string;
  summary: {
    candidateCount: number;
    sourceCandidateCount: number;
    sourceReadyCount: number;
    localDraftCandidateCount: number;
    stewardPackCandidateCount: number;
    pendingKnowledgeReviewCandidateCount: number;
    officialSyncedCandidateCount: number;
    officialGraphSyncedCandidateCount: number;
    archivedCandidateCount: number;
    invalidCandidateCount: number;
    missingLinkCount: number;
    unreviewedNodeCount: number;
    knowledgeBaseCount: number;
    sourceArtifactCount: number;
    proposalCount: number;
    pendingProposalCount: number;
    formalKnowledgeItemCount: number;
    actionItemCount: number;
  };
  stages: TeamWorkflowKnowledgeIngestionStage[];
  actionItems: TeamWorkflowKnowledgeIngestionActionItem[];
  candidateBreakdown: {
    byType: Record<string, number>;
    byState: Record<string, number>;
    byQualityStatus: Record<string, number>;
  };
  candidateGraphSummary: TeamWorkflowCandidateGraphPayload["summary"];
  officialBoundary: {
    candidateStoreOfficialState: string;
    teamKnowledgeRequiresReview: boolean;
    candidateGraphWritesOfficialGraph: boolean;
    formalKnowledgeItemCreated: boolean;
    writesOfficialKnowledge: boolean;
    writesOfficialRag: boolean;
    writesOfficialGraph: boolean;
    graphStatus: string;
    ragStatus: string;
  };
  knowledgeBases: Array<{
    knowledgeBaseId: string;
    scopedKnowledgeBaseId?: string;
    ownerType?: string;
    ownerId?: string;
    name: string;
    status: string;
    stats: TeamKnowledgeBase["stats"];
  }>;
  storage: {
    workflowPath: string;
    candidateStorePath: string;
    transferRecordsPath: string;
  };
  activeWorkRun?: TeamWorkflowKnowledgeIngestionWorkRun | null;
  latestWorkRun?: TeamWorkflowKnowledgeIngestionWorkRun | null;
  updatedAt: string;
};

export type TeamWorkflowKnowledgeIngestionWorkRun = {
  runId: string;
  status: string;
  currentPhase: string;
  teamId: string;
  sourceRunId?: string;
  summary?: string;
  currentTask?: string;
  updatedAt?: string;
  finishedAt?: string;
  error?: string;
  errorType?: string;
  completionSteps?: Array<{
    stageId: string;
    label?: string;
    status: string;
    inputCount?: number;
    outputCount?: number;
    detail?: string;
    artifactId?: string;
    errorType?: string;
  }>;
  flowVisualization?: {
    kind: "knowledge_collection_completion" | string;
    schemaVersion?: number;
    status: string;
    currentStageId?: string;
    error?: string;
    errorType?: string;
    nodes: Array<{
      stageId: string;
      label: string;
      agentRole: string;
      status: string;
      inputCount?: number;
      outputCount?: number;
      artifactIds?: string[];
      detail?: string;
      errorType?: string;
    }>;
  };
  result?: {
    status?: string;
    formalKnowledgeItemCount?: number;
    knowledgeBaseId?: string;
    scopedKnowledgeBaseId?: string;
    stewardPackCandidateId?: string;
  };
};

export type TeamWorkflowKnowledgeCollectionIngestionPayload = {
  schemaVersion: number;
  teamId: string;
  status: "completed" | "pending_review" | "agent_notified" | "agent_wake_pending" | "agent_notification_failed" | "precheck_ready" | "blocked" | string;
  steps: Array<{
    stageId: string;
    label: string;
    status: string;
    inputCount: number;
    outputCount: number;
    detail: string;
    artifactId: string;
  }>;
  sourceQuality: Record<string, unknown>;
  candidateGraph: TeamWorkflowCandidateGraphBuildPayload | null;
  precheck: Record<string, unknown> | null;
  sourceReview: Record<string, unknown> | null;
  knowledgeSubmission: Record<string, unknown> | null;
  knowledgeReview: Record<string, unknown> | null;
  knowledgeStewardActivation: Record<string, unknown> | null;
  reusedCandidateGraph?: boolean;
  reusedStewardPack?: boolean;
  ingestionFingerprint?: string;
  knowledgeBase: {
    knowledgeBaseId: string;
    scopedKnowledgeBaseId?: string;
    [key: string]: unknown;
  } | null;
  statusSnapshot: TeamWorkflowKnowledgeIngestionStatus;
  summary: {
    sourceCandidateCount: number;
    approvedSourceCandidateCount: number;
    candidateGraphNodeCount?: number;
    candidateGraphEdgeCount?: number;
    stewardPackCandidateId?: string;
    knowledgeBaseId?: string;
    scopedKnowledgeBaseId?: string;
    knowledgeStewardInboxMessageId?: string;
    knowledgeStewardActivationStatus?: string;
    reusedCandidateGraph?: boolean;
    reusedStewardPack?: boolean;
    ingestionFingerprint?: string;
    formalKnowledgeItemCount: number;
    nextAction: string;
  };
  workflow: TeamWorkflowOrchestration;
};

export type TeamWorkflowCoordinationQueueItem = {
  queue: "pending_transfer" | "needs_rework" | "stewardship" | "blocked" | "active" | string;
  candidateId: string;
  candidateType: string;
  title: string;
  currentWorkflowNode: string;
  currentState: string;
  qualityStatus: string;
  valid: boolean;
  issueCount: number;
  reason: string;
  updatedAt: string;
  transferId?: string;
  fromNode?: string;
  toNode?: string;
  requestedByAgent?: string;
  communicationBrief?: {
    targetAgentRole: string;
    channel: "team_linked_room" | "project_agent_bus" | string;
    subject: string;
    message: string;
    requiresCoordinatorReview: boolean;
    autoSendEnabled: boolean;
    sourceQueue: string;
  };
};

export type TeamWorkflowCoordinationActionItem = {
  code: string;
  severity: "blocked" | "needs_revision" | "needs_review" | "pending" | string;
  message: string;
  nextAction: string;
  queue: string;
};

export type TeamWorkflowCoordinationStatus = {
  schemaVersion: number;
  teamId: string;
  workflowId: string;
  workflowKind: "challenge_cup_research" | string;
  status: "empty" | "blocked" | "needs_transfer_decision" | "needs_rework" | "stewardship_review" | "in_progress" | string;
  ownerAgentId: string;
  summary: {
    candidateCount: number;
    activeCandidateCount: number;
    archivedCandidateCount: number;
    pendingTransferCount: number;
    reworkCandidateCount: number;
    stewardshipCandidateCount: number;
    blockedCandidateCount: number;
    activeQueueCount: number;
    actionItemCount: number;
    byWorkflowNode: Record<string, number>;
    byState: Record<string, number>;
    byQualityStatus: Record<string, number>;
  };
  queues: {
    pendingTransfers: TeamWorkflowCoordinationQueueItem[];
    needsRework: TeamWorkflowCoordinationQueueItem[];
    stewardship: TeamWorkflowCoordinationQueueItem[];
    blocked: TeamWorkflowCoordinationQueueItem[];
    active: TeamWorkflowCoordinationQueueItem[];
  };
  actionItems: TeamWorkflowCoordinationActionItem[];
  communication: {
    briefCount: number;
    targetAgentRoleCounts: Record<string, number>;
    channelCounts: Record<string, number>;
    readOnly: boolean;
    autoSendEnabled: boolean;
    recommendedSender: string;
    nextAction: string;
    summaryLine: string;
  };
  coordinationPolicy: {
    coordinationAgentId: string;
    organizingAgentId: string;
    functionalAgentsMayRequestTransfer: boolean;
    requiresUserConfirmation: boolean;
    finalStateWriter: string;
    readOnlyStatus: boolean;
    autoTransferEnabled: boolean;
  };
  storage: {
    workflowPath: string;
    candidateStorePath: string;
    transferRecordsPath: string;
  };
  updatedAt: string;
};

export type TeamCaseState = {
  schemaVersion: number;
  caseId: string;
  roomId: string;
  teamId?: string;
  teamTemplateId?: string;
  intent: string;
  userGoal: string;
  knownFacts: string[];
  missingFacts: string[];
  riskFlags: string[];
  informationSufficiency?: "insufficient" | "partially_sufficient" | "sufficient" | "urgent_boundary_needed" | string;
  nextAction: "clarify" | "discuss" | "synthesize" | "answer" | string;
  userFacingMode?: "direct_clarification" | "team_discussion" | "team_discussion_then_advice" | "final_answer" | string;
  discussionVisibility?: "collapsed_by_default" | "user_visible" | string;
  assignedRoles: string[];
  status: string;
  participantsConsidered?: number;
  demoMapping?: string;
};
