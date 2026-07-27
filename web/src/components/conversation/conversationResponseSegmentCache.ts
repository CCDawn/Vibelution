/**
 * Response-segment parse cache pure helpers (claim: timeline segment parse cache).
 * Pure: no React / DOM. Mutates the provided Map (caller-owned cache).
 */
import { parseResponseSegments, type ResponseSegment } from "./messageResponseSegments";

export function trimOldestCacheEntries<T>(cache: Map<string, T>, limit: number) {
  while (cache.size > limit) {
    const oldestKey = cache.keys().next().value;
    if (oldestKey === undefined) {
      return;
    }
    cache.delete(oldestKey);
  }
}

export function getCachedResponseSegments(
  cache: Map<string, ResponseSegment[]>,
  content: string,
  limit: number,
): ResponseSegment[] {
  const key = String(content ?? "");
  const cached = cache.get(key);
  if (cached) {
    cache.delete(key);
    cache.set(key, cached);
    return cached;
  }
  const parsed = parseResponseSegments(key);
  cache.set(key, parsed);
  trimOldestCacheEntries(cache, limit);
  return parsed;
}
