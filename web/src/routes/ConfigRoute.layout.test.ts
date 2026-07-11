import { describe, expect, it } from "vitest";

import routeSource from "./ConfigRoute.tsx?raw";
import draftPanelSource from "./ConfigDraftPanel.tsx?raw";
import draftPanelStylesSource from "./ConfigDraftPanel.styles.ts?raw";
import draftPanelStyles from "./ConfigDraftPanel.styles";
import healthDiagnosticsPanelSource from "./ConfigHealthDiagnosticsPanel.tsx?raw";
import healthDiagnosticsPanelStylesSource from "./ConfigHealthDiagnosticsPanel.styles.ts?raw";
import healthDiagnosticsPanelStyles from "./ConfigHealthDiagnosticsPanel.styles";
import modelLibraryPanelSource from "./ConfigModelLibraryPanel.tsx?raw";
import modelLibraryPanelStylesSource from "./ConfigModelLibraryPanel.styles.ts?raw";
import modelLibraryPanelStyles from "./ConfigModelLibraryPanel.styles";
import overviewPanelSource from "./ConfigOverviewPanel.tsx?raw";
import overviewPanelStylesSource from "./ConfigOverviewPanel.styles.ts?raw";
import overviewPanelStyles from "./ConfigOverviewPanel.styles";
import placeholderPanelSource from "./ConfigWorkspacePlaceholderPanel.tsx?raw";
import placeholderPanelStylesSource from "./ConfigWorkspacePlaceholderPanel.styles.ts?raw";
import placeholderPanelStyles from "./ConfigWorkspacePlaceholderPanel.styles";
import runtimePanelSource from "./ConfigRuntimePanel.tsx?raw";
import runtimePanelStylesSource from "./ConfigRuntimePanel.styles.ts?raw";
import runtimePanelStyles from "./ConfigRuntimePanel.styles";
import styles from "./ConfigRoute.styles";
import stylesSource from "./ConfigRoute.styles.ts?raw";

const extractedPanelStylesSource = [
  draftPanelStylesSource,
  healthDiagnosticsPanelStylesSource,
  modelLibraryPanelStylesSource,
  overviewPanelStylesSource,
  placeholderPanelStylesSource,
  runtimePanelStylesSource,
].join("\n");

const configSources = [
  routeSource,
  overviewPanelSource,
  runtimePanelSource,
  draftPanelSource,
  modelLibraryPanelSource,
  healthDiagnosticsPanelSource,
  placeholderPanelSource,
].join("\n");

