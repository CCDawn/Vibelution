/**
 * Follow-up queue intents: edit, withdraw, steer, reorder, pause, and send-now.
 * Called from the composer submit actions at the original hook position.
 */
import { useCallback, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import type { QueryClient } from "@tanstack/react-query";

import {
  removeSessionQueuedTurn,
  sendNowSessionQueuedTurn,
  updateSessionQueuedTurn,
} from "../../api/chat";
import { queryKeys } from "../../api/queryKeys";
import type { SessionDetail, SessionQueuedTurn } from "../../api/types";
import type { ComposerQueueItem } from "../../components/conversation/composerFollowupQueueModel";
import { resolveSessionStopTurnId } from "./chatStopTurnModel";

type QueuedTurnWithdrawSnapshot = {
  row: SessionQueuedTurn;
  index: number;
};

/**
 * Rollback for an optimistically withdrawn queued turn: re-insert the row at
 * its pre-intent slot into the CURRENT rows instead of wholesale-restoring the
 * snapshot, so authoritative rows that landed while the DELETE was in flight
 * (a reorder, pause or steer rebase) are not clobbered. Mirrors
 * restoreOptimisticallyArchivedAgent in useChatAgentArchiveQueue.
 */
function restoreQueuedTurnIntoRows(rows: SessionQueuedTurn[], snapshot: QueuedTurnWithdrawSnapshot): SessionQueuedTurn[] {
  if (rows.some((row) => row.id === snapshot.row.id)) {
    return rows;
  }
  const next = [...rows];
  next.splice(Math.max(0, Math.min(snapshot.index, next.length)), 0, snapshot.row);
  return next;
}

/**
 * Rollback for an optimistically reordered queue: recover the pre-drag order
 * while keeping current membership — rows authoritative state removed while
 * the PATCH was in flight stay removed, and rows added in the meantime stay
 * (at the tail).
 */
function restoreQueuedTurnOrder(previousRows: SessionQueuedTurn[], currentRows: SessionQueuedTurn[]): SessionQueuedTurn[] {
  const previousIds = new Set(previousRows.map((row) => row.id));
  const appended = currentRows.filter((row) => !previousIds.has(row.id));
  const restored = previousRows.filter((row) => currentRows.some((current) => current.id === row.id));
  if (
    !appended.length
    && restored.length === currentRows.length
    && restored.every((row, index) => currentRows[index]?.id === row.id)
  ) {
    return currentRows;
  }
  return [...restored, ...appended];
}


export type UseComposerFollowupQueueInput = {
  queryClient: QueryClient;
  activeSessionId: string | null | undefined;
  activeTurnId: string | undefined;
  detail: SessionDetail | undefined;
  lang: "zh" | "en";
  describeError: (error: unknown, fallback: string) => string;
  setSessionComposerErrors: Dispatch<SetStateAction<Record<string, string>>>;
  isModelParametersSavePendingNow: () => boolean;
  sessionFollowupQueues: Record<string, ComposerQueueItem[]>;
  sessionGuidanceMutation: {
    mutateAsync: (variables: {
      sessionId: string;
      content: string;
      mode: "safe";
      steeredQueuedTurnId: string;
    }) => Promise<unknown>;
  };
  pendingQueueWithdrawalIdsRef: MutableRefObject<Set<string>>;
  pendingQueueStatusRef: MutableRefObject<Map<string, Promise<boolean>>>;
};

export function useComposerFollowupQueue({
  queryClient,
  activeSessionId,
  activeTurnId,
  detail,
  lang,
  describeError,
  setSessionComposerErrors,
  isModelParametersSavePendingNow,
  sessionFollowupQueues,
  sessionGuidanceMutation,
  pendingQueueWithdrawalIdsRef,
  pendingQueueStatusRef,
}: UseComposerFollowupQueueInput) {
  const syncQueuedTurnsIntoDetail = useCallback((sessionId: string, rows: SessionQueuedTurn[]) => {
    queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detailState) =>
      detailState ? { ...detailState, queuedTurns: rows } : detailState,
    );
  }, [queryClient]);

  const reportQueuedTurnError = useCallback((sessionId: string, error: unknown, fallback: string) => {
    setSessionComposerErrors((current) => ({
      ...current,
      [sessionId]: describeError(error, fallback),
    }));
  }, [describeError, setSessionComposerErrors]);

  const handleFollowupQueueUpdate = useCallback((id: string, text: string) => {
    const sessionId = activeSessionId;
    const content = text.trim();
    if (!sessionId || isModelParametersSavePendingNow()) {
      return;
    }
    // Optimistic edit (same pending-intent style as withdraw): the new text
    // paints at save time while status/pause metadata stay untouched; the
    // PATCH response rebases the authoritative rows and a failure restores
    // the pre-edit text without clobbering fields that moved meanwhile.
    const rowsAtIntent = queryClient.getQueryData<SessionDetail>(queryKeys.session(sessionId))?.queuedTurns ?? [];
    const snapshotRow = rowsAtIntent.find((row) => row.id === id);
    if (!content && !snapshotRow?.attachments?.length) return;
    if (snapshotRow) {
      queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detailState) =>
        detailState
          ? {
            ...detailState,
            queuedTurns: (detailState.queuedTurns ?? []).map((row) =>
              row.id === id ? { ...row, content } : row,
            ),
          }
          : detailState,
      );
    }
    void updateSessionQueuedTurn(sessionId, id, { content })
      .then((rows) => syncQueuedTurnsIntoDetail(sessionId, rows))
      .catch((error) => {
        if (snapshotRow) {
          queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detailState) => {
            if (!detailState) {
              return detailState;
            }
            let reverted = false;
            const queuedTurns = (detailState.queuedTurns ?? []).map((row) => {
              // Roll back only this intent: a row edited again while the
              // failed PATCH was in flight keeps its newer text.
              if (row.id !== id || row.content !== content) {
                return row;
              }
              reverted = true;
              return { ...row, content: snapshotRow.content };
            });
            return reverted ? { ...detailState, queuedTurns } : detailState;
          });
        }
        reportQueuedTurnError(
          sessionId,
          error,
          lang === "zh" ? "修改排队消息失败" : "Failed to update the queued message",
        );
      });
  }, [activeSessionId, isModelParametersSavePendingNow, lang, queryClient, reportQueuedTurnError, syncQueuedTurnsIntoDetail]);

  const handleFollowupQueueRemove = useCallback((id: string) => {
    const sessionId = activeSessionId;
    if (!sessionId || pendingQueueWithdrawalIdsRef.current.has(id)) {
      return;
    }
    // Optimistic withdraw (ZCode pending-intent style): the row leaves the bar
    // at click time; the DELETE response only rebases the authoritative rows.
    const rowsAtIntent = queryClient.getQueryData<SessionDetail>(queryKeys.session(sessionId))?.queuedTurns ?? [];
    const snapshotIndex = rowsAtIntent.findIndex((row) => row.id === id);
    const snapshotRow = snapshotIndex >= 0 ? rowsAtIntent[snapshotIndex] : undefined;
    if (!snapshotRow) {
      return;
    }
    pendingQueueWithdrawalIdsRef.current.add(id);
    queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detailState) =>
      detailState
        ? { ...detailState, queuedTurns: (detailState.queuedTurns ?? []).filter((row) => row.id !== id) }
        : detailState,
    );
    void removeSessionQueuedTurn(sessionId, id)
      .then((rows) => syncQueuedTurnsIntoDetail(sessionId, rows))
      .catch((error) => {
        // Roll back only this intent; authoritative rows that landed meanwhile stay.
        queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detailState) =>
          detailState
            ? {
              ...detailState,
              queuedTurns: restoreQueuedTurnIntoRows(detailState.queuedTurns ?? [], { row: snapshotRow, index: snapshotIndex }),
            }
            : detailState,
        );
        reportQueuedTurnError(
          sessionId,
          error,
          lang === "zh" ? "撤回排队消息失败" : "Failed to withdraw the queued message",
        );
      })
      .finally(() => {
        pendingQueueWithdrawalIdsRef.current.delete(id);
      });
  }, [activeSessionId, lang, queryClient, reportQueuedTurnError, syncQueuedTurnsIntoDetail]);

  // Steering sends one queued item into the running turn as safe guidance and
  // then withdraws it from the server queue; items carrying attachments or
  // references stay queued because guidance cannot carry them.
  const handleFollowupQueueSteer = useCallback((id: string) => {
    const sessionId = activeSessionId;
    if (!sessionId || isModelParametersSavePendingNow() || pendingQueueWithdrawalIdsRef.current.has(id)) {
      return;
    }
    const item = (sessionFollowupQueues[sessionId] ?? []).find((entry) => entry.id === id);
    if (!item) {
      return;
    }
    if (item.canSteer === false) {
      setSessionComposerErrors((current) => ({
        ...current,
        [sessionId]: lang === "zh"
          ? "这条排队消息带图片或会话引用，无法立即引导；本轮结束后会自动发送。"
          : "This queued message carries images or session references, so it cannot steer the running turn. It sends automatically after the turn ends.",
      }));
      return;
    }
    // Optimistic steer (same pending-intent style as withdraw): the row leaves
    // the bar at click time; guidance + DELETE converge the authoritative rows
    // and either failure rolls the row back into its pre-intent slot. The
    // shared pending set also drops a second click while this steer is still
    // in flight.
    const rowsAtIntent = queryClient.getQueryData<SessionDetail>(queryKeys.session(sessionId))?.queuedTurns ?? [];
    const snapshotIndex = rowsAtIntent.findIndex((row) => row.id === id);
    const snapshotRow = snapshotIndex >= 0 ? rowsAtIntent[snapshotIndex] : undefined;
    const restoreSteeredRow = () => {
      if (!snapshotRow) {
        return;
      }
      queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detailState) =>
        detailState
          ? {
            ...detailState,
            queuedTurns: restoreQueuedTurnIntoRows(detailState.queuedTurns ?? [], { row: snapshotRow, index: snapshotIndex }),
          }
          : detailState,
      );
    };
    pendingQueueWithdrawalIdsRef.current.add(id);
    if (snapshotRow) {
      queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detailState) =>
        detailState
          ? { ...detailState, queuedTurns: (detailState.queuedTurns ?? []).filter((row) => row.id !== id) }
          : detailState,
      );
    }
    let guidanceAccepted = false;
    void sessionGuidanceMutation
      .mutateAsync({ sessionId, content: item.text, mode: "safe", steeredQueuedTurnId: id })
      .then(() => {
        guidanceAccepted = true;
        return removeSessionQueuedTurn(sessionId, id);
      })
      .then((rows) => syncQueuedTurnsIntoDetail(sessionId, rows))
      .catch((error) => {
        // Roll back only this intent; authoritative rows that landed meanwhile
        // stay. The guidance mutation surfaces its own copy on its failure, so
        // only the withdraw step reports here.
        restoreSteeredRow();
        if (guidanceAccepted) {
          reportQueuedTurnError(
            sessionId,
            error,
            lang === "zh" ? "立即引导排队消息失败" : "Failed to steer the queued message",
          );
        }
      })
      .finally(() => {
        pendingQueueWithdrawalIdsRef.current.delete(id);
      });
  }, [
    activeSessionId,
    isModelParametersSavePendingNow,
    lang,
    queryClient,
    reportQueuedTurnError,
    sessionFollowupQueues,
    sessionGuidanceMutation,
    setSessionComposerErrors,
    syncQueuedTurnsIntoDetail,
  ]);

  const handleFollowupQueueMove = useCallback((fromIndex: number, toIndex: number) => {
    const sessionId = activeSessionId;
    const rows = detail?.queuedTurns ?? [];
    const from = rows[fromIndex];
    const target = rows[toIndex];
    if (!sessionId || fromIndex === toIndex || !from || !target) {
      return;
    }
    // Optimistic reorder (ZCode pending-intent style): the row lands at its
    // target slot at drop time; the PATCH response rebases the authoritative
    // rows and a failure rolls back to the pre-drag order.
    const rowsAtIntent = rows;
    const optimisticRows = [...rowsAtIntent];
    optimisticRows.splice(fromIndex, 1);
    optimisticRows.splice(toIndex, 0, from);
    queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detailState) =>
      detailState ? { ...detailState, queuedTurns: optimisticRows } : detailState,
    );
    void updateSessionQueuedTurn(sessionId, from.id, { position: target.position })
      .then((next) => syncQueuedTurnsIntoDetail(sessionId, next))
      .catch((error) => {
        queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detailState) =>
          detailState
            ? { ...detailState, queuedTurns: restoreQueuedTurnOrder(rowsAtIntent, detailState.queuedTurns ?? []) }
            : detailState,
        );
        reportQueuedTurnError(
          sessionId,
          error,
          lang === "zh" ? "调整排队顺序失败" : "Failed to reorder the queue",
        );
      });
  }, [activeSessionId, detail?.queuedTurns, lang, queryClient, reportQueuedTurnError, syncQueuedTurnsIntoDetail]);

  // Pausing holds one row out of draining (the server skips paused rows);
  // resuming re-queues it at the tail, mirroring the server semantics.
  const handleFollowupQueueTogglePause = useCallback((id: string, paused: boolean) => {
    const sessionId = activeSessionId;
    const statusKey = `${sessionId}:${id}`;
    if (!sessionId || pendingQueueStatusRef.current.has(statusKey)) {
      return;
    }
    const saving = updateSessionQueuedTurn(sessionId, id, { status: paused ? "paused" : "queued" })
      .then((rows) => { syncQueuedTurnsIntoDetail(sessionId, rows); return true; })
      .catch((error) => {
        reportQueuedTurnError(sessionId, error, paused
          ? (lang === "zh" ? "暂停排队消息失败" : "Failed to pause the queued message")
          : (lang === "zh" ? "恢复排队消息失败" : "Failed to resume the queued message"));
        return false;
      })
      .finally(() => { pendingQueueStatusRef.current.delete(statusKey); });
    pendingQueueStatusRef.current.set(statusKey, saving);
  }, [activeSessionId, lang, reportQueuedTurnError, syncQueuedTurnsIntoDetail]);

  // Send-now (Codex sendQueuedNow parity): pin one queued row at the head and
  // stop the running turn; the server keeps the row persisted in the queue so
  // nothing is lost, and the drain submits the pinned row first after the stop
  // settles.
  const handleFollowupQueueSendNow = useCallback((id: string) => {
    const sessionId = activeSessionId;
    if (!sessionId || pendingQueueWithdrawalIdsRef.current.has(id)) {
      return;
    }
    const expectedTurnId = resolveSessionStopTurnId(detail, activeTurnId);
    const promote = () => {
      if (pendingQueueWithdrawalIdsRef.current.has(id)) return;
      const rowsAtIntent = queryClient.getQueryData<SessionDetail>(queryKeys.session(sessionId))?.queuedTurns ?? [];
      if (!rowsAtIntent.some((row) => row.id === id)) {
        return;
      }
      // Optimistic pin (same pending-intent style as the other queue intents):
      // the row paints at the head with the send-now flag at click time; the
      // API response rebases the authoritative rows and a rejected stop (the
      // running turn changed or settled meanwhile) restores the pre-click order.
      const optimisticRows = rowsAtIntent
        .map((row) => (row.sendNow ? { ...row, sendNow: false } : row))
        .filter((row) => row.id !== id);
      const snapshotRow = rowsAtIntent.find((row) => row.id === id);
      if (snapshotRow) {
        optimisticRows.unshift({ ...snapshotRow, sendNow: true });
      }
      pendingQueueWithdrawalIdsRef.current.add(id);
      queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detailState) =>
        detailState ? { ...detailState, queuedTurns: optimisticRows } : detailState,
      );
      const pinnedRows = queryClient.getQueryData<SessionDetail>(queryKeys.session(sessionId))?.queuedTurns;
      void sendNowSessionQueuedTurn(sessionId, id, { expectedTurnId: expectedTurnId || undefined })
        .then((result) => syncQueuedTurnsIntoDetail(sessionId, result.queuedTurns))
        .catch((error) => {
        // Restore our order only while the exact optimistic cache still owns it.
        // A later snapshot owns its own order and fields; only our target pin is removed.
          queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detailState) =>
            detailState
              ? {
                ...detailState,
                queuedTurns: (detailState.queuedTurns === pinnedRows
                  ? restoreQueuedTurnOrder(rowsAtIntent, detailState.queuedTurns ?? [])
                  : detailState.queuedTurns ?? []).map(row =>
                  row.id === id && row.sendNow === true ? { ...row, sendNow: snapshotRow?.sendNow } : row,
                ),
              }
              : detailState,
          );
          reportQueuedTurnError(
            sessionId,
            error,
            lang === "zh" ? "立即发送排队消息失败" : "Failed to send the queued message now",
          );
        })
        .finally(() => {
          pendingQueueWithdrawalIdsRef.current.delete(id);
        });
    };
    const pendingStatus = pendingQueueStatusRef.current.get(`${sessionId}:${id}`);
    if (pendingStatus) {
      // A visible resume intent is not yet an acknowledged server status.
      // Keep the original turn identity while waiting; never stop a newer turn.
      void pendingStatus.then(saved => { if (saved) promote(); });
    } else {
      promote();
    }
  }, [activeSessionId, activeTurnId, detail, lang, queryClient, reportQueuedTurnError, syncQueuedTurnsIntoDetail]);


  return {
    handleFollowupQueueUpdate,
    handleFollowupQueueRemove,
    handleFollowupQueueSteer,
    handleFollowupQueueMove,
    handleFollowupQueueTogglePause,
    handleFollowupQueueSendNow,
  };
}
