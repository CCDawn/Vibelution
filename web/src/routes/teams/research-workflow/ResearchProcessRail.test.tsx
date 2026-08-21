/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { WorkflowLayoutInput } from "../../../components/vui";
import { ResearchProcessRail } from "./ResearchProcessRail";
import type { HypothesisFirstNextAction } from "./hypothesisFirstNextAction";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const graph: WorkflowLayoutInput = {
  stages: [
    {
      stageId: "hypothesis_first",
      label: "假说先行",
      nodeIds: ["hf_generation", "hf_meeting_1"],
      index: 1,
      stageTone: "active",
    },
    {
      stageId: "knowledge_collection",
      label: "知识搜集",
      nodeIds: ["source_finding"],
      index: 2,
      stageTone: "idle",
    },
  ],
  nodes: [
    {
      nodeId: "hf_generation",
      stageId: "hypothesis_first",
      label: "候选假说生成",
      actorKind: "agent",
      visualKind: "agent_task",
      status: "succeeded",
      description: "已产出候选假说",
    },
    {
      nodeId: "hf_meeting_1",
      stageId: "hypothesis_first",
      label: "第 1 轮讨论·评审",
      actorKind: "agent",
      visualKind: "agent_task",
      status: "waiting_human",
      description: "等待人工确认闭环",
    },
    {
      nodeId: "source_finding",
      stageId: "knowledge_collection",
      label: "资料寻找",
      actorKind: "agent",
      visualKind: "agent_task",
      status: "pending",
      description: "等待搜集任务",
    },
  ],
  edges: [],
  run: null,
};

const nextAction: HypothesisFirstNextAction = {
  stage: "review_awaiting_approval",
  targetNodeId: "hf_meeting_1",
  navigationLabel: "前往确认本轮",
  command: "approve_review_digest",
  commandLabel: "确认并结束本轮",
  commandDetail: "确认后会自动创建资料补充任务。",
  recovery: null,
};

describe("ResearchProcessRail", () => {
  let host: HTMLDivElement | null = null;
  let root: Root | null = null;

  afterEach(() => {
    if (root) {
      act(() => root?.unmount());
      root = null;
    }
    host?.remove();
    host = null;
  });

  function renderRail(
    selectedNodeId: string | null = "hf_generation",
    lang: "zh" | "en" = "zh",
    options: { graph?: WorkflowLayoutInput; nextAction?: HypothesisFirstNextAction } = {},
  ) {
    const onSelectNode = vi.fn();
    const onNavigateCurrent = vi.fn();
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    act(() => {
      root?.render(
        <ResearchProcessRail
          lang={lang}
          graph={options.graph ?? graph}
          selectedNodeId={selectedNodeId}
          runtimeCurrentNodeIds={["source_finding"]}
          nextAction={options.nextAction ?? nextAction}
          onSelectNode={onSelectNode}
          onNavigateCurrent={onNavigateCurrent}
        />,
      );
    });
    return { onSelectNode, onNavigateCurrent };
  }

  it("shows the current task, stage directory, and node status", () => {
    renderRail();

    expect(document.querySelector('[data-testid="research-process-rail"]')).toBeTruthy();
    expect(document.querySelector('[data-testid="research-process-rail-current"]')?.textContent).toContain("第 1 轮讨论·评审");
    expect(document.querySelector('[data-testid="research-process-rail-stage-hypothesis_first"]')?.textContent).toContain("假说先行");
    expect(document.querySelector('[data-testid="research-process-rail-node-source_finding"]')?.textContent).toContain("运行位置");
  });

  it("keeps selected history separate from the current task", () => {
    const { onNavigateCurrent, onSelectNode } = renderRail("hf_generation");

    const selected = document.querySelector<HTMLButtonElement>('[data-testid="research-process-rail-node-hf_generation"]');
    const current = document.querySelector<HTMLButtonElement>('[data-testid="research-process-rail-node-hf_meeting_1"]');
    expect(selected?.getAttribute("aria-pressed")).toBe("true");
    expect(selected?.getAttribute("aria-current")).toBeNull();
    expect(current?.getAttribute("aria-pressed")).toBe("false");
    expect(current?.getAttribute("aria-current")).toBe("step");
    expect(document.querySelector('[data-testid="research-process-rail-current"]')?.textContent).toContain("第 1 轮讨论·评审");

    act(() => {
      selected?.click();
      document.querySelector<HTMLButtonElement>('[data-testid="research-process-rail-current-action"]')?.click();
    });
    expect(onSelectNode).toHaveBeenCalledWith("hf_generation");
    expect(onNavigateCurrent).toHaveBeenCalledWith("hf_meeting_1");
  });

  it("localizes the rail chrome and known workflow nodes", () => {
    renderRail("hf_generation", "en");

    expect(document.querySelector('[data-testid="research-process-rail"]')?.getAttribute("aria-label"))
      .toBe("Research stages and tasks");
    expect(document.querySelector('[data-testid="research-process-rail-current"]')?.textContent)
      .toContain("Current task");
    expect(document.querySelector('[data-testid="research-process-rail-stage-knowledge_collection"]')?.textContent)
      .toContain("Knowledge collection");
    expect(document.querySelector('[data-testid="research-process-rail-node-source_finding"]')?.textContent)
      .toContain("Source finding");
    expect(document.body.textContent).not.toContain("研究阶段");
  });

  it("uses a distinct English description without leaking Chinese graph copy", () => {
    const englishGraph: WorkflowLayoutInput = {
      ...graph,
      stages: [graph.stages[1]],
      nodes: [graph.nodes[2]],
    };
    renderRail(null, "en", {
      graph: englishGraph,
      nextAction: {
        ...nextAction,
        targetNodeId: "source_finding",
        navigationLabel: "Source finding",
        commandDetail: "Review the source-finding task.",
      },
    });

    const node = document.querySelector<HTMLButtonElement>('[data-testid="research-process-rail-node-source_finding"]');
    const title = node?.querySelector("strong")?.textContent;
    const description = node?.querySelector("small")?.textContent;
    expect(title).toBe("Source finding");
    expect(description).toBe("Find relevant sources");
    expect(description).not.toBe(title);
    expect(description).not.toMatch(/[\u4e00-\u9fff]/);
    expect(document.body.textContent).not.toMatch(/[\u4e00-\u9fff]/);
  });

  it("renders a safe empty state before the workflow graph is available", () => {
    const onSelectNode = vi.fn();
    const onNavigateCurrent = vi.fn();
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    act(() => {
      root?.render(
        <ResearchProcessRail
          lang="zh"
          graph={null}
          selectedNodeId={null}
          runtimeCurrentNodeIds={[]}
          nextAction={{ stage: "no_run", targetNodeId: null, navigationLabel: "选择题目开始研究", recovery: null }}
          onSelectNode={onSelectNode}
          onNavigateCurrent={onNavigateCurrent}
        />,
      );
    });

    expect(document.querySelector('[data-testid="research-process-rail"]')).toBeTruthy();
    expect(document.querySelector('[data-testid="research-process-rail-stages"]')).toBeNull();
    expect(document.body.textContent).toContain("流程定义加载后");
  });
});
