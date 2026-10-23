import { useCallback, useRef } from "react";
import type { QueryClient } from "@tanstack/react-query";
import type { SessionDetail, SessionModelSelection } from "../../api/types";
import { queryKeys } from "../../api/queryKeys";
import { createClientSubmissionId } from "../chatSessionState";
import { chatStreamPerformanceNowMs } from "./chatCodingRouteViewModel";
import { continuationSnapshotKey, resolveConversationContinuation } from "./conversationContinuationModel";
import type { ChatComposerTurnMutations } from "./useChatComposerTurnMutations";

type ContinueOptions = {
  queryClient: QueryClient;
  activeSessionId: string | null | undefined;
  detail: SessionDetail | undefined;
  activeDraftEffective: string;
  hasAttachments: boolean;
  hasReferences: boolean;
  blocked: boolean;
  isModelParametersSavePending: () => boolean;
  submitTurnMutation: ChatComposerTurnMutations["submitTurnMutation"];
  mentalModelEnabled: boolean;
  runtimeStatusEnabled: boolean;
  modelSelection?: SessionModelSelection | null;
};

export function useChatContinueTurn(options: ContinueOptions): () => void {
  const attempts = useRef(new Map<string, { key: string; id: string; pending: boolean; accepted: boolean }>());
  return useCallback(() => {
    if (options.blocked || options.isModelParametersSavePending() || options.activeDraftEffective.trim()
      || options.hasAttachments || options.hasReferences || !options.activeSessionId) return;
    const sessionId = options.activeSessionId;
    const expected = resolveConversationContinuation(options.detail, sessionId);
    const cached = options.queryClient.getQueryData<SessionDetail>(queryKeys.session(sessionId));
    const current = resolveConversationContinuation(cached ?? options.detail, sessionId);
    if (!expected || !current || continuationSnapshotKey(expected) !== continuationSnapshotKey(current)) return;
    const key = continuationSnapshotKey(expected);
    let attempt = attempts.current.get(sessionId);
    if (attempt?.pending || (attempt?.key === key && attempt.accepted)) return;
    if (!attempt || attempt.key !== key) {
      attempt = { key, id: createClientSubmissionId(sessionId), pending: false, accepted: false };
      attempts.current.set(sessionId, attempt);
    }
    attempt.pending = true;
    const submittedAttempt = attempt;
    void options.submitTurnMutation.mutateAsync({
      sessionId,
      clientSubmissionId: attempt.id,
      content: "继续",
      continuation: expected,
      mentalModelEnabled: options.mentalModelEnabled,
      runtimeStatusEnabled: options.runtimeStatusEnabled,
      modelSelection: options.modelSelection ?? undefined,
      composerAttachments: [],
      references: [],
      requestStartedAtMs: chatStreamPerformanceNowMs(),
      queuedBehindActiveTurn: false,
    }).then(() => { submittedAttempt.accepted = true; })
      // Native submit owns error copy and acceptance readback. An uncertain
      // request retains its submission id so a later click cannot double-send.
      .catch(() => undefined)
      .finally(() => { submittedAttempt.pending = false; });
  }, [options.activeSessionId, options.activeDraftEffective, options.blocked, options.detail,
    options.hasAttachments, options.hasReferences, options.isModelParametersSavePending,
    options.mentalModelEnabled, options.modelSelection, options.queryClient, options.runtimeStatusEnabled, options.submitTurnMutation.mutateAsync]);
}
