/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const queryState = vi.hoisted(() => ({
  current: {
    isPending: false,
    isError: false,
    error: null as unknown,
    data: undefined as unknown,
    refetch: vi.fn(),
  },
}));

const apiMock = vi.hoisted(() => ({
  fetchChallengeCupRealBatchStatus: vi.fn(),
  authorizeChallengeCupRealBatch: vi.fn(),
  startChallengeCupRealBatch: vi.fn(),
  pollChallengeCupRealBatch: vi.fn(),
  cancelChallengeCupRealBatch: vi.fn(),
}));

const queryClientMock = vi.hoisted(() => ({
  setQueryData: vi.fn(),
  invalidateQueries: vi.fn(),
}));

vi.mock("../../../api/teamExperiment", () => apiMock);
vi.mock("@tanstack/react-query", () => ({
  useQuery: () => queryState.current,
  useQueryClient: () => queryClientMock,
  useMutation: (options: {
    mutationFn: (variables: any) => Promise<unknown>;
    onSuccess?: (data: unknown, variables: any) => unknown;
  }) => ({
    isPending: false,
    isError: false,
    error: null,
    mutate: (variables: any) => {
      void options.mutationFn(variables).then((data) => options.onSuccess?.(data, variables));
    },
    mutateAsync: async (variables: any) => {
      const data = await options.mutationFn(variables);
      options.onSuccess?.(data, variables);
      return data;
    },
  }),
}));

import { ChallengeRealBatchControlPanel } from "./ChallengeRealBatchControlPanel";

function projection(overrides: Record<string, unknown> = {}) {
  return {
    schemaVersion: 1,
    planId: "real-125",
    gateId: "G125",
    exists: true,
    questionCount: 125,
    statusSummary: { pending: 80, running: 2, succeeded: 40, failed: 1, blocked: 2 },
    pendingCount: 80,
    succeededCount: 40,
    failedCount: 1,
    blockedCount: 2,
    totalAttempts: 44,
    completedQuestionIds: ["SCI-001"],
    pendingQuestionIds: ["SCI-002"],
    runRefs: { "SCI-002": { runId: "run-2", attempt: 1 } },
    awaitingApprovalQuestionIds: ["SCI-003"],
    consecutiveFailures: 1,
    failureBudget: 3,
    circuitBreakerOpen: false,
    cancelled: false,
    gateComplete: false,
    lastUpdatedAt: "2026-08-23T05:00:00Z",
    canResume: true,
    drainState: "none",
    concurrencyLimit: 4,
    totalCompletedCount: 45,
    autoClosedCount: 40,
    escalatedCount: 5,
    autoCloseRate: 40 / 45,
    escalationRate: 5 / 45,
    autoCloseTarget: 0.85,
    escalationStopLine: 0.15,
    stopReason: "",
    remainingFailureBudget: 2,
    ...overrides,
  };
}

function authorization() {
  return {
    authorizationId: "auth-125",
    teamId: "team-1",
    planId: "real-125",
    batchScope: { planId: "real-125", gateId: "G125" },
    scopeHash: "scope-hash",
    approvedBy: "operator-1",
    approvedAtMs: 1,
    readinessReportSha256: "readiness-hash",
    recordHash: "record-hash",
    createdAtMs: 1,
  };
}

function renderPanel() {
  return renderToStaticMarkup(<ChallengeRealBatchControlPanel teamId="team-1" lang="zh" />);
}

function button(label: string): HTMLButtonElement {
  const found = Array.from(document.body.querySelectorAll("button"))
    .find((item) => item.textContent?.includes(label));
  if (!found) throw new Error(`Expected button: ${label}`);
  return found as HTMLButtonElement;
}

async function mountPanel() {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(<ChallengeRealBatchControlPanel teamId="team-1" lang="zh" />);
  });
  return {
    async unmount() {
      await act(async () => root.unmount());
      container.remove();
    },
  };
}

