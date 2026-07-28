import { ChevronDown, CircleAlert, LoaderCircle } from "lucide-react";
import type { ReactNode } from "react";

import "./ConversationToolActivity.css";
import type { CodexTranscriptCell } from "./codexTranscriptCells";
import {
  codexTranscriptToolRawName,
  type CodexTranscriptToolActivity,
} from "./conversationToolActivityModel";
import {
  conversationToolRendererForPresentationLabel,
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
  type ConversationToolActivityDigestPresentation,
  type ConversationToolActivityPresentationItem,
} from "./conversationToolActivityPresentation";
import styles from "./ConversationToolActivity.styles";

type ConversationToolActivityProps = {
  activity: CodexTranscriptToolActivity;
  language: ConversationToolPresentationLanguage;
  renderToolDetails: (cell: CodexTranscriptCell, detailsId: string) => ReactNode;
};

function visibleToolSummary(cell: CodexTranscriptCell, language: ConversationToolPresentationLanguage) {
  const exitCode = conversationToolActivityTerminalExitCode(cell);
  if (exitCode !== null && exitCode !== 0) {
    return language === "zh" ? `命令退出 ${exitCode}` : `Command exited ${exitCode}`;
  }
  const toolCall = cell.toolLifecycleModel?.toolCalls?.[0];
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

function ToolActivityStatusIcon({
  cells,
  language,
  state,
}: {
  cells: readonly CodexTranscriptCell[];
  language: ConversationToolPresentationLanguage;
  state: ConversationToolActivityDigestPresentation["state"];
}) {
  if (state === "running") {
    return <LoaderCircle className={`${styles.activityIcon} ${styles.activityIconRunning} animate-spin`} size={15} aria-hidden="true" />;
  }
  if (state === "attention") {
    return <CircleAlert className={`${styles.activityIcon} ${styles.activityIconAttention}`} size={15} aria-hidden="true" />;
  }
  const Icon = conversationToolActivityRendererForCell(cells[0], language).icon;
  return <Icon className={styles.activityIcon} size={15} aria-hidden="true" />;
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
  const digest = buildConversationToolActivityDigestPresentation(activity.cells, language);
  const openByDefault = digest.state === "running" || digest.state === "attention";
  const label = language === "zh"
    ? `展开或收起工具活动：${digest.title}`
    : `Expand or collapse tool activity: ${digest.title}`;
  return (
    <details
      className={`${styles.activity} group`}
      data-codex-tool-activity="digest"
      data-codex-tool-activity-state={digest.state}
      data-codex-tool-activity-count={digest.count}
      data-codex-tool-activity-attention-count={digest.attentionCount || undefined}
      open={openByDefault || undefined}
    >
      <summary
        className={styles.activitySummary}
        aria-label={label}
        aria-live={digest.state === "running" ? "polite" : undefined}
      >
        <ToolActivityStatusIcon cells={activity.cells} language={language} state={digest.state} />
        <span className={styles.activitySummaryBody}>
          <span className={styles.activityTitle}>{digest.title}</span>
          {digest.attentionLabel ? (
            <span className={styles.activityAttention}>· {digest.attentionLabel}</span>
          ) : null}
          {digest.meta ? <span className={styles.activityMeta}>{digest.meta}</span> : null}
          <ChevronDown className={styles.activityChevron} size={14} aria-hidden="true" />
        </span>
      </summary>
      <div className={styles.activityDetails}>
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
    </details>
  );
}
