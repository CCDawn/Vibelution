/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ResearchWorkflowProgress } from "../../../api/types/research-workflow/core";
import type { WorkflowLayoutInput } from "../../../components/vui";
import {
  buildResearchWorkflowStageNavigatorModel,
  ResearchWorkflowStageNavigator,
} from "./ResearchWorkflowStageNavigator";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const graph: WorkflowLayoutInput = {
  stages: [
    { stageId: "hypothesis_first", label: "假说先行", nodeIds: ["hf_generation"], stageTone: "done", progress: { completed: 2, total: 2 } },
    { stageId: "knowledge", label: "知识搜集", nodeIds: ["source_finding", "source_review"], stageTone: "active" },
    { stageId: "experiment", label: "实验设计", nodeIds: ["protocol_design"], stageTone: "attention" },
    { stageId: "handoff", label: "成果交付", nodeIds: [], stageTone: "idle" },
  ],
  nodes: [
    { nodeId: "hf_generation", stageId: "hypothesis_first", label: "候选假说", actorKind: "agent", visualKind: "agent_task", status: "succeeded" },
    { nodeId: "source_finding", stageId: "knowledge", label: "资料发现", actorKind: "agent", visualKind: "agent_task", status: "succeeded" },
    { nodeId: "source_review", stageId: "knowledge", label: "资料复核", actorKind: "human", visualKind: "human_gate", status: "running", isRuntimeCurrent: true },
    { nodeId: "protocol_design", stageId: "experiment", label: "协议设计", actorKind: "agent", visualKind: "agent_task", status: "blocked" },
  ],
  edges: [],
};

function formalProgress(): ResearchWorkflowProgress {
  return {
    completedNodes: 1,
    totalNodes: 3,
    blockedNodes: 1,
    currentStageId: "knowledge",
    stages: [
      { id: "knowledge", completed: 0, total: 2, blocked: 0, state: "current" },
      { id: "experiment", completed: 1, total: 1, blocked: 1, state: "blocked" },
    ],
    completedNodeIds: ["protocol_design"],
    blockedNodeIds: ["source_finding"],
    completed: 1,
    total: 3,
    percent: 33,
    currentNodeId: "source_review",
    status: "running",
  };
}

describe("buildResearchWorkflowStageNavigatorModel", () => {
  it("keeps hypothesis and formal stages continuous and maps graph states", () => {
    const model = buildResearchWorkflowStageNavigatorModel({ graph, progress: null });

    expect(model.stages.map((stage) => stage.id)).toEqual(["hypothesis_first", "knowledge", "experiment", "handoff"]);
    expect(model.stages.map((stage) => stage.status)).toEqual(["completed", "current", "blocked", "upcoming"]);
    expect(model.summary).toMatchObject({ currentStage: 2, totalStages: 4, completedNodes: 2, totalNodes: 4, blockedNodes: 1, percent: 50, authority: "graph" });
    expect(model.stages[3].targetNodeId).toBeNull();
  });

  it("gives matching formal progress precedence without rewriting hypothesis progress", () => {
    const model = buildResearchWorkflowStageNavigatorModel({
      graph,
      progress: formalProgress(),
      currentTaskNodeId: "source_review",
    });

    expect(model.stages[0]).toMatchObject({ id: "hypothesis_first", completed: 2, total: 2, status: "completed" });
    expect(model.stages[1]).toMatchObject({ id: "knowledge", completed: 0, total: 2, blocked: 0, status: "current", targetNodeId: "source_review" });
    expect(model.stages[1].nodes.map((node) => [node.id, node.status])).toEqual([
      ["source_finding", "blocked"],
      ["source_review", "current"],
    ]);
    expect(model.stages[2]).toMatchObject({ id: "experiment", completed: 1, total: 1, blocked: 1, status: "blocked" });
    expect(model.summary).toEqual({ currentStage: 2, totalStages: 4, completedNodes: 1, totalNodes: 3, blockedNodes: 1, percent: 33, authority: "formal" });
  });

  it("keeps unknown and loading states mounted without leaking stale formal progress", () => {
    expect(buildResearchWorkflowStageNavigatorModel({ graph, progress: formalProgress(), scopeMismatch: true })).toEqual({
      state: "unknown",
      detail: "题目或运行范围正在切换，等待权威快照。",
      stages: [],
      summary: {
        currentStage: 0,
        totalStages: 0,
        completedNodes: 0,
        totalNodes: 0,
        blockedNodes: 0,
        percent: 0,
        authority: "graph",
      },
    });
    expect(buildResearchWorkflowStageNavigatorModel({ graph: null, progress: null, loadState: "loading" })).toMatchObject({ state: "loading", stages: [] });
  });
});

describe("ResearchWorkflowStageNavigator", () => {
  let root: Root | null = null;
  afterEach(async () => {
    if (root) await act(async () => root?.unmount());
    root = null;
    document.body.innerHTML = "";
  });

  it("keeps progress compact, expands the current stage, and only navigates from a node", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    const onNavigateNode = vi.fn();
    const model = buildResearchWorkflowStageNavigatorModel({ graph, progress: formalProgress() });
    await act(async () => root?.render(<ResearchWorkflowStageNavigator lang="zh" model={model} onNavigateNode={onNavigateNode} />));

    expect(container.querySelector("header")?.textContent).toContain("进度1/3");
    expect(container.querySelector("header")?.textContent).toContain("1 项阻塞");
    expect(container.querySelector('[role="progressbar"]')?.getAttribute("aria-valuenow")).toBe("33");
    expect(container.querySelector('[data-testid="stage-navigator-summary"]')).toBeNull();
    expect(container.querySelector('li[data-stage-status="blocked"] svg')).not.toBeNull();
    expect(container.querySelector('[aria-label="知识搜集节点"]')).not.toBeNull();
    const knowledgeStage = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent?.includes("知识搜集0/2"));
    await act(async () => knowledgeStage?.click());
    expect(onNavigateNode).not.toHaveBeenCalled();
    expect(container.querySelector('[aria-label="知识搜集节点"]')).toBeNull();
    await act(async () => knowledgeStage?.click());
    const sourceNode = Array.from(container.querySelectorAll("button")).find((button) => button.textContent?.includes("资料发现"));
    await act(async () => sourceNode?.click());
    expect(onNavigateNode).toHaveBeenCalledOnce();
    expect(onNavigateNode).toHaveBeenCalledWith("source_finding");
    expect(sourceNode?.getAttribute("aria-label")).toBe("资料发现 · 已阻塞");
    expect(sourceNode?.textContent).toBe("资料发现");
    const disabledStage = Array.from(container.querySelectorAll("button")).find((button) => button.textContent?.includes("成果交付"));
    expect(disabledStage?.hasAttribute("disabled")).toBe(true);
  });
});
