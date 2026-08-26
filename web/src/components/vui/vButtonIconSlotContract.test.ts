/**
 * Prevents the ResearchPrimaryActionBar-class layout break:
 * default contentLayout="label" truncates a single label slot; icons must use
 * icon= / trailingIcon= (or contentLayout="plain" / isIconOnly).
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

// This contract is executed both from web/ and by root-cwd selector commands.
// Anchor the scan at the test file instead of the caller's working directory.
const SRC = fileURLToPath(new URL("../..", import.meta.url));

function walkTsx(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) {
      if (name === "node_modules" || name === "dist") continue;
      walkTsx(full, out);
    } else if (name.endsWith(".tsx")) {
      out.push(full);
    }
  }
  return out;
}

/** High-signal anti-pattern: ArrowRight as a VButton child without trailingIcon prop nearby. */
const BAD_TRAILING_ARROW =
  /<VButton\b[\s\S]{0,500}?>[\s\S]{0,200}?<ArrowRight\b[\s\S]{0,80}?\/>[\s\S]{0,40}?<\/VButton>/g;

/**
 * Leading self-closing icon child without icon= / plain / isIconOnly.
 * Intentionally narrow: only flags icons that appear immediately after the open tag.
 */
const LEAD_ICON_NAMES =
  "Eye|Save|Trash2|X|Pencil|RotateCcw|RefreshCw|Plus|Check|Sparkles|Pause|" +
  "CheckCircle2|XCircle|LoaderCircle|Square|Search|Play|Wrench|Settings2|" +
  "ArrowUpRight|ArrowRight|ArrowLeft|Download|Upload|Send|Copy|Bot|Users|" +
  "Database|Undo2|Lock|ZoomIn|ZoomOut|MousePointer2|Layers3|GitBranch|" +
  "FlaskConical|SearchCheck|ShieldCheck|CheckSquare|ScrollText|LibraryBig|" +
  "SquareCheckBig|TriangleAlert|FileText|CopyIcon|ImageIcon|Compass|ExternalLink";

const BAD_LEAD_ICON = new RegExp(
  `<VButton\\b(?![^>]*\\b(?:icon|trailingIcon)\\s*=)(?![^>]*contentLayout\\s*=\\s*[\"']plain[\"'])(?![^>]*\\bisIconOnly\\b)[^>]*>\\s*<(?:${LEAD_ICON_NAMES})\\b`,
  "g",
);

describe("VButton icon slot contract", () => {
  it("does not place ArrowRight as a default-label child (use trailingIcon)", () => {
    const offenders: string[] = [];
    for (const file of walkTsx(SRC)) {
      const text = readFileSync(file, "utf8");
      let match: RegExpExecArray | null;
      const re = new RegExp(BAD_TRAILING_ARROW.source, "g");
      while ((match = re.exec(text))) {
        const block = match[0];
        if (
          block.includes('contentLayout="plain"')
          || block.includes("isIconOnly")
          || block.includes("trailingIcon=")
        ) {
          continue;
        }
        if (/trailingIcon=\{\s*<ArrowRight/.test(block)) {
          continue;
        }
        offenders.push(
          `${file.replace(/\\/g, "/")}:${text.slice(0, match.index).split("\n").length}`,
        );
      }
    }
    expect(offenders, `ArrowRight-as-child VButtons:\n${offenders.join("\n")}`).toEqual([]);
  });

  it("does not place a known lead icon as the first default-label child", () => {
    const offenders: string[] = [];
    for (const file of walkTsx(SRC)) {
      const text = readFileSync(file, "utf8");
      let match: RegExpExecArray | null;
      const re = new RegExp(BAD_LEAD_ICON.source, "g");
      while ((match = re.exec(text))) {
        // Multi-line open tags: if icon= appears later in the match window attrs, the
        // lookahead only sees up to first `>` — use a wider open-tag scan for safety.
        const from = match.index;
        const openEnd = text.indexOf(">", from);
        if (openEnd < 0) continue;
        const openTag = text.slice(from, openEnd + 1);
        if (
          /\bicon\s*=/.test(openTag)
          || /\btrailingIcon\s*=/.test(openTag)
          || /contentLayout\s*=\s*["']plain["']/.test(openTag)
          || /\bisIconOnly\b/.test(openTag)
        ) {
          continue;
        }
        offenders.push(
          `${file.replace(/\\/g, "/")}:${text.slice(0, match.index).split("\n").length}`,
        );
      }
    }
    expect(
      offenders,
      `Lead-icon-as-child VButtons (use icon=):\n${offenders.join("\n")}`,
    ).toEqual([]);
  });
});
