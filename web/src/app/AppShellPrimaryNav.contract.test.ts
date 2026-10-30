import { describe, expect, it } from "vitest";

import { isShellPrimaryNavActive } from "./AppShell";
import appShellSource from "./AppShell.tsx?raw";
import menuSource from "./SpecialistAgentMenu.tsx?raw";
import settingsMenuSource from "./AppShellSettingsMenu.tsx?raw";
import paletteSource from "./GlobalCommandSurfaces.tsx?raw";

/** Top bar stays six slots. The companions slot is the specialist menu. */
const PRIMARY_NAV_SLOTS = [
  'to="/chat"',
  "<SpecialistAgentMenu",
  'to="/teams"',
  'to="/evolution/workspace"',
  'to="/memory"',
  'to="/agents"',
];

describe("AppShell primary nav collapse (P2: 8 -> 6 entries)", () => {
  it("renders the six primary entries in the approved order", () => {
    let cursor = -1;
    for (const token of [...PRIMARY_NAV_SLOTS, ...PRIMARY_NAV_SLOTS]) {
      const found = appShellSource.indexOf(token, cursor + 1);
      expect(found, `nav entry ${token} order`).toBeGreaterThan(cursor);
      cursor = found;
    }
    const finance = menuSource.indexOf('"/finance"');
    const companions = menuSource.indexOf('"/companions"');
    expect(finance).toBeGreaterThan(-1);
    expect(companions).toBeGreaterThan(finance);
  });

  it("keeps each primary entry reachable from both the desktop nav and the gear-menu mobile nav", () => {
    expect(appShellSource.split("<SpecialistAgentMenu").length - 1).toBe(2);
    for (const token of PRIMARY_NAV_SLOTS.filter((item) => item.startsWith("to="))) {
      const occurrences = appShellSource.split(token).length - 1;
      expect(occurrences, `nav entry ${token} occurrences`).toBe(2);
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

  it("keeps palette order with finance beside companions", () => {
    expect(paletteSource).toContain('to: "/evolution/workspace"');
    expect(paletteSource).not.toContain('to: "/supervised-evolution"');
    expect(paletteSource).not.toContain('to: "/self-evolution"');
    expect(paletteSource).toContain('t("navEvolution")');
    // Palette order mirrors the primary nav order (Kernel stays palette-only).
    let cursor = -1;
    for (const to of ["/chat", "/finance", "/companions", "/teams", "/evolution/workspace", "/memory", "/agents"]) {
      const found = paletteSource.indexOf(`to: "${to}"`, cursor + 1);
      expect(found, `palette entry ${to} order`).toBeGreaterThan(cursor);
      cursor = found;
    }
  });
});
