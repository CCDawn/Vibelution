import { useEffect, useRef, useState } from "react";
import type { SessionDetail } from "../../api/types";
import { resolveSessionActivity, type SessionActivitySource } from "../sessionActivityState";

export const PET_COMPLETION_DURATION_MS = 4_000;
const MAX_OBSERVED_TERMINALS = 64;
type CompletionSource = SessionActivitySource & Partial<Pick<SessionDetail, "id" | "provisionalTranscript">>;
type Completion = { sessionId: string; turnId: string };

/** A brief visual acknowledgement of a newly settled native Turn, never business acceptance. */
export function usePetCompletion(sessionId: string, source: CompletionSource | undefined, enabled: boolean): boolean {
  const observed = useRef<{ sessionId: string; initialized: boolean; terminals: Set<string> }>({
    sessionId: "", initialized: false, terminals: new Set(),
  });
  const [pulse, setPulse] = useState<Completion | null>(null);
  useEffect(() => {
    if (observed.current.sessionId !== sessionId) {
      observed.current = { sessionId, initialized: false, terminals: new Set() };
      setPulse(null);
    }
    if (!enabled) setPulse(null);
    if (!sessionId || source?.id !== sessionId || source.provisionalTranscript) return;
    const terminalTurnId = source.lastTurnTerminalTurnId?.trim() || "";
    const rememberTerminal = () => {
      if (!terminalTurnId) return;
      observed.current.terminals.add(terminalTurnId);
      if (observed.current.terminals.size > MAX_OBSERVED_TERMINALS) {
        observed.current.terminals.delete(observed.current.terminals.values().next().value!);
      }
    };
    if (!observed.current.initialized) {
      // The first authoritative snapshot is history, including an old success.
      observed.current.initialized = true;
      rememberTerminal();
      return;
    }
    const activity = resolveSessionActivity(source);
    if (activity.execution !== "settled") {
      const activeTurnId = source.activeTurnId?.trim();
      // A different live owner proves this terminal already belongs to history.
      if (activeTurnId && terminalTurnId !== activeTurnId) rememberTerminal();
      setPulse(null);
      return;
    }
    if (!terminalTurnId || observed.current.terminals.has(terminalTurnId)) return;
    rememberTerminal();
    setPulse(enabled && activity.outcome === "completed" ? { sessionId, turnId: terminalTurnId } : null);
  }, [sessionId, source, enabled]);
  useEffect(() => {
    if (!pulse) return;
    const timer = window.setTimeout(() => setPulse(null), PET_COMPLETION_DURATION_MS);
    return () => window.clearTimeout(timer);
  }, [pulse]);
  return Boolean(enabled && pulse?.sessionId === sessionId && source?.id === sessionId
    && !source.provisionalTranscript && pulse.turnId === source.lastTurnTerminalTurnId
    && resolveSessionActivity(source).outcome === "completed");
}
