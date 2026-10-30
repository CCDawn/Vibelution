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

async function render() {
  const router = createMemoryRouter([{ path: "*", element: <LauncherNavigation lang="zh" items={[]} /> }],
    { initialEntries: ["/launcher/assistant"] });
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
    for (const [label, path] of [["电脑操作", "/launcher/assistant?panel=computer"], ["助理设置", "/launcher/assistant?panel=assistant-settings"],
      ["项目与分支", "/launcher"], ["启动设置", "/launcher?view=settings"], ["版本更新", "/launcher/updates"]]) {
      await act(async () => link(label).dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 })));
      expect(router.state.location.pathname + router.state.location.search).toBe(path);
      expect(link(label).getAttribute("aria-current")).toBe("page");
      expect(nav.querySelectorAll('a[aria-current="page"]')).toHaveLength(1);
    }
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
