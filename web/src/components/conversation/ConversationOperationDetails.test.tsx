import { existsSync } from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { AgentMessageOperation } from "./agentMessageOperations";
import {
  buildOperationDetailRows,
  readableOperationResult,
} from "./ConversationOperationDetails";
import detailStyles from "./ConversationOperationDetails.styles";
import conversationViewSource from "./ConversationView.tsx?raw";

const classNames = {
  operationDetails: "operation-details",
  operationDetailsThought: "operation-details-thought",
  operationDetailRow: "operation-detail-row",
  operationDetailLabel: "operation-detail-label",
  operationDetailDescription: "operation-detail-description",
  operationDetailValue: "operation-detail-value",
};

const thoughtOperation: AgentMessageOperation = {
  id: "operation-1",
  kind: "thought",
  label: "Thinking",
  status: "completed",
  summary: "Summarized thought",
  durationSeconds: null,
  resultPreview: "Detailed reasoning",
};

const detailLabels = {
  rawName: "Raw name",
  fullStatus: "Full status",
  toolCallArguments: "Arguments",
  thoughtProcess: "Thought",
  toolCallResult: "Result",
  toolCallError: "Error",
  structuredResultFallback: "Structured result returned; expand details to inspect.",
};

describe("ConversationOperationDetails", () => {
  it("keeps deferred operation details out of the heavy ConversationView module", () => {
    expect(existsSync(new URL("./ConversationOperationDetails.tsx", import.meta.url))).toBe(true);
    expect(conversationViewSource).toContain('from "./ConversationOperationDetails"');
    expect(conversationViewSource).toContain("<DeferredOperationDetails");
    expect(conversationViewSource).not.toContain("function DeferredOperationDetails");
    expect(conversationViewSource).not.toContain("function operationDetailsKind");
    expect(conversationViewSource).not.toContain("function operationDetailRows(");
    expect(conversationViewSource).not.toContain("function readableOperationResult(");
    expect(conversationViewSource).not.toContain("function structuredResultSummary(");
    expect(conversationViewSource).not.toContain("function naturalRecordText(");
    expect(conversationViewSource).not.toContain("type OperationDetailKind");
  });

  it("does not build detail rows while collapsed", async () => {
    const { DeferredOperationDetails } = await import("./ConversationOperationDetails");
    const buildDetailRows = vi.fn(() => [{ label: "Result", value: "Hidden value" }]);

    const html = renderToStaticMarkup(
      <DeferredOperationDetails
        operation={thoughtOperation}
        expanded={false}
        detailsId="operation-details-1"
        kind="thought"
        classNames={classNames}
        buildDetailRows={buildDetailRows}
      />,
    );

    expect(html).toBe("");
    expect(buildDetailRows).not.toHaveBeenCalled();
  });

  it("renders expanded operation detail rows with thought styling", async () => {
    const { DeferredOperationDetails } = await import("./ConversationOperationDetails");
    const buildDetailRows = vi.fn(() => [{ label: "Result", value: "Detailed reasoning" }]);

    const html = renderToStaticMarkup(
      <DeferredOperationDetails
        operation={thoughtOperation}
        expanded
        detailsId="operation-details-1"
        kind="thought"
        className="custom-details"
        classNames={classNames}
        buildDetailRows={buildDetailRows}
      />,
    );

    expect(buildDetailRows).toHaveBeenCalledWith(thoughtOperation);
    expect(html).toContain('id="operation-details-1"');
    expect(html).toContain('class="operation-details operation-details-thought custom-details"');
    expect(html).toContain("<dl");
    expect(html).toContain("<dt");
    expect(html).toContain("<dd");
    expect(html).toContain('class="operation-detail-row"');
    expect(html).toContain('id="operation-details-1-detail-label-0"');
    expect(html).toContain('aria-labelledby="operation-details-1-detail-label-0"');
    expect(html).toContain('tabindex="0"');
    expect(html).toContain("Result");
    expect(html).toContain("Detailed reasoning");
  });

  it("does not render an empty expanded details container", async () => {
    const { DeferredOperationDetails } = await import("./ConversationOperationDetails");
    const html = renderToStaticMarkup(
      <DeferredOperationDetails
        operation={thoughtOperation}
        expanded
        detailsId="operation-details-empty"
        kind="tool"
        classNames={classNames}
        buildDetailRows={() => []}
      />,
    );

    expect(html).toBe("");
  });

  it("keeps expanded detail rows as inline metadata instead of nested cards", () => {
    expect(detailStyles.operationDetailRow).not.toMatch(/radius-panel|surface-glass|shadow-/);
    expect(detailStyles.operationDetailLabel).not.toMatch(/rounded-|border|bg-\[|shadow-|p-2/);
    expect(detailStyles.operationDetailValue).not.toMatch(/radius-panel|surface-glass|shadow-/);
    expect(detailStyles.operationDetailRow).toContain("grid");
    expect(detailStyles.operationDetailRow).toContain("grid-cols-[minmax(5.5rem,8rem)_minmax(0,1fr)]");
    expect(detailStyles.operationDetailRow).toContain("max-[560px]:grid-cols-[minmax(0,1fr)]");
    expect(detailStyles.operationDetailValue).toContain("whitespace-pre-wrap");
    expect(detailStyles.operationDetailValue).toContain("max-h-44");
    expect(detailStyles.operationDetailValue).toContain("focus-visible:ring-2");
  });

  it("classifies thought and status operations distinctly while treating other kinds as tool details", async () => {
    const { operationDetailsKind } = await import("./ConversationOperationDetails");

    expect(operationDetailsKind({ ...thoughtOperation, kind: "thought" })).toBe("thought");
    expect(operationDetailsKind({ ...thoughtOperation, kind: "status" })).toBe("status");
    expect(operationDetailsKind({ ...thoughtOperation, kind: "tool" })).toBe("tool");
    expect(operationDetailsKind({ ...thoughtOperation, kind: "mental" })).toBe("tool");
  });

  it("builds localized operation detail rows from tool metadata", () => {
    const rows = buildOperationDetailRows({
      id: "tool-1",
      kind: "tool",
      label: "Custom tool",
      rawLabel: "custom_tool",
      status: "done",
      summary: "Read project file",
      durationSeconds: 1.2,
      arguments: {
        path: "README.md",
        options: { encoding: "utf8" },
      },
      resultPreview: JSON.stringify({ summary: "Loaded README" }),
      error: "partial warning",
    }, detailLabels);

    expect(rows).toEqual([
      { label: "Raw name", value: "custom_tool" },
      { label: "Arguments", value: "path: README.md\noptions: encoding: utf8" },
      { label: "Result", value: "Loaded README" },
      { label: "Error", value: "partial warning" },
    ]);
  });

  it("builds status and thought rows with the same detail-row helper", () => {
    expect(buildOperationDetailRows({
      id: "status-1",
      kind: "status",
      label: "Status",
      rawLabel: "runtime_status",
      status: "running",
      summary: "Working",
      durationSeconds: null,
      resultPreview: "Still running",
    }, detailLabels)).toEqual([
      { label: "Full status", value: "Still running" },
    ]);

    expect(buildOperationDetailRows(thoughtOperation, detailLabels)).toEqual([
      { label: "Thought", value: "Detailed reasoning" },
    ]);
  });

  it("summarizes structured operation results for compact ReAct previews", () => {
    expect(readableOperationResult({
      id: "tool-2",
      kind: "tool",
      label: "tool",
      rawLabel: "tool",
      status: "done",
      summary: "",
      durationSeconds: null,
      resultPreview: JSON.stringify({ message: "Created file" }),
    }, detailLabels.structuredResultFallback)).toBe("Created file");

    expect(readableOperationResult({
      id: "tool-3",
      kind: "tool",
      label: "tool",
      rawLabel: "tool",
      status: "done",
      summary: "",
      durationSeconds: null,
      resultPreview: JSON.stringify({ data: { id: 1 } }),
    }, detailLabels.structuredResultFallback)).toBe(detailLabels.structuredResultFallback);
  });

  it("keeps long command-like tool output in expanded details only", () => {
    expect(readableOperationResult({
      id: "tool-4",
      kind: "tool",
      label: "cli_tool",
      rawLabel: "cli_tool",
      status: "done",
      summary: "",
      durationSeconds: null,
      resultPreview: ["line 1", "line 2", "line 3", "line 4"].join("\n"),
    }, detailLabels.structuredResultFallback)).toBe("");
  });

  it("bounds expanded command-like tool results so raw output does not dominate the conversation", () => {
    const longResult = Array.from({ length: 30 }, (_, index) =>
      `${index + 1}- output line ${index + 1} with verbose raw payload`,
    ).join("\n");
    const rows = buildOperationDetailRows({
      id: "tool-long-result",
      kind: "tool",
      label: "命令",
      rawLabel: "cli_tool",
      status: "done",
      summary: "命令执行完成",
      durationSeconds: null,
      resultPreview: longResult,
    }, detailLabels);

    expect(rows).toHaveLength(2);
    expect(rows[1]).toMatchObject({
      label: "Result",
    });
    expect(rows[1].value).toContain("1- output line 1");
    expect(rows[1].value).toContain("18- output line 18");
    expect(rows[1].value).not.toContain("19- output line 19");
    expect(rows[1].value).toContain("[已省略 12 行");
  });
});
