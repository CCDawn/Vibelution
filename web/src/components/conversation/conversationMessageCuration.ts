import type { SessionMessageCurationAction, SessionMessageCurationItem } from "../../api/types";

/**
 * Pure model for the in-conversation SFT dataset curation actions
 * ("加入数据集" / "排除" on settled assistant answers). Optimistic writes land
 * here first; the transport lives in web/src/api/chat.ts.
 */
export type MessageCurationDecision = {
  action: SessionMessageCurationAction;
  modelId: string;
  candidateId: string;
  decidedAt: string;
};

/**
 * Indexes the session's curation decisions by message id. Later items win —
 * the backend returns decisions in decision order, so the newest side of a
 * message is the one on display.
 */
export function buildMessageCurationMap(
  items: ReadonlyArray<SessionMessageCurationItem>,
): Map<string, MessageCurationDecision> {
  const map = new Map<string, MessageCurationDecision>();
  for (const item of items) {
    if (!item?.messageId) {
      continue;
    }
    map.set(item.messageId, {
      action: item.action,
      modelId: item.modelId ?? "",
      candidateId: item.candidateId ?? "",
      decidedAt: item.decidedAt ?? "",
    });
  }
  return map;
}

/** Optimistic write: returns a new map with the message moved to `action`. */
export function applyOptimisticCuration(
  map: ReadonlyMap<string, MessageCurationDecision>,
  messageId: string,
  action: SessionMessageCurationAction,
): Map<string, MessageCurationDecision> {
  const next = new Map(map);
  const previous = next.get(messageId);
  next.set(messageId, {
    action,
    modelId: previous?.modelId ?? "",
    candidateId: previous?.candidateId ?? "",
    // Unconfirmed until the POST resolves; the server record replaces it.
    decidedAt: "",
  });
  return next;
}

/** Current curation side for a message, or null when undecided. */
export function resolveMessageCurationState(
  map: ReadonlyMap<string, MessageCurationDecision>,
  messageId: string,
): SessionMessageCurationAction | null {
  return map.get(messageId)?.action ?? null;
}

/**
 * Lifetime include/exclude tally for one model. Returns null when the model
 * has no entry or nothing counted yet; presentation copy stays with the
 * component so zh/en surfaces both localize it.
 */
export function resolveModelCurationTally(
  models: ReadonlyArray<{ modelId: string; included: number; excluded: number }>,
  modelId: string,
): { included: number; excluded: number } | null {
  if (!modelId) {
    return null;
  }
  const stat = models.find((model) => model.modelId === modelId);
  if (!stat || (!stat.included && !stat.excluded)) {
    return null;
  }
  return { included: stat.included, excluded: stat.excluded };
}
