/**
 * P1-4/P1-5 node-render contracts (M level, static markup).
 *
 * Renders each workflow node component via renderToStaticMarkup with a mocked
 * @xyflow/react (Handle/Position stubbed) — no DOM measurement, no React Flow
 * internals. Asserts the visual-data contract:
 *  - data-* attributes (kind/status/current/selected) reach the DOM;
 *  - status labels, attempt chips, agent binding and pending-human subtitles;
 *  - decision exposes its four fixed source handles;
 *  - start/end handle polarity (start: no target, end: no source);
 *  - stage region is presentation-only: never focusable/selectable.
 */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { NodeProps } from "@xyflow/react";

vi.mock("@xyflow/react", async () => {
  const React = (await import("react")).default;
  const Position = { Left: "left", Right: "right", Top: "top", Bottom: "bottom" };
  return {
    Position,
    Handle: ({ type, position, id, style }: { type?: string; position?: string; id?: string; style?: { top?: string; left?: string } }) =>
      React.createElement("span", {
        "data-handle": `${type}:${position}`,
        "data-handle-id": id ?? "",
        "data-snap": style?.top ?? style?.left ?? "",
      }),
  };
});

import { WorkflowAgentTaskNode } from "./WorkflowAgentTaskNode";
import { WorkflowDecisionNode } from "./WorkflowDecisionNode";
import { WorkflowHumanGateNode } from "./WorkflowHumanGateNode";
import { workflowHandleSideOffset } from "./WorkflowNodeChrome";
import { WorkflowStageRegionNode } from "./WorkflowStageRegionNode";
import { WorkflowStartEndNode } from "./WorkflowStartEndNode";
import { WorkflowSystemTaskNode } from "./WorkflowSystemTaskNode";

function renderNode(
  Component: (props: NodeProps) => ReturnType<typeof WorkflowAgentTaskNode>,
  data: Record<string, unknown>,
  extra: Partial<NodeProps> = {},
): string {
  const props = { id: "n1", data, selected: false, ...extra } as NodeProps;
  return renderToStaticMarkup(<Component {...props} />);
}

function countHandles(markup: string, id?: string): number {
  const pattern = id
    ? new RegExp(`data-handle="(?:source|target):(?:left|right|top|bottom)"[^>]*data-handle-id="${id}"`, "g")
    : /data-handle="(source|target):(left|right|top|bottom)"/g;
  const matches = markup.match(pattern);
  return matches ? matches.length : 0;
}

describe("WorkflowAgentTaskNode render (P1-4)", () => {
  it("propagates visual data attributes, status label and runtime-current state", () => {
    const markup = renderNode(WorkflowAgentTaskNode, {
      label: "文献调研",
      status: "running",
      isRuntimeCurrent: true,
    });
    expect(markup).toContain('data-vui="workflow-task-node"');
    expect(markup).toContain('data-visual-kind="agent_task"');
    expect(markup).toContain('data-status="running"');
    expect(markup).toContain('data-current="true"');
    expect(markup).toContain('data-selected="false"');
    expect(markup).toContain("文献调研");
    expect(markup).toContain("运行中");
  });

  it("surfaces selected state, agent binding and attempt chip", () => {
    const markup = renderNode(
      WorkflowAgentTaskNode,
      { label: "实验设计", status: "succeeded", primaryAgentId: "agent-x", attempt: 3 },
      { selected: true },
    );
    expect(markup).toContain('data-selected="true"');
    expect(markup).toContain("agent-x");
    expect(markup).toContain("#3");
    expect(markup).toContain("Agent：agent-x");
    expect(markup).toContain("已完成");
  });

  it("falls back to 未绑定 when no agent is bound", () => {
    const markup = renderNode(WorkflowAgentTaskNode, { label: "执行", status: "pending" });
    expect(markup).toContain("未绑定");
    expect(markup).toContain("待运行");
  });

  it("uses the approved module card hierarchy in serpentine mode", () => {
    const markup = renderNode(WorkflowAgentTaskNode, {
      label: "协议设计",
      status: "ready",
      primaryAgentId: "agent-technical-id",
      primaryRoleKey: "experiment_planner",
      description: "冻结变量、数据切分、预算和停止条件。",
      layoutMode: "serpentine",
    });
    expect(markup).toContain('data-layout-mode="serpentine"');
    expect(markup).toContain("Agent 任务");
    expect(markup).toContain("实验规划 · Agent 已绑定");
    expect(markup).toContain("size-11");
    expect(markup).toContain("data-status-badge");
    expect(markup).not.toContain("冻结变量、数据切分、预算和停止条件。");
    expect(markup).not.toContain(">agent-technical-id<");
    expect(markup).not.toContain("text-[8px]");
    expect(markup).not.toContain("text-[8.5px]");
  });
});

