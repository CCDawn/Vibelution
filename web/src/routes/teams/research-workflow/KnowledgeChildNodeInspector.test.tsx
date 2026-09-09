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

// 缺陷㉑: a 412-rejected offer must surface the structured blockers to the
// operator instead of failing silently; the message mirrors what fetchJson
// builds from `detail.blockers` (title + detail, Chinese original).
it("surfaces 412 command blockers with retry and clear actions", async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.clearAllMocks();
  mocks.readRun.mockReturnValue({ lastSequence: 12, run: {}, refresh: mocks.refresh });
  mocks.readNode.mockReturnValue({ state: { kind: "ready", detail: {} }, retry: mocks.retry });
  mocks.api.mockRejectedValueOnce(Object.assign(
    new Error("节点尚未就绪（阻塞项：上游交接未接受：Handoff ho-abc123 状态为 ready）"),
    { name: "FetchJsonHttpError", status: 412, code: "node_not_ready" },
  ));
  const container = document.createElement("div");
  const root = createRoot(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const surface = () => container.querySelector('[data-testid="knowledge-child-command-error"]');
  const buttonByText = (text: string) => [...container.querySelectorAll("button")]
    .find((node) => node.textContent?.trim() === text);
  try {
    await act(async () => root.render(<QueryClientProvider client={client}>
      <KnowledgeChildNodeInspector teamId="research-team" runId="knowledge-child" nodeId="source_finding" lang="zh" />
    </QueryClientProvider>));
    await act(async () => container.querySelector("button")!.click());
    expect(surface()).not.toBeNull();
    expect(surface()!.textContent).toContain("上游交接未接受");
    expect(surface()!.textContent).toContain("ho-abc123");
    // Retry resubmits the last offer and the surface stays closed on success.
    mocks.api.mockResolvedValueOnce({});
    await act(async () => buttonByText("重试命令")!.click());
    expect(mocks.api).toHaveBeenCalledTimes(2);
    expect(surface()).toBeNull();
    // A fresh 412 rejection re-opens the surface; clear hides it without
    // resubmitting.
    mocks.api.mockRejectedValueOnce(Object.assign(
      new Error("节点尚未就绪（阻塞项：上游交接未接受：Handoff ho-abc123 状态为 ready）"),
      { name: "FetchJsonHttpError", status: 412, code: "node_not_ready" },
    ));
    await act(async () => container.querySelector("button")!.click());
    expect(surface()).not.toBeNull();
    await act(async () => buttonByText("清除")!.click());
    expect(surface()).toBeNull();
    expect(mocks.api).toHaveBeenCalledTimes(3);
  } finally {
    await act(async () => root.unmount());
    client.clear();
  }
});
