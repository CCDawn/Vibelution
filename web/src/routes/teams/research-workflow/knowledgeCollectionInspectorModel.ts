/**
 * Knowledge-collection inspector model (display layer only).
 *
 * Discriminates the four knowledge-sideflow states plus failure recovery
 * from the snapshot's invocationBadges aggregate — never from UI selection
 * or guessed intermediate nodes. Pure functions, no React.
 */
import type { KnowledgeInvocationBadge } from "../../../api/types/research-workflow/core";
import {
  sideflowCardStatesForBadge,
} from "./knowledgeSideflowCanvasRegion";

export type KnowledgeCollectionPhase =
  | "not_started"
  | "collecting"
  | "awaiting_handoff"
  | "handed_off"
  | "failed";

export type KnowledgeCollectionLineage = {
  sourceNodeId: string | null;
  childRunId: string | null;
  currentKnowledgeNodeId: string | null;
  invocationId: string | null;
};

export type KnowledgeCollectionProgress = {
  completedNodes: number;
  totalNodes: number;
  currentNodeId: string | null;
};

export type KnowledgeCollectionInspectorModel = {
  phase: KnowledgeCollectionPhase;
  headline: string;
  detail: string | null;
  lineage: KnowledgeCollectionLineage;
  progress: KnowledgeCollectionProgress | null;
  packageRef: string | null;
  packageHash: string | null;
};

function phaseOf(badge: KnowledgeInvocationBadge): KnowledgeCollectionPhase {
  const status = String(badge.latest?.status ?? "").trim().toLowerCase();
  if (status === "awaiting_handoff") return "awaiting_handoff";
  if (status === "failed" || status === "cancelled") return "failed";
  if (status === "completed") return "handed_off";
  if (status) return "collecting";
  return "not_started";
}

function progressOf(
  badge: KnowledgeInvocationBadge,
  phase: KnowledgeCollectionPhase,
): KnowledgeCollectionProgress | null {
  if (phase === "not_started") return null;
  if (phase === "handed_off") {
    return { completedNodes: 5, totalNodes: 5, currentNodeId: null };
  }
  // Progress comes from the child run's REAL per-node states (via the
  // shared card derivation); when the child run's attempts are unavailable
  // the derivation falls back to the invocation-level current node — it
  // never invents middle-node facts.
  const cards = sideflowCardStatesForBadge(badge);
  let completedNodes = 0;
  let currentNodeId: string | null = null;
  for (const card of cards) {
    if (card.status === "succeeded") {
      completedNodes += 1;
      continue;
    }
    if (currentNodeId === null) currentNodeId = card.sideflowNodeId;
  }
  return {
    completedNodes,
    totalNodes: cards.length,
    currentNodeId,
  };
}

const PHASE_HEADLINES: Record<KnowledgeCollectionPhase, string> = {
  not_started: "补充知识",
  collecting: "知识搜集中",
  awaiting_handoff: "等待知识交接",
  handed_off: "知识已回写",
  failed: "知识搜集失败",
};

export function buildKnowledgeCollectionInspectorModel(input: {
  badge: KnowledgeInvocationBadge | null | undefined;
}): KnowledgeCollectionInspectorModel {
  const badge = input.badge;
  if (!badge || (badge.totalCount ?? 0) <= 0 || !badge.latest) {
    return {
      phase: "not_started",
      headline: PHASE_HEADLINES.not_started,
      detail: "该节点尚未发起知识请求；发起后会创建知识搜集子运行并跨运行回写。",
      lineage: {
        sourceNodeId: null,
        childRunId: null,
        currentKnowledgeNodeId: null,
        invocationId: null,
      },
      progress: null,
      packageRef: null,
      packageHash: null,
    };
  }
  const phase = phaseOf(badge);
  const latest = badge.latest;
  const detail = (() => {
    switch (phase) {
      case "collecting":
        return "知识搜集子运行进行中，可在下方查看五节点进度与停止动作。";
      case "awaiting_handoff":
        return "知识包已产出并等待人工交接确认；请核对来源与风险后接受或要求修订。";
      case "handed_off":
        return "知识包已被父运行吸收并回写；下方可追溯包引用与来源节点。";
      case "failed":
        return "知识搜集失败；可按剩余预算重试，失败节点与子运行见下方。";
      default:
        return null;
    }
  })();
  return {
    phase,
    headline: `${PHASE_HEADLINES[phase]} · 共 ${badge.totalCount} 次请求`,
    detail,
    lineage: {
      sourceNodeId: latest.parentNodeId || null,
      childRunId: latest.knowledgeChildRunId ?? null,
      currentKnowledgeNodeId: latest.currentKnowledgeNodeId ?? null,
      invocationId: latest.invocationId || null,
    },
    progress: progressOf(badge, phase),
    packageRef: latest.knowledgePackageRef ?? null,
    packageHash: latest.packageContentHash ?? null,
  };
}
