const CANONICAL_WORKBENCH_HOSTNAME = "127.0.0.1";
const LEGACY_LOCALHOST = "localhost";

export function canonicalWorkbenchHref(value: string): string {
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" || url.hostname !== LEGACY_LOCALHOST || url.port !== "8000") {
      return "";
    }
    url.hostname = CANONICAL_WORKBENCH_HOSTNAME;
    return url.toString();
  } catch {
    return "";
  }
}

export function redirectToCanonicalWorkbenchHost(location: Location = window.location): boolean {
  const nextHref = canonicalWorkbenchHref(location.href);
  if (!nextHref || nextHref === location.href) {
    return false;
  }
  location.replace(nextHref);
  return true;
}
