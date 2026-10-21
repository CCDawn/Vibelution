/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ConfigProviderPresetOption } from "../api/types";
import { ConfigQuickSetupPanel, templateToProvider, type ConfigQuickSetupPanelProps } from "./ConfigQuickSetupPanel";
import { CONFIG_COPY } from "./config/configCopy";
import { initialProviderQuickSetupState } from "./configProviderLogic";

const templates: ConfigProviderPresetOption[] = [{
  provider_preset_id: "openai", label: "OpenAI", vendor_id: "openai", vendor_label: "OpenAI",
  category: "official", provider_id: "openai", source_preset_id: "openai",
  provider: { service_class: "official_api", base_url: "https://api.openai.com/v1", auth_kind: "api_key", credential_ref: "env:OPENAI_API_KEY", driver: "openai", protocols: { default: "responses", allowed: ["responses"] } },
  default_model: { model: "gpt-5.5", model_ref: "openai/gpt-5.5" },
}, {
  provider_preset_id: "local", label: "Local", vendor_id: "local", vendor_label: "Local", category: "local", provider_id: "local", source_preset_id: "local",
  provider: { service_class: "local_runtime", base_url: "http://127.0.0.1:11434/v1", auth_kind: "none", credential_ref: "none", driver: "openai", protocols: { default: "chat_completions" } },
  default_model: { model: "qwen3:8b", model_ref: "local/qwen" },
}, {
  provider_preset_id: "custom_openai_compatible_relay", label: "自定义 OpenAI 兼容 API", vendor_id: "custom", vendor_label: "Custom", category: "openai_compatible", provider_id: "custom", source_preset_id: "custom_openai_compatible_relay",
  provider: { service_class: "self_hosted", base_url: "", auth_kind: "api_key", credential_ref: "env:CUSTOM_API_KEY", driver: "openai", protocols: { default: "chat_completions" } }, default_model: {},
}];
function props(overrides: Partial<ConfigQuickSetupPanelProps> = {}): ConfigQuickSetupPanelProps {
  return {
    copy: CONFIG_COPY.zh, state: { ...initialProviderQuickSetupState(), provider: templateToProvider(templates[0]) },
    templates, credentialValue: "safe-test-key", disabled: false,
    onCredentialChange: vi.fn(), onProviderChange: vi.fn(), onDetect: vi.fn(), onModelChange: vi.fn(),
    onConfirm: vi.fn(), onReset: vi.fn(), onTestAndSave: vi.fn(), ...overrides,
  };
}

