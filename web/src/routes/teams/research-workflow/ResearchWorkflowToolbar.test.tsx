import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { queryKeys } from "../../../api/queryKeys";
import { ResearchWorkflowToolbar } from "./ResearchWorkflowToolbar";

function renderToolbar(props: React.ComponentProps<typeof ResearchWorkflowToolbar>, language: "zh" | "en" = "zh") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  queryClient.setQueryData(queryKeys.configPublic(), { language });
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ResearchWorkflowToolbar {...props} />
    </QueryClientProvider>,
  );
}

const BASE_PROPS = {
  teamName: "科研团队",
  questionId: "SCI-096",
  runStatus: "",
  nextAction: "创建运行",
  streamState: "idle",
  runOptions: [],
  panel: "node",
  hasRuntimeNode: false,
  createDisabled: false,
  onSelectRun: () => {},
  onOpenPanel: () => {},
  onJumpToRuntime: () => {},
} satisfies Partial<React.ComponentProps<typeof ResearchWorkflowToolbar>>;

describe("ResearchWorkflowToolbar", () => {
  it("keeps create-run available and shows a readable status instead of the run id", () => {
    const empty = renderToolbar({
      ...BASE_PROPS,
      runId: "",
      onSelectRun: vi.fn(),
      onOpenPanel: vi.fn(),
      onJumpToRuntime: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>);
    expect(empty).toContain("创建运行");
    expect(empty).toContain("SCI-096");
    expect(empty).toContain("科研团队");
    expect(empty).not.toContain('data-vui="research-next-action"');

    const running = renderToolbar({
      ...BASE_PROPS,
      runId: "run-5e4fbe6e18f2",
      runStatus: "waiting_human",
      nextAction: "资料寻找",
      streamState: "connected",
      runOptions: [
        { runId: "run-5e4fbe6e18f2", label: "第 1 次运行 · 资料寻找 · 等待确认" },
      ],
      hasRuntimeNode: true,
      onSelectRun: vi.fn(),
      onOpenPanel: vi.fn(),
      onJumpToRuntime: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>);
    expect(running).toContain("等待确认");
    expect(running).toContain("实时");
    expect(running).toContain("下一步：资料寻找");
    expect(running).toContain("第 1 次运行");
    expect(running).not.toContain("waiting_human");
    // 下一步在运行中渲染为可点击按钮，吸收原「当前节点」跳转入口
    expect(running).toContain('data-vui="research-next-action"');
    expect(running).not.toContain("当前节点");
  });

  it("keeps the create-run entry reachable while a run is selected", () => {
    const running = renderToolbar({
      ...BASE_PROPS,
      runId: "run-5e4fbe6e18f2",
      runStatus: "running",
      nextAction: "",
      streamState: "connected",
      runOptions: [
        { runId: "run-5e4fbe6e18f2", label: "第 1 次运行" },
      ],
      onSelectRun: vi.fn(),
      onOpenPanel: vi.fn(),
      onJumpToRuntime: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>);
    expect(running).toContain("新建运行");
    expect(running).toContain("第 1 次运行");
  });

  it("renders English chrome when the shell language is en", () => {
    const running = renderToolbar({
      ...BASE_PROPS,
      runId: "run-1",
      runStatus: "running",
      nextAction: "",
      streamState: "reconnecting",
      runOptions: [{ runId: "run-1", label: "Run 1" }],
      onSelectRun: vi.fn(),
      onOpenPanel: vi.fn(),
      onJumpToRuntime: vi.fn(),
    } as React.ComponentProps<typeof ResearchWorkflowToolbar>, "en");
    expect(running).toContain("New run");
    expect(running).toContain("Reconnecting");
    expect(running).toContain("Timeline");
  });
});
