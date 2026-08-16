import { describe, expect, it } from "vitest";

// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { readdirSync, readFileSync, statSync } from "node:fs";
// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { join } from "node:path";
// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { fileURLToPath } from "node:url";

const sourceRoot = fileURLToPath(new URL("../", import.meta.url));
const queryKeysPath = join(sourceRoot, "api", "queryKeys.ts");
const sourcePattern = /\.(ts|tsx)$/;

function walkSourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      return walkSourceFiles(path);
    }
    if (!sourcePattern.test(entry) || entry.endsWith(".test.ts") || entry.endsWith(".test.tsx")) {
      return [];
    }
    return [path];
  });
}

function listQueryKeyFactories(): string[] {
  const source = readFileSync(queryKeysPath, "utf8");
  return [...source.matchAll(/^\s+(\w+):\s*\(/gm)].map((match) => match[1]);
}

describe("queryKeys registry", () => {
  it("keeps every exported factory referenced outside queryKeys.ts", () => {
    const factories = listQueryKeyFactories();
    const corpus = walkSourceFiles(sourceRoot)
      .filter((path) => !path.endsWith("queryKeys.ts"))
      .map((path) => readFileSync(path, "utf8"))
      .join("\n");

    const unused = factories.filter((name) => !corpus.includes(`queryKeys.${name}(`));
    expect(unused).toEqual([]);
  });
});
