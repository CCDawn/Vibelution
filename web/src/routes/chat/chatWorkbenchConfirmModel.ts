import type { SessionSummary } from "../../api/types";

export type ChatWorkbenchConfirmRequest =
  | { kind: "delete-session"; session: SessionSummary }
  | { kind: "clear-history"; session: SessionSummary }
  | { kind: "delete-group" }
  | { kind: "reset-group" };

export function sessionConfirmTitle(session: SessionSummary): string {
  return (session.agentDisplayName || session.title || session.id).trim() || session.id;
}
