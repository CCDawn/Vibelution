/** @vitest-environment happy-dom */
import React, { act, type ComponentProps } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { LauncherStartupSettings } from "../api/launcher";
import { VuiProvider } from "../components/vui/VuiProvider";
import { LauncherStartupSettingsPanel } from "./LauncherStartupSettingsPanel";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const copy: ComponentProps<typeof LauncherStartupSettingsPanel>["copy"] = {
  startupSettings: "启动设置",
  expandSettings: "展开编辑",
  collapseSettings: "收起设置",
  runtimeProfile: "运行档位",
  windowMode: "启动窗口",
  windowModeFullscreen: "全屏",
  windowModeWindowed: "窗口化",
  windowSize: "窗口尺寸",
  windowSizeAuto: "自动",
  windowSizeEnvOverride: "窗口尺寸被环境变量覆盖",
  interfaceLanguage: "界面语言",
  languageZh: "中文",
  languageEn: "英文",
  preflightDoctor: "启动前自检",
  requireVenv: "要求 .venv",
  saveStartupSettings: "保存设置",
};

function setting(overrides: {
  configHash?: string;
  profile?: string;
  preflightDoctor?: boolean;
  requireVenv?: boolean;
  windowMode?: "fullscreen" | "windowed";
  effectiveWindowMode?: "fullscreen" | "windowed";
  windowModeEnvOverride?: "fullscreen" | "windowed" | "";
  windowSize?: string;
  effectiveWindowSize?: string;
  windowSizeEnvOverride?: string;
  language?: string;
} = {}): LauncherStartupSettings {
  const windowMode = overrides.windowMode ?? "fullscreen";
  const windowSize = overrides.windowSize ?? "auto";
  return {
    launcher: {
      controlPort: 0,
      effectiveControlPort: 0,
      controlPortEnvOverride: 0,
    },
    runtime: {
      profile: overrides.profile ?? "safe_remote",
      preflightDoctor: overrides.preflightDoctor ?? true,
      requireVenv: overrides.requireVenv ?? true,
      profileOptions: ["safe_remote", "safe_local", "debug", "ci"],
    },
    workbench: {
      backendPort: 8000,
      frontendPort: 5173,
      effectiveBackendPort: 8000,
      effectiveFrontendPort: 5173,
      backendPortEnvOverride: 0,
      frontendPortEnvOverride: 0,
      windowMode,
      effectiveWindowMode: overrides.effectiveWindowMode ?? windowMode,
      windowModeEnvOverride: overrides.windowModeEnvOverride ?? "",
      windowSize,
      effectiveWindowSize: overrides.effectiveWindowSize ?? windowSize,
      windowSizeEnvOverride: overrides.windowSizeEnvOverride ?? "",
      windowSizeOptions: [
        { size: "auto", label: { zh: "自动", en: "Auto" } },
        { size: "1440x900", label: { zh: "1440 × 900", en: "1440 × 900" } },
      ],
      windowModeOptions: [
        { mode: "fullscreen", label: { zh: "全屏", en: "Fullscreen" }, detail: { zh: "", en: "" } },
        { mode: "windowed", label: { zh: "窗口化", en: "Windowed" }, detail: { zh: "", en: "" } },
      ],
    },
    interface: {
      language: overrides.language ?? "zh",
      languageOptions: ["zh", "en"],
    },
    configPath: "C:/Users/test/Documents/Vibelution/config/config.toml",
    configHash: overrides.configHash ?? "hash-1",
    restartRequired: true,
  };
}

let root: Root;
let host: HTMLDivElement;
let props: ComponentProps<typeof LauncherStartupSettingsPanel>;

async function renderPanel(nextProps: Partial<ComponentProps<typeof LauncherStartupSettingsPanel>> = {}) {
  props = {
    copy,
    uiLang: "zh",
    setting: setting(),
    configuredWindowMode: "fullscreen",
    effectiveWindowModeLabel: "全屏",
    windowModeDetail: "下次启动或重启工作台生效",
    pending: false,
    onSave: vi.fn(async (next) => next),
    ...props,
    ...nextProps,
  };
  await act(async () => {
    root.render(
      <VuiProvider>
        <LauncherStartupSettingsPanel {...props} />
      </VuiProvider>,
    );
  });
}

function button(label: string): HTMLButtonElement {
  const found = [...host.querySelectorAll("button")].find((item) => item.textContent?.trim() === label);
  expect(found, `button: ${label}`).toBeTruthy();
  return found!;
}

function checkbox(label: string): HTMLInputElement {
  const found = [...host.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')]
    .find((item) => item.getAttribute("aria-label") === label);
  expect(found, `checkbox: ${label}`).toBeTruthy();
  return found!;
}

async function clickButton(label: string) {
  await act(async () => {
    button(label).click();
    await Promise.resolve();
  });
}

beforeEach(async () => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  props = {
    copy,
    uiLang: "zh",
    setting: setting(),
    configuredWindowMode: "fullscreen",
    effectiveWindowModeLabel: "全屏",
    windowModeDetail: "下次启动或重启工作台生效",
    pending: false,
    onSave: vi.fn(async (next) => next),
  };
  await renderPanel({ standalone: true });
});

afterEach(async () => {
  await act(async () => root?.unmount());
  host?.remove();
});

