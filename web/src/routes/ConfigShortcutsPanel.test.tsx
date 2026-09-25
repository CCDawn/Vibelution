// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { SHORTCUT_COMMANDS } from "../shortcuts/commands";
import {
  SHORTCUT_OVERRIDES_STORAGE_KEY,
  readStoredShortcutOverrides,
} from "../shortcuts/shortcutOverrides";
import { CONFIG_COPY } from "./ConfigRoute";
import { ConfigShortcutsPanel } from "./ConfigShortcutsPanel";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function keyEvent(init: Partial<KeyboardEvent> = {}): KeyboardEvent {
  return new KeyboardEvent("keydown", {
    key: "k",
    code: "KeyK",
    ctrlKey: true,
    metaKey: false,
    altKey: false,
    shiftKey: false,
    bubbles: true,
    cancelable: true,
    ...init,
  });
}

let host: HTMLDivElement;
let root: Root | null = null;

async function renderPanel(lang: "zh" | "en" = "zh"): Promise<void> {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => {
    root?.render(<ConfigShortcutsPanel lang={lang} copy={CONFIG_COPY[lang]} />);
  });
}

function query(testId: string): HTMLElement | null {
  return host.querySelector(`[data-testid="${testId}"]`);
}

function queryAll(testId: string): HTMLElement[] {
  return [...host.querySelectorAll(`[data-testid="${testId}"]`)];
}

async function click(testId: string): Promise<void> {
  const element = query(testId);
  if (!element) {
    throw new Error(`missing element: ${testId}`);
  }
  await act(async () => {
    element.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  });
}

async function pressKey(init: Partial<KeyboardEvent>): Promise<void> {
  await act(async () => {
    window.dispatchEvent(keyEvent(init));
  });
}

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(async () => {
  if (root) {
    await act(async () => {
      root?.unmount();
    });
    root = null;
  }
  host?.remove();
});

