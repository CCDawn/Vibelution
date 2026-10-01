/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import shellSource from "./LauncherShell.tsx?raw";
import homeSource from "../routes/LauncherRoute.tsx?raw";
import { LauncherUpdateTopbar } from "./LauncherUpdateTopbar";

const api = vi.hoisted(() => ({ getLauncherFreshness: vi.fn(), restartLatestLauncher: vi.fn() }));
vi.mock("../api/launcher", () => api);
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const available = { current: false, label: "stale", updateAvailable: true, activeWorkState: "idle", activeWorkCount: 0, runningShort: "aaaa", headShort: "bbbb" };
let root: Root;
let host: HTMLDivElement;
let client: QueryClient;

async function mount() {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  await act(async () => root.render(<QueryClientProvider client={client}><LauncherUpdateTopbar lang="zh" branchName="main" /></QueryClientProvider>));
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
}

function button(text: string) {
  const found = [...document.querySelectorAll("button")].find((item) => item.textContent?.trim() === text);
  expect(found, `button: ${text}`).toBeTruthy();
  return found!;
}

async function click(text: string) {
  await act(async () => { button(text).click(); await new Promise((resolve) => setTimeout(resolve, 10)); });
}

beforeEach(() => {
  api.getLauncherFreshness.mockReset().mockResolvedValue(available);
  api.restartLatestLauncher.mockReset().mockResolvedValue({ accepted: true, message: "accepted" });
});
afterEach(async () => {
  await act(async () => root?.unmount());
  host?.remove();
  client?.clear();
});

describe("shared Launcher update topbar", () => {
  it("keeps the reminder after closing details and never updates automatically", async () => {
    await mount();
    await click("有新版本 · 请更新");
    expect(document.body.textContent).toContain("新版 Launcher 已就绪");
    await click("关闭详情");
    expect(button("有新版本 · 请更新")).toBeTruthy();
    expect(api.restartLatestLauncher).not.toHaveBeenCalled();
  });

  it("requires confirmation and stays busy until replacement closes the window", async () => {
    await mount();
    await click("有新版本 · 请更新");
    await click("更新并重启");
    expect(api.restartLatestLauncher).not.toHaveBeenCalled();
    await click("确认更新");
    expect(api.restartLatestLauncher).toHaveBeenCalledOnce();
    expect(document.body.textContent).toContain("正在构建前端和桌面壳");
    expect(host.querySelector("[data-testid='launcher-update-trigger']")?.textContent).toContain("正在更新");
  });

  it.each(["active", "unknown"])("blocks the update button when task status is %s", async (state) => {
    api.getLauncherFreshness.mockResolvedValue({ ...available, activeWorkState: state, activeWorkCount: state === "active" ? 2 : 0 });
    await mount();
    await click("有新版本 · 请更新");
    expect(button(state === "active" ? "任务完成后更新" : "更新并重启").disabled).toBe(true);
    expect(api.restartLatestLauncher).not.toHaveBeenCalled();
  });

  it("treats accepted:false as a visible failure and allows a confirmed retry", async () => {
    api.restartLatestLauncher.mockResolvedValueOnce({ accepted: false, message: "有进行中的任务，无法重启 Vibelution。" });
    await mount();
    await click("有新版本 · 请更新");
    await click("更新并重启");
    await click("确认更新");
    expect(document.body.textContent).toContain("有进行中的任务，无法重启");
    expect(host.textContent).toContain("更新失败 · 重试");
    await click("重试更新");
    await click("确认更新");
    expect(api.restartLatestLauncher).toHaveBeenCalledTimes(2);
  });

  it("shows failed version reads as unknown instead of up to date", async () => {
    api.getLauncherFreshness.mockRejectedValue(new Error("offline"));
    await mount();
    expect(host.textContent).toContain("版本检测失败");
    await click("版本检测失败");
    expect(document.body.textContent).toContain("检测失败不代表已经是最新版本");
    expect(api.restartLatestLauncher).not.toHaveBeenCalled();
  });

  it("uses one shared shell entry for home and tools instead of a dismissible home-only dialog", () => {
    expect(shellSource).toContain("<LauncherUpdateTopbar");
    expect(shellSource).toContain("<Outlet />");
    expect(homeSource).not.toContain("updateDismissed");
    expect(homeSource).not.toContain("restartLatestLauncher");
    expect(homeSource).not.toContain("vibelution.launcher-update-dismissed");
  });
});
