// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { seedControlTokenForTests } from "../api/client";
import { readConfigDraftPresence } from "./configDraftPresence";
import { CONFIG_COPY } from "./config/configCopy";
import { MODEL_SETTINGS_COPY } from "./config/modelSettingsCopy";
import { ConfigRoute } from "./ConfigRoute";
import type { ConfigProviderRegistryPanelProps } from "./ConfigProviderRegistryPanel";

vi.mock("./ConfigProviderRegistryPanel", () => ({ ConfigProviderRegistryPanel: (props: ConfigProviderRegistryPanelProps) => <div>
  <button data-testid="edit-model-input" onClick={() => props.onModelEditorDraftChange?.("relay/model.v1", { label: "Raw model draft", temperature: "0.4" })}>Edit local model</button>
  <button data-testid="edit-model-enabled-input" onClick={() => props.onModelEditorDraftChange?.("relay/model.v1", { enabled: true, label: "Raw model draft", temperature: "0.4" })}>Retain model fields</button>
  <button data-testid="edit-only-model-enabled-input" onClick={() => props.onModelEditorDraftChange?.("relay/model.v1", { enabled: true })}>Retain model enabled</button>
  <button data-testid="invalid-model-input" onClick={() => props.onModelEditorDraftChange?.("relay/model.v1", { context_window: "1e" })}>Invalid local model</button>
  <button data-testid="test-model-input" onClick={() => props.onTestModel("relay/model.v1")}>Test model draft</button>
  <button data-testid="pin-extra-model" onClick={() => props.onPin("relay", [{ availability: "observed", label: "Extra model", modelKey: "extra", modelRef: "relay/extra", status: "observed", upstreamId: "extra", capabilities: {} }])}>Pin another model</button>
  <button data-testid="remove-model-input" onClick={() => props.onUnpin("relay/model.v1")}>Remove edited model</button>
  <output data-testid="raw-model-draft">{JSON.stringify(props.modelEditorDrafts ?? {})}</output>
  <button data-testid="add-subscription" disabled={props.disabled || Boolean(props.subscriptionSetupBlockedReason)} onClick={() => void props.onAddSubscriptionModels?.([
    { slug: "test-plan", display_name: "Plan", visibility: "list", supported_in_api: true, supported_reasoning_levels: [], input_modalities: ["text"] },
  ], { label: "ChatGPT", auth_kind: "oauth", credential_ref: "oauth:chatgpt", driver: "openai", service_class: "official_api", base_url: "https://api.openai.com/v1", protocols: { default: "responses", allowed: ["responses"], routes: { responses: "responses" } } })}>Add subscription</button>
  <button data-testid="stage-provider" disabled={props.disabled} onClick={() => props.onUpdateModel?.("relay", "model.v1", { label: "Draft model" })}>Stage label</button>
  <button data-testid="toggle-provider" disabled={props.disabled} onClick={() => props.onToggleEnabled?.("relay", false)}>Disable</button>
  <button data-testid="toggle-model" disabled={props.disabled} onClick={() => props.onToggleModelEnabled?.("relay/model.v1", false)}>Disable model</button>
  <output data-testid="provider-enabled">{String(props.rows.find((row) => row.providerId === "relay")?.enabled)}</output>
  <output data-testid="model-enabled">{String(props.rows.find((row) => row.providerId === "relay")?.models.find((model) => model.modelKey === "model.v1")?.draftEntry?.enabled !== false)}</output>
  <output data-testid="provider-draft">{props.rows.find((row) => row.providerId === "relay")?.models.find((model) => model.modelKey === "model.v1")?.label}</output>
  <output data-testid="provider-ids">{props.rows.map((row) => row.providerId).join(",")}</output>
</div> }));

