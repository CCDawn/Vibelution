import { createContext, useContext, useEffect, useRef } from "react";
import type { AssistantConversationTurn, ConversationMessage } from "../../api/types";

/** UI requests only. Native Session and the composer remain the authorities. */
export type FinancialDraftRequest = { id: number; sessionId: string; text: string; submit?: boolean };
export type FinancialSessionView = {
  sessionId: string;
  title: string;
  status: string;
  busy: boolean;
  stopping: boolean;
  messages?: readonly ConversationMessage[];
  phase?: string;
  error?: string;
  submitPending?: boolean;
  transcriptPending?: boolean;
  approvalPending?: boolean;
};
type FinancialResearchBridgeValue = {
  agentId: string;
  draftRequest: FinancialDraftRequest | null;
  onSessionView: (view: FinancialSessionView) => void;
  onDraftSubmitted?: (id: number) => void;
  onActiveTurn?: (sessionId: string, turn: AssistantConversationTurn | null) => void;
};
export const FinancialResearchBridgeContext = createContext<FinancialResearchBridgeValue | null>(null);

export function useFinancialResearchSessionBridge({
  sessionId, agentId, title, status, busy, stopping, messages, phase, error, submitPending, transcriptPending, approvalPending,
  onComposerChange, onFocusComposer, composerValue, onSubmit,
}: FinancialSessionView & {
  agentId?: string;
  onComposerChange: (text: string) => void;
  onFocusComposer: (sessionId: string) => void;
  composerValue?: string;
  onSubmit?: () => void;
}) {
  const bridge = useContext(FinancialResearchBridgeContext);
  const consumedRequest = useRef<number | null>(null);
  const submittedRequest = useRef<number | null>(null);
  const authorized = Boolean(bridge && sessionId && agentId === bridge.agentId);
  const request = bridge?.draftRequest;
  useEffect(() => {
    if (!authorized || !request || request.sessionId !== sessionId || consumedRequest.current === request.id) return;
    consumedRequest.current = request.id;
    onComposerChange(request.text);
    onFocusComposer(sessionId);
  }, [authorized, onComposerChange, onFocusComposer, request, sessionId]);
  const submitted = bridge?.onDraftSubmitted;
  useEffect(() => {
    if (!authorized || !request?.submit || request.sessionId !== sessionId || submittedRequest.current === request.id
      || consumedRequest.current !== request.id || composerValue !== request.text || busy || stopping || submitPending || transcriptPending || !onSubmit) return;
    // Submit only after the native composer has committed this exact draft.
    // The native mutation remains the only writer and owns its submission gate.
    submittedRequest.current = request.id;
    onSubmit();
    submitted?.(request.id);
  }, [authorized, busy, composerValue, onSubmit, request, sessionId, stopping, submitPending, submitted, transcriptPending]);
  const publish = bridge?.onSessionView;
  useEffect(() => {
    if (authorized) publish?.({ sessionId, title, status, busy, stopping, messages, phase, error, submitPending, transcriptPending, approvalPending });
  }, [approvalPending, authorized, busy, error, messages, phase, publish, sessionId, status, stopping, submitPending, title, transcriptPending]);
  return bridge !== null;
}
