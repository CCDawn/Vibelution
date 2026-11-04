import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("memory route knowledge graph stylesheet coverage", () => {
  it("scans the nested workbench and its responsive and spatial utilities", () => {
    const css = readFileSync(resolve(import.meta.dirname, "memory.tailwind.css"), "utf8");
    for (const source of [
      "../../routes/memory/PlatformKnowledgeGraphWorkbench.tsx",
      "../../routes/memory/PlatformKnowledgeGraphWorkbench.styles.ts",
    ]) {
      expect(css).toContain(`@source "${source}";`);
    }
  });
});
