import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Business-domain visual token escalation contract (P0-b baseline ratchet).
 *
 * `components/vui` is covered by its own contracts (vuiTypeScaleContract, ...);
 * this gate covers everything else under `web/src`:
 * - `builtinFontSize`: Tailwind built-in text sizes (`text-sm`, ...) including
 *   inline `fontSize: 13` literals,
 * - `arbitraryTextSize`: literal `text-[13px]` / `text-[0.75rem]` values,
 * - `arbitraryRadius`: literal `rounded-[4px]` / `rounded-t-[0.5rem]` values,
 * - `bareHexColor`: bare hex colors in value positions (`"#0f5ea8"`,
 *   `color: #fff`, gradient stops).
 *
 * Existing debt is recorded in `visualTokenEscalation.baseline.json`; the ratchet
 * only tightens — new violations fail, shrinkage must be acknowledged by
 * regenerating the baseline via `npm run tokens:baseline-update`. Ratchet model
 * borrowed from zai-org/ZCode `scripts/architecture/architecture-check.mjs`
 * (newViolations-only gating, Apache-2.0).
 *
 * Scope: all non-test `.ts`/`.tsx` under `web/src` EXCEPT
 * - `components/vui/` (covered by its own contracts, e.g. vuiTypeScaleContract),
 * - `vendor/` (vendored third-party code),
 * - `design/` preview/lab surfaces (design-lab fixtures, not product UI),
 * - this test file itself (its regex literals must not self-report).
 *
 * File-level opt-out: put `// visual-token-escalation-exempt: <reason>` within the
 * first EXEMPT_MARKER_MAX_LINES lines of a file (xterm terminal palettes, HTML
 * export documents, ...). The exempt file list is itself tracked in the baseline so
 * exemptions cannot be added silently.
 */

const BASELINE_PATH = resolve(import.meta.dirname, "visualTokenEscalation.baseline.json");
const UPDATE_MODE = process.env.VISUAL_TOKEN_ESCALATION_UPDATE === "1";

const CATEGORY_NAMES = [
  "builtinFontSize",
  "arbitraryTextSize",
  "arbitraryRadius",
  "bareHexColor",
] as const;

type VisualTokenCategory = (typeof CATEGORY_NAMES)[number];

interface ViolationHit {
  line: number;
  snippet: string;
}

interface CategoryScan {
  total: number;
  /** src-relative file -> violation count */
  files: Record<string, number>;
  /** src-relative file -> hits (diagnostics only, kept out of the baseline JSON) */
  hits: Record<string, ViolationHit[]>;
}

interface VisualTokenScan {
  scannedFileCount: number;
  exemptFiles: string[];
  categories: Record<VisualTokenCategory, CategoryScan>;
}

