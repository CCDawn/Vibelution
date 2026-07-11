import type {
  ConfigCatalogModel,
  ConfigModelCatalog,
  ConfigProviderOption,
  ConfigProviderStatus,
} from "../api/types";

export type ProviderRegistryRow = {
  providerId: string;
  label: string;
  serviceClass: string;
  vendor: string;
  driver: string;
  runtimeFramework: string;
  artifactPath: string;
  baseUrl: string;
  credentialState: string;
  defaultProtocol: string;
  status: ConfigProviderStatus | "configured";
  lastAttemptAt: string;
  lastSuccessAt: string;
  refreshDue: boolean;
  models: ConfigCatalogModel[];
};

export function deriveProviderRegistryRows(
  providers: ConfigProviderOption[],
  catalog: ConfigModelCatalog,
): ProviderRegistryRow[] {
  return providers
    .map((provider) => {
      const observed = catalog.providers[provider.provider_id];
      return {
        providerId: provider.provider_id,
        label: provider.label,
        serviceClass: provider.service_class,
        vendor: provider.vendor,
        driver: provider.driver,
        runtimeFramework: provider.runtime_framework ?? "",
        artifactPath: provider.artifact_path ?? "",
        baseUrl: provider.base_url ?? "",
        credentialState: provider.credential_state,
        defaultProtocol: provider.default_protocol,
        status: observed?.status ?? "configured",
        lastAttemptAt: observed?.lastAttemptAt ?? "",
        lastSuccessAt: observed?.lastSuccessAt ?? "",
        refreshDue: observed?.refreshDue ?? false,
        models: Object.values(observed?.models ?? {}).sort((left, right) => left.modelRef.localeCompare(right.modelRef)),
      };
    })
    .sort((left, right) => left.providerId.localeCompare(right.providerId));
}

export type ProviderWizardStep = "template" | "connection" | "discovery" | "pin";

export type ProviderWizardState = {
  step: ProviderWizardStep;
  templateId: string;
  serviceClass: string;
  providerId: string;
  label: string;
  baseUrl: string;
  credentialRef: string;
  driver: string;
  defaultProtocol: string;
  allowedProtocols: string[];
  runtimeFramework: string;
  artifactPath: string;
  discoveredModels: ConfigCatalogModel[];
  pinnedModelRefs: string[];
};

export type ProviderWizardAction =
  | { type: "choose_template"; templateId: string; serviceClass: string }
  | { type: "set_connection"; providerId: string; label: string; baseUrl: string; credentialRef: string }
  | { type: "set_protocol"; driver: string; defaultProtocol: string; allowedProtocols: string[] }
  | { type: "set_deployment"; runtimeFramework: string; artifactPath: string }
  | { type: "set_discovery"; models: ConfigCatalogModel[] }
  | { type: "toggle_pin"; modelRef: string }
  | { type: "next" }
  | { type: "back" }
  | { type: "reset" };

const STEPS: ProviderWizardStep[] = ["template", "connection", "discovery", "pin"];

export function initialProviderWizardState(): ProviderWizardState {
  return {
    step: "template",
    templateId: "",
    serviceClass: "",
    providerId: "",
    label: "",
    baseUrl: "",
    credentialRef: "",
    driver: "",
    defaultProtocol: "",
    allowedProtocols: [],
    runtimeFramework: "",
    artifactPath: "",
    discoveredModels: [],
    pinnedModelRefs: [],
  };
}

export function canAdvanceProviderWizard(state: ProviderWizardState): boolean {
  if (state.step === "template") {
    return Boolean(state.templateId && state.serviceClass);
  }
  if (state.step === "connection") {
    const connectionReady = Boolean(
      state.providerId
      && state.label
      && state.baseUrl
      && state.credentialRef
      && state.driver
      && state.defaultProtocol
      && state.allowedProtocols.includes(state.defaultProtocol)
    );
    return state.serviceClass === "local_runtime"
      ? connectionReady && Boolean(state.runtimeFramework && state.artifactPath)
      : connectionReady;
  }
  if (state.step === "discovery") {
    return state.discoveredModels.length > 0
      && state.discoveredModels.every((model) => isCanonicalModelForProvider(model, state.providerId));
  }
  const discoveredRefs = new Set(
    state.discoveredModels
      .filter((model) => isCanonicalModelForProvider(model, state.providerId))
      .map((model) => model.modelRef),
  );
  return state.pinnedModelRefs.length > 0
    && state.pinnedModelRefs.every(
      (modelRef) => isCanonicalModelRefForProvider(modelRef, state.providerId) && discoveredRefs.has(modelRef),
    );
}

