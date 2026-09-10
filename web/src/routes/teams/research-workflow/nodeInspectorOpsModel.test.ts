import { describe, expect, it } from "vitest";

import type { CommandOffer } from "../../../api/types/research-workflow/commands";
import type { ResearchBudgetLedgerSnapshot } from "../../../api/types/researchWorkflow";
import {
  agentDisplayInitial,
  budgetMeterPercent,
  commandOfferIdentity,
  isUnknownOutcomeCommandError,
  ledgerForStage,
  mergeNodeOverrideLayer,
  nodeInspectorBudgetMeters,
  nodeInspectorStatus,
  pickPrimaryCommandOffer,
  providerVisualId,
  remainingCommandOffers,
  resolveCurrentCommandOffer,
  researchAgentConfigRoute,
  commandOfferUnavailableReason,
  withoutStartNodeOffers,
} from "./nodeInspectorOpsModel";

function offer(partial: Partial<CommandOffer> & Pick<CommandOffer, "command" | "label">): CommandOffer {
  return {
    nodeId: "knowledge_ingestion",
    available: true,
    reasonCode: "ready",
    blockerIds: [],
    idempotencyKey: `offer:${partial.command}`,
    expectedRunVersion: 1,
    payload: {},
    ...partial,
  };
}

function ledger(overrides: Partial<ResearchBudgetLedgerSnapshot> = {}): ResearchBudgetLedgerSnapshot {
  return {
    budgetLedgerId: "led-1",
    runId: "run-1",
    stageId: "knowledge_collection",
    policySnapshotHash: "h1",
    limits: { tokens: 100, toolCalls: 10, wallClockSeconds: 60 },
    reserved: {},
    consumed: { tokens: 8, toolCalls: 1, wallClockSeconds: 2 },
    remaining: {},
    stopReason: "",
    updatedAt: "2026-08-17T00:00:00.000Z",
    ...overrides,
  };
}

