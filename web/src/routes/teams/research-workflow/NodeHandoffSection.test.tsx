import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { NodeHandoffRecord } from "../../../api/types/researchWorkflow";
import { NodeHandoffSection } from "./NodeHandoffSection";

describe("NodeHandoffSection", () => {
  it("shows canonical handoff provenance for the selected node", () => {
    const handoff = {
      handoffId: "handoff-2",
      fromNodeId: "knowledge_handoff",
      toNodeId: "hypothesis_design",
      status: "accepted",
      outputArtifactRefs: [{ artifactId: "artifact-1" }],
      supersedesHandoffId: "handoff-1",
    } as unknown as NodeHandoffRecord;

    const markup = renderToStaticMarkup(
      <NodeHandoffSection
        handoffs={[handoff]}
        pending={false}
        blockedReason=""
      />,
    );

    expect(markup).toContain("knowledge_handoff");
    expect(markup).toContain("hypothesis_design");
    expect(markup).toContain("accepted");
    expect(markup).toContain("1 项产物");
    expect(markup).toContain("handoff-1");
  });

  it("renders ledger summary handoffs that omit outputArtifactRefs", () => {
    const handoff = {
      handoffId: "handoff-summary",
      toNodeId: "source_extraction",
      status: "accepted",
    } as unknown as NodeHandoffRecord;

    const markup = renderToStaticMarkup(
      <NodeHandoffSection
        handoffs={[handoff]}
        pending={false}
        blockedReason=""
      />,
    );

    expect(markup).toContain("source_extraction");
    expect(markup).toContain("accepted");
    expect(markup).toContain("0 项产物");
  });

  it("renders budget exhaustion as an operator action instead of an internal code", () => {
    const markup = renderToStaticMarkup(
      <NodeHandoffSection handoffs={[]} pending={false} blockedReason="budget_exceeded" />,
    );

    expect(markup).toContain("本阶段预算已用完");
    expect(markup).not.toContain("budget_exceeded");
  });
});
