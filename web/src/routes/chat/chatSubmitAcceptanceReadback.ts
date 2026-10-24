import { sessionOwnsExecution } from "../sessionActivityState";
/**
 * Submit acceptance evidence and the one-shot canonical projection readback.
 * useChatComposerTurnMutations calls this hook where the scheduler used to
 * live, so submit, edit-resubmit, and regenerate still share one readback.
 */
import { useCallback, useEffect, useRef, type Dispatch, type SetStateAction } from "react";
import type { QueryClient } from "@tanstack/react-query";

import { queryKeys } from "../../api/queryKeys";
import type { SessionDetail } from "../../api/types";
import { fetchSessionDetailWindow } from "./chatSessionDetailHelpers";
import {
  bindActiveTurnLayerToTurnId,
  createOptimisticActiveTurnLayer,
  latestUserTurnId,
  settleActiveTurnLayerFromDetail,
  setActiveTurnLayerForSession,
  type ActiveTurnLayerState,
} from "../chatActiveTurnLayer";
import type { ActiveTurnLayersStore } from "./activeTurnLayersStore";
import { mergeSessionDetailMessageWindow } from "../chatSessionState";
import { chatStreamPerformanceNowMs } from "./chatCodingRouteViewModel";
import { postSubmitTelemetry } from "./chatSubmitTelemetry";

export type SubmitAcceptanceEvidence = "canonical_message" | "queued_turn" | "active_task";

export type SubmitAcceptanceReadback = {
  evidence: SubmitAcceptanceEvidence | null;
  status: "cache_confirmed" | "readback_confirmed" | "not_found" | "readback_failed";
};

const SUBMIT_ACCEPTANCE_READBACK_TIMEOUT_MS = 3_000;

export function findSubmitAcceptanceEvidence(
  detail: SessionDetail | undefined,
  clientSubmissionId: string,
): SubmitAcceptanceEvidence | null {
  if (!detail || !clientSubmissionId) return null;
  if (detail.messages?.some((message) => (
    message.role === "user"
    && String(message.metadata?.clientSubmissionId ?? "").trim() === clientSubmissionId
    && message.metadata?.optimisticUserMessage !== true
  ))) {
    return "canonical_message";
  }
  if (detail.queuedTurns?.some((turn) => (
    String(turn.clientSubmissionId ?? "").trim() === clientSubmissionId
  ))) {
    return "queued_turn";
  }
  if (String(detail.activeTask?.metadata?.clientSubmissionId ?? "").trim() === clientSubmissionId) {
    return "active_task";
  }
  return null;
}

export function exactSubmitTurnId(detail: SessionDetail | undefined, clientSubmissionId: string): string {
  const canonicalUserMessage = [...(detail?.messages ?? [])].reverse().find((message) => (
    message.role === "user"
    && String(message.metadata?.clientSubmissionId ?? "").trim() === clientSubmissionId
    && message.metadata?.optimisticUserMessage !== true
  ));
  const rawTurnId = String(canonicalUserMessage?.metadata?.turnId ?? canonicalUserMessage?.metadata?.turn_id ?? "").trim();
  return rawTurnId.startsWith("live:") ? rawTurnId.slice("live:".length) : rawTurnId;
}

export function exactAcceptedSubmitTurnId(
  detail: SessionDetail | undefined,
  clientSubmissionId: string,
  evidence: SubmitAcceptanceEvidence,
): string {
  if (evidence === "queued_turn") return "";
  const canonicalTurnId = exactSubmitTurnId(detail, clientSubmissionId);
  if (canonicalTurnId) return canonicalTurnId;
  if (evidence !== "active_task") return "";
  const task = detail?.activeTask;
  if (String(task?.metadata?.clientSubmissionId ?? "").trim() !== clientSubmissionId) return "";
  const taskTurnId = String(task?.metadata?.turnId ?? task?.metadata?.turn_id ?? "").trim();
  return taskTurnId.startsWith("live:") ? taskTurnId.slice("live:".length) : taskTurnId;
}

