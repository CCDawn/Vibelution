// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LauncherAssistantModelControl } from "./LauncherAssistantModelControl";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | undefined;
let container: HTMLDivElement;
afterEach(async () => {
  await act(async () => root?.unmount());
  root = undefined; container?.remove();
});

async function renderControl(options: { selectionDisabled?: boolean; pending?: boolean; unknownCurrent?: boolean } = {}) {
  const onModelChange = vi.fn();
  const onOpenSettings = vi.fn();
  container = document.createElement("div"); document.body.append(container);
  root = createRoot(container);
  await act(async () => root!.render(<LauncherAssistantModelControl lang="zh"
    modelId={options.unknownCurrent ? "previous" : "deepseek"} modelDisplay="当前对话模型"
    choices={[
      { modelId: "deepseek", label: "DeepSeek V4.1 Flash · 官方", providerLabel: "官方", isDefault: true, providerHealthy: true, missingApiKey: false, availability: "ready" },
      { modelId: "next", label: "另一个模型", providerLabel: "官方", isDefault: false, providerHealthy: true, missingApiKey: false, availability: "ready" },
      { modelId: "unavailable", label: "缺少密钥", providerLabel: "官方", isDefault: false, providerHealthy: true, missingApiKey: true, availability: "unavailable" },
    ]} pending={options.pending ?? false} selectionDisabled={options.selectionDisabled ?? false}
    onModelChange={onModelChange} onOpenSettings={onOpenSettings} />));
  const trigger = container.querySelector<HTMLButtonElement>("button")!;
  return { onModelChange, onOpenSettings, trigger };
}

describe("Launcher model toolbar control", () => {
  it("opens the shared compact popover recipe and preserves model selection", async () => {
    const { trigger, onModelChange } = await renderControl();
    expect(trigger.textContent).toBe("DeepSeek V4.1 Flash · 官方");
    expect(container.querySelector("select")).toBeNull();
    await act(async () => trigger.click());
    const selectTrigger = document.querySelector<HTMLElement>('[role="combobox"][aria-label="切换助理模型"]')!;
    expect(selectTrigger).toBeTruthy();
    await act(async () => selectTrigger.click());
    const disabledOption = [...document.querySelectorAll<HTMLElement>('[role="option"]')]
      .find(node => node.textContent === "缺少密钥")!;
    expect(disabledOption.getAttribute("aria-disabled")).toBe("true");
    const option = [...document.querySelectorAll<HTMLElement>('[role="option"]')]
      .find(node => node.textContent === "另一个模型")!;
    await act(async () => option.click());
    expect(onModelChange).toHaveBeenCalledExactlyOnceWith("next");
    expect(document.querySelector('[role="combobox"][aria-label="切换助理模型"]')).toBeNull();
  });

  it("keeps settings accessible while model switching is locked by active work", async () => {
    const { trigger, onModelChange, onOpenSettings } = await renderControl({ selectionDisabled: true });
    await act(async () => trigger.click());
    const selectTrigger = document.querySelector<HTMLButtonElement>('[role="combobox"][aria-label="切换助理模型"]')!;
    expect(selectTrigger.disabled).toBe(true);
    const settings = [...document.querySelectorAll<HTMLButtonElement>("button")].find(row => row.textContent === "模型设置")!;
    await act(async () => settings.click());
    expect(onOpenSettings).toHaveBeenCalledOnce();
    expect(onModelChange).not.toHaveBeenCalled();
  });

  it("retains a current model absent from the choice catalogue and locks pending configuration", async () => {
    const { trigger } = await renderControl({ unknownCurrent: true });
    await act(async () => trigger.click());
    const selectTrigger = document.querySelector<HTMLElement>('[role="combobox"][aria-label="切换助理模型"]')!;
    expect(selectTrigger.textContent).toContain("当前对话模型");
    await act(async () => selectTrigger.click());
    const option = [...document.querySelectorAll<HTMLElement>('[role="option"]')]
      .find(node => node.textContent === "当前对话模型")!;
    expect(option).toBeTruthy();
    await act(async () => root?.unmount()); root = undefined; container.remove();
    const pending = await renderControl({ pending: true });
    expect(pending.trigger.disabled).toBe(true);
  });
});
