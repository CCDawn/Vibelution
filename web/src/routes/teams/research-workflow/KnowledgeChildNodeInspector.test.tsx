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

function detailWith(offers: CommandOffer[]) {
  return {
    state: { kind: "ready", detail: { runVersion: offers[0]?.expectedRunVersion ?? 2, commandOffers: offers } },
    retry: mocks.retry,
  };
}

/** Render (or re-render after mocks changed) one inspector instance. */
async function mountInspector(
  root: ReturnType<typeof createRoot>,
  container: HTMLElement,
  client: QueryClient,
  overrides: { nodeId?: string } = {},
) {
  await act(async () => root.render(<QueryClientProvider client={client}>
    <KnowledgeChildNodeInspector
      teamId="research-team"
      runId="knowledge-child"
      nodeId={overrides.nodeId ?? "source_finding"}
      lang="zh"
    />
  </QueryClientProvider>));
}

const surface = (container: HTMLElement) =>
  container.querySelector('[data-testid="knowledge-child-command-error"]');
const buttonByText = (container: HTMLElement, text: string) =>
  [...container.querySelectorAll("button")].find((node) => node.textContent?.trim() === text);

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
    await mountInspector(root, container, client);
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
// A06: the error-surface retry never replays the refused offer — it resolves
// the CURRENT offer for the same command identity from the refreshed detail.
it("412 rejection retries with the re-resolved newer offer, not the refused one", async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.clearAllMocks();
  mocks.readRun.mockReturnValue({ lastSequence: 12, run: {}, refresh: mocks.refresh });
  const staleOffer = { ...offer, idempotencyKey: "key-v1", expectedRunVersion: 2 };
  const refreshedOffer = { ...offer, idempotencyKey: "key-v2", expectedRunVersion: 3 };
  mocks.readNode.mockReturnValue({ state: { kind: "ready", detail: { commandOffers: [staleOffer] } }, retry: mocks.retry });
  mocks.api.mockRejectedValueOnce(Object.assign(
    new Error("节点尚未就绪（阻塞项：上游交接未接受：Handoff ho-abc123 状态为 ready）"),
    { name: "FetchJsonHttpError", status: 412, code: "node_not_ready" },
  ));
  const container = document.createElement("div");
  const root = createRoot(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  try {
    await mountInspector(root, container, client);
    await act(async () => container.querySelector("button")!.click());
    expect(surface(container)).not.toBeNull();
    expect(surface(container)!.textContent).toContain("上游交接未接受");
    expect(surface(container)!.textContent).toContain("ho-abc123");
    // The upstream refresh landed (v2 -> v3): the newest snapshot carries the
    // re-signed offer, and the retry must submit exactly that one.
    mocks.readNode.mockReturnValue(detailWith([refreshedOffer]));
    await mountInspector(root, container, client);
    mocks.api.mockResolvedValueOnce({});
    await act(async () => buttonByText(container, "重试命令")!.click());
    expect(mocks.api).toHaveBeenCalledTimes(2);
    const retryCall = mocks.api.mock.calls[1][0] as { offer: CommandOffer };
    expect(retryCall.offer.idempotencyKey).toBe("key-v2");
    expect(retryCall.offer.expectedRunVersion).toBe(3);
    expect(surface(container)).toBeNull();
  } finally {
    await act(async () => root.unmount());
    client.clear();
  }
});

// A06: when the re-resolved offer became unavailable (action undone), the
// surface shows the fresh reason instead of resubmitting a dead offer.
it("shows the new reason and disables retry when the re-resolved offer is unavailable", async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.clearAllMocks();
  mocks.readRun.mockReturnValue({ lastSequence: 12, run: {}, refresh: mocks.refresh });
  mocks.readNode.mockReturnValue({ state: { kind: "ready", detail: { commandOffers: [offer] } }, retry: mocks.retry });
  mocks.api.mockRejectedValueOnce(Object.assign(new Error("版本冲突"), {
    name: "FetchJsonHttpError", status: 412, code: "run_version_conflict",
  }));
  const container = document.createElement("div");
  const root = createRoot(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  try {
    await mountInspector(root, container, client);
    await act(async () => container.querySelector("button")!.click());
    mocks.readNode.mockReturnValue(detailWith([
      { ...offer, available: false, reasonCode: "node_already_succeeded" },
    ]));
    await mountInspector(root, container, client);
    expect(surface(container)).not.toBeNull();
    expect(surface(container)!.textContent).toContain("当前节点已完成");
    const retryButton = buttonByText(container, "重试命令")!;
    expect(retryButton).toBeTruthy();
    expect((retryButton as HTMLButtonElement).disabled).toBe(true);
    const callsBefore = mocks.api.mock.calls.length;
    await act(async () => retryButton.click());
    expect(mocks.api).toHaveBeenCalledTimes(callsBefore);
  } finally {
    await act(async () => root.unmount());
    client.clear();
  }
});

