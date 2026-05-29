import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Apple,
  BookPlus,
  Bot,
  Check,
  ChevronRight,
  HeartHandshake,
  MessageCircleHeart,
  Pencil,
  Plus,
  Search,
  Sparkles,
  Square,
  Trash2,
  UsersRound,
  X,
} from "lucide-react";
import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
} from "react";
import { useLocation } from "react-router-dom";

import { fetchJson } from "../api/client";
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
  ChatRoomMode,
  ChatRoomPurpose,
  ChatRoomStreamEvent,
  FileContent,
  MentalStateSnapshot,
  PetActionResponse,
  PetSummary,
  RuntimeSummary,
  SessionChatReviewCandidateResponse,
  ConversationSummary,
  SessionDetail,
  SessionSummary,
  SessionStreamEvent,
  ConversationMessage,
  ConversationAttachment,
} from "../api/types";
import { ConversationView } from "../components/conversation/ConversationView";
import { postBrowserTelemetry } from "../app/browserTelemetry";
import { resolvePollingInterval, usePageVisibility } from "../app/pollingPolicy";
import type { TranslationKey } from "../i18n/dictionary";
import { PaneCollapseHandle } from "../components/layout/PaneCollapseHandle";
import { petAvatarPresetLabel } from "../i18n/petLabels";
import { useAppI18n } from "../i18n/useAppI18n";
import { useChatWorkbenchStore } from "../store/chatWorkbenchStore";
import { useShellStore } from "../store/shellStore";
import {
  clampPercent,
  contextUsagePercent,
  formatContextUsage,
  formatRelativeTime,
} from "./chatShellFormat";
import {
  deriveSessionDetailQueryErrorState,
  deriveSessionListQueryErrorState,
  markSessionDetailRunning,
  markSessionSummaryRunning,
  mergeSessionDetailIntoSummaries,
  removeDeletedSessionFromSummaries,
  shouldAcceptSessionStreamEvent,
} from "./chatSessionState";
import {
  latestUserMessageId as deriveLatestUserMessageId,
  resolveComposerDraftValue,
  resolveLatestEditTarget,
} from "./chatComposerState";
import { buildVisiblePanelRows, getPetAvatarPresetKey, getPetAvatarSymbol } from "./chatCompactPanel";
import {
  clearPendingSelfEvolutionHandoff,
  loadPendingSelfEvolutionHandoff,
} from "./selfEvolutionHandoff";
import {
  agentDisplayInfo,
  participantAgentDisplayInfo,
  sessionAgentDisplayInfo,
} from "./agentDisplay";
import {
  buildChatMentionTargets,
  tokenizeChatMentions,
  type ChatMentionTarget,
} from "./chatMentionTokens";
import styles from "./ChatCodingRoute.module.css";

function encodeUtf8Base64(value: string): string {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary);
}

function clearSessionImageAttachments(
  current: Record<string, ComposerImageAttachment[]>,
  sessionId: string,
) {
  const attachments = current[sessionId] ?? [];
  attachments.forEach((attachment) => URL.revokeObjectURL(attachment.previewUrl));
  const { [sessionId]: _removed, ...remaining } = current;
  return remaining;
}

function chatRoomModeLabel(mode: ChatRoomMode, lang: "zh" | "en") {
  if (mode.id === "round_robin") {
    return lang === "zh" ? "轮询讨论" : "Round robin";
  }
  if (mode.id === "opportunistic") {
    return lang === "zh" ? "抢占式讨论" : "Opportunistic";
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
  return purpose.label || purpose.id;
}

function removeSessionImageAttachment(
  current: Record<string, ComposerImageAttachment[]>,
  sessionId: string,
  attachmentId: string,
) {
  const attachments = current[sessionId] ?? [];
  const removed = attachments.find((attachment) => attachment.id === attachmentId);
  if (removed) {
    URL.revokeObjectURL(removed.previewUrl);
  }
  return {
    ...current,
    [sessionId]: attachments.filter((attachment) => attachment.id !== attachmentId),
  };
}

async function uploadSessionImageAttachment(sessionId: string, attachment: ComposerImageAttachment) {
  return fetchJson<ConversationAttachment>(`/api/sessions/${sessionId}/attachments`, {
    method: "POST",
    headers: {
      "Content-Type": attachment.contentType || "application/octet-stream",
      "X-Vibelution-Filename": encodeURIComponent(attachment.filename),
    },
    body: attachment.file,
  });
}

const FilePreview = lazy(async () => {
  const module = await import("../components/preview/FilePreview");
  return { default: module.FilePreview };
});

const RESIZE_HANDLE_WIDTH = 10;
const MIN_LEFT_PANEL_WIDTH = 220;
const MAX_LEFT_PANEL_WIDTH = 520;
const MIN_RIGHT_PANEL_WIDTH = 280;
const MAX_RIGHT_PANEL_WIDTH = 560;
const TARGET_CENTER_PANE_WIDTH = 420;
const KEYBOARD_RESIZE_STEP = 24;
const MENTAL_MODEL_TOGGLE_STORAGE_KEY = "vibelution.chat.mentalModelEnabled";
const MAX_COMPOSER_IMAGE_ATTACHMENTS = 4;
const MAX_COMPOSER_IMAGE_BYTES = 8 * 1024 * 1024;
const CHAT_CENTER_FIRST_MEDIA_QUERY = "(max-width: 980px)";

type ResizableSide = "left" | "right";
type PetInteractionAction = "feed" | "talk" | "care";
type FeaturePresetKey = "planningMode" | "goalMode" | "toolBoost";
type RightIndexPanel = "conversations" | "members";
type ConversationGroupKey =
  | "user"
  | "group"
  | "research"
  | "selfEvolution"
  | "supervisedEvolution"
  | "other";
type ComposerImageAttachment = {
  id: string;
  file: File;
  filename: string;
  previewUrl: string;
  sizeBytes: number;
  contentType: string;
};

type DragState = {
  side: ResizableSide;
  startX: number;
  startLeftWidth: number;
  startRightWidth: number;
};

const CHAT_FEATURE_PRESETS: Array<{
  key: FeaturePresetKey;
  labelKey: TranslationKey;
  hintKey: TranslationKey;
}> = [
  {
    key: "planningMode",
    labelKey: "chatFeaturePlanningMode",
    hintKey: "chatFeaturePlanningModeHint",
  },
  {
    key: "goalMode",
    labelKey: "chatFeatureGoalMode",
    hintKey: "chatFeatureGoalModeHint",
  },
  {
    key: "toolBoost",
    labelKey: "chatFeatureToolBoost",
    hintKey: "chatFeatureToolBoostHint",
  },
];

const DEFAULT_CHAT_FEATURE_PRESETS: Record<FeaturePresetKey, boolean> = {
  planningMode: false,
  goalMode: false,
  toolBoost: false,
};

const DEFAULT_COLLAPSED_CONVERSATION_GROUPS: Record<ConversationGroupKey, boolean> = {
  user: false,
  group: false,
  research: true,
  selfEvolution: true,
  supervisedEvolution: true,
  other: true,
};

const CONVERSATION_GROUP_ORDER: ConversationGroupKey[] = [
  "user",
  "group",
  "research",
  "selfEvolution",
  "supervisedEvolution",
  "other",
];

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function getDesiredCenterWidth(layoutWidth: number) {
  const usableWidth = Math.max(0, layoutWidth - RESIZE_HANDLE_WIDTH * 2);
  return Math.min(
    TARGET_CENTER_PANE_WIDTH,
    Math.max(0, usableWidth - MIN_LEFT_PANEL_WIDTH - MIN_RIGHT_PANEL_WIDTH),
  );
}

function normalizePanelWidths(layoutWidth: number, leftWidth: number, rightWidth: number) {
  const usableWidth = Math.max(0, layoutWidth - RESIZE_HANDLE_WIDTH * 2);
  const availableForPanels = Math.max(
    MIN_LEFT_PANEL_WIDTH + MIN_RIGHT_PANEL_WIDTH,
    usableWidth - getDesiredCenterWidth(layoutWidth),
  );

  let nextLeft = clamp(leftWidth, MIN_LEFT_PANEL_WIDTH, MAX_LEFT_PANEL_WIDTH);
  let nextRight = clamp(rightWidth, MIN_RIGHT_PANEL_WIDTH, MAX_RIGHT_PANEL_WIDTH);
  let overflow = nextLeft + nextRight - availableForPanels;

  if (overflow > 0) {
    const rightSlack = nextRight - MIN_RIGHT_PANEL_WIDTH;
    const leftSlack = nextLeft - MIN_LEFT_PANEL_WIDTH;

    if (rightSlack >= leftSlack) {
      const reduceRight = Math.min(overflow, rightSlack);
      nextRight -= reduceRight;
      overflow -= reduceRight;

      const reduceLeft = Math.min(overflow, nextLeft - MIN_LEFT_PANEL_WIDTH);
      nextLeft -= reduceLeft;
    } else {
      const reduceLeft = Math.min(overflow, leftSlack);
      nextLeft -= reduceLeft;
      overflow -= reduceLeft;

      const reduceRight = Math.min(overflow, nextRight - MIN_RIGHT_PANEL_WIDTH);
      nextRight -= reduceRight;
    }
  }

  return {
    leftPanelWidth: Math.round(nextLeft),
    rightPanelWidth: Math.round(nextRight),
  };
}

function getResizeBounds(side: ResizableSide, layoutWidth: number, siblingWidth: number) {
  const usableWidth = Math.max(0, layoutWidth - RESIZE_HANDLE_WIDTH * 2);
  const maxWidth = usableWidth - getDesiredCenterWidth(layoutWidth) - siblingWidth;

  if (side === "left") {
    return {
      min: MIN_LEFT_PANEL_WIDTH,
      max: Math.max(MIN_LEFT_PANEL_WIDTH, Math.min(MAX_LEFT_PANEL_WIDTH, maxWidth)),
    };
  }

  return {
    min: MIN_RIGHT_PANEL_WIDTH,
    max: Math.max(MIN_RIGHT_PANEL_WIDTH, Math.min(MAX_RIGHT_PANEL_WIDTH, maxWidth)),
  };
}

function describeError(error: unknown, fallback: string) {
  if (error instanceof Error && error.message) {
    return `${fallback}: ${error.message}`;
  }
  return fallback;
}

function isRunningPhase(value: string | null | undefined) {
  const phase = String(value ?? "").trim().toLowerCase();
  return ["queued", "running", "thinking", "tooling", "answering", "planning", "reading", "editing", "verifying"].includes(phase);
}

function isStoppingPhase(value: string | null | undefined) {
  const phase = String(value ?? "").trim().toLowerCase();
  return phase === "stopping";
}

function isBusyPhase(value: string | null | undefined) {
  const phase = String(value ?? "").trim().toLowerCase();
  return isRunningPhase(phase) || phase === "stopping";
}

function readStoredMentalModelToggle(): boolean | null {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = window.localStorage.getItem(MENTAL_MODEL_TOGGLE_STORAGE_KEY);
  if (raw === "true") {
    return true;
  }
  if (raw === "false") {
    return false;
  }
  return null;
}

function writeStoredMentalModelToggle(enabled: boolean) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(MENTAL_MODEL_TOGGLE_STORAGE_KEY, enabled ? "true" : "false");
}

function formatAgentIdentity(agentCode?: string, name?: string, fallback = "Agent") {
  const title = String(name ?? "").trim();
  return title || String(fallback || agentCode || "Agent").trim() || "Agent";
}

function agentRoleClass(tone: string) {
  return `agentRoleTag_${tone}`;
}

function avatarInitials(agentCode?: string, name?: string, fallback = "AI") {
  const title = String(name ?? "").trim();
  const ascii = title.match(/[A-Za-z0-9]/g)?.slice(0, 2).join("") ?? "";
  if (ascii) {
    return ascii.toUpperCase();
  }
  return title.slice(0, 2) || fallback;
}

function sessionToConversationSummary(session: SessionSummary): ConversationSummary {
  return {
    conversationId: session.id,
    type: "direct_agent",
    title: String(session.title || session.agentDisplayName || session.id).trim(),
    agentId: session.agentId,
    agentCode: session.agentCode,
    agentDisplayName: session.agentDisplayName,
    directSessionId: session.id,
    roomId: "",
    status: session.status,
    summary: session.taskSummary,
    updatedAt: session.updatedAt || session.lastActive,
    workspacePath: session.agentWorkspacePath || session.workspacePath || "",
    agentProfileId: session.agentProfileId,
    agentTemplateLabel: session.agentTemplateLabel,
    agentPrimaryMode: session.agentPrimaryMode,
    agentRoleKey: session.agentRoleKey,
    agentPromptTemplateId: session.agentPromptTemplateId,
  };
}

function isVisibleDirectSession(session: SessionSummary | undefined | null) {
  if (!session) {
    return false;
  }
  if (!String(session.agentId ?? "").trim()) {
    return true;
  }
  return !session.agentMissing;
}

function isVisibleConversation(
  conversation: ConversationSummary,
  sessionsById?: Map<string, SessionSummary>,
) {
  if (conversation.type !== "direct_agent") {
    return true;
  }
  const sessionId = conversation.directSessionId || conversation.conversationId;
  const session = sessionId && sessionsById ? sessionsById.get(sessionId) : undefined;
  if (session) {
    return isVisibleDirectSession(session);
  }
  if (!String(conversation.agentId ?? "").trim()) {
    return true;
  }
  return !conversation.agentMissing;
}

