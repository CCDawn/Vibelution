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
  pinnedCount: number;
  status: ConfigProviderStatus | "configured";
  lastAttemptAt: string;
  lastSuccessAt: string;
  refreshDue: boolean;
  models: ConfigCatalogModel[];
};

export type ProviderModelFilter = "all" | "pinned" | "discovered" | "unavailable";

export type ProviderModelActionState =
  | { kind: "unpin"; label: "取消固定"; disabled: boolean; reason: string }
  | { kind: "in_use"; label: "使用中"; referenceCount: number }
  | { kind: "not_pinned"; label: "未固定" }
  | { kind: "unavailable"; label: "不可用" };

const PROVIDER_MODEL_AVAILABILITY_GROUPS: Record<Exclude<ProviderModelFilter, "all">, ReadonlySet<string>> = {
  pinned: new Set(["pinned", "missing_remote"]),
  discovered: new Set(["observed", "capability_unknown", "protocol_unknown", "unknown"]),
  unavailable: new Set(["disabled"]),
};

export function filterProviderModels(
  models: ConfigCatalogModel[],
  query: string,
  filter: ProviderModelFilter,
): ConfigCatalogModel[] {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  return models.filter((model) => {
    if (filter !== "all" && !PROVIDER_MODEL_AVAILABILITY_GROUPS[filter].has(model.availability)) {
      return false;
    }
    if (!normalizedQuery) {
      return true;
    }
    return [model.modelRef, model.upstreamId, model.label]
      .some((value) => value.toLocaleLowerCase().includes(normalizedQuery));
  });
}

export function summarizeProviderModels(models: ConfigCatalogModel[]): {
  total: number;
  pinned: number;
  discovered: number;
  unavailable: number;
} {
  return {
    total: models.length,
    pinned: models.filter((model) => PROVIDER_MODEL_AVAILABILITY_GROUPS.pinned.has(model.availability)).length,
    discovered: models.filter((model) => PROVIDER_MODEL_AVAILABILITY_GROUPS.discovered.has(model.availability)).length,
    unavailable: models.filter((model) => PROVIDER_MODEL_AVAILABILITY_GROUPS.unavailable.has(model.availability)).length,
  };
}

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
        pinnedCount: provider.pinned_count,
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
export type ProviderAuthKind = "api_key" | "oauth" | "none";

