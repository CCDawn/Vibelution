import { PanelRightClose, Plus, Search, X } from "lucide-react";
import { lazy, Suspense, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { createSessionChild, fetchSessionDetail, listSessionChildSessions, submitSessionMessage } from "../../api/chat";
import { fetchFileContent } from "../../api/files";
import { queryKeys } from "../../api/queryKeys";
import type { ConversationMessage, FileContent, GitFileDiff, SessionActiveTask, SessionQueuedTurn, SessionSummary } from "../../api/types";
import {
  VButton,
  VDropdownMenu,
  VEmptyState,
  VInput,
  VRouteLinkButton,
  VTextarea,
} from "../../components/vui";
import { auxTaskStatusLabel } from "../auxConversations/auxTaskPresentation";
import { assistantTurnIsInFlight } from "../chatTurnProtocol";
import { isBusyPhase } from "./chatCodingRouteViewModel";
import { ChatChangeRail } from "./ChatChangeRail";
import type { CliAgentRunView, CliAgentTerminalSession } from "./cliAgentRunModel";
import { encodeUtf8Base64 } from "./chatComposerSubmitModel";
import {
  activeChatRightRailTab,
  chatRightRailKindLabel,
  chatRightRailLauncherKinds,
  chatRightRailTabLabel,
  chatRightRailTranscriptLines,
  closeAllChatRightRailTabs,
  closeChatRightRailTab,
  closeOtherChatRightRailTabs,
  consumeChatRightRailSideDraft,
  normalizeChatRightRailBrowserUrl,
  openChatRightRailTab,
  openFreshChatRightRailSideTab,
  projectChatRightRailDevtools,
  rememberChatRightRailSideChild,
  reorderChatRightRailTab,
  searchChatRightRailTabs,
  type ChatRightRailDevtoolsInput,
  type ChatRightRailKind,
  type ChatRightRailModel,
  type ChatRightRailTab,
  confirmChatRightRailSideReadback,
  trackChatRightRailSideSubmission,
  updateChatRightRailSideDraft,
} from "./chatRightRailModel";
import { isTempSessionId } from "../sessionOptimisticIds";
import styles from "./ChatRightRail.styles";
import { isProjectUtilityKind } from "../../app/projectUtilityRail";
import { ProjectUtilityPanel } from "./ProjectUtilityPanel";

const CliAgentRunTerminalPanel = lazy(() =>
  import("./CliAgentRunTerminalPanel").then((module) => ({
    default: module.CliAgentRunTerminalPanel,
  })),
);

export type ChatRightRailSideClient = {
  createChild: (
    sessionId: string,
    payload: {
      userRequest: string;
      taskTitle: string;
      autoStart: boolean;
      switchToChild: boolean;
      source: string;
      announceOnParent: boolean;
    },
  ) => Promise<{ childSessionId: string; parentSessionId: string }>;
  submit: (sessionId: string, content: string) => Promise<void>;
  fetchDetail: (
    sessionId: string,
    signal?: AbortSignal,
  ) => Promise<{
    currentPhase?: string;
    status?: string;
    lastTurnStatus?: string;
    queuedTurns?: Array<Pick<SessionQueuedTurn, "kind" | "status">>;
    activeTask?: Pick<SessionActiveTask, "status"> | null;
    messages: ConversationMessage[];
  }>;
};

const defaultSideClient: ChatRightRailSideClient = {
  createChild: (sessionId, payload) => createSessionChild(sessionId, payload),
  submit: async (sessionId, content) => {
    await submitSessionMessage(sessionId, {
      content,
      clientSubmissionId: globalThis.crypto?.randomUUID?.() ?? `side-${Date.now()}`,
      contentUtf8Base64: encodeUtf8Base64(content),
      attachmentIds: [],
      references: [],
      queueIfBusy: true,
    });
  },
  fetchDetail: async (sessionId, signal) => fetchSessionDetail(sessionId, {
    messageLimit: 40,
    includeSecondary: false,
    signal,
  }),
};

export type ChatRightRailReview = {
  sessionTitle: string;
  sessionEmptyLabel: string;
  sessionPaths: string[];
  sessionSelectedPath: string | null;
  sessionChangedPaths: ReadonlySet<string>;
  gitTitle: string;
  gitEmptyLabel: string;
  gitPending: boolean;
  gitPendingLabel: string;
  gitUnavailableLabel: string;
  gitPaths: string[];
  gitSelectedPath: string | null;
  gitDetailByPath?: Readonly<Record<string, string>>;
  diff: GitFileDiff | undefined;
  diffLoading: boolean;
  hasDiff: boolean;
  file: FileContent | null | undefined;
  fileLoading: boolean;
  fileError: string;
  sourceLabel: string;
  onSelectSessionFile: (path: string) => void;
  onSelectGitFile: (path: string) => void;
};

type ChatRightRailProps = {
  className: string;
  lang: "zh" | "en";
  sessionId: string;
  sessionKind?: string;
  model: ChatRightRailModel;
  onModelChange: (update: ChatRightRailModel | ((current: ChatRightRailModel) => ChatRightRailModel)) => void;
  onCollapse: () => void;
  review: ChatRightRailReview;
  devtools: ChatRightRailDevtoolsInput;
  terminalRun: CliAgentRunView | null;
  terminalMountedInCenter: boolean;
  onTerminalSessionChange?: (runId: string, session: CliAgentTerminalSession) => void;
  onOpenFile: (path: string) => void;
  onOpenSession?: (sessionId: string) => void;
  id?: string;
  sideClient?: ChatRightRailSideClient;
};

function failureText(error: unknown, fallback: string) {
  return error instanceof Error && error.message.trim() ? error.message : fallback;
}

type ChatRightRailSessionDetail = Awaited<ReturnType<ChatRightRailSideClient["fetchDetail"]>>;

const SIDE_CHAT_EXTRA_ACTIVE_PHASES = new Set(["pending", "waiting", "in_progress"]);
const SIDE_CHAT_QUEUED_PHASES = new Set(["queued", "starting", "draining", "paused"]);

function sideChatPhaseIsInFlight(value: string | undefined): boolean {
  const phase = String(value || "").trim().toLowerCase();
  return isBusyPhase(phase) || SIDE_CHAT_EXTRA_ACTIVE_PHASES.has(phase);
}

function sideChatDetailIsInFlight(detail: ChatRightRailSessionDetail | undefined): boolean {
  if (!detail) {
    return false;
  }
  return sideChatPhaseIsInFlight(detail.currentPhase)
    || sideChatPhaseIsInFlight(detail.status)
    || sideChatPhaseIsInFlight(detail.lastTurnStatus)
    || sideChatPhaseIsInFlight(detail.activeTask?.status)
    || Boolean(detail.queuedTurns?.some((turn) => {
      const status = String(turn.status || "").trim().toLowerCase();
      return SIDE_CHAT_QUEUED_PHASES.has(status);
    }))
    || detail.messages.some(assistantTurnIsInFlight);
}

function RailThread({
  boundSessionId,
  parentSessionId,
  createOnSend,
  lang,
  onBound,
  client,
  initialDraft = "",
  initialDraftRevision = 0,
  pendingReadbackGeneration,
  autoSend = false,
  onDraftConsumed,
  onDraftChange,
  onSubmissionTracked,
  onSubmissionReadback,
}: {
  boundSessionId: string;
  parentSessionId: string;
  createOnSend: boolean;
  lang: "zh" | "en";
  onBound: (childSessionId: string) => void;
  client: ChatRightRailSideClient;
  initialDraft?: string;
  initialDraftRevision?: number;
  pendingReadbackGeneration?: number;
  autoSend?: boolean;
  onDraftConsumed?: () => void;
  onDraftChange?: (draft: string, expectedRevision?: number) => void;
  onSubmissionTracked?: () => void;
  onSubmissionReadback?: (generation: number) => void;
}) {
  const [draft, setDraft] = useState(initialDraft);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const bootedDraft = useRef(false);
  const [pendingLine, setPendingLine] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const queryClient = useQueryClient();
  const detailQueryKey = useMemo(
    () => queryKeys.sessionRightRail(boundSessionId || "none"),
    [boundSessionId],
  );
  const onSubmissionReadbackRef = useRef(onSubmissionReadback);
  onSubmissionReadbackRef.current = onSubmissionReadback;
  const copy = lang === "zh"
    ? {
      placeholder: "问一句",
      send: "发送",
      empty: "写一句，就会在右栏里新开一场辅助对话。中间的记录不会改。",
      pending: "正在回复",
      failed: "辅助对话没有发出去",
      temp: "会话还在创建，稍后再开辅助对话。",
    }
    : {
      placeholder: "Ask here",
      send: "Send",
      empty: "Send a line to start a side chat in this column. The center transcript stays as it is.",
      pending: "Replying",
      failed: "The side chat was not sent",
      temp: "This chat is still being created.",
    };
  const detailQuery = useQuery({
    queryKey: detailQueryKey,
    enabled: Boolean(boundSessionId),
    queryFn: ({ signal }) => client.fetchDetail(boundSessionId, signal),
    refetchOnMount: "always",
    refetchInterval: (query) => (
      pendingReadbackGeneration == null && sideChatDetailIsInFlight(query.state.data)
        ? 1200
        : false
    ),
  });
  const detail = detailQuery.data;

  useEffect(() => {
    if (!boundSessionId || pendingReadbackGeneration == null) {
      return;
    }
    const generation = pendingReadbackGeneration;
    let active = true;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    const readback = async () => {
      await queryClient.cancelQueries({ queryKey: detailQueryKey, exact: true });
      if (!active) {
        return;
      }
      const result = await detailQuery.refetch({ cancelRefetch: true });
      if (!active) {
        return;
      }
      if (result.isSuccess && result.data) {
        onSubmissionReadbackRef.current?.(generation);
        return;
      }
      retryTimer = setTimeout(() => void readback(), 1200);
    };
    void readback();
    return () => {
      active = false;
      if (retryTimer) {
        clearTimeout(retryTimer);
      }
      void queryClient.cancelQueries({ queryKey: detailQueryKey, exact: true });
    };
  }, [boundSessionId, detailQuery.refetch, detailQueryKey, pendingReadbackGeneration, queryClient]);
  const lines = chatRightRailTranscriptLines(detail?.messages ?? []);
  useEffect(() => {
    if (pendingLine && lines.some((line) => line.role === "user" && line.text === pendingLine)) {
      setPendingLine("");
    }
  }, [lines, pendingLine]);
  const blocked = isTempSessionId(parentSessionId);
  const sendText = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || sending || blocked) {
      return;
    }
    const submittedDraftRevision = initialDraftRevision;
    setSending(true);
    setError("");
    try {
      if (createOnSend && !boundSessionId) {
        const created = await client.createChild(parentSessionId, {
          userRequest: trimmed,
          taskTitle: trimmed.slice(0, 80),
          autoStart: true,
          switchToChild: false,
          source: "side_pane",
          announceOnParent: false,
        });
        const childSessionId = created.childSessionId.trim();
        if (!childSessionId) {
          throw new Error(copy.failed);
        }
        onBound(childSessionId);
      } else if (boundSessionId) {
        await client.submit(boundSessionId, trimmed);
      } else {
        throw new Error(copy.failed);
      }
      onSubmissionTracked?.();
      setPendingLine(trimmed);
      setDraft("");
      onDraftChange?.("", submittedDraftRevision);
    } catch (sendError) {
      setError(failureText(sendError, copy.failed));
    } finally {
      setSending(false);
    }
  };
  const sendTextRef = useRef(sendText);
  sendTextRef.current = sendText;
  useEffect(() => {
    if (bootedDraft.current) {
      return;
    }
    bootedDraft.current = true;
    const text = initialDraft.trim();
    if (!text) {
      return;
    }
    if (autoSend) {
      onDraftConsumed?.();
      if (!blocked) {
        void sendTextRef.current(text);
        return;
      }
    }
    requestAnimationFrame(() => composerRef.current?.focus());
  }, [autoSend, blocked, initialDraft, onDraftConsumed]);
  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    await sendText(draft);
  };
  return (
    <form className={styles.thread} onSubmit={(event) => void onSubmit(event)}>
      <div className={styles.transcript} aria-live="polite">
        {lines.length === 0 && !pendingLine ? <p className={styles.note}>{copy.empty}</p> : null}
        {lines.map((line) => (
          <p
            key={line.id}
            className={line.role === "user" ? styles.bubbleUser : styles.bubbleAssistant}
          >
            {line.text || (line.pending ? copy.pending : "")}
          </p>
        ))}
        {pendingLine ? <p className={styles.bubbleUser}>{pendingLine}</p> : null}
        {error ? <p className={styles.error} role="alert">{error}</p> : null}
        {blocked ? <p className={styles.note}>{copy.temp}</p> : null}
      </div>
      <div className={styles.composer}>
        <VTextarea
          ref={composerRef}
          aria-label={copy.placeholder}
          rows={2}
          value={draft}
          disabled={sending || blocked}
          onChange={(event) => {
            const value = event.target.value;
            setDraft(value);
            onDraftChange?.(value);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
        />
        <VButton type="submit" density="compact" isDisabled={!draft.trim() || sending || blocked} isPending={sending}>
          {copy.send}
        </VButton>
      </div>
    </form>
  );
}

function openKind(
  model: ChatRightRailModel,
  kind: ChatRightRailKind,
  lang: "zh" | "en",
) {
  return openChatRightRailTab(model, {
    kind,
    title: chatRightRailKindLabel(kind, lang),
  });
}

function ChatRightRailFileBody({
  filePath,
  copy,
  onOpenFile,
}: {
  filePath: string;
  copy: {
    fileOpen: string;
    fileLoading: string;
    fileError: string;
    fileEmpty: string;
    fileTruncated: string;
  };
  onOpenFile: (path: string) => void;
}) {
  const fileQuery = useQuery({
    queryKey: queryKeys.fileContent(filePath),
    queryFn: () => fetchFileContent(filePath),
    enabled: Boolean(filePath),
  });
  return (
    <div className={styles.plain}>
      <p className={styles.note}>{filePath}</p>
      <VButton type="button" density="compact" onClick={() => onOpenFile(filePath)}>
        {copy.fileOpen}
      </VButton>
      {fileQuery.isPending ? <p className={styles.note}>{copy.fileLoading}</p> : null}
      {fileQuery.isError ? <p className={styles.error} role="alert">{copy.fileError}</p> : null}
      {fileQuery.data?.truncated ? <p className={styles.note}>{copy.fileTruncated}</p> : null}
      {fileQuery.data && !fileQuery.data.content ? <p className={styles.note}>{copy.fileEmpty}</p> : null}
      {fileQuery.data?.content ? <pre className={styles.fileBody}>{fileQuery.data.content}</pre> : null}
    </div>
  );
}

type DirectoryRow = {
  id: string;
  title: string;
  status: string;
  summary: string;
};

function directoryRows(sessions: SessionSummary[]): DirectoryRow[] {
  return sessions.flatMap((session) => {
    const id = String(session.id || "").trim();
    if (!id) {
      return [];
    }
    return [{
      id,
      title: String(session.taskTitle || session.title || id).trim() || id,
      status: String(session.childStatus || session.status || session.currentPhase || "").trim(),
      summary: String(session.resultCard?.summary || session.taskSummary || "").trim(),
    }];
  });
}

function ChatRightRailDirectoryBody({
  sessionId,
  lang,
  copy,
  onOpenItem,
}: {
  sessionId: string;
  lang: "zh" | "en";
  copy: {
    directory: string;
    directoryOpen: string;
    directoryLoading: string;
    directoryError: string;
    directoryRunning: string;
    directoryEnded: string;
    directoryRunningEmpty: string;
    directoryEndedEmpty: string;
  };
  onOpenItem: (item: DirectoryRow) => void;
}) {
  const directoryQuery = useQuery({
    queryKey: queryKeys.sessionChildSessions(sessionId || "none"),
    queryFn: () => listSessionChildSessions(sessionId),
    enabled: Boolean(sessionId),
  });
  const rows = directoryRows(directoryQuery.data ?? []);
  const running = rows.filter((row) => sideChatPhaseIsInFlight(row.status));
  const ended = rows.filter((row) => !sideChatPhaseIsInFlight(row.status));
  const section = (title: string, items: DirectoryRow[], empty: string) => (
    <>
      <p className={styles.searchHeading}>{`${title} · ${items.length}`}</p>
      {items.length ? (
        <ul className={styles.launcherList}>
          {items.map((item) => (
            <li key={item.id}>
              <VButton
                type="button"
                variant="ghost"
                contentLayout="plain"
                className={styles.launcherButton}
                onClick={() => onOpenItem(item)}
              >
                {`${item.title} · ${auxTaskStatusLabel(item.status, lang)}`}
              </VButton>
              {item.summary ? <p className={styles.note}>{item.summary}</p> : null}
            </li>
          ))}
        </ul>
      ) : directoryQuery.isPending ? null : (
        <p className={styles.note}>{empty}</p>
      )}
    </>
  );
  return (
    <div className={styles.plain}>
      {directoryQuery.isPending ? <p className={styles.note}>{copy.directoryLoading}</p> : null}
      {directoryQuery.isError ? <p className={styles.error} role="alert">{copy.directoryError}</p> : null}
      {section(copy.directoryRunning, running, copy.directoryRunningEmpty)}
      {section(copy.directoryEnded, ended, copy.directoryEndedEmpty)}
      <p className={styles.note}>{copy.directory}</p>
      <VRouteLinkButton to="/aux" variant="ghost" density="compact">
        {copy.directoryOpen}
      </VRouteLinkButton>
    </div>
  );
}

export function ChatRightRail({
  className,
  lang,
  sessionId,
  sessionKind,
  model,
  onModelChange,
  onCollapse,
  review,
  devtools,
  terminalRun,
  terminalMountedInCenter,
  onTerminalSessionChange,
  onOpenFile,
  onOpenSession,
  id = "chat-status-pane",
  sideClient = defaultSideClient,
}: ChatRightRailProps) {
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [browserDraft, setBrowserDraft] = useState("");
  const [browserError, setBrowserError] = useState("");
  const [tabMenu, setTabMenu] = useState<{ id: string; x: number; y: number } | null>(null);
  const suppressClickTabId = useRef<string | null>(null);
  const draggingTabId = useRef<string | null>(null);
  const copy = lang === "zh"
    ? {
      rail: "右侧栏",
      openTab: "打开标签页",
      add: "添加标签",
      search: "搜索标签",
      collapse: "收起侧栏",
      close: "关闭",
      closeCurrent: "关闭标签",
      closeOthers: "关闭其他标签",
      closeAll: "关闭所有标签",
      tabMenu: "标签操作",
      reopen: "重新打开",
      closed: "最近关闭",
      none: "没有匹配的标签",
      terminalEmpty: "这场对话还没有终端",
      terminalCenter: "这场对话的终端正在中间打开",
      terminalLoading: "正在打开终端",
      browserHint: "只打开 http 或 https。嵌不进来的页面用系统浏览器。",
      browserInvalid: "请输入 http 或 https 地址",
      browserOpen: "打开",
      browserSystem: "在系统浏览器打开",
      devtoolsEmpty: "还没有这场对话的数据",
      fileOpen: "在对话中打开",
      fileLoading: "正在读取文件",
      fileError: "这个文件打不开",
      fileEmpty: "这个文件是空的",
      fileTruncated: "只显示了前面一部分",
      contextualEmpty: "这场对话还没有打开这项内容",
      directory: "这项任务的详情在辅助对话中心。",
      directoryOpen: "打开辅助对话中心",
      directoryLoading: "正在读取子会话",
      directoryError: "子会话列表没有读出来",
      directoryRunning: "进行中",
      directoryEnded: "已结束",
      directoryRunningEmpty: "现在没有正在进行的子会话",
      directoryEndedEmpty: "还没有结束的子会话",
    }
    : {
      rail: "Right column",
      openTab: "Open a tab",
      add: "Add tab",
      search: "Search tabs",
      collapse: "Collapse column",
      close: "Close",
      closeCurrent: "Close tab",
      closeOthers: "Close other tabs",
      closeAll: "Close all tabs",
      tabMenu: "Tab actions",
      reopen: "Reopen",
      closed: "Recently closed",
      none: "No matching tabs",
      terminalEmpty: "This chat has no terminal",
      terminalCenter: "This chat's terminal is open in the center",
      terminalLoading: "Opening the terminal",
      browserHint: "Only http or https. Use the system browser when a page cannot be embedded.",
      browserInvalid: "Enter an http or https address",
      browserOpen: "Open",
      browserSystem: "Open in the system browser",
      devtoolsEmpty: "This chat has no data yet",
      fileOpen: "Open in the chat",
      fileLoading: "Reading the file",
      fileError: "This file could not be opened",
      fileEmpty: "This file is empty",
      fileTruncated: "Showing the first part only",
      contextualEmpty: "This chat has not opened that yet",
      directory: "Details for this task are in the side-chat center.",
      directoryOpen: "Open the side-chat center",
      directoryLoading: "Reading side sessions",
      directoryError: "The side-session list could not be loaded",
      directoryRunning: "Running",
      directoryEnded: "Finished",
      directoryRunningEmpty: "Nothing is running",
      directoryEndedEmpty: "Nothing has finished",
    };
  const active = activeChatRightRailTab(model);
  const launcher = chatRightRailLauncherKinds(sessionKind).filter((kind) => Boolean(sessionId) || isProjectUtilityKind(kind));
  const matches = searchChatRightRailTabs(model, searchQuery);
  const devtoolsView = projectChatRightRailDevtools(devtools);
  const browserUrl = active?.kind === "browser" ? normalizeChatRightRailBrowserUrl(active.url || "") : null;
  const activate = (kind: ChatRightRailKind) => {
    if (kind === "side") {
      onModelChange((current) => openFreshChatRightRailSideTab(current, {
        titleBase: chatRightRailKindLabel("side", lang),
      }));
    } else {
      onModelChange(openKind(model, kind, lang));
    }
    setSearchOpen(false);
  };
  return (
    <section id={id} className={`${styles.shell} ${className}`} aria-label={copy.rail}>
      <div className={styles.toolbar}>
        <div role="tablist" aria-label={copy.rail} className={styles.tabs}>
          {model.tabs.map((tab) => {
            const selected = tab.id === model.activeId;
            const label = chatRightRailTabLabel(tab, lang);
            return (
              <div
                key={tab.id}
                role="tab"
                aria-label={label}
                aria-selected={selected}
                data-chat-right-rail-tab={tab.id}
                draggable
                className={selected ? `${styles.tab} ${styles.tabActive}` : styles.tab}
                onMouseDown={(event) => {
                  if (event.button === 1) {
                    event.preventDefault();
                    suppressClickTabId.current = tab.id;
                  }
                }}
                onAuxClick={(event) => {
                  if (event.button !== 1) {
                    return;
                  }
                  event.preventDefault();
                  suppressClickTabId.current = tab.id;
                  onModelChange((current) => closeChatRightRailTab(current, tab.id));
                }}
                onContextMenu={(event) => {
                  event.preventDefault();
                  setTabMenu({ id: tab.id, x: event.clientX, y: event.clientY });
                }}
                onDragStart={(event) => {
                  const target = event.target;
                  if (target instanceof Element && target.closest("[data-chat-right-rail-close]")) {
                    event.preventDefault();
                    return;
                  }
                  draggingTabId.current = tab.id;
                  suppressClickTabId.current = tab.id;
                  event.dataTransfer?.setData("text/plain", tab.id);
                  if (event.dataTransfer) {
                    event.dataTransfer.effectAllowed = "move";
                  }
                }}
                onDragOver={(event) => {
                  if (!draggingTabId.current || draggingTabId.current === tab.id) {
                    return;
                  }
                  event.preventDefault();
                  if (event.dataTransfer) {
                    event.dataTransfer.dropEffect = "move";
                  }
                }}
                onDrop={(event) => {
                  event.preventDefault();
                  const from = draggingTabId.current || event.dataTransfer?.getData("text/plain") || "";
                  draggingTabId.current = null;
                  if (!from || from === tab.id) {
                    return;
                  }
                  onModelChange((current) => reorderChatRightRailTab(current, from, tab.id));
                }}
                onDragEnd={() => {
                  draggingTabId.current = null;
                }}
              >
                <VButton
                  type="button"
                  contentLayout="plain"
                  draggable
                  className={styles.tabLabel}
                  onClick={(event) => {
                    if (event.button !== 0 || suppressClickTabId.current === tab.id) {
                      suppressClickTabId.current = null;
                      return;
                    }
                    onModelChange((current) => (
                      current.activeId === tab.id ? current : { ...current, activeId: tab.id }
                    ));
                  }}
                >
                  {label}
                </VButton>
                <VButton
                  type="button"
                  isIconOnly
                  aria-label={`${copy.close}${label}`}
                  className={styles.tabClose}
                  data-chat-right-rail-close=""
                  onClick={(event) => {
                    event.stopPropagation();
                    onModelChange((current) => closeChatRightRailTab(current, tab.id));
                  }}
                >
                  <X size={12} aria-hidden="true" />
                </VButton>
              </div>
            );
          })}
        </div>
        <div className={styles.tools}>
          <VButton
            type="button"
            isIconOnly
            aria-label={copy.search}
            aria-expanded={searchOpen}
            className={styles.iconButton}
            onClick={() => setSearchOpen((open) => !open)}
          >
            <Search size={16} aria-hidden="true" />
          </VButton>
          <VDropdownMenu
            align="end"
            side="bottom"
            aria-label={copy.add}
            trigger={(
              <VButton type="button" isIconOnly aria-label={copy.add} className={styles.iconButton}>
                <Plus size={16} aria-hidden="true" />
              </VButton>
            )}
            items={launcher.map((kind) => ({
              id: kind,
              label: chatRightRailKindLabel(kind, lang),
              onSelect: () => activate(kind),
            }))}
          />
          <VButton
            type="button"
            isIconOnly
            aria-label={copy.collapse}
            className={styles.iconButton}
            onClick={onCollapse}
          >
            <PanelRightClose size={16} aria-hidden="true" />
          </VButton>
        </div>
      </div>
      {tabMenu ? (
        <VDropdownMenu
          open
          position={{ x: tabMenu.x, y: tabMenu.y }}
          aria-label={copy.tabMenu}
          onOpenChange={(open) => {
            if (!open) {
              setTabMenu(null);
            }
          }}
          items={[
            {
              id: "close-current",
              label: copy.closeCurrent,
              onSelect: () => onModelChange((current) => closeChatRightRailTab(current, tabMenu.id)),
            },
            {
              id: "close-others",
              label: copy.closeOthers,
              disabled: model.tabs.length < 2,
              onSelect: () => onModelChange((current) => closeOtherChatRightRailTabs(current, tabMenu.id)),
            },
            {
              id: "close-all",
              label: copy.closeAll,
              onSelect: () => onModelChange((current) => closeAllChatRightRailTabs(current)),
            },
          ]}
        />
      ) : null}
      {searchOpen ? (
        <div className={styles.search}>
          <VInput
            aria-label={copy.search}
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
          />
          {matches.open.length === 0 && matches.closed.length === 0 ? (
            <p className={styles.note}>{copy.none}</p>
          ) : null}
          {matches.open.length > 0 ? (
            <ul className={styles.searchList}>
              {matches.open.map((tab) => (
                <li key={tab.id}>
                  <VButton
                    type="button"
                    contentLayout="plain"
                    className={styles.searchButton}
                    onClick={() => onModelChange({ ...model, activeId: tab.id })}
                  >
                    {chatRightRailTabLabel(tab, lang)}
                  </VButton>
                </li>
              ))}
            </ul>
          ) : null}
          {matches.closed.length > 0 ? (
            <>
              <p className={styles.searchHeading}>{copy.closed}</p>
              <ul className={styles.searchList}>
                {matches.closed.map((tab) => (
                  <li key={tab.id}>
                    <VButton
                      type="button"
                      contentLayout="plain"
                      className={styles.searchButton}
                      onClick={() => onModelChange(openChatRightRailTab(model, tab))}
                    >
                      {`${copy.reopen} ${chatRightRailTabLabel(tab, lang)}`}
                    </VButton>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </div>
      ) : null}
      <div className={styles.body}>
        {active && isProjectUtilityKind(active.kind) ? <ProjectUtilityPanel kind={active.kind} lang={lang} sessionId={sessionId || undefined} onOpenSession={onOpenSession} /> : null}
        {model.tabs.length === 0 ? (
          <div className={styles.launcher}>
            <VEmptyState title={copy.openTab} align="start">
              {copy.rail}
            </VEmptyState>
            <ul className={styles.launcherList}>
              {launcher.map((kind) => (
                <li key={kind}>
                  <VButton
                    type="button"
                    variant="ghost"
                    contentLayout="plain"
                    className={styles.launcherButton}
                    onClick={() => activate(kind)}
                  >
                    {chatRightRailKindLabel(kind, lang)}
                  </VButton>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {active?.kind === "review" ? (
          <div className={styles.review}>
            <ChatChangeRail
              embedded
              stacked
              className=""
              lang={lang}
              title={review.sessionTitle}
              emptyLabel={review.sessionEmptyLabel}
              paths={review.sessionPaths}
              selectedPath={review.sessionSelectedPath}
              changedPaths={review.sessionChangedPaths}
              diff={review.sessionSelectedPath ? review.diff : undefined}
              diffLoading={Boolean(review.sessionSelectedPath) && review.diffLoading}
              hasDiff={Boolean(review.sessionSelectedPath) && review.hasDiff}
              file={review.sessionSelectedPath ? review.file : null}
              fileLoading={Boolean(review.sessionSelectedPath) && review.fileLoading}
              fileError={review.sessionSelectedPath ? review.fileError : ""}
              sourceLabel={review.sourceLabel}
              onSelect={review.onSelectSessionFile}
            />
            <ChatChangeRail
              embedded
              stacked
              className=""
              lang={lang}
              title={review.gitTitle}
              emptyLabel={review.gitEmptyLabel}
              pending={review.gitPending}
              pendingLabel={review.gitPendingLabel}
              unavailableLabel={review.gitUnavailableLabel}
              paths={review.gitPaths}
              selectedPath={review.gitSelectedPath}
              changedPaths={new Set(review.gitPaths)}
              detailByPath={review.gitDetailByPath}
              diff={review.gitSelectedPath ? review.diff : undefined}
              diffLoading={Boolean(review.gitSelectedPath) && review.diffLoading}
              hasDiff={Boolean(review.gitSelectedPath) && review.hasDiff}
              file={review.gitSelectedPath ? review.file : null}
              fileLoading={Boolean(review.gitSelectedPath) && review.fileLoading}
              fileError={review.gitSelectedPath ? review.fileError : ""}
              sourceLabel={review.sourceLabel}
              onSelect={review.onSelectGitFile}
            />
          </div>
        ) : null}
        {active?.kind === "side" ? (
          <RailThread
            key={`${sessionId}:${active.id}`}
            boundSessionId={active.childSessionId || ""}
            parentSessionId={sessionId}
            createOnSend
            lang={lang}
            client={sideClient}
            initialDraft={active.draft || ""}
            initialDraftRevision={active.draftRevision ?? 0}
            pendingReadbackGeneration={active.pendingReadbackGeneration}
            autoSend={Boolean(active.sendDraft)}
            onDraftConsumed={() => {
              const tabId = active.id;
              onModelChange((current) => consumeChatRightRailSideDraft(current, tabId));
            }}
            onDraftChange={(draft, expectedRevision) => {
              const tabId = active.id;
              onModelChange((current) => updateChatRightRailSideDraft(current, tabId, draft, expectedRevision));
            }}
            onBound={(childSessionId) => {
              const tabId = active.id;
              onModelChange((current) => rememberChatRightRailSideChild(current, tabId, childSessionId));
            }}
            onSubmissionTracked={() => {
              const tabId = active.id;
              onModelChange((current) => trackChatRightRailSideSubmission(current, tabId));
            }}
            onSubmissionReadback={(generation) => {
              const tabId = active.id;
              onModelChange((current) => confirmChatRightRailSideReadback(current, tabId, generation));
            }}
          />
        ) : null}
        {active?.kind === "subagent" && active.targetId ? (
          <RailThread
            boundSessionId={active.targetId}
            parentSessionId={sessionId}
            createOnSend={false}
            lang={lang}
            client={sideClient}
            onBound={() => undefined}
          />
        ) : null}
        {active?.kind === "terminal" ? (
          <div className={styles.terminal}>
            {terminalRun && !terminalMountedInCenter ? (
              <Suspense fallback={<VEmptyState title={copy.terminalLoading} />}>
                <CliAgentRunTerminalPanel
                  run={terminalRun}
                  sourceSessionId={sessionId}
                  active
                  lang={lang}
                  onTerminalSessionChange={onTerminalSessionChange}
                />
              </Suspense>
            ) : (
              <VEmptyState title={terminalMountedInCenter ? copy.terminalCenter : copy.terminalEmpty} />
            )}
          </div>
        ) : null}
        {active?.kind === "browser" ? (
          <form
            className={styles.browser}
            onSubmit={(event) => {
              event.preventDefault();
              const next = normalizeChatRightRailBrowserUrl(browserDraft);
              if (!next) {
                setBrowserError(copy.browserInvalid);
                return;
              }
              setBrowserError("");
              onModelChange(openChatRightRailTab(model, {
                kind: "browser",
                title: chatRightRailKindLabel("browser", lang),
                url: next,
              }));
            }}
          >
            <p className={styles.note}>{copy.browserHint}</p>
            <VInput
              aria-label={copy.browserOpen}
              value={browserDraft}
              onChange={(event) => setBrowserDraft(event.target.value)}
            />
            {browserError ? <p className={styles.error} role="alert">{browserError}</p> : null}
            <VButton type="submit" density="compact">{copy.browserOpen}</VButton>
            <VButton
              type="button"
              variant="ghost"
              density="compact"
              isDisabled={!browserUrl}
              onClick={() => {
                if (browserUrl) {
                  window.open(browserUrl, "_blank", "noopener,noreferrer");
                }
              }}
            >
              {copy.browserSystem}
            </VButton>
            {browserUrl ? (
              <iframe
                className={styles.frame}
                title={browserUrl}
                src={browserUrl}
                sandbox=""
                referrerPolicy="no-referrer"
              />
            ) : null}
          </form>
        ) : null}
        {active?.kind === "devtools" ? (
          devtoolsView.empty ? <VEmptyState title={copy.devtoolsEmpty} /> : (
            <dl className={styles.metrics}>
              {devtoolsView.rows.map((row) => (
                <div key={row.id} className={styles.metric}>
                  <dt className={styles.metricLabel}>{lang === "zh" ? row.labelZh : row.labelEn}</dt>
                  <dd className={styles.metricValue}>{row.value}</dd>
                </div>
              ))}
            </dl>
          )
        ) : null}
        {active?.kind === "file" && active.filePath ? (
          <ChatRightRailFileBody
            filePath={active.filePath}
            copy={copy}
            onOpenFile={onOpenFile}
          />
        ) : null}
        {active?.kind === "directory" && sessionKind !== "child" ? (
          <ChatRightRailDirectoryBody
            sessionId={sessionId}
            lang={lang}
            copy={copy}
            onOpenItem={(item) => {
              onModelChange((current) => openChatRightRailTab(current, {
                kind: "subagent",
                title: item.title,
                targetId: item.id,
              }));
            }}
          />
        ) : null}
        {active?.kind === "directory" && sessionKind === "child" ? (
          <div className={styles.plain}>
            <p className={styles.note}>{active.title}</p>
            <p className={styles.note}>{copy.directory}</p>
            <VRouteLinkButton to="/aux" variant="ghost" density="compact">
              {copy.directoryOpen}
            </VRouteLinkButton>
          </div>
        ) : null}
        {active && (active.kind === "plan" || active.kind === "workflow" || active.kind === "trajectory" || active.kind === "bash" || (active.kind === "subagent" && !active.targetId)) ? (
          <VEmptyState title={copy.contextualEmpty} />
        ) : null}
      </div>
    </section>
  );
}
