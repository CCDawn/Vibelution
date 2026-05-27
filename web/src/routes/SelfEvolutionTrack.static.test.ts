import { describe, expect, it } from "vitest";

import { pruneSelectedHistoryTxnIds } from "./SelfEvolutionTrack";
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
