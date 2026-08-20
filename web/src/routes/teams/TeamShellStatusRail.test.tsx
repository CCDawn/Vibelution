/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TeamShellStatusRail } from "./TeamShellStatusRail";
import type { TeamShellStatusNode, TeamShellStatusStage } from "./teamShellStatusModel";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const stages: TeamShellStatusStage[] = [
  { id: "knowledge_collection", title: "资料寻找", status: "进行中", tone: "active" },
  { id: "experiment", title: "实验设计", status: "未开始", tone: "idle" },
];

const nodes: TeamShellStatusNode[] = [
  { id: "node-finder", label: "资料寻找", agent: "白望舒", status: "已绑定", statusTone: "success" },
  { id: "node-extract", label: "资料提炼", agent: "顾言初", status: "未绑定", statusTone: "warning" },
];

describe("TeamShellStatusRail", () => {
  let host: HTMLDivElement | null = null;
  let root: Root | null = null;

  afterEach(() => {
    if (root) {
      act(() => root?.unmount());
    }
    host?.remove();
    host = null;
    root = null;
  });

  function renderRail(selectedNodeId: string | null = null) {
    const onCta = vi.fn();
    const onSelectNode = vi.fn();
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    act(() => {
      root?.render(
        <TeamShellStatusRail
          lang="zh"
          nextTitle="继续知识搜集"
          nextBody="资料寻找还差 2 篇核心文献。"
          cta="继续知识搜集"
          stages={stages}
          nodes={nodes}
          selectedNodeId={selectedNodeId}
          onCta={onCta}
          onSelectNode={onSelectNode}
        />,
      );
    });
    return { onCta, onSelectNode };
  }

  it("shows next step, stages, and nodes instead of a team list", () => {
    renderRail();
    expect(document.querySelector('[data-testid="team-shell-status-rail"]')).toBeTruthy();
    expect(document.querySelector('[data-testid="status-rail-next"]')?.textContent).toContain("继续知识搜集");
    expect(document.querySelector('[data-testid="status-rail-stage-knowledge_collection"]')?.textContent).toContain("资料寻找");
    expect(document.body.textContent).not.toContain("搜索团队");
  });

  it("fires CTA and node selection", () => {
    const { onCta, onSelectNode } = renderRail();
    const cta = Array.from(document.querySelectorAll("button")).find((button) => button.textContent === "继续知识搜集");
    act(() => {
      cta?.click();
    });
    expect(onCta).toHaveBeenCalledTimes(1);
    act(() => {
      document.querySelector<HTMLButtonElement>('[data-testid="status-rail-node-node-finder"]')?.click();
    });
    expect(onSelectNode).toHaveBeenCalledWith("node-finder");
  });

  it("marks the selected node", () => {
    renderRail("node-finder");
    expect(document.querySelector('[data-testid="status-rail-node-node-finder"]')?.getAttribute("aria-pressed")).toBe("true");
    expect(document.querySelector('[data-testid="status-rail-node-node-extract"]')?.getAttribute("aria-pressed")).toBe("false");
  });
});
