/**
 * Reload the window when the backend publishes a newer frontend build.
 *
 * A workbench window keeps running the bundle it booted with. The launcher can
 * publish a brand new immutable release underneath it and nothing on screen
 * changes, which reads exactly like a stale cache even though the served HTML
 * is already the new one.
 *
 * The shell HTML is served with ``no-store`` plus a content-hash ETag, so a
 * cheap HEAD probe is enough to notice that a new build exists. Reloading once
 * lets the window pick up the new bundle. The probe keeps a small session
 * budget so a misbehaving proxy cannot reload the shell in a loop.
 */

const PROBE_INTERVAL_MS = 30_000;
const PROBE_PATH = "/";
const RELOAD_GUARD_KEY = "vibelution:frontend-build-reload";
const MAX_RELOADS_PER_HOUR = 3;

let bootEtag: string | null = null;
let probing = false;

function reloadBudgetAvailable(): boolean {
  try {
    const raw = window.sessionStorage.getItem(RELOAD_GUARD_KEY);
    const now = Date.now();
    const stamps = raw ? (JSON.parse(raw) as number[]) : [];
    const recent = stamps.filter((stamp) => now - stamp < 60 * 60 * 1000);
    if (recent.length >= MAX_RELOADS_PER_HOUR) return false;
    recent.push(now);
    window.sessionStorage.setItem(RELOAD_GUARD_KEY, JSON.stringify(recent));
    return true;
  } catch {
    return true;
  }
}

async function probeOnce(): Promise<void> {
  if (probing) return;
  probing = true;
  try {
    const response = await fetch(PROBE_PATH, { method: "HEAD", cache: "no-store" });
    const etag = response.headers.get("etag");
    if (!etag) return;
    if (bootEtag === null) {
      bootEtag = etag;
      return;
    }
    if (etag === bootEtag) return;
    bootEtag = etag;
    if (!reloadBudgetAvailable()) return;
    window.location.reload();
  } catch {
    // A failed probe must never disturb a working window.
  } finally {
    probing = false;
  }
}

export function startFrontendBuildProbe(): void {
  if (typeof window === "undefined") return;
  void probeOnce();
  window.setInterval(() => {
    void probeOnce();
  }, PROBE_INTERVAL_MS);
}
