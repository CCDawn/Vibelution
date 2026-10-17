// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { seedControlTokenForTests } from "../api/client";
import { ConfigRoute } from "./ConfigRoute";
import type { ConfigProviderRegistryPanelProps } from "./ConfigProviderRegistryPanel";

vi.mock("./ConfigProviderRegistryPanel", () => ({ ConfigProviderRegistryPanel: (props: ConfigProviderRegistryPanelProps) => <div>
  <button data-testid="stage-provider" disabled={props.disabled} onClick={() => props.onUpdateModel?.("relay", "model.v1", { label: "Draft model" })}>Stage label</button>
  <button data-testid="toggle-provider" disabled={props.disabled} onClick={() => props.onToggleEnabled?.("relay", false)}>Disable</button>
  <output data-testid="provider-enabled">{String(props.rows.find((row) => row.providerId === "relay")?.enabled)}</output>
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
function installFetch(options: { failApply?: boolean; failProjectionAfterSave?: boolean; waitForApply?: Promise<void> } = {}) {
  let disk = structuredClone(BASE);
  let hash = "saved-1";
  const applyCalls: Record<string, any>[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input); const body = init?.body ? JSON.parse(String(init.body)) : {};
    const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
    if (url.includes("/api/config/workspace")) return response(workspace(disk, EMPTY_META, hash));
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
    const router = createMemoryRouter([{ path: "/config", element: <QueryClientProvider client={client}><ConfigRoute /></QueryClientProvider> }],
      { initialEntries: ["/config?section=models-profiles&page=model-connection"] });
    await act(async () => root.render(<RouterProvider router={router} />));
    await wait(() => !!container.querySelector('[data-testid="toggle-provider"]'));
  }
  async function wait(predicate: () => boolean) { const end = Date.now() + 4000; while (!predicate()) { if (Date.now() > end) throw new Error("condition timed out"); await act(async () => new Promise((resolve) => setTimeout(resolve, 20))); } }
  async function click(id: string) { await act(async () => (container.querySelector(`[data-testid="${id}"]`) as HTMLButtonElement).click()); }

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
    const save = [...container.querySelectorAll('button')].find((button) => button.textContent?.trim() === "保存更改");
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
    expect([...container.querySelectorAll('button')].some((button) => button.textContent?.trim() === "保存更改")).toBe(false);
  });
  it("saves a decision toggle and unbinds handoff atomically without publishing its text draft", async () => {
    const calls = installFetch(); await ready();
    const panel = container.querySelector('[data-testid="config-decision-models"]')!;
    const label = panel.querySelector('input[type="text"]') as HTMLInputElement;
    expect(label.value).toBe("Local decision");
    await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(label, "Draft decision name"); label.dispatchEvent(new Event("input", { bubbles: true })); });
    await act(async () => (panel.querySelector('input[type="checkbox"]') as HTMLInputElement).click());
    await wait(() => calls.length === 1 && !(panel.querySelector('input[type="checkbox"]') as HTMLInputElement).checked);
    expect(calls[0].publicConfig.llm.decision_models["local.v1"]).toEqual({ ...BASE.llm.decision_models["local.v1"], enabled: false });
    expect(calls[0].publicConfig.llm.decision_handoff_model_id).toBe("");
    expect(label.value).toBe("Draft decision name");
    await act(async () => label.dispatchEvent(new FocusEvent("focusout", { bubbles: true })));
    await wait(() => [...container.querySelectorAll('button')].some((button) => button.textContent?.trim() === "保存更改"));
    expect(calls).toHaveLength(1);
  });

});
