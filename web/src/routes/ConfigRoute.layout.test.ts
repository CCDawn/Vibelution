import { describe, expect, it } from "vitest";

import routeSource from "./ConfigRoute.tsx?raw";
import draftPanelSource from "./ConfigDraftPanel.tsx?raw";
import draftPanelStylesSource from "./ConfigDraftPanel.styles.ts?raw";
import draftPanelStyles from "./ConfigDraftPanel.styles";
import healthDiagnosticsPanelSource from "./ConfigHealthDiagnosticsPanel.tsx?raw";
import healthDiagnosticsPanelStylesSource from "./ConfigHealthDiagnosticsPanel.styles.ts?raw";
import healthDiagnosticsPanelStyles from "./ConfigHealthDiagnosticsPanel.styles";
import migrationPanelSource from "./ConfigModelMigrationPanel.tsx?raw";
import migrationPanelStyles from "./ConfigModelMigrationPanel.styles";
import overviewPanelSource from "./ConfigOverviewPanel.tsx?raw";
import overviewPanelStylesSource from "./ConfigOverviewPanel.styles.ts?raw";
import overviewPanelStyles from "./ConfigOverviewPanel.styles";
import placeholderPanelSource from "./ConfigWorkspacePlaceholderPanel.tsx?raw";
import placeholderPanelStylesSource from "./ConfigWorkspacePlaceholderPanel.styles.ts?raw";
import placeholderPanelStyles from "./ConfigWorkspacePlaceholderPanel.styles";
import runtimePanelSource from "./ConfigRuntimePanel.tsx?raw";
import runtimePanelStylesSource from "./ConfigRuntimePanel.styles.ts?raw";
import runtimePanelStyles from "./ConfigRuntimePanel.styles";
import providerPanelSource from "./ConfigProviderRegistryPanel.tsx?raw";
import providerPanelStylesSource from "./ConfigProviderRegistryPanel.styles.ts?raw";
import providerPanelStyles from "./ConfigProviderRegistryPanel.styles";
import providerLogicSource from "./configProviderLogic.ts?raw";
import quickSetupSource from "./ConfigQuickSetupPanel.tsx?raw";
import quickSetupStylesSource from "./ConfigQuickSetupPanel.styles.ts?raw";
import quickSetupStyles from "./ConfigQuickSetupPanel.styles";
import wizardSource from "./ConfigProviderWizard.tsx?raw";
import styles from "./ConfigRoute.styles";
import stylesSource from "./ConfigRoute.styles.ts?raw";

const extractedPanelStylesSource = [
  draftPanelStylesSource,
  healthDiagnosticsPanelStylesSource,
  overviewPanelStylesSource,
  placeholderPanelStylesSource,
  providerPanelStylesSource,
  runtimePanelStylesSource,
].join("\n");

const configSources = [
  routeSource,
  overviewPanelSource,
  runtimePanelSource,
  draftPanelSource,
  providerPanelSource,
  wizardSource,
  migrationPanelSource,
  healthDiagnosticsPanelSource,
  placeholderPanelSource,
].join("\n");

