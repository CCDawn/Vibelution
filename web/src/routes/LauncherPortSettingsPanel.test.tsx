/** @vitest-environment happy-dom */
import React, { act, type ComponentProps } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { LauncherStartupSettings } from "../api/launcher";
import { VuiProvider } from "../components/vui/VuiProvider";
import { LauncherPortSettingsPanel } from "./LauncherPortSettingsPanel";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const copy: ComponentProps<typeof LauncherPortSettingsPanel>["copy"] = {
  portSettings: "端口设置",
  portSettingsHint: "改动在下次启动时生效",
  launcherControlPort: "控制端口",
  launcherControlPortHint: "Launcher 控制端口",
  backendPort: "后端端口",
  backendPortHint: "后端服务端口",
  frontendPort: "前端端口",
  frontendPortHint: "前端页面端口",
  portOverride: "环境变量覆盖",
  savePortSettings: "保存端口设置",
  invalidPort: "端口必须是 1-65535 之间的整数",
};

function setting(overrides: {
  configHash?: string;
  controlPort?: number;
  backendPort?: number;
  frontendPort?: number;
} = {}): LauncherStartupSettings {
  const controlPort = overrides.controlPort ?? 9000;
  const backendPort = overrides.backendPort ?? 8000;
  const frontendPort = overrides.frontendPort ?? 5173;
  return {
    launcher: {
      controlPort,
      effectiveControlPort: controlPort,
      controlPortEnvOverride: 0,
    },
    runtime: {
      profile: "safe_remote",
      preflightDoctor: true,
      requireVenv: true,
      profileOptions: ["safe_remote", "safe_local", "debug", "ci"],
    },
    workbench: {
      backendPort,
      frontendPort,
      effectiveBackendPort: backendPort,
      effectiveFrontendPort: frontendPort,
      backendPortEnvOverride: 0,
      frontendPortEnvOverride: 0,
      windowMode: "fullscreen",
      effectiveWindowMode: "fullscreen",
      windowModeEnvOverride: "",
      windowSize: "auto",
      effectiveWindowSize: "auto",
      windowSizeEnvOverride: "",
      windowSizeOptions: [{ size: "auto", label: { zh: "自动", en: "Auto" } }],
      windowModeOptions: [],
    },
    interface: {
      language: "zh",
      languageOptions: ["zh", "en"],
    },
    configPath: "C:/Users/test/Documents/Vibelution/config/config.toml",
    configHash: overrides.configHash ?? "hash-1",
    restartRequired: true,
  };
}

let root: Root;
let host: HTMLDivElement;
let props: ComponentProps<typeof LauncherPortSettingsPanel>;

async function renderPanel(nextProps: Partial<ComponentProps<typeof LauncherPortSettingsPanel>> = {}) {
  props = {
    copy,
    setting: setting(),
    controlPortOverride: 0,
    backendPortOverride: 0,
    frontendPortOverride: 0,
    pending: false,
    onSave: vi.fn(),
    ...props,
    ...nextProps,
  };
  await act(async () => {
    root.render(
      <VuiProvider>
        <LauncherPortSettingsPanel {...props} />
      </VuiProvider>,
    );
  });
}

beforeEach(async () => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  props = {
    copy,
    setting: setting(),
    controlPortOverride: 0,
    backendPortOverride: 0,
    frontendPortOverride: 0,
    pending: false,
    onSave: vi.fn(),
  };
  await renderPanel();
});

afterEach(async () => {
  await act(async () => root?.unmount());
  host?.remove();
});

function portInputs(): HTMLInputElement[] {
  const found = [...host.querySelectorAll<HTMLInputElement>('input[type="number"]')];
  expect(found, "three port inputs").toHaveLength(3);
  return found;
}

function portValues(): [string, string, string] {
  const inputs = portInputs();
  return [inputs[0].value, inputs[1].value, inputs[2].value];
}

