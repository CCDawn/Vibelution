import type { SessionSummary } from "../../api/types";

export type ChatWorkbenchConfirmRequest =
  | { kind: "delete-session"; session: SessionSummary }
  | { kind: "clear-history"; session: SessionSummary }
  | { kind: "delete-group" }
  | { kind: "reset-group" };

export function sessionConfirmTitle(session: SessionSummary): string {
  // Session title first: the confirm dialog names the conversation being
  // deleted, not the agent behind it (ISS-035).
  return (session.title || session.agentDisplayName || session.id).trim() || session.id;
}
