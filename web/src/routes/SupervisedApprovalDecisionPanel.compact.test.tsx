/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SupervisedWorktreeRun } from "../api/types";
import { SupervisedApprovalDecisionPanel } from "./SupervisedApprovalDecisionPanel";
import type { SupervisedApprovalAction } from "./supervisedApprovalDecision";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

type RunOverrides = Omit<Partial<SupervisedWorktreeRun>, "actionStates"> & {
  actionStates?: SupervisedWorktreeRun["actionStates"] | undefined;
};

function action(enabled: boolean, reason = "") {
  return { enabled, reason };
}

function worktreeRun(overrides: RunOverrides = {}): SupervisedWorktreeRun {
  return {
    runId: "swte-compact-test",
    runKind: "supervised_worktree",
    status: "succeeded",
    phase: "approval",
    runtimeStatus: "idle",
    outcome: "preserved",
    mode: "manual",
    approvalMode: "human",
    executionMode: "simulation",
    sourceKind: "dataset",
    datasetName: "supervised_test",
    datasetLimit: 4,
    bundleName: "",
    keepWorktree: true,
    startedAt: "2026-09-29T04:00:00Z",
    updatedAt: "2026-09-29T04:10:00Z",
    finishedAt: "2026-09-29T04:10:00Z",
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
      baselineScore: 72,
      candidateScore: 83,
      scoreDelta: 11,
      recommendedAction: "preserve",
      reason: "候选得分提升。",
      evaluationState: "VALID",
    },
    candidateJudgment: {
      status: "success",
      phase: "rerun",
      evaluationState: "VALID",
      recommendation: "PROMOTE",
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
      reason: "等待人工复核。",
    },
    mergeAnalysis: {
      status: "ready",
      mergeAllowed: true,
      reason: "无冲突。",
      blockers: [],
      overlapFiles: [],
      highRiskFiles: [],
      changedFiles: [],
    },
    actionStates: {
      approveReview: action(true),
      requestRerun: action(true),
      rejectReview: action(true),
      merge: action(false),
      rollback: action(false),
    },
    ...overrides,
  } as SupervisedWorktreeRun;
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

async function renderPanel(
  run: SupervisedWorktreeRun,
  options: {
    compact?: boolean;
    hideActions?: boolean;
    onAction: (runId: string, action: SupervisedApprovalAction) => void;
  },
) {
  await act(async () => {
    root.render(
      <SupervisedApprovalDecisionPanel
        run={run}
        lang="zh"
        pending={false}
        compact={options.compact}
        hideActions={options.hideActions}
        onAction={options.onAction}
      />,
    );
  });
}

function buttonWithLabel(label: string) {
  return Array.from(container.querySelectorAll("button"))
    .find((button) => button.textContent?.includes(label)) ?? null;
}

describe("SupervisedApprovalDecisionPanel compact mode", () => {
  it("keeps approval disabled when actionStates are missing", async () => {
    const onAction = vi.fn();
    await renderPanel(worktreeRun({ actionStates: undefined }), { compact: true, onAction });

    const approveButton = buttonWithLabel("批准并受控合入");
    expect(approveButton).not.toBeNull();
    expect(approveButton?.disabled).toBe(true);

    await act(async () => approveButton?.click());
    expect(onAction).not.toHaveBeenCalled();
  });

  it("keeps approval disabled when the approve action is explicitly disabled", async () => {
    const onAction = vi.fn();
    await renderPanel(
      worktreeRun({ actionStates: { approveReview: action(false, "需要补充复核") } }),
      { compact: true, onAction },
    );

    const approveButton = buttonWithLabel("批准并受控合入");
    expect(approveButton).not.toBeNull();
    expect(approveButton?.disabled).toBe(true);

    await act(async () => approveButton?.click());
    expect(onAction).not.toHaveBeenCalled();
  });

  it("passes the selected run ID and approval action when approval is enabled", async () => {
    const onAction = vi.fn();
    await renderPanel(worktreeRun(), { compact: true, onAction });

    const approveButton = buttonWithLabel("批准并受控合入");
    expect(approveButton).not.toBeNull();
    expect(approveButton?.disabled).toBe(false);

    await act(async () => approveButton?.click());
    expect(onAction).toHaveBeenCalledExactlyOnceWith("swte-compact-test", "approve_review");
  });

  it("omits all governance actions in hideActions mode", async () => {
    const onAction = vi.fn();
    await renderPanel(worktreeRun(), { hideActions: true, onAction });

    expect(container.querySelector("footer")).toBeNull();
    expect(container.querySelectorAll("button")).toHaveLength(0);
    expect(container.textContent).not.toContain("批准并受控合入");
    expect(container.textContent).not.toContain("要求补证据并复跑");
    expect(container.textContent).not.toContain("拒绝合入");
  });

  it("distinguishes applied from activating without rendering the full title or metric cards", async () => {
    const onAction = vi.fn();
    await renderPanel(
      worktreeRun({
        outcome: "applied",
        merge: { status: "applied", commitSha: "commit-456" },
        runtimeActivation: { status: "applied", targetCommit: "commit-456" },
      }),
      { compact: true, onAction },
    );

    expect(container.textContent).toContain("源码与前端构建已在运行时生效");
    expect(container.textContent).not.toContain("Launcher 正在激活并核验版本");
    expect(container.textContent).not.toContain("是否授权后端受控合入");
    expect(container.querySelector('[aria-label="候选对比指标"]')).toBeNull();

    await renderPanel(
      worktreeRun({
        merge: { status: "committed", commitSha: "commit-456" },
        runtimeActivation: { status: "activating", targetCommit: "commit-456" },
      }),
      { compact: true, onAction },
    );

    expect(container.textContent).toContain("Launcher 正在激活并核验版本");
    expect(container.textContent).not.toContain("源码与前端构建已在运行时生效");
    expect(container.textContent).not.toContain("是否授权后端受控合入");
    expect(container.querySelector('[aria-label="候选对比指标"]')).toBeNull();
  });
});
