import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import routeSource from "./ConfigRoute.tsx?raw";

const stylesModuleSource = readFileSync(new URL("./ConfigRoute.module.css", import.meta.url), "utf-8");
const stylesSource = stylesModuleSource;

describe("ConfigRoute layout contract", () => {
  it("uses a full workspace placeholder for initial loading and load failure states", () => {
    expect(routeSource).toContain("function ConfigWorkspacePlaceholder");
    expect(routeSource).toContain("<ConfigWorkspacePlaceholder title={copy.loading} />");
    expect(routeSource).toContain('tone="error"');
    expect(routeSource).toContain("styles.loadingShell");
    expect(routeSource).toContain("styles.loadingBoard");
    expect(routeSource).not.toContain("<section className={styles.loadingSurface}>");
  });

  it("keeps the config loading placeholder as a dense board with nav, metrics, and specs", () => {
    expect(routeSource).toContain("styles.loadingNavPanel");
    expect(routeSource).toContain("styles.loadingNavList");
    expect(routeSource).toContain("styles.loadingMetricGrid");
    expect(routeSource).toContain("styles.loadingSpecGrid");
  });

  it("moves supplemental config explanation into hover text instead of permanent helper copy", () => {
    expect(routeSource).toContain("subtitleHint");
    expect(routeSource).toContain('title={copy.subtitleHint}');
    expect(routeSource).toContain("sourceBodyShort");
    expect(routeSource).toContain("modelsBodyShort");
    expect(routeSource).toContain('title={copy.sourceBody}');
    expect(routeSource).toContain('title={copy.modelsBody}');
    expect(routeSource).toContain('title={copy.openEnvironmentHint}');
    expect(routeSource).not.toContain('<span className={styles.helperText}>{copy.openEnvironmentHint}</span>');
  });

  it("keeps the model settings group dense enough to use the bottom viewport", () => {
    expect(routeSource).toContain('activeSection?.id === "models-profiles"');
    expect(routeSource).toContain("styles.contentModels");
    expect(routeSource).toContain("styles.modelLibrarySection");
    expect(routeSource).toContain("styles.configEditorSection");
    expect(routeSource).toContain('section.id === "llm-discovery" ? styles.configDiscoverySection : ""');
    expect(stylesSource).toContain(".contentModels");
    expect(routeSource).toContain("styles.notice");
    expect(routeSource).toContain("styles.profileTableWrap");
    expect(routeSource).toContain("styles.profileTaskCell");
    expect(stylesSource).toContain(".configDiscoverySection");
    expect(stylesModuleSource).toContain(".contentModels");
    expect(stylesModuleSource).toContain(".modelLibrarySection");
    expect(stylesModuleSource).toContain(".configEditorSection");
    expect(stylesModuleSource).toContain(".configDiscoverySection");
  });

  it("keeps the tablet config sidebar compact instead of stretching every control full width", () => {
    const tabletBlock = stylesSource.slice(
      stylesSource.indexOf("@media (max-width: 1120px)"),
      stylesSource.indexOf("@media (max-width: 720px)"),
    );
    const mobileBlock = stylesSource.slice(stylesSource.indexOf("@media (max-width: 720px)"));

    expect(tabletBlock).toContain(".sidebarStatus {");
    expect(tabletBlock).toContain("grid-template-columns: minmax(150px, 0.7fr) minmax(180px, 1fr) max-content;");
    expect(tabletBlock).toContain(".sidebarStatus .buttonBlock");
    expect(tabletBlock).toContain("width: auto");
    expect(tabletBlock).toContain(".sidebarNavPanel:not(.sidebarNavPanelCollapsed)");
    expect(tabletBlock).toContain("grid-template-columns: minmax(170px, 0.32fr) minmax(0, 1fr)");
    expect(tabletBlock).toContain(".sectionNav {");
    expect(tabletBlock).toContain("display: flex");
    expect(tabletBlock).toContain("flex-wrap: wrap");

    expect(mobileBlock).toContain(".sidebarStatus .buttonBlock");
    expect(mobileBlock).toContain("width: 100%");
    expect(mobileBlock).toContain(".sectionNav {");
    expect(mobileBlock).toContain("display: grid");
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
    expect(stylesSource).toContain(".returnButton");
  });

  it("splits model creation into vendor templates and concrete model discovery", () => {
    expect(routeSource).toContain("providerVendorGroups");
    expect(routeSource).toContain("selectedProviderVendorTemplates");
    expect(routeSource).toContain("copy.providerVendor");
    expect(routeSource).toContain("copy.providerTemplate");
    expect(routeSource).toContain("applyProviderTemplate");
    expect(routeSource).not.toContain("modelPresetGroups.map");
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
    expect(routeSource).toContain('href="/launcher"');
    expect(routeSource).toContain("queryKeys.launcherMaintenanceSummary()");
    expect(routeSource).not.toContain("healthOpenReset");
    expect(routeSource).not.toContain("queryKeys.resetSummary()");
    expect(routeSource).not.toContain("`/reset?item=");
    expect(routeSource).not.toContain('href={`/reset?item=');
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
    expect(stylesSource).toContain(".themeBackgroundDropButton");
    expect(stylesSource).toContain(".themeBackgroundImagePreview");
    expect(stylesSource).toContain(".themeBackgroundPresetGrid");
    expect(stylesSource).toContain(".themeBackgroundImageValue");
    expect(routeSource).toContain("themeBackgroundPresetButton");
    expect(routeSource).toContain("aria-pressed={active}");
    expect(routeSource).toContain("{active ? <em>{lang === \"zh\" ? \"当前\" : \"Current\"}</em> : null}");
    expect(stylesSource).toContain(".themeBackgroundDropButton");
    expect(stylesModuleSource).toContain(".themeBackgroundPresetGrid");
    expect(stylesModuleSource).toContain("display: grid");
    expect(stylesSource).toContain(".themeBackgroundPresetButton");
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
    expect(stylesSource).toContain(".avatarImageMeta");
    expect(stylesSource).toContain(".avatarImageDropButton");
    expect(stylesSource).toContain(".avatarImageUploadCue");
    expect(stylesSource).toContain(".avatarImageDropButton");
    expect(stylesSource).toContain(".avatarImageMeta");
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
    expect(stylesSource).toContain(".userProfileLayout");
    expect(stylesSource).toContain(".userProfileIdentityFields");
    expect(stylesSource).toContain(".userProfileAvatarFields");
    expect(stylesModuleSource).toContain(".userProfileLayout");
    expect(stylesModuleSource).toContain("display: grid");
    expect(stylesSource).toContain(".userProfileIdentityFields");
    expect(stylesSource).toContain(".userProfileAvatarFields");
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
    expect(stylesModuleSource).toContain(".configDenseSection > .treeGrid");
    expect(stylesModuleSource).toContain(".treeGrid");
  });

  it("routes Config controls through VUI primitives", () => {
    expect(routeSource).toContain('from "../components/vui"');
    expect(routeSource).toContain("<VButton");
    expect(routeSource).toContain("<VNativeInput");
    expect(routeSource).toContain("<VNativeSelect");
    expect(routeSource).toContain("<VNativeTextarea");
    expect(routeSource).not.toMatch(/<button\b/);
    expect(routeSource).not.toMatch(/<input\b/);
    expect(routeSource).not.toMatch(/<select\b/);
    expect(routeSource).not.toMatch(/<textarea\b/);
  });
});
