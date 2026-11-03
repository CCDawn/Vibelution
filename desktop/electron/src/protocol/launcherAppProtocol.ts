import { readFileSync, existsSync, statSync } from "node:fs";
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

// Mirrors core/launcher/frontend_build.py (BUILD_SCHEMA_VERSION,
// _validate_release_assets, _is_complete_release). The shell must apply the
// same completeness contract as the Python publisher: a pointer that names a
// directory with only an index.html is not a verified release.
const FRONTEND_BUILD_SCHEMA_VERSION = 2;
const RELEASE_PROVENANCE_NAME = ".vibelution-build.json";
const INDEX_ASSET_REFERENCE = /(?:src|href)=["']\/assets\/([^"']+)["']/g;

export type LauncherDistSource = "explicit" | "active-release" | "packaged-snapshot" | "legacy-dist";

export type LauncherDistResolution = {
  distRoot: string;
  source: LauncherDistSource;
  /** Active release directory name when `source` is `active-release`. */
  release?: string;
  /** Verified provenance buildKey for `active-release`, or legacy provenance when present. */
  buildKey?: string;
  /** Set when an active pointer existed but did not pass the completeness contract. */
  rejectedActiveRelease?: { release: string; reason: string };
  /** For `legacy-dist`: whether `.vibelution-build.json` with a buildKey exists. */
  legacyProvenance?: "present" | "missing";
  warnings: string[];
};

export type LauncherDistResolutionEvent = {
  kind: "launcher_dist_resolution";
  level: "warning" | "info";
  message: string;
  resolution: LauncherDistResolution;
};

type ReleaseProvenance = { schemaVersion: number; buildKey: string };

function readJsonObject(path: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(readFileSync(path, "utf8")) as unknown;
    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : null;
  } catch {
    return null;
  }
}

function readReleaseProvenance(releaseRoot: string): ReleaseProvenance | null {
  const provenance = readJsonObject(resolve(releaseRoot, RELEASE_PROVENANCE_NAME));
  if (!provenance) {
    return null;
  }
  const schemaVersion = Number(provenance.schemaVersion || 0);
  const buildKey = typeof provenance.buildKey === "string" ? provenance.buildKey.trim() : "";
  return { schemaVersion, buildKey };
}

/**
 * Same completeness contract as frontend_build._is_complete_release: a
 * non-empty index.html whose `/assets/*` references all exist, plus a schema
 * 2 provenance whose buildKey matches the pointer when the pointer names one.
 * Returns the rejection reason, or null when the release is complete.
 */
function releaseRejectionReason(releaseRoot: string, pointerBuildKey: string): string | null {
  const index = resolve(releaseRoot, "index.html");
  let indexContent: string;
  try {
    if (statSync(index).size <= 0) {
      return "empty_index";
    }
    indexContent = readFileSync(index, "utf8");
  } catch {
    return "missing_index";
  }
  for (const match of indexContent.matchAll(INDEX_ASSET_REFERENCE)) {
    if (!existsSync(resolve(releaseRoot, "assets", match[1]))) {
      return `missing_asset:${match[1]}`;
    }
  }
  const provenance = readReleaseProvenance(releaseRoot);
  if (!provenance) {
    return "missing_provenance";
  }
  if (provenance.schemaVersion !== FRONTEND_BUILD_SCHEMA_VERSION) {
    return `provenance_schema:${provenance.schemaVersion}`;
  }
  if (!provenance.buildKey) {
    return "provenance_missing_build_key";
  }
  if (pointerBuildKey && provenance.buildKey !== pointerBuildKey) {
    return "build_key_mismatch";
  }
  return null;
}

type ActiveReleaseOutcome =
  | { kind: "none" }
  | { kind: "rejected"; release: string; reason: string }
  | { kind: "accepted"; distRoot: string; release: string; buildKey: string; warnings: string[] };

function resolveWorkspaceActiveRelease(workspaceRoot: string): ActiveReleaseOutcome {
  const releasesRoot = resolve(workspaceRoot, "web", ".vibelution-builds");
  const active = readJsonObject(resolve(releasesRoot, "active.json"));
  if (!active) {
    // Old workspaces and interrupted builds leave no usable active release.
    return { kind: "none" };
  }
  const release = String(active.release || "").trim();
  if (
    !release.startsWith("release-")
    || basename(release) !== release
    || !resolve(releasesRoot, release).startsWith(`${releasesRoot}${sep}`)
  ) {
    return { kind: "rejected", release, reason: "invalid_pointer_release" };
  }
  const pointerBuildKey = typeof active.buildKey === "string" ? active.buildKey.trim() : "";
  const candidate = resolve(releasesRoot, release);
  const reason = releaseRejectionReason(candidate, pointerBuildKey);
  if (reason) {
    return { kind: "rejected", release, reason };
  }
  const provenance = readReleaseProvenance(candidate);
  const warnings: string[] = [];
  if (!pointerBuildKey) {
    // The Python publisher always writes buildKey; its absence means a
    // hand-edited or pre-v2 pointer. Serve the verified release but say so.
    warnings.push("active release pointer carries no buildKey; verified through provenance only");
  }
  return { kind: "accepted", distRoot: candidate, release, buildKey: provenance?.buildKey ?? "", warnings };
}

