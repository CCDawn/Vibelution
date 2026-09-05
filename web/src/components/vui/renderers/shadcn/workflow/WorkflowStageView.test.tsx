/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { WorkflowStageView } from "./WorkflowStageView";
import type { WorkflowLayoutInput } from "../../../product/workflow/workflowCanvasTypes";

const graph: WorkflowLayoutInput = {
  stages: [{stageId: "a", label: "第一阶段", nodeIds: ["a", "b"]}, {stageId: "c", label: "知识子流程", nodeIds: ["c"]}],
  nodes: [
    {nodeId: "a", stageId: "a", label: "已完成节点", status: "succeeded", actorKind: "agent", visualKind: "agent_task"},
    {nodeId: "b", stageId: "a", label: "当前节点", status: "waiting_human", actorKind: "human", visualKind: "human_gate"},
    {nodeId: "c", stageId: "c", label: "知识搜集", status: "running", actorKind: "agent", visualKind: "agent_task"},
  ],
  edges: [{edgeId: "branch", fromNodeId: "a", toNodeId: "c", label: "补充证据", gateKind: "auto", semanticKind: "decision_branch", pathState: "active", labelAlwaysVisible: true}],
};

describe("readable stage projection", () => {
  it("preserves node states and real branches without inventing sequential edges", async () => {
    (globalThis as {IS_REACT_ACT_ENVIRONMENT?: boolean}).IS_REACT_ACT_ENVIRONMENT = true;
    const before = JSON.stringify(graph);
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    const onSelect = vi.fn();
    try {
      await act(async () => root.render(<WorkflowStageView graph={graph} runtimeCurrentNodeIds={["b"]} onSelectNode={onSelect}/>));
      expect(host.querySelector('[data-node-id="a"]')?.getAttribute("data-node-status")).toBe("succeeded");
      expect(host.querySelector('[data-node-id="b"]')?.textContent).toContain("当前任务");
      expect(host.textContent).toContain("等待人工");
      expect(host.querySelectorAll('[data-edge-id]')).toHaveLength(1);
      expect(host.textContent).toContain("补充证据 → 知识搜集（跨阶段）");
      await act(async () => (host.querySelector('[data-edge-id="branch"] button') as HTMLButtonElement).click());
      expect(onSelect).toHaveBeenCalledWith("c");
      await act(async () => root.render(<WorkflowStageView graph={graph} selectedNodeId="c" runtimeCurrentNodeIds={["b"]} onSelectNode={onSelect}/>));
      expect(host.querySelector('[data-node-id="a"]')).toBeNull();
      expect(host.querySelector('[data-node-id="c"]')?.textContent).not.toContain("当前任务");
      expect(host.querySelector('[data-node-id="c"]')?.getAttribute("data-node-status")).toBe("running");
      expect(JSON.stringify(graph)).toBe(before);
    } finally {
      await act(async () => root.unmount());
      host.remove();
    }
  });
});
