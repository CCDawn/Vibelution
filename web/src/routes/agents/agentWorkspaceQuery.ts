import { deriveQueryPresentation } from "../../app/queryPresentation";

/** Prefer full workspace when needed; otherwise fall back to summary. */
export function resolveAgentWorkspaceSource<T>({
  summary,
  full,
  fullWorkspaceNeeded,
}: {
  summary: T | undefined;
  full: T | undefined;
  fullWorkspaceNeeded: boolean;
}): T | undefined {
  return fullWorkspaceNeeded && full ? full : summary ?? full;
}

/** Derive error ownership for summary/full agent workspace queries. */
export function resolveAgentWorkspaceQueryState({
  hasSummary,
  hasFull,
  fullWorkspaceNeeded,
  summaryError,
  fullError,
}: {
  hasSummary: boolean;
  hasFull: boolean;
  fullWorkspaceNeeded: boolean;
  summaryError: boolean;
  fullError: boolean;
}) {
  const hasWorkspace = hasSummary || hasFull;
  const requiredFullError = fullWorkspaceNeeded && fullError;
  const initialError = !hasWorkspace && summaryError && (!fullWorkspaceNeeded || fullError);
  const backgroundError = hasWorkspace && (requiredFullError || (!fullWorkspaceNeeded && summaryError));
  const errorOwner = requiredFullError ? "full" : summaryError ? "summary" : null;
  return { hasWorkspace, initialError, backgroundError, errorOwner } as const;
}

/** Summary metric display: hide numbers when the query presentation is error-empty. */
export function agentSummaryMetricValue(
  presentation: ReturnType<typeof deriveQueryPresentation>,
  value: number | undefined,
  unavailable: string,
): number | string {
  return presentation === "error-empty" ? unavailable : value ?? 0;
}
