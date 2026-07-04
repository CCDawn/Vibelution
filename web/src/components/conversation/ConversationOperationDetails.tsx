import React, { useDeferredValue } from "react";

import type { AgentMessageOperation } from "./agentMessageOperations";

export type OperationDetailKind = "thought" | "status" | "tool";
export type OperationDetailRow = { label: string; value: string };

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
