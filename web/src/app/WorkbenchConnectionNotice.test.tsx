/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import shellSource from "./AppShell.tsx?raw";
import shellStylesSource from "./AppShell.styles.ts?raw";
import { connectionFailureIsPersistent, WorkbenchConnectionNotice } from "./WorkbenchConnectionNotice";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
let root: Root;
const recover = vi.fn();
const retry = vi.fn();

async function render(unavailable = true, desktopShell = true, recovering = false) {
  await act(async () => root.render(<><WorkbenchConnectionNotice unavailable={unavailable} lang="zh" desktopShell={desktopShell} recovering={recovering} onRecover={recover} onRetry={retry} /><textarea aria-label="draft" defaultValue="未发送的草稿" /></>));
}
// The panel is portalled, so panel assertions read document.body, not the host.
function panelText() { return document.body.textContent ?? ""; }
function button(text: string) { return [...document.body.querySelectorAll("button")].find(x => x.textContent?.trim() === text); }

beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); recover.mockReset(); retry.mockReset(); });
afterEach(async () => { await act(async () => root.unmount()); host.remove(); });

describe("workbench connection recovery", () => {
  it("retains the editor and draft across loss and recovery without automatically restarting", async () => {
    await render(false);
    const draft = host.querySelector("textarea")!;
    draft.value = "断开前输入";
    await render(true);
    expect(host.querySelector("textarea")).toBe(draft);
    expect(draft.value).toBe("断开前输入");
    expect(panelText()).toContain("工作台服务未连接");
    expect(panelText()).not.toContain("服务已停止");
    expect(recover).not.toHaveBeenCalled();
    await render(false);
    expect(host.querySelector("[data-testid=workbench-connection-notice]")).toBeNull();
    expect(draft.value).toBe("断开前输入");
  });

  it("expands itself when health breaks instead of waiting for a click", async () => {
    await render(true);
    expect(host.querySelector("[data-testid=workbench-connection-notice]")?.getAttribute("aria-expanded")).toBe("true");
    expect(panelText()).toContain("工作台服务未连接");
  });

  it("uses explicit recovery and connection checks as separate actions", async () => {
    await render();
    expect(panelText()).toContain("先停止任务并保存已有记录");
    await act(async () => button("检查连接")!.click());
    expect(retry).toHaveBeenCalledOnce();
    expect(recover).not.toHaveBeenCalled();
    await act(async () => button("恢复工作台")!.click());
    expect(recover).toHaveBeenCalledOnce();
    await render(true, true, true);
    expect(button("正在恢复工作台")!.disabled).toBe(true);
    expect(button("检查连接")!.disabled).toBe(true);
  });

  it("gives browser users an honest Launcher handoff without an unavailable lifecycle button", async () => {
    await render(true, false);
    expect(button("恢复工作台")).toBeUndefined();
    expect(panelText()).toContain("请从 Vibelution 启动管理恢复工作台");
    await act(async () => button("检查连接")!.click());
    expect(retry).toHaveBeenCalledOnce();
    expect(recover).not.toHaveBeenCalled();
  });

  it("offers connection checking first after a transient timeout with previously healthy data", async () => {
    await act(async () => root.render(<WorkbenchConnectionNotice unavailable lang="zh" desktopShell recovering={false} lastHealthyAt={1000} failedAt={4000} onRecover={recover} onRetry={retry} />));
    expect(panelText()).toContain("连接检查暂未成功");
    expect(button("恢复工作台")).toBeUndefined();
    await act(async () => button("检查连接")!.click());
    expect(retry).toHaveBeenCalledOnce();
    expect(recover).not.toHaveBeenCalled();
    expect(connectionFailureIsPersistent(1000, 15_999)).toBe(false);
    expect(connectionFailureIsPersistent(1000, 16_000)).toBe(true);
    expect(connectionFailureIsPersistent(0, 4000)).toBe(true);
  });

  it("keeps connection health in the top bar aligned with the Tasks slot, not over the content", () => {
    expect(shellSource).toContain("(backendHealthQuery.isError || backendHealthQuery.isRefetchError) && !startupOverlayActive && !shutdownOpen");
    expect(shellSource).toContain("onRecover={() => { void beginRestart(); }}");
    expect(shellSource).toContain("const routeContent = useMemo(() => <Outlet />, []);");
    expect(shellSource).toContain('<CompanionDesktopAttention startupReady={shellOptionalReady} /><VWorkbenchFrame flush={location.pathname === "/chat" || location.pathname === "/teams"}><WorkbenchStartupReadyContext.Provider value={reportRouteStartupReady}>{routeContent}</WorkbenchStartupReadyContext.Provider></VWorkbenchFrame>');
    expect(shellSource).not.toContain("unavailable ? null : <Outlet");
    expect(shellSource).toContain('data-shell-group="active-work"');
    // Top bar, aligned with the Tasks slot: after it and before the content area.
    expect(shellSource.indexOf('data-shell-group="active-work"')).toBeLessThan(shellSource.indexOf("<WorkbenchConnectionNotice"));
    expect(shellSource.indexOf("<WorkbenchConnectionNotice")).toBeLessThan(shellSource.indexOf("<div className={styles.mainArea}>"));
    // No full-width band injected above the content frame.
    expect(shellSource).not.toContain("<div><WorkbenchConnectionNotice");
    expect(shellSource).toContain("className={styles.contentFrame}");
    expect(shellStylesSource).toContain("grid-rows-[minmax(0,1fr)]");
    expect(shellSource).toContain("lastHealthyAt={backendHealthQuery.dataUpdatedAt}");
    expect(shellSource).toContain("failedAt={backendHealthQuery.errorUpdatedAt}");
  });
});
