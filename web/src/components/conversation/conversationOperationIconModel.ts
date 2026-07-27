/**
 * Operation icon kind pure classifier (claim: process timeline icon mapping).
 * Pure: no React / DOM — shell maps kinds to lucide nodes.
 */
import type { AgentMessageOperationKind } from "./agentMessageOperations";

export type ConversationOperationIconKind =
  | "thought"
  | "mental"
  | "search"
  | "link"
  | "terminal"
  | "tool";

export function conversationOperationIconKind(
  kind: AgentMessageOperationKind,
  label: string,
): ConversationOperationIconKind {
  const normalized = label.trim().toLowerCase();
  if (kind === "thought") {
    return "thought";
  }
  if (kind === "mental") {
    return "mental";
  }
  if (normalized.includes("search") || normalized.includes("搜索")) {
    return "search";
  }
  if (normalized.includes("http") || normalized.includes("访问") || normalized.includes("open")) {
    return "link";
  }
  if (
    normalized.includes("exec")
    || normalized.includes("command")
    || normalized.includes("shell")
    || normalized.includes("powershell")
    || normalized.includes("npm")
    || normalized.includes("pytest")
    || normalized.includes("命令")
  ) {
    return "terminal";
  }
  return "tool";
}
