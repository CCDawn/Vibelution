import { useCallback, useEffect, useRef, useState } from "react";

import { applySessionTurnRewind } from "../../api/chat";
import type { ConversationMessage } from "../../api/types";
import { rerunFileRestorePlan } from "./rerunFileRestore";

export type RerunFileChoiceState = {
  paths: string[];
  error: string;
  restoring: boolean;
};

type PendingRerunFileChoice = RerunFileChoiceState & {
  sessionId: string;
  turnIds: string[];
  run: () => void;
};

/**
 * Ask before edit-resubmit, regenerate, and failed-turn retry when the loaded
 * tail has disk-truth file changes. Restore walks turns newest-first: each
 * turn's after-image is the previous turn's current bytes, so oldest-first
 * would look externally modified. A failed apply leaves the dialog open.
 */
export function useRerunFileChoice({
  sessionId,
  lang,
  describeError,
}: {
  sessionId: string | null | undefined;
  lang: "zh" | "en";
  describeError: (error: unknown, fallback: string) => string;
}): {
  rerunFileChoice: RerunFileChoiceState | null;
  interceptRerun: (
    messages: readonly ConversationMessage[],
    startIndex: number,
    run: () => void,
  ) => void;
  confirmRerunFileRestore: () => Promise<void>;
  keepFilesAndRerun: () => void;
  dismissRerunFileChoice: () => void;
} {
  const [choice, setChoice] = useState<PendingRerunFileChoice | null>(null);
  const pendingRef = useRef<PendingRerunFileChoice | null>(null);
  const sessionKey = sessionId ?? "";

  const publish = useCallback((next: PendingRerunFileChoice | null) => {
    pendingRef.current = next;
    setChoice(next);
  }, []);

  useEffect(() => {
    if (!pendingRef.current) return;
    pendingRef.current = null;
    setChoice(null);
  }, [sessionKey]);

  const interceptRerun = useCallback((
    messages: readonly ConversationMessage[],
    startIndex: number,
    run: () => void,
  ) => {
    if (pendingRef.current) return;
    const plan = rerunFileRestorePlan(messages, startIndex);
    if (plan.turnIds.length === 0 || !sessionKey) {
      run();
      return;
    }
    publish({
      sessionId: sessionKey,
      turnIds: plan.turnIds,
      paths: plan.paths,
      error: "",
      restoring: false,
      run,
    });
  }, [publish, sessionKey]);

  const confirmRerunFileRestore = useCallback(async () => {
    const snapshot = pendingRef.current;
    if (!snapshot || snapshot.restoring) return;
    publish({ ...snapshot, restoring: true, error: "" });
    const fallback = lang === "zh" ? "还原文件失败" : "Could not restore the files";
    try {
      for (const turnId of [...snapshot.turnIds].reverse()) {
        if (pendingRef.current?.sessionId !== snapshot.sessionId) return;
        await applySessionTurnRewind(snapshot.sessionId, { turnId, force: false });
      }
    } catch (error) {
      if (pendingRef.current?.sessionId !== snapshot.sessionId) return;
      publish({
        ...snapshot,
        restoring: false,
        error: describeError(error, fallback),
      });
      return;
    }
    if (pendingRef.current?.sessionId !== snapshot.sessionId) return;
    publish(null);
    snapshot.run();
  }, [describeError, lang, publish]);

  const keepFilesAndRerun = useCallback(() => {
    const snapshot = pendingRef.current;
    if (!snapshot || snapshot.restoring) return;
    publish(null);
    snapshot.run();
  }, [publish]);

  const dismissRerunFileChoice = useCallback(() => {
    if (!pendingRef.current || pendingRef.current.restoring) return;
    publish(null);
  }, [publish]);

  return {
    rerunFileChoice: choice
      ? { paths: choice.paths, error: choice.error, restoring: choice.restoring }
      : null,
    interceptRerun,
    confirmRerunFileRestore,
    keepFilesAndRerun,
    dismissRerunFileChoice,
  };
}
