import type { SessionTurnItem } from "../api/types/chat";

/** Display position follows creation; sequence still selects the latest revision. */
export function sessionTurnItemOrderSequence(item: SessionTurnItem): number {
  const sequence = Number(item.metadata?.orderSequence);
  return Number.isSafeInteger(sequence) && sequence > 0 ? sequence : item.sequence;
}