function isCanonicalModelRefForProvider(modelRef: string, providerId: string): boolean {
  if (!/^[a-z][a-z0-9_-]{0,63}$/.test(providerId) || modelRef !== modelRef.trim()) {
    return false;
  }
  const separator = modelRef.indexOf("/");
  if (separator <= 0 || modelRef.indexOf("/", separator + 1) >= 0) {
    return false;
  }
  const refProviderId = modelRef.slice(0, separator);
  const modelKey = modelRef.slice(separator + 1);
  return refProviderId === providerId && modelKey.length > 0 && modelKey.length <= 96;
}

function isCanonicalModelForProvider(model: ConfigCatalogModel, providerId: string): boolean {
  const separator = model.modelRef.indexOf("/");
  return isCanonicalModelRefForProvider(model.modelRef, providerId)
    && model.modelKey === model.modelRef.slice(separator + 1);
}

export function providerWizardReducer(state: ProviderWizardState, action: ProviderWizardAction): ProviderWizardState {
  if (action.type === "reset") {
    return initialProviderWizardState();
  }
  if (action.type === "choose_template") {
    if (state.step !== "template") {
      return state;
    }
    return {
      ...initialProviderWizardState(),
      templateId: action.templateId,
      serviceClass: action.serviceClass,
    };
  }
  if (action.type === "set_connection") {
    if (state.step !== "connection") {
      return state;
    }
    const routeChanged = state.providerId !== action.providerId
      || state.baseUrl !== action.baseUrl
      || state.credentialRef !== action.credentialRef;
    return {
      ...state,
      providerId: action.providerId,
      label: action.label,
      baseUrl: action.baseUrl,
      credentialRef: action.credentialRef,
      ...(routeChanged
        ? {
            driver: "",
            defaultProtocol: "",
            allowedProtocols: [],
            runtimeFramework: "",
            artifactPath: "",
          }
        : {}),
      discoveredModels: [],
      pinnedModelRefs: [],
    };
  }
  if (action.type === "set_protocol") {
    if (state.step !== "connection") {
      return state;
    }
    return {
      ...state,
      driver: action.driver.trim(),
      defaultProtocol: action.defaultProtocol.trim(),
      allowedProtocols: Array.from(
        new Set(action.allowedProtocols.map((protocol) => protocol.trim()).filter(Boolean)),
      ).sort(),
      discoveredModels: [],
      pinnedModelRefs: [],
    };
  }
  if (action.type === "set_deployment") {
    if (state.step !== "connection") {
      return state;
    }
    return {
      ...state,
      runtimeFramework: action.runtimeFramework,
      artifactPath: action.artifactPath,
      discoveredModels: [],
      pinnedModelRefs: [],
    };
  }
  if (action.type === "set_discovery") {
    if (state.step !== "discovery") {
      return state;
    }
    const modelsByRef = new Map<string, ConfigCatalogModel>();
    for (const model of action.models) {
      if (isCanonicalModelForProvider(model, state.providerId)) {
        modelsByRef.set(model.modelRef, model);
      }
    }
    return {
      ...state,
      discoveredModels: Array.from(modelsByRef.values()).sort((left, right) => left.modelRef.localeCompare(right.modelRef)),
      pinnedModelRefs: [],
    };
  }
  if (action.type === "toggle_pin") {
    if (
      state.step !== "pin"
      || !isCanonicalModelRefForProvider(action.modelRef, state.providerId)
      || !state.discoveredModels.some(
        (model) => isCanonicalModelForProvider(model, state.providerId) && model.modelRef === action.modelRef,
      )
    ) {
      return state;
    }
    const selected = new Set(state.pinnedModelRefs);
    if (selected.has(action.modelRef)) {
      selected.delete(action.modelRef);
    } else {
      selected.add(action.modelRef);
    }
    return { ...state, pinnedModelRefs: Array.from(selected).sort() };
  }
  const index = STEPS.indexOf(state.step);
  if (action.type === "back") {
    return { ...state, step: STEPS[Math.max(0, index - 1)] };
  }
  if (!canAdvanceProviderWizard(state)) {
    return state;
  }
  return { ...state, step: STEPS[Math.min(STEPS.length - 1, index + 1)] };
}
