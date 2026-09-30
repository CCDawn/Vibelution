import { describe, expect, it } from "vitest";

import { isShellPrimaryNavActive } from "./AppShell";
import appShellSource from "./AppShell.tsx?raw";
import settingsMenuSource from "./AppShellSettingsMenu.tsx?raw";
import paletteSource from "./GlobalCommandSurfaces.tsx?raw";

/** P2 nav collapse (approved): the six top-level entries in their fixed order. */
const PRIMARY_NAV_ORDER = ["/chat", "/companions", "/teams", "/evolution/workspace", "/memory", "/agents"];

describe("AppShell primary nav collapse (P2: 8 -> 6 entries)", () => {
  it("renders the six primary entries in the approved order", () => {
    let cursor = -1;
    for (const to of PRIMARY_NAV_ORDER) {
      const found = appShellSource.indexOf(`to="${to}"`, cursor + 1);
      expect(found, `nav entry ${to} order`).toBeGreaterThan(cursor);
      cursor = found;
    }
  });

  it("keeps each primary entry reachable from both the desktop nav and the gear-menu mobile nav", () => {
    for (const to of PRIMARY_NAV_ORDER) {
      const occurrences = appShellSource.split(`to="${to}"`).length - 1;
      expect(occurrences, `nav entry ${to} occurrences`).toBe(2);
    }
  });

  it("retires the supervised/self-evolution and kernel top-level entries", () => {
    expect(appShellSource).not.toContain('to="/supervised-evolution"');
    expect(appShellSource).not.toContain('to="/self-evolution"');
    expect(appShellSource).not.toContain('to="/kernel"');
    // Kernel survives as a settings-gear entry instead of disappearing.
    expect(settingsMenuSource).toContain('to="/kernel"');
    expect(settingsMenuSource).toContain("<Cpu size={16} />");
  });

  it("gates the aggregated Evolution entry on either evolution mode flag", () => {
    expect(appShellSource).toContain("supervisedEvolutionEnabled || selfEvolutionEnabled");
    expect(appShellSource).toContain('t("navEvolution")');
  });

  it("keeps the legacy supervised/self deep links active under the Evolution entry", () => {
    expect(isShellPrimaryNavActive("/evolution/workspace", "/evolution/workspace")).toBe(true);
    expect(isShellPrimaryNavActive("/supervised-evolution", "/evolution/workspace")).toBe(true);
    expect(isShellPrimaryNavActive("/supervised-evolution/library", "/evolution/workspace")).toBe(true);
    expect(isShellPrimaryNavActive("/self-evolution", "/evolution/workspace")).toBe(true);
    expect(isShellPrimaryNavActive("/teams", "/evolution/workspace")).toBe(false);
    expect(isShellPrimaryNavActive("/chat", "/evolution/workspace")).toBe(false);
  });

  it("collapses the command palette navigation to the same six surfaces", () => {
    expect(paletteSource).toContain('to: "/evolution/workspace"');
    expect(paletteSource).not.toContain('to: "/supervised-evolution"');
    expect(paletteSource).not.toContain('to: "/self-evolution"');
    expect(paletteSource).toContain('t("navEvolution")');
    // Palette order mirrors the primary nav order (Kernel stays palette-only).
    let cursor = -1;
    for (const to of ["/chat", "/companions", "/teams", "/evolution/workspace", "/memory", "/agents"]) {
      const found = paletteSource.indexOf(`to: "${to}"`, cursor + 1);
      expect(found, `palette entry ${to} order`).toBeGreaterThan(cursor);
      cursor = found;
    }
  });
});
