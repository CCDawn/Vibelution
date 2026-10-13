/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import shellSource from "./AppShell.tsx?raw";
import { connectionFailureIsPersistent, WorkbenchConnectionNotice } from "./WorkbenchConnectionNotice";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
let root: Root;
const recover = vi.fn();
const retry = vi.fn();
async function render(unavailable = true, desktopShell = true, recovering = false) {
  await act(async () => root.render(<><WorkbenchConnectionNotice unavailable={unavailable} lang="zh" desktopShell={desktopShell} recovering={recovering} onRecover={recover} onRetry={retry} /><textarea aria-label="draft" defaultValue="未发送的草稿" /></>));
}
function button(text: string) { return [...host.querySelectorAll("button")].find(x => x.textContent?.trim() === text)!; }
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
    expect(host.textContent).toContain("工作台服务未连接");
    expect(host.textContent).not.toContain("服务已停止");
    expect(recover).not.toHaveBeenCalled();
    await render(false);
    expect(host.querySelector("[data-testid=workbench-connection-notice]")).toBeNull();
    expect(draft.value).toBe("断开前输入");
  });
  it("uses explicit recovery and connection checks as separate actions", async () => {
    await render();
    expect(host.textContent).toContain("先停止任务并保存已有记录");
    await act(async () => button("检查连接").click());
    expect(retry).toHaveBeenCalledOnce();
    expect(recover).not.toHaveBeenCalled();
    await act(async () => button("恢复工作台").click());
    expect(recover).toHaveBeenCalledOnce();
    await render(true, true, true);
    expect(button("正在恢复工作台").disabled).toBe(true);
    expect(button("检查连接").disabled).toBe(true);
  });
  it("gives browser users an honest Launcher handoff without an unavailable lifecycle button", async () => {
    await render(true, false);
    expect(button("恢复工作台")).toBeUndefined();
    expect(host.textContent).toContain("请从 Vibelution 启动管理恢复工作台");
    await act(async () => button("检查连接").click());
    expect(retry).toHaveBeenCalledOnce();
    expect(recover).not.toHaveBeenCalled();
  });
  it("observes refetch errors and leaves the route mounted while using the existing restart owner", () => {
    expect(shellSource).toContain("(backendHealthQuery.isError || backendHealthQuery.isRefetchError) && !startupOverlayActive && !shutdownOpen");
    expect(shellSource).toContain("onRecover={() => { void beginRestart(); }}");
    expect(shellSource).toContain("<CompanionDesktopAttention /><Outlet />");
    expect(shellSource).not.toContain("unavailable ? null : <Outlet");
    expect(shellSource.indexOf("<div className={styles.mainArea}>" )).toBeLessThan(shellSource.indexOf("<WorkbenchConnectionNotice"));
    expect(shellSource).toContain("grid-rows-[auto_minmax(0,1fr)]");
    expect(shellSource).toContain("lastHealthyAt={backendHealthQuery.dataUpdatedAt}");
    expect(shellSource).toContain("failedAt={backendHealthQuery.errorUpdatedAt}");
  });
  it("offers connection checking first after a transient timeout with previously healthy data", async () => {
    await act(async () => root.render(<WorkbenchConnectionNotice unavailable lang="zh" desktopShell recovering={false} lastHealthyAt={1000} failedAt={4000} onRecover={recover} onRetry={retry} />));
    expect(host.textContent).toContain("连接检查暂未成功");
    expect(button("恢复工作台")).toBeUndefined();
    await act(async () => button("检查连接").click());
    expect(retry).toHaveBeenCalledOnce();
    expect(recover).not.toHaveBeenCalled();
    expect(connectionFailureIsPersistent(1000, 15_999)).toBe(false);
    expect(connectionFailureIsPersistent(1000, 16_000)).toBe(true);
    expect(connectionFailureIsPersistent(0, 4000)).toBe(true);
  });
});