async function typePort(index: number, value: string) {
  await act(async () => {
    const control = portInputs()[index];
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(control, value);
    control.dispatchEvent(new Event("input", { bubbles: true }));
    await Promise.resolve();
  });
}

function button(label: string): HTMLButtonElement {
  const found = [...host.querySelectorAll("button")].find((item) => item.textContent?.trim() === label);
  expect(found, `button: ${label}`).toBeTruthy();
  return found!;
}

async function clickButton(label: string) {
  await act(async () => {
    button(label).click();
    await Promise.resolve();
  });
}

async function openPanel() {
  const details = host.querySelector<HTMLDetailsElement>("details");
  expect(details, "panel details").toBeTruthy();
  if (details && !details.open) {
    await act(async () => details.querySelector("summary")!.click());
  }
}

describe("LauncherPortSettingsPanel", () => {
  it("preserves a dirty draft when refreshed settings arrive and can load the latest ports", async () => {
    await openPanel();
    await typePort(0, "9001");
    expect(portValues()).toEqual(["9001", "8000", "5173"]);

    await renderPanel({ setting: setting({ configHash: "hash-2", backendPort: 8005 }) });
    expect(portValues()).toEqual(["9001", "8000", "5173"]);
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("已被其他页面或进程修改");
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("草稿已保留");
    expect(button("加载最新设置").disabled).toBe(false);

    await clickButton("加载最新设置");
    expect(portValues()).toEqual(["9000", "8005", "5173"]);
    expect(host.querySelector('[role="alert"]')).toBeNull();
  });

  it("adopts refreshed settings as before while the draft is clean", async () => {
    await renderPanel({ setting: setting({ configHash: "hash-2", controlPort: 9005, frontendPort: 5180 }) });
    expect(portValues()).toEqual(["9005", "8000", "5180"]);
    expect(host.querySelector('[role="alert"]')).toBeNull();
  });

  it("parses the three ports into integers before calling onSave and reports invalid drafts", async () => {
    await openPanel();
    await typePort(0, "09100");
    await typePort(1, "0");
    await clickButton("保存端口设置");
    expect(vi.mocked(props.onSave)).not.toHaveBeenCalled();
    expect(host.querySelector('[role="alert"]')?.textContent).toContain(copy.invalidPort);

    await typePort(1, "08010");
    await typePort(2, "5174");
    await clickButton("保存端口设置");
    expect(vi.mocked(props.onSave)).toHaveBeenCalledTimes(1);
    const saved = vi.mocked(props.onSave).mock.calls[0][0];
    expect(saved.launcher.controlPort).toBe(9100);
    expect(saved.workbench.backendPort).toBe(8010);
    expect(saved.workbench.frontendPort).toBe(5174);
    expect(host.querySelector('[role="alert"]')).toBeNull();
  });

  it("syncs fields to the saved values after save and stays clean on later refreshes", async () => {
    await openPanel();
    await typePort(1, "8010");
    await clickButton("保存端口设置");
    expect(vi.mocked(props.onSave).mock.calls[0][0].workbench.backendPort).toBe(8010);

    await renderPanel({ setting: setting({ configHash: "hash-2", backendPort: 8010 }) });
    expect(portValues()).toEqual(["9000", "8010", "5173"]);
    expect(host.querySelector('[role="alert"]')).toBeNull();

    await renderPanel({ setting: setting({ configHash: "hash-3", backendPort: 8010 }) });
    expect(portValues()).toEqual(["9000", "8010", "5173"]);
    expect(host.querySelector('[role="alert"]')).toBeNull();
  });

  it("shows the English conflict notice when uiLang is en", async () => {
    await renderPanel({ uiLang: "en" });
    await openPanel();
    await typePort(2, "5199");

    await renderPanel({ uiLang: "en", setting: setting({ configHash: "hash-2" }) });
    expect(portValues()).toEqual(["9000", "8000", "5199"]);
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("Port settings changed in another page or process");
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("Your draft is preserved");
    expect(button("Load latest settings").disabled).toBe(false);
  });
});
