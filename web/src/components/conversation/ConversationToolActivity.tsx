import {
  Bot,
  Check,
  CircleAlert,
  CircleSlash,
  Copy,
  FileSearch,
  MonitorSmartphone,
  PencilLine,
  TerminalSquare,
  type LucideIcon,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

import { VNativeButton, VTooltip } from "../vui";
import "./ConversationToolActivity.css";
import type { CodexTranscriptCell } from "./codexTranscriptCells";
import {
  codexTranscriptToolDurationSeconds,
  codexTranscriptToolArguments,
  codexTranscriptToolRawName,
  formatCodexTranscriptDuration,
  type CodexTranscriptToolActivity,
} from "./conversationToolActivityModel";
import {
  buildConversationToolCategoryGroups,
  conversationToolPersistKey,
  conversationToolCategoryGroupCountLabel,
  type ConversationToolCategoryGroupItem,
  type ConversationToolCategorizedItem,
} from "./conversationToolCategoryGrouping";
import {
  conversationAgentDisplayName,
  conversationToolCategoryForCell,
  conversationToolCategoryLabel,
  type ConversationToolCategory,
} from "./conversationToolCategory";
import {
  conversationSubagentAccentStyle,
  conversationSubagentColorBucket,
} from "./conversationSubagentColor";
import {
  buildCodexToolActivityPills,
  completedToolPresentationSummary,
  type CodexToolActivityPills,
  type ConversationToolPresentationLanguage,
} from "./conversationToolPresentation";
import {
  conversationToolChecklistModel,
  type ConversationToolChecklistModel,
} from "./conversationToolChecklistModel";
import { ConversationToolChecklist } from "./ConversationToolChecklist";
import {
  buildConversationToolActivityDigestPresentation,
  buildConversationToolActivityPresentation,
  conversationToolActivityHasNonzeroTerminalExit,
  conversationToolActivityIsNoMatchTerminalExit,
  conversationToolActivityRendererForCell,
  conversationToolActivityTerminalExitCode,
  type ConversationToolActivityPresentationItem,
} from "./conversationToolActivityPresentation";
import {
  ConversationToolActivityPills,
  toolActivityAriaTitle,
} from "./ConversationToolActivityPills";
import {
  readToolRowOpen,
  setToolRowOpen,
} from "./conversationToolExpandPersistence";
import styles from "./ConversationToolActivity.styles";

type ConversationToolActivityProps = {
  activity: CodexTranscriptToolActivity;
  language: ConversationToolPresentationLanguage;
  renderToolDetails: (cell: CodexTranscriptCell, detailsId: string) => ReactNode;
  /** True when the cell has no expandable detail: render the row without a toggle. */
  toolDetailIsEmpty?: (cell: CodexTranscriptCell) => boolean;
  /** Codex-style approval card rendered under the matching tool call. */
  approvalSlot?: ReactNode;
  /** Owning session id: scopes the expand-state localStorage persistence. */
  sessionId?: string;
  /** Failed/interrupted turn: initially open its work scene until the user chooses. */
  turnFailed?: boolean;
  /** A parent work disclosure already summarizes this trail; keep only its semantic groups. */
  showAggregateSummary?: boolean;
};

const STAGGERED_DETAILS_CLOSE_DURATION_MS = 520;
const MAX_STAGGERED_ROW_DELAY = 8;

/**
 * ZCode ToolLayout-aligned open persistence: the user's explicit expand/collapse
 * choice survives re-renders, remounts, and full page reloads via the
 * localStorage store in conversationToolExpandPersistence (scoped per session).
 * Rows start collapsed — a running row no longer opens itself; the action
 * word's shimmer carries the live state instead.
 */
const TOOL_ROW_BODY_UNMOUNT_DELAY_MS = 300;
const TOOL_FAILURE_COPY_FEEDBACK_MS = 1600;
const TOOL_FAILURE_SUMMARY_MAX_LENGTH = 240;

/** First meaningful error line, for the status word's hover tooltip and the copy affordance. */
function toolFailureDetailText(cell: CodexTranscriptCell): string {
  const toolCall = cell.toolLifecycleModel?.toolCalls?.[0];
  const candidates = [cell.summary, cell.text, toolCall?.error, toolCall?.resultPreview];
  for (const candidate of candidates) {
    const text = String(candidate ?? "").replace(/\s+/g, " ").trim();
    if (!text) {
      continue;
    }
    return text.length > TOOL_FAILURE_SUMMARY_MAX_LENGTH
      ? `${text.slice(0, TOOL_FAILURE_SUMMARY_MAX_LENGTH - 1)}…`
      : text;
  }
  return "";
}

async function copyToolFailureToClipboard(text: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textArea = document.createElement("textarea");
  textArea.value = text;
  textArea.setAttribute("readonly", "true");
  textArea.style.position = "absolute";
  textArea.style.opacity = "0";
  textArea.style.pointerEvents = "none";
  document.body.appendChild(textArea);
  textArea.select();
  const copied = document.execCommand("copy");
  document.body.removeChild(textArea);
  if (!copied) {
    throw new Error("copy failed");
  }
}

type ToolRowOpenOptions = {
  /** Owning session id; scopes the persistence (empty string = memory only). */
  sessionId: string;
  /** Failed/interrupted turn: initially open its scene until the user chooses. */
  forceOpen?: boolean;
};

function toolRowChoiceKey(key: string, failed: boolean) {
  return failed ? `failed-scene:${key}` : key;
}

/**
 * Expand/collapse state for one tool row.
 *
 * Open-state priority (ZCode ToolLayout semantics, highest first):
 * A failed/interrupted turn (`forceOpen`) initially opens its diagnostic scene.
 * Otherwise the persisted per-session user choice wins, defaulting to collapsed.
 * Running/settled changes never overwrite an explicit expand/collapse choice.
 *
 * Reads the persistence store on mount, writes through on every toggle, and
 * keeps the body mounted for a short delay after a collapse so a rapid
 * re-expand never unmounts/remounts the content.
 */
function usePersistentToolRowOpen(persistKey: string, options: ToolRowOpenOptions) {
  const { sessionId, forceOpen = false } = options;
  const choiceKey = toolRowChoiceKey(persistKey, forceOpen);
  const [isOpen, setIsOpen] = useState(
    () => readToolRowOpen(sessionId, choiceKey) ?? forceOpen,
  );
  const [shouldRenderBody, setShouldRenderBody] = useState(isOpen);
  const bodyUnmountTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isOpenRef = useRef(isOpen);

  const applyOpen = useCallback((next: boolean, persist: boolean) => {
    isOpenRef.current = next;
    if (persist) {
      setToolRowOpen(sessionId, choiceKey, next);
    }
    setShouldRenderBody(true);
    setIsOpen(next);
  }, [choiceKey, sessionId]);

  const toggle = useCallback(() => {
    applyOpen(!isOpenRef.current, true);
  }, [applyOpen]);

  // The first failure opens over choices from the normal scene. A choice made
  // in this failure scene wins, including when the row remounts later.
  useEffect(() => {
    const failedChoice = readToolRowOpen(sessionId, choiceKey) ?? true;
    if (forceOpen && failedChoice !== isOpenRef.current) {
      applyOpen(failedChoice, false);
    }
  }, [applyOpen, choiceKey, forceOpen, sessionId]);

  useEffect(() => {
    if (isOpen) {
      if (bodyUnmountTimerRef.current !== null) {
        clearTimeout(bodyUnmountTimerRef.current);
        bodyUnmountTimerRef.current = null;
      }
      setShouldRenderBody(true);
      return;
    }
    if (!shouldRenderBody) {
      return;
    }
    bodyUnmountTimerRef.current = setTimeout(() => {
      bodyUnmountTimerRef.current = null;
      setShouldRenderBody(false);
    }, TOOL_ROW_BODY_UNMOUNT_DELAY_MS);
    return () => {
      if (bodyUnmountTimerRef.current !== null) {
        clearTimeout(bodyUnmountTimerRef.current);
        bodyUnmountTimerRef.current = null;
      }
    };
  }, [isOpen, shouldRenderBody]);

  return { isOpen, shouldRenderBody, toggle };
}

function staggeredRowStyle(index: number, count: number): CSSProperties {
  const openIndex = Math.min(index, MAX_STAGGERED_ROW_DELAY);
  const closeIndex = Math.min(count - index - 1, MAX_STAGGERED_ROW_DELAY);
  return {
    "--tool-activity-row-open-delay": `${openIndex * 42}ms`,
    "--tool-activity-row-close-delay": `${closeIndex * 34}ms`,
  } as CSSProperties;
}

/**
 * Native <details> hides content immediately; keep it mounted for its exit
 * sequence. With `persistence`, the open choice round-trips through the shared
 * per-session localStorage store (including explicit closed choices) and survives the
 * remounts caused by the group's div→details root swap. A `openByDefault`
 * force-open (failed turn scene) is scene preservation, not a user choice, so
 * it never writes the store.
 */
function useStaggeredDetails(
  openByDefault: boolean,
  persistence?: { sessionId: string; key: string },
) {
  const { sessionId = "", key = "" } = persistence ?? {};
  const [isExpanded, setIsExpanded] = useState(
    () => readToolRowOpen(sessionId, key) ?? openByDefault,
  );
  const [isClosing, setIsClosing] = useState(false);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const persistOpen = useCallback((open: boolean) => {
    if (!sessionId || !key) {
      return;
    }
    setToolRowOpen(sessionId, key, open);
  }, [key, sessionId]);

  const cancelClose = useCallback(() => {
    if (closeTimer.current !== null) {
      clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
    setIsClosing(false);
  }, []);

  const toggle = useCallback(() => {
    if (isClosing) {
      cancelClose();
      setIsExpanded(true);
      persistOpen(true);
      return;
    }
    if (!isExpanded) {
      setIsExpanded(true);
      persistOpen(true);
      return;
    }
    setIsClosing(true);
    persistOpen(false);
    closeTimer.current = setTimeout(() => {
      closeTimer.current = null;
      setIsClosing(false);
      setIsExpanded(false);
    }, STAGGERED_DETAILS_CLOSE_DURATION_MS);
  }, [cancelClose, isClosing, isExpanded, persistOpen]);

  useEffect(() => {
    if (!openByDefault) return;
    cancelClose();
    setIsExpanded(readToolRowOpen(sessionId, key) ?? true);
  }, [cancelClose, key, openByDefault, sessionId]);

  useEffect(() => () => {
    if (closeTimer.current !== null) clearTimeout(closeTimer.current);
  }, []);

  return {
    isClosing,
    isOpen: isExpanded || isClosing,
    onSummaryClick: (event: React.MouseEvent<HTMLElement>) => {
      event.preventDefault();
      toggle();
    },
  };
}

function cellLooksTimedOut(cell: CodexTranscriptCell) {
  const haystack = [
    cell.summary,
    cell.title,
    cell.text,
    cell.toolLifecycleModel?.toolCalls?.[0]?.summary,
    cell.toolLifecycleModel?.toolCalls?.[0]?.resultPreview,
  ].map((value) => String(value || "")).join("\n");
  return /超时|timed?\s*out/i.test(haystack);
}

function isSettledFailedCell(cell: CodexTranscriptCell) {
  return cell.status === "failed"
    || cell.tone === "error"
    || cellLooksTimedOut(cell);
}

function buildToolActivityPills(
  cell: CodexTranscriptCell,
  language: ConversationToolPresentationLanguage,
  options?: { noMatch?: boolean; agentName?: string },
): CodexToolActivityPills {
  const toolCall = cell.toolLifecycleModel?.toolCalls?.[0];
  const terminal = cell.toolLifecycleModel?.terminalOperations?.[0];
  const durationSeconds = codexTranscriptToolDurationSeconds(cell);
  const exitCode = conversationToolActivityTerminalExitCode(cell);
  const nonzeroExit = exitCode !== null && exitCode !== 0
    && !options?.noMatch
    && !isSettledFailedCell(cell);
  const status = isSettledFailedCell(cell)
    ? "failed"
    : nonzeroExit
      ? "completed"
      : cell.status;
  const displayCommand = String(
    terminal?.request?.displayCommand
    || (Array.isArray(terminal?.request?.command) ? terminal?.request?.command.join(" ") : "")
    || "",
  ).trim();
  const toolName = codexTranscriptToolRawName(cell);
  const durationLabel = durationSeconds === null ? "" : formatCodexTranscriptDuration(durationSeconds);
  let cellSummary = cell.summary;
  let toolSummary = toolCall?.summary;
  // Prefer structured code-graph semantic titles as the muted subject.
  if (toolName.trim().toLowerCase() === "code_symbol_tool" && status === "completed") {
    const semantic = completedToolPresentationSummary({
      toolSummary: toolCall?.summary,
      cellSummary: cell.summary,
      resultPreview: toolCall?.resultPreview,
      cellText: cell.text,
      toolName,
      status,
      language,
    });
    if (semantic && /^(搜索|检查|Search |Inspect )/i.test(semantic)) {
      cellSummary = semantic;
      toolSummary = semantic;
    }
  }
  const pills = buildCodexToolActivityPills({
    toolName,
    status,
    language,
    durationSeconds,
    durationLabel,
    toolSummary,
    cellSummary,
    resultPreview: toolCall?.resultPreview || cell.text,
    displayCommand,
    // Names the target while the tool runs, before any result can be summarized.
    toolArguments: codexTranscriptToolArguments(cell),
    timedOut: cellLooksTimedOut(cell) || Boolean(terminal?.result?.timedOut),
    noMatch: Boolean(options?.noMatch),
    nonzeroExit,
  });
  // ZCode subagent rows: when the row's subject IS the agent name (spawn /
  // delegate tools), the name becomes the main text and picks its stable color.
  if (options?.agentName) {
    pills.subject = options.agentName;
  }
  return pills;
}

function ToolStatusIcon({
  cell,
  language,
}: {
  cell: CodexTranscriptCell;
  language: ConversationToolPresentationLanguage;
}) {
  const descriptor = conversationToolActivityRendererForCell(cell, language);
  const category = conversationToolCategoryForCell(cell);
  const Icon = category === "agent" ? Bot : category === "cua" ? MonitorSmartphone : descriptor.icon;
  if (isSettledFailedCell(cell)) {
    return <CircleAlert className={`${styles.itemIcon} ${styles.itemIconFailed}`} size={15} />;
  }
  if (cell.status === "running" || cell.status === "pending") {
    // ZCode-aligned: icons stay static while running; the action word's shimmer
    // carries the live state. A spinning icon burns animation cost across the
    // long stream of tool rows and shouts louder than the quiet tool rail.
    return <Icon className={`${styles.itemIcon} ${styles.itemIconRunning}`} size={15} />;
  }
  if (conversationToolActivityHasNonzeroTerminalExit(cell)) {
    return <CircleAlert className={`${styles.itemIcon} ${styles.itemIconWarning}`} size={15} />;
  }
  if (cell.status === "degraded") {
    return <CircleAlert className={`${styles.itemIcon} ${styles.itemIconWarning}`} size={15} />;
  }
  // Neutral terminal state: cancelled/stopped/denied get the quiet slash glyph,
  // never the red failure alert and never a green check.
  if (cell.status === "cancelled") {
    return <CircleSlash className={styles.itemIcon} size={15} />;
  }
  return <Icon className={styles.itemIcon} size={15} />;
}

type ToolRowScopeProps = {
  sessionId: string;
  turnFailed: boolean;
};

function ToolActivityItem({
  cell,
  language,
  renderToolDetails,
  toolDetailIsEmpty,
  sessionId,
  turnFailed,
}: {
  cell: CodexTranscriptCell;
  language: ConversationToolPresentationLanguage;
  renderToolDetails: ConversationToolActivityProps["renderToolDetails"];
  toolDetailIsEmpty?: ConversationToolActivityProps["toolDetailIsEmpty"];
} & ToolRowScopeProps) {
  const noMatch = conversationToolActivityIsNoMatchTerminalExit(cell);
  // Agent-spawn rows render the subagent's name as the colored main subject.
  const agentName = conversationToolCategoryForCell(cell) === "agent"
    ? conversationAgentDisplayName(cell)
    : "";
  const agentAccentStyle = agentName
    ? conversationSubagentAccentStyle(conversationSubagentColorBucket(agentName))
    : null;
  const pills = buildToolActivityPills(cell, language, { noMatch, agentName });
  const title = toolActivityAriaTitle(pills);
  const detailsId = `codex-tool-detail-${cell.id}`;
  const details = renderToolDetails(cell, detailsId);
  const persistKey = conversationToolPersistKey(cell);
  const { isOpen, shouldRenderBody, toggle } = usePersistentToolRowOpen(persistKey, {
    sessionId,
    forceOpen: turnFailed,
  });
  // ZCode failure denoising: the colored status word + dashed underline carries
  // the failure semantics; hovering it reveals the error summary, and the
  // expanded body keeps the full error with a copy affordance.
  const failureDetail = pills.statusKind === "failed" || pills.statusKind === "timeout"
    ? toolFailureDetailText(cell)
    : "";
  const [failureCopied, setFailureCopied] = useState(false);
  const copyResetTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (copyResetTimerRef.current !== null) {
      clearTimeout(copyResetTimerRef.current);
    }
  }, []);
  const copyLabel = language === "zh"
    ? (failureCopied ? "已复制错误详情" : "复制错误详情")
    : (failureCopied ? "Copied error details" : "Copy error details");
  const handleCopyFailureDetail = () => {
    if (!failureDetail) {
      return;
    }
    void copyToolFailureToClipboard(failureDetail).then(() => {
      setFailureCopied(true);
      if (copyResetTimerRef.current !== null) {
        clearTimeout(copyResetTimerRef.current);
      }
      copyResetTimerRef.current = setTimeout(() => {
        copyResetTimerRef.current = null;
        setFailureCopied(false);
      }, TOOL_FAILURE_COPY_FEEDBACK_MS);
    }).catch(() => undefined);
  };
  const label = language === "zh"
    ? `展开或收起工具结果：${title}`
    : `Expand or collapse tool results: ${title}`;
  // ZCode subagent rows carry a neutral origin badge next to the colored name.
  // Drilling into the child session is not wired yet: the spawn result only
  // carries a subRunId (a JSONL run log), not a chat session id, so there is
  // no href to open — the badge is presentational until that id exists.
  const agentSourceBadge = agentName ? conversationToolCategoryLabel("agent", language) : "";
  const content = (
    <ConversationToolActivityPills
      pills={pills}
      leadingIcon={<ToolStatusIcon cell={cell} language={language} />}
      statusTooltip={failureDetail}
      agentAccentStyle={agentAccentStyle}
      sourceBadge={agentSourceBadge}
    />
  );
  const emptyDetail = language === "zh" ? "无更多详情" : "No further details";

  // Codex/opencode rule: a row with nothing to expand never shows a toggle.
  if (toolDetailIsEmpty?.(cell)) {
    return (
      <div
        className={styles.itemStatic}
        data-codex-tool-activity-item="true"
        data-codex-tool-detail="none"
        data-codex-transcript-cell-kind={cell.kind}
        data-codex-transcript-cell-tone={cell.tone}
        data-codex-transcript-cell-status={cell.status}
        data-codex-transcript-cell-phase={cell.phase ?? "tool_call"}
        data-conversation-part-key={cell.id}
      >
        {content}
      </div>
    );
  }

  // SSR keeps the body mounted (the closed details hides it via CSS); on the
  // client the delayed unmount in usePersistentToolRowOpen prevents flash.
  const renderBody = shouldRenderBody || typeof window === "undefined";

  return (
    <details
      className={`${styles.item} ${styles.itemDetails} group`}
      data-codex-tool-activity-item="true"
      data-codex-tool-detail="true"
      data-codex-transcript-cell-kind={cell.kind}
      data-codex-transcript-cell-tone={cell.tone}
      data-codex-transcript-cell-status={cell.status}
      data-codex-transcript-cell-phase={cell.phase ?? "tool_call"}
      data-conversation-part-key={cell.id}
      open={isOpen}
    >
      <summary
        className={styles.itemSummary}
        aria-label={label}
        aria-live={cell.status === "running" || cell.status === "pending" ? "polite" : undefined}
        onClick={(event) => {
          // Native <details> toggles on summary click; route it through the
          // persisted state so the choice survives re-renders.
          event.preventDefault();
          toggle();
        }}
      >
        {content}
      </summary>
      {renderBody ? (
        <div id={detailsId} className={styles.itemDetailsBody} data-codex-tool-detail-body="true">
          {details ?? <p className={styles.itemDetailsEmpty}>{emptyDetail}</p>}
          {failureDetail ? (
            <div className={styles.itemDetailsActions} data-codex-tool-failure-copy="true">
              <VTooltip
                width="compact"
                content={(
                  <span className={styles.tooltipContent}>
                    <span className={styles.tooltipTitle}>{copyLabel}</span>
                    <span className={styles.tooltipDescription}>
                      {language === "zh" ? "复制失败详情到剪贴板" : "Copy the failure details to the clipboard"}
                    </span>
                  </span>
                )}
              >
                <VNativeButton
                  data-vui="icon-button"
                  className={styles.itemDetailsCopyButton}
                  onClick={handleCopyFailureDetail}
                  aria-label={copyLabel}
                >
                  {failureCopied ? <Check size={12} aria-hidden="true" /> : <Copy size={12} aria-hidden="true" />}
                </VNativeButton>
              </VTooltip>
            </div>
          ) : null}
        </div>
      ) : null}
    </details>
  );
}

