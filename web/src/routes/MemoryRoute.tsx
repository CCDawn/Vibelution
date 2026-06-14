import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Brain,
  CheckCircle2,
  Copy as CopyIcon,
  Database,
  Eye,
  FileText,
  Link2,
  Network,
  Pencil,
  RefreshCw,
  Search,
  Square,
  SquareCheckBig,
  Trash2,
  TriangleAlert,
  Undo2,
  XCircle,
} from "lucide-react";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { NavLink, useSearchParams } from "react-router-dom";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import {
  AgentProjectMemoryUpdateProposal,
  KnowledgeItemsPayload,
  KnowledgeItem,
  KnowledgeCentralSourceRegistryPayload,
  KnowledgeDashboardSnapshotPayload,
  KnowledgeGovernanceTasksPayload,
  KnowledgeIngestionAdaptersPayload,
  KnowledgeOwnerSource,
  KnowledgePermissionAuditPayload,
  KnowledgeRagHealthPayload,
  KnowledgeRatingSuggestionBulkReviewResponse,
  KnowledgeRatingSuggestion,
  KnowledgeRatingSuggestionReviewResponse,
  KnowledgeRatingSuggestionsPayload,
  KnowledgeRefinementProposal,
  KnowledgeReviewResponse,
  KnowledgeRagRetrievalPayload,
  KnowledgeSearchPayload,
  KnowledgeSourceArtifact,
  KnowledgeSourceInboxPayload,
  KnowledgeSourceInboxReviewResponse,
  KnowledgeTracePayload,
  MemoryItem,
  MemoryItemDetailPayload,
  MemoryCleanupExecuteResponse,
  MemoryCleanupPreviewResponse,
  MemoryCleanupTargetRequest,
  MemoryKnowledgeGraphEdge,
  MemoryKnowledgeGraphNode,
  MemoryKnowledgeGraphNodeDetailPayload,
  MemoryKnowledgeGraphPayload,
  MemoryMutationResponse,
  MemoryOverview,
  MemorySection,
  MemoryUsageContractPayload,
  AgentInstance,
  TeamKnowledgeBase,
} from "../api/types";
import { resolvePollingInterval, usePageVisibility } from "../app/pollingPolicy";
import { useShellI18n } from "../i18n/useShellI18n";
import styles from "./MemoryRoute.module.css";

const MemoryGraphCanvas = lazy(() => import("./MemoryGraphCanvas").then((module) => ({ default: module.MemoryGraphCanvas })));

const GRAPH_NODE_TYPE_LABELS: Record<string, string> = {
  project: "Project",
  team: "Team",
  agent: "Agent",
  agent_private_memory: "Memory",
  knowledge_base: "KB",
  knowledge_item: "Item",
  source_artifact: "Source",
  refinement_proposal: "Proposal",
  knowledge_batch: "Batch",
  rating_suggestion: "Rating",
  runtime_scene: "Runtime",
  evolution: "Evolution",
  supervision: "Supervision",
  tag: "Tag",
};

type Copy = {
  eyebrow: string;
  title: string;
  subtitle: string;
  refresh: string;
  loading: string;
  loadFailed: string;
  refreshFailed: string;
  sections: string;
  items: string;
  agentVisible: string;
  runtimeInjected: string;
  sourcePath: string;
  sourceApi: string;
  visibility: string;
  agentVisibility: string;
  usedBy: string;
  summary: string;
  rawContent: string;
  noContent: string;
  sourceOrigin: string;
  searchPlaceholder: string;
  allSections: string;
  noMatches: string;
  yes: string;
  no: string;
  inPrompt: string;
  notInPrompt: string;
  canUse: string;
  manualOnly: string;
  missing: string;
  truncated: string;
  warnings: string;
  generatedAt: string;
  sectionCount: string;
  itemCount: string;
  perceptionMatrix: string;
  whereMemoryWorks: string;
  matrixItems: string;
  matrixPrompt: string;
  conversationMemory: string;
  conversationMemoryHint: string;
  researchMemory: string;
  researchMemoryHint: string;
  selfEvolutionMemory: string;
  selfEvolutionMemoryHint: string;
  supervisedEvolutionMemory: string;
  supervisedEvolutionMemoryHint: string;
  explicitReadMemory: string;
  explicitReadMemoryHint: string;
  filters: string;
  filterAll: string;
  filterPrompt: string;
  filterVisible: string;
  filterManual: string;
  filterMissing: string;
  manageFilters: string;
  manageFilterAll: string;
  manageFilterPrompt: string;
  manageFilterEditable: string;
  manageFilterChanged: string;
  manageFilterMissing: string;
  sourceFilters: string;
  impact: string;
  impactPromptTitle: string;
  impactPromptBody: string;
  impactVisibleTitle: string;
  impactVisibleBody: string;
  impactManualTitle: string;
  impactManualBody: string;
  copySourceSummary: string;
  copySourcePath: string;
  copyRawContentAction: string;
  copyCurrentLink: string;
  copyDone: string;
  copyFailed: string;
  management: string;
  addMemory: string;
  editMemory: string;
  saveMemory: string;
  cancelEdit: string;
  disableMemory: string;
  restoreMemory: string;
  deleteMemory: string;
  titleField: string;
  summaryField: string;
  contentField: string;
  titlePlaceholder: string;
  summaryPlaceholder: string;
  contentPlaceholder: string;
  managementHint: string;
  overridden: string;
  disabledByUser: string;
  userManaged: string;
  mutationDone: string;
  mutationFailed: string;
  overviewView: string;
  effectiveView: string;
  manageView: string;
  sourcesView: string;
  knowledgeView: string;
  overviewSubtitle: string;
  effectiveSubtitle: string;
  manageSubtitle: string;
  sourcesSubtitle: string;
  knowledgeSubtitle: string;
  healthOverview: string;
  affectedRuntimeMemory: string;
  needsReview: string;
  noIssues: string;
  noRuntimeMemory: string;
  managedMemory: string;
  disabledOrOverridden: string;
  effectiveByChannel: string;
  manageAllMemory: string;
  manageConfigPanel: string;
  manageConfigHint: string;
  manageListHint: string;
  selectedMemory: string;
  selectedKnowledgeDetail: string;
  sourceAudit: string;
  reviewQueue: string;
  reviewQueueHint: string;
  projectMemoryQueue: string;
  projectMemoryQueueHint: string;
  projectMemoryQueuePendingOnly: string;
  projectMemoryQueueAll: string;
  projectMemoryQueueAgent: string;
  projectMemoryQueueLane: string;
  projectMemoryQueueFiles: string;
  projectMemoryQueueCreated: string;
  projectMemoryQueueResolved: string;
  projectMemoryQueueResolutionNote: string;
  projectMemoryQueueEmptyPending: string;
  projectMemoryQueueEmptyAll: string;
  projectMemoryQueueApply: string;
  projectMemoryQueueReject: string;
  projectMemoryQueueConflict: string;
  projectMemoryQueueSupersede: string;
  reviewReason: string;
  auditMemory: string;
  manageMemoryAction: string;
  reasonDisabled: string;
  reasonOverridden: string;
  reasonMissing: string;
  reasonTruncated: string;
  reasonInPrompt: string;
  reasonAgentVisible: string;
  reasonUserManaged: string;
  selectMemory: string;
  selectedCount: string;
  selectAllVisible: string;
  clearSelection: string;
  bulkDisable: string;
  bulkRestore: string;
  bulkActionSkipped: string;
  editPreview: string;
  currentValue: string;
  draftValue: string;
  noDraftChanges: string;
  teamKnowledge: string;
  knowledgeBases: string;
  pendingProposals: string;
  sourceArtifacts: string;
  formalKnowledge: string;
  sourceGovernance: string;
  ownerSourceInbox: string;
  centralSourceRegistry: string;
  centralSources: string;
  ownerScope: string;
  ownerTeam: string;
  ownerAgent: string;
  ownerId: string;
  allSourceStatuses: string;
  pendingSources: string;
  acceptedSources: string;
  rejectedSources: string;
  duplicateSources: string;
  needsMoreContextSources: string;
  collectOwnerSource: string;
  originalContent: string;
  originalFilename: string;
  reviewSource: string;
  acceptSource: string;
  markDuplicate: string;
  needsMoreContext: string;
  attachCentralSource: string;
  centralSourceId: string;
  centralPath: string;
  originalPath: string;
  sourceHash: string;
  curationStatus: string;
  dedupeStatus: string;
  reviewedBy: string;
  reviewedAt: string;
  sourceReviewNote: string;
  noInboxSources: string;
  noCentralSources: string;
  useActiveKnowledgeOwner: string;
  refinementProposal: string;
  rating: string;
  sourceType: string;
  sourceRef: string;
  sourceCreatedAt: string;
  capturedBy: string;
  evidenceRange: string;
  proposalTitle: string;
  proposalContent: string;
  tags: string;
  submitSource: string;
  submitProposal: string;
  approveProposal: string;
  rejectProposal: string;
  updateRating: string;
  importanceLevel: string;
  confidence: string;
  stability: string;
  reviewPriority: string;
  markingReason: string;
  noKnowledgeBases: string;
  knowledgeHint: string;
  platformPipeline: string;
  pipelineSource: string;
  pipelineProposal: string;
  pipelineBatch: string;
  pipelineFormal: string;
  pipelineRating: string;
  toolReadableOnly: string;
  promptBoundary: string;
  agentPrivateDomain: string;
  teamKnowledgeDomain: string;
  governance: string;
  knowledgeSearch: string;
  ragRetrieval: string;
  ragContextCandidates: string;
  ragRetrievalHint: string;
  ragHealth: string;
  ragProvider: string;
  ragVector: string;
  ragIndexed: string;
  ragStale: string;
  ragTopK: string;
  ragContextBudget: string;
  ragNoPromptInjection: string;
  ragCitations: string;
  ragNoContexts: string;
  searchQuery: string;
  ratingSuggestions: string;
  submitRatingSuggestion: string;
  applySuggestion: string;
  rejectSuggestion: string;
  permissionAudit: string;
  toolVisibility: string;
  readable: string;
  proposable: string;
  reviewable: string;
  rateable: string;
  excerpt: string;
  status: string;
  allStatuses: string;
  priority: string;
  allPriorities: string;
  selectSuggestion: string;
  selectAllVisibleSuggestions: string;
  clearSuggestionSelection: string;
  bulkApplySuggestions: string;
  bulkRejectSuggestions: string;
  selectedSuggestions: string;
  skippedSuggestions: string;
  governanceTasks: string;
  ingestionAdapters: string;
  traceability: string;
  sourceChain: string;
  outputContract: string;
  createsKnowledgeItem: string;
  knowledgeSteward: string;
  stewardMission: string;
  stewardDirectChat: string;
  stewardBoundary: string;
  protectedAgent: string;
  allowedTools: string;
  preferredTools: string;
  openGovernanceTasks: string;
  noDirectApply: string;
  reviewerRequired: string;
  stewardRecommendations: string;
  stewardRecommendationHint: string;
  recommendationsOnly: string;
  recommendedAction: string;
  stewardWorkbench: string;
  stewardStages: string;
  stewardNextActions: string;
  acceptanceChecklist: string;
  executable: string;
  operationsHealth: string;
  healthFindings: string;
  governancePlan: string;
  planOnly: string;
  searchMode: string;
  exactSearch: string;
  semanticSearch: string;
  hybridSearch: string;
  semanticScore: string;
  usageContract: string;
  memoryDomains: string;
  allowedUse: string;
  writeBoundary: string;
  forbiddenActions: string;
  currentContractState: string;
  graphView: string;
  graphSubtitle: string;
  cleanupView: string;
  cleanupSubtitle: string;
  cleanupTargets: string;
  cleanupPreview: string;
  cleanupExecute: string;
  cleanupConfirmPhrase: string;
  cleanupConfirmPlaceholder: string;
  cleanupHardDelete: string;
  cleanupNoBackup: string;
  cleanupSelectedTargets: string;
  cleanupGlobalRuntime: string;
  cleanupAgentPrivate: string;
  cleanupAgentFormalKnowledge: string;
  cleanupAgentMemoryPolicy: string;
  cleanupTeamKnowledge: string;
  cleanupKnowledgeBase: string;
  cleanupPreviewReady: string;
  cleanupExecuteDone: string;
  cleanupNoTargets: string;
  cleanupSelectTargets: string;
  cleanupFailed: string;
  cleanupRows: string;
  cleanupFiles: string;
  cleanupBytes: string;
  cleanupVectorRecords: string;
  cleanupCentralSourceBoundary: string;
  knowledgeGraph: string;
  graphNodes: string;
  graphEdges: string;
  graphGpu: string;
  graphWorker: string;
  graphReadOnly: string;
  graphAcl: string;
  graphSearchPlaceholder: string;
  graphNodeTypes: string;
  graphVisibleNodes: string;
  graphVisibleEdges: string;
  graphClearFocus: string;
  graphSelectedNode: string;
  graphRelations: string;
  graphIncoming: string;
  graphOutgoing: string;
  graphNoRelations: string;
  graphNoSelection: string;
  graphInteractionHint: string;
  graphCanvasFallback: string;
  graphResponsibilityQuestion: string;
  graphDirectChildren: string;
  graphNoChildren: string;
  graphNodeKnowledge: string;
  graphKnowledgeLoading: string;
  graphKnowledgeTruncated: string;
  graphNoKnowledge: string;
};

type FilterMode = "all" | "prompt" | "visible" | "manual" | "missing";
type ManageFilterMode = "all" | "prompt" | "editable" | "changed" | "missing";
export type MemoryRouteView = "overview" | "effective" | "manage" | "sources" | "knowledge" | "graph" | "cleanup";
type MemoryChannel = "conversation" | "research" | "self_evolution" | "supervised_evolution" | "explicit_read";
type ChannelFilter = MemoryChannel | "";
type CleanupTargetOption = {
  key: string;
  label: string;
  detail: string;
  target: MemoryCleanupTargetRequest;
  risk: "high" | "critical";
};
type GraphRelation = {
  edge: MemoryKnowledgeGraphEdge;
  neighbor: MemoryKnowledgeGraphNode;
};
type MemoryPair = {
  section: MemorySection;
  item: MemoryItem;
};
type BulkMemoryAction = "disable" | "restore";
type MemoryProposalStatusFilter = "pending" | "";
type MemoryProposalResolveStatus = "applied" | "rejected" | "conflict" | "superseded";
type EditDraft = {
  mode: "create" | "edit";
  sectionId: string;
  itemId: string;
  title: string;
  summary: string;
  content: string;
};
type SourceDraft = {
  sourceType: string;
  sourceRef: string;
  sourceCreatedAt: string;
  capturedBy: string;
  evidenceRange: string;
  title: string;
  summary: string;
};
type SourceOwnerType = "team" | "agent";
type SourceInboxStatusFilter = "pending" | "accepted" | "rejected" | "duplicate" | "needs_more_context" | "all";
type OwnerSourceDraft = SourceDraft & {
  originalContent: string;
  originalFilename: string;
  sourceHash: string;
};
type ProposalDraft = {
  sourceArtifactIds: string;
  proposedByAgentId: string;
  title: string;
  summary: string;
  content: string;
  tags: string;
};
type RatingDraft = {
  actorAgentId: string;
  importanceLevel: string;
  confidence: string;
  stability: string;
  scope: string;
  reviewPriority: string;
  markingReason: string;
};
type KnowledgeSearchDraft = {
  query: string;
  tags: string;
  searchMode: "exact" | "semantic" | "hybrid";
  ragTopK: number;
  ragMaxContextChars: number;
};
type RatingSuggestionStatusFilter = "pending" | "applied" | "rejected" | "all";
type RatingSuggestionPriorityFilter = "all" | "urgent" | "elevated" | "normal";
type KnowledgeWorkspaceMode = "sources" | "search" | "review" | "governance" | "permissions";
type KnowledgePermissionEntry = KnowledgePermissionAuditPayload["knowledgeBases"][number]["permissions"][string] | string | null | undefined;

function normalizeKnowledgePermission(permission: KnowledgePermissionEntry): { allowed: boolean; reason: string } {
  if (permission && typeof permission === "object" && "allowed" in permission) {
    return {
      allowed: Boolean(permission.allowed),
      reason: String(permission.reason || "-"),
    };
  }
  return {
    allowed: false,
    reason: typeof permission === "string" && permission.trim() ? permission : "-",
  };
}

const FILTER_MODES: FilterMode[] = ["all", "prompt", "visible", "manual", "missing"];
const MANAGE_FILTER_MODES: ManageFilterMode[] = ["all", "prompt", "editable", "changed", "missing"];
const MEMORY_CHANNELS: MemoryChannel[] = ["conversation", "research", "self_evolution", "supervised_evolution", "explicit_read"];

