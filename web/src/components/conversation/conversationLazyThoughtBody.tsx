import { useEffect, useState } from "react";

import { ThoughtScrollBody } from "./conversationThoughtUnits";

export type ThoughtBodyLoader = (
  turnId: string,
  itemId: string,
  options: { signal?: AbortSignal },
) => Promise<string>;

/**
 * Thought body that upgrades a bounded transport preview to the canonical text
 * on first expand. Readers that never open the disclosure never pay the round
 * trip, which is the point of bounding historical reasoning on the wire.
 *
 * ``text`` keeps the bounded preview as the fallback: a failed or slow fetch
 * must never blank a disclosure the user just opened.
 */
export function ConversationLazyThoughtBody({
  text,
  streaming,
  contentItemId,
  turnId,
  loadThoughtBody,
}: {
  text: string;
  streaming: boolean;
  contentItemId?: string;
  turnId?: string;
  loadThoughtBody?: ThoughtBodyLoader;
}) {
  const [fullBody, setFullBody] = useState("");
  useEffect(() => {
    if (!contentItemId || !turnId || !loadThoughtBody) {
      return;
    }
    let cancelled = false;
    const controller = new AbortController();
    loadThoughtBody(turnId, contentItemId, { signal: controller.signal })
      .then((body) => {
        if (!cancelled && body) {
          setFullBody(body);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [contentItemId, turnId, loadThoughtBody]);
  return (
    <ThoughtScrollBody text={fullBody || text} streaming={streaming} />
  );
}