describe("WorkflowHumanGateNode render (P1-4)", () => {
  it("marks a pending human task with the waiting subtitle", () => {
    const markup = renderNode(WorkflowHumanGateNode, {
      label: "人工确认",
      status: "waiting_human",
      hasPendingHumanTask: true,
    });
    expect(markup).toContain('data-visual-kind="human_gate"');
    expect(markup).toContain("需人工确认");
    expect(markup).toContain("等待人工");
    expect(markup).toContain("人工");
  });

  it("uses the neutral subtitle without a pending task", () => {
    const markup = renderNode(WorkflowHumanGateNode, { label: "门禁", status: "ready" });
    expect(markup).toContain("人工门禁");
    expect(markup).not.toContain("需人工确认");
  });

  it("prefers description subtitle on serpentine human gates", () => {
    const markup = renderNode(WorkflowHumanGateNode, {
      label: "确认候选",
      status: "waiting_human",
      hasPendingHumanTask: true,
      description: "等待人工确认闭环",
      layoutMode: "serpentine",
    });
    expect(markup).toContain("等待人工确认闭环");
    expect(markup).not.toContain("角色待确认 · 待确认");
  });
});

describe("WorkflowDecisionNode render (P1-4)", () => {
  it("exposes the real outgoing outcome handles from sourceHandleIds", () => {
    const markup = renderNode(WorkflowDecisionNode, {
      label: "结果判定",
      status: "running",
      sourceHandleIds: ["rerun", "promote", "rollback", "stop"],
    });
    expect(markup).toContain('data-visual-kind="decision"');
    expect(markup).toContain("条件分支");
    expect(markup).toContain("分支");
    expect(countHandles(markup, "rerun")).toBe(1);
    expect(countHandles(markup, "promote")).toBe(1);
    expect(countHandles(markup, "rollback")).toBe(1);
    expect(countHandles(markup, "stop")).toBe(1);
    expect(countHandles(markup)).toBe(5);
  });

  it("uses outcome language instead of 未绑定 on serpentine decision cards", () => {
    const markup = renderNode(WorkflowDecisionNode, {
      label: "迭代规划",
      status: "pending",
      primaryRoleKey: "iteration_planner",
      layoutMode: "serpentine",
      sourceHandleIds: ["rerun", "promote", "rollback", "stop"],
    });
    expect(markup).toContain("晋升 / 回滚 / 停止");
    expect(markup).not.toContain("迭代规划 · 未绑定");
    expect(markup).not.toContain("角色待确认 · 未绑定");
  });

  it("renders no source handles when the run has no current-run decision edges", () => {
    const markup = renderNode(WorkflowDecisionNode, {
      label: "结果判定",
      status: "running",
      sourceHandleIds: [],
    });
    expect(countHandles(markup)).toBe(1);
  });

  it("places decision handles on the ELK port sides (P1-4)", () => {
    const markup = renderNode(WorkflowDecisionNode, {
      label: "结果判定",
      status: "running",
      sourceHandleIds: ["rerun", "promote", "rollback", "stop"],
      portSides: {
        source: {
          rerun: "WEST",
          promote: "SOUTH",
          rollback: "SOUTH",
          stop: "SOUTH",
        },
        target: {},
      },
    });
    expect(markup).toContain('data-handle="source:left"');
    // Three of the four outcomes share the SOUTH rail; only rerun sits WEST.
    expect(markup.match(/data-handle="source:bottom"/g)?.length).toBe(3);
  });

  it("mirrors ordinary node source/target handles to port sides (P1-4)", () => {
    const markup = renderNode(WorkflowAgentTaskNode, {
      label: "执行",
      status: "pending",
      portSides: {
        source: { "out:east:node": "EAST" },
        target: { "in:west:node": "WEST" },
      },
    });
    expect(markup).toContain('data-handle="target:left"');
    expect(markup).toContain('data-handle="source:right"');
  });

  it("gives ordinary outgoing edges unique handles on relative snap magnets", () => {
    const markup = renderNode(WorkflowAgentTaskNode, {
      label: "执行",
      status: "pending",
      portSides: {
        source: { "out:east:one": "EAST", "out:east:two": "EAST" },
        target: {},
        sourceAnchor: { "out:east:one": 0.25, "out:east:two": 0.75 },
      },
    });
    expect(countHandles(markup, "out:east:one")).toBe(1);
    expect(countHandles(markup, "out:east:two")).toBe(1);
    expect(markup).toContain('data-snap="25%"');
    expect(markup).toContain('data-snap="75%"');
    expect(workflowHandleSideOffset(0, 2, "EAST")).toEqual({ top: "33.3333%" });
    expect(workflowHandleSideOffset(1, 2, "EAST")).toEqual({ top: "66.6667%" });
  });

  it("shows unused serpentine magnets on a used side so the edge can change snap point", () => {
    const markup = renderNode(WorkflowAgentTaskNode, {
      label: "执行",
      status: "pending",
      layoutMode: "serpentine",
      portSides: {
        source: { "out:east:one": "EAST" },
        target: {},
        sourceAnchor: { "out:east:one": 0.5 },
      },
    });
    expect(markup).toContain('data-workflow-snap="EAST"');
    expect(markup).toContain('data-snap-fraction="0.25"');
    expect(markup).toContain('data-snap-fraction="0.75"');
    expect(markup).not.toContain('data-snap-fraction="0.5"');
  });

  it("mirrors every real ELK target port as an id-bearing handle (P1-4)", () => {
    const markup = renderNode(WorkflowHumanGateNode, {
      label: "门禁",
      status: "ready",
      portSides: {
        source: {},
        target: {
          "in:north": "NORTH",
          "in:promote": "NORTH",
          "feedback:in": "EAST",
        },
      },
    });
    expect(countHandles(markup, "in:north")).toBe(1);
    expect(countHandles(markup, "in:promote")).toBe(1);
    expect(countHandles(markup, "feedback:in")).toBe(1);
    expect(markup).toContain('data-handle="target:top"');
    expect(markup).toContain('data-handle="target:right"');
  });
});

