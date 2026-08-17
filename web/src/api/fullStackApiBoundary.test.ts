import { describe, expect, it } from "vitest";

// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { join, relative } from "node:path";
// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { fileURLToPath } from "node:url";

const sourceRoot = fileURLToPath(new URL("../", import.meta.url));
const routesRoot = join(sourceRoot, "routes");
const routeSourcePattern = /\.(ts|tsx)$/;
const routeTestPattern = /\.test\.(ts|tsx)$/;

/**
 * Permanent frontend API boundary guard.
 *
 * Route-layer JSON transport migration completed 2026-08; the ledger is empty
 * and the aggregate budget is 0. Any new `fetchJson(` call or `api/client`
 * import under web/src/routes/ fails this test.
 *
 * New JSON endpoints belong in web/src/api/<domain>.ts — see web/src/api/README.md
 * and docs/standards/development-standard.md §24.4.
 */
const legacyRouteFetchJsonCallBudgets: Record<string, number> = {};
const legacyRouteFetchJsonAggregateBudget = 0;

function walkSourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    return statSync(path).isDirectory() ? walkSourceFiles(path) : [path];
  });
}

function relativeFromSourceRoot(path: string): string {
  return relative(sourceRoot, path).replace(/\\/g, "/");
}

function countFetchJsonCalls(source: string): number {
  return source.match(/\bfetchJson\s*(?:<|\()/g)?.length ?? 0;
}

function currentRouteCallCounts(): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const path of walkSourceFiles(routesRoot)) {
    if (!routeSourcePattern.test(path) || routeTestPattern.test(path)) {
      continue;
    }
    const count = countFetchJsonCalls(readFileSync(path, "utf-8"));
    if (count > 0) {
      counts[relativeFromSourceRoot(path)] = count;
    }
  }
  return counts;
}

function currentRouteClientImports(): string[] {
  return walkSourceFiles(routesRoot)
    .filter((path) => routeSourcePattern.test(path) && !routeTestPattern.test(path))
    .filter((path) => /from\s+["'][^"']*api\/client["']/.test(readFileSync(path, "utf-8")))
    .map(relativeFromSourceRoot)
    .sort();
}

describe("full-stack frontend API boundary", () => {
  it("recognizes direct route-layer fetchJson calls without counting imports", () => {
    expect(countFetchJsonCalls('import { fetchJson } from "../api/client";')).toBe(0);
    expect(countFetchJsonCalls('fetchJson<Foo>("/api/foo");\nfetchJson("/api/bar");')).toBe(2);
  });

  it("keeps route-layer fetchJson absent from the recorded budget map", () => {
    const currentCounts = currentRouteCallCounts();
    const paths = new Set([
      ...Object.keys(legacyRouteFetchJsonCallBudgets),
      ...Object.keys(currentCounts),
    ]);
    const drift = [...paths]
      .filter((path) => (currentCounts[path] ?? 0) !== (legacyRouteFetchJsonCallBudgets[path] ?? 0))
      .map((path) => ({
        path,
        current: currentCounts[path] ?? 0,
        budget: legacyRouteFetchJsonCallBudgets[path] ?? 0,
      }));

    expect(drift).toEqual([]);
  });

  it("keeps route files from importing api/client directly", () => {
    expect(currentRouteClientImports()).toEqual(
      Object.keys(legacyRouteFetchJsonCallBudgets).sort(),
    );
  });

  it("keeps the route-layer fetchJson aggregate budget at zero", () => {
    const aggregateBudget = Object.values(legacyRouteFetchJsonCallBudgets)
      .reduce((total, count) => total + count, 0);
    expect(aggregateBudget).toBeLessThanOrEqual(legacyRouteFetchJsonAggregateBudget);
  });

  it("rejects fetchJson import aliases in route files", () => {
    const offenders = currentRouteClientImports()
      .filter((path) => /\bfetchJson\s+as\s+/.test(readFileSync(join(sourceRoot, path), "utf-8")));
    expect(offenders).toEqual([]);
  });

  it("keeps the empty budget map aligned with existing route files", () => {
    const missing = Object.keys(legacyRouteFetchJsonCallBudgets)
      .filter((path) => !existsSync(join(sourceRoot, path)));
    expect(missing).toEqual([]);
  });
});
