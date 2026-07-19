import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Apple,
  ArrowLeft,
  ArrowUpRight,
  BellRing,
  Check,
  ChevronRight,
  HeartHandshake,
  MessageCircleHeart,
  Plus,
  RotateCcw,
  Search,
  Sparkles,
  Square,
  Trash2,
  UsersRound,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  Suspense,
  lazy,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { fetchJson } from "../api/client";
import { kernelTaskCenterHref } from "../api/kernel";
import { createChatWorkspaceCache } from "./chatWorkspaceCache";
import { AgentCreateWizardDialog } from "./agent-create/AgentCreateWizardDialog";
import {
  isProjectAgentBusEventRevoked,
  listProjectAgentBusTimeline,
  revokeProjectAgentBusMessage,
  sendProjectAgentBusMessage,
} from "../api/projectAgentBus";
import { queryKeys } from "../api/queryKeys";
import {
  AgentInstance,
  ChatRoomDetail,
  ChatRoomMessage,
  ChatRoomParticipant,
  ChatRoomRoundAcceptedResponse,
  ChatRoomMode,
  ChatRoomPurpose,
  ConfigSummary,
  ChatRoomStreamEvent,
  FileContent,
  MentalStateSnapshot,
  PetActionResponse,
  PetSummary,
  RuntimeSummary,
  SessionChatReviewCandidateResponse,
  SessionCacheCompositionSegment,
  ChatNextStateSignalSummary,
  SessionDeleteResponse,
  SessionGuidanceMode,
  ConversationSummary,
  SessionDetail,
  AgentToolGovernanceRequest,
  SessionRuntimeNotice,
    SessionLlmOptions,
    SessionQueryResponse,
    SessionSummary,
  SessionStreamEvent,
  SessionReferenceAttachment,
  SessionTurnAcceptedResponse,
  SkillLibraryPayload,
  TeamListPayload,
  ConversationMessage,
  ToolCall,
} from "../api/types";
import type { ConversationStreamingFramePaintMetrics } from "../components/conversation/conversationStreamingMetrics";
import { shouldShowNextStateSignalInConversation } from "../components/conversation/conversationNextStateSignal";
import type { TurnAvatarResolution } from "../components/conversation/conversationTurnAvatar";
import { isAgentInboxMessage, isTurnErrorMessage } from "../components/conversation/conversationMessagePredicates";
import { VButton, VContextualHint, VInput, VNativeInput, VNativeSelect, VStateSurface, VTooltip, type VButtonProps } from "../components/vui";
import { collectBrowserPageSnapshot, postBrowserTelemetry } from "../app/browserTelemetry";
import { getPageInstanceId } from "../app/pageInstance";
import { resolvePollingInterval, usePageVisibility, useStartupWarmup } from "../app/pollingPolicy";
import type { TranslationKey } from "../i18n/dictionary";
import { PaneCollapseHandle } from "../components/layout/PaneCollapseHandle";
import { petAvatarPresetLabel } from "../i18n/petLabels";
import { useAppI18n } from "../i18n/useAppI18n";
import { useChatWorkbenchStore } from "../store/chatWorkbenchStore";
import {
  clampPercent,
  contextUsagePercent,
  formatContextUsage,
  formatRelativeTime,
} from "./chatShellFormat";
import {
  deriveSessionDetailQueryErrorState,
  deriveSessionListQueryErrorState,
  mergeSessionDetailMessageWindow,
  mergeSessionDetailIntoSummaries,
  renameSessionDetail,
  renameSessionInSummaries,
} from "./chatSessionState";
import {
  SESSION_INDEX_PAGE_SIZE,
  captureAgentSessionCacheSnapshots,
  captureSessionIndexCacheSnapshots,
  removeSessionFromAgentSessionCaches,
  restoreAgentSessionCacheSnapshots,
  restoreSessionIndexCacheSnapshots,
  updateSessionSummaryCaches,
  useSessionIndexQuery,
} from "./chatSessionIndexQuery";
import {
  ACTIVE_BACKGROUND_SYNC_POLL_MS,
  ACTIVE_INDEX_POLL_MS,
  resolveChatLiveQueryPolicy,
} from "./chatLiveQueryPolicy";
import {
  latestUserMessageId as deriveLatestUserMessageId,
  resolveComposerDraftValue,
  resolveLatestEditTarget,
} from "./chatComposerState";
import {
  buildVisiblePanelRows,
  getPetAvatarPresetKey,
  getPetAvatarSymbol,
  resolveChatUserDisplayName,
} from "./chatCompactPanel";
import {
  tokenSpeedSampleFromMessages,
  updateTokenSpeedTracker,
  type TokenSpeedTrackerState,
} from "./chatTokenSpeed";
import {
  browserDesktopNotificationBridge,
  createDesktopConversationNotifier,
} from "./chatDesktopNotifications";
import {
  clearPendingSelfEvolutionHandoff,
  loadPendingSelfEvolutionHandoff,
} from "./selfEvolutionHandoff";
import {
  agentDisplayInfo,
  participantAgentDisplayInfo,
  sessionAgentDisplayInfo,
} from "./agentDisplay";
import { AgentSessionTabStrip, type CliAgentRunTab } from "./AgentSessionTabStrip";
import { AgentConversationDirectory } from "./AgentConversationDirectory";
import { ConversationIndexTree } from "./ConversationIndexTree";
import {
  DEFAULT_COLLAPSED_CONVERSATION_GROUPS,
  defaultConversationGroupCollapsed,
  conversationGroupLabel,
  hasInvalidChildSessionLink,
  isRepresentedInAgentSessionTabs,
  isVisibleDirectSession,
  rootSessionIdFor,
  sessionToConversationSummary,
  useConversationIndexModel,
  type ConversationIndexDynamicGroupKey,
} from "./conversationIndexModel";
import {
  activeTurnLayerToConversationMessage,
  activeTurnLayerTextLength,
  isActiveTurnSettledByDetail,
  setActiveTurnLayerForSession,
  type ActiveTurnLayerState,
} from "./chatActiveTurnLayer";
import { createSessionAssistantDeltaScheduler } from "./sessionAssistantDeltaScheduler";
import {
  routeSessionStreamEvent,
  sessionStreamProtocolTelemetryFields,
  type SessionStreamProtocolTrace,
} from "./chatSessionStreamProtocol";
import {
  planAppliedAssistantDeltaDrain,
  planAppliedSessionDetail,
  planQueuedSessionDetail,
  type SessionStreamApplyStats,
} from "./chatStreamApplyController";
import {
  isChildSession,
  isAgentRootSession,
} from "./DirectSessionIndexItem";
import { SessionContextMenu } from "./SessionContextMenu";
import { agentCenterConfigRoute, safeAgentCenterReturnToPath } from "./agentCenterRoutes";
import {
  buildChatMentionTargets,
  tokenizeChatMentions,
  type ChatMentionTarget,
} from "./chatMentionTokens";
import { CacheDetailDialog, type CacheDonutSegment } from "./chat/CacheDetailDialog";
import {
  buildConversationComposerBridgeState,
} from "./chat/ChatConversationComposerBridge";
import { ChatFileWorkspaceTabs } from "./chat/ChatFileWorkspaceTabs";
import { ConversationIndexLoadingShell } from "./chat/ChatLoadingShell";
import { ChatSessionWorkspacePanel } from "./chat/ChatSessionWorkspacePanel";
import { LlmPayloadTracePanel } from "./chat/LlmPayloadTracePanel";
import { TokenCoreStatusPanel, type TokenCoreStatusMetric } from "./chat/TokenCoreStatusPanel";
import { ChatConversationIndexRail } from "./chat/ChatConversationIndexRail";
import { ChatStatusRail } from "./chat/ChatStatusRail";
import {
  chatStreamPerformanceNowMs,
  describeChatRouteError as describeError,
  formatTokenSpeedValue,
  isBusyPhase,
  isRunningPhase,
  isStoppingPhase,
  shouldSuppressComposerErrorForTurnError,
} from "./chat/chatCodingRouteViewModel";
import { useChatWorkbenchLayout } from "./chat/useChatWorkbenchLayout";
import {
  useChatComposerSubmitActions,
  useChatComposerTurnMutations,
} from "./chat/useChatComposerSubmit";
import {
  CLI_AGENT_RUN_TAB_PREFIX,
  CLI_AGENT_TOOL_NAME,
  buildCliAgentRunViews,
  canInputTerminal,
  cliAgentRunCloseToken,
  cliAgentRunIdFromTabId,
  cliAgentRunTabId,
  isCliAgentRunActiveForClose,
  type CliAgentRunView,
  type CliAgentTerminalSession,
} from "./chat/cliAgentRunModel";
import {
  CHAT_FEATURE_PRESETS,
  DEFAULT_CHAT_FEATURE_PRESETS,
  chatFeaturePresetShortLabel,
  type FeaturePresetKey,
} from "./chat/chatFeaturePresets";
import {
  buildCacheDonutSegments,
  type SessionCacheCompositionDiagnostics,
} from "./chat/sessionCacheComposition";
import {
  toolApprovalLabels,
  toolApprovalRiskLabel,
  toolApprovalScopeLabel,
} from "./chat/toolApprovalLabels";
import { postSubmitTelemetry } from "./chat/chatSubmitTelemetry";
import {
  MAX_COMPOSER_IMAGE_ATTACHMENTS,
  buildSessionReferencePayload,
  classifyComposerImageFiles,
  clearSessionImageAttachments,
  clearSessionReferenceAttachments,
  mergeComposerImageAttachments,
  readStoredMentalModelToggle,
  removeSessionImageAttachment,
  sessionReferenceId,
  startSessionReferenceDrag,
  writeStoredMentalModelToggle,
  type ComposerImageAttachment,
} from "./chat/chatComposerSubmitModel";
import styles from "./ChatCodingRoute.styles";

export type { CliAgentRunView, CliAgentTerminalSession } from "./chat/cliAgentRunModel";
export { canInputTerminal } from "./chat/cliAgentRunModel";

const CliAgentRunTerminalPanel = lazy(() =>
  import("./chat/CliAgentRunTerminalPanel").then((module) => ({
    default: module.CliAgentRunTerminalPanel,
  })),
);

type ActiveSkillContract = {
  status?: string;
  scope?: string;
  command?: string;
  args?: string;
  skillName?: string;
  skillPath?: string;
  skillHash?: string;
  description?: string;
  keyRules?: string[];
  activatedAt?: string;
  staleReason?: string;
};

type SessionDetailWithActiveSkill = SessionDetail & {
  activeSkillContract?: ActiveSkillContract | null;
};

function chatRoomModeLabel(mode: ChatRoomMode, lang: "zh" | "en") {
  if (mode.id === "round_robin") {
    return lang === "zh" ? "轮询讨论" : "Round robin";
  }
  if (mode.id === "opportunistic") {
    return lang === "zh" ? "抢占式讨论" : "Opportunistic";
  }
  if (mode.id === "medical_consultation_panel") {
    return lang === "zh" ? "协同问诊会诊" : "Medical consultation";
  }
  return mode.label || mode.id;
}

function chatRoomPurposeLabel(purpose: ChatRoomPurpose, lang: "zh" | "en") {
  if (purpose.id === "chat") {
    return lang === "zh" ? "聊天" : "Chat";
  }
  if (purpose.id === "discussion") {
    return lang === "zh" ? "讨论" : "Discussion";
  }
  if (purpose.id === "meeting") {
    return lang === "zh" ? "会议" : "Meeting";
  }
  if (purpose.id === "medical_triage") {
    return lang === "zh" ? "医疗分诊建议" : "Medical triage";
  }
  return purpose.label || purpose.id;
}

function contextCompositionSegmentClass(key: string) {
  switch (key) {
    case "current_user":
      return styles.contextCompositionSegmentUser;
    case "history":
      return styles.contextCompositionSegmentHistory;
    case "active_task":
      return styles.contextCompositionSegmentTask;
    case "agent_context":
      return styles.contextCompositionSegmentAgent;
    case "guidance":
      return styles.contextCompositionSegmentGuidance;
    case "skill":
    case "active_skill":
      return styles.contextCompositionSegmentSkill;
    case "attachments":
      return styles.contextCompositionSegmentAttachments;
    default:
      return styles.contextCompositionSegmentOther;
  }
}

function contextCompositionSegmentLabel(key: string, fallback: string, t: (key: TranslationKey) => string) {
  const dictionaryKey = `contextSegment_${key}` as TranslationKey;
  const translated = t(dictionaryKey);
  return translated === dictionaryKey ? (fallback || key) : translated;
}

function cacheCompositionSegmentLabel(key: string, fallback: string, t: (key: TranslationKey) => string) {
  const dictionaryKey = `cacheSegment_${key}` as TranslationKey;
  const translated = t(dictionaryKey);
  return translated === dictionaryKey ? (fallback || key) : translated;
}

function promptSegmentDisplayLabel(
  segment: Pick<SessionCacheCompositionSegment, "key" | "label" | "promptCategory">,
  lang: "zh" | "en",
  t: (key: TranslationKey) => string,
) {
  const key = (segment.key || "").trim();
  switch (key) {
    case "system_prompt":
    case "system_prompt_overhead":
      return lang === "zh" ? "系统提示词" : "system prompt";
    case "agent_protocol":
      return lang === "zh" ? "Agent 规范" : "agent protocol";
    case "tool_descriptions":
      return lang === "zh" ? "工具描述" : "tool descriptions";
    case "tool_schema":
      return lang === "zh" ? "工具 schema" : "tool schema";
    case "provider_unmapped":
      return lang === "zh" ? "Provider 未映射" : "provider unmapped";
    case "agent_runtime":
      return lang === "zh" ? "Agent 运行规范" : "agent runtime rules";
    case "prompt_template":
      return lang === "zh" ? "Agent 提示模板" : "agent prompt template";
    case "project_rules":
      return lang === "zh" ? "项目规范" : "project rules";
    case "research_organization":
      return lang === "zh" ? "研究组织上下文" : "research organization context";
    case "project_agent_registry":
      return lang === "zh" ? "Agent registry" : "agent registry";
    case "agent_messages":
      return lang === "zh" ? "Agent 消息" : "agent messages";
    case "provider_extra_hit":
      return lang === "zh" ? "厂商额外命中" : "provider extra";
    default:
      return contextCompositionSegmentLabel(key, segment.label || key, t);
  }
}

function cacheCalibrationSummaryLabel(
  status: string,
  reason: string,
  overestimatedTokens: number,
  extraCachedTokens: number,
  numberFormatter: Intl.NumberFormat,
  lang: "zh" | "en",
) {
  const normalizedStatus = (status || "").trim();
  const normalizedReason = (reason || "").trim();
  const providerName = /xiaomi|mimo/i.test(normalizedReason)
    ? "Xiaomi/MiMo"
    : /qwen/i.test(normalizedReason)
      ? "Qwen"
      : /openai|gpt/i.test(normalizedReason)
        ? "OpenAI"
        : lang === "zh" ? "厂商" : "provider";
  if (normalizedStatus === "aligned") {
    return lang === "zh" ? `${providerName} 真实命中与稳定前缀上界一致` : `${providerName} observed hits match the stable-prefix upper bound`;
  }
  if (normalizedStatus === "not_available") {
    return lang === "zh" ? "厂商没有返回真实缓存字段，本面板仅展示稳定前缀上界" : "Provider cache fields were not returned; showing stable-prefix upper bound only";
  }
  if (overestimatedTokens > 0) {
    return lang === "zh"
      ? `${providerName} 真实命中低于稳定前缀上界，上界未兑现 ${numberFormatter.format(overestimatedTokens)} tokens`
      : `${providerName} observed hits are below the stable-prefix upper bound by ${numberFormatter.format(overestimatedTokens)} tokens`;
  }
  if (extraCachedTokens > 0) {
    return lang === "zh"
      ? `${providerName} 返回了上界分段外的额外命中 ${numberFormatter.format(extraCachedTokens)} tokens`
      : `${providerName} reported ${numberFormatter.format(extraCachedTokens)} extra cached tokens outside upper-bound segments`;
  }
  return lang === "zh" ? "已按厂商返回的真实缓存字段校准" : "Calibrated with provider-reported cache fields";
}


type SessionDetailWindowOptions = {
  messageLimit?: number;
  beforeMessageIndex?: number;
  transcriptScope?: "all" | "window" | "none";
  signal?: AbortSignal;
};

function fetchSessionDetailWindow(
  sessionId: string | null | undefined,
  options: SessionDetailWindowOptions = {},
) {
  const normalizedSessionId = String(sessionId || "").trim();
  const params = new URLSearchParams();
  params.set("messageLimit", String(options.messageLimit ?? SESSION_DETAIL_INITIAL_MESSAGE_LIMIT));
  params.set("transcriptScope", options.transcriptScope ?? "window");
  if (options.beforeMessageIndex && options.beforeMessageIndex > 0) {
    params.set("beforeMessageIndex", String(options.beforeMessageIndex));
  }
  return fetchJson<SessionDetail>(
    `/api/sessions/${encodeURIComponent(normalizedSessionId)}?${params.toString()}`,
    { signal: options.signal },
  );
}

const SESSION_DETAIL_INITIAL_MESSAGE_LIMIT = 40;
const SESSION_DETAIL_HISTORY_PAGE_SIZE = 40;
const SESSION_STREAM_MIN_APPLY_INTERVAL_MS = 350;
const SESSION_STREAM_ROUTE_SWITCH_GRACE_MS = 4_000;

type PetInteractionAction = "feed" | "talk" | "care";
type RightIndexPanel = "conversations" | "members";

type SessionContextMenuState = {
  sessionId: string;
  session: SessionSummary;
  x: number;
  y: number;
};

type AgentDirectSessionResetResponse = {
  agent: AgentInstance;
  resetSummary: {
    resetDirectSession?: boolean;
    previousDirectSessionId?: string;
    replacementDirectSessionId?: string;
  };
};

function isSessionNotFoundError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error ?? "");
  return /session not found|会话不存在|未找到会话/i.test(message);
}



function latestVisibleTurnErrorMessage(messages: ConversationMessage[] | undefined) {
  const latestMessage = messages?.[messages.length - 1];
  return latestMessage && isTurnErrorMessage(latestMessage) ? String(latestMessage.content ?? "") : "";
}

function formatAgentIdentityWithRole(name: string, role: string, fallback = "Agent") {
  const cleanName = String(name || fallback || "Agent").trim() || "Agent";
  const cleanRole = String(role || "").trim();
  return cleanRole ? `${cleanName} · ${cleanRole}` : cleanName;
}

function compactAgentRoleLabel(role: string, fallback = "") {
  const cleanRole = String(role || "").trim();
  if (!cleanRole) {
    return String(fallback || "").trim();
  }
  const beforeSlash = cleanRole.split("/")[0]?.trim() || cleanRole;
  const beforePunctuation = beforeSlash.split(/[，,。；;：:]/)[0]?.trim() || beforeSlash;
  return beforePunctuation.length > 14 ? `${beforePunctuation.slice(0, 14)}...` : beforePunctuation;
}

function shouldCollapseGroupMessage(content: string) {
  const text = String(content || "").trim();
  return text.length > 260 || text.split(/\r?\n/).length > 8;
}

function shouldDefaultCollapseGroupMessage(message: ChatRoomMessage) {
  return message.audience === "internal" || message.visibility === "collapsed_by_default";
}

function agentRoleClass(tone: string) {
  return `agentRoleTag_${tone}`;
}

function avatarInitials(agentCode?: string, name?: string, fallback = "AI") {
  const code = String(agentCode ?? "").trim();
  const numericTail = code.match(/\d{2,}$/)?.[0];
  if (numericTail) {
    return numericTail.slice(-2);
  }
  const compactCode = code.replace(/[^A-Za-z0-9]/g, "");
  if (compactCode && compactCode.length <= 3) {
    return compactCode.slice(0, 2).toUpperCase();
  }
  const title = String(name ?? "").trim();
  return title.slice(0, 2) || fallback;
}

function avatarImageUrlFrom(...sources: unknown[]) {
  for (const source of sources) {
    if (!source || typeof source !== "object") {
      continue;
    }
    const record = source as { avatarImageUrl?: unknown; agentAvatarImageUrl?: unknown };
    const url = String(record.avatarImageUrl ?? record.agentAvatarImageUrl ?? "").trim();
    if (url) {
      return url;
    }
  }
  return "";
}

function imageInputModelIdForAgent(agent: AgentInstance | undefined, fallbackDialogueModelId = "") {
  const visionModelId = String(agent?.llmBindings?.vision?.modelId ?? "").trim();
  if (visionModelId) {
    return visionModelId;
  }
  const dialogueModelId = String(agent?.llmBindings?.dialogue?.modelId ?? "").trim();
  return dialogueModelId || String(fallbackDialogueModelId || "").trim();
}

function modelImageInputSupport(
  supportByModelId: Map<string, boolean | null>,
  modelId: string,
): boolean | null {
  const normalizedModelId = String(modelId || "").trim();
  if (!normalizedModelId || !supportByModelId.has(normalizedModelId)) {
    return null;
  }
  const support = supportByModelId.get(normalizedModelId);
  return typeof support === "boolean" ? support : null;
}

function conversationMetadataText(metadata: Record<string, unknown> | undefined, key: string) {
  const value = metadata?.[key];
  return typeof value === "string" ? value.trim() : "";
}

