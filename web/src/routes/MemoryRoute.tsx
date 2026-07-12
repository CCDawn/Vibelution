import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Brain,
  CheckCircle2,
  RefreshCw,
  TriangleAlert,
  Undo2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, NavLink, useSearchParams } from "react-router-dom";

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
import { VButton, VRouteHeader } from "../components/vui";
import { useShellI18n } from "../i18n/useShellI18n";
import { safeAgentCenterReturnToPath } from "./agentCenterRoutes";
import { MemoryAgentMemoryPanel } from "./MemoryAgentMemoryPanel";
import { MemoryCleanupPanel } from "./MemoryCleanupPanel";
import { MemoryDetailPanel } from "./MemoryDetailPanel";
import { MemoryEffectivePanel } from "./MemoryEffectivePanel";
import { MemoryKnowledgeBaseSidebar } from "./MemoryKnowledgeBaseSidebar";
import { MemoryKnowledgeDetailPanel } from "./MemoryKnowledgeDetailPanel";
import { MemoryKnowledgeGovernancePanel } from "./MemoryKnowledgeGovernancePanel";
import { MemoryGraphViewPanel, type MemoryGraphRelation } from "./MemoryGraphViewPanel";
import { MemoryKnowledgeModeTabs } from "./MemoryKnowledgeModeTabs";
import { MemoryKnowledgePermissionsPanel } from "./MemoryKnowledgePermissionsPanel";
import { MemoryKnowledgePipelinePanel } from "./MemoryKnowledgePipelinePanel";
import { MemoryKnowledgeReviewPanel } from "./MemoryKnowledgeReviewPanel";
import { MemoryKnowledgeSearchPanel, type MemoryKnowledgeSearchDraft } from "./MemoryKnowledgeSearchPanel";
import {
  MemoryKnowledgeSourceGovernancePanel,
  type MemoryKnowledgeOwnerSourceDraft,
  type MemoryKnowledgeSourceInboxStatusFilter,
  type MemoryKnowledgeSourceOwnerType,
} from "./MemoryKnowledgeSourceGovernancePanel";
import { MemoryKnowledgeStewardPanel } from "./MemoryKnowledgeStewardPanel";
import { MemoryKnowledgeUsageContractPanel } from "./MemoryKnowledgeUsageContractPanel";
import { MemoryManagementEditor, type MemoryManagementEditorDraft } from "./MemoryManagementEditor";
import { MemoryManagePanel } from "./MemoryManagePanel";
import { MemoryMatrixPanel } from "./MemoryMatrixPanel";
import { MemoryItemListPanel } from "./MemoryItemListPanel";
import { MemoryOverviewPanel } from "./MemoryOverviewPanel";
import { MemoryProjectMemoryQueuePanel } from "./MemoryProjectMemoryQueuePanel";
import { MemoryReviewQueuePanel } from "./MemoryReviewQueuePanel";
import { MemorySelectedConfigPanel } from "./MemorySelectedConfigPanel";
import { MemorySourceAndItemPanels } from "./MemorySourceAndItemPanels";
import { MemoryUserContentPanel } from "./MemoryUserContentPanel";
import { MemoryWarningStrip } from "./MemoryWarningStrip";
import styles from "./MemoryRoute.styles";