const COPY: Record<"zh" | "en", Copy> = {
  zh: {
    eyebrow: "Memory Library",
    title: "记忆库",
    subtitle: "统一治理 Agent 私有记忆、团队知识库、来源证据和生效边界。",
    refresh: "刷新",
    loading: "正在整理记忆...",
    loadFailed: "记忆概览加载失败",
    refreshFailed: "记忆概览刷新失败",
    sections: "来源分区",
    items: "记忆条目",
    agentVisible: "agent 可感知",
    runtimeInjected: "运行时注入",
    sourcePath: "路径",
    sourceApi: "接口",
    visibility: "可见性",
    agentVisibility: "Agent 口径",
    usedBy: "作用位置",
    summary: "摘要",
    rawContent: "原文",
    noContent: "无原文",
    sourceOrigin: "来源",
    searchPlaceholder: "搜索来源、路径、摘要或作用位置",
    allSections: "全部来源",
    noMatches: "无匹配记忆",
    yes: "是",
    no: "否",
    inPrompt: "进 prompt",
    notInPrompt: "不默认注入",
    canUse: "可使用",
    manualOnly: "显式读取",
    missing: "缺失",
    truncated: "已截断",
    warnings: "诊断提醒",
    generatedAt: "生成时间",
    sectionCount: "分区",
    itemCount: "条目",
    perceptionMatrix: "感知矩阵",
    whereMemoryWorks: "记忆在哪里起作用",
    matrixItems: "条目",
    matrixPrompt: "进 prompt",
    conversationMemory: "对话",
    conversationMemoryHint: "当前会话历史、PromptManager 与 Git 现场。",
    researchMemory: "科研",
    researchMemoryHint: "科研知识库、来源溯源、论断、证据与缺口。",
    selfEvolutionMemory: "自进化",
    selfEvolutionMemoryHint: "自进化 run prompt、事务和建议基线。",
    supervisedEvolutionMemory: "监督进化",
    supervisedEvolutionMemoryHint: "评测 bundle、监督工作台和策略记录。",
    explicitReadMemory: "显式读取",
    explicitReadMemoryHint: "工具、页面或日志读取后才进入 agent 视野。",
    filters: "快速筛选",
    filterAll: "全部",
    filterPrompt: "进入 prompt",
    filterVisible: "agent 可感知",
    filterManual: "显式读取",
    filterMissing: "缺失/截断",
    manageFilters: "配置任务",
    manageFilterAll: "全部",
    manageFilterPrompt: "进 prompt",
    manageFilterEditable: "可编辑",
    manageFilterChanged: "已改写/禁用",
    manageFilterMissing: "缺失/截断",
    sourceFilters: "来源分区",
    impact: "影响说明",
    impactPromptTitle: "会进入运行上下文",
    impactPromptBody: "这条记忆会通过对应 prompt、会话历史或 harness 输入被 agent 直接感知。",
    impactVisibleTitle: "可被 agent 显式读取",
    impactVisibleBody: "这条记忆不会默认进入 prompt；agent 需要通过工具、页面或日志读取后才会使用。",
    impactManualTitle: "只作为展示或诊断证据",
    impactManualBody: "这条内容不应被理解为默认运行记忆；它主要帮助用户审查来源和证据。",
    copySourceSummary: "复制来源摘要",
    copySourcePath: "复制路径",
    copyRawContentAction: "复制原文",
    copyCurrentLink: "复制当前链接",
    copyDone: "已复制",
    copyFailed: "复制失败",
    management: "手动管理",
    addMemory: "新增记忆",
    editMemory: "编辑",
    saveMemory: "保存",
    cancelEdit: "取消",
    disableMemory: "禁用",
    restoreMemory: "恢复",
    deleteMemory: "删除",
    titleField: "标题",
    summaryField: "摘要",
    contentField: "内容",
    titlePlaceholder: "给这条记忆一个便于检查的标题",
    summaryPlaceholder: "一句话说明这条记忆的来源或作用",
    contentPlaceholder: "写入用户要保留、覆盖或标注的记忆内容",
    managementHint: "系统来源只保存覆盖状态，不改原文件；用户手动记忆会写入 workspace/memory/user_memory_overrides.json。",
    overridden: "已覆盖",
    disabledByUser: "已禁用",
    userManaged: "用户记忆",
    mutationDone: "操作已保存",
    mutationFailed: "操作失败",
    overviewView: "总览",
    effectiveView: "生效范围",
    manageView: "Agent 私有记忆",
    sourcesView: "来源审计",
    knowledgeView: "团队知识库",
    overviewSubtitle: "先看记忆健康、运行影响和需要检查的内容；复杂证据放到子页里。",
    effectiveSubtitle: "按对话、自进化、监督进化和显式读取说明哪些记忆会被 agent 感知。",
    manageSubtitle: "集中新增、编辑、禁用、恢复和删除 Agent 私有或用户可管理的记忆。",
    sourcesSubtitle: "保留完整来源、路径、接口、原文和复制动作，供专业审查使用。",
    knowledgeSubtitle: "管理团队共享知识库、来源登记、精炼提案、审核落盘和重要程度标记。",
    healthOverview: "记忆健康概览",
    affectedRuntimeMemory: "会影响运行的记忆",
    needsReview: "需要检查",
    noIssues: "无待检查",
    noRuntimeMemory: "无运行记忆",
    managedMemory: "用户管理状态",
    disabledOrOverridden: "已禁用/覆盖",
    effectiveByChannel: "按作用位置查看",
    manageAllMemory: "全部可管理记忆",
    manageConfigPanel: "配置面板",
    manageConfigHint: "先在左侧选择一条记忆，再在这里编辑、禁用、恢复或新增用户记忆。系统来源只保存覆盖状态，原始文件保持不变。",
    manageListHint: "选择一条记忆后在中间配置；右侧只负责查看来源、影响和原文。",
    selectedMemory: "选中记忆",
    selectedKnowledgeDetail: "选中知识 / 证据",
    sourceAudit: "来源审计",
    reviewQueue: "优先检查队列",
    reviewQueueHint: "按风险和运行影响排序，先看会改变 agent 行为或证据不完整的记忆。",
    projectMemoryQueue: "项目记忆合并队列",
    projectMemoryQueueHint: "并行会话只提交提案；这里记录人工确认后的处理结果，避免直接改写共享项目记忆。",
    projectMemoryQueuePendingOnly: "仅待处理",
    projectMemoryQueueAll: "全部记录",
    projectMemoryQueueAgent: "Agent",
    projectMemoryQueueLane: "记忆车道",
    projectMemoryQueueFiles: "相关文件",
    projectMemoryQueueCreated: "提交",
    projectMemoryQueueResolved: "处理",
    projectMemoryQueueResolutionNote: "处理说明",
    projectMemoryQueueEmptyPending: "无待处理提案",
    projectMemoryQueueEmptyAll: "无提案记录",
    projectMemoryQueueApply: "标记已合入",
    projectMemoryQueueReject: "拒绝",
    projectMemoryQueueConflict: "标记冲突",
    projectMemoryQueueSupersede: "标记被替代",
    reviewReason: "检查原因",
    auditMemory: "去审计",
    manageMemoryAction: "去管理",
    reasonDisabled: "已被用户禁用",
    reasonOverridden: "已被用户覆盖",
    reasonMissing: "来源缺失",
    reasonTruncated: "内容已截断",
    reasonInPrompt: "会进入 prompt",
    reasonAgentVisible: "agent 可感知",
    reasonUserManaged: "用户手动记忆",
    selectMemory: "选择记忆",
    selectedCount: "已选择",
    selectAllVisible: "选择可见项",
    clearSelection: "清空选择",
    bulkDisable: "批量禁用/删除",
    bulkRestore: "批量恢复",
    bulkActionSkipped: "已跳过不支持的条目",
    editPreview: "保存前预览",
    currentValue: "当前",
    draftValue: "修改后",
    noDraftChanges: "还没有修改。",
    teamKnowledge: "团队知识",
    knowledgeBases: "知识库",
    pendingProposals: "待审提案",
    sourceArtifacts: "来源登记",
    formalKnowledge: "正式知识",
    sourceGovernance: "来源治理",
    ownerSourceInbox: "来源收件箱",
    centralSourceRegistry: "中央来源",
    centralSources: "中央来源",
    ownerScope: "Owner 范围",
    ownerTeam: "团队",
    ownerAgent: "Agent",
    ownerId: "Owner ID",
    allSourceStatuses: "全部状态",
    pendingSources: "待审核来源",
    acceptedSources: "已接收来源",
    rejectedSources: "已拒绝来源",
    duplicateSources: "重复来源",
    needsMoreContextSources: "需补充上下文",
    collectOwnerSource: "登记来源",
    originalContent: "源文件内容",
    originalFilename: "源文件名",
    reviewSource: "审核来源",
    acceptSource: "接收",
    markDuplicate: "标记重复",
    needsMoreContext: "需补充",
    attachCentralSource: "挂到当前知识库",
    centralSourceId: "中央来源 ID",
    centralPath: "中央路径",
    originalPath: "原始路径",
    sourceHash: "来源哈希",
    curationStatus: "治理状态",
    dedupeStatus: "去重状态",
    reviewedBy: "审核人",
    reviewedAt: "审核时间",
    sourceReviewNote: "审核说明",
    noInboxSources: "无来源",
    noCentralSources: "无中央来源",
    useActiveKnowledgeOwner: "使用当前知识库 owner",
    refinementProposal: "精炼提案",
    rating: "等级标记",
    sourceType: "来源类型",
    sourceRef: "来源引用 JSON",
    sourceCreatedAt: "来源产生时间",
    capturedBy: "登记者",
    evidenceRange: "证据范围 JSON",
    proposalTitle: "提案标题",
    proposalContent: "提案内容",
    tags: "标签",
    submitSource: "登记来源",
    submitProposal: "提交提案",
    approveProposal: "审核通过",
    rejectProposal: "驳回",
    updateRating: "更新评级",
    importanceLevel: "重要程度",
    confidence: "置信度",
    stability: "稳定性",
    reviewPriority: "评审优先级",
    markingReason: "标记原因",
    noKnowledgeBases: "无团队知识库",
    knowledgeHint: "来源、提案、审核、正式知识分层治理。",
    platformPipeline: "记忆平台流水线",
    pipelineSource: "来源登记",
    pipelineProposal: "精炼提案",
    pipelineBatch: "审核批次",
    pipelineFormal: "正式知识",
    pipelineRating: "评级标记",
    toolReadableOnly: "工具可读",
    promptBoundary: "不默认进 prompt",
    agentPrivateDomain: "Agent 私有记忆",
    teamKnowledgeDomain: "团队知识库",
    governance: "治理",
    knowledgeSearch: "知识检索",
    ragRetrieval: "RAG 检索",
    ragContextCandidates: "上下文候选",
    ragRetrievalHint: "从正式知识生成带引用的候选，不自动注入 prompt。",
    ragHealth: "健康态",
    ragProvider: "Provider",
    ragVector: "向量",
    ragIndexed: "索引",
    ragStale: "过期",
    ragTopK: "候选数",
    ragContextBudget: "单条预算",
    ragNoPromptInjection: "不默认注入",
    ragCitations: "引用",
    ragNoContexts: "无上下文",
    searchQuery: "检索词",
    ratingSuggestions: "评级建议",
    submitRatingSuggestion: "提交评级建议",
    applySuggestion: "应用建议",
    rejectSuggestion: "拒绝建议",
    permissionAudit: "权限审计",
    toolVisibility: "工具可见性",
    readable: "可读",
    proposable: "可提案",
    reviewable: "可审核",
    rateable: "可评级",
    excerpt: "摘录",
    status: "状态",
    allStatuses: "全部状态",
    priority: "优先级",
    allPriorities: "全部优先级",
    selectSuggestion: "选择建议",
    selectAllVisibleSuggestions: "选择可见建议",
    clearSuggestionSelection: "清空选择",
    bulkApplySuggestions: "批量应用",
    bulkRejectSuggestions: "批量拒绝",
    selectedSuggestions: "已选建议",
    skippedSuggestions: "跳过",
    governanceTasks: "治理任务",
    ingestionAdapters: "摄取适配器",
    traceability: "证据链",
    sourceChain: "来源链路",
    outputContract: "输出合同",
    createsKnowledgeItem: "生成正式知识",
    knowledgeSteward: "知识库管理员",
    stewardMission: "治理职责",
    stewardDirectChat: "打开管理员",
    stewardBoundary: "权限边界",
    protectedAgent: "受保护 Agent",
    allowedTools: "允许工具",
    preferredTools: "优先工具",
    openGovernanceTasks: "待处理治理任务",
    noDirectApply: "不直接落正式知识",
    reviewerRequired: "正式知识需要审核角色确认",
    stewardRecommendations: "治理建议",
    stewardRecommendationHint: "只生成建议，不自动审核或落正式知识。",
    recommendationsOnly: "仅建议",
    recommendedAction: "建议动作",
    stewardWorkbench: "管理员工作台",
    stewardStages: "治理阶段",
    stewardNextActions: "下一步动作",
    acceptanceChecklist: "验收清单",
    executable: "可执行",
    operationsHealth: "运行健康",
    healthFindings: "健康发现",
    governancePlan: "治理计划",
    planOnly: "只读计划",
    searchMode: "检索模式",
    exactSearch: "精确",
    semanticSearch: "语义",
    hybridSearch: "混合",
    semanticScore: "相关度",
    usageContract: "边界策略",
    memoryDomains: "知识边界",
    allowedUse: "允许使用",
    writeBoundary: "写入边界",
    forbiddenActions: "禁止动作",
    currentContractState: "当前状态",
    graphView: "知识图谱",
    graphSubtitle: "以只读 3D 结构网观察 Project、Team、Agent、记忆、知识库、来源、进化和监督关系。",
    cleanupView: "记忆清理",
    cleanupSubtitle: "集中选择运行记忆、Agent 私有记忆、团队知识库和 RAG 元数据，预览后硬删除。",
    cleanupTargets: "清理目标",
    cleanupPreview: "预览影响",
    cleanupExecute: "执行清理",
    cleanupConfirmPhrase: "确认短语",
    cleanupConfirmPlaceholder: "输入：硬删除记忆",
    cleanupHardDelete: "硬删除",
    cleanupNoBackup: "不进入回收站，也不生成兼容副本。",
    cleanupSelectedTargets: "选中目标",
    cleanupGlobalRuntime: "全局运行记忆",
    cleanupAgentPrivate: "Agent 私有记忆",
    cleanupAgentFormalKnowledge: "Agent 正式知识",
    cleanupAgentMemoryPolicy: "Agent MemoryPolicy",
    cleanupTeamKnowledge: "团队知识库",
    cleanupKnowledgeBase: "单个知识库",
    cleanupPreviewReady: "预览已生成",
    cleanupExecuteDone: "清理完成",
    cleanupNoTargets: "当前没有可选择的清理目标。",
    cleanupSelectTargets: "先选择至少一个目标，再生成预览。",
    cleanupFailed: "清理失败",
    cleanupRows: "记录",
    cleanupFiles: "文件",
    cleanupBytes: "字节",
    cleanupVectorRecords: "RAG 索引",
    cleanupCentralSourceBoundary: "单个知识库清理不会删除中央来源文件；中央来源需要单独治理。",
    knowledgeGraph: "项目知识图谱",
    graphNodes: "节点",
    graphEdges: "连线",
    graphGpu: "GPU 渲染",
    graphWorker: "Worker 布局",
    graphReadOnly: "只读",
    graphAcl: "ACL 感知",
    graphSearchPlaceholder: "搜索节点、类型、状态或摘要",
    graphNodeTypes: "节点类型",
    graphVisibleNodes: "当前节点",
    graphVisibleEdges: "当前连线",
    graphClearFocus: "清除聚焦",
    graphSelectedNode: "选中节点",
    graphRelations: "关联关系",
    graphIncoming: "入边",
    graphOutgoing: "出边",
    graphNoRelations: "无关联",
    graphNoSelection: "选择一个节点查看摘要、时间戳、权限和关联信息。",
    graphInteractionHint: "左键移动视角 · 中键拖动图谱 · 滚轮缩放",
    graphCanvasFallback: "3D 画布正在接入；当前先展示可过滤的只读图谱结构。",
    graphResponsibilityQuestion: "职责问题",
    graphDirectChildren: "直接子成员",
    graphNoChildren: "无子成员",
    graphNodeKnowledge: "节点知识",
    graphKnowledgeLoading: "正在读取节点知识正文...",
    graphKnowledgeTruncated: "正文已截断",
    graphNoKnowledge: "无知识条目",
  },
  en: {
    eyebrow: "Memory Library",
    title: "Memory Library",
    subtitle: "Governs Agent private memory, team knowledge, source evidence, and effective scope in one place.",
    refresh: "Refresh",
    loading: "Loading memory...",
    loadFailed: "Memory overview failed to load",
    refreshFailed: "Memory overview refresh failed",
    sections: "Sources",
    items: "Memory Items",
    agentVisible: "agent visible",
    runtimeInjected: "runtime injected",
    sourcePath: "Path",
    sourceApi: "API",
    visibility: "Visibility",
    agentVisibility: "Agent visibility",
    usedBy: "Used by",
    summary: "Summary",
    rawContent: "Raw content",
    noContent: "No content",
    sourceOrigin: "Source",
    searchPlaceholder: "Search source, path, summary, or usage",
    allSections: "All sources",
    noMatches: "No matches",
    yes: "Yes",
    no: "No",
    inPrompt: "In prompt",
    notInPrompt: "Not injected",
    canUse: "Usable",
    manualOnly: "Explicit read",
    missing: "Missing",
    truncated: "Truncated",
    warnings: "Warnings",
    generatedAt: "Generated",
    sectionCount: "Sections",
    itemCount: "Items",
    perceptionMatrix: "Perception matrix",
    whereMemoryWorks: "Where memory takes effect",
    matrixItems: "items",
    matrixPrompt: "in prompt",
    conversationMemory: "Conversation",
    conversationMemoryHint: "Current session history, PromptManager, and Git state.",
    researchMemory: "Research",
    researchMemoryHint: "Research knowledge base, source provenance, claims, evidence, and gaps.",
    selfEvolutionMemory: "Self evolution",
    selfEvolutionMemoryHint: "Run prompt, transactions, and advisory baselines.",
    supervisedEvolutionMemory: "Supervised evolution",
    supervisedEvolutionMemoryHint: "Evaluation bundles, workbench state, and policy records.",
    explicitReadMemory: "Explicit read",
    explicitReadMemoryHint: "Visible only after a tool, page, or log read.",
    filters: "Quick filters",
    filterAll: "All",
    filterPrompt: "In prompt",
    filterVisible: "Agent visible",
    filterManual: "Explicit read",
    filterMissing: "Missing/truncated",
    manageFilters: "Config tasks",
    manageFilterAll: "All",
    manageFilterPrompt: "In prompt",
    manageFilterEditable: "Editable",
    manageFilterChanged: "Changed/disabled",
    manageFilterMissing: "Missing/truncated",
    sourceFilters: "Source groups",
    impact: "Impact",
    impactPromptTitle: "Injected into runtime context",
    impactPromptBody: "This memory can be directly perceived through a prompt section, conversation history, or harness input.",
    impactVisibleTitle: "Explicitly readable by the agent",
    impactVisibleBody: "This memory is not injected by default; the agent must read it through a tool, page, or log workflow.",
    impactManualTitle: "Display or diagnostic evidence",
    impactManualBody: "This content should not be treated as default runtime memory; it mainly helps review source and evidence.",
    copySourceSummary: "Copy source summary",
    copySourcePath: "Copy path",
    copyRawContentAction: "Copy raw content",
    copyCurrentLink: "Copy current link",
    copyDone: "Copied",
    copyFailed: "Copy failed",
    management: "Manual management",
    addMemory: "Add memory",
    editMemory: "Edit",
    saveMemory: "Save",
    cancelEdit: "Cancel",
    disableMemory: "Disable",
    restoreMemory: "Restore",
    deleteMemory: "Delete",
    titleField: "Title",
    summaryField: "Summary",
    contentField: "Content",
    titlePlaceholder: "Name this memory for review",
    summaryPlaceholder: "Briefly describe where it comes from or why it matters",
    contentPlaceholder: "Write the memory content, annotation, or override",
    managementHint: "System sources keep a reversible override and the original file is not changed. User memory is stored in workspace/memory/user_memory_overrides.json.",
    overridden: "Overridden",
    disabledByUser: "Disabled",
    userManaged: "User memory",
    mutationDone: "Saved",
    mutationFailed: "Action failed",
    overviewView: "Overview",
    effectiveView: "Effective scope",
    manageView: "Agent private memory",
    sourcesView: "Source audit",
    knowledgeView: "Team knowledge",
    overviewSubtitle: "Start with memory health, runtime impact, and items that need review. Detailed evidence stays in subpages.",
    effectiveSubtitle: "Shows how conversation, self-evolution, supervised evolution, and explicit-read memory can be perceived.",
    manageSubtitle: "Add, edit, disable, restore, and delete Agent-private or user-manageable memory in one place.",
    sourcesSubtitle: "Keeps the full source, path, API, raw content, and copy actions for professional audit.",
    knowledgeSubtitle: "Manage team knowledge bases, source registration, refinement proposals, review, and importance marking.",
    healthOverview: "Memory health",
    affectedRuntimeMemory: "Runtime-affecting memory",
    needsReview: "Needs review",
    noIssues: "No review items",
    noRuntimeMemory: "No runtime memory",
    managedMemory: "User-managed state",
    disabledOrOverridden: "Disabled/overridden",
    effectiveByChannel: "By effective scope",
    manageAllMemory: "All manageable memory",
    manageConfigPanel: "Configuration panel",
    manageConfigHint: "Select one memory on the left, then edit, disable, restore, or add user memory here. System sources keep reversible overrides and original files stay unchanged.",
    manageListHint: "Select a memory to configure it in the middle; the right pane is for source, impact, and raw inspection.",
    selectedMemory: "Selected memory",
    selectedKnowledgeDetail: "Selected knowledge / evidence",
    sourceAudit: "Source audit",
    reviewQueue: "Priority review queue",
    reviewQueueHint: "Sorted by risk and runtime impact so behavior-changing or incomplete evidence appears first.",
    projectMemoryQueue: "Project memory merge queue",
    projectMemoryQueueHint: "Parallel sessions submit proposals only; this queue records human-confirmed outcomes so shared project memory is not overwritten directly.",
    projectMemoryQueuePendingOnly: "Pending only",
    projectMemoryQueueAll: "All records",
    projectMemoryQueueAgent: "Agent",
    projectMemoryQueueLane: "Lane",
    projectMemoryQueueFiles: "Files",
    projectMemoryQueueCreated: "Created",
    projectMemoryQueueResolved: "Resolved",
    projectMemoryQueueResolutionNote: "Resolution note",
    projectMemoryQueueEmptyPending: "No pending proposals",
    projectMemoryQueueEmptyAll: "No proposal records",
    projectMemoryQueueApply: "Mark applied",
    projectMemoryQueueReject: "Reject",
    projectMemoryQueueConflict: "Mark conflict",
    projectMemoryQueueSupersede: "Supersede",
    reviewReason: "Review reason",
    auditMemory: "Audit",
    manageMemoryAction: "Manage",
    reasonDisabled: "Disabled by user",
    reasonOverridden: "Overridden by user",
    reasonMissing: "Source missing",
    reasonTruncated: "Content truncated",
    reasonInPrompt: "Injected into prompt",
    reasonAgentVisible: "Agent-visible",
    reasonUserManaged: "User-managed memory",
    selectMemory: "Select memory",
    selectedCount: "Selected",
    selectAllVisible: "Select visible",
    clearSelection: "Clear selection",
    bulkDisable: "Disable/delete selected",
    bulkRestore: "Restore selected",
    bulkActionSkipped: "Skipped unsupported items",
    editPreview: "Preview before saving",
    currentValue: "Current",
    draftValue: "Draft",
    noDraftChanges: "No changes yet.",
    teamKnowledge: "Team knowledge",
    knowledgeBases: "Knowledge bases",
    pendingProposals: "Pending proposals",
    sourceArtifacts: "Source artifacts",
    formalKnowledge: "Formal knowledge",
    sourceGovernance: "Source governance",
    ownerSourceInbox: "Source inbox",
    centralSourceRegistry: "Central sources",
    centralSources: "Central sources",
    ownerScope: "Owner scope",
    ownerTeam: "Team",
    ownerAgent: "Agent",
    ownerId: "Owner ID",
    allSourceStatuses: "All statuses",
    pendingSources: "Pending sources",
    acceptedSources: "Accepted sources",
    rejectedSources: "Rejected sources",
    duplicateSources: "Duplicate sources",
    needsMoreContextSources: "Needs more context",
    collectOwnerSource: "Register source",
    originalContent: "Source file content",
    originalFilename: "Source filename",
    reviewSource: "Review source",
    acceptSource: "Accept",
    markDuplicate: "Mark duplicate",
    needsMoreContext: "Needs context",
    attachCentralSource: "Attach to current KB",
    centralSourceId: "Central source ID",
    centralPath: "Central path",
    originalPath: "Original path",
    sourceHash: "Source hash",
    curationStatus: "Curation status",
    dedupeStatus: "Dedupe status",
    reviewedBy: "Reviewed by",
    reviewedAt: "Reviewed at",
    sourceReviewNote: "Review note",
    noInboxSources: "No sources",
    noCentralSources: "No central sources",
    useActiveKnowledgeOwner: "Use current KB owner",
    refinementProposal: "Refinement proposal",
    rating: "Rating",
    sourceType: "Source type",
    sourceRef: "Source ref JSON",
    sourceCreatedAt: "Source created at",
    capturedBy: "Captured by",
    evidenceRange: "Evidence range JSON",
    proposalTitle: "Proposal title",
    proposalContent: "Proposal content",
    tags: "Tags",
    submitSource: "Register source",
    submitProposal: "Submit proposal",
    approveProposal: "Approve",
    rejectProposal: "Reject",
    updateRating: "Update rating",
    importanceLevel: "Importance",
    confidence: "Confidence",
    stability: "Stability",
    reviewPriority: "Review priority",
    markingReason: "Marking reason",
    noKnowledgeBases: "No knowledge bases",
    knowledgeHint: "Sources, proposals, review, and formal knowledge stay separated.",
    platformPipeline: "Memory platform pipeline",
    pipelineSource: "Source registration",
    pipelineProposal: "Refinement proposal",
    pipelineBatch: "Review batch",
    pipelineFormal: "Formal knowledge",
    pipelineRating: "Rating mark",
    toolReadableOnly: "Tool-readable",
    promptBoundary: "Not prompt-injected",
    agentPrivateDomain: "Agent private memory",
    teamKnowledgeDomain: "Team knowledge base",
    governance: "Governance",
    knowledgeSearch: "Knowledge search",
    ragRetrieval: "RAG retrieval",
    ragContextCandidates: "Context candidates",
    ragRetrievalHint: "Builds cited candidates from formal knowledge without prompt injection.",
    ragHealth: "Health",
    ragProvider: "Provider",
    ragVector: "Vector",
    ragIndexed: "Indexed",
    ragStale: "Stale",
    ragTopK: "Candidates",
    ragContextBudget: "Context budget",
    ragNoPromptInjection: "Not injected",
    ragCitations: "Citations",
    ragNoContexts: "No contexts",
    searchQuery: "Search query",
    ratingSuggestions: "Rating suggestions",
    submitRatingSuggestion: "Submit suggestion",
    applySuggestion: "Apply suggestion",
    rejectSuggestion: "Reject suggestion",
    permissionAudit: "Permission audit",
    toolVisibility: "Tool visibility",
    readable: "Readable",
    proposable: "Proposable",
    reviewable: "Reviewable",
    rateable: "Rateable",
    excerpt: "Excerpt",
    status: "Status",
    allStatuses: "All statuses",
    priority: "Priority",
    allPriorities: "All priorities",
    selectSuggestion: "Select suggestion",
    selectAllVisibleSuggestions: "Select visible suggestions",
    clearSuggestionSelection: "Clear selection",
    bulkApplySuggestions: "Bulk apply",
    bulkRejectSuggestions: "Bulk reject",
    selectedSuggestions: "Selected suggestions",
    skippedSuggestions: "Skipped",
    governanceTasks: "Governance tasks",
    ingestionAdapters: "Ingestion adapters",
    traceability: "Traceability",
    sourceChain: "Source chain",
    outputContract: "Output contract",
    createsKnowledgeItem: "Creates formal item",
    knowledgeSteward: "Knowledge Steward",
    stewardMission: "Governance mission",
    stewardDirectChat: "Open steward",
    stewardBoundary: "Permission boundary",
    protectedAgent: "Protected Agent",
    allowedTools: "Allowed tools",
    preferredTools: "Preferred tools",
    openGovernanceTasks: "Open governance tasks",
    noDirectApply: "No direct formal write",
    reviewerRequired: "Formal knowledge requires reviewer confirmation",
    stewardRecommendations: "Governance recommendations",
    stewardRecommendationHint: "Recommendations only; no automatic review or formal writes.",
    recommendationsOnly: "Recommendations only",
    recommendedAction: "Recommended action",
    stewardWorkbench: "Steward workbench",
    stewardStages: "Governance stages",
    stewardNextActions: "Next actions",
    acceptanceChecklist: "Acceptance checklist",
    executable: "Executable",
    operationsHealth: "Operations health",
    healthFindings: "Health findings",
    governancePlan: "Governance plan",
    planOnly: "Plan only",
    searchMode: "Search mode",
    exactSearch: "Exact",
    semanticSearch: "Semantic",
    hybridSearch: "Hybrid",
    semanticScore: "Relevance",
    usageContract: "Boundary policy",
    memoryDomains: "Knowledge boundary",
    allowedUse: "Allowed use",
    writeBoundary: "Write boundary",
    forbiddenActions: "Forbidden actions",
    currentContractState: "Current state",
    graphView: "Knowledge graph",
    graphSubtitle: "Observe Project, Team, Agent, memory, knowledge, source, evolution, and supervision links as a read-only 3D network.",
    cleanupView: "Memory cleanup",
    cleanupSubtitle: "Select runtime memory, Agent private memory, team knowledge, and RAG metadata, preview them, then hard-delete.",
    cleanupTargets: "Cleanup targets",
    cleanupPreview: "Preview impact",
    cleanupExecute: "Execute cleanup",
    cleanupConfirmPhrase: "Confirmation phrase",
    cleanupConfirmPlaceholder: "Type: 硬删除记忆",
    cleanupHardDelete: "Hard delete",
    cleanupNoBackup: "No recycle bin and no compatibility copy.",
    cleanupSelectedTargets: "Selected targets",
    cleanupGlobalRuntime: "Global runtime memory",
    cleanupAgentPrivate: "Agent private memory",
    cleanupAgentFormalKnowledge: "Agent formal knowledge",
    cleanupAgentMemoryPolicy: "Agent MemoryPolicy",
    cleanupTeamKnowledge: "Team knowledge",
    cleanupKnowledgeBase: "Single knowledge base",
    cleanupPreviewReady: "Preview ready",
    cleanupExecuteDone: "Cleanup complete",
    cleanupNoTargets: "No cleanup targets are currently available.",
    cleanupSelectTargets: "Select at least one target before previewing.",
    cleanupFailed: "Cleanup failed",
    cleanupRows: "Rows",
    cleanupFiles: "Files",
    cleanupBytes: "Bytes",
    cleanupVectorRecords: "RAG index",
    cleanupCentralSourceBoundary: "Single knowledge-base cleanup does not delete central source files; central sources need separate governance.",
    knowledgeGraph: "Project knowledge graph",
    graphNodes: "Nodes",
    graphEdges: "Edges",
    graphGpu: "GPU rendering",
    graphWorker: "Worker layout",
    graphReadOnly: "Read-only",
    graphAcl: "ACL-aware",
    graphSearchPlaceholder: "Search nodes, types, status, or summaries",
    graphNodeTypes: "Node types",
    graphVisibleNodes: "Visible nodes",
    graphVisibleEdges: "Visible edges",
    graphClearFocus: "Clear focus",
    graphSelectedNode: "Selected node",
    graphRelations: "Relations",
    graphIncoming: "Incoming",
    graphOutgoing: "Outgoing",
    graphNoRelations: "No relations",
    graphNoSelection: "Select a node to inspect summary, timestamps, permissions, and links.",
    graphInteractionHint: "Left drag view · Middle drag graph · Wheel zoom",
    graphCanvasFallback: "The 3D canvas is being connected; this view shows the filterable read-only graph structure first.",
    graphResponsibilityQuestion: "Responsibility question",
    graphDirectChildren: "Direct children",
    graphNoChildren: "No children",
    graphNodeKnowledge: "Node knowledge",
    graphKnowledgeLoading: "Loading node knowledge content...",
    graphKnowledgeTruncated: "Content truncated",
    graphNoKnowledge: "No knowledge items",
  },
};

function formatTimestamp(value: string, lang: "zh" | "en") {
  const text = String(value || "").trim();
  if (!text) {
    return "-";
  }
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) {
    return text;
  }
  return new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(parsed);
}

function normalizeText(value: string) {
  return String(value || "").trim().toLowerCase();
}

function searchTarget(section: MemorySection, item: MemoryItem) {
  return normalizeText(
    [
      section.title,
      section.sourceKind,
      section.sourcePath,
      section.sourceApi,
      section.agentVisibility,
      item.title,
      item.kind,
      item.source,
      item.path,
      item.visibilityClass,
      item.channels.join(" "),
      item.summary,
      item.usedBy.join(" "),
    ].join(" "),
  );
}

function sourceOriginLabel(section: MemorySection, item: MemoryItem) {
  const origin = [section.title, item.source].map((value) => String(value || "").trim()).filter(Boolean);
  return Array.from(new Set(origin)).join(" · ") || section.sourceKind;
}

function pairSelectionKey(sectionId: string, itemId: string) {
  return `${sectionId}:${itemId}`;
}

async function copyText(text: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const textArea = document.createElement("textarea");
  textArea.value = text;
  textArea.setAttribute("readonly", "true");
  textArea.style.position = "absolute";
  textArea.style.opacity = "0";
  textArea.style.pointerEvents = "none";
  document.body.appendChild(textArea);
  textArea.select();
  const copied = document.execCommand("copy");
  document.body.removeChild(textArea);
  if (!copied) {
    throw new Error("copy failed");
  }
}

function normalizeFilterMode(value: string | null): FilterMode {
  return FILTER_MODES.includes(value as FilterMode) ? (value as FilterMode) : "all";
}

function normalizeManageFilterMode(value: string | null): ManageFilterMode {
  return MANAGE_FILTER_MODES.includes(value as ManageFilterMode) ? (value as ManageFilterMode) : "all";
}

function normalizeChannelFilter(value: string | null): ChannelFilter {
  return MEMORY_CHANNELS.includes(value as MemoryChannel) ? (value as MemoryChannel) : "";
}

function itemMatchesFilter(item: MemoryItem, filterMode: FilterMode) {
  if (filterMode === "prompt") {
    return item.visibilityClass === "prompt";
  }
  if (filterMode === "visible") {
    return item.agentVisible;
  }
  if (filterMode === "manual") {
    return item.visibilityClass === "agent_visible" || item.visibilityClass === "manual" || item.channels.includes("explicit_read");
  }
  if (filterMode === "missing") {
    return item.visibilityClass === "missing" || !item.exists || item.contentTruncated;
  }
  return true;
}

function itemMatchesChannelFilter(item: MemoryItem, channelFilter: ChannelFilter) {
  return !channelFilter || item.channels.includes(channelFilter);
}

function itemIsManageable(item: MemoryItem) {
  return Boolean(
    item.managedState?.editable
      || item.managedState?.deletable
      || item.managedState?.restorable
      || item.managedState?.userManaged
      || item.managedState?.disabled
      || item.managedState?.overridden,
  );
}

function itemMatchesManageFilter(item: MemoryItem, filterMode: ManageFilterMode) {
  if (filterMode === "prompt") {
    return item.inPrompt || item.visibilityClass === "prompt";
  }
  if (filterMode === "editable") {
    return Boolean(item.managedState?.editable || item.managedState?.userManaged);
  }
  if (filterMode === "changed") {
    return Boolean(item.managedState?.disabled || item.managedState?.overridden || item.managedState?.userManaged);
  }
  if (filterMode === "missing") {
    return item.visibilityClass === "missing" || !item.exists || item.contentTruncated;
  }
  return true;
}

function filterSections(
  sections: MemorySection[],
  activeSectionId: string,
  searchText: string,
  filterMode: FilterMode,
  channelFilter: ChannelFilter,
) {
  const query = normalizeText(searchText);
  return sections
    .filter((section) => !activeSectionId || section.id === activeSectionId)
    .map((section) => ({
      ...section,
      items: section.items.filter(
        (item) =>
          itemMatchesFilter(item, filterMode)
          && itemMatchesChannelFilter(item, channelFilter)
          && (!query || searchTarget(section, item).includes(query)),
      ),
    }))
    .filter((section) => section.items.length > 0 || !query);
}

function flattenSections(sections: MemorySection[]): MemoryPair[] {
  return sections.flatMap((section) =>
    section.items.map((item) => ({
      section,
      item,
    })),
  );
}

function matchesMemoryChannel(channelId: MemoryChannel, pair: MemoryPair) {
  return pair.item.channels.includes(channelId);
}

function countChannelItems(pairs: MemoryPair[], channelId: MemoryChannel) {
  const items = pairs.filter((pair) => matchesMemoryChannel(channelId, pair));
  return {
    itemCount: items.length,
    promptCount: items.filter(({ item }) => item.inPrompt).length,
  };
}

function channelLabel(copy: Copy, channelId: MemoryChannel) {
  if (channelId === "conversation") {
    return copy.conversationMemory;
  }
  if (channelId === "research") {
    return copy.researchMemory;
  }
  if (channelId === "self_evolution") {
    return copy.selfEvolutionMemory;
  }
  if (channelId === "supervised_evolution") {
    return copy.supervisedEvolutionMemory;
  }
  return copy.explicitReadMemory;
}

function channelHint(copy: Copy, channelId: MemoryChannel) {
  if (channelId === "conversation") {
    return copy.conversationMemoryHint;
  }
  if (channelId === "research") {
    return copy.researchMemoryHint;
  }
  if (channelId === "self_evolution") {
    return copy.selfEvolutionMemoryHint;
  }
  if (channelId === "supervised_evolution") {
    return copy.supervisedEvolutionMemoryHint;
  }
  return copy.explicitReadMemoryHint;
}

function itemChannelPills(copy: Copy, item: MemoryItem) {
  const channels = item.channels as MemoryChannel[];
  if (!channels.length) {
    return item.visibilityClass === "diagnostic"
      ? [{ label: copy.impactManualTitle, hint: copy.impactManualBody }]
      : [];
  }
  return channels.map((channelId) => ({
    label: channelLabel(copy, channelId),
    hint: channelHint(copy, channelId),
  }));
}

function channelFilterLabel(copy: Copy, channelFilter: ChannelFilter) {
  if (channelFilter === "conversation") {
    return copy.conversationMemory;
  }
  if (channelFilter === "research") {
    return copy.researchMemory;
  }
  if (channelFilter === "self_evolution") {
    return copy.selfEvolutionMemory;
  }
  if (channelFilter === "supervised_evolution") {
    return copy.supervisedEvolutionMemory;
  }
  if (channelFilter === "explicit_read") {
    return copy.explicitReadMemory;
  }
  return "";
}

function filterCount(pairs: MemoryPair[], filterMode: FilterMode) {
  return pairs.filter(({ item }) => itemMatchesFilter(item, filterMode)).length;
}

function manageFilterCount(pairs: MemoryPair[], filterMode: ManageFilterMode) {
  return pairs.filter(({ item }) => itemMatchesManageFilter(item, filterMode)).length;
}

function statusClassName(active: boolean, injected: boolean) {
  if (injected) {
    return `${styles.statusPill} ${styles.statusPillPrompt}`;
  }
  if (active) {
    return `${styles.statusPill} ${styles.statusPillVisible}`;
  }
  return `${styles.statusPill} ${styles.statusPillMuted}`;
}

function contentLanguage(contentType: string) {
  if (contentType === "json") {
    return "json";
  }
  if (contentType === "markdown") {
    return "markdown";
  }
  if (contentType === "html") {
    return "html";
  }
  return "text";
}

function impactCopy(copy: Copy, item: MemoryItem) {
  if (item.managedState?.disabled) {
    return {
      title: copy.disabledByUser,
      body: item.managedState.actionHint || copy.managementHint,
    };
  }
  if (item.inPrompt) {
    return {
      title: copy.impactPromptTitle,
      body: copy.impactPromptBody,
    };
  }
  if (item.agentVisible) {
    return {
      title: copy.impactVisibleTitle,
      body: copy.impactVisibleBody,
    };
  }
  return {
    title: copy.impactManualTitle,
    body: copy.impactManualBody,
  };
}

function buildInspectionText(copy: Copy, section: MemorySection, item: MemoryItem, url: string) {
  return [
    `${section.title} / ${item.title}`,
    `${copy.sourceOrigin}: ${sourceOriginLabel(section, item)}`,
    `${copy.sourcePath}: ${item.path || "-"}`,
    `${copy.sourceApi}: ${section.sourceApi || "-"}`,
    `${copy.visibility}: ${item.visibilityClass} · ${copy.agentVisibility}: ${section.agentVisibility}`,
    `${copy.usedBy}: ${item.usedBy.join(" · ") || "-"}`,
    url ? `URL: ${url}` : "",
  ]
    .filter(Boolean)
    .join("\n");
}

function buildMemorySearchParams(
  activeSectionId: string,
  activeItemId: string,
  activeFilter: FilterMode,
  activeManageFilter: ManageFilterMode,
  activeChannel: ChannelFilter,
  searchText: string,
  agentId = "",
) {
  const next = new URLSearchParams();
  if (agentId.trim()) {
    next.set("agentId", agentId.trim());
  }
  if (activeSectionId) {
    next.set("section", activeSectionId);
  }
  if (activeItemId) {
    next.set("item", activeItemId);
  }
  if (activeFilter !== "all") {
    next.set("filter", activeFilter);
  }
  if (activeManageFilter !== "all") {
    next.set("manage", activeManageFilter);
  }
  if (activeChannel) {
    next.set("channel", activeChannel);
  }
  if (searchText.trim()) {
    next.set("q", searchText.trim());
  }
  return next;
}

function buildMemoryLink(
  activeSectionId: string,
  activeItemId: string,
  activeFilter: FilterMode,
  activeManageFilter: ManageFilterMode,
  activeChannel: ChannelFilter,
  searchText: string,
  agentId = "",
) {
  if (typeof window === "undefined") {
    return "";
  }
  const next = buildMemorySearchParams(activeSectionId, activeItemId, activeFilter, activeManageFilter, activeChannel, searchText, agentId);
  const query = next.toString();
  return `${window.location.origin}${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`;
}

function newCreateDraft(): EditDraft {
  return {
    mode: "create",
    sectionId: "user-managed-memory",
    itemId: "",
    title: "",
    summary: "",
    content: "",
  };
}

function draftFromItem(section: MemorySection, item: MemoryItem): EditDraft {
  return {
    mode: "edit",
    sectionId: section.id,
    itemId: item.id,
    title: item.title,
    summary: item.summary,
    content: item.content,
  };
}

function newSourceDraft(): SourceDraft {
  return {
    sourceType: "manual_user_entry",
    sourceRef: "{}",
    sourceCreatedAt: "",
    capturedBy: "",
    evidenceRange: "{}",
    title: "",
    summary: "",
  };
}

function newOwnerSourceDraft(): OwnerSourceDraft {
  return {
    ...newSourceDraft(),
    originalContent: "",
    originalFilename: "source.txt",
    sourceHash: "",
  };
}

function newProposalDraft(): ProposalDraft {
  return {
    sourceArtifactIds: "",
    proposedByAgentId: "",
    title: "",
    summary: "",
    content: "",
    tags: "",
  };
}

function newRatingDraft(): RatingDraft {
  return {
    actorAgentId: "",
    importanceLevel: "high",
    confidence: "0.8",
    stability: "evolving",
    scope: "team",
    reviewPriority: "elevated",
    markingReason: "",
  };
}

function newKnowledgeSearchDraft(): KnowledgeSearchDraft {
  return {
    query: "",
    tags: "",
    searchMode: "hybrid",
    ragTopK: 5,
    ragMaxContextChars: 1200,
  };
}

function memoryMutationEndpoint(sectionId: string, itemId: string, suffix = "") {
  return `/api/memory/items/${encodeURIComponent(sectionId)}/${encodeURIComponent(itemId)}${suffix}`;
}

function agentProjectMemoryUpdatesEndpoint(status: MemoryProposalStatusFilter, limit = 100) {
  const params = new URLSearchParams();
  params.set("status", status);
  params.set("limit", String(limit));
  return `/api/agents/project-memory-updates?${params.toString()}`;
}

function projectMemoryProposalResolveEndpoint(proposal: AgentProjectMemoryUpdateProposal) {
  return `/api/agents/${encodeURIComponent(proposal.agentId)}/project-memory-updates/${encodeURIComponent(proposal.proposalId)}`;
}

function projectMemoryProposalAgentLabel(proposal: AgentProjectMemoryUpdateProposal) {
  return [proposal.agentName, proposal.agentCode, proposal.agentId].map((value) => String(value || "").trim()).find(Boolean) ?? "-";
}

function projectMemoryProposalResolverLabel(resolvedBy: string | undefined, lang: "zh" | "en") {
  const value = String(resolvedBy || "").trim();
  if (!value) {
    return "-";
  }
  if (value.toLowerCase() === "coordinator") {
    return lang === "zh" ? "旧治理记录" : "legacy governance record";
  }
  if (value.toLowerCase() === "user") {
    return lang === "zh" ? "操作者" : "operator";
  }
  return value;
}

function projectMemoryProposalResolutionFallback(copy: Copy, status: MemoryProposalResolveStatus) {
  if (status === "applied") {
    return copy.projectMemoryQueueApply;
  }
  if (status === "rejected") {
    return copy.projectMemoryQueueReject;
  }
  if (status === "conflict") {
    return copy.projectMemoryQueueConflict;
  }
  return copy.projectMemoryQueueSupersede;
}

function parseJsonObject(text: string, fallback: Record<string, unknown> = {}) {
  const trimmed = text.trim();
  if (!trimmed) {
    return fallback;
  }
  const parsed = JSON.parse(trimmed) as unknown;
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error("Expected a JSON object");
  }
  return parsed as Record<string, unknown>;
}

function commaList(value: string) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

type MemoryRouteProps = {
  forcedView?: MemoryRouteView;
};

const MEMORY_VIEWS: Array<{ key: MemoryRouteView; href: string }> = [
  { key: "overview", href: "/memory" },
  { key: "effective", href: "/memory/effective" },
  { key: "manage", href: "/memory/manage" },
  { key: "sources", href: "/memory/sources" },
  { key: "knowledge", href: "/memory/knowledge" },
  { key: "graph", href: "/memory/graph" },
  { key: "cleanup", href: "/memory/cleanup" },
];

