import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";

import { describe, expect, it } from "vitest";

const sourceRoot = resolve(import.meta.dirname, "../..");
const legacyCssSuffix = [".legacy", ".css"].join("");

function walkFiles(dir: string): string[] {
  if (!existsSync(dir)) {
    return [];
  }
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      return walkFiles(path);
    }
    return entry.isFile() ? [path] : [];
  });
}

function sourcePath(path: string): string {
  return relative(sourceRoot, path).replaceAll("\\", "/");
}

describe("VUI legacy removal contract", () => {
  it("does not load the route legacy stylesheet in the production entrypoint", () => {
    const mainSource = readFileSync(resolve(sourceRoot, "main.tsx"), "utf8");

    expect(mainSource).not.toContain("vui-route-legacy.css");
    expect(mainSource).not.toContain("vui-route-foundation.css");
    expect(mainSource).not.toContain("vui-legacy-bridge.css");
  });

  it("keeps web/src free of legacy CSS artifacts and test dependencies", () => {
    const files = walkFiles(sourceRoot);
    const legacyFiles = files
      .map(sourcePath)
      .filter((path) => path.endsWith(legacyCssSuffix))
      .sort((left, right) => left.localeCompare(right));
    const pageVuiCssFiles = files
      .map(sourcePath)
      .filter((path) => path.endsWith(".vui.css"))
      .sort((left, right) => left.localeCompare(right));
    const legacyReferences = files
      .filter((path) => /\.(?:ts|tsx|css)$/.test(path))
      .flatMap((path) => {
        const source = readFileSync(path, "utf8");
        return source.includes(legacyCssSuffix) ? [sourcePath(path)] : [];
      })
      .sort((left, right) => left.localeCompare(right));

    expect(legacyFiles).toEqual([]);
    expect(pageVuiCssFiles).toEqual([]);
    expect(legacyReferences).toEqual([]);
  });
});
