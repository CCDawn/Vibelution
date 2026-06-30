import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import routeSource from "./ConfigRoute.tsx?raw";

const stylesSource = readFileSync(new URL("./ConfigRoute.legacy.css", import.meta.url), "utf-8");

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
    expect(stylesSource).toContain("grid-template-rows: minmax(0, 1fr) auto");
    expect(stylesSource).toContain("max-height: calc(100dvh - 76px)");
    expect(stylesSource).toContain(".contentModels:has(> .notice)");
    expect(stylesSource).toContain(".modelLibrarySection .profileTableWrap");
    expect(stylesSource).toContain("grid-template-rows: auto auto auto auto auto minmax(0, 1fr)");
    expect(stylesSource).toContain("max-height: none");
    expect(stylesSource).toContain(".modelInventoryTable .profileTaskCell strong");
    expect(stylesSource).toContain(".configDiscoverySection");
    expect(stylesSource).toContain("align-self: end");
    expect(stylesSource).toContain("grid-template-columns: repeat(6, minmax(128px, 1fr))");
    expect(stylesSource).toContain("@media (max-width: 1380px)");
    expect(stylesSource).toContain("grid-template-columns: repeat(3, minmax(180px, 1fr))");
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
    expect(stylesSource).toContain(".themeBackgroundPresetButton[data-active=\"true\"]");
    expect(stylesSource).toContain("grid-column: 1 / -1");
    expect(stylesSource).toContain("grid-template-columns: minmax(260px, 0.34fr) minmax(420px, 1fr)");
    expect(stylesSource).toContain(".themeBackgroundImageValue");
    expect(stylesSource).toContain("grid-template-columns: 1fr");
    expect(stylesSource).toContain("grid-template-columns: repeat(auto-fill, minmax(132px, 1fr))");
    expect(stylesSource).toContain("aspect-ratio: 16 / 9");
    expect(stylesSource).toContain(".themeBackgroundPresetButton > em");
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
    expect(stylesSource).toContain("width: 56px");
    expect(stylesSource).toContain("white-space: nowrap");
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
    expect(stylesSource).toContain("grid-template-columns: repeat(2, minmax(220px, 1fr))");
    expect(stylesSource).toContain("grid-template-columns: minmax(210px, 0.4fr) minmax(320px, 0.6fr)");
  });

  it("uses a compact layout for large config sections with many fields", () => {
    expect(routeSource).toContain("function isDenseConfigSection");
    expect(routeSource).toContain('section.id === "llm-discovery"');
    expect(routeSource).toContain("return false");
    expect(routeSource).toContain("Number(section.fieldCount || 0) >= 12");
    expect(routeSource).toContain("styles.configDenseSection");
    expect(routeSource).toContain('section.id === "llm-discovery" ? styles.configDiscoverySection : ""');
    expect(stylesSource).toContain(".configDenseSection > .treeGrid");
    expect(stylesSource).toContain("grid-template-columns: repeat(auto-fit, minmax(186px, 1fr))");
    expect(stylesSource).toContain(".configDenseSection .treeFieldCardView");
    expect(stylesSource).toContain("grid-template-columns: minmax(92px, 0.42fr) minmax(0, 1fr)");
    expect(stylesSource).toContain(".configDenseSection .treeFieldCardEdit");
    expect(stylesSource).toContain(".configDenseSection .treeObjectCell .treeObjectBlock");
    expect(stylesSource).toContain(".configDenseSection .treeObjectCell .treeToggle");
  });

  it("routes Config controls through VUI primitives", () => {
    expect(routeSource).toContain('from "../components/vui"');
    expect(routeSource).toContain("<VButton");
    expect(routeSource).not.toMatch(/<button\b/);
  });
});
