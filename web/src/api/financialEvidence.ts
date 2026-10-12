import { fetchJson } from "./client";
import type { FinancialPdfInput, FinancialPdfPreview, FinancialPdfStageInput, FinancialPdfStaged } from "./types/financialEvidence";

function evidencePath(agentId: string, action: "preview" | "stage") {
  return `/api/financial-assistants/${encodeURIComponent(agentId)}/evidence/${action}`;
}
export function previewFinancialPdf(agentId: string, input: FinancialPdfInput) {
  return fetchJson<FinancialPdfPreview>(evidencePath(agentId, "preview"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) });
}
export function stageFinancialPdf(agentId: string, input: FinancialPdfStageInput) {
  return fetchJson<FinancialPdfStaged>(evidencePath(agentId, "stage"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) });
}
