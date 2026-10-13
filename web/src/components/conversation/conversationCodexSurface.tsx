import type { ReactNode, RefObject } from "react";
import { ChevronDown, LoaderCircle, TerminalSquare } from "lucide-react";

import type { ConversationMessage, SessionTurnError } from "../../api/types";
import {
  assistantTurnIsStreaming,
} from "../../routes/chatTurnProtocol";
import {
  buildCodexTranscriptTimelineNodes,
  createCodexTranscriptToolActivity,
  shouldAttachToolApprovalToActivity,
} from "./conversationToolActivityModel";
import {
  dedupeCodexTranscriptCellsForDisplay,
  settleCodexTranscriptActiveStatuses,
  type CodexTranscriptCell,
} from "./codexTranscriptCells";
import {
  isNoFinalAnswerStatusContent,
  isStreamingStatusPlaceholderContent,
} from "./conversationInternalStatus";
import { isAgentInboxMessage, isGroupRoomTranscriptMessage, isTurnErrorMessage } from "./conversationMessagePredicates";
import { resolveConversationTurnWorkSummary } from "./conversationTurnWorkStatus";
import { conversationChangedFilesFromMetadata, fileDeliveryFollowupDraft } from "./conversationFileDeliveryModel";
import { buildConversationToolActivityDetailRows } from "./conversationToolActivityDetail";
import { buildTurnErrorDiagnosticRows } from "./conversationTurnErrorPresentation";
import {
  completedToolPresentationSummary,
  conversationToolPresentationLabel,
} from "./conversationToolPresentation";
import { ConversationToolActivity } from "./ConversationToolActivity";
import { ConversationProcessDisclosure } from "./ConversationProcessDisclosure";
import { ConversationFileDeliveries } from "./ConversationFileDeliveries";
import type { ConversationToolApprovalSurface } from "./conversationViewTypes";
import type { AgentMessageTimelineRowIdentity } from "./agentMessageTimelineRows";
import type { createCodexTranscriptCellRenderers } from "./conversationCodexTranscriptCells";
import type { createConversationCodexToolDetails } from "./conversationCodexToolDetails";
import type { createConversationResponseBlocks } from "./conversationResponseBlocks";
import styles from "./ConversationView.styles";

type CodexCellRenderers = Pick<
  ReturnType<typeof createCodexTranscriptCellRenderers>,
  | "renderCodexProgressCell"
  | "renderCodexReasoningSummaryCell"
  | "codexTranscriptCellIcon"
  | "codexTranscriptCellTitle"
  | "codexTranscriptCellMeta"
  | "codexTranscriptVisibleSummary"
>;

type CodexToolDetails = Pick<
  ReturnType<typeof createConversationCodexToolDetails>,
  "renderCodexTranscriptToolDetailContent" | "codexTranscriptToolDetailIsEmpty"
>;

type ResponseBlocks = Pick<
  ReturnType<typeof createConversationResponseBlocks>,
  "renderResponseText" | "renderAssistantTranscriptResponseText" | "renderAssistantFileReferenceChips"
>;

export type ConversationCodexSurfaceDeps = CodexCellRenderers & CodexToolDetails & ResponseBlocks & {
  lang: "zh" | "en";
  sessionId: string;
  toolApproval: ConversationToolApprovalSurface | null;
  toolApprovalConsumedRef: RefObject<boolean>;
  turnError: SessionTurnError | null | undefined;
  turnErrorSupersededByFinalAnswer: boolean;
  imageArtifactUrlsBeforeMessage: Map<string, Set<string>>;
  activeTimelineMessageOrder: Map<string, number>;
  handleProcessDisclosureUserToggle: (summary: HTMLElement, nextExpanded: boolean) => void;
  showComposer: boolean;
  composerDisabled: boolean;
  composerValue: string;
  composerInputRef: RefObject<HTMLTextAreaElement | null>;
  onComposerChange: (value: string) => void;
};

/**
 * Codex transcript surface host: the per-cell renderer, the process/final
 * split, the tool-approval attach ledger and the file-delivery footer.
 * Extracted from ConversationView with identical output.
 */
