import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import routeSource from "./ConfigRoute.tsx?raw";

const stylesSource = readFileSync(new URL("./ConfigRoute.module.css", import.meta.url), "utf-8");

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

  it("shows developer mode as launcher-owned read-only state", () => {
    expect(routeSource).toContain("developerModeReadonly");
    expect(routeSource).toContain("developerModeControlled");
    expect(routeSource).toContain("developerModeConfig.enabled");
    expect(routeSource).toContain("aria-label={copy.developerModeReadonly}");
    expect(routeSource).toContain("Launcher 控制");
    expect(routeSource).not.toContain("updateLauncherDeveloperMode");
    expect(routeSource).not.toContain("developer-mode/cleanup");
  });
});
