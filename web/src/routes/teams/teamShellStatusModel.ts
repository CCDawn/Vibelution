/**
 * Status-rail presentation for the Teams shell.
 * Next-step + stage index + optional org-canvas node index — not a team list.
 */
import type { Team, TeamCanvasNode } from "../../api/types";
import {
  isAiSearchScopeTeam,
  isChallengeCupResearchWorkflowTeam,
  isKnowledgeExpansionWorkflowTeam,
} from "./teamKindModel";
import type { ResearchBoardColumn } from "./researchBoardModel";
import { canvasNodeStatusLabel } from "./teamRouteShellModel";

export type TeamShellStageTone = "done" | "active" | "idle" | "blocked";
export type TeamShellNodeStatusTone = "success" | "warning" | "danger" | "neutral";

export type TeamShellStatusStage = {
  id: string;
  title: string;
  status: string;
  tone: TeamShellStageTone;
};

export type TeamShellStatusNode = {
  id: string;
  label: string;
  agent: string;
  status: string;
  statusTone: TeamShellNodeStatusTone;
};

export function teamShellKindLabel(team: Team | null | undefined, lang: "zh" | "en"): string {
  if (!team) {
    return lang === "zh" ? "团队" : "Team";
  }
  if (isChallengeCupResearchWorkflowTeam(team)) {
    return lang === "zh" ? "科研工作流" : "Research workflow";
  }
  if (isAiSearchScopeTeam(team)) {
    return lang === "zh" ? "资料范围" : "Search scope";
  }
  if (isKnowledgeExpansionWorkflowTeam(team)) {
    return lang === "zh" ? "知识扩充" : "Knowledge expand";
  }
  return lang === "zh" ? "团队" : "Team";
}

export function teamShellStageChipTone(
  tone: TeamShellStageTone,
): "neutral" | "accent" | "success" | "warning" | "danger" {
  if (tone === "done") return "success";
  if (tone === "active") return "warning";
  if (tone === "blocked") return "danger";
  return "neutral";
}

export function teamShellStagesFromBoardColumns(
  columns: ResearchBoardColumn[],
  lang: "zh" | "en",
): TeamShellStatusStage[] {
  return columns.map((column) => {
    const activeCard = column.cards.find((card) => card.active) ?? column.cards[0];
    const status = activeCard?.foot || (lang === "zh" ? "未开始" : "Not started");
    return {
      id: column.id,
      title: lang === "zh" ? column.titleZh : column.titleEn,
      status,
      tone: stageToneFromStatus(Boolean(activeCard?.active), status),
    };
  });
}

export function teamShellNodesFromCanvas(
  nodes: TeamCanvasNode[],
  lang: "zh" | "en",
): TeamShellStatusNode[] {
  return nodes.map((node) => ({
    id: node.id,
    label: node.label,
    agent: node.agentName || node.agentCode || (lang === "zh" ? "未绑定" : "unbound"),
    status: canvasNodeStatusLabel(node, lang),
    statusTone: nodeStatusTone(node),
  }));
}

function stageToneFromStatus(active: boolean, status: string): TeamShellStageTone {
  if (active) return "active";
  if (/阻塞|block|需关注/i.test(status)) return "blocked";
  if (/完成|done|frozen|已冻结/i.test(status)) return "done";
  return "idle";
}

function nodeStatusTone(node: TeamCanvasNode): TeamShellNodeStatusTone {
  const status = String(node.status || "").toLowerCase();
  if (status === "stale") return "danger";
  if (node.agentId || status === "bound") return "success";
  if (status === "unbound") return "warning";
  return "neutral";
}
