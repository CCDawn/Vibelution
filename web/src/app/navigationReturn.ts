export type RouteLocationLike = {
  pathname: string;
  search?: string;
  hash?: string;
};

export type ReturnNavigationEntry = {
  path: string;
};

export type ReturnNavigationTarget = {
  path: string;
  source: "explicit" | "stack" | "fallback";
};

const RETURN_STACK_LIMIT = 20;

function normalizePathPart(value: string | undefined): string {
  return String(value || "");
}

export function routeLocationKey(location: RouteLocationLike): string {
  const pathname = normalizePathPart(location.pathname) || "/";
  return `${pathname}${normalizePathPart(location.search)}${normalizePathPart(location.hash)}`;
}

export function safeReturnToPath(value: string | null | undefined): string {
  const normalized = String(value || "").trim();
  if (!normalized || !normalized.startsWith("/") || normalized.startsWith("//")) {
    return "";
  }
  if (/[\u0000-\u001f\\]/.test(normalized)) {
    return "";
  }
  if (/^[a-z][a-z\d+.-]*:/i.test(normalized)) {
    return "";
  }
  try {
    const parsed = new URL(normalized, "http://vibelution.local");
    if (parsed.origin !== "http://vibelution.local") {
      return "";
    }
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return "";
  }
}

export function explicitReturnTarget(location: RouteLocationLike): string {
  const params = new URLSearchParams(normalizePathPart(location.search));
  return safeReturnToPath(params.get("returnTo"));
}

export function isMeaningfulRouteChange(
  previous: RouteLocationLike | null | undefined,
  next: RouteLocationLike | null | undefined,
): boolean {
  if (!previous || !next) {
    return false;
  }
  return routeLocationKey(previous) !== routeLocationKey(next);
}

export function appendReturnNavigationEntry(
  stack: ReturnNavigationEntry[],
  location: RouteLocationLike,
  currentLocation?: RouteLocationLike,
): ReturnNavigationEntry[] {
  const path = safeReturnToPath(routeLocationKey(location));
  if (!path) {
    return stack;
  }
  const currentPath = currentLocation ? routeLocationKey(currentLocation) : "";
  if (path === currentPath) {
    return stack;
  }
  const withoutDuplicateTail = stack.filter((entry, index) => index !== stack.length - 1 || entry.path !== path);
  return [...withoutDuplicateTail, { path }].slice(-RETURN_STACK_LIMIT);
}

export function consumeReturnNavigationTarget(
  stack: ReturnNavigationEntry[],
  targetPath: string,
): ReturnNavigationEntry[] {
  const normalizedTarget = safeReturnToPath(targetPath);
  if (!normalizedTarget) {
    return stack;
  }
  const next = [...stack];
  for (let index = next.length - 1; index >= 0; index -= 1) {
    if (next[index]?.path === normalizedTarget) {
      next.splice(index, 1);
      break;
    }
  }
  return next;
}

export function fallbackReturnRoute(location: RouteLocationLike): string {
  const pathname = normalizePathPart(location.pathname) || "/";
  const search = normalizePathPart(location.search);
  if (pathname === "/chat" && search) {
    const params = new URLSearchParams(search);
    if (params.has("session") || params.has("room")) {
      return "/chat";
    }
  }
  if (pathname === "/agents" && search) {
    return "/agents";
  }
  if (pathname.startsWith("/agents/")) {
    return "/agents";
  }
  if (pathname === "/memory") {
    return "";
  }
  if (pathname.startsWith("/memory/")) {
    return "/memory";
  }
  if (pathname === "/teams" && search) {
    return "/teams";
  }
  if (pathname === "/config" && search) {
    return "/config";
  }
  if (pathname.startsWith("/supervised-evolution/")) {
    return "/supervised-evolution";
  }
  if (pathname === "/research/flow-canvas") {
    return "/teams";
  }
  return "";
}

export function resolveReturnTarget(
  location: RouteLocationLike,
  stack: ReturnNavigationEntry[],
): ReturnNavigationTarget | null {
  const currentPath = routeLocationKey(location);
  const explicit = explicitReturnTarget(location);
  if (explicit && explicit !== currentPath) {
    return { path: explicit, source: "explicit" };
  }
  for (let index = stack.length - 1; index >= 0; index -= 1) {
    const path = safeReturnToPath(stack[index]?.path);
    if (path && path !== currentPath) {
      return { path, source: "stack" };
    }
  }
  const fallback = fallbackReturnRoute(location);
  if (fallback && fallback !== currentPath) {
    return { path: fallback, source: "fallback" };
  }
  return null;
}

export function serializeReturnNavigationStack(stack: ReturnNavigationEntry[]): string {
  return JSON.stringify(
    stack
      .map((entry) => ({ path: safeReturnToPath(entry.path) }))
      .filter((entry) => Boolean(entry.path))
      .slice(-RETURN_STACK_LIMIT),
  );
}

export function parseReturnNavigationStack(value: string | null | undefined): ReturnNavigationEntry[] {
  if (!value) {
    return [];
  }
  try {
    const parsed = JSON.parse(value) as unknown;
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed
      .map((item) => {
        const path = safeReturnToPath(
          typeof item === "string"
            ? item
            : item && typeof item === "object" && "path" in item
              ? String((item as { path?: unknown }).path || "")
              : "",
        );
        return path ? { path } : null;
      })
      .filter((item): item is ReturnNavigationEntry => item !== null)
      .slice(-RETURN_STACK_LIMIT);
  } catch {
    return [];
  }
}