describe("ConfigQuickSetupPanel single form", () => {
  let host: HTMLDivElement;
  let root: Root;
  beforeEach(() => { (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true; host = document.createElement("div"); document.body.append(host); root = createRoot(host); });
  afterEach(() => { act(() => root.unmount()); host.remove(); });
  function mount(input: ConfigQuickSetupPanelProps) { act(() => root.render(<ConfigQuickSetupPanel {...input} />)); }
  function input(suffix: string) { const element = host.querySelector<HTMLInputElement>(`input[id$='-${suffix}']`); if (!element) throw Error(`Missing ${suffix}`); return element; }
  function changeModel(value: string) { const control = input("model"); act(() => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(control, value); control.dispatchEvent(new Event("input", { bubbles: true })); }); }
  function select(suffix: string, label: string) {
    const control = host.querySelector<HTMLButtonElement>(`[role="combobox"][id$='-${suffix}']`)!;
    act(() => control.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true })));
    const option = [...document.querySelectorAll<HTMLElement>('[role="option"]')]
      .find((item) => item.textContent?.trim() === label);
    if (!option) throw Error(`Missing option ${label}`);
    act(() => option.click());
  }
  function button(label: string) { const match = [...host.querySelectorAll<HTMLButtonElement>("button")].find((item) => item.textContent?.trim() === label); if (!match) throw Error(`Missing button ${label}`); return match; }
  function submit() { act(() => host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }))); }

  it("shows all connection fields together and submits the upstream template ID without discovery", () => {
    const current = props(); mount(current);
    expect(input("model").value).toBe("gpt-5.5");
    expect(input("endpoint").value).toBe("https://api.openai.com/v1");
    expect(input("label").value).toBe("OpenAI");
    expect(host.querySelector("details")?.open).toBe(false);
    submit();
    expect(current.onTestAndSave).toHaveBeenCalledWith({ provider: current.state.provider, credentialValue: "safe-test-key", modelId: "gpt-5.5" });
    expect(current.onDetect).not.toHaveBeenCalled();
    expect(current.onConfirm).not.toHaveBeenCalled();
  });
  it("preserves a typed model when provider ID suggestions or discovery results rerender the same template", () => {
    const current = props(); mount(current); changeModel("my/custom-upstream");
    mount({ ...current, state: { ...current.state, provider: { ...current.state.provider, providerId: "openai_2" }, phase: "review", selectedModelRef: "internal/recommended", discoveredModels: [{ availability: "observed", status: "observed", label: "Recommended", modelKey: "internal/recommended", modelRef: "internal/recommended", upstreamId: "different-upstream", capabilities: {} }] } });
    expect(input("model").value).toBe("my/custom-upstream"); submit();
    expect(current.onTestAndSave).toHaveBeenCalledWith(expect.objectContaining({ modelId: "my/custom-upstream" }));
  });
  it("resets the model only for a different template and allows local no-auth services without paths", () => {
    const current = props(); mount(current); changeModel("manual-model");
    mount({ ...current, credentialValue: "", state: { ...current.state, provider: templateToProvider(templates[1]) } });
    expect(input("model").value).toBe("qwen3:8b");
    expect(host.querySelector('input[type="password"]')).toBeNull();
    expect(host.textContent).not.toContain("artifact_path");
    expect(host.textContent).not.toContain("runtime_framework"); submit();
    expect(current.onTestAndSave).toHaveBeenCalledWith(expect.objectContaining({ modelId: "qwen3:8b", credentialValue: "" }));
  });
  it("keeps direct model entry and save available after model discovery fails", () => {
    const current = props(); current.state = { ...current.state, phase: "error", errorKind: "discovery", errorMessage: "404 models unavailable" }; mount(current);
    changeModel("still-supported-model");
    expect(host.querySelectorAll('[role="alert"]')).toHaveLength(1);
    expect(button(CONFIG_COPY.zh.quickSetupTestAndSave).disabled).toBe(false); submit();
    expect(current.onTestAndSave).toHaveBeenCalledWith(expect.objectContaining({ modelId: "still-supported-model" }));
    act(() => button(CONFIG_COPY.zh.quickSetupGetModels).click());
    expect(current.onDetect).toHaveBeenCalledWith({ provider: current.state.provider, credentialValue: "safe-test-key" });
  });
  it("copies a discovered upstream ID into the model input while retaining the legacy modelRef callback", () => {
    const current = props(); current.state.discoveredModels = [{ availability: "observed", status: "observed", label: "Special", modelKey: "internal-key", modelRef: "provider/internal-key", upstreamId: "actual-upstream-id", capabilities: {} }];
    mount(current); select("catalog", "Special · actual-upstream-id");
    expect(input("model").value).toBe("actual-upstream-id");
    expect(current.onModelChange).toHaveBeenCalledWith("provider/internal-key"); submit();
    expect(current.onTestAndSave).toHaveBeenCalledWith(expect.objectContaining({ modelId: "actual-upstream-id" }));
  });
  it.each(["checking", "saving"] as const)("blocks edits, model fetching and duplicate submits during %s", (phase) => {
    const current = props(); current.state.phase = phase; mount(current);
    expect(host.querySelector("fieldset")?.disabled).toBe(true);
    const selects = [...host.querySelectorAll<HTMLButtonElement>('[role="combobox"]')];
    expect(selects).toHaveLength(3);
    expect(selects.every((control) => control.disabled)).toBe(true);
    expect(button(CONFIG_COPY.zh.quickSetupGetModels).disabled).toBe(true);
    expect(button(CONFIG_COPY.zh.quickSetupTestAndSave).disabled).toBe(true);
    expect(button(CONFIG_COPY.zh.quickSetupTestAndSave).getAttribute("aria-busy")).toBe("true"); submit();
    expect(current.onTestAndSave).not.toHaveBeenCalled();
  });
  it("shows one error message near the credential, and one primary action", () => {
    const current = props(); current.state = { ...current.state, phase: "error", errorKind: "auth", errorMessage: "401 credential rejected" }; mount(current);
    expect(host.querySelectorAll('[role="alert"]')).toHaveLength(1);
    expect(host.textContent?.match(/401 credential rejected/g)).toHaveLength(1);
    expect(input("credential").getAttribute("aria-invalid")).toBe("true");
    expect([...host.querySelectorAll("button")].filter((item) => item.textContent?.trim() === CONFIG_COPY.zh.quickSetupTestAndSave)).toHaveLength(1);
  });
  it("retains model input on save conflicts and exposes the saved Agent handoff", () => {
    const current = props({ onConfigureAgent: vi.fn() }); mount(current); changeModel("saved-model"); submit();
    mount({ ...current, state: { ...current.state, phase: "error", errorKind: "save", errorMessage: "conflict; retry" } });
    expect(input("model").value).toBe("saved-model"); submit(); expect(current.onTestAndSave).toHaveBeenCalledTimes(2);
    mount({ ...current, state: { ...current.state, phase: "success" } });
    expect(host.textContent).toContain(CONFIG_COPY.zh.quickSetupSavedBody); expect(host.textContent).toContain("saved-model");
    act(() => button(CONFIG_COPY.zh.quickSetupGoAgents).click()); expect(current.onConfigureAgent).toHaveBeenCalledOnce();
  });
  it("uses the backend custom preset credential reference and restores it when auth is re-enabled", () => {
    const current = props(); mount(current); select("provider", CONFIG_COPY.zh.quickSetupCustomService);
    const provider = vi.mocked(current.onProviderChange).mock.calls[0][0];
    expect(provider).toMatchObject({ templateId: "custom_openai_compatible_relay", credentialRef: "env:CUSTOM_API_KEY" });
    expect(templates.find((template) => template.provider_preset_id === provider.templateId)).toBeDefined();
    mount({ ...current, state: { ...current.state, provider: { ...provider, authKind: "none", credentialRef: "none" } } }); select("auth", "API Key");
    expect(current.onProviderChange).toHaveBeenLastCalledWith(expect.objectContaining({ authKind: "api_key", credentialRef: "env:CUSTOM_API_KEY" }));
  });
  it("wires cancel without invoking save and renders translated copy", () => {
    const current = props({ copy: CONFIG_COPY.en, onCancel: vi.fn() }); mount(current);
    act(() => button(CONFIG_COPY.en.cancel).click()); expect(current.onCancel).toHaveBeenCalledOnce(); expect(current.onTestAndSave).not.toHaveBeenCalled();
    expect(host.textContent).toContain(CONFIG_COPY.en.quickSetupTestAndSave);
  });
  it("does not derive an upstream model ID from an internal model_ref", () => {
    const template = { ...templates[0], default_model: { model_ref: "provider/internal-only" } };
    const markup = renderToStaticMarkup(<ConfigQuickSetupPanel {...props({ templates: [template] })} />);
    expect(markup).not.toContain('value="provider/internal-only"');
  });
});
