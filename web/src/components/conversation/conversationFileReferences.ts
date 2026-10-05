/**
 * File-reference extractor for settled assistant message text (category model
 * borrowed from zai-org/ZCode `conversation-preview-artifacts.ts`, Apache-2.0,
 * tightened for v1 to the four false-positive-resistant shapes):
 *
 * - fenced code blocks whose every non-empty line is a whitelisted file path
 *   (the "model pasted the deliverable path as a code block" shape);
 * - bare absolute paths in body text (Windows drive / UNC / POSIX root);
 * - double/single-quoted paths (absolute, or relative resolved against the
 *   session workspace root);
 * - markdown link hrefs — resolved only to *suppress* chips: linked workspace
 *   files are already clickable inline, so the chip row must not repeat them.
 *
 * Every extracted path must end in the ZCode preview whitelist (.md/.html/
 * .htm/.docx/.xlsx/.pptx/.pdf, images, audio/video). Relative paths resolve
 * against `workspaceRoot` and drop out when no root is available. Pure and
 * React-free; the chip row decides what each reference can do.
 */

import {
  classifyConversationMarkdownLinkTarget,
  normalizeMarkdownFilePath,
} from "./conversationMarkdownLinkTargets";

export type ConversationFileReference = {
  /** Normalized absolute path (workspaceRoot applied to relative inputs). */
  absolutePath: string;
  /** Raw path text as found in the message, before normalization. */
  raw: string;
  /** Lowercase extension without the dot (`md`, `html`, `png`, …). */
  extension: string;
  /** Media family driving the chip icon. */
  family: "document" | "image" | "audio" | "video";
};

/** Preview whitelist aligned with ZCode conversation preview artifacts. */
const EXTENSION_FAMILIES: Readonly<Record<string, ConversationFileReference["family"]>> = {
  md: "document",
  html: "document",
  htm: "document",
  docx: "document",
  xlsx: "document",
  pptx: "document",
  pdf: "document",
  png: "image",
  jpg: "image",
  jpeg: "image",
  gif: "image",
  webp: "image",
  svg: "image",
  mp3: "audio",
  wav: "audio",
  mp4: "video",
  webm: "video",
};

const WINDOWS_DRIVE_PATH_RE = /^[a-zA-Z]:[\\/]/;
const WINDOWS_UNC_PATH_RE = /^\\\\[^\\]/;
const POSIX_ABSOLUTE_PATH_RE = /^\/[^\s]/;

/**
 * Bare absolute path shapes for the body scan. The drive letter must not be
 * preceded by a word character so URL schemes (`https://…`) never read as
 * `p:/…` drives; UNC runs carry their own double-separator anchor.
 */
