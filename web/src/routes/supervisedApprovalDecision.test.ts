import { describe, expect, it } from "vitest";

import type { SupervisedWorktreeRun } from "../api/types";
import { buildSupervisedApprovalDecision } from "./supervisedApprovalDecision";

function action(enabled: boolean, reason = "") {
  return { enabled, reason };
}

function worktreeRun(overrides: Partial<SupervisedWorktreeRun> = {}): SupervisedWorktreeRun {
  return {
    runId: "swte-approval-test",
    runKind: "supervised_worktree",
    status: "succeeded",
    phase: "approval",
    runtimeStatus: "idle",
    outcome: "preserved",
    mode: "manual",
    executionMode: "simulation",
    sourceKind: "dataset",
    datasetName: "supervised_dry_run",
    datasetLimit: 4,
    bundleName: "",
    keepWorktree: true,
    startedAt: "2026-07-29T04:00:00Z",
    updatedAt: "2026-07-29T04:10:00Z",
    finishedAt: "2026-07-29T04:10:00Z",
    latestMessage: "等待用户审批。",
    costEstimate: {
      caseCount: 4,
      evaluationCalls: 8,
      selfEditCalls: 1,
      modelCalls: 9,
      estimatedInputTokens: 12000,
      estimatedOutputTokens: 4000,
      estimatedTotalTokens: 16000,
      note: "",
    },
    decision: {
      baselineScore: 0.72,
      candidateScore: 0.83,
      scoreDelta: 0.11,
      recommendedAction: "preserve",
      reason: "候选得分提升且没有文件冲突。",
      highRisk: true,
    },
    reviewGate: {
      required: true,
      status: "pending",
      reason: "高风险文件需要人工确认。",
    },
    mergeAnalysis: {
      status: "ready",
      mergeAllowed: true,
      reason: "没有主工作区重叠。",
      blockers: [],
      overlapFiles: [],
      highRiskFiles: ["core/agent/prompt_policy.py"],
      changedFiles: [
        {
          path: "core/agent/prompt_policy.py",
          status: "M",
          changeType: "modified",
          highRisk: true,
        },
        {
          path: "tests/test_prompt_policy.py",
          status: "M",
          changeType: "modified",
          highRisk: false,
        },
      ],
    },
    actionStates: {
      approveReview: action(true),
      merge: action(false, "请先批准 review gate。"),
      rollback: action(false, "当前没有可用回滚清单。"),
    },
    ...overrides,
  };
}

describe("buildSupervisedApprovalDecision", () => {
  it("keeps review approval separate from project merge and runtime application", () => {
    const model = buildSupervisedApprovalDecision(worktreeRun(), "zh");

    expect(model.phase).toBe("pending_review");
    expect(model.primaryAction).toBe("approve_review");
    expect(model.headline).toContain("批准评审");
    expect(model.runtimeEffect).toBe("not_applied");
    expect(model.metrics).toMatchObject({
      baselineScore: 0.72,
      candidateScore: 0.83,
      scoreDelta: 0.11,
      changedFileCount: 2,
      highRiskFileCount: 1,
      overlapFileCount: 0,
      blockerCount: 0,
    });
  });

  it("offers rollback after merge without claiming the runtime has been refreshed", () => {
    const model = buildSupervisedApprovalDecision(
      worktreeRun({
        outcome: "merged",
        reviewGate: { required: true, status: "approved" },
        merge: {
          status: "merged",
          mergedAt: "2026-07-29T04:12:00Z",
          changedFiles: ["core/agent/prompt_policy.py", "tests/test_prompt_policy.py"],
          rollbackManifestPath: "workspace/rollback.json",
        },
        rollback: {
          status: "available",
          manifestPath: "workspace/rollback.json",
          reason: "已生成合并回滚清单。",
        },
        actionStates: {
          approveReview: action(false),
          merge: action(false),
          rollback: action(true),
        },
      }),
      "zh",
    );

    expect(model.phase).toBe("merged");
    expect(model.primaryAction).toBe("rollback");
    expect(model.runtimeEffect).toBe("refresh_required");
    expect(model.headline).toContain("回滚保护可用");
  });

  it("moves to a separate manual merge action after review approval", () => {
    const model = buildSupervisedApprovalDecision(
      worktreeRun({
        reviewGate: { required: true, status: "approved" },
        actionStates: {
          approveReview: action(false),
          merge: action(true),
          rollback: action(false),
        },
      }),
      "zh",
    );

    expect(model.phase).toBe("ready_merge");
    expect(model.primaryAction).toBe("merge");
    expect(model.headline).toContain("可将候选写入项目");
    expect(model.runtimeEffect).toBe("not_applied");
  });

  it("surfaces a merged snapshot without rollback protection as incomplete", () => {
    const model = buildSupervisedApprovalDecision(
      worktreeRun({
        outcome: "merged",
        reviewGate: { required: true, status: "approved" },
        merge: {
          status: "merged",
          changedFiles: ["core/agent/prompt_policy.py"],
        },
        rollback: {},
        actionStates: {
          approveReview: action(false),
          merge: action(false),
          rollback: action(false),
        },
      }),
      "zh",
    );

    expect(model.phase).toBe("merged");
    expect(model.tone).toBe("warning");
    expect(model.primaryAction).toBeNull();
    expect(model.headline).toContain("回滚保护不可用");
    expect(model.evidence.some((item) => item.text.includes("治理结果不完整"))).toBe(true);
  });

  it("keeps merge blockers visible and removes the executable action", () => {
    const model = buildSupervisedApprovalDecision(
      worktreeRun({
        reviewGate: { required: true, status: "approved" },
        mergeAnalysis: {
          status: "blocked",
          mergeAllowed: false,
          reason: "主工作区存在冲突。",
          blockers: ["core/agent/prompt_policy.py 与主工作区重叠"],
          overlapFiles: ["core/agent/prompt_policy.py"],
          highRiskFiles: ["core/agent/prompt_policy.py"],
          changedFiles: [],
        },
        actionStates: {
          approveReview: action(false),
          merge: action(false, "请先处理冲突。"),
          rollback: action(false),
        },
      }),
      "zh",
    );

    expect(model.phase).toBe("blocked");
    expect(model.primaryAction).toBeNull();
    expect(model.metrics).toMatchObject({ overlapFileCount: 1, blockerCount: 1 });
    expect(model.blockers).toEqual(["core/agent/prompt_policy.py 与主工作区重叠"]);
  });

  it("renders completed rollback as a terminal governance result", () => {
    const model = buildSupervisedApprovalDecision(
      worktreeRun({
        outcome: "merge_rolled_back",
        reviewGate: { required: true, status: "approved" },
        merge: {
          status: "merged",
          changedFiles: ["core/agent/prompt_policy.py", "tests/test_prompt_policy.py"],
        },
        rollback: {
          status: "rolled_back",
          rolledBackAt: "2026-07-29T04:15:00Z",
          reason: "已恢复合并前文件状态。",
        },
        actionStates: {
          approveReview: action(false),
          merge: action(false),
          rollback: action(false),
        },
      }),
      "zh",
    );

    expect(model.phase).toBe("rolled_back");
    expect(model.primaryAction).toBeNull();
    expect(model.headline).toContain("已恢复合入前文件状态");
    expect(model.runtimeEffect).toBe("refresh_required");
  });
});
