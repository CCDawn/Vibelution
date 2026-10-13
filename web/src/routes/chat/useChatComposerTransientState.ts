import { useCallback, useRef, useState, type Dispatch, type SetStateAction } from "react";
import type { QueryClient } from "@tanstack/react-query";

import { queryKeys } from "../../api/queryKeys";
import type { SessionModelSelection, SessionReferenceAttachment } from "../../api/types";
import {
  clearSessionImageAttachments,
  clearSessionReferenceAttachments,
  type ComposerImageAttachment,
} from "./chatComposerSubmitModel";
import { readStoredSessionDraftState, removeStoredSessionDraft } from "./chatDraftPersistence";
import { setActiveTurnLayerForSession } from "../chatActiveTurnLayer";
import type { ActiveTurnLayersState } from "./activeTurnLayersStore";

export type ChatComposerTransientState = {
  /** Hydrated once from storage; the workbench also reads turn model selections from it. */
  storedDraftState: {
    drafts: Record<string, string>;
    referenceAttachments: Record<string, SessionReferenceAttachment[]>;
    turnModelSelections: Record<string, SessionModelSelection | null>;
  };
  sessionDrafts: Record<string, string>;
  setSessionDrafts: Dispatch<SetStateAction<Record<string, string>>>;
  sessionComposerErrors: Record<string, string>;
  setSessionComposerErrors: Dispatch<SetStateAction<Record<string, string>>>;
  sessionImageAttachments: Record<string, ComposerImageAttachment[]>;
  setSessionImageAttachments: Dispatch<SetStateAction<Record<string, ComposerImageAttachment[]>>>;
  sessionReferenceAttachments: Record<string, SessionReferenceAttachment[]>;
  setSessionReferenceAttachments: Dispatch<SetStateAction<Record<string, SessionReferenceAttachment[]>>>;
  sessionImageUploadPending: Record<string, boolean>;
  setSessionImageUploadPending: Dispatch<SetStateAction<Record<string, boolean>>>;
  imageUploadInFlightRef: React.MutableRefObject<Record<string, boolean>>;
  clearSessionTransientUiState: (sessionId: string) => void;
};

/**
 * Per-session composer transient state (drafts, errors, image/reference
 * attachments, upload flags) with one storage read hydrating text + rich
 * draft fields up front. Extracted from ChatCodingRouteWorkbench with
 * identical behavior.
 */
export function useChatComposerTransientState({
  queryClient,
  setActiveTurnLayersBySession,
}: {
  queryClient: QueryClient;
  setActiveTurnLayersBySession: Dispatch<SetStateAction<ActiveTurnLayersState>>;
}): ChatComposerTransientState {
  const [storedDraftState] = useState(() => readStoredSessionDraftState());
  const [sessionDrafts, setSessionDrafts] = useState<Record<string, string>>(storedDraftState.drafts);
  const [sessionComposerErrors, setSessionComposerErrors] = useState<Record<string, string>>({});
  const [sessionImageAttachments, setSessionImageAttachments] = useState<Record<string, ComposerImageAttachment[]>>({});
  const [sessionReferenceAttachments, setSessionReferenceAttachments] = useState<Record<string, SessionReferenceAttachment[]>>(storedDraftState.referenceAttachments);
  const [sessionImageUploadPending, setSessionImageUploadPending] = useState<Record<string, boolean>>({});
  const imageUploadInFlightRef = useRef<Record<string, boolean>>({});

  const clearSessionTransientUiState = useCallback(
    (sessionId: string) => {
      const normalizedSessionId = String(sessionId || "").trim();
      if (!normalizedSessionId) {
        return;
      }
      setActiveTurnLayersBySession((current) =>
        setActiveTurnLayerForSession(current, normalizedSessionId, undefined)
      );
      setSessionDrafts((current) => {
        const { [normalizedSessionId]: _removed, ...remaining } = current;
        return remaining;
      });
      removeStoredSessionDraft(normalizedSessionId);
      setSessionImageAttachments((current) => clearSessionImageAttachments(current, normalizedSessionId));
      setSessionReferenceAttachments((current) => clearSessionReferenceAttachments(current, normalizedSessionId));
      delete imageUploadInFlightRef.current[normalizedSessionId];
      setSessionImageUploadPending((current) => {
        const { [normalizedSessionId]: _removed, ...remaining } = current;
        return remaining;
      });
      setSessionComposerErrors((current) => {
        const { [normalizedSessionId]: _removed, ...remaining } = current;
        return remaining;
      });
      void queryClient.cancelQueries({ queryKey: queryKeys.session(normalizedSessionId), exact: true });
      queryClient.removeQueries({ queryKey: queryKeys.session(normalizedSessionId), exact: true });
    },
    [queryClient, setActiveTurnLayersBySession],
  );

  return {
    storedDraftState,
    sessionDrafts,
    setSessionDrafts,
    sessionComposerErrors,
    setSessionComposerErrors,
    sessionImageAttachments,
    setSessionImageAttachments,
    sessionReferenceAttachments,
    setSessionReferenceAttachments,
    sessionImageUploadPending,
    setSessionImageUploadPending,
    imageUploadInFlightRef,
    clearSessionTransientUiState,
  };
}
