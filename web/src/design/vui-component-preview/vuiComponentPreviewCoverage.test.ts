import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const previewRoot = dirname(fileURLToPath(import.meta.url));
const vuiRoot = resolve(previewRoot, "../../components/vui");
const indexPath = join(vuiRoot, "designs", "INDEX.md");

function collectPreviewSources(directory: string): string {
  return readdirSync(directory, { withFileTypes: true })
    .flatMap((entry) => {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) {
        return collectPreviewSources(path);
      }
      return entry.name.endsWith(".tsx") ? readFileSync(path, "utf8") : "";
    })
    .join("\n");
}

function implementedDesignComponents(): string[] {
  const currentDesigns = readFileSync(indexPath, "utf8").split("## 拟新增")[0];
  return currentDesigns
    .split(/\r?\n/)
    .filter((line) => line.startsWith("|"))
    .flatMap((line) =>
      Array.from(line.matchAll(/`([A-Z][A-Za-z0-9]+)`/g), (match) => match[1]),
    )
    .filter((name, index, names) => names.indexOf(name) === index);
}

describe("VUI component preview coverage", () => {
  it("renders every implemented component registered in the design index", () => {
    const previewSources = collectPreviewSources(previewRoot);
    const missing = implementedDesignComponents().filter(
      (name) => !previewSources.includes(`<${name}`),
    );

    expect(missing).toEqual([]);
  });
});
