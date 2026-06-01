import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Brain,
  CheckCircle2,
  Copy as CopyIcon,
  Database,
  Eye,
  FileText,
  Link2,
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
import { useEffect, useMemo, useState } from "react";
import { NavLink, useSearchParams } from "react-router-dom";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import {
  KnowledgeItemsPayload,
  KnowledgeItem,
  KnowledgeGovernancePlanPayload,
  KnowledgeGovernanceTasksPayload,
  KnowledgeIngestionAdaptersPayload,
  KnowledgeIngestionPackageResponse,
  KnowledgeOperationsHealthPayload,
  KnowledgePermissionAuditPayload,
  KnowledgeRatingSuggestionBulkReviewResponse,
  KnowledgeRatingSuggestion,
  KnowledgeRatingSuggestionReviewResponse,
  KnowledgeRatingSuggestionsPayload,
  KnowledgeRefinementProposal,
  KnowledgeReviewResponse,
  KnowledgeSearchPayload,
  KnowledgeSourceArtifact,
  KnowledgeStewardOverview,
  KnowledgeStewardRecommendationsPayload,
  KnowledgeStewardWorkbenchPayload,
  KnowledgeTracePayload,
  MemoryItem,
  MemoryMutationResponse,
  MemoryOverview,
  MemorySection,
  MemoryUsageContractPayload,
  TeamKnowledgeBase,
  TeamKnowledgeOverview,
} from "../api/types";
import { resolvePollingInterval, usePageVisibility } from "../app/pollingPolicy";
import { useAppI18n } from "../i18n/useAppI18n";
import styles from "./MemoryRoute.module.css";

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
  sourceAudit: string;
  reviewQueue: string;
  reviewQueueHint: string;
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
  sourceRegistration: string;
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
  ingestionPackage: string;
  submitIngestionPackage: string;
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
};

