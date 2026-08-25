/**
 * Teams canvas node role/status pure classification (structure M9).
 * Style class mapping stays in the shell (or a styles map inject).
 */
import type { TeamCanvasNode } from "../../api/types";
import { canvasNodeStatusLabel } from "./teamRouteShellModel";

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

/**
 * Node card agent line: resolved agent display name with stored-name fallbacks;
 * nodes without a resolvable agent show the localized binding status instead of
 * raw machine status strings.
 */
export function canvasNodeAgentLine(
  node: TeamCanvasNode,
  displayName: string | undefined,
  lang: "zh" | "en",
) {
  const name = String(displayName || "").trim()
    || String(node.agentName || "").trim();
  if (name) {
    return name;
  }
  // agentCode 是机器标识（如 agent-20260722-220511-556053），不直接透出；
  // 已绑定但无名称时显示"未命名 + 短后缀"，未绑定时走本地化状态。
  const code = String(node.agentCode || "").trim();
  if (node.agentId && code) {
    const suffix = code.slice(-4);
    return lang === "zh" ? `未命名 Agent ${suffix}` : `Unnamed agent ${suffix}`;
  }
  return canvasNodeStatusLabel(node, lang);
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
