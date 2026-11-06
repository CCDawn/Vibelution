/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import shellSource from "./LauncherShell.tsx?raw";
import homeSource from "../routes/LauncherRoute.tsx?raw";
import updatesSource from "../routes/LauncherUpdatesRoute.tsx?raw";
import navigationSource from "./LauncherNavigation.tsx?raw";
import { LauncherUpdateTopbar } from "./LauncherUpdateTopbar";
import { queryKeys } from "../api/queryKeys";

const api = vi.hoisted(() => ({ getLauncherFreshness: vi.fn(), restartLatestLauncher: vi.fn() }));
vi.mock("../api/launcher", () => api);
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const available = { current: false, label: "stale", updateAvailable: true, activeWorkState: "idle", activeWorkCount: 0,
  runningShort: "misleading-commit", headShort: "misleading-commit", availableBuildState: "ready",
  runningBuild: { kind: "unpackaged", id: "a".repeat(64), electronTree: "c".repeat(40) },
  availableBuild: { kind: "unpackaged", id: "b".repeat(64), electronTree: "d".repeat(40) } };
let root: Root;
let host: HTMLDivElement;
let client: QueryClient;

async function mount(cached = false) {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  if (cached) client.setQueryData(queryKeys.launcherFreshness(), available);
  await act(async () => root.render(<QueryClientProvider client={client}><LauncherUpdateTopbar lang="zh" /></QueryClientProvider>));
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
  it("shows not-built honestly while keeping the existing prepare-and-restart action", async () => {
    api.getLauncherFreshness.mockResolvedValue({ ...available, availableBuild: null, availableBuildState: "not_built" });
    await mount();
    expect(host.textContent).toContain("有更新，待构建");
    expect(host.textContent).not.toContain("bbbbbbbbbbbb");
    expect(host.textContent).not.toContain("misleading-commit");
    expect(button("更新并重启")).toBeTruthy();
    expect(api.restartLatestLauncher).not.toHaveBeenCalled();
  });

  it("does not relabel legacy commit fields as real builds", async () => {
    api.getLauncherFreshness.mockResolvedValue({ current: false, updateAvailable: true, label: "old bridge",
      runningShort: "fake-current", headShort: "fake-available" });
    await mount();
    expect(host.textContent).not.toContain("fake-current");
    expect(host.textContent).not.toContain("fake-available");
    expect(host.querySelectorAll("dd")[0]?.textContent).toBe("未知");
  });

  it("rechecks a recently cached update when the Launcher opens", async () => {
    api.getLauncherFreshness.mockResolvedValue({ ...available, current: true, shellStale: false, updateAvailable: false });
    await mount(true);
    expect(api.getLauncherFreshness).toHaveBeenCalledOnce();
    expect(host.textContent).toContain("已是最新版本");
  });

  it("clears an old update immediately on focus without waiting for the poll", async () => {
    await mount();
    api.getLauncherFreshness.mockResolvedValue({ ...available, current: true, shellStale: false, updateAvailable: false });
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
      await new Promise((resolve) => setTimeout(resolve, 10));
    });
    expect(host.textContent).toContain("已是最新版本");
    expect(host.textContent).not.toContain("有新版本");
    expect(api.restartLatestLauncher).not.toHaveBeenCalled();
  });
  it("shows the update directly and confirms exactly once before invoking restart", async () => {
    api.getLauncherFreshness.mockResolvedValue({ ...available, activeWorkState: "active", activeWorkCount: 2 });
    await mount();
    expect(host.textContent).toContain("发现更新");
    expect(host.textContent).toContain("桌面构建 aaaaaaaaaaaa");
    expect(host.textContent).toContain("桌面构建 bbbbbbbbbbbb");
    expect(host.textContent).not.toContain("misleading-commit");
    expect(host.querySelector('[data-testid="launcher-topbar"]')).toBeNull();
    await click("更新并重启");
    expect(document.querySelectorAll('[role="dialog"]')).toHaveLength(1);
    expect(document.body.textContent).toContain("更新会中断任务并保存已有记录");
    expect(api.restartLatestLauncher).not.toHaveBeenCalled();
    await click("确认更新");
    expect(api.restartLatestLauncher).toHaveBeenCalledOnce();
    expect(host.textContent).toContain("准备中");
  });

  it("keeps a real update failure across remount and retries after confirmation", async () => {
    api.restartLatestLauncher.mockResolvedValueOnce({ accepted: false, message: "构建失败" });
    await mount();
    await click("更新并重启");
    await click("确认更新");
    expect(host.textContent).toContain("构建失败");
    await act(async () => root.render(<QueryClientProvider client={client}><div /></QueryClientProvider>));
    await act(async () => root.render(<QueryClientProvider client={client}><LauncherUpdateTopbar lang="zh" /></QueryClientProvider>));
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
    expect(host.textContent).toContain("更新失败");
    await click("重试更新");
    await click("确认更新");
    expect(api.restartLatestLauncher).toHaveBeenCalledTimes(2);
  });

  it("keeps an accepted update busy after leaving and returning to the page", async () => {
    await mount();
    await click("更新并重启");
    await click("确认更新");
    await act(async () => root.render(<QueryClientProvider client={client}><div /></QueryClientProvider>));
    await act(async () => root.render(<QueryClientProvider client={client}><LauncherUpdateTopbar lang="zh" /></QueryClientProvider>));
    expect(host.textContent).toContain("准备中");
    expect(button("准备中…").disabled).toBe(true);
    expect(api.restartLatestLauncher).toHaveBeenCalledOnce();
  });

  it("offers a new check when the version is unknown", async () => {
    api.getLauncherFreshness.mockResolvedValue({ current: null, label: "unknown" });
    await mount();
    expect(host.textContent).toContain("无法确认版本");
    expect(host.textContent).not.toContain("已是最新版本");
    await click("重新检测");
    expect(api.getLauncherFreshness).toHaveBeenCalledTimes(2);
    expect(api.restartLatestLauncher).not.toHaveBeenCalled();
  });

  it("recovers an accepted update when a later native read is idle on the old version", async () => {
    api.getLauncherFreshness.mockResolvedValue({ ...available, updateInProgress: true });
    await mount();
    // The native owner may report an automatic update before this click.
    api.getLauncherFreshness.mockResolvedValue({ ...available, updateInProgress: false });
    await act(async () => { window.dispatchEvent(new Event("focus")); await new Promise((resolve) => setTimeout(resolve, 10)); });
    await click("更新并重启");
    api.getLauncherFreshness.mockResolvedValue({ ...available, updateInProgress: true });
    await click("确认更新");
    expect(button("准备中…").disabled).toBe(true);
    await act(async () => root.render(<QueryClientProvider client={client}><div /></QueryClientProvider>));
    await act(async () => root.render(<QueryClientProvider client={client}><LauncherUpdateTopbar lang="zh" /></QueryClientProvider>));
    api.getLauncherFreshness.mockResolvedValue({ ...available, updateInProgress: false, refreshError: "保存任务失败" });
    await act(async () => { window.dispatchEvent(new Event("focus")); await new Promise((resolve) => setTimeout(resolve, 20)); });
    expect(host.textContent).toContain("更新失败");
    expect(host.textContent).toContain("保存任务失败");
    expect(button("重试更新").disabled).toBe(false);
    expect(api.restartLatestLauncher).toHaveBeenCalledOnce();
    await click("重试更新");
    await click("确认更新");
    expect(api.restartLatestLauncher).toHaveBeenCalledTimes(2);
  });

  it("does not let an idle freshness read release a still-pending update request", async () => {
    let rejectUpdate!: (reason: Error) => void;
    api.restartLatestLauncher.mockImplementationOnce(() => new Promise((_, reject) => { rejectUpdate = reject; }));
    api.getLauncherFreshness.mockResolvedValue({ ...available, updateInProgress: false });
    await mount();
    await click("更新并重启");
    await click("确认更新");
    await act(async () => { await client.refetchQueries({ queryKey: queryKeys.launcherFreshness() }); });
    expect(button("准备中…").disabled).toBe(true);
    expect(api.restartLatestLauncher).toHaveBeenCalledOnce();
    await act(async () => { rejectUpdate(new Error("构建失败")); await new Promise((resolve) => setTimeout(resolve, 10)); });
    expect(button("重试更新").disabled).toBe(false);
  });

  it("keeps update acceptance separate from a failed status read and permits read-only recovery", async () => {
    await mount();
    await click("更新并重启");
    api.getLauncherFreshness.mockRejectedValue(new Error("offline"));
    await click("确认更新");
    expect(host.textContent).toContain("无法确认更新状态");
    expect(button("准备中…").disabled).toBe(true);
    expect(button("重新检测").disabled).toBe(false);
    api.getLauncherFreshness.mockResolvedValue({ ...available, updateInProgress: false });
    await click("重新检测");
    expect(host.textContent).toContain("Launcher 仍在运行旧版本");
    expect(button("重试更新").disabled).toBe(false);
    expect(api.restartLatestLauncher).toHaveBeenCalledOnce();
  });

  it("clears historical success after the native owner confirms the current version", async () => {
    await mount();
    await click("更新并重启");
    await click("确认更新");
    api.getLauncherFreshness.mockResolvedValue({ ...available, current: true, updateAvailable: false, updateInProgress: false });
    await act(async () => { window.dispatchEvent(new Event("focus")); await new Promise((resolve) => setTimeout(resolve, 20)); });
    expect(host.textContent).toContain("已是最新版本");
    expect(host.textContent).not.toContain("准备中");
    expect(api.restartLatestLauncher).toHaveBeenCalledOnce();
  });

  it("recovers through polling without a window focus event after acceptance", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await mount();
    await click("更新并重启");
    await click("确认更新");
    expect(button("准备中…").disabled).toBe(true);
    const readsBefore = api.getLauncherFreshness.mock.calls.length;
    api.getLauncherFreshness.mockResolvedValue({ ...available, updateInProgress: false, refreshError: "保存任务失败" });
    await act(async () => { await vi.advanceTimersByTimeAsync(5_100); });
    expect(api.getLauncherFreshness.mock.calls.length).toBeGreaterThan(readsBefore);
    expect(host.textContent).toContain("更新失败");
    expect(button("重试更新").disabled).toBe(false);
    expect(api.restartLatestLauncher).toHaveBeenCalledOnce();
  });

  it("reports unknown after a cached current version fails a background refresh", async () => {
    api.getLauncherFreshness.mockResolvedValueOnce({ ...available, current: true, updateAvailable: false }).mockRejectedValue(new Error("offline"));
    await mount();
    expect(host.textContent).toContain("已是最新版本");
    await act(async () => { window.dispatchEvent(new Event("focus")); await new Promise((resolve) => setTimeout(resolve, 10)); });
    expect(host.textContent).toContain("无法确认版本");
    expect(host.textContent).not.toContain("已是最新版本");
    expect(button("重新检测")).toBeTruthy();
  });

  it("shows rechecking and preserves the real update error", async () => {
    api.restartLatestLauncher.mockResolvedValueOnce({ accepted: false, message: "构建失败" });
    await mount();
    api.getLauncherFreshness.mockRejectedValueOnce(new Error("offline"));
    await click("更新并重启");
    await click("确认更新");
    expect(host.textContent).toContain("构建失败");
    expect(host.textContent).toContain("无法确认版本");
    let resolve!: (value: typeof available) => void;
    api.getLauncherFreshness.mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
    await click("重新检测");
    expect(host.textContent).toContain("正在检测");
    expect(host.textContent).toContain("构建失败");
    await act(async () => { resolve(available); await new Promise((done) => setTimeout(done, 10)); });
    expect(host.textContent).toContain("更新失败");
    expect(host.textContent).toContain("构建失败");
    expect(button("重试更新")).toBeTruthy();
  });

  it("pauses polling during confirmation and resumes after cancellation", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await mount();
    await click("更新并重启");
    const callsBefore = api.getLauncherFreshness.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(api.getLauncherFreshness).toHaveBeenCalledTimes(callsBefore);
    await click("取消");
    const afterCancel = api.getLauncherFreshness.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(61_000); });
    expect(api.getLauncherFreshness.mock.calls.length).toBeGreaterThan(afterCancel);
  });

  it("keeps updates at a stable sidebar destination and preserves the shared update workflow", () => {
    expect(updatesSource).toContain("<LauncherUpdateTopbar");
    expect(navigationSource).toContain("/launcher/updates");
    expect(shellSource).toContain("<LauncherTitlebar");
    expect(shellSource).toContain("<Outlet />");
    expect(homeSource).not.toContain("updateDismissed");
    expect(homeSource).not.toContain("restartLatestLauncher");
    expect(homeSource).not.toContain("vibelution.launcher-update-dismissed");
  });
});