export function isCurrentRunningSessionTurn(
  detail: SessionDetail | undefined,
  sessionId: string,
  turnId: string,
): boolean {
  const normalizedTurnId = String(turnId || "").trim();
  if (!detail || String(detail.id || "").trim() !== sessionId || !normalizedTurnId) return false;
  const turnLayer = createOptimisticActiveTurnLayer({ sessionId, turnId: normalizedTurnId, accepted: true });
  if (turnLayer && !settleActiveTurnLayerFromDetail(turnLayer, detail)) return false;
  // Stop click optimistically changes the phase to "stopping" before the
  // deferred request can be sent. Keep that exact, still-busy turn eligible.
  if (!sessionOwnsExecution(detail)) return false;
  const activeTurnId = String(detail.activeTurnId || "").trim().replace(/^live:/, "");
  const activeTaskTurnId = String(
    detail.activeTask?.metadata?.turnId ?? detail.activeTask?.metadata?.turn_id ?? "",
  ).trim().replace(/^live:/, "");
  if (activeTurnId && activeTurnId !== normalizedTurnId) return false;
  if (activeTaskTurnId && activeTaskTurnId !== normalizedTurnId) return false;
  if (activeTurnId || activeTaskTurnId) return true;
  return latestUserTurnId(detail) === normalizedTurnId;
}

export function reconcileAcceptedSubmitActiveTurnLayer(
  current: Record<string, ActiveTurnLayerState>,
  input: {
    sessionId: string;
    clientSubmissionId: string;
    turnId: string;
    queued: boolean;
    detail: SessionDetail | undefined;
    updatedAt: string;
  },
): Record<string, ActiveTurnLayerState> {
  const layer = current[input.sessionId];
  const submissionOwnsLayer = layer?.clientSubmissionId === input.clientSubmissionId;
  const turnOwnsLayer = Boolean(layer && input.turnId && layer.turnId === input.turnId);
  if (input.queued) {
    return submissionOwnsLayer
      ? setActiveTurnLayerForSession(current, input.sessionId, undefined)
      : current;
  }

  // An acknowledgement can omit its turn id. In that case the optimistic
  // layer still carries the exact submission identity and must stay visible.
  if (!input.turnId) {
    return current;
  }

  // A late receipt must not replace the layer for a later submission/turn.
  if (layer && !submissionOwnsLayer && !turnOwnsLayer) return current;
  const boundLayer = layer
    ? bindActiveTurnLayerToTurnId(layer, input.turnId)
    : undefined;
  const matchingLayer = boundLayer ?? createOptimisticActiveTurnLayer({
    sessionId: input.sessionId,
    turnId: input.turnId,
    clientSubmissionId: input.clientSubmissionId,
    updatedAt: input.updatedAt,
    accepted: true,
  });
  if (!matchingLayer) return current;
  if (!input.detail) {
    return setActiveTurnLayerForSession(current, input.sessionId, matchingLayer);
  }

  const unsettledLayer = settleActiveTurnLayerFromDetail(matchingLayer, input.detail);
  if (!unsettledLayer) {
    return setActiveTurnLayerForSession(current, input.sessionId, undefined);
  }

  // Preserve streamed output (including a terminal frame) that arrived before
  // the HTTP acknowledgement. The canonical detail path will retire it when
  // the transcript has committed the matching turn.
  if (boundLayer && (boundLayer.status === "completed" || boundLayer.status === "failed" || boundLayer.turnItems.length > 0)) {
    return setActiveTurnLayerForSession(current, input.sessionId, boundLayer);
  }
  if (!isCurrentRunningSessionTurn(input.detail, input.sessionId, input.turnId)) {
    return setActiveTurnLayerForSession(current, input.sessionId, undefined);
  }
  return setActiveTurnLayerForSession(current, input.sessionId, matchingLayer);
}

