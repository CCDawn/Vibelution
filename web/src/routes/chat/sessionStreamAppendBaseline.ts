import type { SessionTurnItem } from "../../api/types";
import { consolidateSessionTurnItemsV2 } from "../chatTurnProtocol";

/** Rebuild protocol state from the full same-turn projection, not its visual residual. */
export function sessionStreamAppendBaseline(
  sessionId: string,
  turnId: string,
  detailItems: SessionTurnItem[],
  activeItems?: SessionTurnItem[],
): SessionTurnItem[] {
  if (!sessionId || !turnId) return [];
  return consolidateSessionTurnItemsV2(detailItems, activeItems)
    .filter((item) => item.sessionId === sessionId && item.turnId === turnId);
}
