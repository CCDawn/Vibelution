/**
 * Decide whether a Markdown link points at a route this SPA owns.
 *
 * Chat transcripts routinely contain absolute links to the workbench itself,
 * e.g. `http://127.0.0.1:8000/chat?session=...`. Electron treats a same-origin
 * main-frame navigation as an in-window document load, so a plain anchor
 * reloads the whole product shell instead of switching the current view.
 * Routing those targets through react-router keeps the document alive.
 *
 * Only the router's own top-level segments qualify. Everything else keeps
 * anchor behaviour, which matters for backend paths such as
 * `/api/sessions/.../artifacts/a.png`: those are downloads, not views, and an
 * SPA navigation to them would land on a route the router never registered.
 *
 * Returns "" when plain anchor behaviour must be kept: cross-origin URLs,
 * protocol-relative URLs, non-http(s) schemes, backend paths, or anything
 * unparseable.
 */
const INTERNAL_TOP_SEGMENTS: ReadonlySet<string> = new Set([
  "launcher-assistant",
  "launcher",
  "tools",
  "assistant",
  "updates",
  "chat",
  "finance",
  "companions",
  "evolution",
  "supervised-evolution",
  "self-evolution",
  "agents",
  "memory",
  "teams",
  "kernel",
  "aux",
  "git",
  "usage",
  "logs",
  "pet",
  "reset",
  "config",
]);

function isRouterOwnedPath(pathname: string): boolean {
  if (pathname === "/") {
    return true;
  }
  const first = pathname.split("/").filter(Boolean)[0] ?? "";
  return INTERNAL_TOP_SEGMENTS.has(first);
}

export function resolveConversationInternalRoutePath(href: string): string {
  const raw = String(href || "").trim();
  if (!raw) {
    return "";
  }
  // Protocol-relative targets (//host/path) point at another origin.
  if (raw.startsWith("//")) {
    return "";
  }
if (raw.startsWith("/")) {
    // Query and hash belong to the target, not to the first route segment.
    const pathOnly = raw.split(/[?#]/, 1)[0];
    return isRouterOwnedPath(pathOnly) ? raw : "";
  }  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    return "";
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    return "";
  }
  // Without a browser origin (tests, SSR) stay conservative and keep the anchor.
  const currentOrigin = typeof window === "undefined" ? "" : String(window.location?.origin || "");
  if (!currentOrigin || parsed.origin !== currentOrigin) {
    return "";
  }
  if (!isRouterOwnedPath(parsed.pathname)) {
    return "";
  }
  return `${parsed.pathname}${parsed.search}${parsed.hash}`;
}
