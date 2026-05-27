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
import { queryKeys } from "../api/queryKeys";
import {
  AgentInstance,
  ChatRoomDetail,
  ChatRoomMode,
  FileContent,
  FileTreeNode,
  PetActionResponse,
  PetSummary,
  RuntimeSummary,
  SessionAgentTemplate,
  SessionChatReviewCandidateResponse,
  ConversationSummary,
  SessionDetail,
  SessionSummary,
  SessionStreamEvent,
  ConversationMessage,
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
import styles from "./ChatCodingRoute.module.css";

function encodeUtf8Base64(value: string): string {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary);
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
const CHAT_CENTER_FIRST_MEDIA_QUERY = "(max-width: 980px)";

type ResizableSide = "left" | "right";
type PetInteractionAction = "feed" | "talk" | "care";
type FeaturePresetKey = "planningMode" | "goalMode" | "toolBoost";

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

function filterTree(nodes: FileTreeNode[], query: string): FileTreeNode[] {
  const term = query.trim().toLowerCase();
  if (!term) {
    return nodes;
  }
  return nodes.flatMap((node) => {
    const matches = node.name.toLowerCase().includes(term) || node.path.toLowerCase().includes(term);
    if (node.type === "directory") {
      const filteredChildren = filterTree(node.children ?? [], query);
      if (matches) {
        return [{ ...node, children: node.children ?? [] }];
      }
      if (filteredChildren.length > 0) {
        return [{ ...node, children: filteredChildren }];
      }
      return [];
    }
    return matches ? [node] : [];
  });
}

function renderTree(
  nodes: FileTreeNode[],
  onOpenFile: (path: string) => void,
  changedFiles: Set<string>,
  activeFilePath: string | null,
  changedLabel: string,
) {
  return nodes.map((node) => {
    if (node.type === "directory") {
      return (
        <details key={node.path} className={styles.treeDir} open>
          <summary>{node.name}</summary>
          <div className={styles.treeChildren}>
            {renderTree(node.children ?? [], onOpenFile, changedFiles, activeFilePath, changedLabel)}
          </div>
        </details>
      );
    }

    const isActive = activeFilePath === node.path;
    const isChanged = changedFiles.has(node.path);
    return (
      <button
        key={node.path}
        type="button"
        className={isActive ? `${styles.treeFile} ${styles.treeFileActive}` : styles.treeFile}
        onClick={() => onOpenFile(node.path)}
      >
        <span>{node.name}</span>
        {isChanged ? <span className={styles.treeChanged}>{changedLabel}</span> : null}
      </button>
    );
  });
}

function describeError(error: unknown, fallback: string) {
  if (error instanceof Error && error.message) {
    return `${fallback}: ${error.message}`;
  }
  return fallback;
}

function isRunningPhase(value: string | null | undefined) {
  const phase = String(value ?? "").trim().toLowerCase();
  return ["running", "thinking", "tooling", "answering", "planning", "reading", "editing", "verifying"].includes(phase);
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

function sessionToConversationSummary(session: SessionSummary): ConversationSummary {
  return {
    conversationId: session.id,
    type: "direct_agent",
    title: session.agentDisplayName || session.title,
    agentId: session.agentId,
    directSessionId: session.id,
    roomId: "",
    status: session.status,
    summary: session.taskSummary,
    updatedAt: session.updatedAt || session.lastActive,
    workspacePath: session.agentWorkspacePath || session.workspacePath || "",
    agentProfileId: session.agentProfileId,
    agentTemplateLabel: session.agentTemplateLabel,
  };
}

function latestChatRoomRound(room: ChatRoomDetail | null | undefined) {
  const rounds = room?.rounds ?? [];
  return rounds.length ? rounds[rounds.length - 1] : null;
}

export function ChatCodingRoute() {
  const { lang, t, statusLabel } = useAppI18n();
  const queryClient = useQueryClient();
  const location = useLocation();
  const rightPanel = useShellStore((state) => state.rightPanel);
  const setRightPanel = useShellStore((state) => state.setRightPanel);
  const chatPanelWidths = useShellStore((state) => state.chatPanelWidths);
  const setChatPanelWidths = useShellStore((state) => state.setChatPanelWidths);
  const activeSessionId = useChatWorkbenchStore((state) => state.activeSessionId);
  const sessionWorkspaces = useChatWorkbenchStore((state) => state.sessionWorkspaces);
  const setActiveSession = useChatWorkbenchStore((state) => state.setActiveSession);
  const hydrateSession = useChatWorkbenchStore((state) => state.hydrateSession);
  const removeSessionWorkspace = useChatWorkbenchStore((state) => state.removeSession);
  const openPreviewTab = useChatWorkbenchStore((state) => state.openPreviewTab);
  const closePreviewTab = useChatWorkbenchStore((state) => state.closePreviewTab);
  const setActiveTab = useChatWorkbenchStore((state) => state.setActiveTab);
  const [sessionFilter, setSessionFilter] = useState("");
  const [fileFilter, setFileFilter] = useState("");
  const [dragState, setDragState] = useState<DragState | null>(null);
  const [leftRailCollapsed, setLeftRailCollapsed] = useState(false);
  const [rightPaneCollapsed, setRightPaneCollapsed] = useState(false);
  const [centerFirstLayout, setCenterFirstLayout] = useState(false);
  const centerFirstAutoCollapseRef = useRef(false);
  const [sessionDrafts, setSessionDrafts] = useState<Record<string, string>>({});
  const [sessionComposerErrors, setSessionComposerErrors] = useState<Record<string, string>>({});
  const [sessionEditTargets, setSessionEditTargets] = useState<Record<string, { messageId: string; original: string }>>({});
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingSessionTitle, setEditingSessionTitle] = useState("");
  const [sessionStreamConnected, setSessionStreamConnected] = useState(false);
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
  const [groupSelectedAgentIds, setGroupSelectedAgentIds] = useState<string[]>([]);
  const [activeGroupRoomId, setActiveGroupRoomId] = useState("");
  const [groupTopicDraft, setGroupTopicDraft] = useState("");
  const [groupRoomActionError, setGroupRoomActionError] = useState("");
  const [groupManageSessionIds, setGroupManageSessionIds] = useState<string[]>([]);
  const [groupManageModeDraft, setGroupManageModeDraft] = useState("round_robin");
  const layoutRef = useRef<HTMLDivElement | null>(null);
  const sessionStreamErrorLoggedRef = useRef<Record<string, boolean>>({});
  const sessionStreamPayloadErrorLoggedRef = useRef<Record<string, boolean>>({});
  const requestedSessionId = useMemo(() => {
    return new URLSearchParams(location.search).get("session") ?? "";
  }, [location.search]);
  const pageVisible = usePageVisibility();

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
    queryFn: () => fetchJson<SessionSummary[]>("/api/sessions"),
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
    enabled: groupComposerOpen,
  });
  const chatRoomModesQuery = useQuery({
    queryKey: queryKeys.chatRoomModes(),
    queryFn: () => fetchJson<ChatRoomMode[]>("/api/chat-rooms/modes"),
    enabled: groupComposerOpen || Boolean(activeGroupRoomId),
  });
  const activeGroupRoomQuery = useQuery({
    queryKey: queryKeys.chatRoom(activeGroupRoomId || "none"),
    queryFn: () => fetchJson<ChatRoomDetail>(`/api/chat-rooms/${activeGroupRoomId}`),
    enabled: Boolean(activeGroupRoomId),
    refetchInterval: activeGroupRoomId ? resolvePollingInterval(pageVisible, 3_000) : false,
    refetchIntervalInBackground: false,
  });
  const sessionAgentTemplatesQuery = useQuery({
    queryKey: queryKeys.sessionAgentTemplates(),
    queryFn: () => fetchJson<SessionAgentTemplate[]>("/api/sessions/agent-templates"),
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
  const fileTreeQuery = useQuery({
    queryKey: queryKeys.fileTree(),
    queryFn: () => fetchJson<FileTreeNode[]>("/api/files/tree"),
    refetchInterval: resolvePollingInterval(pageVisible, 10_000),
    refetchIntervalInBackground: false,
  });

  useEffect(() => {
    if (
      requestedSessionId
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
  }, [activeSessionId, requestedSessionId, sessionsQuery.data, setActiveSession]);

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
      }: {
        sessionId: string;
        content: string;
        mentalModelEnabled: boolean;
      },
    ) =>
      fetchJson<SessionDetail>(`/api/sessions/${sessionId}/messages`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ content, contentUtf8Base64: encodeUtf8Base64(content), mentalModelEnabled }),
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
      }: {
        sessionId: string;
        messageId: string;
        content: string;
        mentalModelEnabled: boolean;
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
    mutationFn: async ({ title, agentIds, mode }: { title: string; agentIds: string[]; mode: string }) =>
      fetchJson<ChatRoomDetail>("/api/chat-rooms", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ title, agentIds, mode }),
      }),
    onSuccess: (room) => {
      setGroupComposerOpen(false);
      setGroupTitleDraft("");
      setGroupModeDraft("round_robin");
      setGroupSelectedAgentIds([]);
      setSessionFilter("");
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: "",
      }));
      setActiveGroupRoomId(room.roomId);
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
    mutationFn: async ({ roomId, topic, mode }: { roomId: string; topic: string; mode: string }) =>
      fetchJson<ChatRoomDetail>(`/api/chat-rooms/${roomId}/rounds`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ topic, mode }),
      }),
    onSuccess: (room) => {
      setActiveGroupRoomId(room.roomId);
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

  const updateGroupRoomMutation = useMutation({
    mutationFn: async ({ roomId, sessionIds, mode }: { roomId: string; sessionIds: string[]; mode: string }) =>
      fetchJson<ChatRoomDetail>(`/api/chat-rooms/${roomId}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          participantSessionIds: sessionIds,
          mode,
        }),
      }),
    onSuccess: (room) => {
      setActiveGroupRoomId(room.roomId);
      setGroupManageSessionIds(room.participants.map((participant) => participant.sessionId));
      setGroupManageModeDraft(room.mode || "round_robin");
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
      setGroupTopicDraft("");
      setGroupRoomActionError("");
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
      setSessionComposerErrors((current) => {
        const { [variables.sessionId]: _removed, ...remaining } = current;
        return {
          ...remaining,
          [nextDetail.id]: "",
        };
      });
      queryClient.removeQueries({ queryKey: queryKeys.session(variables.sessionId), exact: true });
      syncSessionDetail(nextDetail);
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
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
    mutationFn: async ({ sessionId, agentProfileId }: { sessionId: string; agentProfileId: string }) =>
      fetchJson<SessionDetail>(`/api/sessions/${sessionId}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ agentProfileId }),
      }),
    onSuccess: (nextDetail, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      syncSessionDetail(nextDetail);
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.conversations() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessionAgentTemplates() });
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
    setGroupManageSessionIds(activeGroupRoom.participants.map((participant) => participant.sessionId));
    setGroupManageModeDraft(activeGroupRoom.mode || "round_robin");
  }, [activeGroupRoom]);

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
      disposed = true;
      setSessionStreamConnected(false);
      stream.removeEventListener("session_detail", handleSessionDetail as EventListener);
      stream.close();
    };
  }, [activeSessionId, pageVisible, syncSessionDetail]);

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
  const activeGroupRound = latestChatRoomRound(activeGroupRoom);
  const groupPanelActive = Boolean(activeGroupRoomId);
  const groupRoundRunning = String(activeGroupRoom?.status ?? "").trim().toLowerCase() === "running";
  const groupManageSessionSet = useMemo(() => new Set(groupManageSessionIds), [groupManageSessionIds]);
  const activeGroupParticipantSessionSet = useMemo(
    () => new Set((activeGroupRoom?.participants ?? []).map((participant) => participant.sessionId)),
    [activeGroupRoom?.participants],
  );
  const groupManageChanged = Boolean(
    activeGroupRoom
    && (
      groupManageModeDraft !== (activeGroupRoom.mode || "round_robin")
      || groupManageSessionIds.length !== activeGroupParticipantSessionSet.size
      || groupManageSessionIds.some((sessionId) => !activeGroupParticipantSessionSet.has(sessionId))
    ),
  );
  const groupManageDisabled =
    !activeGroupRoom
    || groupRoundRunning
    || updateGroupRoomMutation.isPending
    || groupManageSessionIds.length === 0
    || !groupManageModeDraft;
  const groupDeleteDisabled =
    !activeGroupRoom
    || groupRoundRunning
    || deleteGroupRoomMutation.isPending;
  const activeSurfaceTitle = groupPanelActive
    ? activeGroupRoom?.title ?? (lang === "zh" ? "群聊加载中" : "Loading group")
    : detail?.title ?? runtime?.sessionTitle ?? t("loadingSession");
  const activeSurfaceStatus = groupPanelActive
    ? statusLabel(activeGroupRoom?.status ?? "ready")
    : statusLabel(detail?.status || detail?.currentPhase || "idle");
  const activeSurfaceLine = groupPanelActive
    ? (
      activeGroupRound?.summary
      || `${activeGroupRoom?.participants?.length ?? 0} ${lang === "zh" ? "位 Agent" : "agents"} · ${activeGroupRoom?.mode ?? "round_robin"}`
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
  const sessionAgentTemplates = sessionAgentTemplatesQuery.data ?? [];
  const activeAgentProfileId = detail?.agentProfileId || detail?.agentTemplateId || "primary";
  const activeAgentTemplate = sessionAgentTemplates.find((template) => template.profileId === activeAgentProfileId);
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
    || (editResubmitMutation.isPending && editResubmitMutationMatchesActiveSession);
  const sessionRunning = isRunningPhase(detail?.currentPhase);
  const sessionStopping = isStoppingPhase(detail?.currentPhase) || Boolean(detail?.stopRequested);
  const sessionBusy = isBusyPhase(detail?.currentPhase);
  const composerStopMode = sessionBusy;
  const composerPending =
    composerStopMode ? (stopTurnMutation.isPending && stopMutationMatchesActiveSession) || sessionStopping : submitPending;
  const composerDisabled = !activeSessionId || submitPending || sessionBusy;
  const composerActionDisabled = !activeSessionId || (
    composerStopMode ? composerPending : submitPending || !activeDraftEffective.trim()
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
        : detail?.taskSummary || t("preparingShell"));
  const activeTask = detail?.activeTask ?? null;
  const sessionStateValue = String(groupPanelActive ? activeGroupRoom?.status ?? "ready" : runtime?.sessionState ?? detail?.currentPhase ?? "idle")
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

  const sessionsById = useMemo(() => {
    return new Map((sessionsQuery.data ?? []).map((session) => [session.id, session]));
  }, [sessionsQuery.data]);

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

  const filteredConversations = useMemo(() => {
    const term = sessionFilter.trim().toLowerCase();
    const conversations = conversationsQuery.data ?? (sessionsQuery.data ?? []).map(sessionToConversationSummary);
    if (!term) {
      return conversations;
    }
    return conversations.filter((conversation) =>
      [conversation.title, conversation.summary, conversation.status, conversation.type, conversation.agentTemplateLabel ?? ""].some((value) =>
        String(value ?? "").toLowerCase().includes(term),
      ),
    );
  }, [conversationsQuery.data, sessionFilter, sessionsQuery.data]);

  const filteredTree = useMemo(
    () => filterTree(fileTreeQuery.data ?? [], fileFilter),
    [fileFilter, fileTreeQuery.data],
  );

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

  function handleOpenFile(path: string) {
    if (!activeSessionId) {
      return;
    }
    openPreviewTab(activeSessionId, path);
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

  function handleSubmitTurn() {
    if (!activeSessionId) {
      return;
    }
    const content = activeDraftEffective.trim();
    if (!content || composerDisabled) {
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
    submitTurnMutation.mutate({
      sessionId: activeSessionId,
      content,
      mentalModelEnabled: mentalModelEnabledForNextTurn,
    });
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
    setSessionComposerErrors((current) => ({
      ...current,
      __sessions__: "",
    }));
    createSessionMutation.mutate();
  }

  function handleOpenDirectSession(sessionId: string) {
    setActiveGroupRoomId("");
    setGroupRoomActionError("");
    setActiveSession(sessionId);
  }

  function handleOpenGroupRoom(roomId: string) {
    if (!roomId) {
      return;
    }
    setActiveGroupRoomId(roomId);
    setGroupRoomActionError("");
    void queryClient.invalidateQueries({ queryKey: queryKeys.chatRoom(roomId) });
  }

  function handleToggleGroupManageSession(sessionId: string) {
    if (!sessionId || groupRoundRunning || updateGroupRoomMutation.isPending) {
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
    });
  }

  function handleStartGroupRound() {
    const topic = groupTopicDraft.trim();
    if (!activeGroupRoomId || !topic || startGroupRoundMutation.isPending || groupRoundRunning) {
      return;
    }
    startGroupRoundMutation.mutate({
      roomId: activeGroupRoomId,
      topic,
      mode: activeGroupRoom?.mode || "round_robin",
    });
  }

  function handleApplyGroupRoomManagement() {
    if (!activeGroupRoomId || groupManageDisabled) {
      return;
    }
    updateGroupRoomMutation.mutate({
      roomId: activeGroupRoomId,
      sessionIds: groupManageSessionIds,
      mode: groupManageModeDraft || "round_robin",
    });
  }

  function handleDeleteActiveGroupRoom() {
    if (!activeGroupRoomId || groupDeleteDisabled) {
      return;
    }
    deleteGroupRoomMutation.mutate({ roomId: activeGroupRoomId });
  }

  function handleDeleteSession(session: SessionSummary) {
    if (isBusyPhase(session.currentPhase || session.status)) {
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

  function handleAgentTemplateChange(agentProfileId: string) {
    if (!activeSessionId || !agentProfileId || agentProfileId === activeAgentProfileId) {
      return;
    }
    setSessionComposerErrors((current) => ({
      ...current,
      [activeSessionId]: "",
      __sessions__: "",
    }));
    updateSessionAgentMutation.mutate({ sessionId: activeSessionId, agentProfileId });
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
            {groupPanelActive ? (lang === "zh" ? "群聊" : "Group") : t("agentSession")}
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
          {groupPanelActive ? (
            <div className={styles.groupConversationFrame}>
              <header className={styles.groupConversationHeader}>
                <div>
                  <p>{activeGroupRoom?.mode ?? "round_robin"}</p>
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
              {groupRoomActionError ? (
                <div className={styles.inlineNotice}>{groupRoomActionError}</div>
              ) : null}
              <section className={styles.groupManagementPanel} aria-label={lang === "zh" ? "群聊管理" : "Group management"}>
                <div className={styles.groupManagementHeader}>
                  <div>
                    <strong>{lang === "zh" ? "群聊管理" : "Group management"}</strong>
                    <span>
                      {groupManageSessionIds.length}/{sessionsQuery.data?.length ?? 0}
                      {" "}
                      {lang === "zh" ? "位 Agent 已选择" : "agents selected"}
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
                <div className={styles.groupManagementControls}>
                  <label className={styles.groupModeSelect}>
                    <span>{lang === "zh" ? "调度模式" : "Mode"}</span>
                    <select
                      value={groupManageModeDraft}
                      disabled={groupRoundRunning || updateGroupRoomMutation.isPending}
                      onChange={(event) => {
                        setGroupRoomActionError("");
                        setGroupManageModeDraft(event.target.value);
                      }}
                    >
                      {readyChatRoomModes.map((mode) => (
                        <option key={mode.id} value={mode.id}>
                          {mode.label || mode.id}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className={styles.groupMemberPicker}>
                    {(sessionsQuery.data ?? []).map((session) => {
                      const selected = groupManageSessionSet.has(session.id);
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
                            disabled={groupRoundRunning || updateGroupRoomMutation.isPending}
                            onChange={() => handleToggleGroupManageSession(session.id)}
                          />
                          <span>{session.title}</span>
                        </label>
                      );
                    })}
                  </div>
                </div>
                {groupRoundRunning ? (
                  <p className={styles.groupManagementHint}>
                    {lang === "zh" ? "群聊运行中，成员和模式会在本轮结束后允许修改。" : "The group is running. Members and mode can be changed after this round finishes."}
                  </p>
                ) : null}
              </section>
              <div className={styles.groupMessageTimeline}>
                {(activeGroupRoom?.rounds ?? []).length ? (
                  (activeGroupRoom?.rounds ?? []).map((round) => (
                    <section key={round.roundId} className={styles.groupRoundBlock}>
                      <header>
                        <div>
                          <strong>{round.topic}</strong>
                          <span>{round.mode} · {statusLabel(round.status)}</span>
                        </div>
                        <time>{formatTime(round.updatedAt || round.startedAt)}</time>
                      </header>
                      {round.summary ? <p className={styles.groupRoundSummary}>{round.summary}</p> : null}
                      <div className={styles.groupMessageList}>
                        {(round.messages ?? []).map((message) => (
                          <article
                            key={message.messageId}
                            className={
                              message.status === "failed"
                                ? `${styles.groupMessageCard} ${styles.groupMessageCardFailed}`
                                : styles.groupMessageCard
                            }
                          >
                            <header>
                              <strong>{message.speakerTitle}</strong>
                              <span>{statusLabel(message.status)}</span>
                            </header>
                            <p>{message.content || message.summary || (lang === "zh" ? "暂无内容" : "No content yet")}</p>
                          </article>
                        ))}
                      </div>
                    </section>
                  ))
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
                  disabled={startGroupRoundMutation.isPending || groupRoundRunning}
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
                    || groupRoundRunning
                    || !activeGroupRoom
                  }
                >
                  <UsersRound size={15} />
                  <span>
                    {startGroupRoundMutation.isPending || groupRoundRunning
                      ? (lang === "zh" ? "讨论中" : "Running")
                      : (lang === "zh" ? "启动一轮" : "Run round")}
                  </span>
                </button>
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
                  assistantDisplayName={pet?.name}
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
        <div className={styles.segmented}>
          <button
            type="button"
            className={
              rightPanel === "sessions"
                ? `${styles.segmentButton} ${styles.segmentButtonActive}`
                : styles.segmentButton
            }
            onClick={() => setRightPanel("sessions")}
          >
            {t("sessions")}
          </button>
          <button
            type="button"
            className={
              rightPanel === "files"
                ? `${styles.segmentButton} ${styles.segmentButtonActive}`
                : styles.segmentButton
            }
            onClick={() => setRightPanel("files")}
          >
            {t("files")}
          </button>
        </div>

        <div className={styles.panelSearch}>
          <Search size={15} />
          <input
            className={styles.panelSearchInput}
            type="text"
            value={rightPanel === "sessions" ? sessionFilter : fileFilter}
            onChange={(event) =>
              rightPanel === "sessions"
                ? setSessionFilter(event.target.value)
                : setFileFilter(event.target.value)
            }
            placeholder={
              rightPanel === "sessions" ? t("searchSessionsPlaceholder") : t("searchFilesPlaceholder")
            }
          />
        </div>

        {rightPanel === "sessions" ? (
          <div className={styles.panelBody}>
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
                  <span>{lang === "zh" ? "模式" : "Mode"}</span>
                  <select
                    className={styles.groupComposerInput}
                    value={groupModeDraft}
                    onChange={(event) => setGroupModeDraft(event.target.value)}
                    disabled={chatRoomModesQuery.isPending || createGroupRoomMutation.isPending}
                  >
                    {readyChatRoomModes.map((mode) => (
                      <option key={mode.id} value={mode.id}>
                        {mode.label || mode.id}
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
                      return (
                        <label key={agent.agentId} className={selected ? `${styles.groupAgentOption} ${styles.groupAgentOptionSelected}` : styles.groupAgentOption}>
                          <input
                            type="checkbox"
                            checked={selected}
                            disabled={createGroupRoomMutation.isPending}
                            onChange={() => handleToggleGroupAgent(agent.agentId)}
                          />
                          <span>
                            <strong>{agent.displayName || agent.agentId}</strong>
                            <small>{agent.profileId || agent.templateId || "primary"}</small>
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
                        : activeAgentTemplate?.label ?? detail.agentTemplateLabel ?? activeAgentProfileId}
                    </span>
                  </div>
                </div>
                <select
                  className={styles.agentTemplateSelect}
                  value={activeAgentProfileId}
                  disabled={sessionAgentTemplatesQuery.isPending || updateSessionAgentMutation.isPending || sessionBusy}
                  onChange={(event) => handleAgentTemplateChange(event.target.value)}
                  aria-label={lang === "zh" ? "选择当前会话使用的 Agent 模板" : "Choose the agent template for this session"}
                >
                  {sessionAgentTemplates.length ? (
                    sessionAgentTemplates.map((template) => (
                      <option key={template.templateId} value={template.profileId}>
                        {template.label} · {template.model || template.providerKind || template.profileId}
                      </option>
                    ))
                  ) : (
                    <option value={activeAgentProfileId}>
                      {detail.agentTemplateLabel ?? activeAgentProfileId}
                    </option>
                  )}
                </select>
                <p className={styles.agentTemplateMeta}>
                  {activeAgentTemplate
                    ? `${activeAgentTemplate.providerKind || "-"} · ${activeAgentTemplate.model || "-"}`
                    : lang === "zh" ? "使用当前保存的会话 Agent 配置。" : "Using the saved session agent config."}
                  {activeAgentTemplate?.missingApiKey
                    ? (lang === "zh" ? " · 该配置缺少密钥" : " · missing key")
                    : ""}
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
              filteredConversations.map((conversation) => {
                if (conversation.type === "group_room") {
                  const roomId = conversation.roomId || conversation.conversationId;
                  return (
                    <div
                      key={`group-${roomId}`}
                      aria-current={activeGroupRoomId === roomId ? "true" : undefined}
                      className={
                        activeGroupRoomId === roomId
                          ? `${styles.sessionItem} ${styles.sessionItemActive}`
                          : styles.sessionItem
                      }
                    >
                      <button
                        type="button"
                        className={styles.sessionItemMain}
                        onClick={() => handleOpenGroupRoom(roomId)}
                      >
                        <div className={styles.sessionItemTop}>
                          <div className={styles.sessionItemIdentity}>
                            <UsersRound size={15} />
                            <span className={styles.sessionItemTitle}>{conversation.title}</span>
                          </div>
                          <span className={styles.sessionState}>{statusLabel(conversation.status)}</span>
                        </div>
                        <p className={styles.sessionItemSummary} title={conversation.summary}>
                          {conversation.summary || (lang === "zh" ? "群聊会话" : "Group conversation")}
                        </p>
                        <p className={styles.sessionItemMeta}>{formatTime(conversation.updatedAt)}</p>
                        <p className={styles.sessionAgentLine}>
                          {lang === "zh" ? "群聊" : "Group"} · {conversation.participantCount ?? 0}
                        </p>
                      </button>
                    </div>
                  );
                }
                const sessionId = conversation.directSessionId || conversation.conversationId;
                const session = sessionsById.get(sessionId) ?? {
                  id: sessionId,
                  title: conversation.title,
                  agentId: conversation.agentId,
                  agentProfileId: conversation.agentProfileId,
                  agentTemplateLabel: conversation.agentTemplateLabel,
                  workspacePath: conversation.workspacePath,
                  status: conversation.status,
                  taskSummary: conversation.summary,
                  lastActive: conversation.updatedAt,
                  updatedAt: conversation.updatedAt,
                  currentPhase: conversation.status,
                };
                const deletePending =
                  deleteSessionMutation.isPending &&
                  deleteSessionMutation.variables?.sessionId === session.id;
                const deleteDisabled = deletePending || isBusyPhase(session.currentPhase || session.status);
                const addToReviewPending =
                  addSessionToReviewMutation.isPending &&
                  addSessionToReviewMutation.variables?.sessionId === session.id;
                const addToReviewDisabled = addToReviewPending || isBusyPhase(session.currentPhase || session.status);
                const renamePending =
                  renameSessionMutation.isPending &&
                  renameSessionMutation.variables?.sessionId === session.id;
                const isEditingTitle = editingSessionId === session.id;
                const itemError = sessionComposerErrors[session.id] ?? "";
                const itemIsNotice = itemError.startsWith(t("addSessionToReviewSucceeded"));
                return (
                  <div
                    key={session.id}
                    aria-current={!groupPanelActive && activeSessionId === session.id ? "true" : undefined}
                    className={
                      !groupPanelActive && activeSessionId === session.id
                        ? `${styles.sessionItem} ${styles.sessionItemActive}`
                        : styles.sessionItem
                    }
                  >
                    {isEditingTitle ? (
                      <div className={styles.sessionItemMain}>
                        <div className={styles.sessionItemTop}>
                          <div className={styles.sessionItemIdentity}>
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
                          </div>
                          <span className={styles.sessionState}>{statusLabel(session.status)}</span>
                        </div>
                        <p className={styles.sessionItemSummary} title={session.taskSummary}>
                          {session.taskSummary}
                        </p>
                        <p className={styles.sessionItemMeta}>{formatTime(session.updatedAt || session.lastActive)}</p>
                        <p className={styles.sessionAgentLine}>
                          {session.agentTemplateLabel ?? session.agentProfileId ?? "primary"}
                        </p>
                      </div>
                    ) : (
                      <button
                        type="button"
                        className={styles.sessionItemMain}
                        onClick={() => handleOpenDirectSession(session.id)}
                        aria-current={!groupPanelActive && activeSessionId === session.id ? "true" : undefined}
                      >
                        <div className={styles.sessionItemTop}>
                          <div className={styles.sessionItemIdentity}>
                            <span className={styles.sessionItemTitle}>{session.title}</span>
                            {!groupPanelActive && activeSessionId === session.id ? (
                              <span className={styles.sessionCurrentBadge}>{t("currentSession")}</span>
                            ) : null}
                          </div>
                          <span className={styles.sessionState}>{statusLabel(session.status)}</span>
                        </div>
                        <p className={styles.sessionItemSummary} title={session.taskSummary}>
                          {session.taskSummary}
                        </p>
                        <p className={styles.sessionItemMeta}>{formatTime(session.updatedAt || session.lastActive)}</p>
                        <p className={styles.sessionAgentLine}>
                          {session.agentTemplateLabel ?? session.agentProfileId ?? "primary"}
                        </p>
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
                    {itemError ? (
                      <p className={itemIsNotice ? styles.sessionItemNotice : styles.sessionItemError}>
                        {itemError}
                      </p>
                    ) : null}
                  </div>
                );
              })
            )}
          </div>
        ) : (
          <div className={styles.panelBody}>
            {fileTreeQuery.isError ? (
              <div className={styles.panelState}>{describeError(fileTreeQuery.error, t("loadFailed"))}</div>
            ) : fileTreeQuery.isPending && !fileTreeQuery.data ? (
              <div className={styles.panelState}>{t("loadingFiles")}</div>
            ) : filteredTree.length === 0 ? (
              <div className={styles.panelState}>{t("noFileMatches")}</div>
            ) : (
              renderTree(filteredTree, handleOpenFile, changedFiles, activeFilePath, t("changed"))
            )}
          </div>
        )}
      </aside>
    </div>
  );
}
