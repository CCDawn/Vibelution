// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { initialProviderQuickSetupState } from "../configProviderLogic";
import { useConfigProviderQuickSetupActions, type UseConfigProviderQuickSetupActionsOptions } from "./useConfigProviderQuickSetupActions";

function options(): UseConfigProviderQuickSetupActionsOptions {
  const initial = initialProviderQuickSetupState();
  return {
    providerQuickSetupState: { ...initial, phase: "review", provider: { ...initial.provider, providerId: "test" }, selectedModelRef: "test/model",
      discoveredModels: [{ availability: "observed", modelRef: "test/model", modelKey: "model", label: "Test", upstreamId: "model", status: "observed", capabilities: {} }] },
    providerPresetOptions: [], providerDraftRequestRef: { current: null }, queryClient: new QueryClient(),
    dispatchProviderQuickSetup: vi.fn(), setProviderQuickCredential: vi.fn(), handleSuggestProviderId: vi.fn(),
    handleCreateProvider: vi.fn(), handleDiscoverProvider: vi.fn(), handlePinProviderModels: vi.fn().mockResolvedValue(true),
    handleApply: vi.fn().mockResolvedValue(true), readableErrorMessage: String,
  };
}

async function run(input: UseConfigProviderQuickSetupActionsOptions) {
  const container = document.createElement("div");
  const root = createRoot(container);
  let actions!: ReturnType<typeof useConfigProviderQuickSetupActions>;
  function Harness() { actions = useConfigProviderQuickSetupActions(input); return null; }
  try {
    await act(async () => root.render(<Harness />));
    await act(async () => actions.handleConfirmProviderQuickSetup());
  } finally { await act(async () => root.unmount()); input.queryClient.clear(); }
}

describe("quick setup save recovery", () => {
  it("does not apply or report success when adding the model fails", async () => {
    const input = options(); vi.mocked(input.handlePinProviderModels).mockResolvedValue(false);
    await run(input);
    expect(input.handleApply).not.toHaveBeenCalled();
    expect(input.dispatchProviderQuickSetup).toHaveBeenCalledWith(expect.objectContaining({ type: "save_failed", errorKind: "save" }));
    expect(input.dispatchProviderQuickSetup).not.toHaveBeenCalledWith({ type: "save_succeeded" });
  });
  it("retries only formal save after a partial save failure", async () => {
    const input = options();
    input.providerQuickSetupState = { ...input.providerQuickSetupState, phase: "error", errorKind: "partial_save" };
    await run(input);
    expect(input.handlePinProviderModels).not.toHaveBeenCalled();
    expect(input.handleCreateProvider).not.toHaveBeenCalled();
    expect(input.handleDiscoverProvider).not.toHaveBeenCalled();
    expect(input.handleApply).toHaveBeenCalledOnce();
    expect(input.dispatchProviderQuickSetup).toHaveBeenCalledWith({ type: "save_succeeded" });
  });
  it("keeps a failed apply retryable without a false success", async () => {
    const input = options(); vi.mocked(input.handleApply).mockResolvedValue(false);
    await run(input);
    expect(input.dispatchProviderQuickSetup).toHaveBeenCalledWith(expect.objectContaining({ type: "save_failed", errorKind: "partial_save" }));
    expect(input.dispatchProviderQuickSetup).not.toHaveBeenCalledWith({ type: "save_succeeded" });
  });
});
