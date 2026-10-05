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
