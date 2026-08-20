import { describe, expect, it } from "vitest";

import type { LauncherRegistryReconciliationItem, LauncherStateSnapshotV1 } from "../api/launcher";
import {
  LAUNCHER_REGISTRY_DIAGNOSTIC_CHAR_LIMIT,
  buildLauncherRegistryDiagnosticText,
  buildLauncherRegistryNoticeFacts,
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

function cleanup(overrides: Partial<LauncherStateSnapshotV1["cleanup"]> = {}): LauncherStateSnapshotV1["cleanup"] {
  return {
    reconciliation: { active: false, reason: "" },
    cleanedCount: 0,
    skippedCount: 0,
    failedCount: 0,
    classifications: [],
    portConflicts: [],
    removedInstanceIds: [],
    worktreeDryRun: [],
    orphanCriteria: ["path_detached"],
    ...overrides,
  };
}

describe("launcherRegistryDiagnostics", () => {
  it("summarizes unknown and reclaimable leases without listing worktrees or a kill action", () => {
    const summary = formatUnknownLeaseDiagnostics([
      item(),
      item({ instanceId: "worktree:healthy", classification: "healthy", portLeaseStatus: undefined, reasons: [] }),
    ], "zh", "zh-CN");
    expect(summary).toBe("1 · 可回收");
    expect(summary).not.toContain("worktree:ghost");
    expect(summary).not.toContain("missing_identity");
    expect(summary).not.toContain("worktree:healthy");
    expect(summary).not.toMatch(/kill|taskkill|force-stop/i);
  });

  it("shows only non-default residue facts and omits orphan criteria", () => {
    const facts = buildLauncherRegistryNoticeFacts({
      uiLang: "zh",
      cleanup: cleanup({
        classifications: [
          item({ instanceId: "worktree:a" }),
          item({ instanceId: "worktree:b" }),
          item({ instanceId: "worktree:ok", classification: "healthy", portLeaseStatus: undefined, reasons: [] }),
        ],
        worktreeDryRun: [
          {
            instanceId: "worktree:a",
            projectRoot: "C:/repo",
            branch: "codex/a",
            reason: "dry_run_only",
            action: "dry_run_only",
            dirty: false,
            mergedToMain: false,
            risks: [],
          },
        ],
        orphanCriteria: ["path_detached", "pid_inactive"],
      }),
    });
    expect(facts).toEqual([
      { key: "residue", label: "残留", value: "未知 2" },
      { key: "dry-run", label: "dry-run", value: "1" },
    ]);
    expect(facts.map((fact) => fact.value).join(" ")).not.toContain("worktree:");
    expect(facts.some((fact) => fact.key === "orphan" || /判据/.test(fact.label))).toBe(false);
  });

  it("keeps port conflicts as an explicit fact", () => {
    const facts = buildLauncherRegistryNoticeFacts({
      uiLang: "en",
      cleanup: cleanup({
        portConflicts: [item({ instanceId: "worktree:clash", classification: "conflict", ports: [8011, 5173] })],
        classifications: [item({ instanceId: "worktree:clash", classification: "conflict", ports: [8011, 5173] })],
      }),
    });
    expect(facts).toEqual([
      { key: "residue", label: "Residue", value: "conflict 1" },
      { key: "ports", label: "Port conflicts", value: "worktree:clash:8011/5173" },
    ]);
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
    expect(text).toContain("unknownOrLease=1 · 可回收");
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
