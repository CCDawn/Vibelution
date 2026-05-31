import { useQuery, useQueryClient } from "@tanstack/react-query";
import CodeMirror from "@uiw/react-codemirror";
import {
  Blocks,
  ChevronRight,
  Database,
  ExternalLink,
  Image as ImageIcon,
  Languages,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  ShieldAlert,
  SlidersHorizontal,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { type CSSProperties, type PointerEvent as ReactPointerEvent, type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, type BlockerFunction, useBlocker } from "react-router-dom";
import { json } from "@codemirror/lang-json";
import { EditorView } from "@codemirror/view";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import {
  ConfigEditorMeta,
  ConfigEditorSection,
  ConfigDiscoveredModel,
  ConfigDraftMeta,
  ConfigLlmTestResult,
  ConfigModelDiscoveryResult,
  ConfigModelOption,
  ConfigModelPresetOption,
  ConfigWorkspace,
  AgentInstance,
  AgentModeBindings,
  HealthDiagnostics,
  HealthFinding,
  HealthQuickAction,
  LogHelper,
  PromptTemplateWorkspace,
  SessionHelper,
} from "../api/types";
import {
  applyModelOptionToProfileDraft,
  asRecord,
  avatarCropSourceRect,
  clonePublicConfig,
  collectModelDetailKeys,
  configInvalidationDomainsForApply,
  defaultModelApiKeyEnv,
  deriveConfigEditorSyncState,
  deriveModelCenterInventoryRows,
  deriveModelCenterSummary,
  groupConfigProfileCards,
  getString,
  clampAvatarCropOffset,
  groupModelPresets,
  hasPendingSecretChanges,
  modelLibraryIdFromParts,
  PROVIDER_KIND_OPTIONS,
  resolveConfigSectionUiStateOnSelect,
  resolveImageInputCapabilityStatus,
  resolveProfileDisplayState,
  shouldBlockConfigLeave,
  selectModelScenarioPresetId,
  type ConfigProfileModeGroupLabels,
  type ModelScenarioId,
  uniqueModelLibraryId,
  type ModelPresetGroupLabels,
  type PublicConfigShape,
} from "./configRouteLogic";
import { workbenchCodeMirrorTheme } from "../design/codeMirrorTheme";
import styles from "./ConfigRoute.module.css";

type ConfigLanguage = "zh" | "en";
type NoticeTone = "neutral" | "success" | "error";

type ProviderDraft = {
  kind: string;
  api_key_env: string;
  base_url: string;
  compat_mode: string;
  requires_api_key: boolean;
  context_window: string;
};

type ModelDetailsDraft = {
  transport: string;
  contract: string;
  reasoning_state_field: string;
  strict_compatibility: boolean;
  temperature: string;
  max_output_tokens: string;
  timeout: string;
  connect_timeout: string;
  streaming: boolean;
  tool_calling_mode: string;
  discovery_enabled: boolean;
};

type ModelEditorState = {
  mode: "create" | "edit";
  preset_id: string;
  model_id: string;
  label: string;
  model: string;
  api_key_env: string;
  api_key: string;
  clear_api_key: boolean;
  provider: ProviderDraft;
  details: ModelDetailsDraft;
};

type ProfileDraft = {
  profile_id: string;
  source_profile_id: string;
  model_id: string;
};

type ProfileEditState = {
  modelId: string;
};

type ConfigSectionUiState = {
  expanded: boolean;
  editing: boolean;
  expandedPaths: Record<string, boolean>;
  draftValue?: unknown;
};

type ConfigSidebarGroup = {
  id: string;
  title: string;
  summary: string;
  memberSectionIds: string[];
};

type LogHelperCopy = {
  healthTitle: string;
  healthBody: string;
  healthLoading: string;
  healthEmpty: string;
  healthRefresh: string;
  healthPriority: string;
  healthQuickActions: string;
  healthEvidence: string;
  healthRecommended: string;
  healthRelatedFindings: string;
  healthNoFindings: string;
  healthOpenLogs: string;
  healthOpenChat: string;
  healthOpenReset: string;
  healthOpen: string;
  healthFiles: string;
  healthDirs: string;
  healthSessions: string;
  healthBusy: string;
  healthFailed: string;
  healthStale: string;
  healthPhase: string;
  healthLatest: string;
  healthUpdated: string;
  healthSize: string;
  healthProtected: string;
  healthResetAvailable: string;
  healthStatusOk: string;
  healthStatusWarning: string;
  healthStatusBlocked: string;
  healthMissing: string;
  healthNotRecorded: string;
};

const SIDEBAR_WIDTH_STORAGE_KEY = "vibelution.config.sidebar.width";
const SIDEBAR_HEIGHT_STORAGE_KEY = "vibelution.config.sidebar.height";
const SIDEBAR_INDEX_COLLAPSED_STORAGE_KEY = "vibelution.config.sidebar.indexCollapsed";
const SIDEBAR_WIDTH_DEFAULT = 320;
const SIDEBAR_WIDTH_MIN = 280;
const SIDEBAR_WIDTH_MAX = 520;
const SIDEBAR_HEIGHT_MIN = 360;
const SIDEBAR_VIEWPORT_OFFSET = 28;

function clampValue(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function readStoredNumber(key: string): number | null {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = window.localStorage.getItem(key);
  if (!raw) {
    return null;
  }
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

function readStoredFlag(key: string): boolean | null {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = window.localStorage.getItem(key);
  if (raw == null) {
    return null;
  }
  if (raw === "1") {
    return true;
  }
  if (raw === "0") {
    return false;
  }
  return null;
}

function clampSidebarWidth(value: number, viewportWidth: number): number {
  const max = Math.max(
    SIDEBAR_WIDTH_MIN,
    Math.min(SIDEBAR_WIDTH_MAX, Math.floor(viewportWidth * 0.42), viewportWidth - 720),
  );
  return clampValue(value, SIDEBAR_WIDTH_MIN, max);
}

function clampSidebarHeight(value: number, viewportHeight: number): number {
  const max = Math.max(SIDEBAR_HEIGHT_MIN, viewportHeight - SIDEBAR_VIEWPORT_OFFSET);
  return clampValue(value, SIDEBAR_HEIGHT_MIN, max);
}

function defaultSectionUiState(): ConfigSectionUiState {
  return {
    expanded: true,
    editing: false,
    expandedPaths: {},
  };
}

export const CONFIG_COPY = {
  zh: {
    pageTitle: "统一配置工作台",
    subtitle: "这里是唯一配置网页入口。结构化编辑、完整配置检查和最终保存，都收口到同一份 config.toml。",
    loading: "正在加载统一配置工作区...",
    loadFailed: "配置工作区加载失败",
    sourceTitle: "保存与生效",
    sourceBody: "这里显示当前修改是否已经保存，以及哪些系统级设置需要重启后才会生效。",
    runtimeTitle: "运行时与界面",
    runtimeBody: "语言、默认入口和治理模式可以在这里修改，确认后页面会立即展示本次修改。",
    profilesTitle: "调用档案",
    profilesBody: "按业务分区查看每个大模型调用档案使用哪套模型、服务商和密钥；需要修改时先点编辑，确认后页面立即展示本次修改。",
    modelsTitle: "模型中心",
    modelsBody: "按服务商账号、模型库存、使用位置和密钥状态管理模型；新增或编辑会先进入本次修改，保存后写回 config.toml。",
    draftTitle: "高级配置检查",
    draftBody: "如果结构化面板不够用，可以直接检查整份当前配置；保存时仍只写 config.toml。",
    diagnosticsTitle: "诊断与保存",
    diagnosticsBody: "保存前会显示阻塞问题、警告和可能需要处理的动作。",
    configPath: "配置路径",
    configStatus: "当前状态",
    rawToml: "当前 config.toml",
    rawTomlHint: "这里只读显示真实文件内容；修改并保存后会更新这里。",
    syncedDraft: "已和 config.toml 一致",
    unsavedDraft: "有未保存修改",
    refresh: "重新读取",
    validateDraft: "检查当前修改",
    resetDraft: "还原编辑文本",
    openEnvironment: "打开系统环境变量",
    openEnvironmentHint: "会打开 Windows 系统窗口，方便你自己查看当前使用了哪些 key。",
    openEnvironmentPending: "正在打开系统环境变量",
    openEnvironmentOpened: "已打开系统环境变量窗口。",
    saveConfig: "保存到 config.toml",
    applying: "保存中",
    leaveGuardTitle: "还有未保存的设置",
    leaveGuardBody: "本次修改还没有保存到 config.toml。离开前要保存吗？",
    leaveGuardSave: "保存并离开",
    leaveGuardSaving: "保存后离开中",
    leaveGuardDiscard: "不保存离开",
    leaveGuardCancel: "取消",
    interfaceLanguage: "界面语言",
    intakeMode: "模式",
    languageChinese: "中文",
    languageEnglish: "English",
    groupOverviewSaveTitle: "总览与保存",
    groupOverviewSaveSummary: "查看保存状态、重新读取配置，并处理系统环境变量。",
    groupWorkbenchTitle: "工作台与界面",
    groupWorkbenchSummary: "默认入口、语言、前后端端口与重启后生效的工作台设置。",
    groupAvatarPetTitle: "用户、形象与陪伴体",
    groupAvatarPetSummary: "统一管理用户信息、形象、宠物与陪伴体相关配置。",
    groupModelingTitle: "模型中心",
    groupModelingSummary: "模型库、服务商账号、密钥、能力检测和模型发现都在这里集中管理。",
    groupProfileBindingsTitle: "调用档案",
    groupProfileBindingsSummary: "按对话、Agent、进化和科研分区管理 LLM 调用档案到模型库的绑定。",
    groupPromptTitle: "系统提示词",
    groupPromptSummary: "统一管理 agent 系统提示词组件、章节文件和功能提示词模板。",
    groupAgentEvolutionTitle: "Agent 与进化",
    groupAgentEvolutionSummary: "只保留 Agent 管理入口与进化/上下文系统配置，具体 Agent 绑定在 Agent 管理中维护。",
    groupToolingTitle: "工具与诊断",
    groupToolingSummary: "工具、网络、安全、日志、解析器与调试相关设置。",
    healthTitle: "健康诊断中心",
    healthBody: "把会话入口、日志入口、最近信号、可清理建议和保护边界整理到同一个只读诊断面。",
    healthLoading: "正在整理日志 Helper...",
    healthEmpty: "当前没有可用日志 Helper。",
    healthRefresh: "重新诊断",
    healthPriority: "优先处理",
    healthQuickActions: "快速入口",
    healthEvidence: "证据",
    healthRecommended: "建议",
    healthRelatedFindings: "关联问题",
    healthNoFindings: "当前没有阻塞或注意项。",
    healthOpenLogs: "打开日志页",
    healthOpenChat: "打开会话页",
    healthOpenReset: "去 Reset 清理",
    healthOpen: "打开",
    healthFiles: "文件",
    healthDirs: "目录",
    healthSessions: "会话",
    healthBusy: "运行中",
    healthFailed: "失败",
    healthStale: "缺时间",
    healthPhase: "阶段",
    healthLatest: "最近信号",
    healthUpdated: "更新时间",
    healthSize: "体量",
    healthProtected: "保护",
    healthResetAvailable: "可从 Reset 清理",
    healthStatusOk: "正常",
    healthStatusWarning: "注意",
    healthStatusBlocked: "阻塞",
    healthMissing: "暂无日志文件",
    healthNotRecorded: "未记录",
    settingsStatusTitle: "设置状态",
    settingsNextStep: "下一步",
    settingsCanSave: "可以保存",
    settingsNeedsCheck: "先检查高级配置",
    settingsSynced: "已同步",
    settingsSections: "分区",
    runtimeProfile: "运行档位",
    defaultMode: "默认模式",
    defaultRoute: "默认入口",
    modelLibrary: "模型库",
    profiles: "LLM 配置",
    profileAdd: "新增调用档案",
    profileId: "调用档案 ID",
    sourceProfile: "参考配置",
    assignModel: "模型",
    createProfile: "确认新增",
    profileTableModel: "当前模型",
    profileTableProvider: "服务商",
    profileTableKey: "Key 状态",
    profileTableActions: "连接",
    profileTableCurrent: "当前配置",
    profileTableStaged: "本次修改预览",
    profileGroupChat: "对话 / 主智能体",
    profileGroupSupport: "心智与压缩",
    profileGroupSubagents: "Agent 管理",
    profileGroupEvolution: "监督进化",
    profileGroupResearch: "科研 / Team",
    profileGroupOther: "其他调用档案",
    promptTemplateCenterTitle: "Agent 提示词中心",
    promptTemplateCenterBody: "提示词编辑已迁移到 Agent 管理，配置中心只保留当前模板和引用关系概览，避免双处编辑同一份 Agent 提示词。",
    promptTemplateCategory: "分类",
    promptTemplateSource: "来源",
    promptTemplateUsage: "引用 Agent",
    promptTemplateOpenCenter: "打开提示词中心",
    promptTemplateOpenResearch: "查看科研提示词",
    promptTemplateEmpty: "暂无提示词模板。",
    agentConfigCenterTitle: "Agent 管理入口",
    agentConfigCenterBody: "Agent 绑定、提示词、工具、记忆、私聊会话、工作区和模式成员关系已收口到 Agent 管理；配置页只保留只读引用概览。",
    openAgentManagement: "打开 Agent 管理",
    agentConfigRefs: "模式引用",
    agentConfigIsolation: "隔离资源",
    agentConfigRuns: "最近运行",
    agentConfigRunsOpen: "运行记录",
    agentConfigRunsLoading: "读取运行记录中",
    agentConfigRunsEmpty: "暂无运行记录。",
    agentConfigRunsFailed: "运行记录读取失败：",
    agentConfigSubRuns: "子任务",
    agentConfigStatus: "状态",
    agentConfigActive: "长期 Agent",
    agentConfigEmpty: "暂无长期 Agent。",
    modeBindingTitle: "模式里的 Agent 分配",
    modeBindingBody: "这里只读展示当前模式分配；修改默认 Agent、科研池、自进化和监督进化槽位请到 Agent 管理的成员关系中完成。",
    modeBindingMode: "模式",
    modeBindingSlot: "槽位",
    modeBindingBoundAgent: "绑定 Agent",
    modeBindingDefaultAgent: "默认 Agent",
    modeBindingChatAvailable: "可用于对话",
    modeBindingResearchPool: "科研池",
    modeBindingUpdating: "更新模式绑定中",
    modeBindingUpdated: "模式绑定已更新。",
    modeBindingUpdateFailed: "模式绑定更新失败：",
    researchAgentPoolTitle: "Agent 使用情况摘要",
    researchAgentPoolBody: "Agent 引用详情已收口到 Agent 管理；这里仅保留调用档案到模型库的绑定。",
    researchAgentAdd: "新增科研 Agent",
    researchAgentKey: "Agent Key",
    researchAgentName: "名称",
    researchAgentInstance: "绑定 Agent",
    researchAgentSession: "私聊会话",
    researchAgentWorkspace: "工作区",
    researchAgentUnlinked: "等待同步",
    researchAgentPrompt: "提示词模板",
    researchAgentTemplate: "Agent 类型",
    researchAgentLlm: "模型配置",
    researchAgentEnabled: "启用",
    researchAgentSave: "保存 Agent",
    researchAgentDelete: "删除",
    researchAgentEmpty: "暂无科研 Agent。",
    researchAgentBusy: "保存科研 Agent 中",
    researchAgentDeleteBlocked: "删除失败：",
    llmConfigMissing: "未找到对应 LLM 配置",
    modelEditorCreate: "新增模型",
    modelEditorEdit: "编辑模型",
    modelCenterAccounts: "服务商账号",
    modelCenterInventory: "模型库存",
    modelCenterUsage: "使用位置",
    modelCenterHealth: "状态",
    modelCenterModels: "模型",
    modelCenterBindings: "调用位置",
    modelCenterIssues: "异常",
    modelCenterSource: "来源",
    modelCenterAccountModels: "模型",
    modelCenterAccountKey: "密钥",
    modelCenterAccountHost: "地址",
    modelCenterNoUsage: "暂未被使用",
    modelCenterUsageCount: "处使用",
    modelCenterUsageMore: "更多",
    modelCenterUnresolvedUsage: "有使用位置指向了不存在的模型",
    modelScenario: "新增方式",
    modelScenarioChat: "聊天 Agent",
    modelScenarioRelay: "中转站模型",
    modelScenarioImage: "图片工具模型",
    modelScenarioLocal: "本地模型",
    modelScenarioManual: "高级手填",
    modelScenarioHint: "选择场景会自动套用最接近的模板；服务商、模型名和密钥仍可以在下方调整。",
    image2ToolUsage: "image2 生图工具",
    preset: "预设",
    presetGroupOfficial: "官方供应商",
    presetGroupRelay: "Relay Responses",
    presetGroupOpenAiCompatible: "OpenAI 兼容 API",
    presetGroupLocal: "本地模型",
    customEntry: "手填",
    autoValue: "自动生成",
    modelId: "模型 ID",
    label: "显示名",
    modelName: "模型名",
    discoverModels: "发现模型",
    discoveryPending: "发现模型中",
    discoveredModel: "发现结果",
    discoveryEmpty: "没有发现可用模型",
    discoveryFailed: "模型发现失败",
    providerKind: "服务商类型",
    providerKeyEnv: "服务商密钥变量名",
    modelKeyEnv: "模型密钥变量名",
    modelKeyInput: "API Key",
    keyStorageHint: "填写后先进入本次修改；点击“保存到 config.toml”时才会写入本机用户级环境变量。",
    keyEnvAdvancedHint: "变量名会自动生成。只有要复用已有环境变量，或需要精确控制变量名时再改。",
    deleteModelHint: "删除模型只移除配置项，不会删除系统环境变量。要清除密钥，请先编辑模型并勾选清除密钥。",
    keyLocation: "密钥存放位置",
    keyLocationHint: "这是系统环境变量名，不是要填写的 API Key。",
    baseUrl: "基础地址",
    compatMode: "兼容模式",
    contextWindow: "上下文窗口",
    requiresApiKey: "需要 API Key",
    transport: "传输协议",
    contract: "交互契约",
    reasoningStateField: "推理状态字段",
    toolCallingMode: "工具调用",
    strictCompatibility: "严格兼容",
    streaming: "流式",
    discoveryEnabled: "发现能力",
    temperature: "温度",
    maxOutputTokens: "最大输出令牌数",
    timeout: "超时（秒）",
    connectTimeout: "连接超时（秒）",
    pendingSecret: "待写入新密钥",
    clearSecret: "保存时同时清除这个环境变量里的密钥",
    saveModel: "确认模型修改",
    deleteModel: "删除模型",
    cancelEditing: "清空表单",
    profileCards: "当前模型",
    testConnection: "测试连接",
    testImageInput: "检测图像输入",
    checkAllImageCapabilities: "检测全部图像输入",
    checkModelImageCapability: "检测图像输入",
    imageCapabilityCheckPending: "检测模型能力中",
    imageCapabilityStatus: "图像能力",
    imageInputStatusUnknown: "图像未检测",
    imageInputStatusSupported: "支持图像输入",
    imageInputStatusUnsupported: "不支持图像输入",
    imageInputStatusFailed: "检测失败",
    imageInputUnsupportedHint: "当前模型不能接收图片作为聊天输入，请切换视觉模型或改用图片生成工具。",
    selectedModel: "使用模型",
    editProfiles: "编辑调用档案",
    saveProfileBatch: "确认调用档案",
    cancelProfileBatch: "取消编辑",
    testSelectedModel: "测试当前内容",
    profileSavePendingInline: "保存调用档案修改中",
    profilePrepared: "已准备好新增调用档案",
    profilePreparedHint: "可以在这里新增调用档案。确认后页面会立即展示本次修改，保存后写入 config.toml。",
    currentRoute: "当前配置",
    stagedRoute: "本次修改预览",
    apiKeySource: "密钥来源",
    profileDraftSaved: "本次修改已更新，保存到 config.toml 后生效。",
    routeSummary: "路由信息",
    expandSection: "展开内容",
    collapseSection: "收起内容",
    keyConfigured: "已配置",
    keyPending: "待写入",
    keyClearPending: "待清除",
    keyMissing: "缺失",
    sourceLibrary: "模型库",
    sourceProfileGenerated: "来自当前 LLM 配置",
    requiredModelMissing: "未设置可用模型",
    noBlocking: "当前没有阻塞问题。",
    noWarnings: "当前没有警告。",
    noSuggestions: "当前没有额外建议动作。",
    blockingIssues: "阻塞问题",
    warningSignals: "警告信号",
    suggestedActions: "建议动作",
    editorDirtyHint: "编辑文本有未检查改动。先检查当前修改，再继续结构化编辑或测试。",
    editorCleanHint: "当前结构化面板和编辑文本一致。",
    editorRestoreHint: "放弃编辑文本里的未检查内容，并回到当前结构化面板。",
    saveSourceHint: "当前修改还没写入 config.toml，保存成功后这里会刷新为最新文件状态。",
    modelSavePending: "保存模型修改中",
    modelSaveFailed: "模型修改未生效：",
    modelEditorAdvancedTitle: "高级参数",
    modelEditorAdvancedHint: "常用字段已经在上方，只有需要时再展开这里。",
    profileSavePending: "保存调用档案修改中",
    gitCommitModelUsage: "Git 提交模型",
    testPending: "测试连接中",
    imageInputTestPending: "检测图像输入中",
    testScopeDraft: "按当前修改测试",
    testScopeSaved: "按已保存配置测试",
    testRouteLabel: "测试路由",
    testRuntimeLabel: "运行路径",
    testKeyLabel: "API key",
    testKeyNotRequired: "当前路由不要求",
    testKeySourceLabel: "来源",
    testCapabilityLabel: "能力",
    validationPending: "检查修改中",
    refreshPending: "重新读取中",
    editSection: "编辑分区",
    saveSection: "确认分区修改",
    cancelSection: "取消编辑",
    sectionSavePending: "保存分区修改中",
    uploadAvatarImage: "上传本地图片",
    clearAvatarImage: "清除图片",
    avatarImageUploading: "上传头像图片中",
    avatarImageUploadFailed: "头像图片上传失败：",
    avatarCropTitle: "裁剪头像",
    avatarCropHint: "拖动图片调整位置，使用滑杆缩放；确认后会保存 1:1 裁剪结果。",
    avatarCropZoom: "缩放",
    avatarCropConfirm: "确认裁剪",
    avatarCropCancel: "取消裁剪",
    avatarCropPreview: "头像预览",
    closePanel: "关闭",
    fieldCountLabel: "字段",
    emptyValue: "空",
    itemLabel: "条目",
    yes: "是",
    no: "否",
  },
  en: {
    pageTitle: "Unified Config Workbench",
    subtitle: "This is the single config web entry. Structured editing, full-config checks, and final writes converge on one config.toml.",
    loading: "Loading unified config workspace...",
    loadFailed: "Failed to load config workspace",
    sourceTitle: "Save and Apply",
    sourceBody: "Shows whether current changes are saved and which system-level settings take effect after restart.",
    runtimeTitle: "Runtime and Interface",
    runtimeBody: "Language, default route, and governance mode changes are shown here immediately after confirmation.",
    profilesTitle: "Call Profiles",
    profilesBody: "Review model, provider, and key bindings by business area. Click edit, then confirm to update the page immediately.",
    modelsTitle: "Model Center",
    modelsBody: "Manage model providers, inventory, usage, and key health together. Changes are staged first and saved to config.toml when you apply.",
    draftTitle: "Advanced Config Check",
    draftBody: "When the structured panel is not enough, check the full current config here. Saving still writes only config.toml.",
    diagnosticsTitle: "Diagnostics and Save",
    diagnosticsBody: "Blocking issues, warnings, and suggested actions stay visible before saving.",
    configPath: "Config path",
    configStatus: "Current status",
    rawToml: "Current config.toml",
    rawTomlHint: "This is a read-only view of the real file. It refreshes after you save changes.",
    syncedDraft: "Matches config.toml",
    unsavedDraft: "Unsaved changes",
    refresh: "Reload",
    validateDraft: "Check changes",
    resetDraft: "Restore editor text",
    openEnvironment: "Open system environment variables",
    openEnvironmentHint: "Opens the Windows system dialog so you can inspect which keys are in use.",
    openEnvironmentPending: "Opening system environment variables",
    openEnvironmentOpened: "System environment variables window opened.",
    saveConfig: "Save to config.toml",
    applying: "Saving",
    leaveGuardTitle: "Unsaved settings",
    leaveGuardBody: "These changes have not been saved to config.toml. Save before leaving?",
    leaveGuardSave: "Save and leave",
    leaveGuardSaving: "Saving before leaving",
    leaveGuardDiscard: "Leave without saving",
    leaveGuardCancel: "Cancel",
    interfaceLanguage: "Interface language",
    intakeMode: "Mode",
    languageChinese: "Chinese",
    languageEnglish: "English",
    groupOverviewSaveTitle: "Overview and Save",
    groupOverviewSaveSummary: "Review save status, reload config, and open system environment variables.",
    groupWorkbenchTitle: "Workbench and Interface",
    groupWorkbenchSummary: "Default entry, language, frontend/backend ports, and workbench settings that apply after restart.",
    groupAvatarPetTitle: "User, Avatar, and Companion",
    groupAvatarPetSummary: "Manage user info, avatar, pet, and companion-facing settings together.",
    groupModelingTitle: "Model Center",
    groupModelingSummary: "Manage model inventory, provider accounts, keys, capability checks, and discovery in one place.",
    groupProfileBindingsTitle: "Call Profiles",
    groupProfileBindingsSummary: "Map LLM call profiles to model library entries by chat, Agent, evolution, and research areas.",
    groupPromptTitle: "System Prompts",
    groupPromptSummary: "Manage agent prompt components, section files, and feature prompt templates in one place.",
    groupAgentEvolutionTitle: "Agent and Evolution",
    groupAgentEvolutionSummary: "Keep only the Agent management entry plus evolution/context system settings here; edit Agent bindings in Agent management.",
    groupToolingTitle: "Tooling and Diagnostics",
    groupToolingSummary: "Tooling, network, security, logging, parser, and debug settings.",
    healthTitle: "Health Diagnostics Center",
    healthBody: "Organizes session entry points, log entry points, recent signals, cleanup hints, and protected boundaries in one read-only diagnostic surface.",
    healthLoading: "Organizing log helpers...",
    healthEmpty: "No log helpers are available right now.",
    healthRefresh: "Run again",
    healthPriority: "Top findings",
    healthQuickActions: "Quick actions",
    healthEvidence: "Evidence",
    healthRecommended: "Recommendation",
    healthRelatedFindings: "Related findings",
    healthNoFindings: "No blocked or warning findings.",
    healthOpenLogs: "Open logs",
    healthOpenChat: "Open chat",
    healthOpenReset: "Open Reset",
    healthOpen: "Open",
    healthFiles: "files",
    healthDirs: "dirs",
    healthSessions: "sessions",
    healthBusy: "busy",
    healthFailed: "failed",
    healthStale: "stale",
    healthPhase: "phase",
    healthLatest: "Latest signal",
    healthUpdated: "Updated",
    healthSize: "Size",
    healthProtected: "Protected",
    healthResetAvailable: "Reset cleanup available",
    healthStatusOk: "OK",
    healthStatusWarning: "Attention",
    healthStatusBlocked: "Blocked",
    healthMissing: "No log files yet",
    healthNotRecorded: "Not recorded",
    settingsStatusTitle: "Settings status",
    settingsNextStep: "Next step",
    settingsCanSave: "Ready to save",
    settingsNeedsCheck: "Check advanced config first",
    settingsSynced: "Synced",
    settingsSections: "Sections",
    runtimeProfile: "Runtime mode",
    defaultMode: "Default mode",
    defaultRoute: "Default route",
    modelLibrary: "Model library",
    profiles: "LLM configs",
    profileAdd: "Add call profile",
    profileId: "Call profile ID",
    sourceProfile: "Based on config",
    assignModel: "Model",
    createProfile: "Confirm",
    profileTableModel: "Current model",
    profileTableProvider: "Provider",
    profileTableKey: "Key status",
    profileTableActions: "Connection",
    profileTableCurrent: "Current config",
    profileTableStaged: "Change preview",
    profileGroupChat: "Chat / primary agent",
    profileGroupSupport: "Mental and compression",
    profileGroupSubagents: "Agent management",
    profileGroupEvolution: "Supervised evolution",
    profileGroupResearch: "Research / Team",
    profileGroupOther: "Other call profiles",
    promptTemplateCenterTitle: "Agent prompt center",
    promptTemplateCenterBody: "Prompt editing has moved to Agent management. Config keeps the current template and usage overview only, so the same Agent prompt is not edited in two places.",
    promptTemplateCategory: "Category",
    promptTemplateSource: "Source",
    promptTemplateUsage: "Linked agents",
    promptTemplateOpenCenter: "Open prompt center",
    promptTemplateOpenResearch: "View research prompts",
    promptTemplateEmpty: "No prompt templates yet.",
    agentConfigCenterTitle: "Agent management entry",
    agentConfigCenterBody: "Agent bindings, prompts, tools, memory, direct sessions, workspaces, and mode membership now live in Agent management. Config keeps only a read-only reference overview.",
    openAgentManagement: "Open Agent management",
    agentConfigRefs: "Mode refs",
    agentConfigIsolation: "Isolation",
    agentConfigRuns: "Recent runs",
    agentConfigRunsOpen: "Run history",
    agentConfigRunsLoading: "Loading run history",
    agentConfigRunsEmpty: "No runs recorded yet.",
    agentConfigRunsFailed: "Run history load failed: ",
    agentConfigSubRuns: "Subtasks",
    agentConfigStatus: "Status",
    agentConfigActive: "Long-lived Agents",
    agentConfigEmpty: "No long-lived agents yet.",
    modeBindingTitle: "Agent assignments by mode",
    modeBindingBody: "This is a read-only view of current mode assignments. Edit the chat default agent, research pool, self-evolution roles, and supervised-evolution slots in Agent management.",
    modeBindingMode: "Mode",
    modeBindingSlot: "Slot",
    modeBindingBoundAgent: "Bound agent",
    modeBindingDefaultAgent: "Default agent",
    modeBindingChatAvailable: "Chat available",
    modeBindingResearchPool: "Research pool",
    modeBindingUpdating: "Updating mode binding",
    modeBindingUpdated: "Mode binding updated.",
    modeBindingUpdateFailed: "Mode binding update failed: ",
    researchAgentPoolTitle: "Agent usage summary",
    researchAgentPoolBody: "Agent reference details now live in Agent management. Config only keeps call-profile to model-library bindings here.",
    researchAgentAdd: "Add research agent",
    researchAgentKey: "Agent key",
    researchAgentName: "Name",
    researchAgentInstance: "Bound agent",
    researchAgentSession: "Direct session",
    researchAgentWorkspace: "Workspace",
    researchAgentUnlinked: "Pending sync",
    researchAgentPrompt: "Prompt template",
    researchAgentTemplate: "Agent type",
    researchAgentLlm: "Model config",
    researchAgentEnabled: "Enabled",
    researchAgentSave: "Save agent",
    researchAgentDelete: "Delete",
    researchAgentEmpty: "No research agents yet.",
    researchAgentBusy: "Saving research agent",
    researchAgentDeleteBlocked: "Delete failed: ",
    llmConfigMissing: "LLM config not found",
    modelEditorCreate: "Create model",
    modelEditorEdit: "Edit model",
    modelCenterAccounts: "Provider accounts",
    modelCenterInventory: "Model inventory",
    modelCenterUsage: "Usage",
    modelCenterHealth: "Health",
    modelCenterModels: "Models",
    modelCenterBindings: "Bindings",
    modelCenterIssues: "Issues",
    modelCenterSource: "Source",
    modelCenterAccountModels: "models",
    modelCenterAccountKey: "key",
    modelCenterAccountHost: "host",
    modelCenterNoUsage: "not used yet",
    modelCenterUsageCount: "uses",
    modelCenterUsageMore: "more",
    modelCenterUnresolvedUsage: "Some usages point to a missing model",
    modelScenario: "Add as",
    modelScenarioChat: "Chat agent",
    modelScenarioRelay: "Relay model",
    modelScenarioImage: "Image tool model",
    modelScenarioLocal: "Local model",
    modelScenarioManual: "Advanced manual",
    modelScenarioHint: "The scenario picks the closest template. Provider, model name, and key can still be adjusted below.",
    image2ToolUsage: "image2 image tool",
    preset: "Preset",
    presetGroupOfficial: "Official providers",
    presetGroupRelay: "Relay Responses",
    presetGroupOpenAiCompatible: "OpenAI-compatible APIs",
    presetGroupLocal: "Local models",
    customEntry: "Manual",
    autoValue: "Auto",
    modelId: "Model ID",
    label: "Label",
    modelName: "Model",
    discoverModels: "Discover models",
    discoveryPending: "Discovering models",
    discoveredModel: "Discovered model",
    discoveryEmpty: "No models discovered",
    discoveryFailed: "Model discovery failed",
    providerKind: "Provider kind",
    providerKeyEnv: "Provider key variable",
    modelKeyEnv: "Model key variable",
    modelKeyInput: "API key",
    keyStorageHint: "This is staged first. It is written to the local user environment only when you save to config.toml.",
    keyEnvAdvancedHint: "Variable names are generated automatically. Edit them only when reusing an existing env var or controlling the exact name.",
    deleteModelHint: "Deleting a model only removes the config entry. It does not delete the system environment variable. Edit the model and enable key clearing first if needed.",
    keyLocation: "Key storage",
    keyLocationHint: "This is the system environment variable name, not the API key value.",
    baseUrl: "Base URL",
    compatMode: "Compat mode",
    contextWindow: "Context window",
    requiresApiKey: "Requires API key",
    transport: "Transport",
    contract: "Contract",
    reasoningStateField: "Reasoning state field",
    toolCallingMode: "Tool calling",
    strictCompatibility: "Strict compatibility",
    streaming: "Streaming",
    discoveryEnabled: "Discovery enabled",
    temperature: "Temperature",
    maxOutputTokens: "Max output tokens",
    timeout: "Timeout (s)",
    connectTimeout: "Connect timeout (s)",
    pendingSecret: "Pending new secret",
    clearSecret: "Also clear this environment key on save",
    saveModel: "Confirm model changes",
    deleteModel: "Delete model",
    cancelEditing: "Clear form",
    profileCards: "Current models",
    testConnection: "Test connection",
    testImageInput: "Check image input",
    checkAllImageCapabilities: "Check all image input",
    checkModelImageCapability: "Check image input",
    imageCapabilityCheckPending: "Checking model capabilities",
    imageCapabilityStatus: "Image capability",
    imageInputStatusUnknown: "Image not checked",
    imageInputStatusSupported: "Supports image input",
    imageInputStatusUnsupported: "No image input",
    imageInputStatusFailed: "Check failed",
    imageInputUnsupportedHint: "This model cannot receive images in chat. Switch to a vision model or use the image generation tool.",
    selectedModel: "Model",
    editProfiles: "Edit call profiles",
    saveProfileBatch: "Confirm call profiles",
    cancelProfileBatch: "Cancel editing",
    testSelectedModel: "Test current values",
    profileSavePendingInline: "Saving call profile changes",
    profilePrepared: "Call profile is ready",
    profilePreparedHint: "Add a new call profile here. Confirm updates the page immediately; saving writes config.toml.",
    currentRoute: "Current values",
    stagedRoute: "Change preview",
    apiKeySource: "API key source",
    profileDraftSaved: "Changes are ready. Save to config.toml to persist them.",
    routeSummary: "Route details",
    expandSection: "Expand",
    collapseSection: "Collapse",
    keyConfigured: "configured",
    keyPending: "pending",
    keyClearPending: "clear pending",
    keyMissing: "missing",
    sourceLibrary: "model library",
    sourceProfileGenerated: "from current LLM config",
    requiredModelMissing: "No usable model selected",
    noBlocking: "No blocking issues right now.",
    noWarnings: "No warnings right now.",
    noSuggestions: "No extra suggested actions right now.",
    blockingIssues: "Blocking issues",
    warningSignals: "Warnings",
    suggestedActions: "Suggested actions",
    editorDirtyHint: "The editor text has unchecked changes. Check them before more structured edits or tests.",
    editorCleanHint: "Structured controls and editor text are in sync.",
    editorRestoreHint: "Discard unchecked editor text and return to the current structured panel.",
    saveSourceHint: "Save to config.toml to persist the current changes.",
    modelSavePending: "Saving model changes",
    modelSaveFailed: "Model changes were not applied:",
    modelEditorAdvancedTitle: "Advanced parameters",
    modelEditorAdvancedHint: "The common fields are above. Expand this only when needed.",
    profileSavePending: "Saving call profile changes",
    gitCommitModelUsage: "Git commit model",
    testPending: "Testing connection",
    imageInputTestPending: "Checking image input",
    testScopeDraft: "Testing current changes",
    testScopeSaved: "Testing saved config",
    testRouteLabel: "Route",
    testRuntimeLabel: "Runtime path",
    testKeyLabel: "API key",
    testKeyNotRequired: "not required for this route",
    testKeySourceLabel: "source",
    testCapabilityLabel: "Capability",
    validationPending: "Checking changes",
    refreshPending: "Reloading",
    editSection: "Edit section",
    saveSection: "Confirm section changes",
    cancelSection: "Cancel editing",
    sectionSavePending: "Saving section changes",
    uploadAvatarImage: "Upload local image",
    clearAvatarImage: "Clear image",
    avatarImageUploading: "Uploading avatar image",
    avatarImageUploadFailed: "Avatar image upload failed: ",
    avatarCropTitle: "Crop avatar",
    avatarCropHint: "Drag the image to reposition it and use the slider to zoom. Confirm saves a 1:1 crop.",
    avatarCropZoom: "Zoom",
    avatarCropConfirm: "Confirm crop",
    avatarCropCancel: "Cancel crop",
    avatarCropPreview: "Avatar preview",
    closePanel: "Close",
    fieldCountLabel: "fields",
    emptyValue: "Empty",
    itemLabel: "Item",
    yes: "Yes",
    no: "No",
  },
} as const;

type ConfigCopy = Record<keyof (typeof CONFIG_COPY)["zh"], string>;

function emptyDraftMeta(): ConfigDraftMeta {
  return {
    pending_api_keys: {},
    pending_cleared_api_keys: [],
  };
}

function emptyProviderDraft(): ProviderDraft {
  return {
    kind: "openai_compatible",
    api_key_env: "",
    base_url: "",
    compat_mode: "openai",
    requires_api_key: true,
    context_window: "",
  };
}

function emptyModelDetailsDraft(): ModelDetailsDraft {
  return {
    transport: "chat_completions",
    contract: "tool_chat",
    reasoning_state_field: "",
    strict_compatibility: false,
    temperature: "",
    max_output_tokens: "",
    timeout: "",
    connect_timeout: "",
    streaming: true,
    tool_calling_mode: "auto",
    discovery_enabled: true,
  };
}

function emptyModelEditorState(): ModelEditorState {
  return {
    mode: "create",
    preset_id: "",
    model_id: "",
    label: "",
    model: "",
    api_key_env: "",
    api_key: "",
    clear_api_key: false,
    provider: emptyProviderDraft(),
    details: emptyModelDetailsDraft(),
  };
}

function buildConfigSidebarGroups(copy: ConfigCopy): ConfigSidebarGroup[] {
  return [
    {
      id: "overview-apply",
      title: copy.groupOverviewSaveTitle,
      summary: copy.groupOverviewSaveSummary,
      memberSectionIds: ["overview", "draft", "diagnostics"],
    },
    {
      id: "workbench-interface",
      title: copy.groupWorkbenchTitle,
      summary: copy.groupWorkbenchSummary,
      memberSectionIds: ["shell", "runtime", "workbench", "ui"],
    },
    {
      id: "avatar-pet",
      title: copy.groupAvatarPetTitle,
      summary: copy.groupAvatarPetSummary,
      memberSectionIds: ["user-profile", "avatar", "pet"],
    },
    {
      id: "models-profiles",
      title: copy.groupModelingTitle,
      summary: copy.groupModelingSummary,
      memberSectionIds: ["models", "llm-discovery"],
    },
    {
      id: "profile-bindings",
      title: copy.groupProfileBindingsTitle,
      summary: copy.groupProfileBindingsSummary,
      memberSectionIds: ["profiles"],
    },
    {
      id: "system-prompts",
      title: copy.groupPromptTitle,
      summary: copy.groupPromptSummary,
      memberSectionIds: ["prompt"],
    },
    {
      id: "agent-evolution",
      title: copy.groupAgentEvolutionTitle,
      summary: copy.groupAgentEvolutionSummary,
      memberSectionIds: ["agent", "context-compression", "memory", "strategy", "analysis", "evolution"],
    },
    {
      id: "tooling-diagnostics",
      title: copy.groupToolingTitle,
      summary: copy.groupToolingSummary,
      memberSectionIds: ["health-diagnostics", "tools", "git-commit-profile", "git-commit-prompt", "security", "network", "log", "parser", "debug"],
    },
  ];
}

function emptyProfileDraft(sourceProfileId = "primary"): ProfileDraft {
  return {
    profile_id: "",
    source_profile_id: sourceProfileId,
    model_id: "",
  };
}

function emptyProfileEditState(modelId = ""): ProfileEditState {
  return {
    modelId,
  };
}

function formatJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function readableErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function formatBytes(size: number) {
  if (!Number.isFinite(size) || size <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB"];
  let value = size;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatTimestamp(value: string, lang: ConfigLanguage, emptyLabel: string) {
  const text = String(value || "").trim();
  if (!text) {
    return emptyLabel;
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

function getBoolean(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function getDraftLanguage(config: PublicConfigShape | null, fallback: ConfigLanguage): ConfigLanguage {
  const ui = asRecord(config?.ui);
  return ui.language === "en" ? "en" : fallback;
}

function buildProviderDraft(providerInput: Record<string, unknown>): ProviderDraft {
  return {
    kind: getString(providerInput.kind),
    api_key_env: getString(providerInput.api_key_env),
    base_url: getString(providerInput.base_url),
    compat_mode: getString(providerInput.compat_mode) || "openai",
    requires_api_key: getBoolean(providerInput.requires_api_key, true),
    context_window: getString(providerInput.context_window),
  };
}

function buildModelDetailsDraft(detailsInput: Record<string, unknown>): ModelDetailsDraft {
  return {
    transport: getString(detailsInput.transport) || "chat_completions",
    contract: getString(detailsInput.contract) || "tool_chat",
    reasoning_state_field: getString(detailsInput.reasoning_state_field),
    strict_compatibility: getBoolean(detailsInput.strict_compatibility, false),
    temperature: getString(detailsInput.temperature),
    max_output_tokens: getString(detailsInput.max_output_tokens),
    timeout: getString(detailsInput.timeout),
    connect_timeout: getString(detailsInput.connect_timeout),
    streaming: getBoolean(detailsInput.streaming, true),
    tool_calling_mode: getString(detailsInput.tool_calling_mode) || "auto",
    discovery_enabled: getBoolean(detailsInput.discovery_enabled, true),
  };
}

function hydrateModelEditorFromOption(option: ConfigModelOption): ModelEditorState {
  return {
    mode: "edit",
    preset_id: "",
    model_id: option.model_id,
    label: option.label,
    model: option.model,
    api_key_env: option.api_key_env,
    api_key: "",
    clear_api_key: false,
    provider: buildProviderDraft(asRecord(option.provider)),
    details: buildModelDetailsDraft(asRecord(option.details)),
  };
}

function buildProviderPayload(draft: ProviderDraft): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    kind: draft.kind.trim(),
    api_key_env: draft.api_key_env.trim(),
    base_url: draft.base_url.trim(),
    compat_mode: draft.compat_mode.trim(),
    requires_api_key: draft.requires_api_key,
  };
  if (draft.context_window.trim()) {
    payload.context_window = Number(draft.context_window.trim());
  }
  return payload;
}

function buildModelDetailsPayload(draft: ModelDetailsDraft): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    strict_compatibility: draft.strict_compatibility,
    streaming: draft.streaming,
    discovery_enabled: draft.discovery_enabled,
  };
  if (draft.transport.trim()) {
    payload.transport = draft.transport.trim();
  }
  if (draft.contract.trim()) {
    payload.contract = draft.contract.trim();
  }
  if (draft.reasoning_state_field.trim()) {
    payload.reasoning_state_field = draft.reasoning_state_field.trim();
  }
  if (draft.tool_calling_mode.trim()) {
    payload.tool_calling_mode = draft.tool_calling_mode.trim();
  }
  if (draft.temperature.trim()) {
    payload.temperature = Number(draft.temperature.trim());
  }
  if (draft.max_output_tokens.trim()) {
    payload.max_output_tokens = Number(draft.max_output_tokens.trim());
  }
  if (draft.timeout.trim()) {
    payload.timeout = Number(draft.timeout.trim());
  }
  if (draft.connect_timeout.trim()) {
    payload.connect_timeout = Number(draft.connect_timeout.trim());
  }
  return payload;
}

function splitConfigPath(path: string): string[] {
  return path.split(".").filter(Boolean);
}

function healthStatusLabel(status: string, copy: LogHelperCopy) {
  if (status === "blocked") {
    return copy.healthStatusBlocked;
  }
  if (status === "warning") {
    return copy.healthStatusWarning;
  }
  return copy.healthStatusOk;
}

function healthStatusClassName(status: string) {
  if (status === "blocked") {
    return `${styles.inlineBadge} ${styles.healthBadgeBlocked}`;
  }
  if (status === "warning") {
    return `${styles.inlineBadge} ${styles.inlineBadgeWarning}`;
  }
  return `${styles.inlineBadge} ${styles.statusBadgeReady}`;
}

function healthSeverityClassName(severity: string) {
  if (severity === "blocked") {
    return `${styles.inlineBadge} ${styles.healthBadgeBlocked}`;
  }
  if (severity === "warning") {
    return `${styles.inlineBadge} ${styles.inlineBadgeWarning}`;
  }
  return styles.inlineBadge;
}

function formatFindingId(id: string) {
  return id ? `#${id.replace(/_/g, "-")}` : "";
}

function LogHelperCenter({
  diagnostics,
  loading,
  lang,
  copy,
  onRefresh,
}: {
  diagnostics: HealthDiagnostics | undefined;
  loading: boolean;
  lang: ConfigLanguage;
  copy: LogHelperCopy;
  onRefresh: () => void;
}) {
  const sessionHelpers = diagnostics?.sessionHelpers ?? [];
  const helpers = diagnostics?.logHelpers ?? [];
  const findings = diagnostics?.findings ?? [];
  const priorityFindings = findings.filter((finding) => finding.severity !== "info").slice(0, 4);
  const quickActions = diagnostics?.quickActions ?? [];
  return (
    <section id="config-health-diagnostics" className={styles.sectionSurface}>
      <div className={styles.sectionHeader}>
        <div className={styles.sectionHeaderMain}>
          <p className={styles.eyebrow}>{copy.healthTitle}</p>
          <h2 className={styles.sectionTitle}>{copy.healthTitle}</h2>
          <p className={styles.sectionText}>{copy.healthBody}</p>
        </div>
        <div className={styles.sectionHeaderActions}>
          {diagnostics ? (
            <span className={healthStatusClassName(diagnostics.status)}>
              {healthStatusLabel(diagnostics.status, copy)}
            </span>
          ) : null}
          <button type="button" className={styles.actionButton} onClick={onRefresh} disabled={loading}>
            <RefreshCw size={14} />
            {copy.healthRefresh}
          </button>
        </div>
      </div>
      {loading && !diagnostics ? <p className={styles.helperText}>{copy.healthLoading}</p> : null}
      {diagnostics ? (
        <div className={styles.healthSummaryGrid}>
          <article className={styles.matrixCard}>
            <p className={styles.matrixTitle}>{copy.healthStatusOk}</p>
            <strong className={styles.healthMetric}>{diagnostics.counts.ok}</strong>
          </article>
          <article className={styles.matrixCard}>
            <p className={styles.matrixTitle}>{copy.healthStatusWarning}</p>
            <strong className={styles.healthMetric}>{diagnostics.counts.warning}</strong>
          </article>
          <article className={styles.matrixCard}>
            <p className={styles.matrixTitle}>{copy.healthStatusBlocked}</p>
            <strong className={styles.healthMetric}>{diagnostics.counts.blocked}</strong>
          </article>
        </div>
      ) : null}
      {diagnostics?.summary ? <p className={styles.sectionText}>{diagnostics.summary}</p> : null}
      {diagnostics ? (
        <div className={styles.healthWorkbenchGrid}>
          <div className={styles.healthPanel}>
            <div className={styles.healthPanelHeader}>
              <h3>{copy.healthPriority}</h3>
              <span className={styles.inlineBadge}>{priorityFindings.length.toLocaleString()}</span>
            </div>
            {priorityFindings.length ? (
              <div className={styles.findingList}>
                {priorityFindings.map((finding) => (
                  <HealthFindingCard key={finding.id} finding={finding} copy={copy} />
                ))}
              </div>
            ) : (
              <p className={styles.helperText}>{copy.healthNoFindings}</p>
            )}
          </div>
          <div className={styles.healthPanel}>
            <div className={styles.healthPanelHeader}>
              <h3>{copy.healthQuickActions}</h3>
              <span className={styles.inlineBadge}>{quickActions.length.toLocaleString()}</span>
            </div>
            {quickActions.length ? (
              <div className={styles.quickActionList}>
                {quickActions.map((action) => (
                  <HealthQuickActionLink key={action.id} action={action} copy={copy} />
                ))}
              </div>
            ) : (
              <p className={styles.helperText}>{copy.healthNoFindings}</p>
            )}
          </div>
        </div>
      ) : null}
      {sessionHelpers.length ? (
        <div className={styles.logHelperGrid}>
          {sessionHelpers.map((helper) => (
            <SessionHelperCard key={helper.id} helper={helper} lang={lang} copy={copy} />
          ))}
        </div>
      ) : null}
      {helpers.length ? (
        <div className={styles.logHelperGrid}>
          {helpers.map((helper) => (
            <LogHelperCard key={helper.id} helper={helper} lang={lang} copy={copy} />
          ))}
        </div>
      ) : !loading ? (
        <p className={styles.helperText}>{copy.healthEmpty}</p>
      ) : null}
    </section>
  );
}

function HealthFindingCard({ finding, copy }: { finding: HealthFinding; copy: LogHelperCopy }) {
  return (
    <article className={styles.findingCard}>
      <div className={styles.findingHeader}>
        <div>
          <p className={styles.matrixTitle}>{formatFindingId(finding.id)}</p>
          <h4>{finding.title}</h4>
        </div>
        <span className={healthSeverityClassName(finding.severity)}>
          {healthStatusLabel(finding.severity, copy)}
        </span>
      </div>
      <p className={styles.cardSubtle}>{finding.summary}</p>
      {finding.evidence.length ? (
        <div className={styles.findingEvidence} aria-label={copy.healthEvidence}>
          {finding.evidence.slice(0, 4).map((item) => (
            <span key={`${finding.id}-${item.label}`}>
              <strong>{item.label}</strong>
              {item.value}
            </span>
          ))}
        </div>
      ) : null}
      {finding.recommendedAction ? (
        <p className={styles.findingRecommendation}>
          <strong>{copy.healthRecommended}</strong>
          {finding.recommendedAction}
        </p>
      ) : null}
      <div className={styles.actionsRow}>
        <a className={styles.actionButton} href={finding.route || "/logs"}>
          <ExternalLink size={14} />
          {copy.healthOpen}
        </a>
        {finding.resetItemId ? (
          <a className={styles.actionButton} href={`/reset?item=${encodeURIComponent(finding.resetItemId)}`}>
            <ExternalLink size={14} />
            {copy.healthOpenReset}
          </a>
        ) : null}
      </div>
    </article>
  );
}

function HealthQuickActionLink({ action, copy }: { action: HealthQuickAction; copy: LogHelperCopy }) {
  return (
    <a className={styles.quickActionItem} href={action.route || "/logs"}>
      <div>
        <span className={healthSeverityClassName(action.severity)}>
          {action.findingId ? formatFindingId(action.findingId) : action.source}
        </span>
        <strong>{action.title}</strong>
        <small>{action.description}</small>
      </div>
      <ExternalLink size={15} />
    </a>
  );
}

function SessionHelperCard({ helper, lang, copy }: { helper: SessionHelper; lang: ConfigLanguage; copy: LogHelperCopy }) {
  const updatedLabel = formatTimestamp(helper.updatedAt, lang, copy.healthNotRecorded);
  return (
    <article className={styles.logHelperCard}>
      <div className={styles.logHelperHeader}>
        <div>
          <p className={styles.matrixTitle}>{helper.activeSessionId || helper.id}</p>
          <h3 className={styles.cardTitle}>{helper.title}</h3>
        </div>
        <span className={healthStatusClassName(helper.status)}>
          {helper.statusLabel || healthStatusLabel(helper.status, copy)}
        </span>
      </div>
      <p className={styles.cardSubtle}>{helper.description}</p>
      <div className={styles.logHelperMetaGrid}>
        <span>
          <strong>{helper.sessionCount.toLocaleString()}</strong>
          {copy.healthSessions}
        </span>
        <span>
          <strong>{helper.busyCount.toLocaleString()}</strong>
          {copy.healthBusy}
        </span>
        <span>
          <strong>{helper.failedCount.toLocaleString()}</strong>
          {copy.healthFailed}
        </span>
        <span>
          <strong>{helper.staleCount.toLocaleString()}</strong>
          {copy.healthStale}
        </span>
        <span title={helper.updatedAt}>
          <strong>{updatedLabel}</strong>
          {copy.healthUpdated}
        </span>
      </div>
      <div className={styles.logHelperSignal}>
        <span>{copy.healthLatest}</span>
        <strong>{helper.latestSignal || helper.activeTitle || copy.healthMissing}</strong>
      </div>
      <div className={styles.logHelperSignal}>
        <span>{copy.healthPhase}</span>
        <strong>{helper.currentPhase || copy.healthNotRecorded}</strong>
      </div>
      <p className={styles.cardSubtle}>{helper.recommendedAction}</p>
      <div className={styles.cardBadges}>
        <span className={`${styles.inlineBadge} ${styles.inlineBadgeWarning}`}>{copy.healthProtected}</span>
        {helper.findingIds?.length ? (
          <span className={styles.inlineBadge}>
            {copy.healthRelatedFindings} {helper.findingIds.length}
          </span>
        ) : null}
      </div>
      {helper.protectedReason ? <p className={styles.helperText}>{helper.protectedReason}</p> : null}
      <div className={styles.actionsRow}>
        <a className={styles.actionButton} href={helper.route || "/chat"}>
          <ExternalLink size={14} />
          {copy.healthOpenChat}
        </a>
      </div>
    </article>
  );
}

function LogHelperCard({ helper, lang, copy }: { helper: LogHelper; lang: ConfigLanguage; copy: LogHelperCopy }) {
  const updatedLabel = formatTimestamp(helper.lastModifiedAt, lang, copy.healthNotRecorded);
  const latestSignal = helper.latestSignal || helper.latestPath || copy.healthMissing;
  return (
    <article className={styles.logHelperCard}>
      <div className={styles.logHelperHeader}>
        <div>
          <p className={styles.matrixTitle}>{helper.rootPath}</p>
          <h3 className={styles.cardTitle}>{helper.title}</h3>
        </div>
        <span className={healthStatusClassName(helper.status)}>
          {helper.statusLabel || healthStatusLabel(helper.status, copy)}
        </span>
      </div>
      <p className={styles.cardSubtle}>{helper.description}</p>
      <div className={styles.logHelperMetaGrid}>
        <span>
          <strong>{helper.fileCount.toLocaleString()}</strong>
          {copy.healthFiles}
        </span>
        <span>
          <strong>{helper.directoryCount.toLocaleString()}</strong>
          {copy.healthDirs}
        </span>
        <span>
          <strong>{formatBytes(helper.sizeBytes)}</strong>
          {copy.healthSize}
        </span>
        <span title={helper.lastModifiedAt}>
          <strong>{updatedLabel}</strong>
          {copy.healthUpdated}
        </span>
      </div>
      <div className={styles.logHelperSignal}>
        <span>{copy.healthLatest}</span>
        <strong>{latestSignal}</strong>
      </div>
      <p className={styles.cardSubtle}>{helper.recommendedAction}</p>
      <div className={styles.cardBadges}>
        <span className={helper.protected ? `${styles.inlineBadge} ${styles.inlineBadgeWarning}` : styles.inlineBadge}>
          {helper.protected ? copy.healthProtected : copy.healthResetAvailable}
        </span>
        {helper.findingIds?.length ? (
          <span className={styles.inlineBadge}>
            {copy.healthRelatedFindings} {helper.findingIds.length}
          </span>
        ) : null}
      </div>
      {helper.protectedReason ? <p className={styles.helperText}>{helper.protectedReason}</p> : null}
      <div className={styles.actionsRow}>
        <a className={styles.actionButton} href={helper.route || "/logs"}>
          <ExternalLink size={14} />
          {copy.healthOpenLogs}
        </a>
        {helper.resetItemId ? (
          <a className={styles.actionButton} href={`/reset?item=${encodeURIComponent(helper.resetItemId)}`}>
            <ExternalLink size={14} />
            {copy.healthOpenReset}
          </a>
        ) : null}
      </div>
    </article>
  );
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function getConfigValueAtPath(root: unknown, path: string): unknown {
  let current = root;
  for (const token of splitConfigPath(path)) {
    if (Array.isArray(current)) {
      current = current[Number(token)];
      continue;
    }
    if (isPlainObject(current)) {
      current = current[token];
      continue;
    }
    return undefined;
  }
  return current;
}

function setConfigValueAtPath<T>(root: T, path: string, nextValue: unknown): T {
  if (!path) {
    return nextValue as T;
  }
  const cloned = clonePublicConfig(root);
  const tokens = splitConfigPath(path);
  let current: unknown = cloned;
  for (let index = 0; index < tokens.length - 1; index += 1) {
    const token = tokens[index];
    if (Array.isArray(current)) {
      current = current[Number(token)];
      continue;
    }
    if (isPlainObject(current)) {
      current = current[token];
      continue;
    }
    throw new Error(`Unknown config path: ${path}`);
  }
  const leaf = tokens[tokens.length - 1];
  if (Array.isArray(current)) {
    current[Number(leaf)] = nextValue;
  } else if (isPlainObject(current)) {
    current[leaf] = nextValue;
  }
  return cloned;
}

function humanizeConfigToken(token: string): string {
  return token
    .split("_")
    .filter(Boolean)
    .map((part) => (part.toUpperCase() === part ? part : `${part.charAt(0).toUpperCase()}${part.slice(1)}`))
    .join(" ");
}

function configLabel(metaMap: Record<string, ConfigEditorMeta>, path: string): string {
  return metaMap[path]?.label ?? humanizeConfigToken(splitConfigPath(path).at(-1) ?? path);
}

function configHint(metaMap: Record<string, ConfigEditorMeta>, path: string): string {
  return metaMap[path]?.hint ?? "";
}

function formatConfigDisplayValue(value: unknown, kind: ConfigEditorMeta["kind"] | undefined, copy: ConfigCopy): string {
  if (kind === "secret") {
    return getString(value) ? "******" : copy.emptyValue;
  }
  if (typeof value === "boolean") {
    return value ? copy.yes : copy.no;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return copy.emptyValue;
    }
    return value
      .map((item) => (typeof item === "string" ? item : JSON.stringify(item)))
      .join(", ");
  }
  if (value == null || value === "") {
    return copy.emptyValue;
  }
  return String(value);
}

type ConfigSectionEditorProps = {
  section: ConfigEditorSection;
  value: unknown;
  metaMap: Record<string, ConfigEditorMeta>;
  copy: ConfigCopy;
  disabled: boolean;
  uiState: ConfigSectionUiState;
  onUiStateChange: (sectionId: string, nextState: ConfigSectionUiState) => void;
  onSaveSection: (path: string, nextValue: unknown) => Promise<boolean>;
  onAvatarImageUpload: (file: File) => Promise<AvatarImageUploadResponse | null>;
};

type AvatarImageUploadResponse = {
  path: string;
  url: string;
  contentType: string;
  sizeBytes: number;
};

type AvatarCropDraft = {
  absolutePath: string;
  fileName: string;
  objectUrl: string;
  imageWidth: number;
  imageHeight: number;
  zoom: number;
  offsetX: number;
  offsetY: number;
};

type AvatarCropDrag = {
  pointerId: number;
  startClientX: number;
  startClientY: number;
  startOffsetX: number;
  startOffsetY: number;
};

const AVATAR_CROP_FRAME_SIZE = 320;
const AVATAR_CROP_PREVIEW_SIZE = 112;
const AVATAR_CROP_OUTPUT_SIZE = 512;

function avatarImagePreviewUrl(value: unknown): string {
  const path = getString(value).replace(/\\/g, "/").trim();
  const prefix = "workspace/user_avatars/";
  if (!path.startsWith(prefix)) {
    return "";
  }
  const filename = path.slice(prefix.length);
  if (!/^[A-Za-z0-9_.-]+$/.test(filename)) {
    return "";
  }
  return `/api/config/avatar-image/${encodeURIComponent(filename)}`;
}

function ConfigSectionEditor({
  section,
  value,
  metaMap,
  copy,
  disabled,
  uiState,
  onUiStateChange,
  onSaveSection,
  onAvatarImageUpload,
}: ConfigSectionEditorProps) {
  const sectionExpanded = uiState.expanded;
  const editing = uiState.editing;
  const expandedPaths = uiState.expandedPaths;
  const draftValue = editing ? clonePublicConfig(uiState.draftValue ?? value) : clonePublicConfig(value);
  const [uploadingImagePath, setUploadingImagePath] = useState("");
  const [avatarCrop, setAvatarCrop] = useState<AvatarCropDraft | null>(null);
  const [avatarCropError, setAvatarCropError] = useState("");
  const avatarCropDragRef = useRef<AvatarCropDrag | null>(null);

  useEffect(() => {
    const objectUrl = avatarCrop?.objectUrl;
    return () => {
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [avatarCrop?.objectUrl]);

  function updateSectionDraft(absolutePath: string, nextValue: unknown) {
    const prefix = `${section.path}.`;
    const relativePath = absolutePath === section.path ? "" : absolutePath.startsWith(prefix) ? absolutePath.slice(prefix.length) : absolutePath;
    const currentDraft = editing ? draftValue : clonePublicConfig(value);
    onUiStateChange(section.id, {
      ...uiState,
      editing: true,
      expanded: true,
      draftValue: setConfigValueAtPath(currentDraft, relativePath, nextValue),
    });
  }

  function toggleObjectPath(path: string) {
    onUiStateChange(section.id, {
      ...uiState,
      expandedPaths: { ...expandedPaths, [path]: !expandedPaths[path] },
    });
  }

  function clampAvatarCrop(next: AvatarCropDraft): AvatarCropDraft {
    const offset = clampAvatarCropOffset({
      imageWidth: next.imageWidth,
      imageHeight: next.imageHeight,
      frameSize: AVATAR_CROP_FRAME_SIZE,
      zoom: next.zoom,
      offsetX: next.offsetX,
      offsetY: next.offsetY,
    });
    return { ...next, ...offset };
  }

  async function beginAvatarCrop(file: File, absolutePath: string) {
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
      throw new Error("头像只支持 PNG、JPG 或 WebP 图片。");
    }
    const image = await loadImageForCrop(file);
    setAvatarCropError("");
    setAvatarCrop((current) => {
      if (current?.objectUrl) {
        URL.revokeObjectURL(current.objectUrl);
      }
      return clampAvatarCrop({
        absolutePath,
        fileName: file.name,
        objectUrl: image.objectUrl,
        imageWidth: image.width,
        imageHeight: image.height,
        zoom: 1,
        offsetX: 0,
        offsetY: 0,
      });
    });
  }

  async function confirmAvatarCrop() {
    if (!avatarCrop) {
      return;
    }
    setUploadingImagePath(avatarCrop.absolutePath);
    try {
      const croppedFile = await createCroppedAvatarFile(avatarCrop);
      const result = await onAvatarImageUpload(croppedFile);
      if (result?.path) {
        updateSectionDraft(avatarCrop.absolutePath, result.path);
        setAvatarCrop(null);
      }
    } catch (error) {
      setAvatarCropError(readableErrorMessage(error));
    } finally {
      setUploadingImagePath("");
    }
  }

  function cancelAvatarCrop() {
    setAvatarCropError("");
    setAvatarCrop(null);
  }

  async function handleSave() {
    const ok = await onSaveSection(section.path, draftValue);
    if (ok) {
      onUiStateChange(section.id, {
        ...uiState,
        editing: false,
        draftValue: undefined,
      });
    }
  }

  function renderFieldView(fieldValue: unknown, absolutePath: string) {
    const meta = metaMap[absolutePath];
    if (meta?.kind === "image") {
      const previewUrl = avatarImagePreviewUrl(fieldValue);
      return (
        <article key={absolutePath} className={`${styles.treeFieldCard} ${styles.treeFieldCardView} ${styles.avatarImageCard}`}>
          <div className={styles.treeFieldHead}>
            <span className={styles.treeFieldLabel}>{configLabel(metaMap, absolutePath)}</span>
          </div>
          {configHint(metaMap, absolutePath) ? <p className={styles.treeHint}>{configHint(metaMap, absolutePath)}</p> : null}
          <div className={styles.avatarImageValue}>
            {previewUrl ? (
              <img src={previewUrl} alt="" className={styles.avatarImagePreview} />
            ) : (
              <span className={styles.avatarImagePlaceholder}>
                <ImageIcon size={16} />
              </span>
            )}
            <span>{formatConfigDisplayValue(fieldValue, meta?.kind, copy)}</span>
          </div>
        </article>
      );
    }
    return (
      <article key={absolutePath} className={`${styles.treeFieldCard} ${styles.treeFieldCardView}`}>
        <div className={styles.treeFieldHead}>
          <span className={styles.treeFieldLabel}>{configLabel(metaMap, absolutePath)}</span>
        </div>
        {configHint(metaMap, absolutePath) ? <p className={styles.treeHint}>{configHint(metaMap, absolutePath)}</p> : null}
        <div className={styles.treeFieldValue}>{formatConfigDisplayValue(fieldValue, meta?.kind, copy)}</div>
      </article>
    );
  }

  function renderFieldEditor(fieldValue: unknown, absolutePath: string) {
    const meta = metaMap[absolutePath];
    const kind = meta?.kind ?? "text";
    const imageUploading = uploadingImagePath === absolutePath;
    let control;

    if (kind === "image") {
      const previewUrl = avatarImagePreviewUrl(fieldValue);
      const cropDraft = avatarCrop?.absolutePath === absolutePath ? avatarCrop : null;
      const imageUploading = uploadingImagePath === absolutePath;
      const cropScale = cropDraft
        ? (AVATAR_CROP_FRAME_SIZE / Math.min(cropDraft.imageWidth, cropDraft.imageHeight)) * cropDraft.zoom
        : 1;
      const cropImageStyle: CSSProperties | undefined = cropDraft
        ? {
            width: cropDraft.imageWidth * cropScale,
            height: cropDraft.imageHeight * cropScale,
            transform: `translate(calc(-50% + ${cropDraft.offsetX}px), calc(-50% + ${cropDraft.offsetY}px))`,
          }
        : undefined;
      const cropPreviewRatio = AVATAR_CROP_PREVIEW_SIZE / AVATAR_CROP_FRAME_SIZE;
      const cropPreviewImageStyle: CSSProperties | undefined = cropDraft
        ? {
            width: cropDraft.imageWidth * cropScale * cropPreviewRatio,
            height: cropDraft.imageHeight * cropScale * cropPreviewRatio,
            transform: `translate(calc(-50% + ${cropDraft.offsetX * cropPreviewRatio}px), calc(-50% + ${cropDraft.offsetY * cropPreviewRatio}px))`,
          }
        : undefined;
      control = (
        <div className={styles.avatarImageEditor}>
          <div className={styles.avatarImageValue}>
            {previewUrl ? (
              <img src={previewUrl} alt="" className={styles.avatarImagePreview} />
            ) : (
              <span className={styles.avatarImagePlaceholder}>
                <ImageIcon size={16} />
              </span>
            )}
            <span>{configLabel(metaMap, absolutePath)}</span>
          </div>
          {cropDraft ? (
            <div className={styles.avatarCropPanel}>
              <div className={styles.avatarCropHeader}>
                <div>
                  <strong>{copy.avatarCropTitle}</strong>
                  <p>{copy.avatarCropHint}</p>
                </div>
                <span>{copy.avatarCropPreview}</span>
              </div>
              <div className={styles.avatarCropWorkspace}>
                <div
                  className={styles.avatarCropFrame}
                  onPointerDown={(event) => {
                    event.currentTarget.setPointerCapture(event.pointerId);
                    avatarCropDragRef.current = {
                      pointerId: event.pointerId,
                      startClientX: event.clientX,
                      startClientY: event.clientY,
                      startOffsetX: cropDraft.offsetX,
                      startOffsetY: cropDraft.offsetY,
                    };
                  }}
                  onPointerMove={(event) => {
                    const drag = avatarCropDragRef.current;
                    if (!drag || drag.pointerId !== event.pointerId) {
                      return;
                    }
                    const next = clampAvatarCrop({
                      ...cropDraft,
                      offsetX: drag.startOffsetX + event.clientX - drag.startClientX,
                      offsetY: drag.startOffsetY + event.clientY - drag.startClientY,
                    });
                    setAvatarCrop(next);
                  }}
                  onPointerUp={(event) => {
                    if (avatarCropDragRef.current?.pointerId === event.pointerId) {
                      avatarCropDragRef.current = null;
                    }
                  }}
                  onPointerCancel={() => {
                    avatarCropDragRef.current = null;
                  }}
                >
                  <img src={cropDraft.objectUrl} alt="" className={styles.avatarCropImage} style={cropImageStyle} draggable={false} />
                  <span className={styles.avatarCropMask} />
                </div>
                <div className={styles.avatarCropPreviewWrap}>
                  <div className={styles.avatarCropPreview}>
                    <img src={cropDraft.objectUrl} alt="" className={styles.avatarCropImage} style={cropPreviewImageStyle} draggable={false} />
                  </div>
                </div>
              </div>
              <label className={styles.avatarCropZoomField}>
                <span>{copy.avatarCropZoom}</span>
                <input
                  type="range"
                  min="1"
                  max="3"
                  step="0.01"
                  value={cropDraft.zoom}
                  onChange={(event) => {
                    const zoom = Number(event.target.value);
                    setAvatarCrop(clampAvatarCrop({ ...cropDraft, zoom }));
                  }}
                />
              </label>
              <div className={styles.avatarImageActions}>
                <button
                  type="button"
                  className={`${styles.primaryButton} ${styles.compactButton}`}
                  disabled={disabled || imageUploading}
                  onClick={() => {
                    void confirmAvatarCrop();
                  }}
                >
                  <Save size={14} />
                  {imageUploading ? copy.avatarImageUploading : copy.avatarCropConfirm}
                </button>
                <button
                  type="button"
                  className={`${styles.actionButton} ${styles.compactButton}`}
                  disabled={disabled || imageUploading}
                  onClick={cancelAvatarCrop}
                >
                  <X size={14} />
                  {copy.avatarCropCancel}
                </button>
              </div>
            </div>
          ) : null}
          <div className={styles.avatarImageActions}>
            <label className={`${styles.actionButton} ${styles.compactButton} ${styles.fileUploadButton}`}>
              <Upload size={14} />
              {cropDraft ? copy.uploadAvatarImage : imageUploading ? copy.avatarImageUploading : copy.uploadAvatarImage}
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                disabled={disabled || imageUploading}
                onChange={async (event) => {
                  const file = event.currentTarget.files?.[0];
                  event.currentTarget.value = "";
                  if (!file) {
                    return;
                  }
                  try {
                    await beginAvatarCrop(file, absolutePath);
                  } catch (error) {
                    setAvatarCropError(readableErrorMessage(error));
                  } finally {
                    setUploadingImagePath("");
                  }
                }}
              />
            </label>
            {getString(fieldValue) ? (
              <button
                type="button"
                className={`${styles.actionButton} ${styles.compactButton}`}
                disabled={disabled || imageUploading}
                onClick={() => updateSectionDraft(absolutePath, "")}
              >
                <X size={14} />
                {copy.clearAvatarImage}
              </button>
            ) : null}
          </div>
          {avatarCropError ? <p className={styles.inlineError}>{avatarCropError}</p> : null}
        </div>
      );
    } else if (kind === "boolean") {
      control = (
        <label className={styles.toggleField}>
          <input
            type="checkbox"
            checked={Boolean(fieldValue)}
            onChange={(event) => updateSectionDraft(absolutePath, event.target.checked)}
          />
          <span>{configLabel(metaMap, absolutePath)}</span>
        </label>
      );
    } else if (kind === "select") {
      control = (
        <label className={styles.field}>
          <span>{configLabel(metaMap, absolutePath)}</span>
          <select value={getString(fieldValue)} onChange={(event) => updateSectionDraft(absolutePath, event.target.value)}>
            {(meta?.options ?? []).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      );
    } else if (kind === "number") {
      control = (
        <label className={styles.field}>
          <span>{configLabel(metaMap, absolutePath)}</span>
          <input
            type="number"
            step="any"
            value={getString(fieldValue)}
            onChange={(event) => {
              const raw = event.target.value;
              updateSectionDraft(absolutePath, raw === "" ? "" : Number(raw));
            }}
          />
        </label>
      );
    } else if (kind === "string_list") {
      control = (
        <label className={styles.field}>
          <span>{configLabel(metaMap, absolutePath)}</span>
          <textarea
            rows={Math.max(4, Array.isArray(fieldValue) ? fieldValue.length + 1 : 4)}
            value={Array.isArray(fieldValue) ? fieldValue.join("\n") : getString(fieldValue)}
            onChange={(event) =>
              updateSectionDraft(
                absolutePath,
                event.target.value
                  .split(/\r?\n/)
                  .map((line) => line.trim())
                  .filter(Boolean),
              )
            }
          />
        </label>
      );
    } else if (kind === "multiline") {
      control = (
        <label className={styles.field}>
          <span>{configLabel(metaMap, absolutePath)}</span>
          <textarea
            rows={10}
            value={getString(fieldValue)}
            onChange={(event) => updateSectionDraft(absolutePath, event.target.value)}
          />
        </label>
      );
    } else if (kind === "json") {
      control = (
        <label className={styles.field}>
          <span>{configLabel(metaMap, absolutePath)}</span>
          <textarea
            rows={6}
            value={typeof fieldValue === "string" ? fieldValue : formatJson(fieldValue)}
            onChange={(event) => {
              const raw = event.target.value;
              try {
                updateSectionDraft(absolutePath, JSON.parse(raw));
              } catch {
                updateSectionDraft(absolutePath, raw);
              }
            }}
          />
        </label>
      );
    } else {
      control = (
        <label className={styles.field}>
          <span>{configLabel(metaMap, absolutePath)}</span>
          <input
            type={kind === "secret" ? "password" : "text"}
            value={getString(fieldValue)}
            onChange={(event) => updateSectionDraft(absolutePath, event.target.value)}
          />
        </label>
      );
    }

    return (
      <article key={absolutePath} className={`${styles.treeFieldCard} ${styles.treeFieldCardEdit}`}>
        {configHint(metaMap, absolutePath) ? <p className={styles.treeHint}>{configHint(metaMap, absolutePath)}</p> : null}
        {control}
      </article>
    );
  }

  function renderNestedBlock(absolutePath: string, count: number, children: ReactNode, titleOverride?: string) {
    const expanded = Boolean(expandedPaths[absolutePath]);
    return (
      <div className={styles.treeObjectBlock}>
        <button
          type="button"
          className={styles.treeToggle}
          aria-expanded={expanded}
          onClick={() => toggleObjectPath(absolutePath)}
        >
          <div className={styles.treeToggleLabel}>
            <ChevronRight size={14} className={expanded ? styles.treeToggleIconExpanded : styles.treeToggleIcon} />
            <div>
              <p className={styles.cardTitle}>{titleOverride ?? configLabel(metaMap, absolutePath)}</p>
              {configHint(metaMap, absolutePath) ? <p className={styles.treeHint}>{configHint(metaMap, absolutePath)}</p> : null}
            </div>
          </div>
          <span className={styles.inlineBadge}>{count}</span>
        </button>
        {expanded ? <div className={styles.treeBody}>{children}</div> : null}
      </div>
    );
  }

  function renderObjectBody(nodeValue: Record<string, unknown>, absolutePath: string, mode: "view" | "edit") {
    const entries = Object.entries(nodeValue);
    if (!entries.length) {
      return <p className={styles.helperText}>{copy.emptyValue}</p>;
    }
    return (
      <div className={styles.treeGrid}>
        {entries.map(([key, childValue]) => {
          const childPath = `${absolutePath}.${key}`;
          const childMetaKind = metaMap[childPath]?.kind;
          const childIsObjectList =
            Array.isArray(childValue) &&
            (childMetaKind === "object_list" || childValue.every((item) => isPlainObject(item)));
          const childIsObject = isPlainObject(childValue);
          if (childIsObject || childIsObjectList) {
            const childExpanded = Boolean(expandedPaths[childPath]);
            return (
              <div key={childPath} className={childExpanded ? styles.treeWide : styles.treeObjectCell}>
                {renderNode(childValue, childPath, mode)}
              </div>
            );
          }
          return mode === "edit" ? renderFieldEditor(childValue, childPath) : renderFieldView(childValue, childPath);
        })}
      </div>
    );
  }

  function renderNode(nodeValue: unknown, absolutePath: string, mode: "view" | "edit", itemIndex?: number) {
    const isRoot = absolutePath === section.path;
    if (Array.isArray(nodeValue) && nodeValue.every((item) => isPlainObject(item))) {
      if (isRoot) {
        return nodeValue.length ? (
          <div className={styles.treeStack}>
            {nodeValue.map((item, index) => (
              <div key={`${absolutePath}.${index}`} className={styles.treeNestedBlock}>
                <div className={styles.treeNestedHeader}>
                  <strong>{`${copy.itemLabel} ${index + 1}`}</strong>
                </div>
                {renderObjectBody(item as Record<string, unknown>, `${absolutePath}.${index}`, mode)}
              </div>
            ))}
          </div>
        ) : (
          <p className={styles.helperText}>{copy.emptyValue}</p>
        );
      }

      return renderNestedBlock(
        absolutePath,
        nodeValue.length,
        nodeValue.length ? (
          <div className={styles.treeStack}>
            {nodeValue.map((item, index) => (
              <div key={`${absolutePath}.${index}`} className={styles.treeNestedBlock}>
                <div className={styles.treeNestedHeader}>
                  <strong>{`${copy.itemLabel} ${index + 1}`}</strong>
                </div>
                {renderObjectBody(item as Record<string, unknown>, `${absolutePath}.${index}`, mode)}
              </div>
            ))}
          </div>
        ) : (
          <p className={styles.helperText}>{copy.emptyValue}</p>
        ),
      );
    }

    if (isPlainObject(nodeValue)) {
      if (isRoot) {
        return renderObjectBody(nodeValue, absolutePath, mode);
      }
      const label = itemIndex == null ? configLabel(metaMap, absolutePath) : `${copy.itemLabel} ${itemIndex + 1}`;
      return (
        <>{renderNestedBlock(absolutePath, Object.keys(nodeValue).length, renderObjectBody(nodeValue, absolutePath, mode), label)}</>
      );
    }

    return mode === "edit" ? renderFieldEditor(nodeValue, absolutePath) : renderFieldView(nodeValue, absolutePath);
  }

  return (
    <section id={`config-${section.id}`} className={styles.sectionSurface}>
      <div className={styles.sectionHeader}>
        <div className={styles.sectionHeaderMain}>
          <p className={styles.eyebrow}>{section.path}</p>
          <h2 className={styles.sectionTitle}>{section.title}</h2>
          <p className={styles.sectionText}>{section.summary}</p>
        </div>
        <div className={styles.sectionHeaderActions}>
          <div className={styles.sectionHeaderMeta}>
            <span className={styles.sectionHeaderMetaLabel}>{copy.fieldCountLabel}</span>
            <span className={styles.inlineBadge}>{section.fieldCount}</span>
          </div>
          <div className={styles.sectionToolbarGroup}>
            <button
              type="button"
              className={`${styles.actionButton} ${styles.compactButton} ${styles.toolbarButton}`}
              aria-expanded={sectionExpanded}
              onClick={() => onUiStateChange(section.id, { ...uiState, expanded: !sectionExpanded })}
            >
              <ChevronRight size={14} className={sectionExpanded ? styles.treeToggleIconExpanded : styles.treeToggleIcon} />
              {sectionExpanded ? copy.collapseSection : copy.expandSection}
            </button>
          {editing ? (
            <>
              <button
                type="button"
                className={`${styles.primaryButton} ${styles.compactButton} ${styles.toolbarButton}`}
                disabled={disabled}
                onClick={handleSave}
              >
                <Save size={14} />
                {copy.saveSection}
              </button>
              <button
                type="button"
                className={`${styles.actionButton} ${styles.compactButton} ${styles.toolbarButton}`}
                disabled={disabled}
                onClick={() => {
                  onUiStateChange(section.id, {
                    ...uiState,
                    expanded: true,
                    editing: false,
                    draftValue: undefined,
                  });
                }}
              >
                <RotateCcw size={14} />
                {copy.cancelSection}
              </button>
            </>
          ) : (
            <button
              type="button"
              className={`${styles.actionButton} ${styles.compactButton} ${styles.toolbarButton}`}
              disabled={disabled}
              onClick={() => {
                onUiStateChange(section.id, {
                  ...uiState,
                  expanded: true,
                  editing: true,
                  draftValue: clonePublicConfig(value),
                });
              }}
            >
              <Pencil size={14} />
              {copy.editSection}
            </button>
          )}
          </div>
        </div>
      </div>
      {sectionExpanded ? renderNode(editing ? draftValue : value, section.path, editing ? "edit" : "view") : null}
    </section>
  );
}

async function requestJson<T>(url: string, body?: unknown, method = "POST"): Promise<T> {
  return fetchJson<T>(url, {
    method,
    headers: {
      "Content-Type": "application/json",
    },
    body: body == null ? undefined : JSON.stringify(body),
  });
}

async function fileToBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  const chunkSize = 0x8000;
  for (let index = 0; index < bytes.length; index += chunkSize) {
    const chunk = bytes.subarray(index, index + chunkSize);
    binary += String.fromCharCode(...chunk);
  }
  return btoa(binary);
}

function loadImageForCrop(file: File): Promise<{ objectUrl: string; width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const objectUrl = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      resolve({ objectUrl, width: image.naturalWidth, height: image.naturalHeight });
    };
    image.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      reject(new Error("无法读取这张图片。"));
    };
    image.src = objectUrl;
  });
}

function loadImageElement(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("无法读取裁剪后的图片。"));
    image.src = src;
  });
}

