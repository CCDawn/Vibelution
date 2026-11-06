import {
  BrainCircuit,
  CheckCircle2,
  CircleDot,
  LoaderCircle,
  TerminalSquare,
} from "lucide-react";
import type { ReactNode } from "react";

import { VButton } from "../vui";
import type { TranslationKey } from "../../i18n/dictionaryTypes";
import type { ConversationMessage } from "../../api/types";
import type { CodexTranscriptCell } from "./codexTranscriptCells";
import {
  codexTranscriptToolDurationSeconds,
  formatCodexTranscriptDuration,
} from "./conversationToolActivityModel";
import {
  completedToolPresentationSummary,
  conversationToolPresentationLabel,
} from "./conversationToolPresentation";
import {
  ThoughtDurationLabel,
  ThoughtScrollBody,
  ThoughtStreamingSummary,
} from "./conversationThoughtUnits";
import { stripAnsiArtifacts } from "./conversationAnsiSanitize";
import styles from "./ConversationView.styles";
import processStyles from "./ConversationProcessDisclosure.styles";

export function reasoningExpansionSectionId(cell: Pick<CodexTranscriptCell, "id" | "sourceItemId">) {
  // Prefer sourceItemId so stream updates that rewrite cell.id keep the same open/closed choice.
  const stable = String(cell.sourceItemId || cell.id || "").trim();
  return `reasoning:${stable || "active"}`;
}

export type CodexTranscriptCellRenderersDeps = {
  lang: "zh" | "en";
  t: (key: TranslationKey) => string;
  getExpansionState: (messageId: string, section: string, defaultExpanded: boolean) => boolean;
  toggleSection: (messageId: string, section: string, defaultExpanded: boolean) => void;
  /** Reuse the owning conversation's Markdown renderer for public narration. */
  renderProgressText?: (text: string, streaming: boolean) => ReactNode;
};

/**
 * Codex transcript cell presentation and the thought/progress lanes, bound to
 * the conversation's expansion store. Public narration stays in the flow;
 * each reasoning unit owns its native disclosure in both hosts.
 */
