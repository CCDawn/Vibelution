import { describe, expect, it } from "vitest";

import type { ConfigCatalogModel, ConfigModelCatalog, ConfigProviderOption } from "../api/types";
import {
  canAdvanceProviderWizard,
  canUnpinProviderModel,
  deriveProviderRegistryRows,
  dispatchProviderWizardConnectionAction,
  filterAlreadyPinnedModels,
  initialProviderWizardState,
  isProviderWizardConnectionLocked,
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
  const modelKey = modelRef.split("/").at(-1) || "";
  return {
    modelKey,
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
    expect(rows.map((row) => row.pinnedCount)).toEqual([1, 1]);
  });

  it("allows unpin only for backend-owned pinned or missing-remote models", () => {
    const [provider] = deriveProviderRegistryRows(providers, catalog);
    const pinned = catalogModel("relay_a/pinned");
    const missingRemote = { ...catalogModel("relay_a/missing"), availability: "missing_remote" as const };
    const observed = { ...catalogModel("relay_a/observed"), availability: "observed" as const };

    expect(canUnpinProviderModel(provider, pinned)).toBe(true);
    expect(canUnpinProviderModel(provider, missingRemote)).toBe(true);
    expect(canUnpinProviderModel(provider, observed)).toBe(false);
    expect(canUnpinProviderModel({ ...provider, pinnedCount: 0 }, pinned)).toBe(false);
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
    expect(canAdvanceProviderWizard(state)).toBe(false);
    state = providerWizardReducer(state, {
      type: "set_protocol",
      driver: "openai",
      defaultProtocol: "responses",
      allowedProtocols: ["responses"],
    });
    expect(canAdvanceProviderWizard(state)).toBe(true);
  });

  it("keeps reducer output immutable and ignores raw credential values", () => {
    const initial = initialProviderWizardState();
    const template = providerWizardReducer(initial, {
      type: "choose_template",
      templateId: "relay_openai",
      serviceClass: "relay",
    });
    const connection = providerWizardReducer(template, { type: "next" });
    const state = providerWizardReducer(connection, {
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
      baseUrl: "http://127.0.0.1:8001/v1",
      credentialRef: "none",
    });
    expect(canAdvanceProviderWizard(state)).toBe(false);

    state = providerWizardReducer(state, {
      type: "set_protocol",
      driver: "openai",
      defaultProtocol: "responses",
      allowedProtocols: ["responses"],
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
    const otherProvider = catalogModel("relay_b/gpt-a");
    const malformed = catalogModel("relay_a/gpt/a");
    let state = {
      ...initialProviderWizardState(),
      step: "discovery" as const,
      providerId: "relay_a",
    };
    state = providerWizardReducer(state, {
      type: "set_discovery",
      models: [otherProvider, malformed, discovered],
    });
    expect(state.discoveredModels.map((model) => model.modelRef)).toEqual(["relay_a/gpt-a"]);
    expect(canAdvanceProviderWizard(state)).toBe(true);

    state = providerWizardReducer(state, { type: "next" });
    expect(state.step).toBe("pin");
    state = providerWizardReducer(state, { type: "toggle_pin", modelRef: "label-derived/gpt-a" });
    expect(state.pinnedModelRefs).toEqual([]);

    state = providerWizardReducer(state, { type: "toggle_pin", modelRef: "relay_a/gpt-a" });
    expect(state.pinnedModelRefs).toEqual(["relay_a/gpt-a"]);
    expect(canAdvanceProviderWizard(state)).toBe(true);

    const stalePins = { ...state, pinnedModelRefs: ["relay_b/gpt-a"] };
    expect(canAdvanceProviderWizard(stalePins)).toBe(false);

    state = providerWizardReducer(state, { type: "back" });
    state = providerWizardReducer(state, {
      type: "set_discovery",
      models: [catalogModel("relay_a/gpt-b")],
    });
    expect(state.pinnedModelRefs).toEqual([]);
  });

  it("keeps only unfinished pins after partial success and filters them on retry", () => {
    const models = ["a", "b", "c"].map((key) => ({
      ...catalogModel(`relay_a/${key}`),
      modelKey: key,
      upstreamId: key,
    }));
    let state = {
      ...initialProviderWizardState(),
      step: "pin" as const,
      providerId: "relay_a",
      discoveredModels: models,
      pinnedModelRefs: models.map((model) => model.modelRef),
    };

    state = providerWizardReducer(state, { type: "pin_succeeded", modelRef: "relay_a/a" });
    state = providerWizardReducer(state, { type: "pin_succeeded", modelRef: "relay_a/b" });
    expect(state.pinnedModelRefs).toEqual(["relay_a/c"]);
    expect(state.discoveredModels.map((model) => model.modelRef)).toEqual(["relay_a/c"]);

    const retry = filterAlreadyPinnedModels(models, new Set(["relay_a/a", "relay_a/b"]));
    expect(retry.map((model) => model.modelRef)).toEqual(["relay_a/c"]);
  });

  it("locks every saved connection field after Provider creation", () => {
    expect(isProviderWizardConnectionLocked(false, false)).toBe(false);
    expect(isProviderWizardConnectionLocked(true, false)).toBe(true);
    expect(isProviderWizardConnectionLocked(false, true)).toBe(true);

    const actions: Parameters<typeof providerWizardReducer>[1][] = [];
    const action = {
      type: "set_connection" as const,
      providerId: "relay_a",
      label: "Ignored",
      baseUrl: "https://ignored.example/v1",
      credentialRef: "none",
    };
    expect(dispatchProviderWizardConnectionAction(true, action, (next) => actions.push(next))).toBe(false);
    expect(actions).toEqual([]);
    expect(dispatchProviderWizardConnectionAction(false, action, (next) => actions.push(next))).toBe(true);
    expect(actions).toEqual([action]);
  });

  it("rejects actions outside their owning wizard step", () => {
    const initial = initialProviderWizardState();
    expect(providerWizardReducer(initial, {
      type: "set_connection",
      providerId: "illegal",
      label: "Illegal",
      baseUrl: "https://illegal.example/v1",
      credentialRef: "none",
    })).toBe(initial);

    const template = providerWizardReducer(initial, {
      type: "choose_template",
      templateId: "relay_openai",
      serviceClass: "relay",
    });
    const connection = providerWizardReducer(template, { type: "next" });
    expect(providerWizardReducer(connection, {
      type: "choose_template",
      templateId: "other",
      serviceClass: "official_api",
    })).toBe(connection);
    expect(providerWizardReducer(connection, {
      type: "set_discovery",
      models: [catalogModel("relay_a/gpt-a")],
    })).toBe(connection);

    const discovery = { ...connection, step: "discovery" as const, providerId: "relay_a" };
    expect(providerWizardReducer(discovery, { type: "toggle_pin", modelRef: "relay_a/gpt-a" })).toBe(discovery);
  });

  it("clears downstream state when template, connection, protocol, deployment, or discovery changes", () => {
    const discovered = catalogModel("relay_a/gpt-a");
    const dirty = {
      ...initialProviderWizardState(),
      step: "connection" as const,
      templateId: "relay_openai",
      serviceClass: "relay",
      providerId: "relay_a",
      label: "Relay A",
      baseUrl: "https://relay.example/v1",
      credentialRef: "env:RELAY_KEY",
      driver: "openai",
      defaultProtocol: "responses",
      allowedProtocols: ["responses"],
      runtimeFramework: "vllm",
      artifactPath: "models/a",
      discoveredModels: [discovered],
      pinnedModelRefs: [discovered.modelRef],
    };

    const providerChanged = providerWizardReducer(dirty, {
      type: "set_connection",
      providerId: "relay_b",
      label: "Relay B",
      baseUrl: "https://relay-b.example/v1",
      credentialRef: "env:RELAY_B_KEY",
    });
    expect(providerChanged).toMatchObject({
      driver: "",
      defaultProtocol: "",
      allowedProtocols: [],
      runtimeFramework: "",
      artifactPath: "",
      discoveredModels: [],
      pinnedModelRefs: [],
    });

    const protocolChanged = providerWizardReducer(dirty, {
      type: "set_protocol",
      driver: "openai",
      defaultProtocol: "chat_completions",
      allowedProtocols: ["chat_completions"],
    });
    expect(protocolChanged.discoveredModels).toEqual([]);
    expect(protocolChanged.pinnedModelRefs).toEqual([]);

    const deploymentChanged = providerWizardReducer(dirty, {
      type: "set_deployment",
      runtimeFramework: "ollama",
      artifactPath: "models/b",
    });
    expect(deploymentChanged.discoveredModels).toEqual([]);
    expect(deploymentChanged.pinnedModelRefs).toEqual([]);

    const templateDirty = { ...dirty, step: "template" as const };
    const templateChanged = providerWizardReducer(templateDirty, {
      type: "choose_template",
      templateId: "official_openai",
      serviceClass: "official_api",
    });
    expect(templateChanged).toMatchObject({
      providerId: "",
      driver: "",
      discoveredModels: [],
      pinnedModelRefs: [],
    });
  });

  it.each(["relay", "official_api", "self_hosted"])(
    "requires a complete connection and allowed default protocol for %s",
    (serviceClass) => {
      let state = {
        ...initialProviderWizardState(),
        step: "connection" as const,
        templateId: `${serviceClass}_template`,
        serviceClass,
      };
      state = providerWizardReducer(state, {
        type: "set_connection",
        providerId: `${serviceClass}_provider`,
        label: "Provider",
        baseUrl: "https://provider.example/v1",
        credentialRef: "",
      });
      state = providerWizardReducer(state, {
        type: "set_protocol",
        driver: "openai",
        defaultProtocol: "responses",
        allowedProtocols: ["responses"],
      });
      expect(canAdvanceProviderWizard(state)).toBe(false);

      state = providerWizardReducer(state, {
        type: "set_connection",
        providerId: `${serviceClass}_provider`,
        label: "Provider",
        baseUrl: "https://provider.example/v1",
        credentialRef: "none",
      });
      state = providerWizardReducer(state, {
        type: "set_protocol",
        driver: "openai",
        defaultProtocol: "responses",
        allowedProtocols: ["chat_completions"],
      });
      expect(canAdvanceProviderWizard(state)).toBe(false);

      state = providerWizardReducer(state, {
        type: "set_protocol",
        driver: "openai",
        defaultProtocol: "responses",
        allowedProtocols: ["responses", "chat_completions"],
      });
      expect(canAdvanceProviderWizard(state)).toBe(true);
    },
  );
});
