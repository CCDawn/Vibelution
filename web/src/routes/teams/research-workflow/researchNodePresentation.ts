import type { ActorKind, WorkflowStageId } from "../../../api/types/researchWorkflow";

const STAGE_LABELS: Record<WorkflowStageId, string> = {
  knowledge_collection: "知识搜集",
  experiment_design: "实验设计",
  execution_iteration: "执行迭代",
};

const ACTOR_LABELS: Record<ActorKind, string> = {
  agent: "Agent 执行",
  system: "系统执行",
  human: "人工审核",
};

export function researchStageLabel(stageId: string): string {
  return STAGE_LABELS[stageId as WorkflowStageId] ?? "流程阶段";
}

export function researchActorLabel(actorKind: string): string {
  return ACTOR_LABELS[actorKind as ActorKind] ?? "执行节点";
}