describe("LauncherStartupSettingsPanel", () => {
  it("renders the approved settings page with one row for each existing option", () => {
    const page = host.querySelector<HTMLElement>('[data-vui-recipe="settings-form-page"]');
    expect(page).toBeTruthy();
    expect(page?.className).toContain("!h-auto");
    expect(page?.querySelector('[data-vui="settings-form-header"]')?.className).toContain("hidden");
    const body = page?.querySelector<HTMLElement>('[data-vui="settings-form-body"]');
    expect(body?.className).toContain("overflow-y-auto");
    expect(body?.className).not.toMatch(/(?:^|\s)px-(?:7|4)(?:\s|$)/);
    expect(page?.querySelector('[data-vui="settings-form-footer"]')?.className).not.toMatch(/(?:^|\s)px-(?:7|4)(?:\s|$)/);
    expect(host.querySelectorAll('[data-testid^="row-"]')).toHaveLength(6);
    expect(host.textContent).toContain("要求 .venv");
    expect(host.textContent).toContain("启动前自检");
  });

  it("keeps the compatibility strip collapsed unless standalone is requested", async () => {
    await renderPanel({ standalone: false });
    const disclosure = host.querySelector("details");
    expect(disclosure?.open).toBe(false);
    expect(host.querySelector('[data-vui-recipe="settings-form-page"]')).toBeNull();
  });

  it("retains server options, effective values, and environment override hints", async () => {
    await renderPanel({
      setting: setting({
        windowMode: "fullscreen",
        effectiveWindowMode: "windowed",
        windowModeEnvOverride: "windowed",
        effectiveWindowSize: "1440x900",
        windowSizeEnvOverride: "1440x900",
      }),
      effectiveWindowModeLabel: "窗口化",
    });

    expect(host.textContent).toContain("环境变量覆盖了此设置，当前生效：");
    expect(host.textContent).toContain("窗口化");
    expect(host.textContent).toContain("1440x900");

    const trigger = [...host.querySelectorAll<HTMLButtonElement>("[data-vui-select-trigger]")]
      .find((item) => item.getAttribute("aria-label") === "窗口尺寸");
    expect(trigger).toBeTruthy();
    await act(async () => trigger!.click());
    expect(document.body.textContent).toContain("1440 × 900");
  });

  it("preserves a dirty draft when refreshed settings arrive and can restore the latest version", async () => {
    const dirtyCallback = vi.fn();
    await renderPanel({ onDirtyChange: dirtyCallback });
    await act(async () => checkbox("启动前自检").click());
    expect(checkbox("启动前自检").checked).toBe(false);
    expect(dirtyCallback).toHaveBeenLastCalledWith(true);

    await renderPanel({ setting: setting({ configHash: "hash-2", profile: "debug" }) });
    expect(checkbox("启动前自检").checked).toBe(false);
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("已被其他页面或进程修改");
    expect(button("加载最新设置").disabled).toBe(false);

    await clickButton("加载最新设置");
    expect(checkbox("启动前自检").checked).toBe(true);
    expect(host.textContent).not.toContain("已被其他页面或进程修改");
    expect(dirtyCallback).toHaveBeenLastCalledWith(false);
  });

  it("keeps changes unsaved after a failed request and clears dirty only after success", async () => {
    const onSave = vi.fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(setting({ configHash: "hash-2", preflightDoctor: false }));
    const dirtyCallback = vi.fn();
    await renderPanel({ onSave, onDirtyChange: dirtyCallback });
    await act(async () => checkbox("启动前自检").click());
    await clickButton("保存设置");

    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave.mock.calls[0][0].configHash).toBe("hash-1");
    expect(checkbox("启动前自检").checked).toBe(false);
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("offline");
    expect(host.textContent).toContain("有未保存的更改");
    expect(button("保存设置").disabled).toBe(false);

    await clickButton("保存设置");
    expect(onSave).toHaveBeenCalledTimes(2);
    expect(onSave.mock.calls[1][0].runtime.preflightDoctor).toBe(false);
    expect(onSave.mock.calls[1][0].configHash).toBe("hash-1");
    expect(host.textContent).toContain("没有未保存的更改");
    expect(dirtyCallback).toHaveBeenLastCalledWith(false);
  });

  it("blocks retry on a config conflict until the refreshed configuration is loaded", async () => {
    const onSave = vi.fn().mockRejectedValue({
      status: 409,
      code: "launcher_startup_settings_conflict",
      message: "settings changed",
    });
    await renderPanel({ onSave });
    await act(async () => checkbox("启动前自检").click());
    await clickButton("保存设置");

    expect(button("正在读取最新设置…").disabled).toBe(true);
    expect(button("保存设置").disabled).toBe(true);

    await renderPanel({ setting: setting({ configHash: "hash-2", preflightDoctor: true }) });
    expect(button("加载最新设置").disabled).toBe(false);
    await clickButton("加载最新设置");
    expect(button("保存设置").disabled).toBe(true);
  });

  it("routes window mode through the unified save instead of the legacy immediate mutation", async () => {
    const onSave = vi.fn(async (next: LauncherStartupSettings) => ({
      ...next,
      configHash: "hash-2",
    }));
    const onWindowModeChange = vi.fn();
    await renderPanel({ onSave, onWindowModeChange });

    const trigger = [...host.querySelectorAll<HTMLButtonElement>("[data-vui-select-trigger]")]
      .find((item) => item.getAttribute("aria-label") === "启动窗口");
    expect(trigger).toBeTruthy();
    await act(async () => trigger!.click());
    const option = [...document.querySelectorAll<HTMLElement>('[role="option"]')]
      .find((item) => item.textContent?.includes("窗口化"));
    expect(option).toBeTruthy();
    await act(async () => option!.click());

    expect(onWindowModeChange).not.toHaveBeenCalled();
    expect(onSave).not.toHaveBeenCalled();
    await clickButton("保存设置");
    expect(onSave).toHaveBeenCalledOnce();
    expect(onSave.mock.calls[0][0].workbench.windowMode).toBe("windowed");
  });
});
