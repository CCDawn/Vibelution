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
  parseObservationDurationInput,
  pruneSelectedHistoryTxnIds,
  SELF_TRANSACTION_COLLAPSED_LIMIT,
} from "./SelfEvolutionTrack";
import selfEvolutionSource from "./SelfEvolutionTrack.tsx?raw";
import selfEvolutionStylesSource from "./SelfEvolutionTrack.styles.ts?raw";

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
  const observationStatusStart = selfEvolutionSource.indexOf("function renderObservationStatusSurface()");
  const observationStatusEnd = selfEvolutionSource.indexOf("\n\n  return (", observationStatusStart);
  const observationStatusSurface = observationStatusStart >= 0 && observationStatusEnd > observationStatusStart
    ? selfEvolutionSource.slice(observationStatusStart, observationStatusEnd)
    : "";
  const observationEvidenceStart = selfEvolutionSource.indexOf("function renderObservationEvidenceRail()");
  const observationEvidenceEnd = selfEvolutionSource.indexOf("\n  return (", observationEvidenceStart);
  const observationEvidenceSurface = observationEvidenceStart >= 0 && observationEvidenceEnd > observationEvidenceStart
    ? selfEvolutionSource.slice(observationEvidenceStart, observationEvidenceEnd)
    : "";
  const workspaceStart = selfEvolutionSource.indexOf('{activePage === "workspace" ? (');
  const workspaceEnd = selfEvolutionSource.indexOf(") : observationRunModeActive ? (", workspaceStart);
  const workspaceSurface = workspaceStart >= 0 && workspaceEnd > workspaceStart
    ? selfEvolutionSource.slice(workspaceStart, workspaceEnd)
    : "";
  const statusPageStart = selfEvolutionSource.indexOf('<div className={styles.statusPage}>');
  const statusPageSurface = statusPageStart >= 0
    ? selfEvolutionSource.slice(statusPageStart)
    : "";

  it("routes self-evolution controls through VUI primitives", () => {
    expect(selfEvolutionSource).toContain('from "../components/vui"');
    expect(selfEvolutionSource).toContain("<VButton");
    expect(selfEvolutionSource).toContain("<VNativeInput");
    expect(selfEvolutionSource).not.toMatch(/<button\b/);
    expect(selfEvolutionSource).not.toMatch(/<input\b/);
    expect(selfEvolutionSource).not.toMatch(/<select\b/);
    expect(selfEvolutionSource).not.toMatch(/<textarea\b/);
  });

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

  it("propagates full-height constraints from the parent route into the conversation workspace", () => {
    expect(selfEvolutionStylesSource).toContain("pageStack:");
    expect(selfEvolutionStylesSource).toContain("workspaceLayout:");
    expect(selfEvolutionStylesSource).toContain("conversationShell:");
    expect(selfEvolutionStylesSource).toContain("centerColumnObservation:");
    expect(selfEvolutionStylesSource).toContain("max-h-full");
    expect(selfEvolutionStylesSource).toContain("grid-rows-[auto_minmax(0,1fr)]");
    expect(selfEvolutionStylesSource).toContain("grid-rows-[minmax(0,1fr)]");
  });

  it("surfaces the active run controls before the workspace columns", () => {
    expect(selfEvolutionSource).toContain("styles.runActionBar");
    expect(selfEvolutionSource).toContain("styles.runActionCluster");
    expect(selfEvolutionSource).toContain("showTopTerminateAction");
    expect(selfEvolutionSource).toContain("styles.dangerAction");
    expect(selfEvolutionSource).toContain("styles.primaryAction");
    expect(selfEvolutionSource).toContain('onWorktreeAction(worktreeRun.runId, "terminate")');
    expect(selfEvolutionSource).toContain("onTerminateObservation(observationRun.runId)");
    expect(selfEvolutionSource).toContain("showComposer={!runIsActive && !worktreeRunLocked && !runLocked}");
  });

  it("loads the heavy conversation renderer through the shared lazy bridge", () => {
    expect(selfEvolutionSource).toContain("LazyConversationView");
    expect(selfEvolutionSource).toContain("fallback={<div className={styles.loadingShell}>{t(\"loadingSession\")}</div>}");
    expect(selfEvolutionSource).not.toContain('import { ConversationView } from "../components/conversation/ConversationView"');
  });

  it("uses a structured loading shell instead of a blank loading canvas", () => {
    expect(selfEvolutionSource).toContain("renderLoadingShell");
    expect(selfEvolutionSource).toContain("styles.loadingShell");
    expect(selfEvolutionSource).toContain("styles.loadingStatGrid");
    expect(selfEvolutionSource).toContain("styles.skeletonLineWide");
    expect(selfEvolutionSource).toContain("styles.loadingBody");
    expect(selfEvolutionSource).toContain("现场证据");
  });

  it("keeps the loading shell compact while self-evolution data synchronizes", () => {
    expect(selfEvolutionStylesSource).toContain("loadingShell:");
    expect(selfEvolutionStylesSource).toContain("min-h-[148px]");
    expect(selfEvolutionStylesSource).toContain("max-h-[180px]");
    expect(selfEvolutionStylesSource).toContain("self-start");
    expect(selfEvolutionStylesSource).toContain("grid-cols-3");
    expect(selfEvolutionStylesSource).toContain("max-[1180px]:min-h-[172px]");
    expect(selfEvolutionStylesSource).toContain("max-[1180px]:max-h-[210px]");
    expect(selfEvolutionStylesSource).not.toContain("min-height: min(520px, 72vh)");
    expect(selfEvolutionStylesSource).not.toContain("min-height: 360px");
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

  it("uses the two-stage self-evolution worktree flow instead of legacy live-run controls", () => {
    expect(selfEvolutionSource).toContain("SELF_EVOLUTION_WORKFLOW_STEPS");
    expect(selfEvolutionSource).toContain('{ id: "self_evolution", zh: "自进化", en: "Self-evolution" }');
    expect(selfEvolutionSource).toContain('{ id: "approval", zh: "审批", en: "Approval" }');
    expect(selfEvolutionSource).toContain("worktreeRun?: SupervisedWorktreeRun | null");
    expect(selfEvolutionSource).toContain("selectedWorkflowStepId");
    expect(selfEvolutionSource).toContain("selectedWorkflowStep?.conversationMessages");
    expect(selfEvolutionSource).toContain("approvalEvidenceItems");
    expect(selfEvolutionSource).toContain("onWorktreeAction");
    expect(selfEvolutionSource).not.toContain("SelfEvolutionActiveRun");
    expect(selfEvolutionSource).not.toContain("onPauseRun");
    expect(selfEvolutionSource).not.toContain("onResumeRun");
    expect(selfEvolutionSource).not.toContain("onRollbackRun");
    expect(selfEvolutionSource).not.toContain("onHandoffRun");
  });

  it("offers isolated development and pure observation modes", () => {
    expect(selfEvolutionSource).toContain('type SelfEvolutionMode = "isolated_development" | "observation"');
    expect(selfEvolutionSource).toContain('value="isolated_development"');
    expect(selfEvolutionSource).toContain('value="observation"');
    expect(selfEvolutionSource).toContain("自主观察");
    expect(selfEvolutionSource).toContain("隔离开发");
  });

  it("keeps observation mode free of tool and merge actions", () => {
    expect(selfEvolutionSource).toContain("observationRun");
    expect(selfEvolutionSource).toContain("renderObservationStatusSurface()");
    expect(selfEvolutionSource).toContain("OBSERVATION_MODE_TOOL_COUNT");
    expect(selfEvolutionSource).toContain("OBSERVATION_MODE_WORKTREE_STATE");
    expect(selfEvolutionSource).toContain('const OBSERVATION_MODE_TOOL_COUNT = "0";');
    expect(selfEvolutionSource).toContain('const OBSERVATION_MODE_WORKTREE_STATE = "no";');
    expect(selfEvolutionSource).toContain("onStartObservation");
    expect(selfEvolutionSource).toContain("onTerminateObservation");
    expect(selfEvolutionSource).not.toContain("onRequestObservationTool");
    expect(selfEvolutionSource).not.toContain("observationToolRequest");
    expect(selfEvolutionSource).not.toContain("allowedTools.length");
    expect(selfEvolutionSource).not.toContain("worktreeCreated");
  });

  it("renders the pure observation session through the shared conversation view", () => {
    expect(selfEvolutionSource).toContain("observationConversationSessionId");
    expect(selfEvolutionSource).toContain("observationConversationReady");
    expect(selfEvolutionSource).toContain("sessionId={observationConversationSessionId}");
    expect(selfEvolutionSource).toContain("renderObservationSetupPanel()");
    expect(selfEvolutionSource).not.toContain("{renderObservationPanel()}");
  });

  it("loads real observation session detail instead of rendering only snapshot text", () => {
    expect(selfEvolutionSource).toContain("SessionDetail");
    expect(selfEvolutionSource).toContain("observationSessionDetailQuery");
    expect(selfEvolutionSource).toContain("queryKeys.session(observationConversationSessionId || \"__none__\")");
    expect(selfEvolutionSource).toContain("fetchJson<SessionDetail>(`/api/sessions/${encodeURIComponent(observationConversationSessionId)}`)");
    expect(selfEvolutionSource).toContain("observationSessionMessages");
    expect(selfEvolutionSource).toContain("messages={observationSessionMessages}");
    expect(selfEvolutionSource).not.toContain("messages={observationConversationMessages}");
  });

  it("uses the observation workspace to fill the main area with conversation and evidence", () => {
    expect(selfEvolutionSource).toContain("styles.observationWorkspace");
    expect(selfEvolutionSource).toContain("styles.centerColumnObservation");
    expect(selfEvolutionSource).toContain("styles.observationConversationPane");
    expect(selfEvolutionSource).toContain("styles.observationEvidenceRail");
    expect(selfEvolutionSource).toContain("styles.observationEventTimeline");
    expect(selfEvolutionSource).toContain("observationEventTail.map");
    expect(selfEvolutionSource).toContain("selfObservationEventTitle(event.event, lang)");
    expect(selfEvolutionSource).not.toContain("event.message || event.event");
    expect(selfEvolutionStylesSource).toContain("observationWorkspace:");
    expect(selfEvolutionStylesSource).toContain("grid-cols-[minmax(0,1fr)_minmax(280px,360px)]");
    expect(selfEvolutionStylesSource).toContain("observationEvidenceRail:");
  });

  it("renders self-evolution Agent cards that deep-link to config and activity logs", () => {
    expect(selfEvolutionSource).toContain("AgentConfigWorkspace");
    expect(selfEvolutionSource).toContain("AgentConfigWorkspaceAgent");
    expect(selfEvolutionSource).toContain("queryKeys.agentConfigWorkspace()");
    expect(selfEvolutionSource).toContain('fetchJson<AgentConfigWorkspace>("/api/agents/config-workspace?includeRuntime=false")');
    expect(selfEvolutionSource).toContain("SELF_EVOLUTION_AGENT_ROLE_ORDER");
    expect(selfEvolutionSource).toContain("renderSelfEvolutionAgentCards()");
    expect(selfEvolutionSource).toContain('returnLabel: "self_evolution"');
    expect(selfEvolutionSource).toContain('pane: "config"');
    expect(selfEvolutionSource).toContain('pane: "activity"');
    expect(selfEvolutionStylesSource).toContain("agentCardList:");
    expect(selfEvolutionStylesSource).toContain("agentCardAction:");
  });

  it("keeps observation side rails compact and leaves full transcripts in the conversation view", () => {
    expect(selfEvolutionSource).toContain("compactObservationPreview");
    expect(observationEvidenceSurface).toContain("compactObservationPreview(event.message, 120)");
    expect(observationEvidenceSurface).toContain("compactObservationPreview(observationRun?.latestMessage, 140)");
    expect(observationEvidenceSurface).not.toContain("<strong>{event.message || event.event}</strong>");
    expect(observationEvidenceSurface).not.toContain("<p className={styles.previewText}>{observationRun.latestMessage}</p>");
    expect(observationEvidenceSurface).not.toContain("<pre className={styles.rawBlock}>{observationRun.report}</pre>");
    expect(selfEvolutionStylesSource).toContain("compactPreviewText:");
    expect(selfEvolutionStylesSource).toContain("line-clamp-2");
  });

  it("keeps the observation status surface isolated from worktree approval semantics", () => {
    expect(observationStatusSurface).toContain("OBSERVATION_MODE_TOOL_COUNT");
    expect(observationStatusSurface).toContain("OBSERVATION_MODE_WORKTREE_STATE");
    expect(observationStatusSurface).toContain("statusLabel(observationRun?.status || \"idle\")");
    expect(observationStatusSurface).toContain("observationRun?.goal || \"--\"");
    expect(observationStatusSurface).toContain("observationRun?.durationSeconds != null");
    expect(observationStatusSurface).toContain("observationRun?.latestMessage");
    expect(observationStatusSurface).not.toContain("renderObservationPanel(");
    expect(observationStatusSurface).not.toContain("overview.worktree");
    expect(observationStatusSurface).not.toContain("worktreeRun");
    expect(observationStatusSurface).not.toContain("approvalEvidenceItems");
    expect(observationStatusSurface).not.toContain("approve_review");
    expect(observationStatusSurface).not.toContain("merge");
    expect(observationStatusSurface).not.toContain("discard");
    expect(observationStatusSurface).not.toContain("tool request");
    expect(observationStatusSurface).not.toContain('onWorktreeAction(worktreeRun.runId, "merge")');
    expect(observationStatusSurface).not.toContain('onWorktreeAction(worktreeRun.runId, "discard")');
    expect(observationStatusSurface).not.toContain("dirtyFlags");
    expect(observationStatusSurface).not.toContain("changedFiles");
    expect(observationStatusSurface).not.toContain("terminateAction");
  });

  it("keeps the pet companion read-only inside self-evolution", () => {
    expect(selfEvolutionSource).toContain("deriveSelfEvolutionPetCompanionState");
    expect(selfEvolutionSource).toContain("petSelfCompanion");
    expect(selfEvolutionSource).toContain("petCompanionSurface");
    expect(selfEvolutionSource).toContain('fetchJson<PetSummary>("/api/pet/summary")');
    expect(selfEvolutionSource).not.toContain("/api/pet/actions");
  });

  it("keeps pet metrics out of the workspace first screen and moves them to status", () => {
    expect(workspaceSurface).toContain("petCompanionSurface");
    expect(workspaceSurface).not.toContain("petVitals.map");
    expect(workspaceSurface).not.toContain("styles.compactMetricGrid");
    expect(statusPageSurface).toContain("petVitals.map");
    expect(statusPageSurface).toContain("t(\"petSpace\")");
  });
});

describe("self-observation duration input", () => {
  it("allows draft edits while parsing only bounded numeric durations for submission", () => {
    expect(parseObservationDurationInput("")).toMatchObject({
      durationSeconds: 300,
      isValid: false,
    });
    expect(parseObservationDurationInput(" 45 ")).toMatchObject({
      durationSeconds: 45,
      isValid: true,
    });
    expect(parseObservationDurationInput("12")).toMatchObject({
      durationSeconds: 30,
      isValid: false,
    });
    expect(parseObservationDurationInput("7200")).toMatchObject({
      durationSeconds: 3600,
      isValid: false,
    });
    expect(parseObservationDurationInput("abc")).toMatchObject({
      durationSeconds: 300,
      isValid: false,
    });
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
