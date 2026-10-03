import "../design/route-css/config.tailwind.css";
import { ConfigSettingsIndex } from "./ConfigSettingsIndex";
import { ConfigDesktopPetSettings } from "./ConfigDesktopPetSettings";
import { ConfigShortcutsPanel } from "./ConfigShortcutsPanel";
import { ConfigUiFontSettings } from "./ConfigUiFontSettings";

import { useQueryClient } from "@tanstack/react-query";
import {
  ChevronRight,
  Image as ImageIcon,
  Pencil,
  Plus,
  RotateCcw,
  Save,
  Upload,
  X,
} from "lucide-react";
import {
  Fragment,
  lazy,
  Suspense,
  type CSSProperties,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "react";
import { type BlockerFunction, useBlocker, useNavigate, useSearchParams } from "react-router-dom";

import {
  applyConfigWorkspace,
  openConfigEnvironment,
  previewConfigDraft,
  updateConfigLanguage,
  uploadConfigAvatarImage,
  uploadConfigThemeBackgroundImage,
} from "../api/config";
import { queryKeys } from "../api/queryKeys";
import {
  ConfigEditorSection,
  ConfigDraftMeta,
  ConfigMigrationPreview,
  ConfigWorkspace,
} from "../api/types";
import {
  asRecord,
  clonePublicConfig,
  buildConfigApplyPayload,
  configInvalidationDomainsForApply,
  deriveConfigEditorSyncState,
  getString,
  hasPendingSecretChanges,
  pickEditableConfigView,
  resolveConfigSectionUiStateOnSelect,
  shouldBlockConfigLeave,
  setValueAtConfigPath,
  type PublicConfigShape,
} from "./configRouteLogic";
import {
  configSectionExpandedByDefault,
  configSectionFieldCopy,
  configSectionPresentation,
  configSectionTierCounts,
  isCommonConfigSectionEntry,
} from "./configSectionPresentation";
import {
  VButton,
  VActionGroup,
  VCheckbox,
  VChip,
  VConfirmDialog,
  VDialog,
  VInput,
  VPanelHeader,
  VRouteLinkButton,
  VSection,
  VSettingsFormPage,
  VSettingsGroupCard,
  VSettingsRow,
  VSplitWorkspace,
  VStatusChip,
  VStatusStrip,
  VStringSelect,
  VStateSurface,
  VSurface,
  VTextarea,
} from "../components/vui";
import { WORKBENCH_LAYOUT_IDS } from "../components/layout/workbenchLayoutIds";
import { safeAgentCenterReturnToPath } from "./agentCenterRoutes";
import { publishConfigDraftPresence } from "./configDraftPresence";
import {
  markProviderOnboardingSeen,
  shouldAutoOpenProviderOnboarding,
} from "./config/onboardingGate";
import { useConfigWorkspaceQueries } from "./config/useConfigWorkspaceQueries";
import {
  buildConfigApplyRequestPayload,
  isConfigBaselineStaleErrorMessage,
  isUiLanguageFieldPath,
  shouldImmediateApplyConfigPath,
  shouldImmediateApplyFieldKind,
  UI_LANGUAGE_FIELD_PATH,
  type ConfigApplyDraftOverride,
  type ImmediateFieldStatus,
} from "./config/configApplyModel";
import {
  collectPendingDraftLeaves,
  configValuesEqual,
  deriveNumberStep,
  fieldEditorDisplayText,
  isToolNameListPath,
  numberBounds,
  resolveDraftSubtreeForSave,
  stepNumberValue,
  validateJsonText,
  validateListText,
  validateNumberText,
  type JsonParseIssue,
  type ListIssue,
  type NumberIssue,
} from "./config/configFieldEditorsModel";
import { useConfigProviderDraftActions } from "./config/useConfigProviderDraftActions";
import { useConfigProviderQuickSetupActions } from "./config/useConfigProviderQuickSetupActions";
import { useConfigMigrationActions } from "./config/useConfigMigrationActions";
import { ConfigOverviewPanel } from "./ConfigOverviewPanel";
import {
  type ConfigProviderRegistryTab,
  type ProviderActionFeedback,
} from "./ConfigProviderRegistryPanel";
import {
  buildConfigSettingsGroups,
  ConfigSettingsPageTabs,
  ConfigSettingsSidebar,
  DEFAULT_CONFIG_SETTINGS_GROUP_ID,
  resolveConfigSettingsSelection,
  type ConfigSettingsGroupCopy,
  type ConfigSettingsGroupId,
} from "./ConfigSettingsNavigation";
import {
  buildConfigSettingsNavigationSearch,
  buildConfigSettingsSearchIndex,
  resolveConfigSettingsFocus,
} from "./configSettingsSearch";
import {
  consumeSettingsFocusIntent,
  notifySettingsContentReady,
  onSettingsContentReady,
  readLastSettingsLocation,
  resolveSettingsEntry,
  subscribeSettingsFocus,
  writeLastSettingsLocation,
  type SettingsFocusTarget,
} from "../app/settingsNavigation";
import { ConfigWorkspacePlaceholderPanel } from "./ConfigWorkspacePlaceholderPanel";

/** Heavy settings sections — keep off Config shell first paint (R2). */
const ConfigDraftPanel = lazy(() =>
  import("./ConfigDraftPanel").then((m) => ({ default: m.ConfigDraftPanel })),
);
const ConfigDiagnosisPanel = lazy(() => import("./ConfigDiagnosisPanel"));
const ConfigFeatureDecisionPanel = lazy(() =>
  import("./ConfigFeatureDecisionPanel").then((m) => ({ default: m.ConfigFeatureDecisionPanel })),
);
const ConfigHealthDiagnosticsPanel = lazy(() =>
  import("./ConfigHealthDiagnosticsPanel").then((m) => ({ default: m.ConfigHealthDiagnosticsPanel })),
);
const ConfigModelMigrationPanel = lazy(() =>
  import("./ConfigModelMigrationPanel").then((m) => ({ default: m.ConfigModelMigrationPanel })),
);
const ConfigQuickSetupPanel = lazy(() =>
  import("./ConfigQuickSetupPanel").then((m) => ({ default: m.ConfigQuickSetupPanel })),
);
const ConfigProviderRegistryPanel = lazy(() =>
  import("./ConfigProviderRegistryPanel").then((m) => ({ default: m.ConfigProviderRegistryPanel })),
);
const ConfigProviderWizard = lazy(() =>
  import("./ConfigProviderWizard").then((m) => ({ default: m.ConfigProviderWizard })),
);
const ConfigRuntimePanel = lazy(() =>
  import("./ConfigRuntimePanel").then((m) => ({ default: m.ConfigRuntimePanel })),
);
import {
  buildProviderWizardDraft,
  deriveProviderRegistryRows,
  initialProviderQuickSetupState,
  initialProviderWizardState,
  providerQuickSetupReducer,
  providerWizardReducer,
  type ProviderWizardState,
} from "./configProviderLogic";
import styles from "./ConfigRoute.styles";

const CONFIG_SETTINGS_LAYOUT_ID = WORKBENCH_LAYOUT_IDS.configSettings;
/** Sidebar width contract — owned by VSplitWorkspace resize (not route-local CSS vars). */
const CONFIG_SETTINGS_SIDEBAR_RESIZE = {
  id: "sidebar",
  defaultWidth: 280,
  minWidth: 220,
  maxWidth: 360,
} as const;
/** 已生效徽标的最短展示时长：apply 成功后基线立即对齐，徽标短暂驻留后再清除。 */
const IMMEDIATE_APPLIED_BADGE_HOLD_MS = 4000;

import {
  type ProviderRouteImpact,
  type ProviderRoutePreview,
} from "./config/useConfigProviderDraftActions";
import { CONFIG_COPY, formatConfigCopy, type ConfigCopy, type ConfigLanguage } from "./config/configCopy";
import {
  type AvatarImageUploadResponse,
  ConfigSectionEditor,
} from "./config/ConfigSectionEditor";
import {
  defaultSectionUiState,
  emptyDraftMeta,
  fileToBase64,
  formatJson,
  getConfigValueAtPath,
  getDraftLanguage,
  providerDiscoveryFailureDetail,
  providerDiscoveryFailureMessage,
  readableErrorMessage,
  type ConfigSectionUiState,
} from "./config/configEditorModel";
import { useConfigProviderModelDomain } from "./config/useConfigProviderModelDomain";
type NoticeTone = "neutral" | "success" | "error";


export function ConfigRoute() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const contentViewportRef = useRef<HTMLDivElement | null>(null);
  const lastRequestedSelectionRef = useRef("");
  const lastFocusedSelectionRef = useRef("");
  const pendingFocusSectionRef = useRef("");
  const providerDraftRequestRef = useRef<{
    publicConfig: PublicConfigShape;
    draftMeta: ConfigDraftMeta;
    baseHash: string;
    modelCatalog: ConfigWorkspace["modelCatalog"];
  } | null>(null);
  const { workspaceQuery, healthDiagnosticsQuery } = useConfigWorkspaceQueries();

  const [draftConfig, setDraftConfig] = useState<PublicConfigShape | null>(null);
  const [baseConfig, setBaseConfig] = useState<PublicConfigShape | null>(null);
  const [draftMeta, setDraftMeta] = useState<ConfigDraftMeta>(emptyDraftMeta());
  const [baseHash, setBaseHash] = useState("");
  const [draftHash, setDraftHash] = useState("");
  const [activeWorkspace, setActiveWorkspace] = useState<ConfigWorkspace | null>(null);
  const [jsonText, setJsonText] = useState("{}");
  const [notice, setNotice] = useState<{ tone: NoticeTone; text: string }>({ tone: "neutral", text: "" });
  const [busyAction, setBusyAction] = useState("");
  const [providerConnecting, setProviderConnecting] = useState(false);
  const [providerShowMore, setProviderShowMore] = useState(false);
  const [providerQuickSetupState, dispatchProviderQuickSetup] = useReducer(
    providerQuickSetupReducer,
    undefined,
    initialProviderQuickSetupState,
  );
  const [providerQuickCredential, setProviderQuickCredential] = useState("");
  const [migrationPreview, setMigrationPreview] = useState<ConfigMigrationPreview | null>(null);
  const [activeGroupId, setActiveGroupId] = useState(() => searchParams.get("section") ?? "");
  const [activePageId, setActivePageId] = useState("");
  // 导航意图（settingsNavigation）：搜索选中/命令面板跳转的落地目标；
  // 等待分区内容 ready（onContentReady / 依赖变化）后一次性消费。
  const [pendingIntentFocus, setPendingIntentFocus] = useState<{ sectionId: string; fieldId: string } | null>(null);
  // 字段深链的瞬态高亮（~2s 后摘除）。
  const [fieldHighlight, setFieldHighlight] = useState<{ path: string } | null>(null);
  const fieldHighlightTimerRef = useRef(0);
  // 分区内容 ready 脉冲：ConfigSectionEditor 经意图模块广播，触发落地重放。
  const [settingsReadyToken, setSettingsReadyToken] = useState(0);
  // 「上次停留分区」恢复每次挂载只尝试一次。
  const lastLocationRestoreAttemptedRef = useRef(false);
  const [sectionUiState, setSectionUiState] = useState<Record<string, ConfigSectionUiState>>({});
  // 即时类字段（boolean/select）的行徽标生命周期：waiting → applied|failed。
  const [immediateFieldStatus, setImmediateFieldStatus] = useState<Record<string, ImmediateFieldStatus>>({});
  const immediateStatusTimersRef = useRef<Record<string, number>>({});
  // 分区保存失败的行内错误（wave 4）：按分区 path 记录，落在该分区内，
  // 不再占用全局 notice strip（那里保留给 apply/上传等真正全局的操作）。
  const [sectionSaveErrors, setSectionSaveErrors] = useState<Record<string, string>>({});
  // Atomic edit baseline: only rewritten on full workspace load/apply, never on draft pin/key/route ops.
  // Keeps baseConfig + baseHash paired so apply after pin does not 409 with "配置基线已过期".
  const editBaselineRef = useRef<{ baseConfig: PublicConfigShape | null; baseHash: string }>({
    baseConfig: null,
    baseHash: "",
  });

  function syncWorkspace(workspace: ConfigWorkspace, tone: NoticeTone = "neutral", options: { resetBase?: boolean } = {}) {
    const resetBase = options.resetBase !== false;
    if (resetBase) {
      const nextBaseConfig = clonePublicConfig(workspace.publicConfig);
      const nextBaseHash = String(workspace.baseHash || workspace.hash || "").trim();
      editBaselineRef.current = { baseConfig: nextBaseConfig, baseHash: nextBaseHash };
      setBaseConfig(nextBaseConfig);
      setBaseHash(nextBaseHash);
    }
    const baselineHash = editBaselineRef.current.baseHash || String(workspace.baseHash || "").trim();
    providerDraftRequestRef.current = {
      publicConfig: workspace.publicConfig,
      draftMeta: workspace.draftMeta,
      // Draft mutations must keep sending the frozen external baseline hash, not the draft hash.
      baseHash: baselineHash,
      modelCatalog: workspace.modelCatalog,
    };
    setActiveWorkspace(clonePublicConfig(workspace));
    setDraftConfig(clonePublicConfig(workspace.publicConfig));
    setDraftMeta(clonePublicConfig(workspace.draftMeta));
    setDraftHash(workspace.hash);
    setJsonText(formatJson(pickEditableConfigView(workspace.publicConfig, workspace.editorSections)));
    setNotice({ tone, text: workspace.message || "" });
  }

  useEffect(() => {
    // Background query refreshes must not replace an open editing session.
    // Explicit reload and successful apply still call syncWorkspace directly.
    if (workspaceQuery.data && !editBaselineRef.current.baseConfig) {
      syncWorkspace(workspaceQuery.data);
    }
  }, [workspaceQuery.data]);

  const workspace = activeWorkspace ?? workspaceQuery.data;
  const currentLanguage = getDraftLanguage(draftConfig, workspace?.language === "en" ? "en" : "zh");
  const copy = CONFIG_COPY[currentLanguage];
  const requestedSectionId = String(searchParams.get("section") || "").trim();
  const requestedPageId = String(searchParams.get("page") || "").trim();
  const requestedFocusSectionId = String(searchParams.get("focus") || "").trim();
  const requestedFocusFieldId = String(searchParams.get("field") || "").trim();
  const showingSettingsIndex = !requestedPageId && !requestedFocusSectionId;
  const returnToPath = safeAgentCenterReturnToPath(searchParams.get("returnTo"));
  const returnToLabel = searchParams.get("returnLabel") === "agents" ? copy.returnToAgents : copy.returnToSource;
  const formattedDraft = useMemo(
    () => formatJson(pickEditableConfigView(draftConfig ?? {}, workspace?.editorSections ?? [])),
    [draftConfig, workspace?.editorSections],
  );
  const hasUnsavedConfigChanges = Boolean(baseHash && draftHash && baseHash !== draftHash);
  // First-run onboarding: auto-open the provider quick-setup panel once per
  // browser session while no model credential is configured (skippable, and
  // the settings entry stays available via "添加供应商").
  useEffect(() => {
    if (!workspace?.modelOptions) {
      return;
    }
    if (shouldAutoOpenProviderOnboarding(workspace.modelOptions)) {
      markProviderOnboardingSeen();
      setProviderConnecting(true);
    }
  }, [workspace]);
  const workspaceSections = workspace?.sections ?? [];
  const editorSections = workspace?.editorSections ?? [];
  const editorMeta = workspace?.editorMeta ?? {};
  const groupCopy = useMemo<ConfigSettingsGroupCopy>(() => ({
    "overview-apply": { title: copy.groupOverviewSaveTitle, summary: copy.groupOverviewSaveSummary },
    "workbench-interface": { title: copy.groupWorkbenchTitle, summary: copy.groupWorkbenchSummary },
    "avatar-pet": { title: copy.groupAvatarPetTitle, summary: copy.groupAvatarPetSummary },
    "models-profiles": { title: copy.groupModelingTitle, summary: copy.groupModelingSummary },
    "runtime-context": { title: copy.groupRuntimeContextTitle, summary: copy.groupRuntimeContextSummary },
    "tooling-diagnostics": { title: copy.groupToolingTitle, summary: copy.groupToolingSummary },
  }), [copy]);
  const settingsGroups = useMemo(
    () => buildConfigSettingsGroups(workspaceSections, groupCopy, currentLanguage),
    [currentLanguage, groupCopy, workspaceSections],
  );
  const settingsSearchDocuments = useMemo(
    () => [...buildConfigSettingsSearchIndex({
      groups: settingsGroups,
      editorSections: workspace?.editorSections ?? [],
      editorMeta: workspace?.editorMeta ?? {},
      configValues: draftConfig,
      language: currentLanguage,
    }), {
      groupId: "avatar-pet" as const, pageId: "identity-profile", sectionId: "pet",
      title: copy.searchPetTitle,
      detail: copy.searchPetDetail,
      haystack: copy.searchPetHaystack,
      titleHaystack: copy.searchPetTitleHaystack,
      valueHaystack: "",
    }],
    [currentLanguage, draftConfig, settingsGroups, workspace?.editorMeta, workspace?.editorSections],
  );
  const { group: activeGroup, page: activePage } = useMemo(
    () => resolveConfigSettingsSelection(settingsGroups, activeGroupId, activePageId),
    [activeGroupId, activePageId, settingsGroups],
  );
  const editorSectionById = new Map(editorSections.map((section) => [section.id, section]));
  const activeEditorSections = (activePage?.memberSectionIds ?? [])
    .filter((sectionId) => !requestedFocusSectionId || sectionId === requestedFocusSectionId)
    .map((sectionId) => editorSectionById.get(sectionId))
    .filter((section): section is ConfigEditorSection => Boolean(section) && section?.id !== "agent");
  const providerPresetOptions = workspace?.providerPresetOptions ?? [];
  const providerRows = useMemo(
    () => deriveProviderRegistryRows(
      workspace?.providerOptions ?? [],
      workspace?.modelCatalog ?? { schemaVersion: 2, providerCount: 0, modelCount: 0, providers: {} },
      // Prefer live draft so pin upgrades show immediately even if discovery catalog still says "observed".
      draftConfig ?? workspace?.publicConfig,
    ),
    [draftConfig, workspace?.modelCatalog, workspace?.providerOptions, workspace?.publicConfig],
  );

  useEffect(() => {
    if (!settingsGroups.length) {
      setActiveGroupId("");
      setActivePageId("");
      return;
    }
    const requestedSelectionKey = `${requestedSectionId}:${requestedPageId}:${requestedFocusSectionId}`;
    if (requestedSelectionKey !== lastRequestedSelectionRef.current) {
      lastRequestedSelectionRef.current = requestedSelectionKey;
      const requestedGroup = settingsGroups.find((group) => group.id === requestedSectionId)
        ?? settingsGroups.find((group) => group.id === DEFAULT_CONFIG_SETTINGS_GROUP_ID)
        ?? settingsGroups[0];
      setActiveGroupId(requestedGroup?.id ?? "");
      const requestedPage = requestedGroup?.pages.find((page) => page.id === requestedPageId);
      setActivePageId(requestedPage?.id ?? requestedGroup?.pages[0]?.id ?? "");
      const focusPage = requestedPage ?? requestedGroup?.pages[0];
      if (requestedFocusSectionId && focusPage?.memberSectionIds.includes(requestedFocusSectionId)) {
        setSectionUiState((current) => ({
          ...current,
          [requestedFocusSectionId]: requestedFocusFieldId
            ? prepareSectionUiStateForFocus(current[requestedFocusSectionId], requestedFocusSectionId, requestedFocusFieldId)
            : resolveConfigSectionUiStateOnSelect(
              current[requestedFocusSectionId],
              defaultSectionUiState(requestedFocusSectionId),
            ),
        }));
        pendingFocusSectionRef.current = requestedFocusSectionId;
      } else {
        pendingFocusSectionRef.current = "";
      }
      return;
    }
    const currentGroup = settingsGroups.find((group) => group.id === activeGroupId)
      ?? settingsGroups.find((group) => group.id === DEFAULT_CONFIG_SETTINGS_GROUP_ID)
      ?? settingsGroups[0];
    if (currentGroup.id !== activeGroupId) {
      setActiveGroupId(currentGroup.id);
    }
    if (!currentGroup.pages.some((page) => page.id === activePageId)) {
      setActivePageId(currentGroup.pages[0]?.id ?? "");
    }
  }, [activeGroupId, activePageId, requestedFocusSectionId, requestedPageId, requestedSectionId, settingsGroups]);

  const sectionMap = useMemo(() => {
    return new Map((workspace?.sections ?? []).map((section) => [section.id, section]));
  }, [workspace?.sections]);
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

  // Provider/model domain (models page state machine) — see hook header.
  const {
    selectedProviderId,
    selectedProviderTab,
    providerWizardState,
    routePreview,
    routeEditProviderId,
    routeEditProvider,
    providerCredentialEditId,
    providerCredentialValue,
    providerActionError,
    providerActionFeedback,
    credentialProvider,
    liveReferenceCountByModelRef,
    setSelectedProviderId,
    setSelectedProviderTab,
    setProviderCredentialEditId,
    setProviderCredentialValue,
    setRouteEditProviderId,
    setRouteEditProvider,
    setRoutePreview,
    setProviderActionError,
    setProviderActionFeedback,
    dispatchProviderWizard,
    persistImmediateDraft,
    handleTestProviderModel,
    handleCheckModelImageCapabilities,
  } = useConfigProviderModelDomain({
    workspaceQuery,
    providerRows,
    draftMeta,
    baseHash,
    structuredActionsDisabled,
    setBusyAction,
    setNotice,
    markError,
    requireDraft,
    syncWorkspace,
    readableErrorMessage,
    handleApply,
    providerDraftRequestRef,
    copy,
  });
  // 全局待保存计数口径：各分区编辑态草稿里「草稿值≠当前分区值」的叶子字段数。
  // 原始文本 kinds（json/number/string_list）先按 schema 解析再比较，"16000" 与
  // 16000 不会误报；解析失败的叶子计入且 valid=false（阻塞全局保存）。即时类
  // 字段（boolean/select，见 configApplyModel.shouldImmediateApplyFieldKind）
  // 永不滞留草稿，不计入。
  const pendingConfigDraftItems = useMemo(() => {
    const items: Array<{ path: string; sectionId: string; valid: boolean }> = [];
    if (!draftConfig) {
      return items;
    }
    const metaAt = (path: string) => editorMeta[path];
    for (const section of editorSections) {
      const sectionState = sectionUiState[section.id];
      if (!sectionState?.editing || sectionState.draftValue === undefined) {
        continue;
      }
      const sectionValue = getConfigValueAtPath(draftConfig, section.path);
      for (const leaf of collectPendingDraftLeaves({
        draft: sectionState.draftValue,
        committed: sectionValue,
        path: section.path,
        metaAt,
      })) {
        items.push({ ...leaf, sectionId: section.id });
      }
    }
    return items;
  }, [draftConfig, editorMeta, editorSections, sectionUiState]);
  const pendingConfigDraftCount = pendingConfigDraftItems.length;
  const hasInvalidConfigDraft = pendingConfigDraftItems.some((item) => !item.valid);
  const canApplyConfigWorkspace =
    !structuredActionsDisabled && !hasInvalidConfigDraft && (canSaveConfig || pendingConfigDraftCount > 0);
  // 跨页 presence 广播：保持原有口径，接入分区草稿待保存计数。
  const configDraftPresenceDirty =
    hasUnsavedConfigChanges || hasPendingSecretChanges(draftMeta) || pendingConfigDraftCount > 0;
  useEffect(() => {
    publishConfigDraftPresence(configDraftPresenceDirty);
  }, [configDraftPresenceDirty]);
  const shouldBlockLeave = useCallback<BlockerFunction>(
    ({ currentLocation, nextLocation }) =>
      shouldBlockConfigLeave({
        hasPendingApply,
        hasPendingSectionDrafts: pendingConfigDraftCount > 0,
        busy: Boolean(busyAction),
        currentPathname: currentLocation.pathname,
        nextPathname: nextLocation.pathname,
      }),
    [busyAction, hasPendingApply, pendingConfigDraftCount],
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
    return !showingSettingsIndex && (!requestedFocusSectionId || requestedFocusSectionId === sectionId)
      && Boolean(activePage?.memberSectionIds.includes(sectionId));
  }

  function navigateSettingsSelection(groupId: ConfigSettingsGroupId, pageId: string, focusSectionId?: string, focusFieldId?: string) {
    pendingFocusSectionRef.current = focusSectionId ?? "";
    navigate({ search: buildConfigSettingsNavigationSearch(searchParams, groupId, pageId, focusSectionId, focusFieldId) });
  }

  /** 字段/分区聚焦前的分区 UI 预备：展开分区、高级层与目标路径的祖先嵌套层。 */
  function prepareSectionUiStateForFocus(
    current: ConfigSectionUiState | undefined,
    sectionId: string,
    fieldId: string,
  ): ConfigSectionUiState {
    const base = resolveConfigSectionUiStateOnSelect(current, defaultSectionUiState(sectionId));
    const ancestors: Record<string, boolean> = {};
    const tokens = fieldId.split(".").filter(Boolean);
    // 祖先对象键是分区路径下的绝对子路径（如 ui.workbench_theme）：跳过分区根本身与叶子本身。
    for (let index = 2; index < tokens.length; index += 1) {
      ancestors[tokens.slice(0, index).join(".")] = true;
    }
    return {
      ...base,
      expanded: true,
      advancedExpanded: true,
      expandedPaths: { ...base.expandedPaths, ...ancestors },
    };
  }

  /** 字段深链落地：滚动到目标行并挂 ~2s 瞬态高亮环。 */
  function triggerFieldHighlight(path: string) {
    window.clearTimeout(fieldHighlightTimerRef.current);
    setFieldHighlight({ path });
    fieldHighlightTimerRef.current = window.setTimeout(() => setFieldHighlight(null), 2000);
  }

  /** 一次性聚焦尝试：分区级滚到分区顶，字段级滚到目标 VSettingsRow 行。 */
  function tryFocusSettingsTarget(sectionId: string, fieldId: string): boolean {
    const section = document.getElementById(`config-${sectionId}`);
    if (!section) {
      return false;
    }
    if (fieldId) {
      const row = document.querySelector<HTMLElement>(`[data-testid="row-${fieldId}"]`);
      if (!row) {
        return false;
      }
      row.scrollIntoView({ behavior: "smooth", block: "center" });
      triggerFieldHighlight(fieldId);
      return true;
    }
    section.scrollIntoView({ behavior: "smooth", block: "start" });
    section.focus({ preventScroll: true });
    return true;
  }

  /**
   * 意图模块的统一落地入口（搜索选中/命令面板/跨页跳转共用）。
   * URL 只承载 section/page 导航状态；聚焦意图走意图模块（显式 URL 参数优先）。
   */
  function applySettingsFocusTarget(target: SettingsFocusTarget) {
    const fieldId = (target.fieldId ?? "").trim();
    let sectionId = (target.sectionId ?? "").trim();
    let group = target.groupId ? settingsGroups.find((candidate) => candidate.id === target.groupId) : undefined;
    if (!group && sectionId) {
      for (const candidate of settingsGroups) {
        const ownerPage = candidate.pages.find((item) => item.memberSectionIds.includes(sectionId));
        if (ownerPage) {
          group = candidate;
          break;
        }
      }
    }
    if (!sectionId && fieldId) {
      // 字段目标缺分区时按编辑器分区归属推导。
      const owner = (workspace?.editorSections ?? []).find(
        (section) => fieldId === section.path || fieldId.startsWith(`${section.path}.`),
      );
      sectionId = owner?.id ?? "";
    }
    const page = group?.pages.find((item) => item.id === target.pageId) ?? group?.pages[0];
    if (group) {
      setActiveGroupId(group.id);
      setActivePageId(page?.id ?? "");
    }
    if (sectionId) {
      setSectionUiState((current) => ({
        ...current,
        [sectionId]: fieldId
          ? prepareSectionUiStateForFocus(current[sectionId], sectionId, fieldId)
          : resolveConfigSectionUiStateOnSelect(current[sectionId], defaultSectionUiState(sectionId)),
      }));
      // 显式选择总是重新聚焦：清 dedup，允许同一目标重复落点。
      lastFocusedSelectionRef.current = "";
      setPendingIntentFocus({ sectionId, fieldId });
    }
    if (group) {
      navigate({ search: buildConfigSettingsNavigationSearch(searchParams, group.id, page?.id ?? "") });
    }
  }

  const applySettingsFocusTargetRef = useRef(applySettingsFocusTarget);
  applySettingsFocusTargetRef.current = applySettingsFocusTarget;

  // 已打开设置页的即时热切换：意图广播 → 落地（同时清掉暂存，避免下次挂载重复消费）。
  useEffect(
    () =>
      subscribeSettingsFocus((target) => {
        consumeSettingsFocusIntent();
        applySettingsFocusTargetRef.current(target);
      }),
    [],
  );

  // 分区内容 ready 信号：落地执行器据此重放聚焦尝试。
  useEffect(
    () =>
      onSettingsContentReady(() => {
        setSettingsReadyToken((token) => token + 1);
      }),
    [],
  );

  useEffect(() => () => window.clearTimeout(fieldHighlightTimerRef.current), []);

  // 落地执行器：意图/URL 聚焦目标等待内容 ready 后一次性滚动聚焦。
  // ready 来源：意图模块脉冲（分区编辑器挂载/展开变化）+ 本 effect 依赖变化
  // （工作区数据到达、页切换等）；DOM 仍缺失时挂 MutationObserver 事件驱动
  // 等待（懒分区/特殊面板），替代旧的 60 帧 rAF 轮询。
  useEffect(() => {
    const intentTarget = pendingIntentFocus;
    const focusSectionId = intentTarget?.sectionId || pendingFocusSectionRef.current || requestedFocusSectionId;
    const focusDecision = resolveConfigSettingsFocus(
      lastFocusedSelectionRef.current,
      activeGroupId,
      activePageId,
      focusSectionId,
    );
    if (!focusSectionId) {
      lastFocusedSelectionRef.current = focusDecision.nextKey;
      return;
    }
    if (!isSectionVisible(focusSectionId)) {
      // URL 跨页 focus 等待目标页可见是合法状态；URL pending 不残留（陈旧值遮蔽后续参数），
      // 意图 pending 留存等可见后落地。
      if (!intentTarget) {
        pendingFocusSectionRef.current = "";
      }
      return;
    }
    if (!focusDecision.shouldFocus) {
      if (intentTarget) {
        setPendingIntentFocus(null);
      } else {
        pendingFocusSectionRef.current = "";
      }
      return;
    }
    const fieldTarget = intentTarget
      ? (intentTarget.sectionId === focusSectionId ? intentTarget.fieldId : "")
      : (requestedFocusSectionId === focusSectionId ? requestedFocusFieldId : "");
    if (tryFocusSettingsTarget(focusSectionId, fieldTarget)) {
      lastFocusedSelectionRef.current = focusDecision.nextKey;
      pendingFocusSectionRef.current = "";
      if (intentTarget) {
        setPendingIntentFocus(null);
      }
      return;
    }
    if (intentTarget || pendingFocusSectionRef.current) {
      // 内容未 ready：挂 MutationObserver 等待目标节点出现（事件驱动，不轮询）。
      const viewport = contentViewportRef.current;
      if (!viewport || typeof MutationObserver === "undefined") {
        return;
      }
      const observer = new MutationObserver(() => {
        if (tryFocusSettingsTarget(focusSectionId, fieldTarget)) {
          observer.disconnect();
          lastFocusedSelectionRef.current = focusDecision.nextKey;
          pendingFocusSectionRef.current = "";
          setPendingIntentFocus(null);
        }
      });
      observer.observe(viewport, { childList: true, subtree: true });
      return () => observer.disconnect();
    }
  }, [
    pendingIntentFocus,
    settingsReadyToken,
    activeGroupId,
    activePageId,
    requestedFocusSectionId,
    activePage?.id,
    showingSettingsIndex,
    workspace,
    sectionUiState,
  ]);

  // 挂载入口裁决（每次挂载一次）：显式 URL > 意图 > 上次停留 > 默认。
  // 默认分支不做事 = 保持现状（首次进入落在全部设置总览）。
  useEffect(() => {
    if (lastLocationRestoreAttemptedRef.current || !settingsGroups.length) {
      return;
    }
    lastLocationRestoreAttemptedRef.current = true;
    if (requestedSectionId || requestedPageId || requestedFocusSectionId || requestedFocusFieldId) {
      // 显式 URL 入口：由既有 URL 流程处理，意图留存到下一次无参进入。
      return;
    }
    const entry = resolveSettingsEntry({
      urlGroupId: requestedSectionId,
      urlPageId: requestedPageId,
      urlSectionId: requestedFocusSectionId,
      urlFieldId: requestedFocusFieldId,
    });
    if (entry.source === "intent") {
      if (entry.groupId || entry.pageId || entry.sectionId || entry.fieldId) {
        applySettingsFocusTarget({
          groupId: entry.groupId,
          pageId: entry.pageId,
          sectionId: entry.sectionId,
          fieldId: entry.fieldId,
        });
      }
      return;
    }
    if (entry.source === "last" && entry.groupId) {
      const group = settingsGroups.find((candidate) => candidate.id === entry.groupId);
      if (!group) {
        return;
      }
      const page = group.pages.find((candidate) => candidate.id === entry.pageId) ?? group.pages[0];
      setActiveGroupId(group.id);
      setActivePageId(page?.id ?? "");
      // 与手点分组一致：落回该组的设置索引（?section=组，无 page/focus/field）。
      const params = new URLSearchParams(searchParams);
      params.set("section", group.id);
      params.delete("page");
      params.delete("focus");
      params.delete("field");
      navigate({ search: params.toString() }, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settingsGroups, requestedSectionId, requestedPageId, requestedFocusSectionId, requestedFocusFieldId]);

  // 「上次停留分区」记忆：组/页确定后写入，下一次打开设置页默认停在该组。
  useEffect(() => {
    if (!activeGroupId || !activePageId) {
      return;
    }
    writeLastSettingsLocation({ groupId: activeGroupId, pageId: activePageId });
  }, [activeGroupId, activePageId]);

  function handleSelectGroup(groupId: ConfigSettingsGroupId) {
    const group = settingsGroups.find((candidate) => candidate.id === groupId);
    const pageId = group?.pages[0]?.id ?? "";
    handleNavigateSettings(groupId, pageId);
  }

  function showSettingsIndex(groupId?: ConfigSettingsGroupId) {
    const params = new URLSearchParams(searchParams);
    params.delete("page"); params.delete("focus"); params.delete("field");
    if (groupId) params.set("section", groupId);
    else params.delete("section");
    pendingFocusSectionRef.current = "";
    setPendingIntentFocus(null);
    navigate({ search: params.toString() });
  }

  function handleNavigateSettings(groupId: ConfigSettingsGroupId, pageId: string, sectionId?: string, fieldId?: string) {
    setActiveGroupId(groupId);
    setActivePageId(pageId);
    contentViewportRef.current?.scrollTo({ top: 0, behavior: "smooth" });
    if (groupId === "avatar-pet" && sectionId === "pet") {
      navigateSettingsSelection(groupId, pageId, sectionId);
      return;
    }
    if (sectionId || fieldId) {
      // 搜索选中等显式落点：经意图模块统一落地（分区/字段聚焦 + 瞬态高亮）。
      applySettingsFocusTarget({ groupId, pageId, sectionId, fieldId });
      return;
    }
    navigateSettingsSelection(groupId, pageId);
  }

  function handleSelectPage(pageId: string) {
    setActivePageId(pageId);
    const page = activeGroup?.pages.find((candidate) => candidate.id === pageId);
    for (const sectionId of page?.memberSectionIds ?? []) {
      updateSectionUiState(sectionId, resolveConfigSectionUiStateOnSelect(sectionUiState[sectionId], defaultSectionUiState(sectionId)));
    }
    if (activeGroup?.id) navigateSettingsSelection(activeGroup.id, pageId);
    contentViewportRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  }

  function handleRepairProviderCredential(providerId: string) {
    if (!providerRows.some((row) => row.providerId === providerId)) return;

    setActiveGroupId("models-profiles");
    setActivePageId("model-connection");
    setProviderConnecting(false);
    setProviderShowMore(false);
    setSelectedProviderId(providerId);
    setSelectedProviderTab("connection");
    setProviderCredentialEditId(providerId);
    navigateSettingsSelection("models-profiles", "model-connection", "models");
    setProviderCredentialValue("");
    setRouteEditProviderId("");
    setRouteEditProvider({});
    setRoutePreview(null);
    setProviderActionFeedback(null);
    contentViewportRef.current?.scrollTo({ top: 0, behavior: "smooth" });
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
      queryClient.invalidateQueries({ queryKey: queryKeys.launcherMaintenanceSummary() }),
    ];
    if (domains.includes("evolution")) {
      invalidations.push(
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionOverview() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionLibrary() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionSelfWorkspaceSnapshot() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionWorkspaceSnapshot() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionWorktreeActiveRun() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionWorktreeRuns() }),
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

  const {
    buildProviderDraftRequest,
    handleDiscoverProvider,
    handleSuggestProviderId,
    handleCreateProvider,
    handlePinProviderModels,
    handleUnpinProviderModel: unpinProviderModel,
    handleDeleteProvider,
    deleteProviderRequest,
    handleConfirmDeleteProvider,
    handleCancelDeleteProvider,
    handleUpdateProviderCredential: updateProviderCredential,
    handleUpdatePinnedModel,
    handleUpdateProviderContextWindow: updateProviderContextWindow,
    handleToggleProviderEnabled,
    handleBeginProviderRouteEdit,
    handlePreviewProviderRoute,
    handleApplyProviderRoutePreview: applyProviderRoutePreview,
  } = useConfigProviderDraftActions({
    baseHash,
    draftConfig,
    draftMeta,
    loadFailedMessage: copy.loadFailed,
    copy,
    editBaselineRef,
    providerDraftRequestRef,
    activeWorkspace,
    providerPresetOptions,
    requireDraft,
    syncWorkspace,
    markError,
    readableErrorMessage,
    providerDiscoveryFailureDetail,
    providerDiscoveryFailureMessage: (detail) => providerDiscoveryFailureMessage(detail, copy),
    setBusyAction,
    setProviderActionError,
    setProviderActionFeedback,
    setNotice,
    setSelectedProviderId,
    setSelectedProviderTab,
    setProviderCredentialEditId,
    setProviderCredentialValue,
    setRouteEditProviderId,
    setRouteEditProvider,
    setRoutePreview,
    dispatchProviderWizard,
  });

  const {
    handlePrepareProviderQuickSetup,
    handleConfirmProviderQuickSetup,
  } = useConfigProviderQuickSetupActions({
    providerQuickSetupState,
    copy,
    providerPresetOptions,
    providerDraftRequestRef,
    queryClient,
    dispatchProviderQuickSetup,
    setProviderQuickCredential,
    handleSuggestProviderId,
    handleCreateProvider,
    handleDiscoverProvider,
    handlePinProviderModels,
    handleApply,
    readableErrorMessage,
  });


  async function handleUnpinProviderModel(modelRef: string) {
    const unpinned = await unpinProviderModel(modelRef, (ref) => {
      const separator = ref.indexOf("/");
      if (separator <= 0) return "";
      const providerId = ref.slice(0, separator);
      return providerRows.find((row) => row.providerId === providerId)?.models.find((item) => item.modelRef === ref)?.upstreamId ?? "";
    });
    if (unpinned) {
      await persistImmediateDraft(copy.applying);
    }
  }


  async function handleUpdateProviderCredential(providerId: string) {
    if (structuredActionsDisabled || !providerCredentialValue.trim()) return;
    if (!credentialProvider || credentialProvider.providerId !== providerId || credentialProvider.credentialState === "not_required") return;
    const updated = await updateProviderCredential(providerId, providerCredentialValue);
    if (updated) {
      await persistImmediateDraft(copy.applying);
    }
  }

  async function handleUpdateProviderContextWindow(providerId: string, contextWindow: number | null) {
    if (structuredActionsDisabled) return;
    const updated = await updateProviderContextWindow(providerId, contextWindow);
    if (updated) {
      await persistImmediateDraft(copy.applying);
    }
  }

  async function handleApplyProviderRoutePreview() {
    await applyProviderRoutePreview(routePreview);
  }

  const {
    handlePreviewMigration,
    handleApplyMigration,
    migrationApplyRequest,
    handleConfirmApplyMigration,
    handleCancelApplyMigration,
  } = useConfigMigrationActions({
    migrationPreview,
    migrationPreviewExpiredMessage: copy.migrationPreviewExpired,
    copy,
    workspaceQuery,
    queryClient,
    setBusyAction,
    setMigrationPreview,
    setProviderActionError,
    syncWorkspace,
    markError,
    readableErrorMessage,
  });

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

  async function previewDraft(
    nextConfig: PublicConfigShape,
    nextMeta: ConfigDraftMeta,
    pendingLabel: string,
    onError: (error: unknown) => void = markError,
  ) {
    setBusyAction(pendingLabel);
    try {
      const response = await previewConfigDraft({
        publicConfig: nextConfig,
        draftMeta: nextMeta,
        baseHash,
      });
      syncWorkspace(response, "success", { resetBase: false });
      return true;
    } catch (error) {
      onError(error);
      return false;
    } finally {
      setBusyAction("");
    }
  }

  function setSectionSaveError(path: string, message: string) {
    setSectionSaveErrors((current) => ({ ...current, [path]: message }));
  }

  function clearSectionSaveError(path: string) {
    setSectionSaveErrors((current) => {
      if (!(path in current)) {
        return current;
      }
      const next = { ...current };
      delete next[path];
      return next;
    });
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
      await openConfigEnvironment();
      setNotice({ tone: "success", text: copy.openEnvironmentOpened });
    } catch (error) {
      markError(error);
    } finally {
      setBusyAction("");
    }
  }

  /**
   * 把各分区编辑态草稿折叠进整份草稿（非法草稿分区跳过并标记 allValid=false）。
   * 供全局「保存到外部配置」使用：分区草稿在显式保存前只存在于分区 UI 状态。
   */
  function foldPendingSectionDrafts(baseShape: PublicConfigShape): { config: PublicConfigShape; allValid: boolean } {
    let next = clonePublicConfig(baseShape);
    let allValid = true;
    const metaAt = (path: string) => editorMeta[path];
    for (const section of editorSections) {
      const sectionState = sectionUiState[section.id];
      if (!sectionState?.editing || sectionState.draftValue === undefined) {
        continue;
      }
      const resolution = resolveDraftSubtreeForSave({ draft: sectionState.draftValue, path: section.path, metaAt });
      if (!resolution.ok) {
        allValid = false;
        continue;
      }
      next = setValueAtConfigPath(next, section.path, resolution.value);
    }
    return { config: next, allValid };
  }

  async function handleApply(
    pendingLabel: string = copy.applying,
    draftOverride?: ConfigApplyDraftOverride,
  ): Promise<boolean> {
    setBusyAction(pendingLabel);
    try {
      const baseline = editBaselineRef.current;
      const applyBaseConfig = baseline.baseConfig ?? baseConfig;
      const applyBaseHash = baseline.baseHash || baseHash;
      if (!applyBaseHash) {
        throw new Error(copy.loadFailed);
      }

      // 有分区草稿待保存时，把折叠后的草稿作为 apply 主体（同一保存+apply 管线，
      // baseHash 乐观并发与过期降级重试保持不变）。
      let effectiveOverride = draftOverride;
      let foldedSectionDrafts = false;
      if (!effectiveOverride && pendingConfigDraftCount > 0) {
        const folded = foldPendingSectionDrafts(requireDraft());
        if (!folded.allValid) {
          throw new Error(copy.saveBlockedInvalid);
        }
        effectiveOverride = {
          publicConfig: folded.config,
          draftMeta,
          baseHash: applyBaseHash,
        };
        foldedSectionDrafts = true;
      }

      const payload = buildConfigApplyRequestPayload({
        draftOverride: effectiveOverride,
        draftConfig,
        draftMeta,
        applyBaseHash,
        applyBaseConfig,
        editorText: jsonText,
        hasEditorChanges,
        editorSections: workspace?.editorSections ?? [],
        loadFailedMessage: copy.loadFailed,
      });

      let response: ConfigWorkspace;
      try {
        response = await applyConfigWorkspace(payload);
      } catch (error) {
        // Multi-pin draft loops can desync client baseConfig/baseHash. Retry once without
        // baseConfig so the server uses on-disk baseline + this draft body.
        if (!isConfigBaselineStaleErrorMessage(readableErrorMessage(error)) || payload.baseConfig == null) {
          throw error;
        }
        response = await applyConfigWorkspace({
          publicConfig: payload.publicConfig,
          draftMeta: payload.draftMeta,
          baseHash: payload.baseHash,
          baseConfig: null,
        });
      }
      syncWorkspace(response, "success");
      if (foldedSectionDrafts) {
        // 保存成功后清空所有分区编辑态（草稿已提交，徽标清除）。
        setSectionUiState((current) =>
          Object.fromEntries(
            Object.entries(current).map(([sectionId, sectionState]) => [
              sectionId,
              { ...sectionState, editing: false, draftValue: undefined },
            ]),
          ),
        );
      }
      publishConfigDraftPresence(false);
      await invalidateWorkbenchQueries(payload.publicConfig);
      return true;
    } catch (error) {
      markError(error);
      return false;
    } finally {
      setBusyAction("");
    }
  }

  async function handleSaveAndLeave() {
    if (leaveBlocker.state !== "blocked" || !canApplyConfigWorkspace) {
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
    clearSectionSaveError(path);
    let updated: PublicConfigShape;
    try {
      updated = setValueAtConfigPath(requireDraft(), path, nextValue);
    } catch (error) {
      // 分区级失败：行内呈现，不进全局 notice。
      setSectionSaveError(path, readableErrorMessage(error));
      return false;
    }
    const previewed = await previewDraft(updated, draftMeta, copy.sectionSavePending, (error) => {
      setSectionSaveError(path, readableErrorMessage(error));
    });
    if (!previewed) return false;
    if (shouldImmediateApplyConfigPath(path)) {
      return persistImmediateDraft(copy.applying);
    }
    return true;
  }

  function clearImmediateStatusTimer(path: string) {
    const timer = immediateStatusTimersRef.current[path];
    if (timer) {
      window.clearTimeout(timer);
      delete immediateStatusTimersRef.current[path];
    }
  }

  /**
   * 即时类字段（boolean/select）行内变更：走「保存分区草稿 previewConfigDraft +
   * 自动 apply」同一管线（复用 baseHash 乐观并发与过期降级重试）。
   * 行徽标：等待中 → 已生效（短暂驻留后清除）/ 未生效（失败不静默，notice 走 toast）。
   */
  async function handleImmediateFieldChange(path: string, nextValue: unknown) {
    if (structuredActionsDisabled) {
      return;
    }
    if (isUiLanguageFieldPath(path)) {
      // ui.language 单一写入方：语言只走专用端点（handleUiLanguageChange），
      // 任何流入通用管线的调用在此拒绝（配套后端 apply 守卫保留存量语言）。
      return;
    }
    clearImmediateStatusTimer(path);
    setImmediateFieldStatus((current) => ({ ...current, [path]: "waiting" }));
    try {
      const updated = setValueAtConfigPath(requireDraft(), path, nextValue);
      const previewed = await previewDraft(updated, draftMeta, copy.applying);
      if (!previewed) {
        setImmediateFieldStatus((current) => ({ ...current, [path]: "failed" }));
        return;
      }
      const applied = await persistImmediateDraft(copy.applying);
      if (!applied) {
        setImmediateFieldStatus((current) => ({ ...current, [path]: "failed" }));
        return;
      }
      setImmediateFieldStatus((current) => ({ ...current, [path]: "applied" }));
      immediateStatusTimersRef.current[path] = window.setTimeout(() => {
        setImmediateFieldStatus((current) => {
          if (current[path] !== "applied") {
            return current;
          }
          const next = { ...current };
          delete next[path];
          return next;
        });
      }, IMMEDIATE_APPLIED_BADGE_HOLD_MS);
    } catch {
      setImmediateFieldStatus((current) => ({ ...current, [path]: "failed" }));
    }
  }

  /**
   * ui.language 专用切换（单一写入方，见 configApplyModel.UI_LANGUAGE_FIELD_PATH）：
   * 改走 PUT /api/config/language（updateConfigLanguage）即改即生效，
   * 不经 preview + 整份配置 apply 管线。成功后失效 configPublic 与配置
   * workspace/draft 查询（AppShell 顶栏 useShellI18n/useAppI18n 随之重取），
   * 再回读工作区对齐本路由基线，设置页自身文案不重载完成切换；
   * 行徽标复用 immediateFieldStatus 的 waiting/applied/failed 生命周期。
   */
  async function handleUiLanguageChange(next: ConfigLanguage) {
    if (structuredActionsDisabled) {
      return;
    }
    const path = UI_LANGUAGE_FIELD_PATH;
    clearImmediateStatusTimer(path);
    setImmediateFieldStatus((current) => ({ ...current, [path]: "waiting" }));
    setBusyAction(copy.applying);
    try {
      await updateConfigLanguage(next);
      // configPublic 供 AppShell 级 i18n 消费；configWorkspace 是本路由的
      // 工作区/draft 读模型（refetchType none：下方显式 refetch 一次拿全）。
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.configPublic() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.configWorkspace(), refetchType: "none" }),
      ]);
      const fresh = await workspaceQuery.refetch();
      if (fresh.data) {
        syncWorkspace(fresh.data);
      }
      setImmediateFieldStatus((current) => ({ ...current, [path]: "applied" }));
      immediateStatusTimersRef.current[path] = window.setTimeout(() => {
        setImmediateFieldStatus((current) => {
          if (current[path] !== "applied") {
            return current;
          }
          const nextStatus = { ...current };
          delete nextStatus[path];
          return nextStatus;
        });
      }, IMMEDIATE_APPLIED_BADGE_HOLD_MS);
    } catch (error) {
      markError(error);
      setImmediateFieldStatus((current) => ({ ...current, [path]: "failed" }));
    } finally {
      setBusyAction("");
    }
  }

  // 失败徽标的自动清理：该字段草稿值回到基线值（例如用户改回原值）时清除。
  useEffect(() => {
    setImmediateFieldStatus((current) => {
      let changed = false;
      const next: Record<string, ImmediateFieldStatus> = {};
      for (const [path, status] of Object.entries(current)) {
        if (status === "failed" && configValuesEqual(getConfigValueAtPath(draftConfig, path), getConfigValueAtPath(baseConfig, path))) {
          changed = true;
          continue;
        }
        next[path] = status;
      }
      return changed ? next : current;
    });
  }, [draftConfig, baseConfig]);

  // 卸载时清理「已生效」徽标的驻留定时器。
  useEffect(() => {
    const timers = immediateStatusTimersRef.current;
    return () => {
      Object.values(timers).forEach((timer) => window.clearTimeout(timer));
    };
  }, []);

  async function handleAvatarImageUpload(file: File): Promise<AvatarImageUploadResponse | null> {
    setBusyAction(copy.avatarImageUploading);
    try {
      return await uploadConfigAvatarImage({
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
      return await uploadConfigThemeBackgroundImage({
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


  function sectionTitle(sectionId: string, fallback: string) {
    return sectionMap.get(sectionId)?.title ?? fallback;
  }

  function intakeLabel(mode: string) {
    return mode === "auto" ? copy.intakeAuto : copy.intakeManual;
  }

  if (!draftConfig && workspaceQuery.isLoading) {
    return (
      <div className={styles.page} data-vui-recipe="config-settings-workbench">
        <ConfigWorkspacePlaceholderPanel title={copy.loading} />
      </div>
    );
  }

  if (!draftConfig || !workspace) {
    return (
      <div className={styles.page} data-vui-recipe="config-settings-workbench">
        <ConfigWorkspacePlaceholderPanel
          title={copy.loadFailed}
          subtitle={workspaceQuery.error instanceof Error ? workspaceQuery.error.message : ""}
          tone="error"
        />
      </div>
    );
  }

  return (
    <div
      className={styles.page}
      data-vui-recipe="config-settings-workbench"
      data-vui-layout-id={CONFIG_SETTINGS_LAYOUT_ID}
      data-vui-domain-recipe="config-settings"
    >
      <VDialog
        open={leaveGuardOpen}
        onOpenChange={(nextOpen) => {
          if (!nextOpen && !busyAction) {
            handleCancelLeave();
          }
        }}
        title={copy.leaveGuardTitle}
        description={copy.leaveGuardBody}
        size="md"
        contentClassName={styles.leaveGuardPanel}
        aria-label={copy.leaveGuardTitle}
        hideClose={Boolean(busyAction)}
        footer={(
          <>
            <VButton
              type="button"
              variant="primary"
              className={styles.primaryButton}
              isDisabled={!canApplyConfigWorkspace || Boolean(busyAction)}
              onClick={() => {
                void handleSaveAndLeave();
              }}
              icon={<Save size={14} />}
            >
              {leaveGuardSaveLabel}
            </VButton>
            <VButton type="button" variant="danger" className={styles.dangerButton} isDisabled={Boolean(busyAction)} onClick={handleDiscardAndLeave}>
              {copy.leaveGuardDiscard}
            </VButton>
            <VButton type="button" className={styles.actionButton} isDisabled={Boolean(busyAction)} onClick={handleCancelLeave}>
              {copy.leaveGuardCancel}
            </VButton>
          </>
        )}
      >
        <p className={styles.helperText}>{sidebarApplyHint}</p>
      </VDialog>
      <VConfirmDialog
        open={Boolean(deleteProviderRequest)}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) handleCancelDeleteProvider();
        }}
        tone="danger"
        title={copy.confirmTitle}
        description={deleteProviderRequest
          ? formatConfigCopy(copy.actionDeleteProviderConfirm, { id: deleteProviderRequest.providerId })
          : ""}
        confirmLabel={copy.confirmAction}
        cancelLabel={copy.cancel}
        confirmPending={Boolean(busyAction)}
        onConfirm={() => {
          void handleConfirmDeleteProvider();
        }}
      />
      <VConfirmDialog
        open={Boolean(migrationApplyRequest)}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) handleCancelApplyMigration();
        }}
        tone="danger"
        title={copy.confirmTitle}
        description={migrationApplyRequest ? <span className="whitespace-pre-line">{migrationApplyRequest.message}</span> : ""}
        confirmLabel={copy.migrationApplyAction}
        cancelLabel={copy.cancel}
        confirmPending={Boolean(busyAction)}
        onConfirm={() => {
          void handleConfirmApplyMigration();
        }}
      />
      <VSplitWorkspace
        className={styles.settingsSplit}
        data-vui-region="config-settings-split"
        resize={{
          layoutId: CONFIG_SETTINGS_LAYOUT_ID,
          sidebar: CONFIG_SETTINGS_SIDEBAR_RESIZE,
          collapse: {
            sidebar: { separatorLabel: copy.navResizeSeparator, collapseLabel: copy.navCollapse, expandLabel: copy.navExpand },
          },
        }}
        sidebar={(
          <ConfigSettingsSidebar
            language={currentLanguage}
            title={copy.pageTitle}
            subtitle={copy.subtitle}
            subtitleHint={copy.subtitleHint}
            statusLabel={hasPendingApply ? copy.statusUnsaved : copy.statusSaved}
            groups={settingsGroups}
            activeGroupId={showingSettingsIndex && !requestedSectionId ? "" : activeGroup?.id ?? ""}
            onShowAll={() => showSettingsIndex()}
            onSelectGroup={handleSelectGroup}
            onNavigate={handleNavigateSettings}
            searchDocuments={settingsSearchDocuments}
            headerAction={returnToPath ? (
              <VRouteLinkButton
                to={returnToPath}
                className={styles.returnButton}
                icon={<ChevronRight size={14} />}
              >
                {returnToLabel}
              </VRouteLinkButton>
            ) : undefined}
          />
        )}
        main={(
      <VSettingsFormPage
        ariaLabel={activeGroup?.title ?? copy.pageTitle}
        className={styles.content}
        data-vui-region="config-settings-main"
        headerClassName={styles.configHeader}
        bodyClassName="!gap-0 !overflow-hidden !content-stretch"
        title={showingSettingsIndex && !requestedSectionId ? copy.pageTitle : activeGroup?.title ?? copy.pageTitle}
        actions={
          <div className={styles.configStatusActions}>
            {isSectionVisible("models") && workspace.schemaVersion === 2 ? (
                <VActionGroup ariaLabel={copy.modelsActionsAria}>
                  <VButton
                    title={copy.advancedSettingsHint}
                    className={styles.providerModeButton}
                    aria-pressed={providerShowMore}
                    variant={providerShowMore ? "primary" : "ghost"}
                    onPress={() => { setProviderConnecting(false); setProviderShowMore((open) => !open); }}
                  >
                    {providerShowMore ? copy.collapseAdvancedSettings : copy.advancedSettings}
                  </VButton>
                </VActionGroup>
            ) : null}
            <VButton
              type="button"
              className={styles.actionButton}
              isDisabled={Boolean(busyAction)}
              onClick={() => {
                void reloadWorkspace();
              }}
 icon={<RotateCcw size={14} />}>
                {copy.refresh}
              </VButton>
            {pendingConfigDraftCount > 0 ? (
              <VChip
                tone={hasInvalidConfigDraft ? "danger" : "warning"}
                data-testid="config-pending-save-count"
                title={hasInvalidConfigDraft ? copy.saveBlockedInvalid : undefined}
              >
                {pendingConfigDraftCount}{copy.settingsPendingCountUnit}
              </VChip>
            ) : null}
            <VButton
              type="button"
              variant="primary"
              className={styles.primaryButton}
              isDisabled={!canApplyConfigWorkspace}
              title={!canApplyConfigWorkspace && hasInvalidConfigDraft ? copy.saveBlockedInvalid : undefined}
              onClick={() => {
                void handleApply();
              }}
 icon={<Save size={14} />}>
                {saveButtonLabel}
              </VButton>
          </div>
        }
        toolbar={isSectionVisible("overview") || (!showingSettingsIndex && !requestedFocusSectionId && (activeGroup?.pages.length ?? 0) > 1) ? (
          <div className={styles.configToolbar}>
            {isSectionVisible("overview") ? <VStatusStrip
              className={styles.configStatusMeta}
              items={[
                {
                  label: copy.configStatus,
                  value: hasPendingApply ? copy.unsavedDraft : copy.syncedDraft,
                  tone: hasPendingApply ? "warning" : "success",
                },
                { label: copy.settingsNextStep, value: sidebarNextStepLabel, tone: "info" },
                {
                  label: copy.configPath,
                  value: (
                    <span className={styles.configStatusPath} title={workspace.configPath}>
                      {workspace.configPath}
                    </span>
                  ),
                },
              ]}
            /> : null}
            {!showingSettingsIndex && !requestedFocusSectionId ? <ConfigSettingsPageTabs
              language={currentLanguage}
              group={activeGroup}
              activePageId={activePage?.id ?? ""}
              onSelectPage={handleSelectPage}
            /> : null}
          </div>
        ) : undefined}
      >
        <div ref={contentViewportRef} className={styles.pageViewport} data-vui-region="config-settings-body">

        {showingSettingsIndex ? <ConfigSettingsIndex
          showUsage={!requestedSectionId}
          groups={requestedSectionId ? settingsGroups.filter((group) => group.id === activeGroup?.id) : settingsGroups}
          sections={workspaceSections} language={currentLanguage} onNavigate={handleNavigateSettings}
        /> : null}

        {!showingSettingsIndex && activeGroup?.id === "avatar-pet"
          && (!requestedFocusSectionId || requestedFocusSectionId === "pet") ? (
          <VSettingsGroupCard>
            <ConfigDesktopPetSettings language={currentLanguage} />
          </VSettingsGroupCard>
        ) : null}

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
          <ConfigOverviewPanel
            copy={copy}
            eyebrow={sectionTitle("overview", copy.sourceTitle)}
            workspace={workspace}
          />
        ) : null}

        <Suspense
          fallback={
            <ConfigWorkspacePlaceholderPanel
              title={copy.loading}
            />
          }
        >

        {isSectionVisible("shell") ? (
          <ConfigRuntimePanel
            copy={copy}
            eyebrow={sectionTitle("shell", copy.runtimeTitle)}
            currentIntakeMode={getString(asRecord(draftConfig.evolution).intake_mode)}
            structuredActionsDisabled={structuredActionsDisabled}
            intakeLabel={intakeLabel}
            onIntakeModeChange={(mode) => {
              void updateSimpleDraft((next) => {
                const evolution = asRecord(next.evolution);
                evolution.intake_mode = mode;
                next.evolution = evolution;
              });
            }}
          />
        ) : null}

        {isSectionVisible("models") ? (
          <div className={styles.providerModelsLayout}>
            {workspace.schemaVersion === 2 ? (
              <>

                {providerConnecting ? (
                  <>
                    <VButton
                      className={styles.providerModeButton}
                      variant="ghost"
                      onPress={() => setProviderConnecting(false)}
                    >
                      {copy.backToConfiguredProviders}
                    </VButton>
                    <ConfigQuickSetupPanel
                      copy={copy}
                      state={providerQuickSetupState}
                      templates={providerPresetOptions}
                      credentialValue={providerQuickCredential}
                      disabled={structuredActionsDisabled || Boolean(busyAction)}
                      onConfigureAgent={() => void navigate("/agents")}
                      onCredentialChange={setProviderQuickCredential}
                      onProviderChange={(provider) => {
                        if (provider.templateId !== providerQuickSetupState.provider.templateId || provider.authKind !== providerQuickSetupState.provider.authKind) setProviderQuickCredential("");
                        dispatchProviderQuickSetup({ type: "set_provider", provider });
                      }}
                      onDetect={(input) => {
                        void handlePrepareProviderQuickSetup(input);
                      }}
                      onModelChange={(modelRef) => dispatchProviderQuickSetup({ type: "select_model", modelRef })}
                      onConfirm={() => {
                        void handleConfirmProviderQuickSetup();
                      }}
                      onReset={() => {
                        setProviderQuickCredential("");
                        dispatchProviderQuickSetup({ type: "reset" });
                      }}
                    />
                  </>
                ) : !providerShowMore ? (
                  <>
                <ConfigProviderRegistryPanel
                  copy={copy}
                  routeEditor={routeEditProviderId ? <>
                {routeEditProviderId && !routePreview ? (
                  <VSurface as="section" padding="compact" tone="row" className={styles.providerRouteEditSurface}>
                    <VSection
                    title={copy.routeEditSectionTitle}
                    actions={(
                      <VActionGroup ariaLabel={copy.routeEditActionsAria}>
                        <VButton
                          isDisabled={Boolean(busyAction)}
                          onPress={() => {
                            setRouteEditProviderId("");
                            setRouteEditProvider({});
                            setRoutePreview(null);
                            setProviderActionFeedback(null);
                          }}
                        >
                          {copy.cancel}
                        </VButton>
                        <VButton
                          variant="primary"
                          isDisabled={Boolean(busyAction) || !getString(routeEditProvider.base_url) || !getString(routeEditProvider.driver)}
                          onPress={() => {
                            void handlePreviewProviderRoute(routeEditProviderId, routeEditProvider);
                          }}
                        >
                          {providerActionFeedback?.kind === "route" && providerActionFeedback.phase === "busy"
                            ? copy.routePreviewPending
                            : copy.routePreviewAction}
                        </VButton>
                      </VActionGroup>
                    )}
                    >
                    <div className={styles.providerRouteEditGrid}>
                      <label className={styles.providerRouteEditField}>
                        <span>{copy.routeFieldBaseUrl}</span>
                        <VInput
                          value={getString(routeEditProvider.base_url)}
                          disabled={Boolean(busyAction)}
                          onChange={(event) => setRouteEditProvider((current) => ({ ...current, base_url: event.target.value }))}
                        />
                      </label>
                      <label className={styles.providerRouteEditField}>
                        <span>{copy.routeFieldDriver}</span>
                        <VStringSelect
                          ariaLabel="Provider route driver"
                          value={getString(routeEditProvider.driver)}
                          isDisabled={Boolean(busyAction)}
                          options={["openai", "anthropic", "gemini"].map((value) => ({ value, label: value }))}
                          onValueChange={(driver) => setRouteEditProvider((current) => ({ ...current, driver }))}
                        />
                      </label>
                      <label className={styles.providerRouteEditField}>
                        <span>{copy.routeFieldProtocol}</span>
                        <VStringSelect
                          ariaLabel="Provider default wire protocol"
                          value={getString(asRecord(routeEditProvider.protocols).default)}
                          isDisabled={Boolean(busyAction)}
                          options={["responses", "chat_completions", "anthropic_messages", "gemini_generate_content"].map((value) => ({ value, label: value }))}
                          onValueChange={(defaultProtocol) => setRouteEditProvider((current) => {
                            const protocols = asRecord(current.protocols);
                            const allowed = Array.isArray(protocols.allowed) ? protocols.allowed.filter((item): item is string => typeof item === "string") : [];
                            return {
                              ...current,
                              protocols: { ...protocols, default: defaultProtocol, allowed: Array.from(new Set([...allowed, defaultProtocol])) },
                            };
                          })}
                        />
                      </label>
                    </div>
                    <p className={styles.providerRouteEditWarning} role="alert">
                      {copy.routeEditWarning}
                    </p>
                    </VSection>
                  </VSurface>
                ) : null}
                {routePreview ? (
                  <VStateSurface
                    tone={routePreview.routeChanged ? "unavailable" : "info"}
                    title={routePreview.routeChanged ? copy.routeConfirmChangedTitle : copy.routeConfirmUnchangedTitle}
                    facts={routePreview.impactedRefs.map((impact, index) => ({
                      key: impact.modelRef ?? String(index),
                      label: impact.modelRef ?? routePreview.modelRefs[index] ?? "modelRef",
                      value: `${impact.liveReferenceCount ?? 0}${copy.routeReferenceCountUnit}`,
                    }))}
                    actions={(
                      <VActionGroup ariaLabel={copy.routeConfirmActionsAria}>
                        <VButton onPress={() => {
                          setRoutePreview(null);
                          setProviderActionFeedback(null);
                        }}>{copy.cancel}</VButton>
                        <VButton
                          variant="danger"
                          isDisabled={!routePreview.routeChanged || !routePreview.routePreviewToken || Boolean(busyAction)}
                          onPress={() => {
                            void handleApplyProviderRoutePreview();
                          }}
                        >
                          {providerActionFeedback?.kind === "route" && providerActionFeedback.phase === "busy"
                            ? copy.routeApplyPending
                            : copy.routeConfirmAction}
                        </VButton>
                      </VActionGroup>
                    )}
                  >
                    {copy.routeConfirmBody}
                  </VStateSurface>
                ) : null}
                  </> : undefined}
                  onCancelRoute={() => { setRouteEditProviderId(""); setRouteEditProvider({}); setRoutePreview(null); }}
                  rows={providerRows}
                  selectedProviderId={selectedProviderId}
                  selectedTab={selectedProviderTab}
                  disabled={structuredActionsDisabled || Boolean(busyAction)}
                  activeCredentialProviderId={providerCredentialEditId}
                  credentialValue={providerCredentialValue}
                  activeRouteProviderId={routeEditProviderId}
                  imageCapabilityBusy={busyAction === copy.imageCapabilityCheckPending}
                  actionFeedback={providerActionFeedback}
                  liveReferenceCountByModelRef={liveReferenceCountByModelRef}
                  hasPendingApply={hasPendingApply}
                  canSaveConfig={canSaveConfig}
                  saveBusy={busyAction === copy.applying}
                  onSaveExternal={() => {
                    void handleApply();
                  }}
                  onAddConnection={() => {
                    if (providerQuickSetupState.phase === "success") dispatchProviderQuickSetup({ type: "reset" });
                    setProviderShowMore(false);
                    setProviderConnecting(true);
                  }}
                  onSelectProvider={(providerId) => {
                    setProviderCredentialEditId("");
                    setProviderCredentialValue("");
                    setRouteEditProviderId("");
                    setRouteEditProvider({});
                    setRoutePreview(null);
                    setProviderActionFeedback(null);
                    setSelectedProviderId(providerId);
                  }}
                  onSelectTab={setSelectedProviderTab}
                  onDiscover={(providerId) => {
                    void handleDiscoverProvider(providerId).catch(() => undefined);
                  }}
                  onEditCredential={(providerId) => {
                    setSelectedProviderTab("connection");
                    setProviderCredentialEditId(providerId);
                    setProviderCredentialValue("");
                    setProviderActionFeedback(null);
                  }}
                  onCredentialValueChange={setProviderCredentialValue}
                  onCancelCredential={() => {
                    setProviderCredentialEditId("");
                    setProviderCredentialValue("");
                    setProviderActionFeedback(null);
                  }}
                  onSaveCredential={(providerId) => {
                    void handleUpdateProviderCredential(providerId);
                  }}
                  onSaveContextWindow={(providerId, contextWindow) => {
                    void handleUpdateProviderContextWindow(providerId, contextWindow);
                  }}
                  onEditRoute={(providerId) => {
                    handleBeginProviderRouteEdit(providerId);
                  }}
                  onPin={(providerId, models) => {
                    void handlePinProviderModels(providerId, models).then((pinned) => {
                      if (pinned) {
                        void persistImmediateDraft(copy.applying);
                      }
                    });
                  }}
                  onUnpin={(modelRef) => {
                    void handleUnpinProviderModel(modelRef);
                  }}
                  onTestModel={(modelRef) => {
                    void handleTestProviderModel(modelRef);
                  }}
                  onProbeImageInput={(modelRef) => {
                    void handleCheckModelImageCapabilities([modelRef]);
                  }}
                  onDeleteProvider={(providerId) => {
                    void handleDeleteProvider(providerId);
                  }}
                  onToggleEnabled={(providerId, enabled) => {
                    // Wave 2: draft-only toggle; the save prompt persists it.
                    void handleToggleProviderEnabled(providerId, enabled);
                  }}
                  onUpdateModel={(providerId, modelKey, edits) => {
                    // Wave 3 governance path B: whitelist-gated entry edit,
                    // draft-only until「保存到外部配置」.
                    void handleUpdatePinnedModel(`${providerId}/${modelKey}`, edits);
                  }}
                  modelUpdateBusy={busyAction === copy.actionModelUpdateBusy}
                />
                  </>
                ) : null}
                {providerShowMore ? (
                  <>
                <ConfigProviderWizard
                  copy={copy}
                  state={providerWizardState}
                  templates={providerPresetOptions}
                  disabled={structuredActionsDisabled}
                  busyLabel={busyAction}
                  onChange={dispatchProviderWizard}
                  onSuggestProviderId={handleSuggestProviderId}
                  onCreateProvider={handleCreateProvider}
                  onDiscover={handleDiscoverProvider}
                  onPin={async (providerId, models) => {
                    const pinned = await handlePinProviderModels(providerId, models);
                    if (pinned) {
                      await persistImmediateDraft(copy.applying);
                    }
                  }}
                />
                {workspace.modelAliasUsage.totalLiveReferenceCount > 0 ? <ConfigModelMigrationPanel
                  copy={copy}
                  schemaVersion={2}
                  preview={null}
                  aliasUsageCount={workspace.modelAliasUsage.totalLiveReferenceCount}
                  busy={Boolean(busyAction)}
                  onPreview={() => undefined}
                  onApply={() => undefined}
                /> : null}
                  </>
                ) : null}
              </>
            ) : (
              <ConfigModelMigrationPanel
                copy={copy}
                schemaVersion={1}
                preview={migrationPreview}
                aliasUsageCount={workspace.modelAliasUsage.totalLiveReferenceCount}
                busy={Boolean(busyAction)}
                onPreview={(artifactResolutions) => {
                  void handlePreviewMigration(artifactResolutions);
                }}
                onApply={(previewId, previewBaseHash) => {
                  void handleApplyMigration(previewId, previewBaseHash);
                }}
              />
            )}
            {providerActionError ? <p className={styles.noticeError} role="alert">{providerActionError}</p> : null}
          </div>
        ) : null}

        {!showingSettingsIndex && activePage?.id === "tooling-access" ? (
          <VSurface as="section" className={styles.toolingMetaPanel} padding="compact" tone="row">
            <VStatusStrip
              aria-label={copy.developerModeReadonly}
              items={[
                { label: copy.runtimeProfile, value: workspace.runtimeProfile, tone: "info" },
                { label: copy.defaultMode, value: workspace.defaultMode },
                { label: copy.defaultRoute, value: workspace.defaultRoute },
                { label: copy.intakeMode, value: intakeLabel(asRecord(draftConfig.evolution).intake_mode as string) },
                { label: copy.developerModeReadonly, value: developerModeReadonlyLabel },
              ]}
            />
            <VButton
              type="button"
              className={styles.actionButton}
              isDisabled={Boolean(busyAction)}
              title={copy.openEnvironmentHint}
              onClick={() => {
                void handleOpenEnvironment();
              }}
            >
              {busyAction === copy.openEnvironmentPending ? copy.openEnvironmentPending : copy.openEnvironment}
            </VButton>
          </VSurface>
        ) : null}

        {isSectionVisible("shortcuts") ? (
          <VSection id="config-shortcuts" tabIndex={-1} title={copy.shortcutsTitle}
            className={styles.sectionSurface} headerClassName={styles.sectionHeader}>
            <ConfigShortcutsPanel lang={currentLanguage} copy={copy} />
          </VSection>
        ) : null}

        {isSectionVisible("health-diagnostics") ? (
          <>
            <ConfigFeatureDecisionPanel
              snapshot={workspace.featureDecisions}
              lang={currentLanguage}
            />
            <ConfigHealthDiagnosticsPanel
              diagnostics={healthDiagnosticsQuery.data}
              loading={healthDiagnosticsQuery.isLoading || healthDiagnosticsQuery.isFetching}
              lang={currentLanguage}
              copy={copy}
              onRefresh={() => {
                void healthDiagnosticsQuery.refetch();
              }}
            />
          </>
        ) : null}

        {showingSettingsIndex || (workspace.schemaVersion === 2 && isSectionVisible("models")) ? null : activeEditorSections.map((section) => (
          <Fragment key={section.id}>
            <ConfigSectionEditor
              section={section}
              value={getConfigValueAtPath(draftConfig, section.path)}
              metaMap={editorMeta}
              lang={currentLanguage}
              copy={copy}
              disabled={structuredActionsDisabled}
              uiState={sectionUiState[section.id] ?? defaultSectionUiState(section.id)}
              onUiStateChange={updateSectionUiState}
              onSaveSection={saveConfigSection}
              onImmediateFieldChange={handleImmediateFieldChange}
              onLanguageChange={(next) => {
                void handleUiLanguageChange(next);
              }}
              immediateFieldStatus={immediateFieldStatus}
              onAvatarImageUpload={handleAvatarImageUpload}
              onThemeBackgroundImageUpload={handleThemeBackgroundImageUpload}
              highlightFieldPath={fieldHighlight?.path ?? ""}
              saveError={sectionSaveErrors[section.path] ?? ""}
            />
            {section.id === "ui" ? (
              // 界面字号：--vui-font-base 的本地偏好控制行（不进 config.toml），
              // 渲染在「界面外观」分区卡片之后，VSettingsRow 组卡先例同 ConfigDesktopPetSettings。
              <VSettingsGroupCard testId="config-ui-font-settings">
                <ConfigUiFontSettings copy={copy} />
              </VSettingsGroupCard>
            ) : null}
          </Fragment>
        ))}

        {isSectionVisible("draft") ? (
          <ConfigDraftPanel
            copy={copy}
            eyebrow={sectionTitle("draft", copy.draftTitle)}
            configPath={workspace.configPath}
            rawToml={workspace.rawToml}
            jsonText={jsonText}
            hasEditorChanges={hasEditorChanges}
            canCheckCurrentChanges={canCheckCurrentChanges}
            canRestoreEditorText={canRestoreEditorText}
            onValidateEditorDraft={() => {
              void handleValidateEditorDraft();
            }}
            onRestoreEditorText={restoreEditorText}
            onJsonTextChange={setJsonText}
          />
        ) : null}

        {isSectionVisible("diagnostics") ? (
          <ConfigDiagnosisPanel
            diagnosis={workspace.diagnosis}
            copy={copy}
            repairableProviderIds={providerRows.map((row) => row.providerId)}
            onRepairProvider={handleRepairProviderCredential}
          />
        ) : null}
        </Suspense>
        </div>
      </VSettingsFormPage>
        )}
      />
    </div>
  );
}
