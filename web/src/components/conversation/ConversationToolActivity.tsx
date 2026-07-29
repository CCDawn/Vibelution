import { CircleAlert, LoaderCircle } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

import "./ConversationToolActivity.css";
import type { CodexTranscriptCell } from "./codexTranscriptCells";
import {
  codexTranscriptToolRawName,
  type CodexTranscriptToolActivity,
} from "./conversationToolActivityModel";
import {
  conversationToolRendererLabel,
} from "./conversationToolRendererRegistry";
import {
  completedToolPresentationSummary,
  type ConversationToolPresentationLanguage,
} from "./conversationToolPresentation";
import {
  buildConversationToolActivityDigestPresentation,
  buildConversationToolActivityPresentation,
  conversationToolActivityHasNonzeroTerminalExit,
  conversationToolActivityIsNoMatchTerminalExit,
  conversationToolActivityRendererForCell,
  conversationToolActivityTerminalExitCode,
  type ConversationToolActivityPresentationItem,
} from "./conversationToolActivityPresentation";
import styles from "./ConversationToolActivity.styles";

type ConversationToolActivityProps = {
  activity: CodexTranscriptToolActivity;
  language: ConversationToolPresentationLanguage;
  renderToolDetails: (cell: CodexTranscriptCell, detailsId: string) => ReactNode;
};

const STAGGERED_DETAILS_CLOSE_DURATION_MS = 520;
const MAX_STAGGERED_ROW_DELAY = 8;

function staggeredRowStyle(index: number, count: number): CSSProperties {
  const openIndex = Math.min(index, MAX_STAGGERED_ROW_DELAY);
  const closeIndex = Math.min(count - index - 1, MAX_STAGGERED_ROW_DELAY);
  return {
    "--tool-activity-row-open-delay": `${openIndex * 42}ms`,
    "--tool-activity-row-close-delay": `${closeIndex * 34}ms`,
  } as CSSProperties;
}

/** Native <details> hides content immediately; keep it mounted for its exit sequence. */
function useStaggeredDetails(openByDefault: boolean) {
  const [isExpanded, setIsExpanded] = useState(openByDefault);
  const [isClosing, setIsClosing] = useState(false);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

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
      return;
    }
    if (!isExpanded) {
      setIsExpanded(true);
      return;
    }
    setIsClosing(true);
    closeTimer.current = setTimeout(() => {
      closeTimer.current = null;
      setIsClosing(false);
      setIsExpanded(false);
    }, STAGGERED_DETAILS_CLOSE_DURATION_MS);
  }, [cancelClose, isClosing, isExpanded]);

  useEffect(() => {
    if (!openByDefault) return;
    cancelClose();
    setIsExpanded(true);
  }, [cancelClose, openByDefault]);

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

function visibleToolSummary(cell: CodexTranscriptCell, language: ConversationToolPresentationLanguage) {
  const exitCode = conversationToolActivityTerminalExitCode(cell);
  if (exitCode !== null && exitCode !== 0) {
    return language === "zh" ? `命令退出 ${exitCode}` : `Command exited ${exitCode}`;
  }
  const toolCall = cell.toolLifecycleModel?.toolCalls?.[0];
  if (cell.status === "completed" && toolCall?.runtimeKind === "terminal") {
    return "";
  }
  return completedToolPresentationSummary({
    toolSummary: toolCall?.summary,
    cellSummary: cell.summary,
    resultPreview: toolCall?.resultPreview,
    cellText: cell.text,
    toolName: codexTranscriptToolRawName(cell),
    status: cell.status,
    language,
  });
}

function ToolStatusIcon({
  cell,
  language,
}: {
  cell: CodexTranscriptCell;
  language: ConversationToolPresentationLanguage;
}) {
  const descriptor = conversationToolActivityRendererForCell(cell, language);
  if (cell.status === "running" || cell.status === "pending") {
    return <LoaderCircle className={`${styles.itemIcon} ${styles.itemIconRunning} animate-spin`} size={15} />;
  }
  if (cell.status === "failed") {
    return <CircleAlert className={`${styles.itemIcon} ${styles.itemIconFailed}`} size={15} />;
  }
  if (conversationToolActivityHasNonzeroTerminalExit(cell)) {
    return <CircleAlert className={`${styles.itemIcon} ${styles.itemIconWarning}`} size={15} />;
  }
  if (cell.status === "degraded") {
    return <CircleAlert className={`${styles.itemIcon} ${styles.itemIconWarning}`} size={15} />;
  }
  const Icon = descriptor.icon;
  return <Icon className={styles.itemIcon} size={15} />;
}

