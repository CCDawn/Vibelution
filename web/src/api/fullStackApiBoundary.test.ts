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
 * Transitional debt ledger. Counts may only stay equal or decrease.
 * New domain requests belong in web/src/api/<domain>.ts.
 *
 * The 2026-07-26 route-pack extraction redistributed existing calls without
 * increasing the aggregate debt. Keep the exact per-file ledger so future
 * moves remain reviewable, and keep the aggregate ceiling until these hooks
 * migrate to domain API modules.
 */
// Regenerated 2026-08 (R01 Chat workbench extract + current route client imports).
// Counts may only stay equal or decrease from this snapshot without explicit review.
const legacyRouteFetchJsonCallBudgets: Record<string, number> = {
  "routes/AgentsRoute.tsx": 1,
  "routes/EvolutionRoute.tsx": 5,
  "routes/GitRoute.tsx": 8,
  "routes/LogsRoute.tsx": 5,
  "routes/MemoryRoute.tsx": 2,
  "routes/MemoryUserContentPanel.tsx": 6,
  "routes/PetRoute.tsx": 1,
  "routes/RuntimeScenesPane.tsx": 4,
  "routes/SelfEvolutionTrack.tsx": 2,
  "routes/SkillsRoute.tsx": 2,
  "routes/SupervisedReviewRoute.tsx": 7,
  "routes/SupervisedWorkspaceControls.tsx": 1,
  "routes/ToolsRoute.tsx": 9,
  "routes/UsageRoute.tsx": 1,
  "routes/agent-create/AgentCreateWizardDialog.tsx": 1,
  "routes/chat/ChatCodingRouteWorkbench.tsx": 4,
  "routes/chat/CliAgentRunTerminalPanel.tsx": 3,
  "routes/chat/useChatCliAgentTerminal.ts": 1,
  "routes/config/useConfigWorkspaceQueries.ts": 1,
  "routes/evolution/useEvolutionProposalMutations.ts": 5,
  "routes/evolution/useEvolutionRunMutations.ts": 8,
  "routes/memory/useMemoryItemMutations.ts": 6,
  "routes/memory/useMemoryKnowledgeMutations.ts": 8,
  "routes/memory/useMemoryWorkbenchQueries.ts": 18,
  "routes/teams/research-projects/ResearchProjectSwitcher.tsx": 4,
  "routes/teams/useResearchWorkflowResources.ts": 8,
  "routes/teams/useTeamExperimentLoopMutations.ts": 10,
  "routes/teams/useTeamResearchSecondaryQueries.ts": 4,
  "routes/teams/useTeamSourceCollectionMutations.ts": 8,
};
// Task 9: ResearchFlowCanvasRoute.tsx + ResearchRoute.tsx fully removed (redirect-only shells deleted).
const legacyRouteFetchJsonAggregateBudget = 143;

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

  it("keeps legacy route-layer transport debt explicit and non-growing", () => {
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

  it("keeps direct API client imports inside the same legacy ledger", () => {
    expect(currentRouteClientImports()).toEqual(
      Object.keys(legacyRouteFetchJsonCallBudgets).sort(),
    );
  });

  it("keeps route-layer transport debt at or below the pre-extraction aggregate ceiling", () => {
    const aggregateBudget = Object.values(legacyRouteFetchJsonCallBudgets)
      .reduce((total, count) => total + count, 0);
    expect(aggregateBudget).toBeLessThanOrEqual(legacyRouteFetchJsonAggregateBudget);
  });

  it("keeps legacy fetchJson calls visible instead of hiding them behind aliases", () => {
    const offenders = currentRouteClientImports()
      .filter((path) => /\bfetchJson\s+as\s+/.test(readFileSync(join(sourceRoot, path), "utf-8")));
    expect(offenders).toEqual([]);
  });

  it("keeps the debt ledger explicit and reviewable", () => {
    const missing = Object.keys(legacyRouteFetchJsonCallBudgets)
      .filter((path) => !existsSync(join(sourceRoot, path)));
    expect(missing).toEqual([]);
  });
});
