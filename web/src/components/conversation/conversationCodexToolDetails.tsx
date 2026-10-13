import type { ReactNode } from "react";

import type { CodexTranscriptCell } from "./codexTranscriptCells";
import type { AgentMessageOperation } from "./agentMessageOperations";
import { buildCodexRolloutTraceEvents } from "./codexRolloutTrace";
import { operationStatusTone } from "./conversationOperationState";
import {
  buildConversationToolActivityDetailRows,
  conversationToolActivityEmptyDetailLabel,
} from "./conversationToolActivityDetail";
import { buildTurnErrorDiagnosticRows } from "./conversationTurnErrorPresentation";
import { codexTranscriptToolRawName } from "./conversationToolActivityModel";
import { conversationToolDetailPresentation } from "./conversationToolPresentation";
import {
  buildConversationTerminalToolDetail,
  ConversationTerminalToolDetail,
} from "./ConversationTerminalToolDetail";
import { ConversationPatchDiff } from "./ConversationPatchDiff";
import { conversationToolPatchText } from "./conversationPatchModel";
import type { OperationDetailLabels, OperationDetailRow } from "./ConversationOperationDetails";
import type { createCodexTranscriptCellRenderers } from "./conversationCodexTranscriptCells";
import type { createConversationOperationRows } from "./conversationOperationRows";
import styles from "./ConversationView.styles";

export type ConversationCodexToolDetailsDeps = {
  lang: "zh" | "en";
  operationDetailLabels: OperationDetailLabels;
  rolloutTraceEventLabel: ReturnType<typeof createConversationOperationRows>["rolloutTraceEventLabel"];
  codexTranscriptCellTitle: ReturnType<typeof createCodexTranscriptCellRenderers>["codexTranscriptCellTitle"];
};

/**
 * Codex tool-call detail builders (rows, rollout events, patch diff) and the
 * detail-content renderer consumed by ConversationToolActivity. Extracted
 * from ConversationView with identical output; the isEmpty probe mirrors the
 * detail builder so a row with nothing to expand renders no toggle.
 */
