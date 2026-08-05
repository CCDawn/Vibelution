/**
 * Product gate for the fixed right-rail stage advance button.
 * A click must either start real work or fail loudly with a redirect stage.
 * Never treat "open chat" as success when upstream is not ready.
 */
import type { SourceCollectionStageModuleId } from "./stageProjection";

export type SourceCollectionStageAdvancePreflightInput = {
  stageId: SourceCollectionStageModuleId;
  hasRun: boolean;
  rawRecordCount: number;
  approvedCandidateCount: number;
  displayedCandidateCount: number;
  graphNodeCount: number;
  graphEdgeCount: number;
  graphMissingLinkCount: number;
  /** From knowledge ingestion status action items when available. */
  knowledgeActionItemCodes?: string[];
  findingState?: string;
  extractionState?: string;
  relationsState?: string;
};

export type SourceCollectionStageAdvancePreflightResult =
  | { ok: true }
  | {
      ok: false;
      reasonZh: string;
      reasonEn: string;
      /** Stage the operator should advance instead. */
      redirectStageId: SourceCollectionStageModuleId;
    };

const GRAPH_MISSING_LINK_HARD_LIMIT = 5;

/**
 * Deterministic preflight for stage advance. Keep pure for unit tests.
 */
export function preflightSourceCollectionStageAdvance(
  input: SourceCollectionStageAdvancePreflightInput,
): SourceCollectionStageAdvancePreflightResult {
  const stageId = input.stageId;

  if (stageId === "finding") {
    if (!input.hasRun && input.rawRecordCount <= 0) {
      return { ok: true };
    }
    return { ok: true };
  }

  if (stageId === "extraction") {
    if (input.rawRecordCount <= 0) {
      return {
        ok: false,
        reasonZh: "推进失败：还没有原始资料，无法提炼。请先完成找资料。",
        reasonEn: "Advance failed: no raw records to extract. Finish finding first.",
        redirectStageId: "finding",
      };
    }
    return { ok: true };
  }

  if (stageId === "relations") {
    if (input.approvedCandidateCount <= 0 && input.displayedCandidateCount <= 0) {
      return {
        ok: false,
        reasonZh: "推进失败：没有可整理的候选资料。请先完成提炼/审查。",
        reasonEn: "Advance failed: no candidates for relation mapping. Finish extraction first.",
        redirectStageId: "extraction",
      };
    }
    return { ok: true };
  }

  // ingestion
  if (input.approvedCandidateCount <= 0 && input.displayedCandidateCount <= 0) {
    return {
      ok: false,
      reasonZh: "推进失败：没有可入库的候选资料。请先完成提炼。",
      reasonEn: "Advance failed: no candidates to ingest. Finish extraction first.",
      redirectStageId: "extraction",
    };
  }

  const missingLinks = Math.max(0, Number(input.graphMissingLinkCount || 0));
  const edgeCount = Math.max(0, Number(input.graphEdgeCount || 0));
  const nodeCount = Math.max(0, Number(input.graphNodeCount || 0));
  const actionCodes = input.knowledgeActionItemCodes || [];
  const graphFlagged = actionCodes.some((code) =>
    /candidate_graph_missing_links|candidate_validation_failed/i.test(String(code || "")),
  );
  const relationsIncomplete = input.relationsState === "failed"
    || input.relationsState === "pending"
    || input.relationsState === "active";

  if (nodeCount > 0 && edgeCount <= 0) {
    return {
      ok: false,
      reasonZh: `推进失败：关系图有 ${nodeCount} 个节点但 0 条边，入库会被系统拦截。请先完成「整理关系」。`,
      reasonEn: `Advance failed: graph has ${nodeCount} nodes but 0 edges. Finish relation mapping first.`,
      redirectStageId: "relations",
    };
  }

  if (missingLinks > GRAPH_MISSING_LINK_HARD_LIMIT || graphFlagged) {
    return {
      ok: false,
      reasonZh: `推进失败：关系缺口 ${missingLinks}（或图校验未通过），入库不能当作成功。请先修「整理关系」。`,
      reasonEn: `Advance failed: ${missingLinks} missing graph links (or validation failed). Fix relations first.`,
      redirectStageId: "relations",
    };
  }

  if (relationsIncomplete && edgeCount <= 0) {
    return {
      ok: false,
      reasonZh: "推进失败：关系阶段尚未完成。请先推进「整理关系」。",
      reasonEn: "Advance failed: relations stage is incomplete. Advance relations first.",
      redirectStageId: "relations",
    };
  }

  return { ok: true };
}

export function sourceCollectionStageAdvanceFailureTitle(lang: "zh" | "en") {
  return lang === "zh" ? "推进失败（不合格）" : "Advance failed";
}