describe("WorkflowSystemTaskNode render (P1-4)", () => {
  it("renders the system subtitle and status", () => {
    const markup = renderNode(WorkflowSystemTaskNode, { label: "文档生成", status: "failed" });
    expect(markup).toContain('data-visual-kind="system_task"');
    expect(markup).toContain("系统执行");
    expect(markup).toContain("失败");
  });

  it("uses 受控执行 on serpentine system cards instead of 未绑定", () => {
    const markup = renderNode(WorkflowSystemTaskNode, {
      label: "受控运行",
      status: "pending",
      layoutMode: "serpentine",
    });
    expect(markup).toContain("受控执行");
    expect(markup).not.toContain("角色待确认 · 未绑定");
  });
});

describe("WorkflowStartEndNode render (P1-4)", () => {
  it("start node has no target handle and only a source handle", () => {
    const markup = renderNode(WorkflowStartEndNode, {
      label: "启动",
      visualKind: "start",
      status: "succeeded",
    });
    expect(markup).toContain("起点");
    expect(countHandles(markup)).toBe(1);
    expect(markup).toContain('data-handle="source:right"');
    expect(markup).not.toContain('data-handle="target:left"');
  });

  it("start node mirrors an assigned target port for display-layer incoming edges", () => {
    const markup = renderNode(WorkflowStartEndNode, {
      label: "资料寻找",
      visualKind: "start",
      status: "pending",
      portSides: { source: {}, target: { "in:west": "WEST" } },
    });
    expect(countHandles(markup, "in:west")).toBe(1);
    expect(markup).toContain('data-handle="target:left"');
  });

  it("end node has no source handle and only a target handle", () => {
    const markup = renderNode(WorkflowStartEndNode, {
      label: "完成",
      visualKind: "end",
      status: "succeeded",
    });
    expect(markup).toContain("终点");
    expect(countHandles(markup)).toBe(1);
    expect(markup).toContain('data-handle="target:left"');
    expect(markup).not.toContain('data-handle="source:right"');
  });
});

