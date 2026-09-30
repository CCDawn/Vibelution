// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AppShellSettingsMenu } from "./AppShellSettingsMenu";
const control = vi.fn(), refresh = vi.fn(), close = vi.fn(), theme = vi.fn();
let root: Root, host: HTMLDivElement;
async function mount(disabled = false) {
  await act(async () => root.render(<MemoryRouter><AppShellSettingsMenu lang="zh" theme="light" onThemeChange={theme} onClose={close} onRefresh={refresh} refreshDisabled={disabled} /></MemoryRouter>));
}
function button(label: string) { return [...host.querySelectorAll<HTMLButtonElement>("button")].find(b => b.textContent?.includes(label) || b.getAttribute("aria-label") === label)!; }
beforeEach(async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("vibelutionLauncher", { controlDesktopPet: control });
  control.mockReset().mockResolvedValue({ open: false, busyElsewhere: false });
  refresh.mockReset(); close.mockReset(); theme.mockReset();
  host = document.createElement("div"); document.body.append(host); root = createRoot(host); await mount();
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); });
it("shows five common entries and hides maintenance", () => {
  expect(host.querySelectorAll("a, button, input[role=switch]")).toHaveLength(5);
  expect(host.textContent).not.toContain("重新加载");
  expect(host.querySelector('a[href="/config"]')).not.toBeNull();
  expect(host.querySelector('a[href="/usage"]')).not.toBeNull();
});
it("opens maintenance in place, preserves routes and returns", async () => {
  await act(async () => button("高级与诊断").click());
  expect(host.querySelector('a[href="/kernel"]')).not.toBeNull();
  expect(host.querySelector('a[href="/logs"]')).not.toBeNull();
  expect(host.querySelector('a[href="/launcher"]')?.getAttribute("target")).toBe("_blank");
  await act(async () => button("重新加载界面").click()); expect(refresh).toHaveBeenCalledOnce();
  await act(async () => button("返回设置").click()); expect(host.textContent).toContain("全部设置");
});
it("keeps lifecycle lock on reload", async () => {
  await mount(true); await act(async () => button("高级与诊断").click());
  expect(button("重新加载界面").disabled).toBe(true);
});
it("uses the existing theme action", async () => {
  await act(async () => button("外观").click());
  await act(async () => button("深色").click()); expect(theme).toHaveBeenCalledWith("dark");
});
it("drives the real bridge and does not fake success on rejection", async () => {
  const toggle = host.querySelector<HTMLInputElement>('input[role="switch"]')!;
  control.mockResolvedValueOnce({ open: true, busyElsewhere: false });
  await act(async () => toggle.click()); expect(control).toHaveBeenLastCalledWith(true); expect(toggle.checked).toBe(true);
  control.mockRejectedValueOnce(new Error("failed"));
  await act(async () => toggle.click()); expect(host.textContent).toContain("操作失败"); expect(toggle.checked).toBe(true);
});
it("disables compact pet control without a bridge", async () => {
  vi.stubGlobal("vibelutionLauncher", undefined); await mount();
  expect(host.querySelector<HTMLInputElement>('input[role="switch"]')!.disabled).toBe(true);
  expect(host.textContent).toContain("仅桌面版");
});
it("does not take another workspace's pet", async () => {
  control.mockResolvedValue({ open: false, busyElsewhere: true });
  await act(async () => window.dispatchEvent(new Event("focus")));
  expect(host.querySelector<HTMLInputElement>('input[role="switch"]')!.disabled).toBe(true);
});
