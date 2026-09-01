/**
 * ResearchAnomalyInboxPanel tests (R4.3): empty states (no anomalies vs no
 * question selected), severity grouping with critical first, deep-link
 * generation (run-scoped vs question-scoped rows), and fail-closed handling of
 * legacy/malformed payloads.
 *
 * @vitest-environment happy-dom
 */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

import {
  executeHypothesisFirstInboxExtendBudget,
  fetchHypothesisFirstAnomalyInbox,
} from "../../../api/hypothesisFirst";
import type { AnomalyInboxItem, AnomalyInboxResponse } from "../../../api/types/hypothesisFirst";
import {
  anomalyInboxDeepLink,
  anomalyInboxScopeText,
  ResearchAnomalyInboxPanel,
} from "./ResearchAnomalyInboxPanel";

vi.mock("../../../api/hypothesisFirst", () => ({
  fetchHypothesisFirstAnomalyInbox: vi.fn(),
  executeHypothesisFirstInboxExtendBudget: vi.fn(),
}));

vi.mock("../../../i18n/useShellI18n", () => ({
  useShellI18n: () => ({ lang: "zh" }),
}));

const mockedInbox = vi.mocked(fetchHypothesisFirstAnomalyInbox);
const mockedExtend = vi.mocked(executeHypothesisFirstInboxExtendBudget);

function item(patch: Partial<AnomalyInboxItem>): AnomalyInboxItem {
  return {
    kind: "blocked_run",
    scope: {
      teamId: "team-1",
      questionId: "SCI-001",
      runId: "",
      nodeId: "",
      meetingRoundId: "",
    },
    severity: "critical",
    firstSeenAt: "2026-08-28T00:30:00Z",
    lastSeenAt: "2026-08-28T00:30:00Z",
    summary: "collection_run_needs_continue",
    recommendedAction: "reconcile_run",
    evidence: ["problem:collection_run_needs_continue"],
    ...patch,
  };
}

const extendAction = {
  command: "extend_budget" as const,
  params: {
    runId: "run-7",
    nodeId: "hf_hypothesis",
    stageId: "hypothesis",
    stageLimitTokens: 300000,
    suggestedExtensionTokens: 260000,
    newStageTokens: 560000,
    limits: { stageTokens: { hypothesis: 560000 } },
  },
  then: { command: "retry_node" as const, nodeId: "hf_hypothesis" },
  hint: "extend_budget 提高 stageTokens 后对该节点 retry_node，无需人工修数据",
  requiresConfirmation: true as const,
  confirmHint: "将阶段 hypothesis 预算上限从 300,000 提高到 560,000 tokens（+260,000）",
};

function inboxPayload(items: AnomalyInboxItem[]): AnomalyInboxResponse {
  return {
    schemaVersion: 1,
    teamId: "team-1",
    questionId: "SCI-001",
    inbox: {
      schemaVersion: 1,
      ruleId: "anomaly_inbox_rule.v1",
      generatedAt: "2026-08-28T01:00:00Z",
      items,
    },
  };
}

let container: HTMLDivElement;
let root: Root;
let queryClient: QueryClient;

function renderPanel(props: {
  teamId?: string;
  questionId?: string;
  onOpenItem?: (target: { questionId: string; runId: string }) => void;
}) {
  act(() => {
    root.render(
      <QueryClientProvider client={queryClient}>
        <ResearchAnomalyInboxPanel
          teamId={props.teamId ?? "team-1"}
          questionId={props.questionId ?? "SCI-001"}
          lang="zh"
          onOpenItem={props.onOpenItem}
        />
      </QueryClientProvider>,
    );
  });
}

