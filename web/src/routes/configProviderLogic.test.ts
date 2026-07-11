import { describe, expect, it } from "vitest";

import type { ConfigCatalogModel, ConfigModelCatalog, ConfigProviderOption } from "../api/types";
import {
  canAdvanceProviderWizard,
  deriveProviderRegistryRows,
  initialProviderWizardState,
  providerWizardReducer,
} from "./configProviderLogic";

const providers: ConfigProviderOption[] = [
  {
    provider_id: "relay_a",
    label: "Shared label",
    service_class: "relay",
    vendor: "multi_model",
    driver: "openai",
    runtime_framework: "",
    artifact_path: "",
    base_url: "https://relay.example/v1",
    credential_state: "configured",
    default_protocol: "responses",
    pinned_count: 1,
  },
  {
    provider_id: "relay_b",
    label: "Shared label",
    service_class: "relay",
    vendor: "multi_model",
    driver: "openai",
    runtime_framework: "",
    artifact_path: "",
    base_url: "https://relay.example/v1",
    credential_state: "missing",
    default_protocol: "responses",
    pinned_count: 1,
  },
];

function catalogModel(modelRef: string): ConfigCatalogModel {
  return {
    modelKey: "gpt-a",
    modelRef,
    upstreamId: "gpt-a",
    label: "GPT A",
    availability: "pinned",
    status: "pinned",
  };
}

const catalog: ConfigModelCatalog = {
  schemaVersion: 2,
  providerCount: 2,
  modelCount: 2,
  providers: {
    relay_a: {
      providerId: "relay_a",
      status: "reachable",
      catalogStale: false,
      lastAttemptAt: "2026-07-11T12:00:00Z",
      lastSuccessAt: "2026-07-11T12:00:00Z",
      lastErrorType: "",
      refreshDue: false,
      modelCount: 1,
      pinnedCount: 1,
      observedCount: 0,
      models: { "gpt-a": catalogModel("relay_a/gpt-a") },
      warnings: [],
    },
    relay_b: {
      providerId: "relay_b",
      status: "auth_failed",
      catalogStale: true,
      lastAttemptAt: "2026-07-11T12:01:00Z",
      lastSuccessAt: "",
      lastErrorType: "auth_failed",
      refreshDue: true,
      modelCount: 1,
      pinnedCount: 1,
      observedCount: 0,
      models: { "gpt-a": catalogModel("relay_b/gpt-a") },
      warnings: [],
    },
  },
};

describe("configProviderLogic", () => {
  it("uses backend provider ids and keeps same-name models distinct", () => {
    const rows = deriveProviderRegistryRows(providers, catalog);

    expect(rows.map((row) => row.providerId)).toEqual(["relay_a", "relay_b"]);
    expect(rows.flatMap((row) => row.models.map((model) => model.modelRef))).toEqual([
      "relay_a/gpt-a",
      "relay_b/gpt-a",
    ]);
    expect(rows[1].credentialState).toBe("missing");
    expect(rows[1].status).toBe("auth_failed");
  });

  it("accepts the redacted provider mutation allowlist without inventing identity", () => {
    const projectedProviders: ConfigProviderOption[] = [
      {
        provider_id: "relay_a",
        label: "Relay A",
        service_class: "relay",
        vendor: "multi_model",
        driver: "openai",
        credential_state: "configured",
        default_protocol: "responses",
        pinned_count: 1,
      },
    ];

    const [row] = deriveProviderRegistryRows(projectedProviders, catalog);

    expect(row.providerId).toBe("relay_a");
    expect(row.baseUrl).toBe("");
    expect(row.runtimeFramework).toBe("");
    expect(row.artifactPath).toBe("");
  });

  it("advances the wizard only after the current step contract is satisfied", () => {
    let state = initialProviderWizardState();
    expect(canAdvanceProviderWizard(state)).toBe(false);

    state = providerWizardReducer(state, {
      type: "choose_template",
      templateId: "relay_openai",
      serviceClass: "relay",
    });
    expect(canAdvanceProviderWizard(state)).toBe(true);

    state = providerWizardReducer(state, { type: "next" });
    expect(state.step).toBe("connection");
    expect(canAdvanceProviderWizard(state)).toBe(false);

    state = providerWizardReducer(state, {
      type: "set_connection",
      providerId: "relay_a",
      label: "Relay A",
      baseUrl: "https://relay.example/v1",
      credentialRef: "env:RELAY_A_KEY",
    });
    expect(canAdvanceProviderWizard(state)).toBe(true);
  });

  it("keeps reducer output immutable and ignores raw credential values", () => {
    const initial = initialProviderWizardState();
    const state = providerWizardReducer(initial, {
      type: "set_connection",
      providerId: "stable_provider",
      label: "Label Can Change",
      baseUrl: "https://relay.example/v1",
      credentialRef: "env:RELAY_KEY",
      credentialValue: "must-not-survive",
    } as never);

    expect(state).not.toBe(initial);
    expect(initial.providerId).toBe("");
    expect(state.providerId).toBe("stable_provider");
    expect(JSON.stringify(state)).not.toContain("must-not-survive");
  });

  it("keeps local deployment and protocol requirements inside the connection boundary", () => {
    let state = providerWizardReducer(initialProviderWizardState(), {
      type: "choose_template",
      templateId: "local_vllm",
      serviceClass: "local_runtime",
    });
    state = providerWizardReducer(state, { type: "next" });
    state = providerWizardReducer(state, {
      type: "set_connection",
      providerId: "local_a",
      label: "Local A",
      baseUrl: "",
      credentialRef: "none",
    });
    expect(canAdvanceProviderWizard(state)).toBe(false);

    state = providerWizardReducer(state, {
      type: "set_protocol",
      driver: "openai",
      defaultProtocol: "responses",
    });
    expect(canAdvanceProviderWizard(state)).toBe(false);

    state = providerWizardReducer(state, {
      type: "set_deployment",
      runtimeFramework: "vllm",
      artifactPath: "models/local-a",
    });
    expect(canAdvanceProviderWizard(state)).toBe(true);
  });

  it("pins only canonical model refs returned by backend discovery", () => {
    const discovered = catalogModel("relay_a/gpt-a");
    let state = {
      ...initialProviderWizardState(),
      step: "discovery" as const,
      providerId: "relay_a",
    };
    state = providerWizardReducer(state, { type: "set_discovery", models: [discovered] });
    expect(canAdvanceProviderWizard(state)).toBe(true);

    state = providerWizardReducer(state, { type: "next" });
    expect(state.step).toBe("pin");
    state = providerWizardReducer(state, { type: "toggle_pin", modelRef: "label-derived/gpt-a" });
    expect(state.pinnedModelRefs).toEqual([]);

    state = providerWizardReducer(state, { type: "toggle_pin", modelRef: "relay_a/gpt-a" });
    expect(state.pinnedModelRefs).toEqual(["relay_a/gpt-a"]);
    expect(canAdvanceProviderWizard(state)).toBe(true);
  });
});