/** Ladder escapes: `text-vui-*` is not matched because "vui" is not a size name. */
const BUILTIN_TEXT_SIZE = /\btext-(?:xs|sm|base|lg|xl|2xl|3xl)\b/g;
/** Inline style literals such as `fontSize: 13` or `fontSize: "0.875rem"`. */
const INLINE_FONT_SIZE_LITERAL = /\bfontSize:\s*(?:["'][0-9.]|[0-9])/g;
/** `text-[13px]`, `text-[0.75rem]`, ... */
const ARBITRARY_TEXT_SIZE = /\btext-\[[0-9]+(?:\.[0-9]+)?(?:px|rem)\]/g;
/** `rounded-[4px]`, `rounded-t-[0.5rem]`, ... */
const ARBITRARY_RADIUS = /\brounded(?:-[a-z]+)*-\[[0-9]+(?:\.[0-9]+)?(?:px|rem)\]/g;
/**
 * Bare hex in a value position. `var()` spans are stripped first so token
 * fallbacks (`var(--x, #d92d20)`) stay legal; prose mentions like "blank #f7fafc
 * window" or issue refs like "openai/codex#15633" lack a value-punctuation
 * predecessor and never match.
 */
const BARE_HEX_VALUE = /["':=,(]\s*#[0-9a-fA-F]{3,8}\b/g;
const VAR_SPAN = /var\([^()]*\)/g;

const EXCLUDED_DIRS = new Set(["node_modules", "dist", "vendor", "components/vui"]);
/** Design-lab surfaces: preview workbenches and fixture shots, not product UI. */
const DESIGN_LAB_DIRS = new Set([
  "challenge-cup-single-action-preview",
  "challenge-research-usability",
  "composer-followup-queue-preview-shots",
  "research-process-workspace-preview-shots",
  "team-node-inspector-preview-shots",
  "vui-component-preview",
  "route-css",
]);
const SELF_BASENAMES = new Set(["visualTokenEscalationContract.test.ts"]);
const EXEMPT_MARKER = /^\s*(?:\/\/|\/\*)\s*visual-token-escalation-exempt:/i;
const EXEMPT_MARKER_MAX_LINES = 5;

const SRC_ROOT = resolve(import.meta.dirname, "..");

function toSrcRelative(full: string): string {
  return relative(SRC_ROOT, full).replace(/\\/g, "/");
}

function isExemptFile(source: string): boolean {
  const head = source.split(/\r?\n/, EXEMPT_MARKER_MAX_LINES);
  return head.some((line) => EXEMPT_MARKER.test(line));
}

function collectFiles(dir: string, inDesign: boolean, out: string[]): void {
  for (const entry of readdirSync(dir, { withFileTypes: true }).sort((a, b) =>
    a.name.localeCompare(b.name),
  )) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (EXCLUDED_DIRS.has(toSrcRelative(full))) continue;
      if (inDesign && DESIGN_LAB_DIRS.has(entry.name)) continue;
      collectFiles(full, inDesign || entry.name === "design", out);
      continue;
    }
    if (!/\.(ts|tsx)$/.test(entry.name)) continue;
    if (/\.test\./.test(entry.name)) continue;
    if (inDesign && entry.name.includes("-preview")) continue;
    if (SELF_BASENAMES.has(entry.name)) continue;
    out.push(full);
  }
}

function scanLine(category: VisualTokenCategory, rawLine: string): number {
  if (category === "builtinFontSize") {
    return (
      [...rawLine.matchAll(BUILTIN_TEXT_SIZE)].length
      + [...rawLine.matchAll(INLINE_FONT_SIZE_LITERAL)].length
    );
  }
  if (category === "arbitraryTextSize") {
    return [...rawLine.matchAll(ARBITRARY_TEXT_SIZE)].length;
  }
  if (category === "arbitraryRadius") {
    return [...rawLine.matchAll(ARBITRARY_RADIUS)].length;
  }
  return [...rawLine.replace(VAR_SPAN, "").matchAll(BARE_HEX_VALUE)].length;
}

function scanVisualTokenEscalation(): VisualTokenScan {
  const files: string[] = [];
  collectFiles(SRC_ROOT, false, files);

  const categories = Object.fromEntries(
    CATEGORY_NAMES.map((name) => [
      name,
      { total: 0, files: {} as Record<string, number>, hits: {} as Record<string, ViolationHit[]> },
    ]),
  ) as Record<VisualTokenCategory, CategoryScan>;
  const exemptFiles: string[] = [];

  for (const file of files.sort()) {
    const source = readFileSync(file, "utf8");
    if (isExemptFile(source)) {
      exemptFiles.push(toSrcRelative(file));
      continue;
    }
    source.split(/\r?\n/).forEach((rawLine, index) => {
      for (const category of CATEGORY_NAMES) {
        const count = scanLine(category, rawLine);
        if (count === 0) continue;
        const path = toSrcRelative(file);
        const hits = (categories[category].hits[path] ??= []);
        for (let i = 0; i < count; i += 1) {
          hits.push({ line: index + 1, snippet: rawLine.trim().slice(0, 140) });
        }
        categories[category].total += count;
        categories[category].files[path] = (categories[category].files[path] ?? 0) + count;
      }
    });
  }

  return {
    scannedFileCount: files.length,
    exemptFiles: exemptFiles.sort(),
    categories,
  };
}

interface CategoryBaseline {
  total: number;
  files: Record<string, number>;
}

interface BaselineFile {
  comment: string;
  updatedAt: string;
  scannedFileCount: number;
  exemptFiles: string[];
  categories: Record<VisualTokenCategory, CategoryBaseline>;
}

function sortedRecord(record: Record<string, number>): Record<string, number> {
  return Object.fromEntries(Object.entries(record).sort(([a], [b]) => a.localeCompare(b)));
}

function buildBaseline(): BaselineFile {
  const scan = scanVisualTokenEscalation();
  return {
    comment:
      "Baseline for visualTokenEscalationContract.test.ts. Ratchet: counts may only shrink. Regenerate with: npm run tokens:baseline-update (web/).",
    updatedAt: new Date().toISOString().slice(0, 10),
    scannedFileCount: scan.scannedFileCount,
    exemptFiles: scan.exemptFiles,
    categories: Object.fromEntries(
      CATEGORY_NAMES.map((name) => [
        name,
        { total: scan.categories[name].total, files: sortedRecord(scan.categories[name].files) },
      ]),
    ) as BaselineFile["categories"],
  };
}

describe("visual token escalation contract (business-domain baseline ratchet)", () => {
  it("keeps business-domain token violations at or below the committed baseline", () => {
    const scan = scanVisualTokenEscalation();

    if (UPDATE_MODE) {
      const baseline = buildBaseline();
      writeFileSync(BASELINE_PATH, `${JSON.stringify(baseline, null, 2)}\n`, "utf8");
      const totals = CATEGORY_NAMES.map(
        (name) => `${name}=${baseline.categories[name].total}`,
      ).join(", ");
      console.log(
        `[visual-token-escalation] baseline updated: ${totals}, `
          + `exempt=${baseline.exemptFiles.length}, scanned=${baseline.scannedFileCount} files`,
      );
      return;
    }

    expect(existsSync(BASELINE_PATH)).toBe(true);
    const baseline = JSON.parse(readFileSync(BASELINE_PATH, "utf8")) as BaselineFile;

    const problems: string[] = [];

    const addedExempt = scan.exemptFiles.filter(
      (file) => !baseline.exemptFiles.includes(file),
    );
    const removedExempt = baseline.exemptFiles.filter(
      (file) => !scan.exemptFiles.includes(file),
    );
    if (addedExempt.length > 0 || removedExempt.length > 0) {
      problems.push(
        "visual-token-escalation-exempt file list changed; exemptions are audited baseline state"
          + `${addedExempt.length > 0 ? `, added: ${addedExempt.join(", ")}` : ""}`
          + `${removedExempt.length > 0 ? `, removed: ${removedExempt.join(", ")}` : ""}`
          + ". If the exemption is legitimate, run: npm run tokens:baseline-update",
      );
    }

    for (const name of CATEGORY_NAMES) {
      const current = scan.categories[name];
      const base = baseline.categories[name];
      if (!base) {
        problems.push(`${name}: missing from baseline; run npm run tokens:baseline-update`);
        continue;
      }

      const grownFiles = Object.entries(current.files)
        .filter(([file, count]) => count > (base.files[file] ?? 0))
        .map(([file]) => file);
      if (grownFiles.length > 0) {
        const details = grownFiles
          .map((file) => {
            const hits = current.hits[file]
              ?.map((hit) => `    ${file}:${hit.line}: ${hit.snippet}`)
              .join("\n");
            return `  ${file}: baseline ${base.files[file] ?? 0} -> now ${current.files[file]}\n${hits}`;
          })
          .join("\n");
        problems.push(
          `${name}: NEW business-domain token violations (baseline ${base.total} -> now ${current.total}). `
            + "Use design tokens (text-vui-*, --vui-radius-*, --vui-color-*) instead:\n"
            + details,
        );
        continue;
      }

      if (current.total < base.total) {
        problems.push(
          `${name}: count dropped below baseline (${base.total} -> ${current.total}). `
            + "The ratchet only tightens: run npm run tokens:baseline-update to lock in the improvement.",
        );
      }
    }

    expect(problems).toEqual([]);
  });
});
