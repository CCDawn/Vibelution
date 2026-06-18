import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Blocks,
  ChevronRight,
  Database,
  ExternalLink,
  Image as ImageIcon,
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
  ConfigProviderPresetOption,
  ConfigWorkspace,
  HealthDiagnostics,
  HealthFinding,
  HealthQuickAction,
  LogHelper,
  SessionHelper,
} from "../api/types";
import {
  asRecord,
  avatarCropSourceRect,
  clonePublicConfig,
  buildConfigApplyPayload,
  configInvalidationDomainsForApply,
  defaultModelApiKeyEnv,
  deriveConfigEditorSyncState,
  deriveModelCenterInventoryRows,
  deriveModelCenterSummary,
  countModelCenterHealthIssues,
  getString,
  clampAvatarCropOffset,
  groupProviderPresetsByVendor,
  hasPendingSecretChanges,
  modelLibraryIdFromParts,
  pickEditableConfigView,
  canDiscoverModelsForProvider,
  MODEL_CONTRACT_OPTIONS,
  MODEL_PROMPT_CACHE_MODE_OPTIONS,
  MODEL_TOOL_CALLING_MODE_OPTIONS,
  MODEL_TRANSPORT_OPTIONS,
  PROVIDER_KIND_OPTIONS,
  PROVIDER_COMPAT_MODE_OPTIONS,
  resolveConfigSectionUiStateOnSelect,
  resolveImageInputCapabilityStatus,
  shouldBlockConfigLeave,
  selectModelScenarioProviderPresetId,
  type ModelScenarioId,
  uniqueModelLibraryId,
  type PublicConfigShape,
} from "./configRouteLogic";
import { LazyJsonCodeMirror } from "../components/editor/LazyJsonCodeMirror";
import styles from "./ConfigRoute.module.css";

type ConfigLanguage = "zh" | "en";
type NoticeTone = "neutral" | "success" | "error";

type ProviderDraft = {
  kind: string;
  api: string;
  api_key_env: string;
  base_url: string;
  compat_mode: string;
  requires_api_key: boolean;
  context_window: string;
};

type ModelDetailsDraft = {
  transport: string;
  contract: string;
  protocol: string;
  compat: string;
  reasoning_state_field: string;
  strict_compatibility: boolean;
  temperature: string;
  max_output_tokens: string;
  timeout: string;
  connect_timeout: string;
  streaming: boolean;
  tool_calling_mode: string;
  prompt_cache_mode: string;
  prompt_cache_configured: boolean;
  discovery_enabled: boolean;
  supports_image_input: "unknown" | "supported" | "unsupported";
};