describe("ConfigShortcutsPanel", () => {
  it("renders the real command registry with default bindings and status", async () => {
    await renderPanel();
    for (const command of SHORTCUT_COMMANDS) {
      expect(query(`shortcuts-row-${command.id}`)).not.toBeNull();
    }
    const keys = queryAll("shortcuts-binding-kbd").map((element) => element.textContent);
    expect(keys).toEqual(["Ctrl+K", "Ctrl+P"]);
    expect(host.textContent).toContain("打开命令面板");
    expect(host.textContent).toContain("会话搜索");
    expect(host.textContent).toContain("默认");
    expect(host.textContent).toContain("导航");
  });

  it("renders English copy for the command list", async () => {
    await renderPanel("en");
    expect(host.textContent).toContain("Open command palette");
    expect(host.textContent).toContain("Session search");
    expect(queryAll("shortcuts-binding-kbd").map((element) => element.textContent)).toEqual([
      "Ctrl+K",
      "Ctrl+P",
    ]);
  });

  it("records a new binding on keydown and persists the override", async () => {
    await renderPanel();
    await click("shortcuts-modify-openSessionSearch");
    expect(query("shortcuts-recording-strip")).not.toBeNull();
    await pressKey({ key: "j", code: "KeyJ" });
    expect(query("shortcuts-recording-strip")).toBeNull();
    const sessionKeys = query("shortcuts-keys-openSessionSearch")?.textContent ?? "";
    expect(sessionKeys).toContain("Ctrl+J");
    expect(sessionKeys).toContain("已覆盖");
    expect(readStoredShortcutOverrides()).toEqual({ openSessionSearch: ["CmdOrCtrl+j"] });
    expect(window.localStorage.getItem(SHORTCUT_OVERRIDES_STORAGE_KEY)).toBe(
      JSON.stringify({ openSessionSearch: ["CmdOrCtrl+j"] }),
    );
  });

  it("shows pending hint while only a modifier is pressed", async () => {
    await renderPanel();
    await click("shortcuts-modify-openCommandPalette");
    await pressKey({ key: "Control", code: "ControlLeft", ctrlKey: true });
    expect(query("shortcuts-recording-strip")?.textContent).toContain("已收到修饰键");
    expect(readStoredShortcutOverrides()).toEqual({});
  });

  it("cancels recording with Escape without changing bindings", async () => {
    await renderPanel();
    await click("shortcuts-modify-openCommandPalette");
    await pressKey({ key: "Escape", code: "Escape", ctrlKey: false });
    expect(query("shortcuts-recording-strip")).toBeNull();
    expect(query("shortcuts-banner")?.textContent).toContain("录制已取消");
    expect(readStoredShortcutOverrides()).toEqual({});
    expect(queryAll("shortcuts-binding-kbd").map((element) => element.textContent)).toEqual([
      "Ctrl+K",
      "Ctrl+P",
    ]);
  });

  it("rejects reserved keys with an explanation and keeps storage untouched", async () => {
    await renderPanel();
    await click("shortcuts-modify-openSessionSearch");
    await pressKey({ key: "Enter", code: "Enter", ctrlKey: false });
    const banner = query("shortcuts-banner");
    expect(banner?.getAttribute("data-banner-tone")).toBe("danger");
    expect(banner?.textContent).toContain("保留键");
    expect(banner?.textContent).toContain("Enter");
    expect(readStoredShortcutOverrides()).toEqual({});
    expect(query("shortcuts-keys-openSessionSearch")?.textContent).toContain("Ctrl+P");
  });

  it("detects occupied bindings, offers steal, and unbinds the owner on steal", async () => {
    await renderPanel();
    await click("shortcuts-modify-openSessionSearch");
    // Ctrl+K 已被「打开命令面板」占用 → 拒绝并提示占用方。
    await pressKey({ key: "k", code: "KeyK" });
    const banner = query("shortcuts-banner");
    expect(banner?.getAttribute("data-banner-tone")).toBe("danger");
    expect(banner?.textContent).toContain("已被「打开命令面板」占用");
    expect(readStoredShortcutOverrides()).toEqual({});
    // 抢占：占用方变为未绑定，新键落到目标命令。
    await click("shortcuts-banner-steal");
    expect(readStoredShortcutOverrides()).toEqual({
      openCommandPalette: [],
      openSessionSearch: ["CmdOrCtrl+k"],
    });
    const paletteKeys = query("shortcuts-keys-openCommandPalette")?.textContent ?? "";
    expect(paletteKeys).toContain("未设置");
    expect(paletteKeys).toContain("已清除");
    const sessionKeys = query("shortcuts-keys-openSessionSearch")?.textContent ?? "";
    expect(sessionKeys).toContain("Ctrl+K");
    expect(query("shortcuts-banner")?.textContent).toContain("变为未绑定");
  });

  it("clears one command to explicit unset and keeps the cleared state persisted", async () => {
    await renderPanel();
    await click("shortcuts-clear-openCommandPalette");
    const paletteKeys = query("shortcuts-keys-openCommandPalette")?.textContent ?? "";
    expect(paletteKeys).toContain("未设置");
    expect(paletteKeys).toContain("已清除");
    expect(query(`shortcuts-clear-openCommandPalette`)).toBeNull();
    expect(readStoredShortcutOverrides()).toEqual({ openCommandPalette: [] });
    expect(window.localStorage.getItem(SHORTCUT_OVERRIDES_STORAGE_KEY)).toBe(
      JSON.stringify({ openCommandPalette: [] }),
    );
  });

  it("restores one command default by removing the override", async () => {
    await renderPanel();
    await click("shortcuts-clear-openCommandPalette");
    await click("shortcuts-restore-openCommandPalette");
    expect(readStoredShortcutOverrides()).toEqual({});
    const paletteKeys = query("shortcuts-keys-openCommandPalette")?.textContent ?? "";
    expect(paletteKeys).toContain("Ctrl+K");
    expect(paletteKeys).toContain("默认");
    expect(window.localStorage.getItem(SHORTCUT_OVERRIDES_STORAGE_KEY)).toBeNull();
  });

  it("restores all defaults and removes the persisted storage key", async () => {
    window.localStorage.setItem(
      SHORTCUT_OVERRIDES_STORAGE_KEY,
      JSON.stringify({ openCommandPalette: ["Ctrl+Alt+k"] }),
    );
    await renderPanel();
    const paletteKeys = query("shortcuts-keys-openCommandPalette")?.textContent ?? "";
    expect(paletteKeys).toContain("Ctrl+Alt+K");
    await click("shortcuts-reset-all");
    expect(readStoredShortcutOverrides()).toEqual({});
    expect(queryAll("shortcuts-binding-kbd").map((element) => element.textContent)).toEqual([
      "Ctrl+K",
      "Ctrl+P",
    ]);
    expect(query("shortcuts-banner")?.textContent).toContain("已恢复全部默认绑定");
  });

  it("keeps banner dismissible without touching overrides", async () => {
    await renderPanel();
    await click("shortcuts-modify-openSessionSearch");
    await pressKey({ key: "Enter", code: "Enter", ctrlKey: false });
    expect(query("shortcuts-banner")).not.toBeNull();
    await click("shortcuts-banner-close");
    expect(query("shortcuts-banner")).toBeNull();
    expect(readStoredShortcutOverrides()).toEqual({});
  });
});
