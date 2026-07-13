import { describe, expect, it } from "vitest";

import {
  sourceCollectionCompletionFlowNodeState,
  sourceCollectionStageBackendActionReadiness,
  sourceCollectionStageCardsFromStatus,
  sourceCollectionStageProjectionCount,
  sourceCollectionStageProjectionState,
  sourceCollectionStageUserStatusLabel,
  sourceCollectionStageUserSummary,
  sourceCollectionStageWritebackObservedTaskIds,
  sourceCollectionTaskToolProgressMetric,
  type SourceCollectionStageCardProjection,
} from "./stageProjection";

function stageCard(
  status: string,
  extra: Partial<SourceCollectionStageCardProjection> = {},
): SourceCollectionStageCardProjection {
  return {
    stageId: "extraction",
    status,
    ...extra,
  };
}

describe("source collection stage projection", () => {
  it("maps backend stage states without erasing the caller fallback", () => {
    expect(sourceCollectionStageProjectionState(stageCard("agent_running"), "idle")).toBe("active");
    expect(sourceCollectionStageProjectionState(stageCard("partial_current_inputs"), "idle")).toBe("pending");
    expect(sourceCollectionStageProjectionState(stageCard("agent_blocked"), "idle")).toBe("failed");
    expect(sourceCollectionStageProjectionState(stageCard("closed_loop"), "idle")).toBe("done");
    expect(sourceCollectionStageProjectionState(stageCard("unknown"), "active")).toBe("active");
    expect(sourceCollectionStageProjectionState(null, "pending")).toBe("pending");
  });

  it("keeps finite stage counts and falls back for absent or invalid values", () => {
    const projection = stageCard("pending", { counts: { artifact: 4, pending: Number.NaN } });

    expect(sourceCollectionStageProjectionCount(projection, "artifact", 1)).toBe(4);
    expect(sourceCollectionStageProjectionCount(projection, "pending", 2)).toBe(2);
    expect(sourceCollectionStageProjectionCount(null, "artifact", 3)).toBe(3);
  });

  it("projects completion-flow node statuses into the shared step-state vocabulary", () => {
    expect(sourceCollectionCompletionFlowNodeState("in_progress")).toBe("active");
    expect(sourceCollectionCompletionFlowNodeState("completed")).toBe("done");
    expect(sourceCollectionCompletionFlowNodeState("blocked")).toBe("failed");
    expect(sourceCollectionCompletionFlowNodeState("queued")).toBe("pending");
    expect(sourceCollectionCompletionFlowNodeState("unknown")).toBe("idle");
  });

  it("shows checklist completion and unresolved item count", () => {
    expect(sourceCollectionTaskToolProgressMetric(
      { required: true, total: 3, completed: 1, pendingIds: ["read", "write"] },
      "zh",
      [
        { id: "read", description: "读取资料" },
        { id: "write", description: "写回结果" },
      ],
    )).toBe("检查项 1/3 · 剩余 2 项");
  });

  it("prioritizes interrupted status and recovery instructions", () => {
    const projection = stageCard("agent_interrupted", {
      latestTask: {
        taskId: "task-1",
        status: "interrupted",
        taskChecklist: [{ id: "write", description: "写回结果" }],
        taskToolProgress: {
          required: true,
          total: 2,
          completed: 1,
          pendingIds: ["write"],
        },
        closureSummary: {
          retryInstruction: "继续这次任务",
        },
      },
    });

    expect(sourceCollectionStageUserStatusLabel(projection, "zh")).toBe("已中断，需要继续");
    expect(sourceCollectionStageUserSummary(projection, "zh")).toBe(
      "本轮已中断：Agent 私聊尚未完成阶段回写。检查项 1/2；剩余检查项：写回结果。建议：继续这次任务。",
    );
  });

  it("describes partial coverage as a stage-specific recovery state", () => {
    const projection = stageCard("partial_current_inputs", {
      currentCoverageSummary: {
        applicable: true,
        complete: false,
        total: 5,
        processed: 3,
        missing: 2,
        invalid: 1,
      },
    });

    expect(sourceCollectionStageUserStatusLabel(projection, "zh")).toBe("待补提炼");
    expect(sourceCollectionStageUserSummary(projection, "zh")).toBe(
      "候选资料当前进度 3/5，还有 2 条需要补齐。无效 ID 1 条。建议：继续补全提炼。",
    );
  });

  it("uses backend action readiness only when the backend made an explicit decision", () => {
    const fallback = { disabled: true, loading: true, reason: "仍在加载" };

    expect(sourceCollectionStageBackendActionReadiness(null, fallback, "没有输入")).toEqual(fallback);
    expect(sourceCollectionStageBackendActionReadiness(
      stageCard("idle", { actionReadiness: { canStart: true } }),
      fallback,
      "没有输入",
    )).toEqual({ disabled: false, loading: false, reason: "" });
    expect(sourceCollectionStageBackendActionReadiness(
      stageCard("idle", { actionReadiness: { canStart: false, disabledReason: "等待上游" } }),
      fallback,
      "没有输入",
    )).toEqual({ disabled: true, loading: false, reason: "等待上游" });
  });

  it("deduplicates knowledge-stage cards before collecting observed task IDs", () => {
    const first = stageCard("agent_running", { latestTask: { taskId: "task-1" } });
    const second = stageCard("closed_loop", { stageId: "relations", latestTask: { taskId: "task-2" } });
    const cards = sourceCollectionStageCardsFromStatus({
      phases: [{
        stageType: "knowledge_collection",
        latestRound: {
          stageRoundId: "round-1",
          stageType: "knowledge_collection",
          roundNumber: 1,
          sourceCollectionStageCards: [first],
        },
      }],
      latestRound: {
        stageRoundId: "round-1",
        stageType: "knowledge_collection",
        roundNumber: 1,
        sourceCollectionStageCards: [first],
      },
      activeRounds: [{
        stageRoundId: "round-2",
        stageType: "knowledge_collection",
        roundNumber: 2,
        sourceCollectionStageCards: [second],
      }],
    });

    expect(cards).toEqual([first, second]);
    expect([...sourceCollectionStageWritebackObservedTaskIds(cards)]).toEqual(["task-1", "task-2"]);
  });

  it("accepts the source-summary stage-card shape directly", () => {
    const card = stageCard("closed_loop", { latestTask: { taskId: "task-summary" } });

    expect(sourceCollectionStageCardsFromStatus({ stageCards: [card] })).toEqual([card]);
  });
});
