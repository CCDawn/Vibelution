import type { KnowledgeBatch, KnowledgeItem, KnowledgeRatingSuggestion, KnowledgeRefinementProposal, KnowledgeSourceArtifact, KnowledgeStewardOverview, KnowledgeStewardRecommendationsPayload, KnowledgeStewardWorkbenchPayload, TeamKnowledgeBase, TeamKnowledgeOverview } from "./teams";

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
  contentDeferred?: boolean;
  contentLength?: number;
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

export type MemoryItemDetailPayload = {
  schemaVersion: number;
  generatedAt: string;
  projectRoot: string;
  section: Omit<MemorySection, "items">;
  item: MemoryItem;
  warnings: string[];
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

export interface UserMarkdownSpaceCounts {
  markdownFileCount: number;
  pageCount: number;
  linkCount: number;
  taskCount: number;
  tagCount: number;
}

export interface UserMarkdownSpaceSummary {
  spaceId: string;
  spaceName: string;
  canonicalPagesRoot: string;
  indexRoot: string;
  pageCount: number;
  updatedAt: string;
  userId: string;
  sourceRef?: Record<string, unknown>;
  counts?: UserMarkdownSpaceCounts;
}

export interface UserMarkdownPageSummary {
  pageId: string;
  relativePath: string;
  title: string;
  tags: string[];
  wikilinks: string[];
  taskCounts: { open: number; done: number; total: number };
  contentHash: string;
  byteSize: number;
  updatedAt: string;
  content?: string;
}

export interface UserMarkdownImportPreviewPage {
  relativePath: string;
  title: string;
  tags: string[];
  wikilinkCount: number;
  taskCount: number;
}

export interface UserMarkdownImportPreviewIgnoredFile {
  relativePath: string;
  reason: string;
}

export interface UserMarkdownSpaceImportPreviewPayload {
  ok: boolean;
  schemaVersion: number;
  userId: string;
  source: {
    path: string;
    managedRoot: string;
  };
  summary: {
    markdownFileCount: number;
    ignoredFileCount: number;
    wikilinkCount: number;
    taskCount: number;
    tagCount: number;
  };
  pages: UserMarkdownImportPreviewPage[];
  ignoredFiles: UserMarkdownImportPreviewIgnoredFile[];
  updatedAt: string;
}

export interface UserMarkdownSpaceImportPayload {
  ok: boolean;
  schemaVersion: number;
  userId: string;
  space: {
    spaceId: string;
    spaceName: string;
    canonicalPagesRoot: string;
    indexRoot: string;
    manifestPath: string;
  };
  summary: {
    markdownFileCount: number;
    ignoredFileCount: number;
    wikilinkCount: number;
    taskCount: number;
    tagCount: number;
    importedPageCount: number;
  };
  updatedAt: string;
}

export interface UserMarkdownSpaceListPayload {
  ok: boolean;
  summary: { spaceCount: number };
  spaces: UserMarkdownSpaceSummary[];
}

export interface UserMarkdownSpacePageListPayload {
  ok: boolean;
  space: UserMarkdownSpaceSummary;
  summary: { pageCount: number };
  pages: UserMarkdownPageSummary[];
}

export interface UserMarkdownSpacePagePayload {
  ok: boolean;
  space: UserMarkdownSpaceSummary;
  page: UserMarkdownPageSummary;
  content: string;
}

export interface UserMarkdownSearchResult {
  resultId: string;
  resultType: "user_markdown_page";
  sourceDomain: "user_content";
  title: string;
  excerpt: string;
  score: number;
  rank: number;
  userId: string;
  spaceId: string;
  spaceName: string;
  pageId: string;
  pageRelativePath: string;
  metadata: Record<string, unknown>;
}

export interface UserMarkdownSpaceSearchPayload {
  ok: boolean;
  summary: { resultCount: number };
  spaces: UserMarkdownSpaceSummary[];
  results: UserMarkdownSearchResult[];
}

export type MemoryCleanupTargetRequest = {
  targetType:
    | "global_runtime_memory"
    | "agent_private_memory"
    | "agent_formal_knowledge"
    | "team_knowledge"
    | "knowledge_base"
    | "agent_memory_policy"
    | "sqlite_database_compact"
    | "evaluation_artifacts"
    | "session_artifacts"
    | "legacy_log_info"
    | "runtime_scene_logs"
    | "team_archive_artifacts"
    | string;
  agentId?: string;
  teamId?: string;
  ownerType?: "team" | "agent" | string;
  ownerId?: string;
  knowledgeBaseId?: string;
  scopedKnowledgeBaseId?: string;
};

export type MemoryCleanupPathResult = {
  path: string;
  kind: string;
  action: string;
  status?: "preview" | "deleted" | "skipped" | "failed" | string;
  note?: string;
  message?: string;
  exists: boolean;
  fileCount: number;
  byteCount: number;
  rowCount: number;
};

export type MemoryCleanupCounts = {
  pathCount: number;
  fileCount: number;
  byteCount: number;
  rowCount: number;
  databaseRowCount: number;
  knowledgeBaseCount: number;
  knowledgeItemCount: number;
  sourceArtifactCount: number;
  proposalCount: number;
  batchCount: number;
  ratingSuggestionCount: number;
  vectorRecordCount: number;
  memoryPolicyResetCount: number;
};

export type MemoryCleanupTargetResult = {
  targetKey: string;
  targetType: string;
  label: string;
  ownerType: string;
  ownerId: string;
  agentId: string;
  teamId: string;
  knowledgeBaseId: string;
  scopedKnowledgeBaseId: string;
  status: "preview" | "executed" | string;
  paths: MemoryCleanupPathResult[];
  counts: MemoryCleanupCounts;
  warnings: string[];
};

export type MemoryCleanupPreviewResponse = {
  schemaVersion: number;
  mode: string;
  hardDelete: boolean;
  confirmationPhrase: string;
  targets: MemoryCleanupTargetResult[];
  totals: MemoryCleanupCounts & { targetCount: number };
  operatingBoundary: Record<string, boolean | string>;
  generatedAt: string;
  elapsedMs: number;
};

export type MemoryCleanupExecuteResponse = MemoryCleanupPreviewResponse;

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
