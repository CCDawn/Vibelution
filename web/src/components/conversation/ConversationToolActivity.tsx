import { ChevronDown, CircleAlert, LoaderCircle } from "lucide-react";
import type { ReactNode } from "react";

import type { CodexTranscriptCell } from "./codexTranscriptCells";
import {
  codexTranscriptToolRawName,
  type CodexTranscriptToolActivity,
} from "./conversationToolActivityModel";
import {
  conversationToolRendererFor,
  conversationToolRendererForPresentationLabel,
  conversationToolRendererLabel,
} from "./conversationToolRendererRegistry";
import {
  completedToolPresentationSummary,
  type ConversationToolPresentationLanguage,
} from "./conversationToolPresentation";
import {
  buildConversationToolActivityPresentation,
  type ConversationToolActivityPresentationItem,
} from "./conversationToolActivityPresentation";
import styles from "./ConversationToolActivity.styles";

type ConversationToolActivityProps = {
  activity: CodexTranscriptToolActivity;
  language: ConversationToolPresentationLanguage;
  renderToolDetails: (cell: CodexTranscriptCell, detailsId: string) => ReactNode;
};

function visibleToolSummary(cell: CodexTranscriptCell, language: ConversationToolPresentationLanguage) {
  const toolCall = cell.toolLifecycleModel?.toolCalls?.[0];
  return completedToolPresentationSummary({
    toolSummary: toolCall?.summary,
    cellSummary: cell.summary,
    resultPreview: toolCall?.resultPreview,
    cellText: cell.text,
    toolName: codexTranscriptToolRawName(cell),
    language,
  });
}

function toolRendererForCell(cell: CodexTranscriptCell, language: ConversationToolPresentationLanguage) {
  const rawName = codexTranscriptToolRawName(cell);
  const direct = conversationToolRendererFor(rawName);
  if (direct.family !== "generic") {
    return direct;
  }
  return conversationToolRendererForPresentationLabel(
    conversationToolRendererLabel(rawName || cell.title || "", language),
    language,
  );
}

function ToolStatusIcon({
  cell,
  language,
}: {
  cell: CodexTranscriptCell;
  language: ConversationToolPresentationLanguage;
}) {
  const descriptor = toolRendererForCell(cell, language);
  if (cell.status === "running" || cell.status === "pending") {
    return <LoaderCircle className={`${styles.itemIcon} ${styles.itemIconRunning} animate-spin`} size={15} />;
  }
  if (cell.status === "failed") {
    return <CircleAlert className={`${styles.itemIcon} ${styles.itemIconFailed}`} size={15} />;
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
  const summary = visibleToolSummary(cell, language);
  const useSemanticCodeTitle = toolName.trim().toLowerCase() === "code_symbol_tool"
    && /^(搜索|检查|Search |Inspect )/.test(summary);
  const title = useSemanticCodeTitle ? summary : baseTitle;
  const preview = useSemanticCodeTitle ? "" : summary;
  const detailsId = `codex-tool-detail-${cell.id}`;
  const details = renderToolDetails(cell, detailsId);
  const expandable = details !== null && details !== undefined && details !== false;
  const openByDefault = cell.status === "failed" || cell.status === "degraded";
  const label = language === "zh"
    ? `展开或收起工具结果：${title}`
    : `Expand or collapse tool results: ${title}`;
  const content = (
    <>
      <ToolStatusIcon cell={cell} language={language} />
      <span className={styles.itemBody}>
        <span className={styles.itemTitle}>{title}</span>
        {expandable ? <ChevronDown className={styles.itemChevron} size={14} aria-hidden="true" /> : null}
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
  const descriptor = conversationToolRendererForPresentationLabel(item.title, language);
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
    >
      <summary className={styles.batchSummary} aria-label={label}>
        <Icon className={styles.itemIcon} size={15} aria-hidden="true" />
        <span className={styles.itemBody}>
          <span className={styles.itemTitle}>{item.title}</span>
          <span className={styles.batchCount}>· {countLabel}</span>
          <ChevronDown className={styles.itemChevron} size={14} aria-hidden="true" />
        </span>
      </summary>
      <div className={styles.batchDetails}>
        {item.cells.map((cell) => (
          <ToolActivityItem
            key={cell.id}
            cell={cell}
            language={language}
            renderToolDetails={renderToolDetails}
          />
        ))}
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
  return (
    <div className={styles.activity} data-codex-tool-activity="inline">
      {items.map((item) => item.kind === "batch" ? (
        <ToolActivityBatch
          key={item.id}
          item={item}
          language={language}
          renderToolDetails={renderToolDetails}
        />
      ) : (
        <ToolActivityItem
          key={item.id}
          cell={item.cell}
          language={language}
          renderToolDetails={renderToolDetails}
        />
      ))}
    </div>
  );
}
