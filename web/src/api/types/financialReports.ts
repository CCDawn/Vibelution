export type FinancialReportFormat = "markdown" | "json" | "docx" | "pdf";

export type FinancialReportExportRequest = {
  sessionId: string;
  turnId: string;
  format: FinancialReportFormat;
};

export type FinancialReportExportResponse = FinancialReportExportRequest & {
  fileName: string;
  mediaType: string;
  encoding: "utf8" | "base64";
  content: string;
};

export type FinancialReportSummary = {
  sessionId: string; turnId: string; title: string; sessionTitle: string;
  ticker: string | null; marketCode: "CN" | "HK" | "US" | null;
  completedAt: string; preview: string; chars: number; kind: "research" | "review";
};
export type FinancialReportFilters = {
  q?: string; marketCode?: "CN" | "HK" | "US" | "";
  dateFrom?: string; dateTo?: string; kind?: "research" | "review" | "";
  cursor?: string; limit?: number;
};
export type FinancialReportPage = {
  items: FinancialReportSummary[]; nextCursor: string | null;
  scannedSessions: number; order: "session_recency";
};

export type FinancialReportsExportResponse = { fileName: string; mediaType: "application/zip"; encoding: "base64"; content: string; count: number };
