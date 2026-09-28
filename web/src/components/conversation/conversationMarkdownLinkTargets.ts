/**
 * Link-target classifier for conversation markdown hrefs (semantics borrowed
 * from zai-org/ZCode markdown link resolution, Apache-2.0): an href plus the
 * caller-provided session workspace root resolves to one of three targets —
 *
 * - `external`       http/https/mailto → stays a browser anchor (the desktop
 *                    shell already diverts these to the system browser).
 * - `workspace-file` a path that looks like a file inside the session
 *                    workspace → resolvable to a normalized absolute path the
 *                    desktop bridge can open / reveal / copy.
 * - `other`          fragments, unknown schemes, non-file relatives, or paths
 *                    that cannot be made absolute (no workspace root) → keep
 *                    the legacy inert-anchor behavior unchanged.
 *
 * Pure and React-free: the renderer decides what each kind can do.
 */

export type ConversationMarkdownLinkTarget =
  | { kind: "external"; url: string }
  | { kind: "workspace-file"; absolutePath: string }
  | { kind: "other"; raw: string };

/** http/https/mailto are the only schemes allowed to leave the app (same rule as the desktop bridge). */
const EXTERNAL_URL_PROTOCOLS = new Set(["http:", "https:", "mailto:"]);

/** Windows drive path (`C:\x`, `C:/x`). Checked BEFORE URL scheme parsing — `C:` otherwise reads as a scheme. */
const WINDOWS_DRIVE_PATH_RE = /^[a-zA-Z]:[\\/]/;
/** Windows UNC path (`\\server\share\...`). */
const WINDOWS_UNC_PATH_RE = /^\\\\[^\\]/;

/**
 * Last segment ends like a file extension with at least one letter
 * (`readme.md`, `run.py`, `archive.tar.gz`). Purely numeric tails (`v1.2`,
 * `8.1`) are version strings, not files, and stay unclassified.
 */
const FILE_EXTENSION_TAIL_RE = /\.([A-Za-z][A-Za-z0-9]{0,11})$/;

export function classifyConversationMarkdownLinkTarget(
  rawHref: string,
  workspaceRoot?: string,
): ConversationMarkdownLinkTarget {
  const href = String(rawHref ?? "").trim();
  if (!href || /[\u0000-\u001f\u007f]/.test(href) || /\s/.test(href)) {
    return { kind: "other", raw: href };
  }

  // Drive/UNC paths must be tested before scheme parsing: WHATWG URL accepts
  // `C:/x` as scheme "c", which would misroute absolute Windows paths.
  if (WINDOWS_DRIVE_PATH_RE.test(href) || WINDOWS_UNC_PATH_RE.test(href)) {
    return { kind: "workspace-file", absolutePath: normalizeMarkdownFilePath(href) };
  }

  const schemeMatch = href.match(/^([A-Za-z][A-Za-z0-9+.-]*):/);
  if (schemeMatch) {
    try {
      if (EXTERNAL_URL_PROTOCOLS.has(new URL(href).protocol)) {
        return { kind: "external", url: href };
      }
    } catch {
      return { kind: "other", raw: href };
    }
    return { kind: "other", raw: href };
  }

  if (href.startsWith("//") || href.startsWith("#")) {
    return { kind: "other", raw: href };
  }
  // Query/hash tails mean a web URL shape, never a workspace file path.
  if (href.includes("?") || href.includes("#")) {
    return { kind: "other", raw: href };
  }

  const workspaceRooted =
    href.startsWith("/") || href.startsWith("./") || href.startsWith("../");
  const fileLike =
    FILE_EXTENSION_TAIL_RE.test(href) && !href.endsWith("/") && !href.endsWith("\\");
  if (!workspaceRooted && !fileLike) {
    return { kind: "other", raw: href };
  }
  const root = (workspaceRoot ?? "").trim();
  if (!root) {
    // Without a workspace root the path cannot be made absolute — keep the
    // legacy anchor behavior instead of guessing a base directory.
    return { kind: "other", raw: href };
  }
  const absolutePath = normalizeMarkdownFilePath(`${root}/${href}`);
  if (!resolvesToNamedPath(absolutePath)) {
    return { kind: "other", raw: href };
  }
  return { kind: "workspace-file", absolutePath };
}

/** Whether the normalized path carries a name segment beyond its bare root prefix (`C:\`, `/`). */
function resolvesToNamedPath(path: string): boolean {
  return path.length > 0 && !/[\\/]$/.test(path) && !/^[a-zA-Z]:$/.test(path);
}

/**
 * Lexically normalize a markdown href path: decode percent escapes, collapse
 * separator runs, resolve `.` / `..` segments, and emit one separator style —
 * backslashes when the path or the workspace root is Windows-style, forward
 * slashes otherwise. No filesystem access; nonexistent paths normalize fine.
 */
export function normalizeMarkdownFilePath(input: string, baseDir?: string): string {
  const decoded = decodeHrefPath(input);
  if (decoded.startsWith("\\\\")) {
    // UNC share: preserve the double-separator prefix, normalize the body.
    return `\\\\${normalizeSegments(decoded.slice(2), "\\")}`;
  }
  const windows =
    /^[a-zA-Z]:/.test(decoded) || decoded.includes("\\") || (baseDir ? isWindowsStyle(baseDir) : false);
  if (/^[a-zA-Z]:/.test(decoded)) {
    const body = normalizeSegments(decoded.slice(2), "\\");
    return `${decoded.slice(0, 2)}\\${body}`;
  }
  const separator = windows ? "\\" : "/";
  const leadingAbsolute = decoded.startsWith("/");
  const body = normalizeSegments(decoded, separator);
  return leadingAbsolute ? `${separator}${body}` : body;
}

function normalizeSegments(path: string, separator: string): string {
  const segments: string[] = [];
  for (const segment of path.split(/[\\/]+/)) {
    if (!segment || segment === ".") {
      continue;
    }
    if (segment === "..") {
      segments.pop();
      continue;
    }
    segments.push(segment);
  }
  return segments.join(separator);
}

function isWindowsStyle(path: string): boolean {
  return /^[a-zA-Z]:/.test(path) || path.includes("\\");
}

function decodeHrefPath(path: string): string {
  if (!path.includes("%")) {
    return path;
  }
  try {
    return decodeURIComponent(path);
  } catch {
    return path;
  }
}
