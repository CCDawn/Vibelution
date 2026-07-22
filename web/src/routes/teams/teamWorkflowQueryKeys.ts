export const sourceCollectionSummaryQueryPrefix = (id: string) =>
  ["teams", id, "workflow-orchestration", "source-collection", "summary"] as const;
export const sourceCollectionSummaryQueryKey = (id: string, runId: string) =>
  [...sourceCollectionSummaryQueryPrefix(id), runId || "latest"] as const;
export const sourceCollectionRunRecordsQueryKey = (id: string) => ["data-processing", "runs", id, "records"] as const;

export function sourceCollectionStageTaskClickKey(stageId: string) {
  const randomPart = Math.random().toString(36).slice(2, 10) || "manual";
  return `stage_task_click:${stageId}:${Date.now().toString(36)}:${randomPart}`;
}
