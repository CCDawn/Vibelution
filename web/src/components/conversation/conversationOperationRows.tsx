import { CheckCircle2, CircleDot, LoaderCircle, TerminalSquare } from "lucide-react";

import type { TranslationKey } from "../../i18n/dictionaryTypes";
import type {
  AgentMessageOperation,
  AgentMessageOperationKind,
} from "./agentMessageOperations";
import {
  isRunningOperationStatus,
  operationDisplayLabel,
  operationStatusTone,
  isRetryOperation,
  type OperationStateLabels,
} from "./conversationOperationState";
import {
  operationGroupTitle as resolveOperationGroupTitle,
  hasOperationDetails as resolveHasOperationDetails,
  operationStatusFallbackText,
  operationStatusIconKind,
  operationStatusToneClassNameFromTone,
  operationTimelineTitle as resolveOperationTimelineTitle,
  operationVisualTone,
  processSummaryIconKind,
  rolloutTraceEventLabel as resolveRolloutTraceEventLabel,
} from "./conversationOperationPresentation";
import {
  buildCodexToolActivityPills,
  extractToolDisplayCommand,
  type CodexToolActivityPills,
} from "./conversationToolPresentation";
import { formatConversationDuration } from "./conversationTimeFormat";
import type { CodexRolloutTraceEvent } from "./codexRolloutTrace";
import styles from "./ConversationView.styles";

export type ConversationOperationRowsDeps = {
  lang: "zh" | "en";
  t: (key: TranslationKey) => string;
  statusLabel: (status: string) => string;
  operationStateLabels: OperationStateLabels;
};

/**
 * Codex operation-row presentation bindings: the lang/t/label-injecting
 * wrappers that ConversationView used to declare inline. The factory returns
 * the same function names so timeline call sites stay unchanged; identities
 * still rebuild per render, matching the old inline semantics.
 */
export function createConversationOperationRows({
  lang,
  t,
  statusLabel,
  operationStateLabels,
}: ConversationOperationRowsDeps) {
  const formatDuration = formatConversationDuration;

  function operationTone(operation: AgentMessageOperation) {
    return operationVisualTone(operation);
  }

  function operationStatusToneClassName(operation: AgentMessageOperation) {
    return operationStatusToneClassNameFromTone(operationStatusTone(operation));
  }

  function operationStatusIcon(operation: AgentMessageOperation, animateRunning = true) {
    const status = String(operation.status ?? "").trim().toLowerCase();
    switch (operationStatusIconKind(status, isRunningOperationStatus(status), animateRunning)) {
      case "done":
        return <CheckCircle2 size={14} />;
      case "running":
        return <LoaderCircle className={styles.statusSpinner} size={14} />;
      case "running_static":
      case "idle":
      default:
        return <CircleDot size={14} />;
    }
  }

  function operationStatusText(status: string | null | undefined) {
    return operationStatusFallbackText(String(status ?? ""), lang, statusLabel);
  }

  function rolloutTraceEventLabel(kind: CodexRolloutTraceEvent["kind"]) {
    return resolveRolloutTraceEventLabel(kind, lang);
  }

  function operationLabel(operation: AgentMessageOperation) {
    if (isRetryOperation(operation)) {
      return lang === "zh" ? "请求重试" : "Retrying";
    }
    return operationDisplayLabel(operation, operationStateLabels);
  }

  function operationGroupTitle(kind: AgentMessageOperationKind, count: number) {
    return resolveOperationGroupTitle(kind, count, {
      thoughtProcess: t("thoughtProcess"),
      mentalProcess: t("mentalProcess"),
      toolProcess: t("toolProcess"),
    });
  }

  function operationTimelineTitle(operations: AgentMessageOperation[]) {
    return resolveOperationTimelineTitle(operations, lang, {
      thoughtProcess: t("thoughtProcess"),
      mentalProcess: t("mentalProcess"),
      toolProcess: t("toolProcess"),
    });
  }

  function processSummaryIcon(tone: string) {
    switch (processSummaryIconKind(tone)) {
      case "failed":
        return <TerminalSquare size={14} />;
      case "done":
        return <CheckCircle2 size={14} />;
      case "running":
      case "degraded":
      case "default":
      default:
        return <CircleDot size={14} />;
    }
  }

  function hasOperationDetails(operation: AgentMessageOperation) {
    return resolveHasOperationDetails(operation);
  }

  function buildLegacyToolActivityPills(
    operation: AgentMessageOperation,
    options?: {
      status?: string;
      title?: string;
      summary?: string;
      durationLabel?: string;
    },
  ): CodexToolActivityPills {
    const rawToolName = String(
      operation.rawLabel
      || options?.title
      || operation.label
      || "",
    ).trim();
    const exitCode = typeof operation.exitCode === "number" ? operation.exitCode : null;
    // Prefer rawStatus so fallback/partial survive timeline status normalization.
    const status = operation.rawStatus || options?.status || operation.status;
    const timedOut = Boolean(operation.timedOut)
      || /超时|timed?\s*out/i.test(`${operation.summary || ""} ${operation.error || ""}`);
    // Prefer product-facing labels (operation.label / timeline title) over raw tool ids.
    const productActionLabel = [operation.label, options?.title]
      .map((value) => String(value || "").trim())
      .find((value) => value && value !== rawToolName && !/_tool$/i.test(value));
    const normalizedStatus = String(status || "").trim().toLowerCase();
    const isFailedRow = normalizedStatus === "failed"
      || normalizedStatus === "error"
      || timedOut;
    // Failed rows surface diagnostics; completed rows keep command/summary only (not raw previews).
    const diagnosticSubject = [
      operation.error,
      options?.summary,
      operation.summary,
    ].map((value) => String(value || "").trim()).find(Boolean) || "";
    const pills = buildCodexToolActivityPills({
      toolName: productActionLabel ? productActionLabel : rawToolName,
      status,
      language: lang === "en" ? "en" : "zh",
      durationSeconds: operation.durationSeconds,
      durationLabel: options?.durationLabel ?? formatDuration(operation.durationSeconds),
      toolSummary: isFailedRow ? diagnosticSubject : operation.summary,
      cellSummary: isFailedRow ? diagnosticSubject : (options?.summary || operation.summary),
      resultPreview: isFailedRow ? diagnosticSubject : undefined,
      displayCommand: isFailedRow ? "" : extractToolDisplayCommand(operation.arguments),
      timedOut,
      nonzeroExit: exitCode !== null && exitCode !== 0 && !isFailedRow,
    });
    if (productActionLabel && pills.actionLabel !== productActionLabel) {
      return { ...pills, actionLabel: productActionLabel };
    }
    return pills;
  }

  return {
    formatDuration,
    operationTone,
    operationStatusToneClassName,
    operationStatusIcon,
    operationStatusText,
    rolloutTraceEventLabel,
    operationLabel,
    operationGroupTitle,
    operationTimelineTitle,
    processSummaryIcon,
    hasOperationDetails,
    buildLegacyToolActivityPills,
  };
}