type FilterMode = "all" | "prompt" | "visible" | "manual" | "missing";
type ManageFilterMode = "all" | "prompt" | "editable" | "changed" | "missing";
export type MemoryRouteView = "overview" | "effective" | "manage" | "sources" | "knowledge";
type MemoryChannel = "conversation" | "research" | "self_evolution" | "supervised_evolution" | "explicit_read";
type ChannelFilter = MemoryChannel | "";
type MemoryPair = {
  section: MemorySection;
  item: MemoryItem;
};
type BulkMemoryAction = "disable" | "restore";
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
type ProposalDraft = {
  sourceArtifactIds: string;
  proposedByAgentId: string;
  title: string;
  summary: string;
  content: string;
  tags: string;
};
type IngestionDraft = {
  sourceType: string;
  sourceRef: string;
  sourceCreatedAt: string;
  capturedBy: string;
  evidenceRange: string;
  sourceTitle: string;
  sourceSummary: string;
  excerpt: string;
  proposedByAgentId: string;
  proposalTitle: string;
  proposalSummary: string;
  proposalContent: string;
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
};
type RatingSuggestionStatusFilter = "pending" | "applied" | "rejected" | "all";
type RatingSuggestionPriorityFilter = "all" | "urgent" | "elevated" | "normal";
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
    noContent: "没有可展示的原文。",
    sourceOrigin: "来源",
    searchPlaceholder: "搜索来源、路径、摘要或作用位置",
    allSections: "全部来源",
    noMatches: "没有匹配当前搜索的记忆。",
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
    noIssues: "当前没有需要优先检查的记忆。",
    noRuntimeMemory: "当前没有进入 prompt 或 agent 可感知的记忆。",
    managedMemory: "用户管理状态",
    disabledOrOverridden: "已禁用/覆盖",
    effectiveByChannel: "按作用位置查看",
    manageAllMemory: "全部可管理记忆",
    manageConfigPanel: "配置面板",
    manageConfigHint: "先在左侧选择一条记忆，再在这里编辑、禁用、恢复或新增用户记忆。系统来源只保存覆盖状态，原始文件保持不变。",
    manageListHint: "选择一条记忆后在中间配置；右侧只负责查看来源、影响和原文。",
    selectedMemory: "选中记忆",
    sourceAudit: "来源审计",
    reviewQueue: "优先检查队列",
    reviewQueueHint: "按风险和运行影响排序，先看会改变 agent 行为或证据不完整的记忆。",
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
    sourceRegistration: "来源登记",
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
    noKnowledgeBases: "当前没有可访问的团队知识库。",
    knowledgeHint: "P1 只登记来源、提交候选并审核落盘；正式知识默认可检索，不默认注入 prompt。",
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
    ingestionPackage: "半自动摄取包",
    submitIngestionPackage: "提交摄取包",
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
    usageContract: "使用契约",
    memoryDomains: "系统域",
    allowedUse: "允许使用",
    writeBoundary: "写入边界",
    forbiddenActions: "禁止动作",
    currentContractState: "当前状态",
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
    noContent: "No raw content to show.",
    sourceOrigin: "Source",
    searchPlaceholder: "Search source, path, summary, or usage",
    allSections: "All sources",
    noMatches: "No memory matched the current search.",
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
    noIssues: "No memory needs priority review right now.",
    noRuntimeMemory: "No memory is currently injected or agent-visible.",
    managedMemory: "User-managed state",
    disabledOrOverridden: "Disabled/overridden",
    effectiveByChannel: "By effective scope",
    manageAllMemory: "All manageable memory",
    manageConfigPanel: "Configuration panel",
    manageConfigHint: "Select one memory on the left, then edit, disable, restore, or add user memory here. System sources keep reversible overrides and original files stay unchanged.",
    manageListHint: "Select a memory to configure it in the middle; the right pane is for source, impact, and raw inspection.",
    selectedMemory: "Selected memory",
    sourceAudit: "Source audit",
    reviewQueue: "Priority review queue",
    reviewQueueHint: "Sorted by risk and runtime impact so behavior-changing or incomplete evidence appears first.",
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
    sourceRegistration: "Source registration",
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
    noKnowledgeBases: "No accessible team knowledge bases yet.",
    knowledgeHint: "P1 registers sources, submits candidates, and reviews batches; formal knowledge is tool-readable, not prompt-injected.",
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
    ingestionPackage: "Semi-automatic ingestion",
    submitIngestionPackage: "Submit ingestion",
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
    usageContract: "Usage contract",
    memoryDomains: "System domains",
    allowedUse: "Allowed use",
    writeBoundary: "Write boundary",
    forbiddenActions: "Forbidden actions",
    currentContractState: "Current state",
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
) {
  const next = new URLSearchParams();
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
) {
  if (typeof window === "undefined") {
    return "";
  }
  const next = buildMemorySearchParams(activeSectionId, activeItemId, activeFilter, activeManageFilter, activeChannel, searchText);
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

function newIngestionDraft(): IngestionDraft {
  return {
    sourceType: "external_search_refinement",
    sourceRef: "{\"url\":\"\",\"query\":\"\"}",
    sourceCreatedAt: "",
    capturedBy: "",
    evidenceRange: "{}",
    sourceTitle: "",
    sourceSummary: "",
    excerpt: "",
    proposedByAgentId: "",
    proposalTitle: "",
    proposalSummary: "",
    proposalContent: "",
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
  };
}

function memoryMutationEndpoint(sectionId: string, itemId: string, suffix = "") {
  return `/api/memory/items/${encodeURIComponent(sectionId)}/${encodeURIComponent(itemId)}${suffix}`;
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

export function MemoryRoute({ forcedView = "overview" }: MemoryRouteProps) {
  const { lang } = useAppI18n();
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
  const [sourceDraft, setSourceDraft] = useState<SourceDraft>(() => newSourceDraft());
  const [proposalDraft, setProposalDraft] = useState<ProposalDraft>(() => newProposalDraft());
  const [ingestionDraft, setIngestionDraft] = useState<IngestionDraft>(() => newIngestionDraft());
  const [ratingDraft, setRatingDraft] = useState<RatingDraft>(() => newRatingDraft());
  const [knowledgeSearchDraft, setKnowledgeSearchDraft] = useState<KnowledgeSearchDraft>(() => newKnowledgeSearchDraft());
  const [ratingSuggestionStatus, setRatingSuggestionStatus] = useState<RatingSuggestionStatusFilter>("pending");
  const [ratingSuggestionPriority, setRatingSuggestionPriority] = useState<RatingSuggestionPriorityFilter>("all");
  const [selectedRatingSuggestionIds, setSelectedRatingSuggestionIds] = useState<string[]>([]);
  const [traceTargetId, setTraceTargetId] = useState("");
  const [knowledgeFeedback, setKnowledgeFeedback] = useState<{ tone: "idle" | "success" | "error"; text: string }>({
    tone: "idle",
    text: "",
  });

  const overviewQuery = useQuery({
    queryKey: queryKeys.memoryOverview(),
    queryFn: () => fetchJson<MemoryOverview>("/api/memory/overview"),
    refetchInterval: resolvePollingInterval(pageVisible, 30_000),
    refetchIntervalInBackground: false,
  });
  const memoryUsageContractQuery = useQuery({
    queryKey: queryKeys.memoryUsageContract(),
    queryFn: () => fetchJson<MemoryUsageContractPayload>("/api/memory/usage-contract"),
    refetchInterval: resolvePollingInterval(pageVisible, 60_000),
    refetchIntervalInBackground: false,
    enabled: forcedView === "knowledge",
  });

  const knowledgeOverviewQuery = useQuery({
    queryKey: queryKeys.knowledgeOverview(),
    queryFn: () => fetchJson<TeamKnowledgeOverview>("/api/knowledge/overview"),
    refetchInterval: resolvePollingInterval(pageVisible, 45_000),
    refetchIntervalInBackground: false,
    enabled: forcedView === "knowledge",
  });

  const knowledgeStewardQuery = useQuery({
    queryKey: queryKeys.knowledgeStewardOverview(),
    queryFn: () => fetchJson<KnowledgeStewardOverview>("/api/knowledge/steward/overview"),
    refetchInterval: resolvePollingInterval(pageVisible, 45_000),
    refetchIntervalInBackground: false,
    enabled: forcedView === "knowledge",
  });
  const knowledgeStewardRecommendationsQuery = useQuery({
    queryKey: queryKeys.knowledgeStewardRecommendations(""),
    queryFn: () => fetchJson<KnowledgeStewardRecommendationsPayload>("/api/knowledge/steward/recommendations?limit=6"),
    refetchInterval: resolvePollingInterval(pageVisible, 45_000),
    refetchIntervalInBackground: false,
    enabled: forcedView === "knowledge",
  });
  const knowledgeStewardWorkbenchQuery = useQuery({
    queryKey: queryKeys.knowledgeStewardWorkbench(""),
    queryFn: () => fetchJson<KnowledgeStewardWorkbenchPayload>("/api/knowledge/steward/workbench?limit=8"),
    refetchInterval: resolvePollingInterval(pageVisible, 45_000),
    refetchIntervalInBackground: false,
    enabled: forcedView === "knowledge",
  });
  const knowledgeOperationsHealthQuery = useQuery({
    queryKey: queryKeys.knowledgeOperationsHealth(""),
    queryFn: () => fetchJson<KnowledgeOperationsHealthPayload>("/api/knowledge/operations/health"),
    refetchInterval: resolvePollingInterval(pageVisible, 45_000),
    refetchIntervalInBackground: false,
    enabled: forcedView === "knowledge",
  });
  const knowledgeGovernancePlanQuery = useQuery({
    queryKey: queryKeys.knowledgeGovernancePlan(""),
    queryFn: () => fetchJson<KnowledgeGovernancePlanPayload>("/api/knowledge/governance/plan?limit=8"),
    refetchInterval: resolvePollingInterval(pageVisible, 45_000),
    refetchIntervalInBackground: false,
    enabled: forcedView === "knowledge",
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
      void queryClient.invalidateQueries({ queryKey: queryKeys.memoryOverview() });
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
      void queryClient.invalidateQueries({ queryKey: queryKeys.memoryOverview() });
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
      void queryClient.invalidateQueries({ queryKey: queryKeys.memoryOverview() });
    },
    onError: (error) => {
      setMutationFeedback({
        tone: "error",
        text: `${copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}`,
      });
    },
  });

  const sourceArtifactMutation = useMutation({
    mutationFn: async ({ knowledgeBaseId, draft }: { knowledgeBaseId: string; draft: SourceDraft }) =>
      fetchJson<KnowledgeSourceArtifact>(`/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/source-artifacts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sourceType: draft.sourceType,
          sourceRef: parseJsonObject(draft.sourceRef),
          sourceCreatedAt: draft.sourceCreatedAt,
          capturedBy: draft.capturedBy,
          evidenceRange: parseJsonObject(draft.evidenceRange),
          title: draft.title,
          summary: draft.summary,
        }),
      }),
    onSuccess: (payload) => {
      setSourceDraft(newSourceDraft());
      setProposalDraft((current) => ({
        ...current,
        sourceArtifactIds: [...commaList(current.sourceArtifactIds), payload.sourceArtifactId].join(", "),
      }));
      setKnowledgeFeedback({ tone: "success", text: copy.mutationDone });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeOverview() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeOperationsHealth("") });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeGovernancePlan("") });
      void queryClient.invalidateQueries({ queryKey: queryKeys.memoryOverview() });
    },
    onError: (error) => {
      setKnowledgeFeedback({ tone: "error", text: `${copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}` });
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
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeOverview() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeOperationsHealth("") });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeGovernancePlan("") });
      void queryClient.invalidateQueries({ queryKey: queryKeys.memoryOverview() });
    },
    onError: (error) => {
      setKnowledgeFeedback({ tone: "error", text: `${copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}` });
    },
  });

  const ingestionMutation = useMutation({
    mutationFn: async ({ knowledgeBaseId, draft }: { knowledgeBaseId: string; draft: IngestionDraft }) =>
      fetchJson<KnowledgeIngestionPackageResponse>(`/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/ingestion-packages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sourceType: draft.sourceType,
          sourceRef: parseJsonObject(draft.sourceRef),
          sourceCreatedAt: draft.sourceCreatedAt,
          capturedBy: draft.capturedBy,
          evidenceRange: parseJsonObject(draft.evidenceRange),
          sourceTitle: draft.sourceTitle,
          sourceSummary: draft.sourceSummary,
          excerpt: draft.excerpt,
          proposedByAgentId: draft.proposedByAgentId,
          proposalTitle: draft.proposalTitle,
          proposalSummary: draft.proposalSummary,
          proposalContent: draft.proposalContent,
          tags: commaList(draft.tags),
        }),
      }),
    onSuccess: (payload) => {
      setIngestionDraft(newIngestionDraft());
      setKnowledgeFeedback({ tone: "success", text: `${copy.mutationDone} · ${payload.proposal.title}` });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeOverview() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeOperationsHealth("") });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeGovernancePlan("") });
      void queryClient.invalidateQueries({ queryKey: queryKeys.memoryOverview() });
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
          body: JSON.stringify({ status }),
        },
      ),
    onSuccess: (payload) => {
      setKnowledgeFeedback({ tone: "success", text: payload.item ? `${copy.mutationDone} · ${payload.item.title}` : copy.mutationDone });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeOverview() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeItems(activeKnowledgeBaseId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeSearch(activeKnowledgeBaseId, knowledgeSearchDraft.query, knowledgeSearchDraft.tags) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeOperationsHealth("") });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeGovernancePlan("") });
      void queryClient.invalidateQueries({ queryKey: queryKeys.memoryOverview() });
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
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeOverview() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeOperationsHealth("") });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeGovernancePlan("") });
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
          body: JSON.stringify({ status }),
        },
      ),
    onSuccess: () => {
      setKnowledgeFeedback({ tone: "success", text: copy.mutationDone });
      void queryClient.invalidateQueries({ queryKey: ["knowledge", "rating-suggestions"] });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeItems(activeKnowledgeBaseId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeSearch(activeKnowledgeBaseId, knowledgeSearchDraft.query, knowledgeSearchDraft.tags) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeOperationsHealth("") });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeGovernancePlan("") });
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
          body: JSON.stringify({ suggestionIds, status }),
        },
      ),
    onSuccess: (payload) => {
      setSelectedRatingSuggestionIds([]);
      setKnowledgeFeedback({
        tone: "success",
        text: `${copy.mutationDone} · ${payload.summary.reviewedCount}/${payload.summary.requestedCount}${payload.summary.skippedCount ? ` · ${copy.skippedSuggestions}: ${payload.summary.skippedCount}` : ""}`,
      });
      void queryClient.invalidateQueries({ queryKey: ["knowledge", "rating-suggestions"] });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeItems(activeKnowledgeBaseId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeSearch(activeKnowledgeBaseId, knowledgeSearchDraft.query, knowledgeSearchDraft.tags) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeOperationsHealth("") });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeGovernancePlan("") });
    },
    onError: (error) => {
      setKnowledgeFeedback({ tone: "error", text: `${copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}` });
    },
  });

  const overview = overviewQuery.data;
  const memoryUsageContract = memoryUsageContractQuery.data;
  const sections = overview?.sections ?? [];
  const knowledgeOverview = knowledgeOverviewQuery.data;
  const knowledgeSteward = knowledgeStewardQuery.data;
  const knowledgeStewardRecommendations = knowledgeStewardRecommendationsQuery.data?.recommendations ?? [];
  const knowledgeStewardWorkbench = knowledgeStewardWorkbenchQuery.data;
  const knowledgeOperationsHealth = knowledgeOperationsHealthQuery.data;
  const knowledgeGovernancePlan = knowledgeGovernancePlanQuery.data;
  const knowledgeBases = knowledgeOverview?.knowledgeBases ?? [];
  const activeKnowledgeBase: TeamKnowledgeBase | null =
    knowledgeBases.find((base) => base.knowledgeBaseId === activeKnowledgeBaseId) ?? knowledgeBases[0] ?? null;
  const activeKnowledgeBaseForItems = activeKnowledgeBase?.knowledgeBaseId ?? "";
  const knowledgeItemsQuery = useQuery({
    queryKey: queryKeys.knowledgeItems(activeKnowledgeBaseForItems),
    queryFn: () => fetchJson<KnowledgeItemsPayload>(`/api/knowledge-bases/${encodeURIComponent(activeKnowledgeBaseForItems)}/items`),
    enabled: forcedView === "knowledge" && Boolean(activeKnowledgeBaseForItems),
    refetchInterval: resolvePollingInterval(pageVisible, 45_000),
    refetchIntervalInBackground: false,
  });
  const knowledgeItems = knowledgeItemsQuery.data?.items ?? [];
  const knowledgeSearchQuery = useQuery({
    queryKey: queryKeys.knowledgeSearch(activeKnowledgeBaseForItems, knowledgeSearchDraft.query, `${knowledgeSearchDraft.tags}:${knowledgeSearchDraft.searchMode}`),
    queryFn: () => {
      const params = new URLSearchParams();
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
    enabled: forcedView === "knowledge" && Boolean(activeKnowledgeBaseForItems),
    refetchInterval: false,
  });
  const ratingSuggestionsQuery = useQuery({
    queryKey: queryKeys.knowledgeRatingSuggestions(activeKnowledgeBaseForItems, ratingSuggestionStatus, ratingSuggestionPriority),
    queryFn: () => {
      const params = new URLSearchParams();
      if (ratingSuggestionStatus !== "all") {
        params.set("status", ratingSuggestionStatus);
      }
      return fetchJson<KnowledgeRatingSuggestionsPayload>(
        `/api/knowledge-bases/${encodeURIComponent(activeKnowledgeBaseForItems)}/rating-suggestions?${params.toString()}`,
      );
    },
    enabled: forcedView === "knowledge" && Boolean(activeKnowledgeBaseForItems),
    refetchInterval: resolvePollingInterval(pageVisible, 45_000),
    refetchIntervalInBackground: false,
  });
  const permissionAuditQuery = useQuery({
    queryKey: queryKeys.knowledgePermissionAudit(""),
    queryFn: () => fetchJson<KnowledgePermissionAuditPayload>("/api/knowledge/permissions/audit"),
    enabled: forcedView === "knowledge",
    refetchInterval: resolvePollingInterval(pageVisible, 60_000),
    refetchIntervalInBackground: false,
  });
  const governanceTasksQuery = useQuery({
    queryKey: queryKeys.knowledgeGovernanceTasks("", "open"),
    queryFn: () => fetchJson<KnowledgeGovernanceTasksPayload>("/api/knowledge/governance/tasks?status=open"),
    enabled: forcedView === "knowledge",
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
    queryKey: queryKeys.knowledgeTrace(activeKnowledgeBaseForItems, traceTargetId),
    queryFn: () =>
      fetchJson<KnowledgeTracePayload>(
        `/api/knowledge-bases/${encodeURIComponent(activeKnowledgeBaseForItems)}/trace/${encodeURIComponent(traceTargetId)}`,
      ),
    enabled: forcedView === "knowledge" && Boolean(activeKnowledgeBaseForItems) && Boolean(traceTargetId),
    refetchInterval: false,
  });
  const knowledgeSearchResults = knowledgeSearchQuery.data?.results ?? [];
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
    flatVisibleItems.find(({ item }) => item.id === activeItemId) ?? flatVisibleItems[0] ?? null;
  const activeItem = activePair?.item ?? null;
  const activeSection = activePair?.section ?? null;
  const activeImpact = activeItem ? impactCopy(copy, activeItem) : null;
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
  const canCopyRawContent = Boolean(activeItem?.content);

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
    const next = buildMemorySearchParams(activeSectionId, activeItemId, activeFilter, activeManageFilter, activeChannel, searchText);
    if (next.toString() !== searchParamText) {
      setSearchParams(next, { replace: true });
    }
  }, [activeChannel, activeFilter, activeItemId, activeManageFilter, activeSectionId, searchParamText, searchText, setSearchParams]);

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
    setActiveItemId(flatVisibleItems[0]?.item.id ?? "");
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
    if (!activeKnowledgeBaseId || !knowledgeBases.some((base) => base.knowledgeBaseId === activeKnowledgeBaseId)) {
      setActiveKnowledgeBaseId(knowledgeBases[0].knowledgeBaseId);
    }
  }, [activeKnowledgeBaseId, knowledgeBases]);

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
    void queryClient.invalidateQueries({ queryKey: queryKeys.memoryOverview() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeOverview() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeGovernanceTasks("", "open") });
    void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeIngestionAdapters() });
    if (activeKnowledgeBaseForItems) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeItems(activeKnowledgeBaseForItems) });
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
    () => buildMemoryLink(activeSectionId, activeItemId, activeFilter, activeManageFilter, activeChannel, searchText),
    [activeChannel, activeFilter, activeItemId, activeManageFilter, activeSectionId, searchText],
  );
  const handleCopySourceSummary = async () => {
    if (!activeSection || !activeItem) {
      return;
    }
    try {
      await copyText(buildInspectionText(copy, activeSection, activeItem, currentUrl));
      setCopyFeedback({ tone: "success", text: `${copy.copySourceSummary} · ${copy.copyDone}` });
    } catch {
      setCopyFeedback({ tone: "error", text: `${copy.copySourceSummary} · ${copy.copyFailed}` });
    }
  };
  const handleCopySourcePath = async () => {
    if (!activeSection || !activeItem) {
      return;
    }
    const sourcePath = activeItem.path || activeItem.source || activeSection.sourcePath || "";
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
    if (!activeItem?.content) {
      return;
    }
    try {
      await copyText(activeItem.content);
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
  const startCreate = () => {
    setEditDraft(newCreateDraft());
    setActiveSectionId("user-managed-memory");
    setActiveItemId("");
  };
  const startEdit = () => {
    if (!activeSection || !activeItem) {
      return;
    }
    setEditDraft(draftFromItem(activeSection, activeItem));
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
    if (!activeSection || !activeItem || !activeItem.managedState?.deletable) {
      return;
    }
    deleteMemoryMutation.mutate({ sectionId: activeSection.id, itemId: activeItem.id });
  };
  const restoreActiveItem = () => {
    if (!activeSection || !activeItem || !activeItem.managedState?.restorable) {
      return;
    }
    restoreMemoryMutation.mutate({ sectionId: activeSection.id, itemId: activeItem.id });
  };
  const mutationBusy = memoryMutation.isPending || deleteMemoryMutation.isPending || restoreMemoryMutation.isPending || bulkActionPending !== null;
  const knowledgeBusy =
    sourceArtifactMutation.isPending
    || proposalMutation.isPending
    || ingestionMutation.isPending
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
      void queryClient.invalidateQueries({ queryKey: queryKeys.memoryOverview() });
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
  const submitSourceArtifact = () => {
    if (!activeKnowledgeBase) {
      return;
    }
    sourceArtifactMutation.mutate({ knowledgeBaseId: activeKnowledgeBase.knowledgeBaseId, draft: sourceDraft });
  };
  const submitRefinementProposal = () => {
    if (!activeKnowledgeBase || !proposalDraft.title.trim() || !proposalDraft.content.trim()) {
      setKnowledgeFeedback({ tone: "error", text: `${copy.mutationFailed}: ${copy.proposalTitle}` });
      return;
    }
    proposalMutation.mutate({ knowledgeBaseId: activeKnowledgeBase.knowledgeBaseId, draft: proposalDraft });
  };
  const submitIngestionPackage = () => {
    if (!activeKnowledgeBase || !ingestionDraft.sourceType.trim()) {
      setKnowledgeFeedback({ tone: "error", text: `${copy.mutationFailed}: ${copy.ingestionPackage}` });
      return;
    }
    ingestionMutation.mutate({ knowledgeBaseId: activeKnowledgeBase.knowledgeBaseId, draft: ingestionDraft });
  };
  const reviewProposal = (proposalId: string, status: "approved" | "rejected") => {
    if (!activeKnowledgeBase) {
      return;
    }
    reviewMutation.mutate({ knowledgeBaseId: activeKnowledgeBase.knowledgeBaseId, proposalId, status });
  };
  const updateKnowledgeRating = (item: KnowledgeItem) => {
    if (!activeKnowledgeBase) {
      return;
    }
    ratingMutation.mutate({ knowledgeBaseId: activeKnowledgeBase.knowledgeBaseId, item, draft: ratingDraft });
  };
  const reviewRatingSuggestion = (suggestionId: string, status: "applied" | "rejected") => {
    if (!activeKnowledgeBase) {
      return;
    }
    ratingSuggestionReviewMutation.mutate({ knowledgeBaseId: activeKnowledgeBase.knowledgeBaseId, suggestionId, status });
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
    if (!activeKnowledgeBase || !selectedVisibleRatingSuggestionIds.length) {
      return;
    }
    ratingSuggestionBulkReviewMutation.mutate({
      knowledgeBaseId: activeKnowledgeBase.knowledgeBaseId,
      suggestionIds: selectedVisibleRatingSuggestionIds,
      status,
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
          const active = item.id === activeItem?.id;
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
      <section className={styles.managementPanel} aria-label={copy.management}>
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
        <p>{copy.managementHint}</p>
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
          {activeItem && editDraft.mode === "edit" ? (
            <div className={styles.editPreviewGrid}>
              {[
                { label: copy.titleField, current: activeItem.title, draft: editDraft.title },
                { label: copy.summaryField, current: activeItem.summary, draft: editDraft.summary },
                { label: copy.contentField, current: activeItem.content, draft: editDraft.content },
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
    activeItem && activeSection && !editDraft ? (
      <section className={styles.managementPanel} aria-label={copy.management}>
        <div className={styles.managementHeader}>
          <div>
            <p className={styles.panelEyebrow}>{activeSection.title}</p>
            <h2>{activeItem.managedState?.userManaged ? copy.userManaged : activeItem.managedState?.overridden ? copy.overridden : copy.management}</h2>
          </div>
          <span className={styles.countPill}>
            {activeItem.managedState?.disabled
              ? copy.disabledByUser
              : activeItem.managedState?.userManaged
                ? copy.userManaged
                : activeItem.managedState?.overridden
                  ? copy.overridden
                  : copy.canUse}
          </span>
        </div>
        <p>{activeItem.managedState?.actionHint || copy.managementHint}</p>
        <div className={styles.selectedConfigSummary}>
          <strong>{activeItem.title}</strong>
          <p>{activeItem.summary || activeItem.content || copy.noContent}</p>
        </div>
        <div className={styles.managementActions}>
          <button
            type="button"
            className={styles.detailActionButton}
            onClick={startEdit}
            disabled={!activeItem.managedState?.editable || mutationBusy}
          >
            <Pencil size={15} />
            <span>{copy.editMemory}</span>
          </button>
          {activeItem.managedState?.restorable ? (
            <button type="button" className={styles.detailActionButton} onClick={restoreActiveItem} disabled={mutationBusy}>
              <Undo2 size={15} />
              <span>{copy.restoreMemory}</span>
            </button>
          ) : null}
          <button
            type="button"
            className={styles.detailActionButton}
            onClick={disableOrDeleteActiveItem}
            disabled={!activeItem.managedState?.deletable || mutationBusy}
          >
            <Trash2 size={15} />
            <span>{activeItem.managedState?.userManaged ? copy.deleteMemory : copy.disableMemory}</span>
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

      {activeItem && activeSection ? (
        <>
          <section className={styles.detailHeader}>
            <div>
              <p className={styles.panelEyebrow}>{activeSection.title}</p>
              <h2>{activeItem.title}</h2>
              <p>{activeItem.summary}</p>
            </div>
            <span className={statusClassName(activeItem.agentVisible, activeItem.inPrompt)}>
              {activeItem.inPrompt ? copy.inPrompt : activeItem.agentVisible ? copy.canUse : copy.manualOnly}
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
              <strong title={activeItem.path}>{activeItem.path || "-"}</strong>
            </section>
            <section>
              <span>{copy.sourceApi}</span>
              <strong title={activeSection.sourceApi}>{activeSection.sourceApi || "-"}</strong>
            </section>
            <section>
              <span>{copy.agentVisible}</span>
              <strong>{activeItem.agentVisible ? copy.yes : copy.no}</strong>
            </section>
            <section>
              <span>{copy.runtimeInjected}</span>
              <strong>{activeItem.inPrompt ? copy.yes : copy.no}</strong>
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
              {itemChannelPills(copy, activeItem).map((pill) => (
                <span key={`${activeItem.id}:channel:${pill.label}`} title={pill.hint}>
                  <CheckCircle2 size={13} />
                  {pill.label}
                </span>
              ))}
            </div>
            <div className={styles.usageList}>
              {activeItem.usedBy.map((usage) => (
                <span key={`${activeItem.id}:${usage}`}>
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
              <code>{activeItem.contentType}</code>
            </summary>
            {activeItem.content ? <pre data-language={contentLanguage(activeItem.contentType)}>{activeItem.content}</pre> : <p>{copy.noContent}</p>}
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
        <p className={styles.panelLead}>{copy.reviewQueueHint}</p>
        {renderReviewQueue()}
      </section>

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
              <p className={styles.panelLead}>{card.hint}</p>
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
          onClick={() => setActiveSectionId("")}
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
                onClick={() => setActiveSectionId(section.id)}
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
            <h2>{activeSection?.title ?? title}</h2>
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
              <h2>{copy.manageAllMemory}</h2>
              <span>{copy.manageListHint}</span>
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
          <p>{copy.manageConfigHint}</p>
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
      <section className={styles.pipelinePanel} aria-label={copy.platformPipeline}>
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
      <section className={styles.usageContractPanel} aria-label={copy.usageContract}>
        <div className={styles.managementHeader}>
          <div>
            <p className={styles.panelEyebrow}>{copy.usageContract}</p>
            <h2>{copy.memoryDomains}</h2>
          </div>
          <span className={styles.countPill}>{memoryUsageContract?.domains.length ?? 0}</span>
        </div>
        <div className={styles.contractPrinciples}>
          {(memoryUsageContract?.principles ?? []).slice(0, 5).map((principle) => (
            <span key={principle}>{principle}</span>
          ))}
        </div>
        <div className={styles.contractDomainGrid}>
          {(memoryUsageContract?.domains ?? []).map((domain) => (
            <section key={domain.domainId} className={styles.contractDomainRow}>
              <div>
                <strong>{domain.label}</strong>
                <small>{domain.owner} · {domain.storage}</small>
              </div>
              <span>{copy.allowedUse}: {domain.readsThrough.slice(0, 2).join(", ")}</span>
              <span>{copy.writeBoundary}: {domain.canCreateFormalKnowledge ? copy.reviewerRequired : domain.boundary}</span>
              <code>{domain.promptDefault}</code>
            </section>
          ))}
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
          {(memoryUsageContract?.forbiddenActions ?? []).slice(0, 6).map((action) => (
            <span key={action}>
              <XCircle size={13} />
              {action}
            </span>
          ))}
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
            <strong>{knowledgeSteward?.steward.taskProfile.mission || knowledgeSteward?.steward.displayName || copy.loading}</strong>
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
            <strong>{knowledgeSteward?.steward.permissionBoundary || "proposal_and_rating_suggestion_only"}</strong>
            <small>{knowledgeSteward?.operatingBoundary.formalKnowledgeRequiresReviewer ? copy.reviewerRequired : copy.noDirectApply}</small>
          </div>
        </div>
        <div className={styles.stewardToolRows}>
          <span>{copy.preferredTools}</span>
          {(knowledgeSteward?.steward.toolPolicy.preferredTools ?? []).slice(0, 4).map((tool) => (
            <code key={`preferred:${tool}`}>{tool}</code>
          ))}
          <span>{copy.allowedTools}</span>
          <small>{(knowledgeSteward?.steward.toolPolicy.allowedTools ?? []).join(", ") || "-"}</small>
        </div>
        <div className={styles.stewardRecommendations}>
          <div className={styles.stewardRecommendationHeader}>
            <span>{copy.stewardRecommendations}</span>
            <small>
              {knowledgeStewardRecommendationsQuery.data?.operatingBoundary.recommendationsOnly ? copy.recommendationsOnly : copy.stewardRecommendationHint}
            </small>
          </div>
          {knowledgeStewardRecommendations.map((recommendation) => (
            <section key={recommendation.recommendationId} className={styles.stewardRecommendationRow}>
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
          {!knowledgeStewardRecommendationsQuery.isPending && !knowledgeStewardRecommendations.length ? (
            <section className={styles.emptyDetail}>
              <CheckCircle2 size={20} />
              <strong>{copy.noIssues}</strong>
            </section>
          ) : null}
        </div>
        <div className={styles.stewardWorkbench}>
          <div className={styles.stewardRecommendationHeader}>
            <span>{copy.stewardWorkbench}</span>
            <small>{copy.reviewerRequired}</small>
          </div>
          <div className={styles.stewardStageGrid} aria-label={copy.stewardStages}>
            {(knowledgeStewardWorkbench?.stages ?? []).map((stage) => (
              <section key={stage.stageId} className={styles.stewardStageCard}>
                <div>
                  <span className={stage.status === "clear" ? styles.statusPillMuted : styles.statusPill}>{stage.status}</span>
                  <strong>{stage.title}</strong>
                </div>
                <p>{stage.description}</p>
                <small>
                  {copy.openGovernanceTasks}: {stage.openCount} · {copy.executable}: {stage.executableCount}
                </small>
                <code>{stage.nextTool}</code>
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
            {(knowledgeStewardWorkbench?.acceptanceChecklist ?? []).map((item) => (
              <span key={item.id}>
                <CheckCircle2 size={13} />
                {item.label}
              </span>
            ))}
          </div>
        </div>
      </section>
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
          <p className={styles.panelLead}>{copy.knowledgeHint}</p>
          <section className={styles.governanceMiniPanel} aria-label={copy.toolVisibility}>
            <strong>{copy.toolVisibility}</strong>
            {Object.values(permissionAudit?.tools ?? {}).map((tool) => (
              <span key={tool.toolName} className={tool.visible ? styles.statusPill : styles.statusPillMuted}>
                {tool.toolName}: {tool.visible ? copy.yes : tool.reason}
              </span>
            ))}
          </section>
          {knowledgeOverviewQuery.isPending ? <div className={styles.emptyState}>{copy.loading}</div> : null}
          {!knowledgeOverviewQuery.isPending && !knowledgeBases.length ? (
            <section className={styles.emptyDetail}>
              <Database size={22} />
              <strong>{copy.noKnowledgeBases}</strong>
            </section>
          ) : null}
          <nav className={styles.sourceList} aria-label={copy.knowledgeBases}>
            {knowledgeBases.map((base) => (
              <button
                key={base.knowledgeBaseId}
                type="button"
                className={base.knowledgeBaseId === activeKnowledgeBase?.knowledgeBaseId ? `${styles.sourceButton} ${styles.sourceButtonActive}` : styles.sourceButton}
                onClick={() => setActiveKnowledgeBaseId(base.knowledgeBaseId)}
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
            ))}
          </nav>
        </aside>

        <main className={styles.knowledgeMain}>
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
          </section>

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
              {!knowledgeOperationsHealthQuery.isPending && !(knowledgeOperationsHealth?.findings ?? []).length ? (
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
              {!knowledgeGovernancePlanQuery.isPending && !(knowledgeGovernancePlan?.actions ?? []).length ? (
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

          <section className={styles.managementPanel}>
            <div className={styles.managementHeader}>
              <div>
                <p className={styles.panelEyebrow}>{copy.ingestionPackage}</p>
                <h2>{copy.sourceArtifacts} + {copy.pendingProposals}</h2>
              </div>
              <button
                type="button"
                className={styles.primaryActionButton}
                onClick={submitIngestionPackage}
                disabled={!activeKnowledgeBase?.permissions.canPropose || knowledgeBusy}
              >
                <Link2 size={15} />
                <span>{copy.submitIngestionPackage}</span>
              </button>
            </div>
            <div className={styles.knowledgeFormGrid}>
              <label>
                <span>{copy.sourceType}</span>
                <select value={ingestionDraft.sourceType} onChange={(event) => setIngestionDraft({ ...ingestionDraft, sourceType: event.target.value })}>
                  {["external_search_refinement", "pdf_refinement", "team_chat_refinement", "runtime_evidence_refinement", "agent_authored", "manual_user_entry"].map((type) => (
                    <option key={type} value={type}>{type}</option>
                  ))}
                </select>
              </label>
              <label>
                <span>{copy.titleField}</span>
                <input value={ingestionDraft.sourceTitle} onChange={(event) => setIngestionDraft({ ...ingestionDraft, sourceTitle: event.target.value })} />
              </label>
              <label>
                <span>{copy.capturedBy}</span>
                <input value={ingestionDraft.proposedByAgentId} onChange={(event) => setIngestionDraft({ ...ingestionDraft, proposedByAgentId: event.target.value })} />
              </label>
              <label>
                <span>{copy.tags}</span>
                <input value={ingestionDraft.tags} onChange={(event) => setIngestionDraft({ ...ingestionDraft, tags: event.target.value })} />
              </label>
              <label className={styles.wideField}>
                <span>{copy.sourceRef}</span>
                <textarea rows={2} value={ingestionDraft.sourceRef} onChange={(event) => setIngestionDraft({ ...ingestionDraft, sourceRef: event.target.value })} />
              </label>
              <label className={styles.wideField}>
                <span>{copy.excerpt}</span>
                <textarea rows={3} value={ingestionDraft.excerpt} onChange={(event) => setIngestionDraft({ ...ingestionDraft, excerpt: event.target.value })} />
              </label>
              <label>
                <span>{copy.proposalTitle}</span>
                <input value={ingestionDraft.proposalTitle} onChange={(event) => setIngestionDraft({ ...ingestionDraft, proposalTitle: event.target.value })} />
              </label>
              <label>
                <span>{copy.summaryField}</span>
                <input value={ingestionDraft.proposalSummary} onChange={(event) => setIngestionDraft({ ...ingestionDraft, proposalSummary: event.target.value })} />
              </label>
              <label className={styles.wideField}>
                <span>{copy.proposalContent}</span>
                <textarea rows={4} value={ingestionDraft.proposalContent} onChange={(event) => setIngestionDraft({ ...ingestionDraft, proposalContent: event.target.value })} />
              </label>
            </div>
          </section>

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

          <section className={styles.managementPanel}>
            <div className={styles.managementHeader}>
              <div>
                <p className={styles.panelEyebrow}>{copy.sourceRegistration}</p>
                <h2>{activeKnowledgeBase?.name ?? copy.teamKnowledge}</h2>
              </div>
              <button
                type="button"
                className={styles.primaryActionButton}
                onClick={submitSourceArtifact}
                disabled={!activeKnowledgeBase?.permissions.canPropose || knowledgeBusy}
              >
                <Link2 size={15} />
                <span>{copy.submitSource}</span>
              </button>
            </div>
            <div className={styles.knowledgeFormGrid}>
              <label>
                <span>{copy.sourceType}</span>
                <select value={sourceDraft.sourceType} onChange={(event) => setSourceDraft({ ...sourceDraft, sourceType: event.target.value })}>
                  {["manual_user_entry", "team_chat_refinement", "external_search_refinement", "pdf_refinement", "agent_authored", "runtime_evidence_refinement"].map((type) => (
                    <option key={type} value={type}>{type}</option>
                  ))}
                </select>
              </label>
              <label>
                <span>{copy.titleField}</span>
                <input value={sourceDraft.title} onChange={(event) => setSourceDraft({ ...sourceDraft, title: event.target.value })} />
              </label>
              <label>
                <span>{copy.sourceCreatedAt}</span>
                <input value={sourceDraft.sourceCreatedAt} onChange={(event) => setSourceDraft({ ...sourceDraft, sourceCreatedAt: event.target.value })} />
              </label>
              <label>
                <span>{copy.capturedBy}</span>
                <input value={sourceDraft.capturedBy} onChange={(event) => setSourceDraft({ ...sourceDraft, capturedBy: event.target.value })} />
              </label>
              <label className={styles.wideField}>
                <span>{copy.sourceRef}</span>
                <textarea rows={3} value={sourceDraft.sourceRef} onChange={(event) => setSourceDraft({ ...sourceDraft, sourceRef: event.target.value })} />
              </label>
              <label className={styles.wideField}>
                <span>{copy.evidenceRange}</span>
                <textarea rows={2} value={sourceDraft.evidenceRange} onChange={(event) => setSourceDraft({ ...sourceDraft, evidenceRange: event.target.value })} />
              </label>
              <label className={styles.wideField}>
                <span>{copy.summaryField}</span>
                <textarea rows={2} value={sourceDraft.summary} onChange={(event) => setSourceDraft({ ...sourceDraft, summary: event.target.value })} />
              </label>
            </div>
          </section>

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
        </main>

        <aside className={styles.detailPanel}>
          <div className={styles.detailHeader}>
            <p className={styles.panelEyebrow}>{copy.formalKnowledge}</p>
            <h2>{activeKnowledgeBase?.name ?? copy.selectedMemory}</h2>
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

  return (
    <section className={styles.route}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>{copy.eyebrow}</p>
          <h1 className={styles.title}>{memoryViewLabel(copy, forcedView)}</h1>
          <p className={styles.subtitle}>{memoryViewSubtitle(copy, forcedView)}</p>
        </div>
        <button type="button" className={styles.refreshButton} onClick={refresh}>
          <RefreshCw size={16} />
          {copy.refresh}
        </button>
      </header>

      <div className={styles.controlStrip}>
        {renderSubnav()}
      </div>

      <div className={styles.viewStack}>
        {forcedView === "overview"
          ? renderOverviewView()
          : forcedView === "effective"
            ? renderEffectiveView()
            : forcedView === "manage"
              ? renderManageView()
              : forcedView === "knowledge"
                ? renderKnowledgeView()
                : renderSourcesView()}
      </div>
    </section>
  );
}
