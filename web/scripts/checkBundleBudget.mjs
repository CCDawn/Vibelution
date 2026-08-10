import { readdirSync, statSync } from "node:fs";
import { basename, join } from "node:path";
import { fileURLToPath } from "node:url";

export const DEFAULT_ASSETS_DIR = fileURLToPath(new URL("../dist/assets/", import.meta.url));

// The production ELK worker chunk name is derived from the real Vite build
// output (`elkjs/lib/elk-worker.min.js` -> `elk-worker.min-<hash>.js`).
// It is asserted on the real `dist` (presence + uniqueness + budget), not
// guessed from fixtures.
export const ELK_WORKER_ASSET_PATTERN = /^elk-worker(?:\.min)?-[\w-]+\.js$/;

export const BUNDLE_BUDGETS = [
  {
    name: "known lazy three graph chunk",
    pattern: /^three\.module-[\w-]+\.js$/,
    maxBytes: 760 * 1024,
  },
  {
    // Framework vendors split from the main entry for cache + first-entry size.
    // Matched before generic route chunks so vendor-* is not judged as a route feature.
    name: "known vendor framework chunks",
    pattern: /^vendor-(?:react-dom|react-router|react|query|overlay)-[\w-]+\.js$/,
    maxBytes: 480 * 1024,
  },
  {
    name: "main application entry",
    pattern: /^index-[\w-]+\.js$/,
    maxBytes: 470 * 1024,
  },
  {
    // Shell CSS entry: shared app/components/chat-primary utilities only.
    name: "main application css entry",
    pattern: /^index-[\w-]+\.css$/,
    maxBytes: 360 * 1024,
  },
  {
    // Eager TeamsRoute shell only; SC+shell phase lives in TeamsWorkbenchWithScPhase chunk.
    name: "known Teams route residual",
    pattern: /^TeamsRoute-[\w-]+\.js$/,
    maxBytes: 160 * 1024,
  },
  {
    // The source-collection tail is intentionally isolated from the stage
    // host for an independently cacheable update boundary. Keep the leaf
    // bounded too, so the host budget is not met by merely moving bloat.
    name: "known Teams source collection tail",
    pattern: /^teams-source-collection-tail-[\w-]+\.js$/,
    maxBytes: 120 * 1024,
  },
  {
    // Lazy SC composition + shell phase bag (Mid/Tail + compose + surfaces).
    name: "known Teams SC phase residual",
    pattern: /^TeamsWorkbenchWithScPhase-[\w-]+\.js$/,
    maxBytes: 320 * 1024,
  },
  {
    // ELK layout engine worker asset (elkjs lib/elk-worker.min.js), emitted
    // by Vite as a separate worker chunk. Loaded on demand only when the
    // workflow canvas first runs a layout. Must stay before the generic
    // "route or feature chunks" rule because budget matching is first-match.
    name: "known ELK worker chunk",
    pattern: /^elk-worker(?:\.min)?-[\w-]+\.js$/,
    maxBytes: 1800 * 1024,
  },
  {
    name: "route or feature chunks",
    pattern: /^[\w.-]+-[\w-]+\.js$/,
    maxBytes: 390 * 1024,
  },
  {
    // Lazy route CSS entries (design/route-css/*.tailwind.css).
    name: "lazy route css chunks",
    pattern: /^(?!index-)[\w.-]+-[\w-]+\.css$/,
    maxBytes: 220 * 1024,
  },
];

function budgetForAsset(name) {
  return BUNDLE_BUDGETS.find((budget) => budget.pattern.test(name));
}

export function collectBundleBudgetEntries(assetsDir = DEFAULT_ASSETS_DIR) {
  return readdirSync(assetsDir)
    .map((name) => {
      const path = join(assetsDir, name);
      const stats = statSync(path);
      if (!stats.isFile()) {
        return null;
      }
      if (!name.endsWith(".js") && !name.endsWith(".css")) {
        return null;
      }
      const budget = budgetForAsset(name);
      return {
        name: basename(name),
        bytes: stats.size,
        budgetName: budget?.name ?? "unbudgeted",
        maxBytes: budget?.maxBytes ?? 0,
        ok: Boolean(budget) && stats.size <= budget.maxBytes,
      };
    })
    .filter(Boolean)
    .sort((left, right) => right.bytes - left.bytes);
}

export function checkBundleBudget(assetsDir = DEFAULT_ASSETS_DIR, options = {}) {
  // Production runs expect the ELK worker asset to exist (T1 wired it into
  // the build). A missing or duplicated worker asset is a failure, not a
  // green "no match". Tests can opt out for non-ELK fixture scenarios.
  const expectElkWorker = options.expectElkWorker !== false;
  const entries = collectBundleBudgetEntries(assetsDir);
  const failures = entries.filter((entry) => !entry.ok);

  const workerEntries = entries.filter((entry) => ELK_WORKER_ASSET_PATTERN.test(entry.name));
  if (expectElkWorker) {
    if (workerEntries.length === 0) {
      failures.push({
        name: "<missing> expected ELK worker asset (dist/assets/elk-worker.min-*.js)",
        bytes: 0,
        maxBytes: ELK_WORKER_BUDGET_MAX_BYTES,
        budgetName: "known ELK worker chunk",
        ok: false,
      });
    } else if (workerEntries.length > 1) {
      for (const extra of workerEntries.slice(1)) {
        failures.push({
          name: `${extra.name} (duplicate ELK worker asset)`,
          bytes: extra.bytes,
          maxBytes: ELK_WORKER_BUDGET_MAX_BYTES,
          budgetName: "known ELK worker chunk",
          ok: false,
        });
      }
    }
  }

  return {
    entries,
    failures,
    elkWorker: {
      present: workerEntries.length === 1,
      assets: workerEntries.map((entry) => entry.name),
    },
  };
}

const ELK_WORKER_BUDGET_MAX_BYTES =
  BUNDLE_BUDGETS.find((budget) => budget.name === "known ELK worker chunk")?.maxBytes ?? 0;

function formatBytes(bytes) {
  return `${(bytes / 1024).toFixed(1)} KiB`;
}

if (
  typeof process.argv[1] === "string" &&
  import.meta.url === new URL(`file://${process.argv[1].replace(/\\/g, "/")}`).href
) {
  const expectElkWorker = process.argv.includes("--expect-elk-worker=0") === false;
  const assetsDir =
    process.argv.slice(2).find((arg) => !arg.startsWith("--")) || DEFAULT_ASSETS_DIR;
  const result = checkBundleBudget(assetsDir, { expectElkWorker });
  if (result.failures.length > 0) {
    console.error("Bundle budget exceeded:");
    for (const failure of result.failures) {
      console.error(
        `- ${failure.name}: ${formatBytes(failure.bytes)} > ${formatBytes(failure.maxBytes)} (${failure.budgetName})`,
      );
    }
    process.exitCode = 1;
  } else {
    const largest = result.entries.slice(0, 8).map((entry) => `${entry.name}=${formatBytes(entry.bytes)}`).join(", ");
    console.log(`Bundle budget passed. Largest assets: ${largest}`);
  }
}
