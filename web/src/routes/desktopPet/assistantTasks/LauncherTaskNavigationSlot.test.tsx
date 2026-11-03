// @vitest-environment happy-dom
import React, { act, StrictMode, useLayoutEffect, useRef, useState } from "react";
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
const taskHref = "/launcher/assistant?panel=tasks";
const scopedTaskHiding = '[&_a[href="/launcher/assistant?panel=tasks"]]:!hidden';
const taskHost = '[data-launcher-task-slot="true"]';
let root: Root | null, container: HTMLDivElement, client: QueryClient;
let model: LauncherTaskModel, returnToDesktop: ReturnType<typeof vi.fn>;

function LocationProbe() {
  const location = useLocation();
  return <output data-location>{location.pathname + location.search}</output>;
}
function Navigation({ lang = "zh" }: { lang?: "zh" | "en" }) {
  return <LauncherNavigation lang={lang} items={[]} />;
}
beforeEach(() => {
  const task = { ...projectAssistantDispatchTasks([{ projectId: "project-1", dispatchId: "dispatch-1", agentId: "worker-1",
    agentName: "Report Agent", title: "Weekly report", nativeTaskId: "native-1",
    receipt: { taskId: "native-1", status: "succeeded", shouldPoll: false } }]).tasks[0], kind: "dispatch" as const };
  model = { tasks: [task], loading: false, unavailable: false, refreshing: false, teamUnavailable: false, partial: false,
    invalid: 0, enabled: true, shown: 10, hasNextPage: false, loadingMore: false, selectedId: null, cleanableCount: 1,
    refresh: vi.fn(async () => {}), more: vi.fn(async () => {}), openTask: vi.fn(), cleanCompleted: vi.fn(), reviewRequest: null };
  returnToDesktop = vi.fn(async () => {});
  vi.stubGlobal("vibelutionLauncher", { returnToDesktop });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => {
  await act(async () => { root?.unmount(); });
  container.remove(); client.clear(); vi.unstubAllGlobals();
  document.querySelectorAll("[data-foreign-task-host]").forEach(node => node.remove());
});
async function settle() { await act(async () => new Promise(resolve => setTimeout(resolve, 20))); }
function button(label: string, within: ParentNode = document.body) {
  const found = [...within.querySelectorAll<HTMLButtonElement>("button")].find(node => node.textContent?.trim() === label || node.getAttribute("aria-label") === label);
  if (!found) throw new Error(`Missing button: ${label}`);
  return found;
}
async function click(label: string, within: ParentNode = document.body) {
  await act(async () => { button(label, within).click(); }); await settle();
}
function tasksAnchor(within: ParentNode) { return within.querySelector<HTMLAnchorElement>(`a[href="${taskHref}"]`)!; }
function assertReadySlot(within: ParentNode) {
  const slot = within.querySelector<HTMLElement>("[data-launcher-task-navigation]")!;
  expect(slot).toBeTruthy();
  expect(slot.querySelectorAll(taskHost)).toHaveLength(1);
  const host = slot.querySelector<HTMLElement>(taskHost)!;
  expect(tasksAnchor(slot).nextElementSibling).toBe(host);
  expect(host.querySelector("[data-assistant-task-cards]")).toBeTruthy();
  // happy-dom does not compile Tailwind; only assert the narrowly scoped DOM contract here.
  expect(slot.classList.contains(scopedTaskHiding)).toBe(true);
  return host;
}
async function renderNavigation(lang: "zh" | "en" = "zh", slotKey = 0) {
  await act(async () => { root!.render(<StrictMode><MemoryRouter initialEntries={["/launcher/assistant"]}>
    <LocationProbe /><LauncherTaskContext.Provider value={model}>
      <LauncherTaskNavigationSlot key={slotKey} lang={lang}><Navigation lang={lang} /></LauncherTaskNavigationSlot>
    </LauncherTaskContext.Provider>
  </MemoryRouter></StrictMode>); }); await settle();
}

describe("Launcher task navigation slot", () => {
  it("keeps one owned host through StrictMode, language and route updates, and remounts without losing existing navigation", async () => {
    const foreign = document.createElement("div");
    foreign.dataset.launcherTaskSlot = "true"; foreign.dataset.foreignTaskHost = "true"; document.body.appendChild(foreign);
    await renderNavigation();
    const firstHost = assertReadySlot(container);
    expect(container.querySelectorAll("nav")).toHaveLength(1);
    expect(tasksAnchor(container).textContent).toBe("任务");
    expect(container.querySelector('a[href="/launcher"]')?.textContent).toBe("项目与分支");
    expect(button("设置")).toBeTruthy();
    expect(button("回到桌面")).toBeTruthy();

    await renderNavigation("en");
    expect(assertReadySlot(container)).toBe(firstHost);
    const projects = container.querySelector<HTMLAnchorElement>('a[href="/launcher"]')!;
    expect(projects.textContent).toBe("Projects & branches");
    expect(tasksAnchor(container).textContent).toBe("Tasks");
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
    expect(assertReadySlot(container)).toBe(firstHost);
    await click("Return to desktop");
    expect(returnToDesktop).toHaveBeenCalledTimes(1);

    await renderNavigation("en", 1);
    const replacement = assertReadySlot(container);
    expect(replacement).not.toBe(firstHost);
    expect(firstHost.isConnected).toBe(false);
    expect(button("Settings")).toBeTruthy();
    expect(container.querySelector('a[href="/launcher"]')).toBeTruthy();
    await act(async () => { root!.unmount(); root = null; });
    expect(replacement.isConnected).toBe(false);
    expect(foreign.isConnected).toBe(true);
  });

  it.each(["missing", "duplicate"] as const)("leaves the original navigation unhidden when its task anchor is %s", async condition => {
    function AmbiguousNavigation() {
      const ref = useRef<HTMLDivElement>(null);
      useLayoutEffect(() => {
        const anchor = tasksAnchor(ref.current!);
        if (condition === "missing") {
          anchor.setAttribute("href", "/launcher/legacy-tasks");
          return () => { anchor.setAttribute("href", taskHref); };
        }
        const duplicate = anchor.cloneNode(true);
        anchor.after(duplicate);
        return () => { duplicate.parentNode?.removeChild(duplicate); };
      }, []);
      return <div ref={ref}><Navigation /></div>;
    }
    await act(async () => { root!.render(<MemoryRouter><LauncherTaskContext.Provider value={model}>
      <LauncherTaskNavigationSlot lang="zh"><AmbiguousNavigation /></LauncherTaskNavigationSlot>
    </LauncherTaskContext.Provider></MemoryRouter>); }); await settle();
    const slot = container.querySelector<HTMLElement>("[data-launcher-task-navigation]")!;
    expect(slot.querySelectorAll(taskHost)).toHaveLength(0);
    expect(slot.classList.contains(scopedTaskHiding)).toBe(false);
    expect(slot.querySelector("[data-assistant-task-cards]")).toBeNull();
    const originalTasks = [...slot.querySelectorAll("a")].filter(node => node.textContent === "任务");
    expect(originalTasks).toHaveLength(condition === "missing" ? 1 : 2);
    for (const anchor of originalTasks) {
      expect(anchor.hidden).toBe(false);
      expect(anchor.getAttribute("aria-hidden")).toBeNull();
    }
    expect(slot.querySelector('a[href="/launcher"]')?.textContent).toBe("项目与分支");
    expect(button("设置", slot)).toBeTruthy();
    expect(button("回到桌面", slot)).toBeTruthy();
  });

  it("gives desktop and mobile navigation one host each over the same task model", async () => {
    const onMobileNavigate = vi.fn();
    await act(async () => { root!.render(<MemoryRouter><LauncherTaskContext.Provider value={model}>
      <div data-desktop><LauncherTaskNavigationSlot lang="zh"><Navigation /></LauncherTaskNavigationSlot></div>
      <div data-mobile><LauncherTaskNavigationSlot lang="zh" onNavigate={onMobileNavigate}><Navigation /></LauncherTaskNavigationSlot></div>
    </LauncherTaskContext.Provider></MemoryRouter>); }); await settle();
    const desktop = container.querySelector("[data-desktop]")!, mobile = container.querySelector("[data-mobile]")!;
    const desktopHost = assertReadySlot(desktop), mobileHost = assertReadySlot(mobile);
    expect(desktopHost).not.toBe(mobileHost);
    const desktopTask = desktopHost.querySelector<HTMLButtonElement>('article button[aria-haspopup="dialog"]')!;
    const mobileTask = mobileHost.querySelector<HTMLButtonElement>('article button[aria-haspopup="dialog"]')!;
    await act(async () => { desktopTask.click(); mobileTask.click(); });
    expect(model.openTask).toHaveBeenNthCalledWith(1, model.tasks[0], desktopTask);
    expect(model.openTask).toHaveBeenNthCalledWith(2, model.tasks[0], mobileTask);
    expect(onMobileNavigate).toHaveBeenCalledTimes(1);
    await click("刷新", desktopHost); await click("刷新", mobileHost);
    expect(model.refresh).toHaveBeenCalledTimes(2);
  });

  it("keeps the controlled task dialog alive when mobile navigation closes and cleans only the mobile host", async () => {
    const invoke = vi.fn(async ({ operation }: { operation: string }) => {
      if (operation === "status") return { assistant: { agentId: "assistant-1", directSessionId: "session-1", displayName: "助理" } };
      if (operation === "dispatches") return { dispatches: [{ projectId: "project-1", dispatchId: "dispatch-1", nativeTaskId: "native-1",
        agentId: "worker-1", title: "移动端任务", receipt: { taskId: "native-1", status: "succeeded", shouldPoll: false } }] };
      throw new Error(`Unexpected assistant operation: ${operation}`);
    });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    function SharedNavigation() {
      const [mobileOpen, setMobileOpen] = useState(true);
      return <LauncherAssistantTaskCards>
        <div data-desktop><LauncherTaskNavigationSlot lang="zh"><Navigation /></LauncherTaskNavigationSlot></div>
        {mobileOpen ? <div data-mobile><LauncherTaskNavigationSlot lang="zh" onNavigate={() => setMobileOpen(false)}><Navigation /></LauncherTaskNavigationSlot></div> : null}
        <button onClick={() => setMobileOpen(true)}>Open mobile navigation</button>
      </LauncherAssistantTaskCards>;
    }
    await act(async () => { root!.render(<QueryClientProvider client={client}><MemoryRouter><SharedNavigation /></MemoryRouter></QueryClientProvider>); });
    // Identity confirmation enables the dispatch query on a subsequent notification.
    await settle(); await settle();
    const desktop = container.querySelector("[data-desktop]")!;
    const desktopHost = assertReadySlot(desktop), mobileHost = assertReadySlot(container.querySelector("[data-mobile]")!);
    const trigger = mobileHost.querySelector<HTMLButtonElement>('article button[aria-haspopup="dialog"]')!;
    expect(trigger).toBeTruthy();
    await act(async () => { trigger.click(); }); await settle();
    const dialog = document.body.querySelector<HTMLElement>('[role="dialog"][data-vui="launcher-task-detail"]')!;
    expect(dialog?.textContent).toContain("移动端任务");
    expect(container.querySelector("[data-mobile]")).toBeNull();
    expect(mobileHost.isConnected).toBe(false);
    expect(desktopHost.isConnected).toBe(true);
    expect(desktopHost.querySelector('article button')?.getAttribute("aria-expanded")).toBe("true");
    await click("关闭", dialog);
    expect(document.body.querySelector('[data-vui="launcher-task-detail"]')).toBeNull();
    await click("Open mobile navigation");
    const newMobileHost = assertReadySlot(container.querySelector("[data-mobile]")!);
    expect(newMobileHost).not.toBe(mobileHost);
    expect(assertReadySlot(desktop)).toBe(desktopHost);
    expect(container.querySelectorAll(taskHost)).toHaveLength(2);
    expect(invoke.mock.calls.map(([request]) => request.operation)).toEqual(["status", "dispatches"]);
  });
});
