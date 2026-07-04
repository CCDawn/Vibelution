import React, { useDeferredValue } from "react";

import type { AgentMessageOperation } from "./agentMessageOperations";

export type OperationDetailKind = "thought" | "status" | "tool";
export type OperationDetailRow = { label: string; value: string };
export type OperationDetailLabels = {
  rawName: string;
  fullStatus: string;
  toolCallArguments: string;
  thoughtProcess: string;
  toolCallResult: string;
  toolCallError: string;
  structuredResultFallback: string;
};

export type ConversationOperationDetailsClassNames = {
  operationDetails: string;
  operationDetailsThought: string;
  operationDetailRow: string;
  operationDetailLabel: string;
  operationDetailValue: string;
};

type DeferredOperationDetailsProps = {
  operation: AgentMessageOperation;
  expanded: boolean;
  detailsId: string;
  kind: OperationDetailKind;
  buildDetailRows: (operation: AgentMessageOperation) => OperationDetailRow[];
  classNames: ConversationOperationDetailsClassNames;
  className?: string;
};

export function operationDetailsKind(operation: AgentMessageOperation): OperationDetailKind {
  if (operation.kind === "thought") {
    return "thought";
  }
  if (operation.kind === "status") {
    return "status";
  }
  return "tool";
}

export function readableOperationResult(
  operation: AgentMessageOperation,
  structuredResultFallback: string,
) {
  const result = String(operation.resultPreview ?? "").trim();
  if (!result) {
    return "";
  }
  if (shouldKeepResultInDetailsOnly(operation, result)) {
    return "";
  }
  if (!/^[{[]/.test(result)) {
    return result;
  }
  try {
    const parsed = JSON.parse(result) as unknown;
    const summary = structuredResultSummary(parsed);
    return summary || structuredResultFallback;
  } catch {
    return result;
  }
}

export function buildOperationDetailRows(
  operation: AgentMessageOperation,
  labels: OperationDetailLabels,
): OperationDetailRow[] {
  const rows: OperationDetailRow[] = [];
  const args = operation.arguments ?? {};
  const rawLabel = operation.kind === "tool" ? String(operation.rawLabel ?? "").trim() : "";
  if (rawLabel && rawLabel !== operation.label) {
    rows.push({ label: labels.rawName, value: rawLabel });
  }
  if (operation.kind === "status" && operation.resultPreview) {
    rows.push({ label: labels.fullStatus, value: operation.resultPreview });
  }
  if (Object.keys(args).length > 0) {
    rows.push({ label: labels.toolCallArguments, value: naturalRecordText(args) });
  }
  if (operation.resultPreview && operation.kind !== "status") {
    const readableResult = readableOperationResult(operation, labels.structuredResultFallback);
    rows.push({
      label: operation.kind === "thought" ? labels.thoughtProcess : labels.toolCallResult,
      value: readableResult || operation.resultPreview,
    });
  }
  if (operation.error) {
    rows.push({ label: labels.toolCallError, value: operation.error });
  }
  return rows;
}

function shouldKeepResultInDetailsOnly(operation: AgentMessageOperation, result: string) {
  if (operation.kind !== "tool" || operation.status !== "done") {
    return false;
  }
  const rawName = String(operation.rawLabel ?? operation.label ?? "").trim().toLowerCase();
  const commandLikeTool = [
    "cli_tool",
    "grep_search_tool",
    "read_file_tool",
    "glob_tool",
  ].some((name) => rawName === name || rawName.includes(name));
  if (!commandLikeTool) {
    return false;
  }
  const meaningfulLines = result.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  const codeOrTerminalLike = /(^|\n)\s*(def |class |from |import |return |if |for |while |try:|except |const |let |function |\{|\}|\[STD(?:OUT|ERR)\])/.test(result);
  return result.length > 360 || meaningfulLines.length > 3 || codeOrTerminalLike;
}

function structuredResultSummary(value: unknown): string {
  if (typeof value === "string") {
    return value.trim();
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    const primitiveItems = value
      .map((item) => structuredResultSummary(item))
      .filter(Boolean);
    return primitiveItems.slice(0, 3).join("\n");
  }
  if (!value || typeof value !== "object") {
    return "";
  }
  const record = value as Record<string, unknown>;
  const summaryKeys = [
    "summary",
    "message",
    "resultPreview",
    "stdoutPreview",
    "stderrPreview",
    "output",
    "text",
    "content",
    "title",
    "error",
    "status",
  ];
  for (const key of summaryKeys) {
    const summary = structuredResultSummary(record[key]);
    if (summary) {
      return summary;
    }
  }
  return "";
}

function naturalRecordText(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value
      .map((item, index) => {
        const text = naturalRecordText(item);
        return text ? `${index + 1}. ${text}` : "";
      })
      .filter(Boolean)
      .join("\n");
  }
  if (!value || typeof value !== "object") {
    return "";
  }
  return Object.entries(value as Record<string, unknown>)
    .map(([key, item]) => {
      const text = naturalRecordText(item);
      return text ? `${key}: ${text}` : "";
    })
    .filter(Boolean)
    .join("\n");
}

export function DeferredOperationDetails({
  operation,
  expanded,
  detailsId,
  kind,
  buildDetailRows,
  classNames,
  className,
}: DeferredOperationDetailsProps) {
  const deferredExpanded = useDeferredValue(expanded);
  const detailRows = deferredExpanded ? buildDetailRows(operation) : [];
  if (!deferredExpanded) {
    return null;
  }
  return (
    <div
      id={detailsId}
      className={[
        classNames.operationDetails,
        kind === "thought" ? classNames.operationDetailsThought : "",
        className || "",
      ].filter(Boolean).join(" ")}
    >
      {detailRows.map((row) => (
        <div key={`${operation.id}-${row.label}`} className={classNames.operationDetailRow}>
          <span className={classNames.operationDetailLabel}>{row.label}</span>
          <pre className={classNames.operationDetailValue}>{row.value}</pre>
        </div>
      ))}
    </div>
  );
}
