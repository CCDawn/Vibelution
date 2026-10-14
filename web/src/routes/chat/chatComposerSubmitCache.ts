/**
 * Cache writes shared by turn mutations and the composer upload path.
 * Optimistic removals bypass structural sharing; draft restore stays outside
 * React's replayable updater.
 */
import type { QueryClient } from "@tanstack/react-query";
import type { Dispatch, SetStateAction } from "react";

import { queryKeys } from "../../api/queryKeys";
import type { SessionDetail } from "../../api/types";
import {
  removeOptimisticUserMessage,
  type OptimisticUserMessageInput,
} from "../chatSessionState";
import { restoreSubmittedDraftIfComposerStillEmpty } from "./chatComposerSubmitModel";
import {
  scheduleSessionDraftRecoverySave,
  type SessionDraftRecoveryGuard,
} from "./chatDraftPersistence";
import { removeOptimisticUserMessagePaint } from "./chatSessionPaintCache";

/**
 * Intentional optimistic-row removals must bypass the session detail query's
 * ``structuralSharing``. React Query runs ``query.options.structuralSharing``
 * on every data write (``Query.setData``, manual ``setQueryData`` included),
 * and the workbench registers its windowed UNION merge there
 * (``sessionDetailStructuralSharing``), so a removal updater is undone before
 * it lands: the merge resurrects the optimistic row from the previous data and
 * the row sticks on the timeline forever (multi-file upload allSettled blocked
 * batch residue). Updates survive that merge (same-id messages: later write
 * wins; top-level fields favor ``next``) — only message-array removals die.
 * Write through ``query.setState`` (which skips ``replaceData``) so removals
 * get replace semantics while every other write keeps merge semantics.
 */
export function removeOptimisticUserMessageFromCache(
  queryClient: QueryClient,
  sessionId: string,
  input: OptimisticUserMessageInput,
): void {
  removeOptimisticUserMessagePaint(sessionId, input);
  const query = queryClient
    .getQueryCache()
    .find<SessionDetail>({ queryKey: queryKeys.session(sessionId), exact: true });
  if (!query) {
    return;
  }
  const next = removeOptimisticUserMessage(query.state.data, input);
  if (next === query.state.data) {
    return;
  }
  query.setState({ data: next, dataUpdatedAt: Date.now() });
}

export function restoreSubmittedDraftAfterFailure(
  setSessionDrafts: Dispatch<SetStateAction<Record<string, string>>>,
  sessionId: string,
  content: string,
  recoveryGuard: SessionDraftRecoveryGuard | null | undefined,
) {
  // Persistence is a side effect and must stay outside React's replayable
  // functional updater. The guard rejects late failures after newer input.
  if (recoveryGuard && !scheduleSessionDraftRecoverySave(recoveryGuard, content)) {
    return;
  }
  setSessionDrafts((current) => restoreSubmittedDraftIfComposerStillEmpty(current, sessionId, content));
}