let lastReportedResolutionSignature = "";
let lastResolution: LauncherDistResolution | null = null;

function resolutionSignature(resolution: LauncherDistResolution): string {
  return JSON.stringify([
    resolution.source,
    resolution.distRoot,
    resolution.release ?? "",
    resolution.buildKey ?? "",
    resolution.rejectedActiveRelease?.reason ?? "",
    resolution.legacyProvenance ?? "",
    resolution.warnings
  ]);
}

/** The last dist-root resolution outcome; the usage fact behind the served shell. */
export function lastLauncherDistResolution(): LauncherDistResolution | null {
  return lastResolution;
}

export function resetLauncherDistResolutionStateForTests(): void {
  lastReportedResolutionSignature = "";
  lastResolution = null;
}

function defaultLauncherDistEventSink(event: LauncherDistResolutionEvent): void {
  if (event.level === "warning") {
    console.warn(event.message);
  }
}

/**
 * Resolve the launcher dist root with full provenance. Pure except for the
 * filesystem reads; `resolveLauncherDistRoot` layers event reporting on top.
 */
export function resolveLauncherDistResolution(input: {
  resourcesRoot: string;
  workspaceRoot: string;
  packaged: boolean;
  env: NodeJS.ProcessEnv;
}): LauncherDistResolution {
  const explicit = String(input.env.VIBELUTION_LAUNCHER_DIST_ROOT || "").trim();
  if (explicit) {
    return { distRoot: resolve(explicit), source: "explicit", warnings: [] };
  }
  // The packaged launcher window must observe the workspace active release so
  // web changes reach the shell without a full package rebuild; the packaged
  // snapshot stays as the fallback when no workspace release exists.
  const outcome: ActiveReleaseOutcome = input.workspaceRoot
    ? resolveWorkspaceActiveRelease(input.workspaceRoot)
    : { kind: "none" };
  if (outcome.kind === "accepted") {
    return {
      distRoot: outcome.distRoot,
      source: "active-release",
      release: outcome.release,
      buildKey: outcome.buildKey,
      warnings: outcome.warnings
    };
  }
  const warnings: string[] = [];
  const rejected = outcome.kind === "rejected" ? { release: outcome.release, reason: outcome.reason } : undefined;
  if (rejected) {
    warnings.push(
      `active frontend release "${rejected.release}" rejected (${rejected.reason}); serving a fallback shell that may be stale`
    );
  }
  if (input.packaged) {
    return {
      distRoot: resolve(input.resourcesRoot, "web-dist"),
      source: "packaged-snapshot",
      ...(rejected ? { rejectedActiveRelease: rejected } : {}),
      warnings
    };
  }
  // Legacy web/dist is unverified by construction: no pointer, no immutable
  // release directory, and typically no provenance. It stays as the last
  // resort, but never silently: the missing provenance is reported so a
  // stale developer build cannot masquerade as a verified release.
  const legacyRoot = resolve(input.workspaceRoot, "web", "dist");
  const legacy = readReleaseProvenance(legacyRoot);
  const legacyProvenance: "present" | "missing" = legacy?.buildKey ? "present" : "missing";
  if (legacyProvenance === "missing") {
    warnings.push("legacy web/dist served without provenance/buildKey; frontend freshness cannot be verified");
  }
  return {
    distRoot: legacyRoot,
    source: "legacy-dist",
    ...(legacy?.buildKey ? { buildKey: legacy.buildKey } : {}),
    ...(rejected ? { rejectedActiveRelease: rejected } : {}),
    legacyProvenance,
    warnings
  };
}

export function resolveLauncherDistRoot(input: {
  resourcesRoot: string;
  workspaceRoot: string;
  packaged: boolean;
  env: NodeJS.ProcessEnv;
  /** Receives one event per distinct resolution outcome; defaults to console.warn for warnings. */
  onEvent?: (event: LauncherDistResolutionEvent) => void;
}): string {
  const resolution = resolveLauncherDistResolution(input);
  lastResolution = resolution;
  // This runs per protocol request. Report each distinct outcome once, so a
  // fallback is visible in the log without a line per asset fetch.
  const signature = resolutionSignature(resolution);
  if (signature !== lastReportedResolutionSignature) {
    lastReportedResolutionSignature = signature;
    const level: "warning" | "info" = resolution.warnings.length > 0 ? "warning" : "info";
    const message = level === "warning"
      ? `launcher dist resolution (${resolution.source}): ${resolution.warnings.join("; ")}`
      : `launcher dist resolution (${resolution.source}): ${resolution.distRoot}`;
    (input.onEvent ?? defaultLauncherDistEventSink)({ kind: "launcher_dist_resolution", level, message, resolution });
  }
  return resolution.distRoot;
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
