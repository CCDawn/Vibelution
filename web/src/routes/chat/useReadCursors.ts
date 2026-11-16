import { useCallback, useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  READ_CURSORS_QUERY_KEY,
  fetchReadCursors,
  markReadCursors,
  type MarkReadEntry,
  type ReadCursorEntry,
  type ReadCursorsPayload,
} from "../../api/readCursors";
import { buildReadCursorIndex } from "./teamUnreadModel";

/**
 * Server-backed read cursors for the rail unread projection.
 *
 * Reads are cached for a minute; a mark-read mutation writes the returned
 * snapshot into the same cache so the badge drops immediately without
 * refetching the whole conversation index.
 */
export function useReadCursors() {
  const queryClient = useQueryClient();
  const query = useQuery<ReadCursorsPayload>({
    queryKey: READ_CURSORS_QUERY_KEY,
    queryFn: ({ signal }) => fetchReadCursors(signal),
    staleTime: 60_000,
  });
  const mutation = useMutation<ReadCursorsPayload, Error, MarkReadEntry[]>({
    mutationFn: (entries) => markReadCursors(entries),
    onSuccess: (payload) => {
      queryClient.setQueryData(READ_CURSORS_QUERY_KEY, payload);
    },
  });
  const markRead = useCallback(
    (entries: readonly MarkReadEntry[]) => {
      if (!entries.length) return;
      mutation.mutate([...entries]);
    },
    [mutation],
  );
  const cursors: readonly ReadCursorEntry[] = query.data?.cursors ?? [];
  const index = useMemo(() => buildReadCursorIndex(cursors), [cursors]);
  return {
    index,
    cursors,
    loaded: query.isSuccess,
    markRead,
    pending: mutation.isPending,
  };
}
