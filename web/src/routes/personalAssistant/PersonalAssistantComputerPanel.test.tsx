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
let mockLang: "zh" | "en" = "zh";
vi.mock("../../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: mockLang }) }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const target = { selectionId: "selection", title: "今天的计划.txt", appName: "记事本" };
const idle: ComputerState = { available: true, status: "idle", message: "请选择窗口", grantId: null, window: null, pending: null };
const ready: ComputerState = { ...idle, status: "ready", message: "准备好操作", grantId: "grant", window: target };
let root: Root, container: HTMLDivElement, client: QueryClient;
const collapse = vi.fn();
beforeEach(() => {
  vi.clearAllMocks();
  mockLang = "zh";
  vi.mocked(fetchPersonalAssistantComputer).mockResolvedValue(idle);
  vi.mocked(fetchPersonalAssistantComputerWindows).mockResolvedValue({ windows: [target] });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); client.clear(); vi.restoreAllMocks(); });
async function settle(ms = 0) {
  if (ms > 0) await act(async () => new Promise(resolve => setTimeout(resolve, ms)));
  // A settled query can precede its scheduled React notification. Wait for
  // both the cache and visible loading state, keeping each scheduler yield in act.
  const deadline = Date.now() + 2000;
  do {
    await act(async () => new Promise(resolve => setTimeout(resolve, 10)));
  } while ((client.isFetching() || client.isMutating() || container.querySelector('[aria-busy="true"]')) && Date.now() < deadline);
  expect(client.isFetching()).toBe(0);
  expect(client.isMutating()).toBe(0);
  expect(container.querySelector('[aria-busy="true"]')).toBeNull();
}
async function render(active = true) {
  await act(async () => root.render(<QueryClientProvider client={client}><PersonalAssistantComputerPanel active={active} onCollapse={collapse} /></QueryClientProvider>));
  await settle();
}
async function renderConversation(onGranted = vi.fn(), authorizationRequestId?: string, prepareContinuation?: Parameters<typeof PersonalAssistantComputerPanel>[0]["prepareContinuation"]) {
  await act(async () => root.render(<QueryClientProvider client={client}><PersonalAssistantComputerPanel active onCollapse={collapse} presentation="conversation" onGranted={onGranted} authorizationRequestId={authorizationRequestId} prepareContinuation={prepareContinuation} /></QueryClientProvider>));
  await settle();
  return onGranted;
}
function button(label: string) { const found = [...container.querySelectorAll("button")].find(row => row.textContent === label || row.getAttribute("aria-label") === label); if (!found) throw new Error(`Missing button ${label}`); return found; }
async function click(label: string) { await act(async () => button(label).click()); await settle(); }
describe("single-window personal assistant controls", () => {
  it("freezes the continuation before grant and calls it only after the exact window succeeds", async () => {
    const finish = vi.fn(); const prepare = vi.fn(() => finish);
    let resolve!: (state: ComputerState) => void;
    vi.mocked(grantPersonalAssistantComputer).mockImplementation(() => new Promise(done => { resolve = done; }));
    await renderConversation(vi.fn(), "request-original", prepare);
    await act(async () => (container.querySelector('[aria-pressed="false"]') as HTMLButtonElement).click());
    await act(async () => button("授权并继续当前任务").click());
    expect(prepare).toHaveBeenCalledWith("grant"); expect(finish).not.toHaveBeenCalled();
    expect(grantPersonalAssistantComputer).toHaveBeenCalledWith({ selectionId: target.selectionId, allowVision: true, authorizationRequestId: "request-original" });
    vi.mocked(fetchPersonalAssistantComputer).mockResolvedValue(ready);
    await act(async () => resolve(ready)); await settle();
    expect(finish).toHaveBeenCalledOnce();
  });
  it("does not continue on rejected grants or passive authorized state", async () => {
    const finish = vi.fn(); const prepare = vi.fn(() => finish);
    vi.mocked(grantPersonalAssistantComputer).mockRejectedValue(new Error("expired request"));
    await renderConversation(vi.fn(), "request-original", prepare);
    await act(async () => (container.querySelector('[aria-pressed="false"]') as HTMLButtonElement).click());
    await click("授权并继续当前任务");
    await act(async () => client.setQueryData(queryKeys.personalAssistantComputer(), ready));
    expect(prepare).toHaveBeenCalledOnce(); expect(finish).not.toHaveBeenCalled();
  });
  it("requires an explicit window and grants once from the conversation card", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const onGranted = await renderConversation();
    expect(button("允许读取并操作").disabled).toBe(true);
    expect(container.querySelector('input[type="checkbox"]')).toBeNull();
    expect(onGranted).not.toHaveBeenCalled();
    await act(async () => (container.querySelector('[aria-pressed="false"]') as HTMLButtonElement).click());
    expect(container.textContent).toContain("允许助理读取并操作「今天的计划.txt」");
    expect(container.textContent).toContain("窗口画面将提供给当前助理模型");
    await click("更换窗口");
    expect(button("允许读取并操作").disabled).toBe(true);
    await act(async () => (container.querySelector('[aria-pressed="false"]') as HTMLButtonElement).click());
    vi.mocked(grantPersonalAssistantComputer).mockResolvedValue(ready);
    vi.mocked(fetchPersonalAssistantComputer).mockResolvedValue(ready);
    await act(async () => { button("允许读取并操作").click(); button("允许读取并操作").click(); });
    await settle();
    expect(grantPersonalAssistantComputer).toHaveBeenCalledOnce();
    expect(grantPersonalAssistantComputer).toHaveBeenCalledWith({ selectionId: "selection", allowVision: true });
    expect(onGranted).toHaveBeenCalledOnce();
    expect(onGranted).toHaveBeenCalledWith(ready);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(container.textContent).toContain("今天的计划.txt");
  });
  it("does not grant when declined or call onGranted from passive state reads", async () => {
    const onGranted = await renderConversation();
    await click("暂不允许");
    expect(collapse).toHaveBeenCalledOnce();
    expect(grantPersonalAssistantComputer).not.toHaveBeenCalled();
    await act(async () => client.setQueryData(queryKeys.personalAssistantComputer(), ready));
    expect(onGranted).not.toHaveBeenCalled();
  });
  it("forwards the card's request identity and does not enumerate windows with an existing grant", async () => {
    await renderConversation(vi.fn(), "request-1");
    await act(async () => (container.querySelector('[aria-pressed="false"]') as HTMLButtonElement).click());
    vi.mocked(grantPersonalAssistantComputer).mockResolvedValue(ready);
    vi.mocked(fetchPersonalAssistantComputer).mockResolvedValue(ready);
    await click("允许读取并操作");
    expect(grantPersonalAssistantComputer).toHaveBeenCalledWith({ selectionId: "selection", allowVision: true, authorizationRequestId: "request-1" });
    await act(async () => root.unmount());
    root = createRoot(container);
    vi.mocked(fetchPersonalAssistantComputerWindows).mockClear();
    await renderConversation();
    expect(fetchPersonalAssistantComputerWindows).not.toHaveBeenCalled();
  });
  it("clears a window selection before refreshing and requires a fresh selection", async () => {
    await renderConversation();
    await act(async () => (container.querySelector('[aria-pressed="false"]') as HTMLButtonElement).click());
    await click("更换窗口");
    vi.mocked(fetchPersonalAssistantComputerWindows).mockResolvedValue({ windows: [{ ...target, selectionId: "fresh" }] });
    await click("刷新可选窗口");
    expect(button("允许读取并操作").disabled).toBe(true);
    await act(async () => (container.querySelector('[aria-pressed="false"]') as HTMLButtonElement).click());
    vi.mocked(grantPersonalAssistantComputer).mockResolvedValue(ready);
    vi.mocked(fetchPersonalAssistantComputer).mockResolvedValue(ready);
    await click("允许读取并操作");
    expect(grantPersonalAssistantComputer).toHaveBeenCalledWith({ selectionId: "fresh", allowVision: true });
  });
  it("clears an expired selection after a failed grant and refreshes local choices", async () => {
    const onGranted = await renderConversation();
    await act(async () => (container.querySelector('[aria-pressed="false"]') as HTMLButtonElement).click());
    vi.mocked(fetchPersonalAssistantComputerWindows).mockResolvedValue({ windows: [{ ...target, selectionId: "fresh" }] });
    vi.mocked(grantPersonalAssistantComputer).mockRejectedValueOnce(new Error("窗口已过期"));
    await click("允许读取并操作");
    expect(container.textContent).toContain("窗口已过期");
    expect(button("允许读取并操作").disabled).toBe(true);
    expect(fetchPersonalAssistantComputerWindows).toHaveBeenCalledTimes(2);
    expect(onGranted).not.toHaveBeenCalled();
  });
  it.each([["ready", "暂停电脑操作", "pause"], ["paused", "继续电脑操作", "resume"], ["ready", "交给我", "takeover"],
    ["manual", "交回助理", "return"]] as const)("keeps conversation control %s %s on the existing grant", async (status, label, action) => {
    vi.mocked(fetchPersonalAssistantComputer).mockResolvedValue({ ...ready, status });
    vi.mocked(controlPersonalAssistantComputer).mockResolvedValue({ ...ready, status });
    await renderConversation(); await click(label);
    expect(controlPersonalAssistantComputer).toHaveBeenCalledWith({ grantId: "grant", action });
  });
  it("keeps the exact pending target and text before conversation confirmation", async () => {
    vi.mocked(fetchPersonalAssistantComputer).mockResolvedValue({ ...ready, status: "waiting_confirmation", pending: { id: "pending", action: "type_text", targetLabel: "收件人 小王", text: "完整内容" } });
    vi.mocked(confirmPersonalAssistantComputer).mockResolvedValue({ ...ready, status: "paused" });
    await renderConversation();
    expect(container.querySelector("dl")?.textContent).toContain("收件人 小王");
    expect(container.querySelector("pre")?.textContent).toBe("完整内容");
    await click("确认执行");
    expect(confirmPersonalAssistantComputer).toHaveBeenCalledWith({ grantId: "grant", pendingId: "pending", approved: true });
  });
  it("only closes after end succeeds and retains errors on failure", async () => {
    vi.mocked(fetchPersonalAssistantComputer).mockResolvedValue(ready);
    vi.mocked(controlPersonalAssistantComputer).mockRejectedValueOnce(new Error("结束失败")).mockResolvedValueOnce({ ...idle, status: "ended" });
    await renderConversation(); await click("结束");
    expect(container.textContent).toContain("结束失败");
    expect(collapse).not.toHaveBeenCalled();
    await click("结束");
    expect(controlPersonalAssistantComputer).toHaveBeenLastCalledWith({ grantId: "grant", action: "end" });
    expect(collapse).toHaveBeenCalledOnce();
  });
  it("uses an injected Launcher transport without sharing the Workbench cache", async () => {
    const launcher = { scope: "launcher" as const, state: vi.fn().mockResolvedValue(idle),
      windows: vi.fn().mockResolvedValue({ windows: [target] }), grant: vi.fn().mockResolvedValue(ready),
      control: vi.fn(), confirm: vi.fn() };
    client.setQueryData(queryKeys.personalAssistantComputer(), ready);
    await act(async () => root.render(<QueryClientProvider client={client}>
      <PersonalAssistantComputerPanel active onCollapse={collapse} transport={launcher} />
    </QueryClientProvider>));
    await settle();
    expect(launcher.state).toHaveBeenCalled();
    expect(launcher.windows).toHaveBeenCalled();
    expect(fetchPersonalAssistantComputer).not.toHaveBeenCalled();
    expect(button("授权这个窗口").disabled).toBe(true);
    await act(async () => (container.querySelector('[aria-pressed="false"]') as HTMLButtonElement).click());
    await act(async () => (container.querySelector('input[type="checkbox"]') as HTMLInputElement).click());
    await click("授权这个窗口");
    expect(launcher.grant).toHaveBeenCalledWith({ selectionId: "selection", allowVision: true });
    expect(grantPersonalAssistantComputer).not.toHaveBeenCalled();
    expect(client.getQueryData(queryKeys.personalAssistantComputer())).toEqual(ready);
  });
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
  it("switches fixed copy with shell language and preserves window metadata and control values", async () => {
    vi.mocked(fetchPersonalAssistantComputer).mockResolvedValue(ready);
    vi.mocked(controlPersonalAssistantComputer).mockResolvedValue(ready);
    await render();
    expect(container.querySelector('section[aria-label="电脑操作"]')).not.toBeNull();
    mockLang = "en";
    await render();
    expect(container.querySelector('section[aria-label="Computer controls"]')).not.toBeNull();
    expect(container.textContent).toContain("记事本");
    expect(container.textContent).toContain("今天的计划.txt");
    await click("Take control");
    expect(controlPersonalAssistantComputer).toHaveBeenCalledWith({ grantId: "grant", action: "takeover" });
  });
  it("localizes the fallback mutation error when the shell language changes", async () => {
    vi.mocked(fetchPersonalAssistantComputer).mockResolvedValue(ready);
    vi.mocked(controlPersonalAssistantComputer).mockRejectedValue("unavailable");
    await render();
    await click("暂停电脑操作");
    expect(container.textContent).toContain("操作未成功，请重试。");
    mockLang = "en";
    await render();
    expect(container.textContent).toContain("The operation failed. Please try again.");
    expect(container.textContent).not.toContain("操作未成功，请重试。");
  });
  it("localizes known pending actions while preserving target and input text", async () => {
    const waiting: ComputerState = { ...ready, status: "waiting_confirmation", pending: { id: "pending", action: "type_text", targetLabel: "收件人 小王", text: "今天的计划" } };
    vi.mocked(fetchPersonalAssistantComputer).mockResolvedValue(waiting);
    vi.mocked(confirmPersonalAssistantComputer).mockResolvedValue({ ...ready, status: "paused" });
    mockLang = "en";
    await render();
    expect(container.querySelector("dl")?.textContent).toContain("Type text");
    expect(container.querySelector("dl")?.textContent).toContain("收件人 小王");
    expect(container.querySelector("pre")?.textContent).toBe("今天的计划");
    await click("Confirm action");
    expect(confirmPersonalAssistantComputer).toHaveBeenCalledWith({ grantId: "grant", pendingId: "pending", approved: true });
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
  it("shows a localized placeholder for empty input and still allows explicit confirmation", async () => {
    const waiting: ComputerState = { ...ready, status: "waiting_confirmation", pending: { id: "pending", action: "set_value", targetLabel: "搜索框", text: "" } };
    vi.mocked(fetchPersonalAssistantComputer).mockResolvedValue(waiting);
    vi.mocked(confirmPersonalAssistantComputer).mockResolvedValue({ ...ready, status: "paused" });
    await render();
    expect(container.querySelector("pre")?.textContent).toBe("（空文本）");
    expect(container.querySelector("dl")?.textContent).toContain("设置内容");
    await click("确认执行");
    expect(confirmPersonalAssistantComputer).toHaveBeenCalledWith({ grantId: "grant", pendingId: "pending", approved: true });
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