async function createCroppedAvatarFile(draft: AvatarCropDraft): Promise<File> {
  const image = await loadImageElement(draft.objectUrl);
  const canvas = document.createElement("canvas");
  canvas.width = AVATAR_CROP_OUTPUT_SIZE;
  canvas.height = AVATAR_CROP_OUTPUT_SIZE;
  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error("当前浏览器无法裁剪图片。");
  }
  const source = avatarCropSourceRect({
    imageWidth: draft.imageWidth,
    imageHeight: draft.imageHeight,
    frameSize: AVATAR_CROP_FRAME_SIZE,
    zoom: draft.zoom,
    offsetX: draft.offsetX,
    offsetY: draft.offsetY,
  });
  context.drawImage(
    image,
    source.sx,
    source.sy,
    source.size,
    source.size,
    0,
    0,
    AVATAR_CROP_OUTPUT_SIZE,
    AVATAR_CROP_OUTPUT_SIZE,
  );
  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((result) => {
      if (result) {
        resolve(result);
        return;
      }
      reject(new Error("头像裁剪失败。"));
    }, "image/png");
  });
  const stem = draft.fileName.replace(/\.[^.]+$/, "").replace(/[^A-Za-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "") || "avatar";
  return new File([blob], `${stem}-cropped.png`, { type: "image/png" });
}

