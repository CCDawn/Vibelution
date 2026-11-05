import { useCallback, useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  guideLauncherAssistantTurn, removeLauncherAssistantQueuedTurn,
  sendNowLauncherAssistantQueuedTurn, updateLauncherAssistantQueuedTurn,
} from "../../api/launcherAssistant";
import type { SessionDetail } from "../../api/types";
import type { ComposerQueueItem } from "../../components/conversation/composerFollowupQueueModel";
import { useComposerFollowupQueue, type ComposerFollowupQueueRuntime } from "../chat/useComposerFollowupQueue";
import { mergeSessionDetailMessageWindow } from "../chatSessionState";

const ASSISTANT_QUEUE_RUNTIME: ComposerFollowupQueueRuntime = {
  detailQueryKey: sessionId => ["launcher-assistant", "detail", sessionId],
  updateSessionQueuedTurn: updateLauncherAssistantQueuedTurn,
  removeSessionQueuedTurn: removeLauncherAssistantQueuedTurn,
  sendNowSessionQueuedTurn: sendNowLauncherAssistantQueuedTurn,
};

/** Only the transport and query namespace differ from the ordinary composer. */
export function useLauncherAssistantFollowupQueue({ sessionId, activeTurnId, detail, enabled, blocked, lang }: {
  sessionId: string;
  activeTurnId: string | undefined;
  detail: SessionDetail | undefined;
  enabled: boolean;
  blocked: boolean;
  lang: "zh" | "en";
}) {
  const queryClient = useQueryClient();
  const [errors, setErrors] = useState<Record<string, string>>({});
  const pendingQueueWithdrawalIdsRef = useRef(new Set<string>());
  const pendingQueueStatusRef = useRef(new Map<string, Promise<boolean>>());
  const describeError = useCallback((error: unknown, fallback: string) =>
    error instanceof Error && error.message ? error.message : fallback, []);
  const isBlocked = useCallback(() => blocked, [blocked]);
  const followupQueue = useMemo<ComposerQueueItem[]>(() => !enabled ? [] : (detail?.queuedTurns ?? []).map(row => ({
    id: row.id,
    text: row.content,
    kind: row.kind || "user",
    status: row.status || "queued",
    position: row.position,
    sendNow: row.sendNow === true,
    attachmentCount: row.attachments?.length ?? 0,
    lastError: row.lastError || "",
    canSteer: row.kind !== "task_notification" && row.kind !== "subagent_message"
      && !row.attachments?.length && !row.references?.length,
  })), [detail?.queuedTurns, enabled]);
  const sessionFollowupQueues = useMemo(() => ({ [sessionId]: followupQueue }), [followupQueue, sessionId]);
  const sessionGuidanceMutation = useMutation({
    async mutationFn({ sessionId: targetSessionId, content, steeredQueuedTurnId }: {
      sessionId: string; content: string; mode: "safe"; steeredQueuedTurnId: string;
    }) {
      try {
        const next = await guideLauncherAssistantTurn(targetSessionId, content, "safe");
        queryClient.setQueryData<SessionDetail>(ASSISTANT_QUEUE_RUNTIME.detailQueryKey(targetSessionId), current => {
          const merged = mergeSessionDetailMessageWindow(current, next);
          return { ...merged, queuedTurns: (merged.queuedTurns ?? []).filter(row => row.id !== steeredQueuedTurnId) };
        });
      } catch (error) {
        setErrors(current => ({ ...current, [targetSessionId]: describeError(error,
          lang === "zh" ? "立即引导排队消息失败" : "Failed to steer the queued message") }));
        throw error;
      }
    },
  });
  const actions = useComposerFollowupQueue({
    runtime: ASSISTANT_QUEUE_RUNTIME,
    queryClient,
    activeSessionId: enabled && !blocked && detail?.id === sessionId ? sessionId : undefined,
    activeTurnId,
    detail,
    lang,
    describeError,
    setSessionComposerErrors: setErrors,
    isModelParametersSavePendingNow: isBlocked,
    sessionFollowupQueues,
    sessionGuidanceMutation,
    pendingQueueWithdrawalIdsRef,
    pendingQueueStatusRef,
  });
  const clearError = useCallback(() => setErrors(current => current[sessionId]
    ? { ...current, [sessionId]: "" } : current), [sessionId]);
  return { ...actions, followupQueue, error: errors[sessionId] || "", clearError,
    guidancePending: sessionGuidanceMutation.isPending };
}