export type ProviderWizardState = {
  step: ProviderWizardStep;
  templateId: string;
  serviceClass: string;
  providerId: string;
  label: string;
  baseUrl: string;
  authKind: ProviderAuthKind;
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
  | { type: "set_connection"; providerId: string; label: string; baseUrl: string; authKind?: ProviderAuthKind; credentialRef: string }
  | { type: "set_protocol"; driver: string; defaultProtocol: string; allowedProtocols: string[] }
  | { type: "set_deployment"; runtimeFramework: string; artifactPath: string }
  | { type: "set_discovery"; models: ConfigCatalogModel[] }
  | { type: "toggle_pin"; modelRef: string }
  | { type: "pin_succeeded"; modelRef: string }
  | { type: "next" }
  | { type: "back" }
  | { type: "reset" };

export type ProviderQuickSetupPhase = "input" | "checking" | "review" | "saving" | "success" | "error";

export type ProviderQuickSetupErrorKind =
  | "auth"
  | "endpoint"
  | "discovery"
  | "no_recommendation"
  | "partial_save"
  | "save";

export type ProviderQuickSetupState = {
  phase: ProviderQuickSetupPhase;
  provider: ProviderWizardState;
  discoveredModels: ConfigCatalogModel[];
  selectedModelRef: string;
  recommendationReason: string;
  errorKind: ProviderQuickSetupErrorKind | "";
  errorMessage: string;
};

export type ProviderQuickSetupAction =
  | { type: "reset" }
  | { type: "set_provider"; provider: ProviderWizardState }
  | { type: "start_check" }
  | { type: "check_succeeded"; models: ConfigCatalogModel[]; selectedModelRef: string; recommendationReason: string }
  | { type: "check_failed"; errorKind: ProviderQuickSetupErrorKind; errorMessage: string }
  | { type: "select_model"; modelRef: string }
  | { type: "start_save" }
  | { type: "save_failed"; errorKind: "partial_save" | "save"; errorMessage: string }
  | { type: "save_succeeded" };

export type ProviderModelRecommendationReason =
  | "template_default"
  | "verified_capabilities"
  | "stable_fallback"
  | "no_compatible_model";

const STEPS: ProviderWizardStep[] = ["template", "connection", "discovery", "pin"];

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function buildProviderWizardDraft(
  state: ProviderWizardState,
  templateProvider?: unknown,
): Record<string, unknown> {
  const source = { ...asRecord(templateProvider) };
  const templateDeployment = asRecord(source.deployment);
  delete source.runtime_framework;
  delete source.artifact_path;
  if (state.serviceClass !== "local_runtime") {
    delete source.deployment;
  }
  return {
    ...source,
    label: state.label,
    service_class: state.serviceClass,
    driver: state.driver,
    base_url: state.baseUrl,
    auth_kind: state.authKind,
    credential_ref: state.credentialRef,
    requires_credential: state.authKind !== "none",
    protocols: { default: state.defaultProtocol, allowed: state.allowedProtocols },
    discovery: {
      ...asRecord(source.discovery),
      mode: asString(asRecord(source.discovery).mode) || "auto",
    },
    ...(state.serviceClass === "local_runtime"
      ? {
          deployment: {
            ...templateDeployment,
            runtime_framework: state.runtimeFramework || asString(templateDeployment.runtime_framework),
            artifact_path: state.artifactPath || asString(templateDeployment.artifact_path),
          },
        }
      : {}),
    models: {},
  };
}

export function initialProviderWizardState(): ProviderWizardState {
  return {
    step: "template",
    templateId: "",
    serviceClass: "",
    providerId: "",
    label: "",
    baseUrl: "",
    authKind: "api_key",
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

export function initialProviderQuickSetupState(): ProviderQuickSetupState {
  return {
    phase: "input",
    provider: initialProviderWizardState(),
    discoveredModels: [],
    selectedModelRef: "",
    recommendationReason: "",
    errorKind: "",
    errorMessage: "",
  };
}

export function providerQuickSetupReducer(
  state: ProviderQuickSetupState,
  action: ProviderQuickSetupAction,
): ProviderQuickSetupState {
  if (action.type === "reset") {
    return initialProviderQuickSetupState();
  }
  if (action.type === "set_provider") {
    return { ...initialProviderQuickSetupState(), provider: action.provider };
  }
  if (action.type === "start_check") {
    return { ...state, phase: "checking", errorKind: "", errorMessage: "" };
  }
  if (action.type === "check_succeeded") {
    return {
      ...state,
      phase: "review",
      discoveredModels: [...action.models],
      selectedModelRef: action.selectedModelRef,
      recommendationReason: action.recommendationReason,
      errorKind: action.selectedModelRef ? "" : "no_recommendation",
      errorMessage: "",
    };
  }
  if (action.type === "check_failed") {
    return { ...state, phase: "error", errorKind: action.errorKind, errorMessage: action.errorMessage };
  }
  if (action.type === "select_model") {
    return { ...state, selectedModelRef: action.modelRef, errorKind: "", errorMessage: "" };
  }
  if (action.type === "start_save") {
    return { ...state, phase: "saving", errorKind: "", errorMessage: "" };
  }
  if (action.type === "save_failed") {
    return { ...state, phase: "error", errorKind: action.errorKind, errorMessage: action.errorMessage };
  }
  return { ...state, phase: "success", errorKind: "", errorMessage: "" };
}

function hasVerifiedCapabilities(model: ConfigCatalogModel): boolean {
  return Object.values(model.capabilities ?? {}).some(
    (capability) => capability.value === "supported"
      && ["runtime_probe", "provider_endpoint", "operator_override"].includes(capability.source),
  );
}

export function recommendProviderModel(
  models: ConfigCatalogModel[],
  options: { templateDefaultModelRef?: string; allowedProtocols: string[] },
): { modelRef: string; reason: ProviderModelRecommendationReason } {
  const compatible = models
    .filter((model) => !["disabled", "protocol_mismatch", "unavailable"].includes(model.status.toLowerCase()))
    .slice()
    .sort((left, right) => left.modelRef.localeCompare(right.modelRef));
  if (!compatible.length || !options.allowedProtocols.length) {
    return { modelRef: "", reason: "no_compatible_model" };
  }
  const templateDefault = compatible.find((model) => model.modelRef === options.templateDefaultModelRef);
  if (templateDefault) {
    return { modelRef: templateDefault.modelRef, reason: "template_default" };
  }
  const verified = compatible.find(hasVerifiedCapabilities);
  if (verified) {
    return { modelRef: verified.modelRef, reason: "verified_capabilities" };
  }
  return { modelRef: compatible[0].modelRef, reason: "stable_fallback" };
}

export function canAdvanceProviderWizard(state: ProviderWizardState): boolean {
  if (state.step === "template") {
    return Boolean(state.templateId && state.serviceClass);
  }
  if (state.step === "connection") {
    const credentialReady = state.authKind === "none"
      ? state.credentialRef === "none"
      : Boolean(state.credentialRef && state.credentialRef !== "none");
    const connectionReady = Boolean(
      state.providerId
      && state.label
      && state.baseUrl
      && credentialReady
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

export function canUnpinProviderModel(row: ProviderRegistryRow, model: ConfigCatalogModel): boolean {
  return row.pinnedCount > 0 && (model.availability === "pinned" || model.availability === "missing_remote");
}

export function deriveProviderModelActionState(
  row: ProviderRegistryRow,
  model: ConfigCatalogModel,
  liveReferenceCount: number,
  disabled: boolean,
): ProviderModelActionState {
  if (model.availability === "disabled") {
    return { kind: "unavailable", label: "不可用" };
  }
  if (!canUnpinProviderModel(row, model)) {
    return { kind: "not_pinned", label: "未固定" };
  }
  if (liveReferenceCount > 0) {
    return { kind: "in_use", label: "使用中", referenceCount: liveReferenceCount };
  }
  return {
    kind: "unpin",
    label: "取消固定",
    disabled,
    reason: disabled ? "当前配置操作不可用" : "",
  };
}

export function canTestProviderModel(model: ConfigCatalogModel): boolean {
  return model.availability === "pinned" || model.availability === "missing_remote";
}

export function filterAlreadyPinnedModels(
  models: ConfigCatalogModel[],
  pinnedModelRefs: ReadonlySet<string>,
): ConfigCatalogModel[] {
  return models.filter((model) => !pinnedModelRefs.has(model.modelRef));
}

export function isProviderWizardConnectionLocked(disabled: boolean, providerCreated: boolean): boolean {
  return disabled || providerCreated;
}

export function dispatchProviderWizardConnectionAction(
  locked: boolean,
  action: Extract<ProviderWizardAction, { type: "set_connection" | "set_protocol" | "set_deployment" }>,
  onChange: (action: ProviderWizardAction) => void,
): boolean {
  if (locked) return false;
  onChange(action);
  return true;
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
    const nextAuthKind = action.authKind ?? state.authKind;
    const routeChanged = state.baseUrl !== action.baseUrl
      || state.credentialRef !== action.credentialRef
      || state.authKind !== nextAuthKind;
    return {
      ...state,
      providerId: action.providerId,
      label: action.label,
      baseUrl: action.baseUrl,
      authKind: nextAuthKind,
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
  if (action.type === "pin_succeeded") {
    if (
      state.step !== "pin"
      || !state.pinnedModelRefs.includes(action.modelRef)
      || !state.discoveredModels.some((model) => model.modelRef === action.modelRef)
    ) {
      return state;
    }
    return {
      ...state,
      discoveredModels: state.discoveredModels.filter((model) => model.modelRef !== action.modelRef),
      pinnedModelRefs: state.pinnedModelRefs.filter((modelRef) => modelRef !== action.modelRef),
    };
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
