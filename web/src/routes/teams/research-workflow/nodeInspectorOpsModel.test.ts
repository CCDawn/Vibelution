import { describe, expect, it } from "vitest";

import type { CommandOffer } from "../../../api/types/research-workflow/commands";
import type { ResearchBudgetLedgerSnapshot } from "../../../api/types/researchWorkflow";
import {
  agentDisplayInitial,
  budgetMeterPercent,
  ledgerForStage,
  mergeNodeOverrideLayer,
  nodeInspectorBudgetMeters,
  nodeInspectorStatus,
  pickPrimaryCommandOffer,
  providerVisualId,
  remainingCommandOffers,
  researchAgentConfigRoute,
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

  it("computes budget percents from the stage ledger and stays at zero before a run", () => {
    expect(budgetMeterPercent(88, 100)).toBe(88);
    expect(budgetMeterPercent(8, 0)).toBe(0);
    const empty = nodeInspectorBudgetMeters(null);
    expect(empty.map((item) => item.percent)).toEqual([0, 0, 0]);
    expect(empty[0]?.detail).toContain("运行后显示用量");
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
      unbound: true,
      runtimeCurrent: false,
      status: null,
      budgetWarn: false,
    }).label).toBe("待指定");
  });
});
