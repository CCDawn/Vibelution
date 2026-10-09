import type { FinancialResearchBatch } from "../../api/financialJobs";
import { normalizeFinancialBatchAShareSymbol } from "./financialJobModel";

export const MAX_PROPOSAL_BATCH_REPORTS = 5;

export type FinanceProposalBatchReport = {
  symbol: string;
  sessionId: string;
  turnId: string;
};

export type FinanceProposalBatchImport = {
  importId: string;
  assistantAgentId: string;
  batchId: string;
  researchDate: string;
  reports: FinanceProposalBatchReport[];
};

export type FinanceProposalBatchReportCandidate = {
  symbol: string;
  key: string;
  report: FinanceProposalBatchReport | null;
  unavailableReason: string | null;
};

export type FinanceProposalBatchImportAvailability = { available: boolean; reason: string | null };

export function financeProposalBatchReportKey(report: Pick<FinanceProposalBatchReport, "sessionId" | "turnId">): string {
  return JSON.stringify([report.sessionId, report.turnId]);
}

export function financeProposalBatchCandidates(batch: FinancialResearchBatch): FinanceProposalBatchReportCandidate[] {
  const completedItems = batch.items.filter((item) => item.status === "completed");
  const rows = completedItems.map((item): FinanceProposalBatchReportCandidate => {
    const normalizedSymbol = normalizeFinancialBatchAShareSymbol(item.symbol);
    const unsupportedMarketReason = normalizedSymbol ? null : "组合建议仅支持沪、深、北交所 A 股；港股和美股不能选择";
    const synthesisRefs = item.turnRefs.filter((ref) => ref.role === "synthesis");
    if (synthesisRefs.length !== 1) {
      const referenceReason = synthesisRefs.length ? "汇总报告引用不唯一" : "缺少已完成的汇总报告引用";
      return { symbol: item.symbol, key: `unavailable:${item.symbol}`, report: null, unavailableReason: [unsupportedMarketReason, referenceReason].filter(Boolean).join("；") };
    }
    const ref = synthesisRefs[0];
    if (!ref.sessionId.trim() || !ref.turnId.trim()) {
      return { symbol: item.symbol, key: `unavailable:${item.symbol}`, report: null, unavailableReason: [unsupportedMarketReason, "汇总报告引用不完整"].filter(Boolean).join("；") };
    }
    const report = { symbol: normalizedSymbol ?? item.symbol, sessionId: ref.sessionId, turnId: ref.turnId };
    return { symbol: item.symbol, key: financeProposalBatchReportKey(report), report, unavailableReason: unsupportedMarketReason };
  });

  const occurrences = new Map<string, number>();
  for (const row of rows) if (row.report) occurrences.set(row.key, (occurrences.get(row.key) ?? 0) + 1);
  return rows.map((row) => row.report && (occurrences.get(row.key) ?? 0) > 1
    ? { ...row, unavailableReason: [row.unavailableReason, "多只股票指向同一份汇总报告"].filter(Boolean).join("；") }
    : row);
}

export function financeProposalBatchImportAvailability(batch: FinancialResearchBatch): FinanceProposalBatchImportAvailability {
  if (batch.status !== "completed" && batch.status !== "partial") return { available: false, reason: "仅可导入已完成或部分完成的批次" };
  const candidates = financeProposalBatchCandidates(batch);
  if (candidates.some((row) => row.report && !row.unavailableReason)) return { available: true, reason: null };
  const completedItems = batch.items.filter((item) => item.status === "completed");
  const hasAShareResult = completedItems.some((item) => normalizeFinancialBatchAShareSymbol(item.symbol));
  return hasAShareResult
    ? { available: false, reason: "没有可导入的 A 股汇总报告；请确认研究已完成且引用唯一" }
    : { available: false, reason: completedItems.length ? "此批次不含可导入的 A 股结果；港股和美股不能用于组合建议" : "此批次没有已完成的 A 股汇总报告" };
}

export function buildFinanceProposalBatchImport(batch: FinancialResearchBatch, selectedKeys: Iterable<string>): FinanceProposalBatchImport {
  if (batch.status !== "completed" && batch.status !== "partial") throw new Error("仅可导入已完成的批次结果");
  if (!batch.assistantAgentId.trim() || !batch.batchId.trim()) throw new Error("研究批次身份无效");

  const keys = [...new Set(selectedKeys)];
  if (!keys.length) throw new Error("至少选择一份汇总报告");
  if (keys.length > MAX_PROPOSAL_BATCH_REPORTS) throw new Error(`一次最多选择 ${MAX_PROPOSAL_BATCH_REPORTS} 份报告`);

  const candidates = new Map(financeProposalBatchCandidates(batch).filter((row) => row.report && !row.unavailableReason).map((row) => [row.key, row.report!]));
  const reports = keys.map((key) => candidates.get(key));
  if (reports.some((report) => !report)) throw new Error("所选报告不属于此批次或已不可用");
  const selectedReports = reports as FinanceProposalBatchReport[];
  return {
    importId: `${batch.batchId}:${selectedReports.map((report) => `${report.sessionId}:${report.turnId}`).join(",")}`,
    assistantAgentId: batch.assistantAgentId,
    batchId: batch.batchId,
    researchDate: batch.researchDate,
    reports: selectedReports,
  };
}
