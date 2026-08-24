import { describe, expect, it } from "vitest";

import {
  catalogOverviewAwaitingApprovalCount,
  catalogOverviewDisplayStatus,
  catalogOverviewStatusLabel,
  filterCatalogOverviewRows,
  sortCatalogOverviewRows,
  type CatalogOverviewQuestion,
} from "./challengeCatalogOverviewModel";

function question(
  overrides: Partial<CatalogOverviewQuestion> & Pick<CatalogOverviewQuestion, "questionId" | "status">,
): CatalogOverviewQuestion {
  return {
    title: `${overrides.questionId} title`,
    domain: "physics",
    executionStatus: overrides.status,
    currentStage: "catalog_execution",
    checkpointProgress: "1/1",
    attempts: 1,
    planId: "plan-1",
    action: "view",
    blocker: null,
    ...overrides,
  };
}

describe("challengeCatalogOverviewModel approval projection", () => {
  const rows = [
    question({
      questionId: "SCI-009",
      status: "queued",
      executionStatus: "awaiting_human_approval",
      blocker: {
        code: "awaiting_human_approval",
        message: "等待人工审批",
        remediationLabel: "打开题目档案",
      },
    }),
    question({ questionId: "SCI-002", status: "running" }),
    question({ questionId: "SCI-001", status: "failed" }),
    question({ questionId: "SCI-003", status: "queued" }),
  ];

  it("counts a real human approval gate without changing execution counts", () => {
    expect(catalogOverviewAwaitingApprovalCount(rows)).toBe(1);
    expect(catalogOverviewDisplayStatus(rows[0])).toBe("awaiting_approval");
    expect(catalogOverviewDisplayStatus(rows[1])).toBe("running");
  });

  it("filters only the questions waiting for approval", () => {
    expect(filterCatalogOverviewRows(rows, "awaiting_approval").map((row) => row.questionId))
      .toEqual(["SCI-009"]);
  });

  it("orders approval gates after failures and before active work", () => {
    expect(sortCatalogOverviewRows(rows).map((row) => row.questionId))
      .toEqual(["SCI-001", "SCI-009", "SCI-002", "SCI-003"]);
  });

  it("uses an explicit localized approval label", () => {
    expect(catalogOverviewStatusLabel("awaiting_approval", true)).toBe("待审批");
    expect(catalogOverviewStatusLabel("awaiting_approval", false)).toBe("Awaiting approval");
  });
});
