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
  vi.useRealTimers();
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

  it("keeps operator update available while warning about active tasks", async () => {
    api.getLauncherFreshness.mockResolvedValue({ ...available, activeWorkState: "active", activeWorkCount: 2 });
    await mount();
    await click("有新版本 · 请更新");
    expect(button("更新并重启").disabled).toBe(false);
    expect(document.body.textContent).toContain("更新会中断任务并保存已有记录");
    await click("更新并重启");
    await click("确认更新");
    expect(api.restartLatestLauncher).toHaveBeenCalledOnce();
  });

  it("blocks an update when task status cannot be confirmed", async () => {
    api.getLauncherFreshness.mockResolvedValue({ ...available, activeWorkState: "unknown" });
    await mount();
    await click("有新版本 · 请更新");
    expect(button("更新并重启").disabled).toBe(true);
    expect(api.restartLatestLauncher).not.toHaveBeenCalled();
  });

  it("allows confirmation using cached freshness while a background read is pending", async () => {
    api.getLauncherFreshness.mockResolvedValueOnce(available).mockImplementation(() => new Promise(() => {}));
    await mount();
    await click("有新版本 · 请更新");
    expect(button("更新并重启").disabled).toBe(false);
    await click("更新并重启");
    expect(button("确认更新").disabled).toBe(false);
    await click("确认更新");
    expect(api.restartLatestLauncher).toHaveBeenCalledOnce();
  });

  it("pauses polling during confirmation and resumes after cancellation", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await mount();
    await click("有新版本 · 请更新");
    await click("更新并重启");
    const callsBefore = api.getLauncherFreshness.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(api.getLauncherFreshness).toHaveBeenCalledTimes(callsBefore);
    expect(button("确认更新").disabled).toBe(false);
    await click("取消");
    await act(async () => { await vi.advanceTimersByTimeAsync(5_100); });
    expect(api.getLauncherFreshness.mock.calls.length).toBeGreaterThan(callsBefore);
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
