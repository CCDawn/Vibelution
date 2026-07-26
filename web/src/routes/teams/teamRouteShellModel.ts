/**
 * TeamsRoute pure shell helpers (structure M5).
 * Pure: no React hooks / Query / DOM. Style-bound helpers stay in TeamsRoute.
 */
import type { ChatRoomDetail, TeamCanvasNode, TeamWorkflowCandidate, TeamWorkflowCandidateGraphPayload } from "../../api/types";
import type { ResearchStageRoundStartPayload } from "./workflowStartMutationModel";
import { sourceCollectionRunLabel } from "./source-collection/runModel";
import type { SourceCollectionStageModuleId } from "./source-collection/stageProjection";
import { isRecord } from "./workflowPresentation";

export const SOURCE_COLLECTION_STAGE_CHAT_LABELS: Record<SourceCollectionStageModuleId, { zh: string; en: string }> = {
  finding: { zh: "资料寻找 Agent 私聊", en: "Source finder Agent chat" },
  extraction: { zh: "资料提炼 Agent 私聊", en: "Source extraction Agent chat" },
  relations: { zh: "资料关系整理 Agent 私聊", en: "Source relation Agent chat" },
  ingestion: { zh: "资料入库 Agent 私聊", en: "Source ingestion Agent chat" },
};

export function parseSourceCollectionStageModuleId(value: string | null): SourceCollectionStageModuleId | null {
  if (value === "search") {
    return "finding";
  }
  if (value === "extract") {
    return "extraction";
  }
  if (value === "review") {
    return "extraction";
  }
  if (value === "ingest") {
    return "ingestion";
  }
  if (value === "collection") {
    return "finding";
  }
  if (value === "candidate" || value === "screening") {
    return "extraction";
  }
  if (value === "graph") {
    return "relations";
  }
  if (value === "memory") {
    return "ingestion";
  }
  return value === "finding" || value === "extraction" || value === "relations" || value === "ingestion"
    ? value
    : null;
}

export function researchStageStartFeedbackText(payload: ResearchStageRoundStartPayload, lang: "zh" | "en", stageLabel?: string) {
  const label = stageLabel || payload.stageRound.stageType;
  const sourceRef = payload.continuedSourceRunRef;
  if (payload.created === false && payload.continued && sourceRef) {
    if (lang === "zh") {
      return `已复用正在运行的${label}第 ${payload.stageRound.roundNumber} 轮：${sourceCollectionRunLabel(sourceRef.runId)} · ${sourceRef.recordCount} 条记录 / ${sourceRef.openAssignmentCount} 个待回写任务。要创建全新批次，请点“开启新一轮”。`;
    }
    return `Reused active ${label} round ${payload.stageRound.roundNumber}: ${sourceCollectionRunLabel(sourceRef.runId)} · ${sourceRef.recordCount} records / ${sourceRef.openAssignmentCount} open tasks. Use "New round" to create a fresh batch.`;
  }
  if (lang === "zh") {
    return `已进入 ${label} 第 ${payload.stageRound.roundNumber} 轮`;
  }
  return `Entered ${label} round ${payload.stageRound.roundNumber}`;
}

export function teamNodeFunctionLabel(node: TeamCanvasNode, displayLabel: string | undefined, lang: "zh" | "en") {
  const role = String(node.role || "").trim();
  const purpose = String(node.purpose || "").trim();
  const key = `${role} ${purpose}`.toLowerCase();
  if (key.includes("ceo") || key.includes("lead") || key.includes("负责人")) {
    return lang === "zh" ? "科研负责人" : "Research lead";
  }
  if (key.includes("organization") || key.includes("advisor") || key.includes("组织顾问") || key.includes("顾问")) {
    return lang === "zh" ? "组织顾问" : "Organization advisor";
  }
  if (key.includes("capability") || key.includes("steward") || key.includes("能力管家") || key.includes("管家")) {
    return lang === "zh" ? "能力管家" : "Capability steward";
  }
  if (purpose) {
    return purpose;
  }
  return displayLabel || role || (lang === "zh" ? "未绑定" : "Unbound");
}

export function canvasNodeStatusLabel(node: TeamCanvasNode | null | undefined, lang: "zh" | "en") {
  if (!node) {
    return lang === "zh" ? "未选择" : "not selected";
  }
  const status = String(node.status || "").trim().toLowerCase();
  const role = String(node.role || "").trim();
  if (role === "knowledge_steward" && node.agentId) {
    return lang === "zh" ? "专属管理员" : "dedicated admin";
  }
  if (status === "stale") {
    return lang === "zh" ? "引用失效" : "stale reference";
  }
  if (node.agentId || status === "bound") {
    return lang === "zh" ? "已绑定" : "bound";
  }
  return lang === "zh" ? "未绑定" : "unbound";
}

export function latestChatRoomRound(room: ChatRoomDetail | null | undefined) {
  const rounds = room?.rounds ?? [];
  return rounds.length ? rounds[rounds.length - 1] : null;
}

export function isWorkflowCandidateGraphPayload(value: unknown): value is TeamWorkflowCandidateGraphPayload {
  if (!isRecord(value)) {
    return false;
  }
  return (
    Array.isArray(value.nodes)
    && Array.isArray(value.edges)
    && Array.isArray(value.missingLinks)
    && Array.isArray(value.unreviewedNodes)
    && isRecord(value.officialBoundary)
    && isRecord(value.summary)
  );
}

export function workflowCandidateGraphFromCandidate(candidate: TeamWorkflowCandidate | null | undefined) {
  const graph = candidate?.metadata?.graph;
  return isWorkflowCandidateGraphPayload(graph) ? graph : null;
}

export function sourceCandidateHasCompletedExtraction(candidate: TeamWorkflowCandidate) {
  const metadata = isRecord(candidate.metadata) ? candidate.metadata : {};
  const extraction = isRecord(metadata.sourceExtraction) ? metadata.sourceExtraction : {};
  return candidate.candidateType === "source_manifest" && extraction.status === "extracted" && Array.isArray(extraction.pageAnchors);
}

export function candidatePaperNoteChunkPlanSummary(candidate: TeamWorkflowCandidate) {
  const metadata = isRecord(candidate.metadata) ? candidate.metadata : {};
  const plan = isRecord(metadata.paperNoteChunkPlan) ? metadata.paperNoteChunkPlan : null;
  if (!plan) {
    return null;
  }
  return {
    planId: String(plan.planId || ""),
    status: String(plan.status || ""),
    chunkCount: Number(plan.chunkCount || 0),
    completedChunkCount: Number(plan.completedChunkCount || 0),
    needsRevisionChunkCount: Number(plan.needsRevisionChunkCount || 0),
  };
}

export function latestWorkflowCandidate(candidates: TeamWorkflowCandidate[]) {
  return [...candidates].sort((left, right) => {
    const rightTime = new Date(right.updatedAt || right.createdAt || "").getTime();
    const leftTime = new Date(left.updatedAt || left.createdAt || "").getTime();
    return (Number.isFinite(rightTime) ? rightTime : 0) - (Number.isFinite(leftTime) ? leftTime : 0);
  })[0] ?? null;
}