function memoryViewLabel(copy: Copy, view: MemoryRouteView) {
  if (view === "effective") {
    return copy.effectiveView;
  }
  if (view === "manage") {
    return copy.manageView;
  }
  if (view === "sources") {
    return copy.sourcesView;
  }
  if (view === "knowledge") {
    return copy.knowledgeView;
  }
  if (view === "graph") {
    return copy.graphView;
  }
  if (view === "cleanup") {
    return copy.cleanupView;
  }
  return copy.overviewView;
}

function memoryViewSubtitle(copy: Copy, view: MemoryRouteView) {
  if (view === "effective") {
    return copy.effectiveSubtitle;
  }
  if (view === "manage") {
    return copy.manageSubtitle;
  }
  if (view === "sources") {
    return copy.sourcesSubtitle;
  }
  if (view === "knowledge") {
    return copy.knowledgeSubtitle;
  }
  if (view === "graph") {
    return copy.graphSubtitle;
  }
  if (view === "cleanup") {
    return copy.cleanupSubtitle;
  }
  return copy.overviewSubtitle;
}

function memoryPairPriority(pair: MemoryPair) {
  if (pair.item.managedState?.disabled || pair.item.managedState?.overridden) {
    return 0;
  }
  if (!pair.item.exists || pair.item.contentTruncated) {
    return 1;
  }
  if (pair.item.inPrompt) {
    return 2;
  }
  if (pair.item.agentVisible) {
    return 3;
  }
  if (pair.item.managedState?.userManaged) {
    return 4;
  }
  return 5;
}

function memoryPairActionTarget(pair: MemoryPair) {
  return pair.item.managedState?.editable
    || pair.item.managedState?.deletable
    || pair.item.managedState?.restorable
    || pair.item.managedState?.userManaged
    || pair.item.managedState?.disabled
    || pair.item.managedState?.overridden
    ? "manage"
    : "sources";
}

function reviewReasonLabels(copy: Copy, item: MemoryItem) {
  const reasons: string[] = [];
  if (item.managedState?.disabled) {
    reasons.push(copy.reasonDisabled);
  }
  if (item.managedState?.overridden) {
    reasons.push(copy.reasonOverridden);
  }
  if (!item.exists) {
    reasons.push(copy.reasonMissing);
  }
  if (item.contentTruncated) {
    reasons.push(copy.reasonTruncated);
  }
  if (item.inPrompt) {
    reasons.push(copy.reasonInPrompt);
  } else if (item.agentVisible) {
    reasons.push(copy.reasonAgentVisible);
  }
  if (item.managedState?.userManaged) {
    reasons.push(copy.reasonUserManaged);
  }
  return reasons;
}

function actorAgentIdForKnowledgeBase(base: TeamKnowledgeBase | null) {
  if (!base) {
    return "";
  }
  if (base.ownerType === "agent" && base.ownerId) {
    return base.ownerId;
  }
  const grants = base.acl.grants && typeof base.acl.grants === "object" ? base.acl.grants as Record<string, unknown> : {};
  for (const key of ["read", "review", "propose", "rate", "*"]) {
    const values = Array.isArray(grants[key]) ? grants[key] : [];
    const agentId = values.map((value) => String(value || "").trim()).find(Boolean);
    if (agentId) {
      return agentId;
    }
  }
  return "";
}

function actorAgentIdForKnowledgeContext(base: TeamKnowledgeBase | null, agents: AgentInstance[], preferredAgentId = "") {
  const preferred = preferredAgentId.trim();
  if (preferred) {
    return preferred;
  }
  const baseActor = actorAgentIdForKnowledgeBase(base);
  if (baseActor) {
    return baseActor;
  }
  const activeAgent = agents.find((agent) => agent.status !== "archived");
  return activeAgent?.agentId ?? "";
}

function appendAgentParam(params: URLSearchParams, agentId: string) {
  const normalized = agentId.trim();
  if (normalized) {
    params.set("agentId", normalized);
  }
  return params;
}

function knowledgeBaseRequestId(base: TeamKnowledgeBase | null) {
  return String(base?.scopedKnowledgeBaseId || base?.knowledgeBaseId || "").trim();
}

function normalizeSourceOwnerType(value: string | undefined | null): SourceOwnerType {
  return value === "agent" ? "agent" : "team";
}

function knowledgeBaseOwnerId(base: TeamKnowledgeBase | null) {
  if (!base) {
    return "";
  }
  return String(base.ownerId || (base.ownerType === "agent" ? base.agentId : base.teamId) || "").trim();
}

function sourceInboxStatusLabel(copy: Copy, status: SourceInboxStatusFilter | string) {
  if (status === "pending") {
    return copy.pendingSources;
  }
  if (status === "accepted") {
    return copy.acceptedSources;
  }
  if (status === "rejected") {
    return copy.rejectedSources;
  }
  if (status === "duplicate") {
    return copy.duplicateSources;
  }
  if (status === "needs_more_context") {
    return copy.needsMoreContextSources;
  }
  return copy.allSourceStatuses;
}

function policyTokenLabel(value: string | undefined, lang: "zh" | "en") {
  const normalized = String(value ?? "").trim().toLowerCase();
  const zh: Record<string, string> = {
    not_in_prompt: "不进提示词",
    conversation_context_only: "仅对话上下文",
    bounded_runtime_context: "受限运行上下文",
    proposal_and_rating_suggestion_only: "仅提案与评级建议",
    agent_runtime_dependent: "随 Agent 运行态",
    clear: "无待办",
  };
  const en: Record<string, string> = {
    not_in_prompt: "Not in prompt",
    conversation_context_only: "Conversation only",
    bounded_runtime_context: "Bounded runtime",
    proposal_and_rating_suggestion_only: "Proposal/rating only",
    agent_runtime_dependent: "Agent runtime",
    clear: "Clear",
  };
  return (lang === "zh" ? zh : en)[normalized] || normalized || "-";
}

function memoryDomainDisplayLabel(label: string | undefined, domainId: string | undefined, lang: "zh" | "en") {
  const candidates = [domainId, label].map((value) => String(value || "").trim().toLowerCase().replace(/\s+/g, "_")).filter(Boolean);
  const zh: Record<string, string> = {
    agent_private_memory: "Agent 私有",
    agent_formal_knowledge_base: "Agent 正式知识",
    agent_formal_knowledge: "Agent 正式知识",
    team_knowledge_base: "团队知识库",
    team_knowledge: "团队知识库",
    team_chat_refinement: "群聊精炼",
    self_evolution_evidence: "自进化证据",
    supervised_evolution_evidence: "监督证据",
    external_search_and_pdf: "外部搜索/PDF",
  };
  const en: Record<string, string> = {
    agent_private_memory: "Agent private",
    agent_formal_knowledge_base: "Agent knowledge",
    agent_formal_knowledge: "Agent knowledge",
    team_knowledge_base: "Team knowledge",
    team_knowledge: "Team knowledge",
    team_chat_refinement: "Chat refinement",
    self_evolution_evidence: "Self-evolution",
    supervised_evolution_evidence: "Supervised evidence",
    external_search_and_pdf: "External/PDF",
  };
  const map = lang === "zh" ? zh : en;
  const match = candidates.map((key) => map[key]).find(Boolean);
  return match || label || domainId || "-";
}

function memoryDomainOwnerLabel(owner: string | undefined, lang: "zh" | "en") {
  const normalized = String(owner ?? "").trim().toLowerCase();
  if (!normalized) return "-";
  if (lang !== "zh") return owner || "-";
  if (normalized.includes("agent")) return "Agent";
  if (normalized.includes("team")) return "团队";
  if (normalized.includes("research") || normalized.includes("parser")) return "研究管线";
  if (normalized.includes("self evolution")) return "自进化";
  if (normalized.includes("supervised")) return "监督进化";
  return owner || "-";
}

function memoryBoundaryLabel(boundary: string | undefined, lang: "zh" | "en") {
  const normalized = String(boundary ?? "").trim().toLowerCase();
  if (!normalized) return "-";
  const token = policyTokenLabel(boundary, lang);
  if (token !== normalized) return token;
  if (lang !== "zh") return boundary || "-";
  if (normalized.includes("private identity") || normalized.includes("working notes")) return "私有边界";
  if (normalized.includes("group chat") || normalized.includes("proposal material")) return "仅作来源";
  if (normalized.includes("review")) return "需审核";
  return "受控写入";
}

function stewardStageDisplayTitle(stageId: string | undefined, title: string | undefined, lang: "zh" | "en") {
  if (lang !== "zh") return title || stageId || "-";
  const candidates = [stageId, title].map((value) => String(value || "").trim().toLowerCase().replace(/\s+/g, "_")).filter(Boolean);
  const zh: Record<string, string> = {
    source_evidence_to_proposal: "来源提案",
    source_to_proposal: "来源提案",
    proposal_review: "提案审核",
    rating_review: "评级审核",
  };
  const match = candidates.map((key) => zh[key]).find(Boolean);
  return match || title || stageId || "-";
}

function compactInlineList(items: string[] | undefined, limit: number) {
  const visible = (items ?? []).map((item) => String(item).trim()).filter(Boolean);
  return {
    visible: visible.slice(0, limit),
    overflow: Math.max(0, visible.length - limit),
    title: visible.join(", "),
  };
}

function cleanupTargetKey(target: MemoryCleanupTargetRequest) {
  return [
    target.targetType,
    target.ownerType ?? "",
    target.ownerId ?? "",
    target.agentId ?? "",
    target.teamId ?? "",
    target.scopedKnowledgeBaseId ?? "",
    target.knowledgeBaseId ?? "",
  ].filter(Boolean).join(":");
}

function cleanupOwnerIdForBase(base: TeamKnowledgeBase) {
  return String(base.ownerId || (base.ownerType === "agent" ? base.agentId : base.teamId) || "").trim();
}

function cleanupOwnerLabelForBase(base: TeamKnowledgeBase, lang: "zh" | "en") {
  if (base.ownerType === "agent") {
    return `${lang === "zh" ? "Agent" : "Agent"} ${base.agentName || base.ownerId || base.agentId || "-"}`;
  }
  return `${lang === "zh" ? "团队" : "Team"} ${base.teamName || base.ownerId || base.teamId || "-"}`;
}

