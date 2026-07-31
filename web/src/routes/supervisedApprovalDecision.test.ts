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
    approvalMode: "human",
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
      scoreSource: "judge_agent",
      judgeDecision: "PROMOTE",
      baselineScore: 72,
      candidateScore: 83,
      scoreDelta: 11,
      recommendedAction: "preserve",
      reason: "候选得分提升且没有文件冲突。",
      highRisk: true,
      evaluationState: "VALID",
    },
    candidateJudgment: {
      status: "success",
      phase: "rerun",
      evaluationState: "VALID",
      recommendation: "REJECT",
    },
    approvalDecision: {
      schemaVersion: 1,
      mode: "human",
      status: "pending",
      decision: "",
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
  it("presents the Judge recommendation as advisory with the frozen rubric breakdown", () => {
    const run = worktreeRun();
    Object.assign(run as unknown as Record<string, unknown>, {
      judgeRubric: {
        rubricHash: "abc123",
        taskSummary: "修复失败恢复",
        compositionWeights: { taskSpecific: 0.7, systemFixed: 0.3 },
        taskCriteria: [
          { id: "failure_recovery", label: "失败恢复", description: "恢复后状态一致", weight: 1 },
        ],
        systemCriteria: [
          { id: "scope_and_safety", label: "范围与安全", description: "不越界", weight: 1 },
        ],
      },
      baselineJudgment: {
        status: "success",
        phase: "baseline",
        recommendation: "REVISE",
        decision: "REVISE",
        score: 61,
        taskScore: 58,
        systemScore: 68,
        taskScores: { failure_recovery: 58 },
        systemScores: { scope_and_safety: 68 },
        rubricHash: "abc123",
      },
      candidateJudgment: {
        status: "success",
        phase: "rerun",
        recommendation: "REJECT",
        decision: "REJECT",
        score: 79,
        taskScore: 82,
        systemScore: 72,
        taskScores: { failure_recovery: 82 },
        systemScores: { scope_and_safety: 72 },
        rubricHash: "abc123",
      },
      decision: {
        ...run.decision,
        judgeRecommendation: "REJECT",
        judgeDecision: "REJECT",
        baselineScore: 61,
        candidateScore: 79,
        scoreDelta: 18,
        recommendedAction: "user_decision",
      },
    });

    const model = buildSupervisedApprovalDecision(run, "zh");

    expect(model.judgeRecommendation).toEqual({
      code: "REJECT",
      label: "建议拒绝",
    });
    expect(model.rubric).toMatchObject({
      hash: "abc123",
      taskSummary: "修复失败恢复",
      taskWeight: 0.7,
      systemWeight: 0.3,
    });
    expect(model.rubric.taskCriteria[0].label).toBe("失败恢复");
    expect(model.rubric.taskCriteria[0]).toMatchObject({
      baselineScore: 58,
      candidateScore: 82,
    });
    expect(model.rubric.systemCriteria[0].label).toBe("范围与安全");
    expect(model.rubric.systemCriteria[0]).toMatchObject({
      baselineScore: 68,
      candidateScore: 72,
    });
    expect(model.metrics).toMatchObject({
      baselineTaskScore: 58,
      baselineSystemScore: 68,
      candidateTaskScore: 82,
      candidateSystemScore: 72,
    });
    expect(model.evidence.some((item) => item.text.includes("不能覆盖评估状态"))).toBe(true);
  });

  it("presents human approval as the final immutable merge decision", () => {
    const model = buildSupervisedApprovalDecision(worktreeRun(), "zh");

    expect(model.phase).toBe("pending_review");
    expect(model.primaryAction).toBe("approve_review");
    expect(model.headline).toContain("人工决定");
    expect(model.primaryActionLabel).toBe("批准并受控合入");
    expect(model.approvalMode.code).toBe("human");
    expect(model.evaluationState.code).toBe("VALID");
    expect(model.secondaryActions.map((item) => item.action)).toEqual([
      "request_rerun",
      "reject_review",
    ]);
    expect(model.runtimeEffect).toBe("not_applied");
    expect(model.metrics).toMatchObject({
      baselineScore: 72,
      candidateScore: 83,
      scoreDelta: 11,
      changedFileCount: 2,
      highRiskFileCount: 1,
      overlapFileCount: 0,
      blockerCount: 0,
    });
  });

  it("uses an independent Agent approval action when the run was frozen in agent mode", () => {
    const model = buildSupervisedApprovalDecision(
      worktreeRun({
        approvalMode: "agent",
        approvalDecision: {
          schemaVersion: 1,
          mode: "agent",
          status: "pending",
          decision: "",
        },
        actionStates: {
          approveReview: action(false, "agent mode"),
          runAgentApproval: action(true),
          rollback: action(false),
        },
      }),
      "zh",
    );

    expect(model.phase).toBe("pending_review");
    expect(model.approvalMode).toEqual({ code: "agent", label: "Agent 审批" });
    expect(model.primaryAction).toBe("run_agent_approval");
    expect(model.primaryActionLabel).toBe("启动 Agent 审批");
    expect(model.secondaryActions).toEqual([]);
  });

  it("keeps an inconclusive score visible but blocks approval and offers rerun or reject", () => {
    const run = worktreeRun({
      candidateJudgment: {
        status: "success",
        phase: "rerun",
        evaluationState: "INCONCLUSIVE",
        recommendation: "INCONCLUSIVE",
        score: 91,
      },
      decision: {
        baselineScore: 88,
        candidateScore: 91,
        scoreDelta: 3,
        evaluationState: "INCONCLUSIVE",
      },
      actionStates: {
        approveReview: action(false, "INCONCLUSIVE cannot approve"),
        requestRerun: action(true),
        rejectReview: action(true),
        rollback: action(false),
      },
    });

    const model = buildSupervisedApprovalDecision(run, "zh");

    expect(model.metrics.candidateScore).toBe(91);
    expect(model.evaluationState.code).toBe("INCONCLUSIVE");
    expect(model.phase).toBe("blocked");
    expect(model.primaryAction).toBeNull();
    expect(model.secondaryActions.map((item) => item.action)).toEqual([
      "request_rerun",
      "reject_review",
    ]);
  });

  it("projects an immutable rerun decision as completed review with merge unauthorized", () => {
    const model = buildSupervisedApprovalDecision(
      worktreeRun({
        status: "done",
        phase: "complete",
        outcome: "approval_rerun_required",
        latestMessage: "审批要求补充证据并重新运行。",
        reviewGate: { required: true, status: "rejected" },
        approvalDecision: {
          schemaVersion: 1,
          mode: "human",
          status: "decided",
          decision: "RERUN_REQUIRED",
          evaluationState: "INCONCLUSIVE",
          reason: "",
        },
        actionStates: {
          approveReview: action(false),
          requestRerun: action(false),
          rejectReview: action(false),
          merge: action(false),
          rollback: action(false),
        },
      }),
      "zh",
    );

    expect(model.phase).toBe("closed");
    expect(model.reason).toBe("候选得分提升且没有文件冲突。");
    expect(model.steps.find((step) => step.id === "review")).toMatchObject({
      status: "done",
      statusLabel: "已要求复跑",
    });
    expect(model.steps.find((step) => step.id === "merge")).toMatchObject({
      status: "blocked",
      statusLabel: "未授权 · 待复跑",
    });
    expect(model.primaryAction).toBeNull();
    expect(model.secondaryActions).toEqual([]);
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

  it("projects an existing approved record as backend merge-ready", () => {
    const model = buildSupervisedApprovalDecision(
      worktreeRun({
        reviewGate: { required: true, status: "approved" },
        approvalDecision: {
          schemaVersion: 1,
          mode: "human",
          status: "decided",
          decision: "APPROVE",
          evaluationState: "VALID",
        },
        actionStates: {
          approveReview: action(false),
          merge: action(true),
          rollback: action(false),
        },
      }),
      "zh",
    );

    expect(model.phase).toBe("ready_merge");
    expect(model.primaryAction).toBeNull();
    expect(model.headline).toContain("后端受控合入");
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