type ModelEditorState = {
  mode: "create" | "edit";
  preset_id: string;
  provider_template_id: string;
  model_id: string;
  label: string;
  model: string;
  api_key_env: string;
  api_key: string;
  clear_api_key: boolean;
  provider: ProviderDraft;
  details: ModelDetailsDraft;
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

function ConfigWorkspacePlaceholder({
  title,
  subtitle,
  tone = "loading",
}: {
  title: string;
  subtitle?: string;
  tone?: "loading" | "error";
}) {
  const navLabels = ["Source", "Runtime", "Models", "Diagnostics", "Tools"];
  const matrixLabels = ["operator config", "providers", "models", "runtime"];
  return (
    <div className={`${styles.loadingShell} ${tone === "error" ? styles.loadingShellError : ""}`}>
      <aside className={styles.loadingNavPanel}>
        <p className={styles.eyebrow}>Config</p>
        <h1 className={styles.title}>{title}</h1>
        {subtitle ? <p className={styles.subtitle}>{subtitle}</p> : null}
        <div className={styles.loadingNavList} aria-hidden="true">
          {navLabels.map((label, index) => (
            <span key={label} className={index === 0 ? styles.loadingNavActive : undefined}>
              {label}
            </span>
          ))}
        </div>
      </aside>
      <section className={styles.loadingBoard} aria-hidden="true">
        <div className={styles.loadingBoardHeader}>
          <span />
          <span />
          <span />
        </div>
        <div className={styles.loadingMetricGrid}>
          {matrixLabels.map((label) => (
            <span key={label}>
              <small>{label}</small>
              <strong />
            </span>
          ))}
        </div>
        <div className={styles.loadingSpecGrid}>
          <span />
          <span />
          <span />
          <span />
          <span />
          <span />
        </div>
      </section>
    </div>
  );
}

export const CONFIG_COPY = {
  zh: {
    pageTitle: "统一配置工作台",
    subtitle: "结构化配置、模型资产与保存状态。启动设置在 Launcher 面板维护。",
    subtitleHint: "启动设置在 Launcher 面板维护；结构化编辑、完整配置检查和最终保存仍收口到外部 operator config.toml。",
    loading: "正在加载统一配置工作区...",
    loadFailed: "配置工作区加载失败",
    sourceTitle: "保存与生效",
    sourceBody: "这里显示当前修改是否已经保存，以及哪些系统级设置需要重启后才会生效。",
    sourceBodyShort: "保存状态、配置路径和外部环境入口。",
    runtimeTitle: "运行时与界面",
    runtimeBody: "非启动类界面、治理和高级配置。",
    modelsTitle: "模型库",
    modelsBody: "这里只管理模型资产：服务商、模型名、密钥状态、能力检测和连通性测试。每个 Agent 的具体模型选择请到 Agent 管理中维护。",
    modelsBodyShort: "模型资产、密钥状态、能力检测和连通性。",
    draftTitle: "高级配置检查",
    draftBody: "检查整份当前配置；保存只写外部 operator config.toml。",
    diagnosticsTitle: "诊断与保存",
    diagnosticsBody: "阻塞问题、警告和保存动作。",
    configPath: "配置路径",
    configStatus: "当前状态",
    rawToml: "当前外部 config.toml",
    rawTomlHint: "这里只读显示真实文件内容；修改并保存后会更新这里。",
    syncedDraft: "已和外部 config.toml 一致",
    unsavedDraft: "有未保存修改",
    refresh: "重新读取",
    validateDraft: "检查当前修改",
    resetDraft: "还原编辑文本",
    openEnvironment: "打开系统环境变量",
    openEnvironmentHint: "会打开 Windows 系统窗口，方便你自己查看当前使用了哪些 key。",
    openEnvironmentPending: "正在打开系统环境变量",
    openEnvironmentOpened: "已打开系统环境变量窗口。",
    saveConfig: "保存到外部配置",
    applying: "保存中",
    leaveGuardTitle: "还有未保存的设置",
    leaveGuardBody: "本次修改还没有保存到外部 operator config.toml。离开前要保存吗？",
    leaveGuardSave: "保存并离开",
    leaveGuardSaving: "保存后离开中",
    leaveGuardDiscard: "不保存离开",
    leaveGuardCancel: "取消",
    intakeMode: "进化审核",
    groupOverviewSaveTitle: "总览与保存",
    groupOverviewSaveSummary: "查看保存状态、重新读取配置，并处理系统环境变量。",
    groupWorkbenchTitle: "界面与高级配置",
    groupWorkbenchSummary: "启动设置移到 Launcher；这里保留 shell、非启动类界面和配置检查。",
    groupAvatarPetTitle: "用户、终端形象与陪伴体",
    groupAvatarPetSummary: "统一管理用户信息、终端形象、宠物与陪伴体相关配置；Web 用户头像在用户信息里维护。",
    groupModelingTitle: "模型库",
    groupModelingSummary: "模型资产、服务商账号、密钥、能力检测和模型发现都在这里集中管理。",
    groupRuntimeContextTitle: "运行时与上下文",
    groupRuntimeContextSummary: "只保留全局上下文压缩、分析和高级运行策略；Agent 个体配置在 Agent 管理维护。",
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
    developerModeReadonly: "开发者模式",
    developerModeControlled: "Launcher 控制",
    developerModeEnabled: "已开启",
    developerModeDisabled: "已关闭",
    runtimeProfile: "运行档位",
    defaultMode: "默认模式",
    defaultRoute: "默认入口",
    modelEditorCreate: "新增模型",
    modelEditorEdit: "编辑模型",
    modelCenterAccounts: "服务商账号",
    modelCenterInventory: "模型库存",
    modelCenterHealth: "状态",
    modelCenterModels: "模型",
    modelCenterCapabilityIssues: "需关注",
    modelCenterActions: "操作",
    modelCenterProtocol: "协议链路",
    modelScenario: "新增方式",
    modelScenarioChat: "通用对话模型",
    modelScenarioRelay: "中转站模型",
    modelScenarioImage: "图片工具模型",
    modelScenarioLocal: "本地模型",
    modelScenarioManual: "高级手填",
    modelScenarioHint: "选择场景会自动套用最接近的模板；服务商、模型名和密钥仍可以在下方调整。",
    preset: "厂商",
    providerVendor: "厂商",
    providerTemplate: "模板",
    providerTemplatePlaceholder: "选择模板",
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
    discoveryUnavailable: "当前服务商不支持自动发现，请手动填写模型名。",
    providerKind: "服务商类型",
    providerKeyEnv: "服务商默认变量",
    modelKeyEnv: "模型唯一变量",
    modelKeyInput: "API Key",
    keyStorageHint: "填写后先进入本次修改；点击“保存到外部配置”时才会写入本机用户级环境变量。",
    keyEnvAdvancedHint: "模型密钥变量名由模型 ID 唯一生成并只读展示；真正填写的是 API Key，保存时写入这个用户级环境变量。服务商默认变量仅作兼容来源展示，不作为新增密钥入口。",
    deleteModelHint: "删除模型会同步清理该模型唯一绑定的环境密钥；Agent 与工具的模型选择请在各自管理页调整。",
    deleteModelConfirm: "确认删除这个模型？这会清理它绑定的环境密钥，并从模型库移除该资产。",
    baseUrl: "基础地址",
    compatMode: "兼容模式",
    providerApi: "Provider API",
    modelProtocol: "模型协议",
    modelCompat: "兼容策略对象",
    contextWindow: "上下文窗口",
    requiresApiKey: "需要 API Key",
    imageInputSupport: "图像输入",
    imageInputSupportUnknown: "未声明",
    imageInputSupportSupported: "支持",
    imageInputSupportUnsupported: "不支持",
    transport: "传输协议",
    contract: "交互契约",
    reasoningStateField: "推理状态字段",
    toolCallingMode: "工具调用",
    promptCacheMode: "Prompt cache",
    strictCompatibility: "严格兼容",
    streaming: "流式",
    discoveryEnabled: "发现能力",
    temperature: "温度",
    maxOutputTokens: "最大输出令牌数",
    timeout: "超时（秒）",
    connectTimeout: "连接超时（秒）",
    clearSecret: "保存时同时清除这个环境变量里的密钥",
    saveModel: "确认模型修改",
    modelRequiredFieldsMissing: "请先填写模型名和基础地址。",
    deleteModel: "删除模型",
    cancelEditing: "清空表单",
    modelTestSelect: "测试模型",
    modelTestPlaceholder: "选择一个模型",
    testSelectedLibraryModel: "测试选中模型",
    modelTestRequired: "请先选择要测试的模型。",
    checkSavedImageCapabilities: "检测已保存模型图像输入",
    imageCapabilityCheckPending: "检测模型能力中",
    imageCapabilityStatus: "图像能力",
    imageInputStatusUnknown: "图像未检测",
    imageInputStatusSupported: "支持图像输入",
    imageInputStatusUnsupported: "不支持图像输入",
    imageInputStatusFailed: "检测失败",
    expandSection: "展开内容",
    collapseSection: "收起内容",
    keyConfigured: "已配置",
    keyPending: "待写入",
    keyClearPending: "待清除",
    keyMissing: "缺失",
    noBlocking: "当前没有阻塞问题。",
    noWarnings: "当前没有警告。",
    noSuggestions: "当前没有额外建议动作。",
    blockingIssues: "阻塞问题",
    warningSignals: "警告信号",
    suggestedActions: "建议动作",
    editorDirtyHint: "编辑文本有未检查改动。先检查当前修改，再继续结构化编辑或测试。",
    editorCleanHint: "当前结构化面板和编辑文本一致。",
    editorRestoreHint: "放弃编辑文本里的未检查内容，并回到当前结构化面板。",
    saveSourceHint: "当前修改还没写入外部 operator config.toml，保存成功后这里会刷新为最新文件状态。",
    modelSavePending: "保存模型修改中",
    modelSaveFailed: "模型修改未生效：",
    modelEditorAdvancedTitle: "高级参数",
    modelEditorAdvancedHint: "常用字段已经在上方，只有需要时再展开这里。",
    testPending: "测试连接中",
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
    avatarImageCurrent: "当前头像",
    avatarImageEmpty: "未设置头像图片",
    avatarImageClickToUpload: "点击头像上传",
    userProfileAvatarGroupTitle: "头像设置",
    userProfileAvatarGroupHint: "头像预设和本地头像图片只影响前端展示，不会把图片内容传给模型。",
    uploadThemeBackgroundImage: "上传背景图片",
    clearThemeBackgroundImage: "清除背景图片",
    themeBackgroundPresetTitle: "内置背景",
    themeBackgroundImageUploading: "上传背景图片中",
    themeBackgroundImageUploadFailed: "背景图片上传失败：",
    avatarCropTitle: "裁剪头像",
    avatarCropHint: "拖动图片调整位置，使用滑杆缩放；确认后会保存 1:1 裁剪结果。",
    avatarCropZoom: "缩放",
    avatarCropConfirm: "确认裁剪",
    avatarCropCancel: "取消裁剪",
    avatarCropPreview: "头像预览",
    fieldCountLabel: "字段",
    emptyValue: "空",
    itemLabel: "条目",
    yes: "是",
    no: "否",
  },
  en: {
    pageTitle: "Unified Config Workbench",
    subtitle: "Structured config, model assets, and save state. Startup settings are maintained in Launcher.",
    subtitleHint: "Startup settings are maintained in Launcher; structured editing, full-config checks, and final writes still converge on the external operator config.toml.",
    loading: "Loading unified config workspace...",
    loadFailed: "Failed to load config workspace",
    sourceTitle: "Save and Apply",
    sourceBody: "Shows whether current changes are saved and which system-level settings take effect after restart.",
    sourceBodyShort: "Save state, config path, and environment entry.",
    runtimeTitle: "Runtime and Interface",
    runtimeBody: "Non-startup interface, governance, and advanced config.",
    modelsTitle: "Model Library",
    modelsBody: "This section manages model assets only: provider routes, model names, key state, capability checks, and connection tests. Edit each Agent's model choices in Agent management.",
    modelsBodyShort: "Model assets, key state, capability checks, and connectivity.",
    draftTitle: "Advanced Config Check",
    draftBody: "Inspect the full current config. Saves write only external operator config.toml.",
    diagnosticsTitle: "Diagnostics and Save",
    diagnosticsBody: "Blocking issues, warnings, and save actions.",
    configPath: "Config path",
    configStatus: "Current status",
    rawToml: "Current external config.toml",
    rawTomlHint: "This is a read-only view of the real file. It refreshes after you save changes.",
    syncedDraft: "Matches external config.toml",
    unsavedDraft: "Unsaved changes",
    refresh: "Reload",
    validateDraft: "Check changes",
    resetDraft: "Restore editor text",
    openEnvironment: "Open system environment variables",
    openEnvironmentHint: "Opens the Windows system dialog so you can inspect which keys are in use.",
    openEnvironmentPending: "Opening system environment variables",
    openEnvironmentOpened: "System environment variables window opened.",
    saveConfig: "Save to external config",
    applying: "Saving",
    leaveGuardTitle: "Unsaved settings",
    leaveGuardBody: "These changes have not been saved to the external operator config.toml. Save before leaving?",
    leaveGuardSave: "Save and leave",
    leaveGuardSaving: "Saving before leaving",
    leaveGuardDiscard: "Leave without saving",
    leaveGuardCancel: "Cancel",
    intakeMode: "Review intake",
    groupOverviewSaveTitle: "Overview and Save",
    groupOverviewSaveSummary: "Review save status, reload config, and open system environment variables.",
    groupWorkbenchTitle: "Interface and Advanced Config",
    groupWorkbenchSummary: "Startup settings moved to Launcher; this group keeps shell, non-startup interface, and config checks.",
    groupAvatarPetTitle: "User, Terminal Avatar, and Companion",
    groupAvatarPetSummary: "Manage user info, terminal avatar, pet, and companion-facing settings together. The Web user avatar lives under User Info.",
    groupModelingTitle: "Model Library",
    groupModelingSummary: "Manage model assets, provider accounts, keys, capability checks, and discovery in one place.",
    groupRuntimeContextTitle: "Runtime and Context",
    groupRuntimeContextSummary: "Keep global context compression, analysis, and advanced runtime policy here. Configure individual Agents in Agent management.",
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
    developerModeReadonly: "Developer mode",
    developerModeControlled: "Launcher controlled",
    developerModeEnabled: "Enabled",
    developerModeDisabled: "Disabled",
    runtimeProfile: "Runtime mode",
    defaultMode: "Default mode",
    defaultRoute: "Default route",
    modelEditorCreate: "Create model",
    modelEditorEdit: "Edit model",
    modelCenterAccounts: "Provider accounts",
    modelCenterInventory: "Model inventory",
    modelCenterHealth: "Health",
    modelCenterModels: "Models",
    modelCenterCapabilityIssues: "Attention",
    modelCenterActions: "Actions",
    modelCenterProtocol: "Protocol route",
    modelScenario: "Add as",
    modelScenarioChat: "General chat model",
    modelScenarioRelay: "Relay model",
    modelScenarioImage: "Image tool model",
    modelScenarioLocal: "Local model",
    modelScenarioManual: "Advanced manual",
    modelScenarioHint: "The scenario picks the closest template. Provider, model name, and key can still be adjusted below.",
    preset: "Vendor",
    providerVendor: "Vendor",
    providerTemplate: "Template",
    providerTemplatePlaceholder: "Choose a template",
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
    discoveryUnavailable: "This provider does not support automatic discovery. Enter the model name manually.",
    providerKind: "Provider kind",
    providerKeyEnv: "Provider default variable",
    modelKeyEnv: "Unique model variable",
    modelKeyInput: "API key",
    keyStorageHint: "This is staged first. It is written to the local user environment only when you save to the external config.",
    keyEnvAdvancedHint: "The model key variable is uniquely generated from the model ID and shown read-only. Enter the API key value; saving writes it to this user environment variable. The provider default variable is compatibility-only display, not a new key entry point.",
    deleteModelHint: "Deleting a model also clears the unique environment key bound to that model. Adjust Agent and tool model choices in their own management pages.",
    deleteModelConfirm: "Delete this model? This clears its bound environment key and removes the asset from the model library.",
    baseUrl: "Base URL",
    compatMode: "Compat mode",
    providerApi: "Provider API",
    modelProtocol: "Model protocol",
    modelCompat: "Compat policy object",
    contextWindow: "Context window",
    requiresApiKey: "Requires API key",
    imageInputSupport: "Image input",
    imageInputSupportUnknown: "Undeclared",
    imageInputSupportSupported: "Supported",
    imageInputSupportUnsupported: "Unsupported",
    transport: "Transport",
    contract: "Contract",
    reasoningStateField: "Reasoning state field",
    toolCallingMode: "Tool calling",
    promptCacheMode: "Prompt cache",
    strictCompatibility: "Strict compatibility",
    streaming: "Streaming",
    discoveryEnabled: "Discovery enabled",
    temperature: "Temperature",
    maxOutputTokens: "Max output tokens",
    timeout: "Timeout (s)",
    connectTimeout: "Connect timeout (s)",
    clearSecret: "Also clear this environment key on save",
    saveModel: "Confirm model changes",
    modelRequiredFieldsMissing: "Enter the model name and base URL first.",
    deleteModel: "Delete model",
    cancelEditing: "Clear form",
    modelTestSelect: "Test model",
    modelTestPlaceholder: "Choose a model",
    testSelectedLibraryModel: "Test selected model",
    modelTestRequired: "Choose a model to test first.",
    checkSavedImageCapabilities: "Check saved models image input",
    imageCapabilityCheckPending: "Checking model capabilities",
    imageCapabilityStatus: "Image capability",
    imageInputStatusUnknown: "Image not checked",
    imageInputStatusSupported: "Supports image input",
    imageInputStatusUnsupported: "No image input",
    imageInputStatusFailed: "Check failed",
    expandSection: "Expand",
    collapseSection: "Collapse",
    keyConfigured: "configured",
    keyPending: "pending",
    keyClearPending: "clear pending",
    keyMissing: "missing",
    noBlocking: "No blocking issues right now.",
    noWarnings: "No warnings right now.",
    noSuggestions: "No extra suggested actions right now.",
    blockingIssues: "Blocking issues",
    warningSignals: "Warnings",
    suggestedActions: "Suggested actions",
    editorDirtyHint: "The editor text has unchecked changes. Check them before more structured edits or tests.",
    editorCleanHint: "Structured controls and editor text are in sync.",
    editorRestoreHint: "Discard unchecked editor text and return to the current structured panel.",
    saveSourceHint: "Save to the external config to persist the current changes.",
    modelSavePending: "Saving model changes",
    modelSaveFailed: "Model changes were not applied:",
    modelEditorAdvancedTitle: "Advanced parameters",
    modelEditorAdvancedHint: "The common fields are above. Expand this only when needed.",
    testPending: "Testing connection",
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
    avatarImageCurrent: "Current avatar",
    avatarImageEmpty: "No avatar image set",
    avatarImageClickToUpload: "Click avatar to upload",
    userProfileAvatarGroupTitle: "Avatar settings",
    userProfileAvatarGroupHint: "The avatar preset and local avatar image affect frontend display only. Image content is not sent to the model.",
    uploadThemeBackgroundImage: "Upload background image",
    clearThemeBackgroundImage: "Clear background image",
    themeBackgroundPresetTitle: "Built-in backgrounds",
    themeBackgroundImageUploading: "Uploading background image",
    themeBackgroundImageUploadFailed: "Background image upload failed: ",
    avatarCropTitle: "Crop avatar",
    avatarCropHint: "Drag the image to reposition it and use the slider to zoom. Confirm saves a 1:1 crop.",
    avatarCropZoom: "Zoom",
    avatarCropConfirm: "Confirm crop",
    avatarCropCancel: "Cancel crop",
    avatarCropPreview: "Avatar preview",
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
    api: "",
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
    protocol: "",
    compat: "",
    reasoning_state_field: "",
    strict_compatibility: false,
    temperature: "",
    max_output_tokens: "",
    timeout: "",
    connect_timeout: "",
    streaming: true,
    tool_calling_mode: "auto",
    prompt_cache_mode: "disabled",
    prompt_cache_configured: false,
    discovery_enabled: true,
    supports_image_input: "unknown",
  };
}

function emptyModelEditorState(): ModelEditorState {
  return {
    mode: "create",
    preset_id: "",
    provider_template_id: "",
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
      memberSectionIds: ["shell", "ui"],
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
      id: "runtime-context",
      title: copy.groupRuntimeContextTitle,
      summary: copy.groupRuntimeContextSummary,
      memberSectionIds: ["context-compression", "analysis"],
    },
    {
      id: "tooling-diagnostics",
      title: copy.groupToolingTitle,
      summary: copy.groupToolingSummary,
      memberSectionIds: ["health-diagnostics", "security", "network", "log", "parser", "debug"],
    },
  ];
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
    api: getString(providerInput.api),
    api_key_env: getString(providerInput.api_key_env),
    base_url: getString(providerInput.base_url),
    compat_mode: getString(providerInput.compat_mode) || "openai",
    requires_api_key: getBoolean(providerInput.requires_api_key, true),
    context_window: getString(providerInput.context_window),
  };
}

