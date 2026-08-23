/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import {
  ChallengeCatalogOverviewView,
  isDevBatchCatalogAction,
} from "./ChallengeCatalogOverview";
import {
  catalogOverviewCountLabel,
  visibleCatalogOverviewRows,
  type CatalogOverview,
  type CatalogOverviewQuestion,
} from "./challengeCatalogOverviewModel";

function question(
  overrides: Partial<CatalogOverviewQuestion> & Pick<CatalogOverviewQuestion, "questionId" | "status">,
): CatalogOverviewQuestion {
  return {
    title: `${overrides.questionId} title`,
    domain: "physics",
    executionStatus: overrides.status === "queued" ? "pending" : overrides.status,
    currentStage: overrides.status === "failed" ? "blocked" : overrides.status === "succeeded" ? "complete" : overrides.status === "running" ? "catalog_execution" : "queued",
    checkpointProgress: overrides.status === "queued" ? "0/1" : "1/1",
    attempts: overrides.status === "queued" ? 0 : 1,
    planId: overrides.status === "queued" ? "" : "dev-1",
    action: overrides.status === "failed" ? "retry" : overrides.status === "running" ? "continue" : "view",
    blocker: overrides.status === "failed"
      ? { code: "question_failed", message: "fixture rejected", remediationLabel: "单行重试已有 DEV fixture 命令" }
      : null,
    ...overrides,
  };
}

function overview(rows: CatalogOverviewQuestion[]): CatalogOverview {
  const counts = { queued: 0, running: 0, succeeded: 0, failed: 0 };
  for (const row of rows) counts[row.status] += 1;
  return {
    schemaVersion: 1,
    teamId: "team-1",
    generatedAt: "2026-08-20T00:00:00Z",
    questionCount: rows.length,
    counts,
    questions: rows,
  };
}

function catalog125(): CatalogOverviewQuestion[] {
  const rows: CatalogOverviewQuestion[] = [];
  for (let index = 1; index <= 125; index += 1) {
    const questionId = `SCI-${String(index).padStart(3, "0")}`;
    if (index === 3) {
      rows.push(question({ questionId, status: "failed" }));
      continue;
    }
    if (index === 7) {
      rows.push(question({ questionId, status: "running" }));
      continue;
    }
    if (index <= 2) {
      rows.push(question({ questionId, status: "succeeded" }));
      continue;
    }
    rows.push(question({ questionId, status: "queued" }));
  }
  return rows;
}

describe("challengeCatalogOverviewModel", () => {
  it("sorts failed first, then running, then remaining question ids", () => {
    const rows = visibleCatalogOverviewRows(catalog125(), "all");
    expect(rows).toHaveLength(125);
    expect(rows[0]?.questionId).toBe("SCI-003");
    expect(rows[1]?.questionId).toBe("SCI-007");
    expect(rows[2]?.questionId).toBe("SCI-001");
    expect(rows[3]?.questionId).toBe("SCI-002");
    expect(rows[4]?.questionId).toBe("SCI-004");
  });

  it("filters by status without changing the source order contract", () => {
    const failed = visibleCatalogOverviewRows(catalog125(), "failed");
    expect(failed.map((row) => row.questionId)).toEqual(["SCI-003"]);
    expect(visibleCatalogOverviewRows(catalog125(), "running")).toHaveLength(1);
    expect(visibleCatalogOverviewRows(catalog125(), "queued")).toHaveLength(121);
  });
});

describe("ChallengeCatalogOverviewView", () => {
  it("renders progress counts, 125 rows, and failed-first order", () => {
    const data = overview(catalog125());
    const markup = renderToStaticMarkup(
      <ChallengeCatalogOverviewView
        overview={data}
        selectedId="SCI-003"
        filter="all"
        onSelect={() => {}}
        onFilterChange={() => {}}
        onAction={() => {}}
      />,
    );
    expect(markup).toContain('data-testid="catalog-overview"');
    expect(markup).toContain('data-vui="challenge-catalog-overview"');
    expect(markup).toContain('data-vui-recipe="list-detail-page"');
    expect(markup).toContain(catalogOverviewCountLabel(data.counts, true));
    expect(markup).toContain('data-testid="catalog-overview-row-SCI-003"');
    expect(markup).toContain('data-testid="catalog-overview-row-SCI-125"');
    expect(markup.indexOf("SCI-003")).toBeLessThan(markup.indexOf("SCI-007"));
    expect(markup.indexOf("SCI-003")).toBeLessThan(markup.indexOf("SCI-001"));
  });

  it("shows server blocker copy on the failed detail and does not guess from code", () => {
    const data = overview(catalog125());
    const markup = renderToStaticMarkup(
      <ChallengeCatalogOverviewView
        overview={data}
        selectedId="SCI-003"
        filter="failed"
        onSelect={() => {}}
        onFilterChange={() => {}}
        onAction={() => {}}
      />,
    );
    expect(markup).toContain("fixture rejected");
    expect(markup).toContain("单行重试已有 DEV fixture 命令");
    expect(markup).not.toContain("question_failed");
    expect(markup).toContain("查看详情");
    expect(markup).toContain('data-dev-batch-action="view"');
    expect(markup).not.toContain("SCI-007");
  });

  it("renders empty filtered state", () => {
    const markup = renderToStaticMarkup(
      <ChallengeCatalogOverviewView
        overview={overview([question({ questionId: "SCI-001", status: "queued" })])}
        selectedId=""
        filter="failed"
        onSelect={() => {}}
        onFilterChange={() => {}}
        onAction={() => {}}
      />,
    );
    expect(markup).toContain("没有匹配的题目");
  });

  it("invokes retry on the selected failed row", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const onAction = vi.fn();
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(
        <ChallengeCatalogOverviewView
          overview={overview(catalog125())}
          selectedId="SCI-003"
          filter="failed"
          onSelect={() => {}}
          onFilterChange={() => {}}
          onAction={onAction}
          devBatchControlsEnabled
        />,
      );
    });
    const button = Array.from(container.querySelectorAll("button")).find((node) => node.textContent === "重试");
    expect(button).toBeTruthy();
    await act(async () => {
      button!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(onAction).toHaveBeenCalledWith(expect.objectContaining({
      questionId: "SCI-003",
      action: "retry",
      planId: "dev-1",
    }));
    await act(async () => {
      root.unmount();
    });
    container.remove();
  });

  it("keeps retry and continue rows read-only without the DEV capability", () => {
    const failed = question({ questionId: "SCI-003", status: "failed" });
    const running = question({ questionId: "SCI-007", status: "running" });

    expect(isDevBatchCatalogAction(failed, false)).toBe(false);
    expect(isDevBatchCatalogAction(running, false)).toBe(false);
    expect(isDevBatchCatalogAction(failed, true)).toBe(true);
    expect(isDevBatchCatalogAction(running, true)).toBe(true);
  });
});
