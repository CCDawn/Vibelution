/**
 * Source-collection shell pure helpers used by Teams inject adapters (structure T2).
 * Pure: no React hooks / Query / DOM. Style maps stay in the shell.
 */
import type { SourceCollectionStageModuleId } from "./source-collection/stageProjection";
import type { SourceCollectionStepState } from "./source-collection/runModel";
import { SOURCE_COLLECTION_RESULT_PAGE_SIZE } from "./source-collection/presentationModel";

export const SOURCE_COLLECTION_STAGE_AGENT_KEYS: Record<SourceCollectionStageModuleId, string[]> = {
  finding: ["source_finder"],
  extraction: ["source_extractor"],
  relations: ["source_relation_mapper"],
  ingestion: ["source_ingestor"],
};

export const SOURCE_COLLECTION_STAGE_TERMINAL_TASK_STATUSES = new Set([
  "blocked",
  "cancelled",
  "completed",
  "failed",
  "interrupted",
  "needs_review",
]);

export const SOURCE_COLLECTION_STAGE_TERMINAL_PROJECTION_STATUSES = new Set([
  "agent_blocked",
  "agent_done_artifact_pending",
  "agent_interrupted",
  "artifact_ready_agent_blocked",
  "artifact_ready_no_latest_agent_task",
  "closed_loop",
]);

export function sourceCollectionPageSlice<T>(
  items: T[],
  page: number,
  pageSize: number = SOURCE_COLLECTION_RESULT_PAGE_SIZE,
) {
  const pageCount = Math.max(1, Math.ceil(items.length / pageSize));
  const safePage = Math.min(Math.max(1, page), pageCount);
  const start = (safePage - 1) * pageSize;
  return {
    items: items.slice(start, start + pageSize),
    page: safePage,
    pageCount,
    start: items.length ? start + 1 : 0,
    end: Math.min(items.length, start + pageSize),
  };
}

export function sourceCollectionStageReturnRoute(teamId: string, stageId: SourceCollectionStageModuleId, baseRoute: string) {
  return `${baseRoute}&collectionStage=${stageId}`;
}

export function sourceCollectionStageChatReturnLabel(
  stageId: SourceCollectionStageModuleId,
  lang: "zh" | "en",
  stageChatLabels: Record<SourceCollectionStageModuleId, { zh: string; en: string }>,
) {
  return `${lang === "zh" ? "返回" : "Back to"} ${stageChatLabels[stageId][lang]}`;
}

export function sourceCollectionStageAgentBindingsForStage<T extends { key: string }>(
  stageId: SourceCollectionStageModuleId,
  bindings: T[],
) {
  const targetKeys = SOURCE_COLLECTION_STAGE_AGENT_KEYS[stageId];
  const priorityByKey = new Map(targetKeys.map((key, index) => [key, index]));
  return bindings
    .filter((binding) => priorityByKey.has(binding.key))
    .sort((left, right) => (priorityByKey.get(left.key) ?? 99) - (priorityByKey.get(right.key) ?? 99));
}

export type SourceCollectionLaunchInputs = {
  pendingStageId: string | null | undefined;
  pendingTaskIds: string[];
  writebackSyncActive: boolean;
  latestTaskId: string;
  latestTaskStatus: string;
  projectionStatus: string;
};

export function sourceCollectionStageLaunchActive(
  stageId: SourceCollectionStageModuleId,
  inputs: SourceCollectionLaunchInputs,
) {
  if (inputs.pendingStageId === stageId) {
    return true;
  }
  if (!inputs.writebackSyncActive || inputs.pendingTaskIds.length <= 0) {
    return false;
  }
  if (inputs.latestTaskId && inputs.pendingTaskIds.includes(inputs.latestTaskId)) {
    const latestTaskStatus = String(inputs.latestTaskStatus || "").toLowerCase();
    const projectionStatus = String(inputs.projectionStatus || "").toLowerCase();
    return !SOURCE_COLLECTION_STAGE_TERMINAL_TASK_STATUSES.has(latestTaskStatus)
      && !SOURCE_COLLECTION_STAGE_TERMINAL_PROJECTION_STATUSES.has(projectionStatus);
  }
  return true;
}

export function sourceCollectionStageLaunchSummary(
  stageId: SourceCollectionStageModuleId,
  pendingStageId: string | null | undefined,
  lang: "zh" | "en",
) {
  if (pendingStageId === stageId) {
    return lang === "zh"
      ? "Agent 已启动，正在进入私聊并准备执行本阶段任务。"
      : "Agent started and the private chat is opening for this stage.";
  }
  return lang === "zh"
    ? "等待 Agent 回写。团队页正在同步本阶段结果。"
    : "Waiting for Agent writeback. The team page is syncing this stage result.";
}

export function sourceCollectionStageDisplayState(
  active: boolean,
  fallback: SourceCollectionStepState,
): SourceCollectionStepState {
  return active ? "active" : fallback;
}

export function sourceCollectionStageDisplayStatus(
  stageId: SourceCollectionStageModuleId,
  active: boolean,
  pendingStageId: string | null | undefined,
  fallback: string,
  lang: "zh" | "en",
) {
  if (!active) {
    return fallback;
  }
  return pendingStageId === stageId
    ? (lang === "zh" ? "Agent 已启动" : "Agent started")
    : (lang === "zh" ? "等待 Agent 回写" : "Waiting for Agent writeback");
}

export function sourceCollectionStageDisplaySummary(
  active: boolean,
  summary: string,
  fallback: string,
) {
  return active ? summary : fallback;
}
