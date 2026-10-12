export type FinancialPdfInput = { sourceUrl: string; pdfBase64?: string };
export type FinancialPdfPage = { page: number; excerpt: string; excerptSha256: string };
export type FinancialPdfPreview = {
  documentSha256: string; sourceUrl: string; pageCount: number; byteSize: number;
  pages: FinancialPdfPage[]; warnings: string[]; numericValidation: "not_performed";
};
export type FinancialPdfStageInput = FinancialPdfInput & {
  company: string; ticker: string; reportPeriod: string; reportVersion: string;
  publishedDate: string; page: number; expectedDocumentSha256: string;
};
export type FinancialPdfStaged = {
  status: "pending_review" | "already_staged";
  source: { inboxSourceId: string; title: string; status: string; knowledgeItemId?: string };
};