const BARE_DRIVE_PATH_RE = /(?<![A-Za-z0-9])[a-zA-Z]:[\\/][^\s"'`<>|*?\u0000-\u001f]+/g;
const BARE_UNC_PATH_RE = /\\\\[^\s"'`<>|*?\u0000-\u001f]+/g;
/** Fenced code block: ``` fence (with optional info string) … closing fence. */
const FENCED_BLOCK_RE = /^[ \t]*(```|~~~)[^\n]*\n([\s\S]*?)\n?[ \t]*\1[ \t]*$/gm;
/** Markdown link: [label](href) — href has no unescaped paren/newline. */
const MARKDOWN_LINK_RE = /\[[^\]\n]*\]\(([^)\n]+)\)/g;
/** Double or single quoted run on one line. */
const QUOTED_RUN_RE = /"([^"\n]+)"|'([^'\n]+)'/g;

/** Trailing sentence punctuation stripped from a bare path match. */
const TRAILING_PUNCTUATION_RE = /[.,;:!?)\]】」』）。，；：！？、]+$/;

function extensionOf(path: string): { extension: string; family: ConversationFileReference["family"] } | null {
  const match = /\.([A-Za-z][A-Za-z0-9]{0,11})$/.exec(path);
  if (!match) {
    return null;
  }
  const extension = match[1].toLowerCase();
  const family = EXTENSION_FAMILIES[extension];
  return family ? { extension, family } : null;
}

function isAbsolutePath(path: string): boolean {
  return (
    WINDOWS_DRIVE_PATH_RE.test(path)
    || WINDOWS_UNC_PATH_RE.test(path)
    || POSIX_ABSOLUTE_PATH_RE.test(path)
  );
}

/** Whether the run can be a whitelisted file path at all (shape + extension). */
function isCandidatePath(run: string): run is string {
  if (!run || /\s/.test(run) || /[\u0000-\u001f\u007f]/.test(run)) {
    return false;
  }
  return extensionOf(run) !== null;
}

/** Resolve raw → absolute; relative inputs need a workspace root. */
function resolveReference(raw: string, workspaceRoot: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed || /\s/.test(trimmed)) {
    return null;
  }
  const normalizedRoot = workspaceRoot.trim();
  if (isAbsolutePath(trimmed)) {
    return normalizeMarkdownFilePath(trimmed);
  }
  if (!normalizedRoot) {
    return null;
  }
  // Relative: only plausible workspace-relative file paths (`a/b.md`,
  // `./a/b.md`, `../a/b.md`) — never scheme-like or rootless slashes.
  if (/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(trimmed) || trimmed.startsWith("//")) {
    return null;
  }
  const resolved = normalizeMarkdownFilePath(`${normalizedRoot}/${trimmed.replace(/^[.][/]/, "")}`);
  return resolved || null;
}

function makeReference(raw: string, absolutePath: string): ConversationFileReference {
  const { extension, family } = extensionOf(absolutePath) ?? { extension: "", family: "document" as const };
  return { absolutePath, raw: raw.trim(), extension, family };
}

/**
 * Extract deduplicated file references from one settled assistant message.
 * Order follows first appearance; duplicates collapse on the normalized
 * absolute path; markdown-linked workspace files are suppressed (already
 * clickable inline).
 */
export function extractConversationFileReferences(
  text: string,
  workspaceRoot?: string,
): ConversationFileReference[] {
  const source = String(text ?? "");
  if (!source.trim()) {
    return [];
  }
  const root = String(workspaceRoot ?? "").trim();
  const suppressed = new Set<string>();
  const produced = new Map<string, ConversationFileReference>();

  // 1) Markdown link hrefs resolve to suppressions, never chips.
  for (const match of source.matchAll(MARKDOWN_LINK_RE)) {
    const target = classifyConversationMarkdownLinkTarget(match[1], root || undefined);
    if (target.kind === "workspace-file") {
      suppressed.add(target.absolutePath);
    }
  }

  const addCandidate = (raw: string) => {
    if (!isCandidatePath(raw)) {
      return;
    }
    const absolutePath = resolveReference(raw, root);
    if (!absolutePath || suppressed.has(absolutePath) || produced.has(absolutePath)) {
      return;
    }
    produced.set(absolutePath, makeReference(raw, absolutePath));
  };

  // 2) Fenced code blocks: emit only when *every* non-empty line is a path
  //    (whole-block path listings); the block content is then blanked so the
  //    body scans below cannot double-extract it.
  const body = source.replace(FENCED_BLOCK_RE, (block, _fence: string, inner: string) => {
    const lines = inner.split("\n").map((line) => line.trim()).filter(Boolean);
    if (lines.length > 0 && lines.every((line) => isCandidatePath(line))) {
      for (const line of lines) {
        addCandidate(line);
      }
      return "";
    }
    return block;
  });

  // 3) Quoted paths (double/single quotes): strong delimiter signal, so
  //    workspace-relative paths are allowed here.
  for (const match of body.matchAll(QUOTED_RUN_RE)) {
    addCandidate(match[1] ?? match[2] ?? "");
  }

  // 4) Bare absolute paths in the remaining text (drive / UNC per the v1
  //    contract); trailing sentence punctuation is not part of the path.
  for (const regex of [BARE_DRIVE_PATH_RE, BARE_UNC_PATH_RE]) {
    for (const match of body.matchAll(regex)) {
      addCandidate(match[0].replace(TRAILING_PUNCTUATION_RE, ""));
    }
  }

  return [...produced.values()];
}

/** Leaf display name of a normalized reference path. */
export function conversationFileReferenceName(absolutePath: string): string {
  const segments = absolutePath.split(/[\\/]/).filter(Boolean);
  return segments[segments.length - 1] || absolutePath;
}
