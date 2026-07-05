import { describe, expect, it } from "vitest";

import routeSource from "./PetRoute.tsx?raw";
import styles from "./PetRoute.styles";
import stylesSource from "./PetRoute.styles.ts?raw";

const surfaceKeys = [
  "surfaceClass",
  "heroClass",
  "metricCardClass",
  "cardClass",
] as const;

describe("PetRoute layout contract", () => {
  it("keeps the route root background-aware and CSS-module free", () => {
    expect(styles.pageClass).toContain("h-full");
    expect(styles.pageClass).toContain("overflow-auto");
    expect(styles.pageClass).not.toContain("bg-[var(--surface-page)]");
    expect(styles.pageClass).not.toContain("bg-vui-surface-glass");
    expect(routeSource).not.toContain(".module.css");
    expect(routeSource).toContain('import styles from "./PetRoute.styles"');
  });

  it("keeps PetRoute surfaces lightweight instead of opaque card chrome", () => {
    for (const key of surfaceKeys) {
      expect(styles[key]).toContain("border-vui-border-soft");
      expect(styles[key]).not.toContain("bg-[var(--surface-page)]");
      expect(styles[key]).not.toContain("bg-[var(--surface-panel)]");
      expect(styles[key]).not.toContain("bg-vui-surface-glass");
      expect(styles[key]).not.toContain("shadow-[var(--vui-shadow-hairline)]");
      expect(styles[key]).not.toContain("shadow-[var(--vui-shadow-soft)]");
    }
    expect(styles.surfaceClass).toMatch(/bg-\[color-mix\(in_srgb,var\(--surface-panel\)_\d+%,transparent\)\]/);
  });

  it("keeps progress width on a Tailwind contract variable", () => {
    expect(routeSource).toContain("--pet-progress");
    expect(routeSource).toContain("type PetProgressStyle");
    expect(routeSource).not.toContain("style={{ width:");
    expect(styles.progressFillClass).toContain("w-[var(--pet-progress)]");
  });

  it("keeps compact route-owned surfaces in the style map", () => {
    expect(stylesSource).toContain("const surfaceClass");
    expect(stylesSource).toContain("const avatarPanelClass");
    expect(stylesSource).toContain("const progressTrackClass");
    expect(stylesSource).not.toContain("shadow-");
    expect(styles.metricGridClass).toContain("max-[640px]:grid-cols-1");
    expect(styles.statusGridClass).toContain("max-[640px]:grid-cols-1");
  });

  it("keeps metrics, badges, and narrow layouts from forcing horizontal overflow", () => {
    expect(styles.pageClass).toContain("min-w-0");
    expect(styles.heroClass).toContain("min-w-0");
    expect(styles.metricGridClass).toContain("min-w-0");
    expect(styles.statusGridClass).toContain("min-w-0");
    expect(styles.metricCardClass).toContain("min-w-0");
    expect(styles.cardClass).toContain("min-w-0");
    expect(styles.avatarPanelClass).toContain("max-w-full");
    expect(styles.badgeRowClass).toContain("min-w-0");
    expect(styles.badgeClass).toContain("max-w-full");
    expect(styles.badgeClass).toContain("truncate");
    expect(styles.metricLabelClass).toContain("truncate");
    expect(styles.metricLabelClass).not.toContain("whitespace-nowrap");
  });
});
