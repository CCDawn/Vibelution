// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { addDraftProvider, discoverDraftProvider, fetchConfigWorkspace, pinDraftProviderModel, previewConfigDraft, previewDraftProviderRoute, updateDraftProvider } from "../../api/config";
import { initialProviderWizardState } from "../configProviderLogic";
import type { ConfigCatalogModel, ConfigWorkspace } from "../../api/types";
import { CONFIG_COPY } from "./configCopy";
import { useConfigProviderDraftActions, type UseConfigProviderDraftActionsOptions } from "./useConfigProviderDraftActions";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../../api/config", () => ({
  addDraftProvider: vi.fn(), deleteDraftProvider: vi.fn(), discoverDraftProvider: vi.fn(),
  fetchConfigWorkspace: vi.fn(), pinDraftProviderModel: vi.fn(), previewDraftProviderRoute: vi.fn(),
  previewConfigDraft: vi.fn(),
  suggestDraftProviderId: vi.fn(), unpinDraftProviderModel: vi.fn(), updateDraftProvider: vi.fn(),
}));

function options(): UseConfigProviderDraftActionsOptions {
  const baseline = { llm: { providers: { relay: { models: {} } } } };
  const draft = structuredClone(baseline);
  const meta = { pendingApiKeyTokens: { relay: "pending-token" } } as unknown as UseConfigProviderDraftActionsOptions["draftMeta"];
  return {
    baseHash: "baseline", draftConfig: draft, draftMeta: meta, copy: CONFIG_COPY.zh,
    editBaselineRef: { current: { baseConfig: baseline, baseHash: "baseline" } },
    providerDraftRequestRef: { current: { publicConfig: draft, draftMeta: meta, baseHash: "draft-response-hash" } },
    loadFailedMessage: "load failed", activeWorkspace: null, providerPresetOptions: [],
    requireDraft: () => draft, syncWorkspace: vi.fn(), markError: vi.fn(),
    readableErrorMessage: (error) => (error as Error).message,
    providerDiscoveryFailureDetail: () => null, providerDiscoveryFailureMessage: () => "discovery failed",
    setBusyAction: vi.fn(), setProviderActionError: vi.fn(), setProviderActionFeedback: vi.fn(),
    setNotice: vi.fn(), setSelectedProviderId: vi.fn(), setSelectedProviderTab: vi.fn(),
    setProviderCredentialEditId: vi.fn(), setProviderCredentialValue: vi.fn(),
    setRouteEditProviderId: vi.fn(), setRouteEditProvider: vi.fn(), setRoutePreview: vi.fn(),
    dispatchProviderWizard: vi.fn(),
  };
}

async function run(input: UseConfigProviderDraftActionsOptions, action: (actions: ReturnType<typeof useConfigProviderDraftActions>) => Promise<void>) {
  const root = createRoot(document.createElement("div"));
  let actions!: ReturnType<typeof useConfigProviderDraftActions>;
  function Harness() { actions = useConfigProviderDraftActions(input); return null; }
  try {
    await act(async () => root.render(<Harness />));
    await act(async () => action(actions));
  } finally { await act(async () => root.unmount()); }
}