function ToolActivityBatch({
  item,
  language,
  renderToolDetails,
  toolDetailIsEmpty,
  sessionId,
  turnFailed,
}: {
  item: Extract<ConversationToolActivityPresentationItem, { kind: "batch" }>;
  language: ConversationToolPresentationLanguage;
  renderToolDetails: ConversationToolActivityProps["renderToolDetails"];
  toolDetailIsEmpty?: ConversationToolActivityProps["toolDetailIsEmpty"];
} & ToolRowScopeProps) {
  // A failed turn force-opens the batch so its work history stays on scene;
  // batches have no running→completed auto-collapse (they never self-open).
  // The user's expand choice persists per session (keyed by the batch's
  // anchored id) so the settle-time group remount reopens it.
  const persistKey = toolActivityRowKey(item);
  const staggeredDetails = useStaggeredDetails(turnFailed, {
    sessionId,
    key: toolRowChoiceKey(persistKey, turnFailed),
  });
  const descriptor = conversationToolActivityRendererForCell(item.cells[0], language);
  const Icon = descriptor.icon;
  const countLabel = language === "zh" ? `${item.count} 次` : `${item.count} calls`;
  const label = language === "zh"
    ? `展开或收起连续工具调用：${item.title}，${countLabel}`
    : `Expand or collapse repeated tool calls: ${item.title}, ${countLabel}`;

  return (
    <details
      className={`${styles.batch} group`}
      data-codex-tool-activity-batch="true"
      data-codex-tool-activity-count={item.count}
      data-conversation-part-key={persistKey}
      data-closing={staggeredDetails.isClosing || undefined}
      open={staggeredDetails.isOpen}
    >
      <summary className={styles.batchSummary} aria-label={label} onClick={staggeredDetails.onSummaryClick}>
        <Icon className={styles.itemIcon} size={15} aria-hidden="true" />
        <span className={styles.itemBody}>
          <span className={styles.itemTitle}>{item.title}</span>
          <span className={styles.batchCount}>· {countLabel}</span>
        </span>
      </summary>
      <div className={styles.batchDetails}>
        <div className={styles.batchDetailsInner}>
          {item.cells.map((cell, index) => (
            <div key={cell.id} className={styles.batchRow} style={staggeredRowStyle(index, item.cells.length)}>
              <ToolActivityItem
                cell={cell}
                language={language}
                renderToolDetails={renderToolDetails}
                toolDetailIsEmpty={toolDetailIsEmpty}
                sessionId={sessionId}
                turnFailed={turnFailed}
              />
            </div>
          ))}
        </div>
      </div>
    </details>
  );
}

