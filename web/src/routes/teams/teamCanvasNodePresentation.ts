/**
 * Teams canvas node role/status pure classification (structure M9).
 * Style class mapping stays in the shell (or a styles map inject).
 */
import type { TeamCanvasNode } from "../../api/types";

export type CanvasNodeRoleBadgeKind =
  | "stale"
  | "open"
  | "lead"
  | "advisor"
  | "steward"
  | "research"
  | "self"
  | "general";

export type CanvasNodeToneKind = "stale" | "bound" | "open";

export function canvasNodeRoleBadgeKind(node: TeamCanvasNode, displayTone = ""): CanvasNodeRoleBadgeKind {
  if (node.status === "stale") {
    return "stale";
  }
  if (!node.agentId) {
    return "open";
  }
  const key = `${node.role} ${node.purpose} ${displayTone}`.toLowerCase();
  if (key.includes("ceo") || key.includes("lead") || key.includes("负责人")) {
    return "lead";
  }
  if (key.includes("advisor") || key.includes("organization") || key.includes("顾问")) {
    return "advisor";
  }
  if (key.includes("steward") || key.includes("capability") || key.includes("能力") || key.includes("管家")) {
    return "steward";
  }
  if (key.includes("research") || key.includes("科研")) {
    return "research";
  }
  if (key.includes("self") || key.includes("进化")) {
    return "self";
  }
  return "general";
}

export function canvasNodeToneKind(node: TeamCanvasNode): CanvasNodeToneKind {
  if (node.status === "stale") {
    return "stale";
  }
  if (node.agentId) {
    return "bound";
  }
  return "open";
}

export type CanvasNodeRoleBadgeStyles = Record<CanvasNodeRoleBadgeKind, string> & {
  stale: string;
  open: string;
  lead: string;
  advisor: string;
  steward: string;
  research: string;
  self: string;
  general: string;
};

export type CanvasNodeToneStyles = {
  stale: string;
  bound: string;
  open: string;
};

export function roleBadgeToneClass(
  node: TeamCanvasNode,
  styles: CanvasNodeRoleBadgeStyles,
  displayTone = "",
) {
  return styles[canvasNodeRoleBadgeKind(node, displayTone)];
}

export function nodeToneClass(node: TeamCanvasNode, styles: CanvasNodeToneStyles) {
  return styles[canvasNodeToneKind(node)];
}
