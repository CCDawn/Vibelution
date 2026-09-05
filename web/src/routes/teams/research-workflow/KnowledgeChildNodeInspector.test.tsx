/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { expect, it, vi } from "vitest";
import type { CommandOffer } from "../../../api/types/research-workflow/commands";

const mocks = vi.hoisted(() => ({
  api: vi.fn(), refresh: vi.fn(), retry: vi.fn(), readRun: vi.fn(), readNode: vi.fn(),
}));
vi.mock("../../../api/research-workflow/commands", () => ({ submitResearchWorkflowCommandOffer: mocks.api }));
vi.mock("./useResearchWorkflowRun", () => ({ useResearchWorkflowRun: mocks.readRun }));
vi.mock("./useNodeDetailState", () => ({ useNodeDetailState: mocks.readNode }));
vi.mock("./ResearchProcessNodeInspector", () => ({
  ResearchProcessNodeInspector: (props: { onOffer: (offer: CommandOffer) => Promise<void> }) =>
    <button onClick={() => void props.onOffer(offer).catch(() => undefined)}>retry child</button>,
}));
import { KnowledgeChildNodeInspector } from "./KnowledgeChildNodeInspector";
const offer = { command: "retry_node", nodeId: "source_finding", available: true,
  label: "Retry", reasonCode: "ready", blockerIds: [], payload: {},
  idempotencyKey: "child-retry", expectedRunVersion: 2 } satisfies CommandOffer;

it.each([false, true])("submits child identity and refreshes after command failure=%s", async (fails) => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.clearAllMocks();
  mocks.readRun.mockReturnValue({ lastSequence: 12, run: {}, refresh: mocks.refresh });
  mocks.readNode.mockReturnValue({ state: { kind: "ready", detail: {} }, retry: mocks.retry });
  if (fails) mocks.api.mockRejectedValueOnce(new Error("node_not_ready"));
  else mocks.api.mockResolvedValueOnce({});
  const container = document.createElement("div");
  const root = createRoot(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  try {
    await act(async () => root.render(<QueryClientProvider client={client}>
      <KnowledgeChildNodeInspector teamId="research-team" runId="knowledge-child" nodeId="source_finding" lang="zh" />
    </QueryClientProvider>));
    await act(async () => container.querySelector("button")!.click());
    expect(mocks.readNode).toHaveBeenCalledWith("research-team", "knowledge-child", "source_finding", 12);
    expect(mocks.api).toHaveBeenCalledWith({ teamId: "research-team", runId: "knowledge-child", offer });
    expect(mocks.refresh).toHaveBeenCalledOnce();
    expect(mocks.retry).toHaveBeenCalledOnce();
  } finally {
    await act(async () => root.unmount());
    client.clear();
  }
});
