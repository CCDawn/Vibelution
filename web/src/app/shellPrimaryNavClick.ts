/** Unmodified left-click should stay inside the SPA; modified clicks keep native tab behavior. */

export function isModifiedPrimaryNavClick(event: {
  metaKey: boolean;
  ctrlKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
  button: number;
}): boolean {
  return event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0;
}

export function resolveUnmodifiedShellNavHref(
  href: string | null | undefined,
  origin: string,
): string | null {
  const raw = String(href || "").trim();
  if (!raw || raw.startsWith("#") || /^javascript:/i.test(raw)) {
    return null;
  }
  try {
    const url = new URL(raw, origin);
    if (url.origin !== new URL(origin).origin) {
      return null;
    }
    const path = `${url.pathname}${url.search}${url.hash}`;
    return path.startsWith("/") ? path : null;
  } catch {
    return null;
  }
}

export function shellNavAnchorFromEventTarget(target: EventTarget | null): HTMLAnchorElement | null {
  if (!(target instanceof Element)) {
    return null;
  }
  const link = target.closest(
    '[data-shell-group="navigation"] a[href], [data-shell-group="mobile-navigation"] a[href]',
  );
  return link instanceof HTMLAnchorElement ? link : null;
}
