// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider, notifyManager } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FinanceWalkForward } from "./FinanceWalkForward";
import * as api from "../../api/financialWalkForward";

vi.mock("../../api/financialWalkForward", () => ({ listWalkForward: vi.fn(), previewWalkForward: vi.fn(), actWalkForward: vi.fn(), exportWalkForward: vi.fn() }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root, node: HTMLDivElement, client: QueryClient;
let pendingNotifications = 0;
let notificationDelay = 0;
const workflow: api.WalkForwardWorkflow = {
  agentId: "a", sourceRunId: "source", workflowId: "workflow", status: "preview", planHash: "frozen-plan",
  trainSessions: 126, testSessions: 63, stepSessions: 63, maxTokens: 2000000, estimatedTokens: 10000,
  candidates: [{ candidateId: "cap-40", maxPositionPct: 40 }, { candidateId: "cap-80", maxPositionPct: 80 }],
  folds: [{ foldId: "f1", trainStart: "2024-01-02", trainEnd: "2024-06-28", testStart: "2024-07-01", testEnd: "2024-09-30", selectedCandidateId: null, testRunId: null, status: "pending", metrics: null }],
  activeRunId: null, terminalReason: null, createdAt: "2026-10-10T00:00:00Z", updatedAt: "2026-10-10T00:00:00Z", notice: "每段独立账户，模型历史知识偏差仍存在。",
};
beforeEach(() => {
  pendingNotifications = 0;
  notificationDelay = 0;
  notifyManager.setScheduler(callback => {
    pendingNotifications += 1;
    setTimeout(() => {
      act(() => callback());
      pendingNotifications -= 1;
    }, notificationDelay);
  });
  vi.resetAllMocks();
  vi.mocked(api.listWalkForward).mockResolvedValue({ items: [] });
  node = document.createElement("div"); document.body.append(node); root = createRoot(node);
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
});
afterEach(async () => {
  await act(async () => root.unmount());
  client.clear();
  await vi.waitFor(() => expect(pendingNotifications).toBe(0));
  notifyManager.setScheduler(callback => setTimeout(callback, 0));
  node.remove();
});
async function render(sourceRunId?: string) {
  await act(async () => root.render(<QueryClientProvider client={client}><FinanceWalkForward agentId="a" sourceRunId={sourceRunId} zh onSelectRun={vi.fn()} /></QueryClientProvider>));
}
async function click(text: string) {
  let button: HTMLButtonElement | undefined;
  await vi.waitFor(async () => {
    await act(async () => undefined);
    button = [...node.querySelectorAll("button")].find(item => item.textContent?.includes(text));
    expect(button).toBeDefined();
    expect(button!.disabled).toBe(false);
  });
  await act(async () => button!.click());
  await vi.waitFor(async () => {
    await act(async () => undefined);
    expect(client.isFetching()).toBe(0);
    expect(client.isMutating()).toBe(0);
    expect(pendingNotifications).toBe(0);
  });
  await act(async () => undefined);
}
it("starts collapsed and disables preview without an owned source run", async () => {
  await render(); expect(api.listWalkForward).not.toHaveBeenCalled();
  await click("滚动样本外验证");
  expect([...node.querySelectorAll("button")].find(item => item.textContent === "预检滚动计划")?.disabled).toBe(true);
  expect(node.textContent).toContain("先选择一条已有回测");
});
it("previews frozen plan without starting a model, then requires an explicit start", async () => {
  vi.mocked(api.previewWalkForward).mockResolvedValue(workflow);
  await render("source"); await click("滚动样本外验证");
  vi.mocked(api.listWalkForward).mockResolvedValue({ items: [workflow] });
  await click("预检滚动计划");
  expect(api.previewWalkForward).toHaveBeenCalledWith("a", "source", expect.objectContaining({ trainSessions: 126, testSessions: 63, stepSessions: 63, candidates: [{ candidateId: "cap-40", maxPositionPct: 40 }, { candidateId: "cap-60", maxPositionPct: 60 }, { candidateId: "cap-80", maxPositionPct: 80 }] }));
  expect(api.actWalkForward).not.toHaveBeenCalled();
  expect(node.textContent).toContain("10,000");
  vi.mocked(api.actWalkForward).mockResolvedValue({ ...workflow, status: "running" });
  await click("按冻结预算启动");
  expect(api.actWalkForward).toHaveBeenCalledWith("a", "workflow", "start");
});
it("rejects a response from a different owner and leaves no start control", async () => {
  vi.mocked(api.previewWalkForward).mockResolvedValue({ ...workflow, agentId: "other" });
  await render("source"); await click("滚动样本外验证"); await click("预检滚动计划");
  expect(node.textContent).toContain("身份不匹配");
  expect(node.textContent).not.toContain("按冻结预算启动");
});
it("restores uncertain child state without hiding its recovery reason", async () => {
  vi.mocked(api.listWalkForward).mockResolvedValue({ items: [{ ...workflow, status: "paused_unknown", activeRunId: "child", terminalReason: "请先在子回测确认重复计费" }] });
  await render(); await click("滚动样本外验证");
  expect(node.textContent).toContain("请先在子回测确认重复计费");
  expect(node.textContent).toContain("查看当前子回测");
  expect(api.actWalkForward).not.toHaveBeenCalled();
});
it("allows an explicit retry of a failed workflow and retains a rejected recovery reason", async () => {
  // Query notifications may settle after the click itself under suite load.
  notificationDelay = 80;
  try {
    vi.mocked(api.listWalkForward).mockResolvedValue({ items: [{ ...workflow, status: "failed", terminalReason: "计划保存失败" }] });
    vi.mocked(api.actWalkForward).mockRejectedValue(new Error("子回测失败，请先检查子回测"));
    await render(); await click("滚动样本外验证");
    expect(api.actWalkForward).not.toHaveBeenCalled();
    await click("继续计划");
    expect(api.actWalkForward).toHaveBeenCalledWith("a", "workflow", "resume");
    expect(node.textContent).toContain("子回测失败，请先检查子回测");
  } finally {
    notificationDelay = 0;
  }
});
it("dismisses an operation error without refetching or replaying a model action", async () => {
  vi.mocked(api.listWalkForward).mockResolvedValue({ items: [{ ...workflow, status: "failed" }] });
  vi.mocked(api.actWalkForward).mockRejectedValueOnce(new Error("子回测暂时不可恢复"));
  await render(); await click("滚动样本外验证"); await click("继续计划");
  const reads = vi.mocked(api.listWalkForward).mock.calls.length;
  await click("关闭提示");
  expect(node.textContent).not.toContain("子回测暂时不可恢复");
  expect(api.listWalkForward).toHaveBeenCalledTimes(reads);
  expect(api.actWalkForward).toHaveBeenCalledTimes(1);
  vi.mocked(api.actWalkForward).mockResolvedValue({ ...workflow, status: "running" });
  await click("继续计划");
  expect(api.actWalkForward).toHaveBeenCalledTimes(2);
});
it("retries only the list read and clears its error after recovery", async () => {
  vi.mocked(api.listWalkForward).mockRejectedValueOnce(new Error("读取计划失败"));
  await render(); await click("滚动样本外验证");
  expect(node.textContent).toContain("读取计划失败");
  vi.mocked(api.listWalkForward).mockResolvedValue({ items: [workflow] });
  await click("重新读取");
  expect(node.textContent).not.toContain("读取计划失败");
  expect(node.textContent).toContain("按冻结预算启动");
  expect(api.actWalkForward).not.toHaveBeenCalled();
});
it("keeps a list failure visible after dismissing a separate operation failure", async () => {
  vi.mocked(api.listWalkForward).mockRejectedValue(new Error("计划列表离线"));
  vi.mocked(api.previewWalkForward).mockRejectedValue(new Error("预检暂时失败"));
  await render("source"); await click("滚动样本外验证"); await click("预检滚动计划");
  expect(node.textContent).toContain("计划列表离线");
  expect(node.textContent).toContain("预检暂时失败");
  await click("关闭提示");
  expect(node.textContent).not.toContain("预检暂时失败");
  expect(node.textContent).toContain("计划列表离线");
  expect(node.textContent).toContain("重新读取");
});