const BASE = { language: "zh", llm: { decision_models: { "local.v1": { label: "Local decision", model_id: "small", base_url: "http://127.0.0.1:8088/v1/systemone", enabled: true, min_probability: 0.8, note: "" } }, decision_handoff_model_id: "local.v1", providers: { relay: { label: "Relay", enabled: true, context_window: 16000, models: { "model.v1": { upstream_id: "test", label: "Saved model" } } } } } };
const EMPTY_META = { pending_api_keys: {}, pending_cleared_api_keys: [] as string[] };
function workspace(config: typeof BASE | Record<string, unknown> = BASE, meta = EMPTY_META, baseHash = "saved-1") {
  const providers = (config as typeof BASE).llm.providers;
  return { hash: "projection", baseHash, language: "zh", runtimeProfile: "balanced", defaultMode: "supervised", defaultRoute: "", intakeMode: "manual",
    modeAvailability: {}, domainAvailability: {}, modelLibraryCount: 0, modelLabels: {}, modelImageInputSupport: {}, blockingCount: 0, warningCount: 0,
    sections: [{ id: "models", title: "模型服务", summary: "" }], message: "", configPath: "operator.toml", publicConfig: config,
    featureDecisions: { configRevision: "", source: "", features: {} }, rawToml: "", draftMeta: meta,
    diagnosis: { blocking_issues: [], warnings: [], suggested_actions: [] }, summary: {}, editorSections: [], editorMeta: {}, modelPresetOptions: [], providerPresetOptions: [],
    modelOptions: [{ api_key_configured: true }], schemaVersion: 2,
    providerOptions: Object.entries(providers).map(([id, entry]) => ({ provider_id: id, label: entry.label, enabled: entry.enabled, context_window: entry.context_window,
      service_class: "relay", vendor: "multi_model", driver: "openai", credential_state: "configured", pinned_count: 0 })),
    modelCatalog: { schemaVersion: 2, providerCount: Object.keys(providers).length, modelCount: 0, providers: {} }, modelAliasUsage: { aliases: [], totalLiveReferenceCount: 0 },
  };
}
function installFetch(options: { initialConfig?: typeof BASE; failApply?: boolean; failProjectionAfterSave?: boolean; waitForApply?: Promise<void>; waitForPin?: Promise<void>; waitForTest?: Promise<void> } = {}) {
  let disk = structuredClone(options.initialConfig ?? BASE);
  let hash = "saved-1";
  const applyCalls: Record<string, any>[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input); const body = init?.body ? JSON.parse(String(init.body)) : {};
    const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
    if (url.includes("/api/config/workspace")) return response(workspace(disk, EMPTY_META, hash));
    if (url.endsWith("/api/config/draft/providers/id-suggestion")) return response({ suggestedProviderId: "chatgpt" });
    if (url.endsWith("/api/config/draft/providers")) {
      const draft = structuredClone(body.publicConfig);
      draft.llm.providers[body.providerId] = body.provider;
      return response(workspace(draft, body.draftMeta, hash));
    }
    if (url.endsWith("/api/config/draft/providers/chatgpt/models")) {
      await options.waitForPin;
      const draft = structuredClone(body.publicConfig);
      draft.llm.providers.chatgpt.models[body.upstreamId] = { upstream_id: body.upstreamId, label: body.label };
      return response(workspace(draft, body.draftMeta, hash));
    }
    if (url.endsWith("/api/config/draft/providers/relay/models")) {
      const draft = structuredClone(body.publicConfig);
      draft.llm.providers.relay.models[body.upstreamId] = { upstream_id: body.upstreamId, label: body.label };
      return response(workspace(draft, body.draftMeta, hash));
    }
    if (url.endsWith("/api/config/draft/providers/relay/models/model.v1") && init?.method === "DELETE") {
      const draft = structuredClone(body.publicConfig);
      delete draft.llm.providers.relay.models["model.v1"];
      return response(workspace(draft, body.draftMeta, hash));
    }
    if (url.endsWith("/api/config/test-llm")) { await options.waitForTest; return response({ ok: true, provider_id: "relay", model_id: body.modelId, message: "Passed", capability: "text" }); }
    if (url.includes("/api/config/draft/providers/relay")) {
      const draft = structuredClone(body.publicConfig);
      draft.llm.providers.relay = body.provider;
      draft.llm.providers.pending = { label: "Pending", enabled: true, context_window: 8000, models: { "model.v1": { upstream_id: "pending-test" } } };
      return response(workspace(draft, { pending_api_keys: { TEST: "test-only-token" }, pending_cleared_api_keys: ["OLD_TEST"] }, hash));
    }
    if (url.includes("/api/config/draft/preview")) {
      if (options.failProjectionAfterSave && hash !== "saved-1" && body.publicConfig.llm.providers.pending) return response({ detail: "projection unavailable" }, 500);
      return response(workspace(body.publicConfig, body.draftMeta, body.baseHash));
    }
    if (url.includes("/api/config/apply")) {
      applyCalls.push(body);
      await options.waitForApply;
      if (options.failApply) return response({ detail: "save failed" }, 500);
      disk = body.publicConfig; hash = "saved-" + (applyCalls.length + 1);
      return response(workspace(disk, EMPTY_META, hash));
    }
    if (url.includes("/api/diagnostics")) return response({ blocking_issues: [], warnings: [] });
    return response({}, 404);
  }));
  return applyCalls;
}

