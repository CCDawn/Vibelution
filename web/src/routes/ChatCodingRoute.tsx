import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Apple,
  Check,
  ChevronRight,
  HeartHandshake,
  MessageCircleHeart,
  Pencil,
  Plus,
  Search,
  Sparkles,
  Trash2,
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
  FileContent,
  FileTreeNode,
  PetActionResponse,
  PetSummary,
  RuntimeSummary,
  SessionDetail,
  SessionSummary,
  SessionStreamEvent,
} from "../api/types";
import { ConversationView } from "../components/conversation/ConversationView";
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
import { buildVisiblePanelRows, getPetAvatarPresetKey, getPetAvatarSymbol } from "./chatCompactPanel";
import {
  clearPendingSelfEvolutionHandoff,
  loadPendingSelfEvolutionHandoff,
} from "./selfEvolutionHandoff";
import styles from "./ChatCodingRoute.module.css";

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

type ResizableSide = "left" | "right";
type PetInteractionAction = "feed" | "talk" | "care";

type DragState = {
  side: ResizableSide;
  startX: number;
  startLeftWidth: number;
  startRightWidth: number;
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
  const [sessionDrafts, setSessionDrafts] = useState<Record<string, string>>({});
  const [sessionComposerErrors, setSessionComposerErrors] = useState<Record<string, string>>({});
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
  const layoutRef = useRef<HTMLDivElement | null>(null);
  const requestedSessionId = useMemo(() => {
    return new URLSearchParams(location.search).get("session") ?? "";
  }, [location.search]);

  const runtimeQuery = useQuery({
    queryKey: queryKeys.runtimeSummary(),
    queryFn: () => fetchJson<RuntimeSummary>("/api/runtime/summary"),
    refetchInterval: 5_000,
    refetchIntervalInBackground: true,
  });
  const petQuery = useQuery({
    queryKey: queryKeys.petSummary(),
    queryFn: () => fetchJson<PetSummary>("/api/pet/summary"),
    refetchInterval: 10_000,
    refetchIntervalInBackground: true,
  });
  const sessionsQuery = useQuery({
    queryKey: queryKeys.sessions(),
    queryFn: () => fetchJson<SessionSummary[]>("/api/sessions"),
    refetchInterval: 3_000,
    refetchIntervalInBackground: true,
  });
  const fileTreeQuery = useQuery({
    queryKey: queryKeys.fileTree(),
    queryFn: () => fetchJson<FileTreeNode[]>("/api/files/tree"),
    refetchInterval: 10_000,
    refetchIntervalInBackground: true,
  });

  useEffect(() => {
    if (
      requestedSessionId
      && sessionsQuery.data?.some((session) => session.id === requestedSessionId)
      && activeSessionId !== requestedSessionId
    ) {
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
    refetchInterval: activeSessionId ? (sessionStreamConnected ? false : 3_000) : false,
    refetchIntervalInBackground: true,
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
        body: JSON.stringify({ content, mentalModelEnabled }),
      }),
    onSuccess: (nextDetail, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      setSessionDrafts((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      queryClient.setQueryData(queryKeys.session(variables.sessionId), nextDetail);
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
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
      queryClient.setQueryData(queryKeys.session(variables.sessionId), nextDetail);
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
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
      setActiveSession(nextDetail.id);
      setSessionFilter("");
      setSessionComposerErrors((current) => ({
        ...current,
        [nextDetail.id]: "",
      }));
      queryClient.setQueryData(queryKeys.session(nextDetail.id), nextDetail);
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
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
      queryClient.setQueryData(queryKeys.session(nextDetail.id), nextDetail);
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
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
      queryClient.setQueryData(queryKeys.session(variables.sessionId), nextDetail);
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
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

  useEffect(() => {
    if (activeSessionId && sessionDetailQuery.data) {
      hydrateSession(activeSessionId, [], "agent");
    }
  }, [activeSessionId, hydrateSession, sessionDetailQuery.data]);

  useEffect(() => {
    if (!activeSessionId || typeof EventSource === "undefined") {
      setSessionStreamConnected(false);
      return;
    }

    let disposed = false;
    const stream = new EventSource(`/api/sessions/${activeSessionId}/events`);

    stream.onopen = () => {
      if (!disposed) {
        setSessionStreamConnected(true);
      }
    };

    stream.onerror = () => {
      if (!disposed) {
        setSessionStreamConnected(false);
      }
    };

    function handleSessionDetail(event: MessageEvent<string>) {
      let payload: SessionStreamEvent;
      try {
        payload = JSON.parse(event.data) as SessionStreamEvent;
      } catch {
        return;
      }
      if (payload.type !== "session_detail" || !payload.detail) {
        return;
      }
      queryClient.setQueryData(queryKeys.session(payload.sessionId), payload.detail);
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() });
    }

    stream.addEventListener("session_detail", handleSessionDetail as EventListener);

    return () => {
      disposed = true;
      setSessionStreamConnected(false);
      stream.removeEventListener("session_detail", handleSessionDetail as EventListener);
      stream.close();
    };
  }, [activeSessionId, queryClient]);

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
        const bounds = getResizeBounds("left", layoutWidth, activeDrag.startRightWidth);
        const nextLeftWidth = clamp(activeDrag.startLeftWidth + delta, bounds.min, bounds.max);
        setChatPanelWidths({ leftPanelWidth: Math.round(nextLeftWidth) });
        return;
      }

      const bounds = getResizeBounds("right", layoutWidth, activeDrag.startLeftWidth);
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
  }, [dragState, setChatPanelWidths]);

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
  const activeDraft = activeSessionId ? sessionDrafts[activeSessionId] ?? "" : "";
  const activeComposerError = activeSessionId ? sessionComposerErrors[activeSessionId] ?? "" : "";
  const submitMutationMatchesActiveSession =
    submitTurnMutation.variables?.sessionId === activeSessionId;
  const stopMutationMatchesActiveSession =
    stopTurnMutation.variables?.sessionId === activeSessionId;
  const submitPending = submitTurnMutation.isPending && submitMutationMatchesActiveSession;
  const sessionRunning = isRunningPhase(detail?.currentPhase);
  const sessionStopping = isStoppingPhase(detail?.currentPhase) || Boolean(detail?.stopRequested);
  const sessionBusy = isBusyPhase(detail?.currentPhase);
  const composerStopMode = sessionBusy;
  const composerPending =
    composerStopMode ? (stopTurnMutation.isPending && stopMutationMatchesActiveSession) || sessionStopping : submitPending;
  const composerDisabled = !activeSessionId || submitPending || sessionBusy;
  const composerActionDisabled = !activeSessionId || (
    composerStopMode ? composerPending : submitPending || !activeDraft.trim()
  );
  const composerPlaceholder =
    !activeSessionId
      ? t("loadingSession")
      : sessionStopping
        ? t("sessionStoppingPlaceholder")
      : sessionBusy
        ? t("sessionBusyPlaceholder")
        : t("messageInputPlaceholder");
  const contextPercent = contextUsagePercent(
    runtime?.contextUsage.used ?? 0,
    runtime?.contextUsage.limit ?? 0,
  );
  const contextUsageLabel = formatContextUsage(
    runtime?.contextUsage.used ?? 0,
    runtime?.contextUsage.limit ?? 0,
    locale,
  );
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
    : runtime
      ? contextUsageLabel
      : t("loadingContext");
  const sessionStateLabel = (() => {
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
  const sessionStateLine = runtime?.sessionStateLine
    ?? (sessionDetailQuery.isError
      ? describeError(sessionDetailQuery.error, t("loadFailed"))
      : detail?.taskSummary || t("preparingShell"));
  const activeTask = detail?.activeTask ?? null;
  const sessionStateValue = String(runtime?.sessionState ?? detail?.currentPhase ?? "idle")
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

  const filteredSessions = useMemo(() => {
    const term = sessionFilter.trim().toLowerCase();
    const sessions = sessionsQuery.data ?? [];
    if (!term) {
      return sessions;
    }
    return sessions.filter((session) =>
      [session.title, session.taskSummary, session.status, session.currentPhase].some((value) =>
        value.toLowerCase().includes(term),
      ),
    );
  }, [sessionFilter, sessionsQuery.data]);

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
    const content = activeDraft.trim();
    if (!content || composerDisabled) {
      return;
    }
    submitTurnMutation.mutate({
      sessionId: activeSessionId,
      content,
      mentalModelEnabled: mentalModelEnabledForNextTurn,
    });
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
    setSessionComposerErrors((current) => ({
      ...current,
      __sessions__: "",
    }));
    createSessionMutation.mutate();
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

  function handleResizeStart(side: ResizableSide, event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) {
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

    const { key } = event;
    const direction =
      key === "ArrowLeft" ? -1 : key === "ArrowRight" ? 1 : key === "Home" ? "min" : key === "End" ? "max" : null;
    if (direction === null) {
      return;
    }

    event.preventDefault();
    const layoutWidth = layoutRef.current.getBoundingClientRect().width;

    if (side === "left") {
      const bounds = getResizeBounds("left", layoutWidth, rightPanelWidth);
      const nextLeftWidth =
        direction === "min"
          ? bounds.min
          : direction === "max"
            ? bounds.max
            : clamp(leftPanelWidth + Number(direction) * KEYBOARD_RESIZE_STEP, bounds.min, bounds.max);
      setChatPanelWidths({ leftPanelWidth: Math.round(nextLeftWidth) });
      return;
    }

    const bounds = getResizeBounds("right", layoutWidth, leftPanelWidth);
    const delta =
      direction === "min"
        ? bounds.min
        : direction === "max"
          ? bounds.max
          : clamp(rightPanelWidth - Number(direction) * KEYBOARD_RESIZE_STEP, bounds.min, bounds.max);
    setChatPanelWidths({ rightPanelWidth: Math.round(delta) });
  }

  const layoutStyle = useMemo(
    () =>
      ({
        "--chat-left-pane-width": `${leftPanelWidth}px`,
        "--chat-right-pane-width": `${rightPanelWidth}px`,
      }) as CSSProperties,
    [leftPanelWidth, rightPanelWidth],
  );

  return (
    <div ref={layoutRef} className={styles.layout} style={layoutStyle}>
      <aside className={styles.leftRail}>
        <section className={styles.leftBlock}>
          <div className={styles.sectionHeader}>
            <div className={styles.sectionIdentity}>
              <p className={styles.blockEyebrow}>{t("currentSession")}</p>
              <h3 className={styles.sectionTitle}>{detail?.title ?? runtime?.sessionTitle ?? t("loadingSession")}</h3>
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

        <section className={styles.leftBlock}>
          <div className={styles.sectionHeader}>
            <div className={styles.sectionIdentity}>
              <p className={styles.blockEyebrow}>{t("mentalState")}</p>
              <p className={styles.sectionMetaLine}>{mentalCompactLine || mentalSourceLabel}</p>
            </div>
            <span className={`${styles.mentalStateBadge} ${styles[`mentalStateBadge_${mentalCognitiveStateValue}`]}`}>
              {mentalStateLabel}
            </span>
          </div>
          <p className={styles.contextLineCompact}>{mentalSummary}</p>
          <p className={styles.oneLineValue} title={mentalWhisper}>
            <span>{t("mentalWhisper")}</span>
            {mentalWhisper}
          </p>
          <details className={styles.compactDetails}>
            <summary>
              <ChevronRight size={14} />
              <span className={styles.compactDetailsClosedLabel}>{t("expandSection")}</span>
              <span className={styles.compactDetailsOpenLabel}>{t("collapseSection")}</span>
            </summary>
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
          </details>
        </section>

        <section className={styles.leftBlock}>
          <div className={styles.sectionHeader}>
            <div className={styles.sectionIdentity}>
              <p className={styles.blockEyebrow}>{t("petSpace")}</p>
              <h3 className={styles.sectionTitle}>{pet?.name ?? t("loadingPetState")}</h3>
            </div>
            <span className={styles.metricValue}>{t("level")} {pet?.level ?? 0}</span>
          </div>
          <p className={styles.contextLineCompact}>{petCompactLine}</p>
          <details className={styles.compactDetails}>
            <summary>
              <ChevronRight size={14} />
              <span className={styles.compactDetailsClosedLabel}>{t("expandSection")}</span>
              <span className={styles.compactDetailsOpenLabel}>{t("collapseSection")}</span>
            </summary>
            <div className={styles.inlineMetaList}>
              <span className={styles.inlineMetaPill}>
                <span>{t("preset")}</span>
                <strong>{petPresetLabel}</strong>
              </span>
              <span className={styles.inlineMetaPill}>
                <span>{t("dailyTokens")}</span>
                <strong>{numberFormatter.format(pet?.dailyTokens ?? 0)}</strong>
              </span>
            </div>
            <p className={styles.detailNote}>
              <span>{t("petBoundary")}</span>
              {t("petBoundaryLine")}
            </p>
            <div className={styles.vitalStackCompact}>
              {petVitals.map((vital) => (
                <div key={vital.key} className={styles.vitalItemCompact}>
                  <div className={styles.vitalLabelRow}>
                    <span>{vital.label}</span>
                    <strong>{vital.value}</strong>
                  </div>
                  <div className={styles.progressTrack}>
                    <div className={styles.progressFillCool} style={{ width: `${vital.value}%` }} />
                  </div>
                </div>
              ))}
            </div>
          </details>
        </section>

        <section className={styles.leftBlock}>
          <div className={styles.sectionHeader}>
            <p className={styles.blockEyebrow}>{t("contextInUse")}</p>
            <span className={styles.metricValue}>{contextPercent}%</span>
          </div>
          <p className={styles.contextUsageValue}>{contextStatusLine}</p>
          <div className={styles.progressTrack}>
            <div className={styles.progressFillWarm} style={{ width: `${contextPercent}%` }} />
          </div>
          <p className={styles.backendNote}>
            {runtime
              ? `${numberFormatter.format(runtime.contextUsage.used)} / ${numberFormatter.format(runtime.contextUsage.limit)}`
              : t("loadingContext")}
          </p>
        </section>

        <section className={styles.petShowcase} aria-label={t("petSpace")}>
          <div className={styles.petShowcaseStage} aria-hidden="true">
            <div className={styles.petShowcaseAura} />
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
          <div className={styles.petShowcaseInfo}>
            <div className={styles.petShowcaseTop}>
              <p className={styles.blockEyebrow}>{t("petSpace")}</p>
              <span>{t("level")} {pet?.level ?? 0}</span>
            </div>
            <h3 className={styles.petShowcaseName}>{pet?.name ?? t("loadingPetState")}</h3>
            <p className={styles.petShowcaseLine}>
              {petPresetLabel} · {petCompanionLine}
            </p>
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
        </section>
      </aside>

      <div
        role="separator"
        aria-orientation="vertical"
        aria-label={t("resizeLeftPanel")}
        title={t("resizeLeftPanel")}
        tabIndex={0}
        className={
          dragState?.side === "left"
            ? `${styles.resizeHandle} ${styles.resizeHandleActive}`
            : styles.resizeHandle
        }
        onPointerDown={(event) => handleResizeStart("left", event)}
        onKeyDown={(event) => handleResizeKeyDown("left", event)}
      />

      <section className={styles.centerPane}>
        <div className={styles.tabStrip}>
          <button
            type="button"
            className={
              workspace.activeTab === "agent" ? `${styles.tab} ${styles.tabActive}` : styles.tab
            }
            onClick={() => activeSessionId && setActiveTab(activeSessionId, "agent")}
          >
            {t("agentSession")}
          </button>
          {workspace.openTabs.map((tabPath) => (
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
          {!activeSessionId && !sessionsQuery.isPending ? (
            <div className={styles.emptySurface}>{t("noSessionsYet")}</div>
          ) : sessionDetailQuery.isError ? (
            <div className={styles.emptySurface}>
              {describeError(sessionDetailQuery.error, t("loadFailed"))}
            </div>
          ) : workspace.activeTab === "agent" ? (
            detail ? (
              <ConversationView
                sessionId={activeSessionId ?? detail.id}
                title={detail.title}
                phase={detail.currentPhase}
                messages={detail.messages}
                assistantDisplayName={pet?.name}
                userDisplayName={runtime?.userName}
                taskSummary={currentTaskSummary}
                defaultFileContext={detail.defaultFileContext}
                showHeader={false}
                showSessionOverview={false}
                composerValue={activeDraft}
                composerPlaceholder={composerPlaceholder}
                composerDisabled={composerDisabled}
                composerActionDisabled={composerActionDisabled}
                composerActionMode={composerStopMode ? "stop" : "send"}
                composerPending={composerPending}
                composerError={activeComposerError}
                mentalModelEnabled={mentalModelEnabledForNextTurn}
                mentalModelOptionDisabled={!activeSessionId}
                stopLabel={t("stop")}
                stopPendingLabel={t("stopPending")}
                onComposerChange={handleComposerChange}
                onMentalModelEnabledChange={handleMentalModelEnabledChange}
                onSubmit={handleSubmitTurn}
                onStop={handleStopTurn}
              />
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

      <div
        role="separator"
        aria-orientation="vertical"
        aria-label={t("resizeRightPanel")}
        title={t("resizeRightPanel")}
        tabIndex={0}
        className={
          dragState?.side === "right"
            ? `${styles.resizeHandle} ${styles.resizeHandleActive}`
            : styles.resizeHandle
        }
        onPointerDown={(event) => handleResizeStart("right", event)}
        onKeyDown={(event) => handleResizeKeyDown("right", event)}
      />

      <aside className={styles.rightPane}>
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
            <button
              type="button"
              className={styles.newSessionButton}
              onClick={handleCreateSession}
              disabled={createSessionMutation.isPending}
            >
              <Plus size={15} />
              <span>{createSessionMutation.isPending ? t("creatingSession") : t("newSession")}</span>
            </button>
            {sessionComposerErrors.__sessions__ ? (
              <div className={styles.panelState}>{sessionComposerErrors.__sessions__}</div>
            ) : null}
            {sessionsQuery.isError ? (
              <div className={styles.panelState}>{describeError(sessionsQuery.error, t("loadFailed"))}</div>
            ) : sessionsQuery.isPending && !sessionsQuery.data ? (
              <div className={styles.panelState}>{t("loadingSession")}</div>
            ) : filteredSessions.length === 0 ? (
              <div className={styles.panelState}>
                {sessionFilter.trim() ? t("noSessionMatches") : t("noSessionsYet")}
              </div>
            ) : (
              filteredSessions.map((session) => {
                const deletePending =
                  deleteSessionMutation.isPending &&
                  deleteSessionMutation.variables?.sessionId === session.id;
                const deleteDisabled = deletePending || isBusyPhase(session.currentPhase || session.status);
                const renamePending =
                  renameSessionMutation.isPending &&
                  renameSessionMutation.variables?.sessionId === session.id;
                const isEditingTitle = editingSessionId === session.id;
                const itemError = sessionComposerErrors[session.id] ?? "";
                return (
                  <div
                    key={session.id}
                    className={
                      activeSessionId === session.id
                        ? `${styles.sessionItem} ${styles.sessionItemActive}`
                        : styles.sessionItem
                    }
                  >
                    {isEditingTitle ? (
                      <div className={styles.sessionItemMain}>
                        <div className={styles.sessionItemTop}>
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
                          <span className={styles.sessionState}>{statusLabel(session.status)}</span>
                        </div>
                        <p className={styles.sessionItemSummary} title={session.taskSummary}>
                          {session.taskSummary}
                        </p>
                        <p className={styles.sessionItemMeta}>{formatTime(session.updatedAt || session.lastActive)}</p>
                      </div>
                    ) : (
                      <button
                        type="button"
                        className={styles.sessionItemMain}
                        onClick={() => setActiveSession(session.id)}
                      >
                        <div className={styles.sessionItemTop}>
                          <span className={styles.sessionItemTitle}>{session.title}</span>
                          <span className={styles.sessionState}>{statusLabel(session.status)}</span>
                        </div>
                        <p className={styles.sessionItemSummary} title={session.taskSummary}>
                          {session.taskSummary}
                        </p>
                        <p className={styles.sessionItemMeta}>{formatTime(session.updatedAt || session.lastActive)}</p>
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
                    {itemError ? <p className={styles.sessionItemError}>{itemError}</p> : null}
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
