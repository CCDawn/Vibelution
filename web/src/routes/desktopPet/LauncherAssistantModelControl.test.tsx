// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LauncherAssistantModelControl } from "./LauncherAssistantModelControl";
import type { LauncherAssistantModelChoice } from "../../api/launcherAssistant";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | undefined;
let container: HTMLDivElement;

afterEach(async () => {
  await act(async () => root?.unmount());
  root = undefined;
  container?.remove();
});

const CHOICES = [
  {
    modelId: "deepseek",
    label: "DeepSeek V4.1 Flash · 官方",
    providerLabel: "官方",
    isDefault: true,
    providerHealthy: true,
    missingApiKey: false,
    availability: "ready",
  },
  {
    modelId: "next",
    label: "另一个模型",
    providerLabel: "官方",
    isDefault: false,
    providerHealthy: true,
    missingApiKey: false,
    availability: "ready",
  },
  {
    modelId: "unavailable",
    label: "缺少密钥",
    providerLabel: "官方",
    isDefault: false,
    providerHealthy: true,
    missingApiKey: true,
    availability: "unavailable",
  },
];

function options() {
  return [...document.querySelectorAll<HTMLButtonElement>('[role="option"]')];
}

function optionContaining(text: string) {
  return options().find(node => (node.textContent || "").includes(text));
}

async function renderControl(
  options_: { selectionDisabled?: boolean; pending?: boolean; unknownCurrent?: boolean;
    choices?: LauncherAssistantModelChoice[] } = {},
) {
  const onModelChange = vi.fn();
  const onOpenSettings = vi.fn();
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root!.render(
    <LauncherAssistantModelControl
      lang="zh"
      modelId={options_.unknownCurrent ? "previous" : "deepseek"}
      modelDisplay="当前对话模型"
      choices={options_.choices ?? CHOICES}
      pending={options_.pending ?? false}
      selectionDisabled={options_.selectionDisabled ?? false}
      onModelChange={onModelChange}
      onOpenSettings={onOpenSettings}
    />,
  ));
  const trigger = container.querySelector<HTMLButtonElement>("button")!;
  return { onModelChange, onOpenSettings, trigger };
}

describe("Launcher model toolbar control", () => {
  it("reuses the conversation candidate list with provider groups, search and disable reasons", async () => {
    const { trigger, onModelChange } = await renderControl();
    expect(trigger.textContent).toContain("DeepSeek V4.1 Flash · 官方");
    expect(container.querySelector("select")).toBeNull();

    await act(async () => trigger.click());
    // Search field + provider disclosure come from the shared list body.
    expect(document.querySelector('input[aria-label="搜索模型"]')).toBeTruthy();
    const group = [...document.querySelectorAll<HTMLButtonElement>("button")]
      .find(node => (node.textContent || "").includes("官方") && node.hasAttribute("aria-expanded"))!;
    expect(group.getAttribute("aria-expanded")).toBe("true");

    const blocked = optionContaining("缺少密钥")!;
    expect(blocked.disabled).toBe(true);
    expect(blocked.textContent).toContain("此服务尚未配置 API Key");
    expect(blocked.getAttribute("aria-disabled")).toBe("true");

    const selectable = optionContaining("另一个模型")!;
    await act(async () => selectable.click());
    expect(onModelChange).toHaveBeenCalledExactlyOnceWith("next");
    expect(document.querySelector('input[aria-label="搜索模型"]')).toBeNull();
  });

  it("filters candidates by query inside the shared list", async () => {
    const { trigger } = await renderControl();
    await act(async () => trigger.click());
    const search = document.querySelector<HTMLInputElement>('input[aria-label="搜索模型"]')!;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      setter?.call(search, "另一个");
      search.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const visible = options().map(node => node.textContent || "");
    expect(visible.some(text => text.includes("另一个模型"))).toBe(true);
    expect(visible.some(text => text.includes("缺少密钥"))).toBe(false);
  });

  it("keeps settings accessible while model switching is locked by active work", async () => {
    const { trigger, onModelChange, onOpenSettings } = await renderControl({ selectionDisabled: true });
    await act(async () => trigger.click());
    expect(options().every(node => node.disabled)).toBe(true);
    const settings = [...document.querySelectorAll<HTMLButtonElement>("button")]
      .find(row => row.textContent === "模型设置")!;
    expect(settings.disabled).toBe(false);
    await act(async () => settings.click());
    expect(onOpenSettings).toHaveBeenCalledOnce();
    expect(onModelChange).not.toHaveBeenCalled();
  });

  it("pins the bound model above catalogue order inside its provider group", async () => {
  const reordered = [
    { ...CHOICES[1], modelId: "next", label: "另一个模型" },
    { ...CHOICES[0], modelId: "deepseek", label: "DeepSeek V4.1 Flash · 官方" },
    { ...CHOICES[2], modelId: "unavailable", label: "缺少密钥" },
  ];
  const { trigger } = await renderControl({ choices: reordered });
  await act(async () => trigger.click());
  const visible = options().map(node => node.textContent || "");
  expect(visible[0]).toContain("DeepSeek V4.1 Flash");
  expect(visible[1]).toContain("另一个模型");
  expect(visible[2]).toContain("缺少密钥");
});

it("retains a current model absent from the catalogue and locks pending configuration", async () => {
    const { trigger } = await renderControl({ unknownCurrent: true });
    expect(trigger.textContent).toContain("当前对话模型");
    await act(async () => trigger.click());
    const currentRow = optionContaining("当前对话模型")!;
    expect(currentRow).toBeTruthy();
    expect(currentRow.textContent).toContain("不在当前可用模型目录中");
    expect(currentRow.disabled).toBe(true);
    expect(document.querySelector('input[aria-label="搜索模型"]')).toBeTruthy();

    await act(async () => root?.unmount());
    root = undefined;
    container.remove();
    const pending = await renderControl({ pending: true });
    expect(pending.trigger.disabled).toBe(true);
  });
});