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

export type MemoryItem = {
  id: string;
  title: string;
  kind: string;
  source: string;
  path: string;
  updatedAt: string;
  agentVisible: boolean;
  inPrompt: boolean;
  visibilityClass: "prompt" | "agent_visible" | "manual" | "diagnostic" | "missing" | string;
  channels: Array<"conversation" | "research" | "self_evolution" | "supervised_evolution" | "explicit_read" | string>;
  usedBy: string[];
  summary: string;
  content: string;
  contentType: string;
  contentTruncated: boolean;
  exists: boolean;
  managedState: {
    editable: boolean;
    deletable: boolean;
    restorable: boolean;
    disabled: boolean;
    userManaged: boolean;
    overridden: boolean;
    actionHint: string;
  };
};

export type MemorySection = {
  id: string;
  title: string;
  sourceKind: string;
  visibility: string;
  agentVisibility: string;
  sourcePath: string;
  sourceApi: string;
  updatedAt: string;
  summary: string;
  items: MemoryItem[];
};

export type MemoryOverview = {
  schemaVersion: number;
  generatedAt: string;
  projectRoot: string;
  summary: {
    sectionCount: number;
    itemCount: number;
    agentVisibleCount: number;
    runtimeInjectedCount: number;
    warnings: string[];
  };
  sections: MemorySection[];
};

export type MemoryMutationResponse = {
  ok: boolean;
  action: string;
  sectionId: string;
  itemId: string;
  item: MemoryItem;
};

export type MemoryKnowledgeGraphNode = {
  id: string;
  type:
    | "project"
    | "team"
    | "agent"
    | "agent_private_memory"
    | "knowledge_base"
    | "knowledge_item"
    | "source_artifact"
    | "refinement_proposal"
    | "knowledge_batch"
    | "rating_suggestion"
    | "runtime_scene"
    | "evolution"
    | "supervision"
    | "tag"
    | "concept"
    | string;
  label: string;
  summary: string;
  status: string;
  createdAt: string;
  updatedAt: string;
  metadata: Record<string, unknown>;
  responsibilityQuestion: string;
  visual: {
    size?: "root" | "group" | "container" | "leaf" | "support" | string;
    agentCategory?: "session_agent" | "team_member_agent" | string;
    [key: string]: unknown;
  };
  childNodeIds: string[];
  contentItems: Array<{
    id: string;
    type: string;
    title: string;
    summary: string;
    content?: string;
    contentTruncated?: boolean;
    knowledgeItemId?: string;
    knowledgeBaseId?: string;
    knowledgeBaseName?: string;
    ownerType?: string;
    ownerId?: string;
    teamId?: string;
    agentId?: string;
    status?: string;
    tags?: string[];
    createdAt?: string;
    updatedAt?: string;
    fullContentIncluded?: boolean;
    [key: string]: unknown;
  }>;
};

export type MemoryKnowledgeGraphEdge = {
  id: string;
  source: string;
  target: string;
  type: string;
  label: string;
  weight: number;
  metadata: Record<string, unknown>;
};

export type MemoryKnowledgeGraphPayload = {
  schemaVersion: number;
  mode: "read_only_project_memory_graph" | string;
  agentId: string;
  summary: {
    nodeCount: number;
    edgeCount: number;
    truncated: boolean;
    nodeTypeCounts: Record<string, number>;
    edgeTypeCounts: Record<string, number>;
    elapsedMs: number;
  };
  nodes: MemoryKnowledgeGraphNode[];
  edges: MemoryKnowledgeGraphEdge[];
  filters: {
    teamId?: string;
    knowledgeBaseId?: string;
    include?: string[];
    limit?: number;
  };
  operatingBoundary: {
    readOnly: boolean;
    gpuPreferred: boolean;
    layoutWorker: boolean;
    honorsKnowledgeAcl: boolean;
    fullContentIncluded: boolean;
    canEditGraph: boolean;
    canApplyKnowledge: boolean;
  };
};

export type MemoryKnowledgeGraphNodeDetailPayload = {
  schemaVersion: number;
  mode: "read_only_project_memory_graph_node_detail" | string;
  nodeId: string;
  agentId: string;
  nodeType: string;
  label: string;
  summary: string;
  contentItems: MemoryKnowledgeGraphNode["contentItems"];
  summaryCounts: {
    contentItemCount: number;
    truncatedContentItemCount: number;
  };
  operatingBoundary: {
    readOnly: boolean;
    honorsKnowledgeAcl: boolean;
    fullContentIncluded: boolean;
    canEditGraph: boolean;
    canApplyKnowledge: boolean;
  };
  elapsedMs: number;
};

