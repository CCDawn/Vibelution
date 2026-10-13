import type { SessionSummary } from "../../api/types";
import type { ChatComposerSessionReferenceOption } from "../chat/ChatComposerPlusMenu";
import { buildSessionReferencePayload } from "../chat/chatComposerSubmitModel";
import { isFinancialSession } from "./financialResearchModel";

/** Project the existing assistant-scoped directory into native composer references. */
export function financeSessionReferences(
  sessions: SessionSummary[], agentId: string, currentSessionId: string, displayName: string,
): ChatComposerSessionReferenceOption[] {
  if (!agentId) return [];
  const seen = new Set<string>();
  return sessions.filter((session) => {
    if (!session.id || session.id === currentSessionId || seen.has(session.id) || !isFinancialSession(session, agentId)) return false;
    seen.add(session.id);
    return true;
  }).map((session) => {
    const reference = buildSessionReferencePayload(session, displayName, session.taskSummary);
    return { id: session.id, title: reference.title || session.id, meta: (session.updatedAt || session.lastActive || "").slice(0, 10), reference };
  });
}
