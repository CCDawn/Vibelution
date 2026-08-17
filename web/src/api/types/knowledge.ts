/** Knowledge / RAG DTOs owned by web/src/api/knowledge.ts (JSON) and core/web/services/team_knowledge. */

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
    centralSourceIds?: string[];
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
  centralSourceIds?: string[];
  provider: string;
  retrievalMode: string;
};

export type KnowledgeSourceOwnerType = "team" | "agent" | string;

export type KnowledgeSourceInboxStatus = "pending" | "accepted" | "rejected" | "duplicate" | "needs_more_context" | string;

export type KnowledgeOwnerSource = {
  schemaVersion: number;
  inboxSourceId: string;
  ownerType: KnowledgeSourceOwnerType;
  ownerId: string;
  teamId: string;
  agentId: string;
  sourceType: string;
  sourceRef: Record<string, unknown>;
  sourceCreatedAt: string;
  capturedBy: string;
  capturedAt: string;
  sourceHash: string;
  evidenceRange: Record<string, unknown>;
  title: string;
  summary: string;
  originalFilename: string;
  originalPath: string;
  status: KnowledgeSourceInboxStatus;
  curationStatus: string;
  centralSourceId: string;
  dedupeStatus: string;
  knowledgeBaseId?: string;
  knowledgeItemId?: string;
  reviewedAt: string;
  reviewedByAgentId: string;
  resolutionNote: string;
  updatedAt: string;
};

export type KnowledgeSourceInboxPayload = {
  schemaVersion: number;
  ownerType: KnowledgeSourceOwnerType;
  ownerId: string;
  teamId: string;
  agentId: string;
  actorAgentId: string;
  summary: {
    sourceCount: number;
    pendingSourceCount: number;
    acceptedSourceCount: number;
    rejectedSourceCount: number;
    duplicateSourceCount: number;
    needsMoreContextSourceCount: number;
    statusCounts: Record<string, number>;
  };
  sources: KnowledgeOwnerSource[];
  updatedAt: string;
};

export type KnowledgeCentralSource = {
  schemaVersion: number;
  centralSourceId: string;
  status: string;
  sourceHash: string;
  sourceType: string;
  sourceRef: Record<string, unknown>;
  sourceCreatedAt: string;
  title: string;
  summary: string;
  centralPath: string;
  originOwnerType: KnowledgeSourceOwnerType;
  originOwnerId: string;
  originInboxSourceId: string;
  originOriginalPath: string;
  acceptedByAgentId: string;
  acceptedAt: string;
  updatedAt: string;
};

export type KnowledgeCentralSourceOwnerRef = {
  schemaVersion: number;
  ownerRefId: string;
  promotionId: string;
  centralSourceId: string;
  ownerType: KnowledgeSourceOwnerType;
  ownerId: string;
  teamId: string;
  agentId: string;
  inboxSourceId: string;
  originalPath: string;
  sourceHash: string;
  decision: string;
  dedupeStatus: string;
  reviewedByAgentId: string;
  resolutionNote: string;
  createdAt: string;
  updatedAt: string;
};

export type KnowledgeCentralSourceRegistryPayload = {
  schemaVersion: number;
  agentId: string;
  ownerType: KnowledgeSourceOwnerType;
  ownerId: string;
  summary: {
    centralSourceCount: number;
    ownerRefCount: number;
  };
  centralSources: KnowledgeCentralSource[];
  ownerRefs: KnowledgeCentralSourceOwnerRef[];
  updatedAt: string;
};

export type KnowledgeSourceInboxReviewResponse = {
  schemaVersion: number;
  ownerType: KnowledgeSourceOwnerType;
  ownerId: string;
  source: KnowledgeOwnerSource;
  centralSource: KnowledgeCentralSource | null;
  promotion: {
    schemaVersion?: number;
    promotionId?: string;
    ownerRefId?: string;
    centralSourceId?: string;
    ownerType?: KnowledgeSourceOwnerType;
    ownerId?: string;
    inboxSourceId?: string;
    decision?: string;
    dedupeStatus?: string;
    reviewedByAgentId?: string;
    createdAt?: string;
  } | null;
  directIngestion: {
    schemaVersion: number;
    status: string;
    ownerType: KnowledgeSourceOwnerType;
    ownerId: string;
    teamId: string;
    agentId: string;
    knowledgeBaseId: string;
    scopedKnowledgeBaseId: string;
    sourceArtifact: KnowledgeSourceArtifact;
    batch: {
      batchId: string;
      ownerType: KnowledgeSourceOwnerType;
      ownerId: string;
      teamId: string;
      agentId: string;
      knowledgeBaseId: string;
      proposalIds: string[];
      sourceArtifactIds: string[];
      centralSourceIds: string[];
      reviewedByAgentId: string;
      appliedAt: string;
      status: string;
      ingestionMode?: string;
    };
    item: KnowledgeItem;
    updatedAt: string;
  } | null;
  updatedAt: string;
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
  directReviewContract?: {
    entrypoint: string;
    creates: string[];
    createsKnowledgeItem: boolean;
    requiresScreening: boolean;
    proposalStatus: string;
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