// A06: when the command no longer exists as an offer, there is no retry
// button — only the fresh explanation.
it("drops the retry action when the command is no longer offered", async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.clearAllMocks();
  mocks.readRun.mockReturnValue({ lastSequence: 12, run: {}, refresh: mocks.refresh });
  mocks.readNode.mockReturnValue({ state: { kind: "ready", detail: { commandOffers: [offer] } }, retry: mocks.retry });
  mocks.api.mockRejectedValueOnce(Object.assign(new Error("版本冲突"), {
    name: "FetchJsonHttpError", status: 412, code: "run_version_conflict",
  }));
  const container = document.createElement("div");
  const root = createRoot(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  try {
    await mountInspector(root, container, client);
    await act(async () => container.querySelector("button")!.click());
    mocks.readNode.mockReturnValue(detailWith([]));
    await mountInspector(root, container, client);
    expect(surface(container)).not.toBeNull();
    expect(buttonByText(container, "重试命令")).toBeFalsy();
    expect(surface(container)!.textContent).toContain("已不再提供");
  } finally {
    await act(async () => root.unmount());
    client.clear();
  }
});

// A06: a transport-level failure has an UNKNOWN outcome — the retry replays
// the SAME offer with its ORIGINAL idempotency key (never a second execution
// under a new key).
it("replays the original idempotency key when the outcome is unknown (network failure)", async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.clearAllMocks();
  mocks.readRun.mockReturnValue({ lastSequence: 12, run: {}, refresh: mocks.refresh });
  const refreshedOffer = { ...offer, idempotencyKey: "key-v2", expectedRunVersion: 3 };
  mocks.readNode.mockReturnValue({ state: { kind: "ready", detail: { commandOffers: [offer] } }, retry: mocks.retry });
  mocks.api.mockRejectedValueOnce(new TypeError("Failed to fetch"));
  const container = document.createElement("div");
  const root = createRoot(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  try {
    await mountInspector(root, container, client);
    await act(async () => container.querySelector("button")!.click());
    expect(surface(container)).not.toBeNull();
    // Even though a fresher offer snapshot exists after the refresh, the
    // unknown-outcome retry must probe with the ORIGINAL key.
    mocks.readNode.mockReturnValue(detailWith([refreshedOffer]));
    await mountInspector(root, container, client);
    mocks.api.mockResolvedValueOnce({});
    await act(async () => buttonByText(container, "重试命令")!.click());
    expect(mocks.api).toHaveBeenCalledTimes(2);
    const replayCall = mocks.api.mock.calls[1][0] as { offer: CommandOffer };
    expect(replayCall.offer).toEqual(offer);
  } finally {
    await act(async () => root.unmount());
    client.clear();
  }
});

// A06/缺陷㉑: switching nodes clears both the error surface and the retained
// failed command — no stale retry target survives a surface change.
it("clears the failed command when the selected node changes", async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.clearAllMocks();
  mocks.readRun.mockReturnValue({ lastSequence: 12, run: {}, refresh: mocks.refresh });
  mocks.readNode.mockReturnValue({ state: { kind: "ready", detail: { commandOffers: [offer] } }, retry: mocks.retry });
  mocks.api.mockRejectedValueOnce(Object.assign(new Error("版本冲突"), {
    name: "FetchJsonHttpError", status: 412, code: "run_version_conflict",
  }));
  const container = document.createElement("div");
  const root = createRoot(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  try {
    await mountInspector(root, container, client);
    await act(async () => container.querySelector("button")!.click());
    expect(surface(container)).not.toBeNull();
    mocks.readNode.mockReturnValue(detailWith([offer]));
    await mountInspector(root, container, client, { nodeId: "screening" });
    expect(surface(container)).toBeNull();
    expect(buttonByText(container, "重试命令")).toBeFalsy();
  } finally {
    await act(async () => root.unmount());
    client.clear();
  }
});