describe("WorkflowStageRegionNode render (P1-5)", () => {
  it("renders tone and 1-based stage index as presentation-only", () => {
    const markup = renderNode(WorkflowStageRegionNode, {
      label: "知识搜集",
      stageTone: "active",
      stageIndex: 0,
    });
    expect(markup).toContain('data-vui="workflow-stage-region"');
    expect(markup).toContain('data-stage-tone="active"');
    expect(markup).toContain("知识搜集");
    expect(markup).toContain(">1<");
  });

  it("does not paint a serpentine stage heading or progress counter", () => {
    const markup = renderNode(WorkflowStageRegionNode, {
      label: "实验设计",
      stageTone: "attention",
      stageIndex: 1,
      taskCount: 5,
      completedCount: 2,
      layoutMode: "serpentine",
    });
    expect(markup).toContain('data-layout-mode="serpentine"');
    expect(markup).toContain('data-vui="workflow-stage-region"');
    expect(markup).not.toContain("实验设计");
    expect(markup).not.toContain("/ 5");
    expect(markup).not.toContain("需关注");
  });

  it("removes the large serpentine stage background and heading", () => {
    const idle = renderNode(WorkflowStageRegionNode, {
      label: "知识搜集",
      stageTone: "idle",
      stageIndex: 0,
      layoutMode: "serpentine",
    });
    expect(idle).not.toContain("linear-gradient");
    expect(idle).not.toContain("accent-cool)_8%,var(--vui-surface-workspace)");
    expect(idle).not.toContain("accent-cool)_10%,var(--vui-border-subtle)");
    expect(idle).not.toContain("border-dashed");
    expect(idle).not.toContain("cursor-grab");
    expect(idle).not.toContain("知识搜集");
  });

  it("lifts serpentine task cards with an opaque panel and elevation token", () => {
    const markup = renderNode(WorkflowAgentTaskNode, {
      label: "协议设计",
      status: "ready",
      layoutMode: "serpentine",
    });
    expect(markup).toContain("bg-[var(--vui-surface-panel)]");
    expect(markup).toContain("shadow-[var(--vui-elevation-2)]");
    expect(markup).not.toContain("rgba(15,23,42,0.05)");
  });

  it("is never focusable or selectable (no role/tabIndex/selection attributes)", () => {
    const markup = renderNode(WorkflowStageRegionNode, {
      label: "知识搜集",
      stageTone: "idle",
      stageIndex: 2,
    });
    expect(markup).not.toContain("role=");
    expect(markup).not.toContain("tabindex");
    expect(markup).not.toContain("data-selected");
    expect(markup).toContain(">3<");
  });
});
