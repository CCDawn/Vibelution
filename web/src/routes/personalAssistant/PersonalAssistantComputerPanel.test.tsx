// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { confirmPersonalAssistantComputer, controlPersonalAssistantComputer, fetchPersonalAssistantComputer,
  fetchPersonalAssistantComputerWindows, grantPersonalAssistantComputer } from "../../api/personalAssistantComputer";
import { queryKeys } from "../../api/queryKeys";
import type { ComputerState } from "../../api/types/personalAssistantComputer";
import { PersonalAssistantComputerPanel } from "./PersonalAssistantComputerPanel";

vi.mock("../../api/personalAssistantComputer", () => ({ confirmPersonalAssistantComputer: vi.fn(), controlPersonalAssistantComputer: vi.fn(),
  fetchPersonalAssistantComputer: vi.fn(), fetchPersonalAssistantComputerWindows: vi.fn(), grantPersonalAssistantComputer: vi.fn() }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const target = { selectionId: "selection", title: "今天的计划.txt", appName: "记事本" };
const idle: ComputerState = { available: true, status: "idle", message: "请选择窗口", grantId: null, window: null, pending: null };
const ready: ComputerState = { ...idle, status: "ready", message: "准备好操作", grantId: "grant", window: target };
let root: Root, container: HTMLDivElement, client: QueryClient;
const collapse = vi.fn();
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchPersonalAssistantComputer).mockResolvedValue(idle);
  vi.mocked(fetchPersonalAssistantComputerWindows).mockResolvedValue({ windows: [target] });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); client.clear(); vi.restoreAllMocks(); });
