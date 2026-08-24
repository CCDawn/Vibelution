/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ChallengeCatalogOverview,
  ChallengeCatalogOverviewView,
  isDevBatchCatalogAction,
} from "./ChallengeCatalogOverview";
import {
  catalogOverviewCountLabel,
  failedQuestionIdsInPlan,
  visibleCatalogOverviewRows,
  type CatalogOverview,
  type CatalogOverviewQuestion,
} from "./challengeCatalogOverviewModel";

const containerApiMock = vi.hoisted(() => ({
  fetchChallengeCupCatalogOverview: vi.fn(),
  runChallengeCupDevBatch: vi.fn(async () => ({ schemaVersion: 1, ok: true })),
}));

const containerState = vi.hoisted(() => ({
  overviewData: { current: null as CatalogOverview | null },
  mutationCalls: [] as Array<{ planId: string; retryFailed: boolean }>,
}));

vi.mock("../../../api/teamExperiment", () => containerApiMock);
vi.mock("../../../api/queryKeys", () => ({
  queryKeys: {
    challengeCupCatalogOverview: () => ["challenge-cup-overview"],
    challengeCupDevControlsSnapshot: () => ["challenge-cup-dev-snapshot"],
  },
}));
vi.mock("../../../app/pollingPolicy", () => ({
  usePageVisibility: () => true,
  resolvePollingInterval: () => 5_000,
}));
vi.mock("@tanstack/react-query", () => ({
  useQuery: () => ({
    data: containerState.overviewData.current,
    isPending: false,
    isError: false,
    error: null,
    refetch: () => Promise.resolve(),
  }),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
  useMutation: (options: {
    mutationFn: (input: { planId: string; retryFailed: boolean }) => Promise<unknown>;
    onSuccess?: (result: unknown) => Promise<void>;
  }) => ({
    isPending: false,
    error: null,
    mutate: (input: { planId: string; retryFailed: boolean }) => {
      containerState.mutationCalls.push(input);
      void (async () => {
        const result = await options.mutationFn(input);
        await options.onSuccess?.(result);
      })();
    },
  }),
}));

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

  it("collects every failed question of a plan, not only the selected row", () => {
    const rows = [
      ...catalog125().filter((row) => row.status !== "queued"),
      question({ questionId: "SCI-008", status: "failed" }),
      question({ questionId: "SCI-004", status: "succeeded" }),
    ];
    expect(failedQuestionIdsInPlan(rows, "dev-1")).toEqual(["SCI-003", "SCI-008"]);
    expect(failedQuestionIdsInPlan(rows, "other-plan")).toEqual([]);
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

  it("surfaces a human approval gate in the metric, filter, row, and detail", () => {
    const awaiting = question({
      questionId: "SCI-009",
      status: "queued",
      executionStatus: "awaiting_human_approval",
      blocker: {
        code: "awaiting_human_approval",
        message: "等待人工审批",
        remediationLabel: "打开题目档案",
      },
    });
    const data = overview([
      awaiting,
      question({ questionId: "SCI-002", status: "running" }),
    ]);
    const markup = renderToStaticMarkup(
      <ChallengeCatalogOverviewView
        overview={data}
        selectedId="SCI-009"
        filter="all"
        onSelect={() => {}}
        onFilterChange={() => {}}
        onAction={() => {}}
      />,
    );

    expect(markup).toContain("1 待审批");
    expect(markup).toContain("SCI-009");
    expect(markup).toContain("待审批");
    expect(markup).toContain("等待人工审批");
    expect(markup).toContain('data-tone="warning"');
  });

  it("filters the catalog to only approval-gated questions", () => {
    const data = overview([
      question({
        questionId: "SCI-009",
        status: "queued",
        executionStatus: "awaiting_human_approval",
      }),
      question({ questionId: "SCI-002", status: "running" }),
    ]);
    const markup = renderToStaticMarkup(
      <ChallengeCatalogOverviewView
        overview={data}
        selectedId="SCI-009"
        filter="awaiting_approval"
        onSelect={() => {}}
        onFilterChange={() => {}}
        onAction={() => {}}
      />,
    );

    expect(markup).toContain('data-testid="catalog-overview-row-SCI-009"');
    expect(markup).not.toContain('data-testid="catalog-overview-row-SCI-002"');
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
    const button = Array.from(container.querySelectorAll("button")).find((node) => node.textContent === "重试失败题");
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

describe("ChallengeCatalogOverview retry scope confirmation", () => {
  beforeEach(() => {
    containerApiMock.fetchChallengeCupCatalogOverview.mockClear();
    containerApiMock.runChallengeCupDevBatch.mockClear();
    containerState.mutationCalls.length = 0;
    containerState.overviewData.current = overview([
      question({ questionId: "SCI-003", status: "failed" }),
      question({ questionId: "SCI-008", status: "failed" }),
      question({ questionId: "SCI-007", status: "running" }),
      question({ questionId: "SCI-004", status: "queued" }),
    ]);
    document.body.innerHTML = "";
  });

  function findButton(label: string): HTMLButtonElement | undefined {
    return Array.from(document.body.querySelectorAll("button"))
      .find((node) => node.textContent?.trim() === label);
  }

  async function mountOverview() {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () => {
      root.render(
        <ChallengeCatalogOverview teamId="team-1" onOpenQuestion={() => {}} devBatchControlsEnabled />,
      );
    });
    return async () => {
      await act(async () => {
        root.unmount();
      });
      host.remove();
    };
  }

  it("shows the full failed set of the plan before retrying and cancels without mutating", async () => {
    const unmount = await mountOverview();
    const retryButton = findButton("重试失败题");
    expect(retryButton).toBeTruthy();
    await act(async () => {
      retryButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(document.body.textContent).toContain("重试该批次的全部失败题目？");
    expect(document.body.textContent).toContain("不只是当前这一题");
    expect(document.body.textContent).toContain("SCI-003");
    expect(document.body.textContent).toContain("SCI-008");
    expect(findButton("重试全部 2 道失败题")).toBeTruthy();

    await act(async () => {
      findButton("取消")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(containerState.mutationCalls).toEqual([]);
    expect(document.body.textContent).not.toContain("重试该批次的全部失败题目？");
    await unmount();
  });

  it("confirms the retry as a plan-scoped retryFailed batch", async () => {
    const unmount = await mountOverview();
    await act(async () => {
      findButton("重试失败题")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await act(async () => {
      findButton("重试全部 2 道失败题")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(containerState.mutationCalls).toEqual([{ planId: "dev-1", retryFailed: true }]);
    expect(containerApiMock.runChallengeCupDevBatch).toHaveBeenCalledWith(
      "team-1",
      "dev-1",
      { maxItems: null, retryFailed: true },
    );
    await unmount();
  });
});