export function createConversationCodexSurface({
  lang,
  sessionId,
  toolApproval,
  toolApprovalConsumedRef,
  turnError,
  turnErrorSupersededByFinalAnswer,
  imageArtifactUrlsBeforeMessage,
  activeTimelineMessageOrder,
  handleProcessDisclosureUserToggle,
  showComposer,
  composerDisabled,
  composerValue,
  composerInputRef,
  onComposerChange,
  renderCodexProgressCell,
  renderCodexReasoningSummaryCell,
  codexTranscriptCellIcon,
  codexTranscriptCellTitle,
  codexTranscriptCellMeta,
  codexTranscriptVisibleSummary,
  renderCodexTranscriptToolDetailContent,
  codexTranscriptToolDetailIsEmpty,
  renderResponseText,
  renderAssistantTranscriptResponseText,
  renderAssistantFileReferenceChips,
}: ConversationCodexSurfaceDeps) {
  // Failed/interrupted turns force their tool/work rows open (scene kept for
  // diagnosis): persisted turn_error, interrupted partials, and the live
  // turnError still in flight for this turn (same judgment as the banner).
  function turnWorkForceExpand(message: ConversationMessage): boolean {
    const turnId = message.role === "assistant" ? String(message.turnId || "").trim() : "";
    return isTurnErrorMessage(message)
      || message.metadata?.interrupted === true
      || Boolean(
        turnError
        && !turnErrorSupersededByFinalAnswer
        && turnId
        && String(turnError.turnId || "") === turnId,
      );
  }

  function renderCodexTranscriptCell(
    message: ConversationMessage,
    cell: CodexTranscriptCell,
    options?: { attachToolApproval?: boolean },
  ) {
    if (cell.kind === "assistant_markdown") {
      const text = cell.text?.trim() ?? "";
      if (!text || isNoFinalAnswerStatusContent(text) || isStreamingStatusPlaceholderContent(text)) {
        return null;
      }
      // Commentary is user-facing progress narration: its own lighter lane,
      // while reasoning_summary remains the collapsible thinking lane.
      if (cell.phase === "commentary") {
        return renderCodexProgressCell(message.id, cell, text);
      }
      return (
        <section
          key={cell.id}
          className={[styles.codexTranscriptCell, styles.codexTranscriptAssistantCell, styles.codexTranscriptFinalCell].filter(Boolean).join(" ")}
          data-codex-transcript-cell-kind={cell.kind}
          data-codex-transcript-cell-status={cell.status}
          data-codex-transcript-cell-tone={cell.tone}
          data-codex-transcript-cell-channel={cell.channel || undefined}
          data-codex-transcript-cell-phase={cell.phase ?? ""}
          data-conversation-part-key={cell.id}
        >
          {renderAssistantTranscriptResponseText(
            text,
            assistantTurnIsStreaming(message),
            imageArtifactUrlsBeforeMessage.get(message.id),
          )}
          {renderAssistantFileReferenceChips(message, text)}
        </section>
      );
    }
    if (cell.kind === "reasoning_summary") {
      return renderCodexReasoningSummaryCell(message, cell);
    }
    if (cell.kind === "error_notice") {
      const rawErrorTitle = cell.title?.trim() || (lang === "zh" ? "执行失败" : "Failed");
      const visibleErrorTitle = conversationToolPresentationLabel(rawErrorTitle, lang === "en" ? "en" : "zh");
      const errorText = completedToolPresentationSummary({
        cellSummary: cell.summary,
        resultPreview: cell.text,
        toolName: rawErrorTitle,
        status: cell.status,
        language: lang === "en" ? "en" : "zh",
      });
      const diagnosticRows = buildConversationToolActivityDetailRows(cell, lang === "en" ? "en" : "zh");
      const fallbackDiagnosticRows = diagnosticRows.length > 0
        ? diagnosticRows
        : buildTurnErrorDiagnosticRows(cell.diagnosticSummary, lang);
      const isCompactToolFailure = Boolean(cell.operationIds?.length);
      if (isCompactToolFailure) {
        const compactErrorSummary = (
          <>
            <span className={styles.codexTranscriptCellTitle}>{visibleErrorTitle}</span>
            {cell.failureCount && cell.failureCount > 1 ? (
              <span className={styles.codexTranscriptCellMeta}>· {cell.failureCount} {lang === "zh" ? "次" : "times"}</span>
            ) : null}
            {fallbackDiagnosticRows.length > 0 ? (
              <ChevronDown className={styles.codexTranscriptInlineChevron} size={14} aria-hidden="true" />
            ) : null}
            {errorText ? <span className={styles.codexTranscriptCellMeta} aria-hidden="true">·</span> : null}
            {errorText ? <span className={styles.codexTranscriptCompactErrorSummary}>{errorText}</span> : null}
          </>
        );
        return (
          <section
            key={cell.id}
            className={[styles.codexTranscriptCell, styles.codexTranscriptProcessCell, styles.codexTranscriptCell_error].filter(Boolean).join(" ")}
            data-codex-transcript-cell-kind={cell.kind}
            data-codex-transcript-cell-status={cell.status}
            data-codex-transcript-cell-tone={cell.tone}
            data-codex-tool-error-compact="true"
            data-conversation-part-key={cell.id}
            role="status"
          >
            <span className={styles.codexTranscriptCellIcon} aria-hidden="true">
              <TerminalSquare size={14} />
            </span>
            <div className={styles.codexTranscriptCellBody}>
              {fallbackDiagnosticRows.length > 0 ? (
                <details className={styles.codexTranscriptCompactErrorDetails} data-codex-error-diagnostic="true">
                  <summary className={`${styles.codexTranscriptCellTitleRow} ${styles.codexTranscriptCompactErrorDetailsSummary}`}>
                    {compactErrorSummary}
                  </summary>
                  <dl className={styles.turnErrorReasonList}>
                    {fallbackDiagnosticRows.map((row) => (
                      <div key={`${cell.id}-${row.label}-${row.value}`} className={styles.turnErrorReasonRow}>
                        <dt>{row.label}</dt>
                        <dd>{row.value}</dd>
                      </div>
                    ))}
                  </dl>
                </details>
              ) : (
                <div className={styles.codexTranscriptCellTitleRow}>
                  {compactErrorSummary}
                </div>
              )}
            </div>
          </section>
        );
      }
      return (
        <section
          key={cell.id}
          className={[styles.codexTranscriptCell, styles.codexTranscriptProcessCell, styles.codexTranscriptCell_error].filter(Boolean).join(" ")}
          data-codex-transcript-cell-kind={cell.kind}
          data-codex-transcript-cell-status={cell.status}
          data-codex-transcript-cell-tone={cell.tone}
          data-codex-transcript-cell-channel={cell.channel || undefined}
          data-codex-transcript-cell-phase={cell.phase ?? ""}
          data-codex-transcript-cell-terminal={cell.terminal ? "true" : "false"}
          data-conversation-part-key={cell.id}
          role="status"
        >
          <span className={styles.codexTranscriptCellIcon} aria-hidden="true">
            <TerminalSquare size={14} />
          </span>
          <div className={styles.codexTranscriptCellBody}>
            <span className={styles.codexTranscriptCellTitleRow}>
              <span className={styles.codexTranscriptCellTitle}>{cell.title?.trim() || (lang === "zh" ? "执行失败" : "Failed")}</span>
            </span>
            {errorText ? (
              <div className={styles.codexTranscriptCellSummary}>{renderResponseText(errorText)}</div>
            ) : null}
            {fallbackDiagnosticRows.length > 0 ? (
              <details className={styles.operationDetailsDisclosure} data-codex-error-diagnostic="true">
                <summary className={styles.operationDetailsSummary}>
                  <span className={styles.codexTranscriptCellTitle}>{lang === "zh" ? "诊断详情" : "Diagnostics"}</span>
                  <span className={styles.operationDetailsChevronButton} aria-hidden="true">
                    <span className={styles.operationDetailsChevronClosed}>▸</span>
                    <span className={styles.operationDetailsChevronOpen}>▾</span>
                  </span>
                </summary>
                <dl className={styles.turnErrorReasonList}>
                  {fallbackDiagnosticRows.map((row) => (
                    <div key={`${cell.id}-${row.label}-${row.value}`} className={styles.turnErrorReasonRow}>
                      <dt>{row.label}</dt>
                      <dd>{row.value}</dd>
                    </div>
                  ))}
                </dl>
              </details>
            ) : null}
          </div>
        </section>
      );
    }
    if (cell.kind === "stream_tail") {
      return (
        <section
          key={cell.id}
          className={`${styles.codexTranscriptCell} ${styles.codexTranscriptProcessCell} ${styles.codexTranscriptCell_running}`}
          data-codex-transcript-cell-kind={cell.kind}
          data-codex-transcript-cell-status={cell.status}
          data-codex-transcript-cell-tone={cell.tone}
          data-conversation-part-key={cell.id}
          role="status"
          aria-live="polite"
        >
          <span className={styles.codexTranscriptCellIcon} aria-hidden="true">
            <LoaderCircle className={styles.statusSpinner} size={14} />
          </span>
          <span className={styles.codexTranscriptCellBody}>
            <span className={styles.codexTranscriptCellTitle}>{lang === "zh" ? "正在生成" : "Streaming"}</span>
          </span>
        </section>
      );
    }
    if (cell.kind === "tool_call") {
      const activity = createCodexTranscriptToolActivity([cell]);
      const attachApproval = Boolean(
        options?.attachToolApproval
        && toolApproval
        && !toolApprovalConsumedRef.current
        && shouldAttachToolApprovalToActivity(activity, toolApproval.toolName, { preferAnyOpenWhenUnmatched: true }),
      );
      if (attachApproval) {
        toolApprovalConsumedRef.current = true;
      }
      return (
        <ConversationToolActivity
          key={cell.id}
          activity={activity}
          language={lang === "en" ? "en" : "zh"}
          renderToolDetails={renderCodexTranscriptToolDetailContent}
          approvalSlot={attachApproval && toolApproval ? toolApproval.content : null}
          sessionId={sessionId}
          turnFailed={turnWorkForceExpand(message)}
        />
      );
    }
    const toneClassName = styles[`codexTranscriptCell_${cell.tone}` as keyof typeof styles] ?? "";
    const icon = codexTranscriptCellIcon(cell);
    const title = codexTranscriptCellTitle(cell);
    const meta = codexTranscriptCellMeta(cell);
    const summary = codexTranscriptVisibleSummary(cell);
    return (
      <section
        key={cell.id}
        className={[styles.codexTranscriptCell, styles.codexTranscriptProcessCell, toneClassName].filter(Boolean).join(" ")}
        data-codex-transcript-cell-kind={cell.kind}
        data-codex-transcript-cell-status={cell.status}
        data-codex-transcript-cell-tone={cell.tone}
        data-codex-transcript-cell-channel={cell.channel || undefined}
        data-codex-transcript-cell-phase={cell.phase || undefined}
        data-conversation-part-key={cell.id}
        role={cell.status === "running" || cell.status === "pending" ? "status" : undefined}
        aria-live={cell.status === "running" || cell.status === "pending" ? "polite" : undefined}
      >
        <span className={styles.codexTranscriptCellIcon} aria-hidden="true">
          {icon}
        </span>
        <span className={styles.codexTranscriptCellBody}>
          <span className={styles.codexTranscriptCellTitleRow}>
            <span className={styles.codexTranscriptCellTitle}>{title}</span>
            {meta ? <span className={styles.codexTranscriptCellMeta}>{meta}</span> : null}
          </span>
          {summary ? <span className={styles.codexTranscriptCellSummary}>{summary}</span> : null}
        </span>
      </section>
    );
  }

  function renderCodexTranscriptCells(
    message: ConversationMessage,
    cells: CodexTranscriptCell[],
    rowIdentity: AgentMessageTimelineRowIdentity,
    isCompanionMode = false,
  ) {
    const visibleCells = dedupeCodexTranscriptCellsForDisplay(
      settleCodexTranscriptActiveStatuses(
        cells.filter((cell) => cell.kind !== "user"),
        { turnStreaming: assistantTurnIsStreaming(message) },
      ),
    );
    if (visibleCells.length === 0) {
      return null;
    }
    const isFinalResponseCell = (cell: CodexTranscriptCell) => (
      cell.kind === "assistant_markdown" && cell.phase !== "commentary"
    );
    const processCells = isCompanionMode
      ? []
      : visibleCells.filter((cell) => !isFinalResponseCell(cell));
    const finalCells = isCompanionMode
      ? visibleCells.filter((cell) => isFinalResponseCell(cell) || cell.kind === "error_notice")
      : visibleCells.filter(isFinalResponseCell);
    const renderTimelineNodes = (
      timelineCells: CodexTranscriptCell[],
      options?: { attachToolApproval?: boolean },
    ) => {
      const nodes = buildCodexTranscriptTimelineNodes(timelineCells);
      const canAttach = Boolean(options?.attachToolApproval && toolApproval && !toolApprovalConsumedRef.current);
      const toolActivities = nodes.filter((node) => node.kind === "tool_activity");
      const matchedActivityId = canAttach
        ? (
          toolActivities.find((node) => node.kind === "tool_activity" && shouldAttachToolApprovalToActivity(
            node.activity,
            toolApproval?.toolName,
            { preferAnyOpenWhenUnmatched: false },
          ))
          ?? toolActivities.find((node) => node.kind === "tool_activity" && shouldAttachToolApprovalToActivity(
            node.activity,
            toolApproval?.toolName,
            { preferAnyOpenWhenUnmatched: true },
          ))
          ?? toolActivities[toolActivities.length - 1]
        )
        : null;
      const matchedId = matchedActivityId && matchedActivityId.kind === "tool_activity"
        ? matchedActivityId.activity.id
        : "";
      return nodes.map((node) => {
        if (node.kind !== "tool_activity") {
          return renderCodexTranscriptCell(message, node.cell, { attachToolApproval: false });
        }
        const attachApproval = Boolean(canAttach && node.activity.id === matchedId);
        if (attachApproval) {
          toolApprovalConsumedRef.current = true;
        }
        return (
          <ConversationToolActivity
            key={node.activity.id}
            activity={node.activity}
            language={lang === "en" ? "en" : "zh"}
            renderToolDetails={renderCodexTranscriptToolDetailContent}
            toolDetailIsEmpty={codexTranscriptToolDetailIsEmpty}
            approvalSlot={attachApproval && toolApproval ? toolApproval.content : null}
            sessionId={sessionId}
            turnFailed={turnWorkForceExpand(message)}
          />
        );
      });
    };
    // ZCode AssistantHistoryStatus parity: one status trigger per settled
    // assistant turn, placed ahead of the transcript it summarizes, so a turn
    // never splits its worked time across two places.
    const transcriptWorkSummary = message.role === "assistant"
      && !isCompanionMode
      && !isAgentInboxMessage(message)
      && !isGroupRoomTranscriptMessage(message)
      && !assistantTurnIsStreaming(message)
      ? resolveConversationTurnWorkSummary(message)
      : null;
    return (
      <div
        className={styles.codexTranscriptSurface}
        data-codex-transcript-surface="true"
        data-conversation-part-key={`${rowIdentity.messageKey}:codex-transcript`}
      >
        {processCells.length > 0 || transcriptWorkSummary ? (
          <ConversationProcessDisclosure
            cells={processCells}
            language={lang === "en" ? "en" : "zh"}
            messageOrder={activeTimelineMessageOrder}
            onUserToggle={handleProcessDisclosureUserToggle}
            turnStreaming={assistantTurnIsStreaming(message)}
            workSummary={transcriptWorkSummary}
          >
            {/* Approvals stay composer-adjacent only (toolApprovalFallback); never re-attach into process rows. */}
            {processCells.length > 0
              ? renderTimelineNodes(processCells, { attachToolApproval: false })
              : null}
          </ConversationProcessDisclosure>
        ) : null}
        {finalCells.length > 0 ? (
          <div data-codex-final-response="true">
            {renderTimelineNodes(finalCells, { attachToolApproval: false })}
          </div>
        ) : null}
        {!isCompanionMode ? (
          <ConversationFileDeliveries
            cells={cells}
            language={lang === "en" ? "en" : "zh"}
            changedFiles={conversationChangedFilesFromMetadata(message.metadata)}
            sessionId={sessionId}
            turnId={message.role === "assistant" ? message.turnId : undefined}
            onContinue={showComposer && !composerDisabled ? (path) => {
              onComposerChange(fileDeliveryFollowupDraft(composerValue, path, lang === "en" ? "en" : "zh"));
              requestAnimationFrame(() => composerInputRef.current?.focus());
            } : undefined}
          />
        ) : null}
      </div>
    );
  }

  return {
    turnWorkForceExpand,
    renderCodexTranscriptCell,
    renderCodexTranscriptCells,
  };
}
