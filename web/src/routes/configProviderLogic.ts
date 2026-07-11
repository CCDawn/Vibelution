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
  runtimeFramework: string;
  artifactPath: string;
  discoveredModels: ConfigCatalogModel[];
  pinnedModelRefs: string[];
};

export type ProviderWizardAction =
  | { type: "choose_template"; templateId: string; serviceClass: string }
  | { type: "set_connection"; providerId: string; label: string; baseUrl: string; credentialRef: string }
  | { type: "set_protocol"; driver: string; defaultProtocol: string }
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
    if (state.serviceClass === "local_runtime") {
      return Boolean(
        state.providerId
        && state.label
        && state.driver
        && state.defaultProtocol
        && state.runtimeFramework
        && state.artifactPath
      );
    }
    return Boolean(state.providerId && state.label && state.baseUrl && state.credentialRef);
  }
  if (state.step === "discovery") {
    return state.discoveredModels.length > 0;
  }
  return state.pinnedModelRefs.length > 0;
}

export function providerWizardReducer(state: ProviderWizardState, action: ProviderWizardAction): ProviderWizardState {
  if (action.type === "reset") {
    return initialProviderWizardState();
  }
  if (action.type === "choose_template") {
    return { ...state, templateId: action.templateId, serviceClass: action.serviceClass };
  }
  if (action.type === "set_connection") {
    return {
      ...state,
      providerId: action.providerId,
      label: action.label,
      baseUrl: action.baseUrl,
      credentialRef: action.credentialRef,
    };
  }
  if (action.type === "set_protocol") {
    return { ...state, driver: action.driver, defaultProtocol: action.defaultProtocol };
  }
  if (action.type === "set_deployment") {
    return { ...state, runtimeFramework: action.runtimeFramework, artifactPath: action.artifactPath };
  }
  if (action.type === "set_discovery") {
    return { ...state, discoveredModels: action.models };
  }
  if (action.type === "toggle_pin") {
    if (!state.discoveredModels.some((model) => model.modelRef === action.modelRef)) {
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
