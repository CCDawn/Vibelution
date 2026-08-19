import { describe, expect, it } from "vitest";

import type { LauncherRegistryReconciliationItem } from "../api/launcher";
import {
  LAUNCHER_REGISTRY_DIAGNOSTIC_CHAR_LIMIT,
  buildLauncherRegistryDiagnosticText,
  formatUnknownLeaseDiagnostics,
} from "./launcherRegistryDiagnostics";

function item(overrides: Partial<LauncherRegistryReconciliationItem> = {}): LauncherRegistryReconciliationItem {
  return {
    instanceId: "worktree:ghost",
    classification: "unknown",
    reasons: ["missing_identity"],
    windowOpen: false,
    listener: [],
    ports: [8011],
    portLeaseStatus: "reclaimable",
    firstObservedAt: "2026-08-19T00:00:00.000Z",
    nextReconcileAt: "2026-08-19T00:00:10.000Z",
    ...overrides,
  };
}

describe("launcherRegistryDiagnostics", () => {
  it("summarizes unknown and reclaimable leases without a kill action", () => {
    const summary = formatUnknownLeaseDiagnostics([
      item(),
      item({ instanceId: "worktree:healthy", classification: "healthy", portLeaseStatus: undefined, reasons: [] }),
    ], "zh", "zh-CN");
    expect(summary).toContain("worktree:ghost");
    expect(summary).toContain("reclaimable");
    expect(summary).not.toContain("worktree:healthy");
    expect(summary).not.toMatch(/kill|taskkill|force-stop/i);
  });

  it("copies a bounded diagnostic that keeps identity and lease fields", () => {
    const text = buildLauncherRegistryDiagnosticText({
      snapshot: {
        revision: 9,
        observedAt: "2026-08-19T00:00:00.000Z",
        freshness: "fresh",
        nextReconcileAt: "2026-08-19T00:00:10.000Z",
      },
      items: [item({ reasons: ["missing_identity", "path_missing"] })],
      uiLang: "zh",
    });
    expect(text).toContain("revision=9");
    expect(text).toContain("worktree:ghost");
    expect(text).toContain("class=unknown");
    expect(text).toContain("lease=reclaimable");
    expect(text).toContain("missing_identity");
    expect(text.length).toBeLessThanOrEqual(LAUNCHER_REGISTRY_DIAGNOSTIC_CHAR_LIMIT);
  });

  it("clips oversized diagnostic text and extra rows", () => {
    const items = Array.from({ length: 20 }, (_, index) => item({
      instanceId: `worktree:${"x".repeat(80)}-${index}`,
      reasons: [ "reason".repeat(80) ],
    }));
    const text = buildLauncherRegistryDiagnosticText({
      snapshot: {
        revision: 1,
        observedAt: "2026-08-19T00:00:00.000Z",
        freshness: "stale",
        staleReason: "x".repeat(500),
      },
      items,
      uiLang: "en",
    });
    expect(text.endsWith("…")).toBe(true);
    expect(text.length).toBeLessThanOrEqual(LAUNCHER_REGISTRY_DIAGNOSTIC_CHAR_LIMIT);
    expect(text).toContain("staleReason=");
    expect(text.split("\n").filter((line) => line.includes("class=")).length).toBeLessThanOrEqual(8);
  });
});
