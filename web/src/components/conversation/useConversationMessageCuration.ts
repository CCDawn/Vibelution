import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchSessionMessageCuration, isFetchJsonHttpError, setSessionMessageCuration } from "../../api/chat";
import { queryKeys } from "../../api/queryKeys";
import type { SessionMessageCurationAction } from "../../api/types";
import type { TranslationKey } from "../../i18n/dictionaryTypes";
import {
  applyOptimisticCuration,
  buildMessageCurationMap,
  resolveMessageCurationState,
  type MessageCurationDecision,
} from "./conversationMessageCuration";

const CURATION_FEEDBACK_MS = 3000;

export type ConversationMessageCurationFeedback = {
  messageId: string;
  action: SessionMessageCurationAction;
  message: string;
};

export type UseConversationMessageCurationInput = {
  sessionId: string;
  companionMode: boolean;
  t: (key: TranslationKey) => string;
};

export type UseConversationMessageCurationResult = {
  messageCurationMap: Map<string, MessageCurationDecision>;
  curationFeedback: ConversationMessageCurationFeedback | null;
  handleCurateMessage: (messageId: string, action: SessionMessageCurationAction) => void;
};

/**
 * In-chat SFT curation (like/dislike) extracted from ConversationView.
 * Server map plus an optimistic overlay for instant button feedback; a failed
 * POST rolls the overlay entry back and the 409 copy surfaces briefly on the
 * button title. A session switch drops both so decisions do not inherit.
 * The query stays disabled without a session id or in companion mode.
 */
export function useConversationMessageCuration({
  sessionId,
  companionMode,
  t,
}: UseConversationMessageCurationInput): UseConversationMessageCurationResult {
  // In-chat SFT curation: server map + optimistic overlay for instant button
  // feedback; a failed POST rolls the overlay entry back (ZCode like/dislike
  // rollback pattern) and the 409 copy surfaces briefly on the button title.
  const queryClient = useQueryClient();
  const [curationOverrides, setCurationOverrides] = useState<Map<string, MessageCurationDecision>>(new Map());
  const [curationFeedback, setCurationFeedback] = useState<ConversationMessageCurationFeedback | null>(null);
  const curationFeedbackTimerRef = useRef<number | null>(null);
  const messageCurationQuery = useQuery({
    queryKey: queryKeys.sessionMessageCuration(sessionId),
    queryFn: () => fetchSessionMessageCuration(sessionId),
    enabled: Boolean(sessionId) && !companionMode,
  });
  const serverMessageCurationMap = useMemo(
    () => buildMessageCurationMap(messageCurationQuery.data?.items ?? []),
    [messageCurationQuery.data],
  );
  const messageCurationMap = useMemo(() => {
    if (curationOverrides.size === 0) {
      return serverMessageCurationMap;
    }
    return new Map([...serverMessageCurationMap, ...curationOverrides]);
  }, [curationOverrides, serverMessageCurationMap]);

  // A session switch must not inherit the previous session's optimistic writes.
  useEffect(() => {
    setCurationOverrides(new Map());
    setCurationFeedback(null);
  }, [sessionId]);

  /** Bounded visible feedback for a rejected curation click (~3s on the title). */
  function showCurationFeedback(messageId: string, action: SessionMessageCurationAction, message: string) {
    setCurationFeedback({ messageId, action, message });
    if (curationFeedbackTimerRef.current !== null) {
      window.clearTimeout(curationFeedbackTimerRef.current);
    }
    curationFeedbackTimerRef.current = window.setTimeout(() => {
      curationFeedbackTimerRef.current = null;
      setCurationFeedback((current) => (current?.messageId === messageId ? null : current));
    }, CURATION_FEEDBACK_MS);
  }

  function handleCurateMessage(messageId: string, action: SessionMessageCurationAction) {
    if (!sessionId || resolveMessageCurationState(messageCurationMap, messageId) === action) {
      return;
    }
    // Optimistic flip; the query invalidation restores server authority on
    // success and the overlay entry is dropped again on failure (rollback).
    setCurationOverrides((current) => applyOptimisticCuration(current, messageId, action));
    void setSessionMessageCuration(sessionId, messageId, action)
      .then(() => {
        setCurationOverrides((current) => {
          if (!current.has(messageId)) {
            return current;
          }
          const next = new Map(current);
          next.delete(messageId);
          return next;
        });
        void queryClient.invalidateQueries({ queryKey: queryKeys.sessionMessageCuration(sessionId) });
      })
      .catch((error) => {
        setCurationOverrides((current) => {
          if (!current.has(messageId)) {
            return current;
          }
          const next = new Map(current);
          next.delete(messageId);
          return next;
        });
        showCurationFeedback(
          messageId,
          action,
          isFetchJsonHttpError(error) && error.message ? error.message : t("curationActionFailed"),
        );
      });
  }

  return {
    messageCurationMap,
    curationFeedback,
    handleCurateMessage,
  };
}
