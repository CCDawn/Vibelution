import {
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  LoaderCircle,
} from "lucide-react";
import type { ReactNode } from "react";

import type { CodexTranscriptCell } from "./codexTranscriptCells";
import {
  codexTranscriptToolDurationSeconds,
  codexTranscriptToolRawName,
  formatCodexTranscriptDuration,
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
import styles from "./ConversationToolActivity.styles";

type ConversationToolActivityProps = {
  activity: CodexTranscriptToolActivity;
  language: ConversationToolPresentationLanguage;
  renderToolDetails: (cell: CodexTranscriptCell, detailsId: string) => ReactNode;
};

function statusLabel(cell: CodexTranscriptCell, language: ConversationToolPresentationLanguage) {
  const labels = language === "zh"
    ? {
      completed: "完成",
      failed: "失败",
      degraded: "降级",
      pending: "等待中",
      running: "运行中",
    }
    : {
      completed: "Completed",
      failed: "Failed",
      degraded: "Degraded",
      pending: "Pending",
      running: "Running",
    };
  const duration = codexTranscriptToolDurationSeconds(cell);
  return [labels[cell.status], duration === null ? "" : formatCodexTranscriptDuration(duration)]
    .filter(Boolean)
    .join(" ");
}

function visibleToolSummary(cell: CodexTranscriptCell, language: ConversationToolPresentationLanguage) {
  if (cell.status !== "completed") {
    return cell.summary?.trim() || cell.text?.trim() || "";
  }
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

function activityMeta(activity: CodexTranscriptToolActivity, language: ConversationToolPresentationLanguage) {
  const completed = activity.cells.filter((cell) => cell.status === "completed").length;
  const running = activity.cells.filter((cell) => cell.status === "running" || cell.status === "pending").length;
  const totalDuration = activity.cells
    .map(codexTranscriptToolDurationSeconds)
    .reduce<number | null>((total, duration) => {
      if (duration === null) {
        return total;
      }
      return (total ?? 0) + duration;
    }, null);
  const callLabel = language === "zh"
    ? `${activity.cells.length} 次调用`
    : `${activity.cells.length} calls`;
  const completedLabel = completed > 0
    ? (language === "zh" ? `${completed} 成功` : `${completed} succeeded`)
    : "";
  const runningLabel = running > 0
    ? (language === "zh" ? `${running} 运行中` : `${running} running`)
    : "";
  return [
    callLabel,
    totalDuration === null ? "" : formatCodexTranscriptDuration(totalDuration),
    completedLabel,
    runningLabel,
  ].filter(Boolean).join(" · ");
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
  const title = conversationToolRendererLabel(toolName, language);
  const summary = visibleToolSummary(cell, language);
  const meta = statusLabel(cell, language);
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
        <span className={styles.itemTitleLine}>
          <span className={styles.itemTitle}>{title}</span>
          <span className={styles.itemMeta}>{meta}</span>
        </span>
        {summary ? <span className={styles.itemPreview}>{summary}</span> : null}
      </span>
      {expandable ? (
        <ChevronRight
          className={styles.itemChevron}
          data-codex-tool-detail-toggle="inline-symbol"
          aria-hidden="true"
          size={15}
        />
      ) : <span aria-hidden="true" />}
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
      className={`${styles.item} ${styles.itemDetails}`}
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

export function ConversationToolActivity({
  activity,
  language,
  renderToolDetails,
}: ConversationToolActivityProps) {
  const grouped = activity.cells.length >= 3;
  if (!grouped) {
    return (
      <div className={styles.activity} data-codex-tool-activity="inline">
        {activity.cells.map((cell) => (
          <ToolActivityItem
            key={cell.id}
            cell={cell}
            language={language}
            renderToolDetails={renderToolDetails}
          />
        ))}
      </div>
    );
  }
  const descriptors = activity.cells.map((cell) => toolRendererForCell(cell, language));
  const firstDescriptor = descriptors[0] ?? conversationToolRendererFor("");
  const sameFamily = descriptors.every((descriptor) => descriptor.family === firstDescriptor.family);
  const GroupIcon = firstDescriptor.icon;
  const title = sameFamily
    ? firstDescriptor.groupLabel[language]
    : language === "zh" ? "工具调用" : "Tool activity";
  const latestSummary = [...activity.cells]
    .reverse()
    .map((cell) => visibleToolSummary(cell, language))
    .find(Boolean);
  const groupLabel = language === "zh"
    ? `展开或收起${title}，${activity.cells.length} 次调用`
    : `Expand or collapse ${title}, ${activity.cells.length} calls`;
  const isRunning = activity.cells.some((cell) => cell.status === "running" || cell.status === "pending");
  return (
    <details
      className={styles.group}
      data-codex-tool-activity-group="true"
      data-codex-tool-activity-id={activity.id}
      data-codex-tool-activity-count={activity.cells.length}
      aria-live={isRunning ? "polite" : undefined}
    >
      <summary className={styles.groupSummary} aria-label={groupLabel}>
        {isRunning
          ? <LoaderCircle className={`${styles.groupIcon} ${styles.groupIconRunning} animate-spin`} size={16} />
          : <GroupIcon className={styles.groupIcon} size={16} />}
        <span className={styles.groupBody}>
          <span className={styles.groupTitleLine}>
            <span className={styles.groupTitle}>{title}</span>
            <span className={styles.groupMeta}>{activityMeta(activity, language)}</span>
          </span>
          {latestSummary ? <span className={styles.groupPreview}>{latestSummary}</span> : null}
        </span>
        <ChevronRight className={styles.groupChevron} aria-hidden="true" size={16} />
      </summary>
      <div className={styles.groupItems}>
        {activity.cells.map((cell) => (
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
