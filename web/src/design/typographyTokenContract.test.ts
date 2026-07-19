import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Tailwind maps ambiguous `text-[var(--token)]` to `color`, not `font-size`.
 * Font tokens must use `[font-size:var(--vui-font-*)]` (or `text-[length:...]`).
 */
const FORBIDDEN_FONT_AS_COLOR = /(?<!\[font-size:)(?<!\[length:)(?<!font-size:)(?<!length:)!?(?:text-\[var\(--vui-font-(?:xs|sm|md|title|chat)\)\])/g;

const WAVE9_ROOTS = [
  resolve(import.meta.dirname, "../app"),
  resolve(import.meta.dirname, "../components/vui/renderers"),
  resolve(import.meta.dirname, "../components/vui/forms"),
  resolve(import.meta.dirname, "../components/vui/layout"),
  resolve(import.meta.dirname, "../components/vui/aesthetic"),
  resolve(import.meta.dirname, "../routes/ChatCodingRoute.styles.ts"),
  resolve(import.meta.dirname, "../routes/DirectSessionIndexItem.styles.ts"),
  resolve(import.meta.dirname, "../routes/ConversationIndexSection.styles.ts"),
  resolve(import.meta.dirname, "../routes/chat"),
] as const;

function collectSourceFiles(entry: string, out: string[] = []): string[] {
  const st = statSync(entry);
  if (st.isFile()) {
    if (/\.(ts|tsx|css)$/.test(entry) && !entry.includes("ConversationView")) {
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

describe("typography token contract (Path B wave 9)", () => {
  it("keeps shell / chat chrome / VUI layout free of text-[var(--vui-font-*)] color traps", () => {
    const files = WAVE9_ROOTS.flatMap((root) => collectSourceFiles(root));
    const srcRoot = resolve(import.meta.dirname, "..");
    const offenders: string[] = [];

    for (const file of files) {
      if (file.endsWith(".test.ts") || file.endsWith(".test.tsx") || file.endsWith(".layout.test.ts")) {
        continue;
      }
      const source = readFileSync(file, "utf8");
      const matches = source.match(FORBIDDEN_FONT_AS_COLOR);
      if (matches?.length) {
        offenders.push(`${relative(srcRoot, file)} (${matches.length})`);
      }
    }

    expect(offenders).toEqual([]);
  });
});
