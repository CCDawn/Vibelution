import { describe, expect, it } from "vitest";

// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { readdirSync, readFileSync, statSync } from "node:fs";
// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { extname, join, relative } from "node:path";
// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { fileURLToPath } from "node:url";

const sourceRoot = fileURLToPath(new URL("../../", import.meta.url));
const boundaryTestRelativePath = "components/vui/vuiImportBoundary.test.ts";
const heroUiImportToken = "@heroui/react";
const vuiRendererRelativeRoot = "components/vui/renderers/";
const vuiProductRelativeRoot = "components/vui/product/";
const routeSourceExtensions = new Set([".ts", ".tsx"]);
const routeVisualUtilityPattern =
  /className\s*=\s*(?:["'`][^"'`]*(?:bg-|text-|border-|rounded-|shadow-|px-|py-|gap-|grid|flex)[^"'`]*["'`]|{`[^`]*(?:bg-|text-|border-|rounded-|shadow-|px-|py-|gap-|grid|flex)[^`]*`})/;

function walkFiles(dir: string): string[] {
  const entries = readdirSync(dir);
  return entries.flatMap((entry) => {
    const fullPath = join(dir, entry);
    const stats = statSync(fullPath);
    if (stats.isDirectory()) {
      return walkFiles(fullPath);
    }
    return /\.(ts|tsx|css)$/.test(entry) ? [fullPath] : [];
  });
}

function readText(file: string): string {
  return readFileSync(file, "utf-8");
}

function relativeFromSourceRoot(file: string): string {
  return relative(sourceRoot, file).replace(/\\/g, "/");
}

describe("VUI architecture boundary", () => {
  it("keeps HeroUI imports inside the VUI renderer layer", () => {
    const offenders = walkFiles(sourceRoot)
      .filter((file) => readText(file).includes(heroUiImportToken))
      .map(relativeFromSourceRoot)
      .filter((file) => file !== boundaryTestRelativePath)
      .filter((file) => !file.startsWith("components/vui/"));

    expect(offenders).toEqual([]);
  });

  it("keeps VUI product components from importing HeroUI directly", () => {
    const offenders = walkFiles(join(sourceRoot, "components", "vui", "product"))
      .filter((file) => readText(file).includes(heroUiImportToken))
      .map(relativeFromSourceRoot)
      .filter((file) => !file.startsWith(vuiRendererRelativeRoot))
      .filter((file) => file.startsWith(vuiProductRelativeRoot));

    expect(offenders).toEqual([]);
  });

  it("keeps route files from adding Tailwind visual utility strings", () => {
    const offenders = walkFiles(join(sourceRoot, "routes"))
      .filter((file) => routeSourceExtensions.has(extname(file)))
      .filter((file) => routeVisualUtilityPattern.test(readText(file)))
      .map(relativeFromSourceRoot);

    expect(offenders).toEqual([]);
  });
});