type AcceptedSubmitReadbackTask = {
  key: string;
  sessionId: string;
  clientSubmissionId: string;
  turnId: string;
  timer: ReturnType<typeof globalThis.setTimeout> | null;
  timeout: ReturnType<typeof globalThis.setTimeout> | null;
  controller: AbortController | null;
  unsubscribe: Array<() => void>;
  cancelled: boolean;
};

function retireAcceptedSubmitReadbackTask(
  tasks: Map<string, AcceptedSubmitReadbackTask>,
  task: AcceptedSubmitReadbackTask,
  abort = true,
): void {
  if (tasks.get(task.key) !== task) return;
  tasks.delete(task.key);
  task.cancelled = true;
  if (task.timer !== null) globalThis.clearTimeout(task.timer);
  if (task.timeout !== null) globalThis.clearTimeout(task.timeout);
  task.timer = null;
  task.timeout = null;
  if (abort) task.controller?.abort();
  task.controller = null;
  task.unsubscribe.splice(0).forEach((unsubscribe) => unsubscribe());
}

export async function readbackSubmitAcceptance(
  queryClient: QueryClient,
  sessionId: string,
  clientSubmissionId: string,
): Promise<SubmitAcceptanceReadback> {
  const queryKey = queryKeys.session(sessionId);
  const cachedEvidence = findSubmitAcceptanceEvidence(
    queryClient.getQueryData<SessionDetail>(queryKey),
    clientSubmissionId,
  );
  if (cachedEvidence) {
    return { evidence: cachedEvidence, status: "cache_confirmed" };
  }

  const controller = new AbortController();
  const timeoutId = globalThis.setTimeout(
    () => controller.abort(),
    SUBMIT_ACCEPTANCE_READBACK_TIMEOUT_MS,
  );
  try {
    const readback = await fetchSessionDetailWindow(sessionId, {
      includeSecondary: false,
      signal: controller.signal,
    });
    if (String(readback.id ?? "").trim() !== sessionId) {
      return { evidence: null, status: "not_found" };
    }
    queryClient.setQueryData<SessionDetail>(queryKey, (current) => {
      const currentLedgerSeq = current?.ledgerSeq;
      const readbackLedgerSeq = readback.ledgerSeq;
      if (
        current
        && typeof currentLedgerSeq === "number"
        && Number.isFinite(currentLedgerSeq)
        && typeof readbackLedgerSeq === "number"
        && Number.isFinite(readbackLedgerSeq)
        && currentLedgerSeq > readbackLedgerSeq
      ) {
        return current;
      }
      return mergeSessionDetailMessageWindow(current, readback);
    });
    const evidence = findSubmitAcceptanceEvidence(
      queryClient.getQueryData<SessionDetail>(queryKey) ?? readback,
      clientSubmissionId,
    ) ?? findSubmitAcceptanceEvidence(readback, clientSubmissionId);
    return evidence
      ? { evidence, status: "readback_confirmed" }
      : { evidence: null, status: "not_found" };
  } catch {
    // The POST's original error remains the user-facing failure if this
    // best-effort authority check also fails or is cancelled.
    return { evidence: null, status: "readback_failed" };
  } finally {
    globalThis.clearTimeout(timeoutId);
  }
}

export type AcceptedSubmitProjectionReadbackInput = {
  queryClient: QueryClient;
  activeSessionId?: string;
  activeTurnLayersStore?: Pick<ActiveTurnLayersStore, "getSnapshot" | "subscribe">;
  companionAgentId?: string;
  syncSessionDetail: (detail: SessionDetail) => void;
  setActiveTurnLayersBySession: Dispatch<SetStateAction<Record<string, ActiveTurnLayerState>>>;
};

/**
 * Owns the accepted-submit projection readback tasks. Call once, unconditionally,
 * before the turn mutations that schedule or consume a readback.
 */
