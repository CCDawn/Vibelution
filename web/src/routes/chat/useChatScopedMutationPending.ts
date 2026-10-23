import { useCallback } from "react";
import { useMutationState, useQueryClient, type MutationKey } from "@tanstack/react-query";

/** Mutation observers only retain the last submission; the cache retains every pending write. */
export function useChatScopedMutationPending(mutationKey: MutationKey, field: "sessionId" | "roomId") {
  const client = useQueryClient();
  const ids = useMutationState({
    filters: { mutationKey, exact: true, status: "pending" },
    select: (mutation) => String((mutation.state.variables as Record<string, unknown> | undefined)?.[field] || ""),
  });
  const isPendingFor = useCallback((id: string) => Boolean(id) && client.getMutationCache().findAll({
    mutationKey, exact: true, status: "pending",
    predicate: (mutation) => (mutation.state.variables as Record<string, unknown> | undefined)?.[field] === id,
  }).length > 0, [client, field, mutationKey]);
  return { pendingIds: new Set(ids.filter(Boolean)), isPendingFor };
}

export function isChatRoomMutationPending(
  mutation: { isPending: boolean; variables?: { roomId?: string }; isPendingFor?: (id: string) => boolean },
  roomId: string | null | undefined,
): boolean {
  return Boolean(roomId && (mutation.isPendingFor
    ? mutation.isPendingFor(roomId)
    : mutation.isPending && mutation.variables?.roomId === roomId));
}

/** Cache reconciliation is background work and must not extend the write's pending lifetime. */
export function refreshChatInBackground(refresh: () => unknown): void {
  void Promise.resolve().then(refresh).catch(() => undefined);
}

export function describeUncertainChatWrite(error: unknown, lang: "zh" | "en", fallback: string): string {
  const name = error instanceof Error ? error.name : "";
  if (name === "TimeoutError" || name === "AbortError" || error instanceof TypeError) {
    return lang === "zh"
      ? "请求已中断，操作结果尚未确认，正在后台核对。请先查看最新状态，不要重复提交。"
      : "The request was interrupted and its result is unknown. Checking in the background; review the latest state before submitting again.";
  }
  return fallback;
}