function checklistModelForBatch(
  item: Extract<ConversationToolActivityPresentationItem, { kind: "batch" }>,
  language: ConversationToolPresentationLanguage,
): ConversationToolChecklistModel | null {
  const models = item.cells.map((cell) => conversationToolChecklistModel(cell, language));
  if (models.length === 0 || models.some((model) => model === null)) {
    return null;
  }
  return models[models.length - 1] ?? null;
}

/**
 * ZCode-aligned parent group for a run of same-category tools (Explore /
 * Execute / …). The row shows the current action/target while running and
 * semantic call counts after settling, and aggregates the
 * child states with B2 semantics: any running child keeps the category word
 * shimmering; failures surface as a dashed attention word whose hover tooltip
 * carries the first failed child's error summary. The expand choice persists
 * through the per-session localStorage store keyed by the group's anchored id
 * (first child's stable tool identity), so streaming appends never reset it.
 */
function ToolActivityCategoryGroup({
  item,
  language,
  renderToolDetails,
  toolDetailIsEmpty,
  sessionId,
  turnFailed,
}: {
  item: ConversationToolCategoryGroupItem;
  language: ConversationToolPresentationLanguage;
  renderToolDetails: ConversationToolActivityProps["renderToolDetails"];
  toolDetailIsEmpty?: ConversationToolActivityProps["toolDetailIsEmpty"];
} & ToolRowScopeProps) {
  const { isOpen, shouldRenderBody, toggle } = usePersistentToolRowOpen(item.id, {
    sessionId,
    forceOpen: turnFailed,
  });
  const Icon = CATEGORY_GROUP_ICONS[item.category];
  const countLabel = conversationToolCategoryGroupCountLabel(item, language);
  const activeCells = item.items.flatMap((child) => child.kind === "batch" ? [...child.cells] : [child.cell])
    .filter((cell) => cell.status === "running" || cell.status === "pending");
  const runningCells = activeCells.filter((cell) => cell.status === "running");
  const pendingCount = activeCells.length - runningCells.length;
  const activeCell = runningCells.at(-1) ?? activeCells.at(-1);
  const activePills = activeCell ? buildToolActivityPills(activeCell, language) : null;
  const activeLabel = activePills && activeCell
    ? [language === "zh"
      ? `${activeCell.status === "pending" ? "等待" : "正在"}${activePills.actionLabel}`
      : `${activeCell.status === "pending" ? "Waiting for" : "Running"} ${activePills.actionLabel}`,
      activePills.subject,
    ].filter(Boolean).join(" · ")
    : "";
  const activeCountLabel = activeCells.length > 1
    ? (pendingCount
      ? [runningCells.length ? (language === "zh" ? `${runningCells.length} 项进行中` : `${runningCells.length} running`) : "",
        language === "zh" ? `${pendingCount} 项等待` : `${pendingCount} pending`].filter(Boolean).join(" · ")
      : language === "zh" ? `共 ${activeCells.length} 项进行中` : `${activeCells.length} active`)
    : "";
  const groupSummary = activeLabel || countLabel;
  const statusKind = item.failedCount > 0 ? "failed" : "attention";
  const attentionLabel = item.attentionCount > 0
    ? (language === "zh"
      ? `${item.attentionCount} 项需关注`
      : item.attentionCount === 1
        ? "1 item needs attention"
        : `${item.attentionCount} items need attention`)
    : "";
  const failureDetail = item.firstAttentionCell
    ? toolFailureDetailText(item.firstAttentionCell)
    : "";
  const label = language === "zh"
    ? `展开或收起${item.title}工具组：${item.title}，${countLabel}${activeLabel ? `，${activeLabel}` : ""}`
    : `Expand or collapse ${item.title} tool group: ${item.title}, ${countLabel}${activeLabel ? `, ${activeLabel}` : ""}`;
  // SSR keeps the children mounted; on the client the persisted open flag gates
  // them (same delayed-unmount semantics as tool rows).
  const renderChildren = shouldRenderBody || typeof window === "undefined";

  return (
    <details
      className={`${styles.categoryGroup} group`}
      data-codex-tool-activity-category-group="true"
      data-codex-tool-category={item.category}
      data-codex-tool-activity-count={item.count}
      data-codex-tool-category-attention-count={item.attentionCount || undefined}
      data-conversation-part-key={item.id}
      open={isOpen}
    >
      <summary
        className={styles.categoryGroupSummary}
        aria-label={label}
        aria-live={item.running ? "polite" : undefined}
        onClick={(event) => {
          event.preventDefault();
          toggle();
        }}
      >
        {item.running ? (
          <Icon className={`${styles.itemIcon} ${styles.itemIconRunning}`} size={15} />
        ) : item.failedCount > 0 ? (
          <CircleAlert className={`${styles.itemIcon} ${styles.itemIconFailed}`} size={15} />
        ) : item.attentionCount > 0 ? (
          <CircleAlert className={`${styles.itemIcon} ${styles.itemIconWarning}`} size={15} />
        ) : (
          <Icon className={styles.itemIcon} size={15} aria-hidden="true" />
        )}
        <span className={styles.itemBody}>
          <span
            className={item.running
              ? `${styles.actionLabel} ${styles.actionLabelRunning}`
              : styles.actionLabel}
            data-codex-tool-action-pill="true"
            data-codex-tool-action-running={item.running ? "true" : undefined}
          >
            {item.title}
          </span>
          {attentionLabel ? (
            failureDetail ? (
              <VTooltip width="compact" content={failureDetail}>
                <span
                  className={`${styles.statusLabel} ${
                    statusKind === "failed" ? styles.statusLabel_failed : styles.statusLabel_attention
                  }`}
                  data-codex-tool-status-pill="true"
                  data-codex-tool-status-kind={statusKind}
                >
                  {attentionLabel}
                </span>
              </VTooltip>
            ) : (
              <span
                className={`${styles.statusLabel} ${
                  statusKind === "failed" ? styles.statusLabel_failed : styles.statusLabel_attention
                }`}
                data-codex-tool-status-pill="true"
                data-codex-tool-status-kind={statusKind}
              >
                {attentionLabel}
              </span>
            )
          ) : null}
          <span className={styles.categoryGroupMeta} title={groupSummary} data-codex-tool-category-summary="true">· {groupSummary}</span>
          {activeCountLabel ? <span className={styles.batchCount}>{activeCountLabel}</span> : null}
        </span>
      </summary>
      {renderChildren ? (
        <div className={styles.categoryGroupDetails}>
          <div className={styles.categoryGroupDetailsInner}>
            {item.items.map((child, index) => (
              <div
                key={toolActivityRowKey(child)}
                className={styles.categoryGroupRow}
                style={staggeredRowStyle(index, item.items.length)}
              >
                {toolActivityRowContent(child, language, renderToolDetails, toolDetailIsEmpty, {
                  sessionId,
                  turnFailed,
                })}
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </details>
  );
}

/**
 * ZCode-aligned category group icons. The category word carries the state via
 * the same shimmer/failed language as tool rows; the icon stays static.
 */
const CATEGORY_GROUP_ICONS: Record<ConversationToolCategory, LucideIcon> = {
  explore: FileSearch,
  execute: TerminalSquare,
  changes: PencilLine,
  cua: MonitorSmartphone,
  agent: Bot,
};

/** Streaming appends change a batch's last cell; its first tool stays the anchor. */
function toolActivityRowKey(item: ConversationToolCategorizedItem): string {
  return item.kind === "batch"
    ? `tool-batch:${conversationToolPersistKey(item.cells[0])}`
    : item.id;
}

function toolActivityRowContent(
  item: ConversationToolCategorizedItem,
  language: ConversationToolPresentationLanguage,
  renderToolDetails: ConversationToolActivityProps["renderToolDetails"],
  toolDetailIsEmpty?: ConversationToolActivityProps["toolDetailIsEmpty"],
  scope?: ToolRowScopeProps,
): ReactNode {
  if (item.kind === "categoryGroup") {
    return (
      <ToolActivityCategoryGroup
        item={item}
        language={language}
        renderToolDetails={renderToolDetails}
        toolDetailIsEmpty={toolDetailIsEmpty}
        sessionId={scope?.sessionId ?? ""}
        turnFailed={scope?.turnFailed ?? false}
      />
    );
  }
  const checklist = item.kind === "batch"
    ? checklistModelForBatch(item, language)
    : conversationToolChecklistModel(item.cell, language);
  if (checklist) {
    return <ConversationToolChecklist model={checklist} language={language} />;
  }
  if (item.kind === "batch") {
    return (
      <ToolActivityBatch
        item={item}
        language={language}
        renderToolDetails={renderToolDetails}
        toolDetailIsEmpty={toolDetailIsEmpty}
        sessionId={scope?.sessionId ?? ""}
        turnFailed={scope?.turnFailed ?? false}
      />
    );
  }
  return (
    <ToolActivityItem
      cell={item.cell}
      language={language}
      renderToolDetails={renderToolDetails}
      toolDetailIsEmpty={toolDetailIsEmpty}
      sessionId={scope?.sessionId ?? ""}
      turnFailed={scope?.turnFailed ?? false}
    />
  );
}

function ToolActivityRows({
  items,
  language,
  renderToolDetails,
  toolDetailIsEmpty,
  sessionId,
  turnFailed,
}: {
  items: ConversationToolCategorizedItem[];
  language: ConversationToolPresentationLanguage;
  renderToolDetails: ConversationToolActivityProps["renderToolDetails"];
  toolDetailIsEmpty?: ConversationToolActivityProps["toolDetailIsEmpty"];
} & ToolRowScopeProps) {
  return (
    <>
      {items.map((item) => (
        <div key={toolActivityRowKey(item)} className={styles.activityRow}>
          {toolActivityRowContent(item, language, renderToolDetails, toolDetailIsEmpty, {
            sessionId,
            turnFailed,
          })}
        </div>
      ))}
    </>
  );
}

export function ConversationToolActivity({
  activity,
  language,
  renderToolDetails,
  toolDetailIsEmpty,
  approvalSlot = null,
  sessionId = "",
  turnFailed = false,
  showAggregateSummary = true,
}: ConversationToolActivityProps) {
  // Category pass runs on top of the same-name batches: distinct same-category
  // runs (read + grep + glob → "探索") escalate to one anchored parent group.
  const items = buildConversationToolCategoryGroups(
    buildConversationToolActivityPresentation(activity.cells, language),
    language,
  );
  const digest = buildConversationToolActivityDigestPresentation(activity.cells, language);
  const railRef = useRef<HTMLDivElement | null>(null);
  const isRunning = digest.state === "running";
  // Codex: multi-tool completed groups can collapse under a one-line summary,
  // but default open so the chrono tool trail stays visible after stop/settle.
  const collapsibleGroup = showAggregateSummary && digest.count >= 3 && digest.state !== "running";
  const groupDetails = useStaggeredDetails(true);

  useEffect(() => {
    if (!isRunning || !railRef.current) {
      return;
    }
    const node = railRef.current;
    node.scrollTop = node.scrollHeight;
  }, [isRunning, activity.cells.length, digest.count]);

  const list = (
    <div
      ref={railRef}
      className={styles.activity}
      data-codex-tool-activity="items"
      data-codex-tool-activity-rail="true"
      data-codex-tool-activity-state={digest.state}
      data-codex-tool-activity-count={digest.count}
      data-codex-tool-activity-attention-count={digest.attentionCount || undefined}
      data-codex-tool-approval-attached={approvalSlot ? "true" : undefined}
    >
      <ToolActivityRows
        items={items}
        language={language}
        renderToolDetails={renderToolDetails}
        toolDetailIsEmpty={toolDetailIsEmpty}
        sessionId={sessionId}
        turnFailed={turnFailed}
      />
      {approvalSlot ? (
        <div className={styles.approvalSlot} data-codex-tool-approval-inline="true">
          {approvalSlot}
        </div>
      ) : null}
    </div>
  );

  if (!collapsibleGroup) {
    return list;
  }

  const groupTitle = digest.meta
    ? `${digest.title} · ${digest.meta}`
    : digest.title;
  const groupLabel = language === "zh"
    ? `展开或收起连续工具调用：${groupTitle}`
    : `Expand or collapse continuous tool calls: ${groupTitle}`;

  return (
    <details
      className={styles.group}
      data-codex-tool-activity-group="true"
      data-codex-tool-activity-count={digest.count}
      data-closing={groupDetails.isClosing || undefined}
      open={groupDetails.isOpen}
    >
      <summary className={styles.groupSummary} aria-label={groupLabel} onClick={groupDetails.onSummaryClick}>
        <span className={styles.groupTitle}>{groupTitle}</span>
        {digest.attentionLabel ? (
          <span className={styles.groupMeta}>· {digest.attentionLabel}</span>
        ) : null}
      </summary>
      <div className={styles.groupDetails}>
        {list}
      </div>
    </details>
  );
}
