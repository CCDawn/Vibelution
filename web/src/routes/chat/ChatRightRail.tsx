import { useQuery } from "@tanstack/react-query";
import { PanelRightClose, Plus, Search, X } from "lucide-react";
import { lazy, Suspense, useEffect, useRef, useState, type FormEvent } from "react";

import { createSessionChild, fetchSessionDetail, submitSessionMessage } from "../../api/chat";
import { queryKeys } from "../../api/queryKeys";
import type { ConversationMessage, FileContent, GitFileDiff } from "../../api/types";
import {
  VButton,
  VDropdownMenu,
  VEmptyState,
  VInput,
  VRouteLinkButton,
  VTextarea,
} from "../../components/vui";
import { ChatChangeRail } from "./ChatChangeRail";
import type { CliAgentRunView, CliAgentTerminalSession } from "./cliAgentRunModel";
import { encodeUtf8Base64 } from "./chatComposerSubmitModel";
import {
  activeChatRightRailTab,
  chatRightRailKindLabel,
  chatRightRailLauncherKinds,
  chatRightRailTabLabel,
  chatRightRailTranscriptLines,
  closeChatRightRailTab,
  consumeChatRightRailSideDraft,
  normalizeChatRightRailBrowserUrl,
  openChatRightRailTab,
  openFreshChatRightRailSideTab,
  projectChatRightRailDevtools,
  rememberChatRightRailSideChild,
  searchChatRightRailTabs,
  type ChatRightRailDevtoolsInput,
  type ChatRightRailKind,
  type ChatRightRailModel,
  type ChatRightRailTab,
} from "./chatRightRailModel";
import { isTempSessionId } from "../sessionOptimisticIds";
import styles from "./ChatRightRail.styles";

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
  sideClient?: ChatRightRailSideClient;
};

function failureText(error: unknown, fallback: string) {
  return error instanceof Error && error.message.trim() ? error.message : fallback;
}

function RailThread({
  boundSessionId,
  parentSessionId,
  createOnSend,
  lang,
  onBound,
  client,
  initialDraft = "",
  autoSend = false,
  onDraftConsumed,
}: {
  boundSessionId: string;
  parentSessionId: string;
  createOnSend: boolean;
  lang: "zh" | "en";
  onBound: (childSessionId: string) => void;
  client: ChatRightRailSideClient;
  initialDraft?: string;
  autoSend?: boolean;
  onDraftConsumed?: () => void;
}) {
  const [draft, setDraft] = useState("");
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const bootedDraft = useRef(false);
  const [pendingLine, setPendingLine] = useState("");
  const [sending, setSending] = useState(false);
  const [awaiting, setAwaiting] = useState(false);
  const [awaitingSince, setAwaitingSince] = useState(0);
  const [error, setError] = useState("");
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
    queryKey: queryKeys.sessionRightRail(boundSessionId || "none"),
    enabled: Boolean(boundSessionId),
    queryFn: ({ signal }) => client.fetchDetail(boundSessionId, signal),
    refetchInterval: () => {
      if (!awaiting) {
        return false;
      }
      if (awaitingSince > 0 && Date.now() - awaitingSince > 120_000) {
        return false;
      }
      return 1200;
    },
  });
  const detail = detailQuery.data;
  const inflight = Boolean(detail?.messages.some((message) => (
    message.role === "assistant" && (message.status === "pending" || message.status === "running")
  )) || detail?.currentPhase === "running" || detail?.currentPhase === "stopping");
  const sawAssistant = Boolean(detail?.messages.some((message) => message.role === "assistant"));
  const failed = detail?.status === "failed" || detail?.currentPhase === "failed";
  useEffect(() => {
    if (!awaiting) {
      return;
    }
    const expired = awaitingSince > 0 && Date.now() - awaitingSince > 120_000;
    if (failed || expired || (sawAssistant && !inflight)) {
      setAwaiting(false);
    }
  }, [awaiting, awaitingSince, failed, inflight, sawAssistant]);
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
      setPendingLine(trimmed);
      setDraft("");
      setAwaiting(true);
      setAwaitingSince(Date.now());
    } catch (sendError) {
      setDraft(trimmed);
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
    const text = initialDraft.trim();
    if (!text) {
      return;
    }
    bootedDraft.current = true;
    onDraftConsumed?.();
    if (autoSend && !blocked) {
      void sendTextRef.current(text);
      return;
    }
    setDraft(text);
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
          onChange={(event) => setDraft(event.target.value)}
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
  sideClient = defaultSideClient,
}: ChatRightRailProps) {
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [browserDraft, setBrowserDraft] = useState("");
  const [browserError, setBrowserError] = useState("");
  const copy = lang === "zh"
    ? {
      rail: "右侧栏",
      openTab: "打开标签页",
      add: "添加标签",
      search: "搜索标签",
      collapse: "收起侧栏",
      close: "关闭",
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
      contextualEmpty: "这场对话还没有打开这项内容",
      directory: "这项任务的详情在辅助对话中心。",
      directoryOpen: "打开辅助对话中心",
    }
    : {
      rail: "Right column",
      openTab: "Open a tab",
      add: "Add tab",
      search: "Search tabs",
      collapse: "Collapse column",
      close: "Close",
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
      contextualEmpty: "This chat has not opened that yet",
      directory: "Details for this task are in the side-chat center.",
      directoryOpen: "Open the side-chat center",
    };
  const active = activeChatRightRailTab(model);
  const launcher = chatRightRailLauncherKinds(sessionKind);
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
    <section id="chat-status-pane" className={`${styles.shell} ${className}`} aria-label={copy.rail}>
      <div className={styles.toolbar}>
        <div role="tablist" aria-label={copy.rail} className={styles.tabs}>
          {model.tabs.map((tab) => {
            const selected = tab.id === model.activeId;
            const label = chatRightRailTabLabel(tab, lang);
            return (
              <div
                key={tab.id}
                role="tab"
                aria-selected={selected}
                className={selected ? `${styles.tab} ${styles.tabActive}` : styles.tab}
              >
                <VButton
                  type="button"
                  contentLayout="plain"
                  className={styles.tabLabel}
                  onClick={() => onModelChange({ ...model, activeId: tab.id })}
                >
                  {label}
                </VButton>
                <VButton
                  type="button"
                  isIconOnly
                  aria-label={`${copy.close}${label}`}
                  className={styles.tabClose}
                  onClick={() => onModelChange(closeChatRightRailTab(model, tab.id))}
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
            boundSessionId={active.childSessionId || ""}
            parentSessionId={sessionId}
            createOnSend
            lang={lang}
            client={sideClient}
            initialDraft={active.draft || ""}
            autoSend={Boolean(active.sendDraft)}
            onDraftConsumed={() => {
              const tabId = active.id;
              onModelChange((current) => consumeChatRightRailSideDraft(current, tabId));
            }}
            onBound={(childSessionId) => {
              const tabId = active.id;
              onModelChange((current) => rememberChatRightRailSideChild(current, tabId, childSessionId));
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
          <div className={styles.plain}>
            <p className={styles.note}>{active.filePath}</p>
            <VButton type="button" density="compact" onClick={() => onOpenFile(active.filePath || "")}>
              {copy.fileOpen}
            </VButton>
          </div>
        ) : null}
        {active?.kind === "directory" ? (
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
