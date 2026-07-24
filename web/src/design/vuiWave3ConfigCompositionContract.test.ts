/**
 * Wave 3B-alt composition contract — Config settings workbench.
 *
 * Config keeps its settings-nav + main shell (not a single-column-only page).
 * Composition means:
 * - layout root recipe marker
 * - nav / main / body regions
 * - main column uses VSettingsFormPage (settings-form-page recipe)
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const routesRoot = resolve(import.meta.dirname, "../routes");
const layoutRoot = resolve(import.meta.dirname, "../components/vui/layout");

describe("Wave 3B-alt Config settings workbench composition", () => {
  it("marks Config as the settings workbench domain recipe", () => {
    const routeSource = readFileSync(resolve(routesRoot, "ConfigRoute.tsx"), "utf8");
    expect(routeSource).toContain('data-vui-recipe="config-settings-workbench"');
    expect(routeSource).toContain('data-vui-region="config-settings-main"');
    expect(routeSource).toContain('data-vui-region="config-settings-body"');
    expect(routeSource).toContain("VSettingsFormPage");
  });

  it("marks the settings nav region on the sidebar", () => {
    const navSource = readFileSync(resolve(routesRoot, "ConfigSettingsNavigation.tsx"), "utf8");
    expect(navSource).toContain('data-vui-region="config-settings-nav"');
  });

  it("keeps VSettingsFormPage as the generic settings-form-page recipe", () => {
    const pageSource = readFileSync(resolve(layoutRoot, "VSettingsFormPage.tsx"), "utf8");
    expect(pageSource).toContain('data-vui-recipe="settings-form-page"');
    expect(pageSource).toContain('data-vui="settings-form-header"');
    expect(pageSource).toContain('data-vui="settings-form-toolbar"');
    expect(pageSource).toContain('data-vui="settings-form-body"');
    expect(pageSource).toContain('data-vui="settings-form-footer"');
  });
});