export type MemoryUsageContractDomain = {
  domainId: string;
  label: string;
  owner: string;
  storage: string;
  readsThrough: string[];
  writesThrough: string[];
  canRegisterSource: boolean;
  canCreateFormalKnowledge: boolean;
  promptDefault: string;
  boundary: string;
};

export type MemoryUsageContractPayload = {
  schemaVersion: number;
  generatedAt: string;
  projectRoot: string;
  principles: string[];
  domains: MemoryUsageContractDomain[];
  flow: Array<{
    stepId: string;
    label: string;
    creates: string[];
    requiresReviewer: boolean;
  }>;
  forbiddenActions: string[];
  runtimeAccess: {
    summaryInPromptAllowed: boolean;
    knowledgeBodiesInPromptByDefault: boolean;
    explicitReadChannels: string[];
    agentToolBoundary: Record<string, string>;
  };
  currentState: {
    knowledge: Record<string, number | string | boolean>;
    operationsHealth: Record<string, number | string | boolean>;
    governancePlan: Record<string, number | string | boolean>;
    operatingBoundary: Record<string, boolean | string | number>;
  };
};

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
    canDeleteKnowledge: boolean;
    canChangeAcl: boolean;
    canBypassReviewer: boolean;
    formalKnowledgeRequiresReviewer: boolean;
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
  teamId: string;
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
};