describe("provider enable auto-save isolation", () => {
  let container: HTMLElement; let root: Root; let client: QueryClient;
  beforeEach(() => { container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); seedControlTokenForTests(); });
  afterEach(async () => { await act(async () => root.unmount()); container.remove(); client.clear(); vi.unstubAllGlobals(); window.sessionStorage.clear(); window.localStorage.clear(); });
  async function ready() {
    const router = createMemoryRouter([{ path: "/config", element: <QueryClientProvider client={client}><ConfigRoute /></QueryClientProvider> }, { path: "/elsewhere", element: <p>Other page</p> }],
      { initialEntries: ["/config?section=models-profiles&page=model-connection"] });
    await act(async () => root.render(<RouterProvider router={router} />));
    await wait(() => !!container.querySelector('[data-testid="toggle-provider"]'));
    return router;
  }
  async function wait(predicate: () => boolean) { const end = Date.now() + 4000; while (!predicate()) { if (Date.now() > end) throw new Error("condition timed out"); await act(async () => new Promise((resolve) => setTimeout(resolve, 20))); } }
  async function click(id: string) { await act(async () => (container.querySelector(`[data-testid="${id}"]`) as HTMLButtonElement).click()); }
  function saveButton() {
    const button = [...container.querySelectorAll<HTMLButtonElement>('[data-vui="settings-form-footer"] button')]
      .find((item) => item.textContent?.trim() === MODEL_SETTINGS_COPY.zh.save);
    if (!button) throw new Error("Missing model settings save action");
    return button;
  }
  async function openUsage() {
    const tab = [...container.querySelectorAll<HTMLButtonElement>('[role="tab"]')]
      .find((item) => item.textContent === MODEL_SETTINGS_COPY.zh.usage)!;
    await act(async () => tab.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })));
    const panel = container.querySelector<HTMLElement>('[data-testid="config-decision-models"]')!;
    expect(panel.closest("[hidden]")).toBeNull();
    return panel;
  }

  it.each([false, true])("saves only enabled and preserves all unrelated drafts, including projection failure %s", async (failProjectionAfterSave) => {
    const calls = installFetch({ failProjectionAfterSave }); await ready();
    await click("stage-provider"); await wait(() => container.querySelector('[data-testid="provider-draft"]')?.textContent === "Draft model");
    await click("toggle-provider"); await wait(() => container.querySelector('[data-testid="provider-enabled"]')?.textContent === "false");
    expect(calls).toHaveLength(1);
    expect(calls[0].publicConfig.llm.providers).toEqual({ relay: { ...BASE.llm.providers.relay, enabled: false } });
    expect(calls[0].draftMeta).toEqual(EMPTY_META);
    expect(calls[0].baseConfig).toEqual(BASE);
    expect(container.querySelector('[data-testid="provider-draft"]')?.textContent).toBe("Draft model");
    expect(container.querySelector('[data-testid="provider-ids"]')?.textContent).toContain("pending");
    const save = saveButton();
    expect(save).toBeTruthy(); await act(async () => save!.click()); await wait(() => calls.length === 2);
    expect(calls[1].publicConfig.llm.providers.relay.enabled).toBe(false);
    expect(calls[1].publicConfig.llm.providers.relay.models["model.v1"].label).toBe("Draft model");
    expect(calls[1].publicConfig.llm.providers.pending.models).toHaveProperty("model.v1");
    expect(calls[1].draftMeta).toEqual({ pending_api_keys: { TEST: "test-only-token" }, pending_cleared_api_keys: ["OLD_TEST"] });
    expect(calls[1].baseHash).toBe("saved-2");
  });

  it("leaves saved state and text drafts intact if persistence fails", async () => {
    const calls = installFetch({ failApply: true }); await ready(); await click("stage-provider");
    await wait(() => container.querySelector('[data-testid="provider-draft"]')?.textContent === "Draft model");
    await click("toggle-provider"); await wait(() => calls.length === 1 && !!container.querySelector('[class*="noticeError"]'));
    expect(container.querySelector('[data-testid="provider-enabled"]')?.textContent).toBe("true");
    expect(container.querySelector('[data-testid="provider-draft"]')?.textContent).toBe("Draft model");
    expect(container.querySelector('[data-testid="provider-ids"]')?.textContent).toContain("pending");
  });

  it("guards repeated events before React can disable the controls", async () => {
    let release!: () => void; const waiting = new Promise<void>((resolve) => { release = resolve; });
    const calls = installFetch({ waitForApply: waiting }); await ready();
    await act(async () => { const button = container.querySelector('[data-testid="toggle-provider"]') as HTMLButtonElement; button.click(); button.click(); });
    await wait(() => calls.length === 1); expect(calls).toHaveLength(1);
    await act(async () => release()); await wait(() => container.querySelector('[data-testid="provider-enabled"]')?.textContent === "false");
    expect(saveButton().disabled).toBe(true);
  });

  it.each([false, true])("saves only one model enabled field while retaining provider, secret and model text drafts (projection failure %s)", async (failProjectionAfterSave) => {
    const initialConfig = {
      ...BASE,
      llm: { ...BASE.llm, providers: { relay: { ...BASE.llm.providers.relay, models: {
        ...BASE.llm.providers.relay.models,
        sibling: { upstream_id: "sibling", label: "Saved sibling", enabled: true },
      } } } },
    };
    const calls = installFetch({ initialConfig, failProjectionAfterSave }); await ready();
    await click("stage-provider");
    await wait(() => container.querySelector('[data-testid="provider-draft"]')?.textContent === "Draft model");
    await click("edit-model-enabled-input");
    await click("toggle-model");
    await wait(() => calls.length === 1 && !(container.querySelector('[data-testid="toggle-model"]') as HTMLButtonElement).disabled);
    expect(calls[0].publicConfig).toEqual({
      ...initialConfig,
      llm: { ...initialConfig.llm, providers: { relay: { ...initialConfig.llm.providers.relay, models: {
        ...initialConfig.llm.providers.relay.models,
        "model.v1": { ...BASE.llm.providers.relay.models["model.v1"], enabled: false },
      } } } },
    });
    expect(calls[0].draftMeta).toEqual(EMPTY_META);
    expect(calls[0].baseConfig).toEqual(initialConfig);
    expect(calls[0].baseHash).toBe("saved-1");
    expect(container.querySelector('[data-testid="model-enabled"]')?.textContent).toBe("false");
    expect(container.querySelector('[data-testid="provider-enabled"]')?.textContent).toBe("true");
    expect(container.querySelector('[data-testid="provider-draft"]')?.textContent).toBe("Draft model");
    expect(container.querySelector('[data-testid="provider-ids"]')?.textContent).toContain("pending");
    expect(JSON.parse(container.querySelector('[data-testid="raw-model-draft"]')!.textContent!)).toEqual({
      "relay/model.v1": { label: "Raw model draft", temperature: "0.4" },
    });
    expect(readConfigDraftPresence()).toBe(true);
    await act(async () => saveButton().click());
    await wait(() => calls.length === 2);
    expect(calls[1].publicConfig.llm.providers.relay.enabled).toBe(true);
    expect(calls[1].publicConfig.llm.providers.relay.models["model.v1"]).toEqual({
      upstream_id: "test", label: "Raw model draft", enabled: false, defaults: { temperature: 0.4 },
    });
    expect(calls[1].publicConfig.llm.providers.relay.models.sibling).toEqual(initialConfig.llm.providers.relay.models.sibling);
    expect(calls[1].publicConfig.llm.providers.pending.models).toHaveProperty("model.v1");
    expect(calls[1].draftMeta).toEqual({ pending_api_keys: { TEST: "test-only-token" }, pending_cleared_api_keys: ["OLD_TEST"] });
    expect(calls[1].baseHash).toBe("saved-2");
  });

  it("keeps the saved model enabled state and every retained draft when its immediate save fails", async () => {
    const calls = installFetch({ failApply: true }); await ready();
    await click("stage-provider");
    await wait(() => container.querySelector('[data-testid="provider-draft"]')?.textContent === "Draft model");
    await click("edit-model-enabled-input");
    await click("toggle-model");
    await wait(() => calls.length === 1 && !!container.querySelector('[class*="noticeError"]'));
    expect(calls[0].publicConfig.llm.providers.relay).toEqual({ ...BASE.llm.providers.relay, models: {
      "model.v1": { ...BASE.llm.providers.relay.models["model.v1"], enabled: false },
    } });
    expect(calls[0].draftMeta).toEqual(EMPTY_META);
    expect(container.querySelector('[data-testid="model-enabled"]')?.textContent).toBe("true");
    expect(container.querySelector('[data-testid="provider-enabled"]')?.textContent).toBe("true");
    expect(container.querySelector('[data-testid="provider-draft"]')?.textContent).toBe("Draft model");
    expect(container.querySelector('[data-testid="provider-ids"]')?.textContent).toContain("pending");
    expect(JSON.parse(container.querySelector('[data-testid="raw-model-draft"]')!.textContent!)).toEqual({
      "relay/model.v1": { enabled: true, label: "Raw model draft", temperature: "0.4" },
    });
    expect(readConfigDraftPresence()).toBe(true);
    expect(calls).toHaveLength(1);
  });

  it("deduplicates model switch events before React disables the control", async () => {
    let release!: () => void;
    const waiting = new Promise<void>((resolve) => { release = resolve; });
    const calls = installFetch({ waitForApply: waiting }); await ready();
    await click("edit-only-model-enabled-input");
    expect(readConfigDraftPresence()).toBe(true);
    const toggle = container.querySelector<HTMLButtonElement>('[data-testid="toggle-model"]')!;
    await act(async () => { toggle.click(); toggle.click(); });
    await wait(() => calls.length === 1);
    expect(toggle.disabled).toBe(true);
    expect(container.querySelector('[data-testid="model-enabled"]')?.textContent).toBe("true");
    await act(async () => release());
    await wait(() => container.querySelector('[data-testid="model-enabled"]')?.textContent === "false" && !toggle.disabled);
    expect(calls).toHaveLength(1);
    expect(saveButton().disabled).toBe(true);
    expect(container.querySelector('[data-testid="raw-model-draft"]')?.textContent).toBe("{}");
    expect(readConfigDraftPresence()).toBe(false);
  });

  it("holds the shared settings busy state throughout subscription pinning and releases it after save", async () => {
    let release!: () => void;
    const waiting = new Promise<void>((resolve) => { release = resolve; });
    const calls = installFetch({ waitForPin: waiting }); await ready();
    await click("add-subscription");
    await wait(() => container.querySelector('[data-testid="provider-ids"]')?.textContent?.includes("chatgpt") === true);
    expect((container.querySelector('[data-testid="toggle-provider"]') as HTMLButtonElement).disabled).toBe(true);
    await click("toggle-provider");
    expect(calls).toHaveLength(0);
    await act(async () => release());
    await wait(() => calls.length === 1 && !(container.querySelector('[data-testid="toggle-provider"]') as HTMLButtonElement).disabled);
    expect(calls[0].publicConfig.llm.providers.chatgpt.models).toHaveProperty("test-plan");
    expect(calls[0].publicConfig.llm.providers.relay.enabled).toBe(true);
    expect(calls[0].publicConfig.llm.decision_handoff_model_id).toBe("local.v1");
  });
  it("saves a decision toggle and unbinds handoff atomically without publishing its text draft", async () => {
    const calls = installFetch(); await ready();
    const panel = await openUsage();
    await act(async () => (panel.querySelector('[aria-label="编辑 Local decision"]') as HTMLButtonElement).click());
    const editor = panel.querySelector('[data-testid="decision-model-editor"]')!;
    const label = editor.querySelector('input[type="text"]') as HTMLInputElement;
    expect(label.value).toBe("Local decision");
    await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(label, "Draft decision name"); label.dispatchEvent(new Event("input", { bubbles: true })); });
    await act(async () => (editor.querySelector('input[type="checkbox"]') as HTMLInputElement).click());
    await wait(() => calls.length === 1 && !(editor.querySelector('input[type="checkbox"]') as HTMLInputElement).checked);
    expect(calls[0].publicConfig.llm.decision_models["local.v1"]).toEqual({ ...BASE.llm.decision_models["local.v1"], enabled: false });
    expect(calls[0].publicConfig.llm.decision_handoff_model_id).toBe("");
    expect(label.value).toBe("Draft decision name");
    await act(async () => label.dispatchEvent(new FocusEvent("focusout", { bubbles: true })));
    await wait(() => !saveButton().disabled);
    expect(calls).toHaveLength(1);
  });

  it("folds retained model inputs into one explicit save without publishing them during an immediate toggle", async () => {
    const calls = installFetch(); await ready();
    await click("edit-model-input");
    expect(calls).toHaveLength(0);
    await click("toggle-provider");
    await wait(() => calls.length === 1);
    expect(calls[0].publicConfig.llm.providers.relay.models["model.v1"].label).toBe("Saved model");
    expect(container.querySelector('[data-testid="raw-model-draft"]')?.textContent).toContain("Raw model draft");
    const save = saveButton();
    await wait(() => !save.disabled);
    await act(async () => save.click());
    await wait(() => calls.length === 2);
    expect(calls[1].publicConfig.llm.providers.relay.models["model.v1"]).toEqual({ upstream_id: "test", label: "Raw model draft", defaults: { temperature: 0.4 } });
    expect(calls[1].publicConfig.llm.decision_models).toEqual(BASE.llm.decision_models);
    await wait(() => container.querySelector('[data-testid="raw-model-draft"]')?.textContent === "{}");
  });

  it("retains model inputs after failed save and blocks invalid numeric drafts", async () => {
    const calls = installFetch({ failApply: true }); await ready();
    await click("edit-model-input");
    const save = saveButton();
    await act(async () => save.click());
    await wait(() => calls.length === 1 && !save.disabled);
    expect(container.querySelector('[data-testid="raw-model-draft"]')?.textContent).toContain("Raw model draft");
    await click("invalid-model-input");
    expect(save.disabled).toBe(true);
    expect(container.querySelector('[data-testid="raw-model-draft"]')?.textContent).toContain("1e");
    expect(calls).toHaveLength(1);
  });

  it("keeps the cross-window dirty guard after an explicit override saves a different model", async () => {
    const calls = installFetch(); await ready();
    await click("edit-model-input");
    expect(readConfigDraftPresence()).toBe(true);
    await click("pin-extra-model");
    await wait(() => calls.length === 1);
    await wait(() => !(container.querySelector('[data-testid="toggle-provider"]') as HTMLButtonElement).disabled);
    expect(calls[0].publicConfig.llm.providers.relay.models).toHaveProperty("extra");
    expect(calls[0].publicConfig.llm.providers.relay.models["model.v1"].label).toBe("Saved model");
    expect(container.querySelector('[data-testid="raw-model-draft"]')?.textContent).toContain("Raw model draft");
    expect(readConfigDraftPresence()).toBe(true);
  });

  it("tests current model edits without persisting them", async () => {
    const calls = installFetch(); await ready(); await click("edit-model-input");
    await click("test-model-input");
    const request = vi.mocked(fetch).mock.calls.find(([input]) => String(input).endsWith("/api/config/test-llm"));
    expect(request).toBeDefined();
    const body = JSON.parse(String(request![1]?.body));
    expect(body.publicConfig.llm.providers.relay.models["model.v1"]).toEqual({ upstream_id: "test", label: "Raw model draft", defaults: { temperature: 0.4 } });
    expect(calls).toHaveLength(0);
    expect(readConfigDraftPresence()).toBe(true);
  });

  it("clears only the edited model after an accepted removal so remaining config can save", async () => {
    const calls = installFetch(); await ready(); await click("edit-model-input");
    await click("remove-model-input");
    await wait(() => calls.length === 1);
    expect(calls[0].publicConfig.llm.providers.relay.models).not.toHaveProperty("model.v1");
    expect(calls[0].publicConfig.llm.decision_models).toEqual(BASE.llm.decision_models);
    expect(container.querySelector('[data-testid="raw-model-draft"]')?.textContent).toBe("{}");
  });

  it("blocks leaving retained model inputs while a model test is running", async () => {
    let release!: () => void;
    const waitForTest = new Promise<void>((resolve) => { release = resolve; });
    installFetch({ waitForTest }); const router = await ready();
    await click("edit-model-input"); await click("test-model-input");
    await act(async () => { void router.navigate("/elsewhere"); });
    expect(router.state.location.pathname).toBe("/config");
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain("还有未保存的设置");
    expect(container.querySelector('[data-testid="raw-model-draft"]')?.textContent).toContain("Raw model draft");
    await act(async () => release());
  });

  it("reports unfinished decision input to the page and clears it only after explicit discard", async () => {
    const calls = installFetch(); const router = await ready();
    const panel = await openUsage();
    const add = [...panel.querySelectorAll('button')].find((button) => button.textContent?.trim() === "添加")!;
    await act(async () => add.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true })));
    const custom = [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')].find((item) => item.textContent === "自定义")!;
    await act(async () => custom.click());
    const editor = panel.querySelector('[data-testid="decision-model-editor"]')!;
    const input = editor.querySelector('input[type="text"]') as HTMLInputElement;
    await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "Unfinished decision"); input.dispatchEvent(new Event("input", { bubbles: true })); });
    const back = panel.querySelector<HTMLButtonElement>('button[aria-label="返回用途"]')!;
    await act(async () => back.click());
    expect(readConfigDraftPresence()).toBe(true);
    const save = saveButton();
    expect(save.disabled).toBe(true);
    expect(container.textContent).toContain("有尚未完成的模型编辑");
    await act(async () => { void router.navigate("/elsewhere"); });
    expect(router.state.location.pathname).toBe("/config");
    const leaveDialog = document.querySelector('[role="dialog"]')!;
    const cancel = [...leaveDialog.querySelectorAll('button')].find((button) => button.textContent?.trim() === "取消")!;
    await act(async () => cancel.click());
    const discard = [...container.querySelectorAll('button')].find((button) => button.textContent?.trim() === CONFIG_COPY.zh.discardChanges)!;
    await act(async () => discard.click());
    const confirm = document.querySelector('[role="dialog"]')!;
    const discardConfirm = [...confirm.querySelectorAll('button')].find((button) => button.textContent?.trim() === CONFIG_COPY.zh.discardAndReload)!;
    await act(async () => discardConfirm.click());
    await wait(() => !container.textContent?.includes("Unfinished decision"));
    await wait(() => !readConfigDraftPresence());
    expect(calls).toHaveLength(0);
  });

});
