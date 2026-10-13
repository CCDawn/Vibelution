/**
 * ANSI artifact sanitizer for plain-text narration lanes (progress / thought).
 *
 * Tool output and model prose sometimes carry terminal SGR artifacts. Two
 * shapes leak into the transcript:
 * 1. Full escape sequences (ESC + [1m ... ESC + [0m) — the control byte is
 *    still present;
 * 2. Orphan fragments ([1m, [0m, [?25l, [2K) — an upstream layer ate
 *    the ESC byte and left the bracketed CSI body as literal text.
 *
 * Markdown answer bodies are NOT sanitized here on purpose: a fenced code
 * block about ANSI or array indexing must survive untouched. This helper is
 * only for lanes that render plain text, never for markdown input.
 */

// Full escape sequence: ESC + `[` + parameter/intermediate bytes + a letter final byte.
const ANSI_CSI_WITH_ESC = /\x1b\[[0-9;:?]*[ -/]*[A-Za-z]/g;
// Orphan CSI body after the ESC byte was lost upstream: `[` + params + final
// byte. Requires a digit or `?` right after the bracket so prose like
// `[link]` and footnotes like `[^1]` never match.
const ANSI_CSI_ORPHAN = /\[(?=\d|\?)[0-9;:?]*[ -/]*[A-Za-z]/g;
// Stray C0 control characters other than tab/newline/carriage return.
const C0_CONTROLS = /[\x00-\x08\x0b\x0c\x0e-\x1a\x1c-\x1f\x7f]/g;

export function stripAnsiArtifacts(text: string): string {
  return String(text ?? "")
    .replace(ANSI_CSI_WITH_ESC, "")
    .replace(ANSI_CSI_ORPHAN, "")
    .replace(C0_CONTROLS, "");
}
