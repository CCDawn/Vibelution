import { describe, expect, it } from "vitest";

import type { SelfEvolutionTransaction } from "../api/types";
import {
  buildSelfEvolutionTransactionHistoryView,
  buildTransactionBatchLabel,
  buildTransactionDisplayTitle,
  buildTransactionOutcomeLabel,
  deriveSelfEvolutionPetCompanionState,
  filterSelfEvolutionTransactions,
  groupTransactionsByDate,
  pruneSelectedHistoryTxnIds,
  SELF_TRANSACTION_COLLAPSED_LIMIT,
} from "./SelfEvolutionTrack";
import selfEvolutionSource from "./SelfEvolutionTrack.tsx?raw";

function transaction(overrides: Partial<SelfEvolutionTransaction> & { txnId: string }): SelfEvolutionTransaction {
  return {
    txnId: overrides.txnId,
    openedAt: "2026-05-20T08:00:00+08:00",
    closedAt: "2026-05-20T08:05:00+08:00",
    baseRev: "abcdef1234567890",
    baseRevShort: "abcdef1",
    status: "success",
    summary: "",
    isOpen: false,
    goalPreview: "",
    durationSeconds: 300,
    validationPassed: 1,
    validationFailed: 0,
    mutationsRecorded: 0,
    mutationsBlocked: 0,
    auditEventCount: 0,
    lastAuditEvent: "",
    ...overrides,
  };
}

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

  it("uses a structured loading shell instead of a blank loading canvas", () => {
    expect(selfEvolutionSource).toContain("renderLoadingShell");
    expect(selfEvolutionSource).toContain("styles.loadingShell");
    expect(selfEvolutionSource).toContain("styles.loadingStatGrid");
    expect(selfEvolutionSource).toContain("styles.skeletonLineWide");
    expect(selfEvolutionSource).toContain("styles.loadingBody");
    expect(selfEvolutionSource).toContain("现场证据");
  });

  it("uses readable transaction titles instead of making txn ids the primary label", () => {
    expect(selfEvolutionSource).toContain("buildTransactionDisplayTitle");
    expect(selfEvolutionSource).toContain("buildTransactionOutcomeLabel");
    expect(selfEvolutionSource).toContain("styles.transactionTitleStack");
    expect(selfEvolutionSource).toContain("styles.transactionMetaGrid");
    expect(selfEvolutionSource).toContain("styles.transactionGoalPreview");
    expect(selfEvolutionSource).toContain("<strong>{displayTitle}</strong>");
    expect(selfEvolutionSource).toContain("validationLabel");
    expect(selfEvolutionSource).toContain("mutationLabel");
    expect(selfEvolutionSource).toContain("durationLabel");
    expect(selfEvolutionSource).toContain("{compactTimestamp(item.closedAt || item.openedAt)} · {item.txnId}");
    expect(selfEvolutionSource).not.toContain("<strong>{item.txnId}</strong>");
  });

  it("lets users filter self-evolution transaction history before batch operations", () => {
    expect(selfEvolutionSource).toContain("SelfEvolutionTransactionFilter");
    expect(selfEvolutionSource).toContain("filterSelfEvolutionTransactions");
    expect(selfEvolutionSource).toContain("transactionFilterOptions");
    expect(selfEvolutionSource).toContain("styles.transactionFilterBar");
    expect(selfEvolutionSource).toContain("selfTransactionFilterNeedsReview");
    expect(selfEvolutionSource).toContain("selfTransactionFilterChanged");
    expect(selfEvolutionSource).toContain("selfTransactionFilterEmpty");
  });

  it("keeps transaction evidence scannable behind an expandable details panel", () => {
    expect(selfEvolutionSource).toContain("expandedHistoryTxnIds");
    expect(selfEvolutionSource).toContain("toggleTransactionDetails");
    expect(selfEvolutionSource).toContain("styles.transactionDetailsToggle");
    expect(selfEvolutionSource).toContain("styles.transactionDetailsPanel");
    expect(selfEvolutionSource).toContain("aria-expanded={detailsExpanded}");
    expect(selfEvolutionSource).toContain("showDetails");
    expect(selfEvolutionSource).toContain("hideDetails");
  });

  it("groups self-evolution transactions by date with readable batch labels", () => {
    expect(selfEvolutionSource).toContain("SelfEvolutionTransactionDateGroup");
    expect(selfEvolutionSource).toContain("groupTransactionsByDate");
    expect(selfEvolutionSource).toContain("buildTransactionBatchLabel");
    expect(selfEvolutionSource).toContain("visibleTransactionGroups");
    expect(selfEvolutionSource).toContain("styles.transactionDateGroup");
    expect(selfEvolutionSource).toContain("styles.transactionDateHeader");
    expect(selfEvolutionSource).toContain("styles.transactionGroupList");
  });

  it("adds a date filter layer for grouped transaction history", () => {
    expect(selfEvolutionSource).toContain("SelfEvolutionTransactionDateFilter");
    expect(selfEvolutionSource).toContain("filterTransactionsByDate");
    expect(selfEvolutionSource).toContain("transactionDateFilter");
    expect(selfEvolutionSource).toContain("transactionDateOptions");
    expect(selfEvolutionSource).toContain("styles.transactionDateFilterBar");
    expect(selfEvolutionSource).toContain("selfTransactionDateFilterLabel");
    expect(selfEvolutionSource).toContain("selfTransactionDateAll");
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

describe("self-evolution transaction history logic", () => {
  it("filters transactions by review, open, and changed states", () => {
    const items = [
      transaction({ txnId: "ok", validationPassed: 1 }),
      transaction({ txnId: "failed-validation", validationFailed: 1 }),
      transaction({ txnId: "blocked-mutation", mutationsBlocked: 1 }),
      transaction({ txnId: "failed-status", status: "failed" }),
      transaction({ txnId: "running", status: "running", isOpen: true }),
      transaction({ txnId: "changed", mutationsRecorded: 2 }),
    ];

    expect(filterSelfEvolutionTransactions(items, "needs_review").map((item) => item.txnId)).toEqual([
      "failed-validation",
      "blocked-mutation",
      "failed-status",
    ]);
    expect(filterSelfEvolutionTransactions(items, "open").map((item) => item.txnId)).toEqual(["running"]);
    expect(filterSelfEvolutionTransactions(items, "changed").map((item) => item.txnId)).toEqual(["changed"]);
  });

  it("groups transactions by readable dates and counts review items", () => {
    const groups = groupTransactionsByDate([
      transaction({ txnId: "morning", closedAt: "2026-05-20T08:05:00+08:00" }),
      transaction({ txnId: "review", closedAt: "2026-05-20T09:05:00+08:00", validationFailed: 1 }),
      transaction({ txnId: "next-day", closedAt: "2026-05-21T09:05:00+08:00" }),
      transaction({ txnId: "undated", openedAt: "", closedAt: "" }),
    ], "zh");

    expect(groups.map((group) => [group.key, group.label, group.count, group.needsReviewCount])).toEqual([
      ["2026-05-20", "2026年05月20日", 2, 1],
      ["2026-05-21", "2026年05月21日", 1, 0],
      ["unknown", "未记录日期", 1, 0],
    ]);
  });

  it("collapses long transaction days without losing the total count", () => {
    const items = Array.from({ length: SELF_TRANSACTION_COLLAPSED_LIMIT + 3 }, (_, index) =>
      transaction({
        txnId: `txn-${index}`,
        closedAt: `2026-05-20T${String(index).padStart(2, "0")}:05:00+08:00`,
      }),
    );

    const collapsed = buildSelfEvolutionTransactionHistoryView({
      items,
      filter: "all",
      dateFilter: "2026-05-20",
      lang: "zh",
      expanded: false,
    });
    const expanded = buildSelfEvolutionTransactionHistoryView({
      items,
      filter: "all",
      dateFilter: "2026-05-20",
      lang: "zh",
      expanded: true,
    });

    expect(collapsed.dateFilteredTransactions).toHaveLength(SELF_TRANSACTION_COLLAPSED_LIMIT + 3);
    expect(collapsed.visibleTransactions).toHaveLength(SELF_TRANSACTION_COLLAPSED_LIMIT);
    expect(collapsed.hiddenTransactionCount).toBe(3);
    expect(collapsed.visibleTransactionGroups[0]).toMatchObject({
      key: "2026-05-20",
      count: SELF_TRANSACTION_COLLAPSED_LIMIT,
    });
    expect(expanded.visibleTransactions).toHaveLength(SELF_TRANSACTION_COLLAPSED_LIMIT + 3);
    expect(expanded.hiddenTransactionCount).toBe(0);
  });

  it("builds readable transaction labels before falling back to ids", () => {
    const summarized = transaction({
      txnId: "txn-summary",
      summary: "A".repeat(80),
    });
    const untitled = transaction({
      txnId: "txn-untitled",
      summary: "",
      closedAt: "2026-05-20T10:15:00+08:00",
    });

    expect(buildTransactionDisplayTitle(summarized, {
      closedLabel: "已收口事务",
      openLabel: "进行中事务",
    })).toHaveLength(75);
    expect(buildTransactionDisplayTitle(untitled, {
      closedLabel: "已收口事务",
      openLabel: "进行中事务",
    })).toBe("已收口事务 · 2026-05-20 10:15:00");
    expect(buildTransactionOutcomeLabel(transaction({ txnId: "needs-review", validationFailed: 1 }), "zh")).toBe("需复盘");
    expect(buildTransactionOutcomeLabel(transaction({ txnId: "failed-status", status: "failed", validationPassed: 1 }), "zh")).toBe("需复盘");
    expect(buildTransactionOutcomeLabel(transaction({ txnId: "error-status", status: "error" }), "en")).toBe("Needs review");
    expect(buildTransactionBatchLabel(untitled, "zh")).toBe("批次 10:15");
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