describe("provider draft baseline and failure recovery", () => {
  beforeEach(() => vi.resetAllMocks());

  it.each([false, true])("discards only new providers and exclusive pending tokens, retaining unrelated draft edits (shared env %s)", async (shared) => {
    const input = options();
    const original = {
      publicConfig: { marker: "unrelated-unsaved-edit", llm: { providers: {
        relay: { label: "Edited existing service", credential_ref: shared ? "env:NEW_KEY" : "env:SAVED_KEY" },
        new_provider: { credential_ref: "env:NEW_KEY", models: { manual: { upstream_id: "Vendor/Model" } } },
        other_draft: { credential_ref: "env:OTHER_KEY" },
      } } },
      draftMeta: { pending_api_keys: { NEW_KEY: "own-token", OTHER_KEY: "other-token" }, pending_cleared_api_keys: ["NEW_KEY", "OTHER_KEY"] },
      baseHash: "baseline",
    };
    input.providerDraftRequestRef.current = structuredClone(original);
    vi.mocked(previewConfigDraft).mockImplementation(async (request) => ({
      publicConfig: request.publicConfig, draftMeta: request.draftMeta, hash: "preview-hash", modelCatalog: { providers: {} },
    }) as ConfigWorkspace);
    await run(input, async (actions) => {
      await actions.handleDiscardDraftProviders(["new_provider", "relay"]);
    });
    const request = vi.mocked(previewConfigDraft).mock.calls[0][0];
    expect(request.publicConfig).toEqual({ marker: "unrelated-unsaved-edit", llm: { providers: {
      relay: original.publicConfig.llm.providers.relay, other_draft: original.publicConfig.llm.providers.other_draft,
    } } });
    expect(request.draftMeta).toEqual({
      pending_api_keys: shared ? { NEW_KEY: "own-token", OTHER_KEY: "other-token" } : { OTHER_KEY: "other-token" },
      pending_cleared_api_keys: shared ? ["NEW_KEY", "OTHER_KEY"] : ["OTHER_KEY"],
    });
    expect(request.baseHash).toBe("baseline");
    expect(request.baseConfig).toEqual(input.editBaselineRef.current.baseConfig);
    expect(input.providerDraftRequestRef.current).toEqual(original);
    expect(input.syncWorkspace).toHaveBeenCalledWith(expect.anything(), "neutral", { resetBase: false });
    expect(fetchConfigWorkspace).not.toHaveBeenCalled();
  });

  it("preserves the complete draft if cancel projection fails", async () => {
    const input = options();
    const original = structuredClone(input.providerDraftRequestRef.current);
    vi.mocked(previewConfigDraft).mockRejectedValueOnce(new Error("projection failed"));
    await run(input, async (actions) => {
      await expect(actions.handleDiscardDraftProviders(["new_provider"])).rejects.toThrow("projection failed");
    });
    expect(input.providerDraftRequestRef.current).toEqual(original);
    expect(input.syncWorkspace).not.toHaveBeenCalled();
  });

  it("lets the backend normalize a manual upstream ID and returns its model ref with latest pending meta", async () => {
    const input = options();
    const meta = { pending_api_keys: { relay: "new-pending-token" } };
    input.providerDraftRequestRef.current!.draftMeta = meta;
    const model = { upstreamId: "Vendor/Model-A", modelRef: "relay/vendor-model-a-1234", modelKey: "vendor-model-a-1234", availability: "pinned" } as ConfigCatalogModel;
    const response = {
      publicConfig: input.draftConfig, draftMeta: meta, hash: "new-draft-hash",
      modelCatalog: { providers: { relay: { models: { [model.modelKey]: model } } } },
    } as ConfigWorkspace;
    vi.mocked(pinDraftProviderModel).mockResolvedValueOnce(response);
    await run(input, async (actions) => {
      expect(await actions.handlePinManualProviderModel("relay", "Vendor/Model-A", { wire_protocol: "responses" })).toEqual(model);
    });
    expect(pinDraftProviderModel).toHaveBeenCalledWith("relay", expect.objectContaining({
      baseHash: "baseline", baseConfig: input.editBaselineRef.current.baseConfig,
      upstreamId: "Vendor/Model-A", modelKey: "", draftMeta: meta, overrides: { wire_protocol: "responses" },
    }));
    expect(input.syncWorkspace).toHaveBeenCalledWith(response, "success", { resetBase: false });
    expect(input.setProviderCredentialValue).not.toHaveBeenCalled();
  });

  it.each([false, true])("replaces a retry pin's protocol only in a new provider draft (saved provider %s)", async (saved) => {
    const input = options();
    const previous = { upstream_id: "Vendor/Model-A", wire_protocol: "chat_completions", interaction_contract: "old-contract" };
    input.editBaselineRef.current.baseConfig = { llm: { providers: saved ? { relay: { models: {} } } : {} } };
    input.providerDraftRequestRef.current!.publicConfig = { marker: "unrelated-edit", llm: { providers: {
      relay: { models: { canonical: previous, unrelated: { upstream_id: "other" } } },
    } } };
    const original = structuredClone(input.providerDraftRequestRef.current);
    const model = { upstreamId: "Vendor/Model-A", modelRef: "relay/canonical", modelKey: "canonical", availability: "pinned" } as ConfigCatalogModel;
    vi.mocked(pinDraftProviderModel).mockResolvedValue({
      modelCatalog: { providers: { relay: { models: { canonical: model } } } },
    } as ConfigWorkspace);
    await run(input, async (actions) => {
      await actions.handlePinManualProviderModel("relay", "Vendor/Model-A", { wire_protocol: "responses" });
    });
    const request = vi.mocked(pinDraftProviderModel).mock.calls[0][1];
    expect(request.publicConfig).toEqual({ marker: "unrelated-edit", llm: { providers: {
      relay: { models: { ...(saved ? { canonical: previous } : {}), unrelated: { upstream_id: "other" } } },
    } } });
    expect(request.overrides).toEqual({ wire_protocol: "responses" });
    expect(input.providerDraftRequestRef.current).toEqual(original);
  });

  it.each(["request", "missing"])("rejects a manual pin %s failure without replacing draft or credentials", async (failure) => {
    const input = options();
    const original = structuredClone(input.providerDraftRequestRef.current);
    if (failure === "request") {
      vi.mocked(pinDraftProviderModel).mockRejectedValueOnce(new Error("pin failed"));
    } else {
      vi.mocked(pinDraftProviderModel).mockResolvedValueOnce({ modelCatalog: { providers: {} } } as ConfigWorkspace);
    }
    await run(input, async (actions) => {
      await expect(actions.handlePinManualProviderModel("relay", "Vendor/Model-A")).rejects.toThrow();
    });
    expect(input.providerDraftRequestRef.current).toEqual(original);
    expect(input.syncWorkspace).not.toHaveBeenCalled();
    expect(input.setProviderCredentialValue).not.toHaveBeenCalled();
  });

  it("updates only an unpersisted provider on retry through route preview and retains pinned models", async () => {
    const input = options();
    input.editBaselineRef.current.baseConfig = { llm: { providers: {} } };
    const models = { pinned: { upstream_id: "pinned", enabled: true } };
    const existing = { label: "Draft", base_url: "https://wrong.example", models };
    input.providerDraftRequestRef.current!.publicConfig = { llm: { providers: { relay: existing } } };
    vi.mocked(previewDraftProviderRoute).mockResolvedValue({
      providerId: "relay", routeChanged: true, routePreviewToken: "single-use-token", modelRefs: ["relay/pinned"], impactedRefs: [],
    });
    vi.mocked(updateDraftProvider).mockImplementation(async (_id, request) => ({
      publicConfig: request.publicConfig, draftMeta: request.draftMeta, hash: "draft-hash", modelCatalog: { providers: {} },
    }) as ConfigWorkspace);
    await run(input, async (actions) => {
      await actions.handleCreateProvider({ ...initialProviderWizardState(), providerId: "relay", baseUrl: "https://fixed.example/v1" }, "fixed-key");
    });
    expect(addDraftProvider).not.toHaveBeenCalled();
    expect(previewDraftProviderRoute).toHaveBeenCalledWith("relay", expect.objectContaining({
      baseHash: "baseline", baseConfig: input.editBaselineRef.current.baseConfig, draftMeta: input.draftMeta,
      provider: expect.objectContaining({ base_url: "https://fixed.example/v1", models }),
    }));
    expect(updateDraftProvider).toHaveBeenCalledWith("relay", expect.objectContaining({
      routePreviewToken: "single-use-token", credentialValue: "fixed-key", draftMeta: input.draftMeta,
      provider: expect.objectContaining({ base_url: "https://fixed.example/v1", models }),
    }));
    expect(existing.base_url).toBe("https://wrong.example");
    expect(input.syncWorkspace).toHaveBeenCalledWith(expect.anything(), "success", { resetBase: false });
  });

  it("never silently updates a provider already present in the saved baseline", async () => {
    const input = options();
    const original = structuredClone(input.providerDraftRequestRef.current);
    vi.mocked(addDraftProvider).mockRejectedValueOnce(new Error("provider already exists"));
    await run(input, async (actions) => {
      await expect(actions.handleCreateProvider({ ...initialProviderWizardState(), providerId: "relay" }, "key"))
        .rejects.toThrow("provider already exists");
    });
    expect(previewDraftProviderRoute).not.toHaveBeenCalled();
    expect(updateDraftProvider).not.toHaveBeenCalled();
    expect(input.syncWorkspace).not.toHaveBeenCalled();
    expect(input.providerDraftRequestRef.current).toEqual(original);
    expect(input.setProviderCredentialValue).not.toHaveBeenCalled();
  });

  it.each(["preview", "update"])("rethrows a draft %s failure without changing the draft or clearing credentials", async (stage) => {
    const input = options();
    input.editBaselineRef.current.baseConfig = { llm: { providers: {} } };
    const original = structuredClone(input.providerDraftRequestRef.current);
    vi.mocked(previewDraftProviderRoute).mockResolvedValueOnce({
      providerId: "relay", routeChanged: true, routePreviewToken: "single-use-token", modelRefs: [], impactedRefs: [],
    });
    if (stage === "preview") {
      vi.mocked(previewDraftProviderRoute).mockReset().mockRejectedValueOnce(new Error("baseline conflict"));
    } else {
      vi.mocked(updateDraftProvider).mockRejectedValueOnce(new Error("baseline conflict"));
    }
    await run(input, async (actions) => {
      await expect(actions.handleCreateProvider({ ...initialProviderWizardState(), providerId: "relay" }, "key"))
        .rejects.toThrow("baseline conflict");
    });
    expect(updateDraftProvider).toHaveBeenCalledTimes(stage === "update" ? 1 : 0);
    expect(input.providerDraftRequestRef.current).toEqual(original);
    expect(input.syncWorkspace).not.toHaveBeenCalled();
    expect(input.setProviderCredentialValue).not.toHaveBeenCalled();
  });

  it("does not infer an unpersisted provider when the edit baseline is missing", async () => {
    const input = options();
    input.editBaselineRef.current.baseConfig = null;
    vi.mocked(addDraftProvider).mockRejectedValueOnce(new Error("provider already exists"));
    await run(input, async (actions) => {
      await expect(actions.handleCreateProvider({ ...initialProviderWizardState(), providerId: "relay" }, "key"))
        .rejects.toThrow("provider already exists");
    });
    expect(previewDraftProviderRoute).not.toHaveBeenCalled();
    expect(updateDraftProvider).not.toHaveBeenCalled();
  });

  it("sends the paired baseline and preserves draft plus pending credentials on conflict", async () => {
    const input = options();
    const original = structuredClone(input.providerDraftRequestRef.current);
    vi.mocked(discoverDraftProvider).mockRejectedValue(new Error("当前供应商已被其他页面改动"));
    await run(input, async (actions) => {
      await expect(actions.handleDiscoverProvider("relay")).rejects.toThrow("当前供应商已被其他页面改动");
    });
    expect(discoverDraftProvider).toHaveBeenCalledWith("relay", expect.objectContaining({
      baseHash: "baseline", baseConfig: input.editBaselineRef.current.baseConfig,
      publicConfig: input.draftConfig, draftMeta: input.draftMeta,
    }));
    expect(fetchConfigWorkspace).not.toHaveBeenCalled();
    expect(input.syncWorkspace).not.toHaveBeenCalled();
    expect(input.providerDraftRequestRef.current).toEqual(original);
    expect(input.setProviderCredentialValue).not.toHaveBeenCalled();
    expect(input.setProviderActionFeedback).toHaveBeenLastCalledWith(expect.objectContaining({ phase: "error" }));
  });

  it("keeps the same baseline across consecutive pins and uses the updated draft", async () => {
    const input = options();
    const models = ["one", "two"].map((id) => ({
      modelRef: `relay/${id}`, modelKey: id, upstreamId: id, label: id, availability: "observed",
    })) as ConfigCatalogModel[];
    vi.mocked(pinDraftProviderModel).mockImplementation(async (_id, request) => ({
      publicConfig: { ...request.publicConfig, marker: request.modelKey },
      draftMeta: request.draftMeta, hash: "new-draft-hash", baseHash: "wrong-response-baseline",
      modelCatalog: { providers: {} },
    }) as ConfigWorkspace);
    await run(input, async (actions) => {
      expect(await actions.handlePinProviderModels("relay", models)).toBe(true);
    });
    const calls = vi.mocked(pinDraftProviderModel).mock.calls;
    expect(calls).toHaveLength(2);
    for (const [, request] of calls) {
      expect(request.baseHash).toBe("baseline");
      expect(request.baseConfig).toEqual(input.editBaselineRef.current.baseConfig);
      expect(request.draftMeta).toEqual(input.draftMeta);
    }
    expect(calls[1][1].publicConfig).toHaveProperty("marker", "one");
    expect(input.syncWorkspace).toHaveBeenLastCalledWith(expect.anything(), "success", { resetBase: false });
  });
});

