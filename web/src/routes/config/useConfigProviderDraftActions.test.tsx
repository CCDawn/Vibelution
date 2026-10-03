// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { discoverDraftProvider, fetchConfigWorkspace, pinDraftProviderModel, updateDraftProvider } from "../../api/config";
import type { ConfigCatalogModel, ConfigWorkspace } from "../../api/types";
import { CONFIG_COPY } from "./configCopy";
import { useConfigProviderDraftActions, type UseConfigProviderDraftActionsOptions } from "./useConfigProviderDraftActions";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../../api/config", () => ({
  addDraftProvider: vi.fn(), deleteDraftProvider: vi.fn(), discoverDraftProvider: vi.fn(),
  fetchConfigWorkspace: vi.fn(), pinDraftProviderModel: vi.fn(), previewDraftProviderRoute: vi.fn(),
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
  beforeEach(() => vi.clearAllMocks());

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
  beforeEach(() => vi.clearAllMocks());

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
