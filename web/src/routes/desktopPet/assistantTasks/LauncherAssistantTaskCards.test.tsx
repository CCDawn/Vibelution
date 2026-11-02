// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LauncherAssistantDispatch, LauncherAssistantStatus } from "../../../api/launcherAssistant";
import { LauncherAssistantTaskCards } from "./LauncherAssistantTaskCards";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function row(overrides: Partial<LauncherAssistantDispatch> = {}): LauncherAssistantDispatch {
  return { dispatchId: "dispatch-1", projectId: "project-1", agentId: "worker-1", nativeTaskId: "native-1", title: "核对周报",
    receipt: { taskId: "native-1", status: "running", shouldPoll: true }, ...overrides };
}

let root: Root | null, container: HTMLDivElement, client: QueryClient;
let rows: LauncherAssistantDispatch[], status: LauncherAssistantStatus;
let dispatchReply: () => Promise<LauncherAssistantDispatch[]>;
let visibility: DocumentVisibilityState;
let invoke: ReturnType<typeof vi.fn>, onReview: ReturnType<typeof vi.fn>, onApproval: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.useFakeTimers();
  visibility = "visible";
  vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibility);
  rows = [row()];
  status = { assistant: { agentId: "assistant-1", directSessionId: "session-1", displayName: "助理" } };
  dispatchReply = async () => rows;
  invoke = vi.fn(async (request: { operation: string }) => {
    if (request.operation === "status") return status;
    if (request.operation === "dispatches") return { dispatches: await dispatchReply() };
    throw new Error(`Unexpected mutation: ${request.operation}`);
  });
  vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
  onReview = vi.fn(); onApproval = vi.fn();
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
});

afterEach(async () => {
  await act(async () => { root?.unmount(); });
  container.remove(); client.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers();
});

async function settle() {
  // Query notifications scheduled from an interval land on the next fake-clock tick.
  for (let index = 0; index < 5; index += 1) await act(async () => { await vi.advanceTimersByTimeAsync(1); });
}
async function render(lang: "zh" | "en" = "zh") {
  await act(async () => { root!.render(<QueryClientProvider client={client}>
    <LauncherAssistantTaskCards onReview={onReview} onApproval={onApproval} lang={lang} />
  </QueryClientProvider>); });
  await settle();
}
function button(label: string, within: ParentNode = container): HTMLButtonElement {
  const result = [...within.querySelectorAll<HTMLButtonElement>("button")].find(element => element.textContent === label);
  if (!result) throw new Error(`Missing button: ${label}`);
  return result;
}
async function click(label: string, within: ParentNode = container) {
  await act(async () => { button(label, within).click(); }); await settle();
}
function dispatchReads() { return invoke.mock.calls.filter(([request]) => request.operation === "dispatches").length; }
function onlyReads() { expect(invoke.mock.calls.every(([request]) => ["status", "dispatches"].includes(request.operation))).toBe(true); }

