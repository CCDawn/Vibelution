// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchPersonalAssistantHumanAttention } from "../../api/personalAssistant";
import { queryKeys } from "../../api/queryKeys";
import type { PersonalAssistantHumanAttentionResponse } from "../../api/types/personalAssistant";
import { HumanAttentionNotifier } from "./HumanAttentionNotifier";

vi.mock("../../api/personalAssistant", () => ({ fetchPersonalAssistantHumanAttention: vi.fn() }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

type AttentionRow = PersonalAssistantHumanAttentionResponse["humanAttention"][number];

function feedWith(humanAttention: AttentionRow[]): PersonalAssistantHumanAttentionResponse {
  return {
    humanAttention,
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

async function renderInto(target: Root, client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
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
  it("waits for source capability and leaves an explicitly retired affair unmarked", async () => {
    let finish!: (value: unknown) => void;
    const capability = vi.fn(() => new Promise(resolve => { finish = resolve; }));
    notifyHumanAttention.mockResolvedValue({ delivered: "source_retired" });
    vi.stubGlobal("vibelutionLauncher", { notifyHumanAttention, getHumanAttentionCapabilities: capability });
    vi.mocked(fetchPersonalAssistantHumanAttention).mockResolvedValue(feedWith([
      { id: "affair-reminder:test:20261028", kind: "affair_reminder", title: "虚构提醒" },
    ]));
    await mountNotifier();
    expect(capability).toHaveBeenCalledOnce();
    expect(notifyHumanAttention).not.toHaveBeenCalled();
    await act(async () => { finish({ schemaVersion: 1, legacyAffairReminder: "main_owned" }); });
    await act(async () => new Promise(resolve => setTimeout(resolve, 0)));
    expect(notifyHumanAttention).toHaveBeenCalledOnce();
    expect(localStorage.getItem("vibelution.human-attention.notified.v1")).toBeNull();
  });
  it("pauses affairs but not other notifications on unknown capability", async () => {
    vi.stubGlobal("vibelutionLauncher", { notifyHumanAttention,
      getHumanAttentionCapabilities: vi.fn().mockRejectedValue(new Error("reply lost")) });
    vi.mocked(fetchPersonalAssistantHumanAttention).mockResolvedValue(feedWith([
      { id: "affair-reminder:unknown:20261028", kind: "affair_reminder", title: "虚构提醒" },
      { id: "other-attention", kind: "anomaly", title: "虚构异常" },
    ]));
    await mountNotifier();
    expect(notifyHumanAttention).toHaveBeenCalledTimes(1);
    expect(notifyHumanAttention).toHaveBeenCalledWith(expect.objectContaining({ id: "other-attention" }));
  });
  it("retries an unknown capability and resumes after the same document is confirmed", async () => {
    const capability = vi.fn().mockRejectedValueOnce(new Error("reply lost"))
      .mockResolvedValue({ schemaVersion: 1, legacyAffairReminder: "legacy" });
    vi.stubGlobal("vibelutionLauncher", { notifyHumanAttention, getHumanAttentionCapabilities: capability });
    vi.mocked(fetchPersonalAssistantHumanAttention).mockResolvedValue(feedWith([
      { id: "affair-reminder:retry:20261028", kind: "affair_reminder", title: "虚构提醒" },
    ]));
    await mountNotifier();
    expect(notifyHumanAttention).not.toHaveBeenCalled();
    await act(async () => new Promise(resolve => setTimeout(resolve, 1200)));
    expect(capability).toHaveBeenCalledTimes(2);
    expect(notifyHumanAttention).toHaveBeenCalledWith(expect.objectContaining({ id: "affair-reminder:retry:20261028" }));
  });
  it("uses the existing ledger when main explicitly declines coordination", async () => {
    notifyHumanAttention.mockResolvedValue({ delivered: "source_retired" });
    vi.stubGlobal("vibelutionLauncher", { notifyHumanAttention,
      getHumanAttentionCapabilities: vi.fn().mockResolvedValue({ schemaVersion: 1, legacyAffairReminder: "legacy" }) });
    vi.mocked(fetchPersonalAssistantHumanAttention).mockResolvedValue(feedWith([
      { id: "affair-reminder:legacy:20261028", kind: "affair_reminder", title: "虚构提醒" },
    ]));
    await mountNotifier();
    expect(notifyHumanAttention).toHaveBeenCalledOnce();
    expect(localStorage.getItem("vibelution.human-attention.notified.v1")).toContain("affair-reminder:legacy:20261028");
  });
  it("reads the dedicated feed even when the full overview is already cached", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    client.setQueryData(queryKeys.personalAssistantOverview(), {
      humanAttention: [{ id: "cached-overview", kind: "anomaly", title: "Old overview" }],
    });
    vi.mocked(fetchPersonalAssistantHumanAttention).mockResolvedValue(feedWith([
      { id: "fresh-feed", kind: "knowledge_review", title: "New notification" },
    ]));
    await renderInto(root, client);
    expect(fetchPersonalAssistantHumanAttention).toHaveBeenCalledTimes(1);
    expect(notifyHumanAttention).toHaveBeenCalledTimes(1);
    expect(notifyHumanAttention).toHaveBeenCalledWith(expect.objectContaining({ id: "fresh-feed" }));
  });

  it("notifies unseen human-attention rows once with the contract payload", async () => {
    vi.mocked(fetchPersonalAssistantHumanAttention).mockResolvedValue(feedWith([
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

  it("forwards human_gate rows with their inline actions and meta to the shell", async () => {
    vi.mocked(fetchPersonalAssistantHumanAttention).mockResolvedValue(feedWith([
      {
        id: "gate-1",
        kind: "human_gate",
        title: "研究结论等待审批",
        severity: "high",
        body: "阶段结论需要人工确认",
        targetUrl: "/teams?researchView=workflow&runId=run-7",
        actions: [
          { label: "接受", decision: "accept" },
          { label: "驳回", decision: "reject" },
        ],
        meta: { teamId: "team-1", runId: "run-7", nodeId: "node-gate", taskId: "task-9", decisions: ["accept", "reject", "revise"] },
      },
    ]));
    await mountNotifier();
    expect(notifyHumanAttention).toHaveBeenCalledTimes(1);
    expect(notifyHumanAttention).toHaveBeenCalledWith({
      id: "gate-1",
      kind: "human_gate",
      severity: "high",
      title: "研究结论等待审批",
      body: "阶段结论需要人工确认",
      targetUrl: "/teams?researchView=workflow&runId=run-7",
      actions: [
        { label: "接受", decision: "accept" },
        { label: "驳回", decision: "reject" },
      ],
      meta: { teamId: "team-1", runId: "run-7", nodeId: "node-gate", taskId: "task-9", decisions: ["accept", "reject", "revise"] },
    });
  });

  it("does not re-notify across page refreshes (localStorage day dedup)", async () => {
    vi.mocked(fetchPersonalAssistantHumanAttention).mockResolvedValue(
      feedWith([{ id: "an-1", kind: "anomaly", title: "研究异常", severity: "high" }]),
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
    vi.mocked(fetchPersonalAssistantHumanAttention).mockResolvedValue(
      feedWith([{ id: "kr-2", kind: "knowledge_review", title: "知识", severity: "medium" }]),
    );
    await expect(mountNotifier()).resolves.toBeUndefined();
    expect(notifyHumanAttention).not.toHaveBeenCalled();
  });

  it("navigates the workbench on opened clicks: targetUrl wins, kind default as fallback", async () => {
    vi.mocked(fetchPersonalAssistantHumanAttention).mockResolvedValue(
      feedWith([{ id: "an-1", kind: "anomaly", title: "研究异常", severity: "high" }]),
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
