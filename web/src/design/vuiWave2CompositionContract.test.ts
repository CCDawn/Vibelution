/**
 * Wave 2D composition contract: demo paths must use recipes for structure
 * and fixed state recipes for selection — no inline structure washes.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import {
  extractColorMixCalls,
  scanSourceForVuiSurfaceAlpha,
} from "./vuiSurfaceAlphaPolicy";
import agentsStyles from "../routes/AgentsRoute.styles";
import sessionStyles from "../routes/DirectSessionIndexItem.styles";

const designRoot = resolve(import.meta.dirname);

describe("Wave 2D composition demo paths", () => {
  it("Agents list row keys use dense/state recipes without structure wash", () => {
    expect(agentsStyles.agentRow).toContain("!bg-[var(--vui-surface-row)]");
    expect(agentsStyles.agentRow).toContain("hover:bg-[var(--vui-surface-row-hover)]");
    expect(agentsStyles.agentRowActive).toContain(
      "bg-[color-mix(in_srgb,var(--accent-warm)_9%,var(--vui-surface-row))]",
    );
    expect(agentsStyles.agentRowBulkSelected).toContain(
      "bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))]",
    );

    for (const key of ["agentRow", "agentRowActive", "agentRowBulkSelected"] as const) {
      const value = agentsStyles[key];
      const hits = scanSourceForVuiSurfaceAlpha(value, "routes/AgentsRoute.styles.ts");
      const forbidden = hits.filter((h) => !h.allowed);
      expect(forbidden, `${key}: ${forbidden.map((h) => h.mix).join("; ")}`).toEqual([]);
    }
  });

  it("Chat direct session index item uses dense row + selected state recipe", () => {
    expect(sessionStyles.sessionItem).toContain("!bg-[var(--vui-surface-row)]");
    expect(sessionStyles.sessionItemActive).toContain(
      "bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))]",
    );
    expect(sessionStyles.sessionItemActive).toContain("text-[var(--accent-cool)]");

    const hits = scanSourceForVuiSurfaceAlpha(
      `${sessionStyles.sessionItem} ${sessionStyles.sessionItemActive}`,
      "routes/DirectSessionIndexItem.styles.ts",
    );
    expect(hits.filter((h) => !h.allowed)).toEqual([]);
  });

  it("state recipes remain the sole literal home for selected cool 10% wash definition", () => {
    const recipes = readFileSync(resolve(designRoot, "vuiSurfaceRecipes.ts"), "utf8");
    expect(recipes).toContain("export const vuiStateSelectedRowClass");
    expect(recipes).toContain("export const vuiStateSelectedRowFillClass");
    expect(recipes).toContain("export const vuiStateSelectedWarmRowClass");
    const mixes = extractColorMixCalls(recipes).filter((m) =>
      m.includes("accent-cool") && m.includes("vui-surface-row"),
    );
    expect(mixes.length).toBeGreaterThan(0);
  });
});