async function settle(ms = 25) { await act(async () => new Promise(resolve => setTimeout(resolve, ms))); }
async function render(active = true) {
  await act(async () => root.render(<QueryClientProvider client={client}><PersonalAssistantComputerPanel active={active} onCollapse={collapse} /></QueryClientProvider>));
  await settle();
}
function button(label: string) { const found = [...container.querySelectorAll("button")].find(row => row.textContent === label || row.getAttribute("aria-label") === label); if (!found) throw new Error(`Missing button ${label}`); return found; }
async function click(label: string) { await act(async () => button(label).click()); await settle(); }
describe("single-window personal assistant controls", () => {
  it("requires both an explicit target and vision consent, and grants only that selection", async () => {
    await render();
    expect(button("授权这个窗口").disabled).toBe(true);
    const select = container.querySelector('[aria-pressed="false"]') as HTMLButtonElement;
    await act(async () => select.click());
    expect(button("授权这个窗口").disabled).toBe(true);
    expect(container.textContent).toContain("画面将提供给当前助理模型");
    const checkbox = container.querySelector('input[type="checkbox"]') as HTMLInputElement;
    await act(async () => checkbox.click());
    vi.mocked(grantPersonalAssistantComputer).mockResolvedValue(ready);
    vi.mocked(fetchPersonalAssistantComputer).mockResolvedValue(ready);
    await click("授权这个窗口");
    expect(grantPersonalAssistantComputer).toHaveBeenCalledWith({ selectionId: "selection", allowVision: true });
    expect(container.textContent).toContain("本次授权 · 仅此窗口");
    expect(fetchPersonalAssistantComputerWindows).toHaveBeenCalledTimes(1);
    await act(async () => client.setQueryData(queryKeys.personalAssistantComputer(), { ...idle, status: "ended", message: "窗口已关闭" }));
    await settle();
    expect(button("授权这个窗口").disabled).toBe(true);
    expect((container.querySelector('input[type="checkbox"]') as HTMLInputElement).checked).toBe(false);
  });
  it("polls state without repeatedly enumerating windows and stops polling while inactive", async () => {
    await render(); await settle(1100);
    expect(vi.mocked(fetchPersonalAssistantComputer).mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(fetchPersonalAssistantComputerWindows).toHaveBeenCalledTimes(1);
    await render(false);
    const count = vi.mocked(fetchPersonalAssistantComputer).mock.calls.length;
    await settle(1100);
    expect(fetchPersonalAssistantComputer).toHaveBeenCalledTimes(count);
    await render(); await click("刷新可选窗口");
    expect(fetchPersonalAssistantComputerWindows).toHaveBeenCalledTimes(2);
  });
  it("stops state polling when the document is hidden without enumerating windows on return", async () => {
    await render();
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    await act(async () => document.dispatchEvent(new Event("visibilitychange")));
    const count = vi.mocked(fetchPersonalAssistantComputer).mock.calls.length;
    await settle(1100);
    expect(fetchPersonalAssistantComputer).toHaveBeenCalledTimes(count);
    visibility.mockReturnValue("visible");
    await act(async () => document.dispatchEvent(new Event("visibilitychange")));
    await settle();
    expect(vi.mocked(fetchPersonalAssistantComputer).mock.calls.length).toBeGreaterThan(count);
    expect(fetchPersonalAssistantComputerWindows).toHaveBeenCalledTimes(1);
  });
  it.each([["ready", "暂停电脑操作", "pause"], ["paused", "继续电脑操作", "resume"], ["ready", "交给我", "takeover"],
    ["manual", "交回助理", "return"]] as const)("sends %s control %s using the current grant", async (status, label, action) => {
    vi.mocked(fetchPersonalAssistantComputer).mockResolvedValue({ ...ready, status });
    vi.mocked(controlPersonalAssistantComputer).mockResolvedValue({ ...ready, message: "服务端已处理" });
    await render(); await click(label);
    expect(controlPersonalAssistantComputer).toHaveBeenCalledWith({ grantId: "grant", action });
  });
  it("keeps the authoritative state and error when pause fails", async () => {
    vi.mocked(fetchPersonalAssistantComputer).mockResolvedValue({ ...ready, status: "working", message: "正在操作指定窗口" });
    vi.mocked(controlPersonalAssistantComputer).mockRejectedValue(new Error("暂停请求失败"));
    await render(); await click("暂停电脑操作");
    expect(container.textContent).toContain("暂停请求失败");
    expect(container.textContent).toContain("正在操作指定窗口");
    expect(container.textContent).not.toContain("已暂停");
  });
  it.each([["确认执行", true], ["取消操作", false]] as const)("shows the exact action, target and input before %s", async (label, approved) => {
    const waiting: ComputerState = { ...ready, status: "waiting_confirmation", pending: { id: "pending", action: "发送", targetLabel: "收件人 小王", text: "今天的计划\n明天跟进" } };
    vi.mocked(fetchPersonalAssistantComputer).mockResolvedValue(waiting);
    vi.mocked(confirmPersonalAssistantComputer).mockResolvedValue({ ...ready, status: "paused" });
    await render();
    expect(container.querySelector("dl")?.textContent).toContain("发送");
    expect(container.querySelector("dl")?.textContent).toContain("收件人 小王");
    expect(container.querySelector("pre")?.textContent).toBe("今天的计划\n明天跟进");
    expect(confirmPersonalAssistantComputer).not.toHaveBeenCalled();
    await click(label);
    expect(confirmPersonalAssistantComputer).toHaveBeenCalledWith({ grantId: "grant", pendingId: "pending", approved });
  });
  it("ends the grant before returning to selection and clears prior consent", async () => {
    vi.mocked(fetchPersonalAssistantComputer).mockResolvedValue(ready);
    await render();
    const ended: ComputerState = { ...idle, status: "ended", message: "授权已结束，请重新选择" };
    vi.mocked(controlPersonalAssistantComputer).mockResolvedValue(ended);
    vi.mocked(fetchPersonalAssistantComputer).mockResolvedValue(ended);
    await click("结束并重新选择");
    expect(controlPersonalAssistantComputer).toHaveBeenCalledWith({ grantId: "grant", action: "end" });
    expect(button("授权这个窗口").disabled).toBe(true);
    expect((container.querySelector('input[type="checkbox"]') as HTMLInputElement).checked).toBe(false);
    expect(fetchPersonalAssistantComputerWindows).toHaveBeenCalledTimes(2);
  });
  it("makes window loss recoverable and keeps collapse available", async () => {
    vi.mocked(fetchPersonalAssistantComputer).mockResolvedValue({ ...idle, status: "ended", message: "窗口已关闭，请重新选择" });
    await render();
    expect(container.textContent).toContain("窗口已关闭，请重新选择");
    expect(container.querySelector('[aria-label="暂停电脑操作"]')).toBeNull();
    await click("收起电脑操作栏"); expect(collapse).toHaveBeenCalledOnce();
  });
  it("retains last known state but prevents confirming when state reads fail", async () => {
    client.setQueryData(queryKeys.personalAssistantComputer(), { ...ready, status: "waiting_confirmation", pending: { id: "pending", action: "删除", targetLabel: "文档", text: null } });
    vi.mocked(fetchPersonalAssistantComputer).mockRejectedValue(new Error("连接中断"));
    await render();
    expect(container.textContent).toContain("连接中断");
    expect(button("确认执行").disabled).toBe(true);
    expect(button("交给我").disabled).toBe(false);
  });
});