function buildModelDetailsDraft(detailsInput: Record<string, unknown>): ModelDetailsDraft {
  const promptCache = asRecord(detailsInput.prompt_cache);
  const supportsImageInput =
    typeof detailsInput.supports_image_input === "boolean"
      ? detailsInput.supports_image_input
        ? "supported"
        : "unsupported"
      : "unknown";
  return {
    transport: getString(detailsInput.transport) || "chat_completions",
    contract: getString(detailsInput.contract) || "tool_chat",
    protocol: getString(detailsInput.protocol),
    compat: Object.keys(asRecord(detailsInput.compat)).length ? JSON.stringify(asRecord(detailsInput.compat), null, 2) : "",
    reasoning_state_field: getString(detailsInput.reasoning_state_field),
    strict_compatibility: getBoolean(detailsInput.strict_compatibility, false),
    temperature: getString(detailsInput.temperature),
    max_output_tokens: getString(detailsInput.max_output_tokens),
    timeout: getString(detailsInput.timeout),
    connect_timeout: getString(detailsInput.connect_timeout),
    streaming: getBoolean(detailsInput.streaming, true),
    tool_calling_mode: getString(detailsInput.tool_calling_mode) || "auto",
    prompt_cache_mode: getString(promptCache.mode) || "disabled",
    prompt_cache_configured: Boolean(promptCache.mode),
    discovery_enabled: getBoolean(detailsInput.discovery_enabled, true),
    supports_image_input: supportsImageInput,
  };
}