describe("ChallengeRealBatchControlPanel", () => {
  beforeEach(() => {
    queryState.current = {
      isPending: false,
      isError: false,
      error: null,
      data: projection(),
      refetch: vi.fn(),
    };
    apiMock.fetchChallengeCupRealBatchStatus.mockReset();
    apiMock.authorizeChallengeCupRealBatch.mockReset();
    apiMock.startChallengeCupRealBatch.mockReset();
    apiMock.pollChallengeCupRealBatch.mockReset();
    apiMock.cancelChallengeCupRealBatch.mockReset();
    queryClientMock.setQueryData.mockReset();
    queryClientMock.invalidateQueries.mockReset();
    document.body.innerHTML = "";
  });

  it("shows all real gates, persisted progress, blockers, recent status and the fail-closed boundary", () => {
    const markup = renderPanel();

    expect(markup).toContain("真实批次控制");
    expect(markup).toContain("G1");
    expect(markup).toContain("G5");
    expect(markup).toContain("G12");
    expect(markup).toContain("G125");
    expect(markup).toContain("40 / 125");
    expect(markup).toContain("待处理");
    expect(markup).toContain(">80</strong>");
    expect(markup).toContain("待人工审核");
    expect(markup).toContain("运行观察");
    expect(markup).toContain("进行中 / 并发上限");
    expect(markup).toContain("2 / 4");
    expect(markup).toContain("自动闭环率");
    expect(markup).toContain("40/45");
    expect(markup).toContain("目标 ≥85%");
    expect(markup).toContain("异常升级率");
    expect(markup).toContain("5/45");
    expect(markup).toContain("停止线 ≤15%");
    expect(markup).toContain("停止原因：无");
    expect(markup).toContain("剩余失败预算 2/3");
    expect(markup).toContain("最近事件");
    expect(markup).toContain("realCampaignAllowed=false");
    expect(markup).toContain("尚未视为已授权");
  });

  it("fails closed for loading, error, empty and malformed state", () => {
    queryState.current.isPending = true;
    expect(renderPanel()).toContain("读取真实批次状态");

    queryState.current.isPending = false;
    queryState.current.isError = true;
    queryState.current.error = new Error("batch unavailable");
    expect(renderPanel()).toContain("真实批次状态不可用");

    queryState.current.isError = false;
    queryState.current.error = null;
    queryState.current.data = projection({ exists: false });
    const empty = renderPanel();
    expect(empty).toContain("尚未创建");
    expect(empty).toContain("申请科研授权");
    expect(empty).not.toContain(">已取得授权</span>");

    queryState.current.data = { planId: "real-125", gateId: "G125", exists: true };
    const malformed = renderPanel();
    expect(malformed).toContain("真实批次数据格式异常");
    expect(malformed).not.toContain("40 / 125");
  });

  it("does not mutate on mount and requires confirmation before authorization", async () => {
    apiMock.authorizeChallengeCupRealBatch.mockResolvedValue(authorization());
    const view = await mountPanel();

    expect(apiMock.authorizeChallengeCupRealBatch).not.toHaveBeenCalled();
    await act(async () => button("申请科研授权").click());
    expect(apiMock.authorizeChallengeCupRealBatch).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain("确认写入科研授权");

    await act(async () => button("确认授权").click());
    expect(apiMock.authorizeChallengeCupRealBatch).toHaveBeenCalledWith("team-1", "real-125");
    await view.unmount();
  });

  it("keeps start closed until durable authorization succeeds, then confirms start", async () => {
    apiMock.authorizeChallengeCupRealBatch.mockResolvedValue(authorization());
    apiMock.startChallengeCupRealBatch.mockResolvedValue({ ...projection(), launched: [{ questionId: "SCI-002", outcome: "launched" }] });
    const view = await mountPanel();

    expect(button("继续真实批次").disabled).toBe(true);
    await act(async () => button("申请科研授权").click());
    await act(async () => {
      button("确认授权").click();
      await Promise.resolve();
    });
    expect(button("继续真实批次").disabled).toBe(false);
    await act(async () => button("继续真实批次").click());
    expect(document.body.textContent).toContain("确认启动真实批次");
    await act(async () => button("确认启动").click());
    expect(apiMock.startChallengeCupRealBatch).toHaveBeenCalledWith(
      "team-1",
      "real-125",
      expect.objectContaining({ confirmed: true }),
    );
    await view.unmount();
  });

  it("renders the drain badge, closed-loop accounting and stop reason while draining", () => {
    queryState.current.data = projection({
      cancelled: true,
      canResume: false,
      drainState: "draining",
      stopReason: "cancelled_by_operator",
      statusSummary: { pending: 80, running: 2, succeeded: 40, failed: 1, blocked: 2 },
    });
    const markup = renderPanel();

    expect(markup).toContain("排空中");
    expect(markup).toContain("停止原因：操作员已取消，停止新派遣");
  });

  it("marks a drained batch and the failure-budget stop reason without promising residue-free state", () => {
    queryState.current.data = projection({
      cancelled: true,
      canResume: false,
      drainState: "drained",
      statusSummary: { pending: 0, running: 0, succeeded: 40, failed: 1, blocked: 4 },
      stopReason: "failure_budget_exhausted",
      circuitBreakerOpen: true,
      consecutiveFailures: 3,
      remainingFailureBudget: 0,
    });
    const markup = renderPanel();

    expect(markup).toContain("已排空");
    expect(markup).toContain("停止原因：连续失败达到预算，已停止派遣");
    expect(markup).toContain("剩余失败预算 0/3");
  });

  it("derives drain and rates locally when the service payload predates the observability fields", () => {
    queryState.current.data = projection({
      cancelled: true,
      canResume: false,
      drainState: undefined,
      concurrencyLimit: undefined,
      totalCompletedCount: undefined,
      autoClosedCount: undefined,
      escalatedCount: undefined,
      autoCloseRate: undefined,
      escalationRate: undefined,
      autoCloseTarget: undefined,
      escalationStopLine: undefined,
      stopReason: undefined,
      remainingFailureBudget: undefined,
      statusSummary: { pending: 0, running: 1, succeeded: 40, failed: 1, blocked: 4 },
    });
    const markup = renderPanel();

    expect(markup).toContain("排空中");
    expect(markup).toContain("1 / —");
    expect(markup).toContain("40/45");
    expect(markup).toContain("(2/45");
  });

  it("requires confirmation for cancel and never polls on mount", async () => {
    apiMock.cancelChallengeCupRealBatch.mockResolvedValue(projection({ cancelled: true, canResume: false }));
    const view = await mountPanel();

    expect(apiMock.pollChallengeCupRealBatch).not.toHaveBeenCalled();
    await act(async () => button("取消批次").click());
    expect(document.body.textContent).toContain("确认取消真实批次");
    await act(async () => button("确认取消").click());
    expect(apiMock.cancelChallengeCupRealBatch).toHaveBeenCalledWith("team-1", "real-125", { confirmed: true });
    await view.unmount();
  });

  it("waits for each background poll to settle before scheduling the next one", async () => {
    vi.useFakeTimers();
    let resolveFirstPoll!: (value: ReturnType<typeof projection>) => void;
    let resolveSecondPoll!: (value: ReturnType<typeof projection>) => void;
    const firstPoll = new Promise<ReturnType<typeof projection>>((resolve) => {
      resolveFirstPoll = resolve;
    });
    const secondPoll = new Promise<ReturnType<typeof projection>>((resolve) => {
      resolveSecondPoll = resolve;
    });
    apiMock.authorizeChallengeCupRealBatch.mockResolvedValue(authorization());
    apiMock.startChallengeCupRealBatch.mockResolvedValue(projection());
    apiMock.pollChallengeCupRealBatch
      .mockImplementationOnce(() => firstPoll)
      .mockImplementationOnce(() => secondPoll);
    const view = await mountPanel();

    await act(async () => button("申请科研授权").click());
    await act(async () => {
      button("确认授权").click();
      await Promise.resolve();
    });
    await act(async () => button("继续真实批次").click());
    await act(async () => {
      button("确认启动").click();
      await Promise.resolve();
    });

    await act(async () => {
      vi.advanceTimersByTime(15_000);
      await Promise.resolve();
    });
    expect(apiMock.pollChallengeCupRealBatch).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(15_000);
      await Promise.resolve();
    });
    expect(apiMock.pollChallengeCupRealBatch).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveFirstPoll(projection());
      await Promise.resolve();
      await Promise.resolve();
    });
    await act(async () => {
      vi.advanceTimersByTime(15_000);
      await Promise.resolve();
    });
    expect(apiMock.pollChallengeCupRealBatch).toHaveBeenCalledTimes(2);

    await act(async () => {
      await view.unmount();
      resolveSecondPoll(projection());
      await Promise.resolve();
      await Promise.resolve();
      vi.advanceTimersByTime(15_000);
    });
    expect(apiMock.pollChallengeCupRealBatch).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
  });

  it("stops scheduling when a poll response disables background polling", async () => {
    vi.useFakeTimers();
    apiMock.authorizeChallengeCupRealBatch.mockResolvedValue(authorization());
    apiMock.startChallengeCupRealBatch.mockResolvedValue(projection());
    apiMock.pollChallengeCupRealBatch.mockResolvedValue(projection({ gateComplete: true, canResume: false }));
    const view = await mountPanel();

    await act(async () => button("申请科研授权").click());
    await act(async () => {
      button("确认授权").click();
      await Promise.resolve();
    });
    await act(async () => button("继续真实批次").click());
    await act(async () => {
      button("确认启动").click();
      await Promise.resolve();
    });

    await act(async () => {
      vi.advanceTimersByTime(15_000);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(apiMock.pollChallengeCupRealBatch).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(15_000);
      await Promise.resolve();
    });
    expect(apiMock.pollChallengeCupRealBatch).toHaveBeenCalledTimes(1);
    await view.unmount();
    vi.useRealTimers();
  });
});
