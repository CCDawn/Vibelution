/**
 * Router access resolves to the lazy route's loader; call that loader too so
 * hover/focus preloading starts the same dynamic import used by navigation.
 */
export function loadPrimaryRouteChunk(
  resolveRouteChunkLoader: () => Promise<() => Promise<unknown>>,
): Promise<unknown> {
  return resolveRouteChunkLoader().then((loadChunk) => loadChunk());
}
