import { createContext, useContext, useEffect, useRef } from "react";

/** UI requests only. Native Session and the composer remain the authorities. */
export type FinancialDraftRequest = { id: number; sessionId: string; text: string };
export type FinancialSessionView = {
  sessionId: string;
  title: string;
  status: string;
  busy: boolean;
  stopping: boolean;
};
type FinancialResearchBridgeValue = {
  agentId: string;
  draftRequest: FinancialDraftRequest | null;
  onSessionView: (view: FinancialSessionView) => void;
};
export const FinancialResearchBridgeContext = createContext<FinancialResearchBridgeValue | null>(null);

export function useFinancialResearchSessionBridge({
  sessionId, agentId, title, status, busy, stopping, onComposerChange, onFocusComposer,
}: FinancialSessionView & {
  agentId?: string;
  onComposerChange: (text: string) => void;
  onFocusComposer: (sessionId: string) => void;
}) {
  const bridge = useContext(FinancialResearchBridgeContext);
  const consumedRequest = useRef<number | null>(null);
  const authorized = Boolean(bridge && sessionId && agentId === bridge.agentId);
  const request = bridge?.draftRequest;
  useEffect(() => {
    if (!authorized || !request || request.sessionId !== sessionId || consumedRequest.current === request.id) return;
    consumedRequest.current = request.id;
    onComposerChange(request.text);
    onFocusComposer(sessionId);
  }, [authorized, onComposerChange, onFocusComposer, request, sessionId]);
  const publish = bridge?.onSessionView;
  useEffect(() => {
    if (authorized) publish?.({ sessionId, title, status, busy, stopping });
  }, [authorized, busy, publish, sessionId, status, stopping, title]);
  return bridge !== null;
}
