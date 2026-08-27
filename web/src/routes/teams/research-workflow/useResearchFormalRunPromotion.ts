import { useEffect } from "react";

type ReplaceParams = (patch: Record<string, string | null | undefined>) => void;

/**
 * The canonical V2 state owns the current formal run id. A deep link that
 * names only the question must still reach the formal run's own snapshot,
 * projection, and recovery actions, so the server-owned run id is promoted
 * into the URL once — the same replace contract as the post-create runId
 * patch. Without this promotion a blocked formal run is unreachable from the
 * question entry, and a hypothesis-first card bound to a formal node id can
 * only render as the unknown-card empty state.
 */
export function useResearchFormalRunPromotion(options: {
  /** Run id currently present in the URL; promotion never overrides it. */
  activeRunId: string | null;
  /** Server-owned formal run id from the canonical V2 state, if any. */
  promotedRunId: string | null;
  replaceParams: ReplaceParams;
}) {
  const { activeRunId, promotedRunId, replaceParams } = options;
  useEffect(() => {
    const runId = promotedRunId?.trim() || null;
    if (!runId || activeRunId) return;
    replaceParams({ runId });
  }, [activeRunId, promotedRunId, replaceParams]);
}
