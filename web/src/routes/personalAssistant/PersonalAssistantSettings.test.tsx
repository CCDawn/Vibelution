// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  fetchPersonalAssistantSettings,
  updatePersonalAssistantModel,
  updatePersonalAssistantSettings,
} from "../../api/personalAssistant";
import type { PersonalAssistantSettings } from "../../api/types/personalAssistant";
import { PersonalAssistantSettings as SettingsDialog, assistantModelChoiceLabel } from "./PersonalAssistantSettings";
import { enqueuePetPreferenceOperation } from "../desktopPet/usePetPreferences";

vi.mock("../../api/personalAssistant", () => ({
  fetchPersonalAssistantSettings: vi.fn(),
  updatePersonalAssistantSettings: vi.fn(),
  updatePersonalAssistantModel: vi.fn(),
}));
vi.mock("../../app/userActionTelemetry", () => ({ postUserActionObservation: vi.fn() }));
vi.mock("../../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh" }) }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const settings: PersonalAssistantSettings = {
  displayName: "个人助理",
  preferences: { characterId: "dafeiyu", showStatus: true, showTitles: true, showCompletion: true, idleMessage: "" },
  preferencesConfigured: false,
  model: {
    currentModelId: "assistant-model",
    choices: [
      { modelId: "assistant-model", label: "助理模型", providerLabel: "测试通道", isDefault: true,
        providerHealthy: true, missingApiKey: false, availability: "available" },
      { modelId: "whale-xl", label: "大模型", providerLabel: "测试通道", isDefault: false,
        providerHealthy: true, missingApiKey: false, availability: "available" },
      { modelId: "broken-model", label: "坏通道", providerLabel: "旧通道", isDefault: false,
        providerHealthy: false, missingApiKey: false, availability: "unavailable" },
    ],
  },
};

let root: Root, container: HTMLDivElement, client: QueryClient;
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchPersonalAssistantSettings).mockResolvedValue({ settings });
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); client.clear(); });
async function settle() { await act(async () => new Promise(resolve => setTimeout(resolve, 25))); }
async function render(open: boolean) {
  await act(async () => root.render(<QueryClientProvider client={client}>
    <SettingsDialog open={open} onOpenChange={() => {}} />
  </QueryClientProvider>));
  await settle(); await settle();
}

describe("assistant settings dialog", () => {
  it("does not read settings while closed and shows the surface once opened", async () => {
    await render(false);
    expect(fetchPersonalAssistantSettings).not.toHaveBeenCalled();
    await render(true);
    expect(fetchPersonalAssistantSettings).toHaveBeenCalled();
    expect((document.querySelector('input[aria-label="助理名称"]') as HTMLInputElement)?.value).toBe("个人助理");
    expect(document.body.textContent).toContain("助理设置");
    expect(document.body.textContent).toContain("默认外观");
    expect(document.body.textContent).toContain("对话模型");
    expect(document.body.textContent).toContain("只对那个会话生效");
    expect(document.body.textContent).not.toContain("小洛");
  });

  it("saves a rename through the settings API", async () => {
    vi.mocked(updatePersonalAssistantSettings).mockResolvedValue({ settings: { ...settings, displayName: "小洛管家" } });
    await render(true);
    const input = document.querySelector('input[aria-label="助理名称"]') as HTMLInputElement;
    const nativeInputValue = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
    await act(async () => {
      nativeInputValue?.call(input, "小洛管家");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const save = [...document.querySelectorAll("button")].find(button => button.textContent === "保存名称") as HTMLButtonElement;
    await act(async () => save.click());
    await settle();
    expect(updatePersonalAssistantSettings).toHaveBeenCalledWith({ displayName: "小洛管家" });
    expect(document.body.textContent).toContain("已保存");
  });

  it("confirms an appearance save with the shared saved feedback", async () => {
    vi.mocked(updatePersonalAssistantSettings).mockResolvedValue({ settings: { ...settings, preferences: { ...settings.preferences, characterId: "xiaoluo" } } });
    await render(true);
    const trigger = document.querySelector('button[role="combobox"][aria-label="默认外观"]') as HTMLButtonElement;
    await act(async () => trigger.click());
    const option = await vi.waitFor(() => {
      const found = [...document.body.querySelectorAll('[role="option"]')].find(node => node.textContent === "小洛");
      if (!found) throw new Error("appearance options not rendered yet");
      return found as HTMLElement;
    });
    await act(async () => option.click());
    await settle();
    expect(updatePersonalAssistantSettings).toHaveBeenCalledWith({ preferences: { characterId: "xiaoluo" } });
    expect(document.body.textContent).toContain("已保存");
  });

  it("keeps the rename button disabled until the draft changes", async () => {
    await render(true);
    const save = [...document.querySelectorAll("button")].find(button => button.textContent === "保存名称") as HTMLButtonElement;
    expect(save.disabled).toBe(true);
  });
  it("waits for pending migration before saving an appearance from the dialog", async () => {
    let release!: () => void;
    const migration = enqueuePetPreferenceOperation(() => new Promise<void>(resolve => { release = resolve; }));
    await render(true);
    vi.mocked(updatePersonalAssistantSettings).mockResolvedValue({ settings: { ...settings, preferences: { ...settings.preferences, characterId: "xiaoluo" } } });
    const trigger = document.querySelector('button[role="combobox"][aria-label="默认外观"]') as HTMLButtonElement;
    await act(async () => trigger.click());
    const option = await vi.waitFor(() => {
      const found = [...document.body.querySelectorAll('[role="option"]')].find(node => node.textContent === "小洛");
      if (!found) throw new Error("appearance options not rendered yet");
      return found as HTMLElement;
    });
    await act(async () => option.click());
    expect(updatePersonalAssistantSettings).not.toHaveBeenCalled();
    await act(async () => { release(); await migration; }); await settle();
    expect(updatePersonalAssistantSettings).toHaveBeenCalledWith({ preferences: { characterId: "xiaoluo" } });
  });

  it("shows a retryable read failure instead of a silent fallback", async () => {
    vi.mocked(fetchPersonalAssistantSettings).mockRejectedValue(new Error("后端不可用"));
    await render(true);
    expect(document.body.textContent).toContain("助理设置读取失败");
    expect(document.body.textContent).toContain("后端不可用");
    vi.mocked(fetchPersonalAssistantSettings).mockResolvedValue({ settings });
    await act(async () => ([...document.querySelectorAll("button")].find(button => button.textContent === "重试") as HTMLButtonElement).click());
    await settle(); await settle();
    expect((document.querySelector('input[aria-label="助理名称"]') as HTMLInputElement)?.value).toBe("个人助理");
  });

  it("labels unhealthy channels and keeps the whitelist helper pure", () => {
    expect(assistantModelChoiceLabel(settings.model.choices[0], "zh")).toBe("测试通道 · 助理模型");
    expect(assistantModelChoiceLabel(settings.model.choices[2], "zh")).toBe("旧通道 · 坏通道（通道不可用）");
    expect(assistantModelChoiceLabel({ ...settings.model.choices[0], missingApiKey: true }, "en")).toContain("API key missing");
  });
});