function hydrateModelEditorFromOption(option: ConfigModelOption): ModelEditorState {
  return {
    mode: "edit",
    preset_id: "",
    provider_template_id: "",
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
    api: draft.api.trim(),
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

function parseModelCompatDraft(value: string): Record<string, unknown> | null {
  const text = value.trim();
  if (!text) {
    return {};
  }
  const parsed = JSON.parse(text) as unknown;
  return isPlainObject(parsed) ? parsed : null;
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
  if (draft.protocol.trim()) {
    payload.protocol = draft.protocol.trim();
  }
  const compat = parseModelCompatDraft(draft.compat);
  if (!compat) {
    throw new Error("compat must be a JSON object");
  }
  if (Object.keys(compat).length) {
    payload.compat = compat;
  }
  if (draft.reasoning_state_field.trim()) {
    payload.reasoning_state_field = draft.reasoning_state_field.trim();
  }
  if (draft.tool_calling_mode.trim()) {
    payload.tool_calling_mode = draft.tool_calling_mode.trim();
  }
  if (draft.prompt_cache_configured || draft.prompt_cache_mode.trim() !== "disabled") {
    payload.prompt_cache = { mode: draft.prompt_cache_mode.trim() };
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
  if (draft.supports_image_input === "supported") {
    payload.supports_image_input = true;
    payload.capability_status = "supported";
    payload.capability_source = "manual";
  } else if (draft.supports_image_input === "unsupported") {
    payload.supports_image_input = false;
    payload.capability_status = "unsupported";
    payload.capability_source = "manual";
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

function isConfigObjectListValue(value: unknown, kind: ConfigEditorMeta["kind"] | undefined): value is Record<string, unknown>[] {
  if (!Array.isArray(value)) {
    return false;
  }
  if (kind === "object_list") {
    return true;
  }
  if (kind === "string_list") {
    return false;
  }
  return value.length > 0 && value.every((item) => isPlainObject(item));
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
  lang: ConfigLanguage;
  copy: ConfigCopy;
  disabled: boolean;
  uiState: ConfigSectionUiState;
  onUiStateChange: (sectionId: string, nextState: ConfigSectionUiState) => void;
  onSaveSection: (path: string, nextValue: unknown) => Promise<boolean>;
  onAvatarImageUpload: (file: File) => Promise<AvatarImageUploadResponse | null>;
  onThemeBackgroundImageUpload: (file: File) => Promise<AvatarImageUploadResponse | null>;
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

function avatarImageDisplayName(value: unknown, copy: ConfigCopy): string {
  const path = getString(value).replace(/\\/g, "/").trim();
  if (!path) {
    return copy.avatarImageEmpty;
  }
  return path.split("/").filter(Boolean).at(-1) ?? path;
}

function themeBackgroundImagePreviewUrl(value: unknown): string {
  const path = getString(value).replace(/\\/g, "/").trim();
  const prefix = "theme_backgrounds/";
  if (!path.startsWith(prefix)) {
    return "";
  }
  const filename = path.slice(prefix.length);
  if (!/^[A-Za-z0-9_.-]+$/.test(filename)) {
    return "";
  }
  return `/api/config/theme-background-image/${encodeURIComponent(filename)}`;
}

function configEditorFieldKind(meta: ConfigEditorMeta | undefined): ConfigEditorMeta["kind"] | "background_image" {
  return (meta?.kind ?? "text") as ConfigEditorMeta["kind"] | "background_image";
}

function ConfigSectionEditor({
  section,
  value,
  metaMap,
  lang,
  copy,
  disabled,
  uiState,
  onUiStateChange,
  onSaveSection,
  onAvatarImageUpload,
  onThemeBackgroundImageUpload,
}: ConfigSectionEditorProps) {
  const sectionExpanded = uiState.expanded;
  const editing = uiState.editing;
  const expandedPaths = uiState.expandedPaths;
  const draftValue = editing ? clonePublicConfig(uiState.draftValue ?? value) : clonePublicConfig(value);
  const sectionClassName = [
    styles.sectionSurface,
    styles.configEditorSection,
    section.id === "llm-discovery" ? styles.configDiscoverySection : "",
  ].filter(Boolean).join(" ");
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

  async function uploadThemeBackgroundFile(file: File, absolutePath: string) {
    setUploadingImagePath(absolutePath);
    try {
      const uploaded = await onThemeBackgroundImageUpload(file);
      if (uploaded) {
        updateSectionDraft(absolutePath, uploaded.path);
      }
    } finally {
      setUploadingImagePath("");
    }
  }

  function themeBackgroundDisplayName(value: unknown): string {
    const path = getString(value).replace(/\\/g, "/").trim();
    if (!path) {
      return copy.emptyValue;
    }
    return path.split("/").filter(Boolean).at(-1) ?? path;
  }

  function renderThemeBackgroundControl(fieldValue: unknown, absolutePath: string) {
    const previewUrl = themeBackgroundImagePreviewUrl(fieldValue);
    const imageUploading = uploadingImagePath === absolutePath;
    const currentPath = getString(fieldValue).replace(/\\/g, "/").trim();
    const presetOptions = metaMap[absolutePath]?.options ?? [];
    return (
      <div className={styles.themeBackgroundImageEditor}>
        <div className={styles.themeBackgroundImageValue}>
          <label
            className={styles.themeBackgroundDropButton}
            title={copy.uploadThemeBackgroundImage}
            aria-label={copy.uploadThemeBackgroundImage}
          >
            {previewUrl ? (
              <img src={previewUrl} alt="" className={styles.themeBackgroundImagePreview} />
            ) : (
              <span className={styles.themeBackgroundImagePlaceholder}>
                <ImageIcon size={16} />
              </span>
            )}
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
                await uploadThemeBackgroundFile(file, absolutePath);
              }}
            />
          </label>
          <div className={styles.themeBackgroundImageMeta}>
            <strong>{configLabel(metaMap, absolutePath)}</strong>
            <span>{themeBackgroundDisplayName(fieldValue)}</span>
            <div className={styles.themeBackgroundImageActions}>
              <label className={`${styles.actionButton} ${styles.compactButton} ${styles.fileUploadButton}`}>
                <Upload size={14} />
                {imageUploading ? copy.themeBackgroundImageUploading : copy.uploadThemeBackgroundImage}
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
                    await uploadThemeBackgroundFile(file, absolutePath);
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
                  {copy.clearThemeBackgroundImage}
                </button>
              ) : null}
            </div>
          </div>
        </div>
        {presetOptions.length ? (
          <div className={styles.themeBackgroundPresetPanel} aria-label={copy.themeBackgroundPresetTitle}>
            <span className={styles.themeBackgroundPresetTitle}>{copy.themeBackgroundPresetTitle}</span>
            <div className={styles.themeBackgroundPresetGrid}>
              {presetOptions.map((option) => {
                const optionPreviewUrl = themeBackgroundImagePreviewUrl(option.value);
                const active = currentPath === option.value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    className={styles.themeBackgroundPresetButton}
                    data-active={active ? "true" : undefined}
                    disabled={disabled || imageUploading}
                    aria-pressed={active}
                    title={option.label}
                    onClick={() => updateSectionDraft(absolutePath, option.value)}
                  >
                    {optionPreviewUrl ? <img src={optionPreviewUrl} alt="" /> : <ImageIcon size={14} />}
                    <span>{option.label}</span>
                    {active ? <em>{lang === "zh" ? "当前" : "Current"}</em> : null}
                  </button>
                );
              })}
            </div>
          </div>
        ) : null}
      </div>
    );
  }

  function renderFieldView(fieldValue: unknown, absolutePath: string) {
    const meta = metaMap[absolutePath];
    const kind = configEditorFieldKind(meta);
    if (kind === "background_image") {
      const hint = configHint(metaMap, absolutePath);
      return (
        <article
          key={absolutePath}
          className={`${styles.treeFieldCard} ${styles.treeFieldCardView} ${styles.themeBackgroundImageCard}`}
          title={hint || undefined}
        >
          {renderThemeBackgroundControl(fieldValue, absolutePath)}
        </article>
      );
    }
    if (kind === "image") {
      const previewUrl = avatarImagePreviewUrl(fieldValue);
      const displayName = avatarImageDisplayName(fieldValue, copy);
      return (
        <article
          key={absolutePath}
          className={`${styles.treeFieldCard} ${styles.treeFieldCardView} ${styles.avatarImageCard}`}
        >
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
            <div className={styles.avatarImageMeta}>
              <strong>{previewUrl ? copy.avatarImageCurrent : copy.avatarImageEmpty}</strong>
              <span>{displayName}</span>
            </div>
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
    const kind = configEditorFieldKind(meta);
    const imageUploading = uploadingImagePath === absolutePath;
    let control;

    if (kind === "background_image") {
      control = renderThemeBackgroundControl(fieldValue, absolutePath);
    } else if (kind === "image") {
      const previewUrl = avatarImagePreviewUrl(fieldValue);
      const displayName = avatarImageDisplayName(fieldValue, copy);
      const cropDraft = avatarCrop?.absolutePath === absolutePath ? avatarCrop : null;
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
            <label
              className={styles.avatarImageDropButton}
              title={copy.avatarImageClickToUpload}
              aria-label={copy.avatarImageClickToUpload}
            >
              {previewUrl ? (
                <img src={previewUrl} alt="" className={styles.avatarImagePreview} />
              ) : (
                <span className={styles.avatarImagePlaceholder}>
                  <ImageIcon size={16} />
                </span>
              )}
              <span className={styles.avatarImageUploadCue}>
                <Upload size={12} />
              </span>
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
            <div className={styles.avatarImageMeta}>
              <strong>{configLabel(metaMap, absolutePath)}</strong>
              <span>{displayName}</span>
            </div>
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

    const hint = configHint(metaMap, absolutePath);
    const fieldCardClassName =
      kind === "background_image"
        ? `${styles.treeFieldCard} ${styles.treeFieldCardEdit} ${styles.themeBackgroundImageCard}`
        : `${styles.treeFieldCard} ${styles.treeFieldCardEdit}`;

    return (
      <article key={absolutePath} className={fieldCardClassName} title={kind === "background_image" && hint ? hint : undefined}>
        {kind !== "background_image" && hint ? <p className={styles.treeHint}>{hint}</p> : null}
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

  function renderConfigField(childValue: unknown, childPath: string, mode: "view" | "edit") {
    return mode === "edit" ? renderFieldEditor(childValue, childPath) : renderFieldView(childValue, childPath);
  }

  function renderUserProfileBody(nodeValue: Record<string, unknown>, absolutePath: string, mode: "view" | "edit") {
    const field = (key: string) => renderConfigField(nodeValue[key], `${absolutePath}.${key}`, mode);
    return (
      <div className={styles.userProfileLayout}>
        <div className={styles.userProfileIdentityFields}>
          {field("display_name")}
          {field("bio")}
        </div>
        <div className={styles.userProfilePreferencesField}>{field("preferences")}</div>
        <div className={styles.userProfileAvatarGroup}>
          <div className={styles.userProfileAvatarHeader}>
            <strong>{copy.userProfileAvatarGroupTitle}</strong>
            <span>{copy.userProfileAvatarGroupHint}</span>
          </div>
          <div className={styles.userProfileAvatarFields}>
            {field("avatar_preset")}
            {field("avatar_image_path")}
          </div>
        </div>
      </div>
    );
  }

  function renderObjectBody(nodeValue: Record<string, unknown>, absolutePath: string, mode: "view" | "edit") {
    const entries = Object.entries(nodeValue);
    if (!entries.length) {
      return <p className={styles.helperText}>{copy.emptyValue}</p>;
    }
    if (absolutePath === "user_profile") {
      return renderUserProfileBody(nodeValue, absolutePath, mode);
    }
    return (
      <div className={styles.treeGrid}>
        {entries.map(([key, childValue]) => {
          const childPath = `${absolutePath}.${key}`;
          const childMetaKind = metaMap[childPath]?.kind;
          const childIsObjectList = isConfigObjectListValue(childValue, childMetaKind);
          const childIsObject = isPlainObject(childValue);
          if (childIsObject || childIsObjectList) {
            const childExpanded = Boolean(expandedPaths[childPath]);
            return (
              <div key={childPath} className={childExpanded ? styles.treeWide : styles.treeObjectCell}>
                {renderNode(childValue, childPath, mode)}
              </div>
            );
          }
          return renderConfigField(childValue, childPath, mode);
        })}
      </div>
    );
  }

  function renderNode(nodeValue: unknown, absolutePath: string, mode: "view" | "edit", itemIndex?: number) {
    const isRoot = absolutePath === section.path;
    if (isConfigObjectListValue(nodeValue, metaMap[absolutePath]?.kind)) {
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
    <section id={`config-${section.id}`} className={sectionClassName}>
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
  const modelEditorRef = useRef<HTMLDivElement | null>(null);
  const sidebarResizeCleanupRef = useRef<(() => void) | null>(null);
  const workspaceQuery = useQuery({
    queryKey: queryKeys.configWorkspace(),
    queryFn: () => fetchJson<ConfigWorkspace>("/api/config/workspace"),
  });
  const healthDiagnosticsQuery = useQuery({
    queryKey: queryKeys.diagnosticsHealth(),
    queryFn: () => fetchJson<HealthDiagnostics>("/api/diagnostics/health"),
  });

  const [draftConfig, setDraftConfig] = useState<PublicConfigShape | null>(null);
  const [baseConfig, setBaseConfig] = useState<PublicConfigShape | null>(null);
  const [draftMeta, setDraftMeta] = useState<ConfigDraftMeta>(emptyDraftMeta());
  const [baseHash, setBaseHash] = useState("");
  const [draftHash, setDraftHash] = useState("");
  const [activeWorkspace, setActiveWorkspace] = useState<ConfigWorkspace | null>(null);
  const [jsonText, setJsonText] = useState("{}");
  const [notice, setNotice] = useState<{ tone: NoticeTone; text: string }>({ tone: "neutral", text: "" });
  const [busyAction, setBusyAction] = useState("");
  const [modelEditor, setModelEditor] = useState<ModelEditorState>(emptyModelEditorState());
  const [selectedModelTestId, setSelectedModelTestId] = useState("");
  const [modelEditorError, setModelEditorError] = useState("");
  const [modelDiscoveryError, setModelDiscoveryError] = useState("");
  const [discoveredModels, setDiscoveredModels] = useState<ConfigDiscoveredModel[]>([]);
  const [selectedDiscoveredModelId, setSelectedDiscoveredModelId] = useState("");
  const [selectedProviderVendorId, setSelectedProviderVendorId] = useState("");
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

  function syncWorkspace(workspace: ConfigWorkspace, tone: NoticeTone = "neutral", options: { resetBase?: boolean } = {}) {
    setActiveWorkspace(clonePublicConfig(workspace));
    setDraftConfig(clonePublicConfig(workspace.publicConfig));
    if (options.resetBase !== false) {
      setBaseConfig(clonePublicConfig(workspace.publicConfig));
    }
    setDraftMeta(clonePublicConfig(workspace.draftMeta));
    setBaseHash(workspace.baseHash);
    setDraftHash(workspace.hash);
    setJsonText(formatJson(pickEditableConfigView(workspace.publicConfig, workspace.editorSections)));
    setNotice({ tone, text: workspace.message || "" });
    setModelEditor(emptyModelEditorState());
    setSelectedModelTestId((current) =>
      current && workspace.modelOptions.some((option) => option.model_id === current)
        ? current
        : workspace.modelOptions[0]?.model_id ?? "",
    );
    setModelEditorError("");
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
  const formattedDraft = useMemo(
    () => formatJson(pickEditableConfigView(draftConfig ?? {}, workspace?.editorSections ?? [])),
    [draftConfig, workspace?.editorSections],
  );
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
    return section.id !== "agent";
  });
  const modelOptions = workspace?.modelOptions ?? [];
  const modelOptionsById = useMemo(() => new Map(modelOptions.map((option) => [option.model_id, option])), [modelOptions]);
  const providerPresetOptions = workspace?.providerPresetOptions ?? [];
  const providerVendorGroups = useMemo(() => groupProviderPresetsByVendor(providerPresetOptions), [providerPresetOptions]);
  const selectedProviderVendorTemplates = useMemo(
    () => providerVendorGroups.find((group) => group.id === selectedProviderVendorId)?.templates ?? [],
    [providerVendorGroups, selectedProviderVendorId],
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
  const modelCenterSummary = useMemo(
    () =>
      deriveModelCenterSummary({
        modelOptions,
      }),
    [modelOptions],
  );
  const modelCenterRows = useMemo(() => deriveModelCenterInventoryRows(modelOptions), [modelOptions]);
  useEffect(() => {
    if (!modelOptions.length) {
      if (selectedModelTestId) {
        setSelectedModelTestId("");
      }
      return;
    }
    if (!selectedModelTestId || !modelOptionsById.has(selectedModelTestId)) {
      setSelectedModelTestId(modelOptions[0]?.model_id ?? "");
    }
  }, [modelOptions, modelOptionsById, selectedModelTestId]);
  const modelCapabilityIssueCount = countModelCenterHealthIssues(modelCenterRows);
  const modelDiscoveryAvailable = canDiscoverModelsForProvider(modelEditor.provider);

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
  const modelEditorRequiredFieldsReady = Boolean(modelEditor.model.trim() && modelEditor.provider.base_url.trim());
  const canSubmitModelEditor = !structuredActionsDisabled && modelEditorRequiredFieldsReady;
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
  const launcherConfig = asRecord(draftConfig?.launcher);
  const developerModeConfig = asRecord(launcherConfig.developer_mode);
  const developerModeReadonlyLabel = developerModeConfig.enabled ? copy.developerModeEnabled : copy.developerModeDisabled;

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
    return buildConfigApplyPayload({
      draftConfig,
      draftMeta,
      baseHash,
      baseConfig,
      editorText: jsonText,
      hasEditorChanges,
      editorSections: workspace?.editorSections ?? [],
      loadFailedMessage: copy.loadFailed,
    }).publicConfig;
  }

  async function previewDraft(nextConfig: PublicConfigShape, nextMeta: ConfigDraftMeta, pendingLabel: string) {
    setBusyAction(pendingLabel);
    try {
      const response = await requestJson<ConfigWorkspace>("/api/config/draft/preview", {
        publicConfig: nextConfig,
        draftMeta: nextMeta,
        baseHash,
      });
      syncWorkspace(response, "success", { resetBase: false });
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
      const payload = buildConfigApplyPayload({
        draftConfig,
        draftMeta,
        baseHash,
        baseConfig,
        editorText: jsonText,
        hasEditorChanges,
        editorSections: workspace?.editorSections ?? [],
        loadFailedMessage: copy.loadFailed,
      });
      const response = await requestJson<ConfigWorkspace>(
        "/api/config/apply",
        payload,
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
      const parsed = buildConfigApplyPayload({
        draftConfig: draftConfig ?? {},
        draftMeta,
        baseHash,
        baseConfig,
        editorText: jsonText,
        hasEditorChanges: true,
        editorSections: workspace?.editorSections ?? [],
        loadFailedMessage: copy.loadFailed,
      }).publicConfig;
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

  async function handleThemeBackgroundImageUpload(file: File): Promise<AvatarImageUploadResponse | null> {
    setBusyAction(copy.themeBackgroundImageUploading);
    try {
      return await requestJson<AvatarImageUploadResponse>("/api/config/theme-background-image", {
        filename: file.name,
        contentType: file.type,
        dataBase64: await fileToBase64(file),
      });
    } catch (error) {
      const message = markError(error);
      setNotice({ tone: "error", text: `${copy.themeBackgroundImageUploadFailed}${message}` });
      return null;
    } finally {
      setBusyAction("");
    }
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

  function applyProviderTemplate(templateId: string) {
    setModelEditorExpanded(true);
    setModelEditorError("");
    setModelDiscoveryError("");
    setDiscoveredModels([]);
    setSelectedDiscoveredModelId("");
    const template = providerPresetOptions.find((item) => item.provider_preset_id === templateId);
    if (!template) {
      setModelEditor((current) => ({ ...current, provider_template_id: templateId }));
      return;
    }
    const templateModel = asRecord(template.default_model);
    const templateDetails = {
      ...buildModelDetailsDraft(templateModel),
      supports_image_input: "unknown" as const,
    };
    setSelectedProviderVendorId(template.vendor_id);
    setModelEditor({
      mode: "create",
      preset_id: "",
      provider_template_id: templateId,
      model_id: "",
      label: "",
      model: "",
      api_key_env: "",
      api_key: "",
      clear_api_key: false,
      provider: buildProviderDraft(asRecord(template.provider)),
      details: templateDetails,
    });
  }

  function applyProviderVendor(vendorId: string) {
    setSelectedProviderVendorId(vendorId);
    const template = providerVendorGroups.find((group) => group.id === vendorId)?.templates[0];
    if (template) {
      applyProviderTemplate(template.provider_preset_id);
      return;
    }
    setModelEditor((current) => ({ ...current, provider_template_id: "" }));
  }

  function applyModelScenario(scenario: ModelScenarioId) {
    const templateId = selectModelScenarioProviderPresetId(scenario, providerPresetOptions);
    if (templateId) {
      applyProviderTemplate(templateId);
      return;
    }
    setModelEditorExpanded(true);
    setModelEditorError("");
    setModelDiscoveryError("");
    setDiscoveredModels([]);
    setSelectedDiscoveredModelId("");
    setSelectedProviderVendorId("");
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
    if (structuredActionsDisabled || !modelDiscoveryAvailable) {
      if (!modelDiscoveryAvailable) {
        setModelDiscoveryError(copy.discoveryUnavailable);
      }
      return;
    }
    setBusyAction(copy.discoveryPending);
    setModelDiscoveryError("");
    setDiscoveredModels([]);
    try {
      const discoveryModelId =
        modelEditor.mode === "edit"
          ? modelEditor.model_id
          : modelEditor.model_id.trim() ||
            uniqueModelLibraryId(modelLibraryIdFromParts(modelEditor.label || modelEditor.model, modelEditor.model), modelOptions.map((option) => option.model_id));
      const discoveryApiKeyEnv = modelEditor.api_key_env.trim() || defaultModelApiKeyEnv(discoveryModelId);
      const response = await requestJson<ConfigModelDiscoveryResult>("/api/config/discover-models", {
        publicConfig: requireDraft(),
        draftMeta,
        baseHash,
        provider: buildProviderPayload(modelEditor.provider),
        modelId: discoveryModelId,
        apiKeyEnv: discoveryApiKeyEnv,
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
    if (!modelEditorRequiredFieldsReady) {
      setModelEditorError(copy.modelRequiredFieldsMissing);
      setModelEditorExpanded(true);
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
        presetId: "",
        modelId: resolvedModelId,
        provider: buildProviderPayload(modelEditor.provider),
        model: modelEditor.model,
        label: modelEditor.label,
        details: buildModelDetailsPayload(modelEditor.details),
        apiKeyEnv: resolvedApiKeyEnv,
        apiKey: modelEditor.api_key,
        clearApiKey: modelEditor.clear_api_key,
      });
      syncWorkspace(response, "success", { resetBase: false });
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
    if (typeof window !== "undefined" && !window.confirm(copy.deleteModelConfirm)) {
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
      syncWorkspace(response, "success", { resetBase: false });
    } catch (error) {
      markError(error);
    } finally {
      setBusyAction("");
    }
  }

  function focusModelEditor() {
    window.setTimeout(() => {
      modelEditorRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      const firstInput = modelEditorRef.current?.querySelector<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(
        "input:not([disabled]), select:not([disabled]), textarea:not([disabled])",
      );
      firstInput?.focus({ preventScroll: true });
    }, 0);
  }

  async function handleTestSelectedLibraryModel() {
    if (structuredActionsDisabled) {
      return;
    }
    if (!selectedModelTestId) {
      setNotice({ tone: "error", text: copy.modelTestRequired });
      return;
    }
    setBusyAction(copy.testPending);
    try {
      const result = await requestJson<ConfigLlmTestResult>("/api/config/test-llm", {
        publicConfig: requireDraft(),
        draftMeta,
        baseHash,
        modelId: selectedModelTestId,
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
      syncWorkspace(response, "success", { resetBase: false });
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
    return `${result.model_id} / ${result.model}: ${result.message} [${detailParts.join(" | ")}]`;
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
        <ConfigWorkspacePlaceholder title={copy.loading} />
      </div>
    );
  }

  if (!draftConfig || !workspace) {
    return (
      <div className={styles.page}>
        <ConfigWorkspacePlaceholder
          title={copy.loadFailed}
          subtitle={workspaceQuery.error instanceof Error ? workspaceQuery.error.message : ""}
          tone="error"
        />
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
          <p className={styles.subtitle} title={copy.subtitleHint}>{copy.subtitle}</p>
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
          <article className={styles.metricCard} aria-label={copy.developerModeReadonly}>
            <span>{copy.developerModeReadonly}</span>
            <strong>{developerModeReadonlyLabel}</strong>
            <small>{copy.developerModeControlled}</small>
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

      <section className={activeSection?.id === "models-profiles" ? `${styles.content} ${styles.contentModels}` : styles.content}>
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
          <p className={styles.sectionText} title={copy.sourceBody}>{copy.sourceBodyShort}</p>
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
            <button
              type="button"
              className={styles.actionButton}
              disabled={Boolean(busyAction)}
              title={copy.openEnvironmentHint}
              onClick={handleOpenEnvironment}
            >
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

        {isSectionVisible("models") ? (
        <section id="config-models" className={`${styles.sectionSurface} ${styles.modelLibrarySection}`}>
          <div className={styles.sectionHeader}>
            <div>
              <p className={styles.eyebrow}>{sectionTitle("models", copy.modelsTitle)}</p>
              <h2 className={styles.sectionTitle}>{copy.modelsTitle}</h2>
            </div>
            <Blocks size={16} className={styles.sectionIcon} />
          </div>
          <p className={styles.sectionText} title={copy.modelsBody}>{copy.modelsBodyShort}</p>
          <div className={styles.modelCenterSummaryBar}>
            <span><strong>{modelCenterRows.length}</strong> {copy.modelCenterModels}</span>
            <span><strong>{modelCenterSummary.accounts.length}</strong> {copy.modelCenterAccounts}</span>
            <span className={modelCapabilityIssueCount ? styles.summaryBarWarning : undefined}>
              <strong>{modelCapabilityIssueCount}</strong> {copy.modelCenterCapabilityIssues}
            </span>
          </div>
          <div className={styles.modelLibraryTestBar}>
            <label className={`${styles.field} ${styles.modelLibraryTestSelect}`}>
              <span>{copy.modelTestSelect}</span>
              <select
                value={selectedModelTestId}
                disabled={structuredActionsDisabled || !modelOptions.length}
                onChange={(event) => setSelectedModelTestId(event.target.value)}
              >
                {modelOptions.length ? null : <option value="">{copy.modelTestPlaceholder}</option>}
                {modelOptions.map((option) => (
                  <option key={option.model_id} value={option.model_id}>
                    {option.label || option.model || option.model_id}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className={styles.primaryButton}
              disabled={structuredActionsDisabled || busyAction === copy.testPending || !selectedModelTestId}
              title={selectedModelTestId ? copy.testSelectedLibraryModel : copy.modelTestRequired}
              onClick={handleTestSelectedLibraryModel}
            >
              <Play size={14} />
              {busyAction === copy.testPending ? copy.testPending : copy.testSelectedLibraryModel}
            </button>
            <button
              type="button"
              className={styles.actionButton}
              disabled={structuredActionsDisabled || busyAction === copy.imageCapabilityCheckPending || !selectedModelTestId}
              title={selectedModelTestId ? copy.checkSavedImageCapabilities : copy.modelTestRequired}
              onClick={() => void handleCheckModelImageCapabilities([selectedModelTestId])}
            >
              <ImageIcon size={14} />
              {busyAction === copy.imageCapabilityCheckPending ? copy.imageCapabilityCheckPending : copy.checkSavedImageCapabilities}
            </button>
          </div>
          <div ref={modelEditorRef} className={styles.formSurface} onChange={() => (modelEditorError ? setModelEditorError("") : undefined)}>
            <div className={styles.formHeader}>
              <div className={styles.formHeaderIntro}>
                <Pencil size={16} />
                <span>{modelEditor.mode === "edit" ? copy.modelEditorEdit : copy.modelEditorCreate}</span>
              </div>
              <button
                type="button"
                className={`${styles.actionButton} ${styles.compactButton}`}
                aria-expanded={modelEditorExpanded}
                disabled={structuredActionsDisabled}
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
                    <span>{copy.providerVendor}</span>
                    <select value={selectedProviderVendorId} onChange={(event) => applyProviderVendor(event.target.value)}>
                      <option value="">{copy.customEntry}</option>
                      {providerVendorGroups.map((group) => (
                        <option key={group.id} value={group.id}>
                          {group.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className={styles.field}>
                    <span>{copy.providerTemplate}</span>
                    <select
                      value={modelEditor.provider_template_id}
                      disabled={!selectedProviderVendorTemplates.length}
                      onChange={(event) => applyProviderTemplate(event.target.value)}
                    >
                      <option value="">{copy.providerTemplatePlaceholder}</option>
                      {selectedProviderVendorTemplates.map((template: ConfigProviderPresetOption) => (
                        <option key={template.provider_preset_id} value={template.provider_preset_id}>
                          {template.label}
                        </option>
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
                    disabled={structuredActionsDisabled || busyAction === copy.discoveryPending || !modelDiscoveryAvailable}
                    title={modelDiscoveryAvailable ? copy.discoverModels : copy.discoveryUnavailable}
                    onClick={handleDiscoverModels}
                  >
                    <RefreshCw size={14} />
                    {busyAction === copy.discoveryPending ? copy.discoveryPending : copy.discoverModels}
                  </button>
                  {!modelDiscoveryAvailable && modelEditor.provider.base_url.trim() ? (
                    <span className={styles.helperText}>{copy.discoveryUnavailable}</span>
                  ) : null}
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
                      <code className={styles.readonlyCodeField} aria-readonly="true">
                        {modelEditor.provider.api_key_env || copy.autoValue}
                      </code>
                    </label>
                    <label className={styles.field}>
                      <span>{copy.modelKeyEnv}</span>
                      <code className={styles.readonlyCodeField} aria-readonly="true">
                        {modelEditor.api_key_env || copy.autoValue}
                      </code>
                    </label>
                    <label className={styles.field}>
                      <span>{copy.compatMode}</span>
                      <select
                        value={modelEditor.provider.compat_mode}
                        onChange={(event) =>
                          setModelEditor((current) => ({
                            ...current,
                            provider: { ...current.provider, compat_mode: event.target.value },
                          }))
                        }
                      >
                        {PROVIDER_COMPAT_MODE_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className={styles.field}>
                      <span>{copy.providerApi}</span>
                      <input
                        value={modelEditor.provider.api}
                        onChange={(event) =>
                          setModelEditor((current) => ({
                            ...current,
                            provider: { ...current.provider, api: event.target.value },
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
                      <select
                        value={modelEditor.details.transport}
                        onChange={(event) =>
                          setModelEditor((current) => ({
                            ...current,
                            details: { ...current.details, transport: event.target.value },
                          }))
                        }
                      >
                        {MODEL_TRANSPORT_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className={styles.field}>
                      <span>{copy.contract}</span>
                      <select
                        value={modelEditor.details.contract}
                        onChange={(event) =>
                          setModelEditor((current) => ({
                            ...current,
                            details: { ...current.details, contract: event.target.value },
                          }))
                        }
                      >
                        {MODEL_CONTRACT_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className={styles.field}>
                      <span>{copy.modelProtocol}</span>
                      <input
                        value={modelEditor.details.protocol}
                        onChange={(event) =>
                          setModelEditor((current) => ({
                            ...current,
                            details: { ...current.details, protocol: event.target.value },
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
                      <select
                        value={modelEditor.details.tool_calling_mode}
                        onChange={(event) =>
                          setModelEditor((current) => ({
                            ...current,
                            details: { ...current.details, tool_calling_mode: event.target.value },
                          }))
                        }
                      >
                        {MODEL_TOOL_CALLING_MODE_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className={styles.field}>
                      <span>{copy.promptCacheMode}</span>
                      <select
                        value={modelEditor.details.prompt_cache_mode}
                        onChange={(event) =>
                          setModelEditor((current) => ({
                            ...current,
                            details: {
                              ...current.details,
                              prompt_cache_mode: event.target.value,
                              prompt_cache_configured: true,
                            },
                          }))
                        }
                      >
                        {MODEL_PROMPT_CACHE_MODE_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className={`${styles.field} ${styles.formGridWideSpan}`}>
                      <span>{copy.modelCompat}</span>
                      <textarea
                        value={modelEditor.details.compat}
                        onChange={(event) =>
                          setModelEditor((current) => ({
                            ...current,
                            details: { ...current.details, compat: event.target.value },
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
                  <label className={styles.field}>
                    <span>{copy.imageInputSupport}</span>
                    <select
                      value={modelEditor.details.supports_image_input}
                      onChange={(event) =>
                        setModelEditor((current) => ({
                          ...current,
                          details: {
                            ...current.details,
                            supports_image_input: event.target.value as ModelDetailsDraft["supports_image_input"],
                          },
                        }))
                      }
                    >
                      <option value="unknown">{copy.imageInputSupportUnknown}</option>
                      <option value="supported">{copy.imageInputSupportSupported}</option>
                      <option value="unsupported">{copy.imageInputSupportUnsupported}</option>
                    </select>
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
                  <button
                    type="button"
                    className={styles.primaryButton}
                    disabled={!canSubmitModelEditor}
                    title={modelEditorRequiredFieldsReady ? undefined : copy.modelRequiredFieldsMissing}
                    onClick={handleSaveModel}
                  >
                    <Save size={14} />
                    {copy.saveModel}
                  </button>
                  <button
                    type="button"
                    className={styles.actionButton}
                    disabled={structuredActionsDisabled}
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
                  <th>{copy.modelCenterProtocol}</th>
                  <th>{copy.modelCenterActions}</th>
                </tr>
              </thead>
              <tbody>
                {modelCenterRows.map((row) => {
                  const option = modelOptionsById.get(row.modelId);
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
                        <strong>{row.resolvedProtocol}</strong>
                        <span>{row.protocolSource}</span>
                        <span>{row.providerApi || "-"}</span>
                        {row.compatSummary ? <span>{row.compatSummary}</span> : null}
                        {row.protocolWarnings.length ? (
                          <span className={`${styles.inlineBadge} ${styles.inlineBadgeWarning}`} title={row.protocolWarnings.join("\n")}>
                            {row.protocolWarnings.length}
                          </span>
                        ) : null}
                      </td>
                      <td>
                        <div className={styles.profileTableActions}>
                          <button
                            type="button"
                            className={`${styles.actionButton} ${styles.compactButton}`}
                            disabled={structuredActionsDisabled || !row.editable || !option}
                            onClick={() => {
                              if (!option) {
                                return;
                              }
                              setModelEditorError("");
                              setModelEditor(hydrateModelEditorFromOption(option));
                              setModelEditorExpanded(true);
                              focusModelEditor();
                            }}
                          >
                            <Pencil size={14} />
                            {copy.modelEditorEdit}
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

        {activeEditorSections.map((section) => (
          <ConfigSectionEditor
            key={section.id}
            section={section}
            value={getConfigValueAtPath(draftConfig, section.path)}
            metaMap={editorMeta}
            lang={currentLanguage}
            copy={copy}
            disabled={structuredActionsDisabled}
            uiState={sectionUiState[section.id] ?? defaultSectionUiState()}
            onUiStateChange={updateSectionUiState}
            onSaveSection={saveConfigSection}
            onAvatarImageUpload={handleAvatarImageUpload}
            onThemeBackgroundImageUpload={handleThemeBackgroundImageUpload}
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
            <LazyJsonCodeMirror value={jsonText} onChange={(value) => setJsonText(value)} />
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