describe("nodeInspectorOpsModel", () => {
  it("maps provider ids to visual rails without leaking internal keys", () => {
    expect(providerVisualId("qwen")).toBe("qwen");
    expect(providerVisualId("dashscope")).toBe("qwen");
    expect(providerVisualId("deepseek")).toBe("deepseek");
    expect(providerVisualId("anthropic")).toBe("anthropic");
    expect(agentDisplayInitial("资料入库")).toBe("资");
    expect(researchAgentConfigRoute("agent-ingestor")).toBe(
      "/agents?pane=config&agent=agent-ingestor",
    );
  });

  it("computes measured budget percentages without presenting missing data as zero", () => {
    expect(budgetMeterPercent(88, 100)).toBe(88);
    expect(budgetMeterPercent(8, 0)).toBe(0);
    const empty = nodeInspectorBudgetMeters(null);
    expect(empty).toEqual([]);
    expect(nodeInspectorBudgetMeters(ledger({limits: {tokens: 0, toolCalls: 0, wallClockSeconds: 0}}))).toEqual([]);
    const tight = nodeInspectorBudgetMeters(ledger({
      consumed: { tokens: 88, toolCalls: 81, wallClockSeconds: 84 },
      limits: { tokens: 100, toolCalls: 100, wallClockSeconds: 100 },
    }));
    expect(tight[0]?.warn).toBe(true);
    expect(tight[0]?.detail).toContain("88 / 100");
    expect(ledgerForStage([ledger()], "knowledge_collection")?.budgetLedgerId).toBe("led-1");
    expect(ledgerForStage([ledger()], "experiment_design")).toBeNull();
  });

  it("keeps node override writes as a merged layer instead of a single-key wipe", () => {
    const merged = mergeNodeOverrideLayer(
      [
        { nodeId: "source_finding", roleKey: "source_finder", agentId: "a1", resolvedFrom: "node_override" },
        { nodeId: "knowledge_ingestion", roleKey: "source_ingestor", agentId: "a2", resolvedFrom: "workflow_default" },
      ],
      "knowledge_ingestion",
      "a3",
    );
    expect(merged).toEqual({
      source_finding: "a1",
      knowledge_ingestion: "a3",
    });
  });

  it("picks start_node as the card primary and leaves other offers for the command strip", () => {
    const start = offer({ command: "start_node", label: "启动 知识入库" });
    const fork = offer({ command: "fork_revision", label: "分叉修订", idempotencyKey: "offer:fork" });
    expect(pickPrimaryCommandOffer([fork, start])).toEqual(start);
    expect(remainingCommandOffers([fork, start], start)).toEqual([fork]);
    expect(nodeInspectorStatus({
      unbound: false,
      runtimeCurrent: true,
      status: "running",
      budgetWarn: true,
    }).label).toBe("运行中");
    expect(nodeInspectorStatus({
      unbound: false,
      runtimeCurrent: true,
      status: "pending",
      budgetWarn: false,
    })).toEqual({ tone: "neutral", label: "待启动" });
    expect(nodeInspectorStatus({
      unbound: false,
      runtimeCurrent: true,
      status: "created",
      budgetWarn: false,
    })).toEqual({ tone: "neutral", label: "待启动" });
    expect(nodeInspectorStatus({
      unbound: false,
      runtimeCurrent: false,
      status: "created",
      budgetWarn: false,
    })).toEqual({ tone: "neutral", label: "未开始" });
    expect(nodeInspectorStatus({
      unbound: false,
      runtimeCurrent: true,
      status: "waiting_human",
      budgetWarn: false,
    }).label).toBe("等待确认");
    expect(nodeInspectorStatus({
      unbound: true,
      runtimeCurrent: false,
      status: null,
      budgetWarn: false,
    }).label).toBe("待指定");
  });

  it("maps hypothesis_first_meeting_open to product copy and hides start offers", () => {
    const blocked = offer({
      command: "start_node",
      label: "启动 资料寻找",
      available: false,
      reasonCode: "hypothesis_first_meeting_open",
      payload: { remediation_label: "前往闭环首轮假说讨论" },
    });
    expect(commandOfferUnavailableReason(blocked, true)).toBe("前往闭环首轮假说讨论");
    expect(commandOfferUnavailableReason({
      ...blocked,
      payload: {},
    }, true)).toBe("前往闭环首轮假说讨论");
    expect(commandOfferUnavailableReason(blocked, true)).not.toBe("hypothesis_first_meeting_open");
    expect(withoutStartNodeOffers([blocked, offer({ command: "retry_node", label: "重试" })]).map((item) => item.command)).toEqual(["retry_node"]);
  });

  it("drops unavailable retry offers instead of resurrecting a dead primary button", () => {
    const staleRetry = offer({
      command: "retry_node",
      label: "重试 知识入库",
      available: false,
      reasonCode: "node_in_flight",
      expectedRunVersion: 5,
    });
    expect(pickPrimaryCommandOffer([staleRetry])).toBeNull();
    const freshRetry = offer({
      command: "retry_node",
      label: "重试 知识入库",
      idempotencyKey: "offer:retry-fresh",
      expectedRunVersion: 8,
    });
    expect(pickPrimaryCommandOffer([staleRetry, freshRetry])).toEqual(freshRetry);
  });

  it("keeps an available retry visible when starting the failed node is blocked", () => {
    const start = offer({ command: "start_node", label: "启动", available: false, reasonCode: "retry_owns_recovery" });
    const retry = offer({ command: "retry_node", label: "重试" });
    expect(pickPrimaryCommandOffer([start, retry])).toEqual(retry);
    expect(pickPrimaryCommandOffer([start, { ...retry, available: false }])).toEqual(start);
  });

  it("reports run-version mismatches as a refresh need for available and unavailable offers", () => {
    const stale = offer({ command: "retry_node", label: "重试", expectedRunVersion: 5 });
    expect(commandOfferUnavailableReason(stale, true, 8)).toBe("运行状态已更新，请刷新后重试");
    expect(commandOfferUnavailableReason(stale, false, 8)).toBe("Run state has been updated; refresh and try again");
    expect(commandOfferUnavailableReason({ ...stale, available: false, reasonCode: "node_in_flight" }, true, 8))
      .toBe("运行状态已更新，请刷新后重试");
    expect(commandOfferUnavailableReason(stale, true, 5)).toBe("");
    expect(commandOfferUnavailableReason({ ...stale, available: false, reasonCode: "node_in_flight" }, true, 5))
      .toBe("当前节点已在执行");
    // No current version wired -> legacy behavior, no version gate.
    expect(commandOfferUnavailableReason(stale, true, null)).toBe("");
    expect(commandOfferUnavailableReason(stale, true, undefined)).toBe("");
  });

  // A06: offer re-resolution for the error-surface retry.
  describe("commandOfferIdentity / resolveCurrentCommandOffer", () => {
    const base = {
      nodeId: "source_finding",
      available: true,
      reasonCode: "ready",
      blockerIds: [],
      payload: { humanTaskId: "ht-1" },
    };

    it("matches by command + node + action parameters, ignoring signature fields", () => {
      const refused: CommandOffer = {
        ...base, command: "resolve_human_task", label: "x",
        idempotencyKey: "key-v1", expectedRunVersion: 4,
      };
      const refreshed: CommandOffer = {
        ...base, command: "resolve_human_task", label: "x",
        idempotencyKey: "key-v2", expectedRunVersion: 7,
      };
      expect(commandOfferIdentity(refused)).toBe(commandOfferIdentity(refreshed));

      // A different action parameter is a different command.
      expect(commandOfferIdentity({ ...refused, payload: { humanTaskId: "ht-2" } }))
        .not.toBe(commandOfferIdentity(refused));
      // Key order in the payload must not change identity.
      expect(commandOfferIdentity({ ...refused, payload: { humanTaskId: "ht-1", mode: "fast" } }))
        .toBe(commandOfferIdentity({ ...refused, payload: { mode: "fast", humanTaskId: "ht-1" } }));

      expect(resolveCurrentCommandOffer([refreshed], refused)).toEqual(refreshed);
      expect(resolveCurrentCommandOffer([{ ...refreshed, command: "retry_node" }], refused)).toBeNull();
      expect(resolveCurrentCommandOffer([refreshed], null)).toBeNull();
    });

    it("classifies transport-level failures as unknown outcome and HTTP errors as decided", () => {
      expect(isUnknownOutcomeCommandError(new TypeError("Failed to fetch"))).toBe(true);
      expect(isUnknownOutcomeCommandError(new Error("network down"))).toBe(true);
      const httpError = Object.assign(new Error("version conflict"), {
        name: "FetchJsonHttpError", status: 412, code: "run_version_conflict",
      });
      expect(isUnknownOutcomeCommandError(httpError)).toBe(false);
    });
  });

  it("renders Chinese reasons for knowledge collection availability blockers", () => {
    // 死 turn 死局场景：invocation 卡在 live，ensure offer 被服务端标不可用，
    // 前端必须渲染可读理由而不是裸 reason code。
    const inFlight = offer({
      command: "ensure_knowledge_collection",
      label: "发起知识搜集",
      available: false,
      reasonCode: "knowledge_collection_in_flight",
      blockerIds: ["knowledge_collection_in_flight"],
    });
    expect(commandOfferUnavailableReason(inFlight, true)).toBe("已有进行中的知识搜集请求");
    expect(commandOfferUnavailableReason(inFlight, false))
      .toBe("A knowledge collection request is already in flight");
    const terminal = offer({
      command: "ensure_knowledge_collection",
      label: "发起知识搜集",
      available: false,
      reasonCode: "run_terminal",
      blockerIds: ["run_terminal"],
    });
    expect(commandOfferUnavailableReason(terminal, true)).toBe("运行已结束，无法发起知识搜集");
    expect(commandOfferUnavailableReason(terminal, false))
      .toBe("The run has ended; knowledge collection is unavailable");
    // blockerIds 兜底路径同样映射（reasonCode 缺失时）。
    const blockerOnly = offer({
      command: "ensure_knowledge_collection",
      label: "发起知识搜集",
      available: false,
      reasonCode: "",
      blockerIds: ["knowledge_collection_in_flight"],
    });
    expect(commandOfferUnavailableReason(blockerOnly, true)).toBe("已有进行中的知识搜集请求");
  });
});
