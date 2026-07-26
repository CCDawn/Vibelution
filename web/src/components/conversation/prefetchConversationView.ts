/**
 * Warm the ConversationView feature chunk after session intent is clear (T1).
 * Does not mount React — only starts the dynamic import for cache.
 */
let conversationViewPrefetch: Promise<unknown> | null = null;

export function prefetchConversationView(): Promise<unknown> {
  if (typeof window === "undefined") {
    return Promise.resolve();
  }
  if (!conversationViewPrefetch) {
    conversationViewPrefetch = import("./ConversationView").catch((error) => {
      conversationViewPrefetch = null;
      throw error;
    });
  }
  return conversationViewPrefetch;
}
