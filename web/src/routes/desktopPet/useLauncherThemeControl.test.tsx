// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WORKBENCH_THEME_STORAGE_KEY, writeStoredWorkbenchTheme } from "../../app/themePreference";
import { useLauncherThemeControl, type LauncherThemeBridge } from "./useLauncherThemeControl";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root, container: HTMLDivElement;
let command: (payload: unknown) => void;
let bridge: LauncherThemeBridge;
const id = "a".repeat(32);
function Harness() { useLauncherThemeControl(bridge); return null; }
beforeEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  bridge = { onCommand: vi.fn(listener => { command = listener; return vi.fn(); }), respond: vi.fn(async () => undefined) };
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.restoreAllMocks(); });
async function mount() { await act(async () => root.render(<Harness />)); }
async function send(payload: unknown) { await act(async () => command(payload)); }

describe("Launcher assistant theme renderer", () => {
  it("restores the stored theme, reads it and applies dark/light using the sole storage helper", async () => {
    localStorage.setItem(WORKBENCH_THEME_STORAGE_KEY, "dark");
    await mount();
    expect(document.documentElement.dataset.theme).toBe("dark");
    await send({ deliveryId: id, operation: "read" });
    expect(bridge.respond).toHaveBeenLastCalledWith({ deliveryId: id, operation: "read", code: "read", theme: "dark" });
    for (const theme of ["light", "dark"]) {
      await send({ deliveryId: id, operation: "set", theme });
      expect(localStorage.getItem(WORKBENCH_THEME_STORAGE_KEY)).toBe(theme);
      expect(document.documentElement.dataset.theme).toBe(theme);
      expect(bridge.respond).toHaveBeenLastCalledWith({ deliveryId: id, operation: "set", code: "applied", theme });
    }
  });

  it("synchronizes same-window and same-origin storage changes and removes both subscriptions", async () => {
    await mount();
    await act(async () => { writeStoredWorkbenchTheme("dark"); });
    expect(document.documentElement.dataset.theme).toBe("dark");
    await act(async () => {
      localStorage.setItem(WORKBENCH_THEME_STORAGE_KEY, "light");
      window.dispatchEvent(new StorageEvent("storage", { key: WORKBENCH_THEME_STORAGE_KEY }));
    });
    expect(document.documentElement.dataset.theme).toBe("light");
    await act(async () => root.render(null));
    expect(vi.mocked(bridge.onCommand).mock.results[0].value).toHaveBeenCalledOnce();
    writeStoredWorkbenchTheme("dark");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("ignores closed-schema violations and never invokes an accessor", async () => {
    await mount();
    const getter = vi.fn(() => "dark");
    const valid = { deliveryId: id, operation: "set", theme: "dark" };
    for (const payload of [{ ...valid, extra: true }, { ...valid, deliveryId: id.toUpperCase() },
      { ...valid, theme: "system" }, { ...valid, [Symbol()]: true },
      Object.defineProperty({ ...valid }, "theme", { get: getter }), { deliveryId: id, operation: "read", theme: "light" }]) {
      await send(payload);
    }
    expect(getter).not.toHaveBeenCalled();
    expect(bridge.respond).not.toHaveBeenCalled();
    expect(localStorage.getItem(WORKBENCH_THEME_STORAGE_KEY)).toBeNull();
  });

  it("reports persistence failure when writes throw or do not survive readback", async () => {
    await mount();
    const storage = window.localStorage;
    const write = vi.spyOn(storage, "setItem").mockImplementation(() => { throw new Error("private path"); });
    await send({ deliveryId: id, operation: "set", theme: "dark" });
    expect(bridge.respond).toHaveBeenLastCalledWith({ deliveryId: id, operation: "set", code: "persistence_failed" });
    expect(document.documentElement.dataset.theme).toBe("light");
    write.mockImplementation(() => undefined);
    await send({ deliveryId: id, operation: "set", theme: "dark" });
    expect(bridge.respond).toHaveBeenLastCalledWith({ deliveryId: id, operation: "set", code: "persistence_failed" });
  });

  it("fails closed if the observed document theme differs, and contains rejected ACK promises", async () => {
    await mount();
    vi.spyOn(document.documentElement, "setAttribute").mockImplementation(() => undefined);
    vi.mocked(bridge.respond).mockRejectedValue(new Error("renderer gone"));
    await send({ deliveryId: id, operation: "set", theme: "dark" });
    expect(bridge.respond).toHaveBeenCalledWith({ deliveryId: id, operation: "set", code: "unavailable" });
  });

  it("contains a throwing localStorage getter without claiming a successful set", async () => {
    await mount();
    vi.spyOn(window, "localStorage", "get").mockImplementation(() => { throw new Error("storage denied"); });
    await send({ deliveryId: id, operation: "set", theme: "dark" });
    expect(bridge.respond).toHaveBeenLastCalledWith({ deliveryId: id, operation: "set", code: "persistence_failed" });
  });
});
