import { describe, expect, it } from "vitest";
import type { FinancialResearchBatch } from "../../api/financialJobs";
import { buildFinanceProposalBatchImport, financeProposalBatchCandidates, financeProposalBatchImportAvailability, financeProposalBatchReportKey, MAX_PROPOSAL_BATCH_REPORTS } from "./financeProposalImportModel";

function batch(status: FinancialResearchBatch["status"] = "completed"): FinancialResearchBatch {
  return {
    batchId: "batch-1", scheduleId: null, assistantAgentId: "finance-1", status,
    triggeredAt: "2026-10-08T10:00:00+08:00", updatedAt: "2026-10-08T12:00:00+08:00",
    researchDate: "2026-10-08", periodDays: 30, depth: "standard", symbols: ["sh600000", "sz000001"], terminalReason: null,
    items: [
      { symbol: "sh600000", status: "completed", runId: "run-1", startedAt: null, completedAt: null, terminalReason: null, turnRefs: [
        { role: "market", sessionId: "market-session", turnId: "market-turn" },
        { role: "synthesis", sessionId: "synthesis-session-1", turnId: "synthesis-turn-1" },
      ] },
      { symbol: "sz000001", status: "completed", runId: "run-2", startedAt: null, completedAt: null, terminalReason: null, turnRefs: [
        { role: "synthesis", sessionId: "synthesis-session-2", turnId: "synthesis-turn-2" },
      ] },
    ],
  };
}

describe("finance proposal batch import", () => {
  it("offers only the exact completed synthesis turns and keeps the batch owner", () => {
    const source = batch("partial");
    const candidates = financeProposalBatchCandidates(source);
    expect(candidates.map((row) => row.report)).toEqual([
      { symbol: "sh600000", sessionId: "synthesis-session-1", turnId: "synthesis-turn-1" },
      { symbol: "sz000001", sessionId: "synthesis-session-2", turnId: "synthesis-turn-2" },
    ]);

    const imported = buildFinanceProposalBatchImport(source, [financeProposalBatchReportKey(candidates[1].report!), financeProposalBatchReportKey(candidates[0].report!)]);
    expect(imported).toMatchObject({ assistantAgentId: "finance-1", batchId: "batch-1", researchDate: "2026-10-08" });
    expect(imported.reports).toEqual([
      { symbol: "sz000001", sessionId: "synthesis-session-2", turnId: "synthesis-turn-2" },
      { symbol: "sh600000", sessionId: "synthesis-session-1", turnId: "synthesis-turn-1" },
    ]);
  });

  it("marks missing or ambiguous synthesis references unavailable instead of substituting analyst turns", () => {
    const source = batch();
    source.items[0].turnRefs = [{ role: "market", sessionId: "market", turnId: "market-turn" }];
    source.items[1].turnRefs = [
      { role: "synthesis", sessionId: "same-session", turnId: "same-turn" },
      { role: "synthesis", sessionId: "same-session", turnId: "same-turn" },
    ];
    expect(financeProposalBatchCandidates(source).map(({ report, unavailableReason }) => ({ report, unavailableReason }))).toEqual([
      { report: null, unavailableReason: "缺少已完成的汇总报告引用" },
      { report: null, unavailableReason: "汇总报告引用不唯一" },
    ]);
  });

  it("keeps international reports visible but excludes them from A-share proposal imports", () => {
    const source = batch();
    source.items = ["hk00700", "usAAPL"].map((symbol, index) => ({
      symbol, status: "completed", runId: `run-${index}`, startedAt: null, completedAt: null, terminalReason: null,
      turnRefs: [{ role: "synthesis", sessionId: `session-${index}`, turnId: `turn-${index}` }],
    }));
    source.symbols = source.items.map((item) => item.symbol);
    const candidates = financeProposalBatchCandidates(source);

    expect(candidates.map((row) => row.report?.symbol)).toEqual(["hk00700", "usAAPL"]);
    expect(candidates.every((row) => row.unavailableReason?.includes("组合建议仅支持沪、深、北交所 A 股"))).toBe(true);
    expect(financeProposalBatchImportAvailability(source)).toEqual({
      available: false,
      reason: "此批次不含可导入的 A 股结果；港股和美股不能用于组合建议",
    });
    expect(() => buildFinanceProposalBatchImport(source, [candidates[0].key])).toThrow("不属于此批次或已不可用");
  });

  it("requires an explicit selection of at most five references from a terminal completed batch", () => {
    const source = batch();
    const keys = Array.from({ length: MAX_PROPOSAL_BATCH_REPORTS + 1 }, (_, index) => JSON.stringify([`session-${index}`, `turn-${index}`]));
    expect(() => buildFinanceProposalBatchImport(source, [])).toThrow("至少选择一份");
    expect(() => buildFinanceProposalBatchImport(source, keys)).toThrow("一次最多选择");
    expect(() => buildFinanceProposalBatchImport({ ...source, status: "running" }, [financeProposalBatchReportKey({ sessionId: "synthesis-session-1", turnId: "synthesis-turn-1" })])).toThrow("仅可导入已完成");
    expect(() => buildFinanceProposalBatchImport(source, [JSON.stringify(["foreign-session", "foreign-turn"])] )).toThrow("不属于此批次");
  });
});
