import { readdirSync, statSync } from "node:fs";
import { basename, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export const DEFAULT_ASSETS_DIR = fileURLToPath(new URL("../dist/assets/", import.meta.url));

export const BUNDLE_BUDGETS = [
  {
    name: "known lazy three graph chunk",
    pattern: /^three\.module-[\w-]+\.js$/,
    maxBytes: 760 * 1024,
  },
  {
    name: "main application entry",
    pattern: /^index-[\w-]+\.js$/,
    maxBytes: 470 * 1024,
  },
  {
    name: "route or feature chunks",
    pattern: /^[\w.-]+-[\w-]+\.js$/,
    maxBytes: 390 * 1024,
  },
  {
    name: "route css chunks",
    pattern: /^[\w.-]+-[\w-]+\.css$/,
    maxBytes: 170 * 1024,
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

export function checkBundleBudget(assetsDir = DEFAULT_ASSETS_DIR) {
  const entries = collectBundleBudgetEntries(assetsDir);
  return {
    entries,
    failures: entries.filter((entry) => !entry.ok),
  };
}

function formatBytes(bytes) {
  return `${(bytes / 1024).toFixed(1)} KiB`;
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  const assetsDir = process.argv[2] || DEFAULT_ASSETS_DIR;
  const result = checkBundleBudget(assetsDir);
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
