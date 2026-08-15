export type ComposerQueueItem = {
  id: string;
  text: string;
};

export type ComposerQueueEnterAction =
  | { type: "enqueue"; text: string }
  | { type: "immediate"; items: ComposerQueueItem[] }
  | { type: "send"; text: string }
  | { type: "noop" };

export type ComposerQueuePrimaryKind = "send" | "queue" | "immediate" | "stop-only";

export function createComposerQueueItem(text: string, id = `queue-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`): ComposerQueueItem {
  return {
    id,
    text: text.trim(),
  };
}

export function resolveComposerQueueEnter(input: {
  sessionBusy: boolean;
  draft: string;
  queue: readonly ComposerQueueItem[];
}): ComposerQueueEnterAction {
  const text = input.draft.trim();
  if (!input.sessionBusy) {
    return text ? { type: "send", text } : { type: "noop" };
  }
  if (text) {
    return { type: "enqueue", text };
  }
  if (input.queue.length > 0) {
    return { type: "immediate", items: [...input.queue] };
  }
  return { type: "noop" };
}

export function resolveComposerQueuePrimaryKind(input: {
  sessionBusy: boolean;
  draft: string;
  queueCount: number;
}): ComposerQueuePrimaryKind {
  if (!input.sessionBusy) {
    return "send";
  }
  if (input.draft.trim()) {
    return "queue";
  }
  if (input.queueCount > 0) {
    return "immediate";
  }
  return "stop-only";
}

export function appendComposerQueueItem(
  queue: readonly ComposerQueueItem[],
  text: string,
): ComposerQueueItem[] {
  const item = createComposerQueueItem(text);
  if (!item.text) {
    return [...queue];
  }
  return [...queue, item];
}

export function removeComposerQueueItem(
  queue: readonly ComposerQueueItem[],
  id: string,
): ComposerQueueItem[] {
  return queue.filter((item) => item.id !== id);
}

export function updateComposerQueueItem(
  queue: readonly ComposerQueueItem[],
  id: string,
  text: string,
): ComposerQueueItem[] {
  const nextText = text.trim();
  return queue.map((item) => (item.id === id ? { ...item, text: nextText || item.text } : item));
}

export function appendImmediateSteerTurns<T>(
  messages: readonly T[],
  texts: readonly string[],
  createTurn: (text: string) => T,
): T[] {
  const notes = texts.map((item) => item.trim()).filter(Boolean);
  if (!notes.length) {
    return [...messages];
  }
  return [...messages, ...notes.map(createTurn)];
}

export function moveComposerQueueItem(
  queue: readonly ComposerQueueItem[],
  fromIndex: number,
  toIndex: number,
): ComposerQueueItem[] {
  if (fromIndex === toIndex || fromIndex < 0 || toIndex < 0 || fromIndex >= queue.length || toIndex >= queue.length) {
    return [...queue];
  }
  const next = [...queue];
  const [moved] = next.splice(fromIndex, 1);
  next.splice(toIndex, 0, moved);
  return next;
}
