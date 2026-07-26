import "../design/route-css/agents.tailwind.css";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  Database,
  Layers3,
  UserRound,
  Users,
} from "lucide-react";
import { lazy, Suspense, type MouseEvent, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import {
  AgentDelegationPolicy,
  AgentInboxMessage,
  AgentAvatarOptionsPayload,
  AgentAvatarUploadResponse,
  AgentRuntimeEvidence,
  AgentRuntimeEvidenceMatch,
  AgentRunHistory,
  AgentConfigHealthIssue,
  AgentConfigChanges,
  AgentModeBindings,
  AgentPersonaProfile,
  AgentPurgeResponse,
  AgentTaskProfile,
  AgentToolGovernanceRequest,
  AgentConfigReference,
  AgentSupervisionPolicy,
  AgentBoundary,
  AgentConfigWorkspace,
  AgentConfigWorkspaceAgent,
  AgentConfigWorkspaceGroup,
  AgentContextCompressionPolicy,
  AgentLlmBindings,
  AgentLlmSlotDefinition,
  AgentModelChoice,
  MemoryPolicy,
  ToolPolicy,
  ToolBundle,
  ToolRegistryItem,
  ToolRegistryPayload,
} from "../api/types";
import { resolvePollingInterval, usePageVisibility } from "../app/pollingPolicy";
import {
  type AgentDenseColumn,
  type AgentFilterSectionView,
} from "../components/vui/product/agent-management";
import { VButton } from "../components/vui";
import { safeReturnToPath } from "../app/navigationReturn";
import { useShellI18n } from "../i18n/useShellI18n";
import { useAgentConfigDraftMutations } from "./agents/useAgentConfigDraftMutations";
import { useAgentWorkbenchMutations } from "./agents/useAgentWorkbenchMutations";
import { useChatWorkbenchStore } from "../store/chatWorkbenchStore";
import { type AgentActivityTimelineItem } from "./AgentActivityHistoryPanel";
import {
  type AgentBulkConfigApply,
  type AgentBulkConfigDraft,
  type AgentBulkConfigField,
} from "./AgentBulkConfigPanel";
import { type AgentBulkPromptTemplateOption } from "./AgentBulkOperationsPanel";
import { type AgentContextCompressionPolicyDraft } from "./AgentContextCompressionPanel";
import {
  type AgentConfigDraft,
  type AgentCoreConfigLlmSlotView,
} from "./AgentCoreConfigPanel";
import { type AgentResetOptions } from "./AgentDebugResetPanel";
import { type AgentMemoryPolicyDraft } from "./AgentMemoryPolicyPanel";
import { type AgentModeMembershipDraft } from "./AgentModeMembershipPanel";
import { AgentManagementHeaderPanel } from "./AgentManagementHeaderPanel";
import {
  type AgentOverviewFact,
  type AgentOverviewModeMembership,
  type AgentOverviewPanelPolicy,
  type AgentOverviewTerritory,
} from "./AgentOverviewPanel";
import { type AgentPersonaDraft } from "./AgentPersonaProfilePanel";
import { type AgentReferenceItemView, type AgentReferenceRoomView } from "./AgentReferencesPanel";
import {
  AgentSelectedDetailContentPanel,
  type AgentSelectedDetailContentPanelProps,
} from "./AgentSelectedDetailContentPanel";
import { type AgentTaskDraft } from "./AgentTaskProfilePanel";
import { AgentWorkspaceLayoutPanel } from "./AgentWorkspaceLayoutPanel";
import { governanceStatusLabel } from "./agents/agentStatusPresentation";

const AgentEffectiveConfigurationInspectorPanel = lazy(() =>
  import("./AgentEffectiveConfigurationPanel").then((module) => ({
    default: module.AgentEffectiveConfigurationInspectorPanel,
  })),
);

/** U1: create wizard only when open — keep wizard graph out of Agents shell. */
const AgentCreateWizardDialog = lazy(() =>
  import("./agent-create/AgentCreateWizardDialog").then((module) => ({
    default: module.AgentCreateWizardDialog,
  })),
);
import {
  agentCenterMemoryRoute,
  agentCenterModelsRoute,
  agentCenterPromptsRoute,
  agentCenterToolsRoute,
} from "./agentCenterRoutes";
import { agentDisplayInfo } from "./agentDisplay";
import {
  archivedWorkspaceCache,
  bulkPurgeWorkspaceCache,
  bulkUpdatedAgentWorkspaceCache,
  purgedWorkspaceCache,
  updatedAgentWorkspaceCache,
  type AgentBulkActionItem,
  type AgentBulkActionResponse,
  type AgentConfigWorkspaceWithTeamIndexes,
  type AgentTeamIndexGroup,
} from "./agentWorkspaceCache";
import {
  resolveAgentWorkspaceQueryState,
  resolveAgentWorkspaceSource,
} from "./agents/agentWorkspaceQuery";
import {
  agentDialogueModelDisplay,
  agentFunctionalLabel,
  agentFunctionTone,
  agentLabel,
  agentModelChoiceAllowed,
  agentModelLabel,
  agentSearchText,
  avatarInitials,
  buildAgentModelChoices,
  encodeArrayBufferBase64,
  formatTimestamp,
  normalizeText,
  promptTemplateDisplayName,
  promptTemplateOptionLabel,
  timestampValue,
  type ModelProfileChoice,
  type RuntimeFocusEvidenceResult,
} from "./agents/agentRouteListModel";

import {
  agentLlmSlotModelId,
  agentLlmSlots,
  agentMetadataWithReasoningEffort,
  agentModelById,
  agentModelReasoningEffortValues,
  agentModelSupportsReasoningEffort,
  agentReasoningEffortBySlot,
  FALLBACK_AGENT_LLM_SLOTS,
  normalizeAgentLlmBindings,
  normalizeAgentReasoningEffort,
  normalizeAgentReasoningEffortBySlot,
  pruneAgentReasoningEffortBySlot,
  sameAgentLlmBindings,
  sameAgentReasoningEffortBySlot,
  updateAgentLlmSlotBinding,
  updateAgentReasoningEffortBySlot,
  AGENT_REASONING_EFFORT_VALUES,
} from "./agents/agentRouteLlmModel";
import {
  buildActivityTimeline,
  buildLightweightAgentWorkspace,
  compactProjectionRoute,
  filterAgents,
  findRuntimeFocusEvidence,
  LIGHTWEIGHT_AGENT_CONFIG_STORAGE,
  normalizeLightweightAgent,
  referenceLabel,
  referenceRoute,
  selectedAgentFromList,
  uniqueModes,
  workspaceTeamIndexes,
} from "./agents/agentRouteWorkspaceModel";
import {
  agentBoundaryType,
  agentHasTeamReference,
  configChangeSnapshotFromDraft,
  configDraftEqualsDraft,
  contextCompressionDraftEqualsDraft,
  contextCompressionDraftFromAgent,
  contextCompressionPolicyFromDraft,
  DEFAULT_AGENT_CONTEXT_COMPRESSION_DRAFT,
  draftEqualsAgent,
  draftFromAgent,
  expertiseFromDraft,
  hasModelAndPromptConfiguration,
  hasPersonaProfile,
  hasTaskProfile,
  hasToolPolicyConfiguration,
  hasWorkspaceConfiguration,
  isWorkSessionAgent,
  normalizePersonaProfile,
  normalizeTaskProfile,
  normalizeToolPolicyDraftForAgent,
  personaDraftEqualsAgent,
  personaDraftEqualsDraft,
  personaDraftFromAgent,
  personaProfileFromDraft,
  personaProfileSummary,
  requiresPersonaProfile,
  requiresTaskProfile,
  requiresTeamMembership,
  sameStringSet,
  sortedIds,
  taskDraftEqualsAgent,
  taskDraftEqualsDraft,
  taskDraftFromAgent,
  taskProfileFromDraft,
  taskProfileSummary,
  type AgentToolPolicyDraft,
} from "./agents/agentRouteDraftModel";
import {
  agentHasRuntimeSignal,
  buildAgentManagementBrief,
  buildManagementFilterGroups,
  buildVisibleAgentColumns,
  groupAriaLabel,
  groupDescription,
  groupDisplayLabel,
  groupSectionId,
  hasActionableHealthIssue,
  managementFilterMatches,
  normalizeAgentConfigPane,
  type AgentConfigPaneId,
  type AgentFilterGroup,
  type AgentManagementAction,
  type AgentManagementBrief,
  type AgentManagementFilterGroup,
} from "./agents/agentRouteManagementModel";
import {
  buildAgentCapabilityPreview,
  clampNumber,
  defaultMemoryPolicy,
  defaultToolPolicy,
  delegationPolicyDraftEqualsAgent,
  delegationPolicyDraftEqualsDraft,
  delegationPolicyDraftFromAgent,
  draftSyncSourceFromAgent,
  groupPolicyToolsByBundle,
  membershipDraftEqualsDraft,
  membershipDraftEqualsWorkspace,
  membershipDraftFromWorkspace,
  memoryPolicyDraftEqualsAgent,
  memoryPolicyDraftEqualsDraft,
  memoryPolicyDraftFromAgent,
  sharedGroupCandidates,
  supervisionPolicyDraftEqualsAgent,
  supervisionPolicyDraftEqualsDraft,
  supervisionPolicyDraftFromAgent,
  toolCategoryLabel,
  toolGovernanceDraftFromAgent,
  toolPolicyDeltaCount,
  toolPolicyDeltaFromDraft,
  toolPolicyDraftEqualsAgent,
  toolPolicyDraftEqualsDraft,
  toolPolicyDraftFromAgent,
  toolPolicyMode,
  toolPolicyModeLabel,
  toolTierLabel,
  type AgentCapabilityPreview,
  type AgentDelegationPolicyDraft,
  type AgentDraftSyncSource,
  type AgentSupervisionPolicyDraft,
  type AgentToolGovernanceDraft,
  type ToolBundleApplyMode,
  type ToolPermissionGroup,
  type ToolPolicyMode,
} from "./agents/agentRoutePolicyDraftModel";
import {
  agentArchiveProtected,
  agentBulkActionItemNote,
  agentBulkActionSummary,
  agentBulkPurgeCleanupPending,
  agentCenterReturnLabel,
  bulkConfigApplyFields,
  bulkConfigDraftFromAgents,
  bulkConfigFieldReady,
  bulkConfigPatchFromDraft,
  bulkConfigReady,
  bulkConfigValueMixed,
  DEFAULT_BULK_CONFIG_APPLY,
  DEFAULT_BULK_CONFIG_DRAFT,
  metadataFlag,
  metadataString,
  metadataText,
  optimisticArchivedAgent,
  safeAgentCenterReturnTo,
} from "./agents/agentRouteBulkModel";
import {
  agentConfigPanes,
  agentsRouteCopy,
} from "./agents/agentsRouteCopy";

import {
  issueDisplayTitle,
  issueLabel,
  issueNextStep,
  issuePanelLabel,
  issueSummary,
  issueTone,
  modeLabel,
  runtimeEvidenceReasonLabel,
  runtimeNextStep,
  runtimeStatusLabel,
  runtimeStatusTone,
} from "./agents/agentStatusPresentation";
import { createChatWorkspaceCache } from "./chatWorkspaceCache";
import {
  CONFIG_DRAFT_PRESENCE_EVENT,
  CONFIG_DRAFT_PRESENCE_KEY,
  readConfigDraftPresence,
} from "./configDraftPresence";
import styles from "./AgentsRoute.styles";

type FilterId = string;

type AgentModelPromotionResult = {
  status: string;
  modelRef: string;
  source: "pinned" | "discovered";
  agent: AgentConfigWorkspaceAgent;
  operatorConfigHash: string;
  manifestPath: string;
};

type AgentResetSummary = {
  resetDirectSession?: boolean;
  previousDirectSessionId?: unknown;
  replacementDirectSessionId?: unknown;
};

type AgentBulkPromptTemplateResponse = Omit<AgentBulkActionResponse, "success"> & {
  success: AgentConfigWorkspaceAgent[];
  promptTemplateId?: string;
};
type AgentBulkConfigResponse = Omit<AgentBulkActionResponse, "success"> & {
  success: AgentConfigWorkspaceAgent[];
  appliedFields?: string[];
};
export {
  agentSummaryMetricValue,
  resolveAgentWorkspaceQueryState,
  resolveAgentWorkspaceSource,
} from "./agents/agentWorkspaceQuery";

const AGENT_PRIMARY_MODE_OPTIONS = ["chat", "research", "supervised_evolution", "self_evolution", "general"];
const EMPTY_TOOL_BUNDLES: ToolBundle[] = [];
const EMPTY_TOOL_REGISTRY_ITEMS: ToolRegistryItem[] = [];
const EMPTY_AGENT_CONFIG_GROUPS: AgentConfigWorkspaceGroup[] = [];
const DEFAULT_AGENT_RESET_OPTIONS: AgentResetOptions = {
  clearRuntimeState: true,
  resetDirectSession: true,
  resetPersonaProfile: false,
  resetTaskProfile: false,
  resetToolPolicy: false,
  resetMemoryPolicy: false,
  resetRuntimePolicy: false,
};

function stringValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function reconcileResetDirectSession(summary: AgentResetSummary) {
  if (!summary.resetDirectSession) {
    return;
  }
  const previousDirectSessionId = stringValue(summary.previousDirectSessionId);
  const replacementDirectSessionId = stringValue(summary.replacementDirectSessionId);
  if (!previousDirectSessionId && !replacementDirectSessionId) {
    return;
  }
  if (previousDirectSessionId) {
    useChatWorkbenchStore.getState().removeSession(previousDirectSessionId, replacementDirectSessionId || null);
    return;
  }
  useChatWorkbenchStore.getState().resetSessions(replacementDirectSessionId || null);
}

const DEFAULT_SESSION_AGENT_PREFERRED_TOOLS = [
  "grep_search_tool",
  "conversation_log_inspect_tool",
  "get_core_context_tool",
];

export function AgentsRoute() {
  const { lang } = useShellI18n();
  const queryClient = useQueryClient();
  const chatWorkspaceCache = useMemo(() => createChatWorkspaceCache(queryClient), [queryClient]);
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const pageVisible = usePageVisibility();
  const copy = useMemo(() => agentsRouteCopy(lang), [lang]);
  const numberFormatter = useMemo(() => new Intl.NumberFormat(lang === "zh" ? "zh-CN" : "en-US"), [lang]);
  const requestedAgentId = useMemo(() => String(searchParams.get("agent") || "").trim(), [searchParams]);
  const requestedCreate = useMemo(
    () => !requestedAgentId && searchParams.get("create") === "1",
    [requestedAgentId, searchParams],
  );
  const requestedPane = useMemo(() => normalizeAgentConfigPane(searchParams.get("pane")), [searchParams]);
  const returnToPath = useMemo(() => safeAgentCenterReturnTo(searchParams.get("returnTo")), [searchParams]);
  const returnToLabel = useMemo(() => agentCenterReturnLabel(searchParams.get("returnLabel"), lang), [lang, searchParams]);
  const [activeFilter, setActiveFilter] = useState<FilterId>("active");
  const [searchText, setSearchText] = useState("");
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [activePane, setActivePane] = useState<AgentConfigPaneId>("overview");
  const [selectedEffectiveFieldKey, setSelectedEffectiveFieldKey] = useState("");
  const createOpen = requestedCreate;
  const [configDraft, setConfigDraft] = useState<AgentConfigDraft>(() => draftFromAgent(null));
  const [membershipDraft, setMembershipDraft] = useState<AgentModeMembershipDraft>(() => membershipDraftFromWorkspace(undefined, null));
  const [personaDraft, setPersonaDraft] = useState<AgentPersonaDraft>(() => personaDraftFromAgent(null));
  const [taskDraft, setTaskDraft] = useState<AgentTaskDraft>(() => taskDraftFromAgent(null));
  const [toolPolicyDraft, setToolPolicyDraft] = useState<AgentToolPolicyDraft>(() => toolPolicyDraftFromAgent(null));
  const [toolGovernanceDraft, setToolGovernanceDraft] = useState<AgentToolGovernanceDraft>(() => toolGovernanceDraftFromAgent(null));
  const [memoryPolicyDraft, setMemoryPolicyDraft] = useState<AgentMemoryPolicyDraft>(() => memoryPolicyDraftFromAgent(null));
  const [delegationPolicyDraft, setDelegationPolicyDraft] = useState<AgentDelegationPolicyDraft>(() => delegationPolicyDraftFromAgent(null));
  const [supervisionPolicyDraft, setSupervisionPolicyDraft] = useState<AgentSupervisionPolicyDraft>(() => supervisionPolicyDraftFromAgent(null));
  const [resetOptions, setResetOptions] = useState<AgentResetOptions>(DEFAULT_AGENT_RESET_OPTIONS);
  const [resettingAgentIds, setResettingAgentIds] = useState<Set<string>>(() => new Set());
  const [toolSearchText, setToolSearchText] = useState("");
  const [focusedMessageId, setFocusedMessageId] = useState("");
  const [avatarEditorOpen, setAvatarEditorOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(() => (
    typeof window === "undefined" || typeof window.matchMedia !== "function"
      ? true
      : window.matchMedia("(min-width: 1180px)").matches
  ));
  const [notice, setNotice] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [selectedBulkAgentIds, setSelectedBulkAgentIds] = useState<Set<string>>(() => new Set());
  const [bulkSelectionAnchorAgentId, setBulkSelectionAnchorAgentId] = useState("");
  const [bulkPromptTemplateId, setBulkPromptTemplateId] = useState("");
  const [bulkConfigDraft, setBulkConfigDraft] = useState<AgentBulkConfigDraft>(DEFAULT_BULK_CONFIG_DRAFT);
  const [bulkConfigApply, setBulkConfigApply] = useState<AgentBulkConfigApply>(DEFAULT_BULK_CONFIG_APPLY);
  const [bulkAgentPending, setBulkAgentPending] = useState(false);
  const [configDraftPresenceDirty, setConfigDraftPresenceDirty] = useState(() => readConfigDraftPresence());
  const draftSyncSourceRef = useRef<AgentDraftSyncSource | null>(null);
  const appliedRouteTargetRef = useRef("");
  const agentCreateTriggerRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") {
      return;
    }
    const media = window.matchMedia("(min-width: 1180px)");
    const syncInspector = (event: MediaQueryListEvent) => setInspectorOpen(event.matches);
    media.addEventListener("change", syncInspector);
    return () => media.removeEventListener("change", syncInspector);
  }, []);

  useEffect(() => {
    const refreshPresence = () => setConfigDraftPresenceDirty(readConfigDraftPresence());
    const refreshStoragePresence = (event: StorageEvent) => {
      if (!event.key || event.key === CONFIG_DRAFT_PRESENCE_KEY) {
        refreshPresence();
      }
    };
    window.addEventListener("focus", refreshPresence);
    window.addEventListener("storage", refreshStoragePresence);
    window.addEventListener(CONFIG_DRAFT_PRESENCE_EVENT, refreshPresence);
    return () => {
      window.removeEventListener("focus", refreshPresence);
      window.removeEventListener("storage", refreshStoragePresence);
      window.removeEventListener(CONFIG_DRAFT_PRESENCE_EVENT, refreshPresence);
    };
  }, []);

  const fullWorkspaceNeeded = Boolean(activePane === "effective" || activePane === "relations" || activePane === "config" || activePane === "activity" || requestedAgentId);
  const workspaceQuery = useQuery({
    queryKey: queryKeys.agentConfigWorkspace(),
    queryFn: () => fetchJson<AgentConfigWorkspaceWithTeamIndexes>("/api/agents/config-workspace?includeRuntime=false"),
    enabled: fullWorkspaceNeeded,
    staleTime: 10_000,
  });
  const agentSummaryQuery = useQuery({
    queryKey: queryKeys.agentSummary(true),
    queryFn: () => fetchJson<AgentConfigWorkspaceAgent[]>("/api/agents?includeArchived=true&detail=summary"),
    staleTime: 10_000,
  });

  const toolsWorkspaceNeeded = activePane === "config";
  const toolsQuery = useQuery({
    queryKey: queryKeys.tools(),
    queryFn: () => fetchJson<ToolRegistryPayload>("/api/tools"),
    enabled: toolsWorkspaceNeeded,
    refetchInterval: toolsWorkspaceNeeded ? resolvePollingInterval(pageVisible, 15_000) : false,
    refetchIntervalInBackground: false,
  });
  const toolBundles = toolsQuery.data?.toolBundles ?? EMPTY_TOOL_BUNDLES;

  const avatarOptionsQuery = useQuery({
    queryKey: ["agent-avatar-options"],
    queryFn: () => fetchJson<AgentAvatarOptionsPayload>("/api/agents/avatar-options"),
    enabled: avatarEditorOpen,
    staleTime: 30_000,
  });

  const lightweightWorkspace = useMemo(
    () => agentSummaryQuery.data ? buildLightweightAgentWorkspace(agentSummaryQuery.data, agentSummaryQuery.dataUpdatedAt) : undefined,
    [agentSummaryQuery.data, agentSummaryQuery.dataUpdatedAt],
  );
  const workspace = resolveAgentWorkspaceSource({
    summary: lightweightWorkspace,
    full: workspaceQuery.data,
    fullWorkspaceNeeded,
  });
  const workspaceQueryState = resolveAgentWorkspaceQueryState({
    hasSummary: Boolean(lightweightWorkspace),
    hasFull: Boolean(workspaceQuery.data),
    fullWorkspaceNeeded,
    summaryError: agentSummaryQuery.isError,
    fullError: workspaceQuery.isError,
  });
  const hasAgentWorkspace = workspaceQueryState.hasWorkspace;
  const agentWorkspaceInitialLoading = !hasAgentWorkspace && (
    agentSummaryQuery.isPending
    || (fullWorkspaceNeeded && workspaceQuery.isPending)
  );
  const agentWorkspaceInitialError = workspaceQueryState.initialError;
  const agentWorkspaceBackgroundError = workspaceQueryState.backgroundError;
  const agentWorkspaceError = workspaceQueryState.errorOwner === "full"
    ? workspaceQuery.error
    : agentSummaryQuery.error ?? workspaceQuery.error;
  const tools = toolsQuery.data?.tools ?? EMPTY_TOOL_REGISTRY_ITEMS;
  const agentModelChoices = useMemo(
    () => buildAgentModelChoices(workspace?.agentModelChoices ?? []),
    [workspace?.agentModelChoices],
  );
  const llmSlots = useMemo(() => agentLlmSlots(workspace), [workspace?.agentLlmSlots]);
  const groups = workspace?.groups ?? EMPTY_AGENT_CONFIG_GROUPS;
  const teamIndexGroups = useMemo(() => workspaceTeamIndexes(workspace), [workspace]);
  const managementFilterGroups = useMemo(
    () => buildManagementFilterGroups(workspace?.agents ?? [], copy),
    [copy, workspace?.agents],
  );
  const groupedFilters = useMemo(() => {
    const sectionOrder = ["status", "boundary", "team_index"] as const;
    const indexedGroups = [...groups, ...teamIndexGroups];
    const defaultSections = sectionOrder
      .map((section) => ({
        id: section,
        label: copy.filterSections[section],
        groups: indexedGroups.filter((group) => groupSectionId(group) === section),
      }))
      .filter((section) => section.groups.length > 0);
    const managementSection = {
      id: "management",
      label: copy.filterSections.management,
      groups: managementFilterGroups.filter((group) => group.count > 0),
    };
    return [
      managementSection,
      ...defaultSections,
    ].filter((section) => section.groups.length > 0);
  }, [copy, groups, managementFilterGroups, teamIndexGroups]);
  const advancedGroupedFilters = useMemo(() => {
    const sectionOrder = ["source_scope", "mode", "reference"] as const;
    const indexedGroups = [...groups, ...teamIndexGroups];
    return sectionOrder
      .map((section) => ({
        id: section,
        label: copy.filterSections[section],
        groups: indexedGroups.filter((group) => groupSectionId(group) === section),
      }))
      .filter((section) => section.groups.length > 0);
  }, [copy, groups, teamIndexGroups]);
  const activeGroup = groups.find((group) => group.id === activeFilter);
  const activeTeamIndexGroup = teamIndexGroups.find((group) => group.id === activeFilter);
  const activeManagementGroup = managementFilterGroups.find((group) => group.id === activeFilter);
  const activeGroupLabel = activeManagementGroup?.label ?? activeTeamIndexGroup?.label ?? groupDisplayLabel(activeGroup, copy);
  const visibleAgents = useMemo(
    () => filterAgents(workspace, activeFilter, searchText, { managementFilterMatches }),
    [activeFilter, searchText, workspace],
  );
  const visibleAgentColumns = useMemo(
    () => buildVisibleAgentColumns(visibleAgents, copy, teamIndexGroups),
    [copy, teamIndexGroups, visibleAgents],
  );
  const selectedBulkAgents = useMemo(
    () => visibleAgents.filter((agent) => selectedBulkAgentIds.has(agent.agentId)),
    [selectedBulkAgentIds, visibleAgents],
  );
  const selectedBulkAgentKey = selectedBulkAgents.map((agent) => agent.agentId).join("|");
  const bulkConfigMixed = useMemo(() => {
    return {
      dialogueModelId: bulkConfigValueMixed(selectedBulkAgents, (agent) => agentLlmSlotModelId(agent.llmBindings, FALLBACK_AGENT_LLM_SLOTS[0])),
      promptTemplateId: bulkConfigValueMixed(selectedBulkAgents, (agent) => agent.promptTemplateId || ""),
      primaryMode: bulkConfigValueMixed(selectedBulkAgents, (agent) => agent.primaryMode || ""),
      roleKey: bulkConfigValueMixed(selectedBulkAgents, (agent) => agent.roleKey || ""),
    };
  }, [selectedBulkAgentKey]);
  const bulkSelectedAgentOptions = useMemo(
    () => selectedBulkAgents.map((agent) => ({ agentId: agent.agentId, label: agentLabel(agent) })),
    [selectedBulkAgents],
  );
  const bulkModelOptions = useMemo(
    () => agentModelChoices.map((model) => ({ value: model.modelId, label: model.label })),
    [agentModelChoices],
  );
  const bulkPromptTemplateOptions = useMemo<AgentBulkPromptTemplateOption[]>(
    () => (workspace?.promptTemplates ?? []).map((template) => ({
      value: template.promptTemplateId || template.templateId || "",
      label: promptTemplateOptionLabel(template, lang),
    })),
    [lang, workspace?.promptTemplates],
  );
  const bulkPrimaryModeOptions = useMemo(
    () => AGENT_PRIMARY_MODE_OPTIONS.map((mode) => ({ value: mode, label: modeLabel(mode, lang) })),
    [lang],
  );
  const bulkConfigCanSave = selectedBulkAgents.length > 1 && bulkConfigReady(bulkConfigDraft, bulkConfigApply) && !bulkAgentPending;
  const allVisibleAgentsSelected = visibleAgents.length > 0 && selectedBulkAgents.length === visibleAgents.length;
  const visiblePolicyTools = useMemo(() => {
    const query = normalizeText(toolSearchText);
    return tools.filter((tool) => {
      if (!tool.llmVisible && !tool.runtimeActive) {
        return false;
      }
      if (!query) {
        return true;
      }
      return normalizeText([
        tool.name,
        tool.description,
        tool.source,
        tool.status,
        tool.category,
        tool.categoryLabel,
        tool.permissionTier,
        ...(tool.bundleIds ?? []),
        ...(tool.capabilityTags ?? []),
        ...(tool.riskTags ?? []),
      ].join(" ")).includes(query);
    });
  }, [toolSearchText, tools]);
  const visiblePolicyToolGroups = useMemo(
    () => groupPolicyToolsByBundle(visiblePolicyTools, toolBundles, toolPolicyDraft, lang),
    [lang, toolBundles, toolPolicyDraft, visiblePolicyTools],
  );
  const selectedAgent = selectedAgentFromList(visibleAgents, selectedAgentId, workspace?.agents ?? [], activeFilter);
  const effectiveConfigurationFields = useMemo(
    () => selectedAgent?.effectiveConfiguration?.fields ?? [],
    [selectedAgent?.effectiveConfiguration],
  );
  const selectedEffectiveField = effectiveConfigurationFields.find(
    (field) => field.key === selectedEffectiveFieldKey,
  ) ?? effectiveConfigurationFields[0] ?? null;

  useEffect(() => {
    const firstKey = effectiveConfigurationFields[0]?.key ?? "";
    setSelectedEffectiveFieldKey((current) => (
      effectiveConfigurationFields.some((field) => field.key === current) ? current : firstKey
    ));
  }, [effectiveConfigurationFields]);

  const selectedTeamRelations = useMemo(() => {
    if (!selectedAgent) {
      return [];
    }
    const agentsById = new Map((workspace?.agents ?? []).map((agent) => [agent.agentId, agent]));
    return (workspace?.teams ?? [])
      .filter((team) => team.status !== "archived" && team.agentIds.includes(selectedAgent.agentId))
      .map((team) => ({
        teamId: team.teamId,
        name: team.name || team.teamId,
        purpose: team.purpose,
        members: team.agentIds.map((memberId) => {
          const member = agentsById.get(memberId);
          const current = memberId === selectedAgent.agentId;
          return {
            agentId: memberId,
            label: member ? agentLabel(member) : memberId,
            functionLabel: current
              ? (lang === "zh" ? `当前 Agent · ${agentFunctionalLabel(member, lang)}` : `Current agent · ${agentFunctionalLabel(member, lang)}`)
              : agentFunctionalLabel(member, lang),
            current,
          };
        }),
      }));
  }, [lang, selectedAgent?.agentId, workspace?.agents, workspace?.teams]);

  const configChangesQuery = useQuery({
    queryKey: ["agents", "config-changes", selectedAgent?.agentId ?? ""],
    queryFn: () => fetchJson<AgentConfigChanges>(
      `/api/agents/${encodeURIComponent(selectedAgent?.agentId ?? "")}/config-changes`,
    ),
    enabled: Boolean(selectedAgent?.agentId && (activePane === "changes" || activePane === "config")),
    staleTime: 8_000,
  });
  const activeConfigDraftId = configChangesQuery.data?.activeDraft?.draftId ?? "";

  const selectedAgentReturnRoute = selectedAgent?.agentId
    ? `/agents?agent=${encodeURIComponent(selectedAgent.agentId)}&pane=config`
    : "/agents?pane=config";
  const selectedAgentToolConfigRoute = useMemo(
    () => selectedAgent?.agentId
      ? agentCenterToolsRoute({
          agentId: selectedAgent.agentId,
          returnLabel: "agents",
          returnTo: selectedAgentReturnRoute,
        })
      : "/agents/tools",
    [selectedAgent?.agentId, selectedAgentReturnRoute],
  );
  const selectedAgentPromptConfigRoute = useMemo(
    () => selectedAgent?.agentId
      ? agentCenterPromptsRoute({
          agentId: selectedAgent.agentId,
          templateId: configDraft.promptTemplateId || selectedAgent.promptTemplateId,
          focus: "editor",
          returnLabel: "agents",
          returnTo: selectedAgentReturnRoute,
        })
      : "/agents/prompts",
    [configDraft.promptTemplateId, selectedAgent?.agentId, selectedAgent?.promptTemplateId, selectedAgentReturnRoute],
  );
  const selectedAgentModelConfigRoute = useMemo(
    () => selectedAgent?.agentId
      ? agentCenterModelsRoute({
          agentId: selectedAgent.agentId,
          section: "models-profiles",
          returnLabel: "agents",
          returnTo: selectedAgentReturnRoute,
        })
      : "/config?section=models-profiles",
    [selectedAgent?.agentId, selectedAgentReturnRoute],
  );
  const selectedAgentContextConfigRoute = useMemo(
    () => selectedAgent?.agentId
      ? agentCenterModelsRoute({
          agentId: selectedAgent.agentId,
          section: "runtime-context",
          returnLabel: "agents",
          returnTo: selectedAgentReturnRoute,
        })
      : "/config?section=runtime-context",
    [selectedAgent?.agentId, selectedAgentReturnRoute],
  );
  const selectedAgentMemoryConfigRoute = useMemo(
    () => selectedAgent?.agentId
      ? agentCenterMemoryRoute({
          agentId: selectedAgent.agentId,
          view: "agents",
          returnLabel: "agents",
          returnTo: selectedAgentReturnRoute,
        })
      : "/memory/agents",
    [selectedAgent?.agentId, selectedAgentReturnRoute],
  );
  const managementBrief = useMemo(() => buildAgentManagementBrief(selectedAgent, copy, lang), [copy, lang, selectedAgent]);
  const capabilityPreview = useMemo(
    () => buildAgentCapabilityPreview(toolPolicyDraft, visiblePolicyTools, copy),
    [copy, toolPolicyDraft, visiblePolicyTools],
  );
  const memoryGroupOptions = useMemo(() => sharedGroupCandidates(workspace, selectedAgent), [selectedAgent?.agentId, workspace?.generatedAt]);
  const panes = useMemo(() => agentConfigPanes(copy, selectedAgent), [copy, selectedAgent]);
  const agentRunsQuery = useQuery({
    queryKey: queryKeys.agentRuns(selectedAgent?.agentId ?? ""),
    queryFn: () => fetchJson<AgentRunHistory>(`/api/agents/${encodeURIComponent(selectedAgent?.agentId ?? "")}/runs?limit=12`),
    enabled: Boolean(selectedAgent?.agentId && (activePane === "overview" || activePane === "activity")),
    refetchInterval: activePane === "activity" ? resolvePollingInterval(pageVisible, 12_000) : false,
    refetchIntervalInBackground: false,
  });
  const agentMessagesQuery = useQuery({
    queryKey: queryKeys.agentMessages(selectedAgent?.agentId ?? "", "pending"),
    queryFn: () => fetchJson<AgentInboxMessage[]>(`/api/agents/${encodeURIComponent(selectedAgent?.agentId ?? "")}/messages?status=pending&limit=8`),
    enabled: Boolean(selectedAgent?.agentId && (activePane === "overview" || activePane === "activity")),
    refetchInterval: activePane === "activity" ? resolvePollingInterval(pageVisible, 12_000) : false,
    refetchIntervalInBackground: false,
  });
  const selectedAgentInboxPendingCount = selectedAgent?.agentInboxPendingCount ?? agentMessagesQuery.data?.length ?? 0;
  const agentRuntimeEvidenceQuery = useQuery({
    queryKey: queryKeys.agentRuntimeEvidence(selectedAgent?.agentId ?? ""),
    queryFn: () => fetchJson<AgentRuntimeEvidence>(
      `/api/agents/${encodeURIComponent(selectedAgent?.agentId ?? "")}/runtime-evidence?sessionId=${encodeURIComponent(selectedAgent?.directSessionId ?? "")}&limit=5`,
    ),
    enabled: Boolean(selectedAgent?.agentId && (activePane === "overview" || activePane === "activity")),
    refetchInterval: activePane === "activity" ? resolvePollingInterval(pageVisible, 20_000) : false,
    refetchIntervalInBackground: false,
  });
  const activityTimeline = useMemo(
    () => selectedAgent ? buildActivityTimeline(selectedAgent, agentRunsQuery.data, agentMessagesQuery.data, copy, lang, agentRuntimeEvidenceQuery.data) : [],
    [agentMessagesQuery.data, agentRunsQuery.data, agentRuntimeEvidenceQuery.data, copy, lang, selectedAgent],
  );
  const runtimeFocusEvidence = useMemo(
    () => findRuntimeFocusEvidence(selectedAgent, agentRuntimeEvidenceQuery.data),
    [agentRuntimeEvidenceQuery.data, selectedAgent],
  );
  const runtimeFocusSessionId = selectedAgent?.runtimeStatus?.sessionId || selectedAgent?.directSessionId || "";
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.agentSummary(true) });
    if (fullWorkspaceNeeded) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentConfigWorkspace() });
    }
    void chatWorkspaceCache.afterAgentWorkspaceChanged();
  };

  useEffect(() => {
    const routeTargetKey = requestedAgentId ? `${requestedAgentId}:${requestedPane}` : "";
    if (!routeTargetKey) {
      appliedRouteTargetRef.current = "";
      return;
    }
    if (requestedAgentId && !workspaceQuery.data) {
      return;
    }
    if (!workspace || appliedRouteTargetRef.current === routeTargetKey) {
      return;
    }
    const targetAgent = workspace.agents.find((agent) => agent.agentId === requestedAgentId);
    if (!targetAgent) {
      setNotice({
        tone: "error",
        text: lang === "zh" ? "目标 Agent 不存在或已被移除。" : "The requested Agent does not exist or was removed.",
      });
      appliedRouteTargetRef.current = routeTargetKey;
      return;
    }
    setSelectedAgentId(targetAgent.agentId);
    setActivePane(requestedPane);
    setActiveFilter(targetAgent.status === "archived" ? "archived" : "active");
    setSearchText("");
    setSelectedBulkAgentIds(new Set());
    setBulkSelectionAnchorAgentId(targetAgent.agentId);
    appliedRouteTargetRef.current = routeTargetKey;
  }, [lang, requestedAgentId, requestedPane, workspace, workspaceQuery.data]);

  useEffect(() => {
    setBulkConfigDraft(bulkConfigDraftFromAgents(selectedBulkAgents));
    setBulkConfigApply(DEFAULT_BULK_CONFIG_APPLY);
  }, [selectedBulkAgentKey]);

  useEffect(() => {
    const nextSource = draftSyncSourceFromAgent(workspace, selectedAgent);
    const previousSource = draftSyncSourceRef.current;
    const agentChanged = previousSource?.agentId !== nextSource.agentId;

    if (!previousSource || agentChanged) {
      setConfigDraft(nextSource.config);
      setMembershipDraft(nextSource.membership);
      setPersonaDraft(nextSource.persona);
      setTaskDraft(nextSource.task);
      setToolPolicyDraft(nextSource.toolPolicy);
      setToolGovernanceDraft(toolGovernanceDraftFromAgent(selectedAgent));
      setMemoryPolicyDraft(nextSource.memoryPolicy);
      setDelegationPolicyDraft(nextSource.delegationPolicy);
      setSupervisionPolicyDraft(nextSource.supervisionPolicy);
      setToolSearchText("");
      setFocusedMessageId("");
      setAvatarEditorOpen(false);
      setNotice(null);
      draftSyncSourceRef.current = nextSource;
      return;
    }

    setConfigDraft((current) => configDraftEqualsDraft(current, previousSource.config) ? nextSource.config : current);
    setMembershipDraft((current) => membershipDraftEqualsDraft(current, previousSource.membership) ? nextSource.membership : current);
    setPersonaDraft((current) => personaDraftEqualsDraft(current, previousSource.persona) ? nextSource.persona : current);
    setTaskDraft((current) => taskDraftEqualsDraft(current, previousSource.task) ? nextSource.task : current);
    setToolPolicyDraft((current) => toolPolicyDraftEqualsDraft(current, previousSource.toolPolicy) ? nextSource.toolPolicy : current);
    setMemoryPolicyDraft((current) => memoryPolicyDraftEqualsDraft(current, previousSource.memoryPolicy) ? nextSource.memoryPolicy : current);
    setDelegationPolicyDraft((current) =>
      delegationPolicyDraftEqualsDraft(current, previousSource.delegationPolicy) ? nextSource.delegationPolicy : current,
    );
    setSupervisionPolicyDraft((current) =>
      supervisionPolicyDraftEqualsDraft(current, previousSource.supervisionPolicy) ? nextSource.supervisionPolicy : current,
    );
    draftSyncSourceRef.current = nextSource;
  }, [selectedAgent, workspace]);

  useEffect(() => {
    if (requestedAgentId && selectedAgent?.agentId === requestedAgentId) {
      setResetOptions(DEFAULT_AGENT_RESET_OPTIONS);
      return;
    }
    setActivePane("overview");
    setResetOptions(DEFAULT_AGENT_RESET_OPTIONS);
  }, [requestedAgentId, selectedAgent?.agentId]);

  useEffect(() => {
    setSelectedBulkAgentIds((current) => {
      const visibleIds = new Set(visibleAgents.map((agent) => agent.agentId));
      const next = new Set(Array.from(current).filter((agentId) => visibleIds.has(agentId)));
      return next.size === current.size ? current : next;
    });
  }, [visibleAgents]);

  const configDirty = !draftEqualsAgent(configDraft, selectedAgent);
  const membershipDirty = !membershipDraftEqualsWorkspace(membershipDraft, workspace, selectedAgent);
  const personaDirty = !personaDraftEqualsAgent(personaDraft, selectedAgent);
  const taskDirty = !taskDraftEqualsAgent(taskDraft, selectedAgent);
  const toolPolicyDirty = !toolPolicyDraftEqualsAgent(toolPolicyDraft, selectedAgent);
  const memoryPolicyDirty = !memoryPolicyDraftEqualsAgent(memoryPolicyDraft, selectedAgent);
  const runtimePolicyDirty = !delegationPolicyDraftEqualsAgent(delegationPolicyDraft, selectedAgent)
    || !supervisionPolicyDraftEqualsAgent(supervisionPolicyDraft, selectedAgent);
  const toolGovernanceDelta = toolPolicyDeltaFromDraft(toolPolicyDraft, selectedAgent);
  const toolGovernanceDeltaTotal = toolPolicyDeltaCount(toolGovernanceDelta);
  const canSubmitToolGovernance = Boolean(selectedAgent?.agentId && toolGovernanceDeltaTotal > 0);
  const canSaveConfig = Boolean(selectedAgent?.agentId && configDraft.displayName.trim() && configDirty);
  const canSaveMembership = Boolean(selectedAgent?.agentId && membershipDirty);
  const canSavePersona = Boolean(selectedAgent?.agentId && personaDirty);
  const canSaveTask = Boolean(selectedAgent?.agentId && taskDirty);
  const canSaveToolPolicy = Boolean(selectedAgent?.agentId && toolPolicyDirty);
  const canSaveMemoryPolicy = Boolean(selectedAgent?.agentId && memoryPolicyDirty);
  const canSaveRuntimePolicy = Boolean(selectedAgent?.agentId && runtimePolicyDirty);
  const selectedAgentRequiresPersona = requiresPersonaProfile(selectedAgent);
  const selectedAgentRequiresTask = requiresTaskProfile(selectedAgent);
  const selectedAgentRequiresTeamMembership = requiresTeamMembership(selectedAgent);
  const selectedAgentProtected = agentArchiveProtected(selectedAgent);
  const selectedAgentResetPending = Boolean(selectedAgent?.agentId && resettingAgentIds.has(selectedAgent.agentId));
  const canResetAgent = Boolean(selectedAgent?.agentId && selectedAgent.status !== "archived");
  const canArchiveAgent = Boolean(selectedAgent?.agentId && selectedAgent.status !== "archived" && !selectedAgentProtected);
  const canPurgeAgent = Boolean(selectedAgent?.agentId && selectedAgent.status === "archived" && !selectedAgentProtected);
  const contextCompressionCustom = configDraft.contextCompressionPolicy.mode === "custom";
  const contextCompressionEffectivePolicy = selectedAgent?.contextCompressionEffectivePolicy;
  const contextCompressionEffectiveLimit = contextCompressionEffectivePolicy?.compressionTriggerTokenLimit
    ?? contextCompressionEffectivePolicy?.effectiveTokenLimit
    ?? contextCompressionEffectivePolicy?.maxTokenLimit
    ?? Number(configDraft.contextCompressionPolicy.maxTokenLimit || DEFAULT_AGENT_CONTEXT_COMPRESSION_DRAFT.maxTokenLimit);
  const contextCompressionWindowLimit = contextCompressionEffectivePolicy?.modelContextWindowLimit
    ?? contextCompressionEffectivePolicy?.contextWindowLimit
    ?? 0;
  const contextCompressionPolicySource = contextCompressionCustom
    ? copy.contextCompressionSourceCustom
    : copy.contextCompressionSourceGlobal;
  const contextCompressionPolicyLine = `${contextCompressionPolicySource} · ${copy.contextCompressionEffective}: ${numberFormatter.format(
    Math.max(0, Number(contextCompressionEffectiveLimit) || 0),
  )} · ${copy.contextCompressionWindow}: ${numberFormatter.format(Math.max(0, Number(contextCompressionWindowLimit) || 0))}`;
  const toolPolicySource = selectedAgent?.toolPolicySource;
  const toolPolicySourceLine = toolPolicySource
    ? `${toolPolicySource.label} · ${toolPolicySource.allowedToolCount} ${copy.tools}${toolPolicySource.mutatingToolCount ? ` · ${toolPolicySource.mutatingToolCount} ${lang === "zh" ? "个可写/命令工具" : "mutating tools"}` : ""}`
    : copy.toolPolicyPickerHint;
  const coreConfigLlmSlots = useMemo<AgentCoreConfigLlmSlotView[]>(
    () => llmSlots.map((slot) => {
      const selectedModelId = agentLlmSlotModelId(configDraft.llmBindings, slot);
      const selectedModel = agentModelById(workspace?.agentModelChoices ?? [], selectedModelId);
      const reasoningEffortValues = agentModelReasoningEffortValues(selectedModel);
      const reasoningEffortOptions = Array.isArray(selectedModel?.reasoningEffortOptions)
        ? selectedModel.reasoningEffortOptions
        : reasoningEffortValues.map((value) => ({
          value,
          label: value,
          description: "",
        }));
      return {
        slot,
        selectedModelId,
        candidates: workspace?.agentModelChoices ?? [],
        supportsReasoningEffort: agentModelSupportsReasoningEffort(selectedModel),
        reasoningEffort: normalizeAgentReasoningEffort(
          configDraft.reasoningEffortBySlot[slot.slot],
          reasoningEffortValues,
        ),
        reasoningEffortOptions,
      };
    }),
    [configDraft.llmBindings, configDraft.reasoningEffortBySlot, lang, llmSlots, workspace?.agentModelChoices],
  );
  const coreConfigToolPolicyOptions = useMemo(
    () => (workspace?.toolPolicies ?? []).map((policy) => ({
      value: policy.policyId,
      label: `${policy.policyId} · ${policy.allowedToolCount}/${policy.blockedToolCount}`,
    })),
    [workspace?.toolPolicies],
  );
  const coreConfigMemoryPolicyOptions = useMemo(
    () => (workspace?.memoryPolicies ?? []).map((policy) => ({
      value: policy.policyId,
      label: `${policy.policyId} · ${policy.privateMemoryRoot || "-"}`,
    })),
    [workspace?.memoryPolicies],
  );
  const coreConfigToolPolicyTooltip = [
    toolPolicySourceLine,
    toolPolicySource?.description || copy.toolPolicyPickerHint,
  ].filter(Boolean).join("\n");

  function setCreateWizardOpen(open: boolean) {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      if (open) {
        next.set("create", "1");
      } else {
        next.delete("create");
      }
      return next;
    }, { replace: true });
  }

  const {
    saveAgentConfigDraftMutation,
    discardAgentConfigDraftMutation,
    updateAgentMutation,
    promoteAgentModelMutation,
  } = useAgentConfigDraftMutations({
    lang,
    setNotice,
    chatWorkspaceCache,
    setConfigDraft,
    draftSyncSourceRef,
    getWorkspace: () => workspace,
    draftFromAgent,
    draftSyncSourceFromAgent,
    normalizeAgentLlmBindings,
    contextCompressionPolicyFromDraft,
    agentMetadataWithReasoningEffort,
    agentLabel,
    updatedAgentWorkspaceCache,
  });

  const {
    updatePersonaMutation,
    updateTaskMutation,
    archiveAgentMutation,
    purgeAgentMutation,
    resetAgentMutation,
    updateAvatarMutation,
    uploadAvatarMutation,
    updateMembershipMutation,
    updateToolPolicyMutation,
    createToolGovernanceMutation,
    resolveToolGovernanceMutation,
    updateMemoryPolicyMutation,
    updateRuntimePolicyMutation,
    consumeMessageMutation,
    consumeAllMessagesMutation,
  } = useAgentWorkbenchMutations({
    lang,
    copy,
    setNotice,
    chatWorkspaceCache,
    setPersonaDraft,
    setTaskDraft,
    draftSyncSourceRef,
    setSelectedAgentId,
    setActivePane,
    setResettingAgentIds,
    setResetOptions,
    setMembershipDraft,
    setToolGovernanceDraft,
    getWorkspace: () => workspace,
    getSelectedAgentId: () => selectedAgentId,
    getActivePane: () => activePane,
    getSelectedAgent: () => selectedAgent,
    reconcileResetDirectSession,
    encodeArrayBufferBase64,
    updatedAgentWorkspaceCache,
    archivedWorkspaceCache,
    purgedWorkspaceCache,
    optimisticArchivedAgent,
    personaProfileFromDraft,
    personaDraftFromAgent,
    taskProfileFromDraft,
    taskDraftFromAgent,
    draftSyncSourceFromAgent,
    agentLabel,
    defaultToolPolicy,
    defaultMemoryPolicy,
    sortedIds,
    toolPolicyDeltaFromDraft,
    toolGovernanceDraftFromAgent,
    governanceStatusLabel,
    DEFAULT_AGENT_RESET_OPTIONS,
    stringValue,
  });

  const selectedAgentAvatarUpdatePending = updateAvatarMutation.isPending && updateAvatarMutation.variables?.agentId === selectedAgent?.agentId;
  const selectedAgentAvatarUploadPending = uploadAvatarMutation.isPending && uploadAvatarMutation.variables?.agentId === selectedAgent?.agentId;
  const selectedAgentConsumeAllPending = consumeAllMessagesMutation.isPending && consumeAllMessagesMutation.variables?.agentId === selectedAgent?.agentId;
  const selectedAgentConfigPending = updateAgentMutation.isPending && updateAgentMutation.variables?.agentId === selectedAgent?.agentId;
  const selectedAgentConfigDraftSavePending = saveAgentConfigDraftMutation.isPending && saveAgentConfigDraftMutation.variables?.agentId === selectedAgent?.agentId;
  const selectedAgentConfigDraftDiscardPending = discardAgentConfigDraftMutation.isPending && discardAgentConfigDraftMutation.variables?.agentId === selectedAgent?.agentId;
  const selectedAgentPersonaPending = updatePersonaMutation.isPending && updatePersonaMutation.variables?.agentId === selectedAgent?.agentId;
  const selectedAgentTaskPending = updateTaskMutation.isPending && updateTaskMutation.variables?.agentId === selectedAgent?.agentId;
  const selectedAgentMembershipPending = updateMembershipMutation.isPending && updateMembershipMutation.variables?.agentId === selectedAgent?.agentId;
  const selectedAgentToolPolicyPending = updateToolPolicyMutation.isPending && updateToolPolicyMutation.variables?.agentId === selectedAgent?.agentId;
  const selectedAgentMemoryPolicyPending = updateMemoryPolicyMutation.isPending && updateMemoryPolicyMutation.variables?.agentId === selectedAgent?.agentId;
  const selectedAgentRuntimePolicyPending = updateRuntimePolicyMutation.isPending && updateRuntimePolicyMutation.variables?.agentId === selectedAgent?.agentId;
  const selectedAgentArchivePending = archiveAgentMutation.isPending && archiveAgentMutation.variables?.agentId === selectedAgent?.agentId;
  const selectedAgentPurgePending = purgeAgentMutation.isPending && purgeAgentMutation.variables?.agentId === selectedAgent?.agentId;
  const selectedAgentToolGovernanceCreatePending =
    createToolGovernanceMutation.isPending && createToolGovernanceMutation.variables?.agentId === selectedAgent?.agentId;

  const updateDraft = (patch: Partial<AgentConfigDraft>) => {
    setConfigDraft((current) => ({ ...current, ...patch }));
  };

  const updateContextCompressionDraft = (patch: Partial<AgentContextCompressionPolicyDraft>) => {
    setConfigDraft((current) => ({
      ...current,
      contextCompressionPolicy: { ...current.contextCompressionPolicy, ...patch },
    }));
  };

  const updateMembershipDraft = (patch: Partial<AgentModeMembershipDraft>) => {
    setMembershipDraft((current) => ({ ...current, ...patch }));
  };

  const updatePersonaDraft = (patch: Partial<AgentPersonaDraft>) => {
    setPersonaDraft((current) => ({ ...current, ...patch }));
  };

  const updateTaskDraft = (patch: Partial<AgentTaskDraft>) => {
    setTaskDraft((current) => ({ ...current, ...patch }));
  };

  const updateToolPolicyMode = (toolName: string, mode: Exclude<ToolPolicyMode, "excluded">) => {
    setToolPolicyDraft((current) => {
      const allowed = new Set(current.allowedTools);
      const preferred = new Set(current.preferredTools);
      const blocked = new Set(current.blockedTools);
      allowed.delete(toolName);
      preferred.delete(toolName);
      blocked.delete(toolName);
      if (mode === "allowed") {
        allowed.add(toolName);
      }
      if (mode === "blocked") {
        blocked.add(toolName);
      }
      return normalizeToolPolicyDraftForAgent({
        ...current,
        allowedTools: sortedIds(Array.from(allowed)),
        preferredTools: sortedIds(Array.from(preferred)),
        blockedTools: sortedIds(Array.from(blocked)),
      }, selectedAgent);
    });
  };

  const applyToolBundle = (bundle: ToolBundle, mode: ToolBundleApplyMode) => {
    setToolPolicyDraft((current) => {
      const bundleTools = sortedIds(bundle.toolNames ?? []);
      const bundlePreferred = sortedIds((bundle.preferredToolNames ?? []).filter((tool) => bundleTools.includes(tool)));
      if (mode === "replace") {
        return normalizeToolPolicyDraftForAgent({
          ...current,
          allowedTools: bundleTools,
          preferredTools: bundlePreferred,
          blockedTools: [],
        }, selectedAgent);
      }
      const allowed = new Set(current.allowedTools);
      const preferred = new Set(current.preferredTools);
      const blocked = new Set(current.blockedTools);
      for (const tool of bundleTools) {
        if (!blocked.has(tool)) {
          allowed.add(tool);
        }
      }
      for (const tool of bundlePreferred) {
        if (!blocked.has(tool)) {
          preferred.add(tool);
        }
      }
      return normalizeToolPolicyDraftForAgent({
        ...current,
        allowedTools: sortedIds(Array.from(allowed)),
        preferredTools: sortedIds(Array.from(preferred).filter((tool) => allowed.has(tool))),
        blockedTools: sortedIds(Array.from(blocked)),
      }, selectedAgent);
    });
  };

  const updateToolGovernanceDraft = (patch: Partial<AgentToolGovernanceDraft>) => {
    setToolGovernanceDraft((current) => ({ ...current, ...patch }));
  };

  const toggleToolPolicyScope = (field: "readScopes" | "writeScopes", scope: string, selected: boolean) => {
    setToolPolicyDraft((current) => {
      const scopes = new Set(current[field]);
      if (selected) {
        scopes.add(scope);
      } else {
        scopes.delete(scope);
      }
      return { ...current, [field]: sortedIds(Array.from(scopes)) };
    });
  };

  const updateMemoryDraftField = (patch: Partial<AgentMemoryPolicyDraft>) => {
    setMemoryPolicyDraft((current) => ({ ...current, ...patch }));
  };

  const addMemoryGroup = (field: "readSharedGroups" | "writeSharedGroups", value: string) => {
    const normalized = String(value || "").trim();
    if (!normalized) {
      return;
    }
    setMemoryPolicyDraft((current) => ({
      ...current,
      [field]: sortedIds([...current[field], normalized]),
      newReadGroup: field === "readSharedGroups" ? "" : current.newReadGroup,
      newWriteGroup: field === "writeSharedGroups" ? "" : current.newWriteGroup,
    }));
  };

  const removeMemoryGroup = (field: "readSharedGroups" | "writeSharedGroups", value: string) => {
    setMemoryPolicyDraft((current) => ({
      ...current,
      [field]: current[field].filter((group) => group !== value),
    }));
  };

  const addKnowledgeBaseId = (
    field: "readKnowledgeBaseIds" | "proposeKnowledgeBaseIds" | "reviewKnowledgeBaseIds" | "rateKnowledgeBaseIds",
    value: string,
  ) => {
    const normalized = String(value || "").trim();
    if (!normalized) {
      return;
    }
    setMemoryPolicyDraft((current) => ({
      ...current,
      [field]: sortedIds([...current[field], normalized]),
      newReadKnowledgeBaseId: field === "readKnowledgeBaseIds" ? "" : current.newReadKnowledgeBaseId,
      newProposeKnowledgeBaseId: field === "proposeKnowledgeBaseIds" ? "" : current.newProposeKnowledgeBaseId,
      newReviewKnowledgeBaseId: field === "reviewKnowledgeBaseIds" ? "" : current.newReviewKnowledgeBaseId,
      newRateKnowledgeBaseId: field === "rateKnowledgeBaseIds" ? "" : current.newRateKnowledgeBaseId,
    }));
  };

  const removeKnowledgeBaseId = (
    field: "readKnowledgeBaseIds" | "proposeKnowledgeBaseIds" | "reviewKnowledgeBaseIds" | "rateKnowledgeBaseIds",
    value: string,
  ) => {
    setMemoryPolicyDraft((current) => ({
      ...current,
      [field]: current[field].filter((knowledgeBaseId) => knowledgeBaseId !== value),
    }));
  };

  const updateDelegationPolicyDraft = (patch: Partial<AgentDelegationPolicyDraft>) => {
    setDelegationPolicyDraft((current) => ({ ...current, ...patch }));
  };

  const toggleDelegationContextMode = (mode: "isolated" | "fork", selected: boolean) => {
    setDelegationPolicyDraft((current) => {
      const modes = new Set(current.allowedContextModes);
      if (selected) {
        modes.add(mode);
      } else {
        modes.delete(mode);
      }
      const nextModes = sortedIds(Array.from(modes)).filter((item) => item === "isolated" || item === "fork");
      return { ...current, allowedContextModes: nextModes.length ? nextModes : ["isolated"] };
    });
  };

  const updateSupervisionPolicyDraft = (patch: Partial<AgentSupervisionPolicyDraft>) => {
    setSupervisionPolicyDraft((current) => {
      const next = { ...current, ...patch };
      if (patch.reviewMode === "required") {
        next.requiresReview = true;
      }
      if (patch.reviewMode === "disabled") {
        next.requiresReview = false;
      }
      return next;
    });
  };

  const saveAgentConfig = () => {
    if (!selectedAgent || !canSaveConfig || selectedAgentConfigPending) {
      return;
    }
    updateAgentMutation.mutate({
      agentId: selectedAgent.agentId,
      agent: selectedAgent,
      draft: configDraft,
      modelChoices: workspace?.agentModelChoices ?? [],
      sourceDraftId: activeConfigDraftId,
    });
  };

  const saveAgentConfigDraft = () => {
    if (!selectedAgent || !configDirty || selectedAgentConfigDraftSavePending) {
      return;
    }
    saveAgentConfigDraftMutation.mutate({
      agentId: selectedAgent.agentId,
      baseUpdatedAt: selectedAgent.updatedAt,
      snapshot: configChangeSnapshotFromDraft(configDraft),
    });
  };

  const discardAgentConfigDraft = () => {
    if (!selectedAgent || !activeConfigDraftId || selectedAgentConfigDraftDiscardPending) {
      return;
    }
    discardAgentConfigDraftMutation.mutate({
      agentId: selectedAgent.agentId,
      draftId: activeConfigDraftId,
    });
  };

  const promoteAgentModel = (
    slot: AgentLlmSlotDefinition,
    candidate: AgentModelChoice,
  ) => {
    if (!selectedAgent || promoteAgentModelMutation.isPending) {
      return;
    }
    const expectedBaseHash = String(workspace?.operatorConfigHash || "").trim();
    if (!expectedBaseHash) {
      setNotice({
        tone: "error",
        text: lang === "zh" ? "配置快照已失效，请刷新后重试。" : "The config snapshot is stale; refresh and retry.",
      });
      return;
    }
    const externalConfigDraftDirty = readConfigDraftPresence();
    setConfigDraftPresenceDirty(externalConfigDraftDirty);
    if (configDirty || externalConfigDraftDirty) {
      setNotice({
        tone: "error",
        text: lang === "zh" ? "请先保存或放弃未保存修改。" : "Save or discard unsaved changes first.",
      });
      return;
    }
    // Confirm UI lives in AgentModelPicker (VConfirmDialog).
    promoteAgentModelMutation.mutate({
      agent: selectedAgent,
      slot,
      candidate,
      expectedBaseHash,
    });
  };

  const saveModeMembership = () => {
    if (!selectedAgent || !canSaveMembership || selectedAgentMembershipPending) {
      return;
    }
    updateMembershipMutation.mutate({ agentId: selectedAgent.agentId, draft: membershipDraft });
  };

  const savePersonaProfile = () => {
    if (!selectedAgent || !canSavePersona || selectedAgentPersonaPending) {
      return;
    }
    updatePersonaMutation.mutate({ agentId: selectedAgent.agentId, draft: personaDraft });
  };

  const saveTaskProfile = () => {
    if (!selectedAgent || !canSaveTask || selectedAgentTaskPending) {
      return;
    }
    updateTaskMutation.mutate({ agentId: selectedAgent.agentId, draft: taskDraft });
  };

  const saveToolPolicy = () => {
    if (!selectedAgent || !canSaveToolPolicy || selectedAgentToolPolicyPending) {
      return;
    }
    const saveDraft = normalizeToolPolicyDraftForAgent(toolPolicyDraft, selectedAgent);
    updateToolPolicyMutation.mutate({
      agentId: selectedAgent.agentId,
      draft: saveDraft,
      basePolicy: selectedAgent.toolPolicy,
    });
  };

  const submitToolGovernanceRequest = () => {
    if (!selectedAgent || !canSubmitToolGovernance || selectedAgentToolGovernanceCreatePending) {
      setNotice({ tone: "error", text: copy.toolGovernanceNoDelta });
      return;
    }
    createToolGovernanceMutation.mutate({
      agentId: selectedAgent.agentId,
      draft: toolGovernanceDraft,
      delta: toolGovernanceDelta,
    });
  };

  const resolveToolGovernanceRequest = (request: AgentToolGovernanceRequest, decision: "approve" | "reject") => {
    const requestPending =
      resolveToolGovernanceMutation.isPending
      && resolveToolGovernanceMutation.variables?.agentId === request.targetAgentId
      && resolveToolGovernanceMutation.variables?.requestId === request.requestId;
    if (!request.targetAgentId || !request.requestId || requestPending) {
      return;
    }
    resolveToolGovernanceMutation.mutate({
      agentId: request.targetAgentId,
      requestId: request.requestId,
      decision,
    });
  };

  const saveMemoryPolicy = () => {
    if (!selectedAgent || !canSaveMemoryPolicy || selectedAgentMemoryPolicyPending) {
      return;
    }
    updateMemoryPolicyMutation.mutate({
      agentId: selectedAgent.agentId,
      draft: memoryPolicyDraft,
      basePolicy: selectedAgent.memoryPolicy,
    });
  };

  const saveRuntimePolicy = () => {
    if (!selectedAgent || !canSaveRuntimePolicy || selectedAgentRuntimePolicyPending) {
      return;
    }
    updateRuntimePolicyMutation.mutate({
      agentId: selectedAgent.agentId,
      delegationPolicy: delegationPolicyDraft,
      supervisionPolicy: supervisionPolicyDraft,
    });
  };

  const toggleBulkAgent = (agentId: string, selected: boolean, extendRange = false) => {
    setSelectedBulkAgentIds((current) => {
      const next = new Set(current);
      if (extendRange && bulkSelectionAnchorAgentId) {
        const anchorIndex = visibleAgents.findIndex((agent) => agent.agentId === bulkSelectionAnchorAgentId);
        const targetIndex = visibleAgents.findIndex((agent) => agent.agentId === agentId);
        if (anchorIndex >= 0 && targetIndex >= 0) {
          const [start, end] = anchorIndex <= targetIndex ? [anchorIndex, targetIndex] : [targetIndex, anchorIndex];
          visibleAgents.slice(start, end + 1).forEach((agent) => {
            if (selected) {
              next.add(agent.agentId);
            } else {
              next.delete(agent.agentId);
            }
          });
          return next;
        }
      }
      if (selected) {
        next.add(agentId);
      } else {
        next.delete(agentId);
      }
      return next;
    });
    setBulkSelectionAnchorAgentId(agentId);
  };

  const handleAgentRowSelect = (agent: AgentConfigWorkspaceAgent, event: MouseEvent<HTMLButtonElement>) => {
    if (event.ctrlKey || event.metaKey || event.shiftKey) {
      event.preventDefault();
      toggleBulkAgent(agent.agentId, event.shiftKey ? true : !selectedBulkAgentIds.has(agent.agentId), event.shiftKey);
      return;
    }
    setSelectedAgentId(agent.agentId);
    setBulkSelectionAnchorAgentId(agent.agentId);
  };

  const selectVisibleBulkAgents = () => {
    setSelectedBulkAgentIds(new Set(visibleAgents.map((agent) => agent.agentId)));
    setBulkSelectionAnchorAgentId(visibleAgents[0]?.agentId ?? "");
  };

  const clearBulkAgents = () => {
    setSelectedBulkAgentIds(new Set());
    setBulkSelectionAnchorAgentId("");
  };

  const updateBulkConfigDraft = (patch: Partial<AgentBulkConfigDraft>) => {
    setBulkConfigDraft((current) => ({ ...current, ...patch }));
  };

  const toggleBulkConfigApply = (field: AgentBulkConfigField, selected: boolean) => {
    setBulkConfigApply((current) => ({ ...current, [field]: selected }));
  };

  const bulkApplyAgentConfig = async () => {
    if (bulkAgentPending) {
      return;
    }
    if (selectedBulkAgents.length < 2) {
      setNotice({ tone: "error", text: copy.bulkNoSelection });
      return;
    }
    if (!bulkConfigReady(bulkConfigDraft, bulkConfigApply)) {
      setNotice({ tone: "error", text: copy.bulkNoConfigFields });
      return;
    }

    setBulkAgentPending(true);
    let success = 0;
    let skipped = 0;
    let failed = 0;
    const notes: string[] = [];
    const agentsById = new Map(selectedBulkAgents.map((agent) => [agent.agentId, agent]));

    try {
      const response = await fetchJson<AgentBulkConfigResponse>("/api/agents/bulk-config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          agentIds: selectedBulkAgents.map((agent) => agent.agentId),
          applyFields: bulkConfigApplyFields(bulkConfigApply),
          patch: bulkConfigPatchFromDraft(bulkConfigDraft, bulkConfigApply),
        }),
      });
      queryClient.setQueryData<AgentConfigWorkspace | undefined>(
        queryKeys.agentConfigWorkspace(),
        (current) => bulkUpdatedAgentWorkspaceCache(current, response.success),
      );
      success = response.summary.successCount;
      skipped = response.summary.skippedCount;
      failed = response.summary.failedCount;
      response.skipped.forEach((item) => notes.push(agentBulkActionItemNote(item, agentsById, copy.bulkSkippedProtected)));
      response.failed.forEach((item) => notes.push(agentBulkActionItemNote(item, agentsById, "")));
    } catch (error) {
      failed = selectedBulkAgents.length;
      notes.push(error instanceof Error ? error.message : String(error));
    }

    setBulkAgentPending(false);
    setNotice({
      tone: failed > 0 ? "error" : "success",
      text: agentBulkActionSummary(copy.bulkConfigResult, success, skipped, failed, notes, lang),
    });
    void chatWorkspaceCache.afterAgentWorkspaceChanged();
  };

  const bulkApplyPromptTemplate = async () => {
    if (bulkAgentPending) {
      return;
    }
    if (!selectedBulkAgents.length) {
      setNotice({ tone: "error", text: copy.bulkNoSelection });
      return;
    }
    if (!bulkPromptTemplateId) {
      setNotice({ tone: "error", text: copy.bulkNoPrompt });
      return;
    }

    setBulkAgentPending(true);
    let success = 0;
    let skipped = 0;
    let failed = 0;
    const notes: string[] = [];
    const agentsById = new Map(selectedBulkAgents.map((agent) => [agent.agentId, agent]));

    try {
      const response = await fetchJson<AgentBulkPromptTemplateResponse>("/api/agents/bulk-prompt-template", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agentIds: selectedBulkAgents.map((agent) => agent.agentId), promptTemplateId: bulkPromptTemplateId }),
      });
      queryClient.setQueryData<AgentConfigWorkspace | undefined>(
        queryKeys.agentConfigWorkspace(),
        (current) => bulkUpdatedAgentWorkspaceCache(current, response.success),
      );
      success = response.summary.successCount;
      skipped = response.summary.skippedCount;
      failed = response.summary.failedCount;
      response.skipped.forEach((item) => notes.push(agentBulkActionItemNote(item, agentsById, copy.bulkSkippedArchived)));
      response.failed.forEach((item) => notes.push(agentBulkActionItemNote(item, agentsById, copy.bulkSkippedActive)));
    } catch (error) {
      failed = selectedBulkAgents.length;
      notes.push(error instanceof Error ? error.message : String(error));
    }

    setBulkAgentPending(false);
    setNotice({
      tone: failed > 0 ? "error" : "success",
      text: agentBulkActionSummary(copy.bulkPromptResult, success, skipped, failed, notes, lang),
    });
    clearBulkAgents();
    void chatWorkspaceCache.afterAgentWorkspaceChanged();
  };

  const bulkArchiveAgents = async () => {
    if (bulkAgentPending) {
      return;
    }
    if (!selectedBulkAgents.length) {
      setNotice({ tone: "error", text: copy.bulkNoSelection });
      return;
    }
    // Confirm UI lives in AgentBulkOperationsPanel (VConfirmDialog).

    setBulkAgentPending(true);
    const notes: string[] = [];
    const archivedAgents = selectedBulkAgents.filter((agent) => agent.status === "archived");
    const protectedAgents = selectedBulkAgents.filter((agent) => agent.status !== "archived" && agentArchiveProtected(agent));
    const archiveAgents = selectedBulkAgents.filter((agent) => agent.status !== "archived" && !agentArchiveProtected(agent));
    archivedAgents.forEach((agent) => notes.push(`${agentLabel(agent)}: ${copy.bulkSkippedArchived}`));
    protectedAgents.forEach((agent) => notes.push(`${agentLabel(agent)}: ${copy.bulkSkippedProtected}`));
    const agentsById = new Map(selectedBulkAgents.map((agent) => [agent.agentId, agent]));
    let success = 0;
    let skipped = archivedAgents.length + protectedAgents.length;
    let failed = 0;
    let archivedSelectedAgent = false;

    try {
      if (archiveAgents.length) {
        const response = await fetchJson<AgentBulkActionResponse>("/api/agents/bulk-archive", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ agentIds: archiveAgents.map((agent) => agent.agentId) }),
        });
        response.success.forEach((item) => {
          const archivedAgent = item as AgentConfigWorkspaceAgent;
          if (archivedAgent.agentId === selectedAgent?.agentId) {
            archivedSelectedAgent = true;
          }
          if (archivedAgent.agentId) {
            queryClient.setQueryData<AgentConfigWorkspace | undefined>(
              queryKeys.agentConfigWorkspace(),
              (current) => archivedWorkspaceCache(current, archivedAgent),
            );
          }
        });
        response.skipped.forEach((item) => notes.push(agentBulkActionItemNote(item, agentsById, copy.bulkSkippedArchived)));
        response.failed.forEach((item) => notes.push(agentBulkActionItemNote(item, agentsById, "")));
        success += response.summary.successCount;
        skipped += response.summary.skippedCount;
        failed += response.summary.failedCount;
      }
    } catch (error) {
      failed += archiveAgents.length;
      notes.push(error instanceof Error ? error.message : String(error));
    }

    if (archivedSelectedAgent && success > 0) {
      setSelectedAgentId("");
      setActivePane("overview");
    }
    setBulkAgentPending(false);
    setNotice({
      tone: failed > 0 ? "error" : "success",
      text: agentBulkActionSummary(copy.bulkArchiveResult, success, skipped, failed, notes, lang),
    });
    clearBulkAgents();
    void chatWorkspaceCache.afterAgentArchived();
  };

  const bulkPurgeAgents = async () => {
    if (bulkAgentPending) {
      return;
    }
    if (!selectedBulkAgents.length) {
      setNotice({ tone: "error", text: copy.bulkNoSelection });
      return;
    }
    // Confirm UI lives in AgentBulkOperationsPanel (VConfirmDialog).

    setBulkAgentPending(true);
    const notes: string[] = [];
    const protectedAgents = selectedBulkAgents.filter((agent) => agentArchiveProtected(agent));
    const activeAgents = selectedBulkAgents.filter((agent) => !agentArchiveProtected(agent) && agent.status !== "archived");
    const purgeAgents = selectedBulkAgents.filter((agent) => !agentArchiveProtected(agent) && agent.status === "archived");
    protectedAgents.forEach((agent) => notes.push(`${agentLabel(agent)}: ${copy.bulkSkippedProtected}`));
    activeAgents.forEach((agent) => notes.push(`${agentLabel(agent)}: ${copy.bulkSkippedActive}`));
    const agentsById = new Map(selectedBulkAgents.map((agent) => [agent.agentId, agent]));
    let success = 0;
    let skipped = protectedAgents.length + activeAgents.length;
    let failed = 0;
    let purgedSelectedAgent = false;

    try {
      if (purgeAgents.length) {
        const response = await fetchJson<AgentBulkActionResponse>("/api/agents/bulk-purge", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ agentIds: purgeAgents.map((agent) => agent.agentId) }),
        });
        queryClient.setQueryData<AgentConfigWorkspace | undefined>(
          queryKeys.agentConfigWorkspace(),
          (current) => bulkPurgeWorkspaceCache(current, response),
        );
        purgedSelectedAgent = response.success.some((item) => item.agentId === selectedAgent?.agentId);
        response.success.forEach((item) => {
          if (agentBulkPurgeCleanupPending(item)) {
            notes.push(agentBulkActionItemNote(
              item,
              agentsById,
              lang === "zh"
                ? "Agent 与绑定会话已删除；部分私有文件因系统占用等待后续清理"
                : "The Agent and bound sessions were deleted; some private files remain pending cleanup because they are in use",
            ));
          }
        });
        response.skipped.forEach((item) => notes.push(agentBulkActionItemNote(item, agentsById, copy.bulkSkippedActive)));
        response.failed.forEach((item) => notes.push(agentBulkActionItemNote(item, agentsById, "")));
        success += response.summary.successCount;
        skipped += response.summary.skippedCount;
        failed += response.summary.failedCount;
      }
    } catch (error) {
      failed += purgeAgents.length;
      notes.push(error instanceof Error ? error.message : String(error));
    }

    if (purgedSelectedAgent && success > 0) {
      setSelectedAgentId("");
      setActivePane("overview");
    }
    setBulkAgentPending(false);
    setNotice({
      tone: failed > 0 ? "error" : "success",
      text: agentBulkActionSummary(copy.bulkPurgeResult, success, skipped, failed, notes, lang),
    });
    clearBulkAgents();
    void chatWorkspaceCache.afterAgentArchived();
  };

  const archiveSelectedAgent = () => {
    if (!selectedAgent || !canArchiveAgent || selectedAgentArchivePending) {
      return;
    }
    // Confirm UI lives in AgentArchiveZonePanel (VConfirmDialog).
    archiveAgentMutation.mutate({ agentId: selectedAgent.agentId });
  };

  const purgeSelectedAgent = () => {
    if (!selectedAgent || !canPurgeAgent || selectedAgentPurgePending) {
      return;
    }
    // Confirm UI lives in AgentArchiveZonePanel (VConfirmDialog).
    purgeAgentMutation.mutate({ agentId: selectedAgent.agentId });
  };

  const updateResetOption = (key: keyof AgentResetOptions, value: boolean) => {
    setResetOptions((current) => ({ ...current, [key]: value }));
  };

  const resetSelectedAgent = () => {
    if (!selectedAgent || !canResetAgent || resettingAgentIds.has(selectedAgent.agentId)) {
      return;
    }
    // Confirm UI lives in AgentDebugResetPanel (VConfirmDialog).
    resetAgentMutation.mutate({ agentId: selectedAgent.agentId, options: resetOptions });
  };

  const resetSelectedAgentAvatar = () => {
    if (!selectedAgent?.agentId || selectedAgentAvatarUpdatePending) {
      return;
    }
    updateAvatarMutation.mutate({ agentId: selectedAgent.agentId, resetToDefault: true });
  };

  const selectAgentAvatar = (avatarImagePath: string) => {
    if (!selectedAgent?.agentId || selectedAgentAvatarUpdatePending) {
      return;
    }
    updateAvatarMutation.mutate({ agentId: selectedAgent.agentId, avatarImagePath });
  };

  const uploadSelectedAgentAvatar = (file: File | undefined) => {
    if (!selectedAgent?.agentId || !file || selectedAgentAvatarUploadPending) {
      return;
    }
    uploadAvatarMutation.mutate({ agentId: selectedAgent.agentId, file });
  };

  const consumeInboxMessage = (message: AgentInboxMessage) => {
    if (!selectedAgent?.agentId) {
      return;
    }
    const messageId = String(message.messageId || message.eventId || "").trim();
    const messagePending =
      consumeMessageMutation.isPending
      && consumeMessageMutation.variables?.agentId === selectedAgent.agentId
      && consumeMessageMutation.variables?.messageId === messageId;
    if (!messageId || messagePending) {
      return;
    }
    consumeMessageMutation.mutate({
      agentId: selectedAgent.agentId,
      messageId,
      sessionId: selectedAgent.directSessionId || message.targetSessionId || "",
    });
  };

  const consumeAllInboxMessages = () => {
    if (!selectedAgent?.agentId || selectedAgentConsumeAllPending) {
      return;
    }
    consumeAllMessagesMutation.mutate({
      agentId: selectedAgent.agentId,
      sessionId: selectedAgent.directSessionId || "",
    });
  };

  const openAgentSession = (sessionId: string) => {
    const normalized = String(sessionId || selectedAgent?.directSessionId || "").trim();
    if (!normalized) {
      return;
    }
    void navigate(`/chat?session=${encodeURIComponent(normalized)}`);
  };

  const openAgentLogs = (evidence: AgentRuntimeEvidenceMatch | null | undefined) => {
    if (evidence?.runtimeSceneId) {
      const rawRef = evidence.rawRefs?.[0]?.path || "";
      const params = new URLSearchParams({ root: "runtime_scenes", scene: evidence.runtimeSceneId });
      if (rawRef) {
        params.set("path", rawRef);
      }
      void navigate(`/logs?${params.toString()}`);
      return;
    }
    void navigate("/logs");
  };

  const focusInboxMessage = (messageId: string) => {
    const normalized = String(messageId || "").trim();
    if (normalized) {
      setFocusedMessageId(normalized);
    }
  };

  const handleSelectFilterGroup = (groupId: string) => {
    setActiveFilter(groupId);
    setSelectedAgentId("");
  };

  const filterHealthLabel = (group: { id: string; healthCount?: number }) =>
    group.healthCount
      ? `${group.id === "setup:inbox" ? copy.statusReminderShort : copy.healthIssueShort} ${group.healthCount}`
      : undefined;

  const filterSections: AgentFilterSectionView[] = groupedFilters.map((section) => ({
    id: section.id,
    label: section.label,
    groups: section.groups.map((group) => {
      const displayLabel = groupDisplayLabel(group, copy);
      return {
        id: group.id,
        label: displayLabel,
        title: groupDescription(group, copy),
        ariaLabel: groupAriaLabel(displayLabel, group, copy, lang),
        count: group.count,
        icon:
          section.id === "management" ? (
            <CheckCircle2 size={15} />
          ) : section.id === "boundary" ? (
            <UserRound size={15} />
          ) : section.id === "team_index" ? (
            <Users size={15} />
          ) : group.id === "needs_review" ? (
            <AlertTriangle size={15} />
          ) : (
            <Bot size={15} />
          ),
        healthLabel: filterHealthLabel(group),
      };
    }),
  }));

  const advancedFilterSections: AgentFilterSectionView[] = advancedGroupedFilters.map((section) => ({
    id: section.id,
    label: section.label,
    groups: section.groups.map((group) => {
      const displayLabel = groupDisplayLabel(group, copy);
      return {
        id: group.id,
        label: displayLabel,
        title: groupDescription(group, copy),
        ariaLabel: groupAriaLabel(displayLabel, group, copy, lang),
        count: group.count,
        icon:
          section.id === "source_scope" ? (
            <Database size={15} />
          ) : section.id === "reference" ? (
            <Users size={15} />
          ) : (
            <Layers3 size={15} />
          ),
        healthLabel: filterHealthLabel(group),
      };
    }),
  }));

  const agentRowLookup = new Map<string, AgentConfigWorkspaceAgent>();
  const denseColumns: AgentDenseColumn[] = visibleAgentColumns.map((column) => ({
    id: column.id,
    label: column.label,
    description: column.description,
    count: column.agents.length,
    rows: column.agents.map((agent) => {
      agentRowLookup.set(agent.agentId, agent);
      const display = agentDisplayInfo(agent, lang);
      const modelDisplay = agentDialogueModelDisplay(agent, lang);
      return {
        id: agent.agentId,
        name: display.name,
        roleLabel: display.functionLabel,
        roleTone: display.tone,
        avatarUrl: agent.avatarImageUrl,
        avatarInitials: avatarInitials(agent.agentCode, display.name),
        modelLabel: modelDisplay.label,
        modelDetail: modelDisplay.detail,
        promptLabel: promptTemplateDisplayName(agent.promptTemplate, agent.promptTemplateId, lang),
        runtimeLabel: runtimeStatusLabel(agent, lang),
        runtimeTone: runtimeStatusTone(agent),
        modes: uniqueModes(agent).slice(0, 3).map((mode) => modeLabel(mode, lang)),
        issueLabel: issueLabel(agent.health, lang),
        issueTone: issueTone(agent.health),
        issueSummary: issueSummary(agent.health, lang),
        active: selectedAgent?.agentId === agent.agentId,
        bulkSelected: selectedBulkAgentIds.has(agent.agentId),
        selectLabel: `${copy.bulkSelected}: ${display.name}`,
      };
    }),
  }));

  const selectedAgentOverviewPanel: {
    facts: AgentOverviewFact[];
    territory: AgentOverviewTerritory;
    modeMembership: AgentOverviewModeMembership;
    policies: AgentOverviewPanelPolicy[];
  } | null = selectedAgent ? (() => {
    const selectedModelDisplay = agentDialogueModelDisplay(selectedAgent, lang);
    const normalizedBindings = normalizeAgentLlmBindings(selectedAgent.llmBindings);
    const facts: AgentOverviewFact[] = [
      {
        id: "model",
        icon: "model",
        title: selectedModelDisplay.detail,
        label: copy.model,
        value: selectedModelDisplay.label,
      },
      {
        id: "llm-slots",
        icon: "llm",
        title: llmSlots.map((slot) => `${slot.label}: ${agentLlmSlotModelId(selectedAgent.llmBindings, slot) || "-"}`).join(" / "),
        label: copy.llmSlots,
        value: `${Object.keys(normalizedBindings).length}/${llmSlots.length}`,
      },
      {
        id: "system-ids",
        icon: "system",
        title: selectedAgent.agentId || "-",
        label: lang === "zh" ? "系统编号" : "System IDs",
        value: selectedAgent.agentCode || "-",
      },
      {
        id: "prompt",
        icon: "prompt",
        title: selectedAgent.promptTemplate?.sourcePath || "-",
        label: copy.prompt,
        value: promptTemplateDisplayName(selectedAgent.promptTemplate, selectedAgent.promptTemplateId, lang),
      },
      {
        id: "tools",
        icon: "tools",
        title: `allowed ${selectedAgent.toolPolicy?.allowedTools?.length ?? 0} / blocked ${selectedAgent.toolPolicy?.blockedTools?.length ?? 0}`,
        label: copy.tools,
        value: selectedAgent.toolPolicyId || "-",
      },
      {
        id: "memory",
        icon: "memory",
        title: selectedAgent.memoryPolicy?.privateMemoryRoot || "-",
        label: copy.memory,
        value: selectedAgent.memoryPolicyId || "-",
      },
    ];

    if (selectedAgentRequiresPersona) {
      facts.push({
        id: "persona",
        icon: "persona",
        title: (selectedAgent.personaProfile?.expertise ?? []).join(" / ") || copy.expertise,
        label: copy.personaTitle,
        value: personaProfileSummary(selectedAgent, lang),
      });
    }

    if (selectedAgentRequiresTask) {
      facts.push({
        id: "task",
        icon: "task",
        title: (selectedAgent.taskProfile?.taskTypes ?? []).join(" / ") || copy.taskTypes,
        label: copy.taskTitle,
        value: taskProfileSummary(selectedAgent, lang),
      });
    }

    facts.push({
      id: "territory",
      icon: "territory",
      title: selectedAgent.workspaceTerritory?.privateRoot || selectedAgent.workspacePath || "-",
      label: copy.territory,
      value: selectedAgent.workspaceTerritory?.defaultWriteScope || "private",
    });

    return {
      facts,
      territory: {
        eyebrow: copy.territory,
        title: selectedAgent.workspaceTerritory?.defaultWriteScope || "private",
        privateLabel: copy.privateTerritory,
        privateValue: selectedAgent.workspaceTerritory?.privateRoot || selectedAgent.workspacePath || "-",
        sharedLabel: copy.sharedTerritory,
        sharedValue: selectedAgent.workspaceTerritory?.sharedRoot || "workspace/shared",
        writeBoundaryLabel: copy.writeBoundary,
        writeBoundaryValue: (selectedAgent.workspaceTerritory?.writeScopes ?? ["private"]).join(" / "),
      },
      modeMembership: {
        eyebrow: copy.modeMembership,
        title: `${modeLabel(selectedAgent.primaryMode, lang)} / ${selectedAgent.roleKey || "-"}`,
        modes: uniqueModes(selectedAgent).map((mode) => ({
          id: mode,
          label: modeLabel(mode, lang),
        })),
      },
      policies: [
        {
          id: "context",
          icon: "context",
          label: copy.context,
          value: `${selectedAgent.groupContextEvents?.length ?? 0} group events`,
        },
        {
          id: "runtime",
          icon: "runtime",
          label: copy.runtimeStatus,
          value: runtimeStatusLabel(selectedAgent, lang),
        },
        {
          id: "communication",
          icon: "communication",
          label: copy.communication,
          value: `${selectedAgent.agentInboxPendingCount ?? 0} pending`,
        },
        {
          id: "delegation",
          icon: "delegation",
          label: copy.delegation,
          value: metadataText(selectedAgent, "maxSubagentDepth") || copy.policyPending,
        },
      ],
    };
  })() : null;

  const selectedAgentReferencesPanel: {
    chatRoomSummary: string;
    chatRooms: AgentReferenceRoomView[];
    references: AgentReferenceItemView[];
  } | null = selectedAgent ? (() => {
    const chatRooms: AgentReferenceRoomView[] = (workspace?.chatRooms ?? []).map((room) => {
      const selected = room.agentIds.includes(selectedAgent.agentId);
      return {
        id: room.roomId,
        statusLabel: selected ? (lang === "zh" ? "已加入" : "Joined") : (lang === "zh" ? "未加入" : "Not joined"),
        statusTone: selected ? "active" : "stale",
        title: room.title || room.roomId,
        meta: `${room.mode || "-"} · ${room.participantCount} members · ${formatTimestamp(room.updatedAt, lang)}`,
        route: compactProjectionRoute(room, `/chat?room=${encodeURIComponent(room.roomId)}`),
        actionLabel: lang === "zh" ? "打开群聊" : "Open room",
      };
    });
    const references: AgentReferenceItemView[] = selectedAgent.references.map((reference) => ({
      id: `${reference.kind}:${reference.sourceId}:${reference.mode}:${reference.field}`,
      label: referenceLabel(reference, lang),
      statusLabel: reference.status || "active",
      statusTone: reference.status === "stale" ? "stale" : "active",
      sourceLabel: reference.sourceLabel,
      meta: [reference.mode, reference.field].filter(Boolean).join(" / ") || reference.sourceId,
      route: referenceRoute(reference),
      actionLabel: lang === "zh" ? "打开" : "Open",
    }));
    return {
      chatRoomSummary: `${selectedAgent.references.filter((reference) => reference.kind === "chat_room").length} / ${workspace?.chatRooms.length ?? 0}`,
      chatRooms,
      references,
    };
  })() : null;

  const overviewOperations = selectedAgent ? {
    copy: {
      currentFocus: copy.runtimeFocus,
      recentActivity: copy.activityTimeline,
      loading: copy.loading,
      noActivity: copy.activityTimelineEmpty,
      noActivityDetail: lang === "zh"
        ? "可从会话开始使用此 Agent，或先检查配置。"
        : "Start a session with this Agent or check its configuration first.",
      activityUnavailable: lang === "zh" ? "活动摘要暂不可用" : "Activity preview is unavailable",
      latestRun: copy.runtimeLatestRun,
      updated: copy.runtimeUpdated,
      nextStep: copy.runtimeNextStep,
      openSession: copy.openSession,
      openLogs: copy.openLogs,
      checkConfig: lang === "zh" ? "检查配置" : "Check configuration",
      viewActivity: lang === "zh" ? "查看完整活动" : "View full activity",
    },
    state: (agentRunsQuery.isError || agentMessagesQuery.isError || agentRuntimeEvidenceQuery.isError)
      ? "error" as const
      : (agentRunsQuery.isPending || agentMessagesQuery.isPending || agentRuntimeEvidenceQuery.isPending)
        ? "loading" as const
        : "ready" as const,
    errorMessage: lang === "zh" ? "请在完整活动页重试。" : "Open the full activity view to retry.",
    runtime: {
      statusLabel: runtimeStatusLabel(selectedAgent, lang),
      statusReason: selectedAgent.runtimeStatus?.reason || selectedAgent.status || "-",
      summary: selectedAgent.runtimeStatus?.summary || selectedAgent.directSessionId || selectedAgent.workspacePath || "-",
      latestRunId: selectedAgent.runtimeStatus?.runId || "-",
      updatedAt: formatTimestamp(selectedAgent.runtimeStatus?.updatedAt || selectedAgent.updatedAt, lang),
      nextStep: runtimeNextStep(selectedAgent, lang),
      onOpenSession: runtimeFocusSessionId ? () => openAgentSession(runtimeFocusSessionId) : undefined,
      onOpenLogs: () => openAgentLogs(runtimeFocusEvidence.match),
    },
    activities: activityTimeline.slice(0, 5).map((item) => ({
      id: item.id,
      title: item.title,
      body: item.body,
      meta: item.meta,
      onOpenLogs: item.canOpenLogs ? () => openAgentLogs(item.evidence) : undefined,
    })),
    onOpenActivity: () => setActivePane("activity"),
    onOpenConfig: () => setActivePane("config"),
    onOpenSession: runtimeFocusSessionId ? () => openAgentSession(runtimeFocusSessionId) : undefined,
  } : null;

  const overviewResources = selectedAgent ? {
    title: lang === "zh" ? "关联资源" : "Related resources",
    emptyLabel: lang === "zh" ? "暂无可直接打开的关联资源。" : "No related resource can be opened yet.",
    openLabel: lang === "zh" ? "打开" : "Open",
    resources: [
      {
        id: "prompt",
        label: copy.prompt,
        value: configDraft.promptTemplateId || selectedAgent.promptTemplateId || "-",
        route: selectedAgentPromptConfigRoute,
      },
      {
        id: "tools",
        label: copy.tools,
        value: selectedAgent.toolPolicyId || "-",
        route: selectedAgentToolConfigRoute,
      },
      {
        id: "memory",
        label: copy.memory,
        value: selectedAgent.memoryPolicyId || "-",
        route: selectedAgentMemoryConfigRoute,
      },
      ...(selectedAgentReferencesPanel?.chatRooms.filter((room) => room.statusTone === "active").slice(0, 1).map((room) => ({
        id: `room:${room.id}`,
        label: lang === "zh" ? "群聊" : "Group room",
        value: room.title,
        route: room.route,
      })) ?? []),
      ...(selectedAgentReferencesPanel?.references.slice(0, 1).map((reference) => ({
        id: `reference:${reference.id}`,
        label: reference.label,
        value: reference.sourceLabel || reference.meta,
        route: reference.route,
      })) ?? []),
    ].filter((resource) => resource.value !== "-" && resource.route),
    onOpenRoute: (route: string) => {
      void navigate(route);
    },
  } : null;

  const selectedAgentDetailContent: AgentSelectedDetailContentPanelProps | null = selectedAgent ? {
    activePane,
    preferOpsSection: (selectedAgent.health?.length ?? 0) > 0,
    inspectorInWorkspaceRail: true,
    header: {
      copy,
      lang,
      title: copy.routeHint,
      agentName: agentLabel(selectedAgent),
      roleLabel: agentFunctionalLabel(selectedAgent, lang),
      roleTone: agentFunctionTone(selectedAgent, lang),
      healthTitle: issueSummary(selectedAgent.health, lang),
      healthTone: issueTone(selectedAgent.health),
      healthLabel: issueLabel(selectedAgent.health, lang),
      inspectorLabel: lang === "zh" ? "检查器" : "Inspector",
      inspectorOpen,
      runLabel: copy.run,
      panes,
      activePane,
      isAvatarEditorOpen: avatarEditorOpen,
      avatarImageUrl: selectedAgent.avatarImageUrl,
      avatarImagePath: selectedAgent.avatarImagePath,
      avatarInitials: avatarInitials(selectedAgent.agentCode, agentLabel(selectedAgent)),
      avatarOptions: avatarOptionsQuery.data,
      avatarOptionsPending: avatarOptionsQuery.isPending,
      avatarUploadPending: selectedAgentAvatarUploadPending,
      avatarUpdatePending: selectedAgentAvatarUpdatePending,
      onAvatarEditorOpenChange: setAvatarEditorOpen,
      onUploadAvatar: uploadSelectedAgentAvatar,
      onResetAvatar: resetSelectedAgentAvatar,
      onSelectAvatar: selectAgentAvatar,
      onSelectPane: setActivePane,
      onToggleInspector: () => setInspectorOpen((open) => !open),
      onRun: runtimeFocusSessionId ? () => openAgentSession(runtimeFocusSessionId) : undefined,
    },
    brief: {
      brief: managementBrief,
      copy: {
        managementBriefHint: copy.managementBriefHint,
        managementBriefTitle: copy.managementBriefTitle,
        nextActionsTitle: copy.nextActionsTitle,
        nextAllReady: copy.nextAllReady,
      },
      onOpenRoute: (route: string) => {
        void navigate(route);
      },
      onSelectPane: setActivePane,
    },
    overview: selectedAgentOverviewPanel,
    operations: overviewOperations,
    resources: overviewResources,
    effectiveConfiguration: {
      fields: effectiveConfigurationFields,
      selectedFieldKey: selectedEffectiveField?.key ?? "",
      onSelectField: setSelectedEffectiveFieldKey,
      onOpenConfig: () => setActivePane("config"),
    },
    teamRelations: {
      relations: selectedTeamRelations,
      onOpenTeam: (teamId: string) => {
        void navigate(`/teams?team=${encodeURIComponent(teamId)}`);
      },
    },
    configChanges: {
      changes: configChangesQuery.data,
      configDirty,
      loading: configChangesQuery.isPending,
      savePending: selectedAgentConfigDraftSavePending,
      discardPending: selectedAgentConfigDraftDiscardPending,
      onSaveDraft: saveAgentConfigDraft,
      onDiscardDraft: discardAgentConfigDraft,
      onOpenConfig: () => setActivePane("config"),
    },
    configPrimary: {
      coreConfig: {
        copy,
        lang,
        agentName: agentLabel(selectedAgent),
        draft: configDraft,
        dirty: configDirty,
        configDraftDirty: configDraftPresenceDirty,
        canSave: canSaveConfig && !promoteAgentModelMutation.isPending,
        pending: selectedAgentConfigPending || promoteAgentModelMutation.isPending,
        notice,
        title: copy.personaHint,
        health: {
          tone: issueTone(selectedAgent.health),
          label: issuePanelLabel(selectedAgent.health, { statusReminders: copy.statusReminders, healthIssues: copy.healthIssues }),
          headline: `${issueLabel(selectedAgent.health, lang)} · ${issueSummary(selectedAgent.health, lang)}`,
          nextStepLabel: copy.healthNextStep,
          nextStep: issueNextStep(selectedAgent.health, lang),
        },
        llmSlots: coreConfigLlmSlots,
        pendingModelRef: promoteAgentModelMutation.isPending
          ? promoteAgentModelMutation.variables?.candidate.modelRef ?? ""
          : "",
        promptTemplateOptions: bulkPromptTemplateOptions,
        toolPolicyOptions: coreConfigToolPolicyOptions,
        toolPolicyTooltip: coreConfigToolPolicyTooltip,
        memoryPolicyOptions: coreConfigMemoryPolicyOptions,
        memoryPolicyTooltip: copy.memoryPolicyPickerHint,
        contextCompressionTitle: contextCompressionPolicyLine,
        onDraftChange: updateDraft,
        onLlmSlotModelChange: (slot, modelId) => {
          const nextBindings = updateAgentLlmSlotBinding(configDraft.llmBindings, slot, modelId);
          updateDraft({
            llmBindings: nextBindings,
            reasoningEffortBySlot: pruneAgentReasoningEffortBySlot(
              configDraft.reasoningEffortBySlot,
              nextBindings,
              workspace?.agentModelChoices ?? [],
            ),
          });
        },
        onPromoteModel: promoteAgentModel,
        onReasoningEffortChange: (slot, reasoningEffort) => updateDraft({
          reasoningEffortBySlot: updateAgentReasoningEffortBySlot(
            configDraft.reasoningEffortBySlot,
            slot,
            reasoningEffort,
          ),
        }),
        onContextCompressionChange: updateContextCompressionDraft,
        onOpenModelConfig: () => navigate(selectedAgentModelConfigRoute),
        onOpenPromptConfig: () => navigate(selectedAgentPromptConfigRoute),
        onOpenContextConfig: () => navigate(selectedAgentContextConfigRoute),
        onReset: () => setConfigDraft(draftFromAgent(selectedAgent)),
        onSave: saveAgentConfig,
      },
      personaProfile: selectedAgentRequiresPersona ? {
        copy,
        lang,
        summary: personaProfileSummary(selectedAgent, lang),
        draft: personaDraft,
        dirty: personaDirty,
        canSave: canSavePersona,
        pending: selectedAgentPersonaPending,
        onDraftChange: updatePersonaDraft,
        onReset: () => setPersonaDraft(personaDraftFromAgent(selectedAgent)),
        onSave: savePersonaProfile,
      } : null,
      toolGovernance: {
        copy,
        lang,
        requests: selectedAgent.toolGovernanceRequests ?? [],
        pendingRequestId:
          resolveToolGovernanceMutation.isPending
          && resolveToolGovernanceMutation.variables?.agentId === selectedAgent.agentId
            ? resolveToolGovernanceMutation.variables?.requestId ?? null
            : null,
        onResolve: resolveToolGovernanceRequest,
        onConfigure: () => navigate(selectedAgentToolConfigRoute),
      },
      taskProfile: selectedAgentRequiresTask ? {
        copy,
        lang,
        summary: taskProfileSummary(selectedAgent, lang),
        draft: taskDraft,
        dirty: taskDirty,
        canSave: canSaveTask,
        pending: selectedAgentTaskPending,
        onDraftChange: updateTaskDraft,
        onReset: () => setTaskDraft(taskDraftFromAgent(selectedAgent)),
        onSave: saveTaskProfile,
      } : null,
      healthMaintenance: {
        copy: {
          handleInboxNow: copy.handleInboxNow,
          maintenanceHint: copy.maintenanceHint,
          maintenanceTitle: copy.maintenanceTitle,
          noIssues: copy.noIssues,
        },
        health: {
          title: issueNextStep(selectedAgent.health, lang),
          label: issuePanelLabel(selectedAgent.health, { statusReminders: copy.statusReminders, healthIssues: copy.healthIssues }),
          headline: `${issueLabel(selectedAgent.health, lang)} · ${issueSummary(selectedAgent.health, lang)}`,
          hasIssues: selectedAgent.health.length > 0,
          issues: selectedAgent.health.map((issue) => ({
            key: `${issue.code}:${issue.detail}`,
            severity: issue.severity,
            title: issueDisplayTitle(issue, lang),
            detail: issue.detail,
            showInboxAction: issue.code === "pending_inbox_messages",
          })),
        },
        onOpenActivity: () => setActivePane("activity"),
      },
      archiveZone: {
        copy,
        agentName: agentLabel(selectedAgent),
        status: selectedAgent.status,
        isProtected: selectedAgentProtected,
        canArchive: canArchiveAgent,
        canPurge: canPurgeAgent,
        isArchivePending: selectedAgentArchivePending,
        isPurgePending: selectedAgentPurgePending,
        onArchive: archiveSelectedAgent,
        onPurge: purgeSelectedAgent,
      },
      debugReset: selectedAgent.status !== "archived" ? {
        copy,
        agentName: agentLabel(selectedAgent),
        options: resetOptions,
        canReset: canResetAgent,
        pending: selectedAgentResetPending,
        onOptionChange: updateResetOption,
        onReset: resetSelectedAgent,
      } : null,
    },
    configPolicies: {
      toolSummary: {
        copy,
        lang,
        policyId: selectedAgent.toolPolicyId,
        allowedCount: selectedAgent.toolPolicy?.allowedTools?.length ?? 0,
        preferredCount: selectedAgent.toolPolicy?.preferredTools?.length ?? 0,
        blockedCount: selectedAgent.toolPolicy?.blockedTools?.length ?? 0,
        toolCategoryCount: toolBundles.length,
        onConfigure: () => navigate(selectedAgentToolConfigRoute),
      },
      memoryPolicy: {
        copy,
        lang,
        policyId: selectedAgent.memoryPolicyId || "-",
        rootPath: selectedAgent.memoryPolicy?.privateMemoryRoot || selectedAgent.workspacePath || "-",
        draft: memoryPolicyDraft,
        memoryGroupOptions,
        dirty: memoryPolicyDirty,
        pending: selectedAgentMemoryPolicyPending,
        canSave: canSaveMemoryPolicy,
        onDraftChange: updateMemoryDraftField,
        onAddMemoryGroup: addMemoryGroup,
        onRemoveMemoryGroup: removeMemoryGroup,
        onAddKnowledgeBaseId: addKnowledgeBaseId,
        onRemoveKnowledgeBaseId: removeKnowledgeBaseId,
        onOpenMemoryPage: () => navigate(selectedAgentMemoryConfigRoute),
        onReset: () => setMemoryPolicyDraft(memoryPolicyDraftFromAgent(selectedAgent)),
        onSave: saveMemoryPolicy,
      },
    },
    configReferences: {
      modeMembership: selectedAgentRequiresTeamMembership ? {
        copy,
        lang,
        modesLabel: uniqueModes(selectedAgent).map((mode) => modeLabel(mode, lang)).join(" / "),
        draft: membershipDraft,
        supervisedSlots: Object.keys(workspace?.modeBindings.supervised_evolution?.slots ?? {}),
        selfEvolutionSlots: Object.keys(workspace?.modeBindings.self_evolution?.slots ?? {}),
        dirty: membershipDirty,
        canSave: canSaveMembership,
        pending: selectedAgentMembershipPending,
        onDraftChange: updateMembershipDraft,
        onReset: () => setMembershipDraft(membershipDraftFromWorkspace(workspace, selectedAgent)),
        onSave: saveModeMembership,
      } : null,
      references: selectedAgentReferencesPanel ? {
        copy: {
          chatRoomMembership: copy.chatRoomMembership,
          references: copy.references,
          noChatRooms: copy.noChatRooms,
          selectAgent: copy.selectAgent,
          readOnlyLabel: lang === "zh" ? "只读引用" : "Read-only",
          membershipHelp: lang === "zh"
            ? "群聊成员关系在对话页的群设置中维护；团队关联群聊由团队页同步。这里仅展示引用，避免多处写同一份成员状态。"
            : "Group membership is edited from Chat group settings, while Team-owned rooms sync from Teams. This Agent view is read-only to avoid duplicate writers.",
        },
        showChatRoomMembership: selectedAgentRequiresTeamMembership,
        chatRoomSummary: selectedAgentReferencesPanel.chatRoomSummary,
        referenceCount: selectedAgent.references.length,
        chatRooms: selectedAgentReferencesPanel.chatRooms,
        references: selectedAgentReferencesPanel.references,
        onOpenRoute: (route: string) => navigate(route),
      } : null,
    },
    activity: {
      runtimeFocus: {
        copy: {
          runtimeFocus: copy.runtimeFocus,
          runtimeLatestRun: copy.runtimeLatestRun,
          runtimeReason: copy.runtimeReason,
          runtimeUpdated: copy.runtimeUpdated,
          runtimeNextStep: copy.runtimeNextStep,
          runtimeEvidence: copy.runtimeEvidence,
          openSession: copy.openSession,
          openLogs: copy.openLogs,
        },
        statusLabel: runtimeStatusLabel(selectedAgent, lang),
        statusReason: selectedAgent.runtimeStatus?.reason || selectedAgent.status || "-",
        tone: runtimeStatusTone(selectedAgent),
        summary: selectedAgent.runtimeStatus?.summary || selectedAgent.directSessionId || selectedAgent.workspacePath || "-",
        latestRunId: selectedAgent.runtimeStatus?.runId || "-",
        runReason: selectedAgent.runtimeStatus?.runKind || selectedAgent.runtimeStatus?.state || "-",
        updatedAt: formatTimestamp(selectedAgent.runtimeStatus?.updatedAt || selectedAgent.updatedAt, lang),
        nextStep: runtimeNextStep(selectedAgent, lang),
        evidenceReason: runtimeEvidenceReasonLabel(runtimeFocusEvidence.reason, lang),
        evidenceSceneId: runtimeFocusEvidence.match?.runtimeSceneId || "-",
        logsTargetLabel: runtimeFocusEvidence.match?.runtimeSceneId,
        onOpenLogs: () => openAgentLogs(runtimeFocusEvidence.match),
        onOpenSession: runtimeFocusSessionId ? () => openAgentSession(runtimeFocusSessionId) : undefined,
      },
      activityHistory: {
        agent: selectedAgent,
        copy: {
          sessions: copy.sessions,
          logs: copy.logs,
          activityPane: copy.activityPane,
          activityTimeline: copy.activityTimeline,
          loading: copy.loading,
          activityTimelineEmpty: copy.activityTimelineEmpty,
          openSession: copy.openSession,
          openLogs: copy.openLogs,
          focusMessage: copy.focusMessage,
          runHistoryTitle: copy.runHistoryTitle,
          parentRuns: copy.parentRuns,
          subAgentRuns: copy.subAgentRuns,
          maxDepth: copy.maxDepth,
          runHistoryLoading: copy.runHistoryLoading,
          noRunHistory: copy.noRunHistory,
          communication: copy.communication,
          inboxTitle: copy.inboxTitle,
          consumeAllMessages: copy.consumeAllMessages,
          consumingMessage: copy.consumingMessage,
          inboxLoading: copy.inboxLoading,
          consumeMessage: copy.consumeMessage,
          wakeStatus: copy.wakeStatus,
          inboxEmpty: copy.inboxEmpty,
        },
        lang,
        activityTimeline,
        isActivityLoading: agentRunsQuery.isPending || agentMessagesQuery.isPending,
        runHistory: agentRunsQuery.data,
        isRunHistoryLoading: agentRunsQuery.isPending,
        inboxMessages: agentMessagesQuery.data,
        isInboxLoading: agentMessagesQuery.isPending,
        inboxPendingCount: selectedAgentInboxPendingCount,
        focusedMessageId,
        pendingMessageId:
          consumeMessageMutation.isPending && consumeMessageMutation.variables?.agentId === selectedAgent.agentId
            ? consumeMessageMutation.variables?.messageId ?? ""
            : "",
        isConsumeAllPending: selectedAgentConsumeAllPending,
        onOpenSession: openAgentSession,
        onOpenLogs: openAgentLogs,
        onFocusMessage: focusInboxMessage,
        onConsumeAllMessages: consumeAllInboxMessages,
        onConsumeInboxMessage: consumeInboxMessage,
      },
      runtimePolicy: {
        copy: {
          allowedContextModes: copy.allowedContextModes,
          allowSubagents: copy.allowSubagents,
          allowWakeMessages: copy.allowWakeMessages,
          communication: copy.communication,
          context: copy.context,
          delegation: copy.delegation,
          delegationPolicyTitle: copy.delegationPolicyTitle,
          evidenceLevel: copy.evidenceLevel,
          maxConcurrent: copy.maxConcurrent,
          maxDepth: copy.maxDepth,
          requiresReview: copy.requiresReview,
          resetConfig: copy.resetConfig,
          reviewMode: copy.reviewMode,
          saveRuntimePolicy: copy.saveRuntimePolicy,
          savingRuntimePolicy: copy.savingRuntimePolicy,
          supervisionEnabled: copy.supervisionEnabled,
          supervisionPolicyTitle: copy.supervisionPolicyTitle,
        },
        lang,
        roleLabel: `${copy.supervisedRole}: ${metadataText(selectedAgent, "supervisedRole") || metadataText(selectedAgent, "selfEvolutionRole") || "-"}`,
        dirtyLabel: lang === "zh" ? "未保存" : "Unsaved",
        cleanLabel: lang === "zh" ? "已同步" : "Synced",
        isDirty: runtimePolicyDirty,
        isPending: selectedAgentRuntimePolicyPending,
        canSave: canSaveRuntimePolicy,
        notice,
        delegationPolicyDraft,
        supervisionPolicyDraft,
        inboxPendingCount: selectedAgent.agentInboxPendingCount ?? 0,
        groupContextEventCount: selectedAgent.groupContextEvents?.length ?? 0,
        onUpdateDelegationPolicy: updateDelegationPolicyDraft,
        onToggleDelegationContextMode: toggleDelegationContextMode,
        onMaxConcurrentChange: (value) => updateDelegationPolicyDraft({ maxConcurrent: clampNumber(value, 0, 8, 0) }),
        onMaxDepthChange: (value) => updateDelegationPolicyDraft({ maxDepth: clampNumber(value, 0, 4, 0) }),
        onUpdateSupervisionPolicy: updateSupervisionPolicyDraft,
        onReset: () => {
          setDelegationPolicyDraft(delegationPolicyDraftFromAgent(selectedAgent));
          setSupervisionPolicyDraft(supervisionPolicyDraftFromAgent(selectedAgent));
        },
        onSave: saveRuntimePolicy,
      },
    },
  } : null;

  return (
    <section
      className={styles.route}
      data-vui-recipe="agents-management-workbench"
    >
      <AgentManagementHeaderPanel
        copy={{
          createAgent: copy.createAgent,
          refresh: copy.refresh,
        }}
        createAgentButtonRef={agentCreateTriggerRef}
        createAgentButtonId="agents-create-trigger"
        refreshing={agentSummaryQuery.isFetching || workspaceQuery.isFetching}
        onCreateAgent={() => setCreateWizardOpen(true)}
        onRefresh={refresh}
      />

      <AgentWorkspaceLayoutPanel
        filterRail={{
          ariaLabel: copy.agentFilters,
          searchValue: searchText,
          searchPlaceholder: copy.search,
          onSearchChange: setSearchText,
          sections: filterSections,
          advancedSections: advancedFilterSections,
          advancedLabel: copy.moreFilters,
          activeGroupId: activeFilter,
          onSelectGroup: handleSelectFilterGroup,
          moreFiltersLabel: lang === "zh" ? "更多筛选" : "More filters",
        }}
        listWorkspace={{
          ariaLabel: activeGroupLabel,
          headerEyebrow: copy.agentFilters,
          headerTitle: activeGroupLabel,
          visibleAgentCount: visibleAgents.length,
          bulkOperations: {
            copy,
            selectedCount: selectedBulkAgents.length,
            visibleCount: visibleAgents.length,
            allVisibleSelected: allVisibleAgentsSelected,
            pending: bulkAgentPending,
            selectedPromptTemplateId: bulkPromptTemplateId,
            promptTemplateOptions: bulkPromptTemplateOptions,
            onSelectVisible: selectVisibleBulkAgents,
            onClearSelection: clearBulkAgents,
            onPromptTemplateChange: setBulkPromptTemplateId,
            onApplyPromptTemplate: bulkApplyPromptTemplate,
            onArchive: bulkArchiveAgents,
            onPurge: bulkPurgeAgents,
          },
          listState: {
            copy: {
              loadFailed: copy.loadFailed,
              loading: copy.loading,
              noAgents: copy.noAgents,
              retry: lang === "zh" ? "重试" : "Retry",
              refreshing: lang === "zh" ? "正在更新 Agent 列表…" : "Refreshing Agent list…",
              staleError: lang === "zh" ? "更新失败，继续显示已有 Agent 数据。" : "Refresh failed; showing existing Agent data.",
              model: copy.model,
              prompt: copy.prompt,
              runtimeStatus: copy.runtimeStatus,
              modeMembership: copy.modeMembership,
              statusReminders: copy.statusReminders,
            },
            columns: denseColumns,
            visibleAgentCount: visibleAgents.length,
            isError: agentWorkspaceInitialError || agentWorkspaceBackgroundError,
            error: agentWorkspaceError,
            isPending: agentWorkspaceInitialLoading,
            isFetching: agentSummaryQuery.isFetching || workspaceQuery.isFetching,
            hasWorkspace: hasAgentWorkspace,
            onRetry: refresh,
            onSelectRow: (rowId, event) => {
              const agent = agentRowLookup.get(rowId);
              if (agent) {
                handleAgentRowSelect(agent, event);
              }
            },
            onToggleBulk: (rowId, checked, shiftKey) => toggleBulkAgent(rowId, checked, shiftKey),
          },
        }}
        detailWorkspace={{
          ariaLabel: selectedAgent ? agentLabel(selectedAgent) : copy.title,
          returnBanner: returnToPath ? {
            copy,
            returnToLabel,
            onReturn: () => navigate(returnToPath),
          } : null,
          bulkConfig: selectedBulkAgents.length > 1 ? {
            copy,
            selectedAgents: bulkSelectedAgentOptions,
            draft: bulkConfigDraft,
            apply: bulkConfigApply,
            mixed: bulkConfigMixed,
            pending: bulkAgentPending,
            canSave: bulkConfigCanSave,
            notice,
            modelOptions: bulkModelOptions,
            promptTemplateOptions: bulkPromptTemplateOptions,
            primaryModeOptions: bulkPrimaryModeOptions,
            onToggleApply: toggleBulkConfigApply,
            onDraftChange: updateBulkConfigDraft,
            onReset: () => {
              setBulkConfigDraft(bulkConfigDraftFromAgents(selectedBulkAgents));
              setBulkConfigApply(DEFAULT_BULK_CONFIG_APPLY);
            },
            onSave: bulkApplyAgentConfig,
          } : null,
          selectedContent: selectedAgentDetailContent ? <AgentSelectedDetailContentPanel {...selectedAgentDetailContent} /> : null,
          emptySelectionTitle: copy.selectAgent,
        }}
        inspectorRail={selectedAgentDetailContent && inspectorOpen ? {
          ariaLabel: lang === "zh" ? "Agent 侧栏" : "Agent inspector",
          title: lang === "zh" ? "检查器" : "Inspector",
          subtitle: activePane === "effective" && selectedEffectiveField
            ? selectedEffectiveField.label
            : agentLabel(selectedAgent!),
          emptyTitle: lang === "zh" ? "选择 Agent 查看侧栏" : "Select an Agent",
          emptyHint: lang === "zh"
            ? "管理完整度、下一步建议与关联资源会显示在这里。"
            : "Management score, next steps, and linked resources appear here.",
          brief: selectedAgentDetailContent.brief,
          resources: selectedAgentDetailContent.resources,
          extra: activePane === "effective" ? (
            <Suspense fallback={null}>
              <AgentEffectiveConfigurationInspectorPanel
                field={selectedEffectiveField}
                onOpenConfig={() => setActivePane("config")}
              />
            </Suspense>
          ) : null,
          closeLabel: lang === "zh" ? "关闭检查器" : "Close inspector",
          onClose: () => setInspectorOpen(false),
        } : null}
      />
      {createOpen ? (
        <Suspense fallback={null}>
          <AgentCreateWizardDialog
            open={createOpen}
            triggerRef={agentCreateTriggerRef}
            triggerId="agents-create-trigger"
            onClose={() => setCreateWizardOpen(false)}
            onCreated={(agent) => {
              setSelectedAgentId(agent.agentId);
              setActivePane("overview");
              setNotice({
                tone: "success",
                text: lang === "zh" ? `已新增 ${agentLabel(agent)}` : `Created ${agentLabel(agent)}`,
              });
            }}
            onOpenAdvancedConfig={(agent) => {
              setCreateWizardOpen(false);
              navigate(`/agents?agent=${encodeURIComponent(agent.agentId)}&pane=config`);
            }}
          />
        </Suspense>
      ) : null}
    </section>
  );
}
