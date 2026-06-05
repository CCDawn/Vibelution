import { describe, expect, it } from "vitest";

import { deriveSelfEvolutionPetCompanionState, pruneSelectedHistoryTxnIds } from "./SelfEvolutionTrack";
import selfEvolutionSource from "./SelfEvolutionTrack.tsx?raw";

describe("SelfEvolutionTrack static assets", () => {
  it("does not use remote placeholder images that pollute runtime scene logs", () => {
    expect(selfEvolutionSource).not.toContain("http://");
    expect(selfEvolutionSource).not.toContain("https://");
    expect(selfEvolutionSource).not.toContain("<img");
  });

  it("keeps the workspace side column collapsible from the centered divider", () => {
    expect(selfEvolutionSource).toContain("PaneCollapseHandle");
    expect(selfEvolutionSource).toContain("sidebarCollapsed");
    expect(selfEvolutionSource).toContain("setSidebarCollapsed");
    expect(selfEvolutionSource).toContain("--self-sidebar-width");
  });

  it("uses the compact workbench conversation density on the self-evolution workspace", () => {
    expect(selfEvolutionSource).toContain('density="compact"');
  });

  it("shows a supervised worktree escalation action for risky write start errors", () => {
    expect(selfEvolutionSource).toContain("isWorktreeIsolationStartError");
    expect(selfEvolutionSource).toContain("worktreeIsolationStartError");
    expect(selfEvolutionSource).toContain("selfWorktreeEscalationHint");
    expect(selfEvolutionSource).toContain("startSelfWorktreeRun");
    expect(selfEvolutionSource).toContain("onStartWorktreeRun");
  });

  it("keeps the pet companion read-only inside self-evolution", () => {
    expect(selfEvolutionSource).toContain("deriveSelfEvolutionPetCompanionState");
    expect(selfEvolutionSource).toContain("petSelfCompanion");
    expect(selfEvolutionSource).toContain("petCompanionSurface");
    expect(selfEvolutionSource).toContain('fetchJson<PetSummary>("/api/pet/summary")');
    expect(selfEvolutionSource).not.toContain("/api/pet/actions");
  });
});

describe("self-evolution history selection pruning", () => {
  it("keeps the same selection reference when every selected history group is still visible", () => {
    const selected = ["txn-1", "txn-2"];

    expect(pruneSelectedHistoryTxnIds(selected, ["txn-1", "txn-2", "txn-3"])).toBe(selected);
  });

  it("drops hidden history groups when the visible transaction set changes", () => {
    const selected = ["txn-1", "txn-old", "txn-2"];

    expect(pruneSelectedHistoryTxnIds(selected, ["txn-1", "txn-2"])).toEqual(["txn-1", "txn-2"]);
  });
});

describe("self-evolution pet companion state", () => {
  it("turns active self-evolution runs into read-only companion copy", () => {
    expect(deriveSelfEvolutionPetCompanionState({ runStatus: "queued" })).toMatchObject({
      tone: "active",
      stateKey: "petSelfCompanionQueued",
    });
    expect(deriveSelfEvolutionPetCompanionState({ runStatus: "running" })).toMatchObject({
      tone: "active",
      stateKey: "petSelfCompanionRunning",
    });
  });

  it("prioritizes safety boundaries over ordinary run status", () => {
    expect(deriveSelfEvolutionPetCompanionState({
      runStatus: "running",
      worktreeIsolationStartError: true,
    })).toMatchObject({
      tone: "caution",
      stateKey: "petSelfCompanionWorktree",
    });
    expect(deriveSelfEvolutionPetCompanionState({
      runStatus: "running",
      petLoadFailed: true,
    })).toMatchObject({
      tone: "error",
      stateKey: "petSelfCompanionError",
    });
  });
});