function formatByteCount(value: number) {
  const bytes = Number.isFinite(value) ? Math.max(0, value) : 0;
  if (bytes >= 1024 * 1024) {
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  }
  if (bytes >= 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${bytes} B`;
}

function invalidateKnowledgeDashboard(queryClient: ReturnType<typeof useQueryClient>, agentId = "") {
  void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeDashboardSnapshot(agentId) });
}

function invalidateMemoryQueries(queryClient: ReturnType<typeof useQueryClient>) {
  void queryClient.invalidateQueries({ queryKey: queryKeys.memoryOverview() });
  void queryClient.invalidateQueries({ queryKey: queryKeys.memoryItemDetails() });
}

export function MemoryRoute({ forcedView = "overview" }: MemoryRouteProps) {
  const { lang } = useShellI18n();
  const copy = COPY[lang];
  const queryClient = useQueryClient();
  const pageVisible = usePageVisibility();
  const [searchParams, setSearchParams] = useSearchParams();
  const searchParamText = searchParams.toString();
  const [activeSectionId, setActiveSectionId] = useState(() => searchParams.get("section") ?? "");
  const [activeItemId, setActiveItemId] = useState(() => searchParams.get("item") ?? "");
  const [activeFilter, setActiveFilter] = useState<FilterMode>(() => normalizeFilterMode(searchParams.get("filter")));
  const [activeManageFilter, setActiveManageFilter] = useState<ManageFilterMode>(() => normalizeManageFilterMode(searchParams.get("manage")));
  const [activeChannel, setActiveChannel] = useState<ChannelFilter>(() => normalizeChannelFilter(searchParams.get("channel")));
  const [searchText, setSearchText] = useState(() => searchParams.get("q") ?? "");
  const [copyFeedback, setCopyFeedback] = useState<{ tone: "idle" | "success" | "error"; text: string }>({
    tone: "idle",
    text: "",
  });
  const [editDraft, setEditDraft] = useState<EditDraft | null>(null);
  const [selectedMemoryKeys, setSelectedMemoryKeys] = useState<string[]>([]);
  const [mutationFeedback, setMutationFeedback] = useState<{ tone: "idle" | "success" | "error"; text: string }>({
    tone: "idle",
    text: "",
  });
  const [bulkActionPending, setBulkActionPending] = useState<BulkMemoryAction | null>(null);
  const [activeKnowledgeBaseId, setActiveKnowledgeBaseId] = useState("");
  const [activeKnowledgeWorkspaceMode, setActiveKnowledgeWorkspaceMode] = useState<KnowledgeWorkspaceMode>("sources");
  const [showOwnerSourceForm, setShowOwnerSourceForm] = useState(false);
  const [sourceOwnerType, setSourceOwnerType] = useState<SourceOwnerType>("team");
  const [sourceOwnerId, setSourceOwnerId] = useState("");
  const [sourceInboxStatus, setSourceInboxStatus] = useState<SourceInboxStatusFilter>("pending");
  const [ownerSourceDraft, setOwnerSourceDraft] = useState<OwnerSourceDraft>(() => newOwnerSourceDraft());
  const [sourceReviewNote, setSourceReviewNote] = useState("");
  const [duplicateCentralSourceId, setDuplicateCentralSourceId] = useState("");
  const [proposalDraft, setProposalDraft] = useState<ProposalDraft>(() => newProposalDraft());
  const [ratingDraft, setRatingDraft] = useState<RatingDraft>(() => newRatingDraft());
  const [knowledgeSearchDraft, setKnowledgeSearchDraft] = useState<KnowledgeSearchDraft>(() => newKnowledgeSearchDraft());
  const [ratingSuggestionStatus, setRatingSuggestionStatus] = useState<RatingSuggestionStatusFilter>("pending");
  const [ratingSuggestionPriority, setRatingSuggestionPriority] = useState<RatingSuggestionPriorityFilter>("all");
  const [selectedRatingSuggestionIds, setSelectedRatingSuggestionIds] = useState<string[]>([]);
  const [traceTargetId, setTraceTargetId] = useState("");
  const [graphSearchText, setGraphSearchText] = useState("");
  const [activeGraphNodeType, setActiveGraphNodeType] = useState("");
  const [selectedGraphNodeId, setSelectedGraphNodeId] = useState("");
  const [selectedCleanupTargetKeys, setSelectedCleanupTargetKeys] = useState<string[]>([]);
  const [cleanupConfirmationText, setCleanupConfirmationText] = useState("");
  const [cleanupPreview, setCleanupPreview] = useState<MemoryCleanupPreviewResponse | null>(null);
  const [cleanupExecution, setCleanupExecution] = useState<MemoryCleanupExecuteResponse | null>(null);
  const [cleanupFeedback, setCleanupFeedback] = useState<{ tone: "idle" | "success" | "error"; text: string }>({
    tone: "idle",
    text: "",
  });
  const [knowledgeFeedback, setKnowledgeFeedback] = useState<{ tone: "idle" | "success" | "error"; text: string }>({
    tone: "idle",
    text: "",
  });
  const requestedKnowledgeActorAgentId = (searchParams.get("agentId") ?? "").trim();
  const [memoryProposalStatusFilter, setMemoryProposalStatusFilter] = useState<MemoryProposalStatusFilter>("pending");
  const [memoryProposalResolutionNotes, setMemoryProposalResolutionNotes] = useState<Record<string, string>>({});

  const overviewQuery = useQuery({
    queryKey: queryKeys.memoryOverview(),
    queryFn: () => fetchJson<MemoryOverview>("/api/memory/overview?includeContent=false"),
    refetchInterval: resolvePollingInterval(pageVisible, 30_000),
    refetchIntervalInBackground: false,
  });
  const projectMemoryUpdatesQuery = useQuery({
    queryKey: queryKeys.agentProjectMemoryUpdates(memoryProposalStatusFilter, "", 100),
    queryFn: () => fetchJson<AgentProjectMemoryUpdateProposal[]>(agentProjectMemoryUpdatesEndpoint(memoryProposalStatusFilter, 100)),
    refetchInterval: resolvePollingInterval(pageVisible, 45_000),
    refetchIntervalInBackground: false,
    enabled: forcedView === "overview",
  });
  const memoryUsageContractQuery = useQuery({
    queryKey: queryKeys.memoryUsageContract(),
    queryFn: () => fetchJson<MemoryUsageContractPayload>("/api/memory/usage-contract"),
    refetchInterval: resolvePollingInterval(pageVisible, 60_000),
    refetchIntervalInBackground: false,
    enabled: forcedView === "knowledge",
  });

  const agentsQuery = useQuery({
    queryKey: queryKeys.agents(),
    queryFn: () => fetchJson<AgentInstance[]>("/api/agents?detail=summary"),
    enabled: forcedView === "knowledge" || forcedView === "graph" || forcedView === "cleanup",
    refetchInterval: resolvePollingInterval(pageVisible, 60_000),
    refetchIntervalInBackground: false,
  });

  const knowledgeActorAgents = agentsQuery.data ?? [];
  const fallbackKnowledgeActorAgentId = requestedKnowledgeActorAgentId || knowledgeActorAgents.find((agent) => agent.status !== "archived")?.agentId || "";

  const knowledgeDashboardSnapshotQuery = useQuery({
    queryKey: queryKeys.knowledgeDashboardSnapshot(fallbackKnowledgeActorAgentId),
    queryFn: () => {
      const params = appendAgentParam(new URLSearchParams({
        recommendationLimit: "6",
        workbenchLimit: "8",
        planLimit: "8",
      }), fallbackKnowledgeActorAgentId);
      return fetchJson<KnowledgeDashboardSnapshotPayload>(`/api/knowledge/dashboard-snapshot?${params.toString()}`);
    },
    refetchInterval: resolvePollingInterval(pageVisible, 45_000),
    refetchIntervalInBackground: false,
    enabled: (forcedView === "knowledge" || forcedView === "cleanup") && Boolean(fallbackKnowledgeActorAgentId),
  });

  const memoryKnowledgeGraphQuery = useQuery({
    queryKey: queryKeys.memoryKnowledgeGraph(fallbackKnowledgeActorAgentId, "officialResearchGraph"),
    queryFn: () => {
      const params = appendAgentParam(new URLSearchParams({ include: "officialResearchGraph" }), fallbackKnowledgeActorAgentId);
      return fetchJson<MemoryKnowledgeGraphPayload>(`/api/memory/knowledge-graph?${params.toString()}`);
    },
    refetchInterval: resolvePollingInterval(pageVisible, 60_000),
    refetchIntervalInBackground: false,
    enabled: forcedView === "graph" && Boolean(fallbackKnowledgeActorAgentId),
  });
  const memoryKnowledgeGraphNodeDetailQuery = useQuery({
    queryKey: queryKeys.memoryKnowledgeGraphNodeDetail(selectedGraphNodeId, fallbackKnowledgeActorAgentId),
    queryFn: () => {
      const params = appendAgentParam(new URLSearchParams({ nodeId: selectedGraphNodeId }), fallbackKnowledgeActorAgentId);
      return fetchJson<MemoryKnowledgeGraphNodeDetailPayload>(`/api/memory/knowledge-graph/node-detail?${params.toString()}`);
    },
    refetchInterval: false,
    enabled: forcedView === "graph" && Boolean(selectedGraphNodeId) && Boolean(fallbackKnowledgeActorAgentId),
  });

  const memoryMutation = useMutation({
    mutationFn: async (draft: EditDraft) => {
      const body = JSON.stringify({
        title: draft.title,
        summary: draft.summary,
        content: draft.content,
      });
      if (draft.mode === "create") {
        return fetchJson<MemoryMutationResponse>("/api/memory/items", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body,
        });
      }
      return fetchJson<MemoryMutationResponse>(memoryMutationEndpoint(draft.sectionId, draft.itemId), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body,
      });
    },
    onSuccess: (payload) => {
      setEditDraft(null);
      setActiveSectionId(payload.sectionId);
      setActiveItemId(payload.itemId);
      setMutationFeedback({ tone: "success", text: copy.mutationDone });
      invalidateMemoryQueries(queryClient);
    },
    onError: (error) => {
      setMutationFeedback({
        tone: "error",
        text: `${copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}`,
      });
    },
  });

  const deleteMemoryMutation = useMutation({
    mutationFn: async ({ sectionId, itemId }: { sectionId: string; itemId: string }) =>
      fetchJson<MemoryMutationResponse>(memoryMutationEndpoint(sectionId, itemId), {
        method: "DELETE",
      }),
    onSuccess: (payload) => {
      setActiveSectionId(payload.sectionId === "user-managed-memory" ? "" : payload.sectionId);
      setActiveItemId(payload.sectionId === "user-managed-memory" ? "" : payload.itemId);
      setMutationFeedback({ tone: "success", text: copy.mutationDone });
      invalidateMemoryQueries(queryClient);
    },
    onError: (error) => {
      setMutationFeedback({
        tone: "error",
        text: `${copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}`,
      });
    },
  });

  const restoreMemoryMutation = useMutation({
    mutationFn: async ({ sectionId, itemId }: { sectionId: string; itemId: string }) =>
      fetchJson<MemoryMutationResponse>(memoryMutationEndpoint(sectionId, itemId, "/restore"), {
        method: "POST",
      }),
    onSuccess: (payload) => {
      setActiveSectionId(payload.sectionId);
      setActiveItemId(payload.itemId);
      setMutationFeedback({ tone: "success", text: copy.mutationDone });
      invalidateMemoryQueries(queryClient);
    },
    onError: (error) => {
      setMutationFeedback({
        tone: "error",
        text: `${copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}`,
      });
    },
  });

  const projectMemoryUpdateResolveMutation = useMutation({
    mutationFn: async ({
      proposal,
      status,
      resolutionNote,
    }: {
      proposal: AgentProjectMemoryUpdateProposal;
      status: MemoryProposalResolveStatus;
      resolutionNote: string;
    }) =>
      fetchJson<AgentProjectMemoryUpdateProposal>(projectMemoryProposalResolveEndpoint(proposal), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          status,
          resolvedBy: "user",
          resolutionNote,
        }),
      }),
    onSuccess: (proposal) => {
      setMutationFeedback({ tone: "success", text: `${copy.mutationDone} · ${proposal.status}` });
      setMemoryProposalResolutionNotes((current) => {
        const next = { ...current };
        delete next[proposal.proposalId];
        return next;
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentProjectMemoryUpdates("pending", "", 100) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentProjectMemoryUpdates("", "", 100) });
    },
    onError: (error) => {
      setMutationFeedback({
        tone: "error",
        text: `${copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}`,
      });
    },
  });

  const cleanupPreviewMutation = useMutation({
    mutationFn: async (targets: MemoryCleanupTargetRequest[]) =>
      fetchJson<MemoryCleanupPreviewResponse>("/api/memory/cleanup/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ targets }),
      }),
    onSuccess: (payload) => {
      setCleanupPreview(payload);
      setCleanupExecution(null);
      setCleanupFeedback({ tone: "success", text: copy.cleanupPreviewReady });
      void queryClient.setQueryData(queryKeys.memoryCleanupPreview(), payload);
    },
    onError: (error) => {
      setCleanupFeedback({
        tone: "error",
        text: `${copy.cleanupFailed}: ${error instanceof Error ? error.message : String(error)}`,
      });
    },
  });

  const cleanupExecuteMutation = useMutation({
    mutationFn: async ({ targets, confirmationPhrase }: { targets: MemoryCleanupTargetRequest[]; confirmationPhrase: string }) =>
      fetchJson<MemoryCleanupExecuteResponse>("/api/memory/cleanup/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ targets, confirmationPhrase }),
      }),
    onSuccess: (payload) => {
      setCleanupPreview(payload);
      setCleanupExecution(payload);
      setCleanupConfirmationText("");
      setCleanupFeedback({ tone: "success", text: copy.cleanupExecuteDone });
      invalidateMemoryQueries(queryClient);
      invalidateKnowledgeDashboard(queryClient, fallbackKnowledgeActorAgentId);
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.memoryKnowledgeGraph(fallbackKnowledgeActorAgentId, "officialResearchGraph") });
      void queryClient.invalidateQueries({ queryKey: ["knowledge"] });
    },
    onError: (error) => {
      setCleanupFeedback({
        tone: "error",
        text: `${copy.cleanupFailed}: ${error instanceof Error ? error.message : String(error)}`,
      });
    },
  });

  const proposalMutation = useMutation({
    mutationFn: async ({ knowledgeBaseId, draft }: { knowledgeBaseId: string; draft: ProposalDraft }) =>
      fetchJson<KnowledgeRefinementProposal>(`/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/refinement-proposals`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sourceArtifactIds: commaList(draft.sourceArtifactIds),
          proposedByAgentId: draft.proposedByAgentId,
          title: draft.title,
          summary: draft.summary,
          content: draft.content,
          tags: commaList(draft.tags),
        }),
      }),
    onSuccess: () => {
      setProposalDraft(newProposalDraft());
      setKnowledgeFeedback({ tone: "success", text: copy.mutationDone });
      invalidateKnowledgeDashboard(queryClient, activeKnowledgeActorAgentId);
      invalidateMemoryQueries(queryClient);
    },
    onError: (error) => {
      setKnowledgeFeedback({ tone: "error", text: `${copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}` });
    },
  });

  const reviewMutation = useMutation({
    mutationFn: async ({ knowledgeBaseId, proposalId, status }: { knowledgeBaseId: string; proposalId: string; status: string }) =>
      fetchJson<KnowledgeReviewResponse>(
        `/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/refinement-proposals/${encodeURIComponent(proposalId)}/review`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status, reviewedByAgentId: activeKnowledgeActorAgentId }),
        },
      ),
    onSuccess: (payload) => {
      setKnowledgeFeedback({ tone: "success", text: payload.item ? `${copy.mutationDone} · ${payload.item.title}` : copy.mutationDone });
      invalidateKnowledgeDashboard(queryClient, activeKnowledgeActorAgentId);
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeItems(activeKnowledgeBaseForItems, activeKnowledgeActorAgentId) });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.knowledgeSearch(
          activeKnowledgeBaseForItems,
          activeKnowledgeActorAgentId,
          knowledgeSearchDraft.query,
          knowledgeSearchDraft.tags,
          knowledgeSearchDraft.searchMode,
        ),
      });
      invalidateMemoryQueries(queryClient);
    },
    onError: (error) => {
      setKnowledgeFeedback({ tone: "error", text: `${copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}` });
    },
  });

  const ratingMutation = useMutation({
    mutationFn: async ({ knowledgeBaseId, item, draft }: { knowledgeBaseId: string; item: KnowledgeItem; draft: RatingDraft }) =>
      fetchJson<KnowledgeRatingSuggestion>(`/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/rating-suggestions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          suggestedByAgentId: draft.actorAgentId,
          targetType: "knowledge_item",
          knowledgeItemId: item.knowledgeItemId,
          importanceLevel: draft.importanceLevel,
          confidence: draft.confidence.trim() ? Number(draft.confidence) : null,
          stability: draft.stability,
          reviewPriority: draft.reviewPriority,
          markingReason: draft.markingReason,
        }),
      }),
    onSuccess: () => {
      setKnowledgeFeedback({ tone: "success", text: copy.mutationDone });
      void queryClient.invalidateQueries({ queryKey: ["knowledge", "rating-suggestions"] });
      invalidateKnowledgeDashboard(queryClient, activeKnowledgeActorAgentId);
    },
    onError: (error) => {
      setKnowledgeFeedback({ tone: "error", text: `${copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}` });
    },
  });

  const ratingSuggestionReviewMutation = useMutation({
    mutationFn: async ({ knowledgeBaseId, suggestionId, status }: { knowledgeBaseId: string; suggestionId: string; status: "applied" | "rejected" }) =>
      fetchJson<KnowledgeRatingSuggestionReviewResponse>(
        `/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/rating-suggestions/${encodeURIComponent(suggestionId)}/review`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status, reviewedByAgentId: activeKnowledgeActorAgentId }),
        },
      ),
    onSuccess: () => {
      setKnowledgeFeedback({ tone: "success", text: copy.mutationDone });
      void queryClient.invalidateQueries({ queryKey: ["knowledge", "rating-suggestions"] });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeItems(activeKnowledgeBaseForItems, activeKnowledgeActorAgentId) });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.knowledgeSearch(
          activeKnowledgeBaseForItems,
          activeKnowledgeActorAgentId,
          knowledgeSearchDraft.query,
          knowledgeSearchDraft.tags,
          knowledgeSearchDraft.searchMode,
        ),
      });
      invalidateKnowledgeDashboard(queryClient, activeKnowledgeActorAgentId);
    },
    onError: (error) => {
      setKnowledgeFeedback({ tone: "error", text: `${copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}` });
    },
  });

  const ratingSuggestionBulkReviewMutation = useMutation({
    mutationFn: async ({ knowledgeBaseId, suggestionIds, status }: { knowledgeBaseId: string; suggestionIds: string[]; status: "applied" | "rejected" }) =>
      fetchJson<KnowledgeRatingSuggestionBulkReviewResponse>(
        `/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/rating-suggestions/review-batch`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ suggestionIds, status, reviewedByAgentId: activeKnowledgeActorAgentId }),
        },
      ),
    onSuccess: (payload) => {
      setSelectedRatingSuggestionIds([]);
      setKnowledgeFeedback({
        tone: "success",
        text: `${copy.mutationDone} · ${payload.summary.reviewedCount}/${payload.summary.requestedCount}${payload.summary.skippedCount ? ` · ${copy.skippedSuggestions}: ${payload.summary.skippedCount}` : ""}`,
      });
      void queryClient.invalidateQueries({ queryKey: ["knowledge", "rating-suggestions"] });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeItems(activeKnowledgeBaseForItems, activeKnowledgeActorAgentId) });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.knowledgeSearch(
          activeKnowledgeBaseForItems,
          activeKnowledgeActorAgentId,
          knowledgeSearchDraft.query,
          knowledgeSearchDraft.tags,
          knowledgeSearchDraft.searchMode,
        ),
      });
      invalidateKnowledgeDashboard(queryClient, activeKnowledgeActorAgentId);
    },
    onError: (error) => {
      setKnowledgeFeedback({ tone: "error", text: `${copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}` });
    },
  });

  const overview = overviewQuery.data;
  const projectMemoryUpdateProposals = projectMemoryUpdatesQuery.data ?? [];
  const pendingProjectMemoryProposalCount = projectMemoryUpdateProposals.filter((proposal) => proposal.status === "pending").length;
  const projectMemoryProposalLaneCount = new Set(projectMemoryUpdateProposals.map((proposal) => proposal.laneId).filter(Boolean)).size;
  const memoryUsageContract = memoryUsageContractQuery.data;
  const sections = overview?.sections ?? [];
  const knowledgeDashboardSnapshot = knowledgeDashboardSnapshotQuery.data;
  const knowledgeOverview = knowledgeDashboardSnapshot?.overview;
  const knowledgeSteward = knowledgeDashboardSnapshot?.steward;
  const knowledgeStewardRecommendations = knowledgeDashboardSnapshot?.recommendations.recommendations ?? [];
  const knowledgeStewardWorkbench = knowledgeDashboardSnapshot?.workbench;
  const knowledgeOperationsHealth = knowledgeDashboardSnapshot?.operationsHealth;
  const knowledgeGovernancePlan = knowledgeDashboardSnapshot?.governancePlan;
  const knowledgeBases = knowledgeOverview?.knowledgeBases ?? [];
  const activeKnowledgeBase: TeamKnowledgeBase | null =
    knowledgeBases.find((base) => knowledgeBaseRequestId(base) === activeKnowledgeBaseId) ?? knowledgeBases[0] ?? null;
  const activeKnowledgeBaseForItems = knowledgeBaseRequestId(activeKnowledgeBase);
  const activeKnowledgeActorAgentId = actorAgentIdForKnowledgeContext(activeKnowledgeBase, knowledgeActorAgents, fallbackKnowledgeActorAgentId);
  const cleanupTargetOptions = useMemo<CleanupTargetOption[]>(() => {
    const options: CleanupTargetOption[] = [
      {
        key: "global_runtime_memory",
        label: copy.cleanupGlobalRuntime,
        detail: "workspace/memory, STATE_MEMORY.md, workspace/agent_brain.db memory tables",
        target: { targetType: "global_runtime_memory" },
        risk: "critical",
      },
    ];
    const addOption = (option: Omit<CleanupTargetOption, "key">) => {
      const key = cleanupTargetKey(option.target);
      if (!options.some((item) => item.key === key)) {
        options.push({ ...option, key });
      }
    };
    knowledgeActorAgents
      .filter((agent) => agent.status !== "archived")
      .forEach((agent) => {
        const agentName = agent.displayName || agent.agentCode || agent.agentId;
        addOption({
          label: `${copy.cleanupAgentPrivate} · ${agentName}`,
          detail: agent.workspacePath ? `${agent.workspacePath}/memory` : `workspace/agents/${agent.agentId}/memory`,
          target: { targetType: "agent_private_memory", agentId: agent.agentId },
          risk: "critical",
        });
        addOption({
          label: `${copy.cleanupAgentFormalKnowledge} · ${agentName}`,
          detail: agent.workspacePath ? `${agent.workspacePath}/knowledge` : `workspace/agents/${agent.agentId}/knowledge`,
          target: { targetType: "agent_formal_knowledge", agentId: agent.agentId },
          risk: "critical",
        });
        addOption({
          label: `${copy.cleanupAgentMemoryPolicy} · ${agentName}`,
          detail: agent.memoryPolicyId || `memory-${agent.agentId}`,
          target: { targetType: "agent_memory_policy", agentId: agent.agentId },
          risk: "high",
        });
      });
    knowledgeBases.forEach((base) => {
      const ownerId = cleanupOwnerIdForBase(base);
      const ownerType = String(base.ownerType || "team");
      if (ownerId && ownerType === "team") {
        addOption({
          label: `${copy.cleanupTeamKnowledge} · ${base.teamName || ownerId}`,
          detail: `workspace/teams/${ownerId}/knowledge`,
          target: { targetType: "team_knowledge", teamId: ownerId, ownerType: "team", ownerId },
          risk: "critical",
        });
      }
      if (ownerId && (ownerType === "team" || ownerType === "agent")) {
        addOption({
          label: `${copy.cleanupKnowledgeBase} · ${base.name}`,
          detail: `${cleanupOwnerLabelForBase(base, lang)} · ${base.scopedKnowledgeBaseId || base.knowledgeBaseId}`,
          target: {
            targetType: "knowledge_base",
            ownerType,
            ownerId,
            teamId: ownerType === "team" ? ownerId : "",
            agentId: ownerType === "agent" ? ownerId : "",
            knowledgeBaseId: base.knowledgeBaseId,
            scopedKnowledgeBaseId: base.scopedKnowledgeBaseId || "",
          },
          risk: "critical",
        });
      }
    });
    return options;
  }, [copy, knowledgeActorAgents, knowledgeBases, lang]);
  const selectedCleanupTargets = useMemo(
    () =>
      cleanupTargetOptions
        .filter((option) => selectedCleanupTargetKeys.includes(option.key))
        .map((option) => option.target),
    [cleanupTargetOptions, selectedCleanupTargetKeys],
  );
  const activeSourceOwnerType = sourceOwnerType;
  const activeSourceOwnerId = sourceOwnerId.trim();
  const activeSourceInboxStatus = sourceInboxStatus === "all" ? "" : sourceInboxStatus;
  const knowledgeItemsQuery = useQuery({
    queryKey: queryKeys.knowledgeItems(activeKnowledgeBaseForItems, activeKnowledgeActorAgentId),
    queryFn: () => {
      const params = appendAgentParam(new URLSearchParams(), activeKnowledgeActorAgentId);
      return fetchJson<KnowledgeItemsPayload>(`/api/knowledge-bases/${encodeURIComponent(activeKnowledgeBaseForItems)}/items?${params.toString()}`);
    },
    enabled: forcedView === "knowledge" && Boolean(activeKnowledgeBaseForItems) && Boolean(activeKnowledgeActorAgentId),
    refetchInterval: resolvePollingInterval(pageVisible, 45_000),
    refetchIntervalInBackground: false,
  });
  const knowledgeItems = knowledgeItemsQuery.data?.items ?? [];
  const knowledgeSearchQuery = useQuery({
    queryKey: queryKeys.knowledgeSearch(
      activeKnowledgeBaseForItems,
      activeKnowledgeActorAgentId,
      knowledgeSearchDraft.query,
      knowledgeSearchDraft.tags,
      knowledgeSearchDraft.searchMode,
    ),
    queryFn: () => {
      const params = new URLSearchParams();
      params.set("agentId", activeKnowledgeActorAgentId);
      if (activeKnowledgeBaseForItems) {
        params.set("knowledgeBaseId", activeKnowledgeBaseForItems);
      }
      if (knowledgeSearchDraft.query.trim()) {
        params.set("query", knowledgeSearchDraft.query.trim());
      }
      commaList(knowledgeSearchDraft.tags).forEach((tag) => params.append("tags", tag));
      params.set("searchMode", knowledgeSearchDraft.searchMode);
      params.set("limit", "12");
      return fetchJson<KnowledgeSearchPayload>(`/api/knowledge/search?${params.toString()}`);
    },
    enabled: forcedView === "knowledge" && Boolean(activeKnowledgeBaseForItems) && Boolean(activeKnowledgeActorAgentId),
    refetchInterval: false,
  });
  const knowledgeRagHealthQuery = useQuery({
    queryKey: queryKeys.knowledgeRagHealth(activeKnowledgeActorAgentId),
    queryFn: () => {
      const params = appendAgentParam(new URLSearchParams(), activeKnowledgeActorAgentId);
      return fetchJson<KnowledgeRagHealthPayload>(`/api/knowledge/rag/health?${params.toString()}`);
    },
    enabled: forcedView === "knowledge" && Boolean(activeKnowledgeActorAgentId),
    refetchInterval: resolvePollingInterval(pageVisible, 60_000),
    refetchIntervalInBackground: false,
  });
  const knowledgeRagRetrieveQuery = useQuery({
    queryKey: queryKeys.knowledgeRagRetrieve(
      activeKnowledgeBaseForItems,
      activeKnowledgeActorAgentId,
      knowledgeSearchDraft.query,
      knowledgeSearchDraft.tags,
      knowledgeSearchDraft.searchMode,
      knowledgeSearchDraft.ragTopK,
      knowledgeSearchDraft.ragMaxContextChars,
    ),
    queryFn: () => {
      const params = new URLSearchParams();
      params.set("agentId", activeKnowledgeActorAgentId);
      if (activeKnowledgeBaseForItems) {
        params.set("knowledgeBaseId", activeKnowledgeBaseForItems);
      }
      if (knowledgeSearchDraft.query.trim()) {
        params.set("query", knowledgeSearchDraft.query.trim());
      }
      commaList(knowledgeSearchDraft.tags).forEach((tag) => params.append("tags", tag));
      params.set("retrievalMode", knowledgeSearchDraft.searchMode);
      params.set("provider", "local");
      params.set("topK", String(knowledgeSearchDraft.ragTopK));
      params.set("maxContextChars", String(knowledgeSearchDraft.ragMaxContextChars));
      return fetchJson<KnowledgeRagRetrievalPayload>(`/api/knowledge/rag/retrieve?${params.toString()}`);
    },
    enabled: forcedView === "knowledge" && Boolean(activeKnowledgeBaseForItems) && Boolean(activeKnowledgeActorAgentId),
    refetchInterval: false,
  });
  const ratingSuggestionsQuery = useQuery({
    queryKey: queryKeys.knowledgeRatingSuggestions(
      activeKnowledgeBaseForItems,
      activeKnowledgeActorAgentId,
      ratingSuggestionStatus,
      ratingSuggestionPriority,
    ),
    queryFn: () => {
      const params = appendAgentParam(new URLSearchParams(), activeKnowledgeActorAgentId);
      if (ratingSuggestionStatus !== "all") {
        params.set("status", ratingSuggestionStatus);
      }
      return fetchJson<KnowledgeRatingSuggestionsPayload>(
        `/api/knowledge-bases/${encodeURIComponent(activeKnowledgeBaseForItems)}/rating-suggestions?${params.toString()}`,
      );
    },
    enabled: forcedView === "knowledge" && Boolean(activeKnowledgeBaseForItems) && Boolean(activeKnowledgeActorAgentId),
    refetchInterval: resolvePollingInterval(pageVisible, 45_000),
    refetchIntervalInBackground: false,
  });
  const permissionAuditQuery = useQuery({
    queryKey: queryKeys.knowledgePermissionAudit(activeKnowledgeActorAgentId),
    queryFn: () => fetchJson<KnowledgePermissionAuditPayload>(`/api/knowledge/permissions/audit?agentId=${encodeURIComponent(activeKnowledgeActorAgentId)}`),
    enabled: forcedView === "knowledge" && Boolean(activeKnowledgeActorAgentId),
    refetchInterval: resolvePollingInterval(pageVisible, 60_000),
    refetchIntervalInBackground: false,
  });
  const governanceTasksQuery = useQuery({
    queryKey: queryKeys.knowledgeGovernanceTasks(activeKnowledgeActorAgentId, "open"),
    queryFn: () => fetchJson<KnowledgeGovernanceTasksPayload>(`/api/knowledge/governance/tasks?agentId=${encodeURIComponent(activeKnowledgeActorAgentId)}&status=open`),
    enabled: forcedView === "knowledge" && Boolean(activeKnowledgeActorAgentId),
    refetchInterval: resolvePollingInterval(pageVisible, 45_000),
    refetchIntervalInBackground: false,
  });
  const ingestionAdaptersQuery = useQuery({
    queryKey: queryKeys.knowledgeIngestionAdapters(),
    queryFn: () => fetchJson<KnowledgeIngestionAdaptersPayload>("/api/knowledge/ingestion-adapters"),
    enabled: forcedView === "knowledge",
    refetchInterval: false,
  });
  const knowledgeTraceQuery = useQuery({
    queryKey: queryKeys.knowledgeTrace(activeKnowledgeBaseForItems, activeKnowledgeActorAgentId, traceTargetId),
    queryFn: () => {
      const params = appendAgentParam(new URLSearchParams(), activeKnowledgeActorAgentId);
      return fetchJson<KnowledgeTracePayload>(
        `/api/knowledge-bases/${encodeURIComponent(activeKnowledgeBaseForItems)}/trace/${encodeURIComponent(traceTargetId)}?${params.toString()}`,
      );
    },
    enabled: forcedView === "knowledge" && Boolean(activeKnowledgeBaseForItems) && Boolean(activeKnowledgeActorAgentId) && Boolean(traceTargetId),
    refetchInterval: false,
  });
  const sourceInboxQuery = useQuery({
    queryKey: queryKeys.knowledgeSourceInbox(activeSourceOwnerType, activeSourceOwnerId, activeKnowledgeActorAgentId, activeSourceInboxStatus),
    queryFn: () => {
      const params = new URLSearchParams({
        ownerType: activeSourceOwnerType,
        ownerId: activeSourceOwnerId,
        agentId: activeKnowledgeActorAgentId,
      });
      if (activeSourceInboxStatus) {
        params.set("status", activeSourceInboxStatus);
      }
      return fetchJson<KnowledgeSourceInboxPayload>(`/api/knowledge/sources/inbox?${params.toString()}`);
    },
    enabled: forcedView === "knowledge" && Boolean(activeSourceOwnerId) && Boolean(activeKnowledgeActorAgentId),
    refetchInterval: resolvePollingInterval(pageVisible, 45_000),
    refetchIntervalInBackground: false,
  });
  const centralSourcesQuery = useQuery({
    queryKey: queryKeys.knowledgeCentralSources(activeKnowledgeActorAgentId, activeSourceOwnerType, activeSourceOwnerId),
    queryFn: () => {
      const params = new URLSearchParams({
        agentId: activeKnowledgeActorAgentId,
        ownerType: activeSourceOwnerType,
        ownerId: activeSourceOwnerId,
      });
      return fetchJson<KnowledgeCentralSourceRegistryPayload>(`/api/knowledge/sources/registry?${params.toString()}`);
    },
    enabled: forcedView === "knowledge" && Boolean(activeSourceOwnerId) && Boolean(activeKnowledgeActorAgentId),
    refetchInterval: resolvePollingInterval(pageVisible, 60_000),
    refetchIntervalInBackground: false,
  });
  const sourceInboxCollectMutation = useMutation({
    mutationFn: async (draft: OwnerSourceDraft) =>
      fetchJson<KnowledgeOwnerSource>("/api/knowledge/sources/inbox", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ownerType: activeSourceOwnerType,
          ownerId: activeSourceOwnerId,
          sourceType: draft.sourceType,
          sourceRef: parseJsonObject(draft.sourceRef),
          originalContent: draft.originalContent,
          originalFilename: draft.originalFilename,
          sourceCreatedAt: draft.sourceCreatedAt,
          capturedBy: draft.capturedBy.trim() || activeKnowledgeActorAgentId,
          sourceHash: draft.sourceHash,
          evidenceRange: parseJsonObject(draft.evidenceRange),
          title: draft.title,
          summary: draft.summary,
          actorAgentId: activeKnowledgeActorAgentId,
        }),
      }),
    onSuccess: () => {
      setOwnerSourceDraft(newOwnerSourceDraft());
      setKnowledgeFeedback({ tone: "success", text: copy.mutationDone });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.knowledgeSourceInbox(activeSourceOwnerType, activeSourceOwnerId, activeKnowledgeActorAgentId, activeSourceInboxStatus),
      });
      invalidateMemoryQueries(queryClient);
    },
    onError: (error) => {
      setKnowledgeFeedback({ tone: "error", text: `${copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}` });
    },
  });
  const sourceInboxReviewMutation = useMutation({
    mutationFn: async ({ source, decision }: { source: KnowledgeOwnerSource; decision: "accepted" | "rejected" | "duplicate" | "needs_more_context" }) =>
      fetchJson<KnowledgeSourceInboxReviewResponse>(
        `/api/knowledge/sources/inbox/${encodeURIComponent(activeSourceOwnerType)}/${encodeURIComponent(activeSourceOwnerId)}/${encodeURIComponent(source.inboxSourceId)}/review`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            decision,
            reviewedByAgentId: activeKnowledgeActorAgentId,
            resolutionNote: sourceReviewNote,
            duplicateOf: decision === "duplicate" ? duplicateCentralSourceId : "",
          }),
        },
      ),
    onSuccess: (payload) => {
      setKnowledgeFeedback({ tone: "success", text: payload.centralSource?.centralSourceId ? `${copy.mutationDone} · ${payload.centralSource.centralSourceId}` : copy.mutationDone });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.knowledgeSourceInbox(activeSourceOwnerType, activeSourceOwnerId, activeKnowledgeActorAgentId, activeSourceInboxStatus),
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeCentralSources(activeKnowledgeActorAgentId, activeSourceOwnerType, activeSourceOwnerId) });
      invalidateKnowledgeDashboard(queryClient, activeKnowledgeActorAgentId);
      invalidateMemoryQueries(queryClient);
    },
    onError: (error) => {
      setKnowledgeFeedback({ tone: "error", text: `${copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}` });
    },
  });
  const centralSourceAttachMutation = useMutation({
    mutationFn: async (centralSourceId: string) =>
      fetchJson<KnowledgeSourceArtifact>(`/api/knowledge-bases/${encodeURIComponent(activeKnowledgeBaseForItems)}/central-source-artifacts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          centralSourceId,
          actorAgentId: activeKnowledgeActorAgentId,
        }),
      }),
    onSuccess: (payload) => {
      setProposalDraft((current) => ({
        ...current,
        sourceArtifactIds: [...commaList(current.sourceArtifactIds), payload.sourceArtifactId].join(", "),
      }));
      setKnowledgeFeedback({ tone: "success", text: `${copy.mutationDone} · ${payload.sourceArtifactId}` });
      invalidateKnowledgeDashboard(queryClient, activeKnowledgeActorAgentId);
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeItems(activeKnowledgeBaseForItems, activeKnowledgeActorAgentId) });
      invalidateMemoryQueries(queryClient);
    },
    onError: (error) => {
      setKnowledgeFeedback({ tone: "error", text: `${copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}` });
    },
  });
  const knowledgeSearchResults = knowledgeSearchQuery.data?.results ?? [];
  const knowledgeRagContexts = knowledgeRagRetrieveQuery.data?.contexts ?? [];
  const ownerInboxSources = sourceInboxQuery.data?.sources ?? [];
  const centralSources = centralSourcesQuery.data?.centralSources ?? [];
  const knowledgeRagHealth = knowledgeRagHealthQuery.data;
  const localRagProviderHealth = knowledgeRagHealth?.providers.find((provider) => provider.provider === "local") ?? knowledgeRagHealth?.providers[0];
  const knowledgeRagPolicy = knowledgeRagHealth?.retrievalPolicy ?? knowledgeRagRetrieveQuery.data?.retrievalPolicy;
  const ratingSuggestions = (ratingSuggestionsQuery.data?.suggestions ?? []).filter((suggestion) =>
    ratingSuggestionPriority === "all" ? true : suggestion.reviewPriority === ratingSuggestionPriority,
  );
  const pendingVisibleRatingSuggestions = ratingSuggestions.filter((suggestion) => suggestion.status === "pending");
  const selectedVisibleRatingSuggestionIds = selectedRatingSuggestionIds.filter((suggestionId) =>
    pendingVisibleRatingSuggestions.some((suggestion) => suggestion.suggestionId === suggestionId),
  );
  const permissionAudit = permissionAuditQuery.data;
  const governanceTasks = governanceTasksQuery.data?.tasks ?? [];
  const ingestionAdapters = ingestionAdaptersQuery.data?.adapters ?? [];
  const graphPayload = memoryKnowledgeGraphQuery.data;
  const graphSearch = graphSearchText.trim().toLowerCase();
  const graphNodesMatchingSearch = useMemo(() => {
    const nodes = graphPayload?.nodes ?? [];
    if (!graphSearch) {
      return nodes;
    }
    return nodes.filter((node) =>
      [
        node.label,
        node.type,
        node.status,
        node.summary,
        node.responsibilityQuestion,
        ...(node.contentItems ?? []).map((item) => `${item.title} ${item.summary} ${item.knowledgeBaseName ?? ""}`),
      ].some((value) => String(value || "").toLowerCase().includes(graphSearch)),
    );
  }, [graphPayload?.nodes, graphSearch]);
  const filteredGraphNodes = useMemo(
    () => graphNodesMatchingSearch.filter((node) => (activeGraphNodeType ? node.type === activeGraphNodeType : true)),
    [activeGraphNodeType, graphNodesMatchingSearch],
  );
  const graphVisibleNodeIds = useMemo(() => new Set(filteredGraphNodes.map((node) => node.id)), [filteredGraphNodes]);
  const filteredGraphEdges = useMemo(
    () => (graphPayload?.edges ?? []).filter((edge) => graphVisibleNodeIds.has(edge.source) && graphVisibleNodeIds.has(edge.target)),
    [graphPayload?.edges, graphVisibleNodeIds],
  );
  const selectedGraphNode = selectedGraphNodeId ? filteredGraphNodes.find((node) => node.id === selectedGraphNodeId) ?? null : null;
  const selectedGraphDetailItems = memoryKnowledgeGraphNodeDetailQuery.data?.contentItems ?? selectedGraphNode?.contentItems ?? [];
  const graphNodeById = useMemo(() => new Map((graphPayload?.nodes ?? []).map((node) => [node.id, node])), [graphPayload?.nodes]);
  const selectedGraphRelations = useMemo(() => {
    if (!selectedGraphNode) {
      return { incoming: [] as GraphRelation[], outgoing: [] as GraphRelation[] };
    }
    const graphEdges = graphPayload?.edges ?? [];
    const incoming = graphEdges
      .filter((edge) => edge.target === selectedGraphNode.id)
      .flatMap((edge) => {
        const neighbor = graphNodeById.get(edge.source);
        return neighbor ? [{ edge, neighbor }] : [];
      })
      .slice(0, 8);
    const outgoing = graphEdges
      .filter((edge) => edge.source === selectedGraphNode.id)
      .flatMap((edge) => {
        const neighbor = graphNodeById.get(edge.target);
        return neighbor ? [{ edge, neighbor }] : [];
      })
      .slice(0, 8);
    return { incoming, outgoing };
  }, [graphNodeById, graphPayload?.edges, selectedGraphNode]);
  const selectedGraphChildren = useMemo(() => {
    if (!selectedGraphNode) {
      return [] as MemoryKnowledgeGraphNode[];
    }
    return (selectedGraphNode.childNodeIds ?? []).flatMap((nodeId) => {
      const child = graphNodeById.get(nodeId);
      return child ? [child] : [];
    });
  }, [graphNodeById, selectedGraphNode]);
  const selectGraphNode = (nodeId: string) => {
    setGraphSearchText("");
    setActiveGraphNodeType("");
    setSelectedGraphNodeId(nodeId);
  };
  const graphTypeEntries = useMemo(
    () => Object.entries(graphPayload?.summary.nodeTypeCounts ?? {}).sort((left, right) => right[1] - left[1]),
    [graphPayload?.summary.nodeTypeCounts],
  );
  useEffect(() => {
    if (activeGraphNodeType && !graphTypeEntries.some(([type]) => type === activeGraphNodeType)) {
      setActiveGraphNodeType("");
    }
  }, [activeGraphNodeType, graphTypeEntries]);
  useEffect(() => {
    if (selectedGraphNodeId && !filteredGraphNodes.some((node) => node.id === selectedGraphNodeId)) {
      setSelectedGraphNodeId("");
    }
  }, [filteredGraphNodes, selectedGraphNodeId]);
  const allPairs = useMemo(() => flattenSections(sections), [sections]);
  const runtimePairs = useMemo(
    () =>
      allPairs
        .filter(({ item }) => item.inPrompt || item.agentVisible)
        .sort((left, right) => memoryPairPriority(left) - memoryPairPriority(right))
        .slice(0, 8),
    [allPairs],
  );
  const priorityReviewPairs = useMemo(
    () =>
      allPairs
        .filter(({ item }) => reviewReasonLabels(copy, item).length > 0)
        .sort((left, right) => memoryPairPriority(left) - memoryPairPriority(right))
        .slice(0, 10),
    [allPairs, copy],
  );
  const reviewPairs = useMemo(
    () =>
      allPairs
        .filter(
          ({ item }) =>
            item.managedState?.disabled
            || item.managedState?.overridden
            || item.managedState?.userManaged
            || !item.exists
            || item.contentTruncated,
        )
        .sort((left, right) => memoryPairPriority(left) - memoryPairPriority(right))
        .slice(0, 8),
    [allPairs],
  );
  const manageablePairs = useMemo(
    () => allPairs.filter(({ item }) => itemIsManageable(item)),
    [allPairs],
  );
  const managedStateCount = manageablePairs.filter(
    ({ item }) => item.managedState?.userManaged || item.managedState?.disabled || item.managedState?.overridden,
  ).length;
  const disabledOrOverriddenCount = allPairs.filter(
    ({ item }) => item.managedState?.disabled || item.managedState?.overridden,
  ).length;
  const matrixCards = useMemo(
    () => [
      {
        id: "conversation",
        channel: "conversation" as const,
        title: copy.conversationMemory,
        hint: copy.conversationMemoryHint,
        ...countChannelItems(allPairs, "conversation"),
      },
      {
        id: "research",
        channel: "research" as const,
        title: copy.researchMemory,
        hint: copy.researchMemoryHint,
        ...countChannelItems(allPairs, "research"),
      },
      {
        id: "self",
        channel: "self_evolution" as const,
        title: copy.selfEvolutionMemory,
        hint: copy.selfEvolutionMemoryHint,
        ...countChannelItems(allPairs, "self_evolution"),
      },
      {
        id: "supervised",
        channel: "supervised_evolution" as const,
        title: copy.supervisedEvolutionMemory,
        hint: copy.supervisedEvolutionMemoryHint,
        ...countChannelItems(allPairs, "supervised_evolution"),
      },
      {
        id: "explicit",
        channel: "explicit_read" as const,
        title: copy.explicitReadMemory,
        hint: copy.explicitReadMemoryHint,
        ...countChannelItems(allPairs, "explicit_read"),
      },
    ],
    [allPairs, copy],
  );
  const visibleSectionsBySource = useMemo(
    () => filterSections(sections, "", searchText, activeFilter, activeChannel),
    [activeChannel, activeFilter, searchText, sections],
  );
  const sourceSectionMetrics = useMemo(
    () =>
      new Map(
        visibleSectionsBySource.map((section) => [
          section.id,
          {
            itemCount: section.items.length,
            promptCount: section.items.filter((item) => item.inPrompt).length,
          },
        ]),
      ),
    [visibleSectionsBySource],
  );
  const filterOptions = useMemo(
    () => [
      { id: "all" as const, label: copy.filterAll, count: filterCount(allPairs, "all") },
      { id: "prompt" as const, label: copy.filterPrompt, count: filterCount(allPairs, "prompt") },
      { id: "visible" as const, label: copy.filterVisible, count: filterCount(allPairs, "visible") },
      { id: "manual" as const, label: copy.filterManual, count: filterCount(allPairs, "manual") },
      { id: "missing" as const, label: copy.filterMissing, count: filterCount(allPairs, "missing") },
    ],
    [allPairs, copy],
  );
  const manageFilterOptions = useMemo(
    () => [
      { id: "all" as const, label: copy.manageFilterAll, count: manageFilterCount(manageablePairs, "all") },
      { id: "prompt" as const, label: copy.manageFilterPrompt, count: manageFilterCount(manageablePairs, "prompt") },
      { id: "editable" as const, label: copy.manageFilterEditable, count: manageFilterCount(manageablePairs, "editable") },
      { id: "changed" as const, label: copy.manageFilterChanged, count: manageFilterCount(manageablePairs, "changed") },
      { id: "missing" as const, label: copy.manageFilterMissing, count: manageFilterCount(manageablePairs, "missing") },
    ],
    [copy, manageablePairs],
  );
  const manageableSectionMetrics = useMemo(
    () =>
      new Map(
        sections.map((section) => {
          const items = section.items.filter((item) => itemIsManageable(item));
          return [section.id, items.length] as const;
        }),
      ),
    [sections],
  );
  const visibleSections = useMemo(
    () => filterSections(sections, activeSectionId, searchText, activeFilter, activeChannel),
    [activeChannel, activeFilter, activeSectionId, searchText, sections],
  );
  const manageSections = useMemo(
    () =>
      filterSections(sections, activeSectionId, searchText, activeFilter, activeChannel)
        .map((section) => ({
          ...section,
          items: section.items.filter((item) => itemIsManageable(item) && itemMatchesManageFilter(item, activeManageFilter)),
        }))
        .filter((section) => section.items.length > 0),
    [activeChannel, activeFilter, activeManageFilter, activeSectionId, searchText, sections],
  );
  const activeDisplaySections = forcedView === "manage" ? manageSections : visibleSections;
  const flatVisibleItems = useMemo(
    () =>
      activeDisplaySections.flatMap((section) =>
        section.items.map((item) => ({
          section,
          item,
        })),
      ),
    [activeDisplaySections],
  );
  const activePair =
    activeItemId
      ? flatVisibleItems.find(({ item }) => item.id === activeItemId) ?? null
      : null;
  const activePairKey = activePair ? pairSelectionKey(activePair.section.id, activePair.item.id) : "";
  const activeItem = activePair?.item ?? null;
  const activeSection = activePair?.section ?? null;
  const activeItemDetailQuery = useQuery({
    queryKey: queryKeys.memoryItemDetail(activeSection?.id ?? "", activeItem?.id ?? ""),
    queryFn: () =>
      fetchJson<MemoryItemDetailPayload>(
        `/api/memory/items/${encodeURIComponent(activeSection?.id ?? "")}/${encodeURIComponent(activeItem?.id ?? "")}`,
      ),
    enabled: Boolean(activeSection?.id && activeItem?.id && activeItem.contentDeferred),
    refetchInterval: false,
  });
  const resolvedActiveItem = activeItemDetailQuery.data?.item ?? activeItem;
  const activeImpact = resolvedActiveItem ? impactCopy(copy, resolvedActiveItem) : null;
  const selectedMemoryKeySet = useMemo(() => new Set(selectedMemoryKeys), [selectedMemoryKeys]);
  const selectedMemoryPairs = useMemo(
    () => manageablePairs.filter(({ section, item }) => selectedMemoryKeySet.has(pairSelectionKey(section.id, item.id))),
    [manageablePairs, selectedMemoryKeySet],
  );
  const visibleManagePairs = forcedView === "manage" ? flatVisibleItems : [];
  const visibleSelectableKeys = useMemo(
    () => visibleManagePairs.map(({ section, item }) => pairSelectionKey(section.id, item.id)),
    [visibleManagePairs],
  );
  const allVisibleSelected =
    visibleSelectableKeys.length > 0 && visibleSelectableKeys.every((key) => selectedMemoryKeySet.has(key));
  const selectedDisablePairs = selectedMemoryPairs.filter(({ item }) => item.managedState?.deletable);
  const selectedRestorePairs = selectedMemoryPairs.filter(({ item }) => item.managedState?.restorable);
  const hasOverviewSections = sections.length > 0;
  const showBlockingOverviewError = overviewQuery.isError && !hasOverviewSections;
  const showRefreshNotice = overviewQuery.isError && hasOverviewSections;
  const selectedSectionVisibleCount = activeSectionId
    ? sourceSectionMetrics.get(activeSectionId)?.itemCount ?? 0
    : flatVisibleItems.length;
  const selectedSectionPromptCount = activeSectionId
    ? sourceSectionMetrics.get(activeSectionId)?.promptCount ?? 0
    : flatVisibleItems.filter(({ item }) => item.inPrompt).length;
  const canCopyRawContent = Boolean(resolvedActiveItem?.content);

  useEffect(() => {
    const sectionParam = searchParams.get("section") ?? "";
    const itemParam = searchParams.get("item") ?? "";
    const filterParam = normalizeFilterMode(searchParams.get("filter"));
    const manageFilterParam = normalizeManageFilterMode(searchParams.get("manage"));
    const channelParam = normalizeChannelFilter(searchParams.get("channel"));
    const queryParam = searchParams.get("q") ?? "";
    if (sectionParam !== activeSectionId) {
      setActiveSectionId(sectionParam);
    }
    if (itemParam !== activeItemId) {
      setActiveItemId(itemParam);
    }
    if (filterParam !== activeFilter) {
      setActiveFilter(filterParam);
    }
    if (manageFilterParam !== activeManageFilter) {
      setActiveManageFilter(manageFilterParam);
    }
    if (channelParam !== activeChannel) {
      setActiveChannel(channelParam);
    }
    if (queryParam !== searchText) {
      setSearchText(queryParam);
    }
  }, [searchParamText]);

  useEffect(() => {
    const next = buildMemorySearchParams(
      activeSectionId,
      activeItemId,
      activeFilter,
      activeManageFilter,
      activeChannel,
      searchText,
      requestedKnowledgeActorAgentId,
    );
    if (next.toString() !== searchParamText) {
      setSearchParams(next, { replace: true });
    }
  }, [
    activeChannel,
    activeFilter,
    activeItemId,
    activeManageFilter,
    activeSectionId,
    requestedKnowledgeActorAgentId,
    searchParamText,
    searchText,
    setSearchParams,
  ]);

  useEffect(() => {
    if (copyFeedback.tone === "idle") {
      return;
    }
    const timeout = window.setTimeout(() => {
      setCopyFeedback({ tone: "idle", text: "" });
    }, 1800);
    return () => window.clearTimeout(timeout);
  }, [copyFeedback]);

  useEffect(() => {
    if (mutationFeedback.tone === "idle") {
      return;
    }
    const timeout = window.setTimeout(() => {
      setMutationFeedback({ tone: "idle", text: "" });
    }, 2200);
    return () => window.clearTimeout(timeout);
  }, [mutationFeedback]);

  useEffect(() => {
    if (knowledgeFeedback.tone === "idle") {
      return;
    }
    const timeout = window.setTimeout(() => {
      setKnowledgeFeedback({ tone: "idle", text: "" });
    }, 2400);
    return () => window.clearTimeout(timeout);
  }, [knowledgeFeedback]);

  useEffect(() => {
    if (!sections.length) {
      return;
    }
    if (activeSectionId && !sections.some((section) => section.id === activeSectionId)) {
      setActiveSectionId("");
    }
  }, [activeSectionId, sections]);

  useEffect(() => {
    if (!activeItemId || flatVisibleItems.some(({ item }) => item.id === activeItemId)) {
      return;
    }
    setActiveItemId("");
  }, [activeItemId, flatVisibleItems]);

  useEffect(() => {
    if (!selectedMemoryKeys.length) {
      return;
    }
    const validKeys = new Set(manageablePairs.map(({ section, item }) => pairSelectionKey(section.id, item.id)));
    const nextKeys = selectedMemoryKeys.filter((key) => validKeys.has(key));
    if (nextKeys.length !== selectedMemoryKeys.length) {
      setSelectedMemoryKeys(nextKeys);
    }
  }, [manageablePairs, selectedMemoryKeys]);

  useEffect(() => {
    if (!knowledgeBases.length) {
      if (activeKnowledgeBaseId) {
        setActiveKnowledgeBaseId("");
      }
      return;
    }
    if (!activeKnowledgeBaseId || !knowledgeBases.some((base) => knowledgeBaseRequestId(base) === activeKnowledgeBaseId)) {
      setActiveKnowledgeBaseId(knowledgeBaseRequestId(knowledgeBases[0]));
    }
  }, [activeKnowledgeBaseId, knowledgeBases]);

  useEffect(() => {
    const ownerId = knowledgeBaseOwnerId(activeKnowledgeBase);
    if (!ownerId) {
      return;
    }
    setSourceOwnerType(normalizeSourceOwnerType(activeKnowledgeBase?.ownerType));
    setSourceOwnerId(ownerId);
  }, [activeKnowledgeBaseForItems]);

  useEffect(() => {
    if (!selectedRatingSuggestionIds.length) {
      return;
    }
    const visiblePendingIds = new Set(pendingVisibleRatingSuggestions.map((suggestion) => suggestion.suggestionId));
    const nextIds = selectedRatingSuggestionIds.filter((suggestionId) => visiblePendingIds.has(suggestionId));
    if (nextIds.length !== selectedRatingSuggestionIds.length) {
      setSelectedRatingSuggestionIds(nextIds);
    }
  }, [pendingVisibleRatingSuggestions, selectedRatingSuggestionIds]);

  const refresh = () => {
    invalidateMemoryQueries(queryClient);
    invalidateKnowledgeDashboard(queryClient, activeKnowledgeActorAgentId || fallbackKnowledgeActorAgentId);
    invalidateKnowledgeDashboard(queryClient);
    void queryClient.invalidateQueries({ queryKey: queryKeys.agentProjectMemoryUpdates(memoryProposalStatusFilter, "", 100) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.agentProjectMemoryUpdates("", "", 100) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeGovernanceTasks(activeKnowledgeActorAgentId, "open") });
    void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeGovernanceTasks("", "open") });
    void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeIngestionAdapters() });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.knowledgeSourceInbox(activeSourceOwnerType, activeSourceOwnerId, activeKnowledgeActorAgentId, activeSourceInboxStatus),
    });
    void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeCentralSources(activeKnowledgeActorAgentId, activeSourceOwnerType, activeSourceOwnerId) });
    if (activeKnowledgeBaseForItems) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeItems(activeKnowledgeBaseForItems, activeKnowledgeActorAgentId) });
    }
    if (selectedGraphNodeId) {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.memoryKnowledgeGraphNodeDetail(selectedGraphNodeId, fallbackKnowledgeActorAgentId),
      });
    }
  };

  const selectedSection = sections.find((section) => section.id === activeSectionId) ?? null;
  const warningCount = overview?.summary.warnings.length ?? 0;
  const handleChannelCardClick = (channel: MemoryChannel) => {
    setActiveSectionId("");
    setActiveItemId("");
    setActiveChannel((current) => (current === channel ? "" : channel));
  };
  const currentUrl = useMemo(
    () => buildMemoryLink(activeSectionId, activeItemId, activeFilter, activeManageFilter, activeChannel, searchText, requestedKnowledgeActorAgentId),
    [activeChannel, activeFilter, activeItemId, activeManageFilter, activeSectionId, requestedKnowledgeActorAgentId, searchText],
  );
  const handleCopySourceSummary = async () => {
    if (!activeSection || !resolvedActiveItem) {
      return;
    }
    try {
      await copyText(buildInspectionText(copy, activeSection, resolvedActiveItem, currentUrl));
      setCopyFeedback({ tone: "success", text: `${copy.copySourceSummary} · ${copy.copyDone}` });
    } catch {
      setCopyFeedback({ tone: "error", text: `${copy.copySourceSummary} · ${copy.copyFailed}` });
    }
  };
  const handleCopySourcePath = async () => {
    if (!activeSection || !resolvedActiveItem) {
      return;
    }
    const sourcePath = resolvedActiveItem.path || resolvedActiveItem.source || activeSection.sourcePath || "";
    if (!sourcePath) {
      return;
    }
    try {
      await copyText(sourcePath);
      setCopyFeedback({ tone: "success", text: `${copy.copySourcePath} · ${copy.copyDone}` });
    } catch {
      setCopyFeedback({ tone: "error", text: `${copy.copySourcePath} · ${copy.copyFailed}` });
    }
  };
  const handleCopyRawContent = async () => {
    if (!resolvedActiveItem?.content) {
      return;
    }
    try {
      await copyText(resolvedActiveItem.content);
      setCopyFeedback({ tone: "success", text: `${copy.copyRawContentAction} · ${copy.copyDone}` });
    } catch {
      setCopyFeedback({ tone: "error", text: `${copy.copyRawContentAction} · ${copy.copyFailed}` });
    }
  };
  const handleCopyCurrentLink = async () => {
    if (!currentUrl) {
      return;
    }
    try {
      await copyText(currentUrl);
      setCopyFeedback({ tone: "success", text: `${copy.copyCurrentLink} · ${copy.copyDone}` });
    } catch {
      setCopyFeedback({ tone: "error", text: `${copy.copyCurrentLink} · ${copy.copyFailed}` });
    }
  };
  const handleProjectMemoryProposalResolve = (proposal: AgentProjectMemoryUpdateProposal, status: MemoryProposalResolveStatus) => {
    const resolutionNote =
      memoryProposalResolutionNotes[proposal.proposalId]?.trim() || projectMemoryProposalResolutionFallback(copy, status);
    projectMemoryUpdateResolveMutation.mutate({
      proposal,
      status,
      resolutionNote,
    });
  };
  const startCreate = () => {
    setEditDraft(newCreateDraft());
    setActiveSectionId("user-managed-memory");
    setActiveItemId("");
  };
  const startEdit = () => {
    if (!activeSection || !resolvedActiveItem) {
      return;
    }
    setEditDraft(draftFromItem(activeSection, resolvedActiveItem));
  };
  const saveDraft = () => {
    if (!editDraft || !editDraft.title.trim()) {
      setMutationFeedback({ tone: "error", text: `${copy.mutationFailed}: ${copy.titleField}` });
      return;
    }
    memoryMutation.mutate(editDraft);
  };
  const cancelDraft = () => {
    setEditDraft(null);
  };
  const disableOrDeleteActiveItem = () => {
    if (!activeSection || !resolvedActiveItem || !resolvedActiveItem.managedState?.deletable) {
      return;
    }
    deleteMemoryMutation.mutate({ sectionId: activeSection.id, itemId: resolvedActiveItem.id });
  };
  const restoreActiveItem = () => {
    if (!activeSection || !resolvedActiveItem || !resolvedActiveItem.managedState?.restorable) {
      return;
    }
    restoreMemoryMutation.mutate({ sectionId: activeSection.id, itemId: resolvedActiveItem.id });
  };
  const mutationBusy = memoryMutation.isPending || deleteMemoryMutation.isPending || restoreMemoryMutation.isPending || bulkActionPending !== null;
  const knowledgeBusy =
    sourceInboxCollectMutation.isPending
    || sourceInboxReviewMutation.isPending
    || centralSourceAttachMutation.isPending
    || proposalMutation.isPending
    || reviewMutation.isPending
    || ratingMutation.isPending
    || ratingSuggestionReviewMutation.isPending
    || ratingSuggestionBulkReviewMutation.isPending;
  const toggleMemorySelection = (sectionId: string, itemId: string) => {
    const key = pairSelectionKey(sectionId, itemId);
    setSelectedMemoryKeys((current) => (current.includes(key) ? current.filter((value) => value !== key) : [...current, key]));
  };
  const toggleVisibleMemorySelection = () => {
    setSelectedMemoryKeys((current) => {
      if (allVisibleSelected) {
        const visibleSet = new Set(visibleSelectableKeys);
        return current.filter((key) => !visibleSet.has(key));
      }
      return Array.from(new Set([...current, ...visibleSelectableKeys]));
    });
  };
  const runBulkMemoryAction = async (action: BulkMemoryAction) => {
    if (bulkActionPending !== null) {
      return;
    }
    const pairs = action === "restore" ? selectedRestorePairs : selectedDisablePairs;
    if (!pairs.length) {
      setMutationFeedback({ tone: "error", text: `${copy.mutationFailed}: ${copy.bulkActionSkipped}` });
      return;
    }
    const skipped = selectedMemoryPairs.length - pairs.length;
    setBulkActionPending(action);
    try {
      await Promise.all(
        pairs.map(({ section, item }) =>
          fetchJson<MemoryMutationResponse>(
            memoryMutationEndpoint(section.id, item.id, action === "restore" ? "/restore" : ""),
            { method: action === "restore" ? "POST" : "DELETE" },
          ),
        ),
      );
      setSelectedMemoryKeys((current) => {
        const completed = new Set(pairs.map(({ section, item }) => pairSelectionKey(section.id, item.id)));
        return current.filter((key) => !completed.has(key));
      });
      setMutationFeedback({
        tone: "success",
        text: skipped > 0 ? `${copy.mutationDone} · ${copy.bulkActionSkipped}: ${skipped}` : copy.mutationDone,
      });
      invalidateMemoryQueries(queryClient);
    } catch (error) {
      setMutationFeedback({
        tone: "error",
        text: `${copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}`,
      });
    } finally {
      setBulkActionPending(null);
    }
  };
  const selectMemoryPair = (sectionId: string, itemId: string) => {
    setActiveSectionId(sectionId);
    setActiveItemId(itemId);
  };
  const applyActiveKnowledgeOwner = () => {
    const ownerId = knowledgeBaseOwnerId(activeKnowledgeBase);
    if (!ownerId) {
      setKnowledgeFeedback({ tone: "error", text: `${copy.mutationFailed}: ${copy.ownerId}` });
      return;
    }
    setSourceOwnerType(normalizeSourceOwnerType(activeKnowledgeBase?.ownerType));
    setSourceOwnerId(ownerId);
  };
  const submitOwnerSource = () => {
    if (!activeSourceOwnerId || !activeKnowledgeActorAgentId || !ownerSourceDraft.sourceType.trim()) {
      setKnowledgeFeedback({ tone: "error", text: `${copy.mutationFailed}: ${copy.ownerSourceInbox}` });
      return;
    }
    sourceInboxCollectMutation.mutate(ownerSourceDraft);
  };
  const reviewOwnerSource = (source: KnowledgeOwnerSource, decision: "accepted" | "rejected" | "duplicate" | "needs_more_context") => {
    if (!activeSourceOwnerId || !activeKnowledgeActorAgentId) {
      setKnowledgeFeedback({ tone: "error", text: `${copy.mutationFailed}: agentId` });
      return;
    }
    if (decision === "duplicate" && !duplicateCentralSourceId.trim()) {
      setKnowledgeFeedback({ tone: "error", text: `${copy.mutationFailed}: ${copy.centralSourceId}` });
      return;
    }
    sourceInboxReviewMutation.mutate({ source, decision });
  };
  const attachCentralSource = (centralSourceId: string) => {
    if (!activeKnowledgeBase || !activeKnowledgeBaseForItems || !activeKnowledgeActorAgentId || !centralSourceId.trim()) {
      setKnowledgeFeedback({ tone: "error", text: `${copy.mutationFailed}: ${copy.centralSourceId}` });
      return;
    }
    centralSourceAttachMutation.mutate(centralSourceId);
  };
  const submitRefinementProposal = () => {
    if (!activeKnowledgeBase || !activeKnowledgeActorAgentId || !proposalDraft.title.trim() || !proposalDraft.content.trim()) {
      setKnowledgeFeedback({ tone: "error", text: `${copy.mutationFailed}: ${copy.proposalTitle}` });
      return;
    }
    proposalMutation.mutate({
      knowledgeBaseId: knowledgeBaseRequestId(activeKnowledgeBase),
      draft: { ...proposalDraft, proposedByAgentId: proposalDraft.proposedByAgentId.trim() || activeKnowledgeActorAgentId },
    });
  };
  const reviewProposal = (proposalId: string, status: "approved" | "rejected") => {
    if (!activeKnowledgeBase || !activeKnowledgeActorAgentId) {
      setKnowledgeFeedback({ tone: "error", text: `${copy.mutationFailed}: agentId` });
      return;
    }
    reviewMutation.mutate({ knowledgeBaseId: knowledgeBaseRequestId(activeKnowledgeBase), proposalId, status });
  };
  const updateKnowledgeRating = (item: KnowledgeItem) => {
    if (!activeKnowledgeBase || !activeKnowledgeActorAgentId) {
      setKnowledgeFeedback({ tone: "error", text: `${copy.mutationFailed}: agentId` });
      return;
    }
    ratingMutation.mutate({
      knowledgeBaseId: knowledgeBaseRequestId(activeKnowledgeBase),
      item,
      draft: { ...ratingDraft, actorAgentId: ratingDraft.actorAgentId.trim() || activeKnowledgeActorAgentId },
    });
  };
  const reviewRatingSuggestion = (suggestionId: string, status: "applied" | "rejected") => {
    if (!activeKnowledgeBase || !activeKnowledgeActorAgentId) {
      setKnowledgeFeedback({ tone: "error", text: `${copy.mutationFailed}: agentId` });
      return;
    }
    ratingSuggestionReviewMutation.mutate({ knowledgeBaseId: knowledgeBaseRequestId(activeKnowledgeBase), suggestionId, status });
  };
  const toggleRatingSuggestionSelection = (suggestionId: string) => {
    setSelectedRatingSuggestionIds((current) =>
      current.includes(suggestionId) ? current.filter((value) => value !== suggestionId) : [...current, suggestionId],
    );
  };
  const toggleVisibleRatingSuggestions = () => {
    const visibleIds = pendingVisibleRatingSuggestions.map((suggestion) => suggestion.suggestionId);
    if (!visibleIds.length) {
      return;
    }
    setSelectedRatingSuggestionIds((current) => {
      const allVisibleSelected = visibleIds.every((suggestionId) => current.includes(suggestionId));
      if (allVisibleSelected) {
        return current.filter((suggestionId) => !visibleIds.includes(suggestionId));
      }
      return Array.from(new Set([...current, ...visibleIds]));
    });
  };
  const reviewSelectedRatingSuggestions = (status: "applied" | "rejected") => {
    if (!activeKnowledgeBase || !activeKnowledgeActorAgentId || !selectedVisibleRatingSuggestionIds.length) {
      setKnowledgeFeedback({ tone: "error", text: `${copy.mutationFailed}: agentId` });
      return;
    }
    ratingSuggestionBulkReviewMutation.mutate({
      knowledgeBaseId: knowledgeBaseRequestId(activeKnowledgeBase),
      suggestionIds: selectedVisibleRatingSuggestionIds,
      status,
    });
  };
  const toggleCleanupTarget = (targetKey: string) => {
    setCleanupExecution(null);
    setCleanupPreview(null);
    setSelectedCleanupTargetKeys((current) =>
      current.includes(targetKey) ? current.filter((value) => value !== targetKey) : [...current, targetKey],
    );
  };
  const previewCleanup = () => {
    if (!selectedCleanupTargets.length) {
      setCleanupFeedback({ tone: "error", text: copy.cleanupSelectTargets });
      return;
    }
    cleanupPreviewMutation.mutate(selectedCleanupTargets);
  };
  const executeCleanup = () => {
    if (!selectedCleanupTargets.length) {
      setCleanupFeedback({ tone: "error", text: copy.cleanupSelectTargets });
      return;
    }
    cleanupExecuteMutation.mutate({
      targets: selectedCleanupTargets,
      confirmationPhrase: cleanupConfirmationText,
    });
  };

  const renderSubnav = () => (
    <nav className={styles.subnav} aria-label={copy.title}>
      {MEMORY_VIEWS.map((view) => (
        <NavLink
          key={view.key}
          to={view.href}
          end={view.key === "overview"}
          className={({ isActive }) =>
            isActive || forcedView === view.key ? `${styles.subnavLink} ${styles.subnavLinkActive}` : styles.subnavLink
          }
        >
          {memoryViewLabel(copy, view.key)}
        </NavLink>
      ))}
    </nav>
  );

  const renderMemoryList = (pairs: MemoryPair[], emptyText: string, compact = false, selectable = false) => {
    if (overviewQuery.isPending && !hasOverviewSections) {
      return <div className={styles.emptyState}>{copy.loading}</div>;
    }
    if (showBlockingOverviewError) {
      return (
        <div className={styles.emptyState}>
          {copy.loadFailed}: {overviewQuery.error instanceof Error ? overviewQuery.error.message : String(overviewQuery.error)}
        </div>
      );
    }
    if (!pairs.length) {
      return <div className={styles.emptyState}>{emptyText}</div>;
    }
    return (
      <div className={compact ? styles.compactMemoryList : styles.itemList}>
        {pairs.map(({ section, item }) => {
          const itemKey = pairSelectionKey(section.id, item.id);
          const active = itemKey === activePairKey;
          const compactItemBody = (
            <>
              <span className={styles.compactItemPrimary}>
                <strong>{item.title}</strong>
                <span>{formatTimestamp(item.updatedAt, lang)}</span>
              </span>
              <span className={styles.compactItemMeta}>
                <span>{sourceOriginLabel(section, item)}</span>
                <span title={item.path || item.source}>{item.path || item.source}</span>
              </span>
              <span className={styles.compactItemSummary}>{item.summary}</span>
            </>
          );
          const denseItemBody = (
            <>
              <span className={styles.manageItemPrimary}>
                <strong>{item.title}</strong>
                <span>{formatTimestamp(item.updatedAt, lang)}</span>
              </span>
              <span className={styles.manageItemMeta}>
                <span>{sourceOriginLabel(section, item)}</span>
                <span title={item.path || item.source}>{item.path || item.source}</span>
              </span>
              <span className={styles.manageItemFooter}>
                <span className={styles.manageItemSummary}>{item.summary}</span>
                <span className={styles.manageItemBadges}>
                  <span className={statusClassName(item.agentVisible, item.inPrompt)}>
                    {item.inPrompt ? copy.inPrompt : item.agentVisible ? copy.canUse : copy.manualOnly}
                  </span>
                  {item.managedState?.userManaged ? <span className={styles.statusPill}>{copy.userManaged}</span> : null}
                  {item.managedState?.overridden ? <span className={styles.statusPill}>{copy.overridden}</span> : null}
                  {item.managedState?.disabled ? <span className={styles.statusPill}>{copy.disabledByUser}</span> : null}
                  {!item.exists ? <span className={styles.statusPill}>{copy.missing}</span> : null}
                  {item.contentTruncated ? <span className={styles.statusPill}>{copy.truncated}</span> : null}
                </span>
              </span>
            </>
          );
          const itemBody = (
            <>
              <span className={styles.itemHeader}>
                <strong>{item.title}</strong>
                <span>{formatTimestamp(item.updatedAt, lang)}</span>
              </span>
              <span className={styles.itemOrigin}>
                {copy.sourceOrigin}: {sourceOriginLabel(section, item)}
              </span>
              <span className={styles.itemPath}>{item.path || item.source}</span>
              <span className={styles.itemSummary}>{item.summary}</span>
              <span className={styles.itemBadges}>
                <span className={statusClassName(item.agentVisible, item.inPrompt)}>
                  {item.inPrompt ? copy.inPrompt : item.agentVisible ? copy.canUse : copy.manualOnly}
                </span>
                {item.managedState?.userManaged ? <span className={styles.statusPill}>{copy.userManaged}</span> : null}
                {item.managedState?.overridden ? <span className={styles.statusPill}>{copy.overridden}</span> : null}
                {item.managedState?.disabled ? <span className={styles.statusPill}>{copy.disabledByUser}</span> : null}
                {itemChannelPills(copy, item).map((pill) => (
                  <span key={`${item.id}:${pill.label}`} className={styles.channelPill} title={pill.hint}>
                    {pill.label}
                  </span>
                ))}
                {!item.exists ? <span className={styles.statusPill}>{copy.missing}</span> : null}
                {item.contentTruncated ? <span className={styles.statusPill}>{copy.truncated}</span> : null}
              </span>
            </>
          );

          if (selectable) {
            return (
              <article
                key={itemKey}
                className={
                  active
                    ? `${styles.itemButton} ${styles.itemButtonDense} ${styles.itemButtonActive}`
                    : `${styles.itemButton} ${styles.itemButtonDense}`
                }
              >
                <label className={`${styles.itemSelectionRow} ${styles.itemSelectionRowDense}`}>
                  <input
                    type="checkbox"
                    checked={selectedMemoryKeySet.has(itemKey)}
                    aria-label={`${copy.selectMemory}: ${item.title}`}
                    onChange={() => toggleMemorySelection(section.id, item.id)}
                  />
                </label>
                <button
                  type="button"
                  className={`${styles.itemContentButton} ${styles.itemContentButtonDense}`}
                  onClick={() => selectMemoryPair(section.id, item.id)}
                  aria-pressed={active}
                >
                  {denseItemBody}
                </button>
              </article>
            );
          }

          if (compact) {
            return (
              <button
                key={itemKey}
                type="button"
                className={
                  active
                    ? `${styles.itemButton} ${styles.itemButtonCompact} ${styles.itemButtonActive}`
                    : `${styles.itemButton} ${styles.itemButtonCompact}`
                }
                onClick={() => selectMemoryPair(section.id, item.id)}
                aria-pressed={active}
              >
                {compactItemBody}
              </button>
            );
          }

          return (
            <button
              key={itemKey}
              type="button"
              className={active ? `${styles.itemButton} ${styles.itemButtonActive}` : styles.itemButton}
              onClick={() => selectMemoryPair(section.id, item.id)}
              aria-pressed={active}
            >
              {itemBody}
            </button>
          );
        })}
      </div>
    );
  };

  const openReviewTarget = (pair: MemoryPair) => {
    setActiveSectionId(pair.section.id);
    setActiveItemId(pair.item.id);
    setActiveFilter("all");
    setActiveChannel("");
    setSearchText("");
  };

  const renderProjectMemoryProposalStatus = (status: string) => {
    const className =
      status === "pending"
        ? `${styles.statusPill} ${styles.statusPillVisible}`
        : status === "conflict"
          ? `${styles.statusPill} ${styles.statusPillPrompt}`
          : `${styles.statusPill} ${styles.statusPillMuted}`;
    return <span className={className}>{status || "-"}</span>;
  };

  const renderProjectMemoryQueue = () => {
    const isPendingOnly = memoryProposalStatusFilter === "pending";
    const emptyText = isPendingOnly ? copy.projectMemoryQueueEmptyPending : copy.projectMemoryQueueEmptyAll;
    const isResolving = projectMemoryUpdateResolveMutation.isPending;
    return (
      <section className={styles.projectMemoryQueuePanel}>
        <div className={styles.panelHeader}>
          <div>
            <p className={styles.panelEyebrow}>{copy.governance}</p>
            <h2>{copy.projectMemoryQueue}</h2>
          </div>
          <div className={styles.projectMemoryQueueControls} aria-label={copy.status}>
            <button
              type="button"
              className={isPendingOnly ? styles.filterButtonActive : styles.filterButton}
              aria-pressed={isPendingOnly}
              onClick={() => setMemoryProposalStatusFilter("pending")}
            >
              {copy.projectMemoryQueuePendingOnly}
            </button>
            <button
              type="button"
              className={!isPendingOnly ? styles.filterButtonActive : styles.filterButton}
              aria-pressed={!isPendingOnly}
              onClick={() => setMemoryProposalStatusFilter("")}
            >
              {copy.projectMemoryQueueAll}
            </button>
          </div>
        </div>
        <div className={styles.projectMemoryQueueStats} title={copy.projectMemoryQueueHint}>
          <span>
            <strong>{pendingProjectMemoryProposalCount}</strong>
            {copy.pendingProposals}
          </span>
          <span>
            <strong>{projectMemoryUpdateProposals.length}</strong>
            {isPendingOnly ? copy.projectMemoryQueuePendingOnly : copy.projectMemoryQueueAll}
          </span>
          <span>
            <strong>{projectMemoryProposalLaneCount}</strong>
            {copy.projectMemoryQueueLane}
          </span>
        </div>
        {mutationFeedback.tone !== "idle" ? (
          <p className={styles.copyNotice} data-tone={mutationFeedback.tone}>
            {mutationFeedback.tone === "success" ? <CheckCircle2 size={14} /> : <TriangleAlert size={14} />}
            <span>{mutationFeedback.text}</span>
          </p>
        ) : null}
        {projectMemoryUpdatesQuery.isError ? (
          <p className={styles.panelError}>
            <TriangleAlert size={15} />
            <span>{projectMemoryUpdatesQuery.error instanceof Error ? projectMemoryUpdatesQuery.error.message : String(projectMemoryUpdatesQuery.error)}</span>
          </p>
        ) : null}
        <div className={styles.projectMemoryProposalList}>
          {projectMemoryUpdateProposals.map((proposal) => {
            const isPendingProposal = proposal.status === "pending";
            const noteValue = memoryProposalResolutionNotes[proposal.proposalId] ?? "";
            const relatedFiles = (proposal.relatedFiles ?? []).filter(Boolean);
            return (
              <article key={proposal.proposalId} className={styles.projectMemoryProposalRow} data-status={proposal.status || "unknown"}>
                <div className={styles.projectMemoryProposalMain}>
                  <div className={styles.projectMemoryProposalTitleLine}>
                    <strong>{proposal.focus || proposal.update || proposal.proposalId}</strong>
                    {renderProjectMemoryProposalStatus(proposal.status)}
                  </div>
                  <p>{proposal.update || proposal.details || "-"}</p>
                  <small>{proposal.details || proposal.proposalId}</small>
                </div>
                <div className={styles.projectMemoryProposalMeta}>
                  <span>{copy.projectMemoryQueueAgent}: {projectMemoryProposalAgentLabel(proposal)}</span>
                  <span>{copy.projectMemoryQueueLane}: {proposal.laneId || "-"}</span>
                  <span>{copy.projectMemoryQueueCreated}: {formatTimestamp(proposal.createdAt, lang)}</span>
                </div>
                <div className={styles.projectMemoryProposalFiles} aria-label={copy.projectMemoryQueueFiles}>
                  {relatedFiles.length ? relatedFiles.slice(0, 3).map((file) => <code key={file}>{file}</code>) : <span>-</span>}
                  {relatedFiles.length > 3 ? <span>+{relatedFiles.length - 3}</span> : null}
                </div>
                <div className={styles.projectMemoryProposalNote}>
                  {isPendingProposal ? (
                    <input
                      value={noteValue}
                      placeholder={copy.projectMemoryQueueResolutionNote}
                      onChange={(event) =>
                        setMemoryProposalResolutionNotes((current) => ({
                          ...current,
                          [proposal.proposalId]: event.target.value,
                        }))
                      }
                    />
                  ) : (
                    <span>
                      {proposal.resolutionNote
                        || `${copy.projectMemoryQueueResolved}: ${projectMemoryProposalResolverLabel(proposal.resolvedBy, lang)}`}
                    </span>
                  )}
                </div>
                <div className={styles.projectMemoryProposalActions}>
                  {isPendingProposal ? (
                    <>
                      <button
                        type="button"
                        className={styles.detailActionButton}
                        title={copy.projectMemoryQueueApply}
                        disabled={isResolving}
                        onClick={() => handleProjectMemoryProposalResolve(proposal, "applied")}
                      >
                        <CheckCircle2 size={14} />
                        <span>{copy.projectMemoryQueueApply}</span>
                      </button>
                      <button
                        type="button"
                        className={styles.detailActionButton}
                        title={copy.projectMemoryQueueReject}
                        disabled={isResolving}
                        onClick={() => handleProjectMemoryProposalResolve(proposal, "rejected")}
                      >
                        <XCircle size={14} />
                        <span>{copy.projectMemoryQueueReject}</span>
                      </button>
                      <button
                        type="button"
                        className={styles.detailActionButton}
                        title={copy.projectMemoryQueueConflict}
                        disabled={isResolving}
                        onClick={() => handleProjectMemoryProposalResolve(proposal, "conflict")}
                      >
                        <TriangleAlert size={14} />
                        <span>{copy.projectMemoryQueueConflict}</span>
                      </button>
                      <button
                        type="button"
                        className={styles.detailActionButton}
                        title={copy.projectMemoryQueueSupersede}
                        disabled={isResolving}
                        onClick={() => handleProjectMemoryProposalResolve(proposal, "superseded")}
                      >
                        <Square size={14} />
                        <span>{copy.projectMemoryQueueSupersede}</span>
                      </button>
                    </>
                  ) : (
                    <span className={styles.projectMemoryProposalResolved}>
                      {copy.projectMemoryQueueResolved}: {formatTimestamp(proposal.resolvedAt, lang)}
                    </span>
                  )}
                </div>
              </article>
            );
          })}
          {projectMemoryUpdatesQuery.isPending && !projectMemoryUpdateProposals.length ? (
            <section className={styles.emptyState}>{copy.loading}</section>
          ) : null}
          {!projectMemoryUpdatesQuery.isPending && !projectMemoryUpdateProposals.length ? (
            <section className={styles.emptyState}>
              <CheckCircle2 size={20} />
              <span>{emptyText}</span>
            </section>
          ) : null}
        </div>
      </section>
    );
  };

  const renderReviewQueue = () => {
    if (overviewQuery.isPending && !hasOverviewSections) {
      return <div className={styles.emptyState}>{copy.loading}</div>;
    }
    if (showBlockingOverviewError) {
      return (
        <div className={styles.emptyState}>
          {copy.loadFailed}: {overviewQuery.error instanceof Error ? overviewQuery.error.message : String(overviewQuery.error)}
        </div>
      );
    }
    if (!priorityReviewPairs.length) {
      return <div className={styles.emptyState}>{copy.noIssues}</div>;
    }
    return (
      <div className={styles.reviewQueueList}>
        {priorityReviewPairs.map((pair, index) => {
          const { section, item } = pair;
          const reasons = reviewReasonLabels(copy, item);
          const target = memoryPairActionTarget(pair);
          return (
            <article key={`${section.id}:${item.id}`} className={styles.reviewQueueItem}>
              <div className={styles.reviewRank}>{index + 1}</div>
              <div className={styles.reviewQueueBody}>
                <div className={styles.reviewQueueTitleLine}>
                  <strong>{item.title}</strong>
                  <span>{sourceOriginLabel(section, item)}</span>
                </div>
              </div>
              <span className={styles.reviewQueueSummary}>{item.summary}</span>
              <div className={styles.reviewReasonList} aria-label={copy.reviewReason}>
                {reasons.map((reason) => (
                  <span key={`${item.id}:${reason}`} className={styles.reviewReasonPill}>
                    {reason}
                  </span>
                ))}
              </div>
              <span className={styles.reviewQueueTime}>{formatTimestamp(item.updatedAt, lang)}</span>
              <div className={styles.reviewQueueActions}>
                <NavLink
                  className={styles.detailActionButton}
                  to={`/memory/sources?section=${encodeURIComponent(section.id)}&item=${encodeURIComponent(item.id)}`}
                  onClick={() => openReviewTarget(pair)}
                  title={copy.auditMemory}
                  aria-label={`${copy.auditMemory}: ${item.title}`}
                >
                  <FileText size={14} />
                  <span>{copy.auditMemory}</span>
                </NavLink>
                {target === "manage" ? (
                  <NavLink
                    className={styles.detailActionButton}
                    to={`/memory/manage?section=${encodeURIComponent(section.id)}&item=${encodeURIComponent(item.id)}`}
                    onClick={() => openReviewTarget(pair)}
                    title={copy.manageMemoryAction}
                    aria-label={`${copy.manageMemoryAction}: ${item.title}`}
                  >
                    <Pencil size={14} />
                    <span>{copy.manageMemoryAction}</span>
                  </NavLink>
                ) : null}
              </div>
            </article>
          );
        })}
      </div>
    );
  };

  const renderMatrixPanel = (title = copy.whereMemoryWorks) => (
    <section className={styles.matrixPanel} aria-label={copy.perceptionMatrix}>
      <div className={styles.matrixHeader}>
        <div>
          <p className={styles.panelEyebrow}>{copy.perceptionMatrix}</p>
          <h2>{title}</h2>
        </div>
        <div className={styles.matrixHeaderMeta}>
          {activeChannel ? <span className={styles.activeChannelPill}>{channelFilterLabel(copy, activeChannel)}</span> : null}
          {overview ? <span className={styles.countPill}>{formatTimestamp(overview.generatedAt, lang)}</span> : null}
        </div>
      </div>
      <div className={styles.matrixGrid}>
        {matrixCards.map((card) => (
          <button
            key={card.id}
            type="button"
            className={
              activeChannel === card.channel
                ? `${styles.matrixCard} ${styles.matrixCardButton} ${styles.matrixCardActive}`
                : `${styles.matrixCard} ${styles.matrixCardButton}`
            }
            onClick={() => handleChannelCardClick(card.channel)}
            aria-pressed={activeChannel === card.channel}
          >
            <div>
              <strong>{card.title}</strong>
              <span>{card.hint}</span>
            </div>
            <dl>
              <div>
                <dt>{copy.matrixItems}</dt>
                <dd>{card.itemCount}</dd>
              </div>
              <div>
                <dt>{copy.matrixPrompt}</dt>
                <dd>{card.promptCount}</dd>
              </div>
            </dl>
          </button>
        ))}
      </div>
    </section>
  );

  const renderWarningStrip = () =>
    warningCount > 0 ? (
      <section className={styles.warningStrip} aria-label={copy.warnings}>
        <TriangleAlert size={16} />
        <strong>{copy.warnings}</strong>
        <span>{overview?.summary.warnings.join("；")}</span>
      </section>
    ) : null;

  const renderManagementEditor = () =>
    editDraft ? (
      <section className={styles.managementPanel} aria-label={copy.management} title={copy.managementHint}>
        <div className={styles.managementHeader}>
          <div>
            <p className={styles.panelEyebrow}>{copy.management}</p>
            <h2>{editDraft.mode === "create" ? copy.addMemory : copy.editMemory}</h2>
          </div>
          <button type="button" className={styles.iconButton} onClick={cancelDraft} disabled={mutationBusy}>
            <XCircle size={16} />
            <span>{copy.cancelEdit}</span>
          </button>
        </div>
        <label className={styles.fieldStack}>
          <span>{copy.titleField}</span>
          <input
            value={editDraft.title}
            placeholder={copy.titlePlaceholder}
            onChange={(event) => setEditDraft((current) => (current ? { ...current, title: event.target.value } : current))}
          />
        </label>
        <label className={styles.fieldStack}>
          <span>{copy.summaryField}</span>
          <input
            value={editDraft.summary}
            placeholder={copy.summaryPlaceholder}
            onChange={(event) => setEditDraft((current) => (current ? { ...current, summary: event.target.value } : current))}
          />
        </label>
        <label className={styles.fieldStack}>
          <span>{copy.contentField}</span>
          <textarea
            value={editDraft.content}
            placeholder={copy.contentPlaceholder}
            onChange={(event) => setEditDraft((current) => (current ? { ...current, content: event.target.value } : current))}
          />
        </label>
        <div className={styles.managementActions}>
          <button type="button" className={styles.primaryActionButton} onClick={saveDraft} disabled={mutationBusy}>
            <CheckCircle2 size={15} />
            <span>{copy.saveMemory}</span>
          </button>
          <button type="button" className={styles.detailActionButton} onClick={cancelDraft} disabled={mutationBusy}>
            <XCircle size={15} />
            <span>{copy.cancelEdit}</span>
          </button>
        </div>
        <section className={styles.editPreviewPanel} aria-label={copy.editPreview}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{copy.editPreview}</p>
              <h3>{editDraft.title.trim() || copy.titleField}</h3>
            </div>
          </div>
          {resolvedActiveItem && editDraft.mode === "edit" ? (
            <div className={styles.editPreviewGrid}>
              {[
                { label: copy.titleField, current: resolvedActiveItem.title, draft: editDraft.title },
                { label: copy.summaryField, current: resolvedActiveItem.summary, draft: editDraft.summary },
                { label: copy.contentField, current: resolvedActiveItem.content, draft: editDraft.content },
              ].map((field) => (
                <section key={field.label}>
                  <strong>{field.label}</strong>
                  <div>
                    <span>{copy.currentValue}</span>
                    <p>{field.current || "-"}</p>
                  </div>
                  <div>
                    <span>{copy.draftValue}</span>
                    <p>{field.draft || "-"}</p>
                  </div>
                </section>
              ))}
            </div>
          ) : (
            <p>{editDraft.content.trim() || editDraft.summary.trim() || editDraft.title.trim() ? editDraft.summary || editDraft.content : copy.noDraftChanges}</p>
          )}
        </section>
        {mutationFeedback.tone !== "idle" ? (
          <p className={styles.copyNotice} data-tone={mutationFeedback.tone}>
            {mutationFeedback.tone === "success" ? <CheckCircle2 size={14} /> : <TriangleAlert size={14} />}
            <span>{mutationFeedback.text}</span>
          </p>
        ) : null}
      </section>
    ) : null;

  const renderSelectedMemoryConfig = () =>
    resolvedActiveItem && activeSection && !editDraft ? (
      <section className={styles.managementPanel} aria-label={copy.management} title={resolvedActiveItem.managedState?.actionHint || copy.managementHint}>
        <div className={styles.managementHeader}>
          <div>
            <p className={styles.panelEyebrow}>{activeSection.title}</p>
            <h2>{resolvedActiveItem.managedState?.userManaged ? copy.userManaged : resolvedActiveItem.managedState?.overridden ? copy.overridden : copy.management}</h2>
          </div>
          <span className={styles.countPill}>
            {resolvedActiveItem.managedState?.disabled
              ? copy.disabledByUser
              : resolvedActiveItem.managedState?.userManaged
                ? copy.userManaged
                : resolvedActiveItem.managedState?.overridden
                  ? copy.overridden
                  : copy.canUse}
          </span>
        </div>
        <div className={styles.selectedConfigSummary}>
          <strong>{resolvedActiveItem.title}</strong>
          <p>{resolvedActiveItem.summary || resolvedActiveItem.content || copy.noContent}</p>
        </div>
        <div className={styles.managementActions}>
          <button
            type="button"
            className={styles.detailActionButton}
            onClick={startEdit}
            disabled={!resolvedActiveItem.managedState?.editable || mutationBusy}
          >
            <Pencil size={15} />
            <span>{copy.editMemory}</span>
          </button>
          {resolvedActiveItem.managedState?.restorable ? (
            <button type="button" className={styles.detailActionButton} onClick={restoreActiveItem} disabled={mutationBusy}>
              <Undo2 size={15} />
              <span>{copy.restoreMemory}</span>
            </button>
          ) : null}
          <button
            type="button"
            className={styles.detailActionButton}
            onClick={disableOrDeleteActiveItem}
            disabled={!resolvedActiveItem.managedState?.deletable || mutationBusy}
          >
            <Trash2 size={15} />
            <span>{resolvedActiveItem.managedState?.userManaged ? copy.deleteMemory : copy.disableMemory}</span>
          </button>
        </div>
        {mutationFeedback.tone !== "idle" ? (
          <p className={styles.copyNotice} data-tone={mutationFeedback.tone}>
            {mutationFeedback.tone === "success" ? <CheckCircle2 size={14} /> : <TriangleAlert size={14} />}
            <span>{mutationFeedback.text}</span>
          </p>
        ) : null}
      </section>
    ) : null;

  const renderDetailPanel = (showEditor = true) => (
    <aside className={showEditor ? styles.detailPanel : `${styles.detailPanel} ${styles.manageDetailPanel}`}>
      {showEditor ? renderManagementEditor() : null}

      {resolvedActiveItem && activeSection ? (
        <>
          <section className={styles.detailHeader}>
            <div>
              <p className={styles.panelEyebrow}>{activeSection.title}</p>
              <h2>{resolvedActiveItem.title}</h2>
              <p>{resolvedActiveItem.summary}</p>
            </div>
            <span className={statusClassName(resolvedActiveItem.agentVisible, resolvedActiveItem.inPrompt)}>
              {resolvedActiveItem.inPrompt ? copy.inPrompt : resolvedActiveItem.agentVisible ? copy.canUse : copy.manualOnly}
            </span>
          </section>

          {activeImpact ? (
            <section className={styles.impactPanel}>
              <div className={styles.visibilityHeader}>
                <Brain size={16} />
                <div>
                  <strong>{copy.impact}</strong>
                  <p>{activeImpact.title}</p>
                </div>
              </div>
              <p>{activeImpact.body}</p>
            </section>
          ) : null}

          <div className={styles.detailActions}>
            <button type="button" className={styles.detailActionButton} onClick={handleCopySourceSummary}>
              <CopyIcon size={14} />
              <span>{copy.copySourceSummary}</span>
            </button>
            <button type="button" className={styles.detailActionButton} onClick={handleCopySourcePath}>
              <FileText size={14} />
              <span>{copy.copySourcePath}</span>
            </button>
            <button
              type="button"
              className={styles.detailActionButton}
              onClick={handleCopyRawContent}
              disabled={!canCopyRawContent}
              title={!canCopyRawContent ? copy.noContent : undefined}
            >
              <FileText size={14} />
              <span>{copy.copyRawContentAction}</span>
            </button>
            <button type="button" className={styles.detailActionButton} onClick={handleCopyCurrentLink}>
              <Link2 size={14} />
              <span>{copy.copyCurrentLink}</span>
            </button>
          </div>

          {copyFeedback.tone !== "idle" ? (
            <p className={styles.copyNotice} data-tone={copyFeedback.tone}>
              {copyFeedback.tone === "success" ? <CheckCircle2 size={14} /> : <TriangleAlert size={14} />}
              <span>{copyFeedback.text}</span>
            </p>
          ) : null}

          <div className={styles.factGrid}>
            <section>
              <span>{copy.sourcePath}</span>
              <strong title={resolvedActiveItem.path}>{resolvedActiveItem.path || "-"}</strong>
            </section>
            <section>
              <span>{copy.sourceApi}</span>
              <strong title={activeSection.sourceApi}>{activeSection.sourceApi || "-"}</strong>
            </section>
            <section>
              <span>{copy.agentVisible}</span>
              <strong>{resolvedActiveItem.agentVisible ? copy.yes : copy.no}</strong>
            </section>
            <section>
              <span>{copy.runtimeInjected}</span>
              <strong>{resolvedActiveItem.inPrompt ? copy.yes : copy.no}</strong>
            </section>
          </div>

          <section className={styles.visibilityPanel}>
            <div className={styles.visibilityHeader}>
              <Eye size={16} />
              <div>
                <strong>{copy.agentVisibility}</strong>
                <p>{activeSection.agentVisibility}</p>
              </div>
            </div>
            <div className={styles.usageList}>
              {itemChannelPills(copy, resolvedActiveItem).map((pill) => (
                <span key={`${resolvedActiveItem.id}:channel:${pill.label}`} title={pill.hint}>
                  <CheckCircle2 size={13} />
                  {pill.label}
                </span>
              ))}
            </div>
            <div className={styles.usageList}>
              {resolvedActiveItem.usedBy.map((usage) => (
                <span key={`${resolvedActiveItem.id}:${usage}`}>
                  <CheckCircle2 size={13} />
                  {usage}
                </span>
              ))}
            </div>
          </section>

          <section className={styles.sectionPanel}>
            <div className={styles.panelHeader}>
              <div>
                <p className={styles.panelEyebrow}>{copy.summary}</p>
                <h3>{activeSection.sourceKind}</h3>
              </div>
              <span className={styles.countPill}>{formatTimestamp(activeSection.updatedAt, lang)}</span>
            </div>
            <p>{activeSection.summary}</p>
          </section>

          <details className={styles.rawPanel} open={showEditor}>
            <summary>
              <FileText size={15} />
              <span>{copy.rawContent}</span>
              <code>{resolvedActiveItem.contentType}</code>
            </summary>
            {activeItemDetailQuery.isFetching ? <p>{copy.loading}</p> : null}
            {activeItemDetailQuery.isError ? (
              <p>{copy.loadFailed}: {activeItemDetailQuery.error instanceof Error ? activeItemDetailQuery.error.message : String(activeItemDetailQuery.error)}</p>
            ) : null}
            {resolvedActiveItem.content ? (
              <pre data-language={contentLanguage(resolvedActiveItem.contentType)}>{resolvedActiveItem.content}</pre>
            ) : !activeItemDetailQuery.isFetching ? (
              <p>{copy.noContent}</p>
            ) : null}
          </details>
        </>
      ) : editDraft ? null : (
        <section className={styles.emptyDetail}>
          <Brain size={24} />
          <strong>{copy.title}</strong>
          <p>{overviewQuery.isPending ? copy.loading : copy.noMatches}</p>
        </section>
      )}

      {overview ? (
        <p className={styles.generatedAt}>
          {copy.generatedAt}: {formatTimestamp(overview.generatedAt, lang)}
        </p>
      ) : null}
    </aside>
  );

  const renderOverviewView = () => (
    <>
      <div className={styles.summaryGrid}>
        <section className={styles.summaryCard}>
          <span>{copy.sectionCount}</span>
          <strong>{overview?.summary.sectionCount ?? 0}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.itemCount}</span>
          <strong>{overview?.summary.itemCount ?? 0}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.agentVisible}</span>
          <strong>{overview?.summary.agentVisibleCount ?? 0}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.runtimeInjected}</span>
          <strong>{overview?.summary.runtimeInjectedCount ?? 0}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.managedMemory}</span>
          <strong>{managedStateCount}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.disabledOrOverridden}</span>
          <strong>{disabledOrOverriddenCount}</strong>
        </section>
      </div>

      {renderWarningStrip()}

      <section className={styles.reviewQueuePanel}>
        <div className={styles.panelHeader}>
          <div>
            <p className={styles.panelEyebrow}>{copy.healthOverview}</p>
            <h2>{copy.reviewQueue}</h2>
          </div>
          <span className={styles.countPill}>{priorityReviewPairs.length}</span>
        </div>
        <div title={copy.reviewQueueHint}>{renderReviewQueue()}</div>
      </section>

      {renderProjectMemoryQueue()}

      <div className={styles.overviewGrid}>
        <section className={styles.overviewPanel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{copy.healthOverview}</p>
              <h2>{copy.affectedRuntimeMemory}</h2>
            </div>
            <span className={styles.countPill}>{runtimePairs.length}</span>
          </div>
          {renderMemoryList(runtimePairs, copy.noRuntimeMemory, true)}
        </section>

        <section className={styles.overviewPanel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{copy.healthOverview}</p>
              <h2>{copy.needsReview}</h2>
            </div>
            <span className={styles.countPill}>{reviewPairs.length}</span>
          </div>
          {renderMemoryList(reviewPairs, copy.noIssues, true)}
        </section>
      </div>
    </>
  );

  const renderEffectiveView = () => (
    <>
      {renderMatrixPanel(copy.effectiveByChannel)}
      {renderWarningStrip()}
      <div className={styles.effectiveGrid}>
        {matrixCards.map((card) => {
          const pairs = allPairs.filter((pair) => matchesMemoryChannel(card.channel, pair));
          return (
            <section key={card.id} className={styles.overviewPanel}>
              <div className={styles.panelHeader}>
                <div>
                  <p className={styles.panelEyebrow}>{copy.whereMemoryWorks}</p>
                  <h2>{card.title}</h2>
                </div>
                <span className={styles.countPill}>{pairs.length}</span>
              </div>
              {renderMemoryList(pairs, copy.noMatches, true)}
            </section>
          );
        })}
      </div>
    </>
  );

  const renderSourceAndItemPanels = (title: string) => (
    <>
      <aside className={styles.sourcePanel}>
        <div className={styles.panelHeader}>
          <div>
            <p className={styles.panelEyebrow}>{copy.sections}</p>
            <h2>{selectedSection?.title ?? copy.allSections}</h2>
          </div>
          <span className={styles.countPill}>{selectedSectionVisibleCount}</span>
        </div>

        <label className={styles.searchBox}>
          <Search size={15} />
          <input value={searchText} placeholder={copy.searchPlaceholder} onChange={(event) => setSearchText(event.target.value)} />
        </label>

        <div className={styles.filterGroup} aria-label={copy.filters}>
          {filterOptions.map((option) => (
            <button
              key={option.id}
              type="button"
              className={option.id === activeFilter ? `${styles.filterButton} ${styles.filterButtonActive}` : styles.filterButton}
              onClick={() => setActiveFilter(option.id)}
              aria-pressed={option.id === activeFilter}
            >
              <span>{option.label}</span>
              <strong>{option.count}</strong>
            </button>
          ))}
        </div>

        <button
          type="button"
          className={!activeSectionId ? `${styles.sourceButton} ${styles.sourceButtonActive}` : styles.sourceButton}
          onClick={() => {
            setActiveItemId("");
            setActiveSectionId("");
          }}
        >
          <span className={styles.sourceIcon}>
            <Database size={15} />
          </span>
          <span className={styles.sourceCopy}>
            <strong>{copy.allSections}</strong>
            <span>
              {copy.items}: {flatVisibleItems.length}
              {selectedSectionPromptCount ? ` / ${selectedSectionPromptCount}` : ""}
            </span>
          </span>
        </button>

        <nav className={styles.sourceList} aria-label={copy.sections}>
          {sections.map((section) => {
            const active = section.id === activeSectionId;
            const metrics = sourceSectionMetrics.get(section.id);
            return (
              <button
                key={section.id}
                type="button"
                className={active ? `${styles.sourceButton} ${styles.sourceButtonActive}` : styles.sourceButton}
                onClick={() => {
                  setActiveItemId("");
                  setActiveSectionId(section.id);
                }}
                aria-pressed={active}
              >
                <span className={styles.sourceIcon}>
                  <Brain size={15} />
                </span>
                <span className={styles.sourceCopy}>
                  <strong>{section.title}</strong>
                  <span>{[section.sourcePath, section.sourceApi].filter(Boolean).join(" · ") || section.sourceKind}</span>
                </span>
                <span className={styles.sourceStats}>
                  {metrics?.itemCount ?? 0}
                  {metrics?.promptCount ? ` / ${metrics.promptCount}` : ""}
                </span>
              </button>
            );
          })}
        </nav>
      </aside>

      <main className={styles.itemPanel}>
        <div className={styles.panelHeader}>
          <div>
            <p className={styles.panelEyebrow}>{copy.items}</p>
            <h2>{selectedSection?.title ?? title}</h2>
          </div>
          <span className={styles.countPill}>{flatVisibleItems.length}</span>
        </div>

        {showRefreshNotice ? (
          <section className={styles.panelNotice} aria-label={copy.refreshFailed}>
            <TriangleAlert size={16} />
            <strong>{copy.refreshFailed}</strong>
            <span>{overviewQuery.error instanceof Error ? overviewQuery.error.message : String(overviewQuery.error)}</span>
          </section>
        ) : null}

        {renderMemoryList(flatVisibleItems, copy.noMatches, true)}
      </main>
    </>
  );

  const renderManageView = () => (
    <>
      {renderWarningStrip()}
      <div className={`${styles.workspace} ${styles.manageWorkspace}`}>
        <main className={styles.manageListPanel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{copy.management}</p>
              <h2 title={copy.manageListHint}>{copy.manageAllMemory}</h2>
            </div>
            <span className={styles.countPill}>{manageablePairs.length}</span>
          </div>
          <label className={styles.searchBox}>
            <Search size={15} />
            <input value={searchText} placeholder={copy.searchPlaceholder} onChange={(event) => setSearchText(event.target.value)} />
          </label>
          <section className={styles.manageFilterPanel} aria-label={copy.manageFilters}>
            <div className={styles.manageFilterHeader}>
              <span>{copy.manageFilters}</span>
              <strong>{flatVisibleItems.length}</strong>
            </div>
            <div className={styles.filterGroup}>
              {manageFilterOptions.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  className={option.id === activeManageFilter ? `${styles.filterButton} ${styles.filterButtonActive}` : styles.filterButton}
                  onClick={() => {
                    setActiveItemId("");
                    setActiveManageFilter(option.id);
                  }}
                  aria-pressed={option.id === activeManageFilter}
                >
                  <span>{option.label}</span>
                  <strong>{option.count}</strong>
                </button>
              ))}
            </div>
          </section>
          <section className={styles.manageSourceFilters} aria-label={copy.sourceFilters}>
            <button
              type="button"
              className={!activeSectionId ? `${styles.sourceChip} ${styles.sourceChipActive}` : styles.sourceChip}
              onClick={() => {
                setActiveItemId("");
                setActiveSectionId("");
              }}
              aria-pressed={!activeSectionId}
            >
              <span>{copy.allSections}</span>
              <strong>{manageablePairs.length}</strong>
            </button>
            {sections
              .filter((section) => (manageableSectionMetrics.get(section.id) ?? 0) > 0)
              .map((section) => {
                const active = section.id === activeSectionId;
                return (
                  <button
                    key={section.id}
                    type="button"
                    className={active ? `${styles.sourceChip} ${styles.sourceChipActive}` : styles.sourceChip}
                    onClick={() => {
                      setActiveItemId("");
                      setActiveSectionId(section.id);
                    }}
                    aria-pressed={active}
                    title={section.title}
                  >
                    <span>{section.title}</span>
                    <strong>{manageableSectionMetrics.get(section.id) ?? 0}</strong>
                  </button>
                );
              })}
          </section>
          <section className={styles.bulkActionBar}>
            <button type="button" className={styles.detailActionButton} onClick={toggleVisibleMemorySelection} disabled={mutationBusy}>
              {allVisibleSelected ? <SquareCheckBig size={14} /> : <Square size={14} />}
              <span>{allVisibleSelected ? copy.clearSelection : copy.selectAllVisible}</span>
            </button>
            <span className={styles.countPill}>
              {copy.selectedCount}: {selectedMemoryPairs.length}
            </span>
            <button
              type="button"
              className={styles.detailActionButton}
              onClick={() => {
                void runBulkMemoryAction("disable");
              }}
              disabled={mutationBusy || selectedDisablePairs.length === 0}
            >
              <Trash2 size={14} />
              <span>{bulkActionPending === "disable" ? copy.loading : copy.bulkDisable}</span>
            </button>
            <button
              type="button"
              className={styles.detailActionButton}
              onClick={() => {
                void runBulkMemoryAction("restore");
              }}
              disabled={mutationBusy || selectedRestorePairs.length === 0}
            >
              <Undo2 size={14} />
              <span>{bulkActionPending === "restore" ? copy.loading : copy.bulkRestore}</span>
            </button>
          </section>
          {renderMemoryList(flatVisibleItems, copy.noMatches, false, true)}
        </main>

        <section className={styles.manageFormPanel}>
          <div className={styles.managementHeader}>
            <div>
              <p className={styles.panelEyebrow}>{copy.management}</p>
              <h2>{editDraft ? (editDraft.mode === "create" ? copy.addMemory : copy.editMemory) : copy.manageConfigPanel}</h2>
            </div>
            <button type="button" className={styles.primaryActionButton} onClick={startCreate} disabled={mutationBusy}>
              <Pencil size={15} />
              <span>{copy.addMemory}</span>
            </button>
          </div>
          {renderManagementEditor()}
          {renderSelectedMemoryConfig()}
          {!editDraft && !activeItem ? (
            <section className={styles.emptyDetail}>
              <Brain size={24} />
              <strong>{copy.selectedMemory}</strong>
              <p>{copy.noMatches}</p>
            </section>
          ) : null}
        </section>

        {renderDetailPanel(false)}
      </div>
    </>
  );

  const renderSourcesView = () => (
    <>
      {renderMatrixPanel(copy.sourceAudit)}
      {renderWarningStrip()}
      <div className={styles.workspace}>
        {renderSourceAndItemPanels(copy.sourceAudit)}
        {renderDetailPanel()}
      </div>
    </>
  );

  const renderKnowledgeView = () => (
    <>
      <div className={styles.summaryGrid}>
        <section className={styles.summaryCard}>
          <span>{copy.knowledgeBases}</span>
          <strong>{knowledgeOverview?.summary.knowledgeBaseCount ?? 0}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.pendingProposals}</span>
          <strong>{knowledgeOverview?.summary.pendingProposalCount ?? 0}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.formalKnowledge}</span>
          <strong>{knowledgeOverview?.summary.itemCount ?? 0}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.sourceArtifacts}</span>
          <strong>{knowledgeOverview?.summary.sourceArtifactCount ?? 0}</strong>
        </section>
      </div>
      <section className={styles.pipelinePanel} aria-label={copy.platformPipeline} title={copy.knowledgeSubtitle}>
        <div className={styles.pipelineHeader}>
          <div>
            <p className={styles.panelEyebrow}>{copy.platformPipeline}</p>
            <h2>{copy.teamKnowledgeDomain}</h2>
          </div>
          <div className={styles.pipelineBoundary}>
            <span>{copy.toolReadableOnly}</span>
            <span>{copy.promptBoundary}</span>
            <span>{copy.governance}</span>
          </div>
        </div>
        <div className={styles.pipelineSteps}>
          {[
            { label: copy.pipelineSource, value: knowledgeOverview?.summary.sourceArtifactCount ?? 0 },
            { label: copy.pipelineProposal, value: knowledgeOverview?.summary.pendingProposalCount ?? 0 },
            { label: copy.pipelineBatch, value: knowledgeBases.reduce((total, base) => total + base.stats.batchCount, 0) },
            { label: copy.pipelineFormal, value: knowledgeOverview?.summary.itemCount ?? 0 },
            { label: copy.pipelineRating, value: ratingSuggestionsQuery.data?.summary.pendingSuggestionCount ?? knowledgeItems.filter((item) => item.markedAt).length },
          ].map((step, index) => (
            <div key={step.label} className={styles.pipelineStep}>
              <span className={styles.pipelineIndex}>{index + 1}</span>
              <strong>{step.value}</strong>
              <span>{step.label}</span>
            </div>
          ))}
        </div>
      </section>
      <div className={styles.knowledgeGovernanceDeck}>
      <section className={styles.usageContractPanel} aria-label={copy.usageContract}>
        <div className={styles.managementHeader}>
          <div>
            <p className={styles.panelEyebrow}>{copy.usageContract}</p>
            <h2>{copy.memoryDomains}</h2>
          </div>
          <span className={styles.countPill}>{memoryUsageContract?.domains.length ?? 0}</span>
        </div>
        <div className={styles.contractPrinciples}>
          <span title={(memoryUsageContract?.principles ?? []).join("\n")}>
            {(memoryUsageContract?.principles ?? []).length} {lang === "zh" ? "条边界规则" : "boundary rules"}
          </span>
          <span title={copy.reviewerRequired}>{copy.reviewerRequired}</span>
          <span title={copy.promptBoundary}>{copy.promptBoundary}</span>
        </div>
        <div className={styles.contractDomainGrid}>
          {(memoryUsageContract?.domains ?? []).slice(0, 4).map((domain) => (
            <section
              key={domain.domainId}
              className={styles.contractDomainRow}
              title={[
                domain.label,
                domain.owner && `${copy.ownerScope}: ${domain.owner}`,
                domain.storage && `${copy.sourcePath}: ${domain.storage}`,
                `${copy.allowedUse}: ${domain.readsThrough.join(", ") || "-"}`,
                `${copy.writeBoundary}: ${domain.canCreateFormalKnowledge ? copy.reviewerRequired : domain.boundary}`,
                `Prompt: ${domain.promptDefault || "-"}`,
              ].filter(Boolean).join("\n")}
            >
              <div>
                <strong>{memoryDomainDisplayLabel(domain.label, domain.domainId, lang)}</strong>
                <small>{memoryDomainOwnerLabel(domain.owner, lang)}</small>
              </div>
              <span>{domain.canCreateFormalKnowledge ? (lang === "zh" ? "需审核" : copy.reviewerRequired) : memoryBoundaryLabel(domain.boundary, lang)}</span>
              <code>{policyTokenLabel(domain.promptDefault, lang)}</code>
            </section>
          ))}
          {(memoryUsageContract?.domains.length ?? 0) > 4 ? (
            <section className={styles.contractDomainRow} title={(memoryUsageContract?.domains ?? []).slice(4).map((domain) => domain.label).join("\n")}>
              <div>
                <strong>+{(memoryUsageContract?.domains.length ?? 0) - 4}</strong>
                <small>{copy.memoryDomains}</small>
              </div>
              <span>{lang === "zh" ? "悬停查看" : "Hover for details"}</span>
              <code>{copy.promptBoundary}</code>
            </section>
          ) : null}
        </div>
        <div className={styles.contractStateGrid}>
          <section>
            <span>{copy.currentContractState}</span>
            <strong>{Number(memoryUsageContract?.currentState.knowledge.knowledgeBaseCount ?? 0)}</strong>
            <small>{copy.knowledgeBases}</small>
          </section>
          <section>
            <span>{copy.healthFindings}</span>
            <strong>{Number(memoryUsageContract?.currentState.operationsHealth.findingCount ?? 0)}</strong>
            <small>{copy.operationsHealth}</small>
          </section>
          <section>
            <span>{copy.governancePlan}</span>
            <strong>{Number(memoryUsageContract?.currentState.governancePlan.actionCount ?? 0)}</strong>
            <small>{copy.planOnly}</small>
          </section>
        </div>
        <div className={styles.contractForbiddenList} aria-label={copy.forbiddenActions}>
          <span title={(memoryUsageContract?.forbiddenActions ?? []).join("\n")}>
            <XCircle size={13} />
            {(memoryUsageContract?.forbiddenActions ?? []).length} {copy.forbiddenActions}
          </span>
        </div>
      </section>
      <section className={styles.knowledgeStewardPanel} aria-label={copy.knowledgeSteward}>
        <div className={styles.managementHeader}>
          <div>
            <p className={styles.panelEyebrow}>{copy.knowledgeSteward}</p>
            <h2>{knowledgeSteward?.steward.functionalDisplayName || copy.knowledgeSteward}</h2>
          </div>
          <div className={styles.managementActions}>
            <span className={knowledgeSteward?.steward.protected ? styles.statusPill : styles.statusPillMuted}>
              {knowledgeSteward?.steward.protected ? copy.protectedAgent : knowledgeSteward?.steward.status || copy.missing}
            </span>
            <NavLink className={styles.detailActionButton} to={knowledgeSteward?.steward.directChatPath || "/chat"}>
              <Link2 size={14} />
              <span>{copy.stewardDirectChat}</span>
            </NavLink>
          </div>
        </div>
        <div className={styles.stewardGrid}>
          <div className={styles.stewardMission}>
            <span>{copy.stewardMission}</span>
            <strong title={knowledgeSteward?.steward.taskProfile.mission || knowledgeSteward?.steward.displayName || copy.loading}>
              {lang === "zh" ? "知识治理" : knowledgeSteward?.steward.taskProfile.mission || knowledgeSteward?.steward.displayName || copy.loading}
            </strong>
            <small>{knowledgeSteward?.steward.taskProfile.avoidTasks || copy.noDirectApply}</small>
          </div>
          <div className={styles.stewardMetric}>
            <span>{copy.openGovernanceTasks}</span>
            <strong>{knowledgeSteward?.governance.summary.openTaskCount ?? 0}</strong>
            <small>
              {copy.pendingProposals}: {knowledgeSteward?.governance.summary.proposalReviewCount ?? 0} · {copy.ratingSuggestions}: {knowledgeSteward?.governance.summary.ratingReviewCount ?? 0}
            </small>
          </div>
          <div className={styles.stewardMetric}>
            <span>{copy.stewardBoundary}</span>
            <strong title={knowledgeSteward?.steward.permissionBoundary || "proposal_and_rating_suggestion_only"}>
              {policyTokenLabel(knowledgeSteward?.steward.permissionBoundary || "proposal_and_rating_suggestion_only", lang)}
            </strong>
            <small>{knowledgeSteward?.operatingBoundary.formalKnowledgeRequiresReviewer ? copy.reviewerRequired : copy.noDirectApply}</small>
          </div>
        </div>
        <div className={styles.stewardToolRows}>
          {(() => {
            const preferred = compactInlineList(knowledgeSteward?.steward.toolPolicy.preferredTools, 3);
            const allowed = compactInlineList(knowledgeSteward?.steward.toolPolicy.allowedTools, 2);
            const preferredCount = (knowledgeSteward?.steward.toolPolicy.preferredTools ?? []).length;
            const allowedCount = (knowledgeSteward?.steward.toolPolicy.allowedTools ?? []).length;
            return (
              <>
                <span title={preferred.title}>{copy.preferredTools}</span>
                <code title={preferred.title}>{preferredCount} {lang === "zh" ? "项" : "items"}</code>
                <span title={allowed.title}>{copy.allowedTools}</span>
                <small title={allowed.title}>{allowedCount} {lang === "zh" ? "项" : "items"}</small>
              </>
            );
          })()}
        </div>
        {knowledgeStewardRecommendations.length ? (
          <div className={styles.stewardRecommendations}>
            <div className={styles.stewardRecommendationHeader}>
              <span>{copy.stewardRecommendations}</span>
              <small>
                {knowledgeDashboardSnapshot?.recommendations.operatingBoundary.recommendationsOnly ? copy.recommendationsOnly : copy.stewardRecommendationHint}
              </small>
            </div>
            {knowledgeStewardRecommendations.map((recommendation) => (
              <section
                key={recommendation.recommendationId}
                className={styles.stewardRecommendationRow}
                title={[recommendation.reason, recommendation.recommendedAction, recommendation.knowledgeBaseName].filter(Boolean).join("\n")}
              >
                <span className={styles.statusPill}>{recommendation.priority}</span>
                <strong>{recommendation.title}</strong>
                <span>{recommendation.reason}</span>
                <small>
                  {copy.recommendedAction}: {recommendation.recommendedAction} · {recommendation.knowledgeBaseName}
                </small>
                <button type="button" className={styles.detailActionButton} onClick={() => setTraceTargetId(recommendation.targetId)}>
                  <Eye size={14} />
                  <span>{copy.traceability}</span>
                </button>
              </section>
            ))}
          </div>
        ) : null}
        <div className={styles.stewardWorkbench}>
          <div className={styles.stewardRecommendationHeader}>
            <span>{copy.stewardWorkbench}</span>
            <small>{copy.reviewerRequired}</small>
          </div>
          <div className={styles.stewardStageGrid} aria-label={copy.stewardStages}>
            {(knowledgeStewardWorkbench?.stages ?? []).slice(0, 2).map((stage) => (
              <section key={stage.stageId} className={styles.stewardStageCard} title={[stage.title, stage.description, stage.nextTool].filter(Boolean).join("\n")}>
                <div>
                  <span className={stage.status === "clear" ? styles.statusPillMuted : styles.statusPill} title={stage.status}>
                    {policyTokenLabel(stage.status, lang)}
                  </span>
                  <strong>{stewardStageDisplayTitle(stage.stageId, stage.title, lang)}</strong>
                </div>
                <p title={stage.description}>{stage.description}</p>
                <small>
                  {copy.openGovernanceTasks}: {stage.openCount} · {copy.executable}: {stage.executableCount}
                </small>
                <code title={stage.nextTool}>{stage.nextTool}</code>
              </section>
            ))}
          </div>
          <div className={styles.stewardActionGrid} aria-label={copy.stewardNextActions}>
            {(knowledgeStewardWorkbench?.nextActions ?? []).slice(0, 4).map((action) => (
              <button key={action.actionId} type="button" className={styles.stewardActionRow} onClick={() => setTraceTargetId(action.targetId)}>
                <span className={styles.statusPill}>{action.priority}</span>
                <strong>{action.title}</strong>
                <small>{action.nextStep}</small>
              </button>
            ))}
          </div>
          <div className={styles.stewardChecklist} aria-label={copy.acceptanceChecklist}>
            <span title={(knowledgeStewardWorkbench?.acceptanceChecklist ?? []).map((item) => item.label).join("\n")}>
              <CheckCircle2 size={13} />
              {(knowledgeStewardWorkbench?.acceptanceChecklist ?? []).length} {copy.acceptanceChecklist}
            </span>
          </div>
        </div>
      </section>
      </div>
      {knowledgeFeedback.tone !== "idle" ? (
        <section className={knowledgeFeedback.tone === "error" ? styles.panelError : styles.panelNotice}>
          {knowledgeFeedback.tone === "error" ? <TriangleAlert size={16} /> : <CheckCircle2 size={16} />}
          <span>{knowledgeFeedback.text}</span>
        </section>
      ) : null}
      <div className={`${styles.workspace} ${styles.knowledgeWorkspace}`}>
        <aside className={styles.sourcePanel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{copy.teamKnowledge}</p>
              <h2>{copy.knowledgeBases}</h2>
            </div>
            <span className={styles.countPill}>{knowledgeBases.length}</span>
          </div>
          <section className={styles.governanceMiniPanel} aria-label={copy.toolVisibility} title={copy.knowledgeHint}>
            <strong>{copy.toolVisibility}</strong>
            {(() => {
              const tools = Object.values(permissionAudit?.tools ?? {});
              const visibleTools = tools.filter((tool) => tool.visible);
              const hiddenTools = tools.filter((tool) => !tool.visible);
              return (
                <>
                  <span className={styles.statusPill} title={visibleTools.map((tool) => tool.toolName).join("\n")}>
                    {copy.yes}: {visibleTools.length}
                  </span>
                  <span
                    className={hiddenTools.length ? styles.statusPillMuted : styles.statusPill}
                    title={hiddenTools.map((tool) => `${tool.toolName}: ${tool.reason}`).join("\n")}
                  >
                    {copy.missing}: {hiddenTools.length}
                  </span>
                </>
              );
            })()}
          </section>
          {knowledgeDashboardSnapshotQuery.isPending ? <div className={styles.emptyState}>{copy.loading}</div> : null}
          {!knowledgeDashboardSnapshotQuery.isPending && !knowledgeBases.length ? (
            <section className={styles.emptyDetail}>
              <Database size={22} />
              <strong>{copy.noKnowledgeBases}</strong>
            </section>
          ) : null}
          <nav className={styles.sourceList} aria-label={copy.knowledgeBases}>
            {knowledgeBases.map((base) => {
              const requestId = knowledgeBaseRequestId(base);
              return (
                <button
                  key={requestId}
                  type="button"
                  className={requestId === activeKnowledgeBaseForItems ? `${styles.sourceButton} ${styles.sourceButtonActive}` : styles.sourceButton}
                  onClick={() => setActiveKnowledgeBaseId(requestId)}
                >
                  <span className={styles.sourceIcon}>
                    <Database size={15} />
                  </span>
                  <span className={styles.sourceCopy}>
                    <strong>{base.name}</strong>
                    <span>{base.teamName || base.teamId}</span>
                  </span>
                  <span className={styles.sourceStats}>{base.stats.itemCount}/{base.stats.pendingProposalCount}</span>
                </button>
              );
            })}
          </nav>
        </aside>

        <main className={styles.knowledgeMain}>
          <div className={styles.knowledgeModeTabs} role="tablist" aria-label={copy.governance}>
            {([
              {
                key: "sources",
                label: lang === "zh" ? "来源" : "Sources",
                hint: `${copy.ownerSourceInbox} / ${copy.centralSources}`,
                count: (sourceInboxQuery.data?.summary.sourceCount ?? ownerInboxSources.length) + (centralSourcesQuery.data?.summary.centralSourceCount ?? centralSources.length),
              },
              {
                key: "search",
                label: lang === "zh" ? "检索" : "Search",
                hint: `${copy.knowledgeSearch} / ${copy.ragRetrieval}`,
                count: (knowledgeSearchQuery.data?.summary.resultCount ?? 0) + (knowledgeRagRetrieveQuery.data?.summary.contextCount ?? 0),
              },
              {
                key: "review",
                label: lang === "zh" ? "审核" : "Review",
                hint: `${copy.pendingProposals} / ${copy.ratingSuggestions}`,
                count: (activeKnowledgeBase?.pendingProposals.length ?? 0) + ratingSuggestions.length,
              },
              {
                key: "governance",
                label: lang === "zh" ? "治理" : "Governance",
                hint: `${copy.operationsHealth} / ${copy.governanceTasks}`,
                count: (knowledgeOperationsHealth?.summary.findingCount ?? 0) + (governanceTasksQuery.data?.summary.openTaskCount ?? 0),
              },
              {
                key: "permissions",
                label: lang === "zh" ? "权限" : "Permissions",
                hint: `${copy.permissionAudit} / ${copy.ingestionAdapters}`,
                count: (permissionAudit?.summary.knowledgeBaseCount ?? 0) + ingestionAdapters.length,
              },
            ] satisfies Array<{ key: KnowledgeWorkspaceMode; label: string; hint: string; count: number }>).map((mode) => (
              <button
                key={mode.key}
                type="button"
                role="tab"
                aria-selected={activeKnowledgeWorkspaceMode === mode.key}
                className={activeKnowledgeWorkspaceMode === mode.key ? styles.knowledgeModeTabActive : styles.knowledgeModeTab}
                title={mode.hint}
                onClick={() => setActiveKnowledgeWorkspaceMode(mode.key)}
              >
                <span>{mode.label}</span>
                <strong>{mode.count}</strong>
              </button>
            ))}
          </div>
          {activeKnowledgeWorkspaceMode === "sources" ? (
          <section className={styles.managementPanel}>
            <div className={styles.managementHeader}>
              <div>
                <p className={styles.panelEyebrow}>{copy.sourceGovernance}</p>
                <h2>{copy.ownerSourceInbox}</h2>
              </div>
              <span className={styles.countPill}>{sourceInboxQuery.data?.summary.sourceCount ?? ownerInboxSources.length}</span>
            </div>
            <div className={styles.sourceGovernanceControls}>
              <label>
                <span>{copy.ownerScope}</span>
                <select value={sourceOwnerType} onChange={(event) => setSourceOwnerType(event.target.value as SourceOwnerType)}>
                  <option value="team">{copy.ownerTeam}</option>
                  <option value="agent">{copy.ownerAgent}</option>
                </select>
              </label>
              <label>
                <span>{copy.ownerId}</span>
                <input value={sourceOwnerId} onChange={(event) => setSourceOwnerId(event.target.value)} />
              </label>
              <label>
                <span>{copy.status}</span>
                <select value={sourceInboxStatus} onChange={(event) => setSourceInboxStatus(event.target.value as SourceInboxStatusFilter)}>
                  {(["pending", "accepted", "rejected", "duplicate", "needs_more_context", "all"] as SourceInboxStatusFilter[]).map((status) => (
                    <option key={status} value={status}>{sourceInboxStatusLabel(copy, status)}</option>
                  ))}
                </select>
              </label>
              <button type="button" className={styles.detailActionButton} onClick={applyActiveKnowledgeOwner}>
                <Database size={14} />
                <span>{copy.useActiveKnowledgeOwner}</span>
              </button>
            </div>
            <div className={styles.sourceGovernanceGrid}>
              <div className={styles.sourceGovernanceColumn}>
                <div className={styles.managementHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{copy.collectOwnerSource}</p>
                    <h3>{copy.ownerSourceInbox}</h3>
                  </div>
                  <button type="button" className={styles.primaryActionButton} onClick={() => setShowOwnerSourceForm((value) => !value)}>
                    <Pencil size={15} />
                    <span>{showOwnerSourceForm ? copy.cancelEdit : copy.submitSource}</span>
                  </button>
                </div>
                {showOwnerSourceForm ? (
                <>
                <div className={styles.knowledgeFormGrid}>
                  <label>
                    <span>{copy.sourceType}</span>
                    <select value={ownerSourceDraft.sourceType} onChange={(event) => setOwnerSourceDraft({ ...ownerSourceDraft, sourceType: event.target.value })}>
                      {["manual_user_entry", "team_chat_refinement", "external_search_refinement", "pdf_refinement", "agent_authored", "runtime_evidence_refinement"].map((type) => (
                        <option key={type} value={type}>{type}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>{copy.titleField}</span>
                    <input value={ownerSourceDraft.title} onChange={(event) => setOwnerSourceDraft({ ...ownerSourceDraft, title: event.target.value })} />
                  </label>
                  <label>
                    <span>{copy.originalFilename}</span>
                    <input value={ownerSourceDraft.originalFilename} onChange={(event) => setOwnerSourceDraft({ ...ownerSourceDraft, originalFilename: event.target.value })} />
                  </label>
                  <label>
                    <span>{copy.sourceCreatedAt}</span>
                    <input value={ownerSourceDraft.sourceCreatedAt} onChange={(event) => setOwnerSourceDraft({ ...ownerSourceDraft, sourceCreatedAt: event.target.value })} />
                  </label>
                  <label>
                    <span>{copy.capturedBy}</span>
                    <input value={ownerSourceDraft.capturedBy} onChange={(event) => setOwnerSourceDraft({ ...ownerSourceDraft, capturedBy: event.target.value })} />
                  </label>
                  <label>
                    <span>{copy.sourceHash}</span>
                    <input value={ownerSourceDraft.sourceHash} onChange={(event) => setOwnerSourceDraft({ ...ownerSourceDraft, sourceHash: event.target.value })} />
                  </label>
                  <label className={styles.wideField}>
                    <span>{copy.sourceRef}</span>
                    <textarea rows={2} value={ownerSourceDraft.sourceRef} onChange={(event) => setOwnerSourceDraft({ ...ownerSourceDraft, sourceRef: event.target.value })} />
                  </label>
                  <label className={styles.wideField}>
                    <span>{copy.evidenceRange}</span>
                    <textarea rows={2} value={ownerSourceDraft.evidenceRange} onChange={(event) => setOwnerSourceDraft({ ...ownerSourceDraft, evidenceRange: event.target.value })} />
                  </label>
                  <label className={styles.wideField}>
                    <span>{copy.summaryField}</span>
                    <textarea rows={2} value={ownerSourceDraft.summary} onChange={(event) => setOwnerSourceDraft({ ...ownerSourceDraft, summary: event.target.value })} />
                  </label>
                  <label className={styles.wideField}>
                    <span>{copy.originalContent}</span>
                    <textarea rows={4} value={ownerSourceDraft.originalContent} onChange={(event) => setOwnerSourceDraft({ ...ownerSourceDraft, originalContent: event.target.value })} />
                  </label>
                </div>
                <div className={styles.formActionRow}>
                  <button type="button" className={styles.primaryActionButton} onClick={submitOwnerSource} disabled={knowledgeBusy || !activeSourceOwnerId}>
                    <Link2 size={15} />
                    <span>{copy.collectOwnerSource}</span>
                  </button>
                </div>
                </>
                ) : (
                <button type="button" className={styles.collapsedFormButton} onClick={() => setShowOwnerSourceForm(true)}>
                  <Pencil size={15} />
                  <span>{copy.submitSource}</span>
                  <small>{ownerSourceDraft.sourceType}</small>
                </button>
                )}
              </div>
              <div className={styles.sourceGovernanceColumn}>
                <div className={styles.managementHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{copy.reviewSource}</p>
                    <h3>{copy.centralSourceRegistry}</h3>
                  </div>
                  <span className={styles.countPill}>{centralSourcesQuery.data?.summary.centralSourceCount ?? centralSources.length}</span>
                </div>
                <div className={styles.sourceGovernanceControls}>
                  <label>
                    <span>{copy.sourceReviewNote}</span>
                    <input value={sourceReviewNote} onChange={(event) => setSourceReviewNote(event.target.value)} />
                  </label>
                  <label>
                    <span>{copy.centralSourceId}</span>
                    <input value={duplicateCentralSourceId} onChange={(event) => setDuplicateCentralSourceId(event.target.value)} />
                  </label>
                </div>
                <div className={styles.sourceRecordList}>
                  {ownerInboxSources.map((source) => (
                    <article key={source.inboxSourceId} className={styles.sourceRecord}>
                      <div className={styles.sourceRecordHeader}>
                        <strong>{source.title || source.inboxSourceId}</strong>
                        <span className={source.status === "pending" || source.status === "needs_more_context" ? styles.statusPill : styles.statusPillMuted}>
                          {source.status}
                        </span>
                      </div>
                      <p>{source.summary || source.sourceType}</p>
                      <div className={styles.sourceRecordMeta}>
                        <span>{copy.originalPath}: {source.originalPath || "-"}</span>
                        <span>{copy.sourceHash}: {source.sourceHash || "-"}</span>
                        <span>{copy.curationStatus}: {source.curationStatus || "-"}</span>
                        <span>{copy.dedupeStatus}: {source.dedupeStatus || "-"}</span>
                      </div>
                      <div className={styles.sourceRecordActions}>
                        <button
                          type="button"
                          className={styles.detailActionButton}
                          disabled={knowledgeBusy || !(source.status === "pending" || source.status === "needs_more_context")}
                          onClick={() => reviewOwnerSource(source, "accepted")}
                        >
                          <CheckCircle2 size={14} />
                          <span>{copy.acceptSource}</span>
                        </button>
                        <button
                          type="button"
                          className={styles.detailActionButton}
                          disabled={knowledgeBusy || !(source.status === "pending" || source.status === "needs_more_context")}
                          onClick={() => reviewOwnerSource(source, "needs_more_context")}
                        >
                          <Eye size={14} />
                          <span>{copy.needsMoreContext}</span>
                        </button>
                        <button
                          type="button"
                          className={styles.detailActionButton}
                          disabled={knowledgeBusy || !(source.status === "pending" || source.status === "needs_more_context") || !duplicateCentralSourceId.trim()}
                          onClick={() => reviewOwnerSource(source, "duplicate")}
                        >
                          <CopyIcon size={14} />
                          <span>{copy.markDuplicate}</span>
                        </button>
                        <button
                          type="button"
                          className={styles.detailActionButton}
                          disabled={knowledgeBusy || !(source.status === "pending" || source.status === "needs_more_context")}
                          onClick={() => reviewOwnerSource(source, "rejected")}
                        >
                          <XCircle size={14} />
                          <span>{copy.rejectProposal}</span>
                        </button>
                      </div>
                    </article>
                  ))}
                  {!sourceInboxQuery.isPending && !ownerInboxSources.length ? (
                    <section className={styles.emptyDetail}>
                      <FileText size={20} />
                      <strong>{copy.noInboxSources}</strong>
                    </section>
                  ) : null}
                </div>
              </div>
            </div>
            <div className={styles.sourceRecordList}>
              {centralSources.map((source) => (
                <article key={source.centralSourceId} className={styles.sourceRecord}>
                  <div className={styles.sourceRecordHeader}>
                    <strong>{source.title || source.centralSourceId}</strong>
                    <span className={styles.statusPill}>{source.status}</span>
                  </div>
                  <p>{source.summary || source.sourceType}</p>
                  <div className={styles.sourceRecordMeta}>
                    <span>{copy.centralSourceId}: {source.centralSourceId}</span>
                    <span>{copy.centralPath}: {source.centralPath || "-"}</span>
                    <span>{copy.originalPath}: {source.originOriginalPath || "-"}</span>
                    <span>{copy.reviewedBy}: {source.acceptedByAgentId || "-"}</span>
                    <span>{copy.reviewedAt}: {formatTimestamp(source.acceptedAt, lang)}</span>
                  </div>
                  <div className={styles.sourceRecordActions}>
                    <button
                      type="button"
                      className={styles.detailActionButton}
                      disabled={!activeKnowledgeBase?.permissions.canPropose || knowledgeBusy || !activeKnowledgeBaseForItems}
                      onClick={() => attachCentralSource(source.centralSourceId)}
                    >
                      <Link2 size={14} />
                      <span>{copy.attachCentralSource}</span>
                    </button>
                  </div>
                </article>
              ))}
              {!centralSourcesQuery.isPending && !centralSources.length ? (
                <section className={styles.emptyDetail}>
                  <Database size={20} />
                  <strong>{copy.noCentralSources}</strong>
                </section>
              ) : null}
            </div>
          </section>
          ) : null}

          {activeKnowledgeWorkspaceMode === "search" ? (
          <section className={styles.managementPanel}>
            <div className={styles.managementHeader}>
              <div>
                <p className={styles.panelEyebrow}>{copy.knowledgeSearch}</p>
                <h2>{copy.governance}</h2>
              </div>
              <span className={styles.countPill}>{knowledgeSearchQuery.data?.summary.resultCount ?? 0}</span>
            </div>
            <div className={styles.knowledgeFormGrid}>
              <label>
                <span>{copy.searchQuery}</span>
                <input value={knowledgeSearchDraft.query} onChange={(event) => setKnowledgeSearchDraft({ ...knowledgeSearchDraft, query: event.target.value })} />
              </label>
              <label>
                <span>{copy.tags}</span>
                <input value={knowledgeSearchDraft.tags} onChange={(event) => setKnowledgeSearchDraft({ ...knowledgeSearchDraft, tags: event.target.value })} />
              </label>
              <label>
                <span>{copy.searchMode}</span>
                <select
                  value={knowledgeSearchDraft.searchMode}
                  onChange={(event) =>
                    setKnowledgeSearchDraft({
                      ...knowledgeSearchDraft,
                      searchMode: event.target.value as KnowledgeSearchDraft["searchMode"],
                    })
                  }
                >
                  <option value="exact">{copy.exactSearch}</option>
                  <option value="semantic">{copy.semanticSearch}</option>
                  <option value="hybrid">{copy.hybridSearch}</option>
                </select>
              </label>
              <label>
                <span>{copy.ragTopK}</span>
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={knowledgeSearchDraft.ragTopK}
                  onChange={(event) =>
                    setKnowledgeSearchDraft({
                      ...knowledgeSearchDraft,
                      ragTopK: Math.min(20, Math.max(1, Number(event.target.value) || 5)),
                    })
                  }
                />
              </label>
              <label>
                <span>{copy.ragContextBudget}</span>
                <input
                  type="number"
                  min={120}
                  max={4000}
                  value={knowledgeSearchDraft.ragMaxContextChars}
                  onChange={(event) =>
                    setKnowledgeSearchDraft({
                      ...knowledgeSearchDraft,
                      ragMaxContextChars: Math.min(4000, Math.max(120, Number(event.target.value) || 1200)),
                    })
                  }
                />
              </label>
            </div>
            <div className={styles.knowledgeProposalList}>
              {knowledgeSearchResults.map((item) => (
                <section key={`search:${item.knowledgeItemId}`} className={styles.knowledgeRow}>
                  <strong>{item.title}</strong>
                  <span>{item.summary || item.content}</span>
                  <span className={styles.statusPill}>{item.importanceLevel}</span>
                  <small>{item.teamName} · {item.knowledgeBaseName} · {item.sourceTypes.join(", ") || copy.sourceArtifacts}</small>
                  <small>{copy.semanticScore}: {Math.round(Number(item.semanticScore || 0) * 100)}% · {item.matchReason}</small>
                </section>
              ))}
              {!knowledgeSearchQuery.isPending && !knowledgeSearchResults.length ? (
                <section className={styles.emptyDetail}>
                  <Search size={20} />
                  <strong>{copy.noMatches}</strong>
                </section>
              ) : null}
            </div>
            <section className={styles.ragPreviewPanel} aria-label={copy.ragRetrieval} title={copy.ragRetrievalHint}>
              <div className={styles.ragPreviewHeader}>
                <div>
                  <p className={styles.panelEyebrow}>{copy.ragRetrieval}</p>
                  <h3>{copy.ragContextCandidates}</h3>
                </div>
                <span className={styles.countPill}>{knowledgeRagRetrieveQuery.data?.summary.contextCount ?? 0}</span>
              </div>
              <div className={styles.ragHealthStrip} aria-label={copy.ragHealth}>
                <span>{copy.ragProvider}: {localRagProviderHealth?.provider ?? knowledgeRagHealth?.provider ?? "local"} · {localRagProviderHealth?.status ?? knowledgeRagHealth?.status ?? copy.loading}</span>
                <span>{copy.ragVector}: {localRagProviderHealth?.vectorEnabled ? copy.yes : copy.no}</span>
                <span>{copy.ragIndexed}: {localRagProviderHealth?.indexedItemCount ?? 0}</span>
                <span data-stale={Number(localRagProviderHealth?.staleItemCount ?? 0) > 0 ? "true" : "false"}>
                  {copy.ragStale}: {localRagProviderHealth?.staleItemCount ?? 0}
                </span>
              </div>
              <div className={styles.ragPolicyStrip}>
                <span>{copy.ragNoPromptInjection}: {knowledgeRagPolicy?.injectsPromptByDefault ? copy.no : copy.yes}</span>
                <span>ACL: {knowledgeRagPolicy?.honorsKnowledgeAcl ? copy.yes : copy.no}</span>
                <span>{copy.noDirectApply}: {knowledgeRagPolicy?.mutatesFormalKnowledge ? copy.no : copy.yes}</span>
                <span>{copy.ragCitations}: {knowledgeRagRetrieveQuery.data?.summary.citationCount ?? 0}</span>
              </div>
              <div className={styles.ragContextList}>
                {knowledgeRagContexts.map((context) => (
                  <article key={context.contextId} className={styles.ragContextCard}>
                    <div className={styles.ragContextMeta}>
                      <strong>{context.rank}. {context.title || context.contextId}</strong>
                      <span>{Math.round(Number(context.score || 0) * 100)}% · {context.matchReason || context.retrievalMode}</span>
                    </div>
                    <p>{context.text}</p>
                    <small>
                      {copy.ragCitations}: {context.source.teamName || context.source.teamId} · {context.source.knowledgeBaseName || context.source.knowledgeBaseId} · {context.source.knowledgeItemId}
                    </small>
                  </article>
                ))}
                {!knowledgeRagRetrieveQuery.isPending && !knowledgeRagContexts.length ? (
                  <section className={styles.emptyDetail}>
                    <Link2 size={20} />
                    <strong>{copy.ragNoContexts}</strong>
                  </section>
                ) : null}
              </div>
            </section>
          </section>
          ) : null}

          {activeKnowledgeWorkspaceMode === "governance" ? (
          <>
          <section className={styles.managementPanel}>
            <div className={styles.managementHeader}>
              <div>
                <p className={styles.panelEyebrow}>{copy.operationsHealth}</p>
                <h2>{copy.healthFindings}</h2>
              </div>
              <span className={styles.countPill}>{knowledgeOperationsHealth?.summary.findingCount ?? 0}</span>
            </div>
            <div className={styles.healthStrip}>
              <span>{copy.knowledgeBases}: {knowledgeOperationsHealth?.summary.knowledgeBaseCount ?? 0}</span>
              <span>{copy.pendingProposals}: {knowledgeOperationsHealth?.summary.pendingProposalCount ?? 0}</span>
              <span>{copy.ratingSuggestions}: {knowledgeOperationsHealth?.summary.pendingRatingSuggestionCount ?? 0}</span>
              <span>{copy.formalKnowledge}: {knowledgeOperationsHealth?.summary.unratedItemCount ?? 0}</span>
            </div>
            <div className={styles.knowledgeProposalList}>
              {(knowledgeOperationsHealth?.findings ?? []).slice(0, 8).map((finding) => (
                <section key={finding.findingId} className={styles.knowledgeRow}>
                  <span className={styles.statusPill}>{finding.severity}</span>
                  <strong>{finding.findingType}</strong>
                  <span>{finding.message}</span>
                  <small>{finding.knowledgeBaseName} · {finding.count}</small>
                  <small>{finding.nextReviewTargetIds.slice(0, 2).join(", ") || "-"}</small>
                </section>
              ))}
              {!knowledgeDashboardSnapshotQuery.isPending && !(knowledgeOperationsHealth?.findings ?? []).length ? (
                <section className={styles.emptyDetail}>
                  <CheckCircle2 size={20} />
                  <strong>{copy.noIssues}</strong>
                </section>
              ) : null}
            </div>
          </section>

          <section className={styles.managementPanel}>
            <div className={styles.managementHeader}>
              <div>
                <p className={styles.panelEyebrow}>{copy.governancePlan}</p>
                <h2>{copy.planOnly}</h2>
              </div>
              <span className={styles.statusPillMuted}>{knowledgeGovernancePlan?.mode ?? "recommendations_only"}</span>
            </div>
            <div className={styles.healthStrip}>
              <span>{copy.noDirectApply}: {knowledgeGovernancePlan?.operatingBoundary.canDirectlyApplyKnowledge ? copy.yes : copy.no}</span>
              <span>{copy.reviewerRequired}: {knowledgeGovernancePlan?.operatingBoundary.formalKnowledgeRequiresReviewer ? copy.yes : copy.no}</span>
              <span>{copy.stewardNextActions}: {knowledgeGovernancePlan?.summary.actionCount ?? 0}</span>
            </div>
            <div className={styles.knowledgeProposalList}>
              {(knowledgeGovernancePlan?.actions ?? []).slice(0, 8).map((action) => (
                <section key={action.planActionId} className={styles.knowledgeRow}>
                  <span className={styles.statusPill}>{action.priority}</span>
                  <strong>{action.title}</strong>
                  <span>{action.nextStep}</span>
                  <small>{action.kind} · {action.recommendedTool}</small>
                  <small>{action.mutatesFormalKnowledge ? copy.createsKnowledgeItem : copy.planOnly}</small>
                </section>
              ))}
              {!knowledgeDashboardSnapshotQuery.isPending && !(knowledgeGovernancePlan?.actions ?? []).length ? (
                <section className={styles.emptyDetail}>
                  <CheckCircle2 size={20} />
                  <strong>{copy.noIssues}</strong>
                </section>
              ) : null}
            </div>
          </section>

          <section className={styles.managementPanel}>
            <div className={styles.managementHeader}>
              <div>
                <p className={styles.panelEyebrow}>{copy.governanceTasks}</p>
                <h2>{copy.teamKnowledgeDomain}</h2>
              </div>
              <span className={styles.countPill}>{governanceTasksQuery.data?.summary.openTaskCount ?? 0}</span>
            </div>
            <div className={styles.knowledgeProposalList}>
              {governanceTasks.slice(0, 8).map((task) => (
                <section key={task.taskId} className={styles.knowledgeRow}>
                  <span className={styles.statusPill}>{task.priority}</span>
                  <strong>{task.title}</strong>
                  <span>{task.summary || task.targetId}</span>
                  <small>{task.taskType} · {task.targetStatus} · {task.knowledgeBaseName}</small>
                  <button type="button" className={styles.detailActionButton} onClick={() => setTraceTargetId(task.targetId)}>
                    <Eye size={14} />
                    <span>{copy.traceability}</span>
                  </button>
                </section>
              ))}
              {!governanceTasksQuery.isPending && !governanceTasks.length ? (
                <section className={styles.emptyDetail}>
                  <CheckCircle2 size={20} />
                  <strong>{copy.noIssues}</strong>
                </section>
              ) : null}
            </div>
          </section>
          </>
          ) : null}

          {activeKnowledgeWorkspaceMode === "permissions" ? (
          <section className={styles.managementPanel}>
            <div className={styles.managementHeader}>
              <div>
                <p className={styles.panelEyebrow}>{copy.ingestionAdapters}</p>
                <h2>{copy.outputContract}</h2>
              </div>
              <span className={styles.countPill}>{ingestionAdapters.length}</span>
            </div>
            <div className={styles.permissionMatrix}>
              {ingestionAdapters.map((adapter) => (
                <section key={adapter.sourceType} className={styles.permissionRow}>
                  <strong>{adapter.sourceType}</strong>
                  <span>{adapter.requiredSourceRef.join(", ")}</span>
                  <small>{copy.outputContract}: {adapter.outputContract.creates.join(" + ")}</small>
                  <small>{copy.createsKnowledgeItem}: {adapter.outputContract.createsKnowledgeItem ? copy.yes : copy.no}</small>
                </section>
              ))}
            </div>
          </section>
          ) : null}

          {activeKnowledgeWorkspaceMode === "review" ? (
          <>
          <section className={styles.managementPanel}>
            <div className={styles.managementHeader}>
              <div>
                <p className={styles.panelEyebrow}>{copy.refinementProposal}</p>
                <h2>{copy.pendingProposals}</h2>
              </div>
              <button
                type="button"
                className={styles.primaryActionButton}
                onClick={submitRefinementProposal}
                disabled={!activeKnowledgeBase?.permissions.canPropose || knowledgeBusy}
              >
                <Pencil size={15} />
                <span>{copy.submitProposal}</span>
              </button>
            </div>
            <div className={styles.knowledgeFormGrid}>
              <label>
                <span>{copy.proposalTitle}</span>
                <input value={proposalDraft.title} onChange={(event) => setProposalDraft({ ...proposalDraft, title: event.target.value })} />
              </label>
              <label>
                <span>{copy.capturedBy}</span>
                <input value={proposalDraft.proposedByAgentId} onChange={(event) => setProposalDraft({ ...proposalDraft, proposedByAgentId: event.target.value })} />
              </label>
              <label>
                <span>{copy.sourceArtifacts}</span>
                <input value={proposalDraft.sourceArtifactIds} onChange={(event) => setProposalDraft({ ...proposalDraft, sourceArtifactIds: event.target.value })} />
              </label>
              <label>
                <span>{copy.tags}</span>
                <input value={proposalDraft.tags} onChange={(event) => setProposalDraft({ ...proposalDraft, tags: event.target.value })} />
              </label>
              <label className={styles.wideField}>
                <span>{copy.summaryField}</span>
                <textarea rows={2} value={proposalDraft.summary} onChange={(event) => setProposalDraft({ ...proposalDraft, summary: event.target.value })} />
              </label>
              <label className={styles.wideField}>
                <span>{copy.proposalContent}</span>
                <textarea rows={4} value={proposalDraft.content} onChange={(event) => setProposalDraft({ ...proposalDraft, content: event.target.value })} />
              </label>
            </div>
            <div className={styles.knowledgeProposalList}>
              {(activeKnowledgeBase?.pendingProposals ?? []).map((proposal) => (
                  <section key={proposal.proposalId} className={styles.knowledgeRow}>
                    <strong>{proposal.title}</strong>
                    <span>{proposal.summary || proposal.content}</span>
                    <button
                      type="button"
                      className={styles.detailActionButton}
                      disabled={!activeKnowledgeBase?.permissions.canReview || knowledgeBusy}
                      onClick={() => reviewProposal(proposal.proposalId, "approved")}
                    >
                      <CheckCircle2 size={14} />
                      <span>{copy.approveProposal}</span>
                    </button>
                    <button
                      type="button"
                      className={styles.detailActionButton}
                      disabled={!activeKnowledgeBase?.permissions.canReview || knowledgeBusy}
                      onClick={() => reviewProposal(proposal.proposalId, "rejected")}
                    >
                      <XCircle size={14} />
                      <span>{copy.rejectProposal}</span>
                    </button>
                  </section>
              ))}
              {activeKnowledgeBase && activeKnowledgeBase.pendingProposals.length === 0 ? (
                <section className={styles.emptyDetail}>
                  <Eye size={20} />
                  <strong>{copy.noIssues}</strong>
                </section>
              ) : null}
            </div>
          </section>

          <section className={styles.managementPanel}>
            <div className={styles.managementHeader}>
              <div>
                <p className={styles.panelEyebrow}>{copy.ratingSuggestions}</p>
                <h2>{copy.governance}</h2>
              </div>
              <span className={styles.countPill}>{ratingSuggestions.length}</span>
            </div>
            <div className={styles.queueToolbar}>
              <label>
                <span>{copy.status}</span>
                <select value={ratingSuggestionStatus} onChange={(event) => setRatingSuggestionStatus(event.target.value as RatingSuggestionStatusFilter)}>
                  <option value="pending">{copy.pendingProposals}</option>
                  <option value="applied">{copy.applySuggestion}</option>
                  <option value="rejected">{copy.rejectSuggestion}</option>
                  <option value="all">{copy.allStatuses}</option>
                </select>
              </label>
              <label>
                <span>{copy.priority}</span>
                <select value={ratingSuggestionPriority} onChange={(event) => setRatingSuggestionPriority(event.target.value as RatingSuggestionPriorityFilter)}>
                  <option value="all">{copy.allPriorities}</option>
                  <option value="urgent">urgent</option>
                  <option value="elevated">elevated</option>
                  <option value="normal">normal</option>
                </select>
              </label>
            </div>
            <div className={styles.bulkActionBar}>
              <span className={styles.countPill}>{copy.selectedSuggestions}: {selectedVisibleRatingSuggestionIds.length}</span>
              <button type="button" className={styles.detailActionButton} onClick={toggleVisibleRatingSuggestions} disabled={!pendingVisibleRatingSuggestions.length || knowledgeBusy}>
                <SquareCheckBig size={14} />
                <span>{copy.selectAllVisibleSuggestions}</span>
              </button>
              <button type="button" className={styles.detailActionButton} onClick={() => setSelectedRatingSuggestionIds([])} disabled={!selectedVisibleRatingSuggestionIds.length || knowledgeBusy}>
                <Square size={14} />
                <span>{copy.clearSuggestionSelection}</span>
              </button>
              <button
                type="button"
                className={styles.detailActionButton}
                disabled={!activeKnowledgeBase?.permissions.canRate || !selectedVisibleRatingSuggestionIds.length || knowledgeBusy}
                onClick={() => reviewSelectedRatingSuggestions("applied")}
              >
                <CheckCircle2 size={14} />
                <span>{copy.bulkApplySuggestions}</span>
              </button>
              <button
                type="button"
                className={styles.detailActionButton}
                disabled={!activeKnowledgeBase?.permissions.canRate || !selectedVisibleRatingSuggestionIds.length || knowledgeBusy}
                onClick={() => reviewSelectedRatingSuggestions("rejected")}
              >
                <XCircle size={14} />
                <span>{copy.bulkRejectSuggestions}</span>
              </button>
            </div>
            <div className={styles.knowledgeProposalList}>
              {ratingSuggestions.map((suggestion) => (
                <section key={suggestion.suggestionId} className={styles.knowledgeRow}>
                  <label className={styles.inlineCheck}>
                    <input
                      type="checkbox"
                      aria-label={copy.selectSuggestion}
                      checked={selectedRatingSuggestionIds.includes(suggestion.suggestionId)}
                      disabled={suggestion.status !== "pending" || knowledgeBusy}
                      onChange={() => toggleRatingSuggestionSelection(suggestion.suggestionId)}
                    />
                    <span>{copy.selectSuggestion}</span>
                  </label>
                  <strong>{suggestion.importanceLevel} · {suggestion.reviewPriority}</strong>
                  <span>{suggestion.markingReason || suggestion.suggestionId}</span>
                  <small>{suggestion.status} · {suggestion.targetType} · {suggestion.knowledgeItemId || suggestion.proposalId} · {copy.confidence}: {suggestion.confidence}</small>
                  <button
                    type="button"
                    className={styles.detailActionButton}
                    disabled={!activeKnowledgeBase?.permissions.canRate || suggestion.status !== "pending" || knowledgeBusy}
                    onClick={() => reviewRatingSuggestion(suggestion.suggestionId, "applied")}
                  >
                    <CheckCircle2 size={14} />
                    <span>{copy.applySuggestion}</span>
                  </button>
                  <button
                    type="button"
                    className={styles.detailActionButton}
                    disabled={!activeKnowledgeBase?.permissions.canRate || suggestion.status !== "pending" || knowledgeBusy}
                    onClick={() => reviewRatingSuggestion(suggestion.suggestionId, "rejected")}
                  >
                    <XCircle size={14} />
                    <span>{copy.rejectSuggestion}</span>
                  </button>
                </section>
              ))}
              {!ratingSuggestionsQuery.isPending && !ratingSuggestions.length ? (
                <section className={styles.emptyDetail}>
                  <CheckCircle2 size={20} />
                  <strong>{copy.noIssues}</strong>
                </section>
              ) : null}
            </div>
          </section>
          </>
          ) : null}

          {activeKnowledgeWorkspaceMode === "permissions" ? (
          <section className={styles.managementPanel}>
            <div className={styles.managementHeader}>
              <div>
                <p className={styles.panelEyebrow}>{copy.permissionAudit}</p>
                <h2>{copy.teamKnowledgeDomain}</h2>
              </div>
              <span className={styles.countPill}>{permissionAudit?.summary.knowledgeBaseCount ?? 0}</span>
            </div>
            <div className={styles.permissionMatrix}>
              {(permissionAudit?.knowledgeBases ?? []).map((row) => (
                <section key={`perm:${row.knowledgeBaseId}`} className={styles.permissionRow}>
                  <strong>{row.knowledgeBaseName}</strong>
                  <span>{row.teamName} · {row.teamRole || "-"}</span>
                  {[
                    { label: copy.readable, permission: row.permissions.read },
                    { label: copy.proposable, permission: row.permissions.propose },
                    { label: copy.reviewable, permission: row.permissions.review },
                    { label: copy.rateable, permission: row.permissions.rate },
                  ].map(({ label, permission }) => {
                    const normalizedPermission = normalizeKnowledgePermission(permission);
                    return (
                      <small key={label} className={normalizedPermission.allowed ? styles.statusPill : styles.statusPillMuted}>
                        {label}: {normalizedPermission.allowed ? copy.yes : normalizedPermission.reason}
                      </small>
                    );
                  })}
                </section>
              ))}
            </div>
          </section>
          ) : null}
        </main>

        <aside className={styles.detailPanel}>
          <div className={styles.detailHeader}>
            <p className={styles.panelEyebrow}>{copy.formalKnowledge}</p>
            <h2>{activeKnowledgeBase?.name ?? copy.selectedKnowledgeDetail}</h2>
          </div>
          <section className={styles.managementPanel}>
            <div className={styles.managementHeader}>
              <div>
                <p className={styles.panelEyebrow}>{copy.sourceChain}</p>
                <h2>{copy.traceability}</h2>
              </div>
            </div>
            <label>
              <span>{copy.traceability}</span>
              <input value={traceTargetId} onChange={(event) => setTraceTargetId(event.target.value)} placeholder="source / proposal / item / rating id" />
            </label>
            {knowledgeTraceQuery.data ? (
              <div className={styles.metaGrid}>
                <span>{copy.sourceArtifacts}: {knowledgeTraceQuery.data.summary.sourceArtifacts ?? 0}</span>
                <span>{copy.pendingProposals}: {knowledgeTraceQuery.data.summary.proposals ?? 0}</span>
                <span>{copy.formalKnowledge}: {knowledgeTraceQuery.data.summary.items ?? 0}</span>
                <span>{copy.ratingSuggestions}: {knowledgeTraceQuery.data.summary.ratingSuggestions ?? 0}</span>
              </div>
            ) : null}
          </section>
          {knowledgeItemsQuery.isPending ? <div className={styles.emptyState}>{copy.loading}</div> : null}
          <div className={styles.knowledgeItems}>
            {knowledgeItems.map((item) => (
              <section key={item.knowledgeItemId} className={styles.knowledgeItemCard}>
                <div className={styles.panelHeader}>
                  <div>
                    <strong>{item.title}</strong>
                    <p>{item.summary || item.content}</p>
                  </div>
                  <span className={styles.statusPill}>{item.importanceLevel}</span>
                </div>
                <div className={styles.metaGrid}>
                  <span>{copy.confidence}: {item.confidence}</span>
                  <span>{copy.stability}: {item.stability}</span>
                  <span>{copy.reviewPriority}: {item.reviewPriority}</span>
                  <span>batch: {item.batchId}</span>
                </div>
                <label>
                  <span>{copy.markingReason}</span>
                  <input value={ratingDraft.markingReason} onChange={(event) => setRatingDraft({ ...ratingDraft, markingReason: event.target.value })} />
                </label>
                <div className={styles.ratingControls}>
                  <select value={ratingDraft.importanceLevel} onChange={(event) => setRatingDraft({ ...ratingDraft, importanceLevel: event.target.value })}>
                    {["low", "medium", "high", "critical"].map((value) => <option key={value} value={value}>{value}</option>)}
                  </select>
                  <input value={ratingDraft.confidence} onChange={(event) => setRatingDraft({ ...ratingDraft, confidence: event.target.value })} aria-label={copy.confidence} />
                  <select value={ratingDraft.stability} onChange={(event) => setRatingDraft({ ...ratingDraft, stability: event.target.value })}>
                    {["temporary", "evolving", "stable", "deprecated"].map((value) => <option key={value} value={value}>{value}</option>)}
                  </select>
                  <button
                    type="button"
                    className={styles.detailActionButton}
                    onClick={() => updateKnowledgeRating(item)}
                    disabled={!activeKnowledgeBase?.permissions.canRate || knowledgeBusy}
                  >
                    <CheckCircle2 size={14} />
                    <span>{copy.submitRatingSuggestion}</span>
                  </button>
                </div>
              </section>
            ))}
            {!knowledgeItemsQuery.isPending && !knowledgeItems.length ? (
              <section className={styles.emptyDetail}>
                <FileText size={22} />
                <strong>{copy.noMatches}</strong>
              </section>
            ) : null}
          </div>
        </aside>
      </div>
    </>
  );

  const renderCleanupView = () => {
    const report = cleanupExecution ?? cleanupPreview;
    const totals = report?.totals;
    const canExecute = selectedCleanupTargets.length > 0 && cleanupConfirmationText.trim() === (report?.confirmationPhrase || "硬删除记忆");
    return (
      <>
        <div className={styles.summaryGrid}>
          <section className={styles.summaryCard}>
            <span>{copy.cleanupSelectedTargets}</span>
            <strong>{selectedCleanupTargets.length}</strong>
            <small>{cleanupTargetOptions.length}</small>
          </section>
          <section className={styles.summaryCard}>
            <span>{copy.cleanupRows}</span>
            <strong>{totals?.rowCount ?? 0}</strong>
            <small>{copy.cleanupHardDelete}</small>
          </section>
          <section className={styles.summaryCard}>
            <span>{copy.cleanupFiles}</span>
            <strong>{totals?.fileCount ?? 0}</strong>
            <small>{formatByteCount(totals?.byteCount ?? 0)}</small>
          </section>
          <section className={styles.summaryCard}>
            <span>{copy.cleanupVectorRecords}</span>
            <strong>{totals?.vectorRecordCount ?? 0}</strong>
            <small>RAG</small>
          </section>
        </div>

        <section className={styles.cleanupWarning} title={copy.cleanupNoBackup}>
          <TriangleAlert size={16} />
          <strong>{copy.cleanupHardDelete}</strong>
        </section>

        <div className={styles.cleanupWorkspace}>
          <section className={styles.cleanupTargetPanel}>
            <div className={styles.panelHeader}>
              <div>
                <h2 title={copy.cleanupSelectTargets}>{copy.cleanupTargets}</h2>
              </div>
              <span className={styles.countPill}>{selectedCleanupTargets.length}</span>
            </div>
            {knowledgeDashboardSnapshotQuery.isPending || agentsQuery.isPending ? <div className={styles.emptyState}>{copy.loading}</div> : null}
            {!knowledgeDashboardSnapshotQuery.isPending && !agentsQuery.isPending && !cleanupTargetOptions.length ? (
              <div className={styles.emptyState}>{copy.cleanupNoTargets}</div>
            ) : null}
            <div className={styles.cleanupTargetList}>
              {cleanupTargetOptions.map((option) => {
                const selected = selectedCleanupTargetKeys.includes(option.key);
                return (
                  <label key={option.key} className={styles.cleanupTargetRow} data-selected={selected} data-risk={option.risk}>
                    <input
                      type="checkbox"
                      checked={selected}
                      onChange={() => toggleCleanupTarget(option.key)}
                      aria-label={option.label}
                    />
                    <span>
                      <strong>{option.label}</strong>
                      <small>{option.detail}</small>
                    </span>
                  </label>
                );
              })}
            </div>
          </section>

          <section className={styles.cleanupPreviewPanel}>
            <div className={styles.panelHeader}>
              <div>
                <h2 title={copy.cleanupCentralSourceBoundary}>{copy.cleanupPreview}</h2>
              </div>
              <button
                type="button"
                className={styles.inlineActionButton}
                onClick={previewCleanup}
                disabled={!selectedCleanupTargets.length || cleanupPreviewMutation.isPending}
              >
                <Eye size={15} />
                {copy.cleanupPreview}
              </button>
            </div>
            {report ? (
              <>
                <div className={styles.cleanupStats}>
                  <span>{copy.cleanupRows}: {report.totals.rowCount}</span>
                  <span>{copy.cleanupFiles}: {report.totals.fileCount}</span>
                  <span>{copy.cleanupBytes}: {formatByteCount(report.totals.byteCount)}</span>
                  <span>{copy.cleanupVectorRecords}: {report.totals.vectorRecordCount}</span>
                </div>
                <div className={styles.cleanupPreviewList}>
                  {report.targets.map((target) => (
                    <article key={target.targetKey} className={styles.cleanupPreviewItem}>
                      <header>
                        <strong>{target.label}</strong>
                        <span>{target.status}</span>
                      </header>
                      <div className={styles.cleanupPreviewCounts}>
                        <span>{copy.cleanupRows}: {target.counts.rowCount}</span>
                        <span>{copy.cleanupFiles}: {target.counts.fileCount}</span>
                        <span>{copy.cleanupVectorRecords}: {target.counts.vectorRecordCount}</span>
                      </div>
                      {target.warnings.map((warning) => (
                        <p key={warning} className={styles.cleanupInlineWarning}>{warning}</p>
                      ))}
                      <div className={styles.cleanupPathList}>
                        {target.paths.map((path) => (
                          <span key={`${target.targetKey}:${path.path}:${path.action}`}>
                            <small>{path.action}{path.status ? ` · ${path.status}` : ""}</small>
                            <strong>{path.path}</strong>
                            <em>{path.rowCount ? `${path.rowCount} ${copy.cleanupRows}` : path.fileCount ? `${path.fileCount} ${copy.cleanupFiles}` : path.exists ? path.kind : copy.missing}</em>
                          </span>
                        ))}
                      </div>
                    </article>
                  ))}
                </div>
              </>
            ) : (
              <div className={styles.emptyState}>{copy.cleanupSelectTargets}</div>
            )}
          </section>

          <section className={styles.cleanupExecutePanel}>
            <div className={styles.panelHeader}>
              <div>
                <h2>{copy.cleanupExecute}</h2>
                <p>{copy.cleanupConfirmPhrase}: {report?.confirmationPhrase ?? "硬删除记忆"}</p>
              </div>
              <Trash2 size={18} />
            </div>
            <label className={styles.cleanupConfirmField}>
              <span>{copy.cleanupConfirmPhrase}</span>
              <input
                value={cleanupConfirmationText}
                placeholder={copy.cleanupConfirmPlaceholder}
                onChange={(event) => setCleanupConfirmationText(event.target.value)}
              />
            </label>
            <button
              type="button"
              className={styles.cleanupExecuteButton}
              onClick={executeCleanup}
              disabled={!canExecute || cleanupExecuteMutation.isPending}
            >
              <Trash2 size={15} />
              {copy.cleanupExecute}
            </button>
            {cleanupFeedback.tone !== "idle" ? (
              <p className={styles.cleanupFeedback} data-tone={cleanupFeedback.tone}>{cleanupFeedback.text}</p>
            ) : null}
            {cleanupExecution ? (
              <div className={styles.cleanupExecutionSummary}>
                <CheckCircle2 size={18} />
                <span>{copy.cleanupExecuteDone}</span>
                <strong>{cleanupExecution.totals.targetCount}</strong>
              </div>
            ) : null}
          </section>
        </div>
      </>
    );
  };

  const renderGraphView = () => (
    <>
      <div className={styles.summaryGrid}>
        <section className={styles.summaryCard}>
          <span>{copy.graphVisibleNodes}</span>
          <strong>{filteredGraphNodes.length}</strong>
          <small>{copy.graphNodes}: {graphPayload?.summary.nodeCount ?? 0}</small>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.graphVisibleEdges}</span>
          <strong>{filteredGraphEdges.length}</strong>
          <small>{copy.graphEdges}: {graphPayload?.summary.edgeCount ?? 0}</small>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.graphGpu}</span>
          <strong>{graphPayload?.operatingBoundary.gpuPreferred ? copy.yes : copy.no}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.graphWorker}</span>
          <strong>{graphPayload?.operatingBoundary.layoutWorker ? copy.yes : copy.no}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.graphReadOnly}</span>
          <strong>{graphPayload?.operatingBoundary.readOnly ? copy.yes : copy.no}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.graphAcl}</span>
          <strong>{graphPayload?.operatingBoundary.honorsKnowledgeAcl ? copy.yes : copy.no}</strong>
        </section>
      </div>

      <div className={`${styles.workspace} ${styles.graphWorkspace}`}>
        <aside className={styles.sourcePanel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{copy.knowledgeGraph}</p>
              <h2>{copy.filters}</h2>
            </div>
            <span className={styles.countPill}>{filteredGraphNodes.length}</span>
          </div>
          <label className={styles.searchBox}>
            <Search size={15} />
            <input
              value={graphSearchText}
              onChange={(event) => setGraphSearchText(event.target.value)}
              placeholder={copy.graphSearchPlaceholder}
            />
          </label>
          <section className={styles.managementPanel}>
            <div className={styles.managementHeader}>
              <div>
                <p className={styles.panelEyebrow}>{copy.graphNodeTypes}</p>
                <h2>{copy.graphNodes}</h2>
              </div>
            </div>
            <div className={styles.graphTypeList}>
              {graphTypeEntries.map(([type, count]) => (
                <button
                  key={type}
                  type="button"
                  data-active={activeGraphNodeType === type ? "true" : "false"}
                  data-node-type={type}
                  onClick={() => setActiveGraphNodeType((current) => (current === type ? "" : type))}
                >
                  <strong>{type}</strong>
                  <small>{count}</small>
                </button>
              ))}
            </div>
            {activeGraphNodeType || graphSearchText ? (
              <button
                type="button"
                className={styles.graphClearFocusButton}
                onClick={() => {
                  setActiveGraphNodeType("");
                  setGraphSearchText("");
                }}
              >
                <XCircle size={14} />
                {copy.graphClearFocus}
              </button>
            ) : null}
          </section>
        </aside>

        <main className={styles.graphCanvasPanel}>
          <div className={styles.graphCanvasToolbar}>
            <div>
              <p className={styles.panelEyebrow}>{copy.knowledgeGraph}</p>
              <strong>Three.js / WebGL / Worker</strong>
            </div>
            <span className={styles.graphInteractionHint} title={copy.graphInteractionHint}>
              {copy.graphReadOnly} · {copy.graphAcl}
            </span>
          </div>
          <Suspense fallback={<div className={styles.graphCanvasFallback}><strong>{copy.loading}</strong></div>}>
            <MemoryGraphCanvas
              nodes={filteredGraphNodes}
              edges={filteredGraphEdges}
              selectedNodeId={selectedGraphNode?.id ?? ""}
              onSelectNode={setSelectedGraphNodeId}
              fallbackText={copy.graphCanvasFallback}
            />
          </Suspense>
          <div className={styles.graphNodeList}>
            {filteredGraphNodes.slice(0, 80).map((node) => (
              <button
                key={node.id}
                type="button"
                className={selectedGraphNode?.id === node.id ? `${styles.itemButton} ${styles.itemButtonActive}` : styles.itemButton}
                data-node-type={node.type}
                data-agent-category={String(node.visual?.agentCategory || node.metadata?.agentCategory || "")}
                onClick={() => setSelectedGraphNodeId(node.id)}
              >
                <span className={styles.graphNodeTypeMark}>{GRAPH_NODE_TYPE_LABELS[node.type] ?? node.type.slice(0, 10)}</span>
                <strong>{node.label}</strong>
                <small>{node.status || "-"}</small>
              </button>
            ))}
          </div>
        </main>

        <aside className={styles.detailPanel}>
          <div className={styles.detailHeader}>
            <p className={styles.panelEyebrow}>{copy.graphSelectedNode}</p>
            <h2>{selectedGraphNode?.label ?? copy.graphNoSelection}</h2>
          </div>
          {selectedGraphNode ? (
            <>
              <section className={styles.selectedConfigSummary}>
                <strong>{selectedGraphNode.type}</strong>
                <p>{selectedGraphNode.summary || selectedGraphNode.id}</p>
              </section>
              <section className={styles.graphResponsibilityPanel}>
                <span>{copy.graphResponsibilityQuestion}</span>
                <strong>{selectedGraphNode.responsibilityQuestion || "-"}</strong>
              </section>
              <div className={styles.detailMeta}>
                <span>{copy.status}: {selectedGraphNode.status || "-"}</span>
                <span>{copy.sourceOrigin}: {selectedGraphNode.id}</span>
                <span>{copy.generatedAt}: {formatTimestamp(selectedGraphNode.createdAt || selectedGraphNode.updatedAt, lang)}</span>
              </div>
              <section className={styles.graphRelationPanel}>
                <div className={styles.graphRelationHeader}>
                  <p className={styles.panelEyebrow}>{copy.graphDirectChildren}</p>
                  <strong>{selectedGraphChildren.length}</strong>
                </div>
                {!selectedGraphChildren.length ? (
                  <p className={styles.graphRelationEmpty}>{copy.graphNoChildren}</p>
                ) : (
                  <div className={styles.graphRelationGroup}>
                    {selectedGraphChildren.map((child) => (
                      <button
                        key={child.id}
                        type="button"
                        data-node-type={child.type}
                        data-agent-category={String(child.visual?.agentCategory || child.metadata?.agentCategory || "")}
                        onClick={() => selectGraphNode(child.id)}
                      >
                        <small>{GRAPH_NODE_TYPE_LABELS[child.type] ?? child.type}</small>
                        <strong>{child.label}</strong>
                      </button>
                    ))}
                  </div>
                )}
              </section>
              <section className={styles.graphKnowledgePanel}>
                <div className={styles.graphRelationHeader}>
                  <p className={styles.panelEyebrow}>{copy.graphNodeKnowledge}</p>
                  <strong>{selectedGraphDetailItems.length}</strong>
                </div>
                {memoryKnowledgeGraphNodeDetailQuery.isFetching ? (
                  <p className={styles.graphRelationEmpty}>{copy.graphKnowledgeLoading}</p>
                ) : null}
                {!selectedGraphDetailItems.length && !memoryKnowledgeGraphNodeDetailQuery.isFetching ? (
                  <p className={styles.graphRelationEmpty}>{copy.graphNoKnowledge}</p>
                ) : (
                  <div className={styles.graphKnowledgeList}>
                    {selectedGraphDetailItems.map((item) => (
                      <article key={`${item.type}:${item.id}`} className={styles.graphKnowledgeItem}>
                        <div>
                          <strong>{item.title}</strong>
                          <small>{item.knowledgeBaseName || item.type}</small>
                        </div>
                        {item.summary ? <p>{item.summary}</p> : null}
                        {item.content ? (
                          <pre className={styles.graphKnowledgeContent}>{item.content}</pre>
                        ) : null}
                        {item.contentTruncated ? <em>{copy.graphKnowledgeTruncated}</em> : null}
                        <span>{item.status || "-"} · {formatTimestamp(String(item.updatedAt || item.createdAt || ""), lang)}</span>
                      </article>
                    ))}
                  </div>
                )}
              </section>
              <section className={styles.graphRelationPanel}>
                <div className={styles.graphRelationHeader}>
                  <p className={styles.panelEyebrow}>{copy.graphRelations}</p>
                  <strong>{selectedGraphRelations.incoming.length + selectedGraphRelations.outgoing.length}</strong>
                </div>
                {!selectedGraphRelations.incoming.length && !selectedGraphRelations.outgoing.length ? (
                  <p className={styles.graphRelationEmpty}>{copy.graphNoRelations}</p>
                ) : (
                  <>
                    <div className={styles.graphRelationGroup}>
                      <span>{copy.graphIncoming}</span>
                      {selectedGraphRelations.incoming.map((relation) => (
                        <button
                          key={relation.edge.id}
                          type="button"
                          data-node-type={relation.neighbor.type}
                          data-agent-category={String(relation.neighbor.visual?.agentCategory || relation.neighbor.metadata?.agentCategory || "")}
                          onClick={() => selectGraphNode(relation.neighbor.id)}
                        >
                          <small>{relation.edge.label || relation.edge.type}</small>
                          <strong>{relation.neighbor.label}</strong>
                        </button>
                      ))}
                    </div>
                    <div className={styles.graphRelationGroup}>
                      <span>{copy.graphOutgoing}</span>
                      {selectedGraphRelations.outgoing.map((relation) => (
                        <button
                          key={relation.edge.id}
                          type="button"
                          data-node-type={relation.neighbor.type}
                          data-agent-category={String(relation.neighbor.visual?.agentCategory || relation.neighbor.metadata?.agentCategory || "")}
                          onClick={() => selectGraphNode(relation.neighbor.id)}
                        >
                          <small>{relation.edge.label || relation.edge.type}</small>
                          <strong>{relation.neighbor.label}</strong>
                        </button>
                      ))}
                    </div>
                  </>
                )}
              </section>
              <details className={styles.rawPanel}>
                <summary>
                  <FileText size={15} />
                  <span>metadata</span>
                </summary>
                <pre>{JSON.stringify(selectedGraphNode.metadata ?? {}, null, 2)}</pre>
              </details>
            </>
          ) : (
            <section className={styles.emptyDetail}>
              <Network size={22} />
              <strong>{copy.graphNoSelection}</strong>
            </section>
          )}
        </aside>
      </div>
    </>
  );

  const viewStackClassName =
    forcedView === "graph"
      ? `${styles.viewStack} ${styles.graphViewStack}`
      : forcedView === "knowledge"
        ? `${styles.viewStack} ${styles.knowledgeViewStack}`
        : styles.viewStack;

  return (
    <section className={styles.route}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>{copy.eyebrow}</p>
          <h1 className={styles.title} title={memoryViewSubtitle(copy, forcedView)}>
            {memoryViewLabel(copy, forcedView)}
          </h1>
        </div>
        <button type="button" className={styles.refreshButton} onClick={refresh}>
          <RefreshCw size={16} />
          {copy.refresh}
        </button>
      </header>

      <div className={styles.controlStrip}>
        {renderSubnav()}
      </div>

      <div className={viewStackClassName}>
        {forcedView === "overview"
          ? renderOverviewView()
          : forcedView === "effective"
            ? renderEffectiveView()
            : forcedView === "manage"
              ? renderManageView()
              : forcedView === "knowledge"
                ? renderKnowledgeView()
                : forcedView === "graph"
                  ? renderGraphView()
                  : forcedView === "cleanup"
                    ? renderCleanupView()
                    : renderSourcesView()}
      </div>
    </section>
  );
}