export function createCodexTranscriptCellRenderers({
  lang,
  t,
  getExpansionState,
  toggleSection,
  renderProgressText,
}: CodexTranscriptCellRenderersDeps) {
  /**
   * Collapsible thinking lane (ZCode reasoning parity): the row stays visible
   * with a compact summary until the user expands this unit. The collapsed header
   * keeps icon + status title plus a single-line horizontally rolling summary
   * of the latest thought sentence; the expanded body is height-capped and
   * bottom-following.
   */
  function renderCodexThoughtScrollCell(
    messageId: string,
    input: {
      cellId: string;
      sectionId: string;
      text: string;
      status: CodexTranscriptCell["status"];
      tone: CodexTranscriptCell["tone"];
      phase?: string;
      channel?: string;
      kind?: CodexTranscriptCell["kind"];
      settledDurationSeconds?: number;
      presentation?: "flow";
      expanded?: boolean;
    },
  ) {
    // Narration lanes render plain text only: terminal SGR artifacts from
    // tool output or model prose are presentation noise, not content.
    const fullText = stripAnsiArtifacts(input.text || "").trim();
    if (!fullText) {
      return null;
    }
    const isLive = input.status === "running" || input.status === "pending";
    // The shared session expansion store preserves explicit choices over lifecycle defaults.
    const defaultExpanded = false;
    const expanded = getExpansionState(messageId, input.sectionId, defaultExpanded);
    const thoughtTitle = isLive
      ? (lang === "zh" ? "思考中" : "Thinking…")
      : (lang === "zh" ? "已思考" : "Thought");
    const toneClassName = styles[`codexTranscriptCell_${input.tone}` as keyof typeof styles] ?? "";
    return (
      <section
        key={input.presentation === "flow" ? input.sectionId : input.cellId}
        className={[
          styles.codexTranscriptCell,
          styles.codexTranscriptReasoningCell,
          toneClassName,
        ].filter(Boolean).join(" ")}
        data-codex-transcript-cell-kind={input.kind || "assistant_markdown"}
        data-codex-transcript-cell-status={input.status}
        data-codex-transcript-cell-tone={input.tone}
        data-codex-transcript-cell-channel={input.channel || undefined}
        data-codex-transcript-cell-phase={input.phase ?? ""}
        data-conversation-part-key={input.cellId}
        data-thought-section={input.sectionId}
        data-thought-expanded={expanded ? "true" : "false"}
        role={isLive ? "status" : undefined}
        aria-live={isLive ? "polite" : undefined}
      >
        <VButton
          type="button"
          contentLayout="plain"
          className={styles.codexTranscriptReasoningHeader}
          aria-expanded={expanded}
          aria-label={expanded ? t("thoughtProcessVisible") : t("thoughtProcessHidden")}
          onClick={(event) => {
            event.stopPropagation();
            toggleSection(messageId, input.sectionId, defaultExpanded);
          }}
        >
          <span className={styles.codexTranscriptReasoningIcon} aria-hidden="true">
            {isLive
              ? <LoaderCircle className={styles.statusSpinner} size={14} />
              : <BrainCircuit size={14} />}
          </span>
          <span className={styles.codexTranscriptReasoningHeaderBody}>
            <span className={styles.codexTranscriptReasoningTitleRow}>
              <span className={styles.codexTranscriptReasoningTitle}>{thoughtTitle}</span>
              <ThoughtDurationLabel
                live={isLive}
                expanded={expanded}
                settledDurationSeconds={input.settledDurationSeconds}
                settledSecondsTemplate={t("thoughtDurationSettledSeconds")}
                settledMomentsLabel={t("thoughtDurationSettledMoments")}
              />
              {!expanded && isLive ? <ThoughtStreamingSummary text={fullText} /> : null}
            </span>
          </span>
        </VButton>
        {expanded ? <ThoughtScrollBody text={fullText} streaming={isLive} className={styles.codexTranscriptReasoningBody} /> : null}
      </section>
    );
  }

  /**
   * Progress narration lane (commentary): user-facing updates stay visible in
   * chronological order, with the same full text while live and settled.
   */
  function renderCodexProgressCell(
    _messageId: string,
    cell: CodexTranscriptCell,
    text: string,
  ) {
    const cleanText = stripAnsiArtifacts(text);
    const isLive = cell.status === "running" || cell.status === "pending";
    return (
      <section
        key={cell.id}
        className={processStyles.progress}
        data-codex-transcript-cell-kind={cell.kind}
        data-codex-transcript-cell-status={cell.status}
        data-codex-transcript-cell-tone={cell.tone}
        data-codex-transcript-cell-channel={cell.channel || undefined}
        data-codex-transcript-cell-phase={cell.phase ?? ""}
        data-codex-progress-cell="true"
        data-codex-progress-expandable="false"
        data-conversation-part-key={cell.id}
        role={isLive ? "status" : undefined}
        aria-live={isLive ? "polite" : undefined}
      >
        <div className={processStyles.progressBody} data-codex-progress-body="true" data-codex-progress-clamped="false">
          {renderProgressText ? renderProgressText(cleanText, isLive) : <span className={processStyles.progressPlainText}>{cleanText}</span>}
        </div>
      </section>
    );
  }

  function renderCodexReasoningSummaryCell(
    message: ConversationMessage,
    cell: CodexTranscriptCell,
    options?: { presentation?: "flow"; expanded?: boolean },
  ) {
    const fullText = String(cell.text || cell.summary || "").trim();
    if (!fullText) {
      return null;
    }
    return renderCodexThoughtScrollCell(message.id, {
      cellId: cell.id,
      sectionId: reasoningExpansionSectionId(cell),
      text: fullText,
      status: cell.status,
      tone: cell.tone,
      phase: cell.phase,
      channel: cell.channel,
      kind: cell.kind,
      settledDurationSeconds: cell.settledDurationSeconds,
      presentation: options?.presentation,
      expanded: options?.expanded,
    });
  }

  function codexTranscriptVisibleSummary(cell: CodexTranscriptCell) {
    if (cell.kind === "tool_call") {
      return cell.status === "completed"
        ? codexTranscriptCompletedToolSummary(cell)
        : cell.summary || cell.text;
    }
    if (cell.kind === "error_notice") {
      return "";
    }
    if (cell.kind === "reasoning_summary") {
      // Collapsed preview is rendered by renderCodexReasoningSummaryCell.
      return cell.summary || cell.text;
    }
    return cell.summary || cell.text;
  }

  function codexTranscriptCompletedToolSummary(cell: CodexTranscriptCell) {
    const toolCall = cell.toolLifecycleModel?.toolCalls?.[0];
    return completedToolPresentationSummary({
      toolSummary: toolCall?.summary,
      cellSummary: cell.summary,
      resultPreview: toolCall?.resultPreview,
      cellText: cell.text,
      toolName: toolCall?.rawToolName || cell.title,
      status: cell.status,
      language: lang,
    });
  }

  function codexTranscriptCellIcon(cell: CodexTranscriptCell) {
    if (cell.status === "running" || cell.status === "pending") {
      return <LoaderCircle className={styles.statusSpinner} size={14} />;
    }
    if (cell.kind === "reasoning_summary") {
      return <BrainCircuit size={14} />;
    }
    if (cell.kind === "status") {
      return <CircleDot size={14} />;
    }
    if (cell.kind === "error_notice" || cell.status === "failed") {
      return <TerminalSquare size={14} />;
    }
    return <CheckCircle2 size={14} />;
  }

  function codexTranscriptCellTitle(cell: CodexTranscriptCell) {
    if (cell.kind === "tool_call") {
      const rawToolName = cell.toolLifecycleModel?.toolCalls?.[0]?.rawToolName?.trim();
      const rawTitle = cell.title?.trim();
      return codexTranscriptToolLabel(rawToolName || rawTitle || "");
    }
    if (cell.title?.trim()) {
      return cell.title.trim();
    }
    if (cell.kind === "reasoning_summary") {
      return lang === "zh" ? "思考" : "Reasoning";
    }
    if (cell.kind === "status") {
      return lang === "zh" ? "状态" : "Status";
    }
    if (cell.kind === "error_notice") {
      return lang === "zh" ? "执行失败" : "Failed";
    }
    return lang === "zh" ? "工具调用" : "Tool call";
  }

  function codexTranscriptToolLabel(name: string) {
    return conversationToolPresentationLabel(name, lang);
  }

  function codexTranscriptCellMeta(cell: CodexTranscriptCell) {
    if (cell.status === "completed") {
      const duration = codexTranscriptToolDurationSeconds(cell);
      const completedLabel = lang === "zh" ? "完成" : "Completed";
      return duration === null ? completedLabel : `${completedLabel} ${formatCodexTranscriptDuration(duration)}`;
    }
    if (cell.status === "failed") {
      return lang === "zh" ? "失败" : "Failed";
    }
    if (cell.status === "degraded") {
      return lang === "zh" ? "降级" : "Degraded";
    }
    if (cell.status === "pending") {
      return lang === "zh" ? "等待中" : "Pending";
    }
    if (cell.status === "running") {
      return lang === "zh" ? "运行中" : "Running";
    }
    return "";
  }

  return {
    renderCodexThoughtScrollCell,
    renderCodexProgressCell,
    renderCodexReasoningSummaryCell,
    codexTranscriptVisibleSummary,
    codexTranscriptCompletedToolSummary,
    codexTranscriptCellIcon,
    codexTranscriptCellTitle,
    codexTranscriptToolLabel,
    codexTranscriptCellMeta,
  };
}