function renderAgentAvatar(className: string, imageUrl: string | undefined, fallback: string) {
  return (
    <span className={className} aria-hidden="true">
      {imageUrl ? <img src={imageUrl} alt="" className={styles.agentAvatarImage} /> : fallback}
    </span>
  );
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function stripGroupSpeakerPrefix(message: ChatRoomMessage, identityName = "") {
  let content = String(message.content || message.summary || "").trim();
  if (!content) {
    return "";
  }
  const code = String(message.speakerCode ?? "").trim();
  const labels = [
    message.speakerTitle,
    identityName,
    code,
  ]
    .map((item) => String(item ?? "").trim())
    .filter(Boolean);
  labels.forEach((label) => {
    content = content.replace(new RegExp(`^\\s*${escapeRegExp(label)}\\s*[:：]\\s*`), "").trim();
  });
  if (code) {
    content = content.replace(
      new RegExp(`^\\s*${escapeRegExp(code)}\\s*[·\\-]\\s*[^\\n:：]{1,40}\\s*[:：]\\s*`),
      "",
    ).trim();
  }
  return content;
}

function isAvailableGroupParticipant(participant: ChatRoomParticipant) {
  return !participant.agentMissing && participant.enabled !== false;
}

function removeDeletedSessionFromConversations(
  conversations: ConversationSummary[] | undefined,
  deletedSessionId: string,
): ConversationSummary[] | undefined {
  if (!conversations) {
    return conversations;
  }
  return conversations.filter((conversation) => {
    if (conversation.type !== "direct_agent") {
      return true;
    }
    return conversation.directSessionId !== deletedSessionId && conversation.conversationId !== deletedSessionId;
  });
}

function mergeSessionDetailIntoConversations(
  conversations: ConversationSummary[] | undefined,
  detail: SessionDetail,
): ConversationSummary[] | undefined {
  if (!conversations) {
    return conversations;
  }
  const nextConversation = sessionToConversationSummary(detail);
  const existingIndex = conversations.findIndex(
    (conversation) =>
      conversation.type === "direct_agent"
      && (conversation.directSessionId === detail.id || conversation.conversationId === detail.id),
  );
  if (existingIndex < 0) {
    return [nextConversation, ...conversations];
  }
  return conversations.map((conversation, index) =>
    index === existingIndex
      ? {
          ...conversation,
          ...nextConversation,
        }
      : conversation,
  );
}

function renameSessionInConversations(
  conversations: ConversationSummary[] | undefined,
  sessionId: string,
  title: string,
  updatedAt: string,
  session?: SessionSummary | SessionDetail,
): ConversationSummary[] | undefined {
  if (!conversations || !sessionId) {
    return conversations;
  }

  return conversations.map((conversation) => {
    const directSessionId = String(conversation.directSessionId || conversation.conversationId || "").trim();
    if (conversation.type !== "direct_agent" || directSessionId !== sessionId) {
      return conversation;
    }
    if (session && isAgentRootSession(session)) {
      return {
        ...conversation,
        title,
        agentDisplayName: title,
        updatedAt,
      };
    }
    return {
      ...conversation,
      title,
      updatedAt,
    };
  });
}

function latestSessionMessageId(detail: SessionDetail): string {
  const messages = detail.messages ?? [];
  return messages[messages.length - 1]?.id ?? "";
}

function latestSessionMessageSignal(detail: SessionDetail): string {
  const messages = detail.messages ?? [];
  const message = messages[messages.length - 1];
  if (!message) {
    return "";
  }
  return [
    message.id ?? "",
    message.streaming ? "streaming" : "settled",
    message.content?.length ?? 0,
    message.toolCalls?.length ?? 0,
    message.feedbackEvents?.length ?? 0,
  ].join(":");
}

function sessionDetailSnapshotKey(detail: SessionDetail): string {
  return [
    detail.id,
    detail.status ?? "",
    detail.currentPhase ?? "",
    detail.updatedAt ?? "",
    detail.messages?.length ?? 0,
    latestSessionMessageId(detail),
    latestSessionMessageSignal(detail),
  ].join("|");
}

function normalizedLedgerSeq(value: unknown): number {
  const numeric = Number(value ?? 0);
  return Number.isFinite(numeric) && numeric > 0 ? numeric : 0;
}

function isStaleLedgerUpdate(currentSeq: unknown, incomingSeq: unknown): boolean {
  const current = normalizedLedgerSeq(currentSeq);
  const incoming = normalizedLedgerSeq(incomingSeq);
  return current > 0 && incoming > 0 && incoming < current;
}

function latestMentalSnapshot(messages: ConversationMessage[] | undefined): MentalStateSnapshot | undefined {
  return [...(messages ?? [])].reverse().find((message) => message.role === "assistant" && message.mentalSnapshot)?.mentalSnapshot;
}

function latestChatRoomRound(room: ChatRoomDetail | null | undefined) {
  const rounds = room?.rounds ?? [];
  return rounds.length ? rounds[rounds.length - 1] : null;
}

export function ChatCodingRoute() {
  const { lang, t, statusLabel } = useAppI18n();
  const queryClient = useQueryClient();
  const chatWorkspaceCache = useMemo(() => createChatWorkspaceCache(queryClient), [queryClient]);
  const navigate = useNavigate();
  const location = useLocation();
  const activeSessionId = useChatWorkbenchStore((state) => state.activeSessionId);
  const sessionWorkspaces = useChatWorkbenchStore((state) => state.sessionWorkspaces);
  const setActiveSession = useChatWorkbenchStore((state) => state.setActiveSession);
  const hydrateSession = useChatWorkbenchStore((state) => state.hydrateSession);
  const removeSessionWorkspace = useChatWorkbenchStore((state) => state.removeSession);
  const closePreviewTab = useChatWorkbenchStore((state) => state.closePreviewTab);
  const latestDirectSessionSelectionRef = useRef("");
  const reselectDirectSessionRef = useRef<(sessionId: string) => void>(() => undefined);
  const setActiveTab = useChatWorkbenchStore((state) => state.setActiveTab);
  const [sessionFilter, setSessionFilter] = useState("");
  const [cacheDetailOpen, setCacheDetailOpen] = useState(false);
  const imageUploadInFlightRef = useRef<Record<string, boolean>>({});
  const [sessionDrafts, setSessionDrafts] = useState<Record<string, string>>({});
  const [sessionComposerErrors, setSessionComposerErrors] = useState<Record<string, string>>({});
  const [sessionImageAttachments, setSessionImageAttachments] = useState<Record<string, ComposerImageAttachment[]>>({});
  const [sessionReferenceAttachments, setSessionReferenceAttachments] = useState<Record<string, SessionReferenceAttachment[]>>({});
  const [sessionImageUploadPending, setSessionImageUploadPending] = useState<Record<string, boolean>>({});
  const [sessionEditTargets, setSessionEditTargets] = useState<Record<string, { messageId: string; original: string }>>({});
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingSessionTitle, setEditingSessionTitle] = useState("");
  const [sessionContextMenu, setSessionContextMenu] = useState<SessionContextMenuState | null>(null);
  const [sessionStreamConnected, setSessionStreamConnected] = useState(false);
  const [activeTurnLayersBySession, setActiveTurnLayersBySession] = useState<Record<string, ActiveTurnLayerState>>({});
  const [groupStreamConnected, setGroupStreamConnected] = useState(false);
  const [tokenSpeedTracker, setTokenSpeedTracker] = useState<TokenSpeedTrackerState | null>(null);
  const [petActionFeedback, setPetActionFeedback] = useState("");
  const [mentalModelEnabledForNextTurn, setMentalModelEnabledForNextTurn] = useState<boolean>(
    () => readStoredMentalModelToggle() ?? false,
  );
  const [featurePresetState, setFeaturePresetState] = useState<Record<FeaturePresetKey, boolean>>(
    DEFAULT_CHAT_FEATURE_PRESETS,
  );
  const [groupComposerOpen, setGroupComposerOpen] = useState(false);
  const [groupTitleDraft, setGroupTitleDraft] = useState("");
  const [groupModeDraft, setGroupModeDraft] = useState("round_robin");
  const [groupPurposeDraft, setGroupPurposeDraft] = useState("discussion");
  const [groupSelectedAgentIds, setGroupSelectedAgentIds] = useState<string[]>([]);
  const [collapsedConversationGroups, setCollapsedConversationGroups] = useState<Record<string, boolean>>(
    DEFAULT_COLLAPSED_CONVERSATION_GROUPS,
  );
  const [rightIndexPanel, setRightIndexPanel] = useState<RightIndexPanel>("conversations");
  const [agentCreateWizardOpen, setAgentCreateWizardOpen] = useState(false);
  const agentCreateTriggerRef = useRef<HTMLButtonElement | null>(null);
  const [activeGroupRoomId, setActiveGroupRoomId] = useState("");
  const [expandedGroupAgentSessionIds, setExpandedGroupAgentSessionIds] = useState<string[]>([]);
  const [expandedGroupMessageIds, setExpandedGroupMessageIds] = useState<string[]>([]);
  const [groupTopicDraft, setGroupTopicDraft] = useState("");
  const [projectBusDraft, setProjectBusDraft] = useState("");
  const [projectBusInterruptTargets, setProjectBusInterruptTargets] = useState(false);
  const [groupRoomActionError, setGroupRoomActionError] = useState("");
  const [groupManageTitleDraft, setGroupManageTitleDraft] = useState("");
  const [groupManageSessionIds, setGroupManageSessionIds] = useState<string[]>([]);
  const [groupManageModeDraft, setGroupManageModeDraft] = useState("round_robin");
  const [groupManagePurposeDraft, setGroupManagePurposeDraft] = useState("discussion");
  const [closedCliAgentRunTokensBySession, setClosedCliAgentRunTokensBySession] = useState<Record<string, string[]>>({});
  const [cliAgentTerminalSessions, setCliAgentTerminalSessions] = useState<Record<string, CliAgentTerminalSession>>({});
  const [mountedCliAgentRunIdsBySession, setMountedCliAgentRunIdsBySession] = useState<Record<string, string[]>>({});
  const sessionStreamErrorLoggedRef = useRef<Record<string, boolean>>({});
  const sessionStreamPayloadErrorLoggedRef = useRef<Record<string, boolean>>({});
  const sessionStreamApplyStatsRef = useRef<Record<string, SessionStreamApplyStats>>({});
  const lastConversationStreamingFrameTelemetryAtRef = useRef<Record<string, number>>({});
  const lastAssistantDeltaAppliedAtRef = useRef<Record<string, number>>({});
  const activeTurnLayersBySessionRef = useRef<Record<string, ActiveTurnLayerState>>({});
  const desktopConversationNotifierRef = useRef(createDesktopConversationNotifier({
    bridge: browserDesktopNotificationBridge(),
    postTelemetry: postBrowserTelemetry,
  }));
  const sessionStreamDecisionSnapshotRef = useRef({
    sessionId: "",
    shouldConnect: false,
    pageVisible: false,
    chatStartupWarmupActive: false,
    chatPollingVisible: false,
    directSessionBackgroundSyncActive: false,
    routeTargetMatches: false,
    routeSettling: false,
    routeSwitchGraceActive: false,
    routeSwitchGraceMsRemaining: 0,
  });
  const groupStreamErrorLoggedRef = useRef<Record<string, boolean>>({});
  const groupStreamPayloadErrorLoggedRef = useRef<Record<string, boolean>>({});
  const chatRouteMountStartedAtRef = useRef(Date.now());
  const chatRouteShellMountedLoggedRef = useRef(false);
  const chatRouteStartupReadyLoggedRef = useRef(false);
  const chatRouteLongTaskCountRef = useRef(0);
  const requestedSessionId = useMemo(() => {
    return new URLSearchParams(location.search).get("session") ?? "";
  }, [location.search]);
  const requestedRoomId = useMemo(() => {
    return new URLSearchParams(location.search).get("room") ?? "";
  }, [location.search]);
  const chatReturnTarget = useMemo(() => {
    return safeAgentCenterReturnToPath(new URLSearchParams(location.search).get("returnTo"));
  }, [location.search]);
  const chatReturnLabel = useMemo(() => {
    const raw = String(new URLSearchParams(location.search).get("returnLabel") || "").trim();
    if (!raw || raw.length > 80) {
      return lang === "zh" ? "返回来源" : "Back";
    }
    return raw;
  }, [lang, location.search]);
  useEffect(() => {
    activeTurnLayersBySessionRef.current = activeTurnLayersBySession;
  }, [activeTurnLayersBySession]);
  useEffect(() => {
    if (chatRouteShellMountedLoggedRef.current) {
      return;
    }
    chatRouteShellMountedLoggedRef.current = true;
    postBrowserTelemetry({
      phase: "navigation",
      eventCode: "browser.chat_route.shell_mounted",
      message: "Chat route shell mounted.",
      fields: {
        durationMs: Math.max(0, Date.now() - chatRouteMountStartedAtRef.current),
        pathname: location.pathname,
        requestedSession: Boolean(requestedSessionId),
        requestedRoom: Boolean(requestedRoomId),
        activeSession: Boolean(activeSessionId),
      },
    });
  }, [activeSessionId, location.pathname, requestedRoomId, requestedSessionId]);
  useEffect(() => {
    if (typeof PerformanceObserver === "undefined") {
      return undefined;
    }
    const observer = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (chatRouteLongTaskCountRef.current >= 8) {
          observer.disconnect();
          return;
        }
        chatRouteLongTaskCountRef.current += 1;
        postBrowserTelemetry({
          phase: "navigation",
          eventCode: "browser.chat_route.long_task",
          message: "Chat route long task observed.",
          fields: {
            durationMs: Math.round(entry.duration),
            startTimeMs: Math.round(entry.startTime),
            count: chatRouteLongTaskCountRef.current,
          },
        });
      }
      return undefined;
    });
    try {
      observer.observe({ entryTypes: ["longtask"] });
    } catch {
      return undefined;
    }
    return () => observer.disconnect();
  }, []);
  const pageVisible = usePageVisibility();
  const [chatStartupDataReady, setChatStartupDataReady] = useState(false);
  const [startupDetailSettledSessionId, setStartupDetailSettledSessionId] = useState("");
  const chatStartupWarmupActive = useStartupWarmup(chatStartupDataReady);
  const chatPollingVisible = pageVisible || chatStartupWarmupActive;
  const projectBusActive = activeGroupRoomId === "__project_agent_bus__";
  const groupPanelActive = Boolean(activeGroupRoomId);
  const standardGroupRoomActive = groupPanelActive && !projectBusActive;
  const {
    layoutRef,
    dragState,
    responsiveLayout,
    conversationIndexCollapsed,
    statusRailCollapsed,
    conversationIndexOverlayOpen,
    statusRailOverlayOpen,
    responsiveOverlayOpen,
    layoutStyle,
    chatLayoutClassName,
    centerPaneClassName,
    statusRailClassName,
    conversationIndexPaneClassName,
    handleResizeStart,
    handleResizeKeyDown,
    closeResponsiveOverlayPane,
    setLeftRailCollapsed,
    setRightPaneCollapsed,
    setResponsiveOverlayPane,
  } = useChatWorkbenchLayout({ standardGroupRoomActive });
  const directSessionPanelActive = Boolean(activeSessionId) && !groupPanelActive;
  const sessionQueryText = sessionFilter.trim();
  const [directSessionBackgroundSyncActive, setDirectSessionBackgroundSyncActive] = useState(false);
  const [groupBackgroundSyncActive, setGroupBackgroundSyncActive] = useState(false);
  const secondaryChatDataEnabled = chatStartupDataReady && (
    !activeSessionId || startupDetailSettledSessionId === activeSessionId
  );
  const sessionStreamRouteTargetMatches = Boolean(
    activeSessionId
    && !groupPanelActive
    && (!requestedSessionId || requestedSessionId === activeSessionId),
  );

  useEffect(() => {
    if (!sessionContextMenu) {
      return;
    }
    function closeSessionContextMenu() {
      setSessionContextMenu(null);
    }
    function handleKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        closeSessionContextMenu();
      }
    }
    window.addEventListener("pointerdown", closeSessionContextMenu);
    window.addEventListener("scroll", closeSessionContextMenu, true);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("pointerdown", closeSessionContextMenu);
      window.removeEventListener("scroll", closeSessionContextMenu, true);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [sessionContextMenu]);
  const sessionStreamRouteSettling = Boolean(
    activeSessionId
    && !groupPanelActive
    && requestedSessionId
    && requestedSessionId !== activeSessionId,
  );
  const sessionStreamGraceSessionRef = useRef("");
  const sessionStreamGraceUntilRef = useRef(0);
  if (activeSessionId && sessionStreamGraceSessionRef.current !== activeSessionId) {
    sessionStreamGraceSessionRef.current = activeSessionId;
    sessionStreamGraceUntilRef.current = Date.now() + SESSION_STREAM_ROUTE_SWITCH_GRACE_MS;
  }
  const sessionStreamRouteSwitchGraceActive = Boolean(
    activeSessionId
    && sessionStreamRouteTargetMatches
    && sessionStreamGraceSessionRef.current === activeSessionId
    && Date.now() < sessionStreamGraceUntilRef.current,
  );
  const sessionStreamShouldConnect = Boolean(
    activeSessionId
    && sessionStreamRouteTargetMatches
    && (chatPollingVisible || sessionStreamRouteSwitchGraceActive),
  );
  sessionStreamDecisionSnapshotRef.current = {
    sessionId: activeSessionId || "",
    shouldConnect: sessionStreamShouldConnect,
    pageVisible,
    chatStartupWarmupActive,
    chatPollingVisible,
    directSessionBackgroundSyncActive,
    routeTargetMatches: sessionStreamRouteTargetMatches,
    routeSettling: sessionStreamRouteSettling,
    routeSwitchGraceActive: sessionStreamRouteSwitchGraceActive,
    routeSwitchGraceMsRemaining: Math.max(0, sessionStreamGraceUntilRef.current - Date.now()),
  };
  const groupStreamShouldConnect = Boolean(
    standardGroupRoomActive
    && activeGroupRoomId
    && (chatPollingVisible || groupBackgroundSyncActive),
  );
  const sessionStreamAvailable = typeof EventSource !== "undefined";
  const chatLiveQueryPolicyInput = {
    chatPollingVisible,
    chatStartupWarmupActive,
    directSessionBackgroundSyncActive,
    groupBackgroundSyncActive,
    directSessionPanelActive,
    standardGroupRoomActive,
    sessionStreamAvailable,
    sessionStreamShouldConnect,
    groupStreamShouldConnect,
    activeSessionId: activeSessionId || "",
    activeRootSessionId: "",
  };
  const chatLiveQueryPolicy = resolveChatLiveQueryPolicy(chatLiveQueryPolicyInput);
  const { groupStreamOwnsLiveQueries } = chatLiveQueryPolicy;
  useEffect(() => {
    if (!standardGroupRoomActive && rightIndexPanel === "members") {
      setRightIndexPanel("conversations");
    }
  }, [standardGroupRoomActive, rightIndexPanel]);

  const runtimeQuery = useQuery({
    queryKey: queryKeys.runtimeSummary(),
    queryFn: () => fetchJson<RuntimeSummary>("/api/runtime/summary"),
    enabled: secondaryChatDataEnabled,
    refetchInterval: resolvePollingInterval(chatPollingVisible, 5_000),
    refetchIntervalInBackground: chatStartupWarmupActive,
  });
  const petQuery = useQuery({
    queryKey: queryKeys.petSummary(),
    queryFn: () => fetchJson<PetSummary>("/api/pet/summary"),
    enabled: secondaryChatDataEnabled,
    refetchInterval: resolvePollingInterval(chatPollingVisible, 10_000),
    refetchIntervalInBackground: chatStartupWarmupActive,
  });
  const configSummaryQuery = useQuery({
    queryKey: queryKeys.configPublic(),
    queryFn: () => fetchJson<ConfigSummary>("/api/config/public"),
    staleTime: 30_000,
  });
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const activeSessionBootstrapQuery = useQuery({
    queryKey: ["sessions", "active-bootstrap"],
    queryFn: ({ signal }) => fetchJson<{ activeSessionId: string }>("/api/sessions/active", { signal }),
    staleTime: 5_000,
  });
  // Prefer URL targets immediately; otherwise wait for active-session bootstrap (empty id still settles).
  const sessionIndexQueryEnabled =
    Boolean(requestedSessionId || requestedRoomId)
    || activeSessionBootstrapQuery.isFetched;
  const modelLabelsById = useMemo(
    () => new Map(Object.entries(configSummaryQuery.data?.modelLabels ?? {})),
    [configSummaryQuery.data?.modelLabels],
  );
  const modelImageInputSupportById = useMemo(
    () => new Map(Object.entries(configSummaryQuery.data?.modelImageInputSupport ?? {})),
    [configSummaryQuery.data?.modelImageInputSupport],
  );
  const resolveModelLabel = useCallback(
    (modelId: string) => modelLabelsById.get(modelId),
    [modelLabelsById],
  );
  const rawSessionsQuery = useSessionIndexQuery({
    queryClient,
    queryText: sessionQueryText,
    enabled: sessionIndexQueryEnabled,
    refetchInterval: chatLiveQueryPolicy.sessionsRefetchInterval,
    refetchIntervalInBackground: chatLiveQueryPolicy.directRefetchIntervalInBackground,
  });
  const visibleSessionsData = useMemo(
    () => rawSessionsQuery.data?.filter(isVisibleDirectSession),
    [rawSessionsQuery.data],
  );
  const sessionsQuery = useMemo(
    () => ({
      ...rawSessionsQuery,
      data: visibleSessionsData,
    }),
    [rawSessionsQuery, visibleSessionsData],
  );
  const conversationsQuery = useQuery({
    queryKey: queryKeys.conversations(),
    queryFn: () => fetchJson<ConversationSummary[]>("/api/conversations"),
    enabled: secondaryChatDataEnabled,
    refetchInterval: chatLiveQueryPolicy.conversationsRefetchInterval,
    refetchIntervalInBackground: chatLiveQueryPolicy.sharedRefetchIntervalInBackground,
  });
  const teamsQuery = useQuery({
    queryKey: queryKeys.teams(),
    queryFn: () => fetchJson<TeamListPayload>("/api/teams"),
    enabled: secondaryChatDataEnabled,
    refetchInterval: resolvePollingInterval(chatPollingVisible, directSessionPanelActive ? false : ACTIVE_INDEX_POLL_MS),
    refetchIntervalInBackground: chatStartupWarmupActive,
  });
  const agentsQuery = useQuery({
    queryKey: queryKeys.agents(),
    queryFn: () => fetchJson<AgentInstance[]>("/api/agents?detail=summary"),
    enabled: secondaryChatDataEnabled || groupComposerOpen || standardGroupRoomActive,
  });
  const skillsQuery = useQuery({
    queryKey: queryKeys.skills(),
    queryFn: () => fetchJson<SkillLibraryPayload>("/api/skills"),
    enabled: secondaryChatDataEnabled && Boolean(activeSessionId),
    staleTime: 60_000,
  });
  const slashCommandSuggestions = skillsQuery.data?.skills ?? [];
  const chatRoomModesQuery = useQuery({
    queryKey: queryKeys.chatRoomModes(),
    queryFn: () => fetchJson<ChatRoomMode[]>("/api/chat-rooms/modes"),
    enabled: groupComposerOpen || standardGroupRoomActive,
  });
  const chatRoomPurposesQuery = useQuery({
    queryKey: queryKeys.chatRoomPurposes(),
    queryFn: () => fetchJson<ChatRoomPurpose[]>("/api/chat-rooms/purposes"),
    enabled: groupComposerOpen || standardGroupRoomActive,
  });
  const activeGroupRoomQuery = useQuery({
    queryKey: queryKeys.chatRoom(activeGroupRoomId || "none"),
    queryFn: () => fetchJson<ChatRoomDetail>(`/api/chat-rooms/${activeGroupRoomId}`),
    enabled: standardGroupRoomActive,
    refetchInterval: standardGroupRoomActive
      ? resolvePollingInterval(
          chatPollingVisible,
          groupStreamConnected ? false : 3_000,
          { backgroundMs: groupBackgroundSyncActive && !groupStreamConnected ? ACTIVE_BACKGROUND_SYNC_POLL_MS : false },
        )
      : false,
    refetchIntervalInBackground: chatStartupWarmupActive || groupBackgroundSyncActive,
  });
  const projectAgentBusQuery = useQuery({
    queryKey: queryKeys.projectAgentBus(),
    queryFn: ({ signal }) => listProjectAgentBusTimeline(undefined, { signal }),
    enabled: projectBusActive,
    refetchInterval: projectBusActive ? resolvePollingInterval(chatPollingVisible, 3_000) : false,
    refetchIntervalInBackground: chatStartupWarmupActive,
  });
  const expandedGroupAgentDetailQueries = useQueries({
    queries: expandedGroupAgentSessionIds.map((sessionId) => ({
      queryKey: queryKeys.session(sessionId || "none"),
      queryFn: () => fetchSessionDetailWindow(sessionId, { messageLimit: 20 }),
      enabled: standardGroupRoomActive && Boolean(sessionId),
      refetchInterval: standardGroupRoomActive && sessionId
        ? resolvePollingInterval(
            chatPollingVisible,
            3_000,
            { backgroundMs: groupBackgroundSyncActive && !groupStreamConnected ? ACTIVE_BACKGROUND_SYNC_POLL_MS : false },
          )
        : false,
      refetchIntervalInBackground: chatStartupWarmupActive || groupBackgroundSyncActive,
    })),
  });
  const syncSessionDetail = useCallback(
    (detail: SessionDetail) => {
      let shouldSyncSummaries = true;
      queryClient.setQueryData<SessionDetail>(queryKeys.session(detail.id), (previous) => {
        if (isStaleLedgerUpdate(previous?.ledgerSeq, detail.ledgerSeq)) {
          shouldSyncSummaries = false;
          return previous ?? detail;
        }
        const nextDetail = mergeSessionDetailMessageWindow(previous, detail);
        if (previous && sessionDetailSnapshotKey(previous) === sessionDetailSnapshotKey(nextDetail)) {
          shouldSyncSummaries = false;
          return previous;
        }
        return nextDetail;
      });
      if (!shouldSyncSummaries) {
        return;
      }
      updateSessionSummaryCaches(queryClient, (sessions) =>
        mergeSessionDetailIntoSummaries(sessions, detail),
      );
      const detailRootSessionId = rootSessionIdFor(detail);
      if (isChildSession(detail) && detailRootSessionId) {
        queryClient.setQueryData<SessionSummary[]>(queryKeys.sessionChildSessions(detailRootSessionId), (sessions) =>
          mergeSessionDetailIntoSummaries(sessions, detail),
        );
      }
      queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations(), (conversations) =>
        mergeSessionDetailIntoConversations(conversations, detail),
      );
    },
    [queryClient],
  );
  const clearSessionTransientUiState = useCallback(
    (sessionId: string) => {
      const normalizedSessionId = String(sessionId || "").trim();
      if (!normalizedSessionId) {
        return;
      }
      setActiveTurnLayersBySession((current) =>
        setActiveTurnLayerForSession(current, normalizedSessionId, undefined)
      );
      setSessionDrafts((current) => {
        const { [normalizedSessionId]: _removed, ...remaining } = current;
        return remaining;
      });
      setSessionImageAttachments((current) => clearSessionImageAttachments(current, normalizedSessionId));
      setSessionReferenceAttachments((current) => clearSessionReferenceAttachments(current, normalizedSessionId));
      delete imageUploadInFlightRef.current[normalizedSessionId];
      setSessionImageUploadPending((current) => {
        const { [normalizedSessionId]: _removed, ...remaining } = current;
        return remaining;
      });
      setSessionComposerErrors((current) => {
        const { [normalizedSessionId]: _removed, ...remaining } = current;
        return remaining;
      });
      void queryClient.cancelQueries({ queryKey: queryKeys.session(normalizedSessionId), exact: true });
      queryClient.removeQueries({ queryKey: queryKeys.session(normalizedSessionId), exact: true });
    },
    [queryClient],
  );
  const selectDirectSessionMutation = useMutation({
    mutationFn: async (sessionId: string) =>
      fetchJson<SessionDetail>(`/api/sessions/${encodeURIComponent(sessionId)}/select`, {
        method: "POST",
      }),
    onSuccess: (nextDetail) => {
      const latestSessionId = latestDirectSessionSelectionRef.current;
      if (latestSessionId && latestSessionId !== nextDetail.id) {
        reselectDirectSessionRef.current(latestSessionId);
        return;
      }
      setSessionComposerErrors((current) => ({
        ...current,
        [nextDetail.id]: "",
        __sessions__: "",
      }));
      syncSessionDetail(nextDetail);
      void chatWorkspaceCache.afterSessionSelected();
    },
    onError: (error, sessionId) => {
      if (latestDirectSessionSelectionRef.current !== sessionId) {
        return;
      }
      setSessionComposerErrors((current) => ({
        ...current,
        [sessionId]: describeError(error, lang === "zh" ? "选择会话失败" : "Select session failed"),
      }));
      void chatWorkspaceCache.refreshSessionRuntime(sessionId);
    },
  });
  reselectDirectSessionRef.current = (sessionId: string) => {
    const normalizedSessionId = String(sessionId || "").trim();
    if (!normalizedSessionId) {
      return;
    }
    selectDirectSessionMutation.mutate(normalizedSessionId);
  };
  const syncChatRoomDetail = useCallback(
    (room: ChatRoomDetail) => {
      queryClient.setQueryData(queryKeys.chatRoom(room.roomId), room);
      if (String(room.status ?? "").trim().toLowerCase() !== "running") {
        void chatWorkspaceCache.afterChatRoomChanged(room.roomId);
      }
    },
    [chatWorkspaceCache, queryClient],
  );
  const directSessionActiveSummary = useMemo(
    () => (activeSessionId ? sessionsQuery.data?.find((session) => session.id === activeSessionId) : undefined),
    [activeSessionId, sessionsQuery.data],
  );
  useEffect(() => {
    setGroupBackgroundSyncActive(Boolean(
      standardGroupRoomActive
      && isBusyPhase(activeGroupRoomQuery.data?.status),
    ));
  }, [activeGroupRoomQuery.data?.status, standardGroupRoomActive]);
  useEffect(() => {
    if (requestedSessionId || requestedRoomId || activeSessionId) {
      return;
    }
    const bootstrapSessionId = activeSessionBootstrapQuery.data?.activeSessionId?.trim() ?? "";
    if (!bootstrapSessionId) {
      return;
    }
    setActiveGroupRoomId("");
    setActiveSession(bootstrapSessionId);
  }, [
    activeSessionBootstrapQuery.data?.activeSessionId,
    activeSessionId,
    requestedRoomId,
    requestedSessionId,
    setActiveGroupRoomId,
    setActiveSession,
  ]);

  useEffect(() => {
    if (requestedRoomId && activeGroupRoomId !== requestedRoomId) {
      setActiveGroupRoomId(requestedRoomId);
      setRightIndexPanel("members");
      setRightPaneCollapsed(false);
      setGroupRoomActionError("");
      return;
    }
    if (
      requestedSessionId
      && !requestedRoomId
      && activeSessionId !== requestedSessionId
    ) {
      setActiveGroupRoomId("");
      setActiveSession(requestedSessionId);
      return;
    }
    if (!activeSessionId && sessionsQuery.data && sessionsQuery.data.length > 0) {
      setActiveSession(sessionsQuery.data[0].id);
      return;
    }
  }, [activeGroupRoomId, activeSessionId, requestedRoomId, requestedSessionId, sessionsQuery.data, setActiveSession]);

  useEffect(() => {
    const pendingHandoff = loadPendingSelfEvolutionHandoff();
    if (!pendingHandoff || !sessionsQuery.data || sessionsQuery.data.length === 0) {
      return;
    }
    const matchedSession = sessionsQuery.data.find((item) => item.id === pendingHandoff.sessionId);
    const targetSessionId = matchedSession?.id || activeSessionId || sessionsQuery.data[0]?.id || "";
    if (!targetSessionId) {
      return;
    }
    if (activeSessionId !== targetSessionId) {
      setActiveSession(targetSessionId);
    }
    setSessionDrafts((current) => ({
      ...current,
      [targetSessionId]: pendingHandoff.content,
    }));
    setSessionComposerErrors((current) => ({
      ...current,
      [targetSessionId]: "",
    }));
    clearPendingSelfEvolutionHandoff();
  }, [activeSessionId, sessionsQuery.data, setActiveSession]);

  const sessionDetailQuery = useQuery({
    queryKey: queryKeys.session(activeSessionId ?? "none"),
    enabled: Boolean(activeSessionId),
    queryFn: ({ signal }) => fetchSessionDetailWindow(activeSessionId, { signal }),
    structuralSharing: (previous, next) =>
      mergeSessionDetailMessageWindow(previous as SessionDetail | undefined, next as SessionDetail),
    refetchInterval: startupDetailSettledSessionId === activeSessionId
      ? chatLiveQueryPolicy.sessionDetailRefetchInterval
      : false,
    refetchIntervalInBackground: chatLiveQueryPolicy.directRefetchIntervalInBackground,
  });
  useEffect(() => {
    if (!activeSessionId) {
      setStartupDetailSettledSessionId("");
      return;
    }
    if (
      sessionDetailQuery.isFetching
      || !sessionDetailQuery.data
      || sessionDetailQuery.data.id !== activeSessionId
    ) {
      return;
    }
    setStartupDetailSettledSessionId((current) => current === activeSessionId ? current : activeSessionId);
  }, [activeSessionId, sessionDetailQuery.data, sessionDetailQuery.isFetching]);
  const sessionLlmOptionsQuery = useQuery({
    queryKey: queryKeys.sessionLlmOptions(activeSessionId ?? "none"),
    enabled: secondaryChatDataEnabled && Boolean(activeSessionId),
    queryFn: () => fetchJson<SessionLlmOptions>(
      `/api/sessions/${encodeURIComponent(activeSessionId ?? "")}/llm-options`,
    ),
    staleTime: 30_000,
  });
  const sessionReasoningEffortMutation = useMutation({
    mutationFn: (variables: { sessionId: string; reasoningEffort: string }) =>
      fetchJson<SessionLlmOptions>(`/api/sessions/${encodeURIComponent(variables.sessionId)}/reasoning-effort`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reasoningEffort: variables.reasoningEffort }),
      }),
    onMutate: (variables) => {
      setSessionComposerErrors((current) => ({ ...current, [variables.sessionId]: "" }));
    },
    onSuccess: (payload, variables) => {
      queryClient.setQueryData(queryKeys.sessionLlmOptions(variables.sessionId), payload);
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (current) => current ? {
        ...current,
        reasoningEffort: payload.currentReasoningEffort,
      } : current);
      updateSessionSummaryCaches(queryClient, (sessions) => sessions?.map((session) => session.id === variables.sessionId ? {
        ...session,
        reasoningEffort: payload.currentReasoningEffort,
      } : session));
    },
    onError: (error, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, lang === "zh" ? "推理强度切换失败" : "Failed to change reasoning effort"),
      }));
    },
  });
  const loadEarlierSessionMessagesMutation = useMutation({
    mutationFn: (variables: { sessionId: string; beforeMessageIndex: number }) =>
      fetchSessionDetailWindow(variables.sessionId, {
        messageLimit: SESSION_DETAIL_HISTORY_PAGE_SIZE,
        beforeMessageIndex: variables.beforeMessageIndex,
        transcriptScope: "window",
      }),
    onSuccess: (page, variables) => {
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (current) =>
        mergeSessionDetailMessageWindow(current, page),
      );
    },
  });
  useEffect(() => {
    if (
      !activeSessionId
      || !sessionsQuery.data
      || !sessionDetailQuery.isError
      || !isSessionNotFoundError(sessionDetailQuery.error)
    ) {
      return;
    }
    const nextActiveSessionId = sessionsQuery.data.find((session) => session.id !== activeSessionId)?.id || "";
    clearSessionTransientUiState(activeSessionId);
    removeSessionWorkspace(activeSessionId, nextActiveSessionId || null);
    if (nextActiveSessionId) {
      setActiveSession(nextActiveSessionId);
    }
    if (nextActiveSessionId) {
      setSessionComposerErrors((current) => ({
        ...current,
        [nextActiveSessionId]: "",
      }));
    }
    updateSessionSummaryCaches(queryClient, (sessions) =>
      sessions?.filter((session) => session.id !== activeSessionId),
    );
    queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations(), (conversations) =>
      removeDeletedSessionFromConversations(conversations, activeSessionId),
    );
    setGroupManageSessionIds((current) => current.filter((sessionId) => sessionId !== activeSessionId));
    if (requestedSessionId === activeSessionId) {
      const nextSearchParams = new URLSearchParams(location.search);
      if (nextActiveSessionId) {
        nextSearchParams.set("session", nextActiveSessionId);
      } else {
        nextSearchParams.delete("session");
      }
      const nextSearch = nextSearchParams.toString();
      navigate(`${location.pathname}${nextSearch ? `?${nextSearch}` : ""}`, { replace: true });
    }
    if (nextActiveSessionId) {
      void chatWorkspaceCache.refreshSessionRuntime(nextActiveSessionId);
    } else {
      void chatWorkspaceCache.refreshConversationIndex();
    }
  }, [
    activeSessionId,
    chatWorkspaceCache,
    clearSessionTransientUiState,
    queryClient,
    location.pathname,
    location.search,
    navigate,
    removeSessionWorkspace,
    requestedSessionId,
    sessionDetailQuery.error,
    sessionDetailQuery.isError,
    sessionsQuery.data,
    setActiveSession,
  ]);
  const activeRootSessionId = rootSessionIdFor(sessionDetailQuery.data ?? directSessionActiveSummary);
  const childSessionLiveQueryPolicy = resolveChatLiveQueryPolicy({
    ...chatLiveQueryPolicyInput,
    activeRootSessionId: activeRootSessionId || "",
  });
  const childSessionsQuery = useQuery({
    queryKey: queryKeys.sessionChildSessions(activeRootSessionId || "none"),
    queryFn: () => fetchJson<SessionSummary[]>(`/api/sessions/${activeRootSessionId}/child-sessions`),
    enabled: secondaryChatDataEnabled && Boolean(activeRootSessionId) && directSessionPanelActive,
    refetchInterval: childSessionLiveQueryPolicy.childSessionsRefetchInterval,
    refetchIntervalInBackground: childSessionLiveQueryPolicy.directRefetchIntervalInBackground,
  });
  useEffect(() => {
    const directReady = Boolean(activeSessionId ? sessionDetailQuery.data : sessionsQuery.data);
    const groupReady = !standardGroupRoomActive || Boolean(activeGroupRoomQuery.data);
    if (sessionsQuery.data && directReady && groupReady) {
      setChatStartupDataReady(true);
    }
  }, [
    activeGroupRoomQuery.data,
    activeSessionId,
    standardGroupRoomActive,
    sessionDetailQuery.data,
    sessionsQuery.data,
  ]);
  useEffect(() => {
    if (!chatStartupDataReady || chatRouteStartupReadyLoggedRef.current) {
      return;
    }
    chatRouteStartupReadyLoggedRef.current = true;
    postBrowserTelemetry({
      phase: "navigation",
      eventCode: "browser.chat_route.startup_data_ready",
      message: "Chat route startup data is ready.",
      fields: {
        durationMs: Math.max(0, Date.now() - chatRouteMountStartedAtRef.current),
        activeSession: Boolean(activeSessionId),
        standardGroupRoomActive,
        runtimeReady: Boolean(runtimeQuery.data),
        sessionsReady: Boolean(sessionsQuery.data),
        conversationsReady: Boolean(conversationsQuery.data),
        teamsReady: Boolean(teamsQuery.data),
        sessionDetailReady: Boolean(activeSessionId ? sessionDetailQuery.data : true),
        groupRoomReady: Boolean(!standardGroupRoomActive || activeGroupRoomQuery.data),
      },
    });
  }, [
    activeGroupRoomQuery.data,
    activeSessionId,
    chatStartupDataReady,
    conversationsQuery.data,
    standardGroupRoomActive,
    runtimeQuery.data,
    sessionDetailQuery.data,
    sessionsQuery.data,
    teamsQuery.data,
  ]);
  useEffect(() => {
    setDirectSessionBackgroundSyncActive(Boolean(
      activeSessionId
      && directSessionPanelActive
      && isBusyPhase(sessionDetailQuery.data?.currentPhase || directSessionActiveSummary?.currentPhase || directSessionActiveSummary?.status),
    ));
  }, [
    activeSessionId,
    directSessionActiveSummary?.currentPhase,
    directSessionActiveSummary?.status,
    directSessionPanelActive,
    sessionDetailQuery.data?.currentPhase,
  ]);

  const {
    submitTurnMutation,
    editResubmitMutation,
    stopTurnMutation,
    sessionGuidanceMutation,
  } = useChatComposerTurnMutations({
    queryClient,
    chatWorkspaceCache,
    t,
    describeError,
    syncSessionDetail,
    setActiveTurnLayersBySession,
    setSessionDrafts,
    setSessionComposerErrors,
    setSessionImageAttachments,
    setSessionReferenceAttachments,
    setSessionEditTargets,
  });

  const createSessionMutation = useMutation({
    mutationFn: async ({ agentId }: { agentId: string }) =>
      fetchJson<SessionDetail>("/api/sessions", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ agentId }),
      }),
    onSuccess: (nextDetail, variables) => {
      setActiveGroupRoomId("");
      setRightIndexPanel("conversations");
      setActiveSession(nextDetail.id);
      setSelectedAgentId(String(nextDetail.agentId || variables.agentId || "").trim());
      setSessionFilter("");
      setSessionComposerErrors((current) => ({
        ...current,
        [nextDetail.id]: "",
      }));
      syncSessionDetail(nextDetail);
      if (nextDetail.agentId || variables.agentId) {
        void queryClient.invalidateQueries({ queryKey: ["sessions", "agent", String(nextDetail.agentId || variables.agentId).trim()] });
      }
      void chatWorkspaceCache.afterSessionChanged();
    },
    onError: (error) => {
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: describeError(error, t("createSessionFailed")),
      }));
      void chatWorkspaceCache.refreshConversationIndex();
    },
  });

  const createGroupRoomMutation = useMutation({
    mutationFn: async (
      { title, agentIds, mode, purpose }: { title: string; agentIds: string[]; mode: string; purpose: string },
    ) =>
      fetchJson<ChatRoomDetail>("/api/chat-rooms", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ title, agentIds, mode, purpose }),
      }),
    onSuccess: (room) => {
      setGroupComposerOpen(false);
      setGroupTitleDraft("");
      setGroupModeDraft("round_robin");
      setGroupPurposeDraft("discussion");
      setGroupSelectedAgentIds([]);
      setSessionFilter("");
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: "",
      }));
      setActiveGroupRoomId(room.roomId);
      setRightIndexPanel("members");
      queryClient.setQueryData(queryKeys.chatRoom(room.roomId), room);
      void chatWorkspaceCache.afterChatRoomChanged(room.roomId);
    },
    onError: (error) => {
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: describeError(
          error,
          lang === "zh" ? "创建群聊失败" : "Create group chat failed",
        ),
      }));
    },
  });

  const startGroupRoundMutation = useMutation({
    mutationFn: async (
      { roomId, topic, mode, purpose }: { roomId: string; topic: string; mode: string; purpose: string },
    ) =>
      fetchJson<ChatRoomRoundAcceptedResponse>(`/api/chat-rooms/${roomId}/rounds`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Prefer": "respond-async",
        },
        body: JSON.stringify({ topic, mode, purpose }),
      }),
    onSuccess: (accepted) => {
      setActiveGroupRoomId(accepted.roomId);
      setRightIndexPanel("members");
      setGroupTopicDraft("");
      setGroupRoomActionError("");
      void chatWorkspaceCache.afterGroupRoundStarted(accepted.roomId);
    },
    onError: (error) => {
      setGroupRoomActionError(describeError(error, lang === "zh" ? "启动群聊讨论失败" : "Run group discussion failed"));
      if (activeGroupRoomId) {
        void chatWorkspaceCache.afterChatRoomChanged(activeGroupRoomId);
      }
    },
  });

  const stopGroupRoundMutation = useMutation({
    mutationFn: async ({ roomId }: { roomId: string }) =>
      fetchJson<ChatRoomDetail>(`/api/chat-rooms/${roomId}/stop`, {
        method: "POST",
      }),
    onSuccess: (room) => {
      setActiveGroupRoomId(room.roomId);
      setRightIndexPanel("members");
      setGroupRoomActionError("");
      syncChatRoomDetail(room);
      void chatWorkspaceCache.afterGroupRoundStopped(room.roomId);
    },
    onError: (error, variables) => {
      setGroupRoomActionError(describeError(error, lang === "zh" ? "停止群聊讨论失败" : "Stop group discussion failed"));
      void chatWorkspaceCache.afterGroupRoundStopped(variables.roomId);
    },
  });

  const sendProjectBusMessageMutation = useMutation({
    mutationFn: async (
      {
        content,
        interruptTargets,
      }: {
        content: string;
        interruptTargets: boolean;
      },
    ) =>
      sendProjectAgentBusMessage({ content, interruptTargets }),
    onSuccess: () => {
      setProjectBusDraft("");
      setGroupRoomActionError("");
      void chatWorkspaceCache.afterProjectBusChanged();
    },
    onError: (error) => {
      setGroupRoomActionError(describeError(error, lang === "zh" ? "发送总群引导失败" : "Send project bus guidance failed"));
      void chatWorkspaceCache.afterProjectBusFailed();
    },
  });

  const revokeProjectBusMessageMutation = useMutation({
    mutationFn: async ({ eventId }: { eventId: string }) =>
      revokeProjectAgentBusMessage({
        eventId,
        reason: "user_recalled_project_bus_message",
      }),
    onSuccess: () => {
      setGroupRoomActionError("");
      void chatWorkspaceCache.afterProjectBusChanged();
    },
    onError: (error) => {
      setGroupRoomActionError(describeError(error, lang === "zh" ? "撤回总群消息失败" : "Recall project bus message failed"));
      void chatWorkspaceCache.afterProjectBusFailed();
    },
  });

  const updateGroupRoomMutation = useMutation({
    mutationFn: async (
      { roomId, title, sessionIds, mode, purpose }: {
        roomId: string;
        title: string;
        sessionIds: string[];
        mode: string;
        purpose: string;
      },
    ) =>
      fetchJson<ChatRoomDetail>(`/api/chat-rooms/${roomId}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          title,
          participantSessionIds: sessionIds,
          mode,
          purpose,
        }),
      }),
    onSuccess: (room) => {
      setActiveGroupRoomId(room.roomId);
      setRightIndexPanel("members");
      setGroupManageTitleDraft(room.title || "");
      setGroupManageSessionIds(room.participants.map((participant) => participant.sessionId));
      setGroupManageModeDraft(room.mode || "round_robin");
      setGroupManagePurposeDraft(room.purpose || "discussion");
      setGroupRoomActionError("");
      queryClient.setQueryData(queryKeys.chatRoom(room.roomId), room);
      void chatWorkspaceCache.afterChatRoomChanged(room.roomId);
    },
    onError: (error) => {
      setGroupRoomActionError(describeError(error, lang === "zh" ? "更新群聊失败" : "Update group failed"));
      if (activeGroupRoomId) {
        void chatWorkspaceCache.afterChatRoomChanged(activeGroupRoomId);
      }
    },
  });

  const deleteGroupRoomMutation = useMutation({
    mutationFn: async ({ roomId }: { roomId: string }) =>
      fetchJson<{ deleted: boolean; roomId: string }>(`/api/chat-rooms/${roomId}`, {
        method: "DELETE",
      }),
    onSuccess: (_payload, variables) => {
      setActiveGroupRoomId("");
      setRightIndexPanel("conversations");
      setGroupTopicDraft("");
      setGroupRoomActionError("");
      setGroupManageTitleDraft("");
      setGroupManageSessionIds([]);
      setGroupManageModeDraft("round_robin");
      queryClient.removeQueries({ queryKey: queryKeys.chatRoom(variables.roomId), exact: true });
      void chatWorkspaceCache.afterChatRoomChanged(variables.roomId);
    },
    onError: (error) => {
      setGroupRoomActionError(describeError(error, lang === "zh" ? "删除群聊失败" : "Delete group failed"));
    },
  });

  const resetGroupRoomMutation = useMutation({
    mutationFn: async ({ roomId }: { roomId: string }) =>
      fetchJson<ChatRoomDetail>(`/api/chat-rooms/${roomId}/reset`, {
        method: "POST",
      }),
    onSuccess: (room) => {
      setActiveGroupRoomId(room.roomId);
      setRightIndexPanel("members");
      setGroupRoomActionError("");
      syncChatRoomDetail(room);
      void chatWorkspaceCache.afterChatRoomChanged(room.roomId);
    },
    onError: (error) => {
      setGroupRoomActionError(describeError(error, lang === "zh" ? "重置群聊失败" : "Reset group failed"));
      if (activeGroupRoomId) {
        void chatWorkspaceCache.afterChatRoomChanged(activeGroupRoomId);
      }
    },
  });

  const deleteSessionMutation = useMutation({
    mutationFn: async ({ sessionId }: { sessionId: string }) =>
      fetchJson<SessionDeleteResponse>(`/api/sessions/${sessionId}`, {
        method: "DELETE",
        headers: {
          "Prefer": "respond-async",
        },
      }),
    onMutate: async (variables) => {
      await Promise.all([
        queryClient.cancelQueries({ queryKey: queryKeys.sessions() }),
        queryClient.cancelQueries({ queryKey: queryKeys.conversations() }),
        queryClient.cancelQueries({ queryKey: queryKeys.agents() }),
      ]);
      const previousSessions = queryClient.getQueryData<SessionSummary[]>(queryKeys.sessions());
      const previousSessionIndexCaches = captureSessionIndexCacheSnapshots(queryClient);
      const previousAgentSessionCaches = captureAgentSessionCacheSnapshots(queryClient);
      const previousConversations = queryClient.getQueryData<ConversationSummary[]>(queryKeys.conversations());
      const previousAgents = queryClient.getQueryData<AgentInstance[]>(queryKeys.agents());
      updateSessionSummaryCaches(queryClient, (sessions) =>
        sessions?.filter((session) => session.id !== variables.sessionId),
      );
      removeSessionFromAgentSessionCaches(queryClient, variables.sessionId);
      queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations(), (conversations) =>
        removeDeletedSessionFromConversations(conversations, variables.sessionId),
      );
      queryClient.setQueryData<AgentInstance[]>(queryKeys.agents(), (agents) =>
        agents?.filter((agent) => agent.directSessionId !== variables.sessionId),
      );
      return {
        previousSessions,
        previousSessionIndexCaches,
        previousAgentSessionCaches,
        previousConversations,
        previousAgents,
      };
    },
    onSuccess: (deleteResult, variables) => {
      const nextActiveSessionId = deleteResult.nextActiveSessionId || "";
      clearSessionTransientUiState(variables.sessionId);
      removeSessionWorkspace(variables.sessionId, nextActiveSessionId);
      setActiveSession(nextActiveSessionId);
      if (nextActiveSessionId) {
        setSessionComposerErrors((current) => ({
          ...current,
          [nextActiveSessionId]: "",
        }));
      }
      setGroupManageSessionIds((current) => current.filter((sessionId) => sessionId !== variables.sessionId));
      void chatWorkspaceCache.afterSessionDeleted({
        deletedSessionId: variables.sessionId,
        nextSessionId: nextActiveSessionId,
        roomId: activeGroupRoomId,
      });
    },
    onError: (error, variables, context) => {
      if (context?.previousSessions) {
        queryClient.setQueryData(queryKeys.sessions(), context.previousSessions);
      }
      restoreSessionIndexCacheSnapshots(queryClient, context?.previousSessionIndexCaches);
      restoreAgentSessionCacheSnapshots(queryClient, context?.previousAgentSessionCaches);
      if (context?.previousConversations) {
        queryClient.setQueryData(queryKeys.conversations(), context.previousConversations);
      }
      if (context?.previousAgents !== undefined) {
        queryClient.setQueryData(queryKeys.agents(), context.previousAgents);
      }
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("deleteSessionFailed")),
      }));
      void chatWorkspaceCache.refreshSessionRuntime(variables.sessionId);
    },
  });

  const clearSessionHistoryMutation = useMutation({
    mutationFn: async ({ sessionId, agentId }: { sessionId: string; agentId: string }) =>
      fetchJson<AgentDirectSessionResetResponse>(`/api/agents/${encodeURIComponent(agentId)}/reset`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          clearRuntimeState: false,
          resetDirectSession: true,
          directSessionId: sessionId,
          resetPersonaProfile: false,
          resetTaskProfile: false,
          resetToolPolicy: false,
          resetMemoryPolicy: false,
          resetRuntimePolicy: false,
        }),
      }),
    onSuccess: (result, variables) => {
      const previousDirectSessionId = String(
        result.resetSummary.previousDirectSessionId || variables.sessionId,
      ).trim();
      const replacementDirectSessionId = String(result.resetSummary.replacementDirectSessionId || "").trim();
      if (!result.resetSummary.resetDirectSession || !replacementDirectSessionId) {
        setSessionComposerErrors((current) => ({
          ...current,
          [variables.sessionId]: t("clearSessionHistoryFailed"),
        }));
        void chatWorkspaceCache.afterChatWorkspaceReset();
        return;
      }
      if (previousDirectSessionId) {
        clearSessionTransientUiState(previousDirectSessionId);
        queryClient.removeQueries({ queryKey: queryKeys.session(previousDirectSessionId), exact: true });
        removeSessionWorkspace(previousDirectSessionId, replacementDirectSessionId);
      }
      queryClient.setQueryData<AgentInstance[]>(queryKeys.agents(), (agents) =>
        agents?.map((agent) => (agent.agentId === result.agent.agentId ? result.agent : agent)),
      );
      setActiveSession(replacementDirectSessionId);
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
        [replacementDirectSessionId]: "",
        __sessions__: "",
      }));
      void chatWorkspaceCache.afterChatWorkspaceReset();
    },
    onError: (error, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("clearSessionHistoryFailed")),
      }));
      void chatWorkspaceCache.afterChatWorkspaceReset();
    },
  });

  const renameSessionMutation = useMutation({
    mutationFn: async ({ sessionId, title }: { sessionId: string; title: string }) =>
      fetchJson<SessionDetail>(`/api/sessions/${sessionId}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ title }),
      }),
    onMutate: (variables) => {
      const updatedAt = new Date().toISOString();
      const previousSessions = queryClient.getQueryData<SessionSummary[]>(queryKeys.sessions());
      const previousSessionIndexCaches = captureSessionIndexCacheSnapshots(queryClient);
      const previousConversations = queryClient.getQueryData<ConversationSummary[]>(queryKeys.conversations());
      const previousDetail = queryClient.getQueryData<SessionDetail>(queryKeys.session(variables.sessionId));
      const targetSession = previousDetail ?? previousSessions?.find((session) => session.id === variables.sessionId);
      setEditingSessionId(null);
      setEditingSessionTitle("");
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      updateSessionSummaryCaches(queryClient, (sessions) =>
        renameSessionInSummaries(sessions, variables.sessionId, variables.title, updatedAt),
      );
      queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations(), (conversations) =>
        renameSessionInConversations(conversations, variables.sessionId, variables.title, updatedAt, targetSession),
      );
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (detail) =>
        renameSessionDetail(detail, variables.sessionId, variables.title, updatedAt),
      );
      return { previousSessions, previousSessionIndexCaches, previousConversations, previousDetail };
    },
    onSuccess: (nextDetail, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      const confirmedTitle = String(nextDetail.title || variables.title).trim() || variables.title;
      const confirmedUpdatedAt = String(nextDetail.updatedAt || new Date().toISOString()).trim();
      updateSessionSummaryCaches(queryClient, (sessions) =>
        renameSessionInSummaries(sessions, variables.sessionId, confirmedTitle, confirmedUpdatedAt),
      );
      queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations(), (conversations) =>
        renameSessionInConversations(conversations, variables.sessionId, confirmedTitle, confirmedUpdatedAt, nextDetail),
      );
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (detail) =>
        renameSessionDetail(detail, variables.sessionId, confirmedTitle, confirmedUpdatedAt),
      );
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (detail) => ({
        ...(detail ?? nextDetail),
        ...nextDetail,
      }));
    },
    onError: (error, variables, context) => {
      if (context?.previousSessions) {
        queryClient.setQueryData(queryKeys.sessions(), context.previousSessions);
      }
      restoreSessionIndexCacheSnapshots(queryClient, context?.previousSessionIndexCaches);
      if (context?.previousConversations) {
        queryClient.setQueryData(queryKeys.conversations(), context.previousConversations);
      }
      if (context?.previousDetail) {
        queryClient.setQueryData(queryKeys.session(variables.sessionId), context.previousDetail);
      }
      setEditingSessionId(variables.sessionId);
      setEditingSessionTitle(variables.title);
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("renameSessionFailed")),
      }));
    },
  });

  const addSessionToReviewMutation = useMutation({
    mutationFn: async ({ sessionId }: { sessionId: string }) =>
      fetchJson<SessionChatReviewCandidateResponse>(
        `/api/sessions/${sessionId}/chat-review-candidate`,
        {
          method: "POST",
        },
      ),
    onSuccess: (payload, variables) => {
      const detail = payload.summary
        ? `${t("addSessionToReviewSucceeded")} ${payload.summary}`
        : t("addSessionToReviewSucceeded");
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: detail,
        __sessions__: "",
      }));
      void queryClient.invalidateQueries({ queryKey: queryKeys.evolutionChatReview() });
    },
    onError: (error, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("addSessionToReviewFailed")),
      }));
      void queryClient.invalidateQueries({ queryKey: queryKeys.evolutionChatReview() });
    },
  });

  const resolveToolApprovalMutation = useMutation({
    mutationFn: async (
      { request, decision }: {
        request: AgentToolGovernanceRequest;
        decision: "approve" | "reject";
      },
    ) =>
      fetchJson<AgentToolGovernanceRequest>(
        `/api/agents/${encodeURIComponent(request.targetAgentId)}/tool-governance-requests/${encodeURIComponent(request.requestId)}`,
        {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            decision,
            resolvedBy: "user",
            resolutionNote: decision === "approve" ? "会话内批准" : "会话内拒绝",
          }),
        },
      ),
    onSuccess: (_payload, variables) => {
      const sessionId = activeSessionId || variables.request.sourceSessionId || "";
      setSessionComposerErrors((current) => (sessionId ? { ...current, [sessionId]: "" } : current));
      if (sessionId) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.session(sessionId) });
        void chatWorkspaceCache.refreshSessionRuntime(sessionId);
      }
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentConfigWorkspace() });
      void chatWorkspaceCache.afterSessionChanged({ sessionId });
    },
    onError: (error, variables) => {
      const sessionId = activeSessionId || variables.request.sourceSessionId || "__sessions__";
      setSessionComposerErrors((current) => ({
        ...current,
        [sessionId]: describeError(error, lang === "zh" ? "处理工具审批失败" : "Resolve tool approval failed"),
      }));
    },
  });

  const petActionMutation = useMutation({
    mutationFn: async ({ action }: { action: PetInteractionAction }) =>
      fetchJson<PetActionResponse>("/api/pet/actions", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ action }),
      }),
    onSuccess: (payload) => {
      setPetActionFeedback(payload.message);
      queryClient.setQueryData(queryKeys.petSummary(), payload.summary);
      void queryClient.invalidateQueries({ queryKey: queryKeys.petSummary() });
    },
    onError: (error) => {
      setPetActionFeedback(describeError(error, lang === "zh" ? "宠物互动失败" : "Pet interaction failed"));
      void queryClient.invalidateQueries({ queryKey: queryKeys.petSummary() });
    },
  });

  const activeGroupRoom = activeGroupRoomQuery.data;
  const teams = teamsQuery.data?.teams ?? [];
  const linkedTeamRoomIds = useMemo(() => {
    return new Set(teams.map((team) => String(team.linkedChatRoomId ?? "").trim()).filter(Boolean));
  }, [teams]);
  const activeGroupTeam = useMemo(() => {
    const roomId = String(activeGroupRoom?.roomId || activeGroupRoomId || "").trim();
    const configTeamId = String((activeGroupRoom?.config ?? {}).teamId ?? "").trim();
    return teams.find((team) => {
      const teamId = String(team.teamId ?? "").trim();
      const linkedRoomId = String(team.linkedChatRoomId ?? team.linkedChatRoom?.roomId ?? "").trim();
      return (configTeamId && teamId === configTeamId) || (roomId && linkedRoomId === roomId);
    }) ?? null;
  }, [activeGroupRoom?.config, activeGroupRoom?.roomId, activeGroupRoomId, teams]);
  const activeGroupTeamOwned = Boolean(activeGroupTeam);
  const availableGroupParticipants = useMemo(
    () => (activeGroupRoom?.participants ?? []).filter(isAvailableGroupParticipant),
    [activeGroupRoom?.participants],
  );
  const availableGroupParticipantCount = availableGroupParticipants.length;

  useEffect(() => {
    if (activeSessionId && sessionDetailQuery.data) {
      hydrateSession(activeSessionId, [], "agent");
    }
  }, [activeSessionId, hydrateSession, sessionDetailQuery.data]);

  useEffect(() => {
    if (!activeGroupRoom) {
      return;
    }
    const existingSessionIds = new Set((sessionsQuery.data ?? []).map((session) => session.id));
    setGroupManageSessionIds(
      activeGroupRoom.participants
        .map((participant) => participant.sessionId)
        .filter((sessionId) => existingSessionIds.has(sessionId)),
    );
    setGroupManageTitleDraft(activeGroupRoom.title || "");
    setGroupManageModeDraft(activeGroupRoom.mode || "round_robin");
    setGroupManagePurposeDraft(activeGroupRoom.purpose || "discussion");
  }, [activeGroupRoom, sessionsQuery.data]);

  useEffect(() => {
    if (!sessionStreamShouldConnect || typeof EventSource === "undefined") {
      const decisionSnapshot = sessionStreamDecisionSnapshotRef.current;
      setSessionStreamConnected(false);
      postBrowserTelemetry({
        phase: "session_stream",
        eventCode: "browser.session_stream.skipped",
        message: "Session detail stream connection was skipped.",
        level: "info",
        fields: {
          sessionId: decisionSnapshot.sessionId,
          shouldConnect: decisionSnapshot.shouldConnect,
          pageVisible: decisionSnapshot.pageVisible,
          chatStartupWarmupActive: decisionSnapshot.chatStartupWarmupActive,
          chatPollingVisible: decisionSnapshot.chatPollingVisible,
          directSessionBackgroundSyncActive: decisionSnapshot.directSessionBackgroundSyncActive,
          routeTargetMatches: decisionSnapshot.routeTargetMatches,
          routeSettling: decisionSnapshot.routeSettling,
          routeSwitchGraceActive: decisionSnapshot.routeSwitchGraceActive,
          visibilityState: typeof document === "undefined" ? "unknown" : document.visibilityState,
          eventSourceAvailable: typeof EventSource !== "undefined",
          pageInstanceId: getPageInstanceId(),
          ...collectBrowserPageSnapshot(),
        },
      });
      return;
    }

    let disposed = false;
    const streamSessionId = String(activeSessionId || "");
    if (!streamSessionId) {
      setSessionStreamConnected(false);
      return;
    }
    let pendingDetail: SessionDetail | null = null;
    let pendingDetailTrace: SessionStreamProtocolTrace | null = null;
    let applyTimer: number | null = null;
    let lastAppliedAt = 0;
    let committedAssistantDeltaLayer: ActiveTurnLayerState | undefined = activeTurnLayersBySessionRef.current[streamSessionId];
    const assistantDeltaScheduler = createSessionAssistantDeltaScheduler({
      nowMs: chatStreamPerformanceNowMs,
    });
    let assistantDeltaApplyFrame: number | null = null;
    let frameScheduledAtMs = 0;
    let rejectedSessionStreamRouteLogged = false;
    const decisionSnapshot = sessionStreamDecisionSnapshotRef.current;
    postBrowserTelemetry({
      phase: "session_stream",
      eventCode: "browser.session_stream.effect_started",
      message: "Session detail stream effect started.",
      level: "info",
      fields: {
        sessionId: streamSessionId,
        shouldConnect: decisionSnapshot.shouldConnect,
        pageVisible: decisionSnapshot.pageVisible,
        chatStartupWarmupActive: decisionSnapshot.chatStartupWarmupActive,
        chatPollingVisible: decisionSnapshot.chatPollingVisible,
        directSessionBackgroundSyncActive: decisionSnapshot.directSessionBackgroundSyncActive,
        routeTargetMatches: decisionSnapshot.routeTargetMatches,
        routeSettling: decisionSnapshot.routeSettling,
        routeSwitchGraceActive: decisionSnapshot.routeSwitchGraceActive,
        routeSwitchGraceMsRemaining: decisionSnapshot.routeSwitchGraceMsRemaining,
        visibilityState: typeof document === "undefined" ? "unknown" : document.visibilityState,
        pageInstanceId: getPageInstanceId(),
        ...collectBrowserPageSnapshot(),
      },
    });
    const stream = new EventSource(`/api/sessions/${streamSessionId}/events?initial=light`);

    function logRejectedSessionStreamRoute(trace: SessionStreamProtocolTrace, message: string) {
      if (trace.rejectReason === "parse_error") {
        if (!sessionStreamPayloadErrorLoggedRef.current[streamSessionId]) {
          sessionStreamPayloadErrorLoggedRef.current[streamSessionId] = true;
          postBrowserTelemetry({
            phase: "session_stream",
            eventCode: "browser.session_stream.bad_payload",
            message,
            level: "warning",
            fields: {
              sessionId: streamSessionId,
              payloadLength: trace.payloadLength,
              ...sessionStreamProtocolTelemetryFields(trace),
            },
          });
        }
        return;
      }
      if (rejectedSessionStreamRouteLogged) {
        return;
      }
      rejectedSessionStreamRouteLogged = true;
      postBrowserTelemetry({
        phase: "session_stream",
        eventCode: "browser.session_stream.event_rejected",
        message: "Session stream event was rejected by the protocol router.",
        level: "info",
        fields: {
          sessionId: streamSessionId,
          ...sessionStreamProtocolTelemetryFields(trace),
        },
      });
    }

    function applyPendingDetail(reason: "timer" | "close" | "final") {
      if (!pendingDetail || disposed) {
        return;
      }
      const detail = pendingDetail;
      const trace = pendingDetailTrace;
      pendingDetail = null;
      pendingDetailTrace = null;
      if (applyTimer) {
        window.clearTimeout(applyTimer);
        applyTimer = null;
      }
      lastAppliedAt = Date.now();
      const activeLayer = activeTurnLayersBySessionRef.current[streamSessionId];
      const decision = planAppliedSessionDetail({
        streamSessionId,
        reason,
        detail,
        trace,
        stats: sessionStreamApplyStatsRef.current[streamSessionId],
        activeLayer,
        activeLayerSettled: isActiveTurnSettledByDetail(activeLayer, detail),
        isBusyPhase,
      });
      sessionStreamApplyStatsRef.current[streamSessionId] = decision.stats;
      if (decision.shouldLogApplied) {
        postBrowserTelemetry({
          phase: "session_stream",
          eventCode: "browser.session_stream.snapshot_applied",
          message: "Session detail stream snapshot was applied to the UI cache.",
          level: "info",
          fields: decision.telemetry,
        });
      }
      syncSessionDetail(detail);
      desktopConversationNotifierRef.current.handleSessionDetail(detail, {
        sessionTitle: detail.title || detail.id,
      });
      if (decision.clearActiveLayer) {
        committedAssistantDeltaLayer = undefined;
        setActiveTurnLayersBySession((current) =>
          setActiveTurnLayerForSession(current, streamSessionId, undefined)
        );
      }
    }

    function queueSessionDetail(detail: SessionDetail, trace: SessionStreamProtocolTrace) {
      const decision = planQueuedSessionDetail({
        detail,
        trace,
        pendingDetail,
        stats: sessionStreamApplyStatsRef.current[streamSessionId],
        lastAppliedAtMs: lastAppliedAt,
        nowMs: Date.now(),
        minApplyIntervalMs: SESSION_STREAM_MIN_APPLY_INTERVAL_MS,
        isBusyPhase,
      });
      sessionStreamApplyStatsRef.current[streamSessionId] = decision.stats;
      pendingDetail = decision.pendingDetail;
      pendingDetailTrace = decision.pendingDetailTrace;
      if (decision.action === "apply_now") {
        applyPendingDetail(decision.applyReason ?? "final");
        return;
      }
      if (!applyTimer) {
        applyTimer = window.setTimeout(() => {
          applyTimer = null;
          applyPendingDetail("timer");
        }, decision.delayMs);
      }
      if (decision.shouldLogQueued) {
        postBrowserTelemetry({
          phase: "session_stream",
          eventCode: "browser.session_stream.snapshot_queued",
          message: "Session detail stream snapshot was queued before UI cache apply.",
          level: "info",
          fields: {
            sessionId: streamSessionId,
            ...decision.telemetry,
          },
        });
      }
    }

    function applyPendingAssistantDeltas(reason: "frame" | "close" | "final") {
      if (assistantDeltaScheduler.pendingCount === 0 || disposed) {
        return;
      }
      const applyStartedAtMs = chatStreamPerformanceNowMs();
      if (assistantDeltaApplyFrame !== null) {
        window.cancelAnimationFrame(assistantDeltaApplyFrame);
        assistantDeltaApplyFrame = null;
      }
      const scheduledAtMs = frameScheduledAtMs;
      frameScheduledAtMs = 0;
      const drain = assistantDeltaScheduler.drain(reason, { frameScheduledAtMs: scheduledAtMs });
      const decision = planAppliedAssistantDeltaDrain({
        streamSessionId,
        reason,
        drain,
        committedLayer: committedAssistantDeltaLayer,
        stats: sessionStreamApplyStatsRef.current[streamSessionId],
        applyStartedAtMs,
        nowMs: chatStreamPerformanceNowMs,
      });
      if (!decision.applied) {
        return;
      }
      committedAssistantDeltaLayer = decision.nextCommittedLayer;
      if (decision.shouldCommitRender) {
        setActiveTurnLayersBySession((current) =>
          setActiveTurnLayerForSession(current, streamSessionId, decision.nextCommittedLayer)
        );
      }
      sessionStreamApplyStatsRef.current[streamSessionId] = decision.stats;
      if (decision.shouldCommitRender) {
        lastAssistantDeltaAppliedAtRef.current = {
          ...lastAssistantDeltaAppliedAtRef.current,
          [streamSessionId]: decision.lastAppliedAtMs,
        };
      }
      if (decision.shouldLogApplied) {
        postBrowserTelemetry({
          phase: "session_stream",
          eventCode: "browser.session_stream.assistant_delta_applied",
          message: "Session assistant delta stream was applied to the active turn layer.",
          level: "info",
          fields: decision.telemetry,
        });
      }
      if (decision.shouldScheduleNextFrame && !disposed) {
        scheduleAssistantDeltaFrame();
      }
      if (decision.shouldInvalidateSession) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.session(streamSessionId) });
      }
    }

    function scheduleAssistantDeltaFrame() {
      if (assistantDeltaApplyFrame !== null || disposed) {
        return;
      }
      frameScheduledAtMs = chatStreamPerformanceNowMs();
      assistantDeltaApplyFrame = window.requestAnimationFrame(() => {
        assistantDeltaApplyFrame = null;
        applyPendingAssistantDeltas("frame");
      });
    }

    function queueAssistantDelta(
      payload: Extract<SessionStreamEvent, { type: "assistant_delta" }>,
      trace: SessionStreamProtocolTrace,
    ) {
      const stats = sessionStreamApplyStatsRef.current[streamSessionId] ?? { received: 0, applied: 0, dropped: 0 };
      stats.received += 1;
      sessionStreamApplyStatsRef.current[streamSessionId] = stats;
      const queued = assistantDeltaScheduler.enqueue(payload, trace.payloadLength, trace);
      if (payload.done) {
        applyPendingAssistantDeltas("final");
        return;
      }
      scheduleAssistantDeltaFrame();
      if (stats.received === 1 || stats.received % 50 === 0) {
        postBrowserTelemetry({
          phase: "session_stream",
          eventCode: "browser.session_stream.assistant_delta_frame_scheduled",
          message: "Session assistant delta stream was scheduled for the next browser frame.",
          level: "info",
          fields: {
            sessionId: streamSessionId,
            turnId: payload.turnId,
            stage: payload.stage,
            receivedCount: stats.received,
            appliedCount: stats.applied,
            droppedCount: stats.dropped,
            payloadLength: trace.payloadLength,
            contentDeltaLength: queued.contentDeltaLength,
            thoughtDeltaLength: queued.thoughtDeltaLength,
            pendingTextLength: 0,
            batchSize: queued.pendingCount,
            done: payload.done,
            receivedAtMs: Math.round(queued.receivedAtMs),
            frameScheduledAtMs: Math.round(frameScheduledAtMs),
            queuedForMs: Math.max(0, Math.round(frameScheduledAtMs - queued.receivedAtMs)),
            ...sessionStreamProtocolTelemetryFields(trace),
          },
        });
      }
    }

    stream.onopen = () => {
      if (!disposed) {
        setSessionStreamConnected(true);
        sessionStreamErrorLoggedRef.current[streamSessionId] = false;
        postBrowserTelemetry({
          phase: "session_stream",
          eventCode: "browser.session_stream.opened",
          message: "Session detail stream opened.",
          level: "info",
          fields: {
            sessionId: streamSessionId,
          },
        });
      }
    };

    stream.onerror = () => {
      if (!disposed) {
        setSessionStreamConnected(false);
        const pendingAssistantDeltaCount = assistantDeltaScheduler.pendingCount;
        applyPendingAssistantDeltas("close");
        void queryClient.invalidateQueries({ queryKey: queryKeys.session(streamSessionId) });
        if (!sessionStreamErrorLoggedRef.current[streamSessionId]) {
          sessionStreamErrorLoggedRef.current[streamSessionId] = true;
          postBrowserTelemetry({
            phase: "session_stream",
            eventCode: "browser.session_stream.error",
            message: "Session detail stream reported an error.",
            level: "warning",
            fields: {
              sessionId: streamSessionId,
              readyState: stream.readyState,
            },
          });
          postBrowserTelemetry({
            phase: "session_stream",
            eventCode: "browser.session_stream.authoritative_refresh_requested",
            message: "Authoritative session detail refresh was requested after a stream error.",
            level: "warning",
            fields: {
              sessionId: streamSessionId,
              readyState: stream.readyState,
              pendingAssistantDeltaCount,
            },
          });
        }
      }
    };

    function handleSessionDetail(event: MessageEvent<string>) {
      const routed = routeSessionStreamEvent({
        activeSessionId: streamSessionId,
        expectedType: "session_detail",
        rawData: event.data,
      });
      if (!routed.accepted) {
        logRejectedSessionStreamRoute(routed.trace, "Session detail stream payload could not be parsed.");
        return;
      }
      setSessionStreamConnected(true);
      queueSessionDetail(routed.payload.detail, routed.trace);
    }

    function handleSessionInitial(event: MessageEvent<string>) {
      const routed = routeSessionStreamEvent({
        activeSessionId: streamSessionId,
        expectedType: "session_initial",
        rawData: event.data,
      });
      if (!routed.accepted) {
        logRejectedSessionStreamRoute(routed.trace, "Session initial stream payload could not be parsed.");
        return;
      }
      setSessionStreamConnected(true);
      postBrowserTelemetry({
        phase: "session_stream",
        eventCode: "browser.session_stream.initial_received",
        message: "Session stream lightweight initial state was received.",
        level: "info",
        fields: {
          sessionId: streamSessionId,
          payloadLength: routed.trace.payloadLength,
          ledgerSeq: routed.payload.ledgerSeq,
          currentPhase: routed.payload.currentPhase || "",
          running: routed.payload.running,
          latestMessageRole: routed.payload.latestMessage?.role || "",
          latestMessageContentLength: routed.payload.latestMessage?.contentLength ?? 0,
          latestMessageThoughtLength: routed.payload.latestMessage?.thoughtLength ?? 0,
          ...sessionStreamProtocolTelemetryFields(routed.trace),
        },
      });
    }

    function handleAssistantDelta(event: MessageEvent<string>) {
      const routed = routeSessionStreamEvent({
        activeSessionId: streamSessionId,
        expectedType: "assistant_delta",
        rawData: event.data,
      });
      if (!routed.accepted) {
        logRejectedSessionStreamRoute(routed.trace, "Session assistant delta stream payload could not be parsed.");
        return;
      }
      setSessionStreamConnected(true);
      desktopConversationNotifierRef.current.handleAssistantDelta(routed.payload, {
        sessionTitle: sessionDetailQuery.data?.title || directSessionActiveSummary?.title || streamSessionId,
      });
      queueAssistantDelta(routed.payload, routed.trace);
    }

    stream.addEventListener("session_detail", handleSessionDetail as EventListener);
    stream.addEventListener("session_initial", handleSessionInitial as EventListener);
    stream.addEventListener("assistant_delta", handleAssistantDelta as EventListener);

    return () => {
      const readyStateBeforeClose = stream.readyState;
      applyPendingAssistantDeltas("close");
      applyPendingDetail("close");
      disposed = true;
      setSessionStreamConnected(false);
      if (applyTimer) {
        window.clearTimeout(applyTimer);
        applyTimer = null;
      }
      if (assistantDeltaApplyFrame !== null) {
        window.cancelAnimationFrame(assistantDeltaApplyFrame);
        assistantDeltaApplyFrame = null;
      }
      stream.removeEventListener("session_detail", handleSessionDetail as EventListener);
      stream.removeEventListener("session_initial", handleSessionInitial as EventListener);
      stream.removeEventListener("assistant_delta", handleAssistantDelta as EventListener);
      stream.close();
      postBrowserTelemetry({
        phase: "session_stream",
        eventCode: "browser.session_stream.closed",
        message: "Session detail stream closed.",
        fields: {
          sessionId: streamSessionId,
          readyState: readyStateBeforeClose,
        },
      });
    };
  }, [
    activeSessionId,
    queryClient,
    sessionStreamShouldConnect,
    syncSessionDetail,
  ]);

  useEffect(() => {
    if (!groupStreamShouldConnect || typeof EventSource === "undefined") {
      setGroupStreamConnected(false);
      return;
    }

    let disposed = false;
    const streamRoomId = String(activeGroupRoomId || "");
    if (!streamRoomId) {
      setGroupStreamConnected(false);
      return;
    }
    const stream = new EventSource(`/api/chat-rooms/${streamRoomId}/events`);

    stream.onopen = () => {
      if (!disposed) {
        setGroupStreamConnected(true);
        groupStreamErrorLoggedRef.current[streamRoomId] = false;
        postBrowserTelemetry({
          phase: "chat_room_stream",
          eventCode: "browser.chat_room_stream.opened",
          message: "Chat room detail stream opened.",
          level: "info",
          fields: {
            roomId: streamRoomId,
          },
        });
      }
    };

    stream.onerror = () => {
      if (!disposed) {
        setGroupStreamConnected(false);
        if (!groupStreamErrorLoggedRef.current[streamRoomId]) {
          groupStreamErrorLoggedRef.current[streamRoomId] = true;
          postBrowserTelemetry({
            phase: "chat_room_stream",
            eventCode: "browser.chat_room_stream.error",
            message: "Chat room detail stream reported an error.",
            level: "warning",
            fields: {
              roomId: streamRoomId,
              readyState: stream.readyState,
            },
          });
        }
      }
    };

    function handleChatRoomDetail(event: MessageEvent<string>) {
      let payload: ChatRoomStreamEvent;
      try {
        payload = JSON.parse(event.data) as ChatRoomStreamEvent;
      } catch {
        if (!groupStreamPayloadErrorLoggedRef.current[streamRoomId]) {
          groupStreamPayloadErrorLoggedRef.current[streamRoomId] = true;
          postBrowserTelemetry({
            phase: "chat_room_stream",
            eventCode: "browser.chat_room_stream.bad_payload",
            message: "Chat room detail stream payload could not be parsed.",
            level: "warning",
            fields: {
              roomId: streamRoomId,
              payloadLength: event.data.length,
            },
          });
        }
        return;
      }
      if (payload.roomId !== streamRoomId || payload.detail?.roomId !== streamRoomId) {
        return;
      }
      setGroupStreamConnected(true);
      syncChatRoomDetail(payload.detail);
    }

    stream.addEventListener("chat_room_detail", handleChatRoomDetail as EventListener);

    return () => {
      const readyStateBeforeClose = stream.readyState;
      disposed = true;
      setGroupStreamConnected(false);
      stream.removeEventListener("chat_room_detail", handleChatRoomDetail as EventListener);
      stream.close();
      postBrowserTelemetry({
        phase: "chat_room_stream",
        eventCode: "browser.chat_room_stream.closed",
        message: "Chat room detail stream closed.",
        fields: {
          roomId: streamRoomId,
          readyState: readyStateBeforeClose,
        },
      });
    };
  }, [activeGroupRoomId, groupStreamShouldConnect, syncChatRoomDetail]);

  const workspace = activeSessionId
    ? sessionWorkspaces[activeSessionId] ?? {
        openTabs: [],
        activeTab: "agent",
      }
    : { openTabs: [], activeTab: "agent" };

  const activeCliAgentRunId = cliAgentRunIdFromTabId(workspace.activeTab);
  const activeFilePath = workspace.activeTab !== "agent" && !activeCliAgentRunId ? workspace.activeTab : null;
  const fileContentQuery = useQuery({
    queryKey: queryKeys.fileContent(activeFilePath ?? ""),
    enabled: Boolean(activeFilePath),
    queryFn: () =>
      fetchJson<FileContent>(`/api/files/content?path=${encodeURIComponent(activeFilePath ?? "")}`),
  });

  const changedFiles = new Set(sessionDetailQuery.data?.changedFiles ?? []);

  const locale = lang === "zh" ? "zh-CN" : "en-US";

  const timeFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(locale, {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      }),
    [locale],
  );
  const numberFormatter = useMemo(() => new Intl.NumberFormat(locale), [locale]);
  const compactNumberFormatter = useMemo(
    () => new Intl.NumberFormat(locale, { notation: "compact", maximumFractionDigits: 1 }),
    [locale],
  );

  const runtime = runtimeQuery.data;
  const pet = petQuery.data;
  const rawSessionDetail = sessionDetailQuery.data;
  const selectedSessionDetail =
    rawSessionDetail && rawSessionDetail.id === activeSessionId ? rawSessionDetail : undefined;
  const detail = selectedSessionDetail;
  const handleLoadEarlierSessionMessages = useCallback(() => {
    const beforeMessageIndex = detail?.messageWindow?.nextBeforeMessageIndex ?? 0;
    if (
      !activeSessionId
      || !detail?.messageWindow?.hasEarlier
      || !beforeMessageIndex
      || loadEarlierSessionMessagesMutation.isPending
    ) {
      return;
    }
    loadEarlierSessionMessagesMutation.mutate({
      sessionId: activeSessionId,
      beforeMessageIndex,
    });
  }, [
    activeSessionId,
    detail?.messageWindow?.hasEarlier,
    detail?.messageWindow?.nextBeforeMessageIndex,
    loadEarlierSessionMessagesMutation,
  ]);
  const activeTurnLayer = activeSessionId ? activeTurnLayersBySession[activeSessionId] : undefined;
  const activeTurnSettledByDetail = isActiveTurnSettledByDetail(activeTurnLayer, detail);
  const activeTurnMessage = useMemo(
    () => activeTurnSettledByDetail ? undefined : activeTurnLayerToConversationMessage(activeTurnLayer),
    [activeTurnLayer, activeTurnSettledByDetail],
  );
  useEffect(() => {
    if (!activeSessionId || !activeTurnLayer || !activeTurnSettledByDetail || !detail) {
      return;
    }
    const settledTurnId = activeTurnLayer.turnId;
    setActiveTurnLayersBySession((current) => {
      const currentLayer = current[activeSessionId];
      if (!isActiveTurnSettledByDetail(currentLayer, detail)) {
        return current;
      }
      return setActiveTurnLayerForSession(current, activeSessionId, undefined);
    });
    postBrowserTelemetry({
      phase: "session_stream",
      eventCode: "browser.session_stream.active_layer_reconciled",
      message: "Active turn layer was cleared after authoritative session detail committed the turn.",
      level: "info",
      fields: {
        sessionId: activeSessionId,
        turnId: settledTurnId,
        source: "session_detail_query",
        ledgerSeq: detail.ledgerSeq ?? 0,
      },
    });
  }, [activeSessionId, activeTurnLayer, activeTurnSettledByDetail, detail]);
  const handleConversationStreamingFramePaint = useCallback((metrics: ConversationStreamingFramePaintMetrics) => {
    const sessionId = String(metrics.sessionId || "").trim();
    if (!sessionId || sessionId !== activeSessionId) {
      return;
    }
    const now = Date.now();
    const lastLoggedAt = lastConversationStreamingFrameTelemetryAtRef.current[sessionId] ?? 0;
    if (now - lastLoggedAt < 1_000) {
      return;
    }
    const paintedAtMs = metrics.paintedAtMs || chatStreamPerformanceNowMs();
    const lastAssistantDeltaAppliedAtMs = lastAssistantDeltaAppliedAtRef.current[sessionId] ?? 0;
    const paintedActiveTurn = activeTurnLayersBySessionRef.current[sessionId];
    lastConversationStreamingFrameTelemetryAtRef.current = {
      ...lastConversationStreamingFrameTelemetryAtRef.current,
      [sessionId]: now,
    };
    postBrowserTelemetry({
      phase: "conversation_stream",
      eventCode: "browser.conversation_stream.frame_painted",
      message: "Conversation streaming frame was committed by the conversation view.",
      level: "info",
      fields: {
        sessionId,
        turnId: paintedActiveTurn?.turnId ?? "",
        streamingMessageCount: metrics.streamingMessageCount,
        renderedTextLength: metrics.renderedTextLength,
        scrollSignalLength: metrics.scrollSignal.length,
        activeTurnTextLength: activeTurnLayerTextLength(paintedActiveTurn),
        paintedAtMs: Math.round(paintedAtMs),
        lastAssistantDeltaAppliedAtMs: Math.round(lastAssistantDeltaAppliedAtMs),
        applyToPaintMs: lastAssistantDeltaAppliedAtMs
          ? Math.max(0, Math.round(paintedAtMs - lastAssistantDeltaAppliedAtMs))
          : 0,
      },
    });
  }, [activeSessionId]);
  const closedCliAgentRunTokens = activeSessionId ? (closedCliAgentRunTokensBySession[activeSessionId] ?? []) : [];
  const closedCliAgentRunTokenSet = useMemo(() => new Set(closedCliAgentRunTokens), [closedCliAgentRunTokens]);
  const cliAgentRunTabs = useMemo(
    () => buildCliAgentRunViews(detail?.messages ?? [], activeSessionId ?? "").filter((run) => !closedCliAgentRunTokenSet.has(cliAgentRunCloseToken(run))),
    [activeSessionId, closedCliAgentRunTokenSet, detail?.messages],
  );
  const activeCliAgentRun = useMemo(
    () => activeCliAgentRunId ? cliAgentRunTabs.find((run) => run.id === activeCliAgentRunId) : undefined,
    [activeCliAgentRunId, cliAgentRunTabs],
  );
  const mountedCliAgentRunIds = activeSessionId ? (mountedCliAgentRunIdsBySession[activeSessionId] ?? []) : [];
  const mountedCliAgentRunIdSet = useMemo(() => {
    const ids = new Set(mountedCliAgentRunIds);
    if (activeCliAgentRun && !groupPanelActive) {
      ids.add(activeCliAgentRun.id);
    }
    return ids;
  }, [activeCliAgentRun, groupPanelActive, mountedCliAgentRunIds]);
  const mountedCliAgentRuns = useMemo(
    () => cliAgentRunTabs.filter((run) => mountedCliAgentRunIdSet.has(run.id)),
    [cliAgentRunTabs, mountedCliAgentRunIdSet],
  );
  useEffect(() => {
    if (!activeSessionId || !activeCliAgentRun || groupPanelActive) {
      return;
    }
    setMountedCliAgentRunIdsBySession((current) => {
      const existing = current[activeSessionId] ?? [];
      if (existing.includes(activeCliAgentRun.id)) {
        return current;
      }
      return {
        ...current,
        [activeSessionId]: [...existing, activeCliAgentRun.id],
      };
    });
  }, [activeCliAgentRun, activeSessionId, groupPanelActive]);
  useEffect(() => {
    if (!activeSessionId) {
      return;
    }
    const availableRunIds = new Set(cliAgentRunTabs.map((run) => run.id));
    setMountedCliAgentRunIdsBySession((current) => {
      const existing = current[activeSessionId] ?? [];
      const next = existing.filter((runId) => availableRunIds.has(runId));
      if (next.length === existing.length) {
        return current;
      }
      if (next.length === 0) {
        const { [activeSessionId]: _removed, ...remaining } = current;
        return remaining;
      }
      return {
        ...current,
        [activeSessionId]: next,
      };
    });
  }, [activeSessionId, cliAgentRunTabs]);
  useEffect(() => {
    if (!activeSessionId || !activeCliAgentRunId) {
      return;
    }
    if (!cliAgentRunTabs.some((run) => run.id === activeCliAgentRunId)) {
      setActiveTab(activeSessionId, "agent");
    }
  }, [activeCliAgentRunId, activeSessionId, cliAgentRunTabs, setActiveTab]);
  const handleCliAgentTerminalSessionChange = useCallback((runId: string, session: CliAgentTerminalSession) => {
    setCliAgentTerminalSessions((current) => {
      const previous = current[runId];
      if (
        previous?.terminalSessionId === session.terminalSessionId
        && previous?.status === session.status
        && previous?.alive === session.alive
        && previous?.cliSessionId === session.cliSessionId
      ) {
        return current;
      }
      return {
        ...current,
        [runId]: session,
      };
    });
  }, []);
  const closeCliAgentRun = useCallback(async (run: CliAgentRunView) => {
    if (!activeSessionId) {
      return;
    }
    const terminalSession = cliAgentTerminalSessions[run.id];
    const terminalSessionId = String(terminalSession?.terminalSessionId || run.terminalSessionId || run.result?.terminalSessionId || "").trim();
    const shouldStopTerminal = isCliAgentRunActiveForClose(run, terminalSession);
    if (shouldStopTerminal && typeof window !== "undefined") {
      const confirmed = window.confirm(
        lang === "zh"
          ? `关闭后将结束当前 ${run.title} 终端会话，是否关闭？`
          : `Closing will end the current ${run.title} terminal session. Close it?`,
      );
      if (!confirmed) {
        return;
      }
    }
    if (shouldStopTerminal && terminalSessionId) {
      try {
        await fetchJson<CliAgentTerminalSession>(
          `/api/cli-agents/terminal-sessions/${encodeURIComponent(terminalSessionId)}/stop`,
          { method: "POST" },
        );
        void sessionDetailQuery.refetch();
      } catch (error) {
        if (typeof window !== "undefined") {
          window.alert(
            lang === "zh"
              ? `关闭 ${run.title} 终端失败：${describeError(error, "请求失败")}`
              : `Failed to close ${run.title}: ${describeError(error, "Request failed")}`,
          );
        }
        return;
      }
    }
    setClosedCliAgentRunTokensBySession((current) => {
      const existing = current[activeSessionId] ?? [];
      const closeToken = cliAgentRunCloseToken(run);
      if (existing.includes(closeToken)) {
        return current;
      }
      return {
        ...current,
        [activeSessionId]: [...existing, closeToken],
      };
    });
    setCliAgentTerminalSessions((current) => {
      const { [run.id]: _removed, ...remaining } = current;
      return remaining;
    });
    setMountedCliAgentRunIdsBySession((current) => {
      const existing = current[activeSessionId] ?? [];
      if (!existing.includes(run.id)) {
        return current;
      }
      const next = existing.filter((runId) => runId !== run.id);
      if (next.length === 0) {
        const { [activeSessionId]: _removed, ...remaining } = current;
        return remaining;
      }
      return {
        ...current,
        [activeSessionId]: next,
      };
    });
    if (activeCliAgentRunId === run.id) {
      setActiveTab(activeSessionId, "agent");
    }
  }, [activeCliAgentRunId, activeSessionId, cliAgentTerminalSessions, lang, sessionDetailQuery, setActiveTab]);
  const sessionDetailLoadingForActiveSession = Boolean(
    activeSessionId
    && (!rawSessionDetail || rawSessionDetail.id !== activeSessionId)
    && sessionDetailQuery.isFetching,
  );
  const runtimeActiveChatTurnSessionIds = new Set(
    [
      ...(runtime?.workRuns?.activeItems?.chat_turn ?? []),
      runtime?.workRuns?.active?.chat_turn,
    ]
      .map((run) => String(run?.sessionId ?? "").trim())
      .filter(Boolean),
  );
  const runtimeMatchesSelectedSession = Boolean(
    activeSessionId && runtimeActiveChatTurnSessionIds.has(activeSessionId),
  );
  const runtimeActiveChatTurnSessionId = runtimeActiveChatTurnSessionIds.values().next().value ?? "";
  const runtimeActiveSessionLabel = runtimeActiveChatTurnSessionId
    ? sessionsQuery.data?.find((session) => session.id === runtimeActiveChatTurnSessionId)?.title
      || runtime?.sessionTitle
      || runtimeActiveChatTurnSessionId
    : "";
  const runtimeMismatchLine = runtimeActiveChatTurnSessionId && !runtimeMatchesSelectedSession
    ? (lang === "zh"
      ? `运行器正在处理：${runtimeActiveSessionLabel}`
      : `Runtime is processing: ${runtimeActiveSessionLabel}`)
    : "";
  const lastContextComposition = detail?.lastContextComposition ?? null;
  const lastCacheComposition = detail?.lastCacheComposition ?? null;
  const lastLlmPayloadTrace = detail?.lastLlmPayloadTrace ?? null;
  const lastCacheDiagnostics = lastCacheComposition as SessionCacheCompositionDiagnostics | null;
  const activeSkillContract = (detail as SessionDetailWithActiveSkill | undefined)?.activeSkillContract ?? null;
  const activeSkillCommand = String(activeSkillContract?.command ?? "").trim();
  const activeSkillName = String(activeSkillContract?.skillName ?? activeSkillCommand).trim();
  const activeSkillStatusValue = String(activeSkillContract?.status ?? "active").trim().toLowerCase();
  const activeSkillStatus = ["active", "stale", "missing"].includes(activeSkillStatusValue)
    ? activeSkillStatusValue
    : "active";
  const activeSkillStatusLabel = activeSkillStatus === "stale"
    ? (lang === "zh" ? "已变更" : "stale")
    : activeSkillStatus === "missing"
      ? (lang === "zh" ? "缺失" : "missing")
      : (lang === "zh" ? "生效中" : "active");
  const activeSkillStatusStyle = activeSkillStatus === "stale"
    ? styles.activeSkillStatus_stale
    : activeSkillStatus === "missing"
      ? styles.activeSkillStatus_missing
      : styles.activeSkillStatus_active;
  const activeSkillHash = String(activeSkillContract?.skillHash ?? "").trim();
  const activeSkillShortHash = activeSkillHash ? activeSkillHash.slice(0, 8) : "";
  const activeSkillRuleCount = Array.isArray(activeSkillContract?.keyRules)
    ? activeSkillContract.keyRules.length
    : 0;
  const activeSkillSummary = activeSkillContract && (activeSkillName || activeSkillCommand)
    ? [
      activeSkillCommand ? `/${activeSkillCommand}` : "",
      activeSkillName,
      activeSkillStatusLabel,
      activeSkillShortHash ? `#${activeSkillShortHash}` : "",
    ].filter(Boolean).join(" · ")
    : "";
  const projectBusTimeline = projectAgentBusQuery.data;
  const projectBusEvents = projectBusTimeline?.events ?? [];
  const activeGroupRound = latestChatRoomRound(activeGroupRoom);
  const activeGroupRoomStatus = String(activeGroupRoom?.status ?? "").trim().toLowerCase();
  const groupRoundRunning = activeGroupRoomStatus === "running";
  const groupRoundStopping = activeGroupRoomStatus === "stopping";
  const groupRoundActive = groupRoundRunning || groupRoundStopping;
  const activeGroupParticipantById = useMemo(() => {
    const entries = (activeGroupRoom?.participants ?? []).map((participant) => [participant.participantId, participant] as const);
    return new Map(entries);
  }, [activeGroupRoom?.participants]);
  const groupManageSessionSet = useMemo(() => new Set(groupManageSessionIds), [groupManageSessionIds]);
  const activeGroupParticipantSessionSet = useMemo(
    () => new Set(availableGroupParticipants.map((participant) => participant.sessionId)),
    [availableGroupParticipants],
  );
  const expandedGroupAgentDetailsBySessionId = useMemo(() => {
    const entries = expandedGroupAgentSessionIds.map((sessionId, index) => {
      const query = expandedGroupAgentDetailQueries[index];
      return [sessionId, query] as const;
    });
    return new Map(entries);
  }, [expandedGroupAgentDetailQueries, expandedGroupAgentSessionIds]);
  useEffect(() => {
    if (!groupPanelActive) {
      if (expandedGroupAgentSessionIds.length) {
        setExpandedGroupAgentSessionIds([]);
      }
      return;
    }
    const nextExpanded = expandedGroupAgentSessionIds.filter((sessionId) => activeGroupParticipantSessionSet.has(sessionId));
    if (nextExpanded.length !== expandedGroupAgentSessionIds.length) {
      setExpandedGroupAgentSessionIds(nextExpanded);
    }
  }, [activeGroupParticipantSessionSet, expandedGroupAgentSessionIds, groupPanelActive]);
  const groupManageChanged = Boolean(
    standardGroupRoomActive
    &&
    activeGroupRoom
    && (
      groupManageTitleDraft.trim() !== (activeGroupRoom.title || "").trim()
      || groupManageModeDraft !== (activeGroupRoom.mode || "round_robin")
      || groupManagePurposeDraft !== (activeGroupRoom.purpose || "discussion")
      || groupManageSessionIds.length !== activeGroupParticipantSessionSet.size
      || groupManageSessionIds.some((sessionId) => !activeGroupParticipantSessionSet.has(sessionId))
    ),
  );
  const groupManageDisabled =
    !standardGroupRoomActive
    ||
    !activeGroupRoom
    || activeGroupTeamOwned
    || groupRoundActive
    || updateGroupRoomMutation.isPending
    || !groupManageTitleDraft.trim()
    || groupManageSessionIds.length < 2
    || !groupManageModeDraft
    || !groupManagePurposeDraft;
  const groupDeleteDisabled =
    !standardGroupRoomActive
    ||
    !activeGroupRoom
    || activeGroupTeamOwned
    || groupRoundActive
    || deleteGroupRoomMutation.isPending;
  const groupResetDisabled =
    !standardGroupRoomActive
    ||
    !activeGroupRoom
    || groupRoundActive
    || resetGroupRoomMutation.isPending
    || (activeGroupRoom?.rounds ?? []).length < 1;
  const groupStopDisabled =
    !standardGroupRoomActive
    || !activeGroupRoom
    || !groupRoundRunning
    || stopGroupRoundMutation.isPending;
  const noActiveDirectSessionTitle = lang === "zh" ? "未选择会话" : "No session selected";
  const noActiveDirectSessionLine = lang === "zh" ? "选择或新建会话" : "Select or create a chat";
  const loadingDirectSessionTitle = t("loadingSession");
  const activeSurfaceTitle = groupPanelActive
    ? (
      projectBusActive
        ? (lang === "zh" ? "助手通知流" : "Agent notice stream")
        : activeGroupRoom?.title ?? (lang === "zh" ? "群聊加载中" : "Loading group")
    )
    : !activeSessionId
      ? noActiveDirectSessionTitle
      : detail?.agentDisplayName ?? detail?.title ?? directSessionActiveSummary?.agentDisplayName ?? directSessionActiveSummary?.title ?? loadingDirectSessionTitle;
  const activeSurfaceStatus = groupPanelActive
    ? (
      projectBusActive
        ? (lang === "zh" ? "全局广播" : "global broadcast")
        : statusLabel(activeGroupRoom?.status ?? "ready")
    )
    : statusLabel(detail?.status || detail?.currentPhase || "idle");
  const activeSurfaceLine = groupPanelActive
    ? (
      projectBusActive
        ? `${projectBusTimeline?.activeAgentCount ?? 0} ${lang === "zh" ? "位 active Agent · 全局广播/私信投递记录" : "active agents · broadcast/private delivery log"}`
        : (
          activeGroupRound?.summary
          || (lang === "zh"
            ? `${availableGroupParticipantCount} 位可用助手`
            : `${availableGroupParticipantCount} available agents · ${activeGroupRoom?.mode ?? "round_robin"} · ${activeGroupRoom?.purpose ?? "discussion"}`)
        )
    )
    : "";
  const sessionDetailErrorState = deriveSessionDetailQueryErrorState(detail, sessionDetailQuery.isError, {
    dataUpdatedAt: sessionDetailQuery.dataUpdatedAt,
    errorUpdatedAt: sessionDetailQuery.errorUpdatedAt,
    streamConnected: sessionStreamConnected,
  });
  const sessionsErrorState = deriveSessionListQueryErrorState(sessionsQuery.data, sessionsQuery.isError, {
    emptyNotFoundAsEmpty: true,
    error: sessionsQuery.error,
  });
  const sessionDetailErrorMessage = sessionDetailQuery.isError
    ? describeError(sessionDetailQuery.error, t("loadFailed"))
    : "";
  const invalidChildSessionLinkMessage = hasInvalidChildSessionLink(sessionDetailQuery.data ?? directSessionActiveSummary)
    ? (
      lang === "zh"
        ? "child_session_link_invalid: 子对话缺少 parentSessionId/rootSessionId，无法挂载到顶部 Agent 会话轨道。本轮已停止展示，请修复会话索引数据。"
        : "child_session_link_invalid: child session is missing parentSessionId/rootSessionId and cannot be mounted in the top Agent session strip. Fix the session index data."
    )
    : "";
  const sessionsErrorMessage = sessionsQuery.isError
    ? describeError(sessionsQuery.error, t("loadFailed"))
    : "";
  const activeSkillTitle = activeSkillContract && (activeSkillName || activeSkillCommand)
    ? [
      lang === "zh" ? "当前 Skill Contract" : "Active Skill Contract",
      activeSkillCommand ? `/${activeSkillCommand}` : "",
      activeSkillName,
      activeSkillStatusLabel,
      activeSkillHash ? `hash ${activeSkillHash}` : "",
      activeSkillContract.scope ? `scope ${activeSkillContract.scope}` : "",
      activeSkillContract.activatedAt ? `${lang === "zh" ? "激活于" : "activated"} ${formatTime(activeSkillContract.activatedAt)}` : "",
      activeSkillRuleCount ? `${numberFormatter.format(activeSkillRuleCount)} ${lang === "zh" ? "条规则" : "rules"}` : "",
      activeSkillContract.staleReason ? `reason ${activeSkillContract.staleReason}` : "",
      activeSkillContract.skillPath || "",
    ].filter(Boolean).join(" · ")
    : "";
  const providerCacheInputTokens = Math.max(0, lastCacheComposition?.calibratedInputTokens ?? lastCacheComposition?.inputTokens ?? 0);
  const providerCachedInputTokens = Math.max(
    0,
    Math.min(
      lastCacheComposition?.calibratedCachedInputTokens ?? lastCacheComposition?.cachedInputTokens ?? 0,
      providerCacheInputTokens,
    ),
  );
  const providerUncachedInputTokens = Math.max(
    0,
    lastCacheComposition?.uncachedInputTokens ?? (providerCacheInputTokens - providerCachedInputTokens),
  );
  const cacheCalibrationStatus = lastCacheComposition?.calibrationStatus || "";
  const cacheCalibrationReason = lastCacheComposition?.calibrationReason || "";
  const cacheComputedOverestimatedInputTokens = Math.max(0, lastCacheComposition?.computedOverestimatedInputTokens ?? 0);
  const cacheProviderExtraCachedInputTokens = Math.max(0, lastCacheComposition?.providerExtraCachedInputTokens ?? 0);
  const cacheCalibrationSummaryText = cacheCalibrationSummaryLabel(
    cacheCalibrationStatus,
    cacheCalibrationReason,
    cacheComputedOverestimatedInputTokens,
    cacheProviderExtraCachedInputTokens,
    numberFormatter,
    lang,
  );
  const trueCacheDonutSegments = useMemo(
    () => buildCacheDonutSegments(
      [
        {
          key: "cached",
          label: t("cacheSegment_cached"),
          tokens: providerCachedInputTokens,
          status: "hit",
          source: "provider_usage",
          description: lang === "zh" ? "上游返回的真实缓存命中输入 token。" : "Provider-reported cached input tokens.",
        },
        {
          key: "uncached",
          label: t("cacheSegment_uncached"),
          tokens: Math.max(0, providerCacheInputTokens - providerCachedInputTokens),
          status: "miss",
          source: "provider_usage",
          description: lang === "zh" ? "上游返回的非缓存命中输入 token。" : "Provider-reported input tokens that were not cache hits.",
        },
      ],
      providerCacheInputTokens,
    ),
    [lang, providerCachedInputTokens, providerCacheInputTokens, t],
  );
  const computedCacheCompositionSegments = useMemo(() => {
    const segments = lastCacheComposition?.computedSegments ?? [];
    return segments
      .filter((segment: SessionCacheCompositionSegment) => (segment.tokens ?? 0) > 0 || segment.key === "computed_missing")
      .map((segment) => {
        return {
          ...segment,
          label: promptSegmentDisplayLabel(segment, lang, t),
        };
      });
  }, [lang, lastCacheComposition, t]);
  const computedCacheCompositionTotalTokens = Math.max(
    lastCacheComposition?.computedInputTokens ?? 0,
    computedCacheCompositionSegments.reduce((total, segment) => total + Math.max(0, segment.tokens ?? 0), 0),
  );
  const upperBoundCacheInputTokens = Math.max(
    lastCacheDiagnostics?.upperBoundInputTokens ?? 0,
    computedCacheCompositionTotalTokens,
  );
  const upperBoundCachedInputTokens = Math.max(
    0,
    Math.min(
      lastCacheDiagnostics?.upperBoundCachedInputTokens ?? lastCacheDiagnostics?.computedCachedInputTokens ?? 0,
      upperBoundCacheInputTokens,
    ),
  );
  const upperBoundCacheHitRate = upperBoundCacheInputTokens > 0
    ? (lastCacheDiagnostics?.upperBoundCacheHitRate ?? (upperBoundCachedInputTokens / upperBoundCacheInputTokens))
    : 0;
  const cachePromptCompositionSegments = useMemo(() => {
    const segments = (lastCacheComposition?.calibratedSegments?.length
      ? (lastCacheComposition.calibratedSegments ?? [])
      : computedCacheCompositionSegments
    );
    return segments
      .filter((segment: SessionCacheCompositionSegment) => (segment.tokens ?? 0) > 0 || segment.key === "computed_missing")
      .map((segment) => {
        return {
          ...segment,
          label: promptSegmentDisplayLabel(segment, lang, t),
        };
      });
  }, [computedCacheCompositionSegments, lang, lastCacheComposition, t]);
  const cachePromptCompositionTotalTokens = Math.max(
    computedCacheCompositionTotalTokens,
    cachePromptCompositionSegments.reduce((total, segment) => total + Math.max(0, segment.tokens ?? 0), 0),
  );
  const cachePromptDonutSegments = useMemo(
    () => buildCacheDonutSegments(cachePromptCompositionSegments, cachePromptCompositionTotalTokens),
    [cachePromptCompositionSegments, cachePromptCompositionTotalTokens],
  );
  const cacheCompositionPercent = Math.round(Math.max(0, Math.min(1, lastCacheComposition?.cacheHitRate ?? 0)) * 100);
  const upperBoundCacheCompositionPercent = Math.round(Math.max(0, Math.min(1, upperBoundCacheHitRate)) * 100);
  const averageCacheObservedTurnCount = Math.max(
    0,
    lastCacheComposition?.averageObservedTurnCount || detail?.cacheUsage?.totalObservedTurnCount || 0,
  );
  const averageCacheInputTokens = Math.max(
    0,
    lastCacheComposition?.averageInputTokens || detail?.cacheUsage?.totalInputTokens || 0,
  );
  const averageCachedInputTokens = Math.max(
    0,
    lastCacheComposition?.averageCachedInputTokens || detail?.cacheUsage?.totalCachedInputTokens || 0,
  );
  const averageCacheHitRate = averageCacheInputTokens > 0
    ? averageCachedInputTokens / averageCacheInputTokens
    : (detail?.cacheUsage?.totalCacheHitRate ?? lastCacheComposition?.averageCacheHitRate ?? 0);
  const averageCacheCompositionPercent = Math.round(Math.max(0, Math.min(1, averageCacheHitRate)) * 100);
  const cacheCompositionTrueLabel = lang === "zh" ? "真" : "true";
  const cacheCompositionUpperBoundLabel = lang === "zh" ? "计" : "calc";
  const cacheCompositionAverageLabel = lang === "zh" ? "均" : "avg";
  const cacheCompositionAverageValue = averageCacheObservedTurnCount > 0 ? `${averageCacheCompositionPercent}%` : "--";
  const cacheDetailAvailable = Boolean(lastCacheComposition);
  const cacheDetailDialogTitle = lang === "zh" ? "缓存命中详情" : "Cache hit details";
  const cacheDetailOpenLabel = lang === "zh" ? "查看上一轮缓存命中详情" : "View previous cache hit details";
  const cacheCompositionSummary = lastCacheComposition
    ? lastCacheComposition.source === "provider_usage"
      ? `${cacheCompositionTrueLabel} ${cacheCompositionPercent}% · ${cacheCompositionUpperBoundLabel} ${upperBoundCacheCompositionPercent}% · ${cacheCompositionAverageLabel} ${cacheCompositionAverageValue}`
      : lastCacheComposition.source === "not_called"
        ? t("cacheHitNotCalled")
      : t("cacheHitMissing")
    : t("cacheObservationPending");
  const cacheCompositionTitle = lastCacheComposition
    ? lastCacheComposition.source === "provider_usage"
      ? [
        `${cacheCompositionTrueLabel} ${numberFormatter.format(providerCachedInputTokens)} / ${numberFormatter.format(providerCacheInputTokens)} · ${cacheCompositionPercent}%`,
        `${cacheCompositionUpperBoundLabel} ${numberFormatter.format(upperBoundCachedInputTokens)} / ${numberFormatter.format(upperBoundCacheInputTokens)} · ${upperBoundCacheCompositionPercent}%`,
        `${cacheCompositionAverageLabel} ${numberFormatter.format(averageCachedInputTokens)} / ${numberFormatter.format(averageCacheInputTokens)} · ${cacheCompositionAverageValue}`,
        `${lang === "zh" ? "观测轮次" : "observed turns"} ${numberFormatter.format(averageCacheObservedTurnCount)}`,
        cacheComputedOverestimatedInputTokens > 0 ? `${lang === "zh" ? "上界未兑现" : "upper bound not observed"} ${numberFormatter.format(cacheComputedOverestimatedInputTokens)}` : "",
        cacheProviderExtraCachedInputTokens > 0 ? `${lang === "zh" ? "厂商额外命中" : "provider extra hit"} ${numberFormatter.format(cacheProviderExtraCachedInputTokens)}` : "",
        cacheCalibrationStatus ? `${lang === "zh" ? "校准" : "calibration"} ${cacheCalibrationStatus}` : "",
        `write ${numberFormatter.format(lastCacheComposition.cacheCreationInputTokens ?? 0)}`,
        `uncached ${numberFormatter.format(providerUncachedInputTokens)}`,
        cacheCalibrationReason,
      ].filter(Boolean).join(" · ")
      : lastCacheComposition.source === "not_called"
        ? t("cacheHitNotCalled")
      : t("cacheHitMissing")
    : t("cacheObservationPending");
  const closeCacheDetail = useCallback(() => setCacheDetailOpen(false), []);
  const openCacheDetail = useCallback(() => {
    if (cacheDetailAvailable) {
      setCacheDetailOpen(true);
    }
  }, [cacheDetailAvailable]);
  useEffect(() => {
    if (!cacheDetailOpen) {
      return undefined;
    }
    function handleCacheDetailKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        closeCacheDetail();
      }
    }
    window.addEventListener("keydown", handleCacheDetailKeyDown);
    return () => window.removeEventListener("keydown", handleCacheDetailKeyDown);
  }, [cacheDetailOpen, closeCacheDetail]);
  useEffect(() => {
    setCacheDetailOpen(false);
  }, [activeSessionId]);
  const pendingToolApproval = useMemo(
    () => (detail?.pendingToolGovernanceRequests ?? []).find((request) => request.status === "pending_review") ?? null,
    [detail?.pendingToolGovernanceRequests],
  );
  const pendingToolApprovalLabels = useMemo(
    () => toolApprovalLabels(pendingToolApproval),
    [pendingToolApproval],
  );
  const pendingToolApprovalRawTitle = pendingToolApprovalLabels.map((item) => item.id).join("、");
  const pendingToolApprovalScope = toolApprovalScopeLabel(pendingToolApproval?.grantScope, lang);
  const pendingToolApprovalRisk = toolApprovalRiskLabel(pendingToolApproval?.riskLevel, lang);
  const pendingToolApprovalPending = Boolean(
    pendingToolApproval
    && resolveToolApprovalMutation.isPending
    && resolveToolApprovalMutation.variables?.request.requestId === pendingToolApproval.requestId,
  );
  const activeDraft = activeSessionId ? sessionDrafts[activeSessionId] ?? "" : "";
  const activeComposerRawError = activeSessionId ? sessionComposerErrors[activeSessionId] ?? "" : "";
  const activeLatestTurnErrorMessage = useMemo(
    () => latestVisibleTurnErrorMessage(detail?.messages),
    [detail?.messages],
  );
  const activeComposerError = shouldSuppressComposerErrorForTurnError(
    activeComposerRawError,
    activeLatestTurnErrorMessage,
    detail?.lastTurnError,
  )
    ? ""
    : activeComposerRawError;
  const activeEditTarget = activeSessionId ? sessionEditTargets[activeSessionId] ?? null : null;
  const activeImageAttachments = activeSessionId ? sessionImageAttachments[activeSessionId] ?? [] : [];
  const activeReferenceAttachments = activeSessionId ? sessionReferenceAttachments[activeSessionId] ?? [] : [];
  const activeImageUploadPending = activeSessionId ? Boolean(sessionImageUploadPending[activeSessionId]) : false;
  const activeAgentId = detail?.agentId || "";
  const activeSessionAgent = activeAgentId ? (agentsQuery.data ?? []).find((agent) => agent.agentId === activeAgentId) : undefined;
  const activeImageInputModelId = imageInputModelIdForAgent(activeSessionAgent, detail?.dialogueModelId);
  const activeAgentImageInputSupported = modelImageInputSupport(modelImageInputSupportById, activeImageInputModelId);
  const activeAgentImageInputUnsupported = activeAgentImageInputSupported === false;
  const activeImageInputModelLabel = activeImageInputModelId || (lang === "zh" ? "当前模型" : "the current model");
  const activeImageInputGuidance = !activeImageAttachments.length
    ? ""
    : activeAgentImageInputSupported === true
      ? (lang === "zh"
        ? `图片将发送给已验证支持图像输入的 ${activeImageInputModelLabel}。`
        : `The image will be sent to ${activeImageInputModelLabel}, which has verified image-input support.`)
      : activeAgentImageInputSupported === false
        ? (lang === "zh"
          ? `${activeImageInputModelLabel} 明确不支持图像输入，无法发送图片。`
          : `${activeImageInputModelLabel} explicitly does not support image input, so the image cannot be sent.`)
        : (lang === "zh"
          ? `${activeImageInputModelLabel} 的图像输入能力尚未验证；将尝试发送，失败时会保留诊断。`
          : `${activeImageInputModelLabel}'s image-input capability is not verified yet. Vibelution will try the request and retain diagnostics if it fails.`);
  const activeAgentDisplay = detail
    ? sessionAgentDisplayInfo(detail, activeSessionAgent, lang, resolveModelLabel)
    : { name: pet?.name || "Agent", functionLabel: "", tone: "chat" as const, meta: "" };
  const activeAgentDisplayName = activeAgentDisplay.name;
  const activeAgentAvatarImageUrl = avatarImageUrlFrom(activeSessionAgent, detail);
  const activeAgentAvatarFallback = avatarInitials(detail?.agentCode, activeAgentDisplayName);
  const activeAgentStatusMessage = detail?.agentMissing
    ? detail.agentStatusMessage || (lang === "zh" ? "缺少有效 Agent，部分内容无法继续运行。" : "Missing valid Agent. Some content cannot keep running.")
    : "";
  const activeRuntimeNotices = useMemo<SessionRuntimeNotice[]>(() => {
    return (detail?.runtimeNotices ?? [])
      .filter((notice) => String(notice.message ?? "").trim())
      .slice(-1);
  }, [detail?.runtimeNotices]);
  const activeControlSignals = useMemo<ChatNextStateSignalSummary[]>(() => {
    const phase = detail?.currentPhase || directSessionActiveSummary?.currentPhase || directSessionActiveSummary?.status || "";
    return (detail?.nextStateSignals ?? [])
      .filter((signal) => shouldShowNextStateSignalInConversation(signal, phase))
      .slice(-3)
      .reverse();
  }, [detail?.currentPhase, detail?.nextStateSignals, directSessionActiveSummary?.currentPhase, directSessionActiveSummary?.status]);
  const latestControlSignal = activeControlSignals[0] ?? null;
  const latestControlSignalSummary = latestControlSignal?.summary?.trim() ?? "";
  const latestControlSignalKindLabel = (() => {
    if (!latestControlSignal) {
      return "";
    }
    const lowerSummary = latestControlSignalSummary.toLowerCase();
    const lowerKind = String(latestControlSignal.kind ?? "").toLowerCase();
    if (lowerSummary.includes("tool failed") || lowerKind.includes("tool")) {
      return lang === "zh" ? "工具失败" : "Tool failed";
    }
    if (lowerSummary.includes("provider") || lowerKind.includes("provider")) {
      return lang === "zh" ? "模型通道" : "Provider";
    }
    if (lowerSummary.includes("interrupt") || lowerKind.includes("interrupt")) {
      return lang === "zh" ? "已中断" : "Interrupted";
    }
    return latestControlSignalSummary || latestControlSignal.kind || "";
  })();
  const latestControlSignalLine = latestControlSignal
    ? activeControlSignals.length > 1
      ? `${latestControlSignalKindLabel} ${numberFormatter.format(activeControlSignals.length)}`
      : latestControlSignalKindLabel
    : "";
  const latestControlSignalTitle = latestControlSignal
    ? [
      t("nextStateSignalsLabel"),
      latestControlSignal.kind,
      latestControlSignal.source,
      latestControlSignal.relatedEventCode,
      latestControlSignal.turnId,
      latestControlSignal.createdAt ? formatTime(latestControlSignal.createdAt) : "",
      latestControlSignal.summary,
    ].filter(Boolean).join(" · ")
    : "";
  const latestUserMessageId = useMemo(() => deriveLatestUserMessageId(detail?.messages), [detail?.messages]);
  const resolvedEditTarget = resolveLatestEditTarget(activeEditTarget, latestUserMessageId);
  const activeDraftEffective = resolveComposerDraftValue(activeDraft, activeEditTarget, resolvedEditTarget);
  const submitMutationMatchesActiveSession =
    submitTurnMutation.variables?.sessionId === activeSessionId;
  const editResubmitMutationMatchesActiveSession =
    editResubmitMutation.variables?.sessionId === activeSessionId;
  const stopMutationMatchesActiveSession =
    stopTurnMutation.variables?.sessionId === activeSessionId;
  const guidanceMutationMatchesActiveSession =
    sessionGuidanceMutation.variables?.sessionId === activeSessionId;
  const submitPending =
    (submitTurnMutation.isPending && submitMutationMatchesActiveSession)
    || (editResubmitMutation.isPending && editResubmitMutationMatchesActiveSession)
    || activeImageUploadPending;
  const sessionRunning = isRunningPhase(detail?.currentPhase);
  const sessionStopping = isStoppingPhase(detail?.currentPhase) || Boolean(detail?.stopRequested);
  const sessionBusy = isBusyPhase(detail?.currentPhase);
  const composerStopPending = (stopTurnMutation.isPending && stopMutationMatchesActiveSession) || sessionStopping;
  const composerSafeGuidancePending =
    sessionGuidanceMutation.isPending
    && guidanceMutationMatchesActiveSession
    && sessionGuidanceMutation.variables?.mode === "safe";
  const composerInterruptGuidancePending =
    sessionGuidanceMutation.isPending
    && guidanceMutationMatchesActiveSession
    && sessionGuidanceMutation.variables?.mode === "interrupt";
  const conversationComposer = useMemo(
    () => buildConversationComposerBridgeState({
      editTargetMessageId: resolvedEditTarget?.messageId,
      editTargetPreview: resolvedEditTarget?.original,
      error: activeComposerError,
      guidance: activeImageInputGuidance,
      imageAttachments: activeImageAttachments,
      imageInputUnsupported: activeAgentImageInputUnsupported,
      interruptGuidancePending: composerInterruptGuidancePending,
      labels: {
        editMessageModeNotice: t("editMessageModeNotice"),
        editMessagePlaceholder: t("editMessagePlaceholder"),
        loadingSession: t("loadingSession"),
        messageInputPlaceholder: t("messageInputPlaceholder"),
        saveAndRerunMessage: t("saveAndRerunMessage"),
      },
      references: activeReferenceAttachments,
      safeGuidancePending: composerSafeGuidancePending,
      sessionBusy,
      sessionId: activeSessionId,
      sessionStopping,
      stopPending: composerStopPending,
      submitPending,
      value: activeDraftEffective,
    }),
    [
      activeAgentImageInputUnsupported,
      activeComposerError,
      activeDraftEffective,
      activeImageAttachments,
      activeReferenceAttachments,
      activeSessionId,
      resolvedEditTarget?.original,
      resolvedEditTarget?.messageId,
      composerInterruptGuidancePending,
      composerSafeGuidancePending,
      composerStopPending,
      sessionBusy,
      sessionStopping,
      submitPending,
      t,
    ],
  );
  const composerDisabled = conversationComposer.disabled;

  const {
    handleSubmitTurn,
    handleStopTurn,
    handleSubmitGuidance,
    handleEditUserMessage,
    handleCancelEditMessage,
  } = useChatComposerSubmitActions({
    queryClient,
    lang,
    describeError,
    submitTurnMutation,
    editResubmitMutation,
    stopTurnMutation,
    sessionGuidanceMutation,
    setSessionDrafts,
    setSessionComposerErrors,
    setSessionImageAttachments,
    setSessionReferenceAttachments,
    setSessionImageUploadPending,
    setSessionEditTargets,
    imageUploadInFlightRef,
    activeSessionId,
    activeDraftEffective,
    activeImageAttachments,
    activeReferenceAttachments,
    mentalModelEnabledForNextTurn,
    resolvedEditTarget,
    activeEditTarget,
    composerDisabled,
    sessionBusy,
    sessionStopping,
    activePhase: detail?.currentPhase,
    activeAgentImageInputUnsupported,
    activeImageInputModelId,
    latestUserMessageId,
    detail,
  });
  const sessionLlmOptions = sessionLlmOptionsQuery.data;
  const sessionLlmControl = activeSessionId ? {
    model: sessionLlmOptions?.model ?? null,
    currentReasoningEffort: sessionLlmOptions?.currentReasoningEffort || detail?.reasoningEffort || "",
    disabled: sessionBusy || sessionLlmOptionsQuery.isLoading,
    pending: sessionReasoningEffortMutation.isPending,
    onReasoningEffortChange: (reasoningEffort: string) => {
      sessionReasoningEffortMutation.mutate({
        sessionId: activeSessionId,
        reasoningEffort,
      });
    },
  } : undefined;

  useEffect(() => {
    if (!activeSessionId || !activeAgentImageInputUnsupported || !activeImageAttachments.length) {
      return;
    }
    setSessionImageAttachments((current) => clearSessionImageAttachments(current, activeSessionId));
  }, [activeAgentImageInputUnsupported, activeImageAttachments.length, activeSessionId]);

  const sessionContextUsage = detail?.contextUsage;
  const panelContextUsed = lastContextComposition?.totalTokens ?? sessionContextUsage?.used ?? 0;
  const panelContextLimit = lastContextComposition?.limitTokens ?? sessionContextUsage?.limit ?? 0;
  const contextPercent = contextUsagePercent(panelContextUsed, panelContextLimit);
  const petVitals = useMemo(
    () => [
      { key: "hunger", label: t("hunger"), value: clampPercent(pet?.hunger ?? 0) },
      { key: "energy", label: t("energy"), value: clampPercent(pet?.energy ?? 0) },
      { key: "health", label: t("health"), value: clampPercent(pet?.health ?? 0) },
      { key: "love", label: t("love"), value: clampPercent(pet?.love ?? 0) },
    ],
    [pet?.energy, pet?.health, pet?.hunger, pet?.love, t],
  );
  const petCompanionLine = petQuery.isError
    ? describeError(petQuery.error, t("loadFailed"))
    : pet?.inDream
      ? t("petCompanionDreaming")
      : (pet?.health ?? 0) < 35
        ? t("petCompanionLowHealth")
        : (pet?.hunger ?? 0) < 30
          ? t("petCompanionLowFuel")
          : (pet?.energy ?? 0) < 35
            ? t("petCompanionLowEnergy")
            : t("petCompanionStable");
  const petPresetLabel = petAvatarPresetLabel(t, pet?.avatarPreset);
  const petAvatarPresetKey = getPetAvatarPresetKey(pet?.avatarPreset);
  const petAvatarSkinStyle = styles[`petShowcaseAvatar_${petAvatarPresetKey}`] ?? styles.petShowcaseAvatar_default;
  const petAvatarSymbol = getPetAvatarSymbol(pet?.avatarPreset, pet?.name);
  const petInteractionLabels = {
    group: lang === "zh" ? "宠物互动" : "Pet interactions",
    pending: petActionMutation.isPending
      ? lang === "zh" ? "处理中" : "Working"
      : lang === "zh" ? "即时生效" : "Live",
    feed: lang === "zh" ? "喂食" : "Feed",
    talk: lang === "zh" ? "沟通" : "Talk",
    care: lang === "zh" ? "照看" : "Care",
    feedTitle: lang === "zh" ? "喂食并刷新宠物状态" : "Feed and refresh pet state",
    talkTitle: lang === "zh" ? "和宠物沟通并刷新状态" : "Talk and refresh pet state",
    careTitle: lang === "zh" ? "照看宠物并刷新状态" : "Care and refresh pet state",
  };
  const sessionCacheUsage = detail?.cacheUsage;
  const sessionLlmUsage = detail?.llmUsage ?? null;
  const hasProviderLlmUsage = sessionLlmUsage?.source === "provider_usage";
  const hasProviderCacheUsage = sessionCacheUsage?.source === "provider_usage";
  const llmUsageNotCalled = sessionLlmUsage?.source === "not_called" || sessionCacheUsage?.source === "not_called";
  const cacheHitRatePercent = Math.round(Math.max(0, Math.min(1, sessionCacheUsage?.turnCacheHitRate ?? 0)) * 100);
  const cacheHitLine = hasProviderCacheUsage && sessionCacheUsage
    ? `${numberFormatter.format(sessionCacheUsage.turnCachedInputTokens)} / ${numberFormatter.format(sessionCacheUsage.turnInputTokens)} · ${cacheHitRatePercent}%`
    : llmUsageNotCalled
      ? t("cacheHitNotCalled")
    : t("cacheHitMissing");
  const llmUsageLine = hasProviderLlmUsage
    ? lang === "zh"
      ? `${numberFormatter.format(sessionLlmUsage.inputTokens)} · 缓 ${numberFormatter.format(sessionLlmUsage.cachedInputTokens)}`
      : `${numberFormatter.format(sessionLlmUsage.inputTokens)} in · ${numberFormatter.format(sessionLlmUsage.cachedInputTokens)} cached`
    : llmUsageNotCalled
      ? t("llmUsageNotCalled")
    : t("llmUsageMissing");
  const llmUsageTitle = hasProviderLlmUsage
    ? [
      `${numberFormatter.format(sessionLlmUsage.inputTokens)} in`,
      `${numberFormatter.format(sessionLlmUsage.outputTokens)} out`,
      `${numberFormatter.format(sessionLlmUsage.cachedInputTokens)} cached`,
      `${numberFormatter.format(sessionLlmUsage.cacheCreationInputTokens ?? 0)} write`,
      `${numberFormatter.format(sessionLlmUsage.uncachedInputTokens ?? 0)} uncached`,
    ].join(" · ")
    : llmUsageNotCalled
      ? t("llmUsageNotCalled")
    : t("llmUsageMissing");
  const compression = runtimeMatchesSelectedSession ? runtime?.contextCompression : undefined;
  const compressionCurrentPercent = compression
    ? Math.round(Math.max(0, Math.min(1, compression.usageRatio || 0)) * 100)
    : contextPercent;
  const compressionLevelLabel = compression?.enabled === false
    ? t("compressionDisabled")
    : compression?.currentLevel
      ? compression.currentLevel === "normal"
        ? (lang === "zh" ? "未到阈值" : "below threshold")
        : (lang === "zh" ? `${compression.currentLevel} 档` : `${compression.currentLevel} level`)
      : "--";
  const compressionMainLine = compression
    ? `${numberFormatter.format(compression.currentTokens)} / ${numberFormatter.format(compression.effectiveTokenLimit)} · ${compressionCurrentPercent}%`
    : t("loadingContext");
  const compressionPolicySourceLine = compression
    ? compression.policySource === "agent_custom"
      ? (lang === "zh" ? "Agent 自定义策略" : "Agent custom policy")
      : (lang === "zh" ? "继承全局策略" : "Inherited global policy")
    : t("loadingContext");
  const compressionScopeLine = compression
    ? `${t("compressionScopeRuntime")} · ${compressionPolicySourceLine}`
    : t("loadingContext");
  const compressionModelWindowLine = compression
    ? numberFormatter.format(compression.contextWindowLimit)
    : "--";
  const compressionTitleLine = compression
    ? `${compressionMainLine} · ${compressionScopeLine} · ${t("compressionLimitBasisEffective")} · window ${numberFormatter.format(compression.contextWindowLimit)} · source ${compression.source || "runtime_state"}`
    : t("loadingContext");
  const modelInputAvailable =
    lastCacheComposition?.calibratedInputTokens != null
    || (hasProviderLlmUsage && sessionLlmUsage.inputTokens != null)
    || lastCacheComposition?.inputTokens != null
    || (hasProviderCacheUsage && sessionCacheUsage?.turnInputTokens != null);
  const modelInputTokens = Math.max(
    0,
    lastCacheComposition?.calibratedInputTokens
      ?? (hasProviderLlmUsage ? sessionLlmUsage.inputTokens : undefined)
      ?? lastCacheComposition?.inputTokens
      ?? (hasProviderCacheUsage ? sessionCacheUsage?.turnInputTokens : undefined)
      ?? 0,
  );
  const modelCachedInputTokens = Math.max(
    0,
    Math.min(
      lastCacheComposition?.calibratedCachedInputTokens
        ?? (hasProviderLlmUsage ? sessionLlmUsage.cachedInputTokens : undefined)
        ?? lastCacheComposition?.cachedInputTokens
        ?? (hasProviderCacheUsage ? sessionCacheUsage?.turnCachedInputTokens : undefined)
        ?? 0,
      modelInputTokens,
    ),
  );
  const modelInputLimitTokens = Math.max(
    0,
    lastContextComposition?.limitTokens
      ?? sessionContextUsage?.limit
      ?? compression?.contextWindowLimit
      ?? 0,
  );
  const modelInputPercent = modelInputLimitTokens > 0
    ? Math.round(Math.min(1, modelInputTokens / modelInputLimitTokens) * 100)
    : 0;
  const modelInputSourceLine = modelInputAvailable
    ? lastCacheComposition?.calibratedInputTokens != null
      ? (lang === "zh" ? "厂商校准输入" : "provider-calibrated input")
      : hasProviderLlmUsage
        ? (lang === "zh" ? "厂商 usage 输入" : "provider usage input")
        : lastCacheComposition?.inputTokens != null
          ? (lang === "zh" ? "缓存观测输入" : "cache-observed input")
          : (lang === "zh" ? "厂商 cache usage 输入" : "provider cache usage input")
    : llmUsageNotCalled
      ? t("llmUsageNotCalled")
      : t("llmUsageMissing");
  const modelInputMetaLine = modelInputAvailable
    ? modelInputLimitTokens > 0
      ? `${numberFormatter.format(modelInputTokens)} / ${numberFormatter.format(modelInputLimitTokens)} · ${modelInputPercent}%`
      : `${numberFormatter.format(modelInputTokens)} tokens`
    : modelInputSourceLine;
  const modelInputTitle = [
    lang === "zh"
      ? `模型输入 ${numberFormatter.format(modelInputTokens)}`
      : `Model input ${numberFormatter.format(modelInputTokens)}`,
    modelInputLimitTokens > 0 ? `${lang === "zh" ? "窗口" : "window"} ${numberFormatter.format(modelInputLimitTokens)} · ${modelInputPercent}%` : "",
    `${lang === "zh" ? "缓存输入" : "cached input"} ${numberFormatter.format(modelCachedInputTokens)}`,
    modelInputSourceLine,
    llmUsageTitle,
  ].filter(Boolean).join("\n");
  const lastCompression = compression?.lastCompression ?? null;
  const lastCompressionSourceText = (() => {
    if (!lastCompression) {
      return "";
    }
    switch (lastCompression.triggerSource) {
      case "manual":
        return lang === "zh" ? "Agent 主动请求" : "Agent requested";
      case "provider_limit":
        return lang === "zh" ? "上下文上限触发" : "Context limit triggered";
      case "auto":
        return lang === "zh" ? "阈值自动触发" : "Threshold triggered";
      default:
        return String(lastCompression.triggerSource || "").trim() || (lang === "zh" ? "未知来源" : "Unknown source");
    }
  })();
  const lastCompressionLine = lastCompression
    ? (lang === "zh"
      ? `${lastCompressionSourceText}，${lastCompression.level || "--"} 档：${numberFormatter.format(lastCompression.beforeTokens)} -> ${numberFormatter.format(lastCompression.afterTokens)}，节省 ${numberFormatter.format(lastCompression.savedTokens)} token`
      : `${lastCompressionSourceText}, ${lastCompression.level || "--"} level: ${numberFormatter.format(lastCompression.beforeTokens)} -> ${numberFormatter.format(lastCompression.afterTokens)}, saved ${numberFormatter.format(lastCompression.savedTokens)} tokens`)
    : t("compressionNoRecord");
  const compressionUpdatedLine = lastCompression?.timestamp
    ? formatRelativeTime(lastCompression.timestamp, Date.now(), locale) || formatTime(lastCompression.timestamp)
    : compression?.updatedAt
      ? formatRelativeTime(compression.updatedAt, Date.now(), locale) || formatTime(compression.updatedAt)
      : "";
  const sessionStateLabel = (() => {
    if (groupPanelActive) {
      return activeSurfaceStatus;
    }
    const runtimeSessionState = runtimeMatchesSelectedSession ? runtime?.sessionState : "";
    switch (runtimeSessionState) {
      case "thinking":
        return t("sessionStateThinking");
      case "tooling":
        return t("sessionStateTooling");
      case "answering":
        return t("sessionStateAnswering");
      default:
        return statusLabel(runtimeSessionState || detail?.currentPhase || directSessionActiveSummary?.currentPhase || directSessionActiveSummary?.status || "idle");
    }
  })();
  const sessionStateLine = groupPanelActive
    ? activeSurfaceLine
    : !activeSessionId
      ? noActiveDirectSessionLine
      : runtimeMatchesSelectedSession && runtime?.sessionStateLine
      ? runtime.sessionStateLine
      : runtimeMismatchLine || (sessionDetailErrorState.blockingError
        ? sessionDetailErrorMessage
        : activeAgentStatusMessage || detail?.taskSummary || directSessionActiveSummary?.taskSummary || (sessionDetailLoadingForActiveSession ? t("loadingSession") : t("preparingShell")));
  const compactSessionStateLine = detail?.lastTurnError
    ? [sessionStateLabel, detail.lastTurnError.httpStatus || detail.lastTurnError.reasonCode].filter(Boolean).join(" · ")
    : sessionStateLine;
  const activeTask = detail?.activeTask ?? null;
  const agentDirectSessionMismatch = Boolean(detail?.agentDirectSessionMismatch);
  const agentPrimaryDirectSessionId = String(detail?.agentPrimaryDirectSessionId ?? "").trim();
  const sessionBindingMismatchLine = agentDirectSessionMismatch ? t("sessionBindingMismatchLine") : "";
  const sessionStateValue = String(groupPanelActive ? (projectBusActive ? "ready" : activeGroupRoom?.status ?? "ready") : (runtimeMatchesSelectedSession ? runtime?.sessionState : "") || detail?.currentPhase || directSessionActiveSummary?.currentPhase || directSessionActiveSummary?.status || "idle")
    .trim()
    .toLowerCase();
  useEffect(() => {
    const sample = groupPanelActive
      ? null
      : tokenSpeedSampleFromMessages(
        detail?.id ?? activeSessionId,
        detail?.messages,
        sessionStateValue,
        Date.now(),
      );
    setTokenSpeedTracker((previous) => updateTokenSpeedTracker(previous, sample));
  }, [activeSessionId, detail?.id, detail?.messages, groupPanelActive, sessionStateValue]);
  const activeTaskSummary = agentDirectSessionMismatch
    ? ""
    : activeTask?.goal
      || activeTask?.title
      || activeTask?.nextAction
      || activeTask?.latestSummary
      || "";
  const currentTaskSummary =
    activeTaskSummary
    || detail?.taskSummary
    || directSessionActiveSummary?.taskSummary
    || (runtimeMatchesSelectedSession ? runtime?.taskSummary : "")
    || t("preparingShell");
  const fileContextValue = detail?.defaultFileContext ?? (runtimeMatchesSelectedSession ? runtime?.defaultRoute : undefined) ?? "workspace";
  const sessionCompactRows = buildVisiblePanelRows(
    [
      {
        label: t("fileContext"),
        value: fileContextValue,
        title: fileContextValue,
      },
      ...(agentDirectSessionMismatch ? [{
        label: t("sessionBinding"),
        value: t("sessionBindingHistorical"),
        title: `${sessionBindingMismatchLine} ${agentPrimaryDirectSessionId}`,
      }] : []),
      ...(latestControlSignal ? [{
        label: t("nextStateSignalsLabel"),
        value: latestControlSignalLine,
        title: latestControlSignalTitle,
      }] : []),
    ],
    [t("preparingShell"), t("loadingSession"), t("loadingContext")],
  );
  const tokenCompressionStrategyLevels = compression?.strategy?.levels ?? [];
  const tokenCompressionStrategyKeywords = (compression?.strategy?.errorProtectionKeywords ?? []).join(" / ") || "--";
  const tokenCompressionLevelLabel = compressionLevelLabel === "--"
    ? (lang === "zh" ? "默认" : "Default")
    : compressionLevelLabel;
  const tokenCompressionStrategyTitle = tokenCompressionStrategyLevels.length
    ? tokenCompressionStrategyLevels
      .map((level) => `${level.level}: ${Math.round(level.thresholdRatio * 100)}% / ${numberFormatter.format(level.thresholdTokens)}`)
      .join(" · ")
    : tokenCompressionStrategyKeywords;
  const compressionThresholdValue = compression
    ? `${numberFormatter.format(compression.currentTokens)} / ${numberFormatter.format(compression.effectiveTokenLimit)}`
    : t("loadingContext");
  const compressionThresholdMeta = compression
    ? (lang === "zh"
      ? `压缩阈值 ${compressionCurrentPercent}% · ${compressionLevelLabel}`
      : `threshold ${compressionCurrentPercent}% · ${compressionLevelLabel}`)
    : "";
  const tokenStatusCacheTitle = [
    cacheDetailOpenLabel,
    cacheCompositionTitle,
    cacheHitLine,
    llmUsageLine,
    llmUsageTitle,
  ].filter(Boolean).join("\n");
  const tokenStatusCompressionTitle = [
    compressionTitleLine,
    compressionThresholdValue,
    compressionThresholdMeta,
    compressionModelWindowLine !== "--" ? `${lang === "zh" ? "模型窗口" : "model window"} ${compressionModelWindowLine}` : "",
    tokenCompressionStrategyTitle !== "--" ? tokenCompressionStrategyTitle : "",
    lastCompressionLine,
    compressionUpdatedLine ? `${lang === "zh" ? "更新" : "updated"} ${compressionUpdatedLine}` : "",
  ].filter(Boolean).join("\n");
  const conversationChainTokenSpeedActive = Boolean(activeSessionId)
    && !groupPanelActive
    && isBusyPhase(sessionStateValue);
  const tokenSpeedRateValue = formatTokenSpeedValue(tokenSpeedTracker?.tokensPerSecond);
  const tokenSpeedValue = tokenSpeedRateValue
    || (conversationChainTokenSpeedActive ? t("tokenSpeedSampling") : "--");
  const tokenSpeedMeta = tokenSpeedRateValue
    ? t("tokenSpeedEstimated")
    : conversationChainTokenSpeedActive
      ? sessionStateLabel
      : t("tokenSpeedEstimated");
  const tokenSpeedTitle = [
    t("tokenSpeedEstimated"),
    sessionStateLabel,
    sessionStateLine,
    tokenSpeedTracker
      ? `${lang === "zh" ? "已估算输出" : "estimated output"} ${numberFormatter.format(tokenSpeedTracker.tokenCount)} tokens`
      : "",
  ].filter(Boolean).join("\n");
  const tokenSpeedPercent = clampPercent(
    tokenSpeedTracker?.tokensPerSecond
      ? Math.min(100, Math.round(tokenSpeedTracker.tokensPerSecond))
      : conversationChainTokenSpeedActive
        ? 8
        : 0,
  );
  const tokenStatusMetrics: TokenCoreStatusMetric[] = [
    {
      key: "cache",
      label: t("previousCacheHit"),
      value: cacheDetailAvailable ? `${cacheCompositionPercent}%` : "--",
      meta: cacheDetailAvailable
        ? `${numberFormatter.format(providerCachedInputTokens)} / ${numberFormatter.format(providerCacheInputTokens)}`
        : cacheCompositionSummary,
      title: tokenStatusCacheTitle,
      percent: clampPercent(cacheDetailAvailable ? cacheCompositionPercent : 0),
      tone: "cache",
    },
    {
      key: "modelInput",
      label: lang === "zh" ? "模型输入" : "Model input",
      value: modelInputAvailable ? numberFormatter.format(modelInputTokens) : "--",
      displayValue: modelInputAvailable ? compactNumberFormatter.format(modelInputTokens) : "--",
      meta: modelInputMetaLine,
      title: modelInputTitle,
      percent: clampPercent(modelInputPercent),
      tone: "modelInput",
    },
    {
      key: "compression",
      label: lang === "zh" ? "压缩状态" : "Compression",
      value: compression ? `${compressionCurrentPercent}%` : "--",
      meta: compression ? tokenCompressionLevelLabel : t("loadingContext"),
      title: tokenStatusCompressionTitle,
      percent: clampPercent(compression ? compressionCurrentPercent : 0),
      tone: "compression",
    },
    {
      key: "speed",
      label: t("tokenSpeed"),
      value: tokenSpeedValue,
      meta: tokenSpeedMeta,
      title: tokenSpeedTitle,
      percent: tokenSpeedPercent,
      tone: "speed",
    },
  ];
  const mental = runtime?.mentalState;
  const mentalCognitiveStateValue = String(mental?.cognitiveState ?? "unknown").trim().toLowerCase() || "unknown";
  const mentalSourceValue = String(mental?.source ?? "unavailable").trim().toLowerCase() || "unavailable";
  const mentalCognitiveStateLabel = (() => {
    switch (mentalCognitiveStateValue) {
      case "normal":
        return t("mentalCognitiveState_normal");
      case "productive":
        return t("mentalCognitiveState_productive");
      case "looping":
        return t("mentalCognitiveState_looping");
      case "thrashing":
        return t("mentalCognitiveState_thrashing");
      case "tunnel_vision":
        return t("mentalCognitiveState_tunnel_vision");
      case "disoriented":
        return t("mentalCognitiveState_disoriented");
      default:
        return t("mentalCognitiveState_unknown");
    }
  })();
  const mentalSourceLabel = (() => {
    switch (mentalSourceValue) {
      case "state":
        return t("mentalSourceState");
      case "diagnosis":
        return t("mentalSourceDiagnosis");
      default:
        return t("mentalSourceUnavailable");
    }
  })();
  const mentalStateLabel = mental?.mood?.trim() || mentalCognitiveStateLabel;
  const mentalSummary = mental?.feeling?.trim() || mental?.summary || t("mentalStatePending");
  const mentalWhisper = mental?.whisper?.trim() || t("mentalStatePending");
  const mentalConfidence =
    Number.isFinite(mental?.confidence)
      ? `${Math.round((mental?.confidence ?? 0) * 100)}%`
      : "--";
  const mentalRelativeTime = formatRelativeTime(mental?.updatedAt ?? "", Date.now(), locale) || "--";
  const mentalCompactLine = [
    mentalSourceLabel,
    mentalConfidence !== "--" ? `${t("mentalConfidence")} ${mentalConfidence}` : "",
    mentalRelativeTime !== "--" ? mentalRelativeTime : "",
  ]
    .filter(Boolean)
    .join(" · ");
  const petCompactLine = [
    petCompanionLine,
    pet?.heartActive ? t("heartActive") : t("heartIdle"),
    pet?.inDream ? t("dreamSleeping") : t("dreamAwake"),
    `${t("tokens")} ${numberFormatter.format(pet?.totalTokens ?? 0)}`,
  ]
    .filter(Boolean)
    .join(" · ");

  const agentsById = useMemo(() => {
    return new Map((agentsQuery.data ?? []).map((agent) => [agent.agentId, agent]));
  }, [agentsQuery.data]);

  const agentsByCode = useMemo(() => {
    const map = new Map<string, AgentInstance>();
    for (const agent of agentsQuery.data ?? []) {
      const code = String(agent.agentCode ?? "").trim();
      if (code) {
        map.set(code, agent);
      }
    }
    return map;
  }, [agentsQuery.data]);

  const resolveConversationTurnAvatar = useCallback((message: ConversationMessage): TurnAvatarResolution | undefined => {
    if (!isAgentInboxMessage(message)) {
      return undefined;
    }
    const metadata = message.metadata;
    const sourceAgentId = conversationMetadataText(metadata, "sourceAgentId");
    const sourceAgentCode = conversationMetadataText(metadata, "sourceAgentCode");
    const sourceAgentName = conversationMetadataText(metadata, "sourceAgentName");
    const agent =
      (sourceAgentId ? agentsById.get(sourceAgentId) : undefined)
      ?? (sourceAgentCode ? agentsByCode.get(sourceAgentCode) : undefined);
    return {
      imageUrl: avatarImageUrlFrom(agent),
      fallback: avatarInitials(sourceAgentCode, sourceAgentName),
    };
  }, [agentsByCode, agentsById]);

  const chatMentionTargets = useMemo(() => {
    return buildChatMentionTargets(agentsQuery.data ?? []);
  }, [agentsQuery.data]);

  const allVisibleSessions = useMemo(() => {
    const merged = [...(sessionsQuery.data ?? []), ...(childSessionsQuery.data ?? [])];
    return merged
      .filter(isVisibleDirectSession)
      .filter((session, index, sessions) => sessions.findIndex((item) => item.id === session.id) === index);
  }, [childSessionsQuery.data, sessionsQuery.data]);

  const sessionsById = useMemo(() => {
    return new Map(allVisibleSessions.map((session) => [session.id, session]));
  }, [allVisibleSessions]);

  const visibleChatAgents = useMemo(() => {
    return (agentsQuery.data ?? []).filter((agent) => {
      const visibility = String(agent.conversationIndexVisibility || "").trim();
      const kind = String(agent.conversationIndexKind || "").trim();
      return String(agent.kind || "").trim() === "persistent"
        && String(agent.status || "").trim() !== "archived"
        && visibility !== "hidden"
        && kind !== "team_agent";
    });
  }, [agentsQuery.data]);
  const activeSessionAgentId = useMemo(() => {
    return String(
      sessionDetailQuery.data?.agentId
      || directSessionActiveSummary?.agentId
      || sessionsById.get(activeSessionId || "")?.agentId
      || "",
    ).trim();
  }, [activeSessionId, directSessionActiveSummary?.agentId, sessionDetailQuery.data?.agentId, sessionsById]);
  useEffect(() => {
    if (activeSessionAgentId) {
      setSelectedAgentId(activeSessionAgentId);
    }
  }, [activeSessionAgentId]);
  const selectedChatAgentId = selectedAgentId || activeSessionAgentId || visibleChatAgents[0]?.agentId || "";
  const selectedAgentSessionsQuery = useQuery({
    queryKey: ["sessions", "agent", selectedChatAgentId],
    queryFn: () => fetchJson<SessionQueryResponse>(
      `/api/sessions/query?agentId=${encodeURIComponent(selectedChatAgentId)}&limit=100`,
    ),
    enabled: secondaryChatDataEnabled && Boolean(selectedChatAgentId),
    refetchInterval: chatLiveQueryPolicy.sessionsRefetchInterval,
    refetchIntervalInBackground: chatLiveQueryPolicy.directRefetchIntervalInBackground,
  });

  const contextMenuSession = useMemo(() => {
    if (!sessionContextMenu) {
      return undefined;
    }
    return sessionsById.get(sessionContextMenu.sessionId) ?? sessionContextMenu.session;
  }, [sessionContextMenu, sessionsById]);
  const contextMenuSessionId = sessionContextMenu?.sessionId ?? "";

  const rightIndexSessions = useMemo(() => {
    return allVisibleSessions.filter((session) => !isRepresentedInAgentSessionTabs(session));
  }, [allVisibleSessions]);

  const agentSessionTabs = useMemo(() => {
    const sessions = selectedAgentSessionsQuery.data?.items ?? [];
    return sessions
      .filter((session): session is SessionSummary => Boolean(session))
      .filter((session, index, items) => items.findIndex((item) => item.id === session.id) === index)
      .sort((left, right) => {
        const leftPriority = left.id === agentsById.get(selectedChatAgentId)?.directSessionId ? 0 : isChildSession(left) ? 2 : 1;
        const rightPriority = right.id === agentsById.get(selectedChatAgentId)?.directSessionId ? 0 : isChildSession(right) ? 2 : 1;
        if (leftPriority !== rightPriority) {
          return leftPriority - rightPriority;
        }
        return String(right.updatedAt || right.lastActive || "").localeCompare(String(left.updatedAt || left.lastActive || ""));
      });
  }, [agentsById, selectedAgentSessionsQuery.data?.items, selectedChatAgentId]);

  const groupCandidateAgents = useMemo(() => {
    return (agentsQuery.data ?? []).filter((agent) => {
      return (
        String(agent.kind ?? "").trim() === "persistent"
        && String(agent.status ?? "").trim() !== "archived"
        && String(agent.directSessionId ?? "").trim()
      );
    });
  }, [agentsQuery.data]);

  const readyChatRoomModes = useMemo(() => {
    const modes = (chatRoomModesQuery.data ?? []).filter((mode) => String(mode.status ?? "").trim() === "ready");
    return modes.length ? modes : [{ id: "round_robin", label: "Round robin", status: "ready" }];
  }, [chatRoomModesQuery.data]);
  const availableChatRoomPurposes = useMemo(() => {
    const purposes = chatRoomPurposesQuery.data ?? [];
    return purposes.length
      ? purposes
      : [
          { id: "chat", label: "Chat", description: "" },
          { id: "discussion", label: "Discussion", description: "" },
          { id: "meeting", label: "Meeting", description: "" },
          { id: "medical_triage", label: "Medical triage", description: "" },
        ];
  }, [chatRoomPurposesQuery.data]);

  const activeGroupTeamMemberByAgentId = useMemo(() => {
    return new Map(
      (activeGroupTeam?.members ?? [])
        .map((member) => [String(member.agentId ?? "").trim(), member] as const)
        .filter(([agentId]) => Boolean(agentId)),
    );
  }, [activeGroupTeam?.members]);
  const groupParticipantIdentity = useCallback(
    (
      participant: ChatRoomParticipant | undefined,
      fallback: { agentId?: string; agentCode?: string; title?: string; participantId?: string; agentAvatarImageUrl?: string } = {},
    ) => {
      const agentId = String(participant?.agentId || fallback.agentId || "").trim();
      const participantLike = participant ?? {
        participantId: String(fallback.participantId || agentId || "agent").trim(),
        kind: "session_agent",
        agentId,
        agentCode: String(fallback.agentCode || "").trim(),
        agentAvatarImageUrl: String(fallback.agentAvatarImageUrl || "").trim(),
        sessionId: "",
        title: String(fallback.title || fallback.participantId || agentId || "Agent").trim(),
        enabled: true,
        status: "",
      };
      const participantAgent = agentId ? agentsById.get(agentId) : undefined;
      const display = participantAgentDisplayInfo(participantLike, participantAgent, lang, resolveModelLabel);
      const member = agentId ? activeGroupTeamMemberByAgentId.get(agentId) : undefined;
      const participantTeamRole = String(participant?.teamMemberPurpose || participant?.teamRole || "").trim();
      const role = String(participantTeamRole || member?.purpose || member?.role || display.functionLabel || "").trim();
      const name = String(display.name || fallback.title || fallback.participantId || "Agent").trim();
      const compactRole = compactAgentRoleLabel(role || display.functionLabel);
      return {
        ...display,
        name,
        functionLabel: role || display.functionLabel,
        compactRole,
        avatarImageUrl: avatarImageUrlFrom(participantAgent, participantLike, fallback),
        identityLabel: formatAgentIdentityWithRole(name, compactRole, fallback.participantId || "Agent"),
        fullIdentityLabel: [
          formatAgentIdentityWithRole(name, role || display.functionLabel, fallback.participantId || "Agent"),
          display.modelLabel,
        ].filter(Boolean).join(" · "),
      };
    },
    [activeGroupTeamMemberByAgentId, agentsById, lang, resolveModelLabel],
  );
  const {
    filteredConversations,
    filteredStandaloneGroupConversations,
    filteredTeams,
    groupedConversations,
    searchHasTerm,
  } = useConversationIndexModel({
    agents: agentsQuery.data,
    conversations: conversationsQuery.data,
    lang,
    linkedTeamRoomIds,
    rawSessions: rawSessionsQuery.data,
    rightIndexSessions,
    sessionFilter,
    sessionsById,
    teams,
  });
  const groupedGroupConversations = useMemo(() => {
    return groupedConversations
      .map((group) => ({ ...group, items: group.items.filter((conversation) => conversation.type === "group_room") }))
      .filter((group) => group.items.length > 0);
  }, [groupedConversations]);
  const groupedGroupConversationCount = useMemo(
    () => groupedGroupConversations.reduce((count, group) => count + group.items.length, 0),
    [groupedGroupConversations],
  );
  const sessionIndexLoadedCount = rawSessionsQuery.loadedCount;
  const sessionIndexTotalEstimate = rawSessionsQuery.totalEstimate;
  const sessionIndexHasMore = rawSessionsQuery.hasMore;
  const sessionIndexLoadMoreLabel = rawSessionsQuery.isLoadingMore
    ? (lang === "zh" ? "加载中" : "Loading")
    : (lang === "zh" ? "加载更多会话" : "Load more chats");
  const sessionIndexFullyLoadedLabel = lang === "zh" ? "已加载全部会话" : "All chats loaded";
  const sessionIndexProgressLabel =
    sessionIndexTotalEstimate > sessionIndexLoadedCount
      ? `${numberFormatter.format(sessionIndexLoadedCount)} / ${numberFormatter.format(sessionIndexTotalEstimate)}`
      : numberFormatter.format(sessionIndexLoadedCount);
  const sessionIndexProgressVisible = sessionIndexHasMore || sessionIndexTotalEstimate > SESSION_INDEX_PAGE_SIZE;

  function formatTime(value: string) {
    if (!value) {
      return "";
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      return value;
    }
    return timeFormatter.format(parsed);
  }

  function formatConversationIndexTime(value: string) {
    return formatTime(value).replace(/:\d{2}$/, "");
  }

  function toggleConversationGroup(groupKey: ConversationIndexDynamicGroupKey) {
    setCollapsedConversationGroups((current) => ({
      ...current,
      [groupKey]: !(current[groupKey] ?? defaultConversationGroupCollapsed(groupKey)),
    }));
  }

  function handleComposerChange(value: string) {
    if (!activeSessionId) {
      return;
    }
    setSessionDrafts((current) => ({
      ...current,
      [activeSessionId]: value,
    }));
    setSessionComposerErrors((current) => ({
      ...current,
      [activeSessionId]: "",
    }));
  }

  function handleMentalModelEnabledChange(enabled: boolean) {
    setMentalModelEnabledForNextTurn(enabled);
    writeStoredMentalModelToggle(enabled);
  }

  function handleAddComposerAttachments(files: FileList | File[]) {
    if (!activeSessionId) {
      return;
    }
    if (activeAgentImageInputUnsupported) {
      setSessionComposerErrors((current) => ({
        ...current,
        [activeSessionId]: lang === "zh" ? "当前 Agent 模型不支持图片输入。" : "The current Agent model does not support image input.",
      }));
      return;
    }
    const { accepted, rejected } = classifyComposerImageFiles(files);
    if (!accepted.length && !rejected.length) {
      return;
    }
    if (accepted.length) {
      setSessionImageAttachments((current) => {
        const existing = current[activeSessionId] ?? [];
        return {
          ...current,
          [activeSessionId]: mergeComposerImageAttachments(existing, accepted, MAX_COMPOSER_IMAGE_ATTACHMENTS),
        };
      });
    }
    setSessionComposerErrors((current) => ({
      ...current,
      [activeSessionId]: rejected.length
        ? (lang === "zh" ? "部分图片格式或大小不支持。" : "Some images were rejected by type or size.")
        : "",
    }));
  }

  function handleRemoveComposerAttachment(attachmentId: string) {
    if (!activeSessionId) {
      return;
    }
    setSessionImageAttachments((current) => removeSessionImageAttachment(current, activeSessionId, attachmentId));
  }

  function handleAddComposerReference(reference: SessionReferenceAttachment) {
    if (!activeSessionId) {
      return;
    }
    const referenceId = sessionReferenceId(reference);
    if (!referenceId) {
      setSessionComposerErrors((current) => ({
        ...current,
        [activeSessionId]: lang === "zh" ? "会话引用缺少有效 id。" : "Session reference is missing a valid id.",
      }));
      return;
    }
    setSessionReferenceAttachments((current) => {
      const existing = current[activeSessionId] ?? [];
      if (existing.some((item) => sessionReferenceId(item) === referenceId)) {
        return current;
      }
      return {
        ...current,
        [activeSessionId]: [...existing, reference].slice(-6),
      };
    });
    setSessionComposerErrors((current) => ({
      ...current,
      [activeSessionId]: "",
    }));
  }

  function handleRemoveComposerReference(referenceId: string) {
    if (!activeSessionId) {
      return;
    }
    setSessionReferenceAttachments((current) => {
      const existing = current[activeSessionId] ?? [];
      const next = existing.filter((reference) => sessionReferenceId(reference) !== referenceId);
      if (next.length === existing.length) {
        return current;
      }
      if (!next.length) {
        return clearSessionReferenceAttachments(current, activeSessionId);
      }
      return {
        ...current,
        [activeSessionId]: next,
      };
    });
  }

  function handlePetInteraction(action: PetInteractionAction) {
    setPetActionFeedback("");
    petActionMutation.mutate({ action });
  }

  function handleCreateSession() {
    setActiveGroupRoomId("");
    setRightIndexPanel("conversations");
    setSessionComposerErrors((current) => ({
      ...current,
      __sessions__: "",
    }));
    createSessionMutation.mutate({ agentId: selectedChatAgentId });
  }

  function handleCreateAgent() {
    setAgentCreateWizardOpen(true);
  }

  function handleOpenProjectAgentBus() {
    setSessionContextMenu(null);
    navigate("/chat", { replace: false });
    setActiveGroupRoomId("__project_agent_bus__");
    setRightIndexPanel("conversations");
    setRightPaneCollapsed(false);
    setGroupRoomActionError("");
    void chatWorkspaceCache.afterProjectBusFailed();
  }

  function handleOpenDirectSession(sessionId: string) {
    const normalizedSessionId = String(sessionId || "").trim();
    if (!normalizedSessionId) {
      return;
    }
    setSessionContextMenu(null);
    latestDirectSessionSelectionRef.current = normalizedSessionId;
    setActiveSession(normalizedSessionId);
    setActiveGroupRoomId("");
    setRightIndexPanel("conversations");
    setGroupRoomActionError("");
    setSessionComposerErrors((current) => ({
      ...current,
      [normalizedSessionId]: "",
      __sessions__: "",
    }));
    selectDirectSessionMutation.mutate(normalizedSessionId);
    navigate(`/chat?session=${encodeURIComponent(normalizedSessionId)}`, { replace: false });
  }

  function handleOpenAgent(agent: AgentInstance) {
    const agentId = String(agent.agentId || "").trim();
    const primarySessionId = String(agent.directSessionId || "").trim();
    if (!agentId || !primarySessionId) {
      return;
    }
    setSelectedAgentId(agentId);
    handleOpenDirectSession(primarySessionId);
  }

  function handleOpenMentionTarget(target: ChatMentionTarget) {
    setRightPaneCollapsed(false);
    setGroupRoomActionError("");
    if (target.kind === "all") {
      setActiveGroupRoomId("__project_agent_bus__");
      setRightIndexPanel("conversations");
      setSessionFilter("");
      void chatWorkspaceCache.afterProjectBusFailed();
      return;
    }
    if (target.directSessionId) {
      setSessionFilter("");
      handleOpenDirectSession(target.directSessionId);
      return;
    }
    const fallbackFilter = target.agentCode || target.displayName || target.agentId || "";
    if (fallbackFilter) {
      setActiveGroupRoomId("");
      setRightIndexPanel("conversations");
      setSessionFilter(fallbackFilter);
    }
  }

  function renderMentionedText(content: string, fallback = "") {
    const text = content || fallback;
    return tokenizeChatMentions(text, chatMentionTargets).map((segment, index) => {
      if (segment.type === "text") {
        return <span key={`text-${index}`}>{segment.text}</span>;
      }
      const mentionLabel = segment.target.kind === "all"
        ? (lang === "zh" ? "全体成员" : "All agents")
        : [segment.target.displayName, segment.target.agentCode].filter(Boolean).join(" · ");
      return (
        <VButton
          key={`mention-${index}-${segment.text}`}
          type="button"
          className={styles.agentMention}
          onClick={() => handleOpenMentionTarget(segment.target)}
          aria-label={lang === "zh" ? `打开 ${mentionLabel} 的索引` : `Open ${mentionLabel} index`}
          title={lang === "zh" ? "打开对应 Agent 索引" : "Open the matching agent index"}
        >
          {segment.text}
        </VButton>
      );
    });
  }

  function renderGroupMessageBody(message: ChatRoomMessage, identityName: string) {
    const content = stripGroupSpeakerPrefix(message, identityName);
    const expanded = expandedGroupMessageIds.includes(message.messageId);
    const defaultCollapsed = shouldDefaultCollapseGroupMessage(message);
    const collapsible = defaultCollapsed || shouldCollapseGroupMessage(content);
    const collapsed = collapsible && !expanded;
    const collapseLabel = defaultCollapsed
      ? (lang === "zh" ? "展开讨论" : "Show discussion")
      : (lang === "zh" ? "展开全文" : "Show full");
    return (
      <>
        <p className={collapsed ? `${styles.groupBubbleBody} ${styles.groupBubbleBodyCollapsed}` : styles.groupBubbleBody}>
          {renderMentionedText(content, lang === "zh" ? "暂无内容" : "No content yet")}
        </p>
        {collapsible ? (
          <VButton
            type="button"
            className={styles.groupBubbleToggle}
            onClick={() =>
              setExpandedGroupMessageIds((current) =>
                current.includes(message.messageId)
                  ? current.filter((messageId) => messageId !== message.messageId)
                  : [...current, message.messageId],
              )}
          >
            {expanded ? (lang === "zh" ? "收起" : "Collapse") : collapseLabel}
          </VButton>
        ) : null}
      </>
    );
  }

  function handleOpenGroupRoom(roomId: string) {
    if (!roomId) {
      return;
    }
    navigate(`/chat?room=${encodeURIComponent(roomId)}`, { replace: false });
    setActiveGroupRoomId(roomId);
    setRightIndexPanel("members");
    setRightPaneCollapsed(false);
    setGroupRoomActionError("");
    void chatWorkspaceCache.afterChatRoomChanged(roomId);
  }

  function handleToggleGroupManageSession(sessionId: string) {
    if (!sessionId || activeGroupTeamOwned || groupRoundActive || updateGroupRoomMutation.isPending) {
      return;
    }
    setGroupRoomActionError("");
    setGroupManageSessionIds((current) =>
      current.includes(sessionId)
        ? current.filter((item) => item !== sessionId)
        : [...current, sessionId],
    );
  }

  function handleToggleGroupComposer() {
    setSessionComposerErrors((current) => ({
      ...current,
      __sessions__: "",
    }));
    setGroupComposerOpen((open) => {
      const nextOpen = !open;
      if (nextOpen && !groupTitleDraft.trim()) {
        setGroupTitleDraft(lang === "zh" ? "Agent 群聊" : "Agent group");
      }
      return nextOpen;
    });
  }

  function handleToggleGroupAgent(agentId: string) {
    setSessionComposerErrors((current) => ({
      ...current,
      __sessions__: "",
    }));
    setGroupSelectedAgentIds((current) =>
      current.includes(agentId) ? current.filter((item) => item !== agentId) : [...current, agentId],
    );
  }

  function handleCreateGroupRoom() {
    const title = groupTitleDraft.trim();
    const agentIds = groupSelectedAgentIds.filter(Boolean);
    if (!title || agentIds.length < 2 || createGroupRoomMutation.isPending) {
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: lang === "zh" ? "请输入群聊名称，并至少选择两个 Agent。" : "Enter a group name and choose at least two agents.",
      }));
      return;
    }
    createGroupRoomMutation.mutate({
      title,
      agentIds,
      mode: groupModeDraft || "round_robin",
      purpose: groupPurposeDraft || "discussion",
    });
  }

  function handleStartGroupRound() {
    const topic = groupTopicDraft.trim();
    if (!standardGroupRoomActive || !activeGroupRoomId || !topic || startGroupRoundMutation.isPending || groupRoundActive) {
      return;
    }
    startGroupRoundMutation.mutate({
      roomId: activeGroupRoomId,
      topic,
      mode: activeGroupRoom?.mode || "round_robin",
      purpose: activeGroupRoom?.purpose || "discussion",
    });
  }

  function handleStopGroupRound() {
    if (!standardGroupRoomActive || !activeGroupRoomId || !groupRoundRunning || stopGroupRoundMutation.isPending) {
      return;
    }
    stopGroupRoundMutation.mutate({
      roomId: activeGroupRoomId,
    });
  }

  function handleSendProjectBusMessage() {
    const content = projectBusDraft.trim();
    if (!content || sendProjectBusMessageMutation.isPending) {
      return;
    }
    sendProjectBusMessageMutation.mutate({
      content,
      interruptTargets: projectBusInterruptTargets,
    });
  }

  function handleRevokeProjectBusMessage(eventId: string) {
    if (!eventId || revokeProjectBusMessageMutation.isPending) {
      return;
    }
    revokeProjectBusMessageMutation.mutate({ eventId });
  }

  function handleApplyGroupRoomManagement() {
    if (!standardGroupRoomActive || activeGroupTeamOwned || !activeGroupRoomId || groupManageDisabled) {
      return;
    }
    updateGroupRoomMutation.mutate({
      roomId: activeGroupRoomId,
      title: groupManageTitleDraft.trim(),
      sessionIds: groupManageSessionIds,
      mode: groupManageModeDraft || "round_robin",
      purpose: groupManagePurposeDraft || "discussion",
    });
  }

  function handleDeleteActiveGroupRoom() {
    if (!standardGroupRoomActive || activeGroupTeamOwned || !activeGroupRoomId || groupDeleteDisabled) {
      return;
    }
    const roomTitle = (activeGroupRoom?.title || activeGroupRoomId).trim();
    const groupConfirmMessage = t("deleteGroupConfirm").replace("{title}", roomTitle || activeGroupRoomId);
    if (!window.confirm(groupConfirmMessage)) {
      return;
    }
    deleteGroupRoomMutation.mutate({ roomId: activeGroupRoomId });
  }

  function handleResetActiveGroupRoom() {
    if (!standardGroupRoomActive || !activeGroupRoomId || groupResetDisabled) {
      return;
    }
    const roomTitle = (activeGroupRoom?.title || activeGroupRoomId).trim();
    const groupConfirmMessage = t("resetGroupConfirm").replace("{title}", roomTitle || activeGroupRoomId);
    if (!window.confirm(groupConfirmMessage)) {
      return;
    }
    resetGroupRoomMutation.mutate({ roomId: activeGroupRoomId });
  }

  function handleDeleteSession(session: SessionSummary) {
    setSessionContextMenu(null);
    if (isBusyPhase(session.currentPhase || session.status)) {
      setSessionComposerErrors((current) => ({
        ...current,
        [session.id]: t("deleteSessionBusy"),
        __sessions__: "",
      }));
      return;
    }
    const sessionTitle = (session.agentDisplayName || session.title || session.id).trim();
    const sessionConfirmMessage = t("deleteSessionConfirm").replace("{title}", sessionTitle || session.id);
    if (!window.confirm(sessionConfirmMessage)) {
      return;
    }
    setSessionComposerErrors((current) => ({
      ...current,
      [session.id]: "",
      __sessions__: "",
    }));
    deleteSessionMutation.mutate({ sessionId: session.id });
  }

  function handleClearSessionHistory(session: SessionSummary) {
    setSessionContextMenu(null);
    if (!session.agentId || !isAgentRootSession(session)) {
      return;
    }
    if (isBusyPhase(session.currentPhase || session.status)) {
      setSessionComposerErrors((current) => ({
        ...current,
        [session.id]: t("clearSessionHistoryBusy"),
        __sessions__: "",
      }));
      return;
    }
    const sessionTitle = (session.agentDisplayName || session.title || session.id).trim();
    const confirmMessage = t("clearSessionHistoryConfirm").replace("{title}", sessionTitle || session.id);
    if (!window.confirm(confirmMessage)) {
      return;
    }
    setSessionComposerErrors((current) => ({
      ...current,
      [session.id]: "",
      __sessions__: "",
    }));
    clearSessionHistoryMutation.mutate({ sessionId: session.id, agentId: session.agentId });
  }

  function handleAddSessionToReview(session: SessionSummary) {
    setSessionContextMenu(null);
    if (isBusyPhase(session.currentPhase || session.status)) {
      setSessionComposerErrors((current) => ({
        ...current,
        [session.id]: t("addSessionToReviewBusy"),
        __sessions__: "",
      }));
      return;
    }
    setSessionComposerErrors((current) => ({
      ...current,
      [session.id]: "",
      __sessions__: "",
    }));
    addSessionToReviewMutation.mutate({ sessionId: session.id });
  }

  function beginRenameSession(session: SessionSummary) {
    setSessionContextMenu(null);
    setEditingSessionId(session.id);
    setEditingSessionTitle(
      isAgentRootSession(session)
        ? (session.agentDisplayName || session.title)
        : isChildSession(session)
          ? (session.taskTitle || session.resultCard?.title || session.title)
          : session.title,
    );
    setSessionComposerErrors((current) => ({
      ...current,
      [session.id]: "",
      __sessions__: "",
    }));
  }

  function openSessionAgentConfig(session: SessionSummary) {
    const agentId = String(session.agentId || "").trim();
    if (!agentId) {
      setSessionContextMenu(null);
      return;
    }
    setSessionContextMenu(null);
    navigate(agentCenterConfigRoute({
      agentId,
      pane: "config",
      returnLabel: "chat",
      returnTo: `/chat?session=${encodeURIComponent(session.id)}`,
    }));
  }

  function cancelRenameSession() {
    setSessionContextMenu(null);
    setEditingSessionId(null);
    setEditingSessionTitle("");
  }

  function openSessionContextMenu(event: ReactMouseEvent<HTMLElement>, session: SessionSummary) {
    event.preventDefault();
    event.stopPropagation();
    setSessionContextMenu({
      sessionId: session.id,
      session,
      x: event.clientX,
      y: event.clientY,
    });
  }

  function submitRenameSession(session: SessionSummary) {
    const title = editingSessionTitle.trim();
    if (!title) {
      setSessionComposerErrors((current) => ({
        ...current,
        [session.id]: t(isAgentRootSession(session) ? "renameAgentEmpty" : isChildSession(session) ? "renameTaskEmpty" : "renameSessionEmpty"),
      }));
      return;
    }
    const currentTitle = isAgentRootSession(session)
      ? (session.agentDisplayName || session.title)
      : isChildSession(session)
        ? (session.taskTitle || session.resultCard?.title || session.title)
        : session.title;
    if (title === currentTitle) {
      cancelRenameSession();
      return;
    }
    renameSessionMutation.mutate({ sessionId: session.id, title });
  }

  const toggleFeaturePreset = useCallback((key: FeaturePresetKey) => {
    setFeaturePresetState((current) => ({
      ...current,
      [key]: !current[key],
    }));
  }, []);

  const contextMenuSessionIsBusy = contextMenuSession
    ? isBusyPhase(contextMenuSession.currentPhase || contextMenuSession.status)
    : false;
  const contextMenuDeletePending = Boolean(
    contextMenuSession
    && deleteSessionMutation.isPending
    && deleteSessionMutation.variables?.sessionId === contextMenuSession.id,
  );
  const contextMenuAddToReviewPending = Boolean(
    contextMenuSession
    && addSessionToReviewMutation.isPending
    && addSessionToReviewMutation.variables?.sessionId === contextMenuSession.id,
  );
  const contextMenuClearHistoryPending = Boolean(
    contextMenuSession
    && clearSessionHistoryMutation.isPending
    && clearSessionHistoryMutation.variables?.sessionId === contextMenuSession.id
  );
  const contextMenuClearHistoryVisible = Boolean(
    contextMenuSession?.agentId
    && isAgentRootSession(contextMenuSession)
  );
  const contextMenuDeleteDisabled = contextMenuDeletePending || contextMenuSessionIsBusy;
  const contextMenuAddToReviewDisabled = contextMenuAddToReviewPending || contextMenuSessionIsBusy;
  const contextMenuClearHistoryDisabled = contextMenuClearHistoryPending || contextMenuSessionIsBusy;
  const conversationIndexPanel = (
    <>
      {sessionComposerErrors.__sessions__ ? (
        <VStateSurface
          className={styles.panelState}
          tone="error"
          title={sessionComposerErrors.__sessions__}
        />
      ) : null}
      {sessionsErrorState.transientError ? (
        <div className={styles.panelNotice} role="status">{sessionsErrorMessage}</div>
      ) : null}
      {sessionsErrorState.blockingError ? (
        <VStateSurface className={styles.panelState} tone="error" title={sessionsErrorMessage} />
      ) : conversationsQuery.isPending && !conversationsQuery.data && sessionsQuery.isPending && !sessionsQuery.data ? (
        <ConversationIndexLoadingShell label={t("loadingSession")} />
      ) : filteredConversations.length === 0 && visibleChatAgents.length === 0 && filteredTeams.length === 0 && filteredStandaloneGroupConversations.length === 0 ? (
        <VStateSurface
          className={styles.panelState}
          tone="empty"
          title={sessionFilter.trim() ? t("noSessionMatches") : t("noSessionsYet")}
        />
      ) : (
        <>
          <AgentConversationDirectory
            activeAgentId={selectedChatAgentId}
            agents={visibleChatAgents}
            avatarInitials={avatarInitials}
            filterText={sessionFilter}
            formatTime={formatConversationIndexTime}
            lang={lang}
            resolveModelLabel={resolveModelLabel}
            sessions={allVisibleSessions}
            onOpenAgent={handleOpenAgent}
          />
          <ConversationIndexTree
            activeGroupRoomId={activeGroupRoomId}
            activeSessionId={activeSessionId}
            addToReviewSucceededLabel={t("addSessionToReviewSucceeded")}
            agentsById={agentsById}
            avatarImageUrlFrom={avatarImageUrlFrom}
            avatarInitials={avatarInitials}
            buildSessionReferencePayload={buildSessionReferencePayload}
            collapsedConversationGroups={collapsedConversationGroups}
            contextMenuSessionId={contextMenuSessionId}
            conversationGroupLabel={conversationGroupLabel}
            deleteBusyLabel={t("deleteSessionBusy")}
            editingSessionId={editingSessionId}
            editingSessionTitle={editingSessionTitle}
            filteredConversationsCount={groupedGroupConversationCount}
            filteredStandaloneGroupConversations={filteredStandaloneGroupConversations}
            filteredTeams={filteredTeams}
            formatTime={formatConversationIndexTime}
            groupPanelActive={groupPanelActive}
            groupedConversations={groupedGroupConversations}
            isBusyPhase={isBusyPhase}
            lang={lang}
            renamePending={renameSessionMutation.isPending}
            renameSessionId={renameSessionMutation.variables?.sessionId ?? ""}
            resolveModelLabel={resolveModelLabel}
            searchHasTerm={searchHasTerm}
            sessionComposerErrors={sessionComposerErrors}
            sessionsById={sessionsById}
            statusLabel={statusLabel}
            t={t}
            onCancelRename={cancelRenameSession}
            onContextMenu={openSessionContextMenu}
            onDragReference={startSessionReferenceDrag}
            onOpenDirectSession={handleOpenDirectSession}
            onOpenGroupRoom={handleOpenGroupRoom}
            onRenameTitleChange={setEditingSessionTitle}
            onSubmitRename={submitRenameSession}
            onToggleConversationGroup={toggleConversationGroup}
          />
          {sessionIndexHasMore ? (
            <VButton
              type="button"
              className={styles.sessionLoadMoreButton}
              onClick={() => rawSessionsQuery.loadMore()}
              isDisabled={rawSessionsQuery.isLoadingMore}
              aria-label={sessionIndexLoadMoreLabel}
            >
              <span>{sessionIndexLoadMoreLabel}</span>
              <strong>{sessionIndexProgressLabel}</strong>
            </VButton>
          ) : sessionIndexProgressVisible ? (
            <div className={styles.sessionLoadMoreStatus} role="status">
              <span>{sessionIndexFullyLoadedLabel}</span>
              <strong>{sessionIndexProgressLabel}</strong>
            </div>
          ) : null}
          {sessionContextMenu && contextMenuSession ? (
            <SessionContextMenu
              addToReviewDisabled={contextMenuAddToReviewDisabled}
              addToReviewPending={contextMenuAddToReviewPending}
              clearHistoryDisabled={contextMenuClearHistoryDisabled}
              clearHistoryPending={contextMenuClearHistoryPending}
              clearHistoryVisible={contextMenuClearHistoryVisible}
              deleteDisabled={contextMenuDeleteDisabled}
              lang={lang}
              position={sessionContextMenu}
              session={contextMenuSession}
              t={t}
              onAddToReview={handleAddSessionToReview}
              onClearHistory={handleClearSessionHistory}
              onDelete={handleDeleteSession}
              onOpenAgentConfig={openSessionAgentConfig}
              onRename={beginRenameSession}
            />
          ) : null}
        </>
      )}
    </>
  );

  return (
    <div
      ref={layoutRef}
      className={chatLayoutClassName}
      style={layoutStyle}
      data-chat-responsive-mode={responsiveLayout.mode}
      data-chat-status-rail={statusRailCollapsed ? "collapsed" : "visible"}
    >
      {responsiveOverlayOpen ? (
        <VButton
          type="button"
          className={styles.overlayBackdrop}
          aria-label={lang === "zh" ? "关闭侧栏" : "Close side panel"}
          onClick={closeResponsiveOverlayPane}
        >
          <span className="sr-only">{lang === "zh" ? "关闭侧栏" : "Close side panel"}</span>
        </VButton>
      ) : null}
      <ChatStatusRail
        statusRailClassName={statusRailClassName}
        statusRailCollapsed={statusRailCollapsed}
        statusRailOverlayOpen={statusRailOverlayOpen}
        standardGroupRoomActive={standardGroupRoomActive}
        lang={lang}
        t={t}
        numberFormatter={numberFormatter}
        activeGroupRoom={activeGroupRoom}
        activeGroupTeamOwned={activeGroupTeamOwned}
        activeGroupTeam={activeGroupTeam}
        availableGroupParticipantCount={availableGroupParticipantCount}
        statusLabel={statusLabel}
        groupManageChanged={groupManageChanged}
        groupManageDisabled={groupManageDisabled}
        groupDeleteDisabled={groupDeleteDisabled}
        groupResetDisabled={groupResetDisabled}
        groupRoundActive={groupRoundActive}
        groupRoundRunning={groupRoundRunning}
        groupRoomActionError={groupRoomActionError}
        setGroupRoomActionError={setGroupRoomActionError}
        groupManageTitleDraft={groupManageTitleDraft}
        setGroupManageTitleDraft={setGroupManageTitleDraft}
        groupManageModeDraft={groupManageModeDraft}
        setGroupManageModeDraft={setGroupManageModeDraft}
        groupManagePurposeDraft={groupManagePurposeDraft}
        setGroupManagePurposeDraft={setGroupManagePurposeDraft}
        readyChatRoomModes={readyChatRoomModes}
        availableChatRoomPurposes={availableChatRoomPurposes}
        chatRoomModeLabel={chatRoomModeLabel}
        chatRoomPurposeLabel={chatRoomPurposeLabel}
        groupManageSessionIds={groupManageSessionIds}
        groupManageSessionSet={groupManageSessionSet}
        sessions={sessionsQuery.data}
        agentsById={agentsById}
        resolveModelLabel={resolveModelLabel}
        renderAgentAvatar={renderAgentAvatar}
        avatarInitials={avatarInitials}
        agentRoleClass={agentRoleClass}
        avatarImageUrlFrom={avatarImageUrlFrom}
        updateGroupRoomPending={updateGroupRoomMutation.isPending}
        deleteGroupRoomPending={deleteGroupRoomMutation.isPending}
        resetGroupRoomPending={resetGroupRoomMutation.isPending}
        onOpenTeam={(teamId) => navigate(`/teams?team=${encodeURIComponent(teamId)}`)}
        onApplyGroupRoomManagement={handleApplyGroupRoomManagement}
        onDeleteActiveGroupRoom={handleDeleteActiveGroupRoom}
        onResetActiveGroupRoom={handleResetActiveGroupRoom}
        onToggleGroupManageSession={handleToggleGroupManageSession}
        activeSurfaceTitle={activeSurfaceTitle}
        sessionStateValue={sessionStateValue}
        sessionStateLabel={sessionStateLabel}
        sessionStateLine={sessionStateLine}
        compactSessionStateLine={compactSessionStateLine}
        agentDirectSessionMismatch={agentDirectSessionMismatch}
        agentPrimaryDirectSessionId={agentPrimaryDirectSessionId}
        sessionBindingMismatchLine={sessionBindingMismatchLine}
        onOpenDirectSession={handleOpenDirectSession}
        sessionCompactRows={sessionCompactRows}
        activeSkillSummary={Boolean(activeSkillSummary)}
        activeSkillStatusStyle={activeSkillStatusStyle}
        activeSkillTitle={activeSkillTitle}
        activeSkillName={activeSkillName}
        activeSkillCommand={activeSkillCommand}
        activeSkillStatusLabel={activeSkillStatusLabel}
        activeSkillShortHash={activeSkillShortHash}
        mentalModelEnabledForNextTurn={mentalModelEnabledForNextTurn}
        activeSessionId={activeSessionId}
        onMentalModelEnabledChange={handleMentalModelEnabledChange}
        featurePresetState={featurePresetState}
        onToggleFeaturePreset={toggleFeaturePreset}
        cacheDetailAvailable={cacheDetailAvailable}
        cacheDetailOpen={cacheDetailOpen}
        cacheDetailOpenLabel={cacheDetailOpenLabel}
        tokenStatusMetrics={tokenStatusMetrics}
        onOpenCacheDetail={openCacheDetail}
        lastLlmPayloadTrace={lastLlmPayloadTrace}
        mentalCompactLine={mentalCompactLine}
        mentalSourceLabel={mentalSourceLabel}
        mentalCognitiveStateValue={mentalCognitiveStateValue}
        mentalStateLabel={mentalStateLabel}
        mentalSummary={mentalSummary}
        mentalWhisper={mentalWhisper}
        mentalCognitiveStateLabel={mentalCognitiveStateLabel}
        mentalConfidence={mentalConfidence}
        mentalRelativeTime={mentalRelativeTime}
        formatTime={formatTime}
        mental={mental}
        pet={pet}
        petPresetLabel={petPresetLabel}
        petCompactLine={petCompactLine}
        petAvatarSkinStyle={petAvatarSkinStyle}
        petAvatarSymbol={petAvatarSymbol}
        petVitals={petVitals}
        petInteractionLabels={petInteractionLabels}
        petActionPending={petActionMutation.isPending}
        petActionFeedback={petActionFeedback}
        onPetInteraction={handlePetInteraction}
      />

      {responsiveLayout.leftVisible ? <PaneCollapseHandle
        side="left"
        collapsed={conversationIndexCollapsed}
        separatorLabel={t("resizeLeftPanel")}
        collapseLabel={lang === "zh" ? "收起会话列" : "Collapse conversation column"}
        expandLabel={lang === "zh" ? "展开会话列" : "Expand conversation column"}
        className={`${styles.resizeHandle} ${styles.resizeHandleLeft}`}
        active={dragState?.side === "left"}
        activeClassName={styles.resizeHandleActive}
        onToggle={() => setLeftRailCollapsed((current) => !current)}
        onPointerDown={(event) => handleResizeStart("left", event)}
        onKeyDown={(event) => handleResizeKeyDown("left", event)}
      /> : null}

      <section className={centerPaneClassName}>
        <div className={styles.tabStrip}>
          <div className={styles.overlayPaneControls}>
            {!responsiveLayout.leftVisible ? (
              <VButton
                id="chat-conversation-index-toggle"
                type="button"
                className={styles.overlayPaneToggle}
                aria-expanded={conversationIndexOverlayOpen}
                aria-controls="chat-conversation-index-pane"
                onClick={() => setResponsiveOverlayPane((current) => current === "left" ? null : "left")}
              >
                {lang === "zh" ? "会话" : "Chats"}
              </VButton>
            ) : null}
            {!responsiveLayout.rightVisible ? (
              <VButton
                id="chat-status-toggle"
                type="button"
                className={styles.overlayPaneToggle}
                aria-expanded={statusRailOverlayOpen}
                aria-controls="chat-status-pane"
                onClick={() => setResponsiveOverlayPane((current) => current === "right" ? null : "right")}
              >
                {lang === "zh" ? "状态" : "Status"}
              </VButton>
            ) : null}
          </div>
          {chatReturnTarget ? (
            <Link className={styles.chatReturnLink} to={chatReturnTarget} title={chatReturnLabel}>
              <ArrowLeft size={14} aria-hidden="true" />
              <span>{chatReturnLabel}</span>
            </Link>
          ) : null}
          {groupPanelActive ? (
            <VButton
              type="button"
              className={`${styles.tab} ${styles.tabActive}`}
              onClick={() => undefined}
            >
              {projectBusActive ? (lang === "zh" ? "通知流" : "Notice stream") : (lang === "zh" ? "群聊" : "Group")}
            </VButton>
          ) : agentSessionTabs.length > 0 || cliAgentRunTabs.length > 0 ? (
            <>
            <AgentSessionTabStrip
              activeSessionId={activeSessionId}
              activeCliAgentRunId={activeCliAgentRunId}
              agentsById={agentsById}
              buildSessionReferencePayload={buildSessionReferencePayload}
              contextMenuSessionId={contextMenuSessionId}
              cliAgentRuns={cliAgentRunTabs}
              editingSessionId={editingSessionId}
              editingSessionTitle={editingSessionTitle}
              lang={lang}
              renamePending={renameSessionMutation.isPending}
              renameSessionId={renameSessionMutation.variables?.sessionId ?? ""}
              resolveModelLabel={resolveModelLabel}
              sessions={agentSessionTabs}
              statusLabel={statusLabel}
              t={t}
              workspaceActiveTab={workspace.activeTab}
              onCancelRename={cancelRenameSession}
              onContextMenu={openSessionContextMenu}
              onDragReference={startSessionReferenceDrag}
              onOpenCliAgentRun={(runId) => {
                if (activeSessionId) {
                  setActiveTab(activeSessionId, cliAgentRunTabId(runId));
                }
              }}
              onCloseCliAgentRun={(runId) => {
                const run = cliAgentRunTabs.find((item) => item.id === runId);
                if (run) {
                  void closeCliAgentRun(run);
                }
              }}
              onOpenDirectSession={handleOpenDirectSession}
              onRenameTitleChange={setEditingSessionTitle}
              onSetActiveTab={setActiveTab}
              onSubmitRename={submitRenameSession}
            />
            <VButton
              type="button"
              className={styles.tab}
              icon={<Plus size={14} />}
              onClick={handleCreateSession}
              isDisabled={createSessionMutation.isPending || !selectedChatAgentId}
              title={lang === "zh" ? "在当前 Agent 下新建会话" : "New session for current Agent"}
            >
              <span>{lang === "zh" ? "新建会话" : "New session"}</span>
            </VButton>
            </>
          ) : (
            <VButton
              type="button"
              className={workspace.activeTab === "agent" ? `${styles.tab} ${styles.tabActive}` : styles.tab}
              onClick={() => {
                activeSessionId && setActiveTab(activeSessionId, "agent");
              }}
            >
              {t("agentSession")}
            </VButton>
          )}
          <ChatFileWorkspaceTabs
            activeTab={workspace.activeTab}
            closePreviewTabLabel={t("closePreviewTab")}
            hidden={groupPanelActive}
            openTabs={workspace.openTabs}
            onCloseTab={(tabPath) => {
              activeSessionId && closePreviewTab(activeSessionId, tabPath);
            }}
            onOpenTab={(tabPath) => {
              activeSessionId && setActiveTab(activeSessionId, tabPath);
            }}
          />
        </div>

        <div className={styles.centerSurface}>
          {mountedCliAgentRuns.map((run) => (
            <Suspense
              key={run.id}
              fallback={(
                <section
                  className={
                    !groupPanelActive && activeCliAgentRunId === run.id
                      ? styles.cliAgentRunPanel
                      : `${styles.cliAgentRunPanel} ${styles.cliAgentRunPanelHidden}`
                  }
                  aria-hidden={!(!groupPanelActive && activeCliAgentRunId === run.id)}
                  aria-label={`${run.title} ${lang === "zh" ? "终端加载中" : "terminal loading"}`}
                  data-active={!groupPanelActive && activeCliAgentRunId === run.id ? "true" : "false"}
                  data-cli-agent-run-id={run.id}
                >
                  <div className={styles.cliAgentTerminalFrame}>
                    <div className={styles.cliAgentTerminalCommand} title={run.commandLine}>
                      <span className={styles.cliAgentTerminalStatus}>
                        {lang === "zh" ? "加载终端" : "Loading terminal"}
                      </span>
                      <code>{run.commandLine}</code>
                    </div>
                  </div>
                </section>
              )}
            >
              <CliAgentRunTerminalPanel
                run={run}
                sourceSessionId={activeSessionId || ""}
                active={!groupPanelActive && activeCliAgentRunId === run.id}
                lang={lang}
                onTerminalSessionChange={handleCliAgentTerminalSessionChange}
              />
            </Suspense>
          ))}
          {projectBusActive ? (
            <div className={styles.groupConversationFrame}>
              <header className={styles.groupConversationHeader}>
                <div>
                  <p>
                    {activeGroupRoom?.mode ?? "round_robin"}
                    {" · "}
                    {activeGroupRoom?.purpose ?? "discussion"}
                  </p>
                  <div className={styles.groupConversationTitleRow}>
                    <h2>{lang === "zh" ? "助手通知流" : "Agent notice stream"}</h2>
                    <VContextualHint
                      content={lang === "zh"
                        ? "助手通知流会显示用户引导、助手私信和广播投递结果；它不是团队群聊。"
                        : "The Agent notice stream shows guidance, private messages, broadcasts, and delivery results. It is not a team room."}
                      label={lang === "zh" ? "助手通知流说明" : "Agent notice stream details"}
                      width="wide"
                    />
                  </div>
                  <span>
                    {projectBusTimeline?.activeAgentCount ?? availableGroupParticipantCount} {lang === "zh" ? "位 active Agent" : "active agents"}
                    {" · "}
                    {lang === "zh" ? "全局广播与投递观察" : "broadcasts and delivery observation"}
                  </span>
                </div>
                <VButton
                  type="button"
                  className={styles.groupRefreshButton}
                  onClick={() => void projectAgentBusQuery.refetch()}
                  isDisabled={projectAgentBusQuery.isFetching}
                >
                  {lang === "zh" ? "刷新" : "Refresh"}
                </VButton>
              </header>
              {projectAgentBusQuery.isError ? (
                <div className={styles.inlineNotice}>
                  {describeError(projectAgentBusQuery.error, t("loadFailed"))}
                </div>
              ) : null}
              {groupRoomActionError ? (
                <div className={styles.inlineNotice}>{groupRoomActionError}</div>
              ) : null}
              <div className={styles.groupMessageTimeline} aria-live={sendProjectBusMessageMutation.isPending ? "polite" : undefined}>
                {projectBusEvents.length ? (
                  projectBusEvents.map((event) => {
                    const revoked = isProjectAgentBusEventRevoked(event);
                    const targetLabel = event.targetScope === "all"
                      ? (lang === "zh" ? "全体成员" : "All agents")
                      : event.targetAgentNames.length
                        ? event.targetAgentNames.join(", ")
                        : (lang === "zh" ? "仅观察" : "Observe only");
                    const deliveryLabel = event.deliveries.length
                      ? `${event.deliveries.length} ${lang === "zh" ? "次投递" : "deliveries"}`
                      : (lang === "zh" ? "未投递" : "no delivery");
                    const interruptionLabel = event.interruptions.length
                      ? `${event.interruptions.filter((item) => item.status === "interrupted").length}/${event.interruptions.length} ${lang === "zh" ? "已打断" : "interrupted"}`
                      : "";
                    return (
                      <article key={event.eventId} className={revoked ? `${styles.projectBusEvent} ${styles.projectBusEventRevoked}` : styles.projectBusEvent}>
                        <header className={styles.projectBusEventHeader}>
                          <div>
                            <strong>{event.createdBy === "user" ? runtime?.userName || (lang === "zh" ? "我" : "Me") : event.createdBy}</strong>
                            <span>{targetLabel}</span>
                          </div>
                          <div className={styles.projectBusEventActions}>
                            <time>{formatTime(event.createdAt)}</time>
                            {event.createdBy === "user" && !revoked ? (
                              <VButton
                                type="button"
                                onClick={() => handleRevokeProjectBusMessage(event.eventId)}
                                isDisabled={revokeProjectBusMessageMutation.isPending}
                              >
                                {lang === "zh" ? "撤回" : "Recall"}
                              </VButton>
                            ) : null}
                          </div>
                        </header>
                        <p className={styles.projectBusEventBody}>
                          {revoked
                            ? (lang === "zh" ? "这条消息已撤回，相关 Agent 已请求停止。" : "This message was recalled. Target agents were asked to stop.")
                            : renderMentionedText(event.content)}
                        </p>
                        <div className={styles.projectBusEventMeta}>
                          <span>{revoked ? (lang === "zh" ? "已撤回" : "revoked") : event.messageType}</span>
                          <span>{deliveryLabel}</span>
                          {interruptionLabel ? <span>{interruptionLabel}</span> : null}
                          {event.kernel?.taskId ? (
                            <Link className={styles.kernelTraceLink} to={kernelTaskCenterHref(event.kernel.taskId)}>
                              {lang === "zh" ? "Kernel 任务" : "Kernel Task"}
                            </Link>
                          ) : null}
                          {event.unresolvedMentions.length ? (
                            <span>{lang === "zh" ? "未识别" : "unresolved"} @{event.unresolvedMentions.join(", @")}</span>
                          ) : null}
                        </div>
                      </article>
                    );
                  })
                ) : (activeGroupRoom?.rounds ?? []).length ? (
                  (activeGroupRoom?.rounds ?? []).map((round, roundIndex) => {
                    const roundRunning = String(round.status ?? "").trim().toLowerCase() === "running";
                    const deliveredParticipantIds = new Set(
                      (round.messages ?? []).map((message) => String(message.participantId ?? "").trim()),
                    );
                    const nextSpeakerId = (round.speakerOrder ?? []).find(
                      (participantId) => !deliveredParticipantIds.has(String(participantId ?? "").trim()),
                    );
                    const nextParticipant = nextSpeakerId ? activeGroupParticipantById.get(nextSpeakerId) : undefined;
                    return (
                    <section key={round.roundId} className={styles.groupRoundBlock}>
                      <div className={styles.groupRoundDivider}>
                        <span>
                          {lang === "zh" ? `第 ${roundIndex + 1} 轮` : `Round ${roundIndex + 1}`}
                          {" · "}
                          {round.mode}
                          {" · "}
                          {round.purpose ?? activeGroupRoom?.purpose ?? "discussion"}
                          {" · "}
                          {statusLabel(round.status)}
                        </span>
                        <time>{formatTime(round.updatedAt || round.startedAt)}</time>
                      </div>
                      <article className={styles.groupTopicMessage}>
                        <div className={styles.groupTopicBubble}>
                          <span>{runtime?.userName || (lang === "zh" ? "我" : "Me")}</span>
                          <p>{renderMentionedText(round.topic)}</p>
                        </div>
                      </article>
                      <div className={styles.groupMessageList}>
                        {(round.messages ?? []).map((message: ChatRoomMessage) => {
                          const speakerParticipant = activeGroupParticipantById.get(String(message.participantId ?? "").trim());
                          const speakerIdentity = groupParticipantIdentity(speakerParticipant, {
                            agentId: message.agentId,
                            agentCode: message.speakerCode,
                            title: message.speakerTitle,
                            participantId: message.participantId,
                          });
                          return (
                          <article
                            key={message.messageId}
                            className={
                              message.status === "failed"
                                ? `${styles.groupBubbleRow} ${styles.groupBubbleRowFailed}`
                                : styles.groupBubbleRow
                            }
                          >
                            {renderAgentAvatar(
                              styles.groupBubbleAvatar,
                              speakerIdentity.avatarImageUrl,
                              avatarInitials(message.speakerCode, speakerIdentity.name, "AI"),
                            )}
                            <div className={styles.groupBubble}>
                              <header className={styles.groupBubbleHeader}>
                                <strong title={speakerIdentity.fullIdentityLabel}>{speakerIdentity.identityLabel}</strong>
                                {message.status !== "completed" ? <span>{statusLabel(message.status)}</span> : null}
                              </header>
                              {renderGroupMessageBody(message, speakerIdentity.name)}
                              <time className={styles.groupBubbleMeta}>{formatTime(message.timestamp || round.updatedAt)}</time>
                            </div>
                          </article>
                          );
                        })}
                        {roundRunning && nextParticipant ? (
                          <article className={`${styles.groupBubbleRow} ${styles.groupBubbleRowPending}`}>
                            {(() => {
                              const nextIdentity = groupParticipantIdentity(nextParticipant);
                              return (
                              <>
                            {renderAgentAvatar(
                              styles.groupBubbleAvatar,
                              nextIdentity.avatarImageUrl,
                              avatarInitials(nextParticipant.agentCode, nextIdentity.name, "AI"),
                            )}
                            <div className={styles.groupBubble}>
                              <header className={styles.groupBubbleHeader}>
                                <strong title={nextIdentity.fullIdentityLabel}>{nextIdentity.identityLabel}</strong>
                                <span>{lang === "zh" ? "正在输入" : "typing"}</span>
                              </header>
                              <div className={styles.groupTypingDots} aria-label={lang === "zh" ? "正在输入" : "Typing"}>
                                <span />
                                <span />
                                <span />
                              </div>
                            </div>
                              </>
                              );
                            })()}
                          </article>
                        ) : null}
                      </div>
                      {round.summary && !roundRunning ? <p className={styles.groupRoundSummary}>{round.summary}</p> : null}
                    </section>
                    );
                  })
                ) : (
                  <div className={styles.groupEmptyState}>
                    <BellRing size={28} />
                    <p>{lang === "zh" ? "暂无通知。" : "No notices yet."}</p>
                  </div>
                )}
              </div>
              <div className={styles.groupComposerBar}>
                <VNativeInput
                  value={projectBusDraft}
                  onChange={(event) => setProjectBusDraft(event.target.value)}
                  disabled={sendProjectBusMessageMutation.isPending}
                  placeholder={lang === "zh" ? "输入广播；不带 @ 默认投递全体，可用 @AgentCode 指定" : "Write a broadcast; no @ sends to all, @AgentCode targets one"}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      handleSendProjectBusMessage();
                    }
                  }}
                />
                <label className={styles.projectBusInterruptToggle}>
                  <VNativeInput
                    type="checkbox"
                    checked={projectBusInterruptTargets}
                    onChange={(event) => setProjectBusInterruptTargets(event.target.checked)}
                  />
                  <span>{lang === "zh" ? "打断目标助手" : "Interrupt targets"}</span>
                </label>
                <VButton
                  type="button"
                  onClick={handleSendProjectBusMessage}
                  isDisabled={
                    !projectBusDraft.trim()
                    || sendProjectBusMessageMutation.isPending
                  }
                >
                  <UsersRound size={15} />
                  <span>
                    {sendProjectBusMessageMutation.isPending
                      ? (lang === "zh" ? "发送中" : "Sending")
                      : (lang === "zh" ? "发送广播" : "Send")}
                  </span>
                </VButton>
              </div>
            </div>
          ) : standardGroupRoomActive ? (
            <div className={styles.groupConversationFrame}>
              <header className={styles.groupConversationHeader}>
                <div>
                  <p>
                    {activeGroupRoom?.mode ?? "round_robin"}
                    {" · "}
                    {activeGroupRoom?.purpose ?? "discussion"}
                  </p>
                  <h2>{activeGroupRoom?.title ?? (lang === "zh" ? "群聊加载中" : "Loading group")}</h2>
                  <span>
                    {availableGroupParticipantCount} {lang === "zh" ? "位可用助手" : "available agents"}
                    {" · "}
                    {statusLabel(activeGroupRoom?.status ?? "ready")}
                  </span>
                </div>
                <VButton
                  type="button"
                  className={styles.groupRefreshButton}
                  onClick={() => activeGroupRoomId && void activeGroupRoomQuery.refetch()}
                  isDisabled={activeGroupRoomQuery.isFetching}
                >
                  {lang === "zh" ? "刷新" : "Refresh"}
                </VButton>
              </header>
              {activeGroupRoomQuery.isError ? (
                <div className={styles.inlineNotice}>
                  {describeError(activeGroupRoomQuery.error, t("loadFailed"))}
                </div>
              ) : null}
              <div className={styles.groupMessageTimeline} aria-live={groupRoundActive ? "polite" : undefined}>
                {(activeGroupRoom?.rounds ?? []).length ? (
                  (activeGroupRoom?.rounds ?? []).map((round, roundIndex) => {
                    const roundRunning = String(round.status ?? "").trim().toLowerCase() === "running";
                    const deliveredParticipantIds = new Set(
                      (round.messages ?? []).map((message) => String(message.participantId ?? "").trim()),
                    );
                    const nextSpeakerId = (round.speakerOrder ?? []).find(
                      (participantId) => !deliveredParticipantIds.has(String(participantId ?? "").trim()),
                    );
                    const nextParticipant = nextSpeakerId ? activeGroupParticipantById.get(nextSpeakerId) : undefined;
                    return (
                    <section key={round.roundId} className={styles.groupRoundBlock}>
                      <div className={styles.groupRoundDivider}>
                        <span>
                          {lang === "zh" ? `第 ${roundIndex + 1} 轮` : `Round ${roundIndex + 1}`}
                          {" · "}
                          {round.mode}
                          {" · "}
                          {round.purpose ?? activeGroupRoom?.purpose ?? "discussion"}
                          {" · "}
                          {statusLabel(round.status)}
                        </span>
                        <time>{formatTime(round.updatedAt || round.startedAt)}</time>
                      </div>
                      <article className={styles.groupTopicMessage}>
                        <div className={styles.groupTopicBubble}>
                          <span>{runtime?.userName || (lang === "zh" ? "我" : "Me")}</span>
                          <p>{renderMentionedText(round.topic)}</p>
                        </div>
                      </article>
                      <div className={styles.groupMessageList}>
                        {(round.messages ?? []).map((message: ChatRoomMessage) => {
                          const speakerParticipant = activeGroupParticipantById.get(String(message.participantId ?? "").trim());
                          const speakerIdentity = groupParticipantIdentity(speakerParticipant, {
                            agentId: message.agentId,
                            agentCode: message.speakerCode,
                            title: message.speakerTitle,
                            participantId: message.participantId,
                          });
                          return (
                          <article
                            key={message.messageId}
                            className={
                              message.status === "failed"
                                ? `${styles.groupBubbleRow} ${styles.groupBubbleRowFailed}`
                                : styles.groupBubbleRow
                            }
                          >
                            {renderAgentAvatar(
                              styles.groupBubbleAvatar,
                              speakerIdentity.avatarImageUrl,
                              avatarInitials(message.speakerCode, speakerIdentity.name, "AI"),
                            )}
                            <div className={styles.groupBubble}>
                              <header className={styles.groupBubbleHeader}>
                                <strong title={speakerIdentity.fullIdentityLabel}>{speakerIdentity.identityLabel}</strong>
                                {message.status !== "completed" ? <span>{statusLabel(message.status)}</span> : null}
                              </header>
                              {renderGroupMessageBody(message, speakerIdentity.name)}
                              <time className={styles.groupBubbleMeta}>{formatTime(message.timestamp || round.updatedAt)}</time>
                            </div>
                          </article>
                          );
                        })}
                        {roundRunning && nextParticipant ? (
                          <article className={`${styles.groupBubbleRow} ${styles.groupBubbleRowPending}`}>
                            {(() => {
                              const nextIdentity = groupParticipantIdentity(nextParticipant);
                              return (
                              <>
                            {renderAgentAvatar(
                              styles.groupBubbleAvatar,
                              nextIdentity.avatarImageUrl,
                              avatarInitials(nextParticipant.agentCode, nextIdentity.name, "AI"),
                            )}
                            <div className={styles.groupBubble}>
                              <header className={styles.groupBubbleHeader}>
                                <strong title={nextIdentity.fullIdentityLabel}>{nextIdentity.identityLabel}</strong>
                                <span>{lang === "zh" ? "正在输入" : "typing"}</span>
                              </header>
                              <div className={styles.groupTypingDots} aria-label={lang === "zh" ? "正在输入" : "Typing"}>
                                <span />
                                <span />
                                <span />
                              </div>
                            </div>
                              </>
                              );
                            })()}
                          </article>
                        ) : null}
                      </div>
                      {round.summary && !roundRunning ? <p className={styles.groupRoundSummary}>{round.summary}</p> : null}
                    </section>
                    );
                  })
                ) : (
                  <div className={styles.groupEmptyState}>
                    <UsersRound size={28} />
                    <p>{lang === "zh" ? "群聊已创建，输入议题后开始第一轮讨论。" : "The group is ready. Enter a topic to start the first round."}</p>
                  </div>
                )}
              </div>
              <div className={styles.groupComposerBar}>
                <VNativeInput
                  value={groupTopicDraft}
                  onChange={(event) => setGroupTopicDraft(event.target.value)}
                  disabled={startGroupRoundMutation.isPending}
                  placeholder={lang === "zh" ? "输入下一轮群聊议题" : "Topic for the next group round"}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      handleStartGroupRound();
                    }
                  }}
                />
                <VButton
                  type="button"
                  onClick={handleStartGroupRound}
                  isDisabled={
                    !groupTopicDraft.trim()
                    || startGroupRoundMutation.isPending
                    || groupRoundActive
                    || !activeGroupRoom
                  }
                >
                  <UsersRound size={15} />
                  <span>
                    {startGroupRoundMutation.isPending || groupRoundActive
                      ? (groupRoundStopping ? (lang === "zh" ? "停止中" : "Stopping") : (lang === "zh" ? "讨论中" : "Running"))
                      : (lang === "zh" ? "启动一轮" : "Run round")}
                  </span>
                </VButton>
                {groupRoundActive ? (
                  <VButton
                    type="button"
                    className={styles.groupStopButton}
                    onClick={handleStopGroupRound}
                    isDisabled={groupStopDisabled}
                    title={lang === "zh" ? "停止当前群聊轮次" : "Stop current group round"}
                  >
                    <Square size={15} />
                    <span>
                      {stopGroupRoundMutation.isPending
                        ? (lang === "zh" ? "停止中" : "Stopping")
                        : (lang === "zh" ? "停止" : "Stop")}
                    </span>
                  </VButton>
                ) : null}
              </div>
            </div>
          ) : (
            <ChatSessionWorkspacePanel
              activeCliAgentRunAvailable={Boolean(activeCliAgentRun)}
              activeCliAgentRunId={activeCliAgentRunId}
              activeSessionId={activeSessionId}
              blockingErrorMessage={sessionDetailErrorMessage}
              cliAgentRunEmptyLabel={lang === "zh" ? "这个 CLI 工具页还没有可显示的运行记录。" : "This CLI tool page has no run to display."}
              conversation={detail ? {
                sessionId: activeSessionId ?? detail.id,
                title: detail.title,
                phase: detail.currentPhase,
                messages: detail.messages,
                activeTurnMessage,
                hasEarlierMessages: Boolean(detail.messageWindow?.hasEarlier),
                earlierMessagesLoading: loadEarlierSessionMessagesMutation.isPending,
                onStreamingFramePaint: handleConversationStreamingFramePaint,
                assistantDisplayName: activeAgentDisplayName,
                assistantAvatarImageUrl: activeAgentAvatarImageUrl,
                assistantAvatarFallback: activeAgentAvatarFallback,
                resolveTurnAvatar: resolveConversationTurnAvatar,
                userDisplayName: resolveChatUserDisplayName(runtime?.userName),
                userAvatarPreset: runtime?.userProfile?.avatarPreset,
                userAvatarImageUrl: runtime?.userProfile?.avatarImageUrl,
                taskSummary: currentTaskSummary,
                defaultFileContext: detail.defaultFileContext,
                showHeader: false,
                showSessionOverview: false,
                showMentalSnapshots: mentalModelEnabledForNextTurn,
                composer: conversationComposer,
                llmControl: sessionLlmControl,
                slashCommandSuggestions,
                cancelComposerModeLabel: t("cancelEditMessage"),
                turnError: detail.lastTurnError,
                stopLabel: t("stop"),
                stopPendingLabel: t("stopPending"),
                safeGuidanceLabel: t("safeGuidance"),
                safeGuidancePendingLabel: t("safeGuidancePending"),
                interruptGuidanceLabel: t("interruptGuidance"),
                interruptGuidancePendingLabel: t("interruptGuidancePending"),
                editUserMessageLabel: t("editAndResendMessage"),
                onComposerChange: handleComposerChange,
                onAddComposerAttachments: handleAddComposerAttachments,
                onRemoveComposerAttachment: handleRemoveComposerAttachment,
                onAddComposerReference: handleAddComposerReference,
                onRemoveComposerReference: handleRemoveComposerReference,
                onEditUserMessage: handleEditUserMessage,
                onCancelComposerMode: resolvedEditTarget ? handleCancelEditMessage : undefined,
                onLoadEarlierMessages: handleLoadEarlierSessionMessages,
                onSubmit: handleSubmitTurn,
                onStop: handleStopTurn,
                onSafeGuidance: () => handleSubmitGuidance("safe"),
                onInterruptGuidance: () => handleSubmitGuidance("interrupt"),
              } : null}
              conversationFocused={statusRailCollapsed}
              filePreview={{
                changed: fileContentQuery.data ? changedFiles.has(fileContentQuery.data.path) : false,
                errorMessage: fileContentQuery.isError ? describeError(fileContentQuery.error, t("loadFailed")) : "",
                file: fileContentQuery.data,
                loadingLabel: t("loadingFilePreview"),
                sourceLabel: detail?.title ?? t("currentSession"),
              }}
              hasBlockingError={sessionDetailErrorState.blockingError}
              hasTransientError={sessionDetailErrorState.transientError}
              invalidChildSessionLinkMessage={invalidChildSessionLinkMessage}
              lang={lang}
              loadingSessionLabel={t("loadingSession")}
              noSessionsLabel={t("noSessionsYet")}
              notices={activeRuntimeNotices}
              sessionsPending={sessionsQuery.isPending}
              toolApproval={pendingToolApproval ? {
                pending: pendingToolApprovalPending,
                rawTitle: pendingToolApprovalRawTitle,
                riskLabel: pendingToolApprovalRisk,
                scopeLabel: pendingToolApprovalScope,
                toolLabels: pendingToolApprovalLabels,
              } : null}
              transientErrorMessage={sessionDetailErrorMessage}
              workspaceActiveTab={workspace.activeTab}
              onApproveToolApproval={() => {
                if (!pendingToolApproval) {
                  return;
                }
                resolveToolApprovalMutation.mutate({ request: pendingToolApproval, decision: "approve" });
              }}
              onRejectToolApproval={() => {
                if (!pendingToolApproval) {
                  return;
                }
                resolveToolApprovalMutation.mutate({ request: pendingToolApproval, decision: "reject" });
              }}
            />
          )}
        </div>
      </section>

      {responsiveLayout.rightVisible ? <PaneCollapseHandle
        side="right"
        collapsed={statusRailCollapsed}
        separatorLabel={t("resizeRightPanel")}
        collapseLabel={lang === "zh" ? "收起状态栏" : "Collapse status rail"}
        expandLabel={lang === "zh" ? "展开状态栏" : "Expand status rail"}
        className={`${styles.resizeHandle} ${styles.resizeHandleRight}`}
        active={dragState?.side === "right"}
        activeClassName={styles.resizeHandleActive}
        onToggle={() => setRightPaneCollapsed((current) => !current)}
        onPointerDown={(event) => handleResizeStart("right", event)}
        onKeyDown={(event) => handleResizeKeyDown("right", event)}
      /> : null}

      <ChatConversationIndexRail
        conversationIndexPaneClassName={conversationIndexPaneClassName}
        conversationIndexCollapsed={conversationIndexCollapsed}
        conversationIndexOverlayOpen={conversationIndexOverlayOpen}
        lang={lang}
        locale={locale}
        t={t}
        currentSessionLabel={t("currentSession")}
        standardGroupRoomActive={standardGroupRoomActive}
        rightIndexPanel={rightIndexPanel}
        setRightIndexPanel={setRightIndexPanel}
        sessionFilter={sessionFilter}
        setSessionFilter={setSessionFilter}
        availableGroupParticipantCount={availableGroupParticipantCount}
        availableGroupParticipants={availableGroupParticipants}
        activeGroupRoom={activeGroupRoom}
        expandedGroupAgentSessionIds={expandedGroupAgentSessionIds}
        setExpandedGroupAgentSessionIds={setExpandedGroupAgentSessionIds}
        expandedGroupAgentDetailsBySessionId={expandedGroupAgentDetailsBySessionId}
        sessionsById={sessionsById}
        agentsById={agentsById}
        mentalModelEnabledForNextTurn={mentalModelEnabledForNextTurn}
        numberFormatter={numberFormatter}
        conversationIndexPanel={conversationIndexPanel}
        groupComposerOpen={groupComposerOpen}
        createGroupRoomPending={createGroupRoomMutation.isPending}
        createAgentButtonRef={agentCreateTriggerRef}
        onCreateAgent={handleCreateAgent}
        onToggleGroupComposer={handleToggleGroupComposer}
        groupTitleDraft={groupTitleDraft}
        setGroupTitleDraft={setGroupTitleDraft}
        groupModeDraft={groupModeDraft}
        setGroupModeDraft={setGroupModeDraft}
        groupPurposeDraft={groupPurposeDraft}
        setGroupPurposeDraft={setGroupPurposeDraft}
        readyChatRoomModes={readyChatRoomModes}
        availableChatRoomPurposes={availableChatRoomPurposes}
        chatRoomModesPending={chatRoomModesQuery.isPending}
        chatRoomPurposesPending={chatRoomPurposesQuery.isPending}
        groupCandidateAgents={groupCandidateAgents}
        agentsPending={agentsQuery.isPending}
        groupSelectedAgentIds={groupSelectedAgentIds}
        onToggleGroupAgent={handleToggleGroupAgent}
        onCreateGroupRoom={handleCreateGroupRoom}
        projectBusActive={projectBusActive}
        onOpenProjectAgentBus={handleOpenProjectAgentBus}
        onOpenDirectSession={handleOpenDirectSession}
        resolveModelLabel={resolveModelLabel}
        statusLabel={statusLabel}
        describeError={describeError}
        renderAgentAvatar={renderAgentAvatar}
        avatarInitials={avatarInitials}
        agentRoleClass={agentRoleClass}
        avatarImageUrlFrom={avatarImageUrlFrom}
        groupParticipantIdentity={groupParticipantIdentity}
        latestMentalSnapshot={latestMentalSnapshot}
        chatRoomModeLabel={chatRoomModeLabel}
        chatRoomPurposeLabel={chatRoomPurposeLabel}
      />
      {cacheDetailOpen && cacheDetailAvailable ? (
        <CacheDetailDialog
          averageCacheObservedTurnCount={averageCacheObservedTurnCount}
          cacheCompositionAverageLabel={cacheCompositionAverageLabel}
          cacheCompositionAverageValue={cacheCompositionAverageValue}
          cacheCompositionPercent={cacheCompositionPercent}
          cacheCompositionTitle={cacheCompositionTitle}
          cacheCompositionUpperBoundLabel={cacheCompositionUpperBoundLabel}
          cacheComputedOverestimatedInputTokens={cacheComputedOverestimatedInputTokens}
          cacheDetailDialogTitle={cacheDetailDialogTitle}
          cachePromptCompositionTotalTokens={cachePromptCompositionTotalTokens}
          cachePromptDonutSegments={cachePromptDonutSegments}
          cacheProviderExtraCachedInputTokens={cacheProviderExtraCachedInputTokens}
          cacheCalibrationReason={cacheCalibrationReason}
          cacheCalibrationSummaryText={cacheCalibrationSummaryText}
          closeLabel={lang === "zh" ? "关闭缓存详情" : "Close cache details"}
          lang={lang}
          missingSegmentLabel={cacheCompositionSegmentLabel("missing", "missing", t)}
          numberFormatter={numberFormatter}
          onClose={closeCacheDetail}
          previousCacheHitLabel={t("previousCacheHit")}
          providerCachedInputTokens={providerCachedInputTokens}
          providerCacheInputTokens={providerCacheInputTokens}
          trueCacheDonutSegments={trueCacheDonutSegments}
          upperBoundCachedInputTokens={upperBoundCachedInputTokens}
          upperBoundCacheCompositionPercent={upperBoundCacheCompositionPercent}
          upperBoundCacheInputTokens={upperBoundCacheInputTokens}
        />
      ) : null}
      <AgentCreateWizardDialog
        open={agentCreateWizardOpen}
        triggerRef={agentCreateTriggerRef}
        triggerId="chat-agent-create-trigger"
        onClose={() => setAgentCreateWizardOpen(false)}
        onCreated={(agent) => {
          setSelectedAgentId(agent.agentId);
          setRightIndexPanel("conversations");
        }}
        onStartConversation={async (agent) => {
          try {
            await createSessionMutation.mutateAsync({ agentId: agent.agentId });
            return true;
          } catch {
            return false;
          }
        }}
        onOpenAdvancedConfig={(agent) => {
          setAgentCreateWizardOpen(false);
          navigate(`/agents?agent=${encodeURIComponent(agent.agentId)}&pane=config&returnTo=${encodeURIComponent("/chat")}`);
        }}
      />
    </div>
  );
}