function ToolActivityItem({
  cell,
  language,
  renderToolDetails,
}: {
  cell: CodexTranscriptCell;
  language: ConversationToolPresentationLanguage;
  renderToolDetails: ConversationToolActivityProps["renderToolDetails"];
}) {
  const toolName = codexTranscriptToolRawName(cell);
  const baseTitle = conversationToolRendererLabel(toolName, language);
  const summary = conversationToolActivityIsNoMatchTerminalExit(cell)
    ? (language === "zh" ? "未找到匹配项" : "No matches found")
    : visibleToolSummary(cell, language);
  const useSemanticCodeTitle = toolName.trim().toLowerCase() === "code_symbol_tool"
    && /^(搜索|检查|Search |Inspect )/.test(summary);
  const title = useSemanticCodeTitle ? summary : baseTitle;
  const preview = useSemanticCodeTitle ? "" : summary;
  const detailsId = `codex-tool-detail-${cell.id}`;
  const details = renderToolDetails(cell, detailsId);
  const expandable = details !== null && details !== undefined && details !== false;
  const openByDefault = cell.status === "running" || cell.status === "pending";
  const label = language === "zh"
    ? `展开或收起工具结果：${title}`
    : `Expand or collapse tool results: ${title}`;
  const content = (
    <>
      <ToolStatusIcon cell={cell} language={language} />
      <span className={styles.itemBody}>
        <span className={styles.itemTitle}>{title}</span>
        {preview ? <span className={styles.itemPreview}>{preview}</span> : null}
      </span>
    </>
  );

  if (!expandable) {
    return (
      <div
        className={`${styles.item} ${styles.itemStatic}`}
        data-codex-tool-activity-item="true"
        data-codex-transcript-cell-kind={cell.kind}
        data-codex-transcript-cell-tone={cell.tone}
        data-codex-transcript-cell-status={cell.status}
        data-codex-transcript-cell-phase={cell.phase ?? "tool_call"}
        data-conversation-part-key={cell.id}
        role={cell.status === "running" || cell.status === "pending" ? "status" : undefined}
        aria-live={cell.status === "running" || cell.status === "pending" ? "polite" : undefined}
      >
        {content}
      </div>
    );
  }

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
      open={openByDefault || undefined}
    >
      <summary
        className={styles.itemSummary}
        aria-label={label}
        aria-live={cell.status === "running" || cell.status === "pending" ? "polite" : undefined}
      >
        {content}
      </summary>
      <div id={detailsId} className={styles.itemDetailsBody}>{details}</div>
    </details>
  );
}

function ToolActivityBatch({
  item,
  language,
  renderToolDetails,
}: {
  item: Extract<ConversationToolActivityPresentationItem, { kind: "batch" }>;
  language: ConversationToolPresentationLanguage;
  renderToolDetails: ConversationToolActivityProps["renderToolDetails"];
}) {
  const staggeredDetails = useStaggeredDetails(false);
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
      data-conversation-part-key={item.id}
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
              <ToolActivityItem cell={cell} language={language} renderToolDetails={renderToolDetails} />
            </div>
          ))}
        </div>
      </div>
    </details>
  );
}

export function ConversationToolActivity({
  activity,
  language,
  renderToolDetails,
}: ConversationToolActivityProps) {
  const items = buildConversationToolActivityPresentation(activity.cells, language);
  const digest = buildConversationToolActivityDigestPresentation(activity.cells, language);
  return (
    <div
      className={styles.activity}
      data-codex-tool-activity="items"
      data-codex-tool-activity-state={digest.state}
      data-codex-tool-activity-count={digest.count}
      data-codex-tool-activity-attention-count={digest.attentionCount || undefined}
    >
      {items.map((item) => (
        <div key={item.id} className={styles.activityRow}>
          {item.kind === "batch" ? (
            <ToolActivityBatch item={item} language={language} renderToolDetails={renderToolDetails} />
          ) : (
            <ToolActivityItem cell={item.cell} language={language} renderToolDetails={renderToolDetails} />
          )}
        </div>
      ))}
    </div>
  );
}
