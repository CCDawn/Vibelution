// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { returnLauncherToDesktop } from "../api/launcher";
import { LauncherNavigation } from "./LauncherNavigation";

vi.mock("../api/launcher", () => ({ returnLauncherToDesktop: vi.fn() }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root, host: HTMLDivElement;
beforeEach(() => { vi.resetAllMocks(); host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(async () => { await act(async () => root.unmount()); host.remove(); });

async function render(options: { onNavigate?: () => void; updateAvailable?: boolean } = {}, entry = "/launcher/assistant") {
  const router = createMemoryRouter([{ path: "*", element: <LauncherNavigation lang="zh" items={[]} {...options} /> }],
    { initialEntries: [entry] });
  await act(async () => root.render(<RouterProvider router={router} />));
  return router;
}
function link(label: string): HTMLAnchorElement {
  const found = [...host.querySelectorAll("a")].find(node => node.textContent?.trim() === label);
  if (!found) throw new Error(`Missing link ${label}`);
  return found;
}

describe("Launcher navigation", () => {
  it("navigates and marks the selected assistant and Launcher pages in one rail", async () => {
    const router = await render();
    const nav = host.querySelector('nav[aria-label="Launcher 功能导航"]')!;
    expect(nav.querySelector('[aria-label="个人助理功能"]')).toBeTruthy();
    expect(nav.textContent).toContain("个人助理");
    expect(nav.textContent).toContain("Launcher");
    expect(nav.textContent).not.toContain("平台概览");
    expect(nav.textContent).not.toContain("派遣与回执");
    for (const label of ["浏览器", "事务", "待办与提醒", "电脑操作", "对话偏好", "助理设置", "诊断", "维护", "启动设置", "版本更新"]) expect(nav.textContent).not.toContain(label);
    expect([...nav.querySelectorAll("a")].map(node => node.textContent?.trim())).toEqual(["对话", "项目与分支"]);
    for (const [label, path] of [["项目与分支", "/launcher"], ["对话", "/launcher/assistant"]]) {
      await act(async () => link(label).dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 })));
      expect(router.state.location.pathname + router.state.location.search).toBe(path);
      expect(link(label).getAttribute("aria-current")).toBe("page");
      expect(nav.querySelectorAll('a[aria-current="page"]')).toHaveLength(1);
    }
  });
  it("selects the single conversation entry for legacy browser URLs", async () => {
    await render({}, "/launcher/assistant?panel=browser");
    expect(link("对话").getAttribute("aria-current")).toBe("page");
    expect([...host.querySelectorAll("a")].map(node => node.textContent?.trim())).toEqual(["对话", "项目与分支"]);
  });

  it("opens settings from the keyboard and keeps every destination reachable", async () => {
    const onNavigate = vi.fn();
    const router = await render({ onNavigate, updateAvailable: true });
    const trigger = [...host.querySelectorAll("button")].find(node => node.textContent?.includes("设置"))!;
    expect(trigger.textContent).toContain("有新版");
    for (const [label, path] of [["诊断", "/launcher/tools?view=diagnostics"], ["维护", "/launcher/tools?view=maintenance"], ["启动设置", "/launcher?view=settings"], ["版本更新", "/launcher/updates"]]) {
      await act(async () => { trigger.focus(); trigger.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); });
      const item = await vi.waitFor(() => {
        const found = [...document.querySelectorAll('[role="menuitem"]')].find(node => node.textContent?.trim() === label);
        if (!found) throw new Error(`Missing menu item ${label}`);
        return found as HTMLElement;
      });
      await act(async () => item.click());
      expect(router.state.location.pathname + router.state.location.search).toBe(path);
      expect(trigger.getAttribute("aria-current")).toBe("page");
    }
    expect(onNavigate).toHaveBeenCalledTimes(4);
  });

  it("supports keyboard selection and Escape in the settings menu", async () => {
    const router = await render();
    const trigger = [...host.querySelectorAll("button")].find(node => node.textContent?.trim() === "设置")!;
    await act(async () => { trigger.focus(); trigger.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true })); });
    const item = await vi.waitFor(() => {
      const found = [...document.querySelectorAll('[role="menuitem"]')].find(node => node.textContent?.trim() === "启动设置");
      if (!found) throw new Error("Missing settings item");
      return found as HTMLElement;
    });
    await act(async () => { item.focus(); item.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); });
    expect(router.state.location.pathname + router.state.location.search).toBe("/launcher?view=settings");
    await act(async () => { trigger.focus(); trigger.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); });
    const menu = await vi.waitFor(() => {
      const found = document.querySelector('[role="menu"]');
      if (!found) throw new Error("Missing settings menu");
      return found;
    });
    await act(async () => menu.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
    await vi.waitFor(() => { expect(document.querySelector('[role="menu"]')).toBeNull(); expect(document.activeElement).toBe(trigger); });
  });

  it("requests return once while pending, reports failure and allows retry", async () => {
    let reject!: (error: Error) => void;
    vi.mocked(returnLauncherToDesktop).mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail; }))
      .mockResolvedValueOnce(undefined);
    await render();
    const button = [...host.querySelectorAll("button")].find(node => node.textContent?.includes("回到桌面"))!;
    await act(async () => { button.click(); button.click(); });
    expect(returnLauncherToDesktop).toHaveBeenCalledTimes(1);
    await act(async () => reject(new Error("返回失败")));
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("返回失败");
    await act(async () => button.click());
    expect(returnLauncherToDesktop).toHaveBeenCalledTimes(2);
    expect(host.querySelector('[role="alert"]')).toBeNull();
  });
});
