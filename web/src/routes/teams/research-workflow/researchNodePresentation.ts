import type { ActorKind, WorkflowStageId } from "../../../api/types/researchWorkflow";
import { RESEARCH_STAGE_TERMS } from "./researchTerminology";

const STAGE_LABELS: Record<WorkflowStageId, string> = {
  knowledge_collection: RESEARCH_STAGE_TERMS.knowledge_collection.zh,
  experiment_design: RESEARCH_STAGE_TERMS.experiment_design.zh,
  execution_iteration: RESEARCH_STAGE_TERMS.execution_iteration.zh,
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
