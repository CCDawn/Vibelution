// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchPersonalAssistantOverview } from "../../api/personalAssistant";
import type { PersonalAssistantOverview } from "../../api/types/personalAssistant";
import { HumanAttentionNotifier } from "./HumanAttentionNotifier";

vi.mock("../../api/personalAssistant", () => ({ fetchPersonalAssistantOverview: vi.fn() }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

type AttentionRow = PersonalAssistantOverview["attention"][number];

function overviewWith(attention: AttentionRow[]): PersonalAssistantOverview {
  return {
    generatedAt: "2026-10-18T00:00:00Z",
    counts: { agents: 0, sessions: 0, running: 0, waiting: attention.length, failed: 0 },
    agents: [],
    sessions: [],
    attention,
  };
}

let notifyHumanAttention: ReturnType<typeof vi.fn>;
let openedListener: ((payload: unknown) => void) | undefined;
let root: Root;
let container: HTMLDivElement;
let router: ReturnType<typeof createMemoryRouter>;

function Host() {
  const location = useLocation();
  return (
    <>
      <HumanAttentionNotifier />
      <output>{location.pathname}{location.search}</output>
    </>
  );
}

async function renderInto(target: Root) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    target.render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
  });
  await act(async () => new Promise(resolve => setTimeout(resolve, 20)));
}

async function mountNotifier() {
  await renderInto(root);
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  notifyHumanAttention = vi.fn().mockResolvedValue({ delivered: "assistant_window" });
  openedListener = undefined;
  vi.stubGlobal("vibelutionLauncher", {
    notifyHumanAttention,
    onHumanAttentionOpened: (callback: (payload: unknown) => void) => {
      openedListener = callback;
      return () => undefined;
    },
  });
  router = createMemoryRouter([{ path: "*", element: <Host /> }], { initialEntries: ["/agents"] });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

describe("main workbench human-attention trigger chain", () => {
  it("notifies unseen human-attention rows once with the contract payload", async () => {
    vi.mocked(fetchPersonalAssistantOverview).mockResolvedValue(overviewWith([
      { id: "kr-1", kind: "knowledge_review", title: "知识待复核", severity: "critical", body: "一条新知识", targetUrl: "/memory/knowledge" },
      { id: "approval-1", kind: "approval", title: "等待确认", sessionId: "s1" },
    ]));
    await mountNotifier();
    expect(notifyHumanAttention).toHaveBeenCalledTimes(1);
    expect(notifyHumanAttention).toHaveBeenCalledWith({
      id: "kr-1",
      kind: "knowledge_review",
      severity: "critical",
      title: "知识待复核",
      body: "一条新知识",
      targetUrl: "/memory/knowledge",
    });
  });

  it("does not re-notify across page refreshes (localStorage day dedup)", async () => {
    vi.mocked(fetchPersonalAssistantOverview).mockResolvedValue(
      overviewWith([{ id: "an-1", kind: "anomaly", title: "研究异常", severity: "high" }]),
    );
    await mountNotifier();
    expect(notifyHumanAttention).toHaveBeenCalledTimes(1);
    // Simulated refresh: new component instance + fresh query client, same localStorage.
    await act(async () => root.unmount());
    const nextContainer = document.createElement("div");
    document.body.appendChild(nextContainer);
    const nextRoot = createRoot(nextContainer);
    await renderInto(nextRoot);
    expect(notifyHumanAttention).toHaveBeenCalledTimes(1);
    await act(async () => nextRoot.unmount());
    nextContainer.remove();
  });

  it("skips silently when the launcher bridge is absent", async () => {
    vi.unstubAllGlobals();
    vi.mocked(fetchPersonalAssistantOverview).mockResolvedValue(
      overviewWith([{ id: "kr-2", kind: "knowledge_review", title: "知识", severity: "medium" }]),
    );
    await expect(mountNotifier()).resolves.toBeUndefined();
    expect(notifyHumanAttention).not.toHaveBeenCalled();
  });

  it("navigates the workbench on opened clicks: targetUrl wins, kind default as fallback", async () => {
    vi.mocked(fetchPersonalAssistantOverview).mockResolvedValue(
      overviewWith([{ id: "an-1", kind: "anomaly", title: "研究异常", severity: "high" }]),
    );
    await mountNotifier();
    const locationNow = () => router.state.location.pathname + router.state.location.search;
    // Unknown id without targetUrl: no navigation.
    await act(async () => openedListener?.({ id: "unknown-1" }));
    await act(async () => new Promise(resolve => setTimeout(resolve, 5)));
    expect(locationNow()).toBe("/agents");
    // Known id without targetUrl: kind default route.
    await act(async () => openedListener?.({ id: "an-1" }));
    await act(async () => new Promise(resolve => setTimeout(resolve, 5)));
    expect(locationNow()).toBe("/teams?researchView=workflow");
    // Explicit targetUrl wins.
    await act(async () => openedListener?.({ id: "an-1", targetUrl: "/memory/knowledge" }));
    await act(async () => new Promise(resolve => setTimeout(resolve, 5)));
    expect(locationNow()).toBe("/memory/knowledge");
  });
});
