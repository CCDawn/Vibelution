import { readFileSync, existsSync } from "node:fs";
import { basename, extname, resolve, sep } from "node:path";
import { protocol } from "electron";

export const LAUNCHER_APP_PROTOCOL = "vibelution-launcher";
export const LAUNCHER_APP_HOST = "launcher";
export const LAUNCHER_APP_ORIGIN = `${LAUNCHER_APP_PROTOCOL}://${LAUNCHER_APP_HOST}`;

const MIME_TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".ico": "image/x-icon",
  ".webmanifest": "application/manifest+json; charset=utf-8",
  ".map": "application/json; charset=utf-8",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".txt": "text/plain; charset=utf-8"
};

export function launcherAppOriginFor(rawUrl: string): string {
  const parsed = new URL(rawUrl);
  return `${parsed.protocol}//${parsed.host}`;
}

export function isLauncherAppUrl(rawUrl: string): boolean {
  try {
    const parsed = new URL(rawUrl);
    return parsed.protocol === `${LAUNCHER_APP_PROTOCOL}:` && parsed.host === LAUNCHER_APP_HOST;
  } catch {
    return false;
  }
}

export function resolveLauncherAppUrl(): string {
  return `${LAUNCHER_APP_ORIGIN}/launcher`;
}

export function resolveLauncherDistRoot(input: {
  resourcesRoot: string;
  workspaceRoot: string;
  packaged: boolean;
  env: NodeJS.ProcessEnv;
}): string {
  const explicit = String(input.env.VIBELUTION_LAUNCHER_DIST_ROOT || "").trim();
  if (explicit) {
    return resolve(explicit);
  }
  if (input.packaged) {
    return resolve(input.resourcesRoot, "web-dist");
  }
  const releasesRoot = resolve(input.workspaceRoot, "web", ".vibelution-builds");
  try {
    const active = JSON.parse(readFileSync(resolve(releasesRoot, "active.json"), "utf8")) as { release?: unknown };
    const release = String(active.release || "").trim();
    if (
      release.startsWith("release-")
      && basename(release) === release
      && resolve(releasesRoot, release).startsWith(`${releasesRoot}${sep}`)
    ) {
      const candidate = resolve(releasesRoot, release);
      if (existsSync(resolve(candidate, "index.html"))) {
        return candidate;
      }
    }
  } catch {
    // Old workspaces and interrupted builds retain the web/dist compatibility fallback.
  }
  return resolve(input.workspaceRoot, "web", "dist");
}

function launcherAppProtocolResponse(input: {
  distRoot: string;
  requestUrl: string;
  exists?: (path: string) => boolean;
  readFile?: (path: string) => Buffer;
}): Response {
  const exists = input.exists ?? existsSync;
  const readFile = input.readFile ?? readFileSync;
  let url: URL;
  try {
    url = new URL(input.requestUrl);
  } catch {
    return new Response("blocked request url", { status: 403 });
  }
  if (url.protocol !== `${LAUNCHER_APP_PROTOCOL}:` || url.host !== LAUNCHER_APP_HOST) {
    return new Response("blocked launcher app host", { status: 403 });
  }
  const pathname = decodeURIComponent(url.pathname);
  const normalized = pathname.replace(/^\/+/, "");
  if (normalized.includes("..") || normalized.includes("\\") || normalized.includes("\0")) {
    return new Response("blocked launcher app path", { status: 403 });
  }
  const root = resolve(input.distRoot);
  const requested = resolve(root, normalized || "index.html");
  if (requested !== root && !requested.startsWith(`${root}${sep}`)) {
    return new Response("blocked launcher app path", { status: 403 });
  }
  let target = normalized || "index.html";
  let candidate = resolve(root, target);
  const hasExtension = extname(candidate) !== "";
  if (!exists(candidate)) {
    if (hasExtension) {
      return new Response("launcher app asset not found", { status: 404 });
    }
    target = "index.html";
    candidate = resolve(root, target);
  }
  if (!exists(candidate)) {
    return new Response("launcher app asset not found", { status: 404 });
  }
  const mime = MIME_TYPES[extname(candidate).toLowerCase()] ?? "application/octet-stream";
  const headers: Record<string, string> = { "content-type": mime };
  if (target.endsWith(".html")) {
    // The launcher shell must always observe the current active release; a
    // heuristic renderer cache would pin a stale shell until app restart.
    headers["cache-control"] = "no-store, no-cache, must-revalidate, max-age=0";
    headers["pragma"] = "no-cache";
    headers["expires"] = "0";
  }
  return new Response(new Uint8Array(readFile(candidate)), {
    status: 200,
    headers
  });
}

export function registerLauncherAppProtocolHandle(input: {
  resolveDistRoot: () => string;
  handle?: (scheme: string, handler: (request: Request) => Response | Promise<Response>) => void;
}): void {
  const handle = input.handle ?? ((scheme, handler) => protocol.handle(scheme, handler));
  handle(LAUNCHER_APP_PROTOCOL, (request) =>
    // Resolve per request: the shell stays resident in the tray while
    // frontend rebuilds switch the active release pointer.
    launcherAppProtocolResponse({ distRoot: input.resolveDistRoot(), requestUrl: request.url })
  );
}

export { launcherAppProtocolResponse as handleLauncherAppProtocolRequest };