async function flushQueries() {
  // React Query batches notifications on a macro-task boundary; a few real
  // timer rounds settle deterministically.
  for (let index = 0; index < 5; index += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
}

function testId(id: string): Element {
  const found = container.querySelector(`[data-testid="${id}"]`);
  if (!found) throw new Error(`Expected test id: ${id}`);
  return found;
}

describe("ResearchAnomalyInboxPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it("shows the no-anomaly empty state when the question inbox is empty", async () => {
    mockedInbox.mockResolvedValue(inboxPayload([]));
    renderPanel({ questionId: "SCI-001" });
    await flushQueries();

    expect(mockedInbox).toHaveBeenCalledWith("team-1", "SCI-001", expect.objectContaining({}));
    const empty = testId("anomaly-inbox-empty");
    expect(empty.textContent).toContain("无异常");
    expect(empty.textContent).not.toContain("未选择题目");
  });

  it("asks for a question first when none is selected", async () => {
    mockedInbox.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      questionId: "",
      inbox: { schemaVersion: 1, ruleId: "anomaly_inbox_rule.v1", generatedAt: "2026-08-28T01:00:00Z", items: [] },
    });
    renderPanel({ questionId: "" });
    await flushQueries();

    expect(mockedInbox).toHaveBeenCalledWith("team-1", "", expect.objectContaining({}));
    const empty = testId("anomaly-inbox-empty");
    expect(empty.textContent).toContain("未选择题目");
  });

  it("groups mixed severities with critical first and shows count badges", async () => {
    // Deliberately not server-ordered: grouping must still put critical on top.
    const medium = item({
      kind: "review_disagreement_escalation",
      severity: "medium",
      summary: "评审分歧已升级标记（flagged_only），待人工复核",
      recommendedAction: null,
    });
    const high = item({
      kind: "heartbeat_stale",
      severity: "high",
      scope: { teamId: "team-1", questionId: "SCI-001", runId: "", nodeId: "", meetingRoundId: "round-3" },
      summary: "生成心跳超时",
      recommendedAction: "retry_node",
    });
    const critical = item({
      kind: "blocked_run",
      severity: "critical",
      scope: { teamId: "team-1", questionId: "SCI-001", runId: "run-9", nodeId: "", meetingRoundId: "" },
      summary: "collection_run_needs_continue",
      recommendedAction: "reconcile_run",
    });
    mockedInbox.mockResolvedValue(inboxPayload([medium, high, critical]));
    renderPanel({ questionId: "sci-001" });
    await flushQueries();

    // DOM order of the severity groups: critical → high → medium.
    const groupOrder = Array.from(container.querySelectorAll("[data-testid^='anomaly-group-']"))
      .map((group) => group.getAttribute("data-testid"));
    expect(groupOrder).toEqual([
      "anomaly-group-critical",
      "anomaly-group-high",
      "anomaly-group-medium",
    ]);
    expect(testId("anomaly-count-critical").textContent).toContain("1");
    expect(testId("anomaly-count-high").textContent).toContain("1");
    expect(testId("anomaly-count-medium").textContent).toContain("1");

    const criticalGroup = testId("anomaly-group-critical");
    expect(criticalGroup.textContent).toContain("运行阻塞");
    expect(criticalGroup.textContent).toContain("题 SCI-001 · run run-9");
    expect(criticalGroup.textContent).toContain("建议动作：重建运行");

    const highGroup = testId("anomaly-group-high");
    expect(highGroup.textContent).toContain("心跳超时");
    expect(highGroup.textContent).toContain("会议 round-3");
    expect(highGroup.textContent).toContain("建议动作：重试节点");
  });

  it("deep-links run-scoped rows with runId and question-scoped rows without", async () => {
    const runScoped = item({
      scope: { teamId: "team-1", questionId: "SCI-001", runId: "run-9", nodeId: "", meetingRoundId: "" },
    });
    const questionScoped = item({
      kind: "needs_human_gate",
      severity: "high",
      scope: { teamId: "team-1", questionId: "", runId: "", nodeId: "", meetingRoundId: "" },
      summary: "2 处等待人工处理",
      recommendedAction: null,
    });
    mockedInbox.mockResolvedValue(inboxPayload([runScoped, questionScoped]));
    const onOpenItem = vi.fn();
    renderPanel({ questionId: "SCI-001", onOpenItem });
    await flushQueries();

    const links = Array.from(container.querySelectorAll('[data-testid="anomaly-inbox-row-link"]')) as HTMLButtonElement[];
    expect(links).toHaveLength(2);
    await act(async () => {
      links[0].click();
    });
    await act(async () => {
      links[1].click();
    });
    expect(onOpenItem).toHaveBeenNthCalledWith(1, { questionId: "SCI-001", runId: "run-9", nodeId: "" });
    expect(onOpenItem).toHaveBeenNthCalledWith(2, { questionId: "SCI-001", runId: "", nodeId: "" });
  });

  it("renders plain rows when navigation is not wired", async () => {
    mockedInbox.mockResolvedValue(inboxPayload([
      item({ scope: { teamId: "team-1", questionId: "SCI-001", runId: "run-9", nodeId: "", meetingRoundId: "" } }),
    ]));
    renderPanel({ questionId: "SCI-001" });
    await flushQueries();

    expect(container.querySelectorAll('[data-testid="anomaly-inbox-row-plain"]')).toHaveLength(1);
    expect(container.querySelectorAll('[data-testid="anomaly-inbox-row-link"]')).toHaveLength(0);
  });

  it("fails closed on legacy/malformed payloads with a retry surface", async () => {
    // A legacy server without the anomaly fields must never render as success.
    mockedInbox.mockRejectedValue(new Error("Invalid anomaly inbox response"));
    renderPanel({ questionId: "SCI-001" });
    await flushQueries();

    expect(container.textContent).toContain("异常收件箱不可用");
    const retry = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent?.includes("重试"));
    expect(retry).toBeTruthy();
  });

  it("exposes deep-link and scope-text helpers", () => {
    const runScoped = item({
      scope: { teamId: "team-1", questionId: "", runId: "run-7", nodeId: "", meetingRoundId: "" },
    });
    expect(anomalyInboxDeepLink(runScoped, "SCI-002")).toEqual({ questionId: "SCI-002", runId: "run-7", nodeId: "" });
    const nodeScoped = item({
      kind: "retry_budget_exhausted",
      severity: "high",
      scope: { teamId: "team-1", questionId: "SCI-001", runId: "run-7", nodeId: "node-a", meetingRoundId: "" },
      summary: "节点 node-a 的业务重试预算已耗尽",
      recommendedAction: "retry_node",
    });
    expect(anomalyInboxDeepLink(nodeScoped, "")).toEqual({ questionId: "SCI-001", runId: "run-7", nodeId: "node-a" });
    const orphan = item({
      scope: { teamId: "team-1", questionId: "", runId: "", nodeId: "", meetingRoundId: "" },
    });
    expect(anomalyInboxDeepLink(orphan, "")).toBeNull();
    expect(anomalyInboxScopeText(nodeScoped, true)).toBe("题 SCI-001 · run run-7 · node node-a");
    // Scope text only renders what the scope itself carries; the deep-link
    // fallback questionId does not leak into it.
    expect(anomalyInboxScopeText(runScoped, false)).toBe("run run-7");
  });

  it("arms the extend CTA with the amount, then executes only on explicit confirm", async () => {
    const budgetItem = item({
      kind: "budget_exhausted",
      scope: { teamId: "team-1", questionId: "SCI-001", runId: "run-7", nodeId: "hf_hypothesis", meetingRoundId: "" },
      summary: "阶段 hypothesis 预算预检不足",
      action: extendAction,
    });
    mockedInbox.mockResolvedValue(inboxPayload([budgetItem]));
    mockedExtend.mockResolvedValue({ status: "accepted" });
    renderPanel({ questionId: "SCI-001", onOpenItem: vi.fn() });
    await flushQueries();

    // The CTA shows the amount; a deep link would nest buttons, so the row
    // renders plain while the CTA is interactive.
    expect(testId("anomaly-extend-cta").textContent).toContain("+260,000 tokens");
    expect(container.querySelectorAll('[data-testid="anomaly-inbox-row-link"]')).toHaveLength(0);

    // First click only arms the confirmation; nothing executes yet.
    act(() => {
      (testId("anomaly-extend-arm") as HTMLButtonElement).click();
    });
    expect(mockedExtend).not.toHaveBeenCalled();
    expect(testId("anomaly-extend-confirm").textContent).toContain("确认补预算");

    await act(async () => {
      (testId("anomaly-extend-confirm") as HTMLButtonElement).click();
    });
    await flushQueries();
    expect(mockedExtend).toHaveBeenCalledTimes(1);
    expect(mockedExtend).toHaveBeenCalledWith("team-1", {
      questionId: "SCI-001",
      runId: "run-7",
      nodeId: "hf_hypothesis",
      stageId: "hypothesis",
      stageLimitTokens: 300000,
      suggestedExtensionTokens: 260000,
      confirmed: true,
    });
  });

  it("cancels the armed CTA without executing", async () => {
    mockedInbox.mockResolvedValue(inboxPayload([
      item({ kind: "budget_exhausted", action: extendAction }),
    ]));
    mockedExtend.mockResolvedValue({});
    renderPanel({ questionId: "SCI-001" });
    await flushQueries();

    act(() => {
      (testId("anomaly-extend-arm") as HTMLButtonElement).click();
    });
    act(() => {
      (testId("anomaly-extend-cancel") as HTMLButtonElement).click();
    });
    expect(testId("anomaly-extend-arm")).toBeTruthy();
    expect(mockedExtend).not.toHaveBeenCalled();
  });

  it("surfaces the server refusal when execution fails", async () => {
    mockedInbox.mockResolvedValue(inboxPayload([
      item({ kind: "budget_exhausted", action: extendAction }),
    ]));
    mockedExtend.mockRejectedValue(new Error("confirmation_required"));
    renderPanel({ questionId: "SCI-001" });
    await flushQueries();

    act(() => {
      (testId("anomaly-extend-arm") as HTMLButtonElement).click();
    });
    await act(async () => {
      (testId("anomaly-extend-confirm") as HTMLButtonElement).click();
    });
    await flushQueries();
    expect(testId("anomaly-extend-error").textContent).toContain("confirmation_required");
    // Still armed so the operator can retry after fixing the blocker.
    expect(testId("anomaly-extend-confirm")).toBeTruthy();
  });
});
