import { existsSync } from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { AgentMessageOperation } from "./agentMessageOperations";
import conversationViewSource from "./ConversationView.tsx?raw";

const classNames = {
  operationDetails: "operation-details",
  operationDetailsThought: "operation-details-thought",
  operationDetailRow: "operation-detail-row",
  operationDetailLabel: "operation-detail-label",
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

describe("ConversationOperationDetails", () => {
  it("keeps deferred operation details out of the heavy ConversationView module", () => {
    expect(existsSync(new URL("./ConversationOperationDetails.tsx", import.meta.url))).toBe(true);
    expect(conversationViewSource).toContain('from "./ConversationOperationDetails"');
    expect(conversationViewSource).toContain("<DeferredOperationDetails");
    expect(conversationViewSource).not.toContain("function DeferredOperationDetails");
    expect(conversationViewSource).not.toContain("function operationDetailsKind");
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
    expect(html).toContain('class="operation-detail-row"');
    expect(html).toContain("Result");
    expect(html).toContain("Detailed reasoning");
  });

  it("classifies thought and status operations distinctly while treating other kinds as tool details", async () => {
    const { operationDetailsKind } = await import("./ConversationOperationDetails");

    expect(operationDetailsKind({ ...thoughtOperation, kind: "thought" })).toBe("thought");
    expect(operationDetailsKind({ ...thoughtOperation, kind: "status" })).toBe("status");
    expect(operationDetailsKind({ ...thoughtOperation, kind: "tool" })).toBe("tool");
    expect(operationDetailsKind({ ...thoughtOperation, kind: "mental" })).toBe("tool");
  });
});
