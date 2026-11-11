import { useEffect, useState } from "react";

/**
 * One shared low-frequency clock for every "N seconds elapsed" surface.
 *
 * Why this exists instead of a `setInterval` per component:
 *
 * - A per-component interval keeps a timer and a React subscription alive for
 *   as long as the component is mounted, even when the visible text no longer
 *   depends on the clock (the thinking stage stopped showing a counter).
 * - Background workbenches kept ticking: `document.visibilityState` was never
 *   consulted, so a hidden window still paid a render per second per surface.
 * - Several surfaces (turn heartbeat, process disclosure, launcher update bar,
 *   group rounds timeline) each owned their own interval at the same cadence,
 *   so the same second produced N independent renders instead of one shared
 *   notification.
 *
 * The clock is bucketed by interval: one timer per cadence, one visibility
 * binding for the whole page, and listeners are only registered while a caller
 * reports `active`. When the document is hidden every bucket stops; when it
 * becomes visible again the buckets restart and subscribers are realigned to
 * the current time so a returning window shows a correct value immediately.
 */

type TickListener = () => void;

type Bucket = {
  listeners: Set<TickListener>;
  timer: number | null;
};

const buckets = new Map<number, Bucket>();
let visibilityBound = false;

function documentHidden() {
  return typeof document !== "undefined" && document.visibilityState === "hidden";
}

function getBucket(intervalMs: number): Bucket {
  const existing = buckets.get(intervalMs);
  if (existing) {
    return existing;
  }
  const bucket: Bucket = { listeners: new Set<TickListener>(), timer: null };
  buckets.set(intervalMs, bucket);
  return bucket;
}

function startBucket(intervalMs: number) {
  const bucket = getBucket(intervalMs);
  if (bucket.timer !== null || bucket.listeners.size === 0 || documentHidden()) {
    return;
  }
  bucket.timer = window.setInterval(() => {
    for (const listener of bucket.listeners) {
      listener();
    }
  }, intervalMs);
}

function stopBucket(intervalMs: number) {
  const bucket = buckets.get(intervalMs);
  if (!bucket || bucket.timer === null) {
    return;
  }
  window.clearInterval(bucket.timer);
  bucket.timer = null;
}

function stopAllBuckets() {
  for (const intervalMs of buckets.keys()) {
    stopBucket(intervalMs);
  }
}

function startAllBuckets() {
  for (const intervalMs of buckets.keys()) {
    startBucket(intervalMs);
  }
}

function ensureVisibilityBinding() {
  if (visibilityBound || typeof document === "undefined") {
    return;
  }
  visibilityBound = true;
  document.addEventListener("visibilitychange", () => {
    if (documentHidden()) {
      stopAllBuckets();
      return;
    }
    startAllBuckets();
  });
}

/**
 * Returns the current epoch-ms value, refreshed on a shared cadence.
 *
 * Pass `active: false` when the visible output does not depend on time (for
 * example a thinking heartbeat that stopped showing a counter). An inactive
 * caller keeps its last value and registers no listener, so it costs nothing
 * beyond the hook call itself.
 */
export function useNowTick(active: boolean, intervalMs = 1_000, alignKey?: unknown): number {
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    if (!active) {
      return undefined;
    }
    ensureVisibilityBinding();
    const bucket = getBucket(intervalMs);
    const listener: TickListener = () => setNowMs(Date.now());
    bucket.listeners.add(listener);
    startBucket(intervalMs);
    // Align immediately: a surface that just became active should not render a
    // stale value until the next cadence boundary.
    setNowMs(Date.now());
    return () => {
      bucket.listeners.delete(listener);
      if (bucket.listeners.size === 0) {
        stopBucket(intervalMs);
      }
    };
  }, [active, intervalMs, alignKey]);

  return nowMs;
}

/** Test-only: drop every bucket so one test cannot leak timers into the next. */
export function resetNowTickForTests() {
  stopAllBuckets();
  buckets.clear();
  visibilityBound = false;
}