describe("ConfigRoute layout contract", () => {
  it("renders provider-first configuration without endpoint fingerprint identity", () => {
    expect(routeSource).toContain("ConfigProviderRegistryPanel");
    expect(routeSource).toContain("ConfigProviderWizard");
    expect(routeSource).toContain("ConfigModelMigrationPanel");
    expect(providerPanelSource).toContain("provider.providerId");
    expect(providerPanelSource).toContain("model.modelRef");
    expect(providerPanelSource).toContain("connection");
    expect(providerPanelSource).toContain("models");
    expect(providerPanelSource).toContain("protocols");
    expect(providerPanelSource).toContain("diagnostics");
    expect(providerPanelSource).not.toContain("api_key");
  });

  it("keeps v1 migration preview explicit and apply disabled on unresolved conflicts", () => {
    expect(migrationPanelSource).toContain('preview.status !== "READY"');
    expect(migrationPanelSource).toContain("preview?.conflicts");
    expect(migrationPanelSource).toContain("onApply(preview.previewId, preview.baseHash)");
    expect(migrationPanelSource).toContain('conflict.code === "artifact_path_suspected"');
    expect(migrationPanelSource).not.toContain('conflict.fields?.includes("artifact_path")');
  });

  it("shows all safe model IDs for provider artifact conflicts without rendering paths", () => {
    expect(migrationPanelSource).toContain('conflict.modelIds?.join(", ")');
    expect(migrationPanelSource).not.toContain("conflict.artifactPath");
  });

  it("submits artifact decisions only through a new preview request", () => {
    expect(migrationPanelSource).toContain("onPreview(resolutions)");
    expect(migrationPanelSource).toContain("onPreview([])");
    expect(routeSource).toContain("artifactResolutions,");
    expect(routeSource).toContain("ConfigMigrationPreviewRequest");
    expect(routeSource).toContain("setMigrationPreview(response)");
    expect(routeSource).not.toContain("handleApplyMigration(resolutions");
  });

  it("keeps artifact resolution cards and actions wrapping without page-level overflow", () => {
    expect(migrationPanelStyles.resolutionGrid).toContain("[grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr))]");
    expect(migrationPanelStyles.resolutionCard).toContain("[overflow-wrap:anywhere]");
    expect(migrationPanelStyles.resolutionFields).toContain("max-[390px]:[grid-template-columns:minmax(0,1fr)]");
    expect(migrationPanelStyles.actions).toContain("flex-wrap");
    expect(migrationPanelStyles.tableScroll).toContain("[overflow-x:auto]");
    expect(migrationPanelStyles.migration).toContain("min-w-0");
  });

  it("implements the four provider wizard steps", () => {
    expect(wizardSource).toContain('"template"');
    expect(wizardSource).toContain('"connection"');
    expect(wizardSource).toContain('"discovery"');
    expect(wizardSource).toContain('"pin"');
    expect(wizardSource).toContain("canAdvanceProviderWizard");
  });

  it("makes one-page quick setup the default Provider workspace without mounting management beside it", () => {
    expect(routeSource).toContain("ConfigQuickSetupPanel");
    expect(routeSource).toContain('type ProviderWorkspaceMode = "quick" | "manage" | "advanced"');
    expect(routeSource).toContain('useState<ProviderWorkspaceMode>("quick")');
    expect(routeSource).toContain("handlePrepareProviderQuickSetup");
    expect(routeSource).toContain("handleConfirmProviderQuickSetup");
    expect(routeSource).toContain("recommendProviderModel");
    expect(routeSource).toContain('providerWorkspaceMode === "quick"');
    expect(routeSource).toContain('providerWorkspaceMode === "manage"');
    expect(routeSource).toContain('providerWorkspaceMode === "advanced"');
    expect(quickSetupSource).toContain("检测连接");
    expect(quickSetupSource).toContain("保存并完成");
    expect(quickSetupStyles.workspace).toContain("max-w-[88rem]");
    expect(quickSetupStyles.inputGrid).toContain("grid-template-columns");
    expect(quickSetupSource).toContain('state.phase !== "input"');
    expect(quickSetupStylesSource).not.toContain("min-h-[28rem]");
    expect(quickSetupStylesSource).not.toContain("minmax(22rem,0.9fr)_minmax(28rem,1.1fr)");
    expect(routeSource).toContain('workspace.schemaVersion === 2 && isSectionVisible("models")');
    expect(routeSource).toContain('providerWorkspaceMode === "advanced" ? (\n                  <>');
    expect(routeSource).toContain('activePage?.id !== "model-connection"');
  });

  it("keeps formal config apply outside Provider detection orchestration", () => {
    const detectionBody = routeSource.slice(
      routeSource.indexOf("async function handlePrepareProviderQuickSetup"),
      routeSource.indexOf("async function handleConfirmProviderQuickSetup"),
    );
    const confirmationBody = routeSource.slice(
      routeSource.indexOf("async function handleConfirmProviderQuickSetup"),
      routeSource.indexOf("async function handleUnpinProviderModel"),
    );

    expect(detectionBody).toContain("handleCreateProvider");
    expect(detectionBody).toContain("handleDiscoverProvider");
    expect(detectionBody).not.toContain("handleApply(");
    expect(confirmationBody).toContain("handlePinProviderModels");
    expect(confirmationBody).toContain("handleApply(");
  });

  it("applies quick setup from the latest synchronized Provider workspace instead of stale React state", () => {
    expect(routeSource).toContain("type ConfigApplyDraftOverride");
    expect(routeSource).toContain("draftOverride?: ConfigApplyDraftOverride");
    expect(routeSource).toContain('handleApply("正在应用快速配置…", providerDraftRequestRef.current ?? undefined)');
    expect(routeSource).toContain("publicConfig: draftOverride.publicConfig");
    expect(routeSource).toContain("draftMeta: draftOverride.draftMeta");
    expect(routeSource).toContain("baseHash: draftOverride.baseHash");
  });

  it("refreshes only ttl-expired providers when the model surface opens", () => {
    expect(routeSource).toContain("row.refreshDue");
    expect(routeSource).toContain("autoRefreshAttemptedProviderIds");
    expect(routeSource).not.toContain("load_public_config");
  });

  it("synchronizes every Provider mutation from the full backend ConfigWorkspace response", () => {
    expect(routeSource).toContain('requestJson<ConfigWorkspace>(\n        "/api/config/draft/providers"');
    expect(routeSource).toContain("/discover`");
    expect(routeSource).toContain("/models`");
    expect(routeSource).toContain("/models/${encodeURIComponent(modelKey)}`");
    expect(routeSource).toContain('buildProviderDraftRequest({ providerId, provider }),\n        "DELETE"');
    expect(routeSource).toContain("routePreviewToken: routePreview.routePreviewToken");
    expect((routeSource.match(/syncWorkspace\(response, "success", \{ resetBase: false \}\);/g) ?? []).length).toBeGreaterThanOrEqual(6);
    expect(routeSource).not.toContain("syncProviderProjection");
  });

  it("chains create then discover from the latest synchronized Provider draft", () => {
    expect(routeSource).toContain("providerDraftRequestRef");
    expect(routeSource).toContain("providerDraftRequestRef.current = {");
    expect(routeSource).toContain("publicConfig: workspace.publicConfig");
    expect(routeSource).toContain("const latestDraft = providerDraftRequestRef.current");
    expect(routeSource).toContain("publicConfig: latestDraft.publicConfig");
  });

  it("previews and applies the same proposed Provider route with backend token authority", () => {
    expect(routeSource).toContain("routeEditProviderId");
    expect(routeSource).toContain("routeEditProvider");
    expect(routeSource).toContain("handlePreviewProviderRoute(routeEditProviderId, routeEditProvider)");
    expect(routeSource).toContain("proposedProvider: provider");
    expect(routeSource).toContain("provider: routePreview.proposedProvider");
    expect(routeSource).toContain("routePreviewToken: routePreview.routePreviewToken");
    expect(routeSource).toContain("routePreview.impactedRefs.map");
  });

  it("edits an existing Provider API Key through the draft credential boundary", () => {
    expect(providerPanelSource).toContain("onEditCredential");
    expect(providerPanelSource).toContain("设置 API Key");
    expect(providerPanelSource).toContain('provider.credentialState === "not_required"');
    expect(routeSource).toContain('type="password"');
    expect(routeSource).toContain('`/api/config/draft/providers/${encodeURIComponent(providerId)}`');
    expect(routeSource).toContain("buildProviderDraftRequest({ providerId, provider, credentialValue: providerCredentialValue })");
    expect(routeSource).toContain('"PUT"');
    expect(routeSource).toContain("最终保存会写入用户环境变量，不会写入 config.toml。");
    expect(routeSource).toContain("if (structuredActionsDisabled || !providerCredentialValue.trim()) return;");
    expect(routeSource).toContain('credentialProvider.credentialState === "not_required"');
    expect(routeSource).toContain("structuredActionsDisabled || Boolean(busyAction) || !providerCredentialValue.trim()");
    expect(routeSource).toContain("providerCredentialEditId === selectedProviderId");
    expect(routeSource).toContain('onSelectProvider={(providerId) => {');
    expect(routeSource).toContain('setProviderCredentialEditId("")');
    expect(routeSource).toContain('setProviderCredentialValue("")');
    expect(routeSource).toContain("setSelectedProviderId(providerId)");
    expect(providerPanelSource).not.toContain("credential_ref");
    expect(routeSource).not.toContain("credential_ref");
  });

  it("owns typed Provider action feedback and resets local editors when switching Provider", () => {
    expect(routeSource).toContain("providerActionFeedback");
    expect(routeSource).toContain('phase: "busy"');
    expect(routeSource).toContain('phase: "success"');
    expect(routeSource).toContain('phase: "error"');
    expect(providerPanelSource).toContain("发现中…");
    expect(routeSource).toContain("保存中…");
    expect(routeSource).toContain("生成预览中…");
    expect(routeSource).toContain("更新中…");
    expect(routeSource).toContain('setRouteEditProviderId("")');
    expect(routeSource).toContain("setRoutePreview(null)");
    expect(providerPanelSource).toContain('aria-live="polite"');
    expect(providerPanelSource).toContain("activeCredentialProviderId");
    expect(providerPanelSource).toContain("activeRouteProviderId");
  });

  it("uses backend pinned ownership and live references for destructive controls", () => {
    expect(providerPanelSource).toContain("provider.pinnedCount");
    expect(providerPanelSource).toContain("deriveProviderModelActionState(");
    expect(providerPanelSource).toContain("liveReferenceCountByModelRef");
    expect(providerPanelSource).not.toContain("provider.models.length > 0");
    expect(providerPanelSource).not.toContain('availability !== "pinned"');
  });

  it("recovers multi-pin partial success without resubmitting completed models", () => {
    expect(routeSource).toContain("filterAlreadyPinnedModels");
    expect(routeSource).toContain('dispatchProviderWizard({ type: "pin_succeeded", modelRef: model.modelRef })');
    expect(routeSource).toContain('model.availability === "pinned" || model.availability === "missing_remote"');
  });

  it("locks all saved wizard connection fields after creation", () => {
    expect(wizardSource).toContain("isProviderWizardConnectionLocked");
    expect(wizardSource).toContain("dispatchProviderWizardConnectionAction");
    expect(wizardSource).toContain("Provider 已创建");
    expect(wizardSource).toContain("disabled={connectionLocked}");
    expect(wizardSource).toContain("isDisabled={connectionLocked}");
  });

  it("uses the backend auth kind contract in wizard state and create payload", () => {
    expect(wizardSource).toContain('value={state.authKind}');
    expect(wizardSource).toContain('{ value: "api_key", label: "API key" }');
    expect(wizardSource).toContain('{ value: "oauth", label: "OAuth" }');
    expect(wizardSource).toContain('{ value: "none", label: "None" }');
    expect(wizardSource).not.toContain('value: "bearer"');
    expect(providerLogicSource).toContain("auth_kind: state.authKind");
    expect(providerLogicSource).toContain('requires_credential: state.authKind !== "none"');
  });

  it("reuses one canonical Provider draft builder for suggestion and creation", () => {
    expect(wizardSource).toContain("buildProviderWizardDraft(state, selectedTemplate?.provider)");
    expect(routeSource).toContain("buildProviderWizardDraft(state, template?.provider)");
    expect(wizardSource).toContain("const templateDeployment = asRecord(templateProvider.deployment)");
    expect(wizardSource).not.toContain("asString(templateProvider.runtime_framework)");
    expect(wizardSource).not.toContain("asString(templateProvider.artifact_path)");
    expect(wizardSource).not.toContain("function providerDraft(");
    expect(routeSource).not.toContain("runtime_framework: state.runtimeFramework");
    expect(routeSource).not.toContain("artifact_path: state.artifactPath");
  });

  it("shows capability provenance without native title and avoids fake row-level migration counts", () => {
    expect(providerPanelSource).not.toContain('title={`${observation.source}');
    expect(providerPanelSource).toContain("observation.source");
    expect(providerPanelSource).toContain("observation.confidence");
    expect(providerPanelSource).toContain("observation.checked_at");
    expect(migrationPanelSource).not.toContain('header: "Live references"');
  });

  it("keeps the provider workbench on VUI controls with stable visual-state selectors", () => {
    const providerSources = [providerPanelSource, wizardSource, migrationPanelSource].join("\n");
    const heroUiPackageToken = ["@hero", "ui/react"].join("");
    expect(providerSources).toContain('from "../components/vui"');
    expect(providerSources).not.toContain(heroUiPackageToken);
    expect(providerSources).not.toMatch(/<(button|select|textarea)\b/);
    expect(providerPanelSource).toContain("data-provider-status");
    expect(providerPanelSource).toContain("data-model-availability");
    expect(wizardSource).toContain("data-wizard-step");
    expect(migrationPanelSource).toContain("data-migration-status");
  });

  it("keeps Provider management desktop-first with bounded internal table overflow", () => {
    expect(providerPanelStyles.registryWorkspace).not.toContain("max-[960px]");
    expect(providerPanelStyles.tableScroll).toContain("overflow-auto");
    expect(providerPanelStylesSource).not.toContain("width:100vw");
  });

  it("keeps quick setup in a bounded progressive desktop workspace", () => {
    expect(quickSetupSource).toContain('<div className={styles.workspace}>');
    expect(quickSetupStyles.root).not.toContain("grid-template-columns");
    expect(quickSetupStyles.workspace).toContain("max-w-[88rem]");
    expect(quickSetupStyles.inputGrid).toContain("[grid-template-columns:minmax(15rem,1fr)_minmax(18rem,1.2fr)_max-content]");
    expect(quickSetupStyles.field).toContain("[&_[data-vui=select-trigger]]:!h-10");
    expect(quickSetupStyles.field).toContain("[&_[data-vui=select-trigger]]:!min-h-10");
    expect(quickSetupStyles.primaryAction).toContain("min-h-10");
    expect(styles.providerModeButton).toContain("min-h-10");
    expect(routeSource).toContain('aria-pressed={providerWorkspaceMode === "quick"}');
    expect(routeSource).toContain('aria-pressed={providerWorkspaceMode === "manage"}');
    expect(routeSource).toContain('aria-pressed={providerWorkspaceMode === "advanced"}');
    expect(quickSetupStyles.resultRegion).not.toContain("min-h-");
    expect(quickSetupStylesSource).not.toContain("position:fixed");
    expect(quickSetupStylesSource).not.toContain("bottom-0");
  });

  it("keeps existing Provider management in a bounded desktop list-detail grid", () => {
    expect(providerPanelStyles.registryWorkspace).toContain("[--vui-workspace-sidebar:clamp(22rem,28%,28rem)]");
    expect(providerPanelStyles.registryWorkspace).not.toContain("max-[960px]");
    expect(providerPanelStyles.providerList).toContain("h-full");
    expect(providerPanelStyles.providerList).toContain("overflow-y-auto");
    expect(providerPanelStyles.detailSurface).toContain("overflow-y-auto");
    expect(styles.providerModelsLayout).toContain("[grid-template-rows:auto_minmax(0,1fr)]");
  });

  it("passes the workspace schema version into legacy model account compatibility", () => {
    expect(routeSource).toMatch(
      /deriveModelCenterSummary\(\{\s*modelOptions,\s*schemaVersion: workspace\?\.schemaVersion,\s*\}\)/,
    );
    expect(routeSource).toContain("[modelOptions, workspace?.schemaVersion]");
  });

  it("uses a full workspace placeholder for initial loading and load failure states", () => {
    expect(routeSource).toContain("<ConfigWorkspacePlaceholderPanel title={copy.loading} />");
    expect(placeholderPanelSource).toContain("export function ConfigWorkspacePlaceholderPanel");
    expect(placeholderPanelSource).toContain('from "./ConfigWorkspacePlaceholderPanel.styles"');
    expect(placeholderPanelSource).not.toContain("ConfigRoute.styles");
    expect(routeSource).toContain('tone="error"');
    expect(placeholderPanelSource).toContain("styles.loadingShell");
    expect(placeholderPanelSource).toContain("styles.loadingBoard");
    expect(placeholderPanelStyles.loadingShell).toBeTypeOf("string");
    expect(placeholderPanelStyles.loadingBoard).toBeTypeOf("string");
    expect(routeSource).not.toContain("<section className={styles.loadingSurface}>");
  });

  it("uses comfortable desktop controls and matching six-group placeholders", () => {
    expect(styles.page).toContain("[--control-height:40px]");
    expect(styles.page).toContain("[--vui-control-height-sm:40px]");
    expect(styles.field).toContain("[grid-template-columns:minmax(12rem,0.34fr)_minmax(0,1fr)]");
    expect(styles.actionButton).toContain("[min-height:40px]");
    expect(styles.primaryButton).toContain("[min-height:40px]");
    expect(placeholderPanelSource).toContain("总览与保存");
    expect(placeholderPanelSource).toContain("工具与诊断");
    expect(placeholderPanelStyles.loadingNavList).toContain("[min-height:44px]");
    expect(placeholderPanelStyles.loadingShell).toContain("[height:100%]");
  });

  it("uses fixed two-level settings navigation with one active page", () => {
    expect(routeSource).toContain("const [activeGroupId, setActiveGroupId]");
    expect(routeSource).toContain("const [activePageId, setActivePageId]");
    expect(routeSource).toContain("<ConfigSettingsSidebar");
    expect(routeSource).toContain("<ConfigSettingsPageTabs");
    expect(routeSource).toContain("activePage?.memberSectionIds.includes(sectionId)");
    expect(routeSource).not.toContain("SIDEBAR_WIDTH_STORAGE_KEY");
    expect(routeSource).not.toContain("beginSidebarResize");
    expect(routeSource).not.toContain("sidebarIndexCollapsed");
    expect(routeSource).not.toContain("styles.sidebarMetaStrip");
    expect(styles.page).toContain("[grid-template-rows:minmax(0,1fr)]");
    expect(styles.content).toContain("[grid-template-rows:auto_auto_minmax(0,1fr)]");
    expect(styles.pageViewport).toContain("overflow-y-auto");
  });

  it("extracts core Config sections into route-local display panels", () => {
    expect(routeSource).toContain("<ConfigOverviewPanel");
    expect(routeSource).toContain("<ConfigRuntimePanel");
    expect(routeSource).toContain("<ConfigDraftPanel");
    expect(routeSource).toContain("<ConfigProviderRegistryPanel");
    expect(routeSource).toContain("<ConfigProviderWizard");
    expect(routeSource).toContain("<ConfigModelMigrationPanel");
    expect(routeSource).not.toContain('from "./ConfigModelLibraryPanel"');
    expect(routeSource).not.toContain('<section id="config-overview"');
    expect(routeSource).not.toContain('<section id="config-shell"');
    expect(routeSource).not.toContain('<section id="config-draft"');
    expect(routeSource).not.toContain('<section id="config-models"');

    expect(overviewPanelSource).toContain('from "./ConfigOverviewPanel.styles"');
    expect(runtimePanelSource).toContain('from "./ConfigRuntimePanel.styles"');
    expect(draftPanelSource).toContain('from "./ConfigDraftPanel.styles"');
    expect(providerPanelSource).toContain('from "./ConfigProviderRegistryPanel.styles"');
    expect(overviewPanelSource).not.toContain("ConfigRoute.styles");
    expect(runtimePanelSource).not.toContain("ConfigRoute.styles");
    expect(draftPanelSource).not.toContain("ConfigRoute.styles");
    expect(providerPanelSource).not.toContain("ConfigRoute.styles");

    expect(overviewPanelStyles.sectionSurface).toBeTypeOf("string");
    expect(runtimePanelStyles.sectionSurface).toBeTypeOf("string");
    expect(draftPanelStyles.sectionSurface).toBeTypeOf("string");
    expect(providerPanelStyles.sectionSurface).toBeTypeOf("string");
    expect(providerPanelStyles.registryWorkspace).toBeTypeOf("string");
    expect(draftPanelSource).toContain("<LazyJsonCodeMirror");
    expect(routeSource).toContain("onIntakeModeChange");
  });

  it("keeps the config loading placeholder as a dense board with nav, metrics, and specs", () => {
    expect(placeholderPanelSource).toContain("styles.loadingNavPanel");
    expect(placeholderPanelSource).toContain("styles.loadingNavList");
    expect(placeholderPanelSource).toContain("styles.loadingMetricGrid");
    expect(placeholderPanelSource).toContain("styles.loadingSpecGrid");
    expect(placeholderPanelStyles.loadingNavPanel).toBeTypeOf("string");
    expect(placeholderPanelStyles.loadingMetricGrid).toBeTypeOf("string");
    expect(placeholderPanelStyles.loadingBoardHeader).toContain("max-[720px]:[grid-template-columns:1fr]");
    expect(placeholderPanelStyles.loadingMetricGrid).toContain("max-[1120px]:[grid-template-columns:repeat(2,minmax(0,1fr))]");
    expect(placeholderPanelStyles.loadingMetricGrid).toContain("max-[520px]:[grid-template-columns:1fr]");
    expect(placeholderPanelStyles.loadingSpecGrid).toContain("max-[720px]:[grid-template-columns:1fr]");
    expect(extractedPanelStylesSource).toContain("loadingMetricGrid");
  });

  it("moves supplemental config explanation into hover text instead of permanent helper copy", () => {
    expect(routeSource).toContain("subtitleHint");
    expect(routeSource).toContain('subtitleHint={copy.subtitleHint}');
    expect(overviewPanelSource).toContain("sourceBodyShort");
    expect(providerPanelSource).toContain("Provider 与模型工作台");
    expect(overviewPanelSource).toContain('title={copy.sourceBody}');
    expect(providerPanelSource).toContain('title={provider.providerId}');
    expect(routeSource).toContain('title={copy.openEnvironmentHint}');
    expect(routeSource).not.toContain('<span className={styles.helperText}>{copy.openEnvironmentHint}</span>');
  });

  it("keeps overview concise and moves raw configuration into tooling", () => {
    expect(overviewPanelSource).toContain("workspace.modelLibraryCount");
    expect(overviewPanelSource).toContain("workspace.blockingCount");
    expect(overviewPanelSource).toContain("workspace.warningCount");
    expect(overviewPanelSource).not.toContain("onOpenEnvironment");
    expect(overviewPanelSource).not.toContain("workspace.rawToml");
    expect(draftPanelSource).toContain("rawToml: string");
    expect(draftPanelSource).toContain("configPath: string");
    expect(draftPanelSource).toContain("<LazyJsonCodeMirror");
    expect(draftPanelSource).toContain("<pre");
    expect(routeSource).toContain('activePage?.id === "tooling-access"');
    expect(routeSource).toContain("developerModeConfig.enabled");
    expect(routeSource).toContain("aria-label={copy.developerModeReadonly}");
  });

  it("keeps the model settings group dense enough to use the bottom viewport", () => {
    expect(routeSource).toContain('activePage?.id !== "model-connection"');
    expect(styles.content).toContain("[grid-template-rows:auto_auto_minmax(0,1fr)]");
    expect(styles.pageViewport).toContain("min-h-0");
    expect(routeSource).toContain("<ConfigProviderRegistryPanel");
    expect(providerPanelSource).toContain('id="config-models"');
    expect(providerPanelSource).toContain("styles.registryWorkspace");
    expect(providerPanelSource).toContain("<VDenseTable");
    expect(routeSource).toContain("styles.configEditorSection");
    expect(routeSource).toContain('section.id === "llm-discovery" ? styles.configDiscoverySection : ""');
    expect(routeSource).toContain("styles.notice");
    expect(providerPanelSource).toContain("styles.tableScroll");
    expect(providerPanelSource).toContain("styles.modelIdentity");
    expect(stylesSource).toContain("contentModels:");
    expect(providerPanelStylesSource).toContain("registryWorkspace:");
    expect(providerPanelStylesSource).toContain("tableScroll:");
    expect(stylesSource).toContain("configEditorSection:");
    expect(stylesSource).toContain("configDiscoverySection:");
  });

  it("converges the provider registry into a compact VUI workbench contract", () => {
    expect(providerPanelStylesSource).not.toMatch(/\bsurface-card\b(?!\))/);
    expect(providerPanelStylesSource).not.toContain("var(--radius-panel)");
    expect(providerPanelStyles.sectionSurface).toContain("[border-radius:8px]");
    expect(providerPanelStyles.registryWorkspace).toContain("[--vui-workspace-sidebar:clamp(22rem,28%,28rem)]");
    expect(providerPanelStyles.providerList).toContain("overflow-y-auto");
    expect(providerPanelStyles.tableScroll).toContain("h-full");
    expect(providerPanelStyles.providerButton).toContain("!min-h-[58px]");
    expect(providerPanelStyles.tableScroll).toContain("overflow-auto");
    expect(providerPanelStyles.table).toContain("[&_thead]:sticky");
    expect(providerPanelSource).toContain("filterProviderModels");
    expect(providerPanelSource).toContain("deriveProviderModelActionState");
    expect(providerPanelSource).toContain('aria-label="搜索模型"');
    expect(providerPanelStyles.dangerZone).toContain("justify-between");
    expect(providerPanelSource).toContain("测试调用");
    expect(providerPanelSource).toContain("verificationStatus");
    expect(routeSource).toContain("handleTestProviderModel");
  });

  it("bounds Config diagnostics and transient notices so long text cannot force page overflow", () => {
    expect(styles.notice).toContain("[min-width:0]");
    expect(styles.notice).toContain("[overflow-wrap:anywhere]");
    expect(styles.matrixCard).toContain("[min-width:0]");
    expect(styles.matrixCard).toContain("[&_*]:[overflow-wrap:anywhere]");
    expect(styles.profileTableWrap).toContain("[min-width:0]");
    expect(healthDiagnosticsPanelStyles.findingCard).toContain("[min-width:0]");
    expect(healthDiagnosticsPanelStyles.healthPanelHeader).toContain("[min-width:0]");
    expect(healthDiagnosticsPanelStyles.quickActionItem).toContain("max-[520px]:[grid-template-columns:1fr]");
  });

  it("keeps the tablet config sidebar compact instead of stretching every control full width", () => {
    expect(stylesSource).toContain("sidebarStatus:");
    expect(stylesSource).toContain("buttonBlock:");
    expect(styles.buttonBlock).toContain("[width:auto]");
    expect(stylesSource).not.toContain("buttonBlock [width:100%]");
    expect(stylesSource).toContain("max-[1120px]:[grid-template-columns:minmax(150px,0.7fr)_minmax(180px,1fr)_max-content]");
    expect(stylesSource).toContain("max-[1120px]:[&_.buttonBlock]:[width:auto]");
    expect(stylesSource).toContain("max-[1120px]:[&_.buttonBlock]:[justify-self:end]");
    expect(stylesSource).toContain("max-[1120px]:[&:not(.sidebarNavPanelCollapsed)]:[display:grid]");
    expect(stylesSource).toContain("max-[1120px]:[&:not(.sidebarNavPanelCollapsed)]:[grid-template-columns:minmax(170px,0.32fr)_minmax(0,1fr)]");
    expect(stylesSource).toContain("max-[1120px]:[display:flex]");
    expect(stylesSource).toContain("max-[1120px]:[flex-wrap:wrap]");

    expect(stylesSource).toContain("max-[720px]:[&_.buttonBlock]:[width:100%]");
    expect(stylesSource).toContain("max-[720px]:[display:grid]");
    expect(stylesSource).toContain("max-[720px]:[grid-template-columns:1fr]");
  });

  it("keeps the settings workbench readable over custom backgrounds with a bounded draft editor", () => {
    expect(routeSource).toContain("styles.configHeader");
    expect(routeSource).toContain("styles.configStatusActions");
    expect(routeSource).toContain("<ConfigSettingsSidebar");
    expect(routeSource).not.toContain("styles.sidebarMetaStrip");
    expect(routeSource).not.toContain("styles.sidebarStatusCompact");
    expect(routeSource).not.toContain("styles.sidebarMetrics");

    expect(stylesSource).toContain("const readablePanelSurface");
    expect(stylesSource).toContain("const readableRowSurface");
    expect(styles.page).toContain("[background:color-mix(in_srgb,var(--surface-page)_94%,var(--bg-canvas))]");
    expect(stylesSource).toContain("configHeader:");
    expect(styles.configHeader).toContain("color-mix(in_srgb,var(--surface-panel)_96%,var(--bg-canvas))");

    expect(draftPanelSource).toContain("styles.draftWorkbench");
    expect(draftPanelSource).toContain("styles.draftActionRail");
    expect(draftPanelStylesSource).toContain("const readablePanelSurface");
    expect(draftPanelStyles.draftWorkbench).toContain("[grid-template-rows:auto_minmax(22rem,1fr)_auto]");
    expect(draftPanelStyles.editorWrap).toContain("[min-height:22rem]");
    expect(draftPanelStyles.sectionSurface).toContain("[height:100%]");
    expect(draftPanelStyles.sectionSurface).not.toContain("color-mix(in_srgb,var(--vui-surface-panel)_72%,transparent)");
    expect(overviewPanelStyles.sectionSurface).not.toContain("color-mix(in_srgb,var(--vui-surface-panel)_72%,transparent)");
    expect(runtimePanelStyles.sectionSurface).not.toContain("color-mix(in_srgb,var(--vui-surface-panel)_72%,transparent)");
    expect(providerPanelStyles.sectionSurface).not.toContain("color-mix(in_srgb,var(--vui-surface-panel)_72%,transparent)");
    expect(healthDiagnosticsPanelStyles.sectionSurface).not.toContain("color-mix(in_srgb,var(--vui-surface-panel)_72%,transparent)");
    expect(placeholderPanelStyles.loadingBoard).not.toContain("color-mix(in_srgb,var(--vui-surface-panel)_72%,transparent)");
  });

  it("keeps Config image editors and model content constrained on narrow screens", () => {
    expect(stylesSource).toContain("contentModels:");
    expect(styles.contentModels).toContain("max-[720px]:[max-height:none]");
    expect(styles.contentModels).toContain("max-[720px]:[overflow:visible]");

    expect(stylesSource).toContain("avatarCropWorkspace:");
    expect(styles.avatarCropWorkspace).toContain("[display:grid]");
    expect(styles.avatarCropWorkspace).toContain("[min-width:0]");
    expect(styles.avatarCropWorkspace).toContain("max-[720px]:[grid-template-columns:1fr]");

    expect(stylesSource).toContain("avatarImageEditor:");
    expect(styles.avatarImageEditor).toContain("[display:grid]");
    expect(styles.avatarImageEditor).toContain("[min-width:0]");
    expect(styles.avatarImageValue).toContain("[display:flex]");
    expect(styles.avatarImageValue).toContain("[max-width:100%]");

    expect(stylesSource).toContain("themeBackgroundImageEditor:");
    expect(styles.themeBackgroundImageEditor).toContain("[display:grid]");
    expect(styles.themeBackgroundImageEditor).toContain("[min-width:0]");
    expect(styles.themeBackgroundImageValue).toContain("[min-width:0]");
    expect(styles.themeBackgroundImageValue).toContain("[max-width:100%]");

    expect(stylesSource).toContain("userProfileAvatarFields:");
    expect(styles.userProfileAvatarFields).toContain("max-[900px]:[grid-template-columns:1fr]");
  });

  it("supports Agent Center return links and section deep links", () => {
    expect(routeSource).toContain("useSearchParams");
    expect(routeSource).toContain("safeAgentCenterReturnToPath");
    expect(routeSource).toContain("const lastRequestedSectionRef = useRef(\"\")");
    expect(routeSource).toContain("const requestedSectionId = String(searchParams.get(\"section\") || \"\").trim()");
    expect(routeSource).toContain("const returnToPath = safeAgentCenterReturnToPath(searchParams.get(\"returnTo\"))");
    expect(routeSource).toContain("const returnToLabel = searchParams.get(\"returnLabel\") === \"agents\" ? copy.returnToAgents : copy.returnToSource");
    expect(routeSource).toContain("requestedSectionId !== lastRequestedSectionRef.current");
    expect(routeSource).toContain("lastRequestedSectionRef.current = requestedSectionId");
    expect(routeSource).toContain("setActiveGroupId(requestedGroup.id)");
    expect(routeSource).toContain("className={styles.returnButton}");
    expect(routeSource).toContain("to={returnToPath}");
    expect(stylesSource).toContain("returnButton:");
  });

  it("splits Provider creation into service-class templates and concrete model discovery", () => {
    expect(wizardSource).toContain("TEMPLATE_GROUPS");
    expect(wizardSource).toContain('"official_api"');
    expect(wizardSource).toContain('"local_runtime"');
    expect(wizardSource).toContain("templateModelFamily");
    expect(wizardSource).toContain("onDiscover");
    expect(wizardSource).not.toContain("modelPresetGroups.map");
  });

  it("shows developer mode as launcher-owned read-only state", () => {
    expect(routeSource).toContain("developerModeReadonly");
    expect(routeSource).toContain("developerModeControlled");
    expect(routeSource).toContain("Launcher 控制");
    expect(routeSource).not.toContain("styles.sidebarMetaStrip");
    expect(routeSource).not.toContain("updateLauncherDeveloperMode");
    expect(routeSource).not.toContain("developer-mode/cleanup");
  });

  it("routes cleanup diagnostics to Launcher maintenance instead of Web Reset", () => {
    expect(routeSource).toContain("healthOpenLauncher");
    expect(routeSource).toContain("<ConfigHealthDiagnosticsPanel");
    expect(healthDiagnosticsPanelSource).toContain('from "./ConfigHealthDiagnosticsPanel.styles"');
    expect(healthDiagnosticsPanelSource).not.toContain("ConfigRoute.styles");
    expect(healthDiagnosticsPanelSource).not.toContain("ConfigRoute.module.css");
    expect(healthDiagnosticsPanelSource).toContain('href="/launcher"');
    expect(healthDiagnosticsPanelStyles.sectionSurface).toBeTypeOf("string");
    expect(healthDiagnosticsPanelStyles.logHelperGrid).toBeTypeOf("string");
    expect(extractedPanelStylesSource).toContain("logHelperGrid");
    expect(routeSource).toContain("queryKeys.launcherMaintenanceSummary()");
    expect(routeSource).not.toContain("healthOpenReset");
    expect(healthDiagnosticsPanelSource).not.toContain("healthOpenReset");
    expect(routeSource).not.toContain("queryKeys.resetSummary()");
    expect(healthDiagnosticsPanelSource).not.toContain("`/reset?item=");
    expect(healthDiagnosticsPanelSource).not.toContain('href={`/reset?item=');
  });

  it("moves health diagnostics display into a route-local panel while keeping ConfigRoute as query owner", () => {
    expect(routeSource).toContain('import { ConfigHealthDiagnosticsPanel');
    expect(routeSource).toContain('from "./ConfigHealthDiagnosticsPanel"');
    expect(routeSource).toContain("<ConfigHealthDiagnosticsPanel");
    expect(routeSource).toContain("diagnostics={healthDiagnosticsQuery.data}");
    expect(routeSource).toContain("loading={healthDiagnosticsQuery.isLoading || healthDiagnosticsQuery.isFetching}");
    expect(routeSource).toContain("void healthDiagnosticsQuery.refetch();");

    expect(routeSource).not.toContain("function LogHelperCenter");
    expect(routeSource).not.toContain("function HealthFindingCard");
    expect(routeSource).not.toContain("function HealthQuickActionLink");
    expect(routeSource).not.toContain("function SessionHelperCard");
    expect(routeSource).not.toContain("function LogHelperCard");

    expect(healthDiagnosticsPanelSource).toContain("export function ConfigHealthDiagnosticsPanel");
    expect(healthDiagnosticsPanelSource).toContain("function HealthFindingCard");
    expect(healthDiagnosticsPanelSource).toContain("function HealthQuickActionLink");
    expect(healthDiagnosticsPanelSource).toContain("function SessionHelperCard");
    expect(healthDiagnosticsPanelSource).toContain("function LogHelperCard");
  });

  it("keeps health diagnostics cleanup and reset hints routed to Launcher maintenance", () => {
    expect(healthDiagnosticsPanelSource).toContain("healthOpenLauncher");
    expect(healthDiagnosticsPanelSource).toContain('href="/launcher"');
    expect(healthDiagnosticsPanelSource).toContain("action.resetItemId ? \"/launcher\"");
    expect(healthDiagnosticsPanelSource).not.toContain("`/reset?item=");
    expect(healthDiagnosticsPanelSource).not.toContain("href={`/reset?item=");
    expect(routeSource).not.toContain("`/reset?item=");
    expect(routeSource).not.toContain("href={`/reset?item=");
  });

  it("keeps workbench background image settings separate from avatar cropping", () => {
    expect(routeSource).toContain("themeBackgroundImagePreviewUrl");
    expect(routeSource).toContain("renderThemeBackgroundControl");
    expect(routeSource).toContain("uploadThemeBackgroundFile");
    expect(routeSource).toContain("className={childExpanded ? styles.treeWide : styles.treeObjectCell}");
    expect(routeSource).not.toContain('path === "ui.workbench_theme"');
    expect(routeSource).toContain('kind === "background_image"');
    expect(routeSource).toContain("/api/config/theme-background-image");
    expect(routeSource).toContain("onThemeBackgroundImageUpload");
    expect(routeSource).toContain("copy.uploadThemeBackgroundImage");
    expect(routeSource).toContain("copy.clearThemeBackgroundImage");
    expect(routeSource).toContain("copy.themeBackgroundPresetTitle");
    expect(routeSource).toContain("className={styles.themeBackgroundPresetTitle}");
    expect(routeSource).toContain("{active ? <em>{lang === \"zh\" ? \"当前\" : \"Current\"}</em> : null}");
    expect(routeSource).toContain("title={hint || undefined}");
    expect(routeSource).toContain("themeBackgroundPresetButton");
    expect(routeSource).toContain("aria-pressed={active}");
    expect(stylesSource).toContain("themeBackgroundDropButton:");
    expect(stylesSource).toContain("themeBackgroundImagePreview:");
    expect(stylesSource).toContain("themeBackgroundPresetGrid:");
    expect(stylesSource).toContain("themeBackgroundImageValue:");
    expect(routeSource).toContain("themeBackgroundPresetButton");
    expect(routeSource).toContain("aria-pressed={active}");
    expect(routeSource).toContain("{active ? <em>{lang === \"zh\" ? \"当前\" : \"Current\"}</em> : null}");
    expect(stylesSource).toContain("themeBackgroundDropButton:");
    expect(stylesSource).toContain("themeBackgroundPresetGrid:");
    expect(stylesSource).toContain("[display:grid]");
    expect(stylesSource).toContain("themeBackgroundPresetButton:");
  });

  it("renders the Web user avatar as a compact image control instead of a raw path field", () => {
    expect(routeSource).toContain("avatarImageDisplayName");
    expect(routeSource).toContain("copy.avatarImageCurrent");
    expect(routeSource).toContain("copy.avatarImageEmpty");
    expect(routeSource).toContain("copy.avatarImageClickToUpload");
    expect(routeSource).toContain("className={styles.avatarImageDropButton}");
    expect(routeSource).toContain("className={styles.avatarImageUploadCue}");
    expect(routeSource).toContain("className={styles.avatarImageMeta}");
    expect(routeSource).toContain("await beginAvatarCrop(file, absolutePath)");
    expect(stylesSource).toContain("avatarImageMeta:");
    expect(stylesSource).toContain("avatarImageDropButton:");
    expect(stylesSource).toContain("avatarImageUploadCue:");
    expect(stylesSource).toContain("avatarImageDropButton:");
    expect(stylesSource).toContain("avatarImageMeta:");
  });

  it("keeps empty string-list settings out of object-list layout blocks", () => {
    expect(routeSource).toContain("function isConfigObjectListValue");
    expect(routeSource).toContain('kind === "string_list"');
    expect(routeSource).toContain("value.length > 0");
    expect(routeSource).toContain("isConfigObjectListValue(childValue, childMetaKind)");
    expect(routeSource).toContain("isConfigObjectListValue(nodeValue, metaMap[absolutePath]?.kind)");
    expect(routeSource).not.toContain("childValue.every((item) => isPlainObject(item))");
    expect(routeSource).not.toContain("Array.isArray(nodeValue) && nodeValue.every");
  });

  it("uses a dedicated user profile layout for identity, preferences, and avatar settings", () => {
    expect(routeSource).toContain("function renderUserProfileBody");
    expect(routeSource).toContain('absolutePath === "user_profile"');
    expect(routeSource).toContain("styles.userProfileLayout");
    expect(routeSource).toContain("styles.userProfileIdentityFields");
    expect(routeSource).toContain("styles.userProfilePreferencesField");
    expect(routeSource).toContain("styles.userProfileAvatarGroup");
    expect(routeSource).toContain("styles.userProfileAvatarFields");
    expect(routeSource).toContain("copy.userProfileAvatarGroupTitle");
    expect(routeSource).toContain("copy.userProfileAvatarGroupHint");
    expect(stylesSource).toContain("userProfileLayout:");
    expect(stylesSource).toContain("userProfileIdentityFields:");
    expect(stylesSource).toContain("userProfileAvatarFields:");
    expect(stylesSource).toContain("[display:grid]");
    expect(stylesSource).toContain("userProfileIdentityFields:");
    expect(stylesSource).toContain("userProfileAvatarFields:");
  });

  it("uses a compact layout for large config sections with many fields", () => {
    expect(routeSource).toContain("function isDenseConfigSection");
    expect(routeSource).toContain('section.id === "llm-discovery"');
    expect(routeSource).toContain("return false");
    expect(routeSource).toContain("Number(section.fieldCount || 0) >= 12");
    expect(routeSource).toContain("styles.configDenseSection");
    expect(routeSource).toContain('section.id === "llm-discovery" ? styles.configDiscoverySection : ""');
    expect(routeSource).toContain("styles.treeGrid");
    expect(routeSource).toContain("styles.treeFieldCardView");
    expect(routeSource).toContain("styles.treeFieldCardEdit");
    expect(routeSource).toContain("styles.treeObjectCell");
    expect(routeSource).toContain("styles.treeToggle");
    expect(stylesSource).toContain("configDenseSection:");
    expect(stylesSource).toContain("[&>_.treeGrid]:[grid-template-columns:repeat(3,minmax(220px,1fr))]");
    expect(stylesSource).toContain("max-[1500px]:[&>_.treeGrid]:[grid-template-columns:repeat(2,minmax(220px,1fr))]");
    expect(styles.configDenseSection).not.toContain("repeat(auto-fit");
    expect(stylesSource).toContain("treeGrid:");
  });

  it("keeps operational settings readable over custom workbench backgrounds", () => {
    expect(styles.page).toContain("[background:color-mix(in_srgb,var(--surface-page)_94%,var(--bg-canvas))]");
    expect(styles.page).toContain("[isolation:isolate]");
    expect(stylesSource).toContain("color-mix(in_srgb,var(--surface-panel)_96%,var(--bg-canvas))");
    expect(styles.sidebar).toContain("color-mix(in_srgb,var(--surface-panel)_96%,var(--bg-canvas))");
    expect(styles.sectionSurface).toContain("color-mix(in_srgb,var(--surface-panel)_96%,var(--bg-canvas))");
    expect(styles.treeGrid).toContain("[grid-template-columns:repeat(2,minmax(0,1fr))]");
    expect(styles.configDenseSection).toContain("[&>_.treeGrid]:[grid-template-columns:repeat(3,minmax(220px,1fr))]");
    expect(styles.configDenseSection).not.toContain("repeat(auto-fit");
    expect(styles.configDiscoverySection).toContain("[&>_.treeGrid]:[grid-template-columns:repeat(3,minmax(220px,1fr))]");
    expect(styles.treeFieldValue).toContain("color-mix(in_srgb,var(--surface-code)_92%,var(--surface-panel))");
    expect(healthDiagnosticsPanelStylesSource).toContain("color-mix(in_srgb,var(--surface-panel)_96%,var(--bg-canvas))");
    expect(healthDiagnosticsPanelStylesSource).toContain("color-mix(in_srgb,var(--surface-card)_94%,var(--surface-panel))");
  });

  it("keeps extracted Config panels on local VUI/Tailwind surface contracts", () => {
    expect(extractedPanelStylesSource).toContain("const panelSurface");
    expect(extractedPanelStylesSource).toContain("color-mix(in_srgb,var(--surface-panel)_96%,var(--bg-canvas))");
    expect(extractedPanelStylesSource).toContain("color-mix(in_srgb,var(--surface-card)_94%,var(--surface-panel))");
    expect(extractedPanelStylesSource).toContain("var(--vui-control-muted)");
    expect(extractedPanelStylesSource).toContain("var(--vui-border-subtle)");
    expect(overviewPanelStyles.sectionSurface).toContain(
      "color-mix(in_srgb,var(--surface-panel)_96%,var(--bg-canvas))",
    );
    expect(runtimePanelStyles.segmented).toContain("[background:var(--vui-surface-toolbar)]");
    expect(draftPanelStyles.actionButton).toContain("var(--vui-control-muted)");
    expect(healthDiagnosticsPanelStyles.findingCard).toContain("color-mix(in_srgb,var(--surface-card)_94%,var(--surface-panel))");
    expect(providerPanelStyles.sectionSurface).toContain(
      "color-mix(in_srgb,var(--surface-panel)_96%,var(--bg-canvas))",
    );
    expect(placeholderPanelStyles.loadingBoard).toContain(
      "color-mix(in_srgb,var(--surface-panel)_96%,var(--bg-canvas))",
    );
    expect(extractedPanelStylesSource).not.toContain("[background:var(--vui-gradient-route-soft),var(--surface-panel)]");
  });

  it("keeps Config section roots and status primitives in their direct layout slots", () => {
    const affectedPanelSources = [
      draftPanelSource,
      overviewPanelSource,
      runtimePanelSource,
      healthDiagnosticsPanelSource,
    ].join("\n");

    expect(affectedPanelSources).not.toMatch(/<VSurface[\s\S]*?<VSection/);
    expect(routeSource).not.toMatch(/<VSurface as="section" id="config-diagnostics"[\s\S]*?<VSection/);
    expect(draftPanelSource).toContain("headerClassName={styles.sectionHeader}");
    expect(overviewPanelSource).toContain("headerClassName={styles.sectionHeader}");
    expect(runtimePanelSource).toContain("headerClassName={styles.sectionHeader}");
    expect(healthDiagnosticsPanelSource).toContain("headerClassName={styles.sectionHeader}");
    expect(routeSource).toContain("headerClassName={styles.sectionHeader}");
    expect((routeSource.match(/<VRouteHeader\b/g) ?? []).length).toBe(1);
    expect(routeSource).not.toMatch(/<VRouteHeader[\s\S]*?<VStatusStrip[\s\S]*?<\/VRouteHeader>/);
    expect(styles.configHeader).toContain("[grid-template-columns:minmax(0,1fr)]");
  });

  it("keeps a canonical Config h1 across loaded and placeholder states", () => {
    expect(placeholderPanelSource).toContain("VRouteHeader");
    expect(placeholderPanelSource).not.toContain("<VPanelHeader");
    expect(routeSource).toContain("<ConfigSettingsSidebar");
    expect((routeSource.match(/<VRouteHeader\b/g) ?? []).length).toBe(1);
  });

  it("routes Config controls through VUI primitives", () => {
    expect(routeSource).toContain('from "../components/vui"');
    expect(routeSource).toContain("VRouteHeader");
    expect(routeSource).toContain("VStatusStrip");
    expect(routeSource).toContain("VStringSelect");
    expect(configSources).toContain("<VButton");
    expect(configSources).toContain("<VSurface");
    expect(configSources).toContain("<VSection");
    expect(configSources).not.toContain("<VNativeInput");
    expect(configSources).not.toContain("<VNativeSelect");
    expect(configSources).not.toContain("<VNativeTextarea");
    expect(configSources).not.toContain("<VNativeButton");
    expect(routeSource).toContain('type="file"');
    expect(configSources).not.toMatch(/<button\b/);
    expect(configSources).not.toMatch(/<select\b/);
    expect(configSources).not.toMatch(/<textarea\b/);
  });

  it("prioritizes the visible VUI select trigger when focusing the model editor", () => {
    expect(routeSource).toContain('button[data-vui="select-trigger"]:not([data-disabled="true"]):not([disabled])');
    expect(routeSource).toContain('input:not([disabled]):not([type="hidden"])');
    expect(routeSource).toContain("textarea:not([disabled])");
  });
});
