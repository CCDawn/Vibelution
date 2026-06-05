import { describe, expect, it } from "vitest";

import { EvolutionActiveRun } from "../api/types";
import { buildSupervisedRunControlSummary } from "./supervisedRunSummary";

const labels = {
  statusLabel: (status: string) => {
    const map: Record<string, string> = {
      running: "运行中",
      failed: "失败",
      cancelled: "已取消",
      done: "已完成",
      stopping: "停止中",
      paused: "已暂停",
    };
    return map[status] ?? status;
  },
  roleLabel: (role: string | undefined) => role || "--",
};

function activeRun(overrides: Partial<EvolutionActiveRun>): EvolutionActiveRun {
  return {
    runId: "web-supervised-test",
    status: "running",
    currentPhase: "running",
    runtimeStatus: "running",
    sourceKind: "dataset",
    sessionId: "supervised_test",
    bundleName: "terminal_bench_core_v1",
    datasetName: "terminal_bench_core",
    datasetLimit: null,
    keepWorktree: false,
    startedAt: "",
    updatedAt: "",
    finishedAt: "",
    caseTotal: 1,
    currentCaseIndex: 1,
    currentCaseId: "tb2_fix_code_vulnerability",
    currentRole: "candidate",
    currentCaseScenario: "transaction",
    currentCaseMode: "multi_step_react",
    currentCasePrompt: "",
    currentCaseIo: null,
    currentTask: "candidate 正在执行",
    decision: "",
    reason: "",
    decisionPath: "",
    policyAction: "",
    lineageIndexPath: "",
    lineageSummary: "",
    activeAdvisoryCount: 0,
    pauseRequested: false,
    pauseRequestedAt: "",
    pausedAt: "",
    stopRequested: false,
    stopRequestedAt: "",
    latestMessage: "监督任务正在执行。",
    eventTail: [],
    actionStates: {},
    ...overrides,
  };
}

describe("buildSupervisedRunControlSummary", () => {
  it("summarizes baseline failure plus user cancellation as one readable conclusion", () => {
    const summary = buildSupervisedRunControlSummary(
      activeRun({
        status: "cancelled",
        currentPhase: "cancelled",
        runtimeStatus: "idle",
        reason: "操作者请求终止这一轮监督任务。",
        eventTail: [
          {
            timestamp: "2026-05-31T17:23:50Z",
            event: "role_finish",
            title: "Case 完成",
            summary: "baseline failed",
            status: "failed",
            caseId: "tb2_fix_code_vulnerability",
            caseIndex: 1,
            caseTotal: 1,
            role: "baseline",
            reason: "事务探针状态未知",
            resultStatus: "failed",
          },
          {
            timestamp: "2026-05-31T17:25:41Z",
            event: "role_finish",
            title: "Case 完成",
            summary: "candidate cancelled",
            status: "cancelled",
            caseId: "tb2_fix_code_vulnerability",
            caseIndex: 1,
            caseTotal: 1,
            role: "candidate",
            reason: "操作者请求终止这一轮监督任务。",
            resultStatus: "cancelled",
          },
          {
            timestamp: "2026-05-31T17:25:41Z",
            event: "session_cancelled",
            title: "监督任务终止",
            summary: "session cancelled",
            status: "cancelled",
            reason: "操作者请求终止这一轮监督任务。",
          },
        ],
      }),
      "zh",
      labels,
    );

    expect(summary.tone).toBe("warning");
    expect(summary.headline).toContain("本轮已取消");
    expect(summary.headline).toContain("baseline 失败：事务探针状态未知");
    expect(summary.headline).toContain("candidate 已取消：操作者请求终止这一轮监督任务。");
    expect(summary.nextAction).toContain("重跑失败项");
  });

  it("keeps running runs focused on the active case and next observation", () => {
    const summary = buildSupervisedRunControlSummary(activeRun({}), "zh", labels);

    expect(summary.tone).toBe("running");
    expect(summary.headline).toContain("正在运行");
    expect(summary.stageLabel).toContain("第 1/1 个 case");
    expect(summary.stageLabel).toContain("candidate");
    expect(summary.nextAction).toContain("继续观察");
  });

  it("turns failed role events into a failure headline and recovery hint", () => {
    const summary = buildSupervisedRunControlSummary(
      activeRun({
        status: "failed",
        eventTail: [
          {
            timestamp: "2026-05-31T17:23:50Z",
            event: "role_finish",
            title: "Case 完成",
            summary: "baseline failed",
            status: "failed",
            role: "baseline",
            reason: "事务探针状态未知",
            resultStatus: "failed",
          },
        ],
      }),
      "zh",
      labels,
    );

    expect(summary.tone).toBe("danger");
    expect(summary.headline).toContain("本轮失败");
    expect(summary.headline).toContain("baseline 失败：事务探针状态未知");
    expect(summary.nextAction).toContain("查看失败原因");
  });

  it("treats failed or timed-out case roles as completed evaluation evidence when the session finished", () => {
    const summary = buildSupervisedRunControlSummary(
      activeRun({
        status: "done",
        currentPhase: "done",
        runtimeStatus: "idle",
        decision: "INCONCLUSIVE",
        reason: "baseline 与 candidate 都存在监督边界异常，当前评测无法证明候选退化",
        eventTail: [
          {
            timestamp: "2026-06-01T12:14:40",
            event: "role_finish",
            title: "Case 完成",
            summary: "baseline timeout",
            status: "timeout",
            role: "baseline",
            reason: "运行超时，最后观察阶段: prompt_refresh",
            resultStatus: "timeout",
          },
          {
            timestamp: "2026-06-01T12:17:19",
            event: "role_finish",
            title: "Case 完成",
            summary: "candidate failed",
            status: "failed",
            role: "candidate",
            reason: "事务探针未关账",
            resultStatus: "failed",
          },
          {
            timestamp: "2026-06-01T12:17:20",
            event: "session_finish",
            title: "监督任务结束",
            summary: "decision=INCONCLUSIVE",
            status: "done",
            decision: "INCONCLUSIVE",
            reason: "baseline 与 candidate 都存在监督边界异常，当前评测无法证明候选退化",
          },
        ],
      }),
      "zh",
      labels,
    );

    expect(summary.tone).toBe("warning");
    expect(summary.headline).toContain("本轮评测已完成");
    expect(summary.headline).toContain("INCONCLUSIVE");
    expect(summary.headline).toContain("2 个失败或超时样例");
    expect(summary.nextAction).toContain("这不是中断");
  });
});