export function createConversationCodexToolDetails({
  lang,
  operationDetailLabels,
  rolloutTraceEventLabel,
  codexTranscriptCellTitle,
}: ConversationCodexToolDetailsDeps) {
  function firstNonEmptyText(...values: Array<string | undefined | null>) {
    for (const value of values) {
      const text = String(value ?? "").trim();
      if (text) {
        return text;
      }
    }
    return "";
  }

  /** Codex/opencode parity: replay keeps the command, not just the result blob. */
  function codexTranscriptToolInstructionText(argumentsRecord: Record<string, unknown> | undefined | null) {
    if (!argumentsRecord || typeof argumentsRecord !== "object") {
      return "";
    }
    const pickString = (keys: string[]) => {
      for (const key of keys) {
        const value = argumentsRecord[key];
        if (typeof value === "string" && value.trim()) {
          return value.trim();
        }
        if (Array.isArray(value) && value.length > 0) {
          const joined = value.map((entry) => String(entry ?? "")).join(" ").trim();
          if (joined) {
            return joined;
          }
        }
      }
      return "";
    };
    const direct = pickString(["command", "cmd", "shell_command", "path", "query", "url"]);
    if (direct) {
      return direct;
    }
    try {
      const serialized = JSON.stringify(argumentsRecord);
      return serialized && serialized !== "{}" ? serialized : "";
    } catch {
      return "";
    }
  }

  function boundedCodexToolDetailText(value: string) {
    const normalized = String(value ?? "").trim();
    if (!normalized) {
      return "";
    }
    const maxLines = 18;
    const maxChars = 1600;
    const lines = normalized.split(/\r?\n/);
    const lineBounded = lines.slice(0, maxLines).join("\n").trimEnd();
    const lengthBounded = lineBounded.length > maxChars
      ? lineBounded.slice(0, maxChars).trimEnd()
      : lineBounded;
    const omittedLineCount = Math.max(0, lines.length - maxLines);
    const omittedCharCount = Math.max(0, normalized.length - lengthBounded.length);
    const notices = [
      omittedLineCount > 0 ? (lang === "zh" ? `已省略 ${omittedLineCount} 行` : `${omittedLineCount} lines omitted`) : "",
      omittedCharCount > 0 ? (lang === "zh" ? `已省略 ${omittedCharCount} 个字符` : `${omittedCharCount} characters omitted`) : "",
    ].filter(Boolean);
    return notices.length > 0 ? `${lengthBounded}\n\n[${notices.join(lang === "zh" ? "，" : ", ")}]` : lengthBounded;
  }

  function codexTranscriptToolDetailRows(cell: CodexTranscriptCell): OperationDetailRow[] {
    const model = cell.toolLifecycleModel;
    if (!model) {
      return [];
    }
    const operationIds = new Set(cell.operationIds ?? []);
    const matchedToolCalls = model.toolCalls.filter((toolCall) =>
      operationIds.size === 0
      || operationIds.has(toolCall.rawOperationId)
      || operationIds.has(toolCall.toolCallId)
      || (toolCall.terminalOperationId ? operationIds.has(toolCall.terminalOperationId) : false)
    );
    const toolCalls = matchedToolCalls.length > 0 ? matchedToolCalls : model.toolCalls;
    const toolCallIds = new Set(toolCalls.map((toolCall) => toolCall.toolCallId).filter(Boolean));
    const terminalOperations = model.terminalOperations.filter((operation) =>
      toolCallIds.has(operation.toolCallId)
      || operationIds.has(operation.rawOperationId)
      || operationIds.has(operation.operationId)
    );
    const rows: OperationDetailRow[] = [];
    const primaryToolCall = toolCalls[0];
    const toolName = primaryToolCall?.rawToolName || primaryToolCall?.title || codexTranscriptToolRawName(cell);
    const presentDetail = (value: string) => boundedCodexToolDetailText(
      conversationToolDetailPresentation({
        value,
        toolName,
        language: lang,
      }),
    );
    const visibleTitle = codexTranscriptCellTitle(cell);
    const instructionLabel = lang === "zh" ? "指令" : "Instruction";
    const pushedInstructions = new Set<string>();
    function pushInstruction(value: string) {
      const text = value.trim();
      if (!text || text === visibleTitle || pushedInstructions.has(text)) {
        return;
      }
      pushedInstructions.add(text);
      rows.push({ label: instructionLabel, value: presentDetail(text) });
    }
    for (const operation of terminalOperations) {
      const displayCommand = operation.request?.displayCommand?.trim();
      if (displayCommand) {
        pushInstruction(displayCommand);
      }
      const output = firstNonEmptyText(
        operation.result?.formattedOutput,
        operation.result?.stdout,
      );
      if (output) {
        rows.push({
          label: operationDetailLabels.toolCallResult,
          value: presentDetail(output),
        });
      }
      const error = firstNonEmptyText(operation.result?.stderr);
      if (error) {
        rows.push({
          label: operationDetailLabels.toolCallError,
          value: presentDetail(error),
        });
      }
    }
    const resultPreview = firstNonEmptyText(...toolCalls.map((toolCall) => toolCall.resultPreview));
    if (!rows.some((row) => row.label === instructionLabel)) {
      const argumentInstruction = codexTranscriptToolInstructionText(primaryToolCall?.arguments);
      if (argumentInstruction) {
        pushInstruction(argumentInstruction);
      }
    }
    const resultTruncated = toolCalls.some((toolCall) => toolCall.truncated === true);
    if (resultPreview && !rows.some((row) => row.label === operationDetailLabels.toolCallResult && row.value.includes(resultPreview.slice(0, 80)))) {
      const boundedResult = presentDetail(resultPreview);
      rows.push({
        label: operationDetailLabels.toolCallResult,
        value: resultTruncated && boundedResult
          ? `${boundedResult}\n\n[${lang === "zh" ? "输出已截断，仅显示预览" : "Output truncated; preview only"}]`
          : boundedResult,
      });
    }
    const error = firstNonEmptyText(...toolCalls.map((toolCall) => toolCall.error));
    if (error) {
      rows.push({
        label: operationDetailLabels.toolCallError,
        value: presentDetail(error),
      });
    }
    return rows;
  }

  function renderCodexTranscriptRolloutEvents(cell: CodexTranscriptCell) {
    if (cell.tone !== "error" && cell.tone !== "warning" && cell.status !== "running") {
      return null;
    }
    const events = cell.rolloutTraceEvents ?? [];
    if (events.length === 0) {
      return null;
    }
    return (
      <details
        className={styles.operationDetailsDisclosure}
        data-codex-tool-technical-details="true"
      >
        <summary className={styles.operationDetailsSummary}>
          <span className={styles.operationDetailsChevronButton} aria-hidden="true">
            <span className={styles.operationDetailsChevronClosed}>▸</span>
            <span className={styles.operationDetailsChevronOpen}>▾</span>
          </span>
          <span>{lang === "zh" ? "技术详情" : "Technical details"}</span>
        </summary>
        <ol className={styles.rolloutTraceList} aria-label={lang === "zh" ? "工具生命周期" : "Tool lifecycle"}>
          {events.map((event) => {
            const eventClassName = [
              styles.rolloutTraceItem,
              styles[`rolloutTraceItem_${event.status}`],
            ].filter(Boolean).join(" ");
            const detailText = [
              event.error,
              event.exitCode !== undefined && event.exitCode !== null ? `exit ${event.exitCode}` : "",
              event.timedOut ? (lang === "zh" ? "已超时" : "timed out") : "",
            ].filter(Boolean).join(" · ");
            return (
              <li
                key={event.id}
                className={eventClassName}
                data-rollout-trace-kind={event.kind}
                data-rollout-trace-status={event.status}
                data-rollout-tool-call-id={event.toolCallId}
                data-rollout-terminal-operation-id={event.terminalOperationId}
                data-rollout-terminal-id={event.terminalId}
              >
                <span className={styles.rolloutTraceDot} aria-hidden="true" />
                <span className={styles.rolloutTraceText}>
                  <span className={styles.rolloutTraceTitle}>{rolloutTraceEventLabel(event.kind)}</span>
                  {detailText ? <span className={styles.rolloutTraceMeta}>{detailText}</span> : null}
                </span>
              </li>
            );
          })}
        </ol>
      </details>
    );
  }

  function renderCodexTranscriptToolDetailContent(cell: CodexTranscriptCell): ReactNode {
    if (cell.kind === "error_notice") {
      const activityRows = buildConversationToolActivityDetailRows(cell, lang);
      const diagnosticRows = activityRows.length > 0
        ? activityRows
        : buildTurnErrorDiagnosticRows(cell.diagnosticSummary, lang);
      if (diagnosticRows.length === 0) {
        return (
          <p className={styles.codexTranscriptCellMeta}>{conversationToolActivityEmptyDetailLabel(lang)}</p>
        );
      }
      return (
        <dl className={styles.turnErrorReasonList} data-codex-error-diagnostic="true">
          {diagnosticRows.map((row) => (
            <div key={`${cell.id}-${row.label}-${row.value}`} className={styles.turnErrorReasonRow}>
              <dt>{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
      );
    }
    if (cell.kind !== "tool_call") {
      return null;
    }
    const terminalDetail = buildConversationTerminalToolDetail(cell, lang);
    const rows = terminalDetail ? [] : codexTranscriptToolDetailRows(cell);
    const rolloutEvents = renderCodexTranscriptRolloutEvents(cell);
    const patchText = conversationToolPatchText(cell);
    const patchDiff = patchText
      ? <ConversationPatchDiff patchText={patchText} language={lang} />
      : null;
    if (!terminalDetail && rows.length === 0 && !rolloutEvents) {
      const extraRows = buildConversationToolActivityDetailRows(cell, lang);
      if (extraRows.length === 0) {
        return (
          <>
            {patchDiff}
            {!patchDiff ? (
              <p className={styles.codexTranscriptCellMeta}>{conversationToolActivityEmptyDetailLabel(lang)}</p>
            ) : null}
          </>
        );
      }
      return (
        <>
          {patchDiff}
          <dl className={styles.turnErrorReasonList} data-codex-tool-activity-detail="true">
            {extraRows.map((row) => (
              <div key={`${cell.id}-${row.label}-${row.value}`} className={styles.turnErrorReasonRow}>
                <dt>{row.label}</dt>
                <dd>{row.value}</dd>
              </div>
            ))}
          </dl>
        </>
      );
    }
    return (
      <>
        {patchDiff}
        {terminalDetail ? (
          <ConversationTerminalToolDetail detail={terminalDetail} language={lang} />
        ) : rows.length > 0 ? (
          <div className={styles.operationDetails}>
            {rows.map((row, index) => {
              return (
                <div key={`${cell.id}-${row.label}-${index}`} className={styles.operationDetailRow}>
                  <pre
                    className={styles.operationDetailValue}
                    aria-label={row.label}
                    tabIndex={0}
                  >
                    {row.value}
                  </pre>
                </div>
              );
            })}
          </div>
        ) : null}
        {rolloutEvents}
      </>
    );
  }

  /**
   * Codex/opencode parity: a row with nothing to expand renders no toggle.
   * Mirrors the detail builder above so the two can never disagree.
   */
  function codexTranscriptToolDetailIsEmpty(cell: CodexTranscriptCell): boolean {
    if (cell.kind === "error_notice") {
      const activityRows = buildConversationToolActivityDetailRows(cell, lang);
      const diagnosticRows = activityRows.length > 0
        ? activityRows
        : buildTurnErrorDiagnosticRows(cell.diagnosticSummary, lang);
      return diagnosticRows.length === 0;
    }
    if (cell.kind !== "tool_call") {
      return true;
    }
    if (buildConversationTerminalToolDetail(cell, lang)) {
      return false;
    }
    if (codexTranscriptToolDetailRows(cell).length > 0) {
      return false;
    }
    if (renderCodexTranscriptRolloutEvents(cell)) {
      return false;
    }
    if (conversationToolPatchText(cell)) {
      return false;
    }
    return buildConversationToolActivityDetailRows(cell, lang).length === 0;
  }

  function renderRolloutTraceEvents(operation: AgentMessageOperation) {
    if (operation.kind !== "tool") {
      return null;
    }
    if (operationStatusTone(operation) === "done") {
      return null;
    }
    const events = buildCodexRolloutTraceEvents(operation);
    if (events.length === 0) {
      return null;
    }
    return (
      <ol className={styles.rolloutTraceList} aria-label={lang === "zh" ? "工具生命周期" : "Tool lifecycle"}>
        {events.map((event) => {
          const eventClassName = [
            styles.rolloutTraceItem,
            styles[`rolloutTraceItem_${event.status}`],
          ].filter(Boolean).join(" ");
          const detailText = [
            event.error,
            event.exitCode !== undefined && event.exitCode !== null ? `exit ${event.exitCode}` : "",
            event.timedOut ? (lang === "zh" ? "已超时" : "timed out") : "",
          ].filter(Boolean).join(" · ");
          return (
            <li
              key={event.id}
              className={eventClassName}
              data-rollout-trace-kind={event.kind}
              data-rollout-trace-status={event.status}
              data-rollout-tool-call-id={event.toolCallId}
              data-rollout-terminal-operation-id={event.terminalOperationId}
              data-rollout-terminal-id={event.terminalId}
            >
              <span className={styles.rolloutTraceDot} aria-hidden="true" />
              <span className={styles.rolloutTraceText}>
                <span className={styles.rolloutTraceTitle}>{rolloutTraceEventLabel(event.kind)}</span>
                {detailText ? <span className={styles.rolloutTraceMeta}>{detailText}</span> : null}
              </span>
            </li>
          );
        })}
      </ol>
    );
  }

  return {
    codexTranscriptToolDetailRows,
    renderCodexTranscriptRolloutEvents,
    renderCodexTranscriptToolDetailContent,
    codexTranscriptToolDetailIsEmpty,
    renderRolloutTraceEvents,
  };
}
