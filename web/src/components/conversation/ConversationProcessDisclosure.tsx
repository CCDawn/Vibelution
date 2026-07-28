import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";

import type { CodexTranscriptCell } from "./codexTranscriptCells";
import {
  codexTranscriptToolDurationSeconds,
  formatCodexTranscriptDuration,
} from "./conversationToolActivityModel";
import { buildConversationToolActivityPresentation } from "./conversationToolActivityPresentation";
import styles from "./ConversationProcessDisclosure.styles";

type ConversationProcessDisclosureProps = {
  cells: readonly CodexTranscriptCell[];
  language: "zh" | "en";
  children: ReactNode;
};

function processState(cells: readonly CodexTranscriptCell[]) {
  if (cells.some((cell) => cell.status === "running" || cell.status === "pending")) {
    return "running";
  }
  if (cells.some((cell) => cell.status === "failed")) {
    return "failed";
  }
  return "completed";
}

function processDuration(cells: readonly CodexTranscriptCell[]) {
  const durations = cells
    .map(codexTranscriptToolDurationSeconds)
    .filter((duration): duration is number => duration !== null);
  if (durations.length === 0) {
    return null;
  }
  return durations.reduce((total, duration) => total + duration, 0);
}

function processLabel(cells: readonly CodexTranscriptCell[], language: "zh" | "en") {
  const state = processState(cells);
  const labels = language === "zh"
    ? { completed: "已处理", failed: "处理已停止", running: "处理中" }
    : { completed: "Processed", failed: "Processing stopped", running: "Processing" };
  const duration = processDuration(cells);
  const stageCells = cells.filter(
    (cell) => cell.kind === "tool_call" || cell.kind === "error_notice",
  );
  const stageCount = buildConversationToolActivityPresentation(stageCells, language).length;
  let stageLabel = "";
  if (stageCount > 0) {
    stageLabel = language === "zh"
      ? `${stageCount} 个阶段`
      : `${stageCount} ${stageCount === 1 ? "stage" : "stages"}`;
  }
  return [
    labels[state],
    duration === null ? "" : formatCodexTranscriptDuration(duration),
    stageLabel,
  ].filter(Boolean).join(" ");
}

export function ConversationProcessDisclosure({
  cells,
  language,
  children,
}: ConversationProcessDisclosureProps) {
  const running = processState(cells) === "running";
  const label = processLabel(cells, language);
  const toggleLabel = language === "zh"
    ? "展开或收起处理记录"
    : "Expand or collapse process details";

  return (
    <details
      className={styles.disclosure}
      data-codex-process-disclosure="true"
      data-codex-process-state={processState(cells)}
      aria-live={running ? "polite" : undefined}
      open={running || undefined}
    >
      <summary className={styles.summary} aria-label={toggleLabel}>
        <span>{label}</span>
        <ChevronRight className={styles.chevron} size={14} aria-hidden="true" />
      </summary>
      <div className={styles.content}>{children}</div>
    </details>
  );
}
