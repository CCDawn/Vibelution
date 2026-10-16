import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { TeamCanvasNode } from "../../api/types";
import { TeamCanvasReadOnlyInspector } from "./TeamCanvasReadOnlyInspector";

const node = { id: "planner", label: "规划师", role: "planner", purpose: "需求规划", agentId: "agent-1", agentName: "规划师 Agent", status: "bound" } as TeamCanvasNode;
const render = (overrides: Partial<React.ComponentProps<typeof TeamCanvasReadOnlyInspector>> = {}) => renderToStaticMarkup(
  <TeamCanvasReadOnlyInspector lang="zh" node={node} functionLabel="需求规划" validationIssues={[]} {...overrides} />,
);

describe("TeamCanvasReadOnlyInspector", () => {
  it("shows one identity and role while keeping binding state distinct from execution", () => {
    const html = render();
    expect(html.match(/需求规划/g)).toHaveLength(1);
    expect(html).toContain("规划师</h3>");
    expect(html).not.toContain("规划师 Agent");
    expect(html).toContain("已绑定");
    expect(html).not.toContain("运行中");
  });
  it("retains a distinct assignee, purpose and validation failure", () => {
    const html = render({ node: { ...node, purpose: "确认键盘导航边界" }, agentName: "顾言初", validationIssues: [{ code: "missing-target", message: "连线目标不存在" }] });
    expect(html).toContain("顾言初");
    expect(html).toContain("确认键盘导航边界");
    expect(html).toContain("连线目标不存在");
  });
  it("keeps the empty-selection guidance and stale binding visible", () => {
    expect(render({ node: null })).toContain("选择一个节点查看详情");
    expect(render({ node: { ...node, status: "stale" } })).toContain('data-tone="warning"');
  });
});
