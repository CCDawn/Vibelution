import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { SelfEvolutionAutonomousLoopRun } from "../api/types";
import { SelfEvolutionAutonomousLoopPanel } from "./SelfEvolutionAutonomousLoopPanel";

function reviewRun(): SelfEvolutionAutonomousLoopRun {
  return {
    schemaVersion: 1,
    runKind: "self_evolution_autonomous_loop",
    runId: "self-loop-panel",
    status: "awaiting_user_approval",
    phase: "reporting",
    request: { goal: "收敛自进化流程", maxIterations: 1 },
    observation: {
      summary: "发现状态机仍依赖旧评估阶段。",
      evidence: ["route contract"],
      conversationSessionId: "session-observe",
    },
    plan: {
      summary: "拆出无评分自动闭环。",
      steps: ["新增状态机", "接入 Git 事务"],
      conversationSessionId: "session-plan",
    },
    candidate: {
      summary: "候选已完成并通过聚焦测试。",
      changedFiles: [
        { path: "core/web/services/self_loop.py", changeType: "added" },
      ],
      verification: ["pytest 48 passed"],
      baseCommit: "base123",
      headCommit: "candidate456",
      worktreePath: "C:/tmp/self-loop",
      branchName: "codex/self-evolution-self-loop-panel",
      variantId: "sha256:candidate",
      conversationSessionId: "session-evolve",
    },
    resultReport: {
      summary: "候选已完成并通过聚焦测试。",
      changedFiles: [
        { path: "core/web/services/self_loop.py", changeType: "added" },
      ],
      verification: ["pytest 48 passed"],
      candidateHead: "candidate456",
    },
    reviewGate: {
      status: "pending",
      requiredActorType: "user",
    },
    createdAt: "2026-08-01T00:00:00Z",
    startedAt: "2026-08-01T00:00:00Z",
    updatedAt: "2026-08-01T00:03:00Z",
  };
}

describe("SelfEvolutionAutonomousLoopPanel", () => {
  it("keeps launch failures visible before a run record exists", () => {
    const markup = renderToStaticMarkup(
      <MemoryRouter>
        <SelfEvolutionAutonomousLoopPanel
          lang="zh"
          run={null}
          pending={false}
          error="主工作区当前不干净"
          onAction={vi.fn()}
        />
      </MemoryRouter>,
    );

    expect(markup).toContain("主工作区当前不干净");
    expect(markup).toContain("必须由用户审查");
  });

  it("renders the no-score lifecycle and user-only approval boundary", () => {
    const markup = renderToStaticMarkup(
      <MemoryRouter>
        <SelfEvolutionAutonomousLoopPanel
          lang="zh"
          run={reviewRun()}
          pending={false}
          error=""
          onAction={vi.fn()}
        />
      </MemoryRouter>,
    );

    expect(markup).toContain("自动闭环");
    expect(markup).toContain("观察现状");
    expect(markup).toContain("制定计划");
    expect(markup).toContain("隔离进化");
    expect(markup).toContain("等待用户审查");
    expect(markup).toContain("批准并自动合入");
    expect(markup).toContain("拒绝并保留候选");
    expect(markup).toContain("pytest 48 passed");
    expect(markup).toContain("data-vui=\"surface\"");
    expect(markup).toContain("data-vui=\"metric-strip\"");
    expect(markup).not.toContain("Judge");
    expect(markup).not.toContain("候选评分");
    expect(markup).not.toContain("分数");
  });

  it("reports exact Git and cleanup proof after completion", () => {
    const completed = {
      ...reviewRun(),
      status: "completed",
      phase: "completed",
      reviewGate: {
        status: "approved",
        requiredActorType: "user" as const,
      },
      integration: {
        status: "committed",
        mechanism: "git_commit",
        baseCommit: "base123",
        commitSha: "commit789",
        candidateVariantId: "sha256:candidate",
        changedFiles: ["core/web/services/self_loop.py"],
        rollbackManifestPath: "manifests/self-loop-panel.json",
        committedAt: "2026-08-01T00:04:00Z",
      },
      cleanup: {
        status: "cleaned",
        worktreeRemoved: true,
        localBranchDeleted: true,
      },
      finishedAt: "2026-08-01T00:04:30Z",
    } satisfies SelfEvolutionAutonomousLoopRun;

    const markup = renderToStaticMarkup(
      <MemoryRouter>
        <SelfEvolutionAutonomousLoopPanel
          lang="zh"
          run={completed}
          pending={false}
          error=""
          onAction={vi.fn()}
        />
      </MemoryRouter>,
    );

    expect(markup).toContain("commit789");
    expect(markup).toContain("工作树已删除");
    expect(markup).toContain("本地分支已删除");
    expect(markup).toContain("闭环完成");
  });

  it("shows an interrupted integration without claiming cleanup", () => {
    const failed = {
      ...reviewRun(),
      status: "failed",
      phase: "integration_failed",
      error: {
        type: "CandidateIntegrationError",
        message: "main HEAD 已变化，候选环境已保留",
      },
      finishedAt: "2026-08-01T00:04:30Z",
    } satisfies SelfEvolutionAutonomousLoopRun;

    const markup = renderToStaticMarkup(
      <MemoryRouter>
        <SelfEvolutionAutonomousLoopPanel
          lang="zh"
          run={failed}
          pending={false}
          error=""
          onAction={vi.fn()}
        />
      </MemoryRouter>,
    );

    expect(markup).toContain("自动闭环未完成");
    expect(markup).toContain("main HEAD 已变化");
    expect(markup).toContain("已保留");
    expect(markup).toContain("重试 Git 集成");
    expect(markup).not.toContain("工作树已删除");
    expect(markup).toContain('data-testid="self-loop-phase-stepper"');
    expect(markup).toContain('data-state="interrupted"');
  });

  it("maps observing_interrupted to the observe step and keeps chips compact", () => {
    const interrupted = {
      ...reviewRun(),
      status: "failed",
      phase: "observing_interrupted",
      observation: undefined,
      plan: undefined,
      candidate: undefined,
      resultReport: undefined,
      error: {
        type: "Interrupted",
        message: "The autonomous loop was interrupted before the process restarted.",
      },
      finishedAt: "2026-08-04T03:16:49Z",
    } as SelfEvolutionAutonomousLoopRun;

    const markup = renderToStaticMarkup(
      <MemoryRouter>
        <SelfEvolutionAutonomousLoopPanel
          lang="zh"
          run={interrupted}
          pending={false}
          error=""
          onAction={vi.fn()}
        />
      </MemoryRouter>,
    );

    expect(markup).toContain("自动闭环未完成");
    expect(markup).toContain("闭环中断");
    expect(markup).toContain('data-phase="observing"');
    expect(markup).toContain('data-state="interrupted"');
    expect(markup).toContain("中断");
    expect(markup).toContain("max-w-[9.5rem]");
    expect(markup).toContain("shrink-0");
    // Empty stage cards are collapsed when failed and no summaries exist.
    expect(markup).not.toContain("尚未产生观察摘要");
  });
});
