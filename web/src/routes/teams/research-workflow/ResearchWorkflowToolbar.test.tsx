import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { ResearchWorkflowToolbar } from "./ResearchWorkflowToolbar";

describe("ResearchWorkflowToolbar", () => {
  it("keeps create-run available and shows a readable status instead of the run id", () => {
    const empty = renderToStaticMarkup(
      <ResearchWorkflowToolbar
        teamName="科研团队"
        questionId="SCI-096"
        runId=""
        runStatus=""
        nextAction="创建运行"
        streamState="idle"
        runOptions={[]}
        panel="node"
        hasRuntimeNode={false}
        createDisabled={false}
        onSelectRun={vi.fn()}
        onOpenPanel={vi.fn()}
        onJumpToRuntime={vi.fn()}
      />,
    );
    expect(empty).toContain("创建运行");
    expect(empty).toContain("SCI-096");
    expect(empty).toContain("科研团队");

    const running = renderToStaticMarkup(
      <ResearchWorkflowToolbar
        teamName="科研团队"
        questionId="SCI-096"
        runId="run-5e4fbe6e18f2"
        runStatus="waiting_human"
        nextAction="资料寻找"
        streamState="connected"
        runOptions={[
          { runId: "run-5e4fbe6e18f2", label: "第 1 次运行 · 资料寻找 · 等待确认" },
        ]}
        panel="node"
        hasRuntimeNode
        createDisabled={false}
        onSelectRun={vi.fn()}
        onOpenPanel={vi.fn()}
        onJumpToRuntime={vi.fn()}
      />,
    );
    expect(running).toContain("等待确认");
    expect(running).toContain("实时");
    expect(running).toContain("下一步：资料寻找");
    expect(running).toContain("第 1 次运行");
    expect(running).not.toContain("waiting_human");
  });
});