export function useAcceptedSubmitProjectionReadback({
  queryClient,
  activeSessionId,
  activeTurnLayersStore,
  companionAgentId,
  syncSessionDetail,
  setActiveTurnLayersBySession,
}: AcceptedSubmitProjectionReadbackInput) {
  const acceptedSubmitReadbacksRef = useRef(new Map<string, AcceptedSubmitReadbackTask>());
  const activeSessionIdRef = useRef(String(activeSessionId || "").trim());
  const isMountedRef = useRef(false);

  const retireAcceptedSubmitReadback = useCallback((task: AcceptedSubmitReadbackTask, abort = true) => {
    retireAcceptedSubmitReadbackTask(acceptedSubmitReadbacksRef.current, task, abort);
  }, []);

  useEffect(() => {
    activeSessionIdRef.current = String(activeSessionId || "").trim();
    for (const task of acceptedSubmitReadbacksRef.current.values()) {
      if (task.sessionId !== activeSessionIdRef.current) {
        retireAcceptedSubmitReadback(task);
      }
    }
  }, [activeSessionId, retireAcceptedSubmitReadback]);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      for (const task of acceptedSubmitReadbacksRef.current.values()) {
        retireAcceptedSubmitReadback(task);
      }
    };
  }, [retireAcceptedSubmitReadback]);

  const scheduleAcceptedSubmitReadback = useCallback((
    sessionId: string,
    clientSubmissionId: string,
    acceptedTurnId: string,
  ) => {
    if (
      !sessionId
      || !clientSubmissionId
      || companionAgentId
      || !isMountedRef.current
      || activeSessionIdRef.current !== sessionId
    ) return;

    const key = JSON.stringify([sessionId, clientSubmissionId]);
    const previousTask = acceptedSubmitReadbacksRef.current.get(key);
    if (previousTask) retireAcceptedSubmitReadback(previousTask);
    const task: AcceptedSubmitReadbackTask = {
      key,
      sessionId,
      clientSubmissionId,
      turnId: acceptedTurnId,
      timer: null,
      timeout: null,
      controller: null,
      unsubscribe: [],
      cancelled: false,
    };
    acceptedSubmitReadbacksRef.current.set(key, task);

    const projectionHasSettled = () => {
      if (activeSessionIdRef.current !== sessionId) return true;
      const detail = queryClient.getQueryData<SessionDetail>(queryKeys.session(sessionId));
      const evidence = findSubmitAcceptanceEvidence(detail, clientSubmissionId);
      if (evidence === "canonical_message" || evidence === "queued_turn") return true;
      const turnId = task.turnId || exactSubmitTurnId(detail, clientSubmissionId);
      const layer = activeTurnLayersStore?.getSnapshot()[sessionId];
      if (layer) {
        const ownsLayer = layer.clientSubmissionId === clientSubmissionId
          || Boolean(turnId && layer.turnId === turnId);
        if (!ownsLayer) return true;
        if (layer.status === "completed" || layer.status === "failed") return true;
      }
      if (turnId) {
        const probe = createOptimisticActiveTurnLayer({
          sessionId,
          turnId,
          clientSubmissionId,
          accepted: true,
        });
        if (probe && !settleActiveTurnLayerFromDetail(probe, detail)) return true;
      }
      return false;
    };
    const retireIfSettled = () => {
      if (projectionHasSettled()) retireAcceptedSubmitReadback(task);
    };

    const sessionKey = queryKeys.session(sessionId);
    task.unsubscribe.push(queryClient.getQueryCache().subscribe((event) => {
      if (event.type !== "updated") return;
      const changedKey = event.query.queryKey;
      if (
        changedKey.length !== sessionKey.length
        || changedKey.some((part: unknown, index: number) => part !== sessionKey[index])
      ) return;
      retireIfSettled();
    }));
    if (activeTurnLayersStore) {
      task.unsubscribe.push(activeTurnLayersStore.subscribe(retireIfSettled));
    }

    task.timer = globalThis.setTimeout(() => {
      task.timer = null;
      if (task.cancelled || projectionHasSettled()) {
        retireAcceptedSubmitReadback(task);
        return;
      }
      const controller = new AbortController();
      task.controller = controller;
      const readbackStartedAtMs = chatStreamPerformanceNowMs();
      task.timeout = globalThis.setTimeout(
        () => controller.abort(),
        SUBMIT_ACCEPTANCE_READBACK_TIMEOUT_MS,
      );
      void fetchSessionDetailWindow(sessionId, {
        includeSecondary: false,
        signal: controller.signal,
      }).then((readback) => {
        if (
          task.cancelled
          || controller.signal.aborted
          || activeSessionIdRef.current !== sessionId
          || String(readback.id || "").trim() !== sessionId
        ) {
          if (!task.cancelled && String(readback.id || "").trim() !== sessionId) {
            postSubmitTelemetry(
              "browser.chat_submit.accepted_projection_readback",
              "One-shot canonical projection readback returned a different session.",
              sessionId,
              {
                clientSubmissionId,
                result: "session_mismatch",
                timeoutMs: SUBMIT_ACCEPTANCE_READBACK_TIMEOUT_MS,
                durationMs: Math.max(0, chatStreamPerformanceNowMs() - readbackStartedAtMs),
              },
              "warning",
            );
          }
          return;
        }
        // Remove this task's observers before writing the canonical snapshot;
        // that write must settle the projection rather than cancel itself.
        retireAcceptedSubmitReadback(task, false);
        syncSessionDetail(readback);
        const canonicalDetail = queryClient.getQueryData<SessionDetail>(queryKeys.session(sessionId)) ?? readback;
        const canonicalTurnId = exactSubmitTurnId(canonicalDetail, clientSubmissionId) || task.turnId;
        postSubmitTelemetry(
          "browser.chat_submit.accepted_projection_readback",
          "One-shot canonical projection readback completed.",
          sessionId,
          {
            clientSubmissionId,
            result: findSubmitAcceptanceEvidence(canonicalDetail, clientSubmissionId) ?? "missing_submission",
            timeoutMs: SUBMIT_ACCEPTANCE_READBACK_TIMEOUT_MS,
            durationMs: Math.max(0, chatStreamPerformanceNowMs() - readbackStartedAtMs),
          },
          "info",
        );
        setActiveTurnLayersBySession((current) => reconcileAcceptedSubmitActiveTurnLayer(current, {
          sessionId,
          clientSubmissionId,
          turnId: canonicalTurnId,
          queued: false,
          detail: canonicalDetail,
          updatedAt: readback.updatedAt,
        }));
      }).catch(() => {
        // The HTTP receipt already established acceptance. This is a single
        // best-effort projection readback, never a retry or a second submit.
        if (!task.cancelled && activeSessionIdRef.current === sessionId) {
          const timedOut = controller.signal.aborted;
          postSubmitTelemetry(
            "browser.chat_submit.accepted_projection_readback",
            "One-shot canonical projection readback did not complete.",
            sessionId,
            {
              clientSubmissionId,
              result: timedOut ? "timeout" : "failed",
              timeoutMs: SUBMIT_ACCEPTANCE_READBACK_TIMEOUT_MS,
              durationMs: Math.max(0, chatStreamPerformanceNowMs() - readbackStartedAtMs),
            },
            "warning",
          );
        }
      }).finally(() => {
        retireAcceptedSubmitReadback(task, false);
      });
    }, SUBMIT_ACCEPTANCE_READBACK_TIMEOUT_MS);
  }, [
    activeTurnLayersStore,
    companionAgentId,
    queryClient,
    retireAcceptedSubmitReadback,
    setActiveTurnLayersBySession,
    syncSessionDetail,
  ]);

  return scheduleAcceptedSubmitReadback;
}