describe("ConfigRoute layout contract", () => {
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

  it("extracts core Config sections into route-local display panels", () => {
    expect(routeSource).toContain("<ConfigOverviewPanel");
    expect(routeSource).toContain("<ConfigRuntimePanel");
    expect(routeSource).toContain("<ConfigDraftPanel");
    expect(routeSource).toContain("<ConfigModelLibraryPanel");
    expect(routeSource).not.toContain('<section id="config-overview"');
    expect(routeSource).not.toContain('<section id="config-shell"');
    expect(routeSource).not.toContain('<section id="config-draft"');
    expect(routeSource).not.toContain('<section id="config-models"');

    expect(overviewPanelSource).toContain('from "./ConfigOverviewPanel.styles"');
    expect(runtimePanelSource).toContain('from "./ConfigRuntimePanel.styles"');
    expect(draftPanelSource).toContain('from "./ConfigDraftPanel.styles"');
    expect(modelLibraryPanelSource).toContain('from "./ConfigModelLibraryPanel.styles"');
    expect(overviewPanelSource).not.toContain("ConfigRoute.styles");
    expect(runtimePanelSource).not.toContain("ConfigRoute.styles");
    expect(draftPanelSource).not.toContain("ConfigRoute.styles");
    expect(modelLibraryPanelSource).not.toContain("ConfigRoute.styles");

    expect(overviewPanelStyles.sectionSurface).toBeTypeOf("string");
    expect(runtimePanelStyles.sectionSurface).toBeTypeOf("string");
    expect(draftPanelStyles.sectionSurface).toBeTypeOf("string");
    expect(modelLibraryPanelStyles.sectionSurface).toBeTypeOf("string");
    expect(modelLibraryPanelStyles.modelLibrarySection).toBeTypeOf("string");
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
    expect(routeSource).toContain('title={copy.subtitleHint}');
    expect(overviewPanelSource).toContain("sourceBodyShort");
    expect(modelLibraryPanelSource).toContain("modelsBodyShort");
    expect(overviewPanelSource).toContain('title={copy.sourceBody}');
    expect(modelLibraryPanelSource).toContain('title={copy.modelsBody}');
    expect(overviewPanelSource).toContain('title={copy.openEnvironmentHint}');
    expect(routeSource).not.toContain('<span className={styles.helperText}>{copy.openEnvironmentHint}</span>');
  });

  it("keeps the model settings group dense enough to use the bottom viewport", () => {
    expect(routeSource).toContain('activeSection?.id === "models-profiles"');
    expect(routeSource).toContain("styles.contentModels");
    expect(routeSource).toContain("<ConfigModelLibraryPanel");
    expect(modelLibraryPanelSource).toContain('id="config-models"');
    expect(modelLibraryPanelSource).toContain("styles.modelLibrarySection");
    expect(modelLibraryPanelSource).toContain("styles.modelInventoryTable");
    expect(routeSource).toContain("styles.configEditorSection");
    expect(routeSource).toContain('section.id === "llm-discovery" ? styles.configDiscoverySection : ""');
    expect(routeSource).toContain("styles.notice");
    expect(modelLibraryPanelSource).toContain("styles.profileTableWrap");
    expect(modelLibraryPanelSource).toContain("styles.profileTaskCell");
    expect(stylesSource).toContain("contentModels:");
    expect(modelLibraryPanelStylesSource).toContain("modelLibrarySection:");
    expect(modelLibraryPanelStylesSource).toContain("modelInventoryTable:");
    expect(stylesSource).toContain("configEditorSection:");
    expect(stylesSource).toContain("configDiscoverySection:");
  });

  it("converges the model library panel into a compact VUI row-panel contract", () => {
    expect(modelLibraryPanelStylesSource).not.toMatch(/\bsurface-card\b(?!\))/);
    expect(modelLibraryPanelStylesSource).not.toContain("var(--radius-panel)");
    expect(modelLibraryPanelStyles.sectionSurface).toContain("[border-radius:8px]");
    expect(modelLibraryPanelStyles.formSurface).toContain("[max-height:min(360px,_44vh)]");
    expect(modelLibraryPanelStyles.formSurface).toContain("[overflow:auto]");
    expect(modelLibraryPanelStyles.formGridWide).toContain("repeat(auto-fit,minmax(176px,1fr))");
    expect(modelLibraryPanelStyles.modelLibrarySection).toContain("[grid-template-rows:auto_auto_auto_auto_minmax(0,0.58fr)_minmax(0,1fr)]");
    expect(modelLibraryPanelStyles.modelLibraryTestBar).toContain("[padding:6px_8px]");
    expect(modelLibraryPanelStyles.modelLibraryTestBar).toContain("max-[720px]:[&_.actionButton]:[width:fit-content]");
    expect(modelLibraryPanelStyles.profileTableWrap).toContain("[min-height:min(240px,_34vh)]");
    expect(modelLibraryPanelStyles.profileTableWrap).toContain("[min-width:0]");
    expect(modelLibraryPanelStyles.profileTableActions).toContain("[flex-wrap:nowrap]");
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
    expect(routeSource).toContain("styles.configStatusBand");
    expect(routeSource).toContain("styles.configStatusActions");
    expect(routeSource).toContain("styles.sidebarMetaStrip");
    expect(routeSource).toContain("styles.sidebarStatusCompact");
    expect(routeSource).not.toContain("styles.sidebarMetrics");

    expect(stylesSource).toContain("const readablePanelSurface");
    expect(stylesSource).toContain("const readableRowSurface");
    expect(styles.page).toContain("[background:color-mix(in_srgb,var(--surface-page)_94%,var(--bg-canvas))]");
    expect(stylesSource).toContain("configStatusBand:");
    expect(stylesSource).toContain("sidebar:");
    expect(styles.configStatusBand).toContain("color-mix(in_srgb,var(--surface-panel)_96%,var(--bg-canvas))");
    expect(styles.sidebar).toContain("color-mix(in_srgb,var(--surface-panel)_96%,var(--bg-canvas))");
    expect(styles.sidebarMetaStrip).toContain("[display:flex]");
    expect(styles.sidebarMetaStrip).toContain("[flex-wrap:wrap]");
    expect(styles.sidebarStatusCompact).toContain(
      "[background:color-mix(in_srgb,var(--surface-card)_94%,var(--surface-panel))]",
    );

    expect(draftPanelSource).toContain("styles.draftWorkbench");
    expect(draftPanelSource).toContain("styles.draftActionRail");
    expect(draftPanelStylesSource).toContain("const readablePanelSurface");
    expect(draftPanelStyles.draftWorkbench).toContain("[max-height:min(520px,_54vh)]");
    expect(draftPanelStyles.editorWrap).toContain("[min-height:260px]");
    expect(draftPanelStyles.editorWrap).toContain("[max-height:min(430px,_44vh)]");
    expect(draftPanelStyles.sectionSurface).not.toContain("color-mix(in_srgb,var(--vui-surface-panel)_72%,transparent)");
    expect(overviewPanelStyles.sectionSurface).not.toContain("color-mix(in_srgb,var(--vui-surface-panel)_72%,transparent)");
    expect(runtimePanelStyles.sectionSurface).not.toContain("color-mix(in_srgb,var(--vui-surface-panel)_72%,transparent)");
    expect(modelLibraryPanelStyles.sectionSurface).not.toContain("color-mix(in_srgb,var(--vui-surface-panel)_72%,transparent)");
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
    expect(routeSource).toContain("setActiveSectionId(requestedSectionId)");
    expect(routeSource).toContain("className={styles.returnButton}");
    expect(routeSource).toContain("to={returnToPath}");
    expect(stylesSource).toContain("returnButton:");
  });

  it("splits model creation into vendor templates and concrete model discovery", () => {
    expect(routeSource).toContain("providerVendorGroups");
    expect(routeSource).toContain("selectedProviderVendorTemplates");
    expect(modelLibraryPanelSource).toContain("copy.providerVendor");
    expect(modelLibraryPanelSource).toContain("copy.providerTemplate");
    expect(routeSource).toContain("applyProviderTemplate");
    expect(modelLibraryPanelSource).not.toContain("modelPresetGroups.map");
  });

  it("shows developer mode as launcher-owned read-only state", () => {
    expect(routeSource).toContain("developerModeReadonly");
    expect(routeSource).toContain("developerModeControlled");
    expect(routeSource).toContain("developerModeConfig.enabled");
    expect(routeSource).toContain("aria-label={copy.developerModeReadonly}");
    expect(routeSource).toContain("Launcher 控制");
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
    expect(modelLibraryPanelStyles.formSurface).toContain(
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
    expect(styles.configStatusBand).toContain("[grid-template-columns:1fr]");
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
});
