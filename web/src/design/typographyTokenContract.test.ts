import { readdirSync, readFileSync, statSync } from "node:fs";
import { basename, join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Tailwind maps ambiguous `text-[var(--token)]` to `color`, not `font-size`.
 * Font tokens must use `[font-size:var(--vui-font-*)]` (or `text-[length:...]`).
 */
const FORBIDDEN_FONT_AS_COLOR =
  /(?<!\[font-size:)(?<!\[length:)(?<!font-size:)(?<!length:)!?(?:text-\[var\(--vui-font-(?:xs|sm|md|title|chat)\)\])/g;

/** claim-1ded3aed8d30 owns ConversationView.styles until released. */
const DEFERRED_BASENAMES = new Set<string>([]);

const SRC_ROOT = resolve(import.meta.dirname, "..");

function collectSourceFiles(entry: string, out: string[] = []): string[] {
  const st = statSync(entry);
  if (st.isFile()) {
    if (/\.(ts|tsx|css)$/.test(entry) && !DEFERRED_BASENAMES.has(basename(entry))) {
      out.push(entry);
    }
    return out;
  }
  for (const name of readdirSync(entry)) {
    if (name === "node_modules" || name === "dist") continue;
    collectSourceFiles(join(entry, name), out);
  }
  return out;
}

describe("typography token contract (Path B wave 9 / 9b)", () => {
  it("keeps production sources free of text-[var(--vui-font-*)] color traps (including ConversationView.styles)", () => {
    const files = collectSourceFiles(SRC_ROOT);
    const offenders: string[] = [];

    for (const file of files) {
      if (
        file.endsWith(".test.ts")
        || file.endsWith(".test.tsx")
        || file.endsWith(".layout.test.ts")
      ) {
        continue;
      }
      const source = readFileSync(file, "utf8");
      const matches = source.match(FORBIDDEN_FONT_AS_COLOR);
      if (matches?.length) {
        offenders.push(`${relative(SRC_ROOT, file)} (${matches.length})`);
      }
    }

    expect(offenders).toEqual([]);
  });
});
