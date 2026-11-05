// @vitest-environment happy-dom
import React, { act, StrictMode, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LauncherNavigation } from "../../../app/LauncherNavigation";
import { LauncherAssistantTaskCards } from "./LauncherAssistantTaskCards";
import { LauncherTaskContext, type LauncherTaskModel } from "./LauncherTaskContext";
import { LauncherTaskNavigationSlot } from "./LauncherTaskNavigationSlot";
import { projectAssistantDispatchTasks } from "./assistantDispatchTasks";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | null, container: HTMLDivElement, client: QueryClient;
let model: LauncherTaskModel, returnToDesktop: ReturnType<typeof vi.fn>;

function LocationProbe() {
  const location = useLocation();
  return <output data-location>{location.pathname + location.search}</output>;
}
function Navigation({ lang = "zh", onNavigate, slotKey = 0 }: { lang?: "zh" | "en"; onNavigate?: () => void; slotKey?: number }) {
  return <LauncherNavigation lang={lang} items={[]} onNavigate={onNavigate}
    taskContent={<LauncherTaskNavigationSlot key={slotKey} lang={lang} onNavigate={onNavigate} />} />;
}
beforeEach(() => {
  const task = { ...projectAssistantDispatchTasks([{ projectId: "project-1", dispatchId: "dispatch-1", agentId: "worker-1",
    agentName: "Report Agent", title: "Weekly report", nativeTaskId: "native-1",
    receipt: { taskId: "native-1", status: "succeeded", shouldPoll: false } }]).tasks[0], kind: "dispatch" as const };
  model = { tasks: [task], loading: false, unavailable: false, refreshing: false, teamUnavailable: false, partial: false,
    invalid: 0, enabled: true, shown: 10, hasNextPage: false, loadingMore: false, selectedId: null, cleanableCount: 1,
    cleanupBusy: false, canCleanCompleted: true,
    refresh: vi.fn(async () => {}), more: vi.fn(async () => {}), openTask: vi.fn(), remove: vi.fn(), cleanCompleted: vi.fn(), reviewRequest: null };
  returnToDesktop = vi.fn(async () => {});
  vi.stubGlobal("vibelutionLauncher", { returnToDesktop });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => {
  await act(async () => { root?.unmount(); });
  container.remove(); client.clear(); vi.unstubAllGlobals();
});
async function settle() { await act(async () => new Promise(resolve => setTimeout(resolve, 20))); }
function button(label: string, within: ParentNode = document.body) {
  const found = [...within.querySelectorAll<HTMLButtonElement>("button")].find(node => node.textContent?.trim() === label || node.getAttribute("aria-label") === label);
  if (!found) throw new Error("Missing button: " + label);
  return found;
}
async function click(label: string, within: ParentNode = document.body) {
  await act(async () => { button(label, within).click(); }); await settle();
}
function assertReadySlot(within: ParentNode) {
  const navigation = within.querySelector("nav")!;
  const features = navigation.querySelector("[data-launcher-navigation-features]")!;
  const tasks = navigation.querySelector("[data-launcher-navigation-tasks]")!;
  const footer = navigation.querySelector("[data-launcher-navigation-footer]")!;
  expect([...navigation.children]).toEqual([features, tasks, footer]);
  const slot = tasks.querySelector<HTMLElement>("[data-launcher-task-navigation]")!;
  expect(slot).toBeTruthy();
  expect(tasks.querySelectorAll("[data-launcher-task-navigation]")).toHaveLength(1);
  expect(slot.querySelectorAll("[data-assistant-task-cards]")).toHaveLength(1);
  expect(slot.querySelectorAll("article")).toHaveLength(1);
  expect(slot.querySelector("nav,a,header,[data-assistant-task-refresh],[data-assistant-task-bulk-cleanup]")).toBeNull();
  expect(features.querySelectorAll("a")).toHaveLength(2);
  return slot;
}
async function renderNavigation(lang: "zh" | "en" = "zh", slotKey = 0) {
  await act(async () => { root!.render(<StrictMode><MemoryRouter initialEntries={["/launcher/assistant?panel=tasks"]}>
    <LocationProbe /><LauncherTaskContext.Provider value={model}>
      <Navigation lang={lang} slotKey={slotKey} />
    </LauncherTaskContext.Provider>
  </MemoryRouter></StrictMode>); }); await settle();
}

describe("Launcher task navigation slot", () => {
  it("keeps one task list through StrictMode, language and route updates while preserving navigation", async () => {
    await renderNavigation();
    const firstSlot = assertReadySlot(container), firstNavigation = container.querySelector("nav");
    expect(container.querySelectorAll("nav")).toHaveLength(1);
    expect(container.querySelector('a[href="/launcher/assistant"]')?.getAttribute("aria-current")).toBe("page");
    expect(container.querySelector('a[href="/launcher"]')?.textContent).toBe("项目与分支");
    expect(button("设置")).toBeTruthy();
    expect(button("回到桌面")).toBeTruthy();

    await renderNavigation("en");
    expect(assertReadySlot(container)).toBe(firstSlot);
    expect(container.querySelector('[role="tablist"]')?.getAttribute("aria-label")).toBe("Task categories");
    const projects = container.querySelector<HTMLAnchorElement>('a[href="/launcher"]')!;
    expect(projects.textContent).toBe("Projects & branches");
    await act(async () => { projects.click(); }); await settle();
    expect(container.querySelector("[data-location]")?.textContent).toBe("/launcher");
    expect(projects.getAttribute("aria-current")).toBe("page");

    const settings = button("Settings");
    await act(async () => { settings.focus(); settings.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); });
    const startup = await vi.waitFor(() => {
      const item = [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')].find(node => node.textContent?.trim() === "Startup settings");
      if (!item) throw new Error("Missing Startup settings menu item");
      return item;
    });
    await act(async () => { startup.click(); }); await settle();
    expect(container.querySelector("[data-location]")?.textContent).toBe("/launcher?view=settings");
    expect(settings.getAttribute("aria-current")).toBe("page");
    expect(assertReadySlot(container)).toBe(firstSlot);
    await click("Return to desktop");
    expect(returnToDesktop).toHaveBeenCalledTimes(1);

    await renderNavigation("en", 1);
    const replacement = assertReadySlot(container);
    expect(replacement).not.toBe(firstSlot);
    expect(firstSlot.isConnected).toBe(false);
    expect(container.querySelector("nav")).toBe(firstNavigation);
    expect(button("Settings")).toBeTruthy();
    expect(container.querySelector('a[href="/launcher"]')).toBeTruthy();
    await act(async () => { root!.unmount(); root = null; });
    expect(replacement.isConnected).toBe(false);
    expect(container.querySelector("[data-launcher-task-navigation]")).toBeNull();
  });

  it("renders task content directly without requiring a navigation wrapper", async () => {
    await act(async () => { root!.render(<LauncherTaskContext.Provider value={model}>
      <LauncherTaskNavigationSlot lang="zh" />
    </LauncherTaskContext.Provider>); }); await settle();
    const slot = container.querySelector("[data-launcher-task-navigation]")!;
    expect(slot.parentElement).toBe(container);
    expect(slot.querySelectorAll("[data-assistant-task-cards]")).toHaveLength(1);
    expect(slot.querySelector("article")?.textContent).toContain("Weekly report");
    expect(container.querySelector("nav")).toBeNull();
  });

  it("gives desktop and mobile one task list each over the same context", async () => {
    const onMobileNavigate = vi.fn();
    async function renderBoth() {
      await act(async () => { root!.render(<MemoryRouter><LauncherTaskContext.Provider value={model}>
        <div data-desktop><Navigation /></div>
        <div data-mobile><Navigation onNavigate={onMobileNavigate} /></div>
      </LauncherTaskContext.Provider></MemoryRouter>); }); await settle();
    }
    await renderBoth();
    const desktopSlot = assertReadySlot(container.querySelector("[data-desktop]")!);
    const mobileSlot = assertReadySlot(container.querySelector("[data-mobile]")!);
    expect(desktopSlot).not.toBe(mobileSlot);
    const desktopTask = desktopSlot.querySelector<HTMLButtonElement>('article button[aria-haspopup="dialog"]')!;
    const mobileTask = mobileSlot.querySelector<HTMLButtonElement>('article button[aria-haspopup="dialog"]')!;
    await act(async () => { desktopTask.click(); mobileTask.click(); });
    expect(model.openTask).toHaveBeenNthCalledWith(1, model.tasks[0], desktopTask);
    expect(model.openTask).toHaveBeenNthCalledWith(2, model.tasks[0], mobileTask);
    expect(onMobileNavigate).toHaveBeenCalledTimes(1);

    model = { ...model, selectedId: model.tasks[0].id };
    await renderBoth();
    expect(desktopTask.getAttribute("aria-expanded")).toBe("true");
    expect(mobileTask.getAttribute("aria-expanded")).toBe("true");
    expect(container.querySelectorAll("[data-assistant-task-cards]")).toHaveLength(2);
    expect(model.refresh).not.toHaveBeenCalled();
  });

  it("keeps task details and the conversation draft alive when mobile task navigation closes", async () => {
    const invoke = vi.fn(async ({ operation }: { operation: string }) => {
      if (operation === "status") return { assistant: { agentId: "assistant-1", directSessionId: "session-1", displayName: "助理" } };
      if (operation === "dispatches") return { dispatches: [{ projectId: "project-1", dispatchId: "dispatch-1", nativeTaskId: "native-1",
        agentId: "worker-1", title: "移动端任务", receipt: { taskId: "native-1", status: "succeeded", shouldPoll: false } }] };
      throw new Error("Unexpected assistant operation: " + operation);
    });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    function SharedNavigation() {
      const [mobileOpen, setMobileOpen] = useState(true);
      return <LauncherAssistantTaskCards>
        <div data-desktop><Navigation /></div>
        {mobileOpen ? <div data-mobile><Navigation onNavigate={() => setMobileOpen(false)} /></div> : null}
        <button onClick={() => setMobileOpen(true)}>Open mobile navigation</button>
        <textarea aria-label="聊天草稿" defaultValue="未发送的草稿" />
      </LauncherAssistantTaskCards>;
    }
    await act(async () => { root!.render(<QueryClientProvider client={client}><MemoryRouter><SharedNavigation /></MemoryRouter></QueryClientProvider>); });
    // Identity confirmation enables the dispatch query on a subsequent notification.
    await settle(); await settle();
    const desktopSlot = assertReadySlot(container.querySelector("[data-desktop]")!);
    const mobileSlot = assertReadySlot(container.querySelector("[data-mobile]")!);
    const draft = container.querySelector<HTMLTextAreaElement>('textarea[aria-label="聊天草稿"]')!;
    draft.value = "继续编辑的草稿";
    const trigger = mobileSlot.querySelector<HTMLButtonElement>('article button[aria-haspopup="dialog"]')!;
    expect(trigger).toBeTruthy();
    await act(async () => { trigger.click(); }); await settle();
    const dialog = document.body.querySelector<HTMLElement>('[role="dialog"][data-vui="launcher-task-detail"]')!;
    expect(dialog?.textContent).toContain("移动端任务");
    expect(container.querySelector("[data-mobile]")).toBeNull();
    expect(mobileSlot.isConnected).toBe(false);
    expect(desktopSlot.isConnected).toBe(true);
    expect(desktopSlot.querySelector('article button')?.getAttribute("aria-expanded")).toBe("true");
    expect(draft.value).toBe("继续编辑的草稿");
    await click("关闭", dialog);
    expect(document.body.querySelector('[data-vui="launcher-task-detail"]')).toBeNull();
    expect(container.querySelector('textarea[aria-label="聊天草稿"]')).toBe(draft);
    expect(draft.value).toBe("继续编辑的草稿");
    await click("Open mobile navigation");
    expect(assertReadySlot(container.querySelector("[data-mobile]")!)).not.toBe(mobileSlot);
    expect(assertReadySlot(container.querySelector("[data-desktop]")!)).toBe(desktopSlot);
    expect(container.querySelectorAll("[data-launcher-task-navigation]")).toHaveLength(2);
    expect(invoke.mock.calls.map(([request]) => request.operation)).toEqual(["status", "dispatches"]);
  });
});