export type KnowledgeRefinementProposal = {
  proposalId: string;
  teamId: string;
  targetKnowledgeBaseId: string;
  sourceArtifactIds: string[];
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

export type KnowledgeRagContext = {
  contextId: string;
  text: string;
  title: string;
  score: number;
  rank: number;
  retrievalMode: "exact" | "semantic" | "hybrid" | string;
  provider: string;
  matchReason: string;
  source: {
    ownerType?: "team" | "agent" | "shared" | string;
    ownerId?: string;
    teamId: string;
    teamName: string;
    agentId?: string;
    agentName?: string;
    knowledgeBaseId: string;
    knowledgeBaseName: string;
    knowledgeItemId: string;
    sourceArtifactIds: string[];
  };
  metadata: {
    tags: string[];
    importanceLevel: string;
    confidence: number | null;
    stability: string;
  };
};

export type KnowledgeRagCitation = {
  contextId: string;
  rank: number;
  title: string;
  ownerType?: "team" | "agent" | "shared" | string;
  ownerId?: string;
  teamId: string;
  teamName: string;
  agentId?: string;
  agentName?: string;
  knowledgeBaseId: string;
  knowledgeBaseName: string;
  knowledgeItemId: string;
  sourceArtifactIds: string[];
  provider: string;
  retrievalMode: string;
};

export type KnowledgeRagProviderHealth = {
  provider: string;
  status: "ready" | "degraded" | "unavailable" | string;
  vectorEnabled: boolean;
  indexedItemCount: number;
  staleItemCount: number;
  missingItemCount?: number;
  failedItemCount?: number;
  indexableItemCount?: number;
  embeddingProvider?: string;
  embeddingModel?: string;
  lastIndexedAt?: string;
};

export type KnowledgeRagHealthPayload = {
  schemaVersion: number;
  provider: string;
  status: "ready" | "degraded" | "unavailable" | string;
  providers: KnowledgeRagProviderHealth[];
  retrievalPolicy: {
    provider: string;
    injectsPromptByDefault: boolean;
    honorsKnowledgeAcl: boolean;
    honorsMemoryPolicy: boolean;
    mutatesFormalKnowledge: boolean;
  };
  updatedAt: string;
};

export type KnowledgeRagRetrievalPayload = {
  schemaVersion: number;
  agentId: string;
  request: {
    queryLength: number;
    teamId: string;
    ownerType?: string;
    ownerId?: string;
    knowledgeBaseId: string;
    tags: string[];
    retrievalMode: string;
    provider: string;
    topK: number;
    maxContextChars: number;
  };
  summary: {
    candidateCount: number;
    contextCount: number;
    citationCount: number;
    scannedKnowledgeBaseCount: number;
  };
  contexts: KnowledgeRagContext[];
  citations: KnowledgeRagCitation[];
  retrievalPolicy: {
    provider: string;
    injectsPromptByDefault: boolean;
    honorsKnowledgeAcl: boolean;
    honorsMemoryPolicy: boolean;
    mutatesFormalKnowledge: boolean;
  };
  updatedAt: string;
};

export type KnowledgePermissionAuditPayload = {
  schemaVersion: number;
  agentId: string;
  tools: Record<string, {
    toolName: string;
    visible: boolean;
    allowedByToolPolicy: boolean;
    blockedByToolPolicy: boolean;
    reason: string;
  }>;
  knowledgeBases: Array<{
    teamId: string;
    teamName: string;
    knowledgeBaseId: string;
    knowledgeBaseName: string;
    teamRole: string;
    permissions: Record<string, {
      allowed: boolean;
      reason: string;
      teamAclAllowed: boolean;
      memoryPolicyAllowed: boolean;
      memoryPolicyExplicit: boolean;
    }>;
  }>;
  summary: {
    knowledgeBaseCount: number;
    readableCount: number;
    proposableCount: number;
    reviewableCount: number;
    rateableCount: number;
  };
  updatedAt: string;
};

export type KnowledgeGovernanceTask = {
  taskId: string;
  taskType: "proposal_review" | "rating_review" | "source_needs_proposal" | string;
  status: "open" | "closed" | string;
  priority: string;
  teamId: string;
  teamName: string;
  knowledgeBaseId: string;
  knowledgeBaseName: string;
  targetId: string;
  targetStatus: string;
  title: string;
  summary: string;
  sourceArtifactIds: string[];
  createdAt: string;
  updatedAt: string;
  permissions: {
    canReview: boolean;
    canRate: boolean;
    canPropose: boolean;
  };
};

export type KnowledgeGovernanceTasksPayload = {
  schemaVersion: number;
  agentId: string;
  tasks: KnowledgeGovernanceTask[];
  summary: {
    taskCount: number;
    openTaskCount: number;
    proposalReviewCount: number;
    ratingReviewCount: number;
    sourceNeedsProposalCount: number;
  };
  updatedAt: string;
};

export type KnowledgeOperationsHealthPayload = {
  schemaVersion: number;
  agentId: string;
  knowledgeBases: Array<{
    teamId: string;
    teamName: string;
    knowledgeBaseId: string;
    knowledgeBaseName: string;
    health: "ok" | "attention" | "warning" | string;
    counts: {
      sourceArtifactCount: number;
      orphanSourceCount: number;
      proposalCount: number;
      pendingProposalCount: number;
      formalItemCount: number;
      unratedItemCount: number;
      pendingRatingSuggestionCount: number;
    };
    nextReviewTargetIds: string[];
  }>;
  findings: Array<{
    findingId: string;
    findingType: string;
    severity: string;
    teamId: string;
    teamName: string;
    knowledgeBaseId: string;
    knowledgeBaseName: string;
    count: number;
    message: string;
    nextReviewTargetIds: string[];
  }>;
  summary: {
    knowledgeBaseCount: number;
    attentionCount: number;
    warningCount: number;
    okCount: number;
    findingCount: number;
    orphanSourceCount: number;
    pendingProposalCount: number;
    pendingRatingSuggestionCount: number;
    unratedItemCount: number;
  };
  updatedAt: string;
};

export type KnowledgeGovernancePlanPayload = {
  schemaVersion: number;
  agentId: string;
  mode: "recommendations_only" | string;
  actions: Array<{
    planActionId: string;
    kind: string;
    priority: string;
    knowledgeBaseId: string;
    knowledgeBaseName: string;
    targetId: string;
    title: string;
    recommendedTool: string;
    nextStep: string;
    requiresReviewer: boolean;
    mutatesFormalKnowledge: boolean;
  }>;
  summary: {
    actionCount: number;
    healthFindingCount: number;
    workbenchRecommendationCount: number;
  };
  operatingBoundary: {
    canDirectlyApplyKnowledge: boolean;
    canDeleteKnowledge: boolean;
    canChangeAcl: boolean;
    canBypassReviewer: boolean;
    formalKnowledgeRequiresReviewer: boolean;
    planOnly: boolean;
  };
  updatedAt: string;
};

export type KnowledgeDashboardSnapshotPayload = {
  schemaVersion: number;
  agentId: string;
  overview: TeamKnowledgeOverview;
  steward: KnowledgeStewardOverview;
  recommendations: KnowledgeStewardRecommendationsPayload;
  workbench: KnowledgeStewardWorkbenchPayload;
  operationsHealth: KnowledgeOperationsHealthPayload;
  governancePlan: KnowledgeGovernancePlanPayload;
  updatedAt: string;
};

export type KnowledgeIngestionAdapter = {
  sourceType: string;
  label: string;
  requiredSourceRef: string[];
  optionalSourceRef: string[];
  evidenceKinds: string[];
  outputContract: {
    creates: string[];
    proposalStatus: string;
    createsKnowledgeItem: boolean;
    requiresReview: boolean;
  };
};

export type KnowledgeIngestionAdaptersPayload = {
  schemaVersion: number;
  adapters: KnowledgeIngestionAdapter[];
  summary: {
    adapterCount: number;
  };
  updatedAt: string;
};

export type KnowledgeTracePayload = {
  schemaVersion: number;
  teamId: string;
  knowledgeBase: TeamKnowledgeBase;
  targetId: string;
  targetType: string;
  nodes: {
    sourceArtifacts: KnowledgeSourceArtifact[];
    proposals: KnowledgeRefinementProposal[];
    batches: KnowledgeBatch[];
    items: KnowledgeItem[];
    ratingSuggestions: KnowledgeRatingSuggestion[];
  };
  summary: Record<string, number>;
  updatedAt: string;
};

export type SkillLibraryRoot = {
  path: string;
  source: "codex" | "agents" | "other" | string;
  exists: boolean;
};

export type SkillLibraryItem = {
  name: string;
  aliases: string[];
  command: string;
  description: string;
  source: "codex" | "agents" | "other" | string;
  rootPath: string;
  path: string;
  directoryName: string;
  hash: string;
  contentLength: number;
  preview: string;
  previewTruncated: boolean;
};

export type SkillLibraryDetail = SkillLibraryItem & {
  content: string;
  contentTruncated: boolean;
};

export type SkillLibraryPayload = {
  schemaVersion: number;
  mode: "read_only" | string;
  roots: SkillLibraryRoot[];
  counts: {
    total: number;
    codex: number;
    agents: number;
    other: number;
  };
  skills: SkillLibraryItem[];
};

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
  summary: string;
  counts: {
    total: number;
    staged: number;
    unstaged: number;
    untracked: number;
    deleted: number;
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

export type LauncherOperation = "start" | "stop" | "restart";

export type LauncherComponentState = {
  id: "backend" | "frontend" | "browser" | string;
  ok: boolean;
  state: string;
  requiredForRunning: boolean;
  pid: number;
  detail: string;
};

export type LauncherProjectBundleState = {
  schemaVersion: number;
  id: string;
  mode: "bundled" | string;
  desiredState: string;
  observedState: string;
  phase: string;
  overallState: string;
  statusLine: string;
  url: string;
  lastReason: string;
  failureMessage: string;
  lastOperation: {
    reason: string;
    source: string;
    transitionAt: string;
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
};

export type LauncherControlResponse = RuntimeControlResponse & {
  launcherMode: string;
  operation: LauncherOperation;
};

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
  dialogueModelId?: string;
  workspacePath?: string;
  agentWorkspacePath?: string;
  agentMissingId?: string;
  agentMissing?: boolean;
  agentStatusCode?: string;
  agentStatusMessage?: string;
  agentDirectSessionMismatch?: boolean;
  agentPrimaryDirectSessionId?: string;
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

export type ToolPolicy = {
  policyId: string;
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

export type AgentToolGovernanceRequest = {
  eventId: string;
  requestId: string;
  kind: string;
  status: "pending_review" | "applied" | "rejected" | string;
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
  after?: Record<string, unknown>;
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

export type ProjectAgentBusDelivery = {
  targetAgentId: string;
  targetAgentCode: string;
  targetAgentName: string;
  targetSessionId: string;
  inboxMessageId: string;
  status: string;
  reason: string;
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

export type AgentInstance = {
  agentId: string;
  agentCode: string;
  displayName: string;
  kind: "persistent" | string;
  primaryMode: "chat" | "research" | "self_evolution" | "supervised_evolution" | "general" | string;
  roleKey: string;
  llmBindings: AgentLlmBindings;
  promptTemplateId: string;
  directSessionId: string;
  workspacePath: string;
  workspaceTerritory?: AgentWorkspaceTerritory;
  toolPolicyId: string;
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
  sourceType: "workspace_file" | string;
  sourcePath: string;
  sourceExists: boolean;
  content: string;
  contentHash: string;
  defaultContent: string;
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
      slots: Record<"executor" | "reviewer" | "summarizer" | string, string>;
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

export type AgentConfigWorkspaceAgent = AgentInstance & {
  dialogueModel?: AgentModelChoice | null;
  llmBindingModels?: Partial<Record<keyof AgentLlmBindings, AgentModelChoice | null>>;
  promptTemplate?: PromptTemplate | null;
  agentBoundary?: AgentBoundary;
  references: AgentConfigReference[];
  health: AgentConfigHealthIssue[];
};

export type AgentModelChoice = {
  modelId: string;
  label: string;
  model: string;
  providerKind: string;
  providerBaseUrl: string;
  source: string;
  apiKeyEnv: string;
  apiKeyConfigured: boolean;
  apiKeyState: string;
  requiresApiKey: boolean;
  missingApiKey: boolean;
  supportsImageInput?: boolean | null;
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
  }>;
  teams?: Array<{
    teamId: string;
    name: string;
    purpose: string;
    status: string;
    agentIds: string[];
    memberCount: number;
    updatedAt: string;
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

export type Team = {
  teamId: string;
  name: string;
  description: string;
  purpose: string;
  status: "active" | "archived" | string;
  teamKind: "custom" | "research" | "self_evolution" | "supervised_evolution" | "template_demo" | string;
  teamCategory: string;
  teamSource: "manual" | "research_organization" | "self_evolution" | "supervised_evolution" | "team_template" | string;
  teamTemplateId?: string;
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
  store: TeamWorkflowCandidateStoreSummary;
  validationSummary: TeamWorkflowValidationSummary;
};

export type TeamWorkflowCandidateGraphBuildPayload = {
  candidateGraph: TeamWorkflowCandidate;
  graph: TeamWorkflowCandidateGraphPayload;
  workflow: TeamWorkflowOrchestration;
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
    name: string;
    status: string;
    stats: TeamKnowledgeBase["stats"];
  }>;
  storage: {
    workflowPath: string;
    candidateStorePath: string;
    transferRecordsPath: string;
  };
  updatedAt: string;
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
  agentMissing?: boolean;
  agentStatusCode?: string;
  agentStatusMessage?: string;
};

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
  tracePath?: string;
  relatedThoughtSequence?: number;
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
};

export type SessionCacheComposition = {
  turnId: string;
  recordedAt: string;
  source: string;
  inputTokens: number;
  cachedInputTokens: number;
  cacheReadInputTokens?: number;
  cacheCreationInputTokens: number;
  uncachedInputTokens: number;
  cacheHitRate: number;
  segments: SessionCacheCompositionSegment[];
};

export type SessionDetail = SessionSummary & {
  activeTask?: SessionActiveTask | null;
  defaultFileContext: string;
  previewTabs: string[];
  activePreviewPath: string;
  changedFiles: string[];
  readFiles: string[];
  messages: ConversationMessage[];
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
    updatedAt: string;
    source: string;
  };
  llmUsage?: SessionLlmUsage | null;
  lastContextComposition?: SessionContextComposition | null;
  lastCacheComposition?: SessionCacheComposition | null;
  handoffContext?: SessionChildHandoffContext | null;
  lastTurnError?: SessionTurnError | null;
  nextStateSignals?: ChatNextStateSignalSummary[];
  groupContextEvents?: GroupContextEvent[];
  agentInboxMessages?: AgentInboxMessage[];
  toolPolicy?: ToolPolicy | null;
  memoryPolicy?: MemoryPolicy | null;
  stopRequested: boolean;
  stopRequestedAt: string;
  stopReason: string;
};

export type SessionLlmUsage = {
  source: "provider_usage" | "missing" | "estimated" | string;
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
  detail: SessionDetail;
};

export type SessionAssistantDeltaStreamEvent = {
  type: "assistant_delta";
  sessionId: string;
  turnId: string;
  stage: string;
  content: string;
  thought: string;
  feedbackEvents?: ConversationFeedbackEvent[];
  updatedAt: string;
  done: boolean;
};

export type SessionStreamEvent = SessionDetailStreamEvent | SessionAssistantDeltaStreamEvent;

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
  content: string;
  summary: string;
  messageKind?: "user_clarification" | "team_discussion" | "team_message" | string;
  audience?: "user" | "internal" | string;
  visibility?: "collapsed_by_default" | "default" | string;
  errorType?: string;
  supervision?: AgentSupervisionDecision;
  timestamp: string;
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
  latestInput: string;
  latestOutput: string;
  latestOutputKind: string;
  latestOutputLabel: string;
  updatedAt: string;
  transcript: EvolutionActiveRunIoEntry[];
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
  llmBindings?: Record<string, { modelId?: string }>;
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

export type EvolutionRunDeleteResponse = {
  deleted: boolean;
  runId: string;
  clearedActive: boolean;
  clearedLatest: boolean;
  activeRunId: string;
  latestRunId: string;
  summary: string;
};

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
  costEstimate: {
    caseCount: number;
    evaluationCalls: number;
    selfEditCalls: number;
    modelCalls: number;
    estimatedInputTokens: number;
    estimatedOutputTokens: number;
    estimatedTotalTokens: number;
    note: string;
  };
  decision: {
    mode?: string;
    baselineScore?: number;
    candidateScore?: number;
    scoreDelta?: number;
    recommendedAction?: string;
    reason?: string;
    highRisk?: boolean;
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
  actionStates: Record<string, EvolutionActionState>;
};

export type SupervisedWorktreeRunStreamEvent = {
  type: "supervised_worktree_run";
  runId: string;
  snapshot: SupervisedWorktreeRun;
  terminal?: boolean;
};

export type SelfEvolutionRunStreamEvent = {
  type: "self_evolution_run";
  runId: string;
  snapshot: SelfEvolutionActiveRun;
  terminal?: boolean;
};

export type EvolutionWorkbench = {
  defaultBundleName: string;
  savedState: EvolutionOverview["workbench"];
  bundles: Array<{
    name: string;
    declaredName: string;
    path: string;
    caseCount: number;
    benchmark: string;
  }>;
  datasets: EvolutionDatasetOption[];
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
  worktreeActiveRun: SupervisedWorktreeRun | null;
  worktreeRuns: SupervisedWorktreeRun[];
  selfOverview: SelfEvolutionOverview;
  selfLatestRun: SelfEvolutionActiveRun | null;
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

export type SelfEvolutionRollbackTouchedFile = {
  path: string;
  changeType: string;
  trackedBefore: boolean;
  existedBefore: boolean;
  statusAfter: string;
  preHash: string;
  postHash: string;
  postExists: boolean;
  conflict: boolean;
  conflictReason: string;
};

export type SelfEvolutionRollbackConflictFile = {
  path: string;
  reason: string;
  currentHash: string;
  expectedHash: string;
};

export type SelfEvolutionRollbackState = {
  status: string;
  reason: string;
  baseRev: string;
  rolledBackAt: string;
  entryCount: number;
  touchedFiles: SelfEvolutionRollbackTouchedFile[];
  conflictFiles: SelfEvolutionRollbackConflictFile[];
  blockedHint: string;
};

export type SelfEvolutionRun = {
  runId: string;
  goal: string;
  status: string;
  phase: string;
  startedAt: string;
  updatedAt: string;
  finishedAt: string;
  latestMessage: string;
  currentGoal: string;
  currentTask: string;
  lastToolName: string;
  runtimeStatus: string;
  toolCallCount: number;
  summary: string;
  error: string;
  cancelRequested: boolean;
  cancelRequestedAt: string;
  stopReason: string;
  controlAction: string;
  controlRequestedAt: string;
  messages: ConversationMessage[];
  turnCount: number;
  resumeCount: number;
  readingTask: string;
  readingHint: string;
  readingSufficiency: string;
  convergenceState: string;
  nextToolIntent: string;
  rollback: SelfEvolutionRollbackState;
  runSemantics: SelfEvolutionRunSemantics;
  actionStates: Record<string, EvolutionActionState>;
};

export type SelfEvolutionActiveRun = SelfEvolutionRun;
export type SelfEvolutionLatestRun = SelfEvolutionRun;

export type SelfEvolutionHandoffResponse = {
  status: string;
  message: string;
  sessionId: string;
  content: string;
  run: SelfEvolutionRun | null;
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

export type ConfigModelOption = {
  model_id: string;
  source: string;
  provider: Record<string, unknown>;
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

export type ConfigWorkspace = ConfigSummary & {
  message: string;
  baseHash: string;
  configPath: string;
  publicConfig: Record<string, unknown>;
  rawToml: string;
  draftMeta: ConfigDraftMeta;
  diagnosis: ConfigDiagnosis;
  summary: Record<string, string | number | boolean | null>;
  editorSections: ConfigEditorSection[];
  editorMeta: Record<string, ConfigEditorMeta>;
  modelPresetOptions: ConfigModelPresetOption[];
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