describe("Launcher assistant task cards", () => {
  it("localizes the card, fallback title, details, and navigation when Launcher uses English", async () => {
    rows = [row({ title: undefined, receipt: { taskId: "native-1", status: "succeeded", shouldPoll: false } })];
    await render("en");
    expect(container.querySelector('section[aria-label="Assistant tasks"]')).toBeTruthy();
    expect(container.textContent).toContain("Assistant task");
    expect(container.textContent).toContain("Awaiting verification");
    expect(container.textContent).toContain("Showing tasks dispatched by your assistant");
    await click("Details");
    expect(container.textContent).toContain("Latest receipt summary");
    expect(container.textContent).toContain("No result summary yet.");
    expect(container.textContent).toContain("Project ID: project-1");
    expect(container.textContent).not.toMatch(/[\u4e00-\u9fff]/);
    await click("Review in chat");
    expect(onReview).toHaveBeenCalledWith(expect.objectContaining({ state: "awaiting_verification" }));
    onlyReads();
  });

  it("keeps result text and identifiers collapsed until the user expands details", async () => {
    rows = [row({ receipt: { taskId: "native-1", status: "succeeded", resultSummary: '<img src=x onerror="alert(1)"> 周报待核对' } })];
    await render();
    expect(container.textContent).toContain("待验收");
    expect(container.textContent).not.toContain("dispatch-1");
    expect(container.textContent).not.toContain("周报待核对");
    expect(container.querySelector('button[aria-expanded="false"]')).toBeTruthy();
    await click("详情");
    expect(container.textContent).toContain("dispatch-1");
    expect(container.textContent).toContain("周报待核对");
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector('button[aria-expanded="true"]')).toBeTruthy();
    await click("收起详情");
    expect(container.textContent).not.toContain("native-1");
  });

  it("only navigates to the existing approval flow and never decides an approval", async () => {
    rows = [row({ receipt: { taskId: "native-1", status: "awaiting_approval", shouldPoll: false, pendingApprovals: [{
      approvalId: "approval-1", toolName: "write", risk: "write", targetSummary: {}, revision: "r1", availableDecisions: ["accept", "decline"],
    }] } })];
    await render();
    await click("处理授权");
    expect(onApproval).toHaveBeenCalledWith(expect.objectContaining({ projectId: "project-1", dispatchId: "dispatch-1", state: "waiting_user" }));
    expect(onReview).not.toHaveBeenCalled();
    expect(container.textContent).not.toContain("同意");
    onlyReads();
  });

  it("offers failure review without retry, restart, dispatch, or other mutations", async () => {
    rows = [row({ receipt: { taskId: "native-1", status: "failed", shouldPoll: false } })];
    await render(); await click("去对话核对");
    expect(onReview).toHaveBeenCalledWith(expect.objectContaining({ state: "failed", businessAcceptance: "not_evaluated" }));
    expect(onApproval).not.toHaveBeenCalled();
    expect([...container.querySelectorAll("button")].map(element => element.textContent)).toEqual(["刷新", "去对话核对", "详情"]);
    onlyReads();
  });

  it("presents native success as awaiting verification and reviews the exact project and dispatch", async () => {
    rows = [row({ receipt: { taskId: "native-1", status: "succeeded", resultSummary: "所有目标已完成", shouldPoll: false } })];
    await render();
    expect(container.querySelector('[data-task-state="awaiting_verification"]')).toBeTruthy();
    expect(container.textContent).toContain("还需核对实际结果");
    expect(container.textContent).not.toContain("所有目标已完成");
    await click("去对话核对");
    expect(onReview).toHaveBeenCalledWith(expect.objectContaining({ projectId: "project-1", dispatchId: "dispatch-1", state: "awaiting_verification" }));
    onlyReads();
  });

  it("distinguishes a first read failure from an available empty feed and does not auto retry", async () => {
    dispatchReply = async () => { throw new Error("offline"); };
    await render();
    expect(container.textContent).toContain("任务状态暂不可用");
    expect(container.textContent).not.toContain("暂无助理派遣任务");
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(dispatchReads()).toBe(1);
    rows = []; dispatchReply = async () => rows;
    await click("刷新");
    expect(container.textContent).toContain("暂无助理派遣任务");
    expect(dispatchReads()).toBe(2);
  });

  it("retains old cards as unknown after a poll fails and stops polling the error", async () => {
    await render();
    expect(container.textContent).toContain("执行中");
    dispatchReply = async () => { throw new Error("disconnected"); };
    await act(async () => { await vi.advanceTimersByTimeAsync(3_000); }); await settle();
    expect(dispatchReads()).toBe(2);
    expect(client.getQueryState(["launcher-assistant", "task-cards", "assistant-1", "session-1"])).toMatchObject({ status: "error" });
    expect(container.textContent).toContain("核对周报");
    expect(container.querySelector('[data-task-state="unknown"]')).toBeTruthy();
    expect(container.textContent).toContain("保留上次记录");
    expect(container.textContent).not.toContain("暂无助理派遣任务");
    const reads = dispatchReads();
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(dispatchReads()).toBe(reads);
  });

  it("does not turn unrelated shared status refreshes into automatic retries of a failed feed", async () => {
    dispatchReply = async () => { throw new Error("offline"); };
    await render();
    expect(dispatchReads()).toBe(1);
    for (let index = 0; index < 3; index += 1) {
      await act(async () => { await client.refetchQueries({ queryKey: ["launcher-assistant", "status"], exact: true }); });
      await settle();
    }
    expect(dispatchReads()).toBe(1);
    expect(container.textContent).toContain("任务状态暂不可用");
  });

  it.each([
    { status: "running", shouldPoll: false },
    { status: "succeeded", shouldPoll: true },
    { status: "unfamiliar", shouldPoll: true },
  ])("does not poll an idle, terminal, or unknown receipt: $status/$shouldPoll", async receipt => {
    rows = [row({ receipt: { taskId: "native-1", ...receipt } })];
    await render();
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(dispatchReads()).toBe(1);
  });

  it("polls known active receipts only while visible and stops after unmount", async () => {
    await render();
    await act(async () => { await vi.advanceTimersByTimeAsync(3_000); }); await settle();
    expect(dispatchReads()).toBe(2);
    visibility = "hidden";
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(dispatchReads()).toBe(2);
    await act(async () => { root!.unmount(); root = null; });
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(dispatchReads()).toBe(2);
  });

  it("keeps same-dispatch identifiers from different projects bound to their own summary and callback", async () => {
    rows = [row({ title: "项目甲", receipt: { taskId: "native-1", status: "failed", resultSummary: "甲的摘要" } }),
      row({ projectId: "project-2", title: "项目乙", receipt: { taskId: "native-1", status: "failed", resultSummary: "乙的摘要" } })];
    await render();
    const second = container.querySelector('article[aria-label="项目乙"]')!;
    await click("详情", second);
    expect(second.textContent).toContain("乙的摘要");
    expect(second.textContent).not.toContain("甲的摘要");
    await click("去对话核对", second);
    expect(onReview).toHaveBeenCalledWith(expect.objectContaining({ projectId: "project-2", dispatchId: "dispatch-1" }));
  });

  it("shows ten cards initially and reveals more without claiming complete platform coverage", async () => {
    rows = Array.from({ length: 12 }, (_, index) => row({ dispatchId: `dispatch-${index}`, title: `任务 ${index}`,
      receipt: { taskId: "native-1", status: "succeeded", shouldPoll: false } }));
    await render();
    expect(container.querySelectorAll("article")).toHaveLength(10);
    expect(container.textContent).toContain("这里显示助理已派出的任务");
    await click("显示更多");
    expect(container.querySelectorAll("article")).toHaveLength(12);
    expect(container.textContent).not.toContain("全部任务");
    expect(dispatchReads()).toBe(1);
  });

  it("aborts obsolete identity responses instead of caching them for the next assistant", async () => {
    let resolveOld!: (value: LauncherAssistantDispatch[]) => void;
    dispatchReply = () => new Promise(resolve => { resolveOld = resolve; });
    await render();
    const next = { assistant: { agentId: "assistant-2", directSessionId: "session-2", displayName: "新助理" } };
    dispatchReply = async () => [row({ title: "新身份任务", receipt: { taskId: "native-1", status: "failed" } })];
    await act(async () => { client.setQueryData(["launcher-assistant", "status"], next); }); await settle();
    expect(container.textContent).toContain("新身份任务");
    await act(async () => { resolveOld([row({ title: "过期身份任务" })]); }); await settle();
    expect(container.textContent).not.toContain("过期身份任务");
    expect(client.getQueryData(["launcher-assistant", "task-cards", "assistant-1", "session-1"])).toBeUndefined();
    expect(client.getQueryData(["launcher-assistant", "task-cards", "assistant-2", "session-2"])).toEqual(expect.any(Array));
  });

  it("does not expose cached cards before the current opening verifies the assistant identity", async () => {
    client.setQueryData(["launcher-assistant", "status"], status);
    client.setQueryData(["launcher-assistant", "task-cards", "assistant-1", "session-1"], [row({
      title: "旧身份的任务", receipt: { taskId: "native-1", status: "failed" },
    })]);
    let resolveStatus!: (value: LauncherAssistantStatus) => void;
    invoke.mockImplementation(async (request: { operation: string }) => {
      if (request.operation === "status") return new Promise<LauncherAssistantStatus>(resolve => { resolveStatus = resolve; });
      if (request.operation === "dispatches") return { dispatches: [row({ title: "当前身份的任务" })] };
      throw new Error(`Unexpected mutation: ${request.operation}`);
    });
    await render();
    expect(container.textContent).toContain("正在读取任务");
    expect(container.textContent).not.toContain("旧身份的任务");
    expect(container.querySelector("article")).toBeNull();
    expect(onReview).not.toHaveBeenCalled();
    expect(onApproval).not.toHaveBeenCalled();
    expect(dispatchReads()).toBe(0);
    await act(async () => { resolveStatus({ assistant: { agentId: "assistant-2", directSessionId: "session-2", displayName: "新助理" } }); });
    await settle();
    expect(container.textContent).toContain("当前身份的任务");
    expect(container.textContent).not.toContain("旧身份的任务");
  });
});