type Copy = {
  eyebrow: string;
  title: string;
  subtitle: string;
  returnToAgents: string;
  returnToSource: string;
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
  agentMemoryView: string;
  manageView: string;
  sourcesView: string;
  knowledgeView: string;
  overviewSubtitle: string;
  effectiveSubtitle: string;
  agentMemorySubtitle: string;
  manageSubtitle: string;
  sourcesSubtitle: string;
  knowledgeSubtitle: string;
  agentMemoryAgents: string;
  agentMemoryPrivateFiles: string;
  agentMemoryFormalKnowledge: string;
  agentMemoryPrivateRoot: string;
  agentMemorySelectedAgent: string;
  agentMemorySelectedFile: string;
  agentMemoryNoAgents: string;
  agentMemoryNoPrivateMemory: string;
  agentMemoryNoFileSelected: string;
  agentMemoryFormalBases: string;
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
  cleanupSqliteCompact: string;
  cleanupEvaluationArtifacts: string;
  cleanupSessionArtifacts: string;
  cleanupLegacyLogInfo: string;
  cleanupRuntimeSceneLogs: string;
  cleanupTeamArchiveArtifacts: string;
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
export type MemoryRouteView = "overview" | "effective" | "agents" | "manage" | "sources" | "knowledge" | "graph" | "cleanup";
type MemoryChannel = "conversation" | "research" | "self_evolution" | "supervised_evolution" | "explicit_read";
type ChannelFilter = MemoryChannel | "";
type AgentMemoryKnowledgeSummary = {
  knowledgeBaseCount: number;
  itemCount: number;
  sourceArtifactCount: number;
  pendingProposalCount: number;
  knowledgeBases: Array<{
    knowledgeBaseId: string;
    scopedKnowledgeBaseId: string;
    name: string;
    description: string;
    stats: Record<string, number>;
  }>;
  error?: string;
};
type AgentMemoryFileItem = MemoryItem & {
  agentId: string;
  relativePath: string;
  privateMemoryRoot: string;
  sizeBytes: number;
  contentDeferred: boolean;
  contentLength: number;
};
type AgentMemoryInventoryAgent = {
  agentId: string;
  agentCode: string;
  displayName: string;
  status: string;
  primaryMode: string;
  roleKey: string;
  promptTemplateId: string;
  workspacePath: string;
  privateMemoryRoot: string;
  hasPrivateMemory: boolean;
  fileCount: number;
  byteCount: number;
  latestUpdatedAt: string;
  createdAt: string;
  updatedAt: string;
  knowledgeSummary: AgentMemoryKnowledgeSummary;
  items: AgentMemoryFileItem[];
};
type AgentMemoryInventoryPayload = {
  schemaVersion: number;
  generatedAt: string;
  projectRoot: string;
  selectedAgentId: string;
  selectedAgent: AgentMemoryInventoryAgent | null;
  summary: {
    agentCount: number;
    agentWithPrivateMemoryCount: number;
    privateFileCount: number;
    privateByteCount: number;
    formalKnowledgeBaseCount: number;
    formalKnowledgeItemCount: number;
    warnings: string[];
  };
  agents: AgentMemoryInventoryAgent[];
};
type CleanupTargetOption = {
  key: string;
  label: string;
  detail: string;
  target: MemoryCleanupTargetRequest;
  risk: "high" | "critical";
};
type MemoryPair = {
  section: MemorySection;
  item: MemoryItem;
};
type BulkMemoryAction = "disable" | "restore";
type MemoryProposalStatusFilter = "pending" | "";
type MemoryProposalResolveStatus = "applied" | "rejected" | "conflict" | "superseded";
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
type RatingSuggestionStatusFilter = "pending" | "applied" | "rejected" | "all";
type RatingSuggestionPriorityFilter = "all" | "urgent" | "elevated" | "normal";
type KnowledgeWorkspaceMode = "sources" | "search" | "review" | "governance" | "permissions";

const FILTER_MODES: FilterMode[] = ["all", "prompt", "visible", "manual", "missing"];
const MANAGE_FILTER_MODES: ManageFilterMode[] = ["all", "prompt", "editable", "changed", "missing"];
const MEMORY_CHANNELS: MemoryChannel[] = ["conversation", "research", "self_evolution", "supervised_evolution", "explicit_read"];

const COPY: Record<"zh" | "en", Copy> = {
  zh: {
    eyebrow: "Memory Library",
    title: "记忆库",
    subtitle: "统一治理 Agent 私有记忆、团队知识库、来源证据和生效边界。",
    returnToAgents: "返回 Agent 配置",
    returnToSource: "返回来源页",
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
    agentMemoryView: "Agent 记忆",
    manageView: "来源管理",
    sourcesView: "来源审计",
    knowledgeView: "团队知识库",
    overviewSubtitle: "先看记忆健康、运行影响和需要检查的内容；复杂证据放到子页里。",
    effectiveSubtitle: "按对话、自进化、监督进化和显式读取说明哪些记忆会被 agent 感知。",
    agentMemorySubtitle: "逐个查看 Agent 私有 workspace 记忆文件与正式私有知识库，点击文件读取内容。",
    manageSubtitle: "集中管理可覆盖、可禁用和用户手动新增的来源，不代表单个 Agent 的私有记忆。",
    sourcesSubtitle: "保留完整来源、路径、接口、原文和复制动作，供专业审查使用。",
    knowledgeSubtitle: "管理团队共享知识库、来源登记、精炼提案、审核落盘和重要程度标记。",
    agentMemoryAgents: "Agent 列表",
    agentMemoryPrivateFiles: "私有文件",
    agentMemoryFormalKnowledge: "正式知识",
    agentMemoryPrivateRoot: "私有目录",
    agentMemorySelectedAgent: "选中 Agent",
    agentMemorySelectedFile: "选中文件",
    agentMemoryNoAgents: "暂无 Agent",
    agentMemoryNoPrivateMemory: "该 Agent 暂无私有记忆文件",
    agentMemoryNoFileSelected: "选择一个私有记忆文件查看内容",
    agentMemoryFormalBases: "正式知识库",
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
    cleanupSqliteCompact: "SQLite 数据库压缩",
    cleanupEvaluationArtifacts: "评测候选与队列",
    cleanupSessionArtifacts: "历史会话与附件",
    cleanupLegacyLogInfo: "旧 log_info 日志",
    cleanupRuntimeSceneLogs: "运行现场日志",
    cleanupTeamArchiveArtifacts: "团队归档证据",
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
    returnToAgents: "Return to Agent config",
    returnToSource: "Return to source page",
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
    agentMemoryView: "Agent memory",
    manageView: "Source management",
    sourcesView: "Source audit",
    knowledgeView: "Team knowledge",
    overviewSubtitle: "Start with memory health, runtime impact, and items that need review. Detailed evidence stays in subpages.",
    effectiveSubtitle: "Shows how conversation, self-evolution, supervised evolution, and explicit-read memory can be perceived.",
    agentMemorySubtitle: "Inspect each Agent private workspace memory file and formal private knowledge base, then open files to read their content.",
    manageSubtitle: "Manage overridable, disable-able, and user-created source records. This is not a single Agent private memory view.",
    sourcesSubtitle: "Keeps the full source, path, API, raw content, and copy actions for professional audit.",
    knowledgeSubtitle: "Manage team knowledge bases, source registration, refinement proposals, review, and importance marking.",
    agentMemoryAgents: "Agents",
    agentMemoryPrivateFiles: "Private files",
    agentMemoryFormalKnowledge: "Formal knowledge",
    agentMemoryPrivateRoot: "Private root",
    agentMemorySelectedAgent: "Selected Agent",
    agentMemorySelectedFile: "Selected file",
    agentMemoryNoAgents: "No Agents",
    agentMemoryNoPrivateMemory: "This Agent has no private memory files",
    agentMemoryNoFileSelected: "Select a private memory file to inspect its content",
    agentMemoryFormalBases: "Formal knowledge bases",
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
    knowledgeSteward: "Knowledge Base Admin",
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
    cleanupSqliteCompact: "SQLite database compact",
    cleanupEvaluationArtifacts: "Evaluation candidates and queues",
    cleanupSessionArtifacts: "Historical sessions and artifacts",
    cleanupLegacyLogInfo: "Legacy log_info logs",
    cleanupRuntimeSceneLogs: "Runtime scene logs",
    cleanupTeamArchiveArtifacts: "Team archive evidence",
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

function newCreateDraft(): MemoryManagementEditorDraft {
  return {
    mode: "create",
    sectionId: "user-managed-memory",
    itemId: "",
    title: "",
    summary: "",
    content: "",
  };
}

function draftFromItem(section: MemorySection, item: MemoryItem): MemoryManagementEditorDraft {
  return {
    mode: "edit",
    sectionId: section.id,
    itemId: item.id,
    title: item.title,
    summary: item.summary,
    content: item.content,
  };
}

function newOwnerSourceDraft(): MemoryKnowledgeOwnerSourceDraft {
  return {
    sourceType: "manual_user_entry",
    sourceRef: "{}",
    sourceCreatedAt: "",
    capturedBy: "",
    evidenceRange: "{}",
    title: "",
    summary: "",
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

function newKnowledgeSearchDraft(): MemoryKnowledgeSearchDraft {
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
  { key: "agents", href: "/memory/agents" },
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
  if (view === "agents") {
    return copy.agentMemoryView;
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
  if (view === "agents") {
    return copy.agentMemorySubtitle;
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

function normalizeSourceOwnerType(value: string | undefined | null): MemoryKnowledgeSourceOwnerType {
  return value === "agent" ? "agent" : "team";
}

function knowledgeBaseOwnerId(base: TeamKnowledgeBase | null) {
  if (!base) {
    return "";
  }
  return String(base.ownerId || (base.ownerType === "agent" ? base.agentId : base.teamId) || "").trim();
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
  void queryClient.invalidateQueries({ queryKey: ["memory", "agents"] });
}

export function MemoryRoute({ forcedView = "overview" }: MemoryRouteProps) {
  const { lang } = useShellI18n();
  const copy = COPY[lang];
  const queryClient = useQueryClient();
  const pageVisible = usePageVisibility();
  const [searchParams, setSearchParams] = useSearchParams();
  const searchParamText = searchParams.toString();
  const returnToPath = useMemo(() => safeAgentCenterReturnToPath(searchParams.get("returnTo")), [searchParamText]);
  const returnToLabel = searchParams.get("returnLabel") === "agents" ? copy.returnToAgents : copy.returnToSource;
  const [activeSectionId, setActiveSectionId] = useState(() => searchParams.get("section") ?? "");
  const [activeItemId, setActiveItemId] = useState(() => searchParams.get("item") ?? "");
  const [activeFilter, setActiveFilter] = useState<FilterMode>(() => normalizeFilterMode(searchParams.get("filter")));
  const [activeManageFilter, setActiveManageFilter] = useState<ManageFilterMode>(() => normalizeManageFilterMode(searchParams.get("manage")));
  const [activeChannel, setActiveChannel] = useState<ChannelFilter>(() => normalizeChannelFilter(searchParams.get("channel")));
  const [searchText, setSearchText] = useState(() => searchParams.get("q") ?? "");
  const requestedKnowledgeActorAgentId = (searchParams.get("agentId") ?? "").trim();
  const requestedTeamId = (searchParams.get("teamId") ?? "").trim();
  const requestedKnowledgeBaseId = (searchParams.get("knowledgeBaseId") ?? "").trim();
  const requestedGraphNodeId = (searchParams.get("nodeId") ?? "").trim();
  const [copyFeedback, setCopyFeedback] = useState<{ tone: "idle" | "success" | "error"; text: string }>({
    tone: "idle",
    text: "",
  });
  const [editDraft, setEditDraft] = useState<MemoryManagementEditorDraft | null>(null);
  const [selectedMemoryKeys, setSelectedMemoryKeys] = useState<string[]>([]);
  const [mutationFeedback, setMutationFeedback] = useState<{ tone: "idle" | "success" | "error"; text: string }>({
    tone: "idle",
    text: "",
  });
  const [bulkActionPending, setBulkActionPending] = useState<BulkMemoryAction | null>(null);
  const [activeKnowledgeBaseId, setActiveKnowledgeBaseId] = useState("");
  const [activeKnowledgeWorkspaceMode, setActiveKnowledgeWorkspaceMode] = useState<KnowledgeWorkspaceMode>("sources");
  const [showOwnerSourceForm, setShowOwnerSourceForm] = useState(false);
  const [sourceOwnerType, setSourceOwnerType] = useState<MemoryKnowledgeSourceOwnerType>("team");
  const [sourceOwnerId, setSourceOwnerId] = useState("");
  const [sourceInboxStatus, setSourceInboxStatus] = useState<MemoryKnowledgeSourceInboxStatusFilter>("pending");
  const [ownerSourceDraft, setOwnerSourceDraft] = useState<MemoryKnowledgeOwnerSourceDraft>(() => newOwnerSourceDraft());
  const [sourceReviewNote, setSourceReviewNote] = useState("");
  const [duplicateCentralSourceId, setDuplicateCentralSourceId] = useState("");
  const [proposalDraft, setProposalDraft] = useState<ProposalDraft>(() => newProposalDraft());
  const [ratingDraft, setRatingDraft] = useState<RatingDraft>(() => newRatingDraft());
  const [knowledgeSearchDraft, setKnowledgeSearchDraft] = useState<MemoryKnowledgeSearchDraft>(() => newKnowledgeSearchDraft());
  const [ratingSuggestionStatus, setRatingSuggestionStatus] = useState<RatingSuggestionStatusFilter>("pending");
  const [ratingSuggestionPriority, setRatingSuggestionPriority] = useState<RatingSuggestionPriorityFilter>("all");
  const [selectedRatingSuggestionIds, setSelectedRatingSuggestionIds] = useState<string[]>([]);
  const [traceTargetId, setTraceTargetId] = useState("");
  const [selectedAgentMemoryItemId, setSelectedAgentMemoryItemId] = useState("");
  const [graphSearchText, setGraphSearchText] = useState("");
  const [activeGraphNodeType, setActiveGraphNodeType] = useState("");
  const [selectedGraphNodeId, setSelectedGraphNodeId] = useState(() => requestedGraphNodeId);
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
  const [memoryProposalStatusFilter, setMemoryProposalStatusFilter] = useState<MemoryProposalStatusFilter>("pending");
  const [memoryProposalResolutionNotes, setMemoryProposalResolutionNotes] = useState<Record<string, string>>({});

  const overviewQuery = useQuery({
    queryKey: queryKeys.memoryOverview(),
    queryFn: ({ signal }) => fetchJson<MemoryOverview>("/api/memory/overview?includeContent=false", { signal }),
    refetchInterval: resolvePollingInterval(pageVisible, 30_000),
    refetchIntervalInBackground: false,
  });
  const projectMemoryUpdatesQuery = useQuery({
    queryKey: queryKeys.agentProjectMemoryUpdates(memoryProposalStatusFilter, "", 100),
    queryFn: ({ signal }) => fetchJson<AgentProjectMemoryUpdateProposal[]>(agentProjectMemoryUpdatesEndpoint(memoryProposalStatusFilter, 100), { signal }),
    refetchInterval: resolvePollingInterval(pageVisible, 45_000),
    refetchIntervalInBackground: false,
    enabled: forcedView === "overview",
  });
  const memoryUsageContractQuery = useQuery({
    queryKey: queryKeys.memoryUsageContract(),
    queryFn: ({ signal }) => fetchJson<MemoryUsageContractPayload>("/api/memory/usage-contract", { signal }),
    refetchInterval: resolvePollingInterval(pageVisible, 60_000),
    refetchIntervalInBackground: false,
    enabled: forcedView === "knowledge",
  });

  const agentsQuery = useQuery({
    queryKey: queryKeys.agents(),
    queryFn: ({ signal }) => fetchJson<AgentInstance[]>("/api/agents?detail=summary", { signal }),
    enabled: forcedView === "agents" || forcedView === "knowledge" || forcedView === "graph" || forcedView === "cleanup",
    refetchInterval: resolvePollingInterval(pageVisible, 60_000),
    refetchIntervalInBackground: false,
  });

  const agentMemoryInventoryQuery = useQuery({
    queryKey: ["memory", "agents", "inventory"],
    queryFn: ({ signal }) => fetchJson<AgentMemoryInventoryPayload>("/api/memory/agents", { signal }),
    enabled: forcedView === "agents",
    refetchInterval: resolvePollingInterval(pageVisible, 45_000),
    refetchIntervalInBackground: false,
  });

  const knowledgeActorAgents = agentsQuery.data ?? [];
  const fallbackKnowledgeActorAgentId = requestedKnowledgeActorAgentId || knowledgeActorAgents.find((agent) => agent.status !== "archived")?.agentId || "";

  const agentMemoryInventoryAgents = agentMemoryInventoryQuery.data?.agents ?? [];
  const requestedAgentMemoryAgent = requestedKnowledgeActorAgentId
    ? agentMemoryInventoryAgents.find((agent) => agent.agentId === requestedKnowledgeActorAgentId) ?? null
    : null;
  const selectedAgentMemoryAgentId =
    requestedAgentMemoryAgent?.agentId
    || agentMemoryInventoryAgents.find((agent) => agent.hasPrivateMemory)?.agentId
    || agentMemoryInventoryAgents.find((agent) => agent.status !== "archived")?.agentId
    || agentMemoryInventoryAgents[0]?.agentId
    || "";
  const agentMemoryDetailQuery = useQuery({
    queryKey: ["memory", "agents", selectedAgentMemoryAgentId, "detail"],
    queryFn: () => fetchJson<AgentMemoryInventoryPayload>(
      `/api/memory/agents/${encodeURIComponent(selectedAgentMemoryAgentId)}?actorAgentId=${encodeURIComponent(selectedAgentMemoryAgentId)}`,
    ),
    enabled: forcedView === "agents" && Boolean(selectedAgentMemoryAgentId),
    refetchInterval: false,
  });

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
    queryKey: queryKeys.memoryKnowledgeGraph(fallbackKnowledgeActorAgentId, "officialResearchGraph", requestedTeamId),
    queryFn: () => {
      const params = appendAgentParam(new URLSearchParams({ include: "officialResearchGraph" }), fallbackKnowledgeActorAgentId);
      if (requestedTeamId) {
        params.set("teamId", requestedTeamId);
      }
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
    mutationFn: async (draft: MemoryManagementEditorDraft) => {
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
      void queryClient.invalidateQueries({ queryKey: queryKeys.memoryKnowledgeGraph(fallbackKnowledgeActorAgentId, "officialResearchGraph", requestedTeamId) });
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
  const selectedAgentMemoryListAgent = selectedAgentMemoryAgentId
    ? agentMemoryInventoryAgents.find((agent) => agent.agentId === selectedAgentMemoryAgentId) ?? null
    : null;
  const selectedAgentMemoryAgent = agentMemoryDetailQuery.data?.selectedAgent ?? selectedAgentMemoryListAgent;
  const selectedAgentMemoryItems = selectedAgentMemoryAgent?.items ?? [];
  const selectedAgentMemoryItem =
    selectedAgentMemoryItems.find((item) => item.id === selectedAgentMemoryItemId)
    ?? selectedAgentMemoryItems[0]
    ?? null;
  const knowledgeDashboardSnapshot = knowledgeDashboardSnapshotQuery.data;
  const knowledgeOverview = knowledgeDashboardSnapshot?.overview;
  const knowledgeSteward = knowledgeDashboardSnapshot?.steward;
  const knowledgeStewardRecommendations = knowledgeDashboardSnapshot?.recommendations.recommendations ?? [];
  const knowledgeStewardWorkbench = knowledgeDashboardSnapshot?.workbench;
  const knowledgeOperationsHealth = knowledgeDashboardSnapshot?.operationsHealth;
  const knowledgeGovernancePlan = knowledgeDashboardSnapshot?.governancePlan;
  const knowledgeBases = knowledgeOverview?.knowledgeBases ?? [];
  const requestedTeamKnowledgeBase =
    knowledgeBases.find((base) => {
      const requestId = knowledgeBaseRequestId(base);
      if (requestedKnowledgeBaseId && (
        requestId === requestedKnowledgeBaseId
        || base.knowledgeBaseId === requestedKnowledgeBaseId
        || base.scopedKnowledgeBaseId === requestedKnowledgeBaseId
      )) {
        return true;
      }
      if (!requestedTeamId) {
        return false;
      }
      const ownerId = knowledgeBaseOwnerId(base);
      return String(base.ownerType || "team") === "team" && (ownerId === requestedTeamId || base.teamId === requestedTeamId);
    }) ?? null;
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
      {
        key: "sqlite_database_compact",
        label: copy.cleanupSqliteCompact,
        detail: "workspace/agent_brain.db VACUUM; reclaims free pages without deleting rows",
        target: { targetType: "sqlite_database_compact" },
        risk: "high",
      },
      {
        key: "evaluation_artifacts",
        label: copy.cleanupEvaluationArtifacts,
        detail: "workspace/evaluation",
        target: { targetType: "evaluation_artifacts" },
        risk: "critical",
      },
      {
        key: "session_artifacts",
        label: copy.cleanupSessionArtifacts,
        detail: "workspace/sessions",
        target: { targetType: "session_artifacts" },
        risk: "critical",
      },
      {
        key: "legacy_log_info",
        label: copy.cleanupLegacyLogInfo,
        detail: "log_info",
        target: { targetType: "legacy_log_info" },
        risk: "critical",
      },
      {
        key: "runtime_scene_logs",
        label: copy.cleanupRuntimeSceneLogs,
        detail: "logs/runtime_scenes",
        target: { targetType: "runtime_scene_logs" },
        risk: "critical",
      },
      {
        key: "team_archive_artifacts",
        label: copy.cleanupTeamArchiveArtifacts,
        detail: "workspace/teams/*/archives",
        target: { targetType: "team_archive_artifacts" },
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
    mutationFn: async (draft: MemoryKnowledgeOwnerSourceDraft) =>
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
      return { incoming: [] as MemoryGraphRelation[], outgoing: [] as MemoryGraphRelation[] };
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
    if (!selectedAgentMemoryItemId) {
      return;
    }
    if (!selectedAgentMemoryItems.some((item) => item.id === selectedAgentMemoryItemId)) {
      setSelectedAgentMemoryItemId("");
    }
  }, [selectedAgentMemoryItemId, selectedAgentMemoryItems]);

  useEffect(() => {
    if (!knowledgeBases.length) {
      if (activeKnowledgeBaseId) {
        setActiveKnowledgeBaseId("");
      }
      return;
    }
    if (requestedTeamKnowledgeBase && activeKnowledgeBaseId !== knowledgeBaseRequestId(requestedTeamKnowledgeBase)) {
      setActiveKnowledgeBaseId(knowledgeBaseRequestId(requestedTeamKnowledgeBase));
      return;
    }
    if (!activeKnowledgeBaseId || !knowledgeBases.some((base) => knowledgeBaseRequestId(base) === activeKnowledgeBaseId)) {
      setActiveKnowledgeBaseId(knowledgeBaseRequestId(knowledgeBases[0]));
    }
  }, [activeKnowledgeBaseId, knowledgeBases, requestedTeamKnowledgeBase]);

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
  const handleChannelCardClick = (channel: MemoryChannel) => {
    setActiveSectionId("");
    setActiveItemId("");
    setActiveChannel((current) => (current === channel ? "" : channel));
  };
  const selectMemoryAgent = (agentId: string) => {
    setSelectedAgentMemoryItemId("");
    const next = buildMemorySearchParams(
      activeSectionId,
      activeItemId,
      activeFilter,
      activeManageFilter,
      activeChannel,
      searchText,
      agentId,
    );
    setSearchParams(next);
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

  const renderMemoryList = (pairs: MemoryPair[], emptyText: string, compact = false, selectable = false) => (
    <MemoryItemListPanel
      pairs={pairs}
      emptyText={emptyText}
      loading={overviewQuery.isPending && !hasOverviewSections}
      errorText={
        showBlockingOverviewError
          ? `${copy.loadFailed}: ${overviewQuery.error instanceof Error ? overviewQuery.error.message : String(overviewQuery.error)}`
          : ""
      }
      compact={compact}
      selectable={selectable}
      activePairKey={activePairKey}
      selectedMemoryKeys={selectedMemoryKeySet}
      copy={copy}
      formatTimestamp={(value) => formatTimestamp(value, lang)}
      formatSourceOrigin={sourceOriginLabel}
      statusClassName={statusClassName}
      channelPills={(item) => itemChannelPills(copy, item)}
      onSelectPair={selectMemoryPair}
      onToggleSelection={toggleMemorySelection}
    />
  );

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

  const isPendingProjectMemoryOnly = memoryProposalStatusFilter === "pending";
  const projectMemoryQueueEmptyText = isPendingProjectMemoryOnly ? copy.projectMemoryQueueEmptyPending : copy.projectMemoryQueueEmptyAll;
  const projectMemoryQueueErrorText = projectMemoryUpdatesQuery.isError
    ? projectMemoryUpdatesQuery.error instanceof Error
      ? projectMemoryUpdatesQuery.error.message
      : String(projectMemoryUpdatesQuery.error)
    : "";
  const projectMemoryQueuePanel = (
    <MemoryProjectMemoryQueuePanel
      copy={copy}
      isPendingOnly={isPendingProjectMemoryOnly}
      pendingProposalCount={pendingProjectMemoryProposalCount}
      proposalCount={projectMemoryUpdateProposals.length}
      laneCount={projectMemoryProposalLaneCount}
      proposals={projectMemoryUpdateProposals}
      resolutionNotes={memoryProposalResolutionNotes}
      mutationFeedback={mutationFeedback}
      errorText={projectMemoryQueueErrorText}
      emptyText={projectMemoryQueueEmptyText}
      isLoading={projectMemoryUpdatesQuery.isPending}
      isResolving={projectMemoryUpdateResolveMutation.isPending}
      onFilterChange={setMemoryProposalStatusFilter}
      onResolutionNoteChange={(proposalId, note) =>
        setMemoryProposalResolutionNotes((current) => ({
          ...current,
          [proposalId]: note,
        }))
      }
      onResolve={handleProjectMemoryProposalResolve}
      renderStatus={renderProjectMemoryProposalStatus}
      formatTimestamp={(value) => formatTimestamp(value ?? "", lang)}
      proposalAgentLabel={projectMemoryProposalAgentLabel}
      proposalResolverLabel={(resolvedBy) => projectMemoryProposalResolverLabel(resolvedBy, lang)}
    />
  );

  const reviewQueueErrorText = showBlockingOverviewError
    ? overviewQuery.error instanceof Error
      ? overviewQuery.error.message
      : String(overviewQuery.error)
    : "";
  const reviewQueueItems = priorityReviewPairs.map((pair, index) => {
    const { section, item } = pair;
    const itemId = pairSelectionKey(section.id, item.id);
    const encodedSectionId = encodeURIComponent(section.id);
    const encodedItemId = encodeURIComponent(item.id);
    return {
      id: itemId,
      rank: index + 1,
      title: item.title,
      origin: sourceOriginLabel(section, item),
      summary: item.summary,
      reasons: reviewReasonLabels(copy, item),
      updatedAt: formatTimestamp(item.updatedAt, lang),
      auditHref: `/memory/sources?section=${encodedSectionId}&item=${encodedItemId}`,
      manageHref: memoryPairActionTarget(pair) === "manage" ? `/memory/manage?section=${encodedSectionId}&item=${encodedItemId}` : undefined,
    };
  });
  const reviewQueuePanel = (
    <MemoryReviewQueuePanel
      copy={copy}
      isLoading={overviewQuery.isPending && !hasOverviewSections}
      errorText={reviewQueueErrorText}
      items={reviewQueueItems}
      onOpenItem={(itemId) => {
        const pair = priorityReviewPairs.find(({ section, item }) => pairSelectionKey(section.id, item.id) === itemId);
        if (pair) {
          openReviewTarget(pair);
        }
      }}
    />
  );

  const createMatrixPanel = (title = copy.whereMemoryWorks) => (
    <MemoryMatrixPanel
      copy={copy}
      title={title}
      activeChannel={activeChannel}
      activeChannelLabel={activeChannel ? channelFilterLabel(copy, activeChannel) : ""}
      generatedAt={overview ? formatTimestamp(overview.generatedAt, lang) : ""}
      cards={matrixCards}
      onSelectChannel={handleChannelCardClick}
    />
  );

  const createWarningStrip = () => <MemoryWarningStrip label={copy.warnings} warnings={overview?.summary.warnings ?? []} />;

  const createManagementEditor = () => (
    <MemoryManagementEditor
      copy={copy}
      draft={editDraft}
      previewItem={resolvedActiveItem}
      mutationBusy={mutationBusy}
      mutationFeedback={mutationFeedback}
      onCancel={cancelDraft}
      onDraftChange={setEditDraft}
      onSave={saveDraft}
    />
  );

  const createSelectedMemoryConfig = () => (
    <MemorySelectedConfigPanel
      copy={copy}
      sectionTitle={activeSection?.title ?? ""}
      item={resolvedActiveItem}
      isEditing={Boolean(editDraft)}
      mutationBusy={mutationBusy}
      mutationFeedback={mutationFeedback}
      onEdit={startEdit}
      onRestore={restoreActiveItem}
      onDisableOrDelete={disableOrDeleteActiveItem}
    />
  );

  const createDetailPanel = (showEditor = true) => (
    <MemoryDetailPanel
      copy={copy}
      showEditor={showEditor}
      managementEditor={createManagementEditor()}
      section={activeSection}
      item={resolvedActiveItem}
      activeImpact={activeImpact}
      channelPills={resolvedActiveItem ? itemChannelPills(copy, resolvedActiveItem) : []}
      copyFeedback={copyFeedback}
      canCopyRawContent={canCopyRawContent}
      isDetailFetching={activeItemDetailQuery.isFetching}
      detailErrorText={activeItemDetailQuery.isError ? (activeItemDetailQuery.error instanceof Error ? activeItemDetailQuery.error.message : String(activeItemDetailQuery.error)) : ""}
      isEditing={Boolean(editDraft)}
      overviewIsPending={overviewQuery.isPending}
      sectionUpdatedAt={activeSection ? formatTimestamp(activeSection.updatedAt, lang) : ""}
      generatedAt={overview ? formatTimestamp(overview.generatedAt, lang) : ""}
      onCopySourceSummary={handleCopySourceSummary}
      onCopySourcePath={handleCopySourcePath}
      onCopyRawContent={handleCopyRawContent}
      onCopyCurrentLink={handleCopyCurrentLink}
    />
  );

  const createEffectivePanel = () => (
    <MemoryEffectivePanel
      copy={copy}
      matrixPanel={createMatrixPanel(copy.effectiveByChannel)}
      warningStrip={createWarningStrip()}
      cards={matrixCards.map((card) => {
        const pairs = allPairs.filter((pair) => matchesMemoryChannel(card.channel, pair));
        return {
          id: card.id,
          title: card.title,
          count: pairs.length,
          memoryList: renderMemoryList(pairs, copy.noMatches, true),
        };
      })}
    />
  );

  const createSourceAndItemPanels = (title: string) => (
    <MemorySourceAndItemPanels
      copy={copy}
      sourceTitle={selectedSection?.title ?? copy.allSections}
      itemTitle={selectedSection?.title ?? title}
      selectedSectionVisibleCount={selectedSectionVisibleCount}
      searchText={searchText}
      onSearchTextChange={setSearchText}
      filterOptions={filterOptions}
      activeFilterId={activeFilter}
      onFilterChange={(filterId) => setActiveFilter(filterId as FilterMode)}
      allSectionsActive={!activeSectionId}
      flatVisibleItemCount={flatVisibleItems.length}
      selectedSectionPromptCount={selectedSectionPromptCount}
      onSelectAllSections={() => {
        setActiveItemId("");
        setActiveSectionId("");
      }}
      sections={sections.map((section) => {
        const metrics = sourceSectionMetrics.get(section.id);
        return {
          id: section.id,
          title: section.title,
          sourcePath: section.sourcePath,
          sourceApi: section.sourceApi,
          sourceKind: section.sourceKind,
          itemCount: metrics?.itemCount ?? 0,
          promptCount: metrics?.promptCount ?? 0,
          active: section.id === activeSectionId,
        };
      })}
      onSelectSection={(sectionId) => {
        setActiveItemId("");
        setActiveSectionId(sectionId);
      }}
      showRefreshNotice={showRefreshNotice}
      refreshErrorText={overviewQuery.error instanceof Error ? overviewQuery.error.message : String(overviewQuery.error)}
      memoryList={renderMemoryList(flatVisibleItems, copy.noMatches, true)}
    />
  );

  const createManagePanel = () => (
    <MemoryManagePanel
      copy={copy}
      warningStrip={createWarningStrip()}
      manageableCount={manageablePairs.length}
      visibleItemCount={flatVisibleItems.length}
      searchText={searchText}
      onSearchTextChange={setSearchText}
      manageFilterOptions={manageFilterOptions}
      activeManageFilterId={activeManageFilter}
      onManageFilterChange={(filterId) => {
        setActiveItemId("");
        setActiveManageFilter(filterId as ManageFilterMode);
      }}
      sourceFilters={sections
        .filter((section) => (manageableSectionMetrics.get(section.id) ?? 0) > 0)
        .map((section) => ({
          id: section.id,
          title: section.title,
          count: manageableSectionMetrics.get(section.id) ?? 0,
          active: section.id === activeSectionId,
        }))}
      allSectionsActive={!activeSectionId}
      onSelectAllSections={() => {
        setActiveItemId("");
        setActiveSectionId("");
      }}
      onSelectSourceFilter={(sectionId) => {
        setActiveItemId("");
        setActiveSectionId(sectionId);
      }}
      mutationBusy={mutationBusy}
      allVisibleSelected={allVisibleSelected}
      onToggleVisibleSelection={toggleVisibleMemorySelection}
      selectedMemoryCount={selectedMemoryPairs.length}
      onBulkDisable={() => {
        void runBulkMemoryAction("disable");
      }}
      onBulkRestore={() => {
        void runBulkMemoryAction("restore");
      }}
      disableBulkDisabled={mutationBusy || selectedDisablePairs.length === 0}
      restoreBulkDisabled={mutationBusy || selectedRestorePairs.length === 0}
      disableBulkPending={bulkActionPending === "disable"}
      restoreBulkPending={bulkActionPending === "restore"}
      memoryList={renderMemoryList(flatVisibleItems, copy.noMatches, false, true)}
      editMode={editDraft?.mode ?? null}
      onStartCreate={startCreate}
      managementEditor={createManagementEditor()}
      selectedConfig={createSelectedMemoryConfig()}
      showEmptySelection={!editDraft && !activeItem}
      detailPanel={createDetailPanel(false)}
    />
  );

  const createAgentMemoryPanel = () => {
    const summary = agentMemoryInventoryQuery.data?.summary;
    const agentSearch = searchText.trim().toLowerCase();
    const visibleAgents = agentMemoryInventoryAgents.filter((agent) =>
      !agentSearch
      || [
        agent.displayName,
        agent.agentCode,
        agent.agentId,
        agent.workspacePath,
        agent.privateMemoryRoot,
        agent.primaryMode,
        agent.roleKey,
      ].some((value) => String(value || "").toLowerCase().includes(agentSearch)),
    );
    return (
      <MemoryAgentMemoryPanel
        copy={copy}
        summary={{
          agentCount: summary?.agentCount ?? 0,
          privateFileCount: summary?.privateFileCount ?? 0,
          privateByteText: formatByteCount(summary?.privateByteCount ?? 0),
          formalKnowledgeItemCount: summary?.formalKnowledgeItemCount ?? 0,
          formalKnowledgeBaseCount: summary?.formalKnowledgeBaseCount ?? 0,
          warningCount: summary?.warnings.length ?? 0,
        }}
        searchText={searchText}
        onSearchTextChange={setSearchText}
        agents={visibleAgents.map((agent) => ({
          id: agent.agentId,
          name: agent.displayName || agent.agentId,
          status: agent.status,
          origin: agent.agentCode || agent.agentId,
          path: agent.privateMemoryRoot || agent.workspacePath,
          privateFileCount: agent.fileCount,
          formalKnowledgeBaseCount: agent.knowledgeSummary.knowledgeBaseCount,
          hasPrivateMemory: agent.hasPrivateMemory,
          active: agent.agentId === selectedAgentMemoryAgentId,
        }))}
        selectedAgent={
          selectedAgentMemoryAgent
            ? {
              name: selectedAgentMemoryAgent.displayName || selectedAgentMemoryAgent.agentId,
              privateRoot: selectedAgentMemoryAgent.privateMemoryRoot,
              workspacePath: selectedAgentMemoryAgent.workspacePath,
              fileCount: selectedAgentMemoryAgent.fileCount,
              formalKnowledgeItemCount: selectedAgentMemoryAgent.knowledgeSummary.itemCount,
              formalKnowledgeBaseCount: selectedAgentMemoryAgent.knowledgeSummary.knowledgeBaseCount,
              knowledgeError: selectedAgentMemoryAgent.knowledgeSummary.error,
              knowledgeBases: selectedAgentMemoryAgent.knowledgeSummary.knowledgeBases.map((base) => ({
                id: base.scopedKnowledgeBaseId || base.knowledgeBaseId,
                label: base.name || base.knowledgeBaseId,
                title: base.scopedKnowledgeBaseId || base.knowledgeBaseId,
              })),
            }
            : null
        }
        selectedItem={
          selectedAgentMemoryItem
            ? {
              title: selectedAgentMemoryItem.relativePath || selectedAgentMemoryItem.title,
              path: selectedAgentMemoryItem.path,
              sizeText: formatByteCount(selectedAgentMemoryItem.sizeBytes),
              contentType: selectedAgentMemoryItem.contentType,
              contentLanguage: contentLanguage(selectedAgentMemoryItem.contentType),
              content: selectedAgentMemoryItem.content,
            }
            : null
        }
        items={selectedAgentMemoryItems.map((item) => ({
          id: item.id,
          title: item.relativePath || item.title,
          updatedAtText: formatTimestamp(item.updatedAt, lang),
          path: item.path,
          summary: item.summary,
          sizeText: formatByteCount(item.sizeBytes),
          contentType: item.contentType,
          truncated: item.contentTruncated,
          active: item.id === selectedAgentMemoryItem?.id,
        }))}
        inventoryPending={agentMemoryInventoryQuery.isPending}
        inventoryErrorText={agentMemoryInventoryQuery.error instanceof Error ? agentMemoryInventoryQuery.error.message : agentMemoryInventoryQuery.error ? String(agentMemoryInventoryQuery.error) : ""}
        detailPending={agentMemoryDetailQuery.isPending && Boolean(selectedAgentMemoryAgentId)}
        detailFetching={agentMemoryDetailQuery.isFetching}
        detailErrorText={agentMemoryDetailQuery.error instanceof Error ? agentMemoryDetailQuery.error.message : agentMemoryDetailQuery.error ? String(agentMemoryDetailQuery.error) : ""}
        generatedAtText={formatTimestamp(agentMemoryDetailQuery.data?.generatedAt ?? agentMemoryInventoryQuery.data?.generatedAt ?? "", lang)}
        onSelectAgent={selectMemoryAgent}
        onSelectItem={setSelectedAgentMemoryItemId}
      />
    );
  };

  const renderSourcesView = () => (
    <>
      {createMatrixPanel(copy.sourceAudit)}
      {createWarningStrip()}
      <div className={styles.workspace}>
        {createSourceAndItemPanels(copy.sourceAudit)}
        {createDetailPanel()}
      </div>
    </>
  );

  const renderKnowledgeView = () => (
    <>
      <MemoryKnowledgePipelinePanel
        copy={copy}
        knowledgeBaseCount={knowledgeOverview?.summary.knowledgeBaseCount ?? 0}
        pendingProposalCount={knowledgeOverview?.summary.pendingProposalCount ?? 0}
        itemCount={knowledgeOverview?.summary.itemCount ?? 0}
        sourceArtifactCount={knowledgeOverview?.summary.sourceArtifactCount ?? 0}
        batchCount={knowledgeBases.reduce((total, base) => total + base.stats.batchCount, 0)}
        pendingRatingSuggestionCount={ratingSuggestionsQuery.data?.summary.pendingSuggestionCount ?? knowledgeItems.filter((item) => item.markedAt).length}
      />
      <MemoryUserContentPanel defaultUserId="default" />
      <div className={styles.knowledgeGovernanceDeck}>
        <MemoryKnowledgeUsageContractPanel
          copy={copy}
          lang={lang}
          contract={memoryUsageContract}
          formatDomainLabel={(label, domainId) => memoryDomainDisplayLabel(label, domainId, lang)}
          formatOwnerLabel={(owner) => memoryDomainOwnerLabel(owner, lang)}
          formatBoundaryLabel={(boundary) => memoryBoundaryLabel(boundary, lang)}
          formatPolicyToken={(value) => policyTokenLabel(value, lang)}
        />
        <MemoryKnowledgeStewardPanel
          copy={copy}
          lang={lang}
          knowledgeSteward={knowledgeSteward}
          recommendations={knowledgeStewardRecommendations}
          knowledgeStewardWorkbench={knowledgeStewardWorkbench}
          recommendationsOnly={knowledgeDashboardSnapshot?.recommendations.operatingBoundary.recommendationsOnly ?? false}
          formatPolicyToken={(value) => policyTokenLabel(value, lang)}
          onTraceTarget={setTraceTargetId}
        />
      </div>
      {knowledgeFeedback.tone !== "idle" ? (
        <section className={knowledgeFeedback.tone === "error" ? styles.panelError : styles.panelNotice}>
          {knowledgeFeedback.tone === "error" ? <TriangleAlert size={16} /> : <CheckCircle2 size={16} />}
          <span>{knowledgeFeedback.text}</span>
        </section>
      ) : null}
      <div className={`${styles.workspace} ${styles.knowledgeWorkspace}`}>
        <MemoryKnowledgeBaseSidebar
          copy={copy}
          bases={knowledgeBases.map((base) => ({
            requestId: knowledgeBaseRequestId(base),
            name: base.name,
            teamLabel: base.teamName || base.teamId,
            itemCount: base.stats.itemCount,
            pendingProposalCount: base.stats.pendingProposalCount,
          }))}
          permissionTools={Object.values(permissionAudit?.tools ?? {}).map((tool) => ({
            toolName: tool.toolName,
            visible: tool.visible,
            reason: tool.reason,
          }))}
          activeBaseRequestId={activeKnowledgeBaseForItems}
          isLoading={knowledgeDashboardSnapshotQuery.isPending}
          onSelectBase={setActiveKnowledgeBaseId}
        />

        <main className={styles.knowledgeMain}>
          <MemoryKnowledgeModeTabs
            copy={copy}
            lang={lang}
            activeMode={activeKnowledgeWorkspaceMode}
            sourceCount={sourceInboxQuery.data?.summary.sourceCount ?? ownerInboxSources.length}
            centralSourceCount={centralSourcesQuery.data?.summary.centralSourceCount ?? centralSources.length}
            searchResultCount={knowledgeSearchQuery.data?.summary.resultCount ?? 0}
            ragContextCount={knowledgeRagRetrieveQuery.data?.summary.contextCount ?? 0}
            pendingProposalCount={activeKnowledgeBase?.pendingProposals.length ?? 0}
            ratingSuggestionCount={ratingSuggestions.length}
            operationsFindingCount={knowledgeOperationsHealth?.summary.findingCount ?? 0}
            openGovernanceTaskCount={governanceTasksQuery.data?.summary.openTaskCount ?? 0}
            permissionKnowledgeBaseCount={permissionAudit?.summary.knowledgeBaseCount ?? 0}
            ingestionAdapterCount={ingestionAdapters.length}
            onModeChange={setActiveKnowledgeWorkspaceMode}
          />
          {activeKnowledgeWorkspaceMode === "sources" ? (
          <MemoryKnowledgeSourceGovernancePanel
            copy={copy}
            sourceOwnerType={sourceOwnerType}
            sourceOwnerId={sourceOwnerId}
            sourceInboxStatus={sourceInboxStatus}
            sourceCount={sourceInboxQuery.data?.summary.sourceCount ?? ownerInboxSources.length}
            centralSourceCount={centralSourcesQuery.data?.summary.centralSourceCount ?? centralSources.length}
            showOwnerSourceForm={showOwnerSourceForm}
            ownerSourceDraft={ownerSourceDraft}
            sourceReviewNote={sourceReviewNote}
            duplicateCentralSourceId={duplicateCentralSourceId}
            ownerInboxSources={ownerInboxSources}
            centralSources={centralSources}
            isSourceInboxPending={sourceInboxQuery.isPending}
            isCentralSourcesPending={centralSourcesQuery.isPending}
            knowledgeBusy={knowledgeBusy}
            canSubmitOwnerSource={!knowledgeBusy && Boolean(activeSourceOwnerId)}
            canAttachCentralSource={Boolean(activeKnowledgeBase?.permissions.canPropose && activeKnowledgeBaseForItems) && !knowledgeBusy}
            onSourceOwnerTypeChange={setSourceOwnerType}
            onSourceOwnerIdChange={setSourceOwnerId}
            onSourceInboxStatusChange={setSourceInboxStatus}
            onApplyActiveKnowledgeOwner={applyActiveKnowledgeOwner}
            onShowOwnerSourceFormChange={setShowOwnerSourceForm}
            onOwnerSourceDraftChange={setOwnerSourceDraft}
            onSourceReviewNoteChange={setSourceReviewNote}
            onDuplicateCentralSourceIdChange={setDuplicateCentralSourceId}
            onSubmitOwnerSource={submitOwnerSource}
            onReviewOwnerSource={reviewOwnerSource}
            onAttachCentralSource={attachCentralSource}
            formatTimestamp={(value) => formatTimestamp(value, lang)}
          />
          ) : null}

          {activeKnowledgeWorkspaceMode === "search" ? (
          <MemoryKnowledgeSearchPanel
            copy={copy}
            draft={knowledgeSearchDraft}
            resultCount={knowledgeSearchQuery.data?.summary.resultCount ?? 0}
            results={knowledgeSearchResults}
            searchPending={knowledgeSearchQuery.isPending}
            contexts={knowledgeRagContexts}
            ragHealth={knowledgeRagHealth}
            ragProviderHealth={localRagProviderHealth}
            retrievalPolicy={knowledgeRagPolicy}
            ragContextCount={knowledgeRagRetrieveQuery.data?.summary.contextCount ?? 0}
            ragCitationCount={knowledgeRagRetrieveQuery.data?.summary.citationCount ?? 0}
            ragPending={knowledgeRagRetrieveQuery.isPending}
            onDraftChange={setKnowledgeSearchDraft}
          />
          ) : null}

          {activeKnowledgeWorkspaceMode === "governance" ? (
          <MemoryKnowledgeGovernancePanel
            copy={copy}
            operationsHealth={knowledgeOperationsHealth}
            governancePlan={knowledgeGovernancePlan}
            governanceTasks={governanceTasks}
            operationsPending={knowledgeDashboardSnapshotQuery.isPending}
            governanceTasksPending={governanceTasksQuery.isPending}
            openGovernanceTaskCount={governanceTasksQuery.data?.summary.openTaskCount ?? 0}
            onTraceTarget={setTraceTargetId}
          />
          ) : null}

          {activeKnowledgeWorkspaceMode === "permissions" ? (
          <MemoryKnowledgePermissionsPanel
            copy={copy}
            ingestionAdapters={ingestionAdapters}
            permissionAudit={permissionAudit}
          />
          ) : null}

          {activeKnowledgeWorkspaceMode === "review" ? (
          <MemoryKnowledgeReviewPanel
            copy={copy}
            activeKnowledgeBase={activeKnowledgeBase}
            proposalDraft={proposalDraft}
            ratingSuggestions={ratingSuggestions}
            pendingVisibleRatingSuggestions={pendingVisibleRatingSuggestions}
            selectedRatingSuggestionIds={selectedRatingSuggestionIds}
            selectedVisibleRatingSuggestionIds={selectedVisibleRatingSuggestionIds}
            ratingSuggestionStatus={ratingSuggestionStatus}
            ratingSuggestionPriority={ratingSuggestionPriority}
            ratingSuggestionsPending={ratingSuggestionsQuery.isPending}
            knowledgeBusy={knowledgeBusy}
            onProposalDraftChange={setProposalDraft}
            onSubmitRefinementProposal={submitRefinementProposal}
            onReviewProposal={reviewProposal}
            onRatingSuggestionStatusChange={setRatingSuggestionStatus}
            onRatingSuggestionPriorityChange={setRatingSuggestionPriority}
            onToggleVisibleRatingSuggestions={toggleVisibleRatingSuggestions}
            onClearRatingSuggestionSelection={() => setSelectedRatingSuggestionIds([])}
            onReviewSelectedRatingSuggestions={reviewSelectedRatingSuggestions}
            onToggleRatingSuggestionSelection={toggleRatingSuggestionSelection}
            onReviewRatingSuggestion={reviewRatingSuggestion}
          />
          ) : null}

        </main>

        <MemoryKnowledgeDetailPanel
          copy={copy}
          activeKnowledgeBase={activeKnowledgeBase}
          traceTargetId={traceTargetId}
          trace={knowledgeTraceQuery.data}
          knowledgeItems={knowledgeItems}
          knowledgeItemsPending={knowledgeItemsQuery.isPending}
          ratingDraft={ratingDraft}
          knowledgeBusy={knowledgeBusy}
          onTraceTargetChange={setTraceTargetId}
          onRatingDraftChange={setRatingDraft}
          onUpdateKnowledgeRating={updateKnowledgeRating}
        />
      </div>
    </>
  );

  const createCleanupPanel = () => {
    const report = cleanupExecution ?? cleanupPreview;
    const canExecute = selectedCleanupTargets.length > 0 && cleanupConfirmationText.trim() === (report?.confirmationPhrase || "硬删除记忆");

    return (
      <MemoryCleanupPanel
        copy={copy}
        targetOptions={cleanupTargetOptions}
        selectedTargetKeys={selectedCleanupTargetKeys}
        selectedTargetCount={selectedCleanupTargets.length}
        totalTargetCount={cleanupTargetOptions.length}
        targetsLoading={knowledgeDashboardSnapshotQuery.isPending || agentsQuery.isPending}
        report={report}
        execution={cleanupExecution}
        confirmationText={cleanupConfirmationText}
        feedback={cleanupFeedback}
        previewPending={cleanupPreviewMutation.isPending}
        executePending={cleanupExecuteMutation.isPending}
        canExecute={canExecute}
        formatByteCount={formatByteCount}
        onToggleTarget={toggleCleanupTarget}
        onPreview={previewCleanup}
        onExecute={executeCleanup}
        onConfirmationTextChange={setCleanupConfirmationText}
      />
    );
  };

  const renderGraphView = () => (
    <MemoryGraphViewPanel
      copy={copy}
      graphPayload={graphPayload}
      filteredGraphNodes={filteredGraphNodes}
      filteredGraphEdges={filteredGraphEdges}
      graphSearchText={graphSearchText}
      activeGraphNodeType={activeGraphNodeType}
      graphTypeEntries={graphTypeEntries}
      selectedGraphNode={selectedGraphNode}
      selectedGraphChildren={selectedGraphChildren}
      selectedGraphRelations={selectedGraphRelations}
      selectedGraphDetailItems={selectedGraphDetailItems}
      isGraphNodeDetailFetching={memoryKnowledgeGraphNodeDetailQuery.isFetching}
      formatTimestamp={(value) => formatTimestamp(value, lang)}
      onGraphSearchTextChange={setGraphSearchText}
      onActiveGraphNodeTypeChange={setActiveGraphNodeType}
      onClearGraphFilters={() => {
        setActiveGraphNodeType("");
        setGraphSearchText("");
      }}
      onSelectGraphNode={setSelectedGraphNodeId}
      onFocusGraphNode={selectGraphNode}
    />
  );

  const viewStackClassName =
    forcedView === "graph"
      ? `${styles.viewStack} ${styles.graphViewStack}`
      : forcedView === "agents"
        ? `${styles.viewStack} ${styles.agentMemoryViewStack}`
      : forcedView === "knowledge"
        ? `${styles.viewStack} ${styles.knowledgeViewStack}`
        : styles.viewStack;

  return (
    <section className={styles.route}>
      <VRouteHeader
        className={styles.header}
        eyebrow={copy.eyebrow}
        title={memoryViewLabel(copy, forcedView)}
        meta={memoryViewSubtitle(copy, forcedView)}
        actions={(
          <div className={styles.headerActions}>
            <VButton type="button" className={styles.refreshButton} onClick={refresh}>
              <RefreshCw size={16} />
              {copy.refresh}
            </VButton>
            {returnToPath ? (
              <Link to={returnToPath} className={styles.returnButton}>
                <ArrowLeft size={16} />
                {returnToLabel}
              </Link>
            ) : null}
          </div>
        )}
      />

      <div className={styles.controlStrip}>
        {renderSubnav()}
      </div>

      <div className={viewStackClassName}>
        {forcedView === "overview"
          ? (
            <MemoryOverviewPanel
              copy={copy}
              summary={overview?.summary}
              managedStateCount={managedStateCount}
              disabledOrOverriddenCount={disabledOrOverriddenCount}
              priorityReviewCount={priorityReviewPairs.length}
              runtimeMemoryCount={runtimePairs.length}
              reviewMemoryCount={reviewPairs.length}
              warningStrip={createWarningStrip()}
              reviewQueue={reviewQueuePanel}
              projectMemoryQueue={projectMemoryQueuePanel}
              runtimeMemoryList={renderMemoryList(runtimePairs, copy.noRuntimeMemory, true)}
              reviewMemoryList={renderMemoryList(reviewPairs, copy.noIssues, true)}
            />
          )
           : forcedView === "effective"
             ? createEffectivePanel()
             : forcedView === "agents"
              ? createAgentMemoryPanel()
              : forcedView === "manage"
                ? createManagePanel()
                : forcedView === "knowledge"
                  ? renderKnowledgeView()
                  : forcedView === "graph"
                    ? renderGraphView()
                    : forcedView === "cleanup"
                      ? createCleanupPanel()
                      : renderSourcesView()}
      </div>
    </section>
  );
}