describe("pinned model whitelist edit (wave 3 governance path B)", () => {
  beforeEach(() => vi.resetAllMocks());

  function pinnedEntryOptions() {
    const input = options();
    const draft = input.draftConfig as Record<string, unknown>;
    const llm = draft.llm as Record<string, unknown>;
    const providers = llm.providers as Record<string, unknown>;
    providers.relay = {
      label: "Relay",
      models: {
        luna: {
          upstream_id: "luna-upstream",
          label: "Luna",
          enabled: true,
          wire_protocol: "responses",
          interaction_contract: "tool_chat",
          defaults: {
            reasoning_effort_values: ["low", "medium", "high"],
            reasoning_effort_adapter: "reasoning_object",
            default_reasoning_effort: "medium",
            temperature: 0.7,
          },
        },
      },
    };
    input.providerDraftRequestRef.current = {
      publicConfig: structuredClone(draft),
      draftMeta: input.draftMeta,
      baseHash: "baseline",
    };
    return input;
  }

  it("applies only whitelist edits to the draft entry and keeps protocol fields", async () => {
    const input = pinnedEntryOptions();
    vi.mocked(updateDraftProvider).mockImplementation(async (_id, request) => ({
      publicConfig: request.publicConfig, draftMeta: request.draftMeta,
      hash: "draft-hash", baseHash: request.baseHash, modelCatalog: { providers: {} },
    }) as ConfigWorkspace);
    await run(input, async (actions) => {
      const ok = await actions.handleUpdatePinnedModel("relay/luna", {
        label: "Luna fast",
        temperature: "0.2",
        default_reasoning_effort: "high",
        // @ts-expect-error — protocol keys are not valid edits; the gate drops them.
        wire_protocol: "chat_completions",
      });
      expect(ok).toBe(true);
    });
    const request = vi.mocked(updateDraftProvider).mock.calls[0][1];
    const models = (request.provider.models as Record<string, unknown>);
    expect(models.luna).toEqual({
      upstream_id: "luna-upstream",
      label: "Luna fast",
      enabled: true,
      wire_protocol: "responses",
      interaction_contract: "tool_chat",
      defaults: {
        reasoning_effort_values: ["low", "medium", "high"],
        reasoning_effort_adapter: "reasoning_object",
        default_reasoning_effort: "high",
        temperature: 0.2,
      },
    });
    expect(input.syncWorkspace).toHaveBeenLastCalledWith(expect.anything(), "success", { resetBase: false });
    expect(input.setProviderActionFeedback).toHaveBeenLastCalledWith(
      expect.objectContaining({ kind: "model", phase: "success" }),
    );
  });

  it("reports an error without writing when the model is not pinned in the draft", async () => {
    const input = pinnedEntryOptions();
    await run(input, async (actions) => {
      const ok = await actions.handleUpdatePinnedModel("relay/ghost", { label: "X" });
      expect(ok).toBe(false);
    });
    expect(updateDraftProvider).not.toHaveBeenCalled();
    expect(input.syncWorkspace).not.toHaveBeenCalled();
    expect(input.setProviderActionFeedback).toHaveBeenLastCalledWith(
      expect.objectContaining({ kind: "model", phase: "error" }),
    );
  });
});