function removeDeletedSessionFromConversations(
  conversations: ConversationSummary[] | undefined,
  deletedSessionId: string,
  nextDetail: SessionDetail,
): ConversationSummary[] | undefined {
  if (!conversations) {
    return conversations;
  }
  const filteredConversations = conversations.filter((conversation) => {
    if (conversation.type !== "direct_agent") {
      return true;
    }
    return conversation.directSessionId !== deletedSessionId && conversation.conversationId !== deletedSessionId;
  });
  const nextConversation = sessionToConversationSummary(nextDetail);
  const existingIndex = filteredConversations.findIndex(
    (conversation) =>
      conversation.type === "direct_agent"
      && (conversation.directSessionId === nextDetail.id || conversation.conversationId === nextDetail.id),
  );
  if (existingIndex < 0) {
    return [nextConversation, ...filteredConversations];
  }
  return filteredConversations.map((conversation, index) =>
    index === existingIndex
      ? {
          ...conversation,
          ...nextConversation,
        }
      : conversation,
  );
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

function classifyConversation(conversation: ConversationSummary): ConversationGroupKey {
  if (conversation.type === "group_room") {
    return "group";
  }
  const profile = String(conversation.agentProfileId ?? "").trim().toLowerCase();
  const template = String(conversation.agentTemplateLabel ?? "").trim().toLowerCase();
  const primaryMode = String(conversation.agentPrimaryMode ?? "").trim().toLowerCase();
  const roleKey = String(conversation.agentRoleKey ?? "").trim().toLowerCase();
  const promptTemplateId = String(conversation.agentPromptTemplateId ?? "").trim().toLowerCase();
  const title = String(conversation.title ?? "").trim().toLowerCase();
  const combined = `${primaryMode} ${roleKey} ${promptTemplateId} ${profile} ${template} ${title}`;
  if (
    primaryMode === "research"
    || roleKey.startsWith("research_")
    || promptTemplateId.startsWith("prompt-research-")
    || profile.startsWith("research_")
    || combined.includes("research")
    || combined.includes("广撒网 agent")
    || combined.includes("定向深搜 agent")
    || combined.includes("证据审查 agent")
    || combined.includes("主题生成 agent")
    || combined.includes("主题卡 agent")
  ) {
    return "research";
  }
  if (combined.includes("self_evolution") || combined.includes("自进化")) {
    return "selfEvolution";
  }
  if (profile.startsWith("supervised_") || combined.includes("supervised") || combined.includes("监督进化")) {
    return "supervisedEvolution";
  }
  if (title.includes("agent")) {
    return "other";
  }
  return "user";
}

function conversationGroupLabel(groupKey: ConversationGroupKey, lang: "zh" | "en") {
  const labels: Record<ConversationGroupKey, { zh: string; en: string }> = {
    user: { zh: "用户会话", en: "User chats" },
    group: { zh: "群聊", en: "Group chats" },
    research: { zh: "科研 Agent", en: "Research agents" },
    selfEvolution: { zh: "自进化 Agent", en: "Self-evolution agents" },
    supervisedEvolution: { zh: "监督进化 Agent", en: "Supervised agents" },
    other: { zh: "其他 Agent", en: "Other agents" },
  };
  return labels[groupKey][lang];
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
  const location = useLocation();
  const chatPanelWidths = useShellStore((state) => state.chatPanelWidths);
  const setChatPanelWidths = useShellStore((state) => state.setChatPanelWidths);
  const activeSessionId = useChatWorkbenchStore((state) => state.activeSessionId);
  const sessionWorkspaces = useChatWorkbenchStore((state) => state.sessionWorkspaces);
  const setActiveSession = useChatWorkbenchStore((state) => state.setActiveSession);
  const hydrateSession = useChatWorkbenchStore((state) => state.hydrateSession);
  const removeSessionWorkspace = useChatWorkbenchStore((state) => state.removeSession);
  const closePreviewTab = useChatWorkbenchStore((state) => state.closePreviewTab);
  const setActiveTab = useChatWorkbenchStore((state) => state.setActiveTab);
  const [sessionFilter, setSessionFilter] = useState("");
  const [dragState, setDragState] = useState<DragState | null>(null);
  const [leftRailCollapsed, setLeftRailCollapsed] = useState(false);
  const [rightPaneCollapsed, setRightPaneCollapsed] = useState(false);
  const [centerFirstLayout, setCenterFirstLayout] = useState(false);
  const centerFirstAutoCollapseRef = useRef(false);
  const imageUploadInFlightRef = useRef<Record<string, boolean>>({});
  const [sessionDrafts, setSessionDrafts] = useState<Record<string, string>>({});
  const [sessionComposerErrors, setSessionComposerErrors] = useState<Record<string, string>>({});
  const [sessionImageAttachments, setSessionImageAttachments] = useState<Record<string, ComposerImageAttachment[]>>({});
  const [sessionImageUploadPending, setSessionImageUploadPending] = useState<Record<string, boolean>>({});
  const [sessionEditTargets, setSessionEditTargets] = useState<Record<string, { messageId: string; original: string }>>({});
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingSessionTitle, setEditingSessionTitle] = useState("");
  const [sessionStreamConnected, setSessionStreamConnected] = useState(false);
  const [groupStreamConnected, setGroupStreamConnected] = useState(false);
  const [petActionFeedback, setPetActionFeedback] = useState("");
  const [mentalModelEnabledForNextTurn, setMentalModelEnabledForNextTurn] = useState<boolean>(
    () => readStoredMentalModelToggle() ?? true,
  );
  const [mentalModelToggleHydrated, setMentalModelToggleHydrated] = useState<boolean>(
    () => readStoredMentalModelToggle() !== null,
  );
  const [featurePresetState, setFeaturePresetState] = useState<Record<FeaturePresetKey, boolean>>(
    DEFAULT_CHAT_FEATURE_PRESETS,
  );
  const [groupComposerOpen, setGroupComposerOpen] = useState(false);
  const [groupTitleDraft, setGroupTitleDraft] = useState("");
  const [groupModeDraft, setGroupModeDraft] = useState("round_robin");
  const [groupPurposeDraft, setGroupPurposeDraft] = useState("discussion");
  const [groupSelectedAgentIds, setGroupSelectedAgentIds] = useState<string[]>([]);
  const [collapsedConversationGroups, setCollapsedConversationGroups] = useState<Record<ConversationGroupKey, boolean>>(
    DEFAULT_COLLAPSED_CONVERSATION_GROUPS,
  );
  const [rightIndexPanel, setRightIndexPanel] = useState<RightIndexPanel>("conversations");
  const [activeGroupRoomId, setActiveGroupRoomId] = useState("");
  const [expandedGroupAgentSessionId, setExpandedGroupAgentSessionId] = useState("");
  const [groupTopicDraft, setGroupTopicDraft] = useState("");
  const [projectBusDraft, setProjectBusDraft] = useState("");
  const [projectBusInterruptTargets, setProjectBusInterruptTargets] = useState(false);
  const [groupRoomActionError, setGroupRoomActionError] = useState("");
  const [groupManageTitleDraft, setGroupManageTitleDraft] = useState("");
  const [groupManageSessionIds, setGroupManageSessionIds] = useState<string[]>([]);
  const [groupManageModeDraft, setGroupManageModeDraft] = useState("round_robin");
  const [groupManagePurposeDraft, setGroupManagePurposeDraft] = useState("discussion");
  const layoutRef = useRef<HTMLDivElement | null>(null);
  const sessionStreamErrorLoggedRef = useRef<Record<string, boolean>>({});
  const sessionStreamPayloadErrorLoggedRef = useRef<Record<string, boolean>>({});
  const groupStreamErrorLoggedRef = useRef<Record<string, boolean>>({});
  const groupStreamPayloadErrorLoggedRef = useRef<Record<string, boolean>>({});
  const requestedSessionId = useMemo(() => {
    return new URLSearchParams(location.search).get("session") ?? "";
  }, [location.search]);
  const requestedRoomId = useMemo(() => {
    return new URLSearchParams(location.search).get("room") ?? "";
  }, [location.search]);
  const pageVisible = usePageVisibility();
  const projectBusActive = activeGroupRoomId === "__project_agent_bus__";
  const groupPanelActive = Boolean(activeGroupRoomId);
  const legacyGroupRoomActive = groupPanelActive && !projectBusActive;
  useEffect(() => {
    if (!legacyGroupRoomActive && rightIndexPanel === "members") {
      setRightIndexPanel("conversations");
    }
  }, [legacyGroupRoomActive, rightIndexPanel]);

  const runtimeQuery = useQuery({
    queryKey: queryKeys.runtimeSummary(),
    queryFn: () => fetchJson<RuntimeSummary>("/api/runtime/summary"),
    refetchInterval: resolvePollingInterval(pageVisible, 5_000),
    refetchIntervalInBackground: false,
  });
  const petQuery = useQuery({
    queryKey: queryKeys.petSummary(),
    queryFn: () => fetchJson<PetSummary>("/api/pet/summary"),
    refetchInterval: resolvePollingInterval(pageVisible, 10_000),
    refetchIntervalInBackground: false,
  });
  const sessionsQuery = useQuery({
    queryKey: queryKeys.sessions(),
    queryFn: async () => {
      const sessions = await fetchJson<SessionSummary[]>("/api/sessions");
      return sessions.filter(isVisibleDirectSession);
    },
    refetchInterval: resolvePollingInterval(pageVisible, 3_000),
    refetchIntervalInBackground: false,
  });
  const conversationsQuery = useQuery({
    queryKey: queryKeys.conversations(),
    queryFn: () => fetchJson<ConversationSummary[]>("/api/conversations"),
    refetchInterval: resolvePollingInterval(pageVisible, 3_000),
    refetchIntervalInBackground: false,
  });
  const agentsQuery = useQuery({
    queryKey: queryKeys.agents(),
    queryFn: () => fetchJson<AgentInstance[]>("/api/agents"),
    enabled: groupComposerOpen || Boolean(activeSessionId),
  });
  const chatRoomModesQuery = useQuery({
    queryKey: queryKeys.chatRoomModes(),
    queryFn: () => fetchJson<ChatRoomMode[]>("/api/chat-rooms/modes"),
    enabled: groupComposerOpen || legacyGroupRoomActive,
  });
  const chatRoomPurposesQuery = useQuery({
    queryKey: queryKeys.chatRoomPurposes(),
    queryFn: () => fetchJson<ChatRoomPurpose[]>("/api/chat-rooms/purposes"),
    enabled: groupComposerOpen || legacyGroupRoomActive,
  });
  const activeGroupRoomQuery = useQuery({
    queryKey: queryKeys.chatRoom(activeGroupRoomId || "none"),
    queryFn: () => fetchJson<ChatRoomDetail>(`/api/chat-rooms/${activeGroupRoomId}`),
    enabled: legacyGroupRoomActive,
    refetchInterval: legacyGroupRoomActive ? resolvePollingInterval(pageVisible, groupStreamConnected ? false : 3_000) : false,
    refetchIntervalInBackground: false,
  });
  const projectAgentBusQuery = useQuery({
    queryKey: queryKeys.projectAgentBus(),
    queryFn: () => listProjectAgentBusTimeline(),
    enabled: projectBusActive,
    refetchInterval: projectBusActive ? resolvePollingInterval(pageVisible, 3_000) : false,
    refetchIntervalInBackground: false,
  });
  const expandedGroupAgentDetailQuery = useQuery({
    queryKey: queryKeys.session(expandedGroupAgentSessionId || "none"),
    queryFn: () => fetchJson<SessionDetail>(`/api/sessions/${expandedGroupAgentSessionId}`),
    enabled: legacyGroupRoomActive && Boolean(expandedGroupAgentSessionId),
    refetchInterval: legacyGroupRoomActive && expandedGroupAgentSessionId ? resolvePollingInterval(pageVisible, 3_000) : false,
    refetchIntervalInBackground: false,
  });
  const syncSessionDetail = useCallback(
    (detail: SessionDetail) => {
      queryClient.setQueryData(queryKeys.session(detail.id), detail);
      queryClient.setQueryData<SessionSummary[]>(queryKeys.sessions(), (sessions) =>
        mergeSessionDetailIntoSummaries(sessions, detail),
      );
    },
    [queryClient],
  );
  const syncChatRoomDetail = useCallback(
    (room: ChatRoomDetail) => {
      queryClient.setQueryData(queryKeys.chatRoom(room.roomId), room);
      if (String(room.status ?? "").trim().toLowerCase() !== "running") {
        void queryClient.invalidateQueries({ queryKey: queryKeys.chatRooms() });
        void queryClient.invalidateQueries({ queryKey: queryKeys.conversations() });
      }
    },
    [queryClient],
  );
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
      && sessionsQuery.data?.some((session) => session.id === requestedSessionId)
      && activeSessionId !== requestedSessionId
    ) {
      setActiveGroupRoomId("");
      setActiveSession(requestedSessionId);
      return;
    }
    if (!activeSessionId && sessionsQuery.data && sessionsQuery.data.length > 0) {
      setActiveSession(sessionsQuery.data[0].id);
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
    queryFn: () => fetchJson<SessionDetail>(`/api/sessions/${activeSessionId}`),
    refetchInterval: activeSessionId ? resolvePollingInterval(pageVisible, sessionStreamConnected ? false : 3_000) : false,
    refetchIntervalInBackground: false,
  });

  const submitTurnMutation = useMutation({
    mutationFn: async (
      {
        sessionId,
        content,
        mentalModelEnabled,
        attachmentIds,
      }: {
        sessionId: string;
        content: string;
        mentalModelEnabled: boolean;
        attachmentIds?: string[];
      },
    ) =>
      fetchJson<SessionDetail>(`/api/sessions/${sessionId}/messages`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ content, contentUtf8Base64: encodeUtf8Base64(content), attachmentIds: attachmentIds ?? [], mentalModelEnabled }),
      }),
    onMutate: async (variables) => {
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), markSessionDetailRunning);
      queryClient.setQueryData<SessionSummary[]>(queryKeys.sessions(), (sessions) =>
        markSessionSummaryRunning(sessions, variables.sessionId),
      );
    },
    onSuccess: (nextDetail, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      setSessionDrafts((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      setSessionImageAttachments((current) => clearSessionImageAttachments(current, variables.sessionId));
      syncSessionDetail(nextDetail);
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.conversations() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() });
    },
    onError: (error, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("submitFailed")),
      }));
      void queryClient.invalidateQueries({ queryKey: queryKeys.session(variables.sessionId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() });
    },
  });

  const editResubmitMutation = useMutation({
    mutationFn: async (
      {
        sessionId,
        messageId,
        content,
        mentalModelEnabled,
        attachmentIds: _attachmentIds,
      }: {
        sessionId: string;
        messageId: string;
        content: string;
        mentalModelEnabled: boolean;
        attachmentIds?: string[];
      },
    ) =>
      fetchJson<SessionDetail>(`/api/sessions/${sessionId}/messages/edit-resubmit`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ messageId, content, contentUtf8Base64: encodeUtf8Base64(content), mentalModelEnabled }),
      }),
    onMutate: async (variables) => {
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), markSessionDetailRunning);
      queryClient.setQueryData<SessionSummary[]>(queryKeys.sessions(), (sessions) =>
        markSessionSummaryRunning(sessions, variables.sessionId),
      );
    },
    onSuccess: (nextDetail, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      setSessionDrafts((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      setSessionEditTargets((current) => {
        const { [variables.sessionId]: _removed, ...remaining } = current;
        return remaining;
      });
      syncSessionDetail(nextDetail);
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.conversations() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() });
    },
    onError: (error, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("editResubmitFailed")),
      }));
      void queryClient.invalidateQueries({ queryKey: queryKeys.session(variables.sessionId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() });
    },
  });

  const stopTurnMutation = useMutation({
    mutationFn: async ({ sessionId }: { sessionId: string }) =>
      fetchJson<SessionDetail>(`/api/sessions/${sessionId}/stop`, {
        method: "POST",
      }),
    onSuccess: (nextDetail, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      syncSessionDetail(nextDetail);
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.conversations() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() });
    },
    onError: (error, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("stopFailed")),
      }));
      void queryClient.invalidateQueries({ queryKey: queryKeys.session(variables.sessionId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() });
    },
  });

  const createSessionMutation = useMutation({
    mutationFn: async () =>
      fetchJson<SessionDetail>("/api/sessions", {
        method: "POST",
      }),
    onSuccess: (nextDetail) => {
      setActiveGroupRoomId("");
      setRightIndexPanel("conversations");
      setActiveSession(nextDetail.id);
      setSessionFilter("");
      setSessionComposerErrors((current) => ({
        ...current,
        [nextDetail.id]: "",
      }));
      syncSessionDetail(nextDetail);
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.conversations() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() });
    },
    onError: (error) => {
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: describeError(error, t("createSessionFailed")),
      }));
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
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
      void queryClient.invalidateQueries({ queryKey: queryKeys.chatRooms() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.chatRoom(room.roomId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.conversations() });
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
      fetchJson<ChatRoomDetail>(`/api/chat-rooms/${roomId}/rounds`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ topic, mode, purpose }),
      }),
    onSuccess: (room) => {
      setActiveGroupRoomId(room.roomId);
      setRightIndexPanel("members");
      setGroupTopicDraft("");
      setGroupRoomActionError("");
      queryClient.setQueryData(queryKeys.chatRoom(room.roomId), room);
      void queryClient.invalidateQueries({ queryKey: queryKeys.chatRooms() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.chatRoom(room.roomId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.conversations() });
    },
    onError: (error) => {
      setGroupRoomActionError(describeError(error, lang === "zh" ? "启动群聊讨论失败" : "Run group discussion failed"));
      if (activeGroupRoomId) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.chatRoom(activeGroupRoomId) });
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
      void queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() });
    },
    onError: (error, variables) => {
      setGroupRoomActionError(describeError(error, lang === "zh" ? "停止群聊讨论失败" : "Stop group discussion failed"));
      void queryClient.invalidateQueries({ queryKey: queryKeys.chatRoom(variables.roomId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.chatRooms() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() });
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
      void queryClient.invalidateQueries({ queryKey: queryKeys.projectAgentBus() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.conversations() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() });
    },
    onError: (error) => {
      setGroupRoomActionError(describeError(error, lang === "zh" ? "发送总群引导失败" : "Send project bus guidance failed"));
      void queryClient.invalidateQueries({ queryKey: queryKeys.projectAgentBus() });
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
      void queryClient.invalidateQueries({ queryKey: queryKeys.projectAgentBus() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.conversations() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() });
    },
    onError: (error) => {
      setGroupRoomActionError(describeError(error, lang === "zh" ? "撤回总群消息失败" : "Recall project bus message failed"));
      void queryClient.invalidateQueries({ queryKey: queryKeys.projectAgentBus() });
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
      void queryClient.invalidateQueries({ queryKey: queryKeys.chatRooms() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.chatRoom(room.roomId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.conversations() });
    },
    onError: (error) => {
      setGroupRoomActionError(describeError(error, lang === "zh" ? "更新群聊失败" : "Update group failed"));
      if (activeGroupRoomId) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.chatRoom(activeGroupRoomId) });
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
      void queryClient.invalidateQueries({ queryKey: queryKeys.chatRooms() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.conversations() });
    },
    onError: (error) => {
      setGroupRoomActionError(describeError(error, lang === "zh" ? "删除群聊失败" : "Delete group failed"));
    },
  });

  const deleteSessionMutation = useMutation({
    mutationFn: async ({ sessionId }: { sessionId: string }) =>
      fetchJson<SessionDetail>(`/api/sessions/${sessionId}`, {
        method: "DELETE",
      }),
    onSuccess: (nextDetail, variables) => {
      removeSessionWorkspace(variables.sessionId, nextDetail.id);
      setActiveSession(nextDetail.id);
      setSessionDrafts((current) => {
        const { [variables.sessionId]: _removed, ...remaining } = current;
        return remaining;
      });
      setSessionImageAttachments((current) => clearSessionImageAttachments(current, variables.sessionId));
      delete imageUploadInFlightRef.current[variables.sessionId];
      setSessionImageUploadPending((current) => {
        const { [variables.sessionId]: _removed, ...remaining } = current;
        return remaining;
      });
      setSessionComposerErrors((current) => {
        const { [variables.sessionId]: _removed, ...remaining } = current;
        return {
          ...remaining,
          [nextDetail.id]: "",
        };
      });
      queryClient.removeQueries({ queryKey: queryKeys.session(variables.sessionId), exact: true });
      queryClient.setQueryData<SessionSummary[]>(queryKeys.sessions(), (sessions) =>
        removeDeletedSessionFromSummaries(sessions, variables.sessionId, nextDetail),
      );
      queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations(), (conversations) =>
        removeDeletedSessionFromConversations(conversations, variables.sessionId, nextDetail),
      );
      syncSessionDetail(nextDetail);
      setGroupManageSessionIds((current) => current.filter((sessionId) => sessionId !== variables.sessionId));
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.chatRooms() });
      if (activeGroupRoomId) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.chatRoom(activeGroupRoomId) });
      }
      void queryClient.invalidateQueries({ queryKey: queryKeys.conversations() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() });
    },
    onError: (error, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("deleteSessionFailed")),
      }));
      void queryClient.invalidateQueries({ queryKey: queryKeys.session(variables.sessionId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
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
    onSuccess: (nextDetail, variables) => {
      setEditingSessionId(null);
      setEditingSessionTitle("");
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations(), (conversations) =>
        mergeSessionDetailIntoConversations(conversations, nextDetail),
      );
      syncSessionDetail(nextDetail);
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.conversations() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() });
    },
    onError: (error, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("renameSessionFailed")),
      }));
      void queryClient.invalidateQueries({ queryKey: queryKeys.session(variables.sessionId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
    },
  });

  const updateSessionAgentMutation = useMutation({
    mutationFn: async ({ sessionId, agentId }: { sessionId: string; agentId: string }) =>
      fetchJson<SessionDetail>(`/api/sessions/${sessionId}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ agentId }),
      }),
    onSuccess: (nextDetail, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      syncSessionDetail(nextDetail);
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.conversations() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents() });
    },
    onError: (error, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, lang === "zh" ? "保存会话 Agent 配置失败" : "Save session agent config failed"),
      }));
      void queryClient.invalidateQueries({ queryKey: queryKeys.session(variables.sessionId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
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
    if (!activeSessionId || !pageVisible || typeof EventSource === "undefined") {
      setSessionStreamConnected(false);
      return;
    }

    let disposed = false;
    const streamSessionId = activeSessionId;
    const stream = new EventSource(`/api/sessions/${streamSessionId}/events`);

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
        }
      }
    };

    function handleSessionDetail(event: MessageEvent<string>) {
      let payload: SessionStreamEvent;
      try {
        payload = JSON.parse(event.data) as SessionStreamEvent;
      } catch {
        if (!sessionStreamPayloadErrorLoggedRef.current[streamSessionId]) {
          sessionStreamPayloadErrorLoggedRef.current[streamSessionId] = true;
          postBrowserTelemetry({
            phase: "session_stream",
            eventCode: "browser.session_stream.bad_payload",
            message: "Session detail stream payload could not be parsed.",
            level: "warning",
            fields: {
              sessionId: streamSessionId,
              payloadLength: event.data.length,
            },
          });
        }
        return;
      }
      if (!shouldAcceptSessionStreamEvent(payload, streamSessionId)) {
        return;
      }
      setSessionStreamConnected(true);
      syncSessionDetail(payload.detail);
    }

    stream.addEventListener("session_detail", handleSessionDetail as EventListener);

    return () => {
      const readyStateBeforeClose = stream.readyState;
      disposed = true;
      setSessionStreamConnected(false);
      stream.removeEventListener("session_detail", handleSessionDetail as EventListener);
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
  }, [activeSessionId, pageVisible, syncSessionDetail]);

  useEffect(() => {
    if (!legacyGroupRoomActive || !activeGroupRoomId || !pageVisible || typeof EventSource === "undefined") {
      setGroupStreamConnected(false);
      return;
    }

    let disposed = false;
    const streamRoomId = activeGroupRoomId;
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
  }, [activeGroupRoomId, legacyGroupRoomActive, pageVisible, syncChatRoomDetail]);

  const workspace = activeSessionId
    ? sessionWorkspaces[activeSessionId] ?? {
        openTabs: [],
        activeTab: "agent",
      }
    : { openTabs: [], activeTab: "agent" };

  const activeFilePath = workspace.activeTab !== "agent" ? workspace.activeTab : null;
  const fileContentQuery = useQuery({
    queryKey: queryKeys.fileContent(activeFilePath ?? ""),
    enabled: Boolean(activeFilePath),
    queryFn: () =>
      fetchJson<FileContent>(`/api/files/content?path=${encodeURIComponent(activeFilePath ?? "")}`),
  });

  const changedFiles = new Set(sessionDetailQuery.data?.changedFiles ?? []);
  const leftPanelWidth = chatPanelWidths.leftPanelWidth;
  const rightPanelWidth = chatPanelWidths.rightPanelWidth;

  const syncPanelWidthsToLayout = useCallback(() => {
    const layoutWidth = layoutRef.current?.getBoundingClientRect().width ?? 0;
    if (!layoutWidth) {
      return;
    }
    const normalized = normalizePanelWidths(layoutWidth, leftPanelWidth, rightPanelWidth);
    if (
      normalized.leftPanelWidth !== leftPanelWidth ||
      normalized.rightPanelWidth !== rightPanelWidth
    ) {
      setChatPanelWidths(normalized);
    }
  }, [leftPanelWidth, rightPanelWidth, setChatPanelWidths]);

  useEffect(() => {
    syncPanelWidthsToLayout();
    const layoutElement = layoutRef.current;
    if (!layoutElement) {
      return;
    }

    const observer = new ResizeObserver(() => {
      syncPanelWidthsToLayout();
    });
    observer.observe(layoutElement);

    return () => observer.disconnect();
  }, [syncPanelWidthsToLayout]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const mediaQuery = window.matchMedia(CHAT_CENTER_FIRST_MEDIA_QUERY);
    function applyCenterFirstState(matches: boolean) {
      setCenterFirstLayout(matches);
      if (matches && !centerFirstAutoCollapseRef.current) {
        centerFirstAutoCollapseRef.current = true;
        setLeftRailCollapsed(true);
        setRightPaneCollapsed(true);
      }
      if (!matches) {
        centerFirstAutoCollapseRef.current = false;
      }
    }
    applyCenterFirstState(mediaQuery.matches);
    const handleChange = (event: MediaQueryListEvent) => {
      applyCenterFirstState(event.matches);
    };
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, []);

  useEffect(() => {
    if (!dragState) {
      return;
    }
    const activeDrag = dragState;

    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    function stopDragging() {
      setDragState(null);
    }

    function handlePointerMove(event: globalThis.PointerEvent) {
      const layoutWidth = layoutRef.current?.getBoundingClientRect().width ?? 0;
      if (!layoutWidth) {
        return;
      }

      const delta = event.clientX - activeDrag.startX;

      if (activeDrag.side === "left") {
        if (leftRailCollapsed) {
          return;
        }
        const bounds = getResizeBounds("left", layoutWidth, rightPaneCollapsed ? 0 : activeDrag.startRightWidth);
        const nextLeftWidth = clamp(activeDrag.startLeftWidth + delta, bounds.min, bounds.max);
        setChatPanelWidths({ leftPanelWidth: Math.round(nextLeftWidth) });
        return;
      }

      if (rightPaneCollapsed) {
        return;
      }
      const bounds = getResizeBounds("right", layoutWidth, leftRailCollapsed ? 0 : activeDrag.startLeftWidth);
      const nextRightWidth = clamp(activeDrag.startRightWidth - delta, bounds.min, bounds.max);
      setChatPanelWidths({ rightPanelWidth: Math.round(nextRightWidth) });
    }

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", stopDragging);
    window.addEventListener("pointercancel", stopDragging);

    return () => {
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", stopDragging);
      window.removeEventListener("pointercancel", stopDragging);
    };
  }, [dragState, leftRailCollapsed, rightPaneCollapsed, setChatPanelWidths]);

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

  const runtime = runtimeQuery.data;
  const pet = petQuery.data;
  const detail = sessionDetailQuery.data;
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
    () => new Set((activeGroupRoom?.participants ?? []).map((participant) => participant.sessionId)),
    [activeGroupRoom?.participants],
  );
  useEffect(() => {
    if (!groupPanelActive) {
      if (expandedGroupAgentSessionId) {
        setExpandedGroupAgentSessionId("");
      }
      return;
    }
    if (
      expandedGroupAgentSessionId
      && !activeGroupParticipantSessionSet.has(expandedGroupAgentSessionId)
    ) {
      setExpandedGroupAgentSessionId("");
    }
  }, [activeGroupParticipantSessionSet, expandedGroupAgentSessionId, groupPanelActive]);
  const groupManageChanged = Boolean(
    legacyGroupRoomActive
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
    !legacyGroupRoomActive
    ||
    !activeGroupRoom
    || groupRoundActive
    || updateGroupRoomMutation.isPending
    || !groupManageTitleDraft.trim()
    || groupManageSessionIds.length < 2
    || !groupManageModeDraft
    || !groupManagePurposeDraft;
  const groupDeleteDisabled =
    !legacyGroupRoomActive
    ||
    !activeGroupRoom
    || groupRoundActive
    || deleteGroupRoomMutation.isPending;
  const groupStopDisabled =
    !legacyGroupRoomActive
    || !activeGroupRoom
    || !groupRoundRunning
    || stopGroupRoundMutation.isPending;
  const activeSurfaceTitle = groupPanelActive
    ? (
      projectBusActive
        ? (lang === "zh" ? "项目总群" : "Project bus")
        : activeGroupRoom?.title ?? (lang === "zh" ? "群聊加载中" : "Loading group")
    )
    : detail?.title ?? runtime?.sessionTitle ?? t("loadingSession");
  const activeSurfaceStatus = groupPanelActive
    ? (
      projectBusActive
        ? (lang === "zh" ? "观察与投递" : "observe and deliver")
        : statusLabel(activeGroupRoom?.status ?? "ready")
    )
    : statusLabel(detail?.status || detail?.currentPhase || "idle");
  const activeSurfaceLine = groupPanelActive
    ? (
      projectBusActive
        ? `${projectBusTimeline?.activeAgentCount ?? 0} ${lang === "zh" ? "位 active Agent" : "active agents"} · @全体成员 / @AgentCode`
        : (
          activeGroupRound?.summary
          || `${activeGroupRoom?.participants?.length ?? 0} ${lang === "zh" ? "位 Agent" : "agents"} · ${activeGroupRoom?.mode ?? "round_robin"} · ${activeGroupRoom?.purpose ?? "discussion"}`
        )
    )
    : "";
  const sessionDetailErrorState = deriveSessionDetailQueryErrorState(detail, sessionDetailQuery.isError, {
    dataUpdatedAt: sessionDetailQuery.dataUpdatedAt,
    errorUpdatedAt: sessionDetailQuery.errorUpdatedAt,
    streamConnected: sessionStreamConnected,
  });
  const sessionsErrorState = deriveSessionListQueryErrorState(sessionsQuery.data, sessionsQuery.isError);
  const sessionDetailErrorMessage = sessionDetailQuery.isError
    ? describeError(sessionDetailQuery.error, t("loadFailed"))
    : "";
  const sessionsErrorMessage = sessionsQuery.isError
    ? describeError(sessionsQuery.error, t("loadFailed"))
    : "";
  const activeDraft = activeSessionId ? sessionDrafts[activeSessionId] ?? "" : "";
  const activeComposerError = activeSessionId ? sessionComposerErrors[activeSessionId] ?? "" : "";
  const activeEditTarget = activeSessionId ? sessionEditTargets[activeSessionId] ?? null : null;
  const activeImageAttachments = activeSessionId ? sessionImageAttachments[activeSessionId] ?? [] : [];
  const activeImageUploadPending = activeSessionId ? Boolean(sessionImageUploadPending[activeSessionId]) : false;
  const sessionAgentOptions = useMemo(() => {
    return (agentsQuery.data ?? []).filter((agent) => {
      const mode = String(agent.primaryMode ?? "").trim();
      return (
        String(agent.kind ?? "").trim() === "persistent"
        && String(agent.status ?? "").trim() !== "archived"
        && (mode === "chat" || mode === "general")
      );
    });
  }, [agentsQuery.data]);
  const activeAgentId = detail?.agentId || "";
  const activeSessionAgent = sessionAgentOptions.find((agent) => agent.agentId === activeAgentId);
  const activeAgentProfileId = activeSessionAgent?.profileId || detail?.agentProfileId || detail?.agentTemplateId || "primary";
  const activeAgentDisplay = detail
    ? sessionAgentDisplayInfo(detail, activeSessionAgent, lang)
    : { name: pet?.name || "Agent", functionLabel: "", tone: "chat" as const, meta: "" };
  const activeAgentFunctionLabel = activeAgentDisplay.functionLabel;
  const activeAgentDisplayName = activeAgentDisplay.name;
  const activeAgentMetaLabel = activeAgentDisplay.meta || activeAgentFunctionLabel || activeAgentProfileId;
  const activeAgentStatusMessage = detail?.agentMissing
    ? detail.agentStatusMessage || (lang === "zh" ? "缺少有效 Agent，部分内容无法继续运行。" : "Missing valid Agent. Some content cannot keep running.")
    : "";
  const agentTemplateSavePending =
    updateSessionAgentMutation.isPending && updateSessionAgentMutation.variables?.sessionId === activeSessionId;
  const latestUserMessageId = useMemo(() => deriveLatestUserMessageId(detail?.messages), [detail?.messages]);
  const resolvedEditTarget = resolveLatestEditTarget(activeEditTarget, latestUserMessageId);
  const activeDraftEffective = resolveComposerDraftValue(activeDraft, activeEditTarget, resolvedEditTarget);
  const submitMutationMatchesActiveSession =
    submitTurnMutation.variables?.sessionId === activeSessionId;
  const editResubmitMutationMatchesActiveSession =
    editResubmitMutation.variables?.sessionId === activeSessionId;
  const stopMutationMatchesActiveSession =
    stopTurnMutation.variables?.sessionId === activeSessionId;
  const submitPending =
    (submitTurnMutation.isPending && submitMutationMatchesActiveSession)
    || (editResubmitMutation.isPending && editResubmitMutationMatchesActiveSession)
    || activeImageUploadPending;
  const sessionRunning = isRunningPhase(detail?.currentPhase);
  const sessionStopping = isStoppingPhase(detail?.currentPhase) || Boolean(detail?.stopRequested);
  const sessionBusy = isBusyPhase(detail?.currentPhase);
  const composerStopMode = sessionBusy;
  const composerGuidance = sessionBusy && !sessionStopping ? t("sessionBusyComposerGuidance") : "";
  const composerPending =
    composerStopMode ? (stopTurnMutation.isPending && stopMutationMatchesActiveSession) || sessionStopping : submitPending;
  const composerDisabled = !activeSessionId || submitPending;
  const composerActionDisabled = !activeSessionId || (
    composerStopMode ? composerPending : submitPending || (!activeDraftEffective.trim() && !activeImageAttachments.length)
  );
  const composerPlaceholder =
    !activeSessionId
      ? t("loadingSession")
      : sessionStopping
        ? t("sessionStoppingPlaceholder")
        : sessionBusy
          ? t("sessionBusyPlaceholder")
          : resolvedEditTarget
            ? t("editMessagePlaceholder")
          : t("messageInputPlaceholder");
  const sessionContextUsage = detail?.contextUsage;
  const panelContextUsed = sessionContextUsage?.used ?? runtime?.contextUsage.used ?? 0;
  const panelContextLimit = sessionContextUsage?.limit ?? runtime?.contextUsage.limit ?? 0;
  const contextPercent = contextUsagePercent(panelContextUsed, panelContextLimit);
  const contextUsageLabel = formatContextUsage(panelContextUsed, panelContextLimit, locale);
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
  const petAvatarSkinClass = styles[`petShowcaseAvatar_${petAvatarPresetKey}`] ?? styles.petShowcaseAvatar_default;
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
  const contextStatusLine = runtimeQuery.isError
    ? describeError(runtimeQuery.error, t("loadFailed"))
    : sessionContextUsage
      ? contextUsageLabel
      : runtime
      ? contextUsageLabel
      : t("loadingContext");
  const contextUsageMetaLine = sessionContextUsage
    ? `${numberFormatter.format(sessionContextUsage.messageCount)} ${lang === "zh" ? "条消息" : "messages"} · ${numberFormatter.format(sessionContextUsage.userMessageCount)} ${lang === "zh" ? "用户" : "user"} / ${numberFormatter.format(sessionContextUsage.assistantMessageCount)} Agent`
    : runtime
      ? `${numberFormatter.format(runtime.contextUsage.used)} / ${numberFormatter.format(runtime.contextUsage.limit)}`
      : t("loadingContext");
  const sessionCacheUsage = detail?.cacheUsage;
  const cacheHitRatePercent = Math.round(Math.max(0, Math.min(1, sessionCacheUsage?.turnCacheHitRate ?? 0)) * 100);
  const cacheHitLine = sessionCacheUsage
    ? `${numberFormatter.format(sessionCacheUsage.turnCachedInputTokens)} / ${numberFormatter.format(sessionCacheUsage.turnInputTokens)} · ${cacheHitRatePercent}%`
    : t("cacheObservationPending");
  const compression = runtime?.contextCompression;
  const compressionCurrentPercent = compression
    ? Math.round(Math.max(0, Math.min(1, compression.usageRatio || 0)) * 100)
    : contextPercent;
  const compressionLevelLabel = compression?.enabled === false
    ? t("compressionDisabled")
    : compression?.currentLevel
      ? compression.currentLevel
      : "--";
  const compressionMainLine = compression
    ? `${numberFormatter.format(compression.currentTokens)} / ${numberFormatter.format(compression.effectiveTokenLimit)} · ${compressionCurrentPercent}%`
    : t("loadingContext");
  const lastCompression = compression?.lastCompression ?? null;
  const lastCompressionLine = lastCompression
    ? `${lastCompression.level || "--"} · ${numberFormatter.format(lastCompression.beforeTokens)} -> ${numberFormatter.format(lastCompression.afterTokens)} · -${numberFormatter.format(lastCompression.savedTokens)}`
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
    switch (runtime?.sessionState) {
      case "thinking":
        return t("sessionStateThinking");
      case "tooling":
        return t("sessionStateTooling");
      case "answering":
        return t("sessionStateAnswering");
      default:
        return statusLabel(runtime?.sessionState ?? detail?.currentPhase ?? "idle");
    }
  })();
  const sessionStateLine = groupPanelActive
    ? activeSurfaceLine
    : runtime?.sessionStateLine
      ?? (sessionDetailErrorState.blockingError
        ? sessionDetailErrorMessage
        : activeAgentStatusMessage || detail?.taskSummary || t("preparingShell"));
  const activeTask = detail?.activeTask ?? null;
  const sessionStateValue = String(groupPanelActive ? (projectBusActive ? "ready" : activeGroupRoom?.status ?? "ready") : runtime?.sessionState ?? detail?.currentPhase ?? "idle")
    .trim()
    .toLowerCase();
  const currentTaskSummary =
    activeTask?.goal
    || activeTask?.title
    || activeTask?.nextAction
    || activeTask?.latestSummary
    || detail?.taskSummary
    || runtime?.taskSummary
    || t("preparingShell");
  const fileContextValue = detail?.defaultFileContext ?? runtime?.defaultRoute ?? "workspace";
  const sessionCompactRows = buildVisiblePanelRows(
    [
      {
        label: t("fileContext"),
        value: fileContextValue,
        title: fileContextValue,
      },
      {
        label: t("currentTask"),
        value: currentTaskSummary,
        title: currentTaskSummary,
      },
      {
        label: t("promptCache"),
        value: cacheHitLine,
        title: sessionCacheUsage
          ? `${t("promptCacheLast")} ${numberFormatter.format(sessionCacheUsage.lastCachedInputTokens)} / ${numberFormatter.format(sessionCacheUsage.lastInputTokens)} · ${t("promptCacheTotal")} ${numberFormatter.format(sessionCacheUsage.totalCachedInputTokens)} / ${numberFormatter.format(sessionCacheUsage.totalInputTokens)}`
          : t("cacheObservationPending"),
      },
    ],
    [t("preparingShell"), t("loadingSession"), t("loadingContext")],
  );
  const mental = runtime?.mentalState;
  useEffect(() => {
    if (mentalModelToggleHydrated || !runtime) {
      return;
    }
    const defaultEnabled = String(runtime.mentalState?.source ?? "").trim().toLowerCase() !== "disabled";
    setMentalModelEnabledForNextTurn(defaultEnabled);
    setMentalModelToggleHydrated(true);
  }, [mentalModelToggleHydrated, runtime]);

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

  const chatMentionTargets = useMemo(() => {
    return buildChatMentionTargets(agentsQuery.data ?? []);
  }, [agentsQuery.data]);

  const visibleSessions = useMemo(() => {
    return (sessionsQuery.data ?? []).filter(isVisibleDirectSession);
  }, [sessionsQuery.data]);

  const sessionsById = useMemo(() => {
    return new Map(visibleSessions.map((session) => [session.id, session]));
  }, [visibleSessions]);

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
        ];
  }, [chatRoomPurposesQuery.data]);

  const filteredConversations = useMemo(() => {
    const term = sessionFilter.trim().toLowerCase();
    const conversations = conversationsQuery.data ?? visibleSessions.map(sessionToConversationSummary);
    const visibleConversations = conversations.filter((conversation) => isVisibleConversation(conversation, sessionsById));
    if (!term) {
      return visibleConversations;
    }
    return visibleConversations.filter((conversation) =>
      [conversation.title, conversation.summary, conversation.status, conversation.type, conversation.agentCode ?? "", conversation.agentDisplayName ?? "", conversation.agentTemplateLabel ?? ""].some((value) =>
        String(value ?? "").toLowerCase().includes(term),
      ),
    );
  }, [conversationsQuery.data, sessionFilter, sessionsById, visibleSessions]);
  const groupedConversations = useMemo(() => {
    const buckets = new Map<ConversationGroupKey, ConversationSummary[]>(
      CONVERSATION_GROUP_ORDER.map((groupKey) => [groupKey, []]),
    );
    filteredConversations.forEach((conversation) => {
      const groupKey = classifyConversation(conversation);
      buckets.get(groupKey)?.push(conversation);
    });
    return CONVERSATION_GROUP_ORDER
      .map((groupKey) => ({
        groupKey,
        label: conversationGroupLabel(groupKey, lang === "zh" ? "zh" : "en"),
        items: buckets.get(groupKey) ?? [],
      }))
      .filter((group) => group.items.length > 0);
  }, [filteredConversations, lang]);
  const searchHasTerm = sessionFilter.trim().length > 0;

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

  function toggleConversationGroup(groupKey: ConversationGroupKey) {
    setCollapsedConversationGroups((current) => ({
      ...current,
      [groupKey]: !current[groupKey],
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
    setMentalModelToggleHydrated(true);
    writeStoredMentalModelToggle(enabled);
  }

  function handleAddComposerAttachments(files: FileList | File[]) {
    if (!activeSessionId) {
      return;
    }
    const incoming = Array.from(files || []).filter((file) => file.type.startsWith("image/"));
    if (!incoming.length) {
      return;
    }
    const accepted: ComposerImageAttachment[] = [];
    const rejected: string[] = [];
    for (const file of incoming) {
      if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
        rejected.push(file.name);
        continue;
      }
      if (file.size > MAX_COMPOSER_IMAGE_BYTES) {
        rejected.push(file.name);
        continue;
      }
      accepted.push({
        id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
        file,
        filename: file.name || "image",
        previewUrl: URL.createObjectURL(file),
        sizeBytes: file.size,
        contentType: file.type,
      });
    }
    setSessionImageAttachments((current) => {
      const existing = current[activeSessionId] ?? [];
      const merged = [...existing, ...accepted].slice(0, MAX_COMPOSER_IMAGE_ATTACHMENTS);
      return {
        ...current,
        [activeSessionId]: merged,
      };
    });
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

  async function submitTurnWithAttachments(
    sessionId: string,
    content: string,
    attachments: ComposerImageAttachment[],
    mentalModelEnabled: boolean,
  ) {
    if (imageUploadInFlightRef.current[sessionId]) {
      return;
    }
    imageUploadInFlightRef.current[sessionId] = true;
    setSessionImageUploadPending((current) => ({
      ...current,
      [sessionId]: true,
    }));
    try {
      const uploaded = await Promise.all(attachments.map((attachment) => uploadSessionImageAttachment(sessionId, attachment)));
      submitTurnMutation.mutate({
        sessionId,
        content,
        mentalModelEnabled,
        attachmentIds: uploaded.map((attachment) => attachment.artifactId).filter(Boolean),
      });
    } catch (error) {
      setSessionComposerErrors((current) => ({
        ...current,
        [sessionId]: describeError(error, lang === "zh" ? "图片上传失败" : "Image upload failed"),
      }));
    } finally {
      imageUploadInFlightRef.current[sessionId] = false;
      setSessionImageUploadPending((current) => ({
        ...current,
        [sessionId]: false,
      }));
    }
  }

  function handleSubmitTurn() {
    if (!activeSessionId) {
      return;
    }
    const content = activeDraftEffective.trim();
    if ((!content && !activeImageAttachments.length) || composerDisabled) {
      return;
    }
    if (resolvedEditTarget) {
      editResubmitMutation.mutate({
        sessionId: activeSessionId,
        messageId: resolvedEditTarget.messageId,
        content,
        mentalModelEnabled: mentalModelEnabledForNextTurn,
      });
      return;
    }
    void submitTurnWithAttachments(activeSessionId, content, activeImageAttachments, mentalModelEnabledForNextTurn);
  }

  function handleEditUserMessage(message: ConversationMessage) {
    if (!activeSessionId || sessionBusy) {
      return;
    }
    if (message.id !== latestUserMessageId) {
      return;
    }
    setSessionEditTargets((current) => ({
      ...current,
      [activeSessionId]: {
        messageId: message.id,
        original: message.content,
      },
    }));
    setSessionImageAttachments((current) => clearSessionImageAttachments(current, activeSessionId));
    setSessionDrafts((current) => ({
      ...current,
      [activeSessionId]: message.content,
    }));
    setSessionComposerErrors((current) => ({
      ...current,
      [activeSessionId]: "",
    }));
  }

  useEffect(() => {
    if (!activeSessionId || !detail || !activeEditTarget || activeEditTarget.messageId === latestUserMessageId) {
      return;
    }
    setSessionEditTargets((current) => {
      const { [activeSessionId]: _removed, ...remaining } = current;
      return remaining;
    });
    setSessionDrafts((current) => ({
      ...current,
      [activeSessionId]: "",
    }));
  }, [activeEditTarget, activeSessionId, latestUserMessageId, setSessionDrafts, setSessionEditTargets]);

  function handleCancelEditMessage() {
    if (!activeSessionId) {
      return;
    }
    setSessionEditTargets((current) => {
      const { [activeSessionId]: _removed, ...remaining } = current;
      return remaining;
    });
    setSessionDrafts((current) => ({
      ...current,
      [activeSessionId]: "",
    }));
    setSessionImageAttachments((current) => clearSessionImageAttachments(current, activeSessionId));
  }

  function handleStopTurn() {
    if (!activeSessionId || !sessionBusy || sessionStopping) {
      return;
    }
    stopTurnMutation.mutate({
      sessionId: activeSessionId,
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
    createSessionMutation.mutate();
  }

  function handleOpenProjectAgentBus() {
    setActiveGroupRoomId("__project_agent_bus__");
    setRightIndexPanel("conversations");
    setRightPaneCollapsed(false);
    setGroupRoomActionError("");
    void queryClient.invalidateQueries({ queryKey: queryKeys.projectAgentBus() });
  }

  function handleOpenDirectSession(sessionId: string) {
    setActiveGroupRoomId("");
    setRightIndexPanel("conversations");
    setGroupRoomActionError("");
    setActiveSession(sessionId);
  }

  function handleOpenMentionTarget(target: ChatMentionTarget) {
    setRightPaneCollapsed(false);
    setGroupRoomActionError("");
    if (target.kind === "all") {
      setActiveGroupRoomId("__project_agent_bus__");
      setRightIndexPanel("conversations");
      setSessionFilter("");
      void queryClient.invalidateQueries({ queryKey: queryKeys.projectAgentBus() });
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
        <button
          key={`mention-${index}-${segment.text}`}
          type="button"
          className={styles.agentMention}
          onClick={() => handleOpenMentionTarget(segment.target)}
          aria-label={lang === "zh" ? `打开 ${mentionLabel} 的索引` : `Open ${mentionLabel} index`}
          title={lang === "zh" ? "打开对应 Agent 索引" : "Open the matching agent index"}
        >
          {segment.text}
        </button>
      );
    });
  }

  function handleOpenGroupRoom(roomId: string) {
    if (!roomId) {
      return;
    }
    setActiveGroupRoomId(roomId);
    setRightIndexPanel("members");
    setRightPaneCollapsed(false);
    setGroupRoomActionError("");
    void queryClient.invalidateQueries({ queryKey: queryKeys.chatRoom(roomId) });
  }

  function handleToggleGroupManageSession(sessionId: string) {
    if (!sessionId || groupRoundActive || updateGroupRoomMutation.isPending) {
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
    if (!legacyGroupRoomActive || !activeGroupRoomId || !topic || startGroupRoundMutation.isPending || groupRoundActive) {
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
    if (!legacyGroupRoomActive || !activeGroupRoomId || !groupRoundRunning || stopGroupRoundMutation.isPending) {
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
    if (!legacyGroupRoomActive || !activeGroupRoomId || groupManageDisabled) {
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
    if (!legacyGroupRoomActive || !activeGroupRoomId || groupDeleteDisabled) {
      return;
    }
    const roomTitle = (activeGroupRoom?.title || activeGroupRoomId).trim();
    const groupConfirmMessage = t("deleteGroupConfirm").replace("{title}", roomTitle || activeGroupRoomId);
    if (!window.confirm(groupConfirmMessage)) {
      return;
    }
    deleteGroupRoomMutation.mutate({ roomId: activeGroupRoomId });
  }

  function handleDeleteSession(session: SessionSummary) {
    if (isBusyPhase(session.currentPhase || session.status)) {
      setSessionComposerErrors((current) => ({
        ...current,
        [session.id]: t("deleteSessionBusy"),
        __sessions__: "",
      }));
      return;
    }
    const sessionTitle = (session.title || session.agentDisplayName || session.id).trim();
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

  function handleAddSessionToReview(session: SessionSummary) {
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
    setEditingSessionId(session.id);
    setEditingSessionTitle(session.title);
    setSessionComposerErrors((current) => ({
      ...current,
      [session.id]: "",
      __sessions__: "",
    }));
  }

  function cancelRenameSession() {
    setEditingSessionId(null);
    setEditingSessionTitle("");
  }

  function submitRenameSession(session: SessionSummary) {
    const title = editingSessionTitle.trim();
    if (!title) {
      setSessionComposerErrors((current) => ({
        ...current,
        [session.id]: t("renameSessionEmpty"),
      }));
      return;
    }
    if (title === session.title) {
      cancelRenameSession();
      return;
    }
    renameSessionMutation.mutate({ sessionId: session.id, title });
  }

  function handleAgentTemplateChange(agentId: string) {
    if (!activeSessionId || !agentId || agentId === activeAgentId) {
      return;
    }
    setSessionComposerErrors((current) => ({
      ...current,
      [activeSessionId]: "",
      __sessions__: "",
    }));
    updateSessionAgentMutation.mutate({ sessionId: activeSessionId, agentId });
  }

  function handleResizeStart(side: ResizableSide, event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) {
      return;
    }
    if ((side === "left" && leftRailCollapsed) || (side === "right" && rightPaneCollapsed)) {
      return;
    }
    event.preventDefault();
    setDragState({
      side,
      startX: event.clientX,
      startLeftWidth: leftPanelWidth,
      startRightWidth: rightPanelWidth,
    });
  }

  function handleResizeKeyDown(side: ResizableSide, event: KeyboardEvent<HTMLDivElement>) {
    if (!layoutRef.current) {
      return;
    }
    if ((side === "left" && leftRailCollapsed) || (side === "right" && rightPaneCollapsed)) {
      return;
    }

    const { key } = event;
    const direction =
      key === "ArrowLeft" ? -1 : key === "ArrowRight" ? 1 : key === "Home" ? "min" : key === "End" ? "max" : null;
    if (direction === null) {
      return;
    }

    event.preventDefault();
    const layoutWidth = layoutRef.current.getBoundingClientRect().width;

    if (side === "left") {
      const bounds = getResizeBounds("left", layoutWidth, rightPaneCollapsed ? 0 : rightPanelWidth);
      const nextLeftWidth =
        direction === "min"
          ? bounds.min
          : direction === "max"
            ? bounds.max
            : clamp(leftPanelWidth + Number(direction) * KEYBOARD_RESIZE_STEP, bounds.min, bounds.max);
      setChatPanelWidths({ leftPanelWidth: Math.round(nextLeftWidth) });
      return;
    }

    const bounds = getResizeBounds("right", layoutWidth, leftRailCollapsed ? 0 : leftPanelWidth);
    const delta =
      direction === "min"
        ? bounds.min
        : direction === "max"
          ? bounds.max
          : clamp(rightPanelWidth - Number(direction) * KEYBOARD_RESIZE_STEP, bounds.min, bounds.max);
    setChatPanelWidths({ rightPanelWidth: Math.round(delta) });
  }

  const toggleFeaturePreset = useCallback((key: FeaturePresetKey) => {
    setFeaturePresetState((current) => ({
      ...current,
      [key]: !current[key],
    }));
  }, []);

  const layoutStyle = useMemo(
    () =>
      ({
        "--chat-left-pane-width": leftRailCollapsed ? "0px" : `${leftPanelWidth}px`,
        "--chat-right-pane-width": rightPaneCollapsed ? "0px" : `${rightPanelWidth}px`,
      }) as CSSProperties,
    [leftPanelWidth, leftRailCollapsed, rightPanelWidth, rightPaneCollapsed],
  );

  return (
    <div
      ref={layoutRef}
      className={centerFirstLayout ? `${styles.layout} ${styles.layoutCenterFirst}` : styles.layout}
      style={layoutStyle}
    >
      <aside className={leftRailCollapsed ? `${styles.leftRail} ${styles.paneCollapsed}` : styles.leftRail} aria-hidden={leftRailCollapsed}>
        {legacyGroupRoomActive ? (
          <section className={`${styles.leftBlock} ${styles.groupProfileBlock}`}>
            <div className={styles.sectionHeader}>
              <div className={styles.sectionIdentity}>
                <p className={styles.blockEyebrow}>{lang === "zh" ? "群资料与设置" : "Group profile"}</p>
                <h3 className={styles.sectionTitle}>{activeGroupRoom?.title ?? (lang === "zh" ? "群聊加载中" : "Loading group")}</h3>
              </div>
              <span className={`${styles.sessionStatePill} ${styles[`sessionStatePill_${String(activeGroupRoom?.status ?? "ready").trim().toLowerCase()}`]}`}>
                {statusLabel(activeGroupRoom?.status ?? "ready")}
              </span>
            </div>
            <p className={styles.contextLineCompact}>
              {lang === "zh"
                ? "这里管理当前群聊的资料、成员和调度；成员状态索引放在右侧独立分栏。"
                : "Manage this group's info, members, and scheduling here. Member status lives in the right index."}
            </p>
            <div className={styles.resourceSplit}>
              <div className={styles.resourceMetric}>
                <span>{lang === "zh" ? "成员" : "Members"}</span>
                <strong>{numberFormatter.format(activeGroupRoom?.participants?.length ?? 0)}</strong>
              </div>
              <div className={styles.resourceMetric}>
                <span>{lang === "zh" ? "调度" : "Mode"}</span>
                <strong>{activeGroupRoom?.mode ?? "round_robin"}</strong>
              </div>
              <div className={styles.resourceMetric}>
                <span>{lang === "zh" ? "目的" : "Purpose"}</span>
                <strong>{activeGroupRoom?.purpose ?? "discussion"}</strong>
              </div>
            </div>
            <section className={styles.groupManagementPanel} aria-label={lang === "zh" ? "群聊管理" : "Group management"}>
              <div className={styles.groupManagementHeader}>
                <div>
                  <strong>{lang === "zh" ? "群设置" : "Group settings"}</strong>
                  <span title={activeGroupRoom?.title ?? ""}>
                    {activeGroupRoom?.title ?? (lang === "zh" ? "群聊加载中" : "Loading group")}
                  </span>
                </div>
                <div className={styles.groupManagementActions}>
                  <button
                    type="button"
                    className={groupManageChanged ? styles.groupApplyButton : styles.groupSecondaryButton}
                    disabled={groupManageDisabled || !groupManageChanged}
                    onClick={handleApplyGroupRoomManagement}
                  >
                    <Check size={14} />
                    <span>
                      {updateGroupRoomMutation.isPending
                        ? (lang === "zh" ? "应用中" : "Applying")
                        : (lang === "zh" ? "应用变更" : "Apply")}
                    </span>
                  </button>
                  <button
                    type="button"
                    className={styles.groupDeleteButton}
                    disabled={groupDeleteDisabled}
                    onClick={handleDeleteActiveGroupRoom}
                  >
                    <Trash2 size={14} />
                    <span>
                      {deleteGroupRoomMutation.isPending
                        ? (lang === "zh" ? "删除中" : "Deleting")
                        : (lang === "zh" ? "删除" : "Delete")}
                    </span>
                  </button>
                </div>
              </div>
              {groupRoomActionError ? (
                <div className={styles.panelNotice}>{groupRoomActionError}</div>
              ) : null}
              <div className={styles.groupManagementControls}>
                <label className={styles.groupTitleField}>
                  <span>{lang === "zh" ? "群名" : "Name"}</span>
                  <input
                    value={groupManageTitleDraft}
                    maxLength={80}
                    disabled={groupRoundActive || updateGroupRoomMutation.isPending}
                    onChange={(event) => {
                      setGroupRoomActionError("");
                      setGroupManageTitleDraft(event.target.value);
                    }}
                  />
                </label>
                <label className={styles.groupModeSelect}>
                  <span>{lang === "zh" ? "调度模式" : "Mode"}</span>
                  <select
                    value={groupManageModeDraft}
                    disabled={groupRoundActive || updateGroupRoomMutation.isPending}
                    onChange={(event) => {
                      setGroupRoomActionError("");
                      setGroupManageModeDraft(event.target.value);
                    }}
                  >
                    {readyChatRoomModes.map((mode) => (
                      <option key={mode.id} value={mode.id}>
                        {chatRoomModeLabel(mode, lang)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className={styles.groupModeSelect}>
                  <span>{lang === "zh" ? "对话目的" : "Purpose"}</span>
                  <select
                    value={groupManagePurposeDraft}
                    disabled={groupRoundRunning || updateGroupRoomMutation.isPending}
                    onChange={(event) => {
                      setGroupRoomActionError("");
                      setGroupManagePurposeDraft(event.target.value);
                    }}
                  >
                    {availableChatRoomPurposes.map((purpose) => (
                      <option key={purpose.id} value={purpose.id}>
                        {chatRoomPurposeLabel(purpose, lang)}
                      </option>
                    ))}
                  </select>
                </label>
                <div className={styles.groupManagementCount}>
                  <span>{lang === "zh" ? "已选" : "Selected"}</span>
                  <strong>
                    {groupManageSessionIds.length}/{sessionsQuery.data?.length ?? 0}
                  </strong>
                </div>
                <div className={styles.groupMemberPicker}>
                  {(sessionsQuery.data ?? []).map((session) => {
                    const selected = groupManageSessionSet.has(session.id);
                    const sessionAgent = session.agentId ? agentsById.get(session.agentId) : undefined;
                    const display = sessionAgentDisplayInfo(session, sessionAgent, lang);
                    const missingMessage = session.agentMissing
                      ? session.agentStatusMessage || (lang === "zh" ? "缺少有效 Agent" : "Missing valid Agent")
                      : "";
                    return (
                      <label
                        key={session.id}
                        className={
                          selected
                            ? `${styles.groupMemberChip} ${styles.groupMemberChipSelected}`
                            : styles.groupMemberChip
                        }
                      >
                        <input
                          type="checkbox"
                          checked={selected}
                          disabled={groupRoundActive || updateGroupRoomMutation.isPending}
                          onChange={() => handleToggleGroupManageSession(session.id)}
                        />
                        <span className={styles.groupMemberCopy}>
                          <strong>{display.name}</strong>
                          <small className={`${styles.agentRoleTag} ${styles[agentRoleClass(display.tone)]}`}>
                            {display.functionLabel}
                          </small>
                        </span>
                        {missingMessage ? (
                          <span className={styles.agentMissingInline} title={missingMessage}>
                            {lang === "zh" ? "缺少有效 Agent" : "Missing Agent"}
                          </span>
                        ) : null}
                      </label>
                    );
                  })}
                </div>
              </div>
              {groupRoundActive ? (
                <p className={styles.groupManagementHint}>
                  {lang === "zh" ? "群聊运行中，成员和模式会在本轮结束后允许修改。" : "The group is running. Members and mode can be changed after this round finishes."}
                </p>
              ) : groupManageSessionIds.length < 2 ? (
                <p className={styles.groupManagementHint}>
                  {lang === "zh" ? "群聊至少需要保留 2 位 Agent。" : "A group needs at least 2 agents."}
                </p>
              ) : null}
            </section>
          </section>
        ) : (
          <>
        <section className={styles.leftBlock}>
          <div className={styles.sectionHeader}>
            <div className={styles.sectionIdentity}>
              <p className={styles.blockEyebrow}>{t("currentSession")}</p>
              <h3 className={styles.sectionTitle}>{activeSurfaceTitle}</h3>
            </div>
            <span className={`${styles.sessionStatePill} ${styles[`sessionStatePill_${sessionStateValue}`]}`}>
              {sessionStateLabel}
            </span>
          </div>
          <p className={styles.contextLineCompact}>{sessionStateLine}</p>
          {sessionCompactRows.length > 0 ? (
            <div className={styles.inlineMetaList}>
              {sessionCompactRows.map((row) => (
                <span key={row.label} className={styles.inlineMetaPill} title={row.title ?? row.value}>
                  <span>{row.label}</span>
                  <strong>{row.value}</strong>
                </span>
              ))}
            </div>
          ) : null}
        </section>

        <section className={`${styles.leftBlock} ${styles.featurePresetBlock}`}>
          <div className={styles.sectionHeader}>
            <div className={styles.sectionIdentity}>
              <p className={styles.blockEyebrow}>{t("chatFeaturePanel")}</p>
              <h3 className={styles.sectionTitle}>{t("chatFeaturePanelTitle")}</h3>
            </div>
            <span className={styles.featurePresetScope}>{t("chatFeaturePanelScope")}</span>
          </div>
          <div className={styles.featurePrimarySlot}>
            <button
              type="button"
              className={
                mentalModelEnabledForNextTurn
                  ? `${styles.featureToggle} ${styles.featureToggleActive} ${styles.featureTogglePrimary}`
                  : `${styles.featureToggle} ${styles.featureTogglePrimary}`
              }
              aria-pressed={mentalModelEnabledForNextTurn}
              disabled={!activeSessionId}
              onClick={() => handleMentalModelEnabledChange(!mentalModelEnabledForNextTurn)}
            >
              <span className={styles.featureToggleText}>
                <strong>{t("chatFeatureMentalModel")}</strong>
                <span>{t("mentalModelForNextTurn")}</span>
              </span>
              <span className={styles.featureToggleState}>
                {mentalModelEnabledForNextTurn ? t("mentalModelNextTurnOn") : t("mentalModelNextTurnOff")}
              </span>
            </button>
          </div>
          <div className={styles.featureChipRow}>
            {CHAT_FEATURE_PRESETS.map((item) => {
              const enabled = featurePresetState[item.key];
              return (
                <button
                  key={item.key}
                  type="button"
                  className={enabled ? `${styles.featureChip} ${styles.featureChipActive}` : styles.featureChip}
                  aria-pressed={enabled}
                  onClick={() => toggleFeaturePreset(item.key)}
                  title={t(item.hintKey)}
                >
                  <strong>{t(item.labelKey)}</strong>
                  <span aria-hidden="true" />
                </button>
              );
            })}
          </div>
          <p className={styles.featurePresetNote}>{t("chatFeaturePanelHint")}</p>
        </section>

        <section className={`${styles.leftBlock} ${styles.resourceBlock}`}>
          <div className={styles.sectionHeader}>
            <p className={styles.blockEyebrow}>{t("contextInUse")}</p>
            <span className={styles.metricValue}>{contextPercent}%</span>
          </div>
          <div className={styles.resourceSplit}>
            <div className={styles.resourceMetric}>
              <span>{t("contextInUse")}</span>
              <strong title={contextStatusLine}>{contextStatusLine}</strong>
            </div>
            <div className={styles.resourceMetric}>
              <span>{t("contextCompression")}</span>
              <strong>{compressionCurrentPercent}% · {compressionLevelLabel}</strong>
            </div>
          </div>
          <p className={styles.oneLineValue} title={lastCompression?.reason || lastCompressionLine}>
            <span>{t("compressionLastRun")}</span>
            {lastCompressionLine}
          </p>
          <details className={styles.compactDetails}>
            <summary>
              <ChevronRight size={14} />
              <span className={styles.compactDetailsClosedLabel}>{t("compressionStrategy")}</span>
              <span className={styles.compactDetailsOpenLabel}>{t("collapseSection")}</span>
            </summary>
            <div className={styles.compressionStrategyList}>
              {(compression?.strategy.levels ?? []).map((level) => (
                <div key={level.level} className={styles.compressionStrategyRow}>
                  <strong>{level.level}</strong>
                  <span>{t("compressionThreshold")} {Math.round(level.thresholdRatio * 100)}% / {numberFormatter.format(level.thresholdTokens)}</span>
                  <span>{t("compressionKeepAi")} {level.keepAiMessages}</span>
                  <span>{t("compressionSummary")} {numberFormatter.format(level.summaryMaxChars)}</span>
                </div>
              ))}
            </div>
            <p className={styles.detailNote}>
              <span>{t("compressionErrorProtection")}</span>
              {(compression?.strategy.errorProtectionKeywords ?? []).join(" / ") || "--"}
            </p>
          </details>
        </section>

        <section className={`${styles.leftBlock} ${styles.companionBlock}`}>
          <div className={styles.sectionHeader}>
            <div className={styles.sectionIdentity}>
              <p className={styles.blockEyebrow}>{t("mentalState")} / {t("petSpace")}</p>
              <p className={styles.sectionMetaLine}>{mentalCompactLine || mentalSourceLabel}</p>
            </div>
            <span className={`${styles.mentalStateBadge} ${styles[`mentalStateBadge_${mentalCognitiveStateValue}`]}`}>
              {mentalStateLabel}
            </span>
          </div>
          <p className={styles.contextLineCompact}>{mentalSummary}</p>
          <div className={styles.companionCompact}>
            <div className={styles.petMiniAvatar} aria-hidden="true">
              <div className={`${styles.petShowcaseAvatar} ${petAvatarSkinClass}`}>
                <span className={styles.petShowcaseEarLeft} />
                <span className={styles.petShowcaseEarRight} />
                <span className={styles.petShowcaseFace}>
                  <span className={styles.petShowcaseEye} />
                  <span className={styles.petShowcaseMuzzle} />
                  <span className={styles.petShowcaseEye} />
                </span>
                <span className={styles.petShowcaseSymbol}>{petAvatarSymbol}</span>
                <span className={styles.petShowcaseFootLeft} />
                <span className={styles.petShowcaseFootRight} />
              </div>
            </div>
            <div className={styles.companionCopy}>
              <div className={styles.companionTopLine}>
                <strong>{pet?.name ?? t("loadingPetState")}</strong>
                <span>{t("level")} {pet?.level ?? 0} · {petPresetLabel}</span>
              </div>
              <p title={petCompactLine}>{petCompactLine}</p>
            </div>
          </div>
          <details className={styles.compactDetails}>
            <summary>
              <ChevronRight size={14} />
              <span className={styles.compactDetailsClosedLabel}>{t("expandSection")}</span>
              <span className={styles.compactDetailsOpenLabel}>{t("collapseSection")}</span>
            </summary>
            <p className={styles.oneLineValue} title={mentalWhisper}>
              <span>{t("mentalWhisper")}</span>
              {mentalWhisper}
            </p>
            <div className={styles.inlineStatGrid}>
              <div className={styles.inlineStat}>
                <span>{t("state")}</span>
                <strong>{mentalCognitiveStateLabel}</strong>
              </div>
              <div className={styles.inlineStat}>
                <span>{t("mentalConfidence")}</span>
                <strong>{mentalConfidence}</strong>
              </div>
              <div className={styles.inlineStat}>
                <span>{t("mentalSource")}</span>
                <strong>{mentalSourceLabel}</strong>
              </div>
              <div className={styles.inlineStat}>
                <span>{t("mentalLastUpdated")}</span>
                <strong title={formatTime(mental?.updatedAt ?? "")}>{mentalRelativeTime}</strong>
              </div>
            </div>
            <div className={styles.inlineMetaList}>
              <span className={styles.inlineMetaPill}>
                <span>{t("dailyTokens")}</span>
                <strong>{numberFormatter.format(pet?.dailyTokens ?? 0)}</strong>
              </span>
              {petVitals.map((vital) => (
                <span key={vital.key} className={styles.inlineMetaPill}>
                  <span>{vital.label}</span>
                  <strong>{vital.value}</strong>
                </span>
              ))}
            </div>
            <div className={styles.petShowcaseActions} aria-label={petInteractionLabels.group}>
              <button
                type="button"
                className={styles.petShowcaseAction}
                onClick={() => handlePetInteraction("feed")}
                disabled={petActionMutation.isPending}
                title={petInteractionLabels.feedTitle}
              >
                <Apple size={14} />
                <span>{petInteractionLabels.feed}</span>
              </button>
              <button
                type="button"
                className={styles.petShowcaseAction}
                onClick={() => handlePetInteraction("talk")}
                disabled={petActionMutation.isPending}
                title={petInteractionLabels.talkTitle}
              >
                <MessageCircleHeart size={14} />
                <span>{petInteractionLabels.talk}</span>
              </button>
              <button
                type="button"
                className={styles.petShowcaseAction}
                onClick={() => handlePetInteraction("care")}
                disabled={petActionMutation.isPending}
                title={petInteractionLabels.careTitle}
              >
                <HeartHandshake size={14} />
                <span>{petInteractionLabels.care}</span>
              </button>
              <span className={styles.petShowcaseActionHint}>
                <Sparkles size={13} />
                <span>{petInteractionLabels.pending}</span>
              </span>
            </div>
            {petActionFeedback ? <p className={styles.petShowcaseFeedback}>{petActionFeedback}</p> : null}
          </details>
        </section>
          </>
        )}
      </aside>

      <PaneCollapseHandle
        side="left"
        collapsed={leftRailCollapsed}
        separatorLabel={t("resizeLeftPanel")}
        collapseLabel={lang === "zh" ? "收起左栏" : "Collapse left pane"}
        expandLabel={lang === "zh" ? "展开左栏" : "Expand left pane"}
        className={styles.resizeHandle}
        active={dragState?.side === "left"}
        activeClassName={styles.resizeHandleActive}
        onToggle={() => setLeftRailCollapsed((current) => !current)}
        onPointerDown={(event) => handleResizeStart("left", event)}
        onKeyDown={(event) => handleResizeKeyDown("left", event)}
      />

      <section className={styles.centerPane}>
        <div className={styles.tabStrip}>
          <button
            type="button"
            className={
              groupPanelActive || workspace.activeTab === "agent" ? `${styles.tab} ${styles.tabActive}` : styles.tab
            }
            onClick={() => {
              if (groupPanelActive) {
                return;
              }
              activeSessionId && setActiveTab(activeSessionId, "agent");
            }}
          >
            {groupPanelActive ? (projectBusActive ? (lang === "zh" ? "项目总群" : "Project bus") : (lang === "zh" ? "群聊" : "Group")) : t("agentSession")}
          </button>
          {!groupPanelActive && workspace.openTabs.map((tabPath) => (
            <div
              key={tabPath}
              className={
                workspace.activeTab === tabPath
                  ? `${styles.fileTab} ${styles.fileTabActive}`
                  : styles.fileTab
              }
            >
              <button
                type="button"
                className={styles.fileTabButton}
                onClick={() => activeSessionId && setActiveTab(activeSessionId, tabPath)}
              >
                {tabPath.split("/").at(-1)}
              </button>
              <button
                type="button"
                className={styles.fileTabClose}
                onClick={() => activeSessionId && closePreviewTab(activeSessionId, tabPath)}
                title={t("closePreviewTab")}
                aria-label={`${t("closePreviewTab")} ${tabPath.split("/").at(-1)}`}
              >
                <X size={14} />
              </button>
            </div>
          ))}
        </div>

        <div className={styles.centerSurface}>
          {projectBusActive ? (
            <div className={styles.groupConversationFrame}>
              <header className={styles.groupConversationHeader}>
                <div>
                  <p>
                    {activeGroupRoom?.mode ?? "round_robin"}
                    {" · "}
                    {activeGroupRoom?.purpose ?? "discussion"}
                  </p>
                  <h2>{lang === "zh" ? "项目总群" : "Project bus"}</h2>
                  <span>
                    {projectBusTimeline?.activeAgentCount ?? (activeGroupRoom?.participants ?? []).length} {lang === "zh" ? "位 active Agent" : "active agents"}
                    {" · "}
                    {lang === "zh" ? "观察与投递" : "observe and deliver"}
                  </span>
                </div>
                <button
                  type="button"
                  className={styles.groupRefreshButton}
                  onClick={() => void projectAgentBusQuery.refetch()}
                  disabled={projectAgentBusQuery.isFetching}
                >
                  {lang === "zh" ? "刷新" : "Refresh"}
                </button>
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
                              <button
                                type="button"
                                onClick={() => handleRevokeProjectBusMessage(event.eventId)}
                                disabled={revokeProjectBusMessageMutation.isPending}
                              >
                                {lang === "zh" ? "撤回" : "Recall"}
                              </button>
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
                        {(round.messages ?? []).map((message: ChatRoomMessage) => (
                          <article
                            key={message.messageId}
                            className={
                              message.status === "failed"
                                ? `${styles.groupBubbleRow} ${styles.groupBubbleRowFailed}`
                                : styles.groupBubbleRow
                            }
                          >
                            <span className={styles.groupBubbleAvatar} aria-hidden="true">
                              {avatarInitials(undefined, message.speakerTitle, "AI")}
                            </span>
                            <div className={styles.groupBubble}>
                              <header className={styles.groupBubbleHeader}>
                                <strong>{message.speakerTitle}</strong>
                                <span>{statusLabel(message.status)}</span>
                              </header>
                              <p className={styles.groupBubbleBody}>
                                {renderMentionedText(message.content || message.summary, lang === "zh" ? "暂无内容" : "No content yet")}
                              </p>
                              <time className={styles.groupBubbleMeta}>{formatTime(message.timestamp || round.updatedAt)}</time>
                            </div>
                          </article>
                        ))}
                        {roundRunning && nextParticipant ? (
                          <article className={`${styles.groupBubbleRow} ${styles.groupBubbleRowPending}`}>
                            <span className={styles.groupBubbleAvatar} aria-hidden="true">
                              {avatarInitials(undefined, nextParticipant.title, "AI")}
                            </span>
                            <div className={styles.groupBubble}>
                              <header className={styles.groupBubbleHeader}>
                                <strong>{formatAgentIdentity(nextParticipant.agentCode, nextParticipant.title, nextParticipant.participantId)}</strong>
                                <span>{lang === "zh" ? "正在输入" : "typing"}</span>
                              </header>
                              <div className={styles.groupTypingDots} aria-label={lang === "zh" ? "正在输入" : "Typing"}>
                                <span />
                                <span />
                                <span />
                              </div>
                            </div>
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
                    <p>{lang === "zh" ? "项目总群会显示用户引导、Agent 私聊和广播投递结果。" : "The project bus shows guidance, private messages, broadcasts, and delivery results."}</p>
                  </div>
                )}
              </div>
              <div className={styles.groupComposerBar}>
                <input
                  value={projectBusDraft}
                  onChange={(event) => setProjectBusDraft(event.target.value)}
                  disabled={sendProjectBusMessageMutation.isPending}
                  placeholder={lang === "zh" ? "输入总群消息；不带 @ 默认投递全体，可用 @AgentCode 指定" : "Message the project bus; no @ sends to all, @AgentCode targets one"}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      handleSendProjectBusMessage();
                    }
                  }}
                />
                <label className={styles.projectBusInterruptToggle}>
                  <input
                    type="checkbox"
                    checked={projectBusInterruptTargets}
                    onChange={(event) => setProjectBusInterruptTargets(event.target.checked)}
                  />
                  <span>{lang === "zh" ? "打断目标 Agent" : "Interrupt targets"}</span>
                </label>
                <button
                  type="button"
                  onClick={handleSendProjectBusMessage}
                  disabled={
                    !projectBusDraft.trim()
                    || sendProjectBusMessageMutation.isPending
                  }
                >
                  <UsersRound size={15} />
                  <span>
                    {sendProjectBusMessageMutation.isPending
                      ? (lang === "zh" ? "发送中" : "Sending")
                      : (lang === "zh" ? "发送到总群" : "Send")}
                  </span>
                </button>
              </div>
            </div>
          ) : legacyGroupRoomActive ? (
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
                    {(activeGroupRoom?.participants ?? []).length} {lang === "zh" ? "位 Agent" : "agents"}
                    {" · "}
                    {statusLabel(activeGroupRoom?.status ?? "ready")}
                  </span>
                </div>
                <button
                  type="button"
                  className={styles.groupRefreshButton}
                  onClick={() => activeGroupRoomId && void activeGroupRoomQuery.refetch()}
                  disabled={activeGroupRoomQuery.isFetching}
                >
                  {lang === "zh" ? "刷新" : "Refresh"}
                </button>
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
                        {(round.messages ?? []).map((message: ChatRoomMessage) => (
                          <article
                            key={message.messageId}
                            className={
                              message.status === "failed"
                                ? `${styles.groupBubbleRow} ${styles.groupBubbleRowFailed}`
                                : styles.groupBubbleRow
                            }
                          >
                            <span className={styles.groupBubbleAvatar} aria-hidden="true">
                              {avatarInitials(undefined, message.speakerTitle, "AI")}
                            </span>
                            <div className={styles.groupBubble}>
                              <header className={styles.groupBubbleHeader}>
                                <strong>{message.speakerTitle}</strong>
                                <span>{statusLabel(message.status)}</span>
                              </header>
                              <p className={styles.groupBubbleBody}>
                                {renderMentionedText(message.content || message.summary, lang === "zh" ? "暂无内容" : "No content yet")}
                              </p>
                              <time className={styles.groupBubbleMeta}>{formatTime(message.timestamp || round.updatedAt)}</time>
                            </div>
                          </article>
                        ))}
                        {roundRunning && nextParticipant ? (
                          <article className={`${styles.groupBubbleRow} ${styles.groupBubbleRowPending}`}>
                            <span className={styles.groupBubbleAvatar} aria-hidden="true">
                              {avatarInitials(undefined, nextParticipant.title, "AI")}
                            </span>
                            <div className={styles.groupBubble}>
                              <header className={styles.groupBubbleHeader}>
                                <strong>{formatAgentIdentity(nextParticipant.agentCode, nextParticipant.title, nextParticipant.participantId)}</strong>
                                <span>{lang === "zh" ? "正在输入" : "typing"}</span>
                              </header>
                              <div className={styles.groupTypingDots} aria-label={lang === "zh" ? "正在输入" : "Typing"}>
                                <span />
                                <span />
                                <span />
                              </div>
                            </div>
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
                <input
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
                <button
                  type="button"
                  onClick={handleStartGroupRound}
                  disabled={
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
                </button>
                {groupRoundActive ? (
                  <button
                    type="button"
                    className={styles.groupStopButton}
                    onClick={handleStopGroupRound}
                    disabled={groupStopDisabled}
                    title={lang === "zh" ? "停止当前群聊轮次" : "Stop current group round"}
                  >
                    <Square size={15} />
                    <span>
                      {stopGroupRoundMutation.isPending
                        ? (lang === "zh" ? "停止中" : "Stopping")
                        : (lang === "zh" ? "停止" : "Stop")}
                    </span>
                  </button>
                ) : null}
              </div>
            </div>
          ) : !activeSessionId && !sessionsQuery.isPending ? (
            <div className={styles.emptySurface}>{t("noSessionsYet")}</div>
          ) : sessionDetailErrorState.blockingError ? (
            <div className={styles.emptySurface}>
              {sessionDetailErrorMessage}
            </div>
          ) : workspace.activeTab === "agent" ? (
            detail ? (
              <div className={styles.conversationFrame}>
                {sessionDetailErrorState.transientError ? (
                  <div className={styles.inlineNotice} role="status">
                    {sessionDetailErrorMessage}
                  </div>
                ) : null}
                <ConversationView
                  sessionId={activeSessionId ?? detail.id}
                  title={detail.title}
                  phase={detail.currentPhase}
                  messages={detail.messages}
                  assistantDisplayName={activeAgentDisplayName}
                  userDisplayName={runtime?.userName}
                  userAvatarPreset={runtime?.userProfile?.avatarPreset}
                  userAvatarImageUrl={runtime?.userProfile?.avatarImageUrl}
                  taskSummary={currentTaskSummary}
                  defaultFileContext={detail.defaultFileContext}
                  showHeader={false}
                  showSessionOverview={false}
                  composerValue={activeDraftEffective}
                  composerPlaceholder={composerPlaceholder}
                  composerDisabled={composerDisabled}
                  composerActionDisabled={composerActionDisabled}
                  composerActionMode={composerStopMode ? "stop" : "send"}
                  composerPending={composerPending}
                  composerError={activeComposerError}
                  composerGuidance={composerGuidance}
                  composerAttachments={activeImageAttachments.map((attachment) => ({
                    id: attachment.id,
                    filename: attachment.filename,
                    previewUrl: attachment.previewUrl,
                    sizeBytes: attachment.sizeBytes,
                    contentType: attachment.contentType,
                  }))}
                  composerAttachmentInputDisabled={composerDisabled || Boolean(resolvedEditTarget)}
                  composerModeNotice={resolvedEditTarget ? t("editMessageModeNotice") : ""}
                  cancelComposerModeLabel={t("cancelEditMessage")}
                  turnError={detail.lastTurnError}
                  nextStateSignals={detail.nextStateSignals ?? []}
                  stopLabel={t("stop")}
                  stopPendingLabel={t("stopPending")}
                  editingMessageId={resolvedEditTarget?.messageId}
                  editUserMessageLabel={t("editAndResendMessage")}
                  editUserMessageDisabled={sessionBusy || submitPending}
                  onComposerChange={handleComposerChange}
                  onAddComposerAttachments={handleAddComposerAttachments}
                  onRemoveComposerAttachment={handleRemoveComposerAttachment}
                  onEditUserMessage={handleEditUserMessage}
                  onCancelComposerMode={resolvedEditTarget ? handleCancelEditMessage : undefined}
                  onSubmit={handleSubmitTurn}
                  onStop={handleStopTurn}
                />
              </div>
            ) : (
              <div className={styles.emptySurface}>{t("loadingSession")}</div>
            )
          ) : fileContentQuery.isError ? (
            <div className={styles.emptySurface}>
              {describeError(fileContentQuery.error, t("loadFailed"))}
            </div>
          ) : fileContentQuery.data ? (
            <Suspense fallback={<div className={styles.emptySurface}>{t("loadingFilePreview")}</div>}>
              <FilePreview
                file={fileContentQuery.data}
                changed={changedFiles.has(fileContentQuery.data.path)}
                sourceLabel={detail?.title ?? t("currentSession")}
              />
            </Suspense>
          ) : (
            <div className={styles.emptySurface}>{t("loadingFilePreview")}</div>
          )}
        </div>
      </section>

      <PaneCollapseHandle
        side="right"
        collapsed={rightPaneCollapsed}
        separatorLabel={t("resizeRightPanel")}
        collapseLabel={lang === "zh" ? "收起右栏" : "Collapse right pane"}
        expandLabel={lang === "zh" ? "展开右栏" : "Expand right pane"}
        className={styles.resizeHandle}
        active={dragState?.side === "right"}
        activeClassName={styles.resizeHandleActive}
        onToggle={() => setRightPaneCollapsed((current) => !current)}
        onPointerDown={(event) => handleResizeStart("right", event)}
        onKeyDown={(event) => handleResizeKeyDown("right", event)}
      />

      <aside className={rightPaneCollapsed ? `${styles.rightPane} ${styles.paneCollapsed}` : styles.rightPane} aria-hidden={rightPaneCollapsed}>
        <div
          className={legacyGroupRoomActive ? styles.rightIndexTabs : `${styles.rightIndexTabs} ${styles.rightIndexTabsSingle}`}
          role="tablist"
          aria-label={lang === "zh" ? "右侧索引" : "Right index"}
        >
          <button
            type="button"
            role="tab"
            aria-selected={rightIndexPanel === "conversations"}
            className={rightIndexPanel === "conversations" ? `${styles.rightIndexTab} ${styles.rightIndexTabActive}` : styles.rightIndexTab}
            onClick={() => setRightIndexPanel("conversations")}
          >
            <MessageCircleHeart size={14} />
            <span>{lang === "zh" ? "会话" : "Chats"}</span>
          </button>
          {legacyGroupRoomActive ? (
            <button
              type="button"
              role="tab"
              aria-selected={rightIndexPanel === "members"}
              className={rightIndexPanel === "members" ? `${styles.rightIndexTab} ${styles.rightIndexTabActive}` : styles.rightIndexTab}
              onClick={() => setRightIndexPanel("members")}
            >
              <UsersRound size={14} />
              <span>{lang === "zh" ? "成员" : "Members"}</span>
            </button>
          ) : null}
        </div>

        {rightIndexPanel === "members" && legacyGroupRoomActive ? (
          <div className={styles.memberIndexSummary}>
            <UsersRound size={15} />
            <span>
              {activeGroupRoom?.participants?.length ?? 0} {lang === "zh" ? "位 Agent" : "agents"}
            </span>
            <strong>{statusLabel(activeGroupRoom?.status ?? "ready")}</strong>
          </div>
        ) : (
          <div className={styles.panelSearch}>
            <Search size={15} />
            <input
              className={styles.panelSearchInput}
              type="text"
              value={sessionFilter}
              onChange={(event) => setSessionFilter(event.target.value)}
              placeholder={t("searchSessionsPlaceholder")}
            />
          </div>
        )}

        <div className={styles.panelBody}>
          {rightIndexPanel === "members" && legacyGroupRoomActive ? (
            <section className={styles.agentIndexRoster} aria-label={lang === "zh" ? "群成员状态索引" : "Group member status index"}>
              <div className={styles.sectionHeader}>
                <div className={styles.sectionIdentity}>
                  <p className={styles.blockEyebrow}>{lang === "zh" ? "成员状态" : "Member status"}</p>
                  <h3 className={styles.sectionTitle}>{activeGroupRoom?.title ?? (lang === "zh" ? "群聊加载中" : "Loading group")}</h3>
                </div>
              </div>
              <p className={styles.contextLineCompact}>
                {lang === "zh"
                  ? "展开成员查看该 Agent 自己的上下文、心智快照和会话状态。"
                  : "Expand a member to inspect that agent's context, mental snapshot, and session status."}
              </p>
              <div className={styles.agentIndexList}>
                {(activeGroupRoom?.participants ?? []).map((participant: ChatRoomParticipant) => {
                  const expanded = expandedGroupAgentSessionId === participant.sessionId;
                  const participantSession = sessionsById.get(participant.sessionId);
                  const memberDetail = expanded ? expandedGroupAgentDetailQuery.data : undefined;
                  const memberContext = memberDetail?.contextUsage;
                  const memberContextUsed = memberContext?.used ?? 0;
                  const memberContextLimit = memberContext?.limit ?? 0;
                  const memberContextPercent = contextUsagePercent(memberContextUsed, memberContextLimit);
                  const memberMental = latestMentalSnapshot(memberDetail?.messages);
                  const memberMentalState = memberMental?.mood?.trim()
                    || memberMental?.cognitiveState?.trim()
                    || (lang === "zh" ? "未记录" : "No snapshot");
                  const memberMentalSummary = memberMental?.feeling?.trim()
                    || memberMental?.summary?.trim()
                    || (lang === "zh" ? "该 Agent 尚未形成可展示的心智快照。" : "This agent has no visible mental snapshot yet.");
                  const participantMissingMessage = participant.agentMissing
                    ? participant.agentStatusMessage || (lang === "zh" ? "缺少有效 Agent，已从群聊调度中停用。" : "Missing valid Agent. This member is disabled for group scheduling.")
                    : "";
                  const participantAgent = participant.agentId ? agentsById.get(participant.agentId) : undefined;
                  const participantDisplay = participantAgentDisplayInfo(participant, participantAgent, lang);
                  const memberUpdated = formatRelativeTime(
                    memberMental?.updatedAt || memberDetail?.updatedAt || participantSession?.updatedAt || "",
                    Date.now(),
                    locale,
                  );
                  return (
                    <article key={participant.participantId || participant.sessionId} className={styles.agentIndexCard}>
                      <button
                        type="button"
                        className={styles.agentIndexHeader}
                        aria-expanded={expanded}
                        onClick={() => setExpandedGroupAgentSessionId(expanded ? "" : participant.sessionId)}
                      >
                        <ChevronRight size={14} aria-hidden="true" />
                        <span className={styles.agentIndexAvatar} aria-hidden="true">
                          {avatarInitials(participant.agentCode, participant.title)}
                        </span>
                        <span className={styles.agentIndexCopy}>
                          <strong>{participantDisplay.name}</strong>
                          <em className={`${styles.agentRoleTag} ${styles[agentRoleClass(participantDisplay.tone)]}`}>
                            {participantDisplay.functionLabel}
                          </em>
                        </span>
                        <span className={participant.agentMissing ? styles.agentIndexWarning : styles.agentIndexStatus}>
                          {participant.agentMissing ? (lang === "zh" ? "缺少 Agent" : "Missing") : statusLabel(participant.status || participantSession?.status || "ready")}
                        </span>
                      </button>
                      {participantMissingMessage ? (
                        <p className={styles.agentMissingNotice}>{participantMissingMessage}</p>
                      ) : null}
                      {expanded ? (
                        <div className={styles.agentIndexDetails}>
                          {expandedGroupAgentDetailQuery.isPending ? (
                            <p className={styles.contextLineCompact}>{t("loadingSession")}</p>
                          ) : expandedGroupAgentDetailQuery.isError ? (
                            <p className={styles.panelNotice}>{describeError(expandedGroupAgentDetailQuery.error, t("loadFailed"))}</p>
                          ) : (
                            <>
                              <div className={styles.resourceSplit}>
                                <div className={styles.resourceMetric}>
                                  <span>{t("contextInUse")}</span>
                                  <strong>{formatContextUsage(memberContextUsed, memberContextLimit, locale)}</strong>
                                </div>
                                <div className={styles.resourceMetric}>
                                  <span>{lang === "zh" ? "上下文占比" : "Context ratio"}</span>
                                  <strong>{memberContextPercent}%</strong>
                                </div>
                              </div>
                              <p className={styles.oneLineValue}>
                                <span>{lang === "zh" ? "消息" : "Messages"}</span>
                                {memberContext
                                  ? `${numberFormatter.format(memberContext.messageCount)} ${lang === "zh" ? "条" : "messages"} · ${numberFormatter.format(memberContext.assistantMessageCount)} Agent`
                                  : (lang === "zh" ? "暂无上下文统计" : "No context stats yet")}
                              </p>
                              <div className={styles.agentIndexMentalBlock}>
                                <div className={styles.sectionHeader}>
                                  <div className={styles.sectionIdentity}>
                                    <p className={styles.blockEyebrow}>{t("mentalState")}</p>
                                    <p className={styles.sectionMetaLine}>
                                      {memberUpdated || (lang === "zh" ? "尚未更新" : "Not updated yet")}
                                    </p>
                                  </div>
                                  <span className={styles.mentalStateBadge}>{memberMentalState}</span>
                                </div>
                                <p className={styles.contextLineCompact}>{memberMentalSummary}</p>
                              </div>
                              <p className={styles.featurePresetNote}>
                                {lang === "zh"
                                  ? "群聊成员由群聊调度驱动；需要单独调整下一轮功能时，请打开该 Agent 的单聊。"
                                  : "Group members are driven by group scheduling. Open the direct chat to tune next-turn features."}
                              </p>
                            </>
                          )}
                        </div>
                      ) : null}
                    </article>
                  );
                })}
              </div>
            </section>
          ) : (
            <>
            <div className={styles.sessionActionRow}>
              <button
                type="button"
                className={styles.newSessionButton}
                onClick={handleCreateSession}
                disabled={createSessionMutation.isPending}
              >
                <Plus size={15} />
                <span>{createSessionMutation.isPending ? t("creatingSession") : t("newSession")}</span>
              </button>
              <button
                type="button"
                className={styles.newGroupButton}
                onClick={handleOpenProjectAgentBus}
                aria-current={groupPanelActive ? "true" : undefined}
              >
                <UsersRound size={15} />
                <span>{lang === "zh" ? "项目总群" : "Project bus"}</span>
              </button>
              <button
                type="button"
                className={styles.newGroupButton}
                onClick={handleToggleGroupComposer}
                aria-expanded={groupComposerOpen}
                disabled={createGroupRoomMutation.isPending}
              >
                <UsersRound size={15} />
                <span>{groupComposerOpen ? (lang === "zh" ? "收起" : "Close") : (lang === "zh" ? "新建群聊" : "New group")}</span>
              </button>
            </div>
            {groupComposerOpen ? (
              <section className={styles.groupComposerPanel} aria-label={lang === "zh" ? "新建群聊" : "New group chat"}>
                <label className={styles.groupComposerField}>
                  <span>{lang === "zh" ? "群名" : "Name"}</span>
                  <input
                    className={styles.groupComposerInput}
                    value={groupTitleDraft}
                    maxLength={80}
                    onChange={(event) => setGroupTitleDraft(event.target.value)}
                  />
                </label>
                <label className={styles.groupComposerField}>
                  <span>{lang === "zh" ? "调度模式" : "Mode"}</span>
                  <select
                    className={styles.groupComposerInput}
                    value={groupModeDraft}
                    onChange={(event) => setGroupModeDraft(event.target.value)}
                    disabled={chatRoomModesQuery.isPending || createGroupRoomMutation.isPending}
                  >
                    {readyChatRoomModes.map((mode) => (
                      <option key={mode.id} value={mode.id}>
                        {chatRoomModeLabel(mode, lang)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className={styles.groupComposerField}>
                  <span>{lang === "zh" ? "对话目的" : "Purpose"}</span>
                  <select
                    className={styles.groupComposerInput}
                    value={groupPurposeDraft}
                    onChange={(event) => setGroupPurposeDraft(event.target.value)}
                    disabled={chatRoomPurposesQuery.isPending || createGroupRoomMutation.isPending}
                  >
                    {availableChatRoomPurposes.map((purpose) => (
                      <option key={purpose.id} value={purpose.id}>
                        {chatRoomPurposeLabel(purpose, lang)}
                      </option>
                    ))}
                  </select>
                </label>
                <div className={styles.groupAgentPicker} aria-label={lang === "zh" ? "选择参与 Agent" : "Choose agents"}>
                  {agentsQuery.isPending ? (
                    <p className={styles.groupComposerEmpty}>{lang === "zh" ? "正在读取 Agent..." : "Loading agents..."}</p>
                  ) : groupCandidateAgents.length ? (
                    groupCandidateAgents.map((agent) => {
                      const selected = groupSelectedAgentIds.includes(agent.agentId);
                      const display = agentDisplayInfo(agent, lang);
                      return (
                        <label key={agent.agentId} className={selected ? `${styles.groupAgentOption} ${styles.groupAgentOptionSelected}` : styles.groupAgentOption}>
                          <input
                            type="checkbox"
                            checked={selected}
                            disabled={createGroupRoomMutation.isPending}
                            onChange={() => handleToggleGroupAgent(agent.agentId)}
                          />
                          <span>
                            <strong>{display.name}</strong>
                            <small className={`${styles.agentRoleTag} ${styles[agentRoleClass(display.tone)]}`}>
                              {display.functionLabel}
                            </small>
                          </span>
                        </label>
                      );
                    })
                  ) : (
                    <p className={styles.groupComposerEmpty}>{lang === "zh" ? "暂无可加入群聊的持久 Agent。" : "No persistent agents are available."}</p>
                  )}
                </div>
                <button
                  type="button"
                  className={styles.createGroupButton}
                  onClick={handleCreateGroupRoom}
                  disabled={createGroupRoomMutation.isPending || groupSelectedAgentIds.length < 2 || !groupTitleDraft.trim()}
                >
                  <UsersRound size={15} />
                  <span>{createGroupRoomMutation.isPending ? (lang === "zh" ? "创建中" : "Creating") : (lang === "zh" ? "创建群聊" : "Create group")}</span>
                </button>
              </section>
            ) : null}
            {sessionComposerErrors.__sessions__ ? (
              <div className={styles.panelState}>{sessionComposerErrors.__sessions__}</div>
            ) : null}
            {detail && !groupPanelActive ? (
              <section className={styles.agentTemplatePanel} aria-label={lang === "zh" ? "会话 Agent 配置" : "Session agent config"}>
                <div className={styles.agentTemplateHeader}>
                  <Bot size={15} />
                  <div>
                    <strong>{lang === "zh" ? "会话 Agent" : "Session agent"}</strong>
                    <span>
                      {agentTemplateSavePending
                        ? (lang === "zh" ? "保存中" : "Saving")
                        : activeAgentMetaLabel}
                    </span>
                  </div>
                </div>
                <select
                  className={styles.agentTemplateSelect}
                  value={activeAgentId}
                  disabled={agentsQuery.isPending || updateSessionAgentMutation.isPending || sessionBusy}
                  onChange={(event) => handleAgentTemplateChange(event.target.value)}
                  aria-label={lang === "zh" ? "选择当前会话绑定的 Agent" : "Choose the Agent bound to this session"}
                >
                  {sessionAgentOptions.length ? (
                    sessionAgentOptions.map((agent) => {
                      const display = agentDisplayInfo(agent, lang);
                      return (
                        <option key={agent.agentId} value={agent.agentId}>
                          {display.name} · {display.functionLabel}
                        </option>
                      );
                    })
                  ) : (
                    <option value={activeAgentId}>
                      {activeAgentDisplayName ?? activeAgentId} · {activeAgentFunctionLabel}
                    </option>
                  )}
                </select>
                <p className={styles.agentTemplateMeta}>
                  {activeSessionAgent
                    ? `${activeSessionAgent.primaryMode || "chat"} · ${activeSessionAgent.roleKey || (lang === "zh" ? "通用会话" : "general chat")} · ${activeSessionAgent.profileId || "primary"}`
                    : lang === "zh" ? "使用当前保存的会话 Agent 配置。" : "Using the saved session Agent config."}
                </p>
              </section>
            ) : null}
            {sessionsErrorState.transientError ? (
              <div className={styles.panelNotice} role="status">{sessionsErrorMessage}</div>
            ) : null}
            {sessionsErrorState.blockingError ? (
              <div className={styles.panelState}>{sessionsErrorMessage}</div>
            ) : conversationsQuery.isPending && !conversationsQuery.data && sessionsQuery.isPending && !sessionsQuery.data ? (
              <div className={styles.panelState}>{t("loadingSession")}</div>
            ) : filteredConversations.length === 0 ? (
              <div className={styles.panelState}>
                {sessionFilter.trim() ? t("noSessionMatches") : t("noSessionsYet")}
              </div>
            ) : (
              groupedConversations.map((group) => {
                const collapsed = !searchHasTerm && collapsedConversationGroups[group.groupKey];
                return (
                  <section key={group.groupKey} className={styles.conversationGroup}>
                    <button
                      type="button"
                      className={styles.conversationGroupHeader}
                      onClick={() => toggleConversationGroup(group.groupKey)}
                      aria-expanded={!collapsed}
                    >
                      <ChevronRight size={14} aria-hidden="true" />
                      <span>{group.label}</span>
                      <strong>{group.items.length}</strong>
                    </button>
                    {!collapsed ? (
                      <div className={styles.conversationGroupList}>
                        {group.items.map((conversation) => {
                if (conversation.type === "group_room") {
                  const roomId = conversation.roomId || conversation.conversationId;
                  return (
                    <div
                      key={`group-${roomId}`}
                      aria-current={activeGroupRoomId === roomId ? "true" : undefined}
                      className={
                        activeGroupRoomId === roomId
                          ? `${styles.sessionItem} ${styles.groupSessionItem} ${styles.sessionItemActive}`
                          : `${styles.sessionItem} ${styles.groupSessionItem}`
                      }
                    >
                      <button
                        type="button"
                        className={styles.sessionItemMain}
                        onClick={() => handleOpenGroupRoom(roomId)}
                      >
                        <span className={`${styles.conversationAvatar} ${styles.conversationAvatarGroup}`} aria-hidden="true">
                          <UsersRound size={18} />
                        </span>
                        <span className={styles.conversationCopy}>
                          <span className={styles.conversationTitleRow}>
                            <span className={styles.sessionItemTitle}>{conversation.title}</span>
                            <span className={styles.sessionState}>{statusLabel(conversation.status)}</span>
                          </span>
                          <span className={styles.sessionItemSummary} title={conversation.summary}>
                            {conversation.summary || (lang === "zh" ? "群聊会话" : "Group conversation")}
                          </span>
                          <span className={styles.conversationMetaRow}>
                            <span className={`${styles.conversationKindBadge} ${styles.conversationKindBadgeGroup}`}>
                              {lang === "zh" ? "群聊" : "Group"}
                            </span>
                            <span>{lang === "zh" ? "成员" : "Members"} · {conversation.participantCount ?? 0}</span>
                            <time>{formatTime(conversation.updatedAt)}</time>
                          </span>
                        </span>
                      </button>
                    </div>
                  );
                }
                const sessionId = conversation.directSessionId || conversation.conversationId;
  const session: SessionSummary = sessionsById.get(sessionId) ?? {
                  id: sessionId,
                  title: conversation.title,
                  agentId: conversation.agentId,
                  agentCode: conversation.agentCode,
                  agentProfileId: conversation.agentProfileId,
                  agentTemplateLabel: conversation.agentTemplateLabel,
                  agentPrimaryMode: conversation.agentPrimaryMode,
                  agentRoleKey: conversation.agentRoleKey,
                  agentPromptTemplateId: conversation.agentPromptTemplateId,
                  agentDisplayName: conversation.agentDisplayName,
                  workspacePath: conversation.workspacePath,
                  status: conversation.status,
                  taskSummary: conversation.summary,
                  lastActive: conversation.updatedAt,
                  updatedAt: conversation.updatedAt,
                  currentPhase: conversation.status,
                };
                const sessionIsBusy = isBusyPhase(session.currentPhase || session.status);
                const deletePending =
                  deleteSessionMutation.isPending &&
                  deleteSessionMutation.variables?.sessionId === session.id;
                const deleteDisabled = deletePending || sessionIsBusy;
                const addToReviewPending =
                  addSessionToReviewMutation.isPending &&
                  addSessionToReviewMutation.variables?.sessionId === session.id;
                const addToReviewDisabled = addToReviewPending || sessionIsBusy;
                const renamePending =
                  renameSessionMutation.isPending &&
                  renameSessionMutation.variables?.sessionId === session.id;
                const isEditingTitle = editingSessionId === session.id;
                const itemError = sessionComposerErrors[session.id] ?? "";
                const deleteBusyReason = sessionIsBusy ? t("deleteSessionBusy") : "";
                const itemMessage = itemError || deleteBusyReason;
                const itemIsNotice = itemError
                  ? itemError.startsWith(t("addSessionToReviewSucceeded"))
                  : Boolean(deleteBusyReason);
                const sessionAgent = session.agentId ? agentsById.get(session.agentId) : undefined;
                const sessionDisplay = sessionAgentDisplayInfo(session, sessionAgent, lang);
                const sessionAgentName =
                  sessionDisplay.name && sessionDisplay.name !== session.title ? sessionDisplay.name : "";
                const missingAgentMessage = session.agentMissing
                  ? session.agentStatusMessage || (lang === "zh" ? "缺少有效 Agent，当前会话缺少可运行内容。" : "Missing valid Agent. This session has no runnable Agent content.")
                  : "";
                return (
                  <div
                    key={session.id}
                    aria-current={!groupPanelActive && activeSessionId === session.id ? "true" : undefined}
                    className={
                      !groupPanelActive && activeSessionId === session.id
                        ? `${styles.sessionItem} ${styles.directSessionItem} ${styles.sessionItemActive}`
                        : `${styles.sessionItem} ${styles.directSessionItem}`
                    }
                  >
                    {isEditingTitle ? (
                      <div className={styles.sessionItemMain}>
                        <span className={`${styles.conversationAvatar} ${styles.conversationAvatarDirect}`} aria-hidden="true">
                          {avatarInitials(session.agentCode, session.agentDisplayName || session.title)}
                        </span>
                        <span className={styles.conversationCopy}>
                          <span className={styles.conversationTitleRow}>
                            <input
                              className={styles.sessionTitleInput}
                              value={editingSessionTitle}
                              maxLength={120}
                              autoFocus
                              onChange={(event) => setEditingSessionTitle(event.target.value)}
                              onKeyDown={(event) => {
                                if (event.key === "Enter") {
                                  event.preventDefault();
                                  submitRenameSession(session);
                                }
                                if (event.key === "Escape") {
                                  event.preventDefault();
                                  cancelRenameSession();
                                }
                              }}
                              aria-label={t("renameSession")}
                            />
                            {!groupPanelActive && activeSessionId === session.id ? (
                              <span className={styles.sessionCurrentBadge}>{t("currentSession")}</span>
                            ) : null}
                            <span className={styles.sessionState}>{statusLabel(session.status)}</span>
                          </span>
                          <span className={styles.sessionItemSummary} title={session.taskSummary}>
                            {session.taskSummary || (lang === "zh" ? "暂无摘要" : "No summary yet")}
                          </span>
                          <span className={styles.conversationMetaRow}>
                            <span className={`${styles.conversationKindBadge} ${styles.conversationKindBadgeDirect}`}>
                              {lang === "zh" ? "会话" : "Chat"}
                            </span>
                            {sessionAgentName ? <span>{sessionAgentName}</span> : null}
                            <span className={`${styles.agentRoleTag} ${styles[agentRoleClass(sessionDisplay.tone)]}`}>
                              {sessionDisplay.functionLabel}
                            </span>
                            <time>{formatTime(session.updatedAt || session.lastActive)}</time>
                          </span>
                          {missingAgentMessage ? (
                            <span className={styles.agentMissingLine}>{missingAgentMessage}</span>
                          ) : null}
                        </span>
                      </div>
                    ) : (
                      <button
                        type="button"
                        className={styles.sessionItemMain}
                        onClick={() => handleOpenDirectSession(session.id)}
                        aria-current={!groupPanelActive && activeSessionId === session.id ? "true" : undefined}
                      >
                        <span className={`${styles.conversationAvatar} ${styles.conversationAvatarDirect}`} aria-hidden="true">
                          {avatarInitials(session.agentCode, session.agentDisplayName || session.title)}
                        </span>
                        <span className={styles.conversationCopy}>
                          <span className={styles.conversationTitleRow}>
                            <span className={styles.sessionItemTitle}>
                              {session.title || sessionDisplay.name}
                            </span>
                            {!groupPanelActive && activeSessionId === session.id ? (
                              <span className={styles.sessionCurrentBadge}>{t("currentSession")}</span>
                            ) : null}
                            <span className={styles.sessionState}>{statusLabel(session.status)}</span>
                          </span>
                          <span className={styles.sessionItemSummary} title={session.taskSummary}>
                            {session.taskSummary || (lang === "zh" ? "暂无摘要" : "No summary yet")}
                          </span>
                          <span className={styles.conversationMetaRow}>
                            <span className={`${styles.conversationKindBadge} ${styles.conversationKindBadgeDirect}`}>
                              {lang === "zh" ? "会话" : "Chat"}
                            </span>
                            {sessionAgentName ? <span>{sessionAgentName}</span> : null}
                            <span className={`${styles.agentRoleTag} ${styles[agentRoleClass(sessionDisplay.tone)]}`}>
                              {sessionDisplay.functionLabel}
                            </span>
                            <time>{formatTime(session.updatedAt || session.lastActive)}</time>
                          </span>
                          {missingAgentMessage ? (
                            <span className={styles.agentMissingLine}>{missingAgentMessage}</span>
                          ) : null}
                        </span>
                      </button>
                    )}
                    {isEditingTitle ? (
                      <div className={styles.sessionActionStack}>
                        <button
                          type="button"
                          className={styles.sessionIconButton}
                          onClick={() => submitRenameSession(session)}
                          disabled={renamePending}
                          title={t("saveSessionName")}
                          aria-label={`${t("saveSessionName")} ${session.title}`}
                        >
                          <Check size={15} />
                        </button>
                        <button
                          type="button"
                          className={styles.sessionIconButton}
                          onClick={cancelRenameSession}
                          disabled={renamePending}
                          title={t("cancelRenameSession")}
                          aria-label={t("cancelRenameSession")}
                        >
                          <X size={15} />
                        </button>
                      </div>
                    ) : (
                      <div className={styles.sessionActionStack}>
                        <button
                          type="button"
                          className={styles.sessionIconButton}
                          onClick={() => handleAddSessionToReview(session)}
                          disabled={addToReviewDisabled}
                          title={
                            addToReviewPending
                              ? t("addingSessionToReview")
                              : addToReviewDisabled
                                ? t("addSessionToReviewBusy")
                                : t("addSessionToReview")
                          }
                          aria-label={`${t("addSessionToReview")} ${session.title}`}
                        >
                          <BookPlus size={15} />
                        </button>
                        <button
                          type="button"
                          className={styles.sessionIconButton}
                          onClick={() => beginRenameSession(session)}
                          title={t("renameSession")}
                          aria-label={`${t("renameSession")} ${session.title}`}
                        >
                          <Pencil size={15} />
                        </button>
                        <button
                          type="button"
                          className={styles.sessionDeleteButton}
                          onClick={() => handleDeleteSession(session)}
                          disabled={deleteDisabled}
                          title={deleteDisabled ? t("deleteSessionBusy") : t("deleteSession")}
                          aria-label={`${t("deleteSession")} ${session.title}`}
                        >
                          <Trash2 size={15} />
                        </button>
                      </div>
                    )}
                    {itemMessage ? (
                      <p className={itemIsNotice ? styles.sessionItemNotice : styles.sessionItemError}>
                        {itemMessage}
                      </p>
                    ) : null}
                  </div>
                );
              })}
                      </div>
                    ) : null}
                  </section>
                );
              })
            )}
            </>
          )}
        </div>
      </aside>
    </div>
  );
}
