import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  ResearchMemoryEvidencePanel,
  type ResearchMemoryContextSummary,
} from "./ResearchMemoryEvidencePanel";

const summary: ResearchMemoryContextSummary = {
  contextId: "research-memory-context-test",
  knowledgeItemCount: 2,
  reviewedSourceCount: 3,
  negativeExperimentCount: 4,
  successfulRunCount: 1,
  forbiddenDuplicateExperimentCount: 2,
  claimCount: 2,
  claimStatusCounts: {
    qualified: 1,
    unsupported: 1,
    rejected: 0,
    not_established: 0,
  },
  allowedVariableCount: 1,
  allowedVariables: ["methodConfig.budget.epochs"],
  allowedVariableContract: {
    status: "explicit",
    variables: [
      {
        path: "methodConfig.budget.epochs",
        source: "iteration_contract",
        evidenceRef: "plan-revision-12",
      },
    ],
    frozenControls: ["dataset split fixed", "seed set fixed"],
  },
  claimMap: [
    {
      claimId: "claim-qualified",
      claim: "Weight 0.875 provides bounded engineering benefit.",
      status: "qualified",
      supportEvidenceRefs: [
        { type: "experiment_result", id: "full-best-revision4" },
        { type: "knowledge_item", id: "kitem-revision4" },
      ],
      counterEvidenceRefs: [],
      applicableBoundaries: ["fixed dataset and seed protocol"],
      sourcePlanIds: ["plan-best-revision4"],
    },
    {
      claimId: "claim-unsupported",
      claim: "Spatial alignment is the source of the benefit.",
      status: "unsupported",
      supportEvidenceRefs: [],
      counterEvidenceRefs: [
        { type: "experiment_result", id: "full-aligned-vs-shifted" },
      ],
      applicableBoundaries: [],
      sourcePlanIds: ["plan-alignment-diagnostic"],
    },
  ],
  claimMapPreview: [
    {
      claimId: "claim-qualified",
      claim: "Weight 0.875 provides bounded engineering benefit.",
      status: "qualified",
    },
  ],
  missingEvidence: [],
};

describe("ResearchMemoryEvidencePanel", () => {
  it("renders bounded claim evidence, boundaries, source plans, and the variable contract", () => {
    const markup = renderToStaticMarkup(
      <ResearchMemoryEvidencePanel lang="zh" stage="experiment" summary={summary} variant="detail" />,
    );

    expect(markup).toContain('data-research-memory-evidence="detail"');
    expect(markup).toContain("实验设计使用的团队记忆");
    expect(markup).toContain("有边界支持");
    expect(markup).toContain("暂不支持");
    expect(markup).toContain("full-best-revision4");
    expect(markup).toContain("kitem-revision4");
    expect(markup).toContain("full-aligned-vs-shifted");
    expect(markup).toContain("fixed dataset and seed protocol");
    expect(markup).toContain("plan-alignment-diagnostic");
    expect(markup).toContain("methodConfig.budget.epochs");
    expect(markup).toContain("iteration_contract");
    expect(markup).toContain("dataset split fixed");
    expect(markup).toContain("无直接支持证据");
    expect(markup).toContain("无直接反证");
    expect(markup).not.toContain("<button");
    expect(markup).not.toContain("<input");
  });

  it("keeps the overview compact without expanding full evidence records", () => {
    const markup = renderToStaticMarkup(
      <ResearchMemoryEvidencePanel lang="zh" stage="iteration" summary={summary} variant="compact" />,
    );

    expect(markup).toContain('data-research-memory-evidence="compact"');
    expect(markup).toContain("查看 Claim Map 与变量边界");
    expect(markup).toContain("methodConfig.budget.epochs");
    expect(markup).not.toContain("full-best-revision4");
    expect(markup).not.toContain("full-aligned-vs-shifted");
    expect(markup).not.toContain("执行批次");
  });
});
