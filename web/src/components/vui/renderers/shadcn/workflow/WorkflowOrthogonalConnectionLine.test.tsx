/**
 * @vitest-environment happy-dom
 */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ConnectionLineType, type ConnectionLineComponentProps, type Position } from "@xyflow/react";

import { WorkflowOrthogonalConnectionLine } from "./WorkflowOrthogonalConnectionLine";
import { resolveWorkflowManualEdgeGeometry } from "./workflowManualLayout";

function renderLine(
  extra: Partial<ConnectionLineComponentProps> = {},
): string {
  const props = {
    fromX: 0,
    fromY: 0,
    toX: 120,
    toY: 40,
    fromPosition: "right" as Position,
    toPosition: "left" as Position,
    connectionLineType: ConnectionLineType.Step,
    connectionStatus: "valid" as const,
    fromNode: {} as ConnectionLineComponentProps["fromNode"],
    fromHandle: {} as ConnectionLineComponentProps["fromHandle"],
    toNode: null,
    toHandle: null,
    pointer: { x: 120, y: 40 },
    ...extra,
  } satisfies ConnectionLineComponentProps;
  return renderToStaticMarkup(<WorkflowOrthogonalConnectionLine {...props} />);
}

describe("WorkflowOrthogonalConnectionLine", () => {
  it("paints the live L/Z rubber band instead of a bezier curve", () => {
    const expected = resolveWorkflowManualEdgeGeometry(
      { x: 0, y: 0 },
      { x: 120, y: 40 },
      "right",
      "left",
    );
    const markup = renderLine();
    expect(markup).toContain('data-vui="workflow-connection-line"');
    expect(markup).toContain('data-orthogonal="true"');
    expect(markup).toContain(`d="${expected.path}"`);
    expect(markup).not.toMatch(/\s[CcQqSs]\s/);
    expect(markup).toContain("L ");
  });

  it("uses the error token when the drop target is invalid", () => {
    const markup = renderLine({ connectionStatus: "invalid" });
    expect(markup).toContain('data-connection-status="invalid"');
    expect(markup).toContain("var(--state-error");
  });
});
