import {
  ArrowDown,
  BrainCircuit,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDot,
  ExternalLink,
  LoaderCircle,
  Pencil,
  Search,
  Sparkles,
  TerminalSquare,
  Wrench,
} from "lucide-react";
import { ReactNode, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import {
  ChatNextStateSignalSummary,
  ConversationMessage,
  MentalStateSnapshot,
  SessionTurnError,
} from "../../api/types";
import { useAppI18n } from "../../i18n/useAppI18n";
import { shouldSubmitComposerOnKeydown } from "./composerShortcuts";
import {
  buildConversationOperationGroups,
  ConversationOperation,
  ConversationOperationKind,
} from "./conversationOperations";
import {
  hasResponseBlock,
  hasUserContent,
} from "./messageSections";
import { parseResponseSegments, ResponseSegment } from "./messageResponseSegments";
import styles from "./ConversationView.module.css";

const RUNNING_OPERATION_STATUSES = new Set(["queued", "pending", "running", "thinking", "tooling", "answering"]);

type MarkdownBlock =
  | { type: "heading"; level: 1 | 2 | 3 | 4; content: string }
  | { type: "paragraph"; content: string }
  | { type: "unorderedList"; items: string[] }
  | { type: "orderedList"; items: string[] }
  | { type: "divider" };

export function buildTimelineScrollSignal(messages: ConversationMessage[]) {
  return messages
    .map((message) => {
      const mentalSnapshot = message.mentalSnapshot;
      const mentalSignal = mentalSnapshot
        ? [
            mentalSnapshot.mood,
            mentalSnapshot.feeling,
            mentalSnapshot.whisper,
            mentalSnapshot.summary,
            mentalSnapshot.cognitiveState,
            mentalSnapshot.confidence,
            mentalSnapshot.sampleSize,
            mentalSnapshot.interventionCount,
            mentalSnapshot.updatedAt,
            mentalSnapshot.source,
            mentalSnapshot.intervention ?? "",
            JSON.stringify(mentalSnapshot.metrics ?? {}),
          ].join(":")
        : "";
      const toolSignal = (message.toolCalls ?? [])
        .map((toolCall) => [toolCall.name, toolCall.status, toolCall.summary ?? ""].join(":"))
        .join("|");
      return [
        message.id,
        message.content.length,
        message.thought?.length ?? 0,
        toolSignal,
        mentalSignal,
        message.streaming ? 1 : 0,
      ].join(":");
    })
    .join("|");
}

function isBusyConversationPhase(phase: string) {
  return ["queued", "running", "stopping"].includes(String(phase || "").trim().toLowerCase());
}

function userAvatarSymbol(preset: string | undefined, label: string) {
  const normalized = String(preset ?? "").trim().toLowerCase();
  if (normalized === "spark") {
    return "*";
  }
  if (normalized === "codex") {
    return "C";
  }
  if (normalized === "minimal") {
    return ".";
  }
  return label.trim().slice(0, 1).toUpperCase() || "U";
}

export function shouldShowNextStateSignalInConversation(
  signal: ChatNextStateSignalSummary,
  phase: string,
) {
  if (signal.kind === "user_continues") {
    return isBusyConversationPhase(phase);
  }
  return true;
}

type ConversationViewProps = {
  sessionId: string;
  title: string;
  phase: string;
  messages: ConversationMessage[];
  className?: string;
  density?: "default" | "compact";
  eyebrowLabel?: string;
  assistantDisplayName?: string;
  userDisplayName?: string;
  userAvatarPreset?: string;
  userAvatarImageUrl?: string;
  taskSummary?: string;
  defaultFileContext: string;
  summaryItems?: Array<{
    label: string;
    value: string;
  }>;
  stats?: Array<{
    label: string;
    value: string | number;
  }>;
  headerActions?: ReactNode;
  supplementalContent?: ReactNode;
  showHeader?: boolean;
  showSessionOverview?: boolean;
  autoScrollToLatest?: boolean;
  composerValue: string;
  composerPlaceholder: string;
  composerDisabled: boolean;
  composerActionDisabled?: boolean;
  composerActionMode?: "send" | "stop";
  composerPending: boolean;
  composerError?: string;
  turnError?: SessionTurnError | null;
  nextStateSignals?: ChatNextStateSignalSummary[];
  submitLabel?: string;
  submitPendingLabel?: string;
  stopLabel?: string;
  stopPendingLabel?: string;
  editingMessageId?: string;
  editUserMessageLabel?: string;
  editUserMessageDisabled?: boolean;
  composerModeNotice?: string;
  cancelComposerModeLabel?: string;
  onComposerChange: (value: string) => void;
  onEditUserMessage?: (message: ConversationMessage) => void;
  onCancelComposerMode?: () => void;
  onSubmit: () => void;
  onStop?: () => void;
};

export function ConversationView({
  sessionId,
  title,
  phase,
  messages,
  className,
  density = "default",
  eyebrowLabel,
  assistantDisplayName,
  userDisplayName,
  userAvatarPreset,
  userAvatarImageUrl,
  taskSummary,
  defaultFileContext,
  summaryItems,
  stats,
  headerActions,
  supplementalContent,
  showHeader = true,
  showSessionOverview = true,
  autoScrollToLatest = true,
  composerValue,
  composerPlaceholder,
  composerDisabled,
  composerActionDisabled,
  composerActionMode,
  composerPending,
  composerError,
  turnError,
  nextStateSignals = [],
  submitLabel,
  submitPendingLabel,
  stopLabel,
  stopPendingLabel,
  editingMessageId,
  editUserMessageLabel,
  editUserMessageDisabled,
  composerModeNotice,
  cancelComposerModeLabel,
  onComposerChange,
  onEditUserMessage,
  onCancelComposerMode,
  onSubmit,
  onStop,
}: ConversationViewProps) {
  const { lang, t, statusLabel } = useAppI18n();
  const timelineRef = useRef<HTMLDivElement | null>(null);
  const composerInputRef = useRef<HTMLTextAreaElement | null>(null);
  const initializedSessionRef = useRef("");
  const atBottomRef = useRef(true);
  const lastComposerFocusSignalRef = useRef("");
  const [sectionExpansion, setSectionExpansion] = useState<Record<string, Record<string, boolean>>>({});
  const [isAtBottom, setIsAtBottom] = useState(true);
  const previousStreamingRef = useRef<Record<string, boolean>>({});
  const resolvedActionMode = composerActionMode ?? "send";
  const resolvedActionDisabled =
    composerActionDisabled
    ?? (resolvedActionMode === "stop" ? composerDisabled : composerDisabled || !composerValue.trim());
  const resolvedActionLabel =
    resolvedActionMode === "stop" ? (stopLabel ?? t("stop")) : (submitLabel ?? t("send"));
  const resolvedPendingLabel =
    resolvedActionMode === "stop"
      ? (stopPendingLabel ?? t("stopPending"))
      : (submitPendingLabel ?? t("sendPending"));
  const assistantLabel = assistantDisplayName?.trim() || t("agent");
  const userLabel = userDisplayName?.trim() || t("operator");
  const userAvatarLabel = userAvatarSymbol(userAvatarPreset, userLabel);
  const handlePrimaryAction = resolvedActionMode === "stop" ? onStop ?? onSubmit : onSubmit;
  const timestampFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }),
    [lang],
  );

  const latestUserMessage = useMemo(
    () =>
      [...messages]
        .reverse()
        .find((message) => message.role === "user")?.content ?? "",
    [messages],
  );
  const latestUserMessageId = useMemo(
    () =>
      [...messages]
        .reverse()
        .find((message) => message.role === "user")?.id ?? "",
    [messages],
  );
  const lastMessageTimestamp = useMemo(
    () => [...messages].reverse().find((message) => message.timestamp)?.timestamp ?? "",
    [messages],
  );

  const taskFocus = compactPreview(taskSummary || latestUserMessage || title);
  const fileContext = defaultFileContext || "workspace";
  const resolvedSummaryItems = summaryItems ?? [
    { label: t("taskFocus"), value: taskFocus },
    { label: t("fileContext"), value: fileContext },
    { label: t("status"), value: statusLabel(phase) },
    { label: t("lastUpdated"), value: lastMessageTimestamp ? formatTimestamp(lastMessageTimestamp) : "--" },
  ];
  const resolvedStats = stats ?? [];
  const visibleNextStateSignals = useMemo(
    () =>
      nextStateSignals
        .filter((signal) => shouldShowNextStateSignalInConversation(signal, phase))
        .slice(-5)
        .reverse(),
    [nextStateSignals, phase],
  );
  const [nextStateSignalsExpanded, setNextStateSignalsExpanded] = useState(false);
  const latestToolCalls = useMemo(
    () =>
      [...messages]
        .reverse()
        .find((message) => (message.toolCalls?.length ?? 0) > 0)?.toolCalls ?? [],
    [messages],
  );
  const timelineScrollSignal = useMemo(() => buildTimelineScrollSignal(messages), [messages]);
  const hasSessionMeta = resolvedStats.length > 0 || latestToolCalls.length > 0;
  const hasMetaSection = showSessionOverview && (hasSessionMeta || Boolean(supplementalContent));
  const operationLabels = useMemo(
    () => ({
      thought: t("thoughtProcess"),
      mental: t("mentalProcess"),
    }),
    [t],
  );

  function formatTimestamp(timestamp: string) {
    if (!timestamp) {
      return "";
    }
    const value = new Date(timestamp);
    if (Number.isNaN(value.getTime())) {
      return timestamp;
    }
    return timestampFormatter.format(value);
  }

  function compactPreview(value: string, maxLength = 180) {
    const normalized = value.replace(/\s+/g, " ").trim();
    if (!normalized) {
      return "";
    }
    if (normalized.length <= maxLength) {
      return normalized;
    }
    return `${normalized.slice(0, maxLength - 1).trimEnd()}...`;
  }

  useLayoutEffect(() => {
    const timeline = timelineRef.current;
    if (!timeline) {
      return;
    }
    if (initializedSessionRef.current !== sessionId) {
      initializedSessionRef.current = sessionId;
      timeline.scrollTop = timeline.scrollHeight;
      atBottomRef.current = true;
      setIsAtBottom(true);
      return;
    }
    if (autoScrollToLatest && atBottomRef.current) {
      timeline.scrollTop = timeline.scrollHeight;
      setIsAtBottom(true);
    }
  }, [autoScrollToLatest, sessionId, timelineScrollSignal]);

  useEffect(() => {
    const timeline = timelineRef.current;
    if (!timeline) {
      return;
    }
    const handleScroll = () => {
      const distance = timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight;
      const nextAtBottom = distance < 16;
      atBottomRef.current = nextAtBottom;
      setIsAtBottom(nextAtBottom);
    };
    handleScroll();
    timeline.addEventListener("scroll", handleScroll);
    return () => timeline.removeEventListener("scroll", handleScroll);
  }, [sessionId]);

  useEffect(() => {
    const focusSignal = String(editingMessageId || "").trim();
    if (!focusSignal || focusSignal === lastComposerFocusSignalRef.current || composerDisabled) {
      return;
    }
    lastComposerFocusSignalRef.current = focusSignal;
    const input = composerInputRef.current;
    if (!input) {
      return;
    }
    input.focus();
    const cursorPosition = input.value.length;
    input.setSelectionRange(cursorPosition, cursorPosition);
  }, [composerDisabled, editingMessageId]);

  useEffect(() => {
    const previous = previousStreamingRef.current;
    const nextStreaming: Record<string, boolean> = {};
    let shouldCollapse = false;
    for (const message of messages) {
      if (message.role !== "assistant") {
        continue;
      }
      nextStreaming[message.id] = Boolean(message.streaming);
      if (previous[message.id] && !message.streaming) {
        shouldCollapse = true;
      }
    }
    previousStreamingRef.current = nextStreaming;
    if (!shouldCollapse) {
      return;
    }
    setSectionExpansion((current) => {
      const next = { ...current };
      for (const message of messages) {
        if (message.role !== "assistant" || message.streaming) {
          continue;
        }
        next[message.id] = {
          ...(next[message.id] ?? {}),
          thought: false,
          mental: false,
          tools: false,
        };
      }
      return next;
    });
  }, [messages]);

  function cognitiveStateLabel(snapshot: MentalStateSnapshot | undefined) {
    const value = String(snapshot?.cognitiveState ?? "").trim().toLowerCase() || "unknown";
    const keyMap = {
      unknown: "mentalCognitiveState_unknown",
      normal: "mentalCognitiveState_normal",
      productive: "mentalCognitiveState_productive",
      looping: "mentalCognitiveState_looping",
      thrashing: "mentalCognitiveState_thrashing",
      tunnel_vision: "mentalCognitiveState_tunnel_vision",
      disoriented: "mentalCognitiveState_disoriented",
    } as const;
    const key = keyMap[value as keyof typeof keyMap];
    return key ? t(key) : snapshot?.cognitiveState ?? "";
  }

  function getExpansionState(messageId: string, section: string, defaultExpanded: boolean) {
    if (section === "response") {
      return sectionExpansion[messageId]?.[section] ?? true;
    }
    return sectionExpansion[messageId]?.[section] ?? defaultExpanded;
  }

  function toggleSection(messageId: string, section: string, defaultExpanded: boolean) {
    setSectionExpansion((current) => ({
      ...current,
      [messageId]: {
        ...(current[messageId] ?? {}),
        [section]: !getExpansionState(messageId, section, defaultExpanded),
      },
    }));
  }

  function scrollToBottom() {
    const timeline = timelineRef.current;
    if (!timeline) {
      return;
    }
    timeline.scrollTo({ top: timeline.scrollHeight, behavior: "smooth" });
    atBottomRef.current = true;
    setIsAtBottom(true);
  }

  function formatDuration(seconds: number | null) {
    if (seconds === null || !Number.isFinite(seconds) || seconds < 0) {
      return "";
    }
    if (seconds < 10) {
      return `${seconds.toFixed(1)}s`;
    }
    return `${Math.round(seconds)}s`;
  }

  function operationIcon(kind: ConversationOperationKind, label: string) {
    const normalized = label.trim().toLowerCase();
    if (kind === "thought") {
      return <Sparkles size={17} />;
    }
    if (kind === "mental") {
      return <BrainCircuit size={17} />;
    }
    if (normalized.includes("search") || normalized.includes("搜索")) {
      return <Search size={17} />;
    }
    if (normalized.includes("http") || normalized.includes("访问") || normalized.includes("open")) {
      return <ExternalLink size={17} />;
    }
    if (
      normalized.includes("exec")
      || normalized.includes("command")
      || normalized.includes("shell")
      || normalized.includes("powershell")
      || normalized.includes("npm")
      || normalized.includes("pytest")
      || normalized.includes("命令")
    ) {
      return <TerminalSquare size={17} />;
    }
    return <Wrench size={17} />;
  }

  function operationStatusIcon(operation: ConversationOperation) {
    const status = operation.status.trim().toLowerCase();
    if (["done", "success", "completed", "succeeded"].includes(status)) {
      return <CheckCircle2 size={14} />;
    }
    if (RUNNING_OPERATION_STATUSES.has(status)) {
      return <LoaderCircle className={styles.statusSpinner} size={14} />;
    }
    return <CircleDot size={14} />;
  }

  function operationLabel(operation: ConversationOperation) {
    if (operation.kind !== "tool") {
      return operation.label;
    }
    const normalized = operation.label.trim();
    if (!normalized) {
      return t("toolProcess");
    }
    if (
      normalized.startsWith("搜索")
      || normalized.startsWith("访问")
      || normalized.toLowerCase().startsWith("search ")
      || normalized.toLowerCase().startsWith("open ")
    ) {
      return normalized;
    }
    return normalized;
  }

  function operationGroupTitle(kind: ConversationOperationKind, count: number) {
    if (kind === "thought") {
      return t("thoughtProcess");
    }
    if (kind === "mental") {
      return t("mentalProcess");
    }
    return `${t("toolProcess")} ${count}`;
  }

  function renderOperationTimeline(operations: ConversationOperation[]) {
    return (
      <div className={styles.operationTimeline}>
        {operations.map((operation) => {
          const duration = formatDuration(operation.durationSeconds);
          return (
            <div key={operation.id} className={styles.operationItem}>
              <span className={`${styles.operationIcon} ${styles[`operationIcon_${operation.kind}`]}`}>
                {operationIcon(operation.kind, operation.label)}
              </span>
              <div className={styles.operationText}>
                <span className={styles.operationName}>{operationLabel(operation)}</span>
                {operation.summary ? (
                  <span className={styles.operationSummaryText}>{operation.summary}</span>
                ) : null}
              </div>
              <span className={styles.operationStatus}>
                {operationStatusIcon(operation)}
                <span>{statusLabel(operation.status)}</span>
              </span>
              {duration ? <span className={styles.operationDuration}>{duration}</span> : null}
              <ChevronRight className={styles.operationChevron} size={16} />
            </div>
          );
        })}
      </div>
    );
  }

  function renderOperationGroup(
    messageId: string,
    section: "thought" | "mental" | "tools",
    operations: ConversationOperation[],
    defaultExpanded: boolean,
  ) {
    if (operations.length === 0) {
      return null;
    }
    const expanded = getExpansionState(messageId, section, defaultExpanded);
    const kind = operations[0]?.kind ?? "tool";
    const title = operationGroupTitle(kind, operations.length);
    const isRunning = operations.some((operation) => {
      const status = operation.status.trim().toLowerCase();
      return RUNNING_OPERATION_STATUSES.has(status);
    });
    const toggleTitle = expanded
      ? section === "thought"
        ? t("thoughtProcessVisible")
        : section === "mental"
          ? t("mentalProcessVisible")
          : t("toolProcessVisible")
      : section === "thought"
        ? t("thoughtProcessHidden")
        : section === "mental"
          ? t("mentalProcessHidden")
          : t("toolProcessHidden");
    return (
      <section className={styles.operationGroup}>
        <button
          type="button"
          className={styles.operationSummary}
          aria-expanded={expanded}
          onClick={() => toggleSection(messageId, section, defaultExpanded)}
          title={toggleTitle}
        >
          {operationIcon(kind, title)}
          <span>{title}</span>
          {isRunning ? <LoaderCircle className={styles.statusSpinner} size={14} /> : null}
          {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </button>
        {expanded ? renderOperationTimeline(operations) : null}
      </section>
    );
  }

  function responseSegmentLabel(segment: ResponseSegment) {
    switch (segment.kind) {
      case "status":
        return t("responseSegmentStatus");
      case "commit":
        return t("responseSegmentCommit");
      case "verification":
        return t("responseSegmentVerification");
      case "code":
        return segment.language || t("responseSegmentCode");
      case "files":
        return t("responseSegmentFiles");
      case "logs":
        return t("responseSegmentLogs");
      case "answer":
      default:
        return t("responseSegmentAnswer");
    }
  }

  function renderResponseSegment(segment: ResponseSegment) {
    const label = responseSegmentLabel(segment);
    const isCodeLike = segment.kind === "code"
      || Boolean(segment.language)
      || (["commit", "verification", "logs"].includes(segment.kind) && segment.content.includes("\n"));
    return (
      <section
        key={segment.id}
        className={`${styles.responseSegment} ${styles[`responseSegment_${segment.kind}`]}`}
      >
        <div className={styles.responseSegmentHeader}>
          <span className={styles.responseSegmentLabel}>{label}</span>
          {segment.language && segment.kind !== "code" ? (
            <span className={styles.responseSegmentMeta}>{segment.language}</span>
          ) : null}
        </div>
        {isCodeLike ? (
          <pre className={styles.responseSegmentPre}>
            <code>{segment.content}</code>
          </pre>
        ) : (
          renderResponseText(segment.content)
        )}
      </section>
    );
  }

  function renderResponseText(content: string) {
    const blocks = parseMarkdownBlocks(content);
    if (blocks.length === 0) {
      return null;
    }
    return (
      <div className={styles.markdownBody}>
        {blocks.map((block, index) => renderMarkdownBlock(block, index))}
      </div>
    );
  }

  function renderMarkdownBlock(block: MarkdownBlock, index: number) {
    if (block.type === "heading") {
      const HeadingTag = block.level <= 2 ? "h3" : "h4";
      return (
        <HeadingTag
          key={`heading-${index}-${block.content}`}
          className={`${styles.markdownHeading} ${styles[`markdownHeading${block.level}`]}`}
        >
          {renderInlineContent(block.content)}
        </HeadingTag>
      );
    }
    if (block.type === "divider") {
      return <hr key={`divider-${index}`} className={styles.markdownDivider} />;
    }
    if (block.type === "unorderedList") {
      return (
        <ul key={`ul-${index}`} className={styles.responseSegmentList}>
          {block.items.map((item, itemIndex) => (
            <li key={`${item}-${itemIndex}`}>{renderInlineContent(item)}</li>
          ))}
        </ul>
      );
    }
    if (block.type === "orderedList") {
      return (
        <ol key={`ol-${index}`} className={styles.responseSegmentList}>
          {block.items.map((item, itemIndex) => (
            <li key={`${item}-${itemIndex}`}>{renderInlineContent(item)}</li>
          ))}
        </ol>
      );
    }
    return (
      <p key={`paragraph-${index}`} className={styles.messageBody}>
        {renderInlineContent(block.content)}
      </p>
    );
  }

  function renderInlineContent(content: string) {
    const parts = content.split(/(`[^`\n]+`)/g).filter((part) => part.length > 0);
    return parts.map((part, index) => {
      if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
        return (
          <code key={`${part}-${index}`} className={styles.inlineCode}>
            {part.slice(1, -1)}
          </code>
        );
      }
      return part;
    });
  }

  function parseMarkdownBlocks(content: string): MarkdownBlock[] {
    const lines = String(content ?? "").replace(/\r\n/g, "\n").split("\n");
    const blocks: MarkdownBlock[] = [];
    let paragraphLines: string[] = [];

    function flushParagraph() {
      const paragraph = paragraphLines.join("\n").trim();
      if (paragraph) {
        blocks.push({ type: "paragraph", content: paragraph });
      }
      paragraphLines = [];
    }

    for (let index = 0; index < lines.length; index += 1) {
      const line = lines[index];
      const trimmed = line.trim();
      if (!trimmed) {
        flushParagraph();
        continue;
      }

      const heading = trimmed.match(/^(#{1,4})\s+(.+?)\s*#*$/);
      if (heading) {
        flushParagraph();
        blocks.push({
          type: "heading",
          level: Math.min(4, heading[1].length) as 1 | 2 | 3 | 4,
          content: heading[2].trim(),
        });
        continue;
      }

      if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
        flushParagraph();
        blocks.push({ type: "divider" });
        continue;
      }

      const unorderedMatch = trimmed.match(/^[-*]\s+(.+)$/);
      if (unorderedMatch) {
        flushParagraph();
        const items = [unorderedMatch[1].trim()];
        for (let nextIndex = index + 1; nextIndex < lines.length; nextIndex += 1) {
          const nextMatch = lines[nextIndex].trim().match(/^[-*]\s+(.+)$/);
          if (!nextMatch) {
            break;
          }
          items.push(nextMatch[1].trim());
          index = nextIndex;
        }
        blocks.push({ type: "unorderedList", items });
        continue;
      }

      const orderedMatch = trimmed.match(/^\d+[.)]\s+(.+)$/);
      if (orderedMatch) {
        flushParagraph();
        const items = [orderedMatch[1].trim()];
        for (let nextIndex = index + 1; nextIndex < lines.length; nextIndex += 1) {
          const nextMatch = lines[nextIndex].trim().match(/^\d+[.)]\s+(.+)$/);
          if (!nextMatch) {
            break;
          }
          items.push(nextMatch[1].trim());
          index = nextIndex;
        }
        blocks.push({ type: "orderedList", items });
        continue;
      }

      paragraphLines.push(line);
    }

    flushParagraph();
    return blocks;
  }

  return (
    <div
      className={[
        styles.surface,
        density === "compact" ? styles.surfaceCompact : "",
        className ?? "",
      ].filter(Boolean).join(" ")}
    >
      {showHeader ? (
        <div className={styles.header}>
          <div>
            <p className={styles.eyebrow}>{eyebrowLabel ?? t("agentSession")}</p>
            <h2 className={styles.title}>{title}</h2>
          </div>
          <div className={styles.headerControls}>
            {headerActions}
            <span className={styles.phase}>{statusLabel(phase)}</span>
          </div>
        </div>
      ) : null}

      {showSessionOverview && resolvedSummaryItems.length > 0 ? (
        <div className={styles.summaryGrid}>
          {resolvedSummaryItems.map((item) => (
            <section key={item.label} className={styles.summaryCard}>
              <p className={styles.summaryLabel}>{item.label}</p>
              <p className={styles.summaryValue} title={item.value}>
                {item.value}
              </p>
            </section>
          ))}
        </div>
      ) : null}

      {hasMetaSection ? (
        <div className={styles.metaStack}>
          {hasSessionMeta ? (
            <div className={styles.sessionMeta}>
              {resolvedStats.length > 0 ? (
                <div className={styles.statRow}>
                  {resolvedStats.map((item) => (
                    <span key={item.label} className={styles.statPill}>
                      {item.label} {item.value}
                    </span>
                  ))}
                </div>
              ) : null}
              {latestToolCalls.length > 0 ? (
                <div className={styles.toolsBlock}>
                  <span className={styles.toolsLabel}>{t("activeToolsLabel")}</span>
                  <div className={styles.toolRow}>
                    {latestToolCalls.map((toolCall, index) => (
                      <span key={`${toolCall.name}-${index}`} className={styles.toolPill}>
                        {toolCall.name} · {statusLabel(toolCall.status)}
                      </span>
                    ))}
                  </div>
                </div>
              ) : null}
              {lastMessageTimestamp ? (
                <p className={styles.updateLine}>
                  {t("lastUpdated")} {formatTimestamp(lastMessageTimestamp)}
                </p>
              ) : null}
            </div>
          ) : null}

          {supplementalContent ? <div className={styles.supplemental}>{supplementalContent}</div> : null}
        </div>
      ) : null}

      <div ref={timelineRef} className={styles.timeline}>
        {messages.length === 0 ? (
          <div className={styles.emptyState}>{t("sessionNoMessages")}</div>
        ) : (
          messages.map((message) => {
            const operationGroups = buildConversationOperationGroups(message, operationLabels);
            const responseSegments = parseResponseSegments(message.content);
            const responseExpanded = getExpansionState(message.id, "response", true);
            const isEditingMessage = message.role === "user" && message.id === editingMessageId;
            const turnClassName = [
              message.role === "assistant" ? styles.assistantTurn : styles.userTurn,
              isEditingMessage ? styles.turnEditing : "",
            ].filter(Boolean).join(" ");
            const editDisabled = Boolean(editUserMessageDisabled);
            return (
              <article
                key={message.id}
                className={turnClassName}
              >
                <div className={styles.turnAvatar} aria-hidden="true">
                  {message.role === "assistant" ? (
                    <Sparkles size={18} />
                  ) : userAvatarImageUrl ? (
                    <img src={userAvatarImageUrl} alt="" className={styles.turnAvatarImage} />
                  ) : (
                    userAvatarLabel
                  )}
                </div>
            <div className={styles.turnContent}>
                  <div className={styles.turnMeta}>
                    <div className={styles.turnMetaIdentity}>
                      <span className={styles.turnSpeaker}>
                        {message.role === "assistant" ? assistantLabel : userLabel}
                      </span>
                      {isEditingMessage ? <span className={styles.turnEditBadge}>{t("editMessage")}</span> : null}
                    </div>
                    <span className={styles.turnMetaActions}>
                      {message.timestamp ? <span>{formatTimestamp(message.timestamp)}</span> : null}
                      {message.role === "user" && message.id === latestUserMessageId && onEditUserMessage ? (
                        <button
                          type="button"
                          className={
                            isEditingMessage
                              ? `${styles.turnIconButton} ${styles.turnIconButtonActive}`
                              : styles.turnIconButton
                          }
                          onClick={() => onEditUserMessage(message)}
                          disabled={editDisabled}
                          aria-pressed={isEditingMessage}
                          title={editDisabled ? composerPlaceholder : editUserMessageLabel ?? t("editMessage")}
                          aria-label={editUserMessageLabel ?? t("editMessage")}
                        >
                          <Pencil size={14} />
                        </button>
                      ) : null}
                    </span>
                  </div>

                  {hasUserContent(message) ? (
                    <div className={styles.userMessageBody}>{renderResponseText(message.content)}</div>
                  ) : null}

                  {renderOperationGroup(message.id, "thought", operationGroups.thoughts, Boolean(message.streaming))}
                  {renderOperationGroup(message.id, "mental", operationGroups.mental, Boolean(message.streaming))}
                  {renderOperationGroup(message.id, "tools", operationGroups.tools, Boolean(message.streaming))}

                  {hasResponseBlock(message) ? (
                    <section className={styles.responseSection}>
                      <button
                        type="button"
                        className={styles.responseToggle}
                        aria-expanded={responseExpanded}
                        onClick={() => toggleSection(message.id, "response", true)}
                        title={responseExpanded ? t("responseHidden") : t("responseVisible")}
                      >
                        {responseExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                        <span>{t("responseLabel")}</span>
                        {message.streaming ? <LoaderCircle className={styles.statusSpinner} size={14} /> : null}
                      </button>
                      {responseExpanded ? (
                        <div className={styles.responseBody}>
                          {responseSegments.map(renderResponseSegment)}
                        </div>
                      ) : null}
                    </section>
                  ) : null}
                </div>
              </article>
            );
          })
        )}
      </div>

      {!isAtBottom ? (
        <button
          type="button"
          className={styles.backToBottomButton}
          onClick={scrollToBottom}
          title={t("backToBottom")}
          aria-label={t("backToBottom")}
        >
          <ArrowDown size={16} />
          <span>{t("backToBottom")}</span>
        </button>
      ) : null}

      {turnError?.message ? (
        <div className={styles.turnError} role="status" aria-live="polite">
          <div className={styles.turnErrorText}>
            <span className={styles.turnErrorLabel}>{t("turnErrorLabel")}</span>
            <span>{turnError.message}</span>
          </div>
          {turnError.errorType ? <span className={styles.turnErrorType}>{turnError.errorType}</span> : null}
        </div>
      ) : null}

      {visibleNextStateSignals.length > 0 ? (
        <section className={styles.nextStateSignals} aria-label={t("nextStateSignalsLabel")}>
          <button
            type="button"
            className={styles.nextStateSignalsToggle}
            aria-expanded={nextStateSignalsExpanded}
            onClick={() => setNextStateSignalsExpanded((current) => !current)}
            title={nextStateSignalsExpanded ? t("nextStateSignalsVisible") : t("nextStateSignalsHidden")}
          >
            {nextStateSignalsExpanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
            <span>{t("nextStateSignalsLabel")}</span>
            <span className={styles.nextStateSignalsCount}>{visibleNextStateSignals.length}</span>
            {!nextStateSignalsExpanded ? (
              <span className={styles.nextStateSignalsSummary}>{visibleNextStateSignals[0].summary}</span>
            ) : null}
          </button>
          {nextStateSignalsExpanded ? (
            <div className={styles.nextStateSignalList}>
              {visibleNextStateSignals.map((signal) => (
                <div key={signal.signalId || `${signal.turnId}-${signal.kind}`} className={styles.nextStateSignalItem}>
                  <div className={styles.nextStateSignalMeta}>
                    <span className={styles.nextStateSignalKind}>{signal.kind}</span>
                    <span>{signal.source}</span>
                    {signal.createdAt ? <span>{formatTimestamp(signal.createdAt)}</span> : null}
                    {signal.turnId ? <span>{signal.turnId}</span> : null}
                  </div>
                  <p className={styles.nextStateSignalText}>{signal.summary}</p>
                  {signal.relatedEventCode ? (
                    <span className={styles.nextStateSignalEvent}>{signal.relatedEventCode}</span>
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      <div className={styles.composer}>
        <div className={styles.composerField}>
          {composerError ? <p className={styles.composerError}>{composerError}</p> : null}
          {composerModeNotice ? (
            <div className={styles.composerModeNotice} role="status">
              <span className={styles.composerModeNoticeIcon} aria-hidden="true">
                <Pencil size={14} />
              </span>
              <span>{composerModeNotice}</span>
              {onCancelComposerMode ? (
                <button type="button" onClick={onCancelComposerMode}>
                  {cancelComposerModeLabel ?? t("cancelEditMessage")}
                </button>
              ) : null}
            </div>
          ) : null}
          <textarea
            ref={composerInputRef}
            className={styles.input}
            value={composerValue}
            disabled={composerDisabled}
            placeholder={composerPlaceholder}
            onChange={(event) => onComposerChange(event.target.value)}
            onKeyDown={(event) => {
              if (
                shouldSubmitComposerOnKeydown({
                  key: event.key,
                  shiftKey: event.shiftKey,
                  ctrlKey: event.ctrlKey,
                  metaKey: event.metaKey,
                  altKey: event.altKey,
                  isComposing: event.nativeEvent.isComposing,
                })
              ) {
                event.preventDefault();
                if (
                  resolvedActionMode === "send"
                  && !resolvedActionDisabled
                  && composerValue.trim()
                ) {
                  onSubmit();
                }
              }
            }}
          />
        </div>
        <button
          className={
            resolvedActionMode === "stop" ? `${styles.sendButton} ${styles.stopButton}` : styles.sendButton
          }
          disabled={resolvedActionDisabled}
          type="button"
          onClick={handlePrimaryAction}
        >
          {composerPending ? resolvedPendingLabel : resolvedActionLabel}
        </button>
      </div>
    </div>
  );
}
