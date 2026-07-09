import type { DataProcessingRunListPayload } from "../../api/types";

export type SourceCollectionRunSummaryValue = DataProcessingRunListPayload["runs"][number] | null | undefined;

function sourceCollectionRunMetric(run: SourceCollectionRunSummaryValue, keys: string[]) {
  if (!run) {
    return 0;
  }
  const scopes = [
    run.summary,
    (run.scope as Record<string, unknown> | undefined)?.sourceCollectionSummary,
    (run.metadata as Record<string, unknown> | undefined)?.sourceCollectionSummary,
    run.scope,
    run.metadata,
  ].filter((value): value is Record<string, unknown> => Boolean(value && typeof value === "object"));
  for (const scope of scopes) {
    for (const key of keys) {
      const value = Number(scope[key]);
      if (Number.isFinite(value) && value > 0) {
        return value;
      }
    }
  }
  return 0;
}

export function sourceCollectionRunRecordCount(run: SourceCollectionRunSummaryValue) {
  return sourceCollectionRunMetric(run, ["recordCount", "rawRecordCount", "createdUniqueRecordCount"]);
}

export function sourceCollectionRunCandidateMetric(run: SourceCollectionRunSummaryValue) {
  return sourceCollectionRunMetric(run, ["sourceCandidateCount", "candidateCount", "importedCount"]);
}

export function sourceCollectionRunHasUsableRecords(run: SourceCollectionRunSummaryValue) {
  return sourceCollectionRunRecordCount(run) > 0 || sourceCollectionRunCandidateMetric(run) > 0;
}

export function selectDefaultSourceCollectionRun(
  runs: DataProcessingRunListPayload["runs"],
  requestedRunId: string,
) {
  return runs.find((run) => run.runId === requestedRunId)
    ?? runs.find(sourceCollectionRunHasUsableRecords)
    ?? runs[0]
    ?? null;
}
