// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AppShellSettingsMenu } from "./AppShellSettingsMenu";
const refresh = vi.fn(), close = vi.fn(), theme = vi.fn();
let root: Root, host: HTMLDivElement;
async function mount(disabled = false, themePending = false) {
  await act(async () => root.render(<MemoryRouter><AppShellSettingsMenu lang="zh" theme="light" themePending={themePending} onThemeChange={theme} onClose={close} onRefresh={refresh} refreshDisabled={disabled} /></MemoryRouter>));
}
function button(label: string) { return [...host.querySelectorAll<HTMLButtonElement>("button")].find(b => b.textContent?.includes(label) || b.getAttribute("aria-label") === label)!; }
beforeEach(async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  refresh.mockReset(); close.mockReset(); theme.mockReset();
  host = document.createElement("div"); document.body.append(host); root = createRoot(host); await mount();
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); });
it("shows four common entries and hides maintenance", () => {
  expect(host.querySelectorAll("a, button, input[role=switch]")).toHaveLength(4);
  expect(host.textContent).not.toContain("重新加载");
  expect(host.querySelector('a[href="/config"]')).not.toBeNull();
  expect(host.querySelector('a[href="/usage"]')).not.toBeNull();
  // The retired desktop-pet toggle no longer mounts in the shell menu.
  expect(host.querySelector('input[role="switch"]')).toBeNull();
  expect(host.textContent).not.toContain("个人助理");
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
it("disables both theme choices while a prior selection is pending", async () => {
  await mount(false, true);
  await act(async () => button("外观").click());
  expect(button("浅色").disabled).toBe(true);
  expect(button("深色").disabled).toBe(true);
});