export function ConfigRoute() {
  const queryClient = useQueryClient();
  const pageRef = useRef<HTMLDivElement | null>(null);
  const profileFormRef = useRef<HTMLDivElement | null>(null);
  const sidebarResizeCleanupRef = useRef<(() => void) | null>(null);
  const workspaceQuery = useQuery({
    queryKey: queryKeys.configWorkspace(),
    queryFn: () => fetchJson<ConfigWorkspace>("/api/config/workspace"),
  });
  const healthDiagnosticsQuery = useQuery({
    queryKey: queryKeys.diagnosticsHealth(),
    queryFn: () => fetchJson<HealthDiagnostics>("/api/diagnostics/health"),
  });
  const agentsQuery = useQuery({
    queryKey: queryKeys.agents(),
    queryFn: () => fetchJson<AgentInstance[]>("/api/agents"),
  });
  const promptTemplatesQuery = useQuery({
    queryKey: queryKeys.promptTemplates(),
    queryFn: () => fetchJson<PromptTemplateWorkspace>("/api/prompt-templates"),
  });
  const modeBindingsQuery = useQuery({
    queryKey: queryKeys.agentModeBindings(),
    queryFn: () => fetchJson<AgentModeBindings>("/api/agent-mode-bindings"),
  });

  const [draftConfig, setDraftConfig] = useState<PublicConfigShape | null>(null);
  const [draftMeta, setDraftMeta] = useState<ConfigDraftMeta>(emptyDraftMeta());
  const [baseHash, setBaseHash] = useState("");
  const [draftHash, setDraftHash] = useState("");
  const [activeWorkspace, setActiveWorkspace] = useState<ConfigWorkspace | null>(null);
  const [jsonText, setJsonText] = useState("{}");
  const [notice, setNotice] = useState<{ tone: NoticeTone; text: string }>({ tone: "neutral", text: "" });
  const [busyAction, setBusyAction] = useState("");
  const [modelEditor, setModelEditor] = useState<ModelEditorState>(emptyModelEditorState());
  const [modelEditorError, setModelEditorError] = useState("");
  const [modelDiscoveryError, setModelDiscoveryError] = useState("");
  const [discoveredModels, setDiscoveredModels] = useState<ConfigDiscoveredModel[]>([]);
  const [selectedDiscoveredModelId, setSelectedDiscoveredModelId] = useState("");
  const [profileDraft, setProfileDraft] = useState<ProfileDraft>(emptyProfileDraft());
  const [profileEditors, setProfileEditors] = useState<Record<string, ProfileEditState>>({});
  const [profileFormExpanded, setProfileFormExpanded] = useState(false);
  const [modelEditorExpanded, setModelEditorExpanded] = useState(false);
  const [sidebarIndexCollapsed, setSidebarIndexCollapsed] = useState(() => readStoredFlag(SIDEBAR_INDEX_COLLAPSED_STORAGE_KEY) ?? false);
  const [activeSectionId, setActiveSectionId] = useState("");
  const [sectionUiState, setSectionUiState] = useState<Record<string, ConfigSectionUiState>>({});
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    const viewportWidth = typeof window === "undefined" ? 1440 : window.innerWidth;
    return clampSidebarWidth(readStoredNumber(SIDEBAR_WIDTH_STORAGE_KEY) ?? SIDEBAR_WIDTH_DEFAULT, viewportWidth);
  });
  const [sidebarHeight, setSidebarHeight] = useState(() => {
    const viewportHeight = typeof window === "undefined" ? 960 : window.innerHeight;
    return clampSidebarHeight(
      readStoredNumber(SIDEBAR_HEIGHT_STORAGE_KEY) ?? viewportHeight - SIDEBAR_VIEWPORT_OFFSET,
      viewportHeight,
    );
  });

  function syncWorkspace(workspace: ConfigWorkspace, tone: NoticeTone = "neutral") {
    setActiveWorkspace(clonePublicConfig(workspace));
    setDraftConfig(clonePublicConfig(workspace.publicConfig));
    setDraftMeta(clonePublicConfig(workspace.draftMeta));
    setBaseHash(workspace.baseHash);
    setDraftHash(workspace.hash);
    setJsonText(formatJson(workspace.publicConfig));
    setNotice({ tone, text: workspace.message || "" });
    setModelEditor(emptyModelEditorState());
    setModelEditorError("");
    setProfileDraft(emptyProfileDraft(workspace.profileCards[0]?.profileId ?? "primary"));
    setProfileEditors({});
  }

  useEffect(() => {
    if (workspaceQuery.data) {
      syncWorkspace(workspaceQuery.data);
    }
  }, [workspaceQuery.data]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return undefined;
    }

    function handleWindowResize() {
      setSidebarWidth((current) => clampSidebarWidth(current, window.innerWidth));
      setSidebarHeight((current) => clampSidebarHeight(current, window.innerHeight));
    }

    window.addEventListener("resize", handleWindowResize);
    return () => {
      window.removeEventListener("resize", handleWindowResize);
    };
  }, []);

  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(SIDEBAR_INDEX_COLLAPSED_STORAGE_KEY, sidebarIndexCollapsed ? "1" : "0");
    }
  }, [sidebarIndexCollapsed]);

  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(SIDEBAR_WIDTH_STORAGE_KEY, String(sidebarWidth));
    }
  }, [sidebarWidth]);

  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(SIDEBAR_HEIGHT_STORAGE_KEY, String(sidebarHeight));
    }
  }, [sidebarHeight]);

  useEffect(() => {
    return () => {
      sidebarResizeCleanupRef.current?.();
    };
  }, []);

  const workspace = activeWorkspace ?? workspaceQuery.data;
  const currentLanguage = getDraftLanguage(draftConfig, workspace?.language === "en" ? "en" : "zh");
  const copy = CONFIG_COPY[currentLanguage];
  const sectionIndexTitle = currentLanguage === "en" ? "Section index" : "分区索引";
  const sectionIndexHint = currentLanguage === "en" ? "Jump directly to a config area" : "直接跳到具体配置区";
  const sectionIndexCollapsedHint = currentLanguage === "en" ? "Index hidden for focused editing" : "目录已收起，专注右侧编辑区";
  const sectionIndexToggleLabel = currentLanguage === "en" ? (sidebarIndexCollapsed ? "Expand index" : "Collapse index") : (sidebarIndexCollapsed ? "展开索引" : "收起索引");
  const resizeWidthTitle = currentLanguage === "en" ? "Drag to resize sidebar width" : "左右拖动调整侧栏宽度";
  const resizeHeightTitle = currentLanguage === "en" ? "Drag to resize sidebar height" : "上下拖动调整侧栏高度";
  const resizeCornerTitle = currentLanguage === "en" ? "Drag to resize sidebar" : "拖动调整侧栏尺寸";
  const formattedDraft = useMemo(() => formatJson(draftConfig ?? {}), [draftConfig]);
  const hasUnsavedConfigChanges = Boolean(baseHash && draftHash && baseHash !== draftHash);
  const sidebarSections = workspace?.sections ?? [];
  const editorSections = workspace?.editorSections ?? [];
  const editorMeta = workspace?.editorMeta ?? {};
  const sidebarGroups = useMemo(() => buildConfigSidebarGroups(copy), [copy]);
  const availableSectionIds = useMemo(() => new Set(sidebarSections.map((section) => section.id)), [sidebarSections]);
  const visibleSidebarGroups = useMemo(
    () =>
      sidebarGroups
        .map((group) => ({
          ...group,
          memberSectionIds: group.memberSectionIds.filter((sectionId) => availableSectionIds.has(sectionId)),
        }))
        .filter((group) => group.memberSectionIds.length),
    [availableSectionIds, sidebarGroups],
  );
  const activeSection = visibleSidebarGroups.find((section) => section.id === activeSectionId) ?? visibleSidebarGroups[0] ?? null;
  const activeEditorSections = editorSections.filter((section) => {
    if (!activeSection?.memberSectionIds.includes(section.id)) {
      return false;
    }
    return section.id !== "prompt" && section.id !== "agent" && section.id !== "tools";
  });
  const modelOptions = workspace?.modelOptions ?? [];
  const modelOptionsById = useMemo(() => new Map(modelOptions.map((option) => [option.model_id, option])), [modelOptions]);
  const modelDetailKeys = useMemo(() => collectModelDetailKeys(modelOptions), [modelOptions]);
  const modelPresetGroups = useMemo(
    () => {
      const labels: ModelPresetGroupLabels = {
        official: copy.presetGroupOfficial,
        relay: copy.presetGroupRelay,
        openai_compatible: copy.presetGroupOpenAiCompatible,
        local: copy.presetGroupLocal,
      };
      return groupModelPresets(workspace?.modelPresetOptions ?? [], labels);
    },
    [copy, workspace?.modelPresetOptions],
  );
  const modelScenarioOptions = useMemo(
    () =>
      [
        { id: "chat" as ModelScenarioId, label: copy.modelScenarioChat },
        { id: "relay" as ModelScenarioId, label: copy.modelScenarioRelay },
        { id: "image" as ModelScenarioId, label: copy.modelScenarioImage },
        { id: "local" as ModelScenarioId, label: copy.modelScenarioLocal },
        { id: "manual" as ModelScenarioId, label: copy.modelScenarioManual },
      ],
    [copy],
  );
  const profileModeGroups = useMemo(() => {
    const labels: ConfigProfileModeGroupLabels = {
      chat: copy.profileGroupChat,
      support: copy.profileGroupSupport,
      subagents: copy.profileGroupSubagents,
      evolution: copy.profileGroupEvolution,
      research: copy.profileGroupResearch,
      other: copy.profileGroupOther,
    };
    return groupConfigProfileCards(workspace?.profileCards ?? [], labels);
  }, [copy, workspace?.profileCards]);
  const modelCenterSummary = useMemo(
    () =>
      deriveModelCenterSummary({
        modelOptions,
        profiles: workspace?.profileCards ?? [],
        publicConfig: draftConfig ?? workspace?.publicConfig ?? {},
        labels: {
          chat: copy.profileGroupChat,
          support: copy.profileGroupSupport,
          subagents: copy.profileGroupSubagents,
          evolution: copy.profileGroupEvolution,
          research: copy.profileGroupResearch,
          other: copy.profileGroupOther,
          image2Tool: copy.image2ToolUsage,
          gitCommitModel: copy.gitCommitModelUsage,
        },
      }),
    [copy, draftConfig, modelOptions, workspace?.profileCards, workspace?.publicConfig],
  );
  const modelCenterRows = useMemo(
    () => deriveModelCenterInventoryRows(modelOptions, modelCenterSummary),
    [modelCenterSummary, modelOptions],
  );
  const agentInstances = agentsQuery.data ?? [];
  const promptTemplates = promptTemplatesQuery.data?.templates ?? [];
  const promptTemplatesById = useMemo(
    () => new Map(promptTemplates.map((template) => [template.promptTemplateId, template])),
    [promptTemplates],
  );
  const promptTemplateUsageTotal = useMemo(
    () => agentInstances.filter((agent) => Boolean(agent.promptTemplateId)).length,
    [agentInstances],
  );
  const modeBindings = modeBindingsQuery.data?.modes ?? null;
  const modeBindingWarnings = modeBindingsQuery.data?.repairWarnings ?? [];
  const activeAgentInstances = useMemo(
    () => agentInstances.filter((agent) => agent.status !== "archived"),
    [agentInstances],
  );

  useEffect(() => {
    if (!visibleSidebarGroups.length) {
      setActiveSectionId("");
      return;
    }
    if (!visibleSidebarGroups.some((section) => section.id === activeSectionId)) {
      setActiveSectionId(visibleSidebarGroups[0].id);
    }
  }, [activeSectionId, visibleSidebarGroups]);

  const sectionMap = useMemo(() => {
    return new Map((workspace?.sections ?? []).map((section) => [section.id, section]));
  }, [workspace?.sections]);
  const pageStyle = useMemo(
    () =>
      ({
        "--sidebar-width": `${sidebarWidth}px`,
      }) as CSSProperties,
    [sidebarWidth],
  );
  const sidebarStyle = useMemo(
    () =>
      ({
        height: `${sidebarHeight}px`,
      }) as CSSProperties,
    [sidebarHeight],
  );
  const saveButtonLabel = busyAction === copy.applying ? copy.applying : copy.saveConfig;
  const editorSyncState = deriveConfigEditorSyncState({
    editorText: jsonText,
    formattedConfigText: formattedDraft,
    configLoaded: Boolean(draftConfig),
    hasUnsavedConfigChanges,
    hasPendingSecretChanges: hasPendingSecretChanges(draftMeta),
    busy: Boolean(busyAction),
  });
  const {
    hasEditorChanges,
    hasPendingApply,
    structuredActionsDisabled,
    canSaveConfig,
    canCheckCurrentChanges,
    canRestoreEditorText,
  } = editorSyncState;
  const profilesEditing = Object.keys(profileEditors).length > 0;
  const shouldBlockLeave = useCallback<BlockerFunction>(
    ({ currentLocation, nextLocation }) =>
      shouldBlockConfigLeave({
        hasPendingApply,
        busy: Boolean(busyAction),
        currentPathname: currentLocation.pathname,
        nextPathname: nextLocation.pathname,
      }),
    [busyAction, hasPendingApply],
  );
  const leaveBlocker = useBlocker(shouldBlockLeave);
  const leaveGuardOpen = leaveBlocker.state === "blocked";
  const leaveGuardSaveLabel = busyAction === copy.leaveGuardSaving ? copy.leaveGuardSaving : copy.leaveGuardSave;
  const sidebarNextStepLabel = hasEditorChanges ? copy.settingsNeedsCheck : hasPendingApply ? copy.settingsCanSave : copy.settingsSynced;

  function updateSectionUiState(sectionId: string, nextState: ConfigSectionUiState) {
    setSectionUiState((current) => ({ ...current, [sectionId]: nextState }));
  }

  function isSectionVisible(sectionId: string): boolean {
    return Boolean(activeSection?.memberSectionIds.includes(sectionId));
  }

  function handleSelectSection(sectionId: string) {
    setActiveSectionId(sectionId);
    updateSectionUiState(sectionId, resolveConfigSectionUiStateOnSelect(sectionUiState[sectionId], defaultSectionUiState()));
    pageRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  }

  function restoreEditorText() {
    setJsonText(formattedDraft);
    setNotice({ tone: "neutral", text: "" });
  }

  const sidebarApplyHint = hasEditorChanges ? copy.editorDirtyHint : hasPendingApply ? copy.saveSourceHint : copy.editorCleanHint;

  async function invalidateWorkbenchQueries(nextConfig: PublicConfigShape) {
    const domains = configInvalidationDomainsForApply(nextConfig);
    const invalidations = [
      queryClient.invalidateQueries({ queryKey: queryKeys.configPublic() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.configWorkspace() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.sessions() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.resetSummary() }),
    ];
    if (domains.includes("evolution")) {
      invalidations.push(
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionOverview() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionRuns() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionLibrary() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionSelfOverview() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionSelfActiveRun() }),
      );
    }
    await Promise.all(invalidations);
  }

  function markError(error: unknown) {
    const text = readableErrorMessage(error);
    setNotice({
      tone: "error",
      text,
    });
    return text;
  }

  function requireDraft(): PublicConfigShape {
    if (!draftConfig) {
      throw new Error(copy.loadFailed);
    }
    return draftConfig;
  }

  function resolveDraftForSubmission(): PublicConfigShape {
    if (!draftConfig) {
      throw new Error(copy.loadFailed);
    }
    if (!hasEditorChanges) {
      return draftConfig;
    }
    return JSON.parse(jsonText) as PublicConfigShape;
  }

  async function previewDraft(nextConfig: PublicConfigShape, nextMeta: ConfigDraftMeta, pendingLabel: string) {
    setBusyAction(pendingLabel);
    try {
      const response = await requestJson<ConfigWorkspace>("/api/config/draft/preview", {
        publicConfig: nextConfig,
        draftMeta: nextMeta,
        baseHash,
      });
      syncWorkspace(response, "success");
      return true;
    } catch (error) {
      markError(error);
      return false;
    } finally {
      setBusyAction("");
    }
  }

  async function reloadWorkspace() {
    setBusyAction(copy.refreshPending);
    try {
      const fresh = await workspaceQuery.refetch();
      if (fresh.data) {
        syncWorkspace(fresh.data);
      }
    } catch (error) {
      markError(error);
    } finally {
      setBusyAction("");
    }
  }

  async function handleOpenEnvironment() {
    setBusyAction(copy.openEnvironmentPending);
    try {
      await requestJson<{ opened: boolean }>("/api/config/open-environment", {});
      setNotice({ tone: "success", text: copy.openEnvironmentOpened });
    } catch (error) {
      markError(error);
    } finally {
      setBusyAction("");
    }
  }

  async function handleApply(pendingLabel: string = copy.applying): Promise<boolean> {
    setBusyAction(pendingLabel);
    try {
      const nextConfig = resolveDraftForSubmission();
      const response = await requestJson<ConfigWorkspace>(
        "/api/config/apply",
        {
          publicConfig: nextConfig,
          draftMeta,
          baseHash,
        },
        "PUT",
      );
      syncWorkspace(response, "success");
      await invalidateWorkbenchQueries(nextConfig);
      return true;
    } catch (error) {
      markError(error);
      return false;
    } finally {
      setBusyAction("");
    }
  }

  async function handleSaveAndLeave() {
    if (leaveBlocker.state !== "blocked" || !canSaveConfig) {
      return;
    }
    const proceed = leaveBlocker.proceed;
    const ok = await handleApply(copy.leaveGuardSaving);
    if (ok) {
      proceed();
    }
  }

  function handleDiscardAndLeave() {
    if (leaveBlocker.state === "blocked") {
      leaveBlocker.proceed();
    }
  }

  function handleCancelLeave() {
    if (leaveBlocker.state === "blocked") {
      leaveBlocker.reset();
    }
  }

  async function handleValidateEditorDraft() {
    try {
      const parsed = JSON.parse(jsonText) as PublicConfigShape;
      await previewDraft(parsed, draftMeta, copy.validationPending);
    } catch (error) {
      markError(error);
    }
  }

  async function updateSimpleDraft(mutator: (nextConfig: PublicConfigShape) => void) {
    try {
      const next = clonePublicConfig(requireDraft());
      mutator(next);
      await previewDraft(next, draftMeta, copy.validationPending);
    } catch (error) {
      markError(error);
    }
  }

  async function saveConfigSection(path: string, nextValue: unknown) {
    try {
      const next = clonePublicConfig(requireDraft());
      const updated = setConfigValueAtPath(next, path, nextValue);
      return await previewDraft(updated, draftMeta, copy.sectionSavePending);
    } catch (error) {
      markError(error);
      return false;
    }
  }

  async function handleAvatarImageUpload(file: File): Promise<AvatarImageUploadResponse | null> {
    setBusyAction(copy.avatarImageUploading);
    try {
      return await requestJson<AvatarImageUploadResponse>("/api/config/avatar-image", {
        filename: file.name,
        contentType: file.type,
        dataBase64: await fileToBase64(file),
      });
    } catch (error) {
      const message = markError(error);
      setNotice({ tone: "error", text: `${copy.avatarImageUploadFailed}${message}` });
      return null;
    } finally {
      setBusyAction("");
    }
  }

  function resolveSelectedProfileModelId(profileId: string, fallback = ""): string {
    return profileEditors[profileId]?.modelId ?? fallback;
  }

  function beginProfilesEdit() {
    const nextEditors: Record<string, ProfileEditState> = {};
    for (const profile of workspace?.profileCards ?? []) {
      nextEditors[profile.profileId] = emptyProfileEditState(profile.selectedModelId);
    }
    setProfileEditors(nextEditors);
  }

  function cancelProfilesEdit() {
    setProfileEditors({});
  }

  function updateProfileModelDraft(profileId: string, modelId: string) {
    setProfileEditors((current) => ({
      ...current,
      [profileId]: emptyProfileEditState(modelId),
    }));
  }

  function resetSidebarWidth() {
    if (typeof window === "undefined") {
      setSidebarWidth(SIDEBAR_WIDTH_DEFAULT);
      return;
    }
    setSidebarWidth(clampSidebarWidth(SIDEBAR_WIDTH_DEFAULT, window.innerWidth));
  }

  function resetSidebarHeight() {
    if (typeof window === "undefined") {
      setSidebarHeight(SIDEBAR_HEIGHT_MIN);
      return;
    }
    setSidebarHeight(clampSidebarHeight(window.innerHeight - SIDEBAR_VIEWPORT_OFFSET, window.innerHeight));
  }

  function beginSidebarResize(axis: "width" | "height" | "both") {
    return (event: ReactPointerEvent<HTMLDivElement>) => {
      if (typeof window === "undefined") {
        return;
      }
      event.preventDefault();
      sidebarResizeCleanupRef.current?.();

      const startX = event.clientX;
      const startY = event.clientY;
      const initialWidth = sidebarWidth;
      const initialHeight = sidebarHeight;
      const cursor = axis === "width" ? "col-resize" : axis === "height" ? "row-resize" : "nwse-resize";

      const handlePointerMove = (moveEvent: PointerEvent) => {
        if (axis !== "height") {
          setSidebarWidth(clampSidebarWidth(initialWidth + (moveEvent.clientX - startX), window.innerWidth));
        }
        if (axis !== "width") {
          setSidebarHeight(clampSidebarHeight(initialHeight + (moveEvent.clientY - startY), window.innerHeight));
        }
      };

      const cleanup = () => {
        window.removeEventListener("pointermove", handlePointerMove);
        window.removeEventListener("pointerup", cleanup);
        window.removeEventListener("pointercancel", cleanup);
        document.body.style.userSelect = "";
        document.body.style.cursor = "";
        sidebarResizeCleanupRef.current = null;
      };

      sidebarResizeCleanupRef.current = cleanup;
      document.body.style.userSelect = "none";
      document.body.style.cursor = cursor;
      window.addEventListener("pointermove", handlePointerMove);
      window.addEventListener("pointerup", cleanup);
      window.addEventListener("pointercancel", cleanup);
    };
  }

  function buildDraftWithSelectedProfileModel(profileId: string, fallback = "") {
    const modelId = resolveSelectedProfileModelId(profileId, fallback);
    if (!modelId) {
      throw new Error(copy.requiredModelMissing);
    }
    const option = modelOptionsById.get(modelId);
    if (!option) {
      throw new Error(`Unknown model: ${modelId}`);
    }
    const next = clonePublicConfig(requireDraft());
    applyModelOptionToProfileDraft(next, profileId, option, modelDetailKeys);
    return { next, option };
  }

  function buildDraftWithSelectedProfileModels() {
    let next = clonePublicConfig(requireDraft());
    let changedCount = 0;
    for (const profile of workspace?.profileCards ?? []) {
      const selectedModelId = resolveSelectedProfileModelId(profile.profileId, profile.selectedModelId);
      if (!selectedModelId || selectedModelId === profile.selectedModelId) {
        continue;
      }
      const option = modelOptionsById.get(selectedModelId);
      if (!option) {
        throw new Error(`Unknown model: ${selectedModelId}`);
      }
      applyModelOptionToProfileDraft(next, profile.profileId, option, modelDetailKeys);
      changedCount += 1;
    }
    return { next, changedCount };
  }

  function applyPreset(presetId: string) {
    setModelEditorExpanded(true);
    setModelEditorError("");
    setModelDiscoveryError("");
    setDiscoveredModels([]);
    setSelectedDiscoveredModelId("");
    const preset = workspace?.modelPresetOptions.find((item) => item.preset_id === presetId);
    if (!preset) {
      setModelEditor((current) => ({ ...current, preset_id: presetId }));
      return;
    }
    const presetModel = asRecord(preset.model);
    const presetModelId = getString(preset.model_id);
    const presetModelName = getString(presetModel.model);
    setModelEditor({
      mode: "create",
      preset_id: presetId,
      model_id: presetId === "custom_openai_compatible_relay" ? "" : presetModelId,
      label: getString(presetModel.label) || preset.label,
      model: presetModelName,
      api_key_env:
        getString(presetModel.api_key_env) ||
        defaultModelApiKeyEnv(
          presetId === "custom_openai_compatible_relay"
            ? modelLibraryIdFromParts(getString(presetModel.label) || preset.label, presetModelName)
            : presetModelId,
        ),
      api_key: "",
      clear_api_key: false,
      provider: buildProviderDraft(asRecord(preset.provider)),
      details: buildModelDetailsDraft(presetModel),
    });
  }

  function applyModelScenario(scenario: ModelScenarioId) {
    const presetId = selectModelScenarioPresetId(scenario, workspace?.modelPresetOptions ?? []);
    if (presetId) {
      applyPreset(presetId);
      return;
    }
    setModelEditorExpanded(true);
    setModelEditorError("");
    setModelDiscoveryError("");
    setDiscoveredModels([]);
    setSelectedDiscoveredModelId("");
    setModelEditor({
      ...emptyModelEditorState(),
      provider: {
        ...emptyProviderDraft(),
        kind: scenario === "local" ? "local" : scenario === "relay" || scenario === "image" ? "relay" : "openai_compatible",
      },
      details: {
        ...emptyModelDetailsDraft(),
        streaming: scenario !== "image",
        tool_calling_mode: scenario === "image" ? "disabled" : "auto",
      },
    });
  }

  function applyDiscoveredModel(model: ConfigDiscoveredModel) {
    const modelName = model.id;
    const nextLabel = model.label || modelName;
    const existingIds = modelOptions.map((option) => option.model_id);
    const nextModelId = modelLibraryIdFromParts(nextLabel, modelName);
    const uniqueModelId = uniqueModelLibraryId(nextModelId, existingIds);
    setSelectedDiscoveredModelId(modelName);
    setModelEditor((current) => ({
      ...current,
      model_id: current.mode === "edit" ? current.model_id : uniqueModelId,
      label: current.mode === "create" ? nextLabel : current.label.trim() || nextLabel,
      model: modelName,
      api_key_env: current.mode === "create" ? defaultModelApiKeyEnv(uniqueModelId) : current.api_key_env.trim() || defaultModelApiKeyEnv(uniqueModelId),
      provider: {
        ...current.provider,
        context_window:
          !current.provider.context_window.trim() && typeof model.contextWindow === "number"
            ? String(model.contextWindow)
            : current.provider.context_window,
      },
    }));
  }

  async function handleDiscoverModels() {
    if (structuredActionsDisabled) {
      return;
    }
    setBusyAction(copy.discoveryPending);
    setModelDiscoveryError("");
    setDiscoveredModels([]);
    try {
      const response = await requestJson<ConfigModelDiscoveryResult>("/api/config/discover-models", {
        publicConfig: requireDraft(),
        draftMeta,
        baseHash,
        provider: buildProviderPayload(modelEditor.provider),
        apiKey: modelEditor.api_key,
      });
      setDiscoveredModels(response.models);
      if (response.models.length) {
        applyDiscoveredModel(response.models[0]);
      } else {
        setModelDiscoveryError(copy.discoveryEmpty);
      }
    } catch (error) {
      setModelDiscoveryError(markError(error));
    } finally {
      setBusyAction("");
    }
  }

  async function handleSaveModel() {
    if (structuredActionsDisabled) {
      return;
    }
    setBusyAction(copy.modelSavePending);
    setModelEditorError("");
    try {
      const endpoint = modelEditor.mode === "edit" ? "/api/config/draft/update-model" : "/api/config/draft/add-model";
      const resolvedModelId =
        modelEditor.mode === "edit"
          ? modelEditor.model_id
          : modelEditor.model_id.trim() ||
            uniqueModelLibraryId(modelLibraryIdFromParts(modelEditor.label || modelEditor.model, modelEditor.model), modelOptions.map((option) => option.model_id));
      const resolvedApiKeyEnv = modelEditor.api_key_env.trim() || defaultModelApiKeyEnv(resolvedModelId);
      const response = await requestJson<ConfigWorkspace>(endpoint, {
        publicConfig: requireDraft(),
        draftMeta,
        baseHash,
        presetId: modelEditor.mode === "create" ? modelEditor.preset_id : "",
        modelId: resolvedModelId,
        provider: buildProviderPayload(modelEditor.provider),
        model: modelEditor.model,
        label: modelEditor.label,
        details: buildModelDetailsPayload(modelEditor.details),
        apiKeyEnv: resolvedApiKeyEnv,
        apiKey: modelEditor.api_key,
        clearApiKey: modelEditor.clear_api_key,
      });
      syncWorkspace(response, "success");
      setModelEditorExpanded(false);
    } catch (error) {
      setModelEditorError(markError(error));
      setModelEditorExpanded(true);
    } finally {
      setBusyAction("");
    }
  }

  async function handleDeleteModel(modelId: string) {
    if (structuredActionsDisabled) {
      return;
    }
    setBusyAction(copy.modelSavePending);
    try {
      const response = await requestJson<ConfigWorkspace>("/api/config/draft/delete-model", {
        publicConfig: requireDraft(),
        draftMeta,
        baseHash,
        modelId,
      });
      syncWorkspace(response, "success");
    } catch (error) {
      markError(error);
    } finally {
      setBusyAction("");
    }
  }

  async function handleAddProfile() {
    if (structuredActionsDisabled) {
      return;
    }
    setBusyAction(copy.profileSavePending);
    try {
      const response = await requestJson<ConfigWorkspace>("/api/config/draft/add-profile", {
        publicConfig: requireDraft(),
        draftMeta,
        baseHash,
        profileId: profileDraft.profile_id,
        sourceProfileId: profileDraft.source_profile_id,
        modelId: profileDraft.model_id,
      });
      syncWorkspace(response, "success");
      setProfileFormExpanded(false);
    } catch (error) {
      markError(error);
    } finally {
      setBusyAction("");
    }
  }

  async function handleApplySelectedProfileModels() {
    if (structuredActionsDisabled) {
      return;
    }
    try {
      const { next, changedCount } = buildDraftWithSelectedProfileModels();
      if (changedCount > 0) {
        await previewDraft(next, draftMeta, copy.profileSavePendingInline);
        setNotice({ tone: "success", text: copy.profileDraftSaved });
      }
      cancelProfilesEdit();
    } catch (error) {
      markError(error);
    }
  }

  async function handleTestProfile(profileId: string) {
    if (structuredActionsDisabled) {
      return;
    }
    setBusyAction(copy.testPending);
    try {
      const result = await requestJson<ConfigLlmTestResult>("/api/config/test-llm", {
        publicConfig: requireDraft(),
        draftMeta,
        baseHash,
        profileId,
      });
      setNotice({
        tone: result.ok ? "success" : "error",
        text: formatTestNotice(result),
      });
    } catch (error) {
      markError(error);
    } finally {
      setBusyAction("");
    }
  }

  async function handleTestSelectedProfile(profileId: string, fallbackModelId = "") {
    if (structuredActionsDisabled) {
      return;
    }
    setBusyAction(copy.testPending);
    try {
      const { next, option } = buildDraftWithSelectedProfileModel(profileId, fallbackModelId);
      const result = await requestJson<ConfigLlmTestResult>("/api/config/test-llm", {
        publicConfig: next,
        draftMeta,
        baseHash,
        profileId,
      });
      setNotice({
        tone: result.ok ? "success" : "error",
        text: formatTestNotice({
          ...result,
          provider_kind: result.provider_kind || option.provider_kind,
          base_url: result.base_url || getString(asRecord(option.provider).base_url),
        }),
      });
    } catch (error) {
      markError(error);
    } finally {
      setBusyAction("");
    }
  }

  async function handleCheckModelImageCapabilities(modelIds: string[] = []) {
    if (structuredActionsDisabled) {
      return;
    }
    setBusyAction(copy.imageCapabilityCheckPending);
    try {
      const response = await requestJson<ConfigWorkspace>("/api/config/draft/check-model-capabilities", {
        publicConfig: requireDraft(),
        draftMeta,
        baseHash,
        modelIds,
      });
      syncWorkspace(response, "success");
    } catch (error) {
      markError(error);
    } finally {
      setBusyAction("");
    }
  }

  function sectionTitle(sectionId: string, fallback: string) {
    return sectionMap.get(sectionId)?.title ?? fallback;
  }

  function keyStateLabel(state: string) {
    switch (state) {
      case "pending":
        return copy.keyPending;
      case "clear_pending":
        return copy.keyClearPending;
      case "configured":
        return copy.keyConfigured;
      default:
        return copy.keyMissing;
    }
  }

  function testScopeLabel(scope: ConfigLlmTestResult["config_scope"]) {
    return scope === "saved" ? copy.testScopeSaved : copy.testScopeDraft;
  }

  function formatTestKeyDetail(result: ConfigLlmTestResult) {
    if (!result.requires_api_key) {
      return `${copy.testKeyNotRequired}${result.api_key_source ? ` (${copy.testKeySourceLabel}: ${result.api_key_source})` : ""}`;
    }
    return result.api_key_source || "-";
  }

  function formatTestNotice(result: ConfigLlmTestResult) {
    const detailParts = [
      testScopeLabel(result.config_scope),
      `${copy.testRouteLabel}: ${[result.provider_kind, result.base_url].filter(Boolean).join(" · ") || "-"}`,
      `${copy.testRuntimeLabel}: ${[result.transport, result.contract].filter(Boolean).join(" · ") || "-"}`,
      `${copy.testKeyLabel}: ${formatTestKeyDetail(result)}`,
    ];
    if (result.capability === "image_input") {
      detailParts.push(`${copy.testCapabilityLabel}: ${imageInputStatusLabel(result)}`);
    }
    return `${result.profile_id} / ${result.model}: ${result.message} [${detailParts.join(" | ")}]`;
  }

  function imageInputStatusFromResult(result: ConfigLlmTestResult): "supported" | "unsupported" | "unknown" {
    return resolveImageInputCapabilityStatus({
      supportsImageInput: result.supports_image_input,
      capabilityStatus: result.capability_status,
    });
  }

  function imageInputStatusLabel(
    result: ConfigLlmTestResult | { status: "supported" | "unsupported" | "unknown" | "failed"; checkedAt?: string } | null | undefined,
  ) {
    const status = !result
      ? "unknown"
      : "ok" in result
        ? imageInputStatusFromResult(result)
        : result.status;
    switch (status) {
      case "supported":
        return copy.imageInputStatusSupported;
      case "unsupported":
        return copy.imageInputStatusUnsupported;
      case "failed":
        return copy.imageInputStatusFailed;
      default:
        return copy.imageInputStatusUnknown;
    }
  }

  function intakeLabel(mode: string) {
    if (mode === "auto") {
      return currentLanguage === "en" ? "automatic review" : "自动审查";
    }
    return currentLanguage === "en" ? "manual operation" : "手工操作";
  }

  if (!draftConfig && workspaceQuery.isLoading) {
    return (
      <div className={styles.page}>
        <section className={styles.loadingSurface}>
          <p className={styles.eyebrow}>Config</p>
          <h1 className={styles.title}>{copy.loading}</h1>
        </section>
      </div>
    );
  }

  if (!draftConfig || !workspace) {
    return (
      <div className={styles.page}>
        <section className={styles.loadingSurface}>
          <p className={styles.eyebrow}>Config</p>
          <h1 className={styles.title}>{copy.loadFailed}</h1>
          <p className={styles.subtitle}>{workspaceQuery.error instanceof Error ? workspaceQuery.error.message : ""}</p>
        </section>
      </div>
    );
  }

  return (
    <div ref={pageRef} className={styles.page} style={pageStyle}>
      {leaveGuardOpen ? (
        <div className={styles.leaveGuardOverlay}>
          <section
            className={styles.leaveGuardPanel}
            role="dialog"
            aria-modal="true"
            aria-labelledby="config-leave-guard-title"
          >
            <div className={styles.leaveGuardCopy}>
              <p className={styles.eyebrow}>Config</p>
              <h2 id="config-leave-guard-title">{copy.leaveGuardTitle}</h2>
              <p>{copy.leaveGuardBody}</p>
              <p className={styles.helperText}>{sidebarApplyHint}</p>
            </div>
            <div className={styles.leaveGuardActions}>
              <button
                type="button"
                className={styles.primaryButton}
                disabled={!canSaveConfig || Boolean(busyAction)}
                onClick={() => {
                  void handleSaveAndLeave();
                }}
              >
                <Save size={14} />
                {leaveGuardSaveLabel}
              </button>
              <button type="button" className={styles.dangerButton} disabled={Boolean(busyAction)} onClick={handleDiscardAndLeave}>
                {copy.leaveGuardDiscard}
              </button>
              <button type="button" className={styles.actionButton} disabled={Boolean(busyAction)} onClick={handleCancelLeave}>
                {copy.leaveGuardCancel}
              </button>
            </div>
          </section>
        </div>
      ) : null}
      <aside className={styles.sidebar} style={sidebarStyle}>
        <div className={styles.sidebarIntro}>
          <p className={styles.eyebrow}>Config</p>
          <h1 className={styles.title}>{copy.pageTitle}</h1>
          <p className={styles.subtitle}>{copy.subtitle}</p>
        </div>

        <div className={styles.sidebarStatus}>
          <div className={styles.sidebarStatusHeader}>
            <span>{copy.settingsStatusTitle}</span>
            <span
              className={
                hasPendingApply
                  ? `${styles.statusBadge} ${styles.statusBadgePending}`
                  : `${styles.statusBadge} ${styles.statusBadgeReady}`
              }
            >
              {hasPendingApply ? copy.unsavedDraft : copy.syncedDraft}
            </span>
          </div>
          <div className={styles.sidebarStatusGrid}>
            <span>
              <small>{copy.settingsNextStep}</small>
              <strong>{sidebarNextStepLabel}</strong>
            </span>
            <span>
              <small>{copy.settingsSections}</small>
              <strong>{visibleSidebarGroups.length}</strong>
            </span>
          </div>
          <button
            type="button"
            className={`${styles.primaryButton} ${styles.buttonBlock}`}
            disabled={!canSaveConfig}
            onClick={() => {
              void handleApply();
            }}
          >
            <Save size={14} />
            {saveButtonLabel}
          </button>
          <span className={styles.helperText}>{sidebarApplyHint}</span>
        </div>

        <section className={sidebarIndexCollapsed ? `${styles.sidebarNavPanel} ${styles.sidebarNavPanelCollapsed}` : styles.sidebarNavPanel}>
          <div className={styles.sidebarPanelHeader}>
            <div className={styles.sidebarPanelIntro}>
              <p className={styles.matrixTitle}>{sectionIndexTitle}</p>
              <p className={styles.helperText}>{sidebarIndexCollapsed ? sectionIndexCollapsedHint : sectionIndexHint}</p>
            </div>
            <div className={styles.sidebarPanelActions}>
              <span className={styles.inlineBadge}>{visibleSidebarGroups.length}</span>
              <button
                type="button"
                className={`${styles.actionButton} ${styles.compactButton} ${styles.sidebarPanelToggle}`}
                aria-expanded={!sidebarIndexCollapsed}
                onClick={() => setSidebarIndexCollapsed((current) => !current)}
              >
                <ChevronRight size={14} className={sidebarIndexCollapsed ? styles.treeToggleIcon : styles.treeToggleIconExpanded} />
                {sectionIndexToggleLabel}
              </button>
            </div>
          </div>
          {sidebarIndexCollapsed ? null : (
            <nav className={styles.sectionNav} aria-label="config sections">
                {visibleSidebarGroups.map((section) => (
                  <button
                    key={section.id}
                    type="button"
                    className={
                      section.id === activeSection?.id
                      ? `${styles.sectionLink} ${styles.sectionLinkActive}`
                      : styles.sectionLink
                  }
                  aria-pressed={section.id === activeSection?.id}
                  onClick={() => handleSelectSection(section.id)}
                  >
                    <span>{section.title}</span>
                    <span className={styles.inlineBadge}>{section.memberSectionIds.length}</span>
                  </button>
                ))}
              </nav>
            )}
          </section>

        <div className={styles.sidebarMetrics}>
          <article className={styles.metricCard}>
            <span>{copy.runtimeProfile}</span>
            <strong>{workspace.runtimeProfile}</strong>
          </article>
          <article className={styles.metricCard}>
            <span>{copy.defaultMode}</span>
            <strong>{workspace.defaultMode}</strong>
          </article>
          <article className={styles.metricCard}>
            <span>{copy.defaultRoute}</span>
            <strong>{workspace.defaultRoute}</strong>
          </article>
          <article className={styles.metricCard}>
            <span>{copy.intakeMode}</span>
            <strong>{intakeLabel(asRecord(draftConfig.evolution).intake_mode as string)}</strong>
          </article>
        </div>
        <div
          className={styles.sidebarResizeX}
          title={resizeWidthTitle}
          onDoubleClick={resetSidebarWidth}
          onPointerDown={beginSidebarResize("width")}
        />
        <div
          className={styles.sidebarResizeY}
          title={resizeHeightTitle}
          onDoubleClick={resetSidebarHeight}
          onPointerDown={beginSidebarResize("height")}
        />
        <div
          className={styles.sidebarResizeCorner}
          title={resizeCornerTitle}
          onDoubleClick={() => {
            resetSidebarWidth();
            resetSidebarHeight();
          }}
          onPointerDown={beginSidebarResize("both")}
        />
      </aside>

      <section className={styles.content}>
        {notice.text ? (
          <div
            className={
              notice.tone === "error"
                ? `${styles.notice} ${styles.noticeError}`
                : notice.tone === "success"
                  ? `${styles.notice} ${styles.noticeSuccess}`
                  : styles.notice
            }
          >
            {notice.text}
          </div>
        ) : null}

        {isSectionVisible("overview") ? (
        <section id="config-overview" className={styles.sectionSurface}>
          <div className={styles.sectionHeader}>
            <div>
              <p className={styles.eyebrow}>{sectionTitle("overview", copy.sourceTitle)}</p>
              <h2 className={styles.sectionTitle}>{copy.sourceTitle}</h2>
            </div>
            <Database size={16} className={styles.sectionIcon} />
          </div>
          <p className={styles.sectionText}>{copy.sourceBody}</p>
          <div className={styles.hashGrid}>
            <article className={styles.detailCard}>
              <span>{copy.configPath}</span>
              <code className={styles.hashValue}>{workspace.configPath}</code>
            </article>
            <article className={styles.detailCard}>
              <span>{copy.configStatus}</span>
              <strong>{hasPendingApply ? copy.unsavedDraft : copy.syncedDraft}</strong>
            </article>
          </div>
          <div className={styles.actionsRow}>
            <button type="button" className={styles.actionButton} disabled={Boolean(busyAction)} onClick={reloadWorkspace}>
              <RefreshCw size={14} />
              {copy.refresh}
            </button>
            <button type="button" className={styles.actionButton} disabled={Boolean(busyAction)} onClick={handleOpenEnvironment}>
              <ExternalLink size={14} />
              {busyAction === copy.openEnvironmentPending ? copy.openEnvironmentPending : copy.openEnvironment}
            </button>
            <button
              type="button"
              className={styles.actionButton}
              disabled={!canRestoreEditorText}
              title={copy.editorRestoreHint}
              onClick={restoreEditorText}
            >
              <RotateCcw size={14} />
              {copy.resetDraft}
            </button>
            <span className={styles.helperText}>{copy.openEnvironmentHint}</span>
          </div>
          <details className={styles.rawConfigPanel}>
            <summary>{copy.rawToml}</summary>
            <p className={styles.helperText}>{copy.rawTomlHint}</p>
            <pre className={styles.rawToml}>{workspace.rawToml}</pre>
          </details>
        </section>
        ) : null}

        {isSectionVisible("shell") ? (
        <section id="config-shell" className={styles.sectionSurface}>
          <div className={styles.sectionHeader}>
            <div>
              <p className={styles.eyebrow}>{sectionTitle("shell", copy.runtimeTitle)}</p>
              <h2 className={styles.sectionTitle}>{copy.runtimeTitle}</h2>
            </div>
            <SlidersHorizontal size={16} className={styles.sectionIcon} />
          </div>
          <p className={styles.sectionText}>{copy.runtimeBody}</p>
          <div className={styles.matrixGrid}>
            <article className={styles.matrixCard}>
              <p className={styles.matrixTitle}>{copy.interfaceLanguage}</p>
              <div className={styles.segmented}>
                {([
                  { value: "zh" as const, label: copy.languageChinese },
                  { value: "en" as const, label: copy.languageEnglish },
                ]).map((item) => (
                  <button
                    key={item.value}
                    type="button"
                    className={
                      getDraftLanguage(draftConfig, workspace.language) === item.value
                        ? `${styles.segmentButton} ${styles.segmentButtonActive}`
                        : styles.segmentButton
                    }
                    disabled={structuredActionsDisabled}
                    onClick={() =>
                      updateSimpleDraft((next) => {
                        const ui = asRecord(next.ui);
                        ui.language = item.value;
                        next.ui = ui;
                      })
                    }
                  >
                    <Languages size={14} />
                    {item.label}
                  </button>
                ))}
              </div>
            </article>

            <article className={styles.matrixCard}>
              <p className={styles.matrixTitle}>{copy.intakeMode}</p>
              <div className={styles.segmented}>
                {(["manual_review", "auto"] as const).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    className={
                      getString(asRecord(draftConfig.evolution).intake_mode) === mode
                        ? `${styles.segmentButton} ${styles.segmentButtonActive}`
                        : styles.segmentButton
                    }
                    disabled={structuredActionsDisabled}
                    onClick={() =>
                      updateSimpleDraft((next) => {
                        const evolution = asRecord(next.evolution);
                        evolution.intake_mode = mode;
                        next.evolution = evolution;
                      })
                    }
                  >
                    {intakeLabel(mode)}
                  </button>
                ))}
              </div>
            </article>
          </div>
        </section>
        ) : null}

        {isSectionVisible("profiles") ? (
        <section id="config-profiles" className={styles.sectionSurface}>
          <div className={styles.sectionHeader}>
            <div>
              <p className={styles.eyebrow}>{sectionTitle("profiles", copy.profilesTitle)}</p>
              <h2 className={styles.sectionTitle}>{copy.profilesTitle}</h2>
            </div>
            <div className={styles.sectionHeaderActions}>
              {profilesEditing ? (
                <>
                  <button
                    type="button"
                    className={`${styles.primaryButton} ${styles.compactButton}`}
                    disabled={structuredActionsDisabled}
                    onClick={handleApplySelectedProfileModels}
                  >
                    <Save size={14} />
                    {copy.saveProfileBatch}
                  </button>
                  <button
                    type="button"
                    className={`${styles.actionButton} ${styles.compactButton}`}
                    disabled={structuredActionsDisabled}
                    onClick={cancelProfilesEdit}
                  >
                    <RotateCcw size={14} />
                    {copy.cancelProfileBatch}
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  className={`${styles.actionButton} ${styles.compactButton}`}
                  disabled={structuredActionsDisabled}
                  onClick={beginProfilesEdit}
                >
                  <Pencil size={14} />
                  {copy.editProfiles}
                </button>
              )}
            </div>
          </div>
          <p className={styles.sectionText}>{copy.profilesBody}</p>
          <div className={styles.profileCardGroups}>
            <div className={styles.profileCardGrid}>
              {profileModeGroups.flatMap((group) =>
                group.profiles.map((profile) => {
                    const profileEditor = profileEditors[profile.profileId];
                    const isEditingProfile = profilesEditing && Boolean(profileEditor);
                    const selectedModelId = resolveSelectedProfileModelId(profile.profileId, profile.selectedModelId);
                    const selectedModel = modelOptionsById.get(selectedModelId) ?? null;
                    const displayState = resolveProfileDisplayState(profile, selectedModelId, selectedModel, isEditingProfile);
                    const selectedImageInputStatus = resolveImageInputCapabilityStatus({
                      supportsImageInput: selectedModel?.supports_image_input,
                      capabilityStatus: selectedModel?.capability_status,
                    });
                    const imageInputStatus = selectedImageInputStatus;
                    const imageInputTitle =
                      selectedModel?.capability_error ||
                      selectedModel?.capability_checked_at ||
                      selectedModel?.capability_source ||
                      copy.imageCapabilityStatus;
                    const keyStateClassName =
                      displayState.apiKeyState === "missing" || displayState.apiKeyState === "clear_pending"
                        ? `${styles.inlineBadge} ${styles.inlineBadgeWarning}`
                        : styles.inlineBadge;
                    const imageInputBadgeClassName =
                      imageInputStatus === "supported"
                        ? `${styles.inlineBadge} ${styles.inlineBadgeSuccess}`
                        : imageInputStatus === "unsupported"
                          ? `${styles.inlineBadge} ${styles.inlineBadgeWarning}`
                          : `${styles.inlineBadge} ${styles.inlineBadgeMuted}`;
                    return (
                      <article key={profile.profileId} className={styles.profileConfigCard}>
                        <div className={styles.profileConfigCardHeader}>
                          <div className={styles.profileTaskCell}>
                            <strong>{profile.label}</strong>
                            <span>{profile.profileId}</span>
                          </div>
                          <div className={styles.profileConfigBadges}>
                            <span className={styles.inlineBadge}>{group.label}</span>
                            {displayState.selectionDirty ? <span className={styles.inlineBadge}>{copy.profileTableStaged}</span> : null}
                          </div>
                        </div>
                        <div className={styles.profileConfigCardBody}>
                          {isEditingProfile ? (
                            <label className={`${styles.field} ${styles.profileCardSelect}`}>
                              <span>{copy.selectedModel}</span>
                              <select
                                value={selectedModelId}
                                disabled={structuredActionsDisabled}
                                onChange={(event) => updateProfileModelDraft(profile.profileId, event.target.value)}
                              >
                                <option value="" />
                                {modelOptions.map((option) => (
                                  <option key={option.model_id} value={option.model_id}>
                                    {option.label}
                                  </option>
                                ))}
                              </select>
                            </label>
                          ) : (
                            <div className={styles.profileModelCell}>
                              <span>{copy.profileTableModel}</span>
                              <strong>{profile.requiredModelMissing ? copy.requiredModelMissing : displayState.selectedModelLabel}</strong>
                              <span>{displayState.model || "-"}</span>
                            </div>
                          )}
                          <div className={styles.profileMetaCell}>
                            <span>{copy.profileTableProvider}</span>
                            <strong>{displayState.providerKind || "-"}</strong>
                            <span>{displayState.baseUrl || "-"}</span>
                          </div>
                          <div className={styles.profileMetaCell}>
                            <span>{copy.profileTableKey}</span>
                            <div className={styles.profileStatusBadges}>
                              <span className={keyStateClassName}>{keyStateLabel(displayState.apiKeyState)}</span>
                              <span className={imageInputBadgeClassName} title={imageInputTitle}>
                                {imageInputStatusLabel({
                                  status: imageInputStatus,
                                  message: "",
                                  checkedAt: selectedModel?.capability_checked_at ?? "",
                                })}
                              </span>
                            </div>
                            {imageInputStatus === "unsupported" ? <span>{copy.imageInputUnsupportedHint}</span> : null}
                          </div>
                        </div>
                        <div className={styles.profileCardActions}>
                          <button
                            type="button"
                            className={`${styles.actionButton} ${styles.compactButton}`}
                            disabled={structuredActionsDisabled || !selectedModelId}
                            onClick={() =>
                              isEditingProfile
                                ? handleTestSelectedProfile(profile.profileId, profile.selectedModelId)
                                : handleTestProfile(profile.profileId)
                            }
                          >
                            <Play size={14} />
                            {isEditingProfile ? copy.testSelectedModel : copy.testConnection}
                          </button>
                        </div>
                      </article>
                    );
                  }),
                )}
            </div>
          </div>
          <div ref={profileFormRef} className={styles.formSurface}>
            <div className={styles.formHeader}>
              <div className={styles.formHeaderIntro}>
                <Plus size={16} />
                <div>
                  <span>{copy.profileAdd}</span>
                  <p className={styles.helperText}>{copy.profilePreparedHint}</p>
                </div>
              </div>
              <button
                type="button"
                className={`${styles.actionButton} ${styles.compactButton}`}
                aria-expanded={profileFormExpanded}
                onClick={() => setProfileFormExpanded((current) => !current)}
              >
                <ChevronRight size={14} className={profileFormExpanded ? styles.treeToggleIconExpanded : styles.treeToggleIcon} />
                {profileFormExpanded ? copy.collapseSection : copy.expandSection}
              </button>
            </div>
            {profileFormExpanded ? (
              <>
                <div className={styles.formGrid}>
                  <label className={styles.field}>
                    <span>{copy.profileId}</span>
                    <input
                      value={profileDraft.profile_id}
                      onChange={(event) => setProfileDraft((current) => ({ ...current, profile_id: event.target.value }))}
                    />
                  </label>
                  <label className={styles.field}>
                    <span>{copy.sourceProfile}</span>
                    <select
                      value={profileDraft.source_profile_id}
                      onChange={(event) =>
                        setProfileDraft((current) => ({ ...current, source_profile_id: event.target.value }))
                      }
                    >
                      {workspace.profileCards.map((profile) => (
                        <option key={profile.profileId} value={profile.profileId}>
                          {profile.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className={styles.field}>
                    <span>{copy.assignModel}</span>
                    <select
                      value={profileDraft.model_id}
                      onChange={(event) => setProfileDraft((current) => ({ ...current, model_id: event.target.value }))}
                    >
                      <option value="" />
                      {modelOptions.map((option) => (
                        <option key={option.model_id} value={option.model_id}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <button
                  type="button"
                  className={styles.primaryButton}
                  disabled={structuredActionsDisabled}
                  onClick={handleAddProfile}
                >
                  <Plus size={14} />
                  {copy.createProfile}
                </button>
              </>
            ) : null}
          </div>
        </section>
        ) : null}

        {isSectionVisible("models") ? (
        <section id="config-models" className={styles.sectionSurface}>
          <div className={styles.sectionHeader}>
            <div>
              <p className={styles.eyebrow}>{sectionTitle("models", copy.modelsTitle)}</p>
              <h2 className={styles.sectionTitle}>{copy.modelsTitle}</h2>
            </div>
            <Blocks size={16} className={styles.sectionIcon} />
          </div>
          <p className={styles.sectionText}>{copy.modelsBody}</p>
          <div className={styles.modelCenterSummaryBar}>
            <span><strong>{modelCenterRows.length}</strong> {copy.modelCenterModels}</span>
            <span><strong>{modelCenterSummary.accounts.length}</strong> {copy.modelCenterAccounts}</span>
            <span><strong>{modelCenterSummary.usages.length}</strong> {copy.modelCenterBindings}</span>
            <span className={modelCenterSummary.unresolvedUsageCount ? styles.summaryBarWarning : undefined}>
              <strong>{modelCenterSummary.unresolvedUsageCount}</strong> {copy.modelCenterIssues}
            </span>
          </div>
          <div className={styles.formSurface} onChange={() => (modelEditorError ? setModelEditorError("") : undefined)}>
            <div className={styles.formHeader}>
              <div className={styles.formHeaderIntro}>
                <Pencil size={16} />
                <span>{modelEditor.mode === "edit" ? copy.modelEditorEdit : copy.modelEditorCreate}</span>
              </div>
              <button
                type="button"
                className={`${styles.actionButton} ${styles.compactButton}`}
                aria-expanded={modelEditorExpanded}
                onClick={() => setModelEditorExpanded((current) => !current)}
              >
                <ChevronRight size={14} className={modelEditorExpanded ? styles.treeToggleIconExpanded : styles.treeToggleIcon} />
                {modelEditorExpanded ? copy.collapseSection : copy.expandSection}
              </button>
            </div>
            {modelEditorExpanded ? (
              <>
                {modelEditor.mode === "create" ? (
                  <>
                    <div className={styles.modelScenarioPicker}>
                      <span>{copy.modelScenario}</span>
                      <div className={styles.modelScenarioButtons}>
                        {modelScenarioOptions.map((scenario) => (
                          <button
                            key={scenario.id}
                            type="button"
                            className={styles.actionButton}
                            onClick={() => applyModelScenario(scenario.id)}
                          >
                            {scenario.id === "image" ? <ImageIcon size={14} /> : <Blocks size={14} />}
                            {scenario.label}
                          </button>
                        ))}
                      </div>
                    </div>
                    <p className={styles.fieldHint}>{copy.modelScenarioHint}</p>
                  </>
                ) : null}
                <div className={styles.formGridWide}>
                  <label className={styles.field}>
                    <span>{copy.preset}</span>
                    <select value={modelEditor.preset_id} onChange={(event) => applyPreset(event.target.value)}>
                      <option value="">{copy.customEntry}</option>
                      {modelPresetGroups.map((group) => (
                        <optgroup key={group.id} label={group.label}>
                          {group.presets.map((preset: ConfigModelPresetOption) => (
                            <option key={preset.preset_id} value={preset.preset_id}>
                              {preset.label}
                            </option>
                          ))}
                        </optgroup>
                      ))}
                    </select>
                  </label>
                  <label className={styles.field}>
                    <span>{copy.modelId}</span>
                    <input
                      value={modelEditor.model_id}
                      onChange={(event) => setModelEditor((current) => ({ ...current, model_id: event.target.value }))}
                      disabled={modelEditor.mode === "edit"}
                      placeholder={copy.autoValue}
                    />
                  </label>
                  <label className={styles.field}>
                    <span>{copy.label}</span>
                    <input value={modelEditor.label} onChange={(event) => setModelEditor((current) => ({ ...current, label: event.target.value }))} />
                  </label>
                  <label className={styles.field}>
                    <span>{copy.modelName}</span>
                    <input value={modelEditor.model} onChange={(event) => setModelEditor((current) => ({ ...current, model: event.target.value }))} />
                  </label>
                  <label className={styles.field}>
                    <span>{copy.providerKind}</span>
                    <select
                      value={modelEditor.provider.kind}
                      onChange={(event) =>
                        setModelEditor((current) => ({
                          ...current,
                          provider: { ...current.provider, kind: event.target.value },
                        }))
                      }
                    >
                      {PROVIDER_KIND_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className={styles.field}>
                    <span>{copy.baseUrl}</span>
                    <input
                      value={modelEditor.provider.base_url}
                      onChange={(event) =>
                        setModelEditor((current) => ({
                          ...current,
                          provider: { ...current.provider, base_url: event.target.value },
                        }))
                      }
                    />
                  </label>
                  <label className={styles.field}>
                    <span>{copy.modelKeyInput}</span>
                    <input
                      type="password"
                      value={modelEditor.api_key}
                      onChange={(event) => setModelEditor((current) => ({ ...current, api_key: event.target.value }))}
                      placeholder={modelEditor.api_key_env || copy.autoValue}
                    />
                  </label>
                </div>
                <p className={styles.fieldHint}>{copy.keyStorageHint}</p>

                <div className={styles.actionsRow}>
                  <button
                    type="button"
                    className={styles.actionButton}
                    disabled={structuredActionsDisabled || busyAction === copy.discoveryPending || !modelEditor.provider.base_url.trim()}
                    onClick={handleDiscoverModels}
                  >
                    <RefreshCw size={14} />
                    {busyAction === copy.discoveryPending ? copy.discoveryPending : copy.discoverModels}
                  </button>
                  <button
                    type="button"
                    className={styles.actionButton}
                    disabled={structuredActionsDisabled || busyAction === copy.imageCapabilityCheckPending || !modelOptions.length}
                    onClick={() => void handleCheckModelImageCapabilities()}
                  >
                    <ImageIcon size={14} />
                    {busyAction === copy.imageCapabilityCheckPending ? copy.imageCapabilityCheckPending : copy.checkAllImageCapabilities}
                  </button>
                  {discoveredModels.length ? (
                    <label className={`${styles.field} ${styles.profileTableSelect}`}>
                      <span>{copy.discoveredModel}</span>
                      <select
                        value={selectedDiscoveredModelId}
                        onChange={(event) => {
                          const selected = discoveredModels.find((item) => item.id === event.target.value);
                          if (selected) {
                            applyDiscoveredModel(selected);
                          }
                        }}
                      >
                        {discoveredModels.map((model) => (
                          <option key={model.id} value={model.id}>
                            {model.label || model.id}
                          </option>
                        ))}
                      </select>
                    </label>
                  ) : null}
                  {modelDiscoveryError ? (
                    <span className={styles.inlineFormError}>
                      {copy.discoveryFailed}: {modelDiscoveryError}
                    </span>
                  ) : null}
                </div>

                <details className={styles.advancedEditorPanel}>
                  <summary>
                    <span>{copy.modelEditorAdvancedTitle}</span>
                    <small>{copy.modelEditorAdvancedHint}</small>
                  </summary>
                  <p className={styles.fieldHint}>{copy.keyEnvAdvancedHint}</p>
                  <div className={styles.formGridWide}>
                    <label className={styles.field}>
                      <span>{copy.providerKeyEnv}</span>
                      <input
                        value={modelEditor.provider.api_key_env}
                        onChange={(event) =>
                          setModelEditor((current) => ({
                            ...current,
                            provider: { ...current.provider, api_key_env: event.target.value },
                          }))
                        }
                      />
                    </label>
                    <label className={styles.field}>
                      <span>{copy.modelKeyEnv}</span>
                      <input
                        value={modelEditor.api_key_env}
                        onChange={(event) => setModelEditor((current) => ({ ...current, api_key_env: event.target.value }))}
                      />
                    </label>
                    <label className={styles.field}>
                      <span>{copy.compatMode}</span>
                      <input
                        value={modelEditor.provider.compat_mode}
                        onChange={(event) =>
                          setModelEditor((current) => ({
                            ...current,
                            provider: { ...current.provider, compat_mode: event.target.value },
                          }))
                        }
                      />
                    </label>
                    <label className={styles.field}>
                      <span>{copy.contextWindow}</span>
                      <input
                        value={modelEditor.provider.context_window}
                        onChange={(event) =>
                          setModelEditor((current) => ({
                            ...current,
                            provider: { ...current.provider, context_window: event.target.value },
                          }))
                        }
                      />
                    </label>
                    <label className={styles.field}>
                      <span>{copy.transport}</span>
                      <input
                        value={modelEditor.details.transport}
                        onChange={(event) =>
                          setModelEditor((current) => ({
                            ...current,
                            details: { ...current.details, transport: event.target.value },
                          }))
                        }
                      />
                    </label>
                    <label className={styles.field}>
                      <span>{copy.contract}</span>
                      <input
                        value={modelEditor.details.contract}
                        onChange={(event) =>
                          setModelEditor((current) => ({
                            ...current,
                            details: { ...current.details, contract: event.target.value },
                          }))
                        }
                      />
                    </label>
                    <label className={styles.field}>
                      <span>{copy.reasoningStateField}</span>
                      <input
                        value={modelEditor.details.reasoning_state_field}
                        onChange={(event) =>
                          setModelEditor((current) => ({
                            ...current,
                            details: { ...current.details, reasoning_state_field: event.target.value },
                          }))
                        }
                      />
                    </label>
                    <label className={styles.field}>
                      <span>{copy.toolCallingMode}</span>
                      <input
                        value={modelEditor.details.tool_calling_mode}
                        onChange={(event) =>
                          setModelEditor((current) => ({
                            ...current,
                            details: { ...current.details, tool_calling_mode: event.target.value },
                          }))
                        }
                      />
                    </label>
                    <label className={styles.field}>
                      <span>{copy.temperature}</span>
                      <input
                        value={modelEditor.details.temperature}
                        onChange={(event) =>
                          setModelEditor((current) => ({
                            ...current,
                            details: { ...current.details, temperature: event.target.value },
                          }))
                        }
                      />
                    </label>
                    <label className={styles.field}>
                      <span>{copy.maxOutputTokens}</span>
                      <input
                        value={modelEditor.details.max_output_tokens}
                        onChange={(event) =>
                          setModelEditor((current) => ({
                            ...current,
                            details: { ...current.details, max_output_tokens: event.target.value },
                          }))
                        }
                      />
                    </label>
                    <label className={styles.field}>
                      <span>{copy.timeout}</span>
                      <input
                        value={modelEditor.details.timeout}
                        onChange={(event) =>
                          setModelEditor((current) => ({
                            ...current,
                            details: { ...current.details, timeout: event.target.value },
                          }))
                        }
                      />
                    </label>
                    <label className={styles.field}>
                      <span>{copy.connectTimeout}</span>
                      <input
                        value={modelEditor.details.connect_timeout}
                        onChange={(event) =>
                          setModelEditor((current) => ({
                            ...current,
                            details: { ...current.details, connect_timeout: event.target.value },
                          }))
                        }
                      />
                    </label>
                  </div>
                </details>

                <div className={styles.toggleGrid}>
                  <label className={styles.toggleField}>
                    <input
                      type="checkbox"
                      checked={modelEditor.provider.requires_api_key}
                      onChange={(event) =>
                        setModelEditor((current) => ({
                          ...current,
                          provider: { ...current.provider, requires_api_key: event.target.checked },
                        }))
                      }
                    />
                    <span>{copy.requiresApiKey}</span>
                  </label>
                  <label className={styles.toggleField}>
                    <input
                      type="checkbox"
                      checked={modelEditor.details.strict_compatibility}
                      onChange={(event) =>
                        setModelEditor((current) => ({
                          ...current,
                          details: { ...current.details, strict_compatibility: event.target.checked },
                        }))
                      }
                    />
                    <span>{copy.strictCompatibility}</span>
                  </label>
                  <label className={styles.toggleField}>
                    <input
                      type="checkbox"
                      checked={modelEditor.details.streaming}
                      onChange={(event) =>
                        setModelEditor((current) => ({
                          ...current,
                          details: { ...current.details, streaming: event.target.checked },
                        }))
                      }
                    />
                    <span>{copy.streaming}</span>
                  </label>
                  <label className={styles.toggleField}>
                    <input
                      type="checkbox"
                      checked={modelEditor.details.discovery_enabled}
                      onChange={(event) =>
                        setModelEditor((current) => ({
                          ...current,
                          details: { ...current.details, discovery_enabled: event.target.checked },
                        }))
                      }
                    />
                    <span>{copy.discoveryEnabled}</span>
                  </label>
                  <label className={styles.toggleField}>
                    <input
                      type="checkbox"
                      checked={modelEditor.clear_api_key}
                      onChange={(event) => setModelEditor((current) => ({ ...current, clear_api_key: event.target.checked }))}
                    />
                    <span>{copy.clearSecret}</span>
                  </label>
                </div>
                <p className={styles.fieldHint}>{copy.deleteModelHint}</p>

                <div className={styles.actionsRow}>
                  <button type="button" className={styles.primaryButton} disabled={structuredActionsDisabled} onClick={handleSaveModel}>
                    <Save size={14} />
                    {copy.saveModel}
                  </button>
                  <button
                    type="button"
                    className={styles.actionButton}
                      onClick={() => {
                        setModelEditorError("");
                        setModelEditor(emptyModelEditorState());
                        setModelEditorExpanded(false);
                      }}
                  >
                    <RotateCcw size={14} />
                    {copy.cancelEditing}
                  </button>
                  {modelEditor.mode === "edit" ? (
                    <button
                      type="button"
                      className={styles.dangerButton}
                      disabled={structuredActionsDisabled}
                      onClick={() => handleDeleteModel(modelEditor.model_id)}
                    >
                      <Trash2 size={14} />
                      {copy.deleteModel}
                    </button>
                  ) : null}
                </div>
                {modelEditorError ? (
                  <p className={styles.inlineFormError} role="alert" aria-live="assertive">
                    <strong>{copy.modelSaveFailed}</strong> {modelEditorError}
                  </p>
                ) : null}
              </>
            ) : null}
          </div>

          <div className={styles.profileTableWrap}>
            <table className={`${styles.profileTable} ${styles.modelInventoryTable}`}>
              <thead>
                <tr>
                  <th>{copy.modelCenterInventory}</th>
                  <th>{copy.providerKind}</th>
                  <th>{copy.modelId}</th>
                  <th>{copy.modelCenterHealth}</th>
                  <th>{copy.modelCenterUsage}</th>
                  <th>{copy.modelCenterSource}</th>
                  <th>{copy.profileTableActions}</th>
                </tr>
              </thead>
              <tbody>
                {modelCenterRows.map((row) => {
                  const option = modelOptionsById.get(row.modelId);
                  const sourceLabel = row.source === "profile" ? copy.sourceProfileGenerated : copy.sourceLibrary;
                  return (
                    <tr key={row.modelId}>
                      <td className={styles.profileTaskCell}>
                        <strong>{row.label}</strong>
                        <span>{row.model}</span>
                      </td>
                      <td className={styles.profileMetaCell}>
                        <strong>{row.providerKind}</strong>
                        <span>{row.baseUrl || "-"}</span>
                      </td>
                      <td className={styles.profileMetaCell}>
                        <strong>{row.modelId}</strong>
                        <span>{row.apiKeyEnv || copy.autoValue}</span>
                      </td>
                      <td className={styles.profileMetaCell}>
                        <span className={row.apiKeyState === "missing" || row.apiKeyState === "clear_pending" ? `${styles.inlineBadge} ${styles.inlineBadgeWarning}` : styles.inlineBadge}>
                          {keyStateLabel(row.apiKeyState)}
                        </span>
                        <span
                          className={
                            row.imageInputStatus === "supported"
                              ? `${styles.inlineBadge} ${styles.inlineBadgeSuccess}`
                              : row.imageInputStatus === "unsupported"
                                ? `${styles.inlineBadge} ${styles.inlineBadgeWarning}`
                                : styles.inlineBadge
                          }
                          title={row.capabilityError || row.capabilityCheckedAt || row.capabilitySource || copy.imageCapabilityStatus}
                        >
                          {imageInputStatusLabel({
                            status: row.imageInputStatus,
                            message: row.capabilityError,
                            checkedAt: row.capabilityCheckedAt,
                          })}
                        </span>
                      </td>
                      <td className={styles.profileMetaCell}>
                        <strong>{row.usageCount} {copy.modelCenterUsageCount}</strong>
                        {row.usages.length ? (
                          <>
                            {row.usages.slice(0, 3).map((usage) => (
                              <span key={usage.id}>{usage.groupLabel} · {usage.label}</span>
                            ))}
                            {row.usages.length > 3 ? <span>{row.usages.length - 3} {copy.modelCenterUsageMore}</span> : null}
                          </>
                        ) : (
                          <span>{copy.modelCenterNoUsage}</span>
                        )}
                      </td>
                      <td className={styles.profileMetaCell}>
                        <span className={styles.inlineBadge}>{sourceLabel}</span>
                      </td>
                      <td>
                        <div className={styles.profileTableActions}>
                          <button
                            type="button"
                            className={`${styles.actionButton} ${styles.compactButton}`}
                            disabled={!row.editable || !option}
                            onClick={() => {
                              if (!option) {
                                return;
                              }
                              setModelEditorError("");
                              setModelEditor(hydrateModelEditorFromOption(option));
                              setModelEditorExpanded(true);
                            }}
                          >
                            <Pencil size={14} />
                            {copy.modelEditorEdit}
                          </button>
                          <button
                            type="button"
                            className={`${styles.actionButton} ${styles.compactButton}`}
                            disabled={structuredActionsDisabled || busyAction === copy.imageCapabilityCheckPending || !option}
                            onClick={() => void handleCheckModelImageCapabilities([row.modelId])}
                          >
                            <ImageIcon size={14} />
                            {copy.checkModelImageCapability}
                          </button>
                          <button
                            type="button"
                            className={`${styles.dangerButton} ${styles.compactButton}`}
                            disabled={structuredActionsDisabled || !row.deletable}
                            onClick={() => handleDeleteModel(row.modelId)}
                          >
                            <Trash2 size={14} />
                            {copy.deleteModel}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
        ) : null}

        {isSectionVisible("agent") ? (
        <section id="config-agent-center" className={styles.sectionSurface}>
          <div className={styles.sectionHeader}>
            <div>
              <p className={styles.eyebrow}>{sectionTitle("agent", copy.agentConfigCenterTitle)}</p>
              <h2 className={styles.sectionTitle}>{copy.agentConfigCenterTitle}</h2>
            </div>
            <div className={styles.sectionHeaderActions}>
              <Link className={styles.primaryButton} to="/agents">
                <ExternalLink size={14} />
                {copy.openAgentManagement}
              </Link>
              <Blocks size={16} className={styles.sectionIcon} />
            </div>
          </div>
          <p className={styles.sectionText}>{copy.agentConfigCenterBody}</p>
          <div className={styles.matrixGrid}>
            <article className={styles.matrixCard}>
              <p className={styles.matrixTitle}>{copy.agentConfigActive}</p>
              <strong>{agentsQuery.isPending ? copy.loading : activeAgentInstances.length}</strong>
              <span>{copy.agentConfigCenterBody}</span>
            </article>
            <article className={styles.matrixCard}>
              <p className={styles.matrixTitle}>{copy.modeBindingTitle}</p>
              <strong>{modeBindingWarnings.length}</strong>
              <span>{modeBindingWarnings.length ? copy.warningSignals : copy.noWarnings}</span>
            </article>
            <article className={styles.matrixCard}>
              <p className={styles.matrixTitle}>{copy.promptTemplateCenterTitle}</p>
              <strong>{promptTemplatesQuery.isPending ? copy.loading : promptTemplates.length}</strong>
              <span>{copy.promptTemplateUsage}: {promptTemplateUsageTotal}</span>
            </article>
          </div>
        </section>
        ) : null}

        {isSectionVisible("prompt") ? (
        <section id="config-prompt-templates" className={styles.sectionSurface}>
          <div className={styles.sectionHeader}>
            <div>
              <p className={styles.eyebrow}>{sectionTitle("prompt", copy.promptTemplateCenterTitle)}</p>
              <h2 className={styles.sectionTitle}>{copy.promptTemplateCenterTitle}</h2>
            </div>
            <Pencil size={16} className={styles.sectionIcon} />
          </div>
          <p className={styles.sectionText}>{copy.promptTemplateCenterBody}</p>
          <div className={styles.promptTemplateGrid}>
            <article className={styles.promptTemplateCard}>
              <div className={styles.promptTemplateMain}>
                <strong>{promptTemplatesQuery.isPending ? copy.loading : promptTemplates.length}</strong>
                <span>{copy.promptTemplateCenterTitle}</span>
              </div>
              <div className={styles.promptTemplateMeta}>
                <span>{copy.promptTemplateCategory}: {new Set(promptTemplates.map((template) => template.category || "general")).size}</span>
                <span>{copy.promptTemplateUsage}: {promptTemplateUsageTotal}</span>
              </div>
            </article>
            <article className={styles.promptTemplateCard}>
              <div className={styles.promptTemplateMain}>
                <strong>{copy.promptTemplateUsage}</strong>
                <span>{copy.promptTemplateCenterBody}</span>
              </div>
              <div className={styles.formActions}>
                <Link className={styles.primaryButton} to="/agents/prompts">
                  <ExternalLink size={14} />
                  {copy.promptTemplateOpenCenter}
                </Link>
                <Link className={styles.actionButton} to="/agents/prompts?category=research">
                  <Pencil size={14} />
                  {copy.promptTemplateOpenResearch}
                </Link>
              </div>
            </article>
          </div>
          {!promptTemplates.length && !promptTemplatesQuery.isPending ? (
            <p className={styles.helperText}>{copy.promptTemplateEmpty}</p>
          ) : null}
        </section>
        ) : null}

        {activeEditorSections.map((section) => (
          <ConfigSectionEditor
            key={section.id}
            section={section}
            value={getConfigValueAtPath(draftConfig, section.path)}
            metaMap={editorMeta}
            copy={copy}
            disabled={structuredActionsDisabled}
            uiState={sectionUiState[section.id] ?? defaultSectionUiState()}
            onUiStateChange={updateSectionUiState}
            onSaveSection={saveConfigSection}
            onAvatarImageUpload={handleAvatarImageUpload}
          />
        ))}

        {isSectionVisible("draft") ? (
        <section id="config-draft" className={styles.sectionSurface}>
          <div className={styles.sectionHeader}>
            <div>
              <p className={styles.eyebrow}>{sectionTitle("draft", copy.draftTitle)}</p>
              <h2 className={styles.sectionTitle}>{copy.draftTitle}</h2>
            </div>
            <Database size={16} className={styles.sectionIcon} />
          </div>
          <p className={styles.sectionText}>{copy.draftBody}</p>
          <div className={styles.actionsRow}>
            <button type="button" className={styles.actionButton} disabled={!canCheckCurrentChanges} onClick={handleValidateEditorDraft}>
              <RefreshCw size={14} />
              {copy.validateDraft}
            </button>
            <button
              type="button"
              className={styles.actionButton}
              disabled={!canRestoreEditorText}
              title={copy.editorRestoreHint}
              onClick={restoreEditorText}
            >
              <RotateCcw size={14} />
              {copy.resetDraft}
            </button>
            <span className={styles.helperText}>{hasEditorChanges ? copy.editorDirtyHint : copy.editorCleanHint}</span>
          </div>
          <div className={styles.editorWrap}>
            <CodeMirror
              value={jsonText}
              theme={workbenchCodeMirrorTheme}
              height="100%"
              extensions={[json(), EditorView.lineWrapping]}
              onChange={(value) => setJsonText(value)}
              basicSetup={{
                foldGutter: false,
                allowMultipleSelections: false,
              }}
            />
          </div>
        </section>
        ) : null}

        {isSectionVisible("health-diagnostics") ? (
          <LogHelperCenter
            diagnostics={healthDiagnosticsQuery.data}
            loading={healthDiagnosticsQuery.isLoading || healthDiagnosticsQuery.isFetching}
            lang={currentLanguage}
            copy={copy}
            onRefresh={() => {
              void healthDiagnosticsQuery.refetch();
            }}
          />
        ) : null}

        {isSectionVisible("diagnostics") ? (
        <section id="config-diagnostics" className={styles.sectionSurface}>
          <div className={styles.sectionHeader}>
            <div>
              <p className={styles.eyebrow}>{sectionTitle("diagnostics", copy.diagnosticsTitle)}</p>
              <h2 className={styles.sectionTitle}>{copy.diagnosticsTitle}</h2>
            </div>
            <ShieldAlert size={16} className={styles.sectionIcon} />
          </div>
          <p className={styles.sectionText}>{copy.diagnosticsBody}</p>
          <div className={styles.diagnosticsGrid}>
            <article className={styles.matrixCard}>
              <p className={styles.matrixTitle}>{copy.blockingIssues}</p>
              {workspace.diagnosis.blocking_issues.length ? (
                <ul className={styles.issueList}>
                  {workspace.diagnosis.blocking_issues.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p className={styles.helperText}>{copy.noBlocking}</p>
              )}
            </article>
            <article className={styles.matrixCard}>
              <p className={styles.matrixTitle}>{copy.warningSignals}</p>
              {workspace.diagnosis.warnings.length ? (
                <ul className={styles.issueList}>
                  {workspace.diagnosis.warnings.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p className={styles.helperText}>{copy.noWarnings}</p>
              )}
            </article>
            <article className={styles.matrixCard}>
              <p className={styles.matrixTitle}>{copy.suggestedActions}</p>
              {workspace.diagnosis.suggested_actions.length ? (
                <ul className={styles.issueList}>
                  {workspace.diagnosis.suggested_actions.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p className={styles.helperText}>{copy.noSuggestions}</p>
              )}
            </article>
          </div>
        </section>
        ) : null}
      </section>
    </div>
  );
}
