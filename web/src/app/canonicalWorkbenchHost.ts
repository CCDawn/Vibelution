const CANONICAL_WORKBENCH_HOSTNAME = "127.0.0.1";
const LEGACY_LOCALHOST = "localhost";
const LAUNCHER_CONTROL_PORT = "8765";
const WORKBENCH_PORT = "8000";
const WORKBENCH_ONLY_PATHS = new Set([
  "/",
  "/chat",
  "/supervised-evolution",
  "/supervised-evolution/runs",
  "/supervised-evolution/library",
  "/supervised-evolution/review",
  "/self-evolution",
  "/teams",
  "/kernel",
  "/memory",
  "/agents",
  "/git",
  "/usage",
  "/logs",
  "/research",
  "/research/flow-canvas",
  "/pet",
  "/reset",
  "/config",
]);

function isWorkbenchOnlyPath(pathname: string): boolean {
  return WORKBENCH_ONLY_PATHS.has(pathname) || pathname.startsWith("/memory/") || pathname.startsWith("/agents/");
}

function suppressNextNavigationReferrer(targetDocument: Document | undefined): void {
  const head = targetDocument?.head;
  if (!head) {
    return;
  }
  const existing = targetDocument.querySelector(
    'meta[name="referrer"][data-vibelution-workbench-redirect="true"]',
  ) as HTMLMetaElement | null;
  const meta = existing ?? targetDocument.createElement("meta");
  meta.setAttribute("name", "referrer");
  meta.setAttribute("content", "no-referrer");
  meta.setAttribute("data-vibelution-workbench-redirect", "true");
  if (!meta.parentElement) {
    head.appendChild(meta);
  }
}

export function canonicalWorkbenchHref(value: string): string {
  try {
    const url = new URL(value);
    if (url.protocol !== "http:") {
      return "";
    }
    if (url.hostname === LEGACY_LOCALHOST && url.port === WORKBENCH_PORT) {
      url.hostname = CANONICAL_WORKBENCH_HOSTNAME;
      return url.toString();
    }
    if (
      (url.hostname === LEGACY_LOCALHOST || url.hostname === CANONICAL_WORKBENCH_HOSTNAME)
      && url.port === LAUNCHER_CONTROL_PORT
      && isWorkbenchOnlyPath(url.pathname)
    ) {
      url.hostname = CANONICAL_WORKBENCH_HOSTNAME;
      url.port = WORKBENCH_PORT;
      return url.toString();
    }
    return "";
  } catch {
    return "";
  }
}

export function redirectToCanonicalWorkbenchHost(
  location: Location = window.location,
  targetDocument: Document | undefined = typeof document === "undefined" ? undefined : document,
): boolean {
  const nextHref = canonicalWorkbenchHref(location.href);
  if (!nextHref || nextHref === location.href) {
    return false;
  }
  suppressNextNavigationReferrer(targetDocument);
  location.replace(nextHref);
  return true;
}
