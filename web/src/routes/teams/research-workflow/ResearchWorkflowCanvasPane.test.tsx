/** @vitest-environment happy-dom */
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { queryKeys } from "../../../api/queryKeys";
import type { WorkflowLayoutInput } from "../../../components/vui";
import { ResearchWorkflowCanvasPane } from "./ResearchWorkflowCanvasPane";

function makeQueryClient(language?: "zh" | "en") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  queryClient.setQueryDefaults(queryKeys.configPublic(), { staleTime: Number.POSITIVE_INFINITY });
  queryClient.setQueryData(queryKeys.configPublic(), { language: language ?? "zh" });
  return queryClient;
}

async function renderPane(props: {
  graph?: WorkflowLayoutInput | null;
  error?: string | null;
  language?: "zh" | "en";
}) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <QueryClientProvider client={makeQueryClient(props.language)}>
        <ResearchWorkflowCanvasPane
          graph={props.graph ?? null}
          selectedNodeId={null}
          runtimeCurrentNodeIds={[]}
          error={props.error ?? null}
          onSelectNode={() => undefined}
        />
      </QueryClientProvider>,
    );
  });
  return { container, root };
}

describe("ResearchWorkflowCanvasPane", () => {
  let root: Root | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => root?.unmount());
      root = null;
    }
    document.body.innerHTML = "";
  });

  it("shows the loading state while the workflow definition is missing", async () => {
    const rendered = await renderPane({ graph: null });
    root = rendered.root;
    expect(rendered.container.textContent).toContain("加载流程定义");
    expect(rendered.container.querySelector('[role="alert"]')).toBeNull();
  });

  it("follows the shell language for the loading state", async () => {
    const rendered = await renderPane({ graph: null, language: "en" });
    root = rendered.root;
    expect(rendered.container.textContent).toContain("Loading workflow definition");
  });

  it("surfaces the workspace error inline with an alert role", async () => {
    const rendered = await renderPane({ graph: null, error: "快照加载失败，请重试" });
    root = rendered.root;
    const alert = rendered.container.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain("快照加载失败，请重试");
  });

  it("clears the inline error once the workspace recovers", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    const queryClient = makeQueryClient();
    const renderWithError = (error: string | null) => (
      <QueryClientProvider client={queryClient}>
        <ResearchWorkflowCanvasPane
          graph={null}
          selectedNodeId={null}
          runtimeCurrentNodeIds={[]}
          error={error}
          onSelectNode={() => undefined}
        />
      </QueryClientProvider>
    );
    await act(async () => {
      root?.render(renderWithError("运行事件流中断"));
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("运行事件流中断");

    await act(async () => {
      root?.render(renderWithError(null));
    });
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });
});
