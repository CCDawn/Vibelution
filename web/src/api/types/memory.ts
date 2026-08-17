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
  status: "preview" | "executed" | "partial" | "failed" | string;
  paths: MemoryCleanupPathResult[];
  counts: MemoryCleanupCounts;
  warnings: string[];
};

export type MemoryCleanupPreviewResponse = {
  schemaVersion: number;
  mode: string;
  hardDelete: boolean;
  confirmationPhrase: string;
  previewToken: string;
  previewExpiresAt: string;
  targets: MemoryCleanupTargetResult[];
  totals: MemoryCleanupCounts & {
    targetCount: number;
    executedTargetCount?: number;
    partialTargetCount?: number;
    failedTargetCount?: number;
    failedPathCount?: number;
    auditFailureCount?: number;
  };
  operatingBoundary: Record<string, boolean | string>;
  generatedAt: string;
  elapsedMs: number;
};

export type MemoryCleanupExecuteResponse = Omit<MemoryCleanupPreviewResponse, "previewToken" | "previewExpiresAt"> & {
  outcome: "succeeded" | "partial" | "failed";
  audit?: { status: "written" | "failed"; message?: string };
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
